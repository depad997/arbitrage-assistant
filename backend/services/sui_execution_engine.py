"""
Sui 执行引擎模块

功能：
- 交易提交 (Sui RPC)
- 交易确认 (等待 effects)
- 失败重试 (指数退避)
- 状态追踪
- 错误解析

Sui 交易确认特点：
- 确认时间约 1-2 秒
- Gas 费用低
- 使用 Object 模型
- 可查询 Effects
"""

import asyncio
import base64
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Tuple, Any, Callable
import httpx

import sys
import os as _os
_backend_dir = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from config.sui_dex import (
    SuiRPCConfig,
    SuiTxConfig,
    SuiConfig,
)
from services.sui_wallet_manager import SuiWalletManager, SuiRpcClient
from services.sui_tx_builder import SuiTransactionBuilder

logger = logging.getLogger(__name__)


# ============================================
# 枚举和常量
# ============================================

class SuiExecutionStatus(Enum):
    """Sui 执行状态"""
    PENDING = "pending"              # 待提交
    SUBMITTED = "submitted"          # 已提交
    CONFIRMING = "confirming"       # 确认中
    CONFIRMED = "confirmed"         # 已确认
    FINALIZED = "finalized"         # 最终确认
    FAILED = "failed"               # 失败
    TIMEOUT = "timeout"             # 超时
    INVALID = "invalid"             # 无效交易


class ExecutionLevel(Enum):
    """确认级别"""
    PROCESSED = "processed"         # 已处理
    CONFIRMED = "confirmed"         # 已确认
    FINALIZED = "finalized"        # 最终确认


# ============================================
# 数据类定义
# ============================================

@dataclass
class SuiExecutionResult:
    """Sui 执行结果"""
    digest: str                       # 交易摘要 (Digest)
    status: SuiExecutionStatus        # 状态
    block_height: Optional[int] = None  # 区块高度
    epoch: Optional[int] = None       # Epoch
    gas_used: int = 0                 # Gas 使用量
    gas_price: int = 0                # Gas 价格
    total_gas_cost: int = 0           # 总 Gas 成本 (MIST)
    
    # 错误信息
    error_message: Optional[str] = None
    error_code: Optional[int] = None
    
    # 影响
    mutated: List[str] = field(default_factory=list)  # 修改的对象
    created: List[str] = field(default_factory=list)     # 创建的对象
    deleted: List[str] = field(default_factory=list)     # 删除的对象
    
    # 时间
    submitted_at: Optional[datetime] = None
    confirmed_at: Optional[datetime] = None
    finalized_at: Optional[datetime] = None
    execution_time_ms: float = 0.0
    
    # 附加信息
    events: List[Dict] = field(default_factory=list)  # 事件
    balance_changes: List[Dict] = field(default_factory=list)  # 余额变化
    
    def to_dict(self) -> Dict:
        return {
            "digest": self.digest,
            "status": self.status.value,
            "block_height": self.block_height,
            "epoch": self.epoch,
            "gas_used": self.gas_used,
            "gas_price": self.gas_price,
            "total_gas_cost": self.total_gas_cost,
            "error_message": self.error_message,
            "error_code": self.error_code,
            "mutated": self.mutated,
            "created": self.created,
            "deleted": self.deleted,
            "submitted_at": self.submitted_at.isoformat() if self.submitted_at else None,
            "confirmed_at": self.confirmed_at.isoformat() if self.confirmed_at else None,
            "finalized_at": self.finalized_at.isoformat() if self.finalized_at else None,
            "execution_time_ms": self.execution_time_ms,
            "events": self.events,
            "balance_changes": self.balance_changes
        }
    
    @property
    def success(self) -> bool:
        """是否成功"""
        return self.status in (SuiExecutionStatus.CONFIRMED, SuiExecutionStatus.FINALIZED)


@dataclass
class RetryConfig:
    """重试配置"""
    max_retries: int = 3
    base_delay: float = 1.0
    max_delay: float = 30.0
    exponential_base: float = 2.0
    jitter: bool = True


# ============================================
# RPC 客户端 (扩展)
# ============================================

class SuiExecutionRpcClient(SuiRpcClient):
    """用于交易执行的 RPC 客户端"""
    
    def execute_transaction_block(
        self,
        tx_bytes: str,
        signature: str,
        options: Optional[Dict] = None
    ) -> Dict:
        """
        执行交易块
        
        Args:
            tx_bytes: Base64 编码的交易字节
            signature: Base64 编码的签名
            options: 返回选项
        
        Returns:
            执行结果
        """
        default_options = {
            "showInput": True,
            "showEffects": True,
            "showEvents": True,
            "showBalanceChanges": True,
            "showObjectChanges": True,
        }
        options = options or default_options
        
        return self._post("sui_executeTransactionBlock", [
            tx_bytes,
            [signature],
            options.get("requestType", "waitForEffectsCert"),
            options
        ])
    
    def wait_for_transaction(
        self,
        digest: str,
        timeout: int = 60,
        poll_interval: float = 1.0
    ) -> Dict:
        """
        等待交易确认
        
        Args:
            digest: 交易摘要
            timeout: 超时时间 (秒)
            poll_interval: 轮询间隔 (秒)
        
        Returns:
            交易确认结果
        """
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            try:
                result = self.get_transaction(digest)
                
                if result:
                    effects = result.get("effects", {})
                    status = effects.get("status", {})
                    
                    if status.get("status") in ("success", "executed"):
                        return result
                    elif status.get("status") == "failure":
                        return result
                
                time.sleep(poll_interval)
            except Exception as e:
                logger.warning(f"Polling error: {e}")
                time.sleep(poll_interval)
        
        raise TimeoutError(f"Transaction {digest} not confirmed within {timeout}s")
    
    def get_transaction_block(
        self,
        digest: str,
        options: Optional[Dict] = None
    ) -> Optional[Dict]:
        """获取交易块详情"""
        default_options = {
            "showInput": True,
            "showEffects": True,
            "showEvents": True,
            "showBalanceChanges": True,
        }
        return self._post("sui_getTransactionBlock", [
            digest,
            options or default_options
        ])


# ============================================
# Sui 执行引擎
# ============================================

class SuiExecutionEngine:
    """
    Sui 执行引擎
    
    功能：
    - 交易提交和确认
    - 失败重试
    - 状态追踪
    - Gas 优化
    """
    
    def __init__(
        self,
        wallet_manager: SuiWalletManager,
        rpc_url: Optional[str] = None,
        tx_config: Optional[SuiTxConfig] = None,
        retry_config: Optional[RetryConfig] = None
    ):
        self.wallet_manager = wallet_manager
        self.rpc_url = rpc_url or SuiConfig.get_rpc()
        self.tx_config = tx_config or SuiConfig.get_tx_config()
        self.retry_config = retry_config or RetryConfig()
        
        self._client: Optional[SuiExecutionRpcClient] = None
        self._tx_builder: Optional[SuiTransactionBuilder] = None
        
        # 交易追踪
        self._pending_transactions: Dict[str, SuiExecutionResult] = {}
        self._execution_history: List[SuiExecutionResult] = []
        self._max_history = 1000
    
    @property
    def client(self) -> SuiExecutionRpcClient:
        """获取 RPC 客户端"""
        if self._client is None:
            self._client = SuiExecutionRpcClient(self.rpc_url)
        return self._client
    
    @property
    def tx_builder(self) -> SuiTransactionBuilder:
        """获取交易构建器"""
        if self._tx_builder is None:
            self._tx_builder = SuiTransactionBuilder(
                rpc_url=self.rpc_url,
                tx_config=self.tx_config
            )
        return self._tx_builder
    
    def submit_transaction(
        self,
        tx_data: Dict,
        skip_pre_execution: bool = False
    ) -> str:
        """
        提交交易
        
        Args:
            tx_data: 交易数据
            skip_pre_execution: 是否跳过预执行检查
        
        Returns:
            交易摘要 (digest)
        """
        if not self.wallet_manager.is_unlocked:
            raise ValueError("Wallet not unlocked")
        
        sender = self.wallet_manager.current_address
        if not sender:
            raise ValueError("No sender address")
        
        # 序列化交易
        tx_bytes = self.tx_builder.serialize_transaction(tx_data)
        
        # 签名交易
        tx_bytes_raw = base64.b64decode(tx_bytes)
        signature = self.wallet_manager.sign_transaction(tx_bytes_raw)
        
        # 提交交易
        try:
            result = self.client.execute_transaction_block(
                tx_bytes=tx_bytes,
                signature=signature
            )
            
            digest = result.get("digest")
            logger.info(f"Transaction submitted: {digest}")
            
            return digest
        except Exception as e:
            logger.error(f"Transaction submission failed: {e}")
            raise
    
    def execute_and_confirm(
        self,
        tx_data: Dict,
        wait_for: ExecutionLevel = ExecutionLevel.CONFIRMED,
        timeout: Optional[int] = None
    ) -> SuiExecutionResult:
        """
        执行交易并等待确认
        
        Args:
            tx_data: 交易数据
            wait_for: 确认级别
            timeout: 超时时间
        
        Returns:
            SuiExecutionResult
        """
        start_time = time.time()
        
        # 提交交易
        digest = self.submit_transaction(tx_data)
        
        # 创建结果对象
        result = SuiExecutionResult(
            digest=digest,
            status=SuiExecutionStatus.SUBMITTED,
            submitted_at=datetime.now()
        )
        
        self._pending_transactions[digest] = result
        
        # 等待确认
        try:
            confirmed = self._wait_for_confirmation(
                digest=digest,
                wait_for=wait_for,
                timeout=timeout or self.tx_config.confirmation_timeout
            )
            
            result = self._parse_transaction_result(digest, confirmed)
            result.submitted_at = datetime.fromtimestamp(start_time)
            result.confirmed_at = datetime.now()
            result.execution_time_ms = (datetime.now().timestamp() - start_time) * 1000
            
        except TimeoutError as e:
            result.status = SuiExecutionStatus.TIMEOUT
            result.error_message = str(e)
            logger.warning(f"Transaction timeout: {digest}")
        except Exception as e:
            result.status = SuiExecutionStatus.FAILED
            result.error_message = str(e)
            logger.error(f"Transaction failed: {digest}, error: {e}")
        
        # 更新状态
        self._pending_transactions.pop(digest, None)
        self._execution_history.append(result)
        
        # 限制历史记录长度
        if len(self._execution_history) > self._max_history:
            self._execution_history = self._execution_history[-self._max_history:]
        
        return result
    
    def _wait_for_confirmation(
        self,
        digest: str,
        wait_for: ExecutionLevel,
        timeout: int
    ) -> Dict:
        """等待交易确认"""
        start_time = time.time()
        poll_interval = self.tx_config.poll_interval
        
        while time.time() - start_time < timeout:
            try:
                tx_result = self.client.get_transaction_block(digest)
                
                if not tx_result:
                    time.sleep(poll_interval)
                    continue
                
                effects = tx_result.get("effects", {})
                status = effects.get("status", {})
                status_str = status.get("status", "")
                
                if status_str == "success":
                    if wait_for == ExecutionLevel.PROCESSED:
                        return tx_result
                    elif wait_for == ExecutionLevel.CONFIRMED:
                        # 检查是否有 EffectsCert
                        if "effects_cert" in tx_result or "confirmed_tx" in tx_result:
                            return tx_result
                    elif wait_for == ExecutionLevel.FINALIZED:
                        # 检查是否已最终化
                        if tx_result.get("finalized", False):
                            return tx_result
                elif status_str == "failure":
                    return tx_result
                
                time.sleep(poll_interval)
                
            except Exception as e:
                logger.warning(f"Polling error: {e}")
                time.sleep(poll_interval)
        
        raise TimeoutError(f"Transaction {digest} not confirmed within {timeout}s")
    
    def _parse_transaction_result(
        self,
        digest: str,
        tx_result: Dict
    ) -> SuiExecutionResult:
        """解析交易结果"""
        effects = tx_result.get("effects", {})
        status = effects.get("status", {})
        status_str = status.get("status", "unknown")
        
        result = SuiExecutionResult(
            digest=digest,
            status=SuiExecutionStatus.CONFIRMED if status_str == "success" else SuiExecutionStatus.FAILED,
            error_message=status.get("error")
        )
        
        # Gas 信息
        gas_used = effects.get("gasUsed", {})
        result.gas_used = int(gas_used.get("computationCost", 0))
        result.gas_price = int(gas_used.get("storagePrice", 0))
        result.total_gas_cost = (
            int(gas_used.get("computationCost", 0)) +
            int(gas_used.get("storageCost", 0)) +
            int(gas_used.get("storageRebate", 0))
        )
        
        # 对象变化
        obj_changes = effects.get("objectChanges", [])
        for change in obj_changes:
            if change.get("type") == "mutated":
                result.mutated.append(change.get("objectId", ""))
            elif change.get("type") == "created":
                result.created.append(change.get("objectId", ""))
            elif change.get("type") == "deleted":
                result.deleted.append(change.get("objectId", ""))
        
        # 事件
        result.events = tx_result.get("events", [])
        
        # 余额变化
        result.balance_changes = tx_result.get("balanceChanges", [])
        
        # 区块信息
        result.block_height = tx_result.get("checkpoint", None)
        result.epoch = tx_result.get("epoch", None)
        
        return result
    
    def get_execution_status(self, digest: str) -> Optional[SuiExecutionResult]:
        """
        获取执行状态
        
        Args:
            digest: 交易摘要
        
        Returns:
            SuiExecutionResult 或 None
        """
        # 先检查本地缓存
        if digest in self._pending_transactions:
            return self._pending_transactions[digest]
        
        # 从链上查询
        try:
            tx_result = self.client.get_transaction_block(digest)
            if tx_result:
                return self._parse_transaction_result(digest, tx_result)
        except Exception as e:
            logger.error(f"Failed to get transaction status: {e}")
        
        return None
    
    def execute_swap(
        self,
        dex_name: str,
        pool_address: str,
        token_in: str,
        token_out: str,
        amount_in: int,
        slippage_bps: int = 50,
        wait_for: ExecutionLevel = ExecutionLevel.CONFIRMED
    ) -> SuiExecutionResult:
        """
        执行 Swap
        
        Args:
            dex_name: DEX 名称
            pool_address: 池子地址
            token_in: 输入代币类型
            token_out: 输出代币类型
            amount_in: 输入金额
            slippage_bps: 滑点容忍
            wait_for: 确认级别
        
        Returns:
            SuiExecutionResult
        """
        sender = self.wallet_manager.current_address
        if not sender:
            raise ValueError("No sender address")
        
        # 构建交易
        tx_data = build_swap_transaction(
            sender=sender,
            dex_name=dex_name,
            pool_address=pool_address,
            token_in=token_in,
            token_out=token_out,
            amount_in=amount_in,
            slippage_bps=slippage_bps,
            rpc_url=self.rpc_url
        )
        
        # 执行交易
        return self.execute_and_confirm(tx_data, wait_for=wait_for)
    
    def retry_failed_transaction(
        self,
        original_digest: str,
        new_gas_budget: Optional[int] = None
    ) -> SuiExecutionResult:
        """
        重试失败的交易
        
        Args:
            original_digest: 原始交易摘要
            new_gas_budget: 新的 Gas 预算
        
        Returns:
            SuiExecutionResult
        """
        # 获取原始交易
        original_tx = self.client.get_transaction_block(original_digest)
        if not original_tx:
            raise ValueError(f"Original transaction not found: {original_digest}")
        
        # 获取交易输入
        tx_input = original_tx.get("transaction", {})
        tx_data = tx_input.get("data", {}).get("transaction", {})
        
        # 如果提供了新的 Gas 预算，更新它
        if new_gas_budget:
            if "gas_config" in tx_data:
                tx_data["gas_config"]["budget"] = str(new_gas_budget)
        
        # 执行新交易
        return self.execute_and_confirm(tx_data)
    
    def get_execution_history(
        self,
        limit: int = 100,
        status_filter: Optional[SuiExecutionStatus] = None
    ) -> List[SuiExecutionResult]:
        """
        获取执行历史
        
        Args:
            limit: 返回数量
            status_filter: 状态过滤
        
        Returns:
            执行结果列表
        """
        history = self._execution_history
        
        if status_filter:
            history = [r for r in history if r.status == status_filter]
        
        return history[-limit:]
    
    def get_pending_transactions(self) -> Dict[str, SuiExecutionResult]:
        """获取待处理交易"""
        return self._pending_transactions.copy()
    
    def close(self):
        """关闭资源"""
        if self._client:
            self._client.close()
        if self._tx_builder:
            self._tx_builder.close()


# ============================================
# 便捷函数
# ============================================

def build_swap_transaction(
    sender: str,
    dex_name: str,
    pool_address: str,
    token_in: str,
    token_out: str,
    amount_in: int,
    slippage_bps: int = 50,
    rpc_url: Optional[str] = None
) -> Dict:
    """便捷函数: 构建 Swap 交易"""
    from services.sui_tx_builder import build_swap_transaction as _build_swap
    return _build_swap(
        sender=sender,
        dex_name=dex_name,
        pool_address=pool_address,
        token_in=token_in,
        token_out=token_out,
        amount_in=amount_in,
        slippage_bps=slippage_bps,
        rpc_url=rpc_url
    )


# ============================================
# 全局单例
# ============================================

_sui_execution_engine: Optional[SuiExecutionEngine] = None


def get_sui_execution_engine() -> Optional[SuiExecutionEngine]:
    """获取 Sui 执行引擎单例"""
    return _sui_execution_engine


def init_sui_execution_engine(
    wallet_manager: SuiWalletManager,
    rpc_url: Optional[str] = None,
    tx_config: Optional[SuiTxConfig] = None
) -> SuiExecutionEngine:
    """初始化 Sui 执行引擎"""
    global _sui_execution_engine
    _sui_execution_engine = SuiExecutionEngine(
        wallet_manager=wallet_manager,
        rpc_url=rpc_url,
        tx_config=tx_config
    )
    return _sui_execution_engine
