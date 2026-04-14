"""
Aptos 交易构建模块

功能：
- 构建 Aptos交易 (Entry Function)
- DEX Swap 交易构建 (Liquidswap/Thala)
- 跨链桥接交易 (Wormhole/LayerZero)
- Gas 计算
- 交易序列化 (BCS)
- Payload 构建

Aptos 交易特点：
- 使用 BCS (Binary Canonical Serialization) 编码
- 支持 Entry Function 调用
- Transaction Payload 类型:
  - entry_function: 入口函数调用
  - script: Move 脚本
  - script_function: 脚本函数
"""

import base64
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any, Union
from enum import Enum

import sys
import os as _os
_backend_dir = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from config.aptos_dex import (
    AptosAPIConfig,
    AptosTxConfig,
    AptosCoins,
    SupportedAptosDEX,
    WormholeAptosConfig,
    LayerZeroAptosConfig,
    format_apt_amount,
    parse_apt_amount,
)

logger = logging.getLogger(__name__)


# ============================================
# 错误定义
# ============================================

class AptosTxBuilderError(Exception):
    """Aptos 交易构建错误"""
    pass


class InvalidSwapParamsError(AptosTxBuilderError):
    """无效的 Swap 参数"""
    pass


class SimulationError(AptosTxBuilderError):
    """模拟执行错误"""
    pass


# ============================================
# 枚举和常量
# ============================================

class PayloadType(Enum):
    """交易负载类型"""
    ENTRY_FUNCTION = "entry_function"
    SCRIPT = "script"
    SCRIPT_FUNCTION = "script_function"


class TransactionType(Enum):
    """交易类型"""
    SCRIPT = "script"
    SCRIPT_FUNCTION = "script_function"
    MODULE_PUBLICATION = "module_publication"
    ONE_TIME_WALLET_REGISTRATION = "one_time_wallet_registration"


# ============================================
# 数据类定义
# ============================================

@dataclass
class EntryFunctionPayload:
    """Entry Function 负载"""
    module_address: str                  # 模块地址
    module_name: str                      # 模块名称
    function_name: str                    # 函数名称
    type_arguments: List[str] = field(default_factory=list)  # 类型参数
    arguments: List[Any] = field(default_factory=list)       # 函数参数
    
    def to_dict(self) -> Dict:
        return {
            "type": "entry_function_payload",
            "function": f"{self.module_address}::{self.module_name}::{self.function_name}",
            "type_arguments": self.type_arguments,
            "arguments": self.arguments
        }


@dataclass
class RawTransaction:
    """原始交易"""
    sender: str                           # 发送者地址
    sequence_number: int                  # 序列号
    payload: Dict                        # 交易负载
    max_gas_amount: int                  # 最大 Gas
    gas_unit_price: int                  # Gas 单价 (Octas)
    expiration_timestamp_secs: int       # 过期时间戳
    chain_id: int                        # 链 ID
    
    def to_dict(self) -> Dict:
        return {
            "sender": self.sender,
            "sequence_number": self.sequence_number,
            "payload": self.payload,
            "max_gas_amount": self.max_gas_amount,
            "gas_unit_price": self.gas_unit_price,
            "expiration_timestamp_secs": self.expiration_timestamp_secs,
            "chain_id": self.chain_id
        }


@dataclass
class SignedTransaction:
    """已签名交易"""
    transaction: RawTransaction           # 原始交易
    signature: str                        # 签名 (base64)
    public_key: str                       # 公钥 (base64)
    
    def to_dict(self) -> Dict:
        return {
            "transaction": self.transaction.to_dict(),
            "signature": self.signature,
            "public_key": self.public_key
        }


@dataclass
class SwapParams:
    """Swap 参数"""
    token_in: str                         # 输入代币地址
    token_out: str                        # 输出代币地址
    amount_in: int                        # 输入金额 (最小单位)
    amount_out_min: int                   # 最小输出金额
    slippage_bps: int = 50                # 滑点容忍 (basis points)
    
    def __post_init__(self):
        if self.amount_in <= 0:
            raise InvalidSwapParamsError("amount_in must be positive")
        if self.slippage_bps < 0 or self.slippage_bps > 10000:
            raise InvalidSwapParamsError("slippage_bps must be between 0 and 10000")


@dataclass
class SwapQuote:
    """Swap 报价"""
    dex_name: str                         # DEX 名称
    amount_in: int                        # 输入金额
    amount_out: int                       # 输出金额
    amount_out_min: int                   # 最小输出金额
    price_impact_bps: int                # 价格影响 (basis points)
    pool_address: str                     # 池子地址
    gas_estimate: int                    # 预估 Gas
    route: List[str] = field(default_factory=list)  # 路由路径
    fees: Dict[str, int] = field(default_factory=dict)  # 手续费
    
    @property
    def price_impact_pct(self) -> float:
        """价格影响百分比"""
        return self.price_impact_bps / 100
    
    def to_dict(self) -> Dict:
        return {
            "dex_name": self.dex_name,
            "amount_in": self.amount_in,
            "amount_out": self.amount_out,
            "amount_out_min": self.amount_out_min,
            "price_impact_bps": self.price_impact_bps,
            "price_impact_pct": self.price_impact_pct,
            "pool_address": self.pool_address,
            "gas_estimate": self.gas_estimate,
            "route": self.route,
            "fees": self.fees
        }


# ============================================
# BCS 编码工具
# ============================================

class AptosBcsCodec:
    """Aptos BCS (Binary Canonical Serialization) 编解码器"""
    
    @staticmethod
    def encode_address(address: str) -> bytes:
        """编码 Aptos 地址 (32 字节)"""
        if address.startswith("0x"):
            address = address[2:]
        return bytes.fromhex(address.zfill(64))
    
    @staticmethod
    def encode_u8(value: int) -> bytes:
        """编码 u8 整数"""
        return bytes([value & 0xff])
    
    @staticmethod
    def encode_u16(value: int) -> bytes:
        """编码 u16 整数 (小端)"""
        return struct.pack("<H", value)
    
    @staticmethod
    def encode_u32(value: int) -> bytes:
        """编码 u32 整数 (小端)"""
        return struct.pack("<I", value)
    
    @staticmethod
    def encode_u64(value: int) -> bytes:
        """编码 u64 整数 (LEB128)"""
        result = []
        while True:
            byte = value & 0x7f
            value >>= 7
            if value != 0:
                byte |= 0x80
            result.append(byte)
            if value == 0:
                break
        return bytes(result)
    
    @staticmethod
    def encode_u128(value: int) -> bytes:
        """编码 u128 整数 (LEB128)"""
        result = []
        while True:
            byte = value & 0x7f
            value >>= 7
            if value != 0:
                byte |= 0x80
            result.append(byte)
            if value == 0:
                break
        return bytes(result)
    
    @staticmethod
    def encode_bool(value: bool) -> bytes:
        """编码布尔值"""
        return bytes([1 if value else 0])
    
    @staticmethod
    def encode_string(value: str) -> bytes:
        """编码字符串"""
        encoded = value.encode('utf-8')
        return AptosBcsCodec.encode_u64(len(encoded)) + encoded
    
    @staticmethod
    def encode_vector(values: List[bytes], serializer) -> bytes:
        """编码向量"""
        result = AptosBcsCodec.encode_u64(len(values))
        for value in values:
            result += serializer(value)
        return result
    
    @staticmethod
    def encode_transaction(
        sender: str,
        sequence_number: int,
        payload: Dict,
        max_gas_amount: int,
        gas_unit_price: int,
        expiration_timestamp_secs: int,
        chain_id: int
    ) -> bytes:
        """
        编码交易 (BCS 格式)
        
        顺序:
        1. sender (32 bytes)
        2. sequence_number (LEB128)
        3. payload (复杂类型)
        4. max_gas_amount (LEB128)
        5. gas_unit_price (LEB128)
        6. expiration_timestamp_secs (LEB128)
        7. chain_id (u8)
        """
        result = AptosBcsCodec.encode_address(sender)
        result += AptosBcsCodec.encode_u64(sequence_number)
        # Payload 编码
        result += AptosBcsCodec._encode_payload(payload)
        result += AptosBcsCodec.encode_u64(max_gas_amount)
        result += AptosBcsCodec.encode_u64(gas_unit_price)
        result += AptosBcsCodec.encode_u64(expiration_timestamp_secs)
        result += AptosBcsCodec.encode_u8(chain_id)
        return result
    
    @staticmethod
    def _encode_payload(payload: Dict) -> bytes:
        """编码 Payload"""
        payload_type = payload.get("type", "entry_function_payload")
        
        if payload_type == "entry_function_payload":
            result = AptosBcsCodec.encode_u8(0)  # variant index
            
            # function: string
            result += AptosBcsCodec.encode_string(payload.get("function", ""))
            
            # type_arguments: vector<string>
            type_args = payload.get("type_arguments", [])
            result += AptosBcsCodec.encode_vector(
                type_args,
                AptosBcsCodec.encode_string
            )
            
            # arguments: vector<any>
            args = payload.get("arguments", [])
            result += AptosBcsCodec.encode_vector(
                args,
                AptosBcsCodec._encode_argument
            )
            
            return result
        
        return b""
    
    @staticmethod
    def _encode_argument(arg: Any) -> bytes:
        """编码函数参数"""
        if isinstance(arg, bool):
            return AptosBcsCodec.encode_bool(arg)
        elif isinstance(arg, int):
            return AptosBcsCodec.encode_u64(arg)
        elif isinstance(arg, str):
            if arg.startswith("0x"):
                return AptosBcsCodec.encode_address(arg)
            return AptosBcsCodec.encode_string(arg)
        elif isinstance(arg, list):
            return AptosBcsCodec.encode_vector(arg, AptosBcsCodec._encode_argument)
        
        return AptosBcsCodec.encode_string(str(arg))


# ============================================
# RPC 客户端
# ============================================

class AptosRpcClient:
    """Aptos REST API 客户端 (简化版)"""
    
    def __init__(
        self,
        rpc_url: Optional[str] = None,
        timeout: int = AptosAPIConfig.REQUEST_TIMEOUT
    ):
        import httpx
        self.rpc_url = rpc_url or AptosAPIConfig.MAINNET
        self.timeout = timeout
        self._client = httpx.Client(timeout=timeout)
    
    def close(self):
        self._client.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
    
    def _get(self, endpoint: str, params: Dict = None) -> Dict:
        url = f"{self.rpc_url}/{endpoint.lstrip('/')}"
        try:
            response = self._client.get(url, params=params)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            raise AptosTxBuilderError(f"GET {url} failed: {e}")
    
    def _post(self, endpoint: str, data: Dict = None) -> Dict:
        url = f"{self.rpc_url}/{endpoint.lstrip('/')}"
        try:
            response = self._client.post(
                url,
                json=data,
                headers={"Content-Type": "application/json"}
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            raise AptosTxBuilderError(f"POST {url} failed: {e}")
    
    def getAccount(self, address: str) -> Dict:
        """获取账户信息"""
        return self._get(f"/accounts/{address}")
    
    def getChainId(self) -> int:
        """获取链 ID"""
        return self._get("/").get("chain_id", 1)
    
    def getLedgerInfo(self) -> Dict:
        """获取账本信息"""
        return self._get("/")
    
    def submit_transaction(self, txn: Dict) -> Dict:
        """提交交易"""
        return self._post("/transactions", txn)
    
    def simulate_transaction(self, txn: Dict) -> Dict:
        """模拟交易"""
        return self._post("/transactions/simulate", txn)
    
    def getTransaction(self, tx_hash: str) -> Dict:
        """获取交易"""
        return self._get(f"/transactions/{tx_hash}")


# ============================================
# Aptos 交易构建器
# ============================================

class AptosTransactionBuilder:
    """
    Aptos 交易构建器
    
    功能：
    - 构建 Entry Function 交易
    - 构建 DEX Swap 交易
    - 构建跨链桥交易
    - Gas 计算
    """
    
    def __init__(
        self,
        rpc_url: Optional[str] = None,
        tx_config: Optional[AptosTxConfig] = None
    ):
        self.rpc_url = rpc_url or AptosAPIConfig.MAINNET
        self.tx_config = tx_config or AptosTxConfig()
        self.rpc_client = AptosRpcClient(self.rpc_url)
        
        # 当前 sender
        self._sender: Optional[str] = None
        self._keypair = None
    
    def close(self):
        """关闭资源"""
        self.rpc_client.close()
    
    def set_sender(self, address: str, keypair=None):
        """
        设置发送者
        
        Args:
            address: 发送者地址
            keypair: 密钥对 (用于签名)
        """
        self._sender = address
        self._keypair = keypair
    
    def _get_chain_id(self) -> int:
        """获取链 ID"""
        try:
            return self.rpc_client.getChainId()
        except Exception:
            # 默认主网
            return 1
    
    def _get_ledger_timestamp(self) -> int:
        """获取账本时间戳 (秒)"""
        try:
            ledger = self.rpc_client.getLedgerInfo()
            return ledger.get("ledger_timestamp", int(time.time()) * 1000) // 1000
        except Exception:
            return int(time.time())
    
    def _get_sequence_number(self, address: str) -> int:
        """获取序列号"""
        try:
            account = self.rpc_client.getAccount(address)
            return int(account.get("sequence_number", "0"))
        except Exception:
            return 0
    
    def build_entry_function_payload(
        self,
        module_address: str,
        module_name: str,
        function_name: str,
        type_arguments: List[str] = None,
        arguments: List[Any] = None
    ) -> Dict:
        """
        构建 Entry Function Payload
        
        Args:
            module_address: 模块地址 (如 0x1)
            module_name: 模块名称 (如 coin)
            function_name: 函数名称 (如 transfer)
            type_arguments: 类型参数 (如 ["0x1::aptos_coin::AptosCoin"])
            arguments: 函数参数
        
        Returns:
            Payload 字典
        """
        return {
            "type": "entry_function_payload",
            "function": f"{module_address}::{module_name}::{function_name}",
            "type_arguments": type_arguments or [],
            "arguments": arguments or []
        }
    
    def build_coin_transfer_payload(
        self,
        to_address: str,
        amount: int,
        coin_type: str = AptosCoins.APT
    ) -> Dict:
        """
        构建 Coin 转账 Payload
        
        Args:
            to_address: 接收地址
            amount: 金额 (最小单位)
            coin_type: Coin 类型
        
        Returns:
            Payload 字典
        """
        return self.build_entry_function_payload(
            module_address="0x1",
            module_name="coin",
            function_name="transfer",
            type_arguments=[coin_type],
            arguments=[to_address, amount]
        )
    
    def build_swap_payload_liquidswap(
        self,
        token_in: str,
        token_out: str,
        amount_in: int,
        min_amount_out: int,
        is_stable: bool = False
    ) -> Dict:
        """
        构建 Liquidswap Swap Payload
        
        Args:
            token_in: 输入代币类型
            token_out: 输出代币类型
            amount_in: 输入金额
            min_amount_out: 最小输出金额
            is_stable: 是否为稳定币池
        
        Returns:
            Payload 字典
        """
        module = "stabilize" if is_stable else "curve"
        
        return self.build_entry_function_payload(
            module_address=SupportedAptosDEX.LIQUIDSWAP.contract_address,
            module_name=module,
            function_name="swap",
            type_arguments=[token_in, token_out],
            arguments=[
                amount_in,
                min_amount_out
            ]
        )
    
    def build_swap_payload_thala(
        self,
        token_in: str,
        token_out: str,
        amount_in: int,
        min_amount_out: int
    ) -> Dict:
        """
        构建 Thala Swap Payload
        
        Args:
            token_in: 输入代币类型
            token_out: 输出代币类型
            amount_in: 输入金额
            min_amount_out: 最小输出金额
        
        Returns:
            Payload 字典
        """
        return self.build_entry_function_payload(
            module_address=SupportedAptosDEX.THALA.contract_address,
            module_name="pool",
            function_name="swap",
            type_arguments=[token_in, token_out],
            arguments=[
                amount_in,
                min_amount_out
            ]
        )
    
    def build_add_liquidity_payload(
        self,
        token_x: str,
        token_y: str,
        amount_x: int,
        amount_y: int,
        is_stable: bool = False
    ) -> Dict:
        """
        构建添加流动性 Payload
        
        Args:
            token_x: 代币 X 类型
            token_y: 代币 Y 类型
            amount_x: 代币 X 金额
            amount_y: 代币 Y 金额
            is_stable: 是否为稳定币池
        
        Returns:
            Payload 字典
        """
        module = "stabilize" if is_stable else "curve"
        
        return self.build_entry_function_payload(
            module_address=SupportedAptosDEX.LIQUIDSWAP.contract_address,
            module_name=module,
            function_name="add_liquidity",
            type_arguments=[token_x, token_y],
            arguments=[
                amount_x,
                amount_y
            ]
        )
    
    def build_remove_liquidity_payload(
        self,
        token_x: str,
        token_y: str,
        amount: int,
        is_stable: bool = False
    ) -> Dict:
        """
        构建移除流动性 Payload
        
        Args:
            token_x: 代币 X 类型
            token_y: 代币 Y 类型
            amount: 流动性代币金额
            is_stable: 是否为稳定币池
        
        Returns:
            Payload 字典
        """
        module = "stabilize" if is_stable else "curve"
        
        return self.build_entry_function_payload(
            module_address=SupportedAptosDEX.LIQUIDSWAP.contract_address,
            module_name=module,
            function_name="remove_liquidity",
            type_arguments=[token_x, token_y],
            arguments=[amount]
        )
    
    def build_swap_payload(
        self,
        dex_name: str,
        token_in: str,
        token_out: str,
        amount_in: int,
        min_amount_out: int,
        **kwargs
    ) -> Dict:
        """
        构建 DEX Swap Payload (统一接口)
        
        Args:
            dex_name: DEX 名称 (liquidswap, thala)
            token_in: 输入代币类型
            token_out: 输出代币类型
            amount_in: 输入金额
            min_amount_out: 最小输出金额
            **kwargs: 其他参数
        
        Returns:
            Payload 字典
        """
        dex = dex_name.lower()
        
        if dex == "liquidswap":
            return self.build_swap_payload_liquidswap(
                token_in, token_out, amount_in, min_amount_out,
                is_stable=kwargs.get("is_stable", False)
            )
        elif dex == "thala":
            return self.build_swap_payload_thala(
                token_in, token_out, amount_in, min_amount_out
            )
        else:
            raise AptosTxBuilderError(f"Unsupported DEX: {dex_name}")
    
    def build_bridge_payload_wormhole(
        self,
        token: str,
        amount: int,
        recipient_chain: int,
        recipient: bytes
    ) -> Dict:
        """
        构建 Wormhole 跨链桥 Payload
        
        Args:
            token: 代币类型
            amount: 金额
            recipient_chain: 目标链 ID
            recipient: 目标链接收者地址 (bytes)
        
        Returns:
            Payload 字典
        """
        return self.build_entry_function_payload(
            module_address=WormholeAptosConfig.TOKEN_BRIDGE,
            module_name="transfer_tokens",
            function_name="transfer",
            type_arguments=[token],
            arguments=[
                amount,
                recipient_chain,
                base64.b64encode(recipient).decode(),
                0  # relayer fee
            ]
        )
    
    def build_transaction(
        self,
        payload: Dict,
        sender: Optional[str] = None,
        max_gas_amount: Optional[int] = None,
        gas_unit_price: Optional[int] = None,
        expiration_seconds: Optional[int] = None
    ) -> Dict:
        """
        构建完整交易
        
        Args:
            payload: 交易负载
            sender: 发送者地址
            max_gas_amount: 最大 Gas
            gas_unit_price: Gas 单价
            expiration_seconds: 过期时间 (秒)
        
        Returns:
            交易字典
        """
        sender = sender or self._sender
        if not sender:
            raise AptosTxBuilderError("Sender not set")
        
        # 获取序列号
        sequence_number = self._get_sequence_number(sender)
        
        # 获取账本时间
        ledger_timestamp = self._get_ledger_timestamp()
        
        # 计算过期时间
        expiry = ledger_timestamp + (expiration_seconds or self.tx_config.expiration_seconds)
        
        # Gas 配置
        max_gas = max_gas_amount or self.tx_config.max_gas_amount
        gas_price = gas_unit_price or self.tx_config.gas_unit_price
        
        return {
            "sender": sender,
            "sequence_number": str(sequence_number),
            "payload": payload,
            "max_gas_amount": str(max_gas),
            "gas_unit_price": str(gas_price),
            "expiration_timestamp_secs": str(expiry),
            "chain_id": self._get_chain_id()
        }
    
    def sign_transaction(
        self,
        transaction: Dict,
        keypair
    ) -> Dict:
        """
        签名交易
        
        Args:
            transaction: 交易字典
            keypair: 密钥对
        
        Returns:
            带签名的交易
        """
        # 这里需要 BCS 编码然后签名
        # 简化实现：直接使用 keypair 签名
        signature = keypair.sign(json.dumps(transaction, sort_keys=True).encode())
        
        return {
            "transaction": transaction,
            "signature": base64.b64encode(signature).decode(),
            "public_key": base64.b64encode(keypair.public_key_bytes).decode()
        }
    
    def submit_transaction(self, signed_txn: Dict) -> Dict:
        """
        提交交易
        
        Args:
            signed_txn: 已签名交易
        
        Returns:
            提交结果
        """
        return self.rpc_client.submit_transaction(signed_txn)
    
    def simulate_transaction(self, txn: Dict) -> Dict:
        """
        模拟交易
        
        Args:
            txn: 交易
        
        Returns:
            模拟结果
        """
        return self.rpc_client.simulate_transaction(txn)
    
    def estimate_gas(
        self,
        payload: Dict,
        sender: Optional[str] = None
    ) -> int:
        """
        估算 Gas
        
        Args:
            payload: 交易负载
            sender: 发送者地址
        
        Returns:
            预估 Gas 数量
        """
        sender = sender or self._sender
        if not sender:
            raise AptosTxBuilderError("Sender not set")
        
        # 构建模拟交易
        txn = self.build_transaction(payload, sender)
        
        try:
            # 模拟执行
            result = self.simulate_transaction(txn)
            
            # 获取 Gas 使用量
            if isinstance(result, list):
                result = result[0]
            
            gas_used = result.get("gas_used", "0")
            if isinstance(gas_used, str):
                gas_used = int(gas_used)
            
            # 增加 20% buffer
            return int(gas_used * 1.2)
        
        except Exception as e:
            logger.warning(f"Gas estimation failed, using default: {e}")
            return self.tx_config.max_gas_amount
    
    def get_quote(
        self,
        dex_name: str,
        token_in: str,
        token_out: str,
        amount_in: int,
        **kwargs
    ) -> Optional[SwapQuote]:
        """
        获取 Swap 报价 (需要外部价格 API)
        
        Args:
            dex_name: DEX 名称
            token_in: 输入代币
            token_out: 输出代币
            amount_in: 输入金额
        
        Returns:
            SwapQuote 或 None
        """
        # 这里需要调用 DEX API 获取报价
        # 简化实现：返回模拟数据
        return SwapQuote(
            dex_name=dex_name,
            amount_in=amount_in,
            amount_out=amount_in,  # 需要实际计算
            amount_out_min=int(amount_in * 0.995),  # 假设 0.5% 滑点
            price_impact_bps=10,
            pool_address="",
            gas_estimate=5000,
            route=[token_in, token_out],
            fees={"network_fee": 5000, "dex_fee": int(amount_in * 0.003)}
        )


# ============================================
# 便捷函数
# ============================================

def build_aptos_swap_transaction(
    rpc_url: str,
    sender: str,
    keypair,
    dex_name: str,
    token_in: str,
    token_out: str,
    amount_in: int,
    slippage_bps: int = 50,
    gas_unit_price: Optional[int] = None
) -> Dict:
    """
    便捷函数：构建 Aptos Swap 交易
    
    Args:
        rpc_url: RPC URL
        sender: 发送者地址
        keypair: 密钥对
        dex_name: DEX 名称
        token_in: 输入代币
        token_out: 输出代币
        amount_in: 输入金额
        slippage_bps: 滑点容忍
        gas_unit_price: Gas 单价
    
    Returns:
        已签名的交易
    """
    builder = AptosTransactionBuilder(rpc_url=rpc_url)
    builder.set_sender(sender, keypair)
    
    # 计算最小输出
    amount_out_min = int(amount_in * (1 - slippage_bps / 10000))
    
    # 构建 Payload
    payload = builder.build_swap_payload(
        dex_name=dex_name,
        token_in=token_in,
        token_out=token_out,
        amount_in=amount_in,
        min_amount_out=amount_out_min
    )
    
    # 构建交易
    txn = builder.build_transaction(
        payload=payload,
        sender=sender,
        gas_unit_price=gas_unit_price
    )
    
    # 签名
    signed_txn = builder.sign_transaction(txn, keypair)
    
    return signed_txn
