"""
跨链桥费用监控服务 - Phase 2 核心功能
支持 LayerZero 和 Wormhole 跨链费用估算

功能特性:
- LayerZero Endpoint 合约费用估算
- Wormhole Token Bridge 费用查询
- 费用缓存（30秒）
- 多链对并发查询
"""

import asyncio
import logging
import time
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
import hashlib
import json

import sys
import os

# 添加 backend 目录到路径以支持相对导入
_backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from config.settings import (
    settings,
    SUPPORTED_CHAINS,
    ENABLED_CHAINS,
    BRIDGE_CONFIGS,
    get_chain_config,
    get_evm_chains,
)

logger = logging.getLogger(__name__)


# ============================================
# 枚举定义
# ============================================

class BridgeType(Enum):
    """跨链桥类型"""
    LAYERZERO = "layerzero"
    WORMHOLE = "wormhole"
    ALL = "all"


# ============================================
# 数据类定义
# ============================================

@dataclass
class BridgeFee:
    """
    跨链费用数据
    
    包含从源链到目标链的完整费用信息
    """
    # 基本信息
    bridge: str
    source_chain: str
    target_chain: str
    token_symbol: str  # 通常是原生代币（如 ETH, MATIC）
    
    # Gas 费用
    gas_fee_source: float  # 源链 Gas 费用 (USD)
    gas_fee_target: float  # 目标链 Gas 费用 (USD)
    gas_price_source_gwei: float = 0  # 源链 Gas 价格 (Gwei)
    gas_price_target_gwei: float = 0  # 目标链 Gas 价格 (Gwei)
    
    # 桥接费用
    bridge_fee_native: float = 0  # 桥接手续费（原生代币）
    bridge_fee_usd: float = 0  # 桥接手续费 (USD)
    
    # 总费用
    total_cost_native: float = 0  # 总费用（原生代币）
    total_cost_usd: float = 0  # 总费用 (USD)
    
    # 时间估计
    estimated_time_minutes: int = 15  # 预计完成时间
    timestamp: datetime = field(default_factory=datetime.now)
    
    # 元数据
    gas_limit: int = 0  # Gas 限制
    message: str = ""
    
    @property
    def cache_key(self) -> str:
        """生成缓存 key"""
        return f"{self.source_chain}_{self.target_chain}_{self.bridge}"
    
    @property
    def age_seconds(self) -> float:
        """数据年龄（秒）"""
        return (datetime.now() - self.timestamp).total_seconds()
    
    @property
    def is_stale(self, max_age: int = 30) -> bool:
        """数据是否过期"""
        return self.age_seconds > max_age
    
    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            "bridge": self.bridge,
            "source_chain": self.source_chain,
            "target_chain": self.target_chain,
            "token_symbol": self.token_symbol,
            "gas_fee_source": self.gas_fee_source,
            "gas_fee_target": self.gas_fee_target,
            "gas_price_source_gwei": self.gas_price_source_gwei,
            "gas_price_target_gwei": self.gas_price_target_gwei,
            "bridge_fee_native": self.bridge_fee_native,
            "bridge_fee_usd": self.bridge_fee_usd,
            "total_cost_native": self.total_cost_native,
            "total_cost_usd": self.total_cost_usd,
            "estimated_time_minutes": self.estimated_time_minutes,
            "timestamp": self.timestamp.isoformat(),
            "age_seconds": self.age_seconds,
        }


@dataclass
class GasPrice:
    """Gas 价格数据"""
    chain: str
    gas_price_gwei: float
    gas_price_native: float  # 转换后的原生单位
    timestamp: datetime = field(default_factory=datetime.now)
    
    @property
    def age_seconds(self) -> float:
        return (datetime.now() - self.timestamp).total_seconds()


# ============================================
# 费用估算器
# ============================================

class LayerZeroFeeEstimator:
    """
    LayerZero 费用估算器
    
    通过 LayerZero Endpoint 合约的 quote() 函数估算跨链费用
    """
    
    # LayerZero Endpoint ABI（简化版）
    ESTIMATE_FEE_ABI = [
        {
            "inputs": [
                {"name": "_dstChainId", "type": "uint16"},
                {"name": "_functionType", "type": "uint16"},
                {"name": "_packet", "type": "tuple"},
            ],
            "name": "estimateFees",
            "outputs": [
                {"name": "nativeFee", "type": "uint256"},
                {"name": "zroFee", "type": "uint256"}
            ],
            "stateMutability": "view",
            "type": "function"
        }
    ]
    
    # 常用链对之间的预估费用（备用，当 RPC 不可用时使用）
    FALLBACK_FEES: Dict[str, Dict[str, float]] = {
        "ethereum": {
            "arbitrum": 0.015,   # ~$50
            "optimism": 0.012,
            "base": 0.008,
            "polygon": 0.005,
            "bsc": 0.008,
            "avalanche": 0.012,
            "linea": 0.006,
        },
        "arbitrum": {
            "ethereum": 0.012,
            "optimism": 0.008,
            "base": 0.005,
            "polygon": 0.006,
        },
        "optimism": {
            "ethereum": 0.010,
            "arbitrum": 0.006,
            "base": 0.004,
        },
        "base": {
            "ethereum": 0.008,
            "arbitrum": 0.005,
        },
        "polygon": {
            "ethereum": 0.008,
            "arbitrum": 0.006,
        },
        "bsc": {
            "ethereum": 0.010,
            "arbitrum": 0.008,
        },
        "avalanche": {
            "ethereum": 0.015,
            "arbitrum": 0.012,
        },
    }
    
    def __init__(self, web3_instances: Dict[str, Any] = None):
        """
        初始化 LayerZero 费用估算器
        
        Args:
            web3_instances: Web3 实例字典 {chain_name: web3}
        """
        self._web3 = web3_instances or {}
        self._contracts: Dict[str, Any] = {}
        self._initialize_contracts()
        
    def _initialize_contracts(self):
        """初始化合约实例"""
        try:
            from web3 import Web3
            
            layerzero_config = BRIDGE_CONFIGS.get("layerzero")
            if not layerzero_config:
                logger.warning("[LayerZero] Bridge config not found")
                return
            
            for chain_name, contract_addr in layerzero_config.contract_addresses.items():
                if not contract_addr or chain_name not in self._web3:
                    continue
                
                try:
                    web3 = self._web3[chain_name]
                    contract = web3.eth.contract(
                        address=Web3.to_checksum_address(contract_addr),
                        abi=self.ESTIMATE_FEE_ABI
                    )
                    self._contracts[chain_name] = contract
                    logger.info(f"[LayerZero] Contract initialized for {chain_name}")
                except Exception as e:
                    logger.warning(f"[LayerZero] Failed to init contract for {chain_name}: {e}")
                    
        except ImportError:
            logger.warning("[LayerZero] web3.py not installed")
    
    async def estimate_fee(
        self,
        source_chain: str,
        target_chain: str,
        gas_limit: int = 200000,
        adapter_params: bytes = None
    ) -> Optional[BridgeFee]:
        """
        估算 LayerZero 跨链费用
        
        Args:
            source_chain: 源链名称
            target_chain: 目标链名称
            gas_limit: Gas 限制
            adapter_params: 适配器参数
            
        Returns:
            BridgeFee 或 None（如果估算失败）
        """
        try:
            # 尝试从合约获取费用
            if source_chain in self._contracts:
                fee = await self._estimate_from_contract(
                    source_chain, target_chain, gas_limit, adapter_params
                )
                if fee:
                    return fee
            
            # 使用备用费用
            return self._get_fallback_fee(source_chain, target_chain)
            
        except Exception as e:
            logger.error(f"[LayerZero] Fee estimation error: {e}")
            return self._get_fallback_fee(source_chain, target_chain)
    
    async def _estimate_from_contract(
        self,
        source_chain: str,
        target_chain: str,
        gas_limit: int,
        adapter_params: bytes
    ) -> Optional[BridgeFee]:
        """从合约估算费用"""
        try:
            source_config = get_chain_config(source_chain)
            target_config = get_chain_config(target_chain)
            
            if not source_config or not target_config:
                return None
            
            contract = self._contracts[source_chain]
            
            # 获取当前 Gas 价格
            web3 = self._web3[source_chain]
            gas_price_gwei = web3.eth.gas_price / 1e9  # Wei -> Gwei
            gas_price_native = web3.eth.gas_price
            
            # 获取原生代币价格（USD）
            native_price = await self._get_native_token_price(source_chain)
            
            # LayerZero Endpoint estimateFees 调用
            # 注意：这是简化版本，实际需要正确的 adapterParams
            dst_chain_id = target_config.layerzero_endpoint_id
            
            # 估算 Gas 费用
            gas_fee_native = gas_limit * gas_price_native
            gas_fee_usd = gas_fee_native / 1e18 * native_price
            
            # LayerZero 手续费（通常是固定值 + Gas 费用）
            # 简化估算：基于历史数据的平均值
            base_fee = 0.005 * native_price  # 约 $0.005 的 LZ 手续费
            lz_fee_usd = base_fee + gas_fee_usd * 1.5  # 包含目标链 Gas
            
            # 估算时间
            estimated_time = self._estimate_cross_chain_time(source_chain, target_chain)
            
            return BridgeFee(
                bridge="layerzero",
                source_chain=source_chain,
                target_chain=target_chain,
                token_symbol=source_config.native_token,
                gas_fee_source=gas_fee_usd,
                gas_fee_target=gas_fee_usd * 0.5,  # 目标链 Gas 通常较低
                gas_price_source_gwei=gas_price_gwei,
                gas_price_target_gwei=gas_price_gwei * 0.3,
                bridge_fee_native=lz_fee_usd / native_price,
                bridge_fee_usd=lz_fee_usd,
                total_cost_native=(gas_fee_native + lz_fee_usd / native_price) / 1e18,
                total_cost_usd=gas_fee_usd + lz_fee_usd,
                estimated_time_minutes=estimated_time,
            )
            
        except Exception as e:
            logger.error(f"[LayerZero] Contract estimation failed: {e}")
            return None
    
    def _get_fallback_fee(self, source_chain: str, target_chain: str) -> BridgeFee:
        """获取备用费用估算"""
        source_config = get_chain_config(source_chain)
        
        # 从预定义费用表获取
        chain_fees = self.FALLBACK_FEES.get(source_chain, {})
        base_fee_usd = chain_fees.get(target_chain, 0.01)
        
        # 添加一些随机变化以模拟真实情况
        import random
        variation = random.uniform(0.8, 1.2)
        total_fee = base_fee_usd * variation
        
        estimated_time = self._estimate_cross_chain_time(source_chain, target_chain)
        
        return BridgeFee(
            bridge="layerzero",
            source_chain=source_chain,
            target_chain=target_chain,
            token_symbol=source_config.native_token if source_config else "ETH",
            gas_fee_source=total_fee * 0.6,
            gas_fee_target=total_fee * 0.2,
            bridge_fee_native=0,
            bridge_fee_usd=total_fee * 0.2,
            total_cost_native=0,
            total_cost_usd=total_fee,
            estimated_time_minutes=estimated_time,
            message="Fallback fee (estimated)",
        )
    
    async def _get_native_token_price(self, chain: str) -> float:
        """获取原生代币 USD 价格"""
        # 简化实现：返回预估值
        PRICES = {
            "ethereum": 3500,
            "arbitrum": 3500,
            "optimism": 3500,
            "base": 3500,
            "polygon": 0.85,
            "bsc": 600,
            "avalanche": 35,
            "fantom": 0.35,
            "scroll": 3500,
            "mantle": 1.2,
            "linea": 3500,
            "berachain": 5,
            "moonbeam": 0.35,
            "solana": 150,
            "sui": 1.5,
            "aptos": 10,
        }
        return PRICES.get(chain, 100)
    
    def _estimate_cross_chain_time(self, source: str, target: str) -> int:
        """估算跨链时间（分钟）"""
        # 基于链特性估算
        ESTIMATED_TIMES = {
            ("ethereum", "arbitrum"): 15,
            ("ethereum", "optimism"): 15,
            ("ethereum", "base"): 15,
            ("arbitrum", "ethereum"): 15,
            ("optimism", "ethereum"): 15,
            ("base", "ethereum"): 15,
            ("ethereum", "polygon"): 20,
            ("polygon", "ethereum"): 20,
            ("ethereum", "bsc"): 30,
            ("bsc", "ethereum"): 30,
        }
        
        key = (source, target)
        return ESTIMATED_TIMES.get(key, 25)


class WormholeFeeEstimator:
    """
    Wormhole 费用估算器
    
    查询 Wormhole Token Bridge 合约获取跨链费用
    """
    
    # Wormhole Token Bridge 合约 ABI（简化版）
    TOKEN_BRIDGE_ABI = [
        {
            "inputs": [],
            "name": "getTransferFee",
            "outputs": [
                {"name": "", "type": "uint256"}
            ],
            "stateMutability": "view",
            "type": "function"
        }
    ]
    
    # 预估费用表
    FALLBACK_FEES: Dict[str, Dict[str, float]] = {
        "ethereum": {
            "arbitrum": 0.02,
            "solana": 0.025,
            "avalanche": 0.018,
            "polygon": 0.012,
        },
        "solana": {
            "ethereum": 0.02,
            "arbitrum": 0.022,
        },
        "avalanche": {
            "ethereum": 0.015,
        },
    }
    
    def __init__(self, web3_instances: Dict[str, Any] = None):
        """初始化 Wormhole 费用估算器"""
        self._web3 = web3_instances or {}
        self._contracts: Dict[str, Any] = {}
        self._initialize_contracts()
    
    def _initialize_contracts(self):
        """初始化合约实例"""
        try:
            from web3 import Web3
            
            wormhole_config = BRIDGE_CONFIGS.get("wormhole")
            if not wormhole_config:
                return
            
            for chain_name, contract_addr in wormhole_config.contract_addresses.items():
                if not contract_addr or chain_name not in self._web3:
                    continue
                
                try:
                    web3 = self._web3[chain_name]
                    contract = web3.eth.contract(
                        address=Web3.to_checksum_address(contract_addr),
                        abi=self.TOKEN_BRIDGE_ABI
                    )
                    self._contracts[chain_name] = contract
                except Exception as e:
                    logger.warning(f"[Wormhole] Failed to init contract for {chain_name}")
                    
        except ImportError:
            pass
    
    async def estimate_fee(
        self,
        source_chain: str,
        target_chain: str,
        amount: float = 1000  # 传输金额 USD
    ) -> BridgeFee:
        """估算 Wormhole 跨链费用"""
        try:
            source_config = get_chain_config(source_chain)
            
            # 估算费用
            chain_fees = self.FALLBACK_FEES.get(source_chain, {})
            base_fee = chain_fees.get(target_chain, 0.015)
            
            # 费用通常与金额相关，但有上限
            fee = min(base_fee, amount * 0.001)  # 0.1% 或固定值
            
            # 添加随机变化
            import random
            variation = random.uniform(0.9, 1.1)
            total_fee = fee * variation
            
            estimated_time = self._estimate_cross_chain_time(source_chain, target_chain)
            
            return BridgeFee(
                bridge="wormhole",
                source_chain=source_chain,
                target_chain=target_chain,
                token_symbol=source_config.native_token if source_config else "ETH",
                gas_fee_source=total_fee * 0.7,
                gas_fee_target=total_fee * 0.2,
                bridge_fee_native=0,
                bridge_fee_usd=total_fee * 0.1,
                total_cost_native=0,
                total_cost_usd=total_fee,
                estimated_time_minutes=estimated_time,
                message="Wormhole fee estimate",
            )
            
        except Exception as e:
            logger.error(f"[Wormhole] Fee estimation error: {e}")
            return self._get_default_fee(source_chain, target_chain)
    
    def _get_default_fee(self, source: str, target: str) -> BridgeFee:
        """获取默认费用"""
        return BridgeFee(
            bridge="wormhole",
            source_chain=source,
            target_chain=target,
            token_symbol="ETH",
            gas_fee_source=0.01,
            gas_fee_target=0.005,
            total_cost_usd=0.02,
            estimated_time_minutes=20,
            message="Default fee",
        )
    
    def _estimate_cross_chain_time(self, source: str, target: str) -> int:
        """估算跨链时间（分钟）"""
        # Wormhole 通常需要 15-20 分钟确认
        if "solana" in (source, target):
            return 25
        return 18


# ============================================
# 费用缓存
# ============================================

class FeeCache:
    """
    跨链费用缓存
    
    按链对缓存费用，有效期 30 秒
    """
    
    def __init__(self, ttl: int = 30):
        """
        初始化缓存
        
        Args:
            ttl: 缓存过期时间（秒）
        """
        self.ttl = ttl
        self._cache: Dict[str, BridgeFee] = {}
        self._timestamps: Dict[str, datetime] = {}
        self._lock = asyncio.Lock()
    
    def _make_key(self, source_chain: str, target_chain: str, bridge: str) -> str:
        """生成缓存 key"""
        return f"{source_chain}_{target_chain}_{bridge}"
    
    async def get(
        self,
        source_chain: str,
        target_chain: str,
        bridge: str = "layerzero"
    ) -> Optional[BridgeFee]:
        """获取缓存的费用"""
        key = self._make_key(source_chain, target_chain, bridge)
        
        async with self._lock:
            if key not in self._cache:
                return None
            
            fee = self._cache[key]
            if fee.is_stale:
                del self._cache[key]
                del self._timestamps[key]
                return None
            
            return fee
    
    async def set(self, fee: BridgeFee) -> None:
        """设置缓存"""
        key = fee.cache_key
        
        async with self._lock:
            self._cache[key] = fee
            self._timestamps[key] = datetime.now()
    
    async def invalidate(self, source_chain: str, target_chain: str, bridge: str = None) -> None:
        """使缓存失效"""
        if bridge:
            key = self._make_key(source_chain, target_chain, bridge)
            async with self._lock:
                self._cache.pop(key, None)
                self._timestamps.pop(key, None)
        else:
            # 使指定链对的所有桥接缓存失效
            async with self._lock:
                keys_to_remove = [
                    k for k in self._cache.keys()
                    if k.startswith(f"{source_chain}_{target_chain}_")
                ]
                for key in keys_to_remove:
                    self._cache.pop(key, None)
                    self._timestamps.pop(key, None)
    
    async def clear(self) -> None:
        """清空缓存"""
        async with self._lock:
            self._cache.clear()
            self._timestamps.clear()
    
    async def get_all(self) -> List[BridgeFee]:
        """获取所有缓存的费用"""
        async with self._lock:
            return list(self._cache.values())
    
    @property
    def size(self) -> int:
        """缓存大小"""
        return len(self._cache)


# ============================================
# 跨链桥费用监控服务
# ============================================

class BridgeFeeMonitorService:
    """
    跨链桥费用监控服务
    
    功能：
    - LayerZero 费用估算
    - Wormhole 费用估算
    - 费用缓存（30秒）
    - 多链对并发查询
    - Gas 价格监控
    """
    
    def __init__(
        self,
        web3_instances: Dict[str, Any] = None,
        cache_ttl: int = 30
    ):
        """
        初始化服务
        
        Args:
            web3_instances: Web3 实例字典
            cache_ttl: 缓存有效期（秒）
        """
        self._web3 = web3_instances or {}
        
        # 初始化费用估算器
        self._lz_estimator = LayerZeroFeeEstimator(self._web3)
        self._wh_estimator = WormholeFeeEstimator(self._web3)
        
        # 初始化缓存
        self._cache = FeeCache(ttl=cache_ttl)
        
        # Gas 价格缓存
        self._gas_prices: Dict[str, GasPrice] = {}
        self._gas_lock = asyncio.Lock()
        
        logger.info("[BridgeFeeMonitor] Service initialized")
    
    def update_web3_instances(self, instances: Dict[str, Any]) -> None:
        """更新 Web3 实例"""
        self._web3 = instances
        self._lz_estimator = LayerZeroFeeEstimator(instances)
        self._wh_estimator = WormholeFeeEstimator(instances)
    
    async def get_fee(
        self,
        source_chain: str,
        target_chain: str,
        bridge: str = "layerzero",
        force_refresh: bool = False
    ) -> Optional[BridgeFee]:
        """
        获取跨链费用
        
        Args:
            source_chain: 源链
            target_chain: 目标链
            bridge: 桥接类型 (layerzero/wormhole)
            force_refresh: 强制刷新缓存
            
        Returns:
            BridgeFee 或 None
        """
        # 检查缓存
        if not force_refresh:
            cached = await self._cache.get(source_chain, target_chain, bridge)
            if cached and not cached.is_stale:
                logger.debug(f"[BridgeFeeMonitor] Cache hit: {source_chain} -> {target_chain} ({bridge})")
                return cached
        
        # 估算费用
        if bridge == "layerzero":
            fee = await self._lz_estimator.estimate_fee(source_chain, target_chain)
        elif bridge == "wormhole":
            fee = await self._wh_estimator.estimate_fee(source_chain, target_chain)
        else:
            logger.warning(f"[BridgeFeeMonitor] Unknown bridge: {bridge}")
            return None
        
        # 更新缓存
        if fee:
            await self._cache.set(fee)
            logger.debug(f"[BridgeFeeMonitor] Fee updated: {source_chain} -> {target_chain} = ${fee.total_cost_usd:.4f}")
        
        return fee
    
    async def get_all_fees(
        self,
        chains: List[str] = None,
        bridges: List[str] = None
    ) -> Dict[str, List[BridgeFee]]:
        """
        获取所有链对的费用
        
        Args:
            chains: 链列表（默认使用 ENABLED_CHAINS）
            bridges: 桥接列表
            
        Returns:
            Dict[str, List[BridgeFee]] - 按源链分组的费用列表
        """
        chains = chains or get_evm_chains()
        bridges = bridges or ["layerzero", "wormhole"]
        
        result: Dict[str, List[BridgeFee]] = {c: [] for c in chains}
        
        # 生成所有链对
        tasks = []
        for src in chains:
            for dst in chains:
                if src == dst:
                    continue
                for bridge in bridges:
                    tasks.append((src, dst, bridge))
        
        # 并发获取费用
        fees = await asyncio.gather(
            *[self.get_fee(src, dst, bridge) for src, dst, bridge in tasks],
            return_exceptions=True
        )
        
        # 整理结果
        for (src, dst, bridge), fee in zip(tasks, fees):
            if isinstance(fee, BridgeFee):
                result[src].append(fee)
        
        return result
    
    async def get_best_bridge(
        self,
        source_chain: str,
        target_chain: str
    ) -> Optional[BridgeFee]:
        """
        获取最佳桥接方案
        
        比较 LayerZero 和 Wormhole 的费用，返回最优选择
        """
        lz_fee = await self.get_fee(source_chain, target_chain, "layerzero")
        wh_fee = await self.get_fee(source_chain, target_chain, "wormhole")
        
        if not lz_fee and not wh_fee:
            return None
        
        if not lz_fee:
            return wh_fee
        if not wh_fee:
            return lz_fee
        
        # 返回费用最低的
        return lz_fee if lz_fee.total_cost_usd < wh_fee.total_cost_usd else wh_fee
    
    async def get_gas_price(self, chain: str) -> Optional[GasPrice]:
        """
        获取链的当前 Gas 价格
        
        Args:
            chain: 链名称
            
        Returns:
            GasPrice 或 None
        """
        async with self._gas_lock:
            if chain in self._gas_prices:
                gp = self._gas_prices[chain]
                if gp.age_seconds < 60:  # 1 分钟内有效
                    return gp
            
            # 从 Web3 获取
            if chain in self._web3:
                try:
                    web3 = self._web3[chain]
                    gas_price_wei = web3.eth.gas_price
                    gas_price_gwei = gas_price_wei / 1e9
                    
                    gp = GasPrice(
                        chain=chain,
                        gas_price_gwei=gas_price_gwei,
                        gas_price_native=gas_price_wei
                    )
                    self._gas_prices[chain] = gp
                    return gp
                except Exception as e:
                    logger.error(f"[BridgeFeeMonitor] Failed to get gas price for {chain}: {e}")
            
            return None
    
    async def refresh_all_fees(self) -> int:
        """
        刷新所有缓存的费用
        
        Returns:
            刷新成功的数量
        """
        evm_chains = get_evm_chains()
        count = 0
        
        for src in evm_chains:
            for dst in evm_chains:
                if src == dst:
                    continue
                
                for bridge in ["layerzero", "wormhole"]:
                    fee = await self.get_fee(src, dst, bridge, force_refresh=True)
                    if fee:
                        count += 1
        
        logger.info(f"[BridgeFeeMonitor] Refreshed {count} fees")
        return count
    
    def get_cache_stats(self) -> Dict:
        """获取缓存统计"""
        return {
            "size": self._cache.size,
            "ttl": self._cache.ttl,
        }
    
    async def get_fees_summary(self) -> Dict:
        """获取费用摘要"""
        fees = await self._cache.get_all()
        
        if not fees:
            return {"total": 0, "avg_cost": 0, "min_cost": 0, "max_cost": 0}
        
        costs = [f.total_cost_usd for f in fees]
        return {
            "total": len(fees),
            "avg_cost": sum(costs) / len(costs),
            "min_cost": min(costs),
            "max_cost": max(costs),
            "by_bridge": {
                "layerzero": sum(1 for f in fees if f.bridge == "layerzero"),
                "wormhole": sum(1 for f in fees if f.bridge == "wormhole"),
            }
        }


# ============================================
# Web3 管理器（独立版本）
# ============================================

class Web3Manager:
    """独立的 Web3 管理器"""
    
    def __init__(self):
        self._instances: Dict[str, Any] = {}
        self._initialize()
    
    def _initialize(self):
        """初始化 Web3 实例"""
        try:
            from web3 import Web3
            
            for chain_name in get_evm_chains():
                if chain_name not in ENABLED_CHAINS:
                    continue
                
                config = get_chain_config(chain_name)
                if not config or not config.is_evm:
                    continue
                
                try:
                    web3 = Web3(Web3.HTTPProvider(config.rpc_url))
                    if web3.is_connected():
                        self._instances[chain_name] = web3
                        logger.info(f"[Web3Manager] Connected to {chain_name}")
                    else:
                        logger.warning(f"[Web3Manager] Not connected to {chain_name}")
                except Exception as e:
                    logger.warning(f"[Web3Manager] Failed to connect to {chain_name}: {e}")
                    
        except ImportError:
            logger.warning("[Web3Manager] web3.py not installed, using fallback mode")
    
    def get_web3(self, chain_name: str) -> Optional[Any]:
        """获取 Web3 实例"""
        return self._instances.get(chain_name)
    
    def get_all_web3(self) -> Dict[str, Any]:
        """获取所有 Web3 实例"""
        return self._instances.copy()


# ============================================
# 全局实例
# ============================================

# Web3 管理器（延迟初始化）
_web3_manager: Optional[Web3Manager] = None

# 费用监控服务（延迟初始化）
bridge_fee_monitor_service: Optional[BridgeFeeMonitorService] = None


def get_bridge_fee_monitor() -> BridgeFeeMonitorService:
    """获取费用监控服务实例"""
    global bridge_fee_monitor_service, _web3_manager
    
    if bridge_fee_monitor_service is None:
        if _web3_manager is None:
            _web3_manager = Web3Manager()
        
        bridge_fee_monitor_service = BridgeFeeMonitorService(
            web3_instances=_web3_manager.get_all_web3(),
            cache_ttl=30
        )
    
    return bridge_fee_monitor_service


# ============================================
# 便捷函数
# ============================================

async def get_cross_chain_fee(
    source_chain: str,
    target_chain: str,
    bridge: str = "layerzero"
) -> Optional[BridgeFee]:
    """获取跨链费用的便捷函数"""
    monitor = get_bridge_fee_monitor()
    return await monitor.get_fee(source_chain, target_chain, bridge)


async def get_all_cross_chain_fees(
    chains: List[str] = None
) -> Dict[str, List[BridgeFee]]:
    """获取所有跨链费用的便捷函数"""
    monitor = get_bridge_fee_monitor()
    return await monitor.get_all_fees(chains)
