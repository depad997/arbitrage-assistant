"""
交易构建模块 - Phase 2 执行能力核心组件

功能：
- DEX 交易构建（Uniswap V2/V3, PancakeSwap, SushiSwap 等）
- 跨链交易构建（LayerZero/Wormhole 消息格式）
- Gas 估算与优化
- Nonce 管理
- 交易类型：单链swap、跨链swap、闪电贷

支持的去中心化交易所：
- Uniswap V2/V3 (Ethereum, Arbitrum, Optimism, Base, etc.)
- PancakeSwap (BSC)
- SushiSwap (Multi-chain)
- QuickSwap (Polygon)
- Trader Joe (Avalanche)
- SpookySwap (Fantom)
"""

import os
import json
import logging
from typing import Dict, List, Optional, Tuple, Any, Union, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from decimal import Decimal
from abc import ABC, abstractmethod

import sys
import os as _os
_backend_dir = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from web3 import Web3
from web3.contract import Contract
from web3.types import Wei, ChecksumAddress

from config.settings import SUPPORTED_CHAINS, get_chain_config, ChainConfig

logger = logging.getLogger(__name__)


# ============================================
# 枚举和常量
# ============================================

class DEXType(Enum):
    """DEX 类型"""
    UNISWAP_V2 = "uniswap_v2"
    UNISWAP_V3 = "uniswap_v3"
    PANCAKESWAP = "pancakeswap"
    SUSHISWAP = "sushiswap"
    QUICKSWAP = "quickswap"
    TRADER_JOE = "trader_joe"
    SPOOKYSWAP = "spookyswap"
    CURVE = "curve"
    BALANCER = "balancer"


class TradeType(Enum):
    """交易类型"""
    EXACT_INPUT = "exact_input"      # 指定输入金额
    EXACT_OUTPUT = "exact_output"    # 指定输出金额


@dataclass
class SwapParams:
    """Swap 参数"""
    token_in: str                      # 输入代币地址
    token_out: str                     # 输出代币地址
    amount_in: Optional[int] = None   # 输入金额（最小单位）
    amount_out_min: Optional[int] = None  # 最小输出金额
    recipient: str = ""                # 接收地址
    deadline: Optional[int] = None    # 过期时间戳
    
    # Uniswap V3 专用
    fee: Optional[int] = None          # 手续费等级 (500, 3000, 10000)
    sqrt_price_limit: Optional[int] = None  # 价格限制


@dataclass
class RouteInfo:
    """路由信息"""
    dex: DEXType
    path: List[str]                   # 代币地址路径
    fees: Optional[List[int]] = None  # V3 手续费等级
    pool_address: Optional[str] = None


@dataclass
class QuoteResult:
    """报价结果"""
    token_in: str
    token_out: str
    amount_in: int
    amount_out: int
    price_impact: float
    route: List[RouteInfo]
    estimated_gas: int
    provider: str


@dataclass
class TransactionParams:
    """交易构建参数"""
    chain: str
    from_address: str
    to_address: str
    value: int = 0                    # 原生代币金额 (wei)
    data: str = ""                    # calldata
    gas_limit: int = 0
    gas_price: Optional[int] = None   # 预置则自动估算
    max_fee_per_gas: Optional[int] = None  # EIP-1559
    max_priority_fee_per_gas: Optional[int] = None
    nonce: Optional[int] = None
    chain_id: Optional[int] = None
    type: int = 2                    # 交易类型：2=EIP-1559, 0=Legacy


@dataclass
class CrossChainParams:
    """跨链交易参数"""
    source_chain: str
    target_chain: str
    bridge: str                       # "layerzero" or "wormhole"
    token_in: str
    amount: int
    min_amount_out: int              # 目标链最小收到金额
    recipient: str                   # 目标链接收地址
    relayer_fee: int = 0             # LayerZero 中继费


# ============================================
# DEX Router ABI
# ============================================

# Uniswap V2 Router ABI
UNISWAP_V2_ROUTER_ABI = [
    {
        "inputs": [
            {"internalType": "uint256", "name": "amountOut", "type": "uint256"},
            {"internalType": "address[]", "name": "path", "type": "address[]"}
        ],
        "name": "getAmountsOut",
        "outputs": [
            {"internalType": "uint256[]", "name": "amounts", "type": "uint256[]"}
        ],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [
            {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
            {"internalType": "address[]", "name": "path", "type": "address[]"}
        ],
        "name": "getAmountsIn",
        "outputs": [
            {"internalType": "uint256[]", "name": "amounts", "type": "uint256[]"}
        ],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [
            {"internalType": "uint256", "name": "amountOutMin", "type": "uint256"},
            {"internalType": "address[]", "name": "path", "type": "address[]"},
            {"internalType": "address", "name": "to", "type": "address"},
            {"internalType": "uint256", "name": "deadline", "type": "uint256"}
        ],
        "name": "swapExactETHForTokens",
        "outputs": [
            {"internalType": "uint256[]", "name": "amounts", "type": "uint256[]"}
        ],
        "stateMutability": "payable",
        "type": "function"
    },
    {
        "inputs": [
            {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
            {"internalType": "uint256", "name": "amountOutMin", "type": "uint256"},
            {"internalType": "address[]", "name": "path", "type": "address[]"},
            {"internalType": "address", "name": "to", "type": "address"},
            {"internalType": "uint256", "name": "deadline", "type": "uint256"}
        ],
        "name": "swapExactTokensForTokens",
        "outputs": [
            {"internalType": "uint256[]", "name": "amounts", "type": "uint256[]"}
        ],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "inputs": [
            {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
            {"internalType": "uint256", "name": "amountOutMin", "type": "uint256"},
            {"internalType": "address[]", "name": "path", "type": "address[]"},
            {"internalType": "address", "name": "to", "type": "address"},
            {"internalType": "uint256", "name": "deadline", "type": "uint256"}
        ],
        "name": "swapExactTokensForETH",
        "outputs": [
            {"internalType": "uint256[]", "name": "amounts", "type": "uint256[]"}
        ],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "inputs": [
            {"internalType": "uint256", "name": "amountOutMin", "type": "uint256"},
            {"internalType": "address[]", "name": "path", "type": "address[]"},
            {"internalType": "address", "name": "to", "type": "address"},
            {"internalType": "uint256", "name": "deadline", "type": "uint256"}
        ],
        "name": "swapExactETHForTokensSupportingFeeOnTransferTokens",
        "outputs": [],
        "stateMutability": "payable",
        "type": "function"
    },
    {
        "inputs": [
            {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
            {"internalType": "uint256", "name": "amountOutMin", "type": "uint256"},
            {"internalType": "address[]", "name": "path", "type": "address[]"},
            {"internalType": "address", "name": "to", "type": "address"},
            {"internalType": "uint256", "name": "deadline", "type": "uint256"}
        ],
        "name": "swapExactTokensForTokensSupportingFeeOnTransferTokens",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    }
]

# Uniswap V3 Router ABI (Quoter & SwapRouter)
UNISWAP_V3_ROUTER_ABI = [
    {
        "inputs": [
            {"internalType": "bytes", "name": "path", "type": "bytes"},
            {"internalType": "uint24", "name": "fee", "type": "uint24"},
            {"internalType": "address", "name": "recipient", "type": "address"},
            {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
            {"internalType": "uint256", "name": "amountOutMinimum", "type": "uint256"}
        ],
        "name": "exactInput",
        "outputs": [
            {"internalType": "uint256", "name": "amountOut", "type": "uint256"}
        ],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "inputs": [
            {
                "components": [
                    {"internalType": "address", "name": "tokenIn", "type": "address"},
                    {"internalType": "address", "name": "tokenOut", "type": "address"},
                    {"internalType": "uint24", "name": "fee", "type": "uint24"},
                    {"internalType": "address", "name": "recipient", "type": "address"},
                    {"internalType": "uint256", "name": "deadline", "type": "uint256"},
                    {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
                    {"internalType": "uint256", "name": "amountOutMinimum", "type": "uint256"},
                    {"internalType": "uint160", "name": "sqrtPriceLimitX96", "type": "uint160"}
                ],
                "internalType": "struct ISwapRouter.ExactInputSingleParams",
                "name": "params",
                "type": "tuple"
            }
        ],
        "name": "exactInputSingle",
        "outputs": [
            {"internalType": "uint256", "name": "amountOut", "type": "uint256"}
        ],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "inputs": [
            {
                "components": [
                    {"internalType": "address", "name": "tokenIn", "type": "address"},
                    {"internalType": "address", "name": "tokenOut", "type": "address"},
                    {"internalType": "uint24", "name": "fee", "type": "uint24"},
                    {"internalType": "address", "name": "recipient", "type": "address"},
                    {"internalType": "uint256", "name": "deadline", "type": "uint256"},
                    {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
                    {"internalType": "uint256", "name": "amountOutMinimum", "type": "uint256"},
                    {"internalType": "uint160", "name": "sqrtPriceLimitX96", "type": "uint160"}
                ],
                "internalType": "struct ISwapRouter.ExactOutputSingleParams",
                "name": "params",
                "type": "tuple"
            }
        ],
        "name": "exactOutputSingle",
        "outputs": [
            {"internalType": "uint256", "name": "amountIn", "type": "uint256"}
        ],
        "stateMutability": "nonpayable",
        "type": "function"
    }
]

# Quoter V2 ABI
UNISWAP_V3_QUOTER_ABI = [
    {
        "inputs": [
            {"internalType": "bytes", "name": "path", "type": "bytes"},
            {"internalType": "uint256", "name": "amountIn", "type": "uint256"}
        ],
        "name": "quoteExactInput",
        "outputs": [
            {"internalType": "uint256", "name": "amountOut", "type": "uint256"}
        ],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "inputs": [
            {
                "components": [
                    {"internalType": "address", "name": "tokenIn", "type": "address"},
                    {"internalType": "address", "name": "tokenOut", "type": "address"},
                    {"internalType": "uint24", "name": "fee", "type": "uint24"},
                    {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
                    {"internalType": "uint160", "name": "sqrtPriceLimitX96", "type": "uint160"}
                ],
                "internalType": "struct IQuoterV2.QuoteExactInputSingleParams",
                "name": "params",
                "type": "tuple"
            }
        ],
        "name": "quoteExactInputSingle",
        "outputs": [
            {"internalType": "uint256", "name": "amountOut", "type": "uint256"},
            {"internalType": "uint160[]", "name": "sqrtPriceX96AfterList", "type": "uint160[]"},
            {"internalType": "uint32[]", "name": "initializedTicksCrossedList", "type": "uint32[]"},
            {"internalType": "uint256", "name": "gasEstimate", "type": "uint256"}
        ],
        "stateMutability": "nonpayable",
        "type": "function"
    }
]

# ERC20 ABI
ERC20_ABI = [
    {
        "inputs": [
            {"internalType": "address", "name": "spender", "type": "address"},
            {"internalType": "uint256", "name": "amount", "type": "uint256"}
        ],
        "name": "approve",
        "outputs": [{"internalType": "bool", "name": "", "type": "bool"}],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "inputs": [{"internalType": "address", "name": "account", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [
            {"internalType": "address", "name": "owner", "type": "address"},
            {"internalType": "address", "name": "spender", "type": "address"}
        ],
        "name": "allowance",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [],
        "name": "decimals",
        "outputs": [{"internalType": "uint8", "name": "", "type": "uint8"}],
        "stateMutability": "view",
        "type": "function"
    }
]


# ============================================
# DEX 路由器配置
# ============================================

@dataclass
class DEXConfig:
    """DEX 配置"""
    name: str
    router_address: str
    dex_type: DEXType  # 使用 dex_type 避免与内置 type 冲突
    chain: str
    quoter_address: Optional[str] = None  # V3 才有
    factory_address: Optional[str] = None


# 各链的 DEX Router 地址
DEX_ROUTERS: Dict[str, Dict[str, DEXConfig]] = {
    "ethereum": {
        "uniswap_v3": DEXConfig(
            name="Uniswap V3",
            router_address="0x68b3465833fb72A70ecDF485E0e4C7bD8665Fc45",
            quoter_address="0xb27308f9F90D607463bb33eA1BeBb41C27CE5AB6",
            dex_type=DEXType.UNISWAP_V3,
            chain="ethereum"
        ),
        "uniswap_v2": DEXConfig(
            name="Uniswap V2",
            router_address="0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D",
            dex_type=DEXType.UNISWAP_V2,
            chain="ethereum"
        ),
        "sushiswap": DEXConfig(
            name="SushiSwap",
            router_address="0xd9e1cE17f2641f24aE83637ab66a2cca9C378B9F",
            dex_type=DEXType.SUSHISWAP,
            chain="ethereum"
        )
    },
    "arbitrum": {
        "uniswap_v3": DEXConfig(
            name="Uniswap V3",
            router_address="0x68b3465833fb72A70ecDF485E0e4C7bD8665Fc45",
            quoter_address="0xb27308f9F90D607463bb33eA1BeBb41C27CE5AB6",
            dex_type=DEXType.UNISWAP_V3,
            chain="arbitrum"
        ),
        "uniswap_v2": DEXConfig(
            name="Sushiswap",
            router_address="0x1b02dA8Cb0d097eB8D57A175b88c7D8b47997506",
            dex_type=DEXType.UNISWAP_V2,
            chain="arbitrum"
        )
    },
    "optimism": {
        "uniswap_v3": DEXConfig(
            name="Uniswap V3",
            router_address="0x68b3465833fb72A70ecDF485E0e4C7bD8665Fc45",
            quoter_address="0xb27308f9F90D607463bb33eA1BeBb41C27CE5AB6",
            dex_type=DEXType.UNISWAP_V3,
            chain="optimism"
        ),
        "uniswap_v2": DEXConfig(
            name="Uniswap V2",
            router_address="0x4752ba5DBc23f44D87826276BF6Fd6b1C372aD24",
            dex_type=DEXType.UNISWAP_V2,
            chain="optimism"
        )
    },
    "base": {
        "uniswap_v3": DEXConfig(
            name="Uniswap V3",
            router_address="0x2626664c2603336E54B2768D244d6297B30eA180",
            quoter_address="0x3d4e44Eb1374240CE5F1B871ab261CD16335B76a",
            dex_type=DEXType.UNISWAP_V3,
            chain="base"
        )
    },
    "bsc": {
        "pancakeswap": DEXConfig(
            name="PancakeSwap",
            router_address="0x10ED43C718714eb63d5aA57B78B54704E256024E",
            dex_type=DEXType.PANCAKESWAP,
            chain="bsc"
        ),
        "sushiswap": DEXConfig(
            name="SushiSwap",
            router_address="0x1b02dA8Cb0d097eB8D57A175b88c7D8b47997506",
            dex_type=DEXType.SUSHISWAP,
            chain="bsc"
        )
    },
    "polygon": {
        "quickswap": DEXConfig(
            name="QuickSwap",
            router_address="0xa5E0829CaCEd8fFDD4De3c43696c57F7D7A678ff",
            dex_type=DEXType.QUICKSWAP,
            chain="polygon"
        ),
        "uniswap_v3": DEXConfig(
            name="Uniswap V3",
            router_address="0x68b3465833fb72A70ecDF485E0e4C7bD8665Fc45",
            quoter_address="0xb27308f9F90D607463bb33eA1BeBb41C27CE5AB6",
            dex_type=DEXType.UNISWAP_V3,
            chain="polygon"
        )
    },
    "avalanche": {
        "trader_joe": DEXConfig(
            name="Trader Joe",
            router_address="0x0FB54156B8b2D0d735174d2aDf77E0A7bF2f1193",
            dex_type=DEXType.TRADER_JOE,
            chain="avalanche"
        )
    },
    "fantom": {
        "spookyswap": DEXConfig(
            name="SpookySwap",
            router_address="0xF491e7B69E4244ad4002BC14e878f342A44406Ec",
            dex_type=DEXType.SPOOKYSWAP,
            chain="fantom"
        )
    }
}

# WETH 地址映射
WETH_ADDRESSES: Dict[str, str] = {
    "ethereum": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
    "arbitrum": "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1",
    "optimism": "0x4200000000000000000000000000000000000042",
    "base": "0x4200000000000000000000000000000000000006",
    "polygon": "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270",  # WMATIC
    "bsc": "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c",  # WBNB
    "avalanche": "0xB31f66AA3C1e785363F0875A1B74D27e9627F6D0",  # WAVAX
    "fantom": "0x21be370D5312f44cB42ce377BC9b8a0cEF1A4C83"  # WFTM
}

# LayerZero Endpoint ABI (简化)
LAYERZERO_ENDPOINT_ABI = [
    {
        "inputs": [
            {"internalType": "uint16", "name": "_dstChainId", "type": "uint16"},
            {"internalType": "bytes", "name": "_destination", "type": "bytes"},
            {"internalType": "bytes", "name": "_payload", "type": "bytes"},
            {"internalType": "bool", "name": "_payInZRO", "type": "bool"},
            {"internalType": "bytes", "name": "_adapterParams", "type": "bytes"}
        ],
        "name": "send",
        "outputs": [],
        "stateMutability": "payable",
        "type": "function"
    },
    {
        "inputs": [
            {"internalType": "uint16", "name": "_dstChainId", "type": "uint16"},
            {"internalType": "address", "name": "_userApplication", "type": "address"},
            {"internalType": "bytes", "name": "_payload", "type": "bytes"}
        ],
        "name": "estimateFees",
        "outputs": [
            {"internalType": "uint256", "name": "nativeFee", "type": "uint256"},
            {"internalType": "uint256", "name": "zroFee", "type": "uint256"}
        ],
        "stateMutability": "view",
        "type": "function"
    }
]

# Wormhole Core Bridge ABI (简化)
WORMHOLE_BRIDGE_ABI = [
    {
        "inputs": [
            {"internalType": "uint16", "name": "recipientChain", "type": "uint16"},
            {"internalType": "bytes32", "name": "recipient", "type": "bytes32"},
            {"internalType": "uint256", "name": "amount", "type": "uint256"},
            {"internalType": "uint256", "name": "nChainId", "type": "uint256"},
            {"internalType": "address", "name": "relayerFee", "type": "address"}
        ],
        "name": "wrapAndTransferETH",
        "outputs": [{"internalType": "uint64", "name": "sequence", "type": "uint64"}],
        "stateMutability": "payable",
        "type": "function"
    },
    {
        "inputs": [
            {"internalType": "uint16", "name": "recipientChain", "type": "uint16"},
            {"internalType": "bytes32", "name": "recipient", "type": "bytes32"},
            {"internalType": "uint256", "name": "amount", "type": "uint256"},
            {"internalType": "address", "name": "token", "type": "address"},
            {"internalType": "uint256", "name": "nChainId", "type": "uint256"},
            {"internalType": "uint256", "name": "relayerFee", "type": "uint256"}
        ],
        "name": "transferTokens",
        "outputs": [{"internalType": "uint64", "name": "sequence", "type": "uint64"}],
        "stateMutability": "payable",
        "type": "function"
    }
]

# LayerZero 端点地址
LAYERZERO_ENDPOINTS: Dict[str, str] = {
    "ethereum": "0x66A71Dcef29A0fFBDBE3c6a460a3B5BC225cd675",
    "bsc": "0x3c2269811836af69497E5F501Abe0f789cD70E95",
    "arbitrum": "0x3c2269811836af69497E5F501Abe0f789cD70E95",
    "optimism": "0x3c2269811836af69497E5F501Abe0f789cD70E95",
    "polygon": "0x3c2269811836af69497E5F501Abe0f789cD70E95",
    "avalanche": "0x3c2269811836af69497E5F501Abe0f789cD70E95",
    "base": "0x1a44076050125825900ef736555ea139E6816Bb0"
}


# ============================================
# Gas 估算器
# ============================================

class GasEstimator:
    """Gas 估算器"""
    
    def __init__(self, web3: Web3, chain: str):
        self.web3 = web3
        self.chain = chain
    
    async def get_gas_price(self) -> Tuple[int, int]:
        """
        获取当前 Gas 价格
        
        Returns:
            (gas_price, max_priority_fee_per_gas)
        """
        try:
            # 尝试 EIP-1559
            fee_history = await self.web3.eth.fee_history(1, 'latest', [50])
            base_fee = fee_history['baseFeePerGas'][0]
            
            # 优先费用
            max_priority_fee = await self.web3.eth.max_priority_fee()
            
            # 最终费用
            max_fee = base_fee * 2 + max_priority_fee
            
            return max_fee, max_priority_fee
        except Exception:
            # 回退到 Legacy
            gas_price = await self.web3.eth.gas_price()
            return gas_price, 0
    
    def estimate_gas(self, tx_dict: Dict) -> int:
        """估算 Gas"""
        try:
            return self.web3.eth.estimate_gas(tx_dict)
        except Exception as e:
            logger.warning(f"Gas estimation failed: {e}")
            return 500000  # 默认值
    
    def estimate_eip1559_gas(self, tx_dict: Dict) -> int:
        """估算 EIP-1559 交易 Gas"""
        return self.estimate_gas(tx_dict)
    
    def calculate_gas_cost(self, gas_limit: int, gas_price: int) -> int:
        """计算 Gas 成本（Wei）"""
        return gas_limit * gas_price


# ============================================
# Nonce 管理器
# ============================================

class NonceManager:
    """Nonce 管理器"""
    
    def __init__(self, web3: Web3, address: str):
        self.web3 = web3
        self.address = address
        self._nonce_cache: Optional[int] = None
        self._pending_nonces: List[int] = []
    
    def get_next_nonce(self, force_refresh: bool = False) -> int:
        """
        获取下一个可用的 Nonce
        
        Args:
            force_refresh: 强制刷新缓存
            
        Returns:
            下一个 Nonce
        """
        if self._nonce_cache is None or force_refresh:
            self._nonce_cache = self.web3.eth.get_transaction_count(self.address)
        
        # 找到一个未使用的 Nonce
        while self._nonce_cache in self._pending_nonces:
            self._nonce_cache += 1
        
        return self._nonce_cache
    
    def mark_used(self, nonce: int):
        """标记 Nonce 已使用"""
        self._pending_nonces.append(nonce)
        if self._nonce_cache is None or nonce < self._nonce_cache:
            self._nonce_cache = nonce + 1
    
    def clear_pending(self):
        """清除已完成交易的 Nonce"""
        try:
            current_nonce = self.web3.eth.get_transaction_count(self.address)
            self._pending_nonces = [n for n in self._pending_nonces if n >= current_nonce]
        except Exception:
            pass
    
    def reset(self):
        """重置 Nonce 管理器"""
        self._nonce_cache = None
        self._pending_nonces = []


# ============================================
# DEX 交易构建器基类
# ============================================

class BaseDEXBuilder(ABC):
    """DEX 交易构建器基类"""
    
    def __init__(self, web3: Web3, dex_config: DEXConfig):
        self.web3 = web3
        self.dex_config = dex_config
        self.router_contract = web3.eth.contract(
            address=Web3.to_checksum_address(dex_config.router_address),
            abi=UNISWAP_V2_ROUTER_ABI if dex_config.type in [DEXType.UNISWAP_V2, DEXType.PANCAKESWAP, DEXType.SUSHISWAP, DEXType.QUICKSWAP, DEXType.TRADER_JOE, DEXType.SPOOKYSWAP] else UNISWAP_V3_ROUTER_ABI
        )
    
    @abstractmethod
    def build_swap(self, params: SwapParams, **kwargs) -> Dict:
        """构建 swap 交易"""
        pass
    
    def get_token_balance(self, token_address: str, owner: str) -> int:
        """获取代币余额"""
        contract = self.web3.eth.contract(
            address=Web3.to_checksum_address(token_address),
            abi=ERC20_ABI
        )
        return contract.functions.balanceOf(owner).call()
    
    def get_allowance(self, token_address: str, owner: str, spender: str) -> int:
        """获取授权额度"""
        contract = self.web3.eth.contract(
            address=Web3.to_checksum_address(token_address),
            abi=ERC20_ABI
        )
        return contract.functions.allowance(owner, spender).call()
    
    def approve_token(self, token_address: str, amount: int, owner: str) -> Dict:
        """构建授权交易"""
        contract = self.web3.eth.contract(
            address=Web3.to_checksum_address(token_address),
            abi=ERC20_ABI
        )
        return contract.functions.approve(
            self.dex_config.router_address,
            amount
        ).build_transaction({
            'from': owner
        })


# ============================================
# Uniswap V2 构建器
# ============================================

class UniswapV2Builder(BaseDEXBuilder):
    """Uniswap V2 / SushiSwap / PancakeSwap 构建器"""
    
    def build_swap(self, params: SwapParams, **kwargs) -> Dict:
        """
        构建 V2 swap 交易
        
        Args:
            params: Swap 参数
            
        Returns:
            交易参数字典
        """
        deadline = params.deadline or int(datetime.now().timestamp()) + 600
        path = [Web3.to_checksum_address(a) for a in params.path]
        recipient = Web3.to_checksum_address(params.recipient)
        
        # 确定交易类型
        token_in = params.token_in.lower()
        token_out = params.token_out.lower()
        weth_address = WETH_ADDRESSES.get(self.dex_config.chain, "").lower()
        
        is_native_in = token_in == weth_address
        is_native_out = token_out == weth_address
        
        # 选择合约函数
        if is_native_in:
            # ETH -> Token
            fn = self.router_contract.functions.swapExactETHForTokens(
                params.amount_out_min or 0,
                path,
                recipient,
                deadline
            )
            tx_data = fn.buildTransaction({
                'value': params.amount_in
            })
        elif is_native_out:
            # Token -> ETH
            fn = self.router_contract.functions.swapExactTokensForETH(
                params.amount_in,
                params.amount_out_min or 0,
                path,
                recipient,
                deadline
            )
            tx_data = fn.buildTransaction({
                'from': recipient
            })
        else:
            # Token -> Token
            fn = self.router_contract.functions.swapExactTokensForTokens(
                params.amount_in,
                params.amount_out_min or 0,
                path,
                recipient,
                deadline
            )
            tx_data = fn.buildTransaction({
                'from': recipient
            })
        
        return tx_data
    
    def get_quote(self, amount_in: int, path: List[str]) -> Tuple[int, int]:
        """
        获取报价
        
        Returns:
            (amount_out, price_impact)
        """
        path = [Web3.to_checksum_address(a) for a in path]
        amounts = self.router_contract.functions.getAmountsOut(amount_in, path).call()
        amount_out = amounts[-1]
        
        # 简单计算价格影响
        if amount_out > 0 and len(amounts) > 1:
            price_impact = abs(amounts[0] - amounts[-1]) / amounts[0]
        else:
            price_impact = 0
        
        return amount_out, price_impact


# ============================================
# Uniswap V3 构建器
# ============================================

class UniswapV3Builder(BaseDEXBuilder):
    """Uniswap V3 构建器"""
    
    def __init__(self, web3: Web3, dex_config: DEXConfig):
        super().__init__(web3, dex_config)
        
        if dex_config.quoter_address:
            self.quoter_contract = web3.eth.contract(
                address=Web3.to_checksum_address(dex_config.quoter_address),
                abi=UNISWAP_V3_QUOTER_ABI
            )
        else:
            self.quoter_contract = None
    
    def _build_path_bytes(self, path: List[str], fees: List[int]) -> bytes:
        """
        构建 V3 路径字节
        
        path: [token0, token1, token2, ...]
        fees: [fee01, fee12, ...]
        """
        # V3 path 格式: token_in, fee, token_out, fee, token_out...
        assert len(path) == len(fees) + 1
        
        result = b''
        for i, token in enumerate(path):
            result += Web3.to_checksum_address(token).encode('utf-8')[2:]
            if i < len(fees):
                result += fees[i].to_bytes(3, 'big')
        
        return result
    
    def build_swap(self, params: SwapParams, **kwargs) -> Dict:
        """
        构建 V3 swap 交易
        
        Args:
            params: Swap 参数
            kwargs:
                - path: 代币路径
                - fees: 手续费等级列表
        """
        path = kwargs.get('path', [params.token_in, params.token_out])
        fees = kwargs.get('fees', [params.fee] if params.fee else [3000])
        deadline = params.deadline or int(datetime.now().timestamp()) + 600
        recipient = Web3.to_checksum_address(params.recipient)
        
        # 单跳 vs 多跳
        if len(path) == 2:
            # 单跳 swap
            fn = self.router_contract.functions.exactInputSingle({
                'tokenIn': Web3.to_checksum_address(path[0]),
                'tokenOut': Web3.to_checksum_address(path[1]),
                'fee': fees[0],
                'recipient': recipient,
                'deadline': deadline,
                'amountIn': params.amount_in,
                'amountOutMinimum': params.amount_out_min or 0,
                'sqrtPriceLimitX96': params.sqrt_price_limit or 0
            })
        else:
            # 多跳 swap
            path_bytes = self._build_path_bytes(path, fees)
            fn = self.router_contract.functions.exactInput({
                'path': path_bytes,
                'fee': fees[0],
                'recipient': recipient,
                'amountIn': params.amount_in,
                'amountOutMinimum': params.amount_out_min or 0
            })
        
        return fn.buildTransaction({
            'from': recipient
        })
    
    async def get_quote(
        self,
        amount_in: int,
        token_in: str,
        token_out: str,
        fee: int = 3000
    ) -> Tuple[int, int]:
        """
        获取 V3 报价
        
        Returns:
            (amount_out, gas_estimate)
        """
        if not self.quoter_contract:
            raise ValueError("Quoter not configured")
        
        try:
            # 需要先给 Quoter 授权或发送查询
            # 这里简化处理，假设可以直接查询
            token_in_checksum = Web3.to_checksum_address(token_in)
            token_out_checksum = Web3.to_checksum_address(token_out)
            
            # 构造查询参数
            params = {
                'tokenIn': token_in_checksum,
                'tokenOut': token_out_checksum,
                'fee': fee,
                'amountIn': amount_in,
                'sqrtPriceLimitX96': 0
            }
            
            # 注意：V3 Quoter 是 view 函数，但需要调用者支付 gas
            # 这里需要使用 call 来模拟
            amount_out = self.quoter_contract.functions.quoteExactInputSingle(
                params
            ).call()
            
            return amount_out, 150000  # 估算 gas
        except Exception as e:
            logger.error(f"Quote failed: {e}")
            return 0, 0


# ============================================
# 主交易构建器
# ============================================

class TransactionBuilder:
    """
    主交易构建器
    
    统一管理所有 DEX 的交易构建
    """
    
    def __init__(self, chain: str, web3: Optional[Web3] = None):
        """
        初始化交易构建器
        
        Args:
            chain: 链名称
            web3: Web3 实例
        """
        self.chain = chain
        self.web3 = web3 or self._create_web3()
        self.config = get_chain_config(chain)
        
        # 初始化 Gas 估算器
        self.gas_estimator = GasEstimator(self.web3, chain)
        
        # 初始化 Nonce 管理器
        self._nonce_manager: Optional[NonceManager] = None
        
        # DEX 构建器
        self._dex_builders: Dict[str, BaseDEXBuilder] = {}
        self._init_dex_builders()
    
    def _create_web3(self) -> Web3:
        """创建 Web3 实例"""
        config = get_chain_config(self.chain)
        return Web3(Web3.HTTPProvider(config.rpc_url))
    
    def _init_dex_builders(self):
        """初始化 DEX 构建器"""
        if self.chain in DEX_ROUTERS:
            for dex_name, dex_config in DEX_ROUTERS[self.chain].items():
                if dex_config.type in [DEXType.UNISWAP_V2, DEXType.PANCAKESWAP, DEXType.SUSHISWAP, DEXType.QUICKSWAP, DEXType.TRADER_JOE, DEXType.SPOOKYSWAP]:
                    self._dex_builders[dex_name] = UniswapV2Builder(self.web3, dex_config)
                elif dex_config.type == DEXType.UNISWAP_V3:
                    self._dex_builders[dex_name] = UniswapV3Builder(self.web3, dex_config)
    
    @property
    def nonce_manager(self) -> NonceManager:
        """获取 Nonce 管理器"""
        if self._nonce_manager is None:
            raise ValueError("Address not set, call set_sender() first")
        return self._nonce_manager
    
    def set_sender(self, address: str):
        """设置发送者地址"""
        self._nonce_manager = NonceManager(self.web3, address)
    
    def get_dex_builder(self, dex_name: str) -> Optional[BaseDEXBuilder]:
        """获取 DEX 构建器"""
        return self._dex_builders.get(dex_name)
    
    def list_available_dex(self) -> List[str]:
        """列出可用的 DEX"""
        return list(self._dex_builders.keys())
    
    async def build_swap_transaction(
        self,
        dex_name: str,
        params: SwapParams,
        sender: str,
        gas_price: Optional[int] = None,
        nonce: Optional[int] = None,
        **kwargs
    ) -> TransactionParams:
        """
        构建 Swap 交易
        
        Args:
            dex_name: DEX 名称 (e.g., "uniswap_v3", "pancakeswap")
            params: Swap 参数
            sender: 发送者地址
            gas_price: Gas 价格
            nonce: Nonce
            
        Returns:
            TransactionParams 对象
        """
        builder = self.get_dex_builder(dex_name)
        if not builder:
            raise ValueError(f"Unknown DEX: {dex_name}")
        
        # 构建基础交易
        tx_dict = builder.build_swap(params, **kwargs)
        tx_dict['from'] = Web3.to_checksum_address(sender)
        tx_dict['to'] = Web3.to_checksum_address(builder.dex_config.router_address)
        
        # 估算 Gas
        if tx_dict.get('gas', 0) == 0:
            try:
                tx_dict['gas'] = self.gas_estimator.estimate_gas(tx_dict)
            except Exception as e:
                logger.warning(f"Gas estimation failed: {e}")
                tx_dict['gas'] = 300000
        
        # 设置 Gas 价格
        if gas_price is None:
            max_fee, priority_fee = await self.gas_estimator.get_gas_price()
            tx_dict['maxFeePerGas'] = max_fee
            tx_dict['maxPriorityFeePerGas'] = priority_fee
        else:
            tx_dict['gasPrice'] = gas_price
        
        # 设置 Nonce
        if nonce is None:
            nonce = self.nonce_manager.get_next_nonce()
        tx_dict['nonce'] = nonce
        
        # 设置 Chain ID
        tx_dict['chainId'] = self.config.chain_id
        
        # 设置交易类型
        tx_dict['type'] = 2 if 'maxFeePerGas' in tx_dict else 0
        
        return TransactionParams(
            chain=self.chain,
            from_address=sender,
            to_address=tx_dict['to'],
            value=tx_dict.get('value', 0),
            data=tx_dict.get('data', ''),
            gas_limit=tx_dict.get('gas', 0),
            gas_price=tx_dict.get('gasPrice'),
            max_fee_per_gas=tx_dict.get('maxFeePerGas'),
            max_priority_fee_per_gas=tx_dict.get('maxPriorityFeePerGas'),
            nonce=nonce,
            chain_id=self.config.chain_id,
            type=tx_dict['type']
        )
    
    async def build_approve_transaction(
        self,
        token_address: str,
        amount: int,
        sender: str,
        spender: str,
        nonce: Optional[int] = None
    ) -> TransactionParams:
        """
        构建授权交易
        
        Args:
            token_address: 代币地址
            amount: 授权数量
            sender: 发送者地址
            spender: 授权给谁
            nonce: Nonce
        """
        token_contract = self.web3.eth.contract(
            address=Web3.to_checksum_address(token_address),
            abi=ERC20_ABI
        )
        
        tx_dict = token_contract.functions.approve(
            Web3.to_checksum_address(spender),
            amount
        ).build_transaction({
            'from': Web3.to_checksum_address(sender)
        })
        
        # 估算 Gas
        try:
            tx_dict['gas'] = self.gas_estimator.estimate_gas(tx_dict)
        except Exception:
            tx_dict['gas'] = 100000
        
        # Gas 价格
        max_fee, priority_fee = await self.gas_estimator.get_gas_price()
        tx_dict['maxFeePerGas'] = max_fee
        tx_dict['maxPriorityFeePerGas'] = priority_fee
        
        # Nonce
        if nonce is None:
            nonce = self.nonce_manager.get_next_nonce()
        tx_dict['nonce'] = nonce
        
        tx_dict['chainId'] = self.config.chain_id
        tx_dict['type'] = 2
        
        return TransactionParams(
            chain=self.chain,
            from_address=sender,
            to_address=Web3.to_checksum_address(token_address),
            value=0,
            data=tx_dict['data'],
            gas_limit=tx_dict['gas'],
            max_fee_per_gas=max_fee,
            max_priority_fee_per_gas=priority_fee,
            nonce=nonce,
            chain_id=self.config.chain_id,
            type=2
        )
    
    def estimate_swap_gas(
        self,
        dex_name: str,
        params: SwapParams,
        sender: str
    ) -> int:
        """估算 Swap 交易的 Gas"""
        builder = self.get_dex_builder(dex_name)
        if not builder:
            return 0
        
        tx_dict = builder.build_swap(params)
        tx_dict['from'] = Web3.to_checksum_address(sender)
        
        return self.gas_estimator.estimate_gas(tx_dict)
    
    def check_allowance(
        self,
        token_address: str,
        owner: str,
        spender: str,
        required_amount: int
    ) -> bool:
        """检查授权额度是否足够"""
        contract = self.web3.eth.contract(
            address=Web3.to_checksum_address(token_address),
            abi=ERC20_ABI
        )
        allowance = contract.functions.allowance(owner, spender).call()
        return allowance >= required_amount


# ============================================
# 跨链交易构建器
# ============================================

class CrossChainTransactionBuilder:
    """
    跨链交易构建器
    
    支持 LayerZero 和 Wormhole
    """
    
    def __init__(self, source_chain: str, target_chain: str):
        """
        初始化跨链交易构建器
        
        Args:
            source_chain: 源链
            target_chain: 目标链
        """
        self.source_chain = source_chain
        self.target_chain = target_chain
        
        source_config = get_chain_config(source_chain)
        self.source_web3 = Web3(Web3.HTTPProvider(source_config.rpc_url))
        
        # LayerZero Endpoint
        if source_chain in LAYERZERO_ENDPOINTS:
            self.lz_endpoint = self.source_web3.eth.contract(
                address=Web3.to_checksum_address(LAYERZERO_ENDPOINTS[source_chain]),
                abi=LAYERZERO_ENDPOINT_ABI
            )
        else:
            self.lz_endpoint = None
    
    def estimate_layerzero_fee(
        self,
        payload: bytes,
        pay_in_zro: bool = False
    ) -> Tuple[int, int]:
        """
        估算 LayerZero 费用
        
        Returns:
            (native_fee, zro_fee)
        """
        if not self.lz_endpoint:
            raise ValueError(f"LayerZero not supported on {self.source_chain}")
        
        source_config = get_chain_config(self.source_chain)
        target_config = get_chain_config(self.target_chain)
        
        try:
            fees = self.lz_endpoint.functions.estimateFees(
                target_config.layerzero_endpoint_id,
                "0x0000000000000000000000000000000000000000",  # placeholder
                payload,
                pay_in_zro,
                "0x"  # default adapter params
            ).call()
            return fees
        except Exception as e:
            logger.error(f"Fee estimation failed: {e}")
            return 0, 0
    
    def build_layerzero_send_transaction(
        self,
        token_address: str,
        amount: int,
        recipient_address: str,  # 目标链接收地址
        min_amount_out: int,
        gas_limit: int = 200000,
        gas_price: Optional[int] = None,
        nonce: Optional[int] = None
    ) -> TransactionParams:
        """
        构建 LayerZero 跨链交易
        
        Args:
            token_address: 代币地址
            amount: 数量
            recipient_address: 目标链接收地址
            min_amount_out: 最小输出
            gas_limit: Gas 限制
            gas_price: Gas 价格
            nonce: Nonce
        """
        if not self.lz_endpoint:
            raise ValueError("LayerZero not configured")
        
        # 目标链配置
        target_config = get_chain_config(self.target_chain)
        
        # 构造 payload（这里简化，实际需要编码具体的 swap 指令）
        # 实际项目中需要在目标链部署对应的接收合约
        payload = self._encode_oft_payload(recipient_address, min_amount_out)
        
        # 估算费用
        native_fee, zro_fee = self.estimate_layerzero_fee(payload)
        
        # 适配器参数（指定目标链的 Gas）
        adapter_params = self._encode_adapter_params(gas_limit)
        
        # 构建交易
        source_config = get_chain_config(self.source_chain)
        
        tx_dict = self.lz_endpoint.functions.send(
            target_config.layerzero_endpoint_id,
            recipient_address.encode(),  # 目标链地址
            payload,
            False,  # payInZRO
            adapter_params
        ).buildTransaction({
            'value': native_fee + amount  # Fee + 跨链金额（如果是 native）
        })
        
        # Gas 价格
        if gas_price is None:
            gas_price = self.source_web3.eth.gas_price
        tx_dict['gasPrice'] = gas_price
        
        # Nonce
        if nonce is None:
            nonce = self.source_web3.eth.get_transaction_count(tx_dict['from'])
        tx_dict['nonce'] = nonce
        
        tx_dict['chainId'] = source_config.chain_id
        
        return TransactionParams(
            chain=self.source_chain,
            from_address=tx_dict['from'],
            to_address=LAYERZERO_ENDPOINTS[self.source_chain],
            value=native_fee + amount,
            data=tx_dict['data'],
            gas_limit=tx_dict.get('gas', 500000),
            gas_price=gas_price,
            nonce=nonce,
            chain_id=source_config.chain_id,
            type=0
        )
    
    def _encode_oft_payload(
        self,
        recipient_address: str,
        min_amount_out: int
    ) -> bytes:
        """
        编码 OFT (Omnichain Fungible Token) payload
        
        这是一个简化版本，实际需要参考 LayerZero 的具体实现
        """
        # 实际 payload 格式需要参考 LayerZero 的 Omnichain 合约
        # 这里返回一个占位符
        return b''
    
    def _encode_adapter_params(self, gas_limit: int) -> bytes:
        """
        编码适配器参数
        
        Returns:
            编码后的字节
        """
        # 适配器参数版本 1
        # 结构: version(1) + gasLimit(32) + airDropAmt(32) + airDropAddr(20)
        version = 1
        return bytes.fromhex(f"{version:02x}") + gas_limit.to_bytes(32, 'big')


# ============================================
# 闪电贷交易构建器
# ============================================

class FlashLoanTransactionBuilder:
    """
    闪电贷交易构建器
    
    支持 Aave V3, Uniswap V3
    """
    
    # Aave V3 Flash Loan Receiver ABI
    AAVE_FLASHLOAN_ABI = [
        {
            "inputs": [
                {"internalType": "address[]", "name": "assets", "type": "address[]"},
                {"internalType": "uint256[]", "name": "amounts", "type": "uint256[]"},
                {"internalType": "uint256[]", "name": "premiums", "type": "uint256[]"},
                {"internalType": "address", "name": "initiator", "type": "address"},
                {"internalType": "bytes", "name": "params", "type": "bytes"}
            ],
            "name": "executeOperation",
            "outputs": [{"internalType": "bool", "name": "", "type": "bool"}],
            "stateMutability": "nonpayable",
            "type": "function"
        }
    ]
    
    # Aave V3 Pool 地址
    AAVE_V3_POOL: Dict[str, str] = {
        "ethereum": "0x87870Bca3F3fD6335C3F4ce8392D69350B4fA4E2",
        "arbitrum": "0x794a61358D6845594F94dc1DB02A252b5b4814aD",
        "optimism": "0x794a61358D6845594F94dc1DB02A252b5b4814aD",
        "polygon": "0x794a61358D6845594F94dc1DB02A252b5b4814aD",
        "avalanche": "0x794a61358D6845594F94dc1DB02A252b5b4814aD",
        "base": "0x945257d1570d5B301b5C3D2D2Bd9F4F04B84c69e",
        "bsc": "0x6892Bf49f070b6953Ca4fD34cD5B9D4CE5b8B89f"
    }
    
    def __init__(self, chain: str):
        self.chain = chain
        config = get_chain_config(chain)
        self.web3 = Web3(Web3.HTTPProvider(config.rpc_url))
        
        # Pool 合约
        if chain in self.AAVE_V3_POOL:
            self.pool_address = self.AAVE_V3_POOL[chain]
            self.pool_contract = self.web3.eth.contract(
                address=Web3.to_checksum_address(self.pool_address),
                abi=[
                    {
                        "inputs": [
                            {"internalType": "address[]", "name": "assets", "type": "address[]"},
                            {"internalType": "uint256[]", "name": "amounts", "type": "uint256[]"},
                            {"internalType": "uint256[]", "name": "modes", "type": "uint256[]"},
                            {"internalType": "address", "name": "onBehalfOf", "type": "address"},
                            {"internalType": "bytes", "name": "params", "type": "bytes"},
                            {"internalType": "uint16", "name": "referralCode", "type": "uint16"}
                        ],
                        "name": "flashLoan",
                        "outputs": [],
                        "stateMutability": "nonpayable",
                        "type": "function"
                    }
                ]
            )
        else:
            self.pool_contract = None
    
    def build_flashloan_transaction(
        self,
        assets: List[str],
        amounts: List[int],
        modes: List[int],  # 0 = 归还全部, 1 = 只还利息转债务
        initiator: str,
        params: bytes,
        nonce: Optional[int] = None
    ) -> TransactionParams:
        """
        构建 Aave V3 闪电贷交易
        
        Args:
            assets: 代币地址列表
            amounts: 数量列表
            modes: 模式列表 (0=归还全部, 1=转债务)
            initiator: 发起者地址（通常是我们的合约地址）
            params: 传给 executeOperation 的参数
            nonce: Nonce
        """
        if not self.pool_contract:
            raise ValueError(f"Aave V3 not supported on {self.chain}")
        
        tx_dict = self.pool_contract.functions.flashLoan(
            [Web3.to_checksum_address(a) for a in assets],
            amounts,
            modes,
            Web3.to_checksum_address(initiator),
            params,
            0  # referral code
        ).buildTransaction({
            'from': Web3.to_checksum_address(initiator)
        })
        
        # Gas 估算
        try:
            tx_dict['gas'] = self.web3.eth.estimate_gas(tx_dict)
        except Exception:
            tx_dict['gas'] = 1000000
        
        # Gas 价格
        gas_price = self.web3.eth.gas_price
        tx_dict['gasPrice'] = gas_price
        
        # Nonce
        if nonce is None:
            nonce = self.web3.eth.get_transaction_count(initiator)
        tx_dict['nonce'] = nonce
        
        config = get_chain_config(self.chain)
        tx_dict['chainId'] = config.chain_id
        
        return TransactionParams(
            chain=self.chain,
            from_address=initiator,
            to_address=self.pool_address,
            value=0,
            data=tx_dict['data'],
            gas_limit=tx_dict['gas'],
            gas_price=gas_price,
            nonce=nonce,
            chain_id=config.chain_id,
            type=0
        )
    
    def encode_operation_params(
        self,
        swap_data: List[Dict],
        profit_address: str
    ) -> bytes:
        """
        编码操作参数
        
        Args:
            swap_data: Swap 操作数据列表
            profit_address: 利润接收地址
            
        Returns:
            编码后的参数字节
        """
        # 编码格式（自定义）:
        # swap_data_len(32) + 
        # swap_data_1 +
        # swap_data_2 +
        # ...
        # profit_address(20)
        
        import eth_abi
        
        return eth_abi.encode(
            ['tuple(address,address,uint256,uint256,bytes)[]', 'address'],
            [swap_data, profit_address]
        )


# ============================================
# 单例和工具函数
# ============================================

# Chain ID 到 Wormhole Chain ID 的映射
WORMHOLE_CHAIN_IDS: Dict[str, int] = {name: cfg.wormhole_chain_id for name, cfg in SUPPORTED_CHAINS.items()}

# LayerZero Chain ID 映射（在 settings 中已有）


def address_to_bytes32(address: str) -> bytes:
    """将 EVM 地址转换为 Wormhole 使用的 bytes32 格式"""
    return Web3.to_checksum_address(address).encode('utf-8').rjust(32, b'\x00')


def address_from_bytes32(b: bytes) -> str:
    """从 bytes32 转换回 EVM 地址"""
    return Web3.to_checksum_address(b[:20].hex())
