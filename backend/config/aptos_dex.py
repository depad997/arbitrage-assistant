"""
Aptos DEX 配置模块

定义 Aptos 链上支持的 DEX、Token 和 REST API 配置

支持的去中心化交易所：
- Liquidswap (Pontem)
- Thala Labs
- Aptin
- Movex
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
# Aptos REST API 配置
# ============================================

class AptosAPIConfig:
    """Aptos REST API 节点配置"""
    
    # 主网 API
    MAINNET = "https://fullnode.mainnet.aptoslabs.com/v1"
    MAINNET_INDEXER = "https://indexer.mainnet.aptoslabs.com/v1/graphql"
    
    # 备用 API
    ALT_MAINNET = "https://aptos-mainnet.public.blastapi.io/v1"
    
    # 测试网
    TESTNET = "https://fullnode.testnet.aptoslabs.com/v1"
    
    # 开发网
    DEVNET = "https://fullnode.devnet.aptoslabs.com"
    
    # API 配置参数
    REQUEST_TIMEOUT = 30  # 秒
    MAX_RETRIES = 3
    RETRY_DELAY = 1.0  # 秒
    
    # 默认 Gas 配置
    DEFAULT_GAS_UNIT_PRICE = 100  # Octas
    MAX_GAS_AMOUNT = 10000         # 最大 Gas 单位
    MIN_GAS_UNIT_PRICE = 80        # 最小 Gas 单价 (Octas)


# ============================================
# Aptos 交易配置
# ============================================

@dataclass
class AptosTxConfig:
    """Aptos 交易配置"""
    gas_unit_price: int = 100            # Gas 单价 (Octas)
    max_gas_amount: int = 10000          # 最大 Gas 数量
    slippage_tolerance: float = 0.005    # 滑点容忍 (0.5%)
    expiration_seconds: int = 30        # 交易过期时间
    max_retries: int = 3                # 最大重试次数
    retry_delay: float = 2.0           # 重试延迟 (秒)
    
    # 确认配置
    wait_for_confirmation: bool = True
    confirmation_timeout: int = 60      # 确认超时 (秒)
    poll_interval: float = 1.0         # 轮询间隔 (秒)


# ============================================
# Aptos Token 配置
# ============================================

class AptosCoins:
    """Aptos 常用 Coin Type"""
    
    # Aptos 原生代币
    APT = "0x1::aptos_coin::AptosCoin"
    
    # 常用稳定币
    USDC = "0x1::usdc::USDC"
    USDT = "0xf22bede237a07e121b56d91a491eb7bcdfd1f371792464a502a87400000000001::usdt::USDT"
    
    # Thala USD (去中心化稳定币)
    USD = "0xf22bede237a07e121b56d91a491eb7bcdfd1f371792464a502a87400000000001::usd::USD"
    
    # BTC
    BTCB = "0xf22bede237a07e121b56d91a491eb7bcdfd1f371792464a502a87400000000001::btcb::BTCB"
    
    # ETH
    WETH = "0xf22bede237a07e121b56d91a491eb7bcdfd1f371792464a502a87400000000001::weth::WETH"
    
    # DEFI 代币
    LIQ = "0xopraw091n5dg9g2h9::liq::LIQ"  # Liquidswap
    THL = "0xthla1::thla::THL"              # Thala
    APTI = "0xaptin::apti::APTI"            # Aptin
    
    # 符号到地址的映射
    COIN_SYMBOLS: Dict[str, str] = {
        "APT": APT,
        "USDC": USDC,
        "USDT": USDT,
        "USD": USD,
        "BTCB": BTCB,
        "WETH": WETH,
    }
    
    # 地址到符号的映射
    COIN_ADDRESSES: Dict[str, str] = {v: k for k, v in COIN_SYMBOLS.items()}
    
    # 代币精度配置
    DECIMALS: Dict[str, int] = {
        APT: 8,
        USDC: 6,
        USDT: 6,
        USD: 6,
        BTCB: 8,
        WETH: 8,
    }
    
    # 常用交易对
    COMMON_PAIRS: List[Tuple[str, str]] = [
        ("APT", "USDC"),
        ("APT", "USDT"),
        ("USDC", "USDT"),
        ("BTCB", "USDC"),
        ("WETH", "USDC"),
        ("WETH", "APT"),
    ]


# ============================================
# DEX 配置
# ============================================

@dataclass
class AptosDEXInfo:
    """Aptos DEX 信息"""
    name: str
    contract_address: str               # Move 模块地址 (数字标签)
    version: str
    description: str
    swap_function: str                  # Swap 函数名
    pool_function: str                  # 池子查询函数名
    supports_swap: bool = True
    supports_add_liquidity: bool = True
    supports_remove_liquidity: bool = True
    swap_fee_bps: int = 30              # 默认交易费率


class SupportedAptosDEX:
    """Aptos 支持的 DEX 列表"""
    
    # Liquidswap - Aptos 头部 DEX
    LIQUIDSWAP = AptosDEXInfo(
        name="Liquidswap",
        contract_address="0xopraw091n5dg9g2h9",
        version="v2.0",
        description="Liquidswap - First DEX on Aptos",
        swap_function="swap",
        pool_function="get_pool",
        supports_swap=True,
        supports_add_liquidity=True,
        supports_remove_liquidity=True,
        swap_fee_bps=30
    )
    
    # Thala Labs
    THALA = AptosDEXInfo(
        name="Thala",
        contract_address="0xthla1",
        version="v1.0",
        description="Thala Labs - DeFi primitive on Aptos",
        swap_function="swap",
        pool_function="get_pool",
        supports_swap=True,
        supports_add_liquidity=True,
        supports_remove_liquidity=True,
        swap_fee_bps=25
    )
    
    # Aptin
    APTIN = AptosDEXInfo(
        name="Aptin",
        contract_address="0xaptin",
        version="v1.0",
        description="Aptin - Lending on Aptos",
        swap_function="swap",
        pool_function="get_pool",
        supports_swap=True,
        supports_add_liquidity=False,
        supports_remove_liquidity=False,
        swap_fee_bps=20
    )
    
    # Movex
    MOVEX = AptosDEXInfo(
        name="Movex",
        contract_address="0xmovex1",
        version="v1.0",
        description="Movex - DEX on Aptos",
        swap_function="swap",
        pool_function="get_pool",
        supports_swap=True,
        supports_add_liquidity=True,
        supports_remove_liquidity=True,
        swap_fee_bps=30
    )
    
    @classmethod
    def get_dex(cls, name: str) -> Optional[AptosDEXInfo]:
        """获取 DEX 信息"""
        dex_map = {
            "liquidswap": cls.LIQUIDSWAP,
            "thala": cls.THALA,
            "aptin": cls.APTIN,
            "movex": cls.MOVEX,
        }
        return dex_map.get(name.lower())
    
    @classmethod
    def all_dexes(cls) -> List[AptosDEXInfo]:
        """获取所有支持的 DEX"""
        return [cls.LIQUIDSWAP, cls.THALA, cls.APTIN, cls.MOVEX]


# ============================================
# Wormhole Aptos 配置
# ============================================

class WormholeAptosConfig:
    """Wormhole Aptos 跨链桥配置"""
    
    # Wormhole Core Bridge (主合约)
    CORE_BRIDGE = "0xWORMHOLE_CORE_BRIDGE_ADDRESS"
    
    # Wormhole Wormhole Portal Token Bridge
    TOKEN_BRIDGE = "0xWORMHOLE_TOKEN_BRIDGE_ADDRESS"
    
    # 支持的 Wormhole 代币映射 (Aptos 地址)
    WRAPPED_TOKENS: Dict[str, str] = {
        "ETH": "0xWORMHOLE_ETH_ADDRESS",
        "BTC": "0xWORMHOLE_BTC_ADDRESS",
        "USDC": "0xWORMHOLE_USDC_ADDRESS",
        "USDT": "0xWORMHOLE_USDT_ADDRESS",
    }
    
    # 跨链配置
    TRANSFER_FEE_BPS = 0  # 无额外费用
    RELAY_FEE_USD = 0.5   # Relayer 费用


# ============================================
# LayerZero Aptos 配置
# ============================================

class LayerZeroAptosConfig:
    """LayerZero Aptos 跨链桥配置"""
    
    # OApp (Omnichain Application)
    OAPP = "0xLAYERZERO_OAPP_ADDRESS"
    
    # 链 ID 映射
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

def apt_format_decimal(amount: int, decimals: int) -> float:
    """将 Octas/APT 转换为可读格式"""
    return amount / (10 ** decimals)


def apt_parse_decimal(amount: float, decimals: int) -> int:
    """将可读格式转换为 Octas/APT"""
    return int(amount * (10 ** decimals))


def format_apt_amount(octas: int) -> float:
    """格式化 APT 金额"""
    return octas / 1e8  # 1 APT = 10^8 Octas


def parse_apt_amount(apt: float) -> int:
    """解析 APT 金额为 Octas"""
    return int(apt * 1e8)


def format_coin_amount(amount: int, coin_type: str) -> float:
    """格式化代币金额"""
    decimals = AptosCoins.DECIMALS.get(coin_type, 8)
    return format_apt_amount(amount) if coin_type == AptosCoins.APT else amount / (10 ** decimals)


# ============================================
# 配置单例
# ============================================

class AptosConfig:
    """Aptos 配置单例"""
    
    _instance = None
    _api_url: str = AptosAPIConfig.MAINNET
    _tx_config: AptosTxConfig = AptosTxConfig()
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    @classmethod
    def set_api(cls, url: str):
        """设置 API URL"""
        cls._api_url = url
    
    @classmethod
    def get_api(cls) -> str:
        """获取 API URL"""
        return cls._api_url
    
    @classmethod
    def set_tx_config(cls, config: AptosTxConfig):
        """设置交易配置"""
        cls._tx_config = config
    
    @classmethod
    def get_tx_config(cls) -> AptosTxConfig:
        """获取交易配置"""
        return cls._tx_config
