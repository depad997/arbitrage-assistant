"""
执行引擎模块 - Phase 2 执行能力核心组件

功能：
- 交易提交与确认
- 失败重试机制
- 交易状态追踪
- 执行结果记录
- 支持两种执行模式：
  - 预置资金模式：使用钱包自有资金
  - 闪电贷模式：Aave V3 / dYdX / Uniswap V3 Flash Loan
"""

import os
import json
import asyncio
import logging
from typing import Dict, List, Optional, Tuple, Any, Callable, Union
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from decimal import Decimal
from collections import deque
import time
import hashlib

import sys
import os as _os
_backend_dir = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from web3 import Web3
from web3.contract import Contract
from web3.types import TxReceipt, BlockData

from config.settings import SUPPORTED_CHAINS, get_chain_config
from services.wallet_manager import WalletManager, SignedTransaction, get_wallet_manager
from services.tx_builder import TransactionParams, TransactionBuilder, FlashLoanTransactionBuilder

logger = logging.getLogger(__name__)


# ============================================
# 枚举和常量
# ============================================

class ExecutionStatus(Enum):
    """执行状态"""
    PENDING = "pending"             # 待提交
    SUBMITTED = "submitted"         # 已提交
    CONFIRMING = "confirming"       # 确认中
    CONFIRMED = "confirmed"         # 已确认
    FAILED = "failed"               # 失败
    REVERTED = "reverted"          # 回滚
    CANCELLED = "cancelled"        # 已取消


class ExecutionMode(Enum):
    """执行模式"""
    NORMAL = "normal"               # 普通模式（预置资金）
    FLASH_LOAN = "flash_loan"       # 闪电贷模式


class TransactionPriority(Enum):
    """交易优先级"""
    LOW = 1
    NORMAL = 2
    HIGH = 3
    URGENT = 4


# ============================================
# 数据类定义
# ============================================

@dataclass
class GasConfig:
    """Gas 配置"""
    max_gas_price_gwei: float = 100.0     # 最大 Gas Price (Gwei)
    max_total_gas_cost_usd: float = 100.0  # 最大 Gas 总成本 (USD)
    priority_fee_boost: float = 1.2       # 优先费用倍数
    gas_price_refresh_seconds: int = 30   # Gas 价格刷新间隔


@dataclass
class RetryConfig:
    """重试配置"""
    max_retries: int = 3                  # 最大重试次数
    retry_delay_seconds: int = 5          # 重试延迟
    exponential_backoff: bool = True      # 指数退避
    max_retry_delay_seconds: int = 60      # 最大重试延迟


@dataclass
class ExecutionResult:
    """执行结果"""
    tx_hash: str                          # 交易哈希
    chain: str                           # 链名称
    status: ExecutionStatus              # 状态
    block_number: Optional[int] = None   # 区块号
    gas_used: Optional[int] = None        # 使用的 Gas
    effective_gas_price: Optional[int] = None  # 实际 Gas 价格
    gas_cost: Optional[float] = None      # Gas 成本 (ETH)
    gas_cost_usd: Optional[float] = None # Gas 成本 (USD)
    
    # 交易详情
    from_address: str = ""
    to_address: str = ""
    value: int = 0                        # 发送金额 (Wei)
    
    # 结果
    success: bool = True
    error_message: Optional[str] = None
    revert_reason: Optional[str] = None
    
    # 时间
    submitted_at: Optional[datetime] = None
    confirmed_at: Optional[datetime] = None
    execution_time_seconds: float = 0.0
    
    # 附加数据
    raw_receipt: Optional[Dict] = None
    
    def to_dict(self) -> Dict:
        return {
            "tx_hash": self.tx_hash,
            "chain": self.chain,
            "status": self.status.value,
            "block_number": self.block_number,
            "gas_used": self.gas_used,
            "effective_gas_price": self.effective_gas_price,
            "gas_cost": self.gas_cost,
            "gas_cost_usd": self.gas_cost_usd,
            "from_address": self.from_address,
            "to_address": self.to_address,
            "value": self.value,
            "success": self.success,
            "error_message": self.error_message,
            "revert_reason": self.revert_reason,
            "submitted_at": self.submitted_at.isoformat() if self.submitted_at else None,
            "confirmed_at": self.confirmed_at.isoformat() if self.confirmed_at else None,
            "execution_time_seconds": self.execution_time_seconds
        }


@dataclass
class ExecutionPlan:
    """执行计划"""
    plan_id: str                         # 计划 ID
    mode: ExecutionMode                  # 执行模式
    steps: List['ExecutionStep'] = field(default_factory=list)  # 执行步骤
    total_cost_estimate: float = 0.0    # 总成本估算
    profit_estimate: float = 0.0        # 预计利润
    created_at: datetime = field(default_factory=datetime.now)
    expires_at: Optional[datetime] = None
    status: ExecutionStatus = ExecutionStatus.PENDING
    
    # 关联的机会
    opportunity_id: Optional[str] = None
    
    def to_dict(self) -> Dict:
        return {
            "plan_id": self.plan_id,
            "mode": self.mode.value,
            "steps": [step.to_dict() for step in self.steps],
            "total_cost_estimate": self.total_cost_estimate,
            "profit_estimate": self.profit_estimate,
            "created_at": self.created_at.isoformat(),
            "status": self.status.value,
            "opportunity_id": self.opportunity_id
        }


@dataclass
class ExecutionStep:
    """执行步骤"""
    step_id: str
    step_type: str                      # "swap", "bridge", "flash_loan", "approve"
    chain: str
    tx_params: Optional[TransactionParams] = None  # 交易参数
    depends_on: Optional[List[str]] = None  # 依赖的前置步骤
    status: ExecutionStatus = ExecutionStatus.PENDING
    result: Optional[ExecutionResult] = None
    gas_limit_override: Optional[int] = None
    
    def to_dict(self) -> Dict:
        return {
            "step_id": self.step_id,
            "step_type": self.step_type,
            "chain": self.chain,
            "status": self.status.value,
            "result": self.result.to_dict() if self.result else None,
            "depends_on": self.depends_on
        }


@dataclass
class ExecutionHistory:
    """执行历史记录"""
    execution_id: str
    plan: ExecutionPlan
    results: List[ExecutionResult]
    started_at: datetime
    completed_at: Optional[datetime] = None
    total_profit: float = 0.0
    total_cost: float = 0.0
    
    def to_dict(self) -> Dict:
        return {
            "execution_id": self.execution_id,
            "plan": self.plan.to_dict(),
            "results": [r.to_dict() for r in self.results],
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "total_profit": self.total_profit,
            "total_cost": self.total_cost
        }


# ============================================
# Gas 价格服务
# ============================================

class GasPriceService:
    """Gas 价格服务"""
    
    def __init__(self, web3: Web3):
        self.web3 = web3
        self._cached_gas_price: Optional[int] = None
        self._cache_time: float = 0
        self._cache_ttl: int = 30  # 秒
    
    async def get_gas_price(self) -> int:
        """获取当前 Gas 价格"""
        current_time = time.time()
        
        if self._cached_gas_price and (current_time - self._cache_time) < self._cache_ttl:
            return self._cached_gas_price
        
        try:
            # 尝试 EIP-1559
            fee_history = await self.web3.eth.fee_history(1, 'latest', [50])
            base_fee = fee_history['baseFeePerGas'][0]
            max_priority_fee = await self.web3.eth.max_priority_fee()
            
            self._cached_gas_price = base_fee + max_priority_fee
        except Exception:
            # 回退到 Legacy
            self._cached_gas_price = await self.web3.eth.gas_price()
        
        self._cache_time = current_time
        return self._cached_gas_price
    
    async def get_eip1559_gas(self) -> Tuple[int, int, int]:
        """
        获取 EIP-1559 Gas 价格
        
        Returns:
            (max_fee, max_priority_fee, base_fee)
        """
        try:
            base_fee = (await self.web3.eth.fee_history(1, 'latest', [50]))['baseFeePerGas'][0]
            max_priority_fee = await self.web3.eth.max_priority_fee()
            max_fee = base_fee * 2 + max_priority_fee
            return max_fee, max_priority_fee, base_fee
        except Exception:
            legacy_price = await self.web3.eth.gas_price()
            return legacy_price, 0, legacy_price
    
    def calculate_gas_cost_wei(self, gas_used: int, gas_price: int) -> int:
        """计算 Gas 成本 (Wei)"""
        return gas_used * gas_price
    
    def calculate_gas_cost_usd(
        self,
        gas_used: int,
        gas_price: int,
        native_price_usd: float,
        decimals: int = 18
    ) -> float:
        """计算 Gas 成本 (USD)"""
        cost_wei = self.calculate_gas_cost_wei(gas_used, gas_price)
        cost_eth = cost_wei / (10 ** decimals)
        return cost_eth * native_price_usd


# ============================================
# 交易追踪器
# ============================================

class TransactionTracker:
    """交易追踪器"""
    
    def __init__(self, web3: Web3, chain: str):
        self.web3 = web3
        self.chain = chain
        self._pending_txs: Dict[str, ExecutionResult] = {}
        self._confirmed_txs: deque = deque(maxlen=1000)  # 保留最近1000笔
    
    def add_pending(self, tx_hash: str, result: ExecutionResult):
        """添加待确认交易"""
        self._pending_txs[tx_hash] = result
    
    async def check_status(self, tx_hash: str) -> Tuple[ExecutionStatus, Optional[TxReceipt]]:
        """
        检查交易状态
        
        Returns:
            (状态, 收据)
        """
        if tx_hash not in self._pending_txs:
            return ExecutionStatus.PENDING, None
        
        try:
            receipt = await self.web3.eth.get_transaction_receipt(tx_hash)
            
            if receipt is None:
                return ExecutionStatus.SUBMITTED, None
            
            if receipt['status'] == 1:
                return ExecutionStatus.CONFIRMED, receipt
            else:
                return ExecutionStatus.REVERTED, receipt
                
        except Exception as e:
            logger.debug(f"Transaction {tx_hash} not found yet: {e}")
            return ExecutionStatus.SUBMITTED, None
    
    def mark_confirmed(self, tx_hash: str, receipt: TxReceipt):
        """标记交易已确认"""
        if tx_hash in self._pending_txs:
            result = self._pending_txs.pop(tx_hash)
            result.status = ExecutionStatus.CONFIRMED if receipt['status'] == 1 else ExecutionStatus.REVERTED
            result.block_number = receipt['blockNumber']
            result.gas_used = receipt['gasUsed']
            result.confirmed_at = datetime.now()
            self._confirmed_txs.append(result)
    
    def get_pending_count(self) -> int:
        """获取待确认交易数量"""
        return len(self._pending_txs)
    
    def get_recent_results(self, limit: int = 10) -> List[ExecutionResult]:
        """获取最近的执行结果"""
        return list(self._confirmed_txs)[-limit:]


# ============================================
# 交易发送器
# ============================================

class TransactionSender:
    """交易发送器"""
    
    def __init__(
        self,
        chain: str,
        wallet_manager: WalletManager,
        gas_config: Optional[GasConfig] = None,
        retry_config: Optional[RetryConfig] = None
    ):
        """
        初始化交易发送器
        
        Args:
            chain: 链名称
            wallet_manager: 钱包管理器
            gas_config: Gas 配置
            retry_config: 重试配置
        """
        self.chain = chain
        self.config = get_chain_config(chain)
        self.web3 = Web3(Web3.HTTPProvider(self.config.rpc_url))
        self.wallet_manager = wallet_manager
        
        self.gas_config = gas_config or GasConfig()
        self.retry_config = retry_config or RetryConfig()
        
        self.gas_service = GasPriceService(self.web3)
        self.tracker = TransactionTracker(self.web3, chain)
        
        # 签名后的交易缓存（用于防止 nonce 冲突）
        self._signed_txs: Dict[str, Any] = {}
    
    def _to_tx_dict(self, tx_params: TransactionParams) -> Dict:
        """将 TransactionParams 转换为 Web3 交易字典"""
        tx_dict = {
            'from': tx_params.from_address,
            'to': tx_params.to_address,
            'value': tx_params.value,
            'data': tx_params.data,
            'nonce': tx_params.nonce,
            'chainId': tx_params.chain_id,
            'type': tx_params.type
        }
        
        if tx_params.type == 2:
            # EIP-1559
            tx_dict['maxFeePerGas'] = tx_params.max_fee_per_gas
            tx_dict['maxPriorityFeePerGas'] = tx_params.max_priority_fee_per_gas
        else:
            tx_dict['gasPrice'] = tx_params.gas_price
        
        # Gas limit
        if tx_params.gas_limit > 0:
            tx_dict['gas'] = tx_params.gas_limit
        
        return tx_dict
    
    async def send_transaction(
        self,
        tx_params: TransactionParams,
        priority: TransactionPriority = TransactionPriority.NORMAL
    ) -> Tuple[bool, str, Optional[str]]:
        """
        发送交易
        
        Args:
            tx_params: 交易参数
            priority: 优先级
            
        Returns:
            (是否成功, tx_hash, error_message)
        """
        retries = 0
        last_error = None
        
        while retries <= self.retry_config.max_retries:
            try:
                # 检查钱包是否解锁
                if not self.wallet_manager.evm_manager:
                    return False, "", "Wallet not unlocked"
                
                # 签名交易
                tx_dict = self._to_tx_dict(tx_params)
                
                # 如果有优先费用加成
                if priority != TransactionPriority.NORMAL and 'maxPriorityFeePerGas' in tx_dict:
                    boost = self.gas_config.priority_fee_boost
                    if priority == TransactionPriority.HIGH:
                        boost = 1.5
                    elif priority == TransactionPriority.URGENT:
                        boost = 2.0
                    
                    base_fee = tx_dict['maxFeePerGas'] - tx_dict['maxPriorityFeePerGas']
                    tx_dict['maxPriorityFeePerGas'] = int(tx_dict['maxPriorityFeePerGas'] * boost)
                    tx_dict['maxFeePerGas'] = base_fee + tx_dict['maxPriorityFeePerGas']
                
                signed_tx = self.wallet_manager.evm_manager.sign_transaction(
                    self.chain,
                    tx_dict
                )
                
                # 发送交易
                raw_hex = signed_tx.raw_hex
                tx_hash = self.web3.eth.send_raw_transaction(raw_hex)
                tx_hash_hex = tx_hash.hex()
                
                logger.info(f"Transaction submitted: {tx_hash_hex}")
                
                # 创建结果对象
                result = ExecutionResult(
                    tx_hash=tx_hash_hex,
                    chain=self.chain,
                    status=ExecutionStatus.SUBMITTED,
                    from_address=tx_params.from_address,
                    to_address=tx_params.to_address,
                    value=tx_params.value,
                    submitted_at=datetime.now()
                )
                
                self.tracker.add_pending(tx_hash_hex, result)
                
                return True, tx_hash_hex, None
                
            except ValueError as e:
                # Nonce 冲突或其他错误
                last_error = str(e)
                
                if "nonce" in last_error.lower() or "already known" in last_error.lower():
                    logger.warning(f"Nonce conflict, retrying with new nonce")
                    tx_params.nonce = None  # 刷新 nonce
                
                retries += 1
                await asyncio.sleep(self.retry_config.retry_delay_seconds)
                
            except Exception as e:
                last_error = str(e)
                logger.error(f"Transaction failed: {e}")
                return False, "", last_error
        
        return False, "", f"Max retries exceeded: {last_error}"
    
    async def wait_for_confirmation(
        self,
        tx_hash: str,
        timeout_seconds: int = 120,
        confirmations: int = 1
    ) -> ExecutionResult:
        """
        等待交易确认
        
        Args:
            tx_hash: 交易哈希
            timeout_seconds: 超时时间
            confirmations: 需要的确认数
            
        Returns:
            ExecutionResult
        """
        start_time = time.time()
        
        while time.time() - start_time < timeout_seconds:
            status, receipt = await self.tracker.check_status(tx_hash)
            
            if status == ExecutionStatus.CONFIRMED:
                result = self.tracker._pending_txs.get(tx_hash)
                if result:
                    # 获取更多信息
                    tx = await self.web3.eth.get_transaction(tx_hash)
                    result.effective_gas_price = receipt['effectiveGasPrice']
                    result.gas_cost = self.web3.from_wei(
                        result.gas_used * result.effective_gas_price,
                        'ether'
                    )
                    result.execution_time_seconds = (datetime.now() - result.submitted_at).total_seconds()
                    self.tracker.mark_confirmed(tx_hash, receipt)
                    return result
                
            elif status == ExecutionStatus.REVERTED:
                result = self.tracker._pending_txs.get(tx_hash)
                if result:
                    # 获取回滚原因
                    result.revert_reason = await self._get_revert_reason(tx_hash)
                    self.tracker.mark_confirmed(tx_hash, receipt)
                    return result
            
            await asyncio.sleep(2)  # 每2秒检查一次
        
        # 超时
        result = self.tracker._pending_txs.get(tx_hash)
        if result:
            result.status = ExecutionStatus.FAILED
            result.error_message = "Confirmation timeout"
            return result
        
        return ExecutionResult(
            tx_hash=tx_hash,
            chain=self.chain,
            status=ExecutionStatus.FAILED,
            error_message="Confirmation timeout"
        )
    
    async def _get_revert_reason(self, tx_hash: str) -> Optional[str]:
        """获取回滚原因"""
        try:
            tx = await self.web3.eth.get_transaction(tx_hash)
            receipt = await self.web3.eth.get_transaction_receipt(tx_hash)
            
            # 尝试从 revert reason 中获取信息
            # 实际项目中可能需要模拟执行来获取完整原因
            return f"Reverted at block {receipt['blockNumber']}"
        except Exception:
            return None
    
    async def cancel_transaction(
        self,
        original_tx_hash: str,
        gas_price_boost: float = 1.1
    ) -> Tuple[bool, str, Optional[str]]:
        """
        取消待处理交易
        
        Args:
            original_tx_hash: 原交易哈希
            gas_price_boost: Gas 价格加成
            
        Returns:
            (是否成功, 新交易哈希, 错误信息)
        """
        try:
            # 获取原始交易
            original_tx = await self.web3.eth.get_transaction(original_tx_hash)
            
            # 构建取消交易 (发送 0 ETH 到自己)
            cancel_tx = {
                'from': original_tx['from'],
                'to': original_tx['from'],
                'value': 0,
                'nonce': original_tx['nonce'],
                'gas': 21000,
                'gasPrice': int(original_tx['gasPrice'] * gas_price_boost),
                'chainId': original_tx['chainId']
            }
            
            # 签名并发送
            signed_tx = self.wallet_manager.evm_manager.sign_transaction(
                self.chain,
                cancel_tx
            )
            
            tx_hash = self.web3.eth.send_raw_transaction(signed_tx.raw_hex)
            
            logger.info(f"Cancel transaction submitted: {tx_hash.hex()}")
            
            return True, tx_hash.hex(), None
            
        except Exception as e:
            logger.error(f"Cancel transaction failed: {e}")
            return False, "", str(e)


# ============================================
# 执行引擎
# ============================================

class ExecutionEngine:
    """
    主执行引擎
    
    负责协调所有交易执行
    """
    
    def __init__(
        self,
        wallet_manager: WalletManager,
        gas_config: Optional[GasConfig] = None,
        retry_config: Optional[RetryConfig] = None
    ):
        """
        初始化执行引擎
        
        Args:
            wallet_manager: 钱包管理器
            gas_config: Gas 配置
            retry_config: 重试配置
        """
        self.wallet_manager = wallet_manager
        self.gas_config = gas_config or GasConfig()
        self.retry_config = retry_config or RetryConfig()
        
        # 各链的交易发送器
        self._senders: Dict[str, TransactionSender] = {}
        
        # 执行历史
        self._execution_history: deque = deque(maxlen=100)
        
        # 统计信息
        self._stats = {
            "total_executions": 0,
            "successful_executions": 0,
            "failed_executions": 0,
            "total_profit": 0.0,
            "total_cost": 0.0
        }
    
    def _get_sender(self, chain: str) -> TransactionSender:
        """获取指定链的交易发送器"""
        if chain not in self._senders:
            self._senders[chain] = TransactionSender(
                chain=chain,
                wallet_manager=self.wallet_manager,
                gas_config=self.gas_config,
                retry_config=self.retry_config
            )
        return self._senders[chain]
    
    async def execute_swap(
        self,
        chain: str,
        tx_params: TransactionParams,
        wait_confirm: bool = True,
        timeout_seconds: int = 120,
        priority: TransactionPriority = TransactionPriority.NORMAL
    ) -> ExecutionResult:
        """
        执行单链 Swap
        
        Args:
            chain: 链名称
            tx_params: 交易参数
            wait_confirm: 是否等待确认
            timeout_seconds: 超时时间
            priority: 优先级
            
        Returns:
            ExecutionResult
        """
        sender = self._get_sender(chain)
        
        # 发送交易
        success, tx_hash, error = await sender.send_transaction(
            tx_params,
            priority=priority
        )
        
        if not success:
            return ExecutionResult(
                tx_hash=tx_hash or "",
                chain=chain,
                status=ExecutionStatus.FAILED,
                success=False,
                error_message=error
            )
        
        # 等待确认
        if wait_confirm:
            return await sender.wait_for_confirmation(
                tx_hash,
                timeout_seconds=timeout_seconds
            )
        
        # 返回待确认状态
        return ExecutionResult(
            tx_hash=tx_hash,
            chain=chain,
            status=ExecutionStatus.SUBMITTED,
            submitted_at=datetime.now()
        )
    
    async def execute_plan(
        self,
        plan: ExecutionPlan,
        stop_on_failure: bool = True,
        parallel_chains: Optional[List[str]] = None
    ) -> Tuple[bool, List[ExecutionResult]]:
        """
        执行完整的执行计划
        
        Args:
            plan: 执行计划
            stop_on_failure: 失败时是否停止
            parallel_chains: 可以并行执行的链列表
            
        Returns:
            (是否全部成功, 结果列表)
        """
        self._stats["total_executions"] += 1
        results: List[ExecutionResult] = []
        
        # 构建依赖图
        completed_steps: Dict[str, bool] = {}
        pending_by_chain: Dict[str, List[ExecutionStep]] = {}
        
        for step in plan.steps:
            if step.chain not in pending_by_chain:
                pending_by_chain[step.chain] = []
            pending_by_chain[step.chain].append(step)
        
        # 按顺序执行（单链顺序，多链可并行）
        try:
            # 收集所有链
            chains = list(pending_by_chain.keys())
            
            for chain in chains:
                sender = self._get_sender(chain)
                
                for step in pending_by_chain[chain]:
                    # 检查依赖
                    if step.depends_on:
                        for dep_id in step.depends_on:
                            if not completed_steps.get(dep_id, False):
                                raise ValueError(f"Dependency {dep_id} not completed")
                    
                    if step.tx_params is None:
                        continue
                    
                    # 执行步骤
                    result = await self.execute_swap(
                        chain=step.chain,
                        tx_params=step.tx_params,
                        wait_confirm=True,
                        priority=TransactionPriority.NORMAL
                    )
                    
                    step.result = result
                    step.status = result.status
                    results.append(result)
                    completed_steps[step.step_id] = result.success
                    
                    # 失败处理
                    if not result.success and stop_on_failure:
                        logger.error(f"Step {step.step_id} failed, stopping execution")
                        return False, results
                    
                    # 短暂延迟避免 nonce 冲突
                    await asyncio.sleep(1)
            
            # 所有步骤完成
            all_success = all(r.success for r in results)
            
            if all_success:
                self._stats["successful_executions"] += 1
            else:
                self._stats["failed_executions"] += 1
            
            return all_success, results
            
        except Exception as e:
            logger.error(f"Execution plan failed: {e}")
            self._stats["failed_executions"] += 1
            return False, results
    
    async def execute_flash_loan_arbitrage(
        self,
        chain: str,
        flash_loan_params: Dict,
        swap_steps: List[TransactionParams],
        profit_address: str
    ) -> Tuple[bool, List[ExecutionResult]]:
        """
        执行闪电贷套利
        
        Args:
            chain: 链名称
            flash_loan_params: 闪电贷参数 (assets, amounts, modes)
            swap_steps: Swap 交易列表
            profit_address: 利润接收地址
            
        Returns:
            (是否成功, 结果列表)
        """
        from services.tx_builder import FlashLoanTransactionBuilder
        
        results: List[ExecutionResult] = []
        
        # 构建闪电贷交易
        flash_builder = FlashLoanTransactionBuilder(chain)
        
        try:
            # 步骤1: Flash Loan
            flash_params = flash_builder.encode_operation_params(
                swap_data=[{
                    "token_in": s.to_address if s.data else "",
                    "token_out": s.data[:42] if s.data else "",  # 简化
                    "amount_in": s.value,
                    "amount_out_min": 0,
                    "data": s.data
                } for s in swap_steps],
                profit_address=profit_address
            )
            
            flash_tx = flash_builder.build_flashloan_transaction(
                assets=flash_loan_params["assets"],
                amounts=flash_loan_params["amounts"],
                modes=[0] * len(flash_loan_params["assets"]),  # 全部归还
                initiator=profit_address,  # 实际应该是合约地址
                params=flash_params
            )
            
            # 执行闪电贷
            flash_result = await self.execute_swap(
                chain=chain,
                tx_params=flash_tx,
                wait_confirm=True
            )
            
            results.append(flash_result)
            
            if not flash_result.success:
                return False, results
            
            return True, results
            
        except Exception as e:
            logger.error(f"Flash loan execution failed: {e}")
            return False, results
    
    def get_stats(self) -> Dict:
        """获取统计信息"""
        return {
            **self._stats,
            "success_rate": (
                self._stats["successful_executions"] / max(1, self._stats["total_executions"])
            ) * 100,
            "avg_profit": (
                self._stats["total_profit"] / max(1, self._stats["successful_executions"])
            )
        }
    
    def get_execution_history(self, limit: int = 10) -> List[ExecutionHistory]:
        """获取执行历史"""
        return list(self._execution_history)[-limit:]
    
    def get_pending_transactions(self, chain: Optional[str] = None) -> List[ExecutionResult]:
        """获取待确认交易"""
        if chain:
            sender = self._senders.get(chain)
            if sender:
                return list(sender.tracker._pending_txs.values())
        else:
            results = []
            for sender in self._senders.values():
                results.extend(sender.tracker._pending_txs.values())
            return results


# ============================================
# 执行计划构建器
# ============================================

class ExecutionPlanBuilder:
    """执行计划构建器"""
    
    def __init__(self):
        self._steps: List[ExecutionStep] = []
        self._mode: ExecutionMode = ExecutionMode.NORMAL
        self._opportunity_id: Optional[str] = None
    
    def add_step(
        self,
        step_type: str,
        chain: str,
        tx_params: TransactionParams,
        depends_on: Optional[List[str]] = None
    ) -> 'ExecutionPlanBuilder':
        """
        添加执行步骤
        
        Args:
            step_type: 步骤类型
            chain: 链
            tx_params: 交易参数
            depends_on: 依赖的步骤 ID
        """
        import uuid
        step_id = str(uuid.uuid4())[:8]
        
        step = ExecutionStep(
            step_id=step_id,
            step_type=step_type,
            chain=chain,
            tx_params=tx_params,
            depends_on=depends_on
        )
        
        self._steps.append(step)
        return self
    
    def set_mode(self, mode: ExecutionMode) -> 'ExecutionPlanBuilder':
        """设置执行模式"""
        self._mode = mode
        return self
    
    def set_opportunity_id(self, opp_id: str) -> 'ExecutionPlanBuilder':
        """设置关联的机会 ID"""
        self._opportunity_id = opp_id
        return self
    
    def build(self) -> ExecutionPlan:
        """构建执行计划"""
        import uuid
        
        return ExecutionPlan(
            plan_id=str(uuid.uuid4())[:16],
            mode=self._mode,
            steps=self._steps,
            opportunity_id=self._opportunity_id
        )
    
    def reset(self) -> 'ExecutionPlanBuilder':
        """重置"""
        self._steps = []
        self._mode = ExecutionMode.NORMAL
        self._opportunity_id = None
        return self


# ============================================
# 单例和工具函数
# ============================================

_execution_engine_instance: Optional[ExecutionEngine] = None


def get_execution_engine() -> ExecutionEngine:
    """获取执行引擎单例"""
    global _execution_engine_instance
    if _execution_engine_instance is None:
        wallet_manager = get_wallet_manager()
        _execution_engine_instance = ExecutionEngine(wallet_manager)
    return _execution_engine_instance


def init_execution_engine(
    wallet_manager: WalletManager,
    gas_config: Optional[GasConfig] = None,
    retry_config: Optional[RetryConfig] = None
) -> ExecutionEngine:
    """初始化执行引擎"""
    global _execution_engine_instance
    _execution_engine_instance = ExecutionEngine(
        wallet_manager,
        gas_config,
        retry_config
    )
    return _execution_engine_instance
