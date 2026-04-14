"""
多数据源价格获取服务
支持 DexScreener、1inch、链上DEX 三层数据源
"""

import asyncio
import logging
import time
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import statistics

import aiohttp
import json

import sys
import os
_backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from config.settings import SUPPORTED_CHAINS, get_chain_config

logger = logging.getLogger(__name__)


# ============================================
# 数据源枚举
# ============================================

class PriceSource(Enum):
    """价格数据源"""
    DEXSCREENER = "dexscreener"
    INCH = "1inch"
    ONCHAIN = "onchain_dex"
    
    @property
    def priority(self) -> int:
        priorities = {
            PriceSource.DEXSCREENER: 1,
            PriceSource.INCH: 2,
            PriceSource.ONCHAIN: 3,
        }
        return priorities.get(self, 99)


# ============================================
# 链ID映射
# ============================================

# DexScreener chain ID
DEXSCREENER_CHAINS = {
    "ethereum": "ethereum",
    "arbitrum": "arbitrum",
    "optimism": "optimism",
    "base": "base",
    "bsc": "bsc",
    "polygon": "polygon",
    "avalanche": "avalanche",
    "fantom": "fantom",
    "scroll": "scroll",
    "mantle": "mantle",
    "linea": "linea",
}

# 1inch chain ID
INCH_CHAIN_IDS = {
    "ethereum": 1,
    "arbitrum": 42161,
    "optimism": 10,
    "base": 8453,
    "bsc": 56,
    "polygon": 137,
    "avalanche": 43114,
    "fantom": 250,
}

# 代币地址映射
TOKEN_ADDRESSES = {
    "ethereum": {
        "WETH": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
        "USDC": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
        "USDT": "0xdAC17F958D2ee523a2206206994597C13D831ec7",
        "WBTC": "0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599",
        "LINK": "0x514910771AF9Ca656af840dff83E8264EcF986CA",
        "UNI": "0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984",
        "AAVE": "0x7Fc66500c84A76Ad7e9c93437bFc5Ac33E2DDaE9",
        "ARB": "0xB50721BCf8d664c30412Cfbc6cf7a15145234ad1",
        "OP": "0x4200000000000000000000000000000000000042",
    },
    "arbitrum": {
        "WETH": "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1",
        "USDC": "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
        "USDT": "0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9",
        "ARB": "0x912CE59144191C1204E64559FE8253a0e49E6548",
        "LINK": "0xf97f4df75117a78c1A5a0DBb814Af924585397A4",
        "UNI": "0xFa7F8980b0f1E64A2062791cc3b0871572f1F7F0",
        "GMX": "0xfc5A1A6EB076a2B7a7b3b8c0b0b0b0b0b0b0b0b0",
    },
    "optimism": {
        "WETH": "0x4200000000000000000000000000000000000006",
        "USDC": "0x0b2C639c533813f4Aa9D7837CAf62653d097Ff85",
        "OP": "0x4200000000000000000000000000000000000042",
        "LINK": "0x350a791Bfc2C21F9Ed5d10980Dad2e2638ffa7f6",
    },
    "base": {
        "WETH": "0x4200000000000000000000000000000000000006",
        "USDC": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
    },
    "polygon": {
        "WETH": "0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619",
        "USDC": "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359",
        "MATIC": "0x0000000000000000000000000000000000001010",
        "LINK": "0xb0897686c545045aFc77CF20eC7A532E3120E0F1",
    },
    "bsc": {
        "WBNB": "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c",
        "USDC": "0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d",
        "USDT": "0x55d398326f99059fF775485246999027B3197955",
        "BTCB": "0x7130d2A12B9BCbFAe4f2634d864A1Ee1Ce3Ead9c",
        "ETH": "0x2170Ed0880ac9A755fd29B2688956BD959F933F8",
        "CAKE": "0x0E09FaBB73Bd3Ade0a17ECC321fD13a19e81cE82",
    },
    "avalanche": {
        "WAVAX": "0xB31f66AA3C1e785363F0875A1B74E27b85FD66c7",
        "USDC": "0xB97EF9Ef8734C71904D8002F8b6Bc66Dd9c48a6E",
        "USDT": "0x9702230A8Ea53601f5cD2dc00fDBc13d4dF4A8c7",
        "JOE": "0x6e84a6216eA6dACC71eE8E6b0a5B7322EEbC0fDd",
    },
}


# ============================================
# 价格结果数据结构
# ============================================

@dataclass
class PriceResult:
    """单个数据源的价格结果"""
    source: PriceSource
    price: float
    timestamp: datetime = field(default_factory=datetime.now)
    success: bool = True
    error: Optional[str] = None
    raw_data: Optional[dict] = None


@dataclass
class AggregatedPrice:
    """聚合后的价格"""
    symbol: str
    chain: str
    price: float
    sources: List[PriceSource]
    source_prices: Dict[PriceSource, float]
    timestamp: datetime = field(default_factory=datetime.now)
    confidence: float = 1.0  # 置信度 0-1
    
    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "chain": self.chain,
            "price": self.price,
            "sources": [s.value for s in self.sources],
            "source_prices": {s.value: p for s, p in self.source_prices.items()},
            "timestamp": self.timestamp.isoformat(),
            "confidence": self.confidence,
        }


# ============================================
# DexScreener 数据源
# ============================================

class DexScreenerSource:
    """DexScreener 价格源"""
    
    BASE_URL = "https://api.dexscreener.com/latest"
    
    def __init__(self, session: aiohttp.ClientSession = None):
        self.session = session
        self._own_session = session is None
        
    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=10)
            )
        return self.session
    
    async def get_price(
        self, 
        chain: str, 
        token_address: str
    ) -> Optional[PriceResult]:
        """获取代币价格"""
        try:
            session = await self._get_session()
            ds_chain = DEXSCREENER_CHAINS.get(chain)
            
            if not ds_chain:
                return PriceResult(
                    source=PriceSource.DEXSCREENER,
                    price=0,
                    success=False,
                    error=f"Chain {chain} not supported"
                )
            
            # DexScreener 用 pair 地址查询，我们用 token 地址
            url = f"{self.BASE_URL}/dex/tokens/{token_address}"
            
            async with session.get(url) as resp:
                if resp.status != 200:
                    return PriceResult(
                        source=PriceSource.DEXSCREENER,
                        price=0,
                        success=False,
                        error=f"HTTP {resp.status}"
                    )
                
                data = await resp.json()
                
                if not data.get("pairs"):
                    return PriceResult(
                        source=PriceSource.DEXSCREENER,
                        price=0,
                        success=False,
                        error="No pairs found"
                    )
                
                # 找到当前链上的 pair
                for pair in data["pairs"]:
                    if pair.get("chainId") == ds_chain:
                        price_usd = float(pair.get("priceUsd", 0))
                        if price_usd > 0:
                            return PriceResult(
                                source=PriceSource.DEXSCREENER,
                                price=price_usd,
                                raw_data={
                                    "pair": pair.get("pairAddress"),
                                    "liquidity": pair.get("liquidity", {}).get("usd", 0),
                                    "volume_24h": pair.get("volume", {}).get("h24", 0),
                                }
                            )
                
                return PriceResult(
                    source=PriceSource.DEXSCREENER,
                    price=0,
                    success=False,
                    error="No price found for chain"
                )
                
        except Exception as e:
            logger.error(f"[DexScreener] Error: {e}")
            return PriceResult(
                source=PriceSource.DEXSCREENER,
                price=0,
                success=False,
                error=str(e)
            )
    
    async def close(self):
        if self._own_session and self.session:
            await self.session.close()


# ============================================
# 1inch 数据源
# ============================================

class InchSource:
    """1inch Spot Price 数据源"""
    
    BASE_URL = "https://api.1inch.dev/spot/v1.1"
    
    def __init__(self, api_key: str = None, session: aiohttp.ClientSession = None):
        self.api_key = api_key
        self.session = session
        self._own_session = session is None
        
    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=10)
            )
        return self.session
    
    async def get_price(
        self,
        chain: str,
        token_address: str
    ) -> Optional[PriceResult]:
        """获取代币价格"""
        try:
            chain_id = INCH_CHAIN_IDS.get(chain)
            if not chain_id:
                return PriceResult(
                    source=PriceSource.INCH,
                    price=0,
                    success=False,
                    error=f"Chain {chain} not supported"
                )
            
            session = await self._get_session()
            
            # 1inch Spot Price API
            url = f"{self.BASE_URL}/{chain_id}/quote"
            
            # 用 USDC 作为目标报价
            usdc_addr = TOKEN_ADDRESSES.get(chain, {}).get("USDC", "")
            if not usdc_addr:
                return PriceResult(
                    source=PriceSource.INCH,
                    price=0,
                    success=False,
                    error="No USDC address for chain"
                )
            
            params = {
                "src": token_address,
                "dst": usdc_addr,
                "amount": "1000000000000000000",  # 1 token (18 decimals)
            }
            
            headers = {}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            
            async with session.get(url, params=params, headers=headers) as resp:
                if resp.status == 401:
                    # 1inch 需要 API Key，没有则返回不可用
                    return PriceResult(
                        source=PriceSource.INCH,
                        price=0,
                        success=False,
                        error="API key required"
                    )
                
                if resp.status != 200:
                    return PriceResult(
                        source=PriceSource.INCH,
                        price=0,
                        success=False,
                        error=f"HTTP {resp.status}"
                    )
                
                data = await resp.json()
                
                # 计算价格
                dst_amount = float(data.get("dstAmount", 0)) / 1e6  # USDC 6 decimals
                if dst_amount > 0:
                    return PriceResult(
                        source=PriceSource.INCH,
                        price=dst_amount,
                        raw_data={
                            "src_amount": data.get("srcAmount"),
                            "dst_amount": data.get("dstAmount"),
                            "gas": data.get("gas"),
                        }
                    )
                
                return PriceResult(
                    source=PriceSource.INCH,
                    price=0,
                    success=False,
                    error="Invalid quote"
                )
                
        except Exception as e:
            logger.error(f"[1inch] Error: {e}")
            return PriceResult(
                source=PriceSource.INCH,
                price=0,
                success=False,
                error=str(e)
            )
    
    async def close(self):
        if self._own_session and self.session:
            await self.session.close()


# ============================================
# 链上 DEX 数据源（复用现有代码）
# ============================================

class OnchainSource:
    """链上 DEX 价格源"""
    
    def __init__(self, onchain_service=None):
        self.onchain_service = onchain_service
        
    async def get_price(
        self,
        chain: str,
        token_address: str
    ) -> Optional[PriceResult]:
        """从链上 DEX 获取价格"""
        try:
            if self.onchain_service is None:
                from services.onchain_price import get_onchain_price_service
                self.onchain_service = await get_onchain_price_service()
            
            # 获取链上价格
            price = await self.onchain_service.get_token_price(chain, token_address)
            
            if price and price > 0:
                return PriceResult(
                    source=PriceSource.ONCHAIN,
                    price=price,
                )
            
            return PriceResult(
                source=PriceSource.ONCHAIN,
                price=0,
                success=False,
                error="Price not available"
            )
            
        except Exception as e:
            logger.error(f"[Onchain] Error: {e}")
            return PriceResult(
                source=PriceSource.ONCHAIN,
                price=0,
                success=False,
                error=str(e)
            )


# ============================================
# 多数据源聚合服务
# ============================================

class MultiSourcePriceService:
    """多数据源价格聚合服务"""
    
    def __init__(
        self,
        inch_api_key: str = None,
        session: aiohttp.ClientSession = None
    ):
        self.session = session
        self._own_session = session is None
        
        # 初始化各数据源
        self.dexscreener = DexScreenerSource(session)
        self.inch = InchSource(api_key=inch_api_key, session=session)
        self.onchain = OnchainSource()
        
        # 缓存
        self._cache: Dict[str, Tuple[AggregatedPrice, float]] = {}
        self._cache_ttl = 30  # 30秒缓存
        
        # Rate limit
        self._last_request_time = 0
        self._min_interval = 0.2  # 每个源最小间隔 200ms
        
    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=15)
            )
        return self.session
    
    def _cache_key(self, chain: str, symbol: str) -> str:
        return f"{chain}:{symbol}"
    
    async def get_price(
        self,
        chain: str,
        symbol: str,
        use_cache: bool = True
    ) -> AggregatedPrice:
        """
        获取聚合价格
        
        Args:
            chain: 链名称
            symbol: 代币符号
            use_cache: 是否使用缓存
            
        Returns:
            AggregatedPrice
        """
        cache_key = self._cache_key(chain, symbol)
        
        # 检查缓存
        if use_cache and cache_key in self._cache:
            cached, timestamp = self._cache[cache_key]
            if time.time() - timestamp < self._cache_ttl:
                return cached
        
        # 获取代币地址
        token_address = TOKEN_ADDRESSES.get(chain, {}).get(symbol.upper())
        
        if not token_address:
            return AggregatedPrice(
                symbol=symbol,
                chain=chain,
                price=0,
                sources=[],
                source_prices={},
                confidence=0
            )
        
        # 并行从三个数据源获取价格
        results = await asyncio.gather(
            self.dexscreener.get_price(chain, token_address),
            self.inch.get_price(chain, token_address),
            self.onchain.get_price(chain, token_address),
            return_exceptions=True
        )
        
        # 整理成功的结果
        successful_results: List[PriceResult] = []
        for r in results:
            if isinstance(r, PriceResult) and r.success and r.price > 0:
                successful_results.append(r)
        
        if not successful_results:
            return AggregatedPrice(
                symbol=symbol,
                chain=chain,
                price=0,
                sources=[],
                source_prices={},
                confidence=0
            )
        
        # 聚合价格（取中位数）
        prices = [r.price for r in successful_results]
        final_price = statistics.median(prices) if len(prices) > 1 else prices[0]
        
        # 计算置信度
        if len(prices) > 1:
            # 价格差异越小，置信度越高
            price_std = statistics.stdev(prices) if len(prices) > 1 else 0
            price_mean = statistics.mean(prices)
            deviation = price_std / price_mean if price_mean > 0 else 1
            confidence = max(0.3, 1 - deviation)
        else:
            confidence = 0.6  # 单数据源默认置信度
        
        # 多数据源加分
        confidence = min(1.0, confidence + 0.1 * (len(successful_results) - 1))
        
        result = AggregatedPrice(
            symbol=symbol,
            chain=chain,
            price=final_price,
            sources=[r.source for r in successful_results],
            source_prices={r.source: r.price for r in successful_results},
            confidence=round(confidence, 2)
        )
        
        # 更新缓存
        self._cache[cache_key] = (result, time.time())
        
        return result
    
    async def get_all_prices(self, chain: str) -> Dict[str, AggregatedPrice]:
        """获取链上所有主流代币价格"""
        tokens = TOKEN_ADDRESSES.get(chain, {})
        if not tokens:
            return {}
        
        results = {}
        
        # 并行获取所有代币价格
        tasks = []
        for symbol in tokens:
            tasks.append(self.get_price(chain, symbol))
        
        prices = await asyncio.gather(*tasks, return_exceptions=True)
        
        for symbol, price in zip(tokens.keys(), prices):
            if isinstance(price, AggregatedPrice) and price.price > 0:
                results[symbol] = price
        
        return results
    
    async def get_multi_chain_prices(
        self,
        chains: List[str],
        symbols: List[str]
    ) -> Dict[str, Dict[str, AggregatedPrice]]:
        """
        获取多链多代币价格
        
        Returns:
            {symbol: {chain: AggregatedPrice}}
        """
        results = {}
        
        # 构建所有任务
        tasks = []
        task_keys = []  # (symbol, chain)
        
        for symbol in symbols:
            for chain in chains:
                if chain in TOKEN_ADDRESSES and symbol.upper() in TOKEN_ADDRESSES[chain]:
                    tasks.append(self.get_price(chain, symbol))
                    task_keys.append((symbol, chain))
        
        # 并行执行
        prices = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 整理结果
        for (symbol, chain), price in zip(task_keys, prices):
            if isinstance(price, AggregatedPrice) and price.price > 0:
                if symbol not in results:
                    results[symbol] = {}
                results[symbol][chain] = price
        
        return results
    
    async def close(self):
        """清理资源"""
        await self.dexscreener.close()
        await self.inch.close()
        if self._own_session and self.session:
            await self.session.close()


# ============================================
# 单例
# ============================================

_multi_source_price_service: Optional[MultiSourcePriceService] = None


async def get_multi_source_price_service(
    inch_api_key: str = None
) -> MultiSourcePriceService:
    """获取多数据源价格服务单例"""
    global _multi_source_price_service
    
    if _multi_source_price_service is None:
        _multi_source_price_service = MultiSourcePriceService(inch_api_key=inch_api_key)
    
    return _multi_source_price_service
