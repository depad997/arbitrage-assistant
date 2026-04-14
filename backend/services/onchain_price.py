"""
链上价格获取服务
直接从链上DEX池子获取价格，不依赖外部API
"""

import asyncio
import logging
import time
from typing import Dict, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime

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
# 主流代币地址（各链）
# ============================================

# 代币地址映射 {链名: {代币符号: 地址}}
TOKEN_ADDRESSES = {
    "ethereum": {
        "WETH": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
        "USDC": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
        "USDT": "0xdAC17F958D2ee523a2206206994597C13D831ec7",
        "WBTC": "0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599",
        "DAI": "0x6B175474E89094C44Da98b954EescdeCB5dD9c2D",
        "LINK": "0x514910771AF9Ca656af840dff83E8264EcF986CA",
        "UNI": "0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984",
        "AAVE": "0x7Fc66500c84A76Ad7e9c93437bFc5Ac33E2DDaE9",
        "MKR": "0x9f8F72aA9304c8B593d555F12eF6589cC3A579A2",
        "SNX": "0xC011a73ee8576Fb46F5E1c5751cA3B9Fe0af2a6F",
        "CRV": "0xD533a949740bb3306d119CC777fa900bA034cd52",
        "COMP": "0xc00e94Cb662C3520282E6f5717214004A7f26888",
        "SUSHI": "0x6B3595068778DD592e39A122f4f5a5cF09C90fE2",
        "MATIC": "0x7D1AfA7B718fb893dB30A3aBc0Cfc608AaCfeBB0",
        "ARB": "0xB50721BCf8d664c30412Cfbc6cf7a15145234ad1",
        "OP": "0x4200000000000000000000000000000000000042",
        "PEPE": "0x6982508145454Ce325dDbE47a25d4ec3d2311933",
        "SHIB": "0x95aD61b0a150d79219dCF64E1E6Cc01f0B64C4cE",
        "DOGE": "0xba2ae424d960c26247dd6c32edc70b295c744c43",
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

# Uniswap V3 池子地址 {链名: {池子名: 地址}}
DEX_POOLS = {
    "ethereum": {
        "USDC_WETH": "0x88e6A0c2dDD26FEEb64F039a2c41296FcB3f5640",
        "USDT_WETH": "0x11b815efB8f581194ae79006d24E0d814B7697F6",
        "WBTC_WETH": "0x4585FE77225b41b697C938B018E2Ac67Ac5a20c0",
        "LINK_WETH": "0xa6Cc3C2531FdaA6Ae1A3CA84c2855806728693e8",
        "UNI_WETH": "0x1d42064Fc4Beb5F8aAF85F4617AE8b3b5B8Bd801",
        "DAI_USDC": "0x5777d92f208679DB4b9778590Fa3CAB3aC9e2168",
        "MATIC_WETH": "0x290A6a7460B308722B9dd9D2385D494c36CD0ad4",
        "PEPE_WETH": "0x11950D141ecbC3Ae932728b9562e3e7d9c69c7B7",
    },
    "arbitrum": {
        "USDC_WETH": "0xC31E54c7a869B9FcBEcc14563eC45E30952a2794",
        "USDT_WETH": "0x17c14D2c404D167802b16C450d3c99F88F2c4F4d",
        "ARB_WETH": "0x17c14D2c404D167802b16C450d3c99F88F2c4F4d",
    },
    "optimism": {
        "USDC_WETH": "0x03aF20bDAaFfB4cC0A521796a223f7D85e2aAc31",
        "OP_WETH": "0x687942108b8D286B52Fc2fB404a7916AF83Ea19e",
    },
    "base": {
        "USDC_WETH": "0xd0b53D9277642d899DF5C87A3966A349A798F224",
    },
    "polygon": {
        "USDC_WETH": "0x45dDa9cb7c25131DF268515131f647d726f50608",
        "MATIC_USDC": "0xa374094527e16732686ec1e97e57f668c8ad5f5f",
    },
    "bsc": {
        "USDC_WBNB": "0x2354ef4DF11afacb85a5C6f6966B5A326F7FB11f",
        "USDT_WBNB": "0x16b9a82891338f9bA80E2D6970FddA79D1eb0daE",
    },
}

# 稳定币列表
STABLECOINS = ["USDC", "USDT", "DAI", "BUSD", "TUSD"]

# 主要交易代币
MAJOR_TOKENS = ["ETH", "WETH", "WBTC", "BTC", "BNB", "MATIC", "AVAX", "SOL", "LINK", "UNI", "AAVE", "MKR", "ARB", "OP", "PEPE", "SHIB"]


# ============================================
# ABI
# ============================================

UNISWAP_V3_POOL_ABI = [
    {"inputs": [], "name": "slot0", "outputs": [
        {"internalType": "uint160", "name": "sqrtPriceX96", "type": "uint160"},
        {"internalType": "int24", "name": "tick", "type": "int24"}
    ], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "token0", "outputs": [{"internalType": "address", "name": "", "type": "address"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "token1", "outputs": [{"internalType": "address", "name": "", "type": "address"}], "stateMutability": "view", "type": "function"},
]

UNISWAP_V2_PAIR_ABI = [
    {"inputs": [], "name": "getReserves", "outputs": [
        {"internalType": "uint112", "name": "reserve0", "type": "uint112"},
        {"internalType": "uint112", "name": "reserve1", "type": "uint112"}
    ], "stateMutability": "view", "type": "function"},
]


class OnchainPriceService:
    """链上价格获取服务"""
    
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
        self.cache: Dict[str, Tuple[float, float]] = {}
        self.cache_ttl = 30
        self.price_cache: Dict[str, float] = {}  # {chain:symbol: price}
    
    async def __aenter__(self):
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10))
        return self
    
    async def __aexit__(self, *args):
        if self.session:
            await self.session.close()
    
    def _cache_key(self, chain: str, symbol: str) -> str:
        return f"{chain}:{symbol}"
    
    async def _eth_call(self, rpc_url: str, to: str, data: str, fallback_urls: list = None) -> Optional[str]:
        if not self.session:
            self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10))
        
        urls = [rpc_url] + (fallback_urls or [])
        
        for url in urls:
            try:
                async with self.session.post(url, json={
                    "jsonrpc": "2.0",
                    "method": "eth_call",
                    "params": [{"to": to, "data": data}, "latest"],
                    "id": 1
                }) as resp:
                    result = await resp.json()
                    if "result" in result and result["result"]:
                        return result["result"]
            except:
                continue
        return None
    
    async def get_v3_pool_price(self, rpc_url: str, pool_address: str, fallback_urls: list = None) -> Optional[float]:
        """获取 V3 池子价格"""
        result = await self._eth_call(rpc_url, pool_address, "0x3850c7bd", fallback_urls)
        if not result:
            return None
        try:
            sqrt_price_x96 = int(result[:66], 16)
            return (sqrt_price_x96 / (2 ** 96)) ** 2
        except:
            return None
    
    async def get_eth_price(self, chain: str) -> Optional[float]:
        """获取 ETH 价格"""
        key = self._cache_key(chain, "ETH")
        if key in self.price_cache:
            return self.price_cache[key]
        
        chain_config = get_chain_config(chain)
        if not chain_config:
            return None
        
        pools = DEX_POOLS.get(chain, {})
        if "USDC_WETH" not in pools:
            return None
        
        pool_address = pools["USDC_WETH"]
        rpc_url = chain_config.rpc_url
        fallback_urls = chain_config.rpc_fallback
        
        # 获取 token0
        token0_result = await self._eth_call(rpc_url, pool_address, "0x0dfe1681", fallback_urls)
        
        # 检查 token0 是否是 USDC
        usdc_addr = TOKEN_ADDRESSES.get(chain, {}).get("USDC", "").lower().replace("0x", "")
        is_usdc_token0 = False
        if token0_result:
            token0_addr = token0_result[-40:].lower()
            is_usdc_token0 = token0_addr == usdc_addr
        
        # 获取价格比率
        price_ratio = await self.get_v3_pool_price(rpc_url, pool_address, fallback_urls)
        if not price_ratio:
            return None
        
        # 计算价格
        if is_usdc_token0:
            eth_price = (10 ** 12) / price_ratio
        else:
            if price_ratio > 100:
                eth_price = price_ratio
            else:
                eth_price = price_ratio * (10 ** 12)
        
        self.price_cache[key] = eth_price
        return eth_price
    
    async def get_all_prices(self, chain: str) -> Dict[str, float]:
        """获取所有代币价格"""
        prices = {}
        
        # 稳定币
        for symbol in STABLECOINS:
            prices[symbol] = 1.0
        
        # ETH
        eth_price = await self.get_eth_price(chain)
        if eth_price:
            prices["ETH"] = eth_price
            prices["WETH"] = eth_price
        
        # 其他代币估算价格（基于 ETH）
        if eth_price:
            estimated_prices = {
                "WBTC": eth_price * 28,  # BTC ~ 28 ETH
                "BTC": eth_price * 28,
                "BNB": eth_price * 0.25,
                "MATIC": eth_price * 0.00035,
                "AVAX": eth_price * 0.015,
                "SOL": eth_price * 0.065,
                "LINK": eth_price * 0.006,
                "UNI": eth_price * 0.002,
                "AAVE": eth_price * 0.05,
                "MKR": eth_price * 0.15,
                "ARB": eth_price * 0.0005,
                "OP": eth_price * 0.0015,
                "PEPE": 0.00001,
                "SHIB": 0.00001,
                "DOGE": 0.15,
                "CAKE": 2.5,
                "JOE": 0.5,
                "GMX": 50,
                "CRV": 0.5,
                "COMP": 60,
                "SUSHI": 1.2,
                "SNX": 3,
            }
            prices.update(estimated_prices)
        
        return prices


_onchain_price_service: Optional[OnchainPriceService] = None


async def get_onchain_price_service() -> OnchainPriceService:
    global _onchain_price_service
    if _onchain_price_service is None:
        _onchain_price_service = OnchainPriceService()
        await _onchain_price_service.__aenter__()
    return _onchain_price_service
