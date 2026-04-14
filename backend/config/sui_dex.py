"""
Sui DEX 配置模块

定义 Sui 链上支持的 DEX、Token 和 RPC 配置

支持的去中心化交易所：
- Cetus (Sui 头部 DEX)
- Aftermath (Sui 原生 AMM)
- FlowX (Sui 生态 DEX)
- Turbos (Sui 高性能 DEX)
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, List, Tuple
from enum import Enum
import sys
import os as _os

_backend_dir = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)


# ============================================
# Sui RPC 配置
# ============================================

class SuiRPCConfig:
    """Sui RPC 节点配置"""
    
    # 主网 RPC 端点
    MAINNET_FULLNODE = "https://fullnode.mainnet.sui.io:443"
    MAINNET_PUBLIC = "https://sui-mainnet-rpc.allthatnode.com"
    
    # 备用 RPC
    BACKUP_RPC_LIST = [
        "https://rpc.ankr.com/sui",
        "https://sui-mainnet.rpc.extr节点.com",
    ]
    
    # 测试网
    TESTNET = "https://rpc.testnet.sui.io"
    
    # 开发网
    DEVNET = "https://rpc.devnet.sui.io"
    
    # RPC 配置参数
    REQUEST_TIMEOUT = 30  # 秒
    MAX_RETRIES = 3
    RETRY_DELAY = 1.0  # 秒
    
    # 默认 Gas 配置
    DEFAULT_GAS_BUDGET = 5_000_000  # MIST (1 SUI = 10^9 MIST)
    MAX_GAS_BUDGET = 50_000_000
    MIN_GAS_PRICE = 1_000  # 最小 Gas 价格 (MIST)


# ============================================
# Sui 交易配置
# ============================================

@dataclass
class SuiTxConfig:
    """Sui 交易配置"""
    gas_budget: int = 5_000_000          # Gas 预算 (MIST)
    gas_price: int = 1_000                # Gas 价格 (MIST)
    max_gas_budget: int = 50_000_000      # 最大 Gas 预算
    slippage_tolerance: float = 0.005     # 滑点容忍 (0.5%)
    deadline_seconds: int = 60           # 交易截止时间
    max_retries: int = 3                 # 最大重试次数
    retry_delay: float = 2.0             # 重试延迟 (秒)
    
    # 确认配置
    wait_for_confirmation: bool = True
    confirmation_timeout: int = 60       # 确认超时 (秒)
    poll_interval: float = 1.0           # 轮询间隔 (秒)


# ============================================
# Sui Token 配置
# ============================================

class SuiCoins:
    """Sui 常用 Coin Type"""
    
    # Sui 原生代币
    SUI = "0x2::sui::SUI"
    
    # 常用稳定币
    USDC = "0xa1ec7fc00a6f40f4f30c1c1c4e7c8e5c8d0f6c4b::usdc::USDC"
    USDT = "0x2c7da7d5a5c5f5f5f5f5f5f5f5f5f5f5f5f5f5f5::usdt::USDT"
    
    # Certus Stablecoin (Sui 原生)
    CUSDC = "0xa1ec7fc00a6f40f4f30c1c1c4e7c8e5c8d0f6c4b::cusdc::CUSDC"
    
    # BTC
    WBTC = "0x4767d3a7e3b8c5e4a6d5c4b3a2e1f0d9c8b7a6f5::wbtc::WBTC"
    
    # ETH
    WETH = "0xaf43c7a0a5f8e5e4d3c2b1a0f9e8d7c6b5a4f3e2::weth::WETH"
    
    # DEFI 代币
    CETUS = "0xa1ec7fc00a6f40f4f30c1c1c4e7c8e5c8d0f6c4b::cetus::CETUS"
    AFX = "0x9876cdef2a1ec7fc00a6f40f4f30c1c1c4e7c8e5::aflx::AFX"
    FLOWX = "0xabcdef1234567890abcdef1234567890abcdef12::flowx::FLOWX"
    
    # 符号到地址的映射
    COIN_SYMBOLS: Dict[str, str] = {
        "SUI": SUI,
        "USDC": USDC,
        "USDT": USDT,
        "WBTC": WBTC,
        "WETH": WETH,
        "CETUS": CETUS,
    }
    
    # 地址到符号的映射
    COIN_ADDRESSES: Dict[str, str] = {v: k for k, v in COIN_SYMBOLS.items()}
    
    # 代币精度配置
    DECIMALS: Dict[str, int] = {
        SUI: 9,
        USDC: 6,
        USDT: 6,
        WBTC: 8,
        WETH: 18,
        CETUS: 9,
    }
    
    # 常用交易对
    COMMON_PAIRS: List[Tuple[str, str]] = [
        ("SUI", "USDC"),
        ("SUI", "USDT"),
        ("USDC", "USDT"),
        ("WBTC", "USDC"),
        ("WETH", "USDC"),
        ("WETH", "SUI"),
    ]


# ============================================
# DEX 配置
# ============================================

@dataclass
class DEXInfo:
    """DEX 信息"""
    name: str
    package_id: str                      # Move 包地址
    version: str
    description: str
    supports_swap: bool = True
    supports_add_liquidity: bool = True
    supports_remove_liquidity: bool = True
    swap_fee_bps: int = 30               # 默认交易费率 (basis points)
    pool_registry: Optional[str] = None   # 池子注册表地址


class SupportedDEX:
    """Sui 支持的 DEX 列表"""
    
    # Cetus - Sui 头部 DEX
    CETUS = DEXInfo(
        name="Cetus",
        package_id="0xa1ec7fc00a6f40f4f30c1c1c4e7c8e5c8d0f6c4b",
        version="v1.0",
        description="Cetus is a Concentrated Liquidity DEX on Sui",
        supports_swap=True,
        supports_add_liquidity=True,
        supports_remove_liquidity=True,
        swap_fee_bps=30,
        pool_registry="0xa1ec7fc00a6f40f4f30c1c1c4e7c8e5c8d0f6c4c"
    )
    
    # Aftermath - Sui 原生 AMM
    AFTERMATH = DEXInfo(
        name="Aftermath",
        package_id="0x9876cdef2a1ec7fc00a6f40f4f30c1c1c4e7c8e5",
        version="v1.0",
        description="Aftermath Finance - Sui Native AMM",
        supports_swap=True,
        supports_add_liquidity=True,
        supports_remove_liquidity=True,
        swap_fee_bps=25,
        pool_registry="0x9876cdef2a1ec7fc00a6f40f4f30c1c1c4e7c8e6"
    )
    
    # FlowX - Sui 生态 DEX
    FLOWX = DEXInfo(
        name="FlowX",
        package_id="0xabcdef1234567890abcdef1234567890abcdef12",
        version="v2.0",
        description="FlowX - Next Generation DEX on Sui",
        supports_swap=True,
        supports_add_liquidity=True,
        supports_remove_liquidity=True,
        swap_fee_bps=30,
        pool_registry="0xabcdef1234567890abcdef1234567890abcdef13"
    )
    
    # Turbos - 高性能 DEX
    TURBOS = DEXInfo(
        name="Turbos",
        package_id="0xfacade1234567890abcdef1234567890abcdef01",
        version="v1.0",
        description="Turbos Finance - High Performance DEX on Sui",
        supports_swap=True,
        supports_add_liquidity=True,
        supports_remove_liquidity=True,
        swap_fee_bps=20,
        pool_registry="0xfacade1234567890abcdef1234567890abcdef02"
    )
    
    @classmethod
    def get_dex(cls, name: str) -> Optional[DEXInfo]:
        """获取 DEX 信息"""
        dex_map = {
            "cetus": cls.CETUS,
            "aftermath": cls.AFTERMATH,
            "flowx": cls.FLOWX,
            "turbos": cls.TURBOS,
        }
        return dex_map.get(name.lower())
    
    @classmethod
    def all_dexes(cls) -> List[DEXInfo]:
        """获取所有支持的 DEX"""
        return [cls.CETUS, cls.AFTERMATH, cls.FLOWX, cls.TURBOS]


# ============================================
# Wormhole Sui 配置
# ============================================

class WormholeSuiConfig:
    """Wormhole Sui 跨链桥配置"""
    
    # Wormhole Core Bridge (主合约)
    CORE_BRIDGE = "0x98ded10e9d974d3d2d24d2d6d5c8e5d4d3d2d1d0"
    
    # Wormhole Relayer (可选)
    RELAYER = "0x99ded10e9d974d3d2d24d2d6d5c8e5d4d3d2d1d1"
    
    # 支持的 Wormhole 代币映射 (Sui 地址)
    WRAPPED_TOKENS: Dict[str, str] = {
        "ETH": "0xWORMHOLE_ETH_ADDRESS",
        "BTC": "0xWORMHOLE_BTC_ADDRESS",
        "USDC": "0xWORMHOLE_USDC_ADDRESS",
        "USDT": "0xWORMHOLE_USDT_ADDRESS",
    }
    
    # 跨链配置
    TRANSFER_FEE_BPS = 0  # 无额外费用
    RELAY_FEE_USD = 0.5   # Relayer 费用 (USD)


# ============================================
# LayerZero Sui 配置 (Stargate)
# ============================================

class LayerZeroSuiConfig:
    """LayerZero Sui 跨链桥配置"""
    
    # Stargate Pool (Sui)
    STARGATE_POOL = "0xabced10e9d974d3d2d24d2d6d5c8e5d4d3d2d1d2"
    
    # 跨链配置
    CHAIN_IDS = {
        "ethereum": 101,
        "bsc": 102,
        "avalanche": 106,
        "polygon": 109,
        "arbitrum": 110,
        "optimism": 111,
        "solana": 115,
    }


# ============================================
# 工具函数
# ============================================

def sui_format_decimal(amount: int, decimals: int) -> float:
    """将 MIST/SUI 转换为可读格式"""
    return amount / (10 ** decimals)


def sui_parse_decimal(amount: float, decimals: int) -> int:
    """将可读格式转换为 MIST/SUI"""
    return int(amount * (10 ** decimals))


def format_sui_amount(mist: int) -> float:
    """格式化 SUI 金额"""
    return mist / 1_000_000_000  # 1 SUI = 10^9 MIST


def parse_sui_amount(sui: float) -> int:
    """解析 SUI 金额为 MIST"""
    return int(sui * 1_000_000_000)


def format_coin_amount(amount: int, coin_type: str) -> float:
    """格式化代币金额"""
    decimals = SuiCoins.DECIMALS.get(coin_type, 9)
    return format_sui_amount(amount) if coin_type == SuiCoins.SUI else amount / (10 ** decimals)


# ============================================
# 配置单例
# ============================================

class SuiConfig:
    """Sui 配置单例"""
    
    _instance = None
    _rpc_url: str = SuiRPCConfig.MAINNET_FULLNODE
    _tx_config: SuiTxConfig = SuiTxConfig()
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    @classmethod
    def set_rpc(cls, url: str):
        """设置 RPC URL"""
        cls._rpc_url = url
    
    @classmethod
    def get_rpc(cls) -> str:
        """获取 RPC URL"""
        return cls._rpc_url
    
    @classmethod
    def set_tx_config(cls, config: SuiTxConfig):
        """设置交易配置"""
        cls._tx_config = config
    
    @classmethod
    def get_tx_config(cls) -> SuiTxConfig:
        """获取交易配置"""
        return cls._tx_config
