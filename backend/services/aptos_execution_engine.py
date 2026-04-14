"""
Aptos 执行引擎模块

功能：
- 交易提交 (Aptos REST API)
- 交易确认 (等待 execution)
- 失败重试 (指数退避)
- 状态追踪
- 错误解析

Aptos 交易确认特点：
- 确认时间约 1-2 秒
- Gas 费用极低
- 使用 Account Model
- 可查询 Transaction 状态
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

from config.aptos_dex import (
    AptosAPIConfig,
    AptosTxConfig,
)
from services.aptos_wallet_manager import (
    AptosWalletManager,
    AptosRpcClient,
    AptosWalletError,
)
from services.aptos_tx_builder import AptosTransactionBuilder

logger = logging.getLogger(__name__)


# ============================================
# 枚举和常量
# ============================================

class AptosExecutionStatus(Enum):
    """Aptos 执行状态"""
    PENDING = "pending"                  # 待提交
    SUBMITTED = "submitted"              # 已提交
    CONFIRMING = "confirming"           # 确认中
    CONFIRMED = "confirmed"             # 已确认
    FINALIZED = "finalized"             # 最终确认
    FAILED = "failed"                   # 失败
    TIMEOUT = "timeout"                 # 超时
    REJECTED = "rejected"                # 被拒绝
    ABORTED = "aborted"                  # 中止


class ExecutionLevel(Enum):
    """确认级别"""
    PENDING = "pending"                 # 待处理
    PROCESSED = "processed"             # 已处理
    CONFIRMED = "confirmed"             # 已确认
    FINALIZED = "finalized"            # 最终确认


class TransactionStatus(Enum):
    """Aptos 交易状态 (来自 API)"""
    PENDING = "pending"
    PROCESSED = "processed"
    EXECUTED = "executed"
    FAILED = "failed"
    ABORTED = "aborted"


# ============================================
# 数据类定义
# ============================================

@dataclass
class AptosExecutionResult:
    """Aptos 执行结果"""
    hash: str                            # 交易哈希
    status: AptosExecutionStatus        # 状态
    success: bool = False               # 是否成功
    version: Optional[int] = None       # 版本号
    
    # Gas 信息
    gas_used: int = 0                   # Gas 使用量
    gas_unit_price: int = 0             # Gas 单价 (Octas)
    total_gas_cost: int = 0             # 总 Gas 成本 (Octas)
    
    # 错误信息
    error_message: Optional[str] = None
    error_code: Optional[str] = None
    vm_status: Optional[str] = None
    
    # 事件
    events: List[Dict] = field(default_factory=list)
    
    # 时间
    submitted_at: Optional[datetime] = None
    processed_at: Optional[datetime] = None
    confirmed_at: Optional[datetime] = None
    execution_time_ms: float = 0.0
    
    # 附加信息
    sender: Optional[str] = None
    sequence_number: Optional[int] = None
    payload_type: Optional[str] = None
    
    def to_dict(self) -> Dict:
        return {
            "hash": self.hash,
            "version": self.version,
            "status": self.status.value,
            "success": self.success,
            "gas_used": self.gas_used,
            "gas_unit_price": self.gas_unit_price,
            "total_gas_cost": self.total_gas_cost,
            "gas_cost_apt": self.total_gas_cost / 1e8,  # Octas to APT
            "error_message": self.error_message,
            "error_code": self.error_code,
            "vm_status": self.vm_status,
            "events": self.events,
            "submitted_at": self.submitted_at.isoformat() if self.submitted_at else None,
            "processed_at": self.processed_at.isoformat() if self.processed_at else None,
            "confirmed_at": self.confirmed_at.isoformat() if self.confirmed_at else None,
            "execution_time_ms": self.execution_time_ms,
            "sender": self.sender,
            "sequence_number": self.sequence_number,
            "payload_type": self.payload_type
        }
    
    @property
    def is_confirmed(self) -> bool:
        """是否已确认"""
        return self.status in (AptosExecutionStatus.CONFIRMED, AptosExecutionStatus.FINALIZED)
    
    @property
    def explorer_url(self) -> str:
        """返回浏览器链接"""
        return f"https://explorer.aptoslabs.com/txn/{self.hash}"


@dataclass
class RetryConfig:
    """重试配置"""
    max_retries: int = 3
    base_delay: float = 1.0
    max_delay: float = 30.0
    exponential_base: float = 2.0
    jitter: bool = True
    
    def get_delay(self, attempt: int) -> float:
        """计算延迟时间"""
        delay = self.base_delay * (self.exponential_base ** attempt)
        delay = min(delay, self.max_delay)
        
        if self.jitter:
            import random
            delay *= (0.5 + random.random())
        
        return delay


@dataclass
class ExecutionOptions:
    """执行选项"""
    wait_for_confirmation: bool = True
    confirmation_timeout: int = 60
    poll_interval: float = 1.0
    retry_config: RetryConfig = field(default_factory=RetryConfig)
    
    # Gas 配置
    gas_unit_price: Optional[int] = None
    max_gas_amount: Optional[int] = None
    
    # 优先级
    priority_level: str = "normal"


# ============================================
# RPC 客户端 (扩展)
# ============================================

class AptosExecutionRpcClient(AptosRpcClient):
    """用于交易执行的 RPC 客户端"""
    
    def submit_transaction(self, txn: Dict) -> Dict:
        """
        提交交易
        
        Returns:
            {
                "type": "user_transaction",
                "hash": "0x...",
                "version": "12345",
                ...
            }
        """
        return self._post("/transactions", txn)
    
    def getTransaction(self, tx_hash: str) -> Dict:
        """获取交易信息"""
        return self._get(f"/transactions/{tx_hash}")
    
    def getTransactionByVersion(self, version: int) -> Dict:
        """通过版本号获取交易"""
        return self._get(f"/transactions/{version}")
    
    def wait_for_transaction(
        self,
        tx_hash: str,
        timeout: int = 60,
        poll_interval: float = 1.0
    ) -> Tuple[bool, Optional[Dict]]:
        """
        等待交易确认
        
        Args:
            tx_hash: 交易哈希
            timeout: 超时时间 (秒)
            poll_interval: 轮询间隔 (秒)
        
        Returns:
            (是否成功, 交易结果)
        """
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            try:
                txn = self.getTransaction(tx_hash)
                
                if txn:
                    # 检查状态
                    success = txn.get("success", False)
                    return success, txn
                
                # 交易还在处理中
                time.sleep(poll_interval)
            
            except Exception as e:
                logger.debug(f"Polling transaction {tx_hash}: {e}")
                time.sleep(poll_interval)
        
        # 超时
        return False, None
    
    def getAccountTransactionCount(self, address: str) -> int:
        """获取账户交易数量"""
        try:
            account = self._get(f"/accounts/{address}")
            return int(account.get("sequence_number", "0"))
        except Exception:
            return 0


# ============================================
# 错误解析
# ============================================

class AptosErrorParser:
    """Aptos 错误解析器"""
    
    ERROR_MESSAGES = {
        "INSUFFICIENT_BALANCE": "余额不足",
        "GAS_UNIT_PRICE_TOO_LOW": "Gas 单价太低",
        "MAX_GAS_UNITS_EXCEED_LIMIT": "Gas 超出限制",
        "TRANSACTION_EXPIRED": "交易已过期",
        "SEQUENCE_NUMBER_TOO_OLD": "序列号过期",
        "SEQUENCE_NUMBER_TOO_NEW": "序列号冲突",
        "INVALID_SIGNATURE": "签名无效",
        "INSUFFICIENT_GAS": "Gas 不足",
        "ACCOUNT_NOT_FOUND": "账户不存在",
        "MODULE_NOT_FOUND": "模块不存在",
        "FUNCTION_NOT_FOUND": "函数不存在",
        "TYPE_ERROR": "类型错误",
        "ABORT": "执行中止",
        "OUT_OF_GAS": "Gas 用尽",
        "ARITY_MISMATCH": "参数数量不匹配",
    }
    
    @classmethod
    def parse_error(cls, error: Dict) -> Tuple[str, str]:
        """
        解析错误
        
        Args:
            error: 错误信息
        
        Returns:
            (错误代码, 错误消息)
        """
        # 尝试从 vm_status 获取
        vm_status = error.get("vm_status", "")
        
        # 提取错误代码
        error_code = error.get("error_code", "UNKNOWN")
        
        # 查找中文解释
        message = cls.ERROR_MESSAGES.get(error_code, vm_status)
        
        return error_code, message
    
    @classmethod
    def format_error(cls, result: Dict) -> str:
        """格式化错误信息"""
        error_code, message = cls.parse_error(result)
        
        details = result.get("vm_status_code", "")
        if details:
            return f"{message} ({error_code}: {details})"
        
        return f"{message} ({error_code})"


# ============================================
# Aptos 执行引擎
# ============================================

class AptosExecutionEngine:
    """
    Aptos 执行引擎
    
    功能：
    - 交易提交
    - 交易确认
    - 失败重试
    - 状态追踪
    """
    
    def __init__(
        self,
        rpc_url: Optional[str] = None,
        tx_config: Optional[AptosTxConfig] = None
    ):
        self.rpc_url = rpc_url or AptosAPIConfig.MAINNET
        self.tx_config = tx_config or AptosTxConfig()
        self.rpc_client = AptosExecutionRpcClient(self.rpc_url)
        
        # 钱包管理器
        self._wallet_manager: Optional[AptosWalletManager] = None
        
        # 交易构建器
        self._tx_builder: Optional[AptosTransactionBuilder] = None
        
        # 执行历史
        self._execution_history: Dict[str, AptosExecutionResult] = {}
    
    def close(self):
        """关闭资源"""
        self.rpc_client.close()
        if self._wallet_manager:
            self._wallet_manager.close()
        if self._tx_builder:
            self._tx_builder.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
    
    @property
    def wallet_manager(self) -> AptosWalletManager:
        """获取钱包管理器"""
        if self._wallet_manager is None:
            self._wallet_manager = AptosWalletManager(self.rpc_url, self.tx_config)
        return self._wallet_manager
    
    @property
    def tx_builder(self) -> AptosTransactionBuilder:
        """获取交易构建器"""
        if self._tx_builder is None:
            self._tx_builder = AptosTransactionBuilder(self.rpc_url, self.tx_config)
        return self._tx_builder
    
    def _exponential_backoff(
        self,
        attempt: int,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
        jitter: bool = True
    ) -> float:
        """指数退避"""
        delay = base_delay * (2 ** attempt)
        delay = min(delay, max_delay)
        
        if jitter:
            import random
            delay *= (0.5 + random.random())
        
        return delay
    
    async def submit_transaction(
        self,
        signed_txn: Dict,
        options: Optional[ExecutionOptions] = None
    ) -> AptosExecutionResult:
        """
        提交交易
        
        Args:
            signed_txn: 已签名交易
            options: 执行选项
        
        Returns:
            AptosExecutionResult
        """
        options = options or ExecutionOptions()
        
        result = AptosExecutionResult(
            hash="",
            status=AptosExecutionStatus.PENDING,
            submitted_at=datetime.now()
        )
        
        # 获取 sender
        result.sender = signed_txn.get("transaction", {}).get("sender")
        result.sequence_number = signed_txn.get("transaction", {}).get("sequence_number")
        
        retry_config = options.retry_config
        
        for attempt in range(retry_config.max_retries + 1):
            try:
                # 提交交易
                response = self.rpc_client.submit_transaction(signed_txn)
                
                # 获取交易哈希
                result.hash = response.get("hash", "")
                result.status = AptosExecutionStatus.SUBMITTED
                
                logger.info(f"Transaction submitted: {result.hash}")
                
                # 如果不需要等待确认，直接返回
                if not options.wait_for_confirmation:
                    return result
                
                # 等待确认
                confirmed_result = await self.wait_for_confirmation(
                    result.hash,
                    timeout=options.confirmation_timeout,
                    poll_interval=options.poll_interval
                )
                
                return confirmed_result
            
            except Exception as e:
                logger.warning(f"Submit attempt {attempt + 1} failed: {e}")
                
                if attempt < retry_config.max_retries:
                    delay = self._exponential_backoff(
                        attempt,
                        base_delay=retry_config.base_delay,
                        max_delay=retry_config.max_delay,
                        jitter=retry_config.jitter
                    )
                    logger.info(f"Retrying in {delay:.2f}s...")
                    await asyncio.sleep(delay)
                else:
                    result.status = AptosExecutionStatus.FAILED
                    result.error_message = str(e)
                    logger.error(f"Transaction submission failed after {attempt + 1} attempts")
        
        return result
    
    async def wait_for_confirmation(
        self,
        tx_hash: str,
        timeout: int = 60,
        poll_interval: float = 1.0
    ) -> AptosExecutionResult:
        """
        等待交易确认
        
        Args:
            tx_hash: 交易哈希
            timeout: 超时时间 (秒)
            poll_interval: 轮询间隔 (秒)
        
        Returns:
            AptosExecutionResult
        """
        result = AptosExecutionResult(
            hash=tx_hash,
            status=AptosExecutionStatus.CONFIRMING
        )
        
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            try:
                # 获取交易信息
                txn = self.rpc_client.getTransaction(tx_hash)
                
                if not txn:
                    await asyncio.sleep(poll_interval)
                    continue
                
                # 解析状态
                result.status = AptosExecutionStatus.CONFIRMED
                result.success = txn.get("success", False)
                result.version = int(txn.get("version", 0)) if txn.get("version") else None
                
                # 解析 Gas
                gas_used = txn.get("gas_used", "0")
                result.gas_used = int(gas_used) if isinstance(gas_used, str) else gas_used
                
                gas_unit_price = txn.get("gas_unit_price", "0")
                result.gas_unit_price = int(gas_unit_price) if isinstance(gas_unit_price, str) else gas_unit_price
                
                result.total_gas_cost = result.gas_used * result.gas_unit_price
                
                # 解析时间
                timestamp = txn.get("timestamp", "0")
                if timestamp:
                    try:
                        result.processed_at = datetime.fromtimestamp(int(timestamp) / 1000)
                    except Exception:
                        pass
                
                result.confirmed_at = datetime.now()
                
                # 解析事件
                result.events = txn.get("events", [])
                
                # 解析错误
                if not result.success:
                    result.vm_status = txn.get("vm_status", "")
                    result.error_message = AptosErrorParser.format_error(txn)
                    result.status = AptosExecutionStatus.FAILED
                
                # 计算执行时间
                if result.submitted_at:
                    result.execution_time_ms = (
                        result.confirmed_at - result.submitted_at
                    ).total_seconds() * 1000
                
                # 保存到历史
                self._execution_history[tx_hash] = result
                
                return result
            
            except Exception as e:
                logger.debug(f"Polling {tx_hash}: {e}")
                await asyncio.sleep(poll_interval)
        
        # 超时
        result.status = AptosExecutionStatus.TIMEOUT
        result.error_message = f"Timeout after {timeout}s"
        
        return result
    
    def get_execution_status(self, tx_hash: str) -> Optional[AptosExecutionResult]:
        """
        获取执行状态
        
        Args:
            tx_hash: 交易哈希
        
        Returns:
            AptosExecutionResult 或 None
        """
        # 先检查历史
        if tx_hash in self._execution_history:
            return self._execution_history[tx_hash]
        
        # 查询链上
        try:
            txn = self.rpc_client.getTransaction(tx_hash)
            
            if not txn:
                return None
            
            result = AptosExecutionResult(
                hash=tx_hash,
                status=AptosExecutionStatus.CONFIRMED,
                success=txn.get("success", False),
                version=int(txn.get("version", 0)) if txn.get("version") else None
            )
            
            # Gas 信息
            gas_used = txn.get("gas_used", "0")
            result.gas_used = int(gas_used) if isinstance(gas_used, str) else gas_used
            
            gas_unit_price = txn.get("gas_unit_price", "0")
            result.gas_unit_price = int(gas_unit_price) if isinstance(gas_unit_price, str) else gas_unit_price
            
            result.total_gas_cost = result.gas_used * result.gas_unit_price
            
            # 事件
            result.events = txn.get("events", [])
            
            # 错误
            if not result.success:
                result.vm_status = txn.get("vm_status", "")
                result.error_message = AptosErrorParser.format_error(txn)
            
            return result
        
        except Exception as e:
            logger.error(f"Failed to get transaction status: {e}")
            return None
    
    async def execute_swap(
        self,
        sender: str,
        keypair,
        dex_name: str,
        token_in: str,
        token_out: str,
        amount_in: int,
        slippage_bps: int = 50,
        options: Optional[ExecutionOptions] = None
    ) -> AptosExecutionResult:
        """
        执行 Swap
        
        Args:
            sender: 发送者地址
            keypair: 密钥对
            dex_name: DEX 名称
            token_in: 输入代币
            token_out: 输出代币
            amount_in: 输入金额
            slippage_bps: 滑点容忍
            options: 执行选项
        
        Returns:
            AptosExecutionResult
        """
        options = options or ExecutionOptions()
        
        # 构建交易
        self.tx_builder.set_sender(sender, keypair)
        
        # 计算最小输出
        amount_out_min = int(amount_in * (1 - slippage_bps / 10000))
        
        # 构建 Payload
        payload = self.tx_builder.build_swap_payload(
            dex_name=dex_name,
            token_in=token_in,
            token_out=token_out,
            amount_in=amount_in,
            min_amount_out=amount_out_min
        )
        
        # 构建交易
        txn = self.tx_builder.build_transaction(
            payload=payload,
            sender=sender,
            gas_unit_price=options.gas_unit_price,
            max_gas_amount=options.max_gas_amount
        )
        
        # 签名
        signed_txn = self.tx_builder.sign_transaction(txn, keypair)
        
        # 提交
        return await self.submit_transaction(signed_txn, options)
    
    async def execute_coin_transfer(
        self,
        sender: str,
        keypair,
        to_address: str,
        amount: int,
        coin_type: str = "0x1::aptos_coin::AptosCoin",
        options: Optional[ExecutionOptions] = None
    ) -> AptosExecutionResult:
        """
        执行 Coin 转账
        
        Args:
            sender: 发送者地址
            keypair: 密钥对
            to_address: 接收地址
            amount: 金额
            coin_type: Coin 类型
            options: 执行选项
        
        Returns:
            AptosExecutionResult
        """
        options = options or ExecutionOptions()
        
        # 构建交易
        self.tx_builder.set_sender(sender, keypair)
        
        # 构建 Payload
        payload = self.tx_builder.build_coin_transfer_payload(
            to_address=to_address,
            amount=amount,
            coin_type=coin_type
        )
        
        # 构建交易
        txn = self.tx_builder.build_transaction(
            payload=payload,
            sender=sender,
            gas_unit_price=options.gas_unit_price,
            max_gas_amount=options.max_gas_amount
        )
        
        # 签名
        signed_txn = self.tx_builder.sign_transaction(txn, keypair)
        
        # 提交
        return await self.submit_transaction(signed_txn, options)
    
    def get_gas_price(self) -> int:
        """
        获取当前 Gas 价格
        
        Returns:
            Gas 单价 (Octas)
        """
        try:
            ledger = self.rpc_client.getLedgerInfo()
            
            # 尝试从ledger获取 gas price
            if "oldest_block_height" in ledger:
                # 这是新格式
                return self.tx_config.gas_unit_price
            
            # 默认值
            return self.tx_config.gas_unit_price
        
        except Exception:
            return self.tx_config.gas_unit_price
    
    def estimate_gas(
        self,
        sender: str,
        payload: Dict
    ) -> int:
        """
        估算 Gas
        
        Args:
            sender: 发送者地址
            payload: 交易负载
        
        Returns:
            预估 Gas 数量
        """
        return self.tx_builder.estimate_gas(payload, sender)
    
    def get_execution_history(self) -> Dict[str, AptosExecutionResult]:
        """获取执行历史"""
        return self._execution_history.copy()
    
    def clear_history(self):
        """清除执行历史"""
        self._execution_history.clear()


# ============================================
# 全局单例
# ============================================

_aptos_execution_engine: Optional[AptosExecutionEngine] = None


def get_aptos_execution_engine() -> AptosExecutionEngine:
    """获取全局 Aptos 执行引擎"""
    global _aptos_execution_engine
    if _aptos_execution_engine is None:
        _aptos_execution_engine = AptosExecutionEngine()
    return _aptos_execution_engine


def init_aptos_execution_engine(
    rpc_url: Optional[str] = None
) -> AptosExecutionEngine:
    """
    初始化 Aptos 执行引擎
    
    Args:
        rpc_url: RPC URL
    
    Returns:
        AptosExecutionEngine 实例
    """
    global _aptos_execution_engine
    _aptos_execution_engine = AptosExecutionEngine(rpc_url=rpc_url)
    return _aptos_execution_engine
