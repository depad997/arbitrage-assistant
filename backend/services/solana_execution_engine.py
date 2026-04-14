"""
Solana 执行引擎模块

功能：
- 交易提交与确认
- 失败重试机制（指数退避）
- 交易状态追踪
- 错误处理和日志记录
- 交易日志解析

Solana 交易特点：
- 确认时间约 400-600ms
- Gas 费用极低（约 0.000005 SOL）
- 交易失败也会扣除费用
- 需要轮询确认
"""

import asyncio
import logging
import time
import json
import base64
import hashlib
from typing import Dict, List, Optional, Tuple, Any, Union
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from decimal import Decimal
import httpx

import sys
import os as _os
_backend_dir = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from config.solana_dex import (
    SolanaRPCConfig,
    SolanaTxConfig,
    lamports_to_sol,
    sol_to_lamports
)

logger = logging.getLogger(__name__)


# ============================================
# 枚举和常量
# ============================================

class SolanaExecutionStatus(Enum):
    """Solana 执行状态"""
    PENDING = "pending"              # 待提交
    SUBMITTED = "submitted"          # 已提交
    CONFIRMING = "confirming"       # 确认中
    CONFIRMED = "confirmed"         # 已确认
    FINALIZED = "finalized"         # 最终确认
    FAILED = "failed"               # 失败
    TIMEOUT = "timeout"             # 超时
    REJECTED = "rejected"           # 被拒绝


class CommitmentLevel(Enum):
    """确认级别"""
    PROCESSED = "processed"         # 已处理（最快，不保证最终性）
    CONFIRMED = "confirmed"         # 已确认
    FINALIZED = "finalized"         # 最终确认（最安全）


# ============================================
# 数据类定义
# ============================================

@dataclass
class SolanaExecutionResult:
    """Solana 执行结果"""
    signature: str                    # 交易签名
    status: SolanaExecutionStatus     # 状态
    block_height: Optional[int] = None  # 区块高度
    slot: Optional[int] = None         # Slot
    fee: int = 0                       # 手续费 (lamports)
    fee_usd: Optional[float] = None   # 手续费 (USD)
    
    # 错误信息
    error_message: Optional[str] = None
    error_code: Optional[int] = None
    
    # 日志
    logs: List[str] = field(default_factory=list)
    
    # 时间
    submitted_at: Optional[datetime] = None
    confirmed_at: Optional[datetime] = None
    finalized_at: Optional[datetime] = None
    execution_time_ms: float = 0.0
    
    # 附加信息
    compute_units_used: Optional[int] = None
    compute_units_limit: Optional[int] = None
    
    def to_dict(self) -> Dict:
        return {
            "signature": self.signature,
            "status": self.status.value,
            "block_height": self.block_height,
            "slot": self.slot,
            "fee": self.fee,
            "fee_usd": self.fee_usd,
            "error_message": self.error_message,
            "error_code": self.error_code,
            "logs": self.logs,
            "submitted_at": self.submitted_at.isoformat() if self.submitted_at else None,
            "confirmed_at": self.confirmed_at.isoformat() if self.confirmed_at else None,
            "finalized_at": self.finalized_at.isoformat() if self.finalized_at else None,
            "execution_time_ms": self.execution_time_ms,
            "compute_units_used": self.compute_units_used,
            "compute_units_limit": self.compute_units_limit
        }


@dataclass
class RetryConfig:
    """重试配置"""
    max_retries: int = SolanaTxConfig.MAX_RETRIES
    base_delay: float = SolanaTxConfig.RETRY_DELAY
    max_delay: float = 30.0
    exponential_base: float = 2.0
    jitter: bool = True


@dataclass
class RpcConfig:
    """RPC 配置"""
    url: str
    commitment: str = "confirmed"
    timeout: int = 30
    max_retries: int = 3


# ============================================
# RPC 客户端
# ============================================

class SolanaRpcClient:
    """
    Solana RPC 客户端
    
    封装常用的 RPC 调用
    """
    
    def __init__(
        self,
        rpc_url: str = SolanaRPCConfig.DEFAULT_MAINNET,
        commitment: CommitmentLevel = CommitmentLevel.CONFIRMED
    ):
        self.rpc_url = rpc_url
        self.commitment = commitment.value
        self._client = httpx.Client(timeout=30)
    
    def close(self):
        """关闭客户端"""
        self._client.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
    
    def _post(self, method: str, params: List = None) -> Dict:
        """发送 RPC 请求"""
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params or []
        }
        
        response = self._client.post(
            self.rpc_url,
            json=payload,
            headers={"Content-Type": "application/json"}
        )
        response.raise_for_status()
        return response.json()
    
    def get_latest_blockhash(self) -> Tuple[str, int]:
        """
        获取最新的 blockhash 和 block height
        
        Returns:
            (blockhash, last_valid_block_height)
        """
        result = self._post("getLatestBlockhash", [{"commitment": self.commitment}])
        value = result["result"]["value"]
        return value["blockhash"], value["lastValidBlockHeight"]
    
    def get_block_height(self) -> int:
        """获取当前区块高度"""
        result = self._post("getBlockHeight", [{"commitment": self.commitment}])
        return result["result"]
    
    def get_signature_status(
        self,
        signature: str,
        search_transaction_history: bool = False
    ) -> Dict:
        """
        获取交易签名状态
        
        Returns:
            状态信息字典
        """
        return self._post(
            "getSignatureStatuses",
            [[signature], {"searchTransactionHistory": search_transaction_history}]
        )
    
    def get_transaction(
        self,
        signature: str,
        encoding: str = "jsonParsed"
    ) -> Optional[Dict]:
        """
        获取交易详情
        
        Returns:
            交易信息或 None
        """
        result = self._post(
            "getTransaction",
            [signature, {"encoding": encoding, "maxSupportedTransactionVersion": 0}]
        )
        
        if "result" in result and result["result"] is not None:
            return result["result"]
        return None
    
    def send_transaction(
        self,
        transaction: Union[bytes, str],
        skip_preflight: bool = False,
        preflight_commitment: str = "confirmed",
        max_retries: int = 3
    ) -> str:
        """
        发送交易
        
        Args:
            transaction: 交易字节或 hex 字符串
            skip_preflight: 跳过预检
            preflight_commitment: 预检确认级别
            max_retries: 最大重试次数
        
        Returns:
            交易签名
        """
        if isinstance(transaction, str):
            # hex 字符串
            tx_bytes = bytes.fromhex(transaction)
        elif isinstance(transaction, bytes):
            tx_bytes = transaction
        else:
            raise ValueError("Transaction must be bytes or hex string")
        
        tx_base64 = base64.b64encode(tx_bytes).decode()
        
        for attempt in range(max_retries):
            try:
                result = self._post(
                    "sendTransaction",
                    [{
                        "transaction": tx_base64,
                        "skipPreflight": skip_preflight,
                        "preflightCommitment": preflight_commitment,
                        "encoding": "base64",
                        "maxSupportedTransactionVersion": 0
                    }]
                )
                
                if "result" in result:
                    return result["result"]
                elif "error" in result:
                    error = result["error"]
                    logger.warning(f"Transaction error: {error}")
                    if attempt < max_retries - 1:
                        time.sleep(0.5 * (attempt + 1))
                        continue
                    raise Exception(f"Transaction failed: {error}")
                    
            except httpx.HTTPError as e:
                logger.warning(f"RPC error (attempt {attempt + 1}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                raise
        
        raise Exception("Failed to send transaction after retries")
    
    def simulate_transaction(
        self,
        transaction: Union[bytes, str],
        sig_verify: bool = False
    ) -> Dict:
        """
        模拟交易
        
        Returns:
            模拟结果
        """
        if isinstance(transaction, str):
            tx_bytes = bytes.fromhex(transaction)
        else:
            tx_bytes = transaction
        
        tx_base64 = base64.b64encode(tx_bytes).decode()
        
        result = self._post(
            "simulateTransaction",
            [{
                "transaction": tx_base64,
                "encoding": "base64",
                "sigVerify": sig_verify,
                "maxSupportedTransactionVersion": 0
            }]
        )
        
        return result.get("result", {})
    
    def get_token_account_balance(self, token_account: str) -> Dict:
        """
        获取代币账户余额
        
        Returns:
            余额信息
        """
        return self._post("getTokenAccountBalance", [token_account])
    
    def get_balance(self, pubkey: str) -> int:
        """
        获取 SOL 余额
        
        Returns:
            余额 (lamports)
        """
        result = self._post("getBalance", [pubkey])
        return result["result"]["value"]


# ============================================
# 执行引擎
# ============================================

class SolanaExecutionEngine:
    """
    Solana 执行引擎
    
    功能：
    - 交易提交
    - 确认等待
    - 失败重试
    - 状态追踪
    """
    
    def __init__(
        self,
        rpc_url: str = SolanaRPCConfig.DEFAULT_MAINNET,
        commitment: CommitmentLevel = CommitmentLevel.CONFIRMED,
        retry_config: Optional[RetryConfig] = None,
        fallback_rpcs: Optional[List[str]] = None
    ):
        """
        初始化执行引擎
        
        Args:
            rpc_url: RPC URL
            commitment: 确认级别
            retry_config: 重试配置
            fallback_rpcs: 备用 RPC 列表
        """
        self.rpc_url = rpc_url
        self.commitment = commitment
        self.retry_config = retry_config or RetryConfig()
        self.fallback_rpcs = fallback_rpcs or SolanaRPCConfig.MAINNET_RPCS.copy()
        
        # 初始化 RPC 客户端
        self._client = SolanaRpcClient(rpc_url, commitment)
        
        # 执行历史
        self._execution_history: Dict[str, SolanaExecutionResult] = {}
        
        # RPC 故障转移
        self._current_rpc_index = 0
    
    def close(self):
        """关闭引擎"""
        self._client.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
    
    def _switch_rpc(self):
        """切换到备用 RPC"""
        self._current_rpc_index = (self._current_rpc_index + 1) % len(self.fallback_rpcs)
        self.rpc_url = self.fallback_rpcs[self._current_rpc_index]
        
        # 重新创建客户端
        self._client.close()
        self._client = SolanaRpcClient(self.rpc_url, self.commitment)
        
        logger.info(f"Switched to RPC: {self.rpc_url}")
    
    def submit_transaction(
        self,
        transaction: Union[bytes, str],
        skip_preflight: bool = False
    ) -> str:
        """
        提交交易
        
        Args:
            transaction: 交易字节或 hex
            skip_preflight: 跳过预检
        
        Returns:
            交易签名
        """
        start_time = time.time()
        
        try:
            signature = self._client.send_transaction(
                transaction,
                skip_preflight=skip_preflight
            )
            
            logger.info(f"Transaction submitted: {signature}")
            
            # 创建执行结果
            result = SolanaExecutionResult(
                signature=signature,
                status=SolanaExecutionStatus.SUBMITTED,
                submitted_at=datetime.now()
            )
            
            self._execution_history[signature] = result
            
            return signature
            
        except Exception as e:
            logger.error(f"Failed to submit transaction: {e}")
            
            # 尝试故障转移
            for _ in range(len(self.fallback_rpcs) - 1):
                try:
                    self._switch_rpc()
                    signature = self._client.send_transaction(
                        transaction,
                        skip_preflight=skip_preflight
                    )
                    
                    result = SolanaExecutionResult(
                        signature=signature,
                        status=SolanaExecutionStatus.SUBMITTED,
                        submitted_at=datetime.now()
                    )
                    
                    self._execution_history[signature] = result
                    return signature
                    
                except Exception:
                    continue
            
            raise
    
    def wait_for_confirmation(
        self,
        signature: str,
        timeout: float = SolanaTxConfig.TX_TIMEOUT,
        poll_interval: float = SolanaTxConfig.CONFIRM_POLL_INTERVAL
    ) -> SolanaExecutionResult:
        """
        等待交易确认
        
        Args:
            signature: 交易签名
            timeout: 超时时间（秒）
            poll_interval: 轮询间隔（秒）
        
        Returns:
            执行结果
        """
        start_time = time.time()
        
        # 更新状态
        if signature in self._execution_history:
            self._execution_history[signature].status = SolanaExecutionStatus.CONFIRMING
        else:
            result = SolanaExecutionResult(
                signature=signature,
                status=SolanaExecutionStatus.CONFIRMING,
                submitted_at=datetime.now()
            )
            self._execution_history[signature] = result
        
        last_status = None
        poll_count = 0
        
        while True:
            elapsed = time.time() - start_time
            
            # 检查超时
            if elapsed > timeout:
                result = self._execution_history[signature]
                result.status = SolanaExecutionStatus.TIMEOUT
                result.execution_time_ms = elapsed * 1000
                logger.warning(f"Transaction confirmation timeout: {signature}")
                return result
            
            # 查询状态
            try:
                status_response = self._client.get_signature_status(signature)
                
                if "result" in status_response:
                    status_info = status_response["result"]["value"]
                    
                    if status_info is not None:
                        confirmation_status = status_info.get("confirmationStatus")
                        
                        # 检查是否有错误
                        if status_info.get("err"):
                            result = self._execution_history[signature]
                            result.status = SolanaExecutionStatus.FAILED
                            result.error_message = str(status_info["err"])
                            result.execution_time_ms = elapsed * 1000
                            
                            # 尝试解析错误
                            self._parse_error(result, status_info["err"])
                            
                            logger.error(f"Transaction failed: {signature}, error: {result.error_message}")
                            return result
                        
                        # 更新状态
                        result = self._execution_history[signature]
                        
                        if confirmation_status == "finalized":
                            result.status = SolanaExecutionStatus.FINALIZED
                            result.finalized_at = datetime.now()
                            result.execution_time_ms = elapsed * 1000
                            logger.info(f"Transaction finalized: {signature}")
                            
                            # 获取交易详情
                            self._fetch_transaction_details(result, signature)
                            return result
                            
                        elif confirmation_status == "confirmed":
                            if result.status != SolanaExecutionStatus.CONFIRMED:
                                result.status = SolanaExecutionStatus.CONFIRMED
                                result.confirmed_at = datetime.now()
                                result.execution_time_ms = elapsed * 1000
                            
                            # 获取交易详情
                            self._fetch_transaction_details(result, signature)
                
                poll_count += 1
                
                # 动态调整轮询间隔
                current_interval = min(poll_interval * (1 + poll_count * 0.1), 2.0)
                time.sleep(current_interval)
                
            except Exception as e:
                logger.warning(f"Error polling status: {e}")
                time.sleep(poll_interval)
    
    def _fetch_transaction_details(self, result: SolanaExecutionResult, signature: str):
        """获取交易详情"""
        try:
            tx_info = self._client.get_transaction(signature)
            
            if tx_info:
                # 解析元数据
                meta = tx_info.get("meta", {})
                
                result.fee = meta.get("fee", 0)
                result.compute_units_used = meta.get("computeUnitsConsumed")
                result.logs = meta.get("logMessages", [])
                result.block_height = tx_info.get("slot")
                
                # 解析预执行信息
                if "preTokenBalances" in meta and "postTokenBalances" in meta:
                    # Token 余额变化
                    result.token_changes = {
                        "pre": meta.get("preTokenBalances", []),
                        "post": meta.get("postTokenBalances", [])
                    }
                    
        except Exception as e:
            logger.warning(f"Failed to fetch transaction details: {e}")
    
    def _parse_error(self, result: SolanaExecutionResult, error: Dict):
        """解析错误信息"""
        if isinstance(error, dict):
            # 尝试提取错误代码和消息
            if "InstructionError" in error:
                instr_error = error["InstructionError"]
                if isinstance(instr_error, list) and len(instr_error) >= 2:
                    result.error_code = instr_error[0]
                    result.error_message = str(instr_error[1])
            elif "Custom" in error:
                result.error_code = error["Custom"]
                result.error_message = f"Custom error: {error['Custom']}"
            else:
                result.error_message = str(error)
    
    def execute_with_retry(
        self,
        transaction: Union[bytes, str],
        skip_preflight: bool = False
    ) -> SolanaExecutionResult:
        """
        执行交易（带重试）
        
        Args:
            transaction: 交易字节或 hex
            skip_preflight: 跳过预检
        
        Returns:
            执行结果
        """
        last_error = None
        
        for attempt in range(self.retry_config.max_retries):
            try:
                # 1. 提交交易
                signature = self.submit_transaction(transaction, skip_preflight)
                
                # 2. 等待确认
                result = self.wait_for_confirmation(signature)
                
                # 3. 检查结果
                if result.status in [
                    SolanaExecutionStatus.CONFIRMED,
                    SolanaExecutionStatus.FINALIZED
                ]:
                    return result
                
                # 如果失败且不是超时，重试
                if result.status == SolanaExecutionStatus.FAILED:
                    last_error = result.error_message
                    logger.warning(
                        f"Transaction failed (attempt {attempt + 1}): {result.error_message}"
                    )
                    
                    # 计算退避时间
                    delay = min(
                        self.retry_config.base_delay * (
                            self.retry_config.exponential_base ** attempt
                        ),
                        self.retry_config.max_delay
                    )
                    
                    if self.retry_config.jitter:
                        import random
                        delay *= (0.5 + random.random())
                    
                    logger.info(f"Retrying in {delay:.2f} seconds...")
                    time.sleep(delay)
                    continue
                
                return result
                
            except Exception as e:
                last_error = str(e)
                logger.warning(f"Execution error (attempt {attempt + 1}): {e}")
                
                if attempt < self.retry_config.max_retries - 1:
                    delay = self.retry_config.base_delay * (
                        self.retry_config.exponential_base ** attempt
                    )
                    time.sleep(min(delay, self.retry_config.max_delay))
        
        # 所有重试都失败
        result = SolanaExecutionResult(
            signature="unknown",
            status=SolanaExecutionStatus.FAILED,
            error_message=f"All retries failed. Last error: {last_error}"
        )
        return result
    
    def get_execution_status(self, signature: str) -> Optional[SolanaExecutionResult]:
        """
        获取执行状态
        
        Args:
            signature: 交易签名
        
        Returns:
            执行结果或 None
        """
        # 先从历史记录中查找
        if signature in self._execution_history:
            return self._execution_history[signature]
        
        # 查询 RPC
        try:
            status_response = self._client.get_signature_status(signature)
            
            if "result" in status_response:
                status_info = status_response["result"]["value"]
                
                if status_info is None:
                    return None
                
                result = SolanaExecutionResult(
                    signature=signature,
                    status=self._map_status(status_info.get("confirmationStatus")),
                    block_height=status_info.get("slot")
                )
                
                if status_info.get("err"):
                    result.status = SolanaExecutionStatus.FAILED
                    result.error_message = str(status_info["err"])
                
                return result
                
        except Exception as e:
            logger.error(f"Failed to get status: {e}")
        
        return None
    
    def _map_status(self, status: Optional[str]) -> SolanaExecutionStatus:
        """映射确认状态"""
        if status is None:
            return SolanaExecutionStatus.SUBMITTED
        
        mapping = {
            "processed": SolanaExecutionStatus.CONFIRMING,
            "confirmed": SolanaExecutionStatus.CONFIRMED,
            "finalized": SolanaExecutionStatus.FINALIZED
        }
        
        return mapping.get(status, SolanaExecutionStatus.SUBMITTED)
    
    def get_execution_history(self) -> List[SolanaExecutionResult]:
        """获取执行历史"""
        return list(self._execution_history.values())
    
    def parse_transaction_logs(self, logs: List[str]) -> Dict[str, Any]:
        """
        解析交易日志
        
        Args:
            logs: 日志列表
        
        Returns:
            解析后的信息
        """
        parsed = {
            "programs": [],
            "errors": [],
            "warnings": [],
            "computed_units": None,
            "logs": logs
        }
        
        for log in logs:
            # 解析程序调用
            if "invoke" in log.lower():
                parsed["programs"].append(log)
            
            # 解析错误
            if "error" in log.lower():
                parsed["errors"].append(log)
            
            # 解析警告
            if "warning" in log.lower() or "warn" in log.lower():
                parsed["warnings"].append(log)
            
            # 解析计算单元
            if "compute units" in log.lower():
                try:
                    # "1234 compute units consumed"
                    parts = log.split()
                    for i, part in enumerate(parts):
                        if "compute" in part.lower() and i > 0:
                            parsed["computed_units"] = int(parts[i - 1])
                            break
                except (ValueError, IndexError):
                    pass
        
        return parsed
    
    def estimate_fee_usd(self, fee_lamports: int, sol_price: float = 100.0) -> float:
        """
        估算手续费（USD）
        
        Args:
            fee_lamports: 手续费 (lamports)
            sol_price: SOL 价格 (USD)
        
        Returns:
            手续费 (USD)
        """
        sol_amount = lamports_to_sol(fee_lamports)
        return sol_amount * sol_price


# ============================================
# 异步执行引擎
# ============================================

class AsyncSolanaExecutionEngine:
    """
    异步 Solana 执行引擎
    
    适用于 asyncio 环境
    """
    
    def __init__(
        self,
        rpc_url: str = SolanaRPCConfig.DEFAULT_MAINNET,
        commitment: CommitmentLevel = CommitmentLevel.CONFIRMED,
        retry_config: Optional[RetryConfig] = None
    ):
        self.rpc_url = rpc_url
        self.commitment = commitment
        self.retry_config = retry_config or RetryConfig()
        self._client: Optional[httpx.AsyncClient] = None
    
    async def _get_client(self) -> httpx.AsyncClient:
        """获取或创建异步客户端"""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client
    
    async def close(self):
        """关闭客户端"""
        if self._client:
            await self._client.aclose()
            self._client = None
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
    
    async def _post(self, method: str, params: List = None) -> Dict:
        """发送异步 RPC 请求"""
        client = await self._get_client()
        
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params or []
        }
        
        response = await client.post(
            self.rpc_url,
            json=payload,
            headers={"Content-Type": "application/json"}
        )
        response.raise_for_status()
        return response.json()
    
    async def send_transaction(
        self,
        transaction: Union[bytes, str],
        skip_preflight: bool = False
    ) -> str:
        """异步发送交易"""
        if isinstance(transaction, str):
            tx_bytes = bytes.fromhex(transaction)
        else:
            tx_bytes = transaction
        
        tx_base64 = base64.b64encode(tx_bytes).decode()
        
        result = await self._post(
            "sendTransaction",
            [{
                "transaction": tx_base64,
                "skipPreflight": skip_preflight,
                "preflightCommitment": self.commitment.value,
                "encoding": "base64"
            }]
        )
        
        return result["result"]
    
    async def wait_for_confirmation(
        self,
        signature: str,
        timeout: float = SolanaTxConfig.TX_TIMEOUT,
        poll_interval: float = SolanaTxConfig.CONFIRM_POLL_INTERVAL
    ) -> SolanaExecutionResult:
        """异步等待确认"""
        start_time = time.time()
        
        result = SolanaExecutionResult(
            signature=signature,
            status=SolanaExecutionStatus.CONFIRMING,
            submitted_at=datetime.now()
        )
        
        while True:
            elapsed = time.time() - start_time
            
            if elapsed > timeout:
                result.status = SolanaExecutionStatus.TIMEOUT
                result.execution_time_ms = elapsed * 1000
                return result
            
            try:
                status_response = await self._post(
                    "getSignatureStatuses",
                    [[signature], {"searchTransactionHistory": False}]
                )
                
                if "result" in status_response:
                    status_info = status_response["result"]["value"]
                    
                    if status_info is not None:
                        confirmation_status = status_info.get("confirmationStatus")
                        
                        if status_info.get("err"):
                            result.status = SolanaExecutionStatus.FAILED
                            result.error_message = str(status_info["err"])
                            result.execution_time_ms = elapsed * 1000
                            return result
                        
                        if confirmation_status == "finalized":
                            result.status = SolanaExecutionStatus.FINALIZED
                            result.finalized_at = datetime.now()
                            result.execution_time_ms = elapsed * 1000
                            return result
                        
                        elif confirmation_status == "confirmed":
                            result.status = SolanaExecutionStatus.CONFIRMED
                            result.confirmed_at = datetime.now()
                            result.execution_time_ms = elapsed * 1000
                
                await asyncio.sleep(poll_interval)
                
            except Exception as e:
                logger.warning(f"Error polling status: {e}")
                await asyncio.sleep(poll_interval)
        
        return result
    
    async def execute(
        self,
        transaction: Union[bytes, str]
    ) -> SolanaExecutionResult:
        """异步执行交易"""
        signature = await self.send_transaction(transaction)
        return await self.wait_for_confirmation(signature)


# ============================================
# 单例访问器
# ============================================

_solana_engine_instance: Optional[SolanaExecutionEngine] = None


def get_solana_execution_engine(
    rpc_url: Optional[str] = None,
    commitment: CommitmentLevel = CommitmentLevel.CONFIRMED
) -> SolanaExecutionEngine:
    """
    获取 SolanaExecutionEngine 单例
    
    Args:
        rpc_url: RPC URL
        commitment: 确认级别
    
    Returns:
        SolanaExecutionEngine 实例
    """
    global _solana_engine_instance
    
    if _solana_engine_instance is None:
        _solana_engine_instance = SolanaExecutionEngine(
            rpc_url=rpc_url or SolanaRPCConfig.DEFAULT_MAINNET,
            commitment=commitment
        )
    
    return _solana_engine_instance


def close_solana_execution_engine():
    """关闭执行引擎"""
    global _solana_engine_instance
    
    if _solana_engine_instance is not None:
        _solana_engine_instance.close()
        _solana_engine_instance = None
