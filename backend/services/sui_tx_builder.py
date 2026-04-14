"""
Sui 交易构建模块

功能：
- 构建 Move Call 交易
- DEX Swap 交易构建 (Cetus/Aftermath/FlowX/Turbos)
- 跨链桥接交易 (Wormhole)
- Gas 预算计算
- 交易序列化

Sui 交易特点：
- 使用 BCS 编码序列化交易
- 每个交易包含多个 Move Call
- Gas 预算基于执行步骤
"""

import base64
import binascii
import json
import logging
import struct
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any, Union
from enum import Enum
import httpx

import sys
import os as _os
_backend_dir = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from config.sui_dex import (
    SuiRPCConfig,
    SuiTxConfig,
    SuiCoins,
    SupportedDEX,
    WormholeSuiConfig,
    LayerZeroSuiConfig,
    SuiConfig,
    format_sui_amount,
    parse_sui_amount,
)

logger = logging.getLogger(__name__)


# ============================================
# 错误定义
# ============================================

class SuiTxBuilderError(Exception):
    """Sui 交易构建错误"""
    pass


class InvalidSwapParamsError(SuiTxBuilderError):
    """无效的 Swap 参数"""
    pass


# ============================================
# 枚举和常量
# ============================================

class TransactionKind(Enum):
    """交易类型"""
    PROGRAMMABLE = "Programmable"
    SYSTEM = "System"


@dataclass
class MoveCall:
    """Move Call 交易单元"""
    package: str                        # Move 包地址
    module: str                          # 模块名称
    function: str                        # 函数名称
    type_arguments: List[str] = field(default_factory=list)  # 类型参数
    arguments: List[Any] = field(default_factory=list)         # 函数参数
    
    def to_dict(self) -> Dict:
        return {
            "package": self.package,
            "module": self.module,
            "function": self.function,
            "type_arguments": self.type_arguments,
            "arguments": self.arguments
        }


@dataclass
class SwapParams:
    """Swap 参数"""
    token_in: str                        # 输入代币类型
    token_out: str                       # 输出代币类型
    amount_in: int                       # 输入金额
    amount_out_min: int                  # 最小输出金额
    slippage_bps: int = 50               # 滑点容忍 (basis points)
    
    def __post_init__(self):
        if self.amount_in <= 0:
            raise InvalidSwapParamsError("amount_in must be positive")
        if self.slippage_bps < 0 or self.slippage_bps > 10000:
            raise InvalidSwapParamsError("slippage_bps must be between 0 and 10000")


@dataclass
class SwapQuote:
    """Swap 报价"""
    dex_name: str                        # DEX 名称
    amount_in: int                       # 输入金额
    amount_out: int                      # 输出金额
    amount_out_min: int                  # 最小输出金额
    price_impact_bps: int               # 价格影响 (basis points)
    pool_address: str                   # 池子地址
    gas_estimate: int                   # 预估 Gas
    route: List[str] = field(default_factory=list)  # 路由路径
    
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
            "route": self.route
        }


# ============================================
# BCS 编码工具
# ============================================

class BcsCodec:
    """BCS (Binary Canonical Serialization) 编解码器"""
    
    @staticmethod
    def encode_address(address: str) -> bytes:
        """编码 Sui 地址 (32 字节)"""
        if address.startswith("0x"):
            address = address[2:]
        return bytes.fromhex(address.zfill(64))
    
    @staticmethod
    def encode_u64(value: int) -> bytes:
        """编码 u64 (LEB128)"""
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
        """编码 u128 (LEB128)"""
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
    def encode_string(s: str) -> bytes:
        """编码字符串"""
        return BcsCodec.encode_u64(len(s)) + s.encode('utf-8')
    
    @staticmethod
    def encode_vector(values: List[bytes]) -> bytes:
        """编码向量"""
        return BcsCodec.encode_u64(len(values)) + b''.join(values)


# ============================================
# RPC 客户端
# ============================================

class SuiTxRpcClient:
    """用于交易构建的 RPC 客户端"""
    
    def __init__(
        self,
        rpc_url: Optional[str] = None,
        timeout: int = SuiRPCConfig.REQUEST_TIMEOUT
    ):
        self.rpc_url = rpc_url or SuiConfig.get_rpc()
        self.timeout = timeout
        self._client = httpx.Client(timeout=timeout)
    
    def close(self):
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
        result = response.json()
        
        if "error" in result:
            raise SuiTxBuilderError(f"RPC Error: {result['error']}")
        
        return result.get("result", {})
    
    def get_object(self, object_id: str) -> Dict:
        """获取对象信息"""
        return self._post("sui_getObject", [object_id])
    
    def get_all_coins(self, address: str) -> Dict:
        """获取所有 Coin 对象"""
        return self._post("suix_getCoins", [address, None, True])
    
    def get_reference_gas_price(self) -> int:
        """获取参考 Gas 价格"""
        return self._post("suix_getReferenceGasPrice", [])
    
    def get_latest_epoch(self) -> Dict:
        """获取最新 Epoch"""
        return self._post("sui_getLatestEpoch", [])
    
    def dev_inspect_transaction(
        self,
        sender: str,
        tx_bytes: str
    ) -> Dict:
        """模拟交易"""
        return self._post("sui_devInspectTransactionBlock", [
            sender,
            tx_bytes,
            None,
            None
        ])


# ============================================
# Sui 交易构建器
# ============================================

class SuiTransactionBuilder:
    """
    Sui 交易构建器
    
    支持：
    - Programmable Transaction Blocks (PTB)
    - Cetus DEX Swap
    - Aftermath DEX Swap
    - FlowX DEX Swap
    - Turbos DEX Swap
    - Wormhole 跨链
    """
    
    def __init__(
        self,
        rpc_url: Optional[str] = None,
        tx_config: Optional[SuiTxConfig] = None
    ):
        self.rpc_url = rpc_url or SuiConfig.get_rpc()
        self.tx_config = tx_config or SuiConfig.get_tx_config()
        self._client: Optional[SuiTxRpcClient] = None
    
    @property
    def client(self) -> SuiTxRpcClient:
        """获取 RPC 客户端"""
        if self._client is None:
            self._client = SuiTxRpcClient(self.rpc_url)
        return self._client
    
    def build_transfer_sui(
        self,
        sender: str,
        recipient: str,
        amount: int,
        gas_budget: Optional[int] = None
    ) -> List[Dict]:
        """
        构建 SUI 转账交易
        
        Args:
            sender: 发送者地址
            recipient: 接收者地址
            amount: 金额 (MIST)
            gas_budget: Gas 预算
        
        Returns:
            交易构建命令列表
        """
        commands = [
            {
                "kind": "TransferObjects",
                "objects": ["$to_address"],
                "recipient": recipient
            }
        ]
        
        return self._build_transaction(
            sender=sender,
            commands=commands,
            gas_budget=gas_budget or self.tx_config.gas_budget,
            coins=[],  # 将添加 SplitCoins
            split_amounts=[amount]
        )
    
    def build_transfer_object(
        self,
        sender: str,
        recipient: str,
        object_id: str,
        gas_budget: Optional[int] = None
    ) -> List[Dict]:
        """
        构建对象转账交易
        
        Args:
            sender: 发送者地址
            recipient: 接收者地址
            object_id: 对象 ID
            gas_budget: Gas 预算
        
        Returns:
            交易构建命令列表
        """
        commands = [
            {
                "kind": "TransferObjects",
                "objects": [object_id],
                "recipient": recipient
            }
        ]
        
        return self._build_transaction(
            sender=sender,
            commands=commands,
            gas_budget=gas_budget or self.tx_config.gas_budget
        )
    
    # ============================================
    # Cetus DEX Swap
    # ============================================
    
    def build_cetus_swap(
        self,
        sender: str,
        pool_address: str,
        coin_in_type: str,
        coin_out_type: str,
        amount_in: int,
        amount_out_min: int,
        gas_budget: Optional[int] = None
    ) -> Dict:
        """
        构建 Cetus Swap 交易
        
        Args:
            sender: 发送者地址
            pool_address: 池子地址
            coin_in_type: 输入代币类型
            coin_out_type: 输出代币类型
            amount_in: 输入金额
            amount_out_min: 最小输出金额
            gas_budget: Gas 预算
        
        Returns:
            交易数据
        """
        dex = SupportedDEX.CETUS
        
        # 构建 Move Call
        move_call = MoveCall(
            package=dex.package_id,
            module="clmm",  # Concentrated Liquidity Module
            function="swap",
            type_arguments=[coin_in_type, coin_out_type],
            arguments=[
                pool_address,      # pool
                sender,            # sender
                "0",               # coin_type (clock object)
                amount_in,         # amount_in
                amount_out_min,    # min_amount_out
                True               # static_gas_price
            ]
        )
        
        return self._build_programmable_tx(
            sender=sender,
            move_calls=[move_call],
            gas_budget=gas_budget
        )
    
    def build_cetus_swap_with_coin(
        self,
        sender: str,
        pool_address: str,
        coin_in_object: str,
        coin_in_type: str,
        coin_out_type: str,
        amount_in: int,
        amount_out_min: int,
        gas_budget: Optional[int] = None
    ) -> Dict:
        """
        使用特定 Coin 对象构建 Cetus Swap
        
        Args:
            sender: 发送者地址
            pool_address: 池子地址
            coin_in_object: 输入 Coin 对象 ID
            coin_in_type: 输入代币类型
            coin_out_type: 输出代币类型
            amount_in: 输入金额
            amount_out_min: 最小输出金额
            gas_budget: Gas 预算
        
        Returns:
            交易数据
        """
        dex = SupportedDEX.CETUS
        
        move_call = MoveCall(
            package=dex.package_id,
            module="clmm",
            function="swap",
            type_arguments=[coin_in_type, coin_out_type],
            arguments=[
                pool_address,
                sender,
                "0",
                coin_in_object,
                amount_in,
                amount_out_min,
                True
            ]
        )
        
        return self._build_programmable_tx(
            sender=sender,
            move_calls=[move_call],
            gas_budget=gas_budget
        )
    
    # ============================================
    # Aftermath DEX Swap
    # ============================================
    
    def build_aftermath_swap(
        self,
        sender: str,
        pool_address: str,
        coin_in_type: str,
        coin_out_type: str,
        amount_in: int,
        amount_out_min: int,
        gas_budget: Optional[int] = None
    ) -> Dict:
        """
        构建 Aftermath Swap 交易
        
        Args:
            sender: 发送者地址
            pool_address: 池子地址
            coin_in_type: 输入代币类型
            coin_out_type: 输出代币类型
            amount_in: 输入金额
            amount_out_min: 最小输出金额
            gas_budget: Gas 预算
        
        Returns:
            交易数据
        """
        dex = SupportedDEX.AFTERMATH
        
        move_call = MoveCall(
            package=dex.package_id,
            module="router",
            function="swap",
            type_arguments=[coin_in_type, coin_out_type],
            arguments=[
                pool_address,
                sender,
                amount_in,
                amount_out_min
            ]
        )
        
        return self._build_programmable_tx(
            sender=sender,
            move_calls=[move_call],
            gas_budget=gas_budget
        )
    
    # ============================================
    # FlowX DEX Swap
    # ============================================
    
    def build_flowx_swap(
        self,
        sender: str,
        pool_address: str,
        coin_in_type: str,
        coin_out_type: str,
        amount_in: int,
        amount_out_min: int,
        gas_budget: Optional[int] = None
    ) -> Dict:
        """
        构建 FlowX Swap 交易
        """
        dex = SupportedDEX.FLOWX
        
        move_call = MoveCall(
            package=dex.package_id,
            module="router",
            function="swap_exact_in",
            type_arguments=[coin_in_type, coin_out_type],
            arguments=[
                pool_address,
                sender,
                amount_in,
                amount_out_min
            ]
        )
        
        return self._build_programmable_tx(
            sender=sender,
            move_calls=[move_call],
            gas_budget=gas_budget
        )
    
    # ============================================
    # Turbos DEX Swap
    # ============================================
    
    def build_turbos_swap(
        self,
        sender: str,
        pool_address: str,
        coin_in_type: str,
        coin_out_type: str,
        amount_in: int,
        amount_out_min: int,
        gas_budget: Optional[int] = None
    ) -> Dict:
        """
        构建 Turbos Swap 交易
        """
        dex = SupportedDEX.TURBOS
        
        move_call = MoveCall(
            package=dex.package_id,
            module="router",
            function="swap",
            type_arguments=[coin_in_type, coin_out_type],
            arguments=[
                pool_address,
                sender,
                amount_in,
                amount_out_min
            ]
        )
        
        return self._build_programmable_tx(
            sender=sender,
            move_calls=[move_call],
            gas_budget=gas_budget
        )
    
    # ============================================
    # Wormhole 跨链桥
    # ============================================
    
    def build_wormhole_transfer(
        self,
        sender: str,
        token_type: str,
        amount: int,
        target_chain: int,  # Wormhole Chain ID
        recipient: bytes,  # Target address bytes
        gas_budget: Optional[int] = None
    ) -> Dict:
        """
        构建 Wormhole 跨链转账交易
        
        Args:
            sender: 发送者地址
            token_type: 代币类型
            amount: 转账金额
            target_chain: Wormhole 目标链 ID
            recipient: 目标链接收地址
            gas_budget: Gas 预算
        
        Returns:
            交易数据
        """
        bridge = WormholeSuiConfig.CORE_BRIDGE
        
        # Transfer tokens via Wormhole
        move_call = MoveCall(
            package=bridge,
            module="wormhole",
            function="transfer_tokens",
            type_arguments=[token_type],
            arguments=[
                amount,
                target_chain,
                base64.b64encode(recipient).decode(),
                0  # relayer fee (0 for no relayer)
            ]
        )
        
        return self._build_programmable_tx(
            sender=sender,
            move_calls=[move_call],
            gas_budget=gas_budget
        )
    
    # ============================================
    # 底层交易构建
    # ============================================
    
    def _build_programmable_tx(
        self,
        sender: str,
        move_calls: List[MoveCall],
        gas_budget: Optional[int] = None,
        gas_price: Optional[int] = None
    ) -> Dict:
        """
        构建可编程交易块 (PTB)
        
        Args:
            sender: 发送者地址
            move_calls: Move Call 列表
            gas_budget: Gas 预算
            gas_price: Gas 价格
        
        Returns:
            交易数据字典
        """
        if gas_price is None:
            gas_price = self.tx_config.gas_price
        
        if gas_budget is None:
            gas_budget = self.tx_config.gas_budget
        
        return {
            "sender": sender,
            "gas_config": {
                "budget": str(gas_budget),
                "price": str(gas_price),
                "payment": []  # 将由节点自动选择
            },
            "kind": {
                "ProgrammableTransaction": {
                    "inputs": [],
                    "transactions": [mc.to_dict() for mc in move_calls]
                }
            }
        }
    
    def _build_transaction(
        self,
        sender: str,
        commands: List[Dict],
        gas_budget: int,
        coins: List[str] = None,
        split_amounts: List[int] = None
    ) -> Dict:
        """构建基础交易"""
        return {
            "sender": sender,
            "gas_config": {
                "budget": str(gas_budget),
                "price": str(self.tx_config.gas_price),
                "payment": coins or []
            },
            "kind": {
                "ProgrammableTransaction": {
                    "inputs": [],
                    "transactions": commands
                }
            }
        }
    
    # ============================================
    # 交易序列化
    # ============================================
    
    def serialize_transaction(self, tx_data: Dict) -> str:
        """
        序列化交易为字节 (Base64)
        
        Args:
            tx_data: 交易数据
        
        Returns:
            Base64 编码的交易字节
        """
        # 在实际实现中，需要使用 BCS 编码
        # 这里返回 JSON 表示，由 RPC 节点处理序列化
        tx_json = json.dumps(tx_data)
        return base64.b64encode(tx_json.encode()).decode()
    
    # ============================================
    # Gas 估算
    # ============================================
    
    def estimate_gas(
        self,
        sender: str,
        tx_data: Dict
    ) -> Tuple[int, int]:
        """
        估算 Gas 预算和价格
        
        Args:
            sender: 发送者地址
            tx_data: 交易数据
        
        Returns:
            (gas_budget, gas_price)
        """
        try:
            # 获取参考 Gas 价格
            gas_price = self.client.get_reference_gas_price()
            
            # 模拟交易获取 Gas 使用量
            tx_bytes = self.serialize_transaction(tx_data)
            result = self.client.dev_inspect_transaction(sender, tx_bytes)
            
            if "effects" in result:
                gas_used = int(result["effects"].get("gasUsed", "0"))
            else:
                gas_used = self.tx_config.gas_budget
            
            # 添加 20% buffer
            gas_budget = int(gas_used * 1.2)
            
            # 确保不超过最大限制
            gas_budget = min(gas_budget, self.tx_config.max_gas_budget)
            gas_budget = max(gas_budget, self.tx_config.gas_budget)
            
            return gas_budget, gas_price
        except Exception as e:
            logger.warning(f"Gas estimation failed, using defaults: {e}")
            return self.tx_config.gas_budget, self.tx_config.gas_price
    
    # ============================================
    # DEX 报价查询 (辅助方法)
    # ============================================
    
    def get_swap_quote(
        self,
        dex_name: str,
        pool_address: str,
        coin_in_type: str,
        coin_out_type: str,
        amount_in: int
    ) -> Optional[SwapQuote]:
        """
        获取 Swap 报价 (通过 RPC 查询池子状态)
        
        注意: 实际报价需要通过 DEX 的 SDK 或合约查询
        这里提供框架，实际实现可能需要额外 API
        
        Args:
            dex_name: DEX 名称
            pool_address: 池子地址
            coin_in_type: 输入代币类型
            coin_out_type: 输出代币类型
            amount_in: 输入金额
        
        Returns:
            SwapQuote 或 None
        """
        try:
            # 获取池子信息
            pool_info = self.client.get_object(pool_address)
            
            if not pool_info.get("status") == "Exists":
                return None
            
            # 简化计算 (实际需要根据池子类型计算)
            # 这里返回估算值
            return SwapQuote(
                dex_name=dex_name,
                amount_in=amount_in,
                amount_out=int(amount_in * 0.997),  # 假设 0.3% 手续费
                amount_out_min=int(amount_in * 0.994),
                price_impact_bps=10,
                pool_address=pool_address,
                gas_estimate=self.tx_config.gas_budget
            )
        except Exception as e:
            logger.error(f"Failed to get swap quote: {e}")
            return None
    
    def close(self):
        """关闭资源"""
        if self._client:
            self._client.close()


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
    """
    便捷函数: 构建 Swap 交易
    
    Args:
        sender: 发送者地址
        dex_name: DEX 名称 (cetus, aftermath, flowx, turbos)
        pool_address: 池子地址
        token_in: 输入代币类型
        token_out: 输出代币类型
        amount_in: 输入金额
        slippage_bps: 滑点容忍
        rpc_url: RPC URL
    
    Returns:
        交易数据
    """
    builder = SuiTransactionBuilder(rpc_url=rpc_url)
    
    # 计算最小输出
    amount_out_min = int(amount_in * 0.997 * (10000 - slippage_bps) / 10000)
    
    dex_name = dex_name.lower()
    
    if dex_name == "cetus":
        return builder.build_cetus_swap(
            sender, pool_address, token_in, token_out, amount_in, amount_out_min
        )
    elif dex_name == "aftermath":
        return builder.build_aftermath_swap(
            sender, pool_address, token_in, token_out, amount_in, amount_out_min
        )
    elif dex_name == "flowx":
        return builder.build_flowx_swap(
            sender, pool_address, token_in, token_out, amount_in, amount_out_min
        )
    elif dex_name == "turbos":
        return builder.build_turbos_swap(
            sender, pool_address, token_in, token_out, amount_in, amount_out_min
        )
    else:
        raise SuiTxBuilderError(f"Unknown DEX: {dex_name}")
