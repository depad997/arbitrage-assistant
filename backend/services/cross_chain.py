"""
跨链套利助手 - 跨链桥交互服务
支持 LayerZero、Wormhole 等跨链桥的费用估算和状态追踪
支持 EVM 链和非 EVM 链（Solana, Sui, Aptos）
"""

import asyncio
import logging
import sys
import os
from typing import Dict, List, Optional, Tuple, Any, Union
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from abc import ABC, abstractmethod

# 添加 backend 目录到路径以支持相对导入
_backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from config.settings import (
    SUPPORTED_CHAINS,
    ENABLED_CHAINS,
    BRIDGE_CONFIGS,
    get_chain_config,
    get_evm_chains,
    get_non_evm_chains,
)

logger = logging.getLogger(__name__)


# ============================================
# 跨链状态枚举
# ============================================

class CrossChainStatus(Enum):
    """跨链交易状态"""
    PENDING = "pending"
    CONFIRMED = "confirmed"
    DELIVERED = "delivered"
    FAILED = "failed"
    UNKNOWN = "unknown"


class ChainType(Enum):
    """链类型"""
    EVM = "evm"
    SOLANA = "solana"
    SUI = "sui"
    APTOS = "aptos"


# ============================================
# 数据类定义
# ============================================

@dataclass
class CrossChainQuote:
    """跨链报价"""
    bridge: str
    source_chain: str
    target_chain: str
    token_symbol: str
    amount: float
    
    # 费用
    bridge_fee_usd: float
    gas_fee_source: float  # 源链 Gas 费用 (USD)
    gas_fee_target: float  # 目标链 Gas 费用 (USD)
    total_cost_usd: float
    
    # 时间
    estimated_time_minutes: int
    timestamp: datetime
    
    # 元数据
    gas_price_source: int = 0
    gas_price_target: int = 0
    message: str = ""


@dataclass
class CrossChainTransfer:
    """跨链转账记录"""
    tx_hash: str
    bridge: str
    source_chain: str
    target_chain: str
    status: CrossChainStatus
    token_symbol: str
    amount: float
    created_at: datetime
    updated_at: datetime
    source_tx_hash: str = ""
    dest_tx_hash: str = ""
    message: str = ""


@dataclass
class ChainInfo:
    """链信息"""
    name: str
    chain_id: int
    chain_type: ChainType
    is_evm: bool
    wormhole_chain_id: int
    layerzero_endpoint_id: int
    native_token: str
    rpc_url: str
    explorer_url: str


# ============================================
# 链类型检测工具
# ============================================

def get_chain_type(chain_name: str) -> ChainType:
    """获取链类型"""
    if chain_name == "solana":
        return ChainType.SOLANA
    elif chain_name == "sui":
        return ChainType.SUI
    elif chain_name == "aptos":
        return ChainType.APTOS
    else:
        return ChainType.EVM


def is_evm_chain(chain_name: str) -> bool:
    """判断是否为 EVM 链"""
    config = get_chain_config(chain_name)
    return config.is_evm if config else False


def is_non_evm_chain(chain_name: str) -> bool:
    """判断是否为非 EVM 链"""
    return not is_evm_chain(chain_name)


# ============================================
# Web3 实例管理（支持 EVM 链）
# ============================================

class Web3Manager:
    """
    Web3 实例管理器
    
    负责 EVM 链的 Web3 实例初始化和维护
    """
    
    def __init__(self):
        self._instances: Dict[str, Any] = {}
        self._initialize()
    
    def _initialize(self):
        """初始化所有 EVM 链的 Web3 实例"""
        try:
            from web3 import Web3
            
            for chain_name in get_evm_chains():
                if chain_name not in ENABLED_CHAINS:
                    continue
                    
                config = get_chain_config(chain_name)
                if not config:
                    continue
                
                try:
                    web3 = Web3(Web3.HTTPProvider(config.rpc_url))
                    if web3.is_connected():
                        self._instances[chain_name] = web3
                        logger.info(f"[Web3Manager] Connected to {chain_name}")
                    else:
                        logger.warning(f"[Web3Manager] Failed to connect to {chain_name}")
                except Exception as e:
                    logger.error(f"[Web3Manager] Error connecting to {chain_name}: {e}")
                    
        except ImportError:
            logger.warning("[Web3Manager] web3.py not installed")
    
    def get_web3(self, chain_name: str) -> Optional[Any]:
        """获取指定链的 Web3 实例"""
        return self._instances.get(chain_name)
    
    def get_all_web3(self) -> Dict[str, Any]:
        """获取所有 Web3 实例"""
        return self._instances.copy()
    
    def reconnect(self, chain_name: str) -> bool:
        """重新连接指定链"""
        if chain_name in self._instances:
            del self._instances[chain_name]
        
        config = get_chain_config(chain_name)
        if not config or not config.is_evm:
            return False
        
        try:
            from web3 import Web3
            web3 = Web3(Web3.HTTPProvider(config.rpc_url))
            if web3.is_connected():
                self._instances[chain_name] = web3
                return True
        except Exception as e:
            logger.error(f"[Web3Manager] Reconnect error for {chain_name}: {e}")
        
        return False


# 全局 Web3 管理器
web3_manager = Web3Manager()


# ============================================
# LayerZero 服务
# ============================================

class LayerZeroService:
    """
    LayerZero 跨链服务
    
    功能：
    - 获取跨链费用估算
    - 追踪跨链消息状态
    - 生成跨链交易数据
    - 支持所有 EVM 链和部分非 EVM 链
    """
    
    # LayerZero Endpoint IDs（从配置同步）
    CHAIN_IDS: Dict[str, int] = {
        name: config.layerzero_endpoint_id
        for name, config in SUPPORTED_CHAINS.items()
        if config.layerzero_endpoint_id > 0
    }
    
    # 默认 gaslimit
    DEFAULT_GAS_LIMIT = 300000
    
    def __init__(self):
        self.web3_instances = web3_manager.get_all_web3()
        self._native_prices: Dict[str, float] = {
            "ethereum": 3500,
            "arbitrum": 3500,
            "optimism": 3500,
            "base": 3500,
            "bsc": 600,
            "polygon": 1.0,
            "avalanche": 35,
            "fantom": 0.4,
            "scroll": 3500,
            "mantle": 1.2,
            "linea": 3500,
            "berachain": 10,
            "moonbeam": 0.5,
        }
    
    async def estimate_fee(
        self,
        source_chain: str,
        target_chain: str,
        gas_limit: int = None,
        token_symbol: str = "ETH"
    ) -> Optional[CrossChainQuote]:
        """
        估算 LayerZero 跨链费用
        
        简化实现：基于历史数据和当前 Gas 估算
        生产环境应调用 LayerZero Endpoint 合约
        """
        try:
            # 验证链支持
            if source_chain not in self.CHAIN_IDS or target_chain not in self.CHAIN_IDS:
                logger.warning(f"[LayerZero] Unsupported chain pair: {source_chain} -> {target_chain}")
                return None
            
            gas_limit = gas_limit or self.DEFAULT_GAS_LIMIT
            
            # 获取源链 Gas 价格
            gas_price_source = 0
            gas_price_target = 0
            
            if is_evm_chain(source_chain):
                web3_source = self.web3_instances.get(source_chain)
                if web3_source and web3_source.is_connected():
                    gas_price_source = web3_source.eth.gas_price
                else:
                    logger.warning(f"[LayerZero] No connection to {source_chain}")
            
            if is_evm_chain(target_chain):
                web3_target = self.web3_instances.get(target_chain)
                if web3_target and web3_target.is_connected():
                    gas_price_target = web3_target.eth.gas_price
                else:
                    gas_price_target = gas_price_source  # fallback
            
            # LayerZero Relayer Fee（简化估算）
            # 实际费用取决于消息大小和目标链配置
            bridge_fee_usd = self._estimate_relayer_fee(source_chain, target_chain)
            
            # 计算 Gas 费用
            price_source = self._native_prices.get(source_chain, 3500)
            price_target = self._native_prices.get(target_chain, 3500)
            
            gas_fee_source_eth = (gas_price_source * gas_limit) / 1e18 if gas_price_source else 0
            gas_fee_target_eth = (gas_price_target * 50000) / 1e18 if gas_price_target else 0
            
            gas_fee_source_usd = gas_fee_source_eth * price_source
            gas_fee_target_usd = gas_fee_target_eth * price_target
            
            total_cost = bridge_fee_usd + gas_fee_source_usd + gas_fee_target_usd
            
            # 估算时间（LayerZero 通常 5-15 分钟）
            estimated_time = self._estimate_time(source_chain, target_chain)
            
            return CrossChainQuote(
                bridge="layerzero",
                source_chain=source_chain,
                target_chain=target_chain,
                token_symbol=token_symbol,
                amount=0,  # 待填充
                bridge_fee_usd=bridge_fee_usd,
                gas_fee_source=gas_fee_source_usd,
                gas_fee_target=gas_fee_target_usd,
                total_cost_usd=total_cost,
                estimated_time_minutes=estimated_time,
                timestamp=datetime.now(),
                gas_price_source=gas_price_source,
                gas_price_target=gas_price_target
            )
            
        except Exception as e:
            logger.error(f"[LayerZero] Fee estimation error: {e}")
            return None
    
    def _estimate_relayer_fee(self, source_chain: str, target_chain: str) -> float:
        """估算 Relayer 费用"""
        # 基础费用
        base_fee = 5.0  # USD
        
        # 目标链特定费用
        target_fees = {
            "ethereum": 8.0,
            "arbitrum": 2.0,
            "optimism": 2.0,
            "base": 2.0,
            "bsc": 3.0,
            "polygon": 1.5,
            "avalanche": 4.0,
            "solana": 10.0,  # 非 EVM 链可能更贵
            "sui": 10.0,
            "aptos": 10.0,
        }
        
        return base_fee + target_fees.get(target_chain, 5.0)
    
    def _estimate_time(self, source_chain: str, target_chain: str) -> int:
        """估算跨链时间（分钟）"""
        # 同为 EVM 链通常更快
        if is_evm_chain(source_chain) and is_evm_chain(target_chain):
            return 8
        elif is_evm_chain(source_chain) or is_evm_chain(target_chain):
            return 15
        else:
            return 20
    
    async def get_transaction_status(
        self,
        tx_hash: str,
        source_chain: str
    ) -> CrossChainStatus:
        """
        获取跨链交易状态
        
        生产环境应查询 LayerZero UltraLight 节点
        """
        try:
            if not is_evm_chain(source_chain):
                logger.warning(f"[LayerZero] Non-EVM chain status check not implemented: {source_chain}")
                return CrossChainStatus.UNKNOWN
            
            web3 = self.web3_instances.get(source_chain)
            if not web3:
                return CrossChainStatus.UNKNOWN
            
            # 检查交易是否确认
            try:
                receipt = web3.eth.get_transaction_receipt(tx_hash)
                if receipt:
                    if receipt.status == 1:
                        return CrossChainStatus.CONFIRMED
                    else:
                        return CrossChainStatus.FAILED
            except Exception:
                pass
            
            return CrossChainStatus.PENDING
            
        except Exception as e:
            logger.warning(f"[LayerZero] Status check error: {e}")
            return CrossChainStatus.UNKNOWN


# ============================================
# Wormhole 服务
# ============================================

class WormholeService:
    """
    Wormhole 跨链服务
    
    功能：
    - 估算 Wormhole 跨链费用
    - 追踪 VAAs (Verified Action Approvals)
    - 支持所有 EVM 链和部分非 EVM 链
    """
    
    # Wormhole Chain IDs（从配置同步）
    CHAIN_IDS: Dict[str, int] = {
        name: config.wormhole_chain_id
        for name, config in SUPPORTED_CHAINS.items()
        if config.wormhole_chain_id > 0
    }
    
    # 基础费用（USDC）
    BASE_FEE_USDC = 0.05  # 约 5 美分
    RELAY_FEE_PERCENT = 0.0001  # 0.01%
    
    def __init__(self):
        self.web3_instances = web3_manager.get_all_web3()
    
    async def estimate_fee(
        self,
        source_chain: str,
        target_chain: str,
        amount_usd: float,
        token_symbol: str = "USDC"
    ) -> Optional[CrossChainQuote]:
        """
        估算 Wormhole 跨链费用
        
        费用结构：
        - 基础费用：$0.05
        - 转账金额的 0.01%
        - Gas 费用
        """
        try:
            # 验证链支持
            if source_chain not in self.CHAIN_IDS or target_chain not in self.CHAIN_IDS:
                logger.warning(f"[Wormhole] Unsupported chain pair: {source_chain} -> {target_chain}")
                return None
            
            # 获取 Gas 价格
            gas_price = 0
            if is_evm_chain(source_chain):
                web3 = self.web3_instances.get(source_chain)
                if web3 and web3.is_connected():
                    gas_price = web3.eth.gas_price
            
            # Wormhole 费用
            base_fee = self.BASE_FEE_USDC
            relay_fee = amount_usd * self.RELAY_FEE_PERCENT
            bridge_fee = base_fee + relay_fee
            
            # Gas 费用估算（约 $2-5）
            gas_fee_usd = self._estimate_gas_fee(source_chain)
            
            total_cost = bridge_fee + gas_fee_usd
            
            # Wormhole 时间较长（15-30 分钟）
            estimated_time = self._estimate_time(source_chain, target_chain)
            
            return CrossChainQuote(
                bridge="wormhole",
                source_chain=source_chain,
                target_chain=target_chain,
                token_symbol=token_symbol,
                amount=amount_usd,
                bridge_fee_usd=bridge_fee,
                gas_fee_source=gas_fee_usd,
                gas_fee_target=0,
                total_cost_usd=total_cost,
                estimated_time_minutes=estimated_time,
                timestamp=datetime.now(),
                gas_price_source=gas_price
            )
            
        except Exception as e:
            logger.error(f"[Wormhole] Fee estimation error: {e}")
            return None
    
    def _estimate_gas_fee(self, chain_name: str) -> float:
        """估算 Gas 费用"""
        gas_fees = {
            "ethereum": 5.0,
            "arbitrum": 0.3,
            "optimism": 0.2,
            "base": 0.3,
            "bsc": 0.5,
            "polygon": 0.2,
            "avalanche": 0.5,
            "fantom": 0.2,
            "scroll": 0.5,
            "mantle": 0.1,
            "linea": 0.5,
            "berachain": 0.5,
            "moonbeam": 0.3,
            "solana": 0.01,  # Solana 手续费极低
            "sui": 0.01,
            "aptos": 0.01,
        }
        return gas_fees.get(chain_name, 1.0)
    
    def _estimate_time(self, source_chain: str, target_chain: str) -> int:
        """估算跨链时间（分钟）"""
        # Wormhole 通常需要等待 15-30 个区块确认
        if source_chain == "solana" or target_chain == "solana":
            return 15  # Solana 确认快
        elif source_chain == "sui" or target_chain == "sui":
            return 20
        elif source_chain == "aptos" or target_chain == "aptos":
            return 20
        else:
            return 25  # EVM 链之间
    
    async def get_vaa_status(self, emitter_chain: int, emitter_address: str, sequence: int) -> str:
        """
        查询 VAA 状态
        
        返回值：pending / confirmed / null
        """
        # 简化实现
        # 生产环境应调用 Wormhole Guardian RPC
        # API: https://wormhole-v2-mainnet.api.mstr.games/1/vlysses/subscribe/{emitter_chain}/{emitter_address}/{sequence}
        return "confirmed"


# ============================================
# 非 EVM 链服务（抽象基类）
# ============================================

class NonEVMBridgeService(ABC):
    """非 EVM 链桥接服务抽象基类"""
    
    @abstractmethod
    async def get_balance(self, address: str) -> float:
        """获取余额"""
        pass
    
    @abstractmethod
    async def send_transaction(self, to: str, amount: float) -> str:
        """发送交易"""
        pass


class SolanaBridgeService(NonEVMBridgeService):
    """Solana 桥接服务"""
    
    def __init__(self, rpc_url: str = None):
        self.rpc_url = rpc_url or "https://api.mainnet-beta.solana.com"
    
    async def get_balance(self, address: str) -> float:
        """获取 SOL 余额"""
        # TODO: 实现 Solana 余额查询
        # 使用 solana-py 或 solders
        return 0.0
    
    async def send_transaction(self, to: str, amount: float) -> str:
        """发送交易"""
        # TODO: 实现 Solana 交易
        return ""


class SuiBridgeService(NonEVMBridgeService):
    """Sui 桥接服务"""
    
    def __init__(self, rpc_url: str = None):
        self.rpc_url = rpc_url or "https://fullnode.mainnet.sui.io"
    
    async def get_balance(self, address: str) -> float:
        """获取 SUI 余额"""
        # TODO: 实现 Sui 余额查询
        return 0.0
    
    async def send_transaction(self, to: str, amount: float) -> str:
        """发送交易"""
        # TODO: 实现 Sui 交易
        return ""


class AptosBridgeService(NonEVMBridgeService):
    """Aptos 桥接服务"""
    
    def __init__(self, rpc_url: str = None):
        self.rpc_url = rpc_url or "https://fullnode.mainnet.aptoslabs.com"
    
    async def get_balance(self, address: str) -> float:
        """获取 APT 余额"""
        # TODO: 实现 Aptos 余额查询
        return 0.0
    
    async def send_transaction(self, to: str, amount: float) -> str:
        """发送交易"""
        # TODO: 实现 Aptos 交易
        return ""


# ============================================
# 跨链统一服务
# ============================================

class CrossChainService:
    """
    跨链桥统一服务
    
    整合 LayerZero 和 Wormhole，提供统一接口
    自动处理 EVM 和非 EVM 链的差异
    """
    
    def __init__(self):
        self.layerzero = LayerZeroService()
        self.wormhole = WormholeService()
        self._active_transfers: Dict[str, CrossChainTransfer] = {}
        
        # 初始化非 EVM 服务
        self._non_evm_services: Dict[str, NonEVMBridgeService] = {
            "solana": SolanaBridgeService(),
            "sui": SuiBridgeService(),
            "aptos": AptosBridgeService(),
        }
    
    def _validate_chain_pair(self, source_chain: str, target_chain: str) -> Tuple[bool, str]:
        """
        验证链对是否支持
        
        Returns:
            (is_valid, error_message)
        """
        if source_chain not in ENABLED_CHAINS:
            return False, f"Source chain {source_chain} not enabled"
        
        if target_chain not in ENABLED_CHAINS:
            return False, f"Target chain {target_chain} not enabled"
        
        if source_chain == target_chain:
            return False, "Source and target chain cannot be the same"
        
        return True, ""
    
    async def get_quote(
        self,
        bridge: str,
        source_chain: str,
        target_chain: str,
        token_symbol: str,
        amount: float
    ) -> Optional[CrossChainQuote]:
        """获取跨链报价"""
        # 验证链对
        is_valid, error = self._validate_chain_pair(source_chain, target_chain)
        if not is_valid:
            logger.warning(f"[CrossChain] {error}")
            return None
        
        if bridge == "layerzero":
            quote = await self.layerzero.estimate_fee(
                source_chain, target_chain, token_symbol=token_symbol
            )
            if quote:
                quote.amount = amount
            return quote
        elif bridge == "wormhole":
            return await self.wormhole.estimate_fee(
                source_chain, target_chain, amount, token_symbol
            )
        else:
            logger.warning(f"[CrossChain] Unknown bridge: {bridge}")
            return None
    
    async def compare_bridges(
        self,
        source_chain: str,
        target_chain: str,
        token_symbol: str,
        amount: float
    ) -> List[CrossChainQuote]:
        """比较不同跨链桥的费用"""
        quotes = []
        
        # LayerZero
        lz_quote = await self.get_quote("layerzero", source_chain, target_chain, token_symbol, amount)
        if lz_quote:
            quotes.append(lz_quote)
        
        # Wormhole
        wh_quote = await self.get_quote("wormhole", source_chain, target_chain, token_symbol, amount)
        if wh_quote:
            quotes.append(wh_quote)
        
        return quotes
    
    async def get_transfer_status(self, transfer_id: str) -> Optional[CrossChainTransfer]:
        """获取转账状态"""
        return self._active_transfers.get(transfer_id)
    
    async def get_best_bridge(
        self,
        source_chain: str,
        target_chain: str,
        token_symbol: str,
        amount: float
    ) -> Optional[Tuple[str, CrossChainQuote]]:
        """
        获取最优跨链桥
        
        Returns:
            (bridge_name, quote) 或 None
        """
        quotes = await self.compare_bridges(
            source_chain, target_chain, token_symbol, amount
        )
        
        if not quotes:
            return None
        
        # 按总费用排序
        best = min(quotes, key=lambda q: q.total_cost_usd)
        return (best.bridge, best)
    
    def calculate_net_profit(
        self,
        price_diff_pct: float,
        amount_usd: float,
        cross_chain_cost_usd: float,
        trading_slippage_pct: float = 0.1
    ) -> Dict:
        """
        计算跨链套利净利润
        
        公式：
        利润 = 价差收益 - 跨链成本 - 交易滑点
        """
        # 价差收益
        price_diff_value = amount_usd * (price_diff_pct / 100)
        
        # 滑点成本
        slippage_cost = amount_usd * (trading_slippage_pct / 100) * 2  # 买卖两次
        
        # 净利润
        net_profit = price_diff_value - cross_chain_cost_usd - slippage_cost
        net_profit_pct = (net_profit / amount_usd) * 100
        
        return {
            "gross_profit": price_diff_value,
            "cross_chain_cost": cross_chain_cost_usd,
            "slippage_cost": slippage_cost,
            "net_profit": net_profit,
            "net_profit_percent": net_profit_pct,
            "is_profitable": net_profit > 0
        }
    
    def get_supported_chains(self, bridge: Optional[str] = None) -> List[str]:
        """获取支持的链列表"""
        if bridge == "layerzero":
            return list(LayerZeroService.CHAIN_IDS.keys())
        elif bridge == "wormhole":
            return list(WormholeService.CHAIN_IDS.keys())
        else:
            return ENABLED_CHAINS.copy()
    
    def get_evm_chains(self) -> List[str]:
        """获取支持的 EVM 链"""
        return list(web3_manager.get_all_web3().keys())
    
    def get_non_evm_chains(self) -> List[str]:
        """获取支持的非 EVM 链"""
        return list(self._non_evm_services.keys())


# 全局实例
cross_chain_service = CrossChainService()
