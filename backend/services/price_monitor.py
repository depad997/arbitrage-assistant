"""
多链价格监控服务 - Phase 1 核心功能
基于 DexScreener API 实现多链价格监控

功能特性:
- DexScreener API 封装（免费、无需 Key、80+ 链支持）
- 多链并发价格获取
- 价格缓存（内存/Redis）
- 价格监控循环
- 实时价格推送（WebSocket）
"""

import asyncio
import logging
import time
import random
from typing import Dict, List, Optional, Set, Any
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from collections import defaultdict
from enum import Enum
from functools import wraps
import hashlib
import json

import requests
import aiohttp
from aiohttp import ClientTimeout

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
)

logger = logging.getLogger(__name__)


# ============================================
# 数据模型
# ============================================

class PriceSource(Enum):
    """价格数据来源"""
    DEXSCREENER = "dexscreener"
    DEX = "dex"
    CEX = "cex"
    CACHE = "cache"


@dataclass
class TokenPrice:
    """代币价格数据"""
    symbol: str
    chain: str
    price_usd: float
    price_raw: float  # 原始价格（可能是 gecko 等小币种）
    liquidity_usd: float
    volume_24h: float
    price_change_24h: float  # 百分比
    tx_count_24h: int
    pair_address: str
    dex: str
    timestamp: datetime
    source: str = "dexscreener"
    confidence: float = 1.0  # 置信度 0-1
    
    @property
    def age_seconds(self) -> float:
        """数据年龄（秒）"""
        return (datetime.now() - self.timestamp).total_seconds()
    
    @property
    def is_stale(self, max_age: int = 60) -> bool:
        """数据是否过期"""
        return self.age_seconds > max_age
    
    def to_dict(self) -> Dict:
        """转换为字典"""
        d = asdict(self)
        d['timestamp'] = self.timestamp.isoformat()
        return d


@dataclass
class ChainPriceSummary:
    """链的价格汇总"""
    chain: str
    pairs_count: int
    total_liquidity: float
    pairs: List[TokenPrice]
    timestamp: datetime


# ============================================
# DexScreener API 映射
# ============================================

class DexScreenerChainMapper:
    """DexScreener 链 ID 映射"""
    
    # DexScreener 使用小写链 ID
    CHAIN_IDS: Dict[str, str] = {
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
        "berachain": "berachain",
        "moonbeam": "moonbeam",
        # Solana 生态
        "solana": "solana",
        # Sui
        "sui": "sui",
        # Aptos
        "aptos": "aptos",
    }
    
    # 常用代币的 DexScreener 代币 Symbol 映射
    TOKEN_SYMBOLS: Dict[str, str] = {
        # ETH 系列
        "ETH": "ETH",
        "WETH": "WETH",
        "WBTC": "WBTC",
        # USD 稳定币
        "USDC": "USDC",
        "USDT": "USDT",
        "DAI": "DAI",
        "FRAX": "FRAX",
        "LUSD": "LUSD",
        # EVM 链原生代币
        "BNB": "BNB",
        "MATIC": "MATIC",
        "AVAX": "AVAX",
        "FTM": "FTM",
        "OP": "OP",
        "ARB": "ARB",
        "MNT": "MNT",
        "GLMR": "GLMR",
        "SUI": "SUI",
        "APT": "APT",
        "SOL": "SOL",
        # Meme 币
        "DEGEN": "DEGEN",
        # DEX 代币
        "CAKE": "CAKE",
    }
    
    @classmethod
    def get_chain_id(cls, chain: str) -> Optional[str]:
        """获取 DexScreener 链 ID"""
        return cls.CHAIN_IDS.get(chain.lower())
    
    @classmethod
    def get_token_symbol(cls, symbol: str) -> str:
        """获取 DexScreener 代币 Symbol"""
        return cls.TOKEN_SYMBOLS.get(symbol.upper(), symbol.upper())


# ============================================
# 缓存实现
# ============================================

class PriceCache:
    """价格缓存（内存实现，支持 Redis 扩展）"""
    
    def __init__(self, redis_client=None, ttl: int = 30):
        """
        初始化缓存
        
        Args:
            redis_client: Redis 客户端（可选）
            ttl: 缓存过期时间（秒）
        """
        self.redis_client = redis_client
        self.ttl = ttl
        self._memory_cache: Dict[str, Dict] = {}
        self._cache_timestamps: Dict[str, datetime] = {}
        self._lock = asyncio.Lock()
        
    def _make_key(self, chain: str, symbol: str, quote: str = "USDC") -> str:
        """生成缓存 key"""
        return f"price:{chain}:{symbol}:{quote}"
    
    async def get(self, chain: str, symbol: str, quote: str = "USDC") -> Optional[TokenPrice]:
        """获取缓存的价格"""
        key = self._make_key(chain, symbol, quote)
        
        # 优先使用 Redis
        if self.redis_client:
            try:
                data = await self.redis_client.get(key)
                if data:
                    d = json.loads(data)
                    d['timestamp'] = datetime.fromisoformat(d['timestamp'])
                    return TokenPrice(**d)
            except Exception as e:
                logger.warning(f"Redis get error: {e}")
        
        # 回退到内存缓存
        async with self._lock:
            if key in self._memory_cache:
                ts = self._cache_timestamps.get(key)
                if ts and (datetime.now() - ts).total_seconds() < self.ttl:
                    return TokenPrice(**self._memory_cache[key])
        
        return None
    
    async def set(self, price: TokenPrice, quote: str = "USDC") -> None:
        """设置缓存"""
        key = self._make_key(price.chain, price.symbol, quote)
        data = price.to_dict()
        
        # 优先使用 Redis
        if self.redis_client:
            try:
                await self.redis_client.setex(
                    key, 
                    self.ttl, 
                    json.dumps(data, default=str)
                )
            except Exception as e:
                logger.warning(f"Redis set error: {e}")
        
        # 同时更新内存缓存
        async with self._lock:
            self._memory_cache[key] = data
            self._cache_timestamps[key] = datetime.now()
    
    async def invalidate(self, chain: str, symbol: str, quote: str = "USDC") -> None:
        """使缓存失效"""
        key = self._make_key(chain, symbol, quote)
        
        if self.redis_client:
            try:
                await self.redis_client.delete(key)
            except Exception as e:
                logger.warning(f"Redis delete error: {e}")
        
        async with self._lock:
            self._memory_cache.pop(key, None)
            self._cache_timestamps.pop(key, None)
    
    async def clear(self) -> None:
        """清空缓存"""
        if self.redis_client:
            try:
                keys = await self.redis_client.keys("price:*")
                if keys:
                    await self.redis_client.delete(*keys)
            except Exception as e:
                logger.warning(f"Redis clear error: {e}")
        
        async with self._lock:
            self._memory_cache.clear()
            self._cache_timestamps.clear()


# ============================================
# 限流器
# ============================================

class RateLimiter:
    """API 限流器（令牌桶算法）"""
    
    def __init__(self, max_requests: int = 300, time_window: int = 60):
        """
        初始化限流器
        
        Args:
            max_requests: 时间窗口内最大请求数
            time_window: 时间窗口（秒）
        """
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests: List[float] = []
        self._lock = asyncio.Lock()
    
    async def acquire(self) -> bool:
        """获取请求许可（阻塞直到可用或超时）"""
        async with self._lock:
            now = time.time()
            # 清理过期请求
            self.requests = [t for t in self.requests if now - t < self.time_window]
            
            if len(self.requests) < self.max_requests:
                self.requests.append(now)
                return True
            else:
                return False
    
    async def wait_if_needed(self, timeout: float = 60) -> bool:
        """等待直到可以发送请求"""
        start = time.time()
        while time.time() - start < timeout:
            if await self.acquire():
                return True
            # 等待一小段时间后重试
            await asyncio.sleep(0.5)
        return False
    
    @property
    def remaining(self) -> int:
        """剩余请求配额"""
        now = time.time()
        valid = [t for t in self.requests if now - t < self.time_window]
        return max(0, self.max_requests - len(valid))


# ============================================
# DexScreener API 客户端
# ============================================

class DexScreenerClient:
    """
    DexScreener API 客户端
    
    API 文档: https://docs.dexscreener.com/
    
    端点:
    - GET /latest/dex/pairs/{chainId}/{pairAddress} - 获取交易对
    - GET /latest/dex/tokens/{tokenAddress} - 获取代币的所有交易对
    - GET /latest/dex/search?q={query} - 搜索交易对
    """
    
    BASE_URL = "https://api.dexscreener.com"
    
    def __init__(
        self, 
        rate_limiter: Optional[RateLimiter] = None,
        timeout: int = 10,
        max_retries: int = 3
    ):
        """
        初始化 DexScreener 客户端
        
        Args:
            rate_limiter: 限流器
            timeout: 请求超时（秒）
            max_retries: 最大重试次数
        """
        self.rate_limiter = rate_limiter or RateLimiter(
            max_requests=settings.DEXSCREENER_RATE_LIMIT,
            time_window=60
        )
        self.timeout = ClientTimeout(total=timeout)
        self.max_retries = max_retries
        self._session: Optional[aiohttp.ClientSession] = None
        
    async def _get_session(self) -> aiohttp.ClientSession:
        """获取或创建 aiohttp session"""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self.timeout)
        return self._session
    
    async def close(self):
        """关闭客户端"""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
    
    async def _make_request(
        self, 
        method: str, 
        url: str, 
        params: Optional[Dict] = None,
        retries: int = 0
    ) -> Optional[Dict]:
        """
        发起 HTTP 请求（带重试和限流）
        
        Args:
            method: HTTP 方法
            url: 请求 URL
            params: 查询参数
            retries: 当前重试次数
            
        Returns:
            响应数据或 None
        """
        # 等待限流
        if not await self.rate_limiter.wait_if_needed(timeout=30):
            logger.warning(f"Rate limit timeout for {url}")
            return None
        
        try:
            session = await self._get_session()
            
            async with session.request(method, url, params=params) as response:
                if response.status == 200:
                    return await response.json()
                elif response.status == 429:
                    # 限流，短暂等待后重试
                    logger.warning(f"Rate limited (429), retrying...")
                    await asyncio.sleep(2 ** min(retries, 3))
                    if retries < self.max_retries:
                        return await self._make_request(method, url, params, retries + 1)
                elif response.status == 404:
                    # 资源不存在
                    logger.debug(f"Resource not found: {url}")
                    return None
                else:
                    logger.error(f"API error {response.status}: {url}")
                    
        except asyncio.TimeoutError:
            logger.warning(f"Timeout for {url}")
            if retries < self.max_retries:
                await asyncio.sleep(1)
                return await self._make_request(method, url, params, retries + 1)
        except aiohttp.ClientError as e:
            logger.warning(f"Client error for {url}: {e}")
            if retries < self.max_retries:
                await asyncio.sleep(1)
                return await self._make_request(method, url, params, retries + 1)
        except Exception as e:
            logger.error(f"Unexpected error for {url}: {e}")
            
        return None
    
    async def get_pairs_by_chain(
        self, 
        chain: str, 
        limit: int = 50,
        sort_by: str = "liquidity"  # liquidity, volume, priceChange
    ) -> List[Dict]:
        """
        获取链上的交易对列表
        
        Args:
            chain: 链名称
            limit: 返回数量限制
            sort_by: 排序字段
            
        Returns:
            交易对列表
        """
        chain_id = DexScreenerChainMapper.get_chain_id(chain)
        if not chain_id:
            logger.warning(f"Unknown chain: {chain}")
            return []
        
        url = f"{self.BASE_URL}/latest/dex/pairs/{chain_id}"
        params = {"limit": limit}
        
        data = await self._make_request("GET", url, params)
        if not data or "pairs" not in data:
            return []
        
        # 解析并过滤交易对
        pairs = data.get("pairs", [])
        valid_pairs = []
        
        for pair in pairs:
            # 过滤掉流动性太低的交易对
            liquidity = pair.get("liquidity", {})
            if isinstance(liquidity, dict):
                usd_liquidity = float(liquidity.get("usd", 0))
            else:
                usd_liquidity = float(liquidity) if liquidity else 0
            
            if usd_liquidity < settings.MIN_LIQUIDITY:
                continue
            
            valid_pairs.append(pair)
        
        return valid_pairs
    
    async def get_token_pairs(
        self, 
        chain: str, 
        token_address: str,
        limit: int = 20
    ) -> List[Dict]:
        """
        获取特定代币的交易对
        
        Args:
            chain: 链名称
            token_address: 代币地址
            limit: 返回数量限制
            
        Returns:
            交易对列表
        """
        chain_id = DexScreenerChainMapper.get_chain_id(chain)
        if not chain_id:
            return []
        
        url = f"{self.BASE_URL}/latest/dex/tokens/{token_address}"
        params = {"limit": limit}
        
        data = await self._make_request("GET", url, params)
        if not data or "pairs" not in data:
            return []
        
        # 按流动性排序
        pairs = data.get("pairs", [])
        valid_pairs = [
            p for p in pairs 
            if self._parse_liquidity(p) >= settings.MIN_LIQUIDITY
        ]
        
        # 按流动性降序
        valid_pairs.sort(
            key=lambda x: self._parse_liquidity(x), 
            reverse=True
        )
        
        return valid_pairs[:limit]
    
    async def search_pairs(
        self, 
        query: str, 
        limit: int = 20
    ) -> List[Dict]:
        """
        搜索交易对
        
        Args:
            query: 搜索关键词
            limit: 返回数量限制
            
        Returns:
            交易对列表
        """
        url = f"{self.BASE_URL}/latest/dex/search"
        params = {"q": query}
        
        data = await self._make_request("GET", url, params)
        if not data or "pairs" not in data:
            return []
        
        pairs = data.get("pairs", [])
        
        # 过滤并排序
        valid_pairs = [
            p for p in pairs 
            if self._parse_liquidity(p) >= settings.MIN_LIQUIDITY
        ]
        
        valid_pairs.sort(
            key=lambda x: self._parse_liquidity(x),
            reverse=True
        )
        
        return valid_pairs[:limit]
    
    def _parse_liquidity(self, pair: Dict) -> float:
        """解析流动性数据"""
        liquidity = pair.get("liquidity", {})
        if isinstance(liquidity, dict):
            return float(liquidity.get("usd", 0))
        return float(liquidity) if liquidity else 0
    
    def _parse_volume(self, pair: Dict) -> Dict[str, float]:
        """解析交易量数据"""
        volume = pair.get("volume", {})
        if isinstance(volume, dict):
            return {
                "h24": float(volume.get("h24", 0)),
                "h6": float(volume.get("h6", 0)),
                "h1": float(volume.get("h1", 0)),
                "m5": float(volume.get("m5", 0)),
            }
        return {"h24": 0, "h6": 0, "h1": 0, "m5": 0}


# ============================================
# 价格监控服务
# ============================================

class PriceMonitorService:
    """
    多链价格监控服务
    
    功能:
    - 多链并发价格获取
    - 价格缓存
    - 周期性价格更新
    - WebSocket 实时推送
    """
    
    def __init__(
        self,
        redis_client=None,
        polling_interval: int = None,
        cache_ttl: int = 30
    ):
        """
        初始化价格监控服务
        
        Args:
            redis_client: Redis 客户端（可选）
            polling_interval: 轮询间隔（秒）
            cache_ttl: 缓存过期时间（秒）
        """
        self.redis_client = redis_client
        self.polling_interval = polling_interval or settings.PRICE_POLLING_INTERVAL
        
        # 初始化组件
        self.dex_client = DexScreenerClient(
            rate_limiter=RateLimiter(
                max_requests=settings.DEXSCREENER_RATE_LIMIT,
                time_window=60
            ),
            timeout=settings.DEXSCREENER_TIMEOUT
        )
        self.cache = PriceCache(redis_client, ttl=cache_ttl)
        
        # 价格数据存储
        self._prices: Dict[str, Dict[str, TokenPrice]] = defaultdict(dict)  # chain -> symbol -> price
        self._pair_data: Dict[str, List[Dict]] = defaultdict(list)  # chain -> pairs
        
        # WebSocket 连接管理
        self._ws_connections: Set[Any] = set()
        self._ws_lock = asyncio.Lock()
        
        # 监控任务
        self._monitor_task: Optional[asyncio.Task] = None
        self._running = False
        
        logger.info(f"[PriceMonitor] Initialized with {len(ENABLED_CHAINS)} chains")
    
    async def start(self):
        """启动价格监控"""
        if self._running:
            logger.warning("[PriceMonitor] Already running")
            return
        
        self._running = True
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        logger.info(f"[PriceMonitor] Started with {self.polling_interval}s interval")
    
    async def stop(self):
        """停止价格监控"""
        self._running = False
        
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        
        await self.dex_client.close()
        logger.info("[PriceMonitor] Stopped")
    
    async def _monitor_loop(self):
        """价格监控主循环"""
        while self._running:
            try:
                await self._update_all_prices()
                await self._broadcast_prices()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[PriceMonitor] Monitor loop error: {e}")
            
            await asyncio.sleep(self.polling_interval)
    
    async def _update_all_prices(self):
        """更新所有链的价格"""
        # 并发获取所有链的价格
        tasks = []
        for chain in ENABLED_CHAINS:
            # 获取该链的主要交易对
            pairs = settings.MONITORED_PAIRS
            chain_pairs = [(chain, symbol, quote) for chain_name, symbol, quote in pairs if chain_name == chain]
            
            for _, symbol, quote in chain_pairs:
                tasks.append(self._fetch_and_cache_price(chain, symbol, quote))
        
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # 记录成功获取的价格数量
            success = sum(1 for r in results if isinstance(r, TokenPrice))
            logger.debug(f"[PriceMonitor] Updated {success}/{len(tasks)} prices")
    
    async def _fetch_and_cache_price(
        self, 
        chain: str, 
        symbol: str, 
        quote: str = "USDC"
    ) -> Optional[TokenPrice]:
        """获取并缓存价格"""
        # 检查缓存
        cached = await self.cache.get(chain, symbol, quote)
        if cached and not cached.is_stale:
            self._prices[chain][symbol] = cached
            return cached
        
        # 获取交易对信息
        pairs = await self._get_pairs_for_token(chain, symbol, quote)
        if not pairs:
            return cached  # 返回可能过期的缓存
        
        # 解析最佳交易对
        best_pair = pairs[0]
        price = self._parse_pair_to_price(best_pair, chain, symbol, quote)
        
        if price:
            # 更新缓存
            await self.cache.set(price, quote)
            self._prices[chain][symbol] = price
        
        return price
    
    async def _get_pairs_for_token(
        self, 
        chain: str, 
        symbol: str, 
        quote: str
    ) -> List[Dict]:
        """获取代币的交易对"""
        # 构建搜索关键词
        search_term = f"{symbol}/{quote}"
        
        # 尝试搜索
        pairs = await self.dex_client.search_pairs(search_term, limit=10)
        
        # 过滤匹配的交易对
        filtered = [
            p for p in pairs 
            if self._is_matching_pair(p, chain, symbol, quote)
        ]
        
        if filtered:
            return filtered
        
        # 搜索不到则获取链上所有交易对（较慢）
        return await self.dex_client.get_pairs_by_chain(chain, limit=100)
    
    def _is_matching_pair(self, pair: Dict, chain: str, symbol: str, quote: str) -> bool:
        """检查交易对是否匹配"""
        base = pair.get("baseToken", {})
        quote_token = pair.get("quoteToken", {})
        
        base_symbol = base.get("symbol", "").upper()
        quote_symbol = quote_token.get("symbol", "").upper()
        
        return (
            base_symbol == symbol.upper() and 
            quote_symbol == quote.upper()
        )
    
    def _parse_pair_to_price(
        self, 
        pair: Dict, 
        chain: str, 
        symbol: str,
        quote: str
    ) -> Optional[TokenPrice]:
        """将交易对数据解析为价格对象"""
        try:
            # 解析价格
            price_raw = float(pair.get("priceUsd", 0) or pair.get("priceNative", 0))
            if price_raw == 0:
                return None
            
            # 解析流动性
            liquidity = self._parse_liquidity(pair)
            
            # 解析交易量
            volume = self._parse_volume(pair)
            
            # 解析价格变动
            price_change = float(pair.get("priceChange", {}).get("h24", 0) or 0)
            
            # 解析交易次数
            tx_count = int(pair.get("txns", {}).get("h24", {}).get("buys", 0) or 0) + \
                       int(pair.get("txns", {}).get("h24", {}).get("sells", 0) or 0)
            
            base = pair.get("baseToken", {})
            
            return TokenPrice(
                symbol=symbol,
                chain=chain,
                price_usd=price_raw,
                price_raw=price_raw,
                liquidity_usd=liquidity,
                volume_24h=volume.get("h24", 0),
                price_change_24h=price_change,
                tx_count_24h=tx_count,
                pair_address=pair.get("pairAddress", ""),
                dex=pair.get("dexId", "unknown"),
                timestamp=datetime.now(),
                source="dexscreener",
                confidence=self._calculate_confidence(pair)
            )
        except Exception as e:
            logger.warning(f"[PriceMonitor] Failed to parse pair: {e}")
            return None
    
    def _calculate_confidence(self, pair: Dict) -> float:
        """计算数据置信度"""
        confidence = 0.5  # 基础置信度
        
        # 流动性越高置信度越高
        liquidity = self._parse_liquidity(pair)
        if liquidity > 1000000:  # > 1M
            confidence += 0.3
        elif liquidity > 100000:  # > 100K
            confidence += 0.2
        elif liquidity > 10000:  # > 10K
            confidence += 0.1
        
        # 有官方验证的置信度更高
        if pair.get("baseToken", {}).get("isVerified"):
            confidence += 0.1
        
        # 24h 交易量
        volume = self._parse_volume(pair).get("h24", 0)
        if volume > 1000000:
            confidence += 0.1
        
        return min(confidence, 1.0)
    
    # ============================================
    # 公开 API
    # ============================================
    
    async def get_price(
        self, 
        chain: str, 
        symbol: str, 
        quote: str = "USDC",
        use_cache: bool = True
    ) -> Optional[TokenPrice]:
        """
        获取代币价格
        
        Args:
            chain: 链名称
            symbol: 代币符号
            quote: 计价代币（默认 USDC）
            use_cache: 是否使用缓存
            
        Returns:
            价格数据或 None
        """
        # 检查缓存
        if use_cache:
            cached = await self.cache.get(chain, symbol, quote)
            if cached:
                return cached
        
        # 获取最新价格
        return await self._fetch_and_cache_price(chain, symbol, quote)
    
    async def get_prices_by_chain(
        self, 
        chain: str,
        symbols: Optional[List[str]] = None
    ) -> Dict[str, TokenPrice]:
        """
        获取链上多个代币价格
        
        Args:
            chain: 链名称
            symbols: 代币列表（None 表示获取所有）
            
        Returns:
            symbol -> price 映射
        """
        if symbols is None:
            # 从监控列表获取
            pairs = [p for p in settings.MONITORED_PAIRS if p[0] == chain]
            symbols = [p[1] for p in pairs]
        
        # 并发获取
        tasks = [self.get_price(chain, sym) for sym in symbols]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        return {
            sym: result 
            for sym, result in zip(symbols, results) 
            if isinstance(result, TokenPrice)
        }
    
    async def get_all_prices(self) -> Dict[str, Dict[str, TokenPrice]]:
        """
        获取所有链的价格
        
        Returns:
            chain -> symbol -> price 映射
        """
        # 并发获取所有链
        tasks = [
            self.get_prices_by_chain(chain) 
            for chain in ENABLED_CHAINS
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        return {
            chain: result 
            for chain, result in zip(ENABLED_CHAINS, results) 
            if isinstance(result, dict)
        }
    
    async def get_trending_pairs(
        self, 
        chain: str, 
        limit: int = 20,
        sort_by: str = "volume"
    ) -> List[Dict]:
        """
        获取热门交易对
        
        Args:
            chain: 链名称
            limit: 返回数量
            sort_by: 排序字段 (volume/liquidity/priceChange)
            
        Returns:
            交易对列表
        """
        pairs = await self.dex_client.get_pairs_by_chain(chain, limit=limit * 2)
        
        if not pairs:
            return []
        
        # 排序
        if sort_by == "volume":
            pairs.sort(key=lambda x: self._parse_volume(x).get("h24", 0), reverse=True)
        elif sort_by == "liquidity":
            pairs.sort(key=self._parse_liquidity, reverse=True)
        elif sort_by == "priceChange":
            pairs.sort(
                key=lambda x: abs(float(x.get("priceChange", {}).get("h24", 0) or 0)),
                reverse=True
            )
        
        return pairs[:limit]
    
    async def search_token(
        self, 
        query: str, 
        chains: Optional[List[str]] = None
    ) -> List[Dict]:
        """
        搜索代币
        
        Args:
            query: 搜索关键词
            chains: 限制的链列表
            
        Returns:
            匹配的代币列表
        """
        pairs = await self.dex_client.search_pairs(query, limit=50)
        
        if chains:
            pairs = [p for p in pairs if p.get("chainId") in chains]
        
        return pairs
    
    # ============================================
    # WebSocket 支持
    # ============================================
    
    async def register_ws_connection(self, websocket):
        """注册 WebSocket 连接"""
        async with self._ws_lock:
            self._ws_connections.add(websocket)
            logger.info(f"[PriceMonitor] WebSocket connected, total: {len(self._ws_connections)}")
    
    async def unregister_ws_connection(self, websocket):
        """取消注册 WebSocket 连接"""
        async with self._ws_lock:
            self._ws_connections.discard(websocket)
            logger.info(f"[PriceMonitor] WebSocket disconnected, remaining: {len(self._ws_connections)}")
    
    async def _broadcast_prices(self):
        """广播价格更新"""
        if not self._ws_connections:
            return
        
        async with self._ws_lock:
            connections = list(self._ws_connections)
        
        # 广播到所有连接
        message = {
            "type": "price_update",
            "timestamp": datetime.now().isoformat(),
            "prices": {
                chain: {
                    symbol: price.to_dict() 
                    for symbol, price in prices.items()
                }
                for chain, prices in self._prices.items()
            }
        }
        
        for ws in connections:
            try:
                await ws.send_json(message)
            except Exception as e:
                logger.warning(f"[PriceMonitor] Failed to send to WebSocket: {e}")
    
    # ============================================
    # 辅助方法
    # ============================================
    
    @property
    def prices(self) -> Dict[str, Dict[str, TokenPrice]]:
        """获取当前所有价格"""
        return dict(self._prices)
    
    async def get_chain_status(self) -> Dict[str, Dict]:
        """获取各链的状态"""
        return {
            "chains": ENABLED_CHAINS,
            "total_prices": sum(len(p) for p in self._prices.values()),
            "ws_connections": len(self._ws_connections),
            "rate_limiter_remaining": self.dex_client.rate_limiter.remaining,
            "running": self._running
        }


# ============================================
# 便捷函数
# ============================================

async def get_price_service(redis_client=None) -> PriceMonitorService:
    """获取价格监控服务单例"""
    if not hasattr(get_price_service, "_instance"):
        get_price_service._instance = PriceMonitorService(redis_client)
        await get_price_service._instance.start()
    return get_price_service._instance
