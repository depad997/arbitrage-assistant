"""
Solana DEX 配置模块

定义 Solana 链上支持的 DEX、Token 和 Jupiter API 配置

支持的去中心化交易所：
- Jupiter Aggregator (聚合器，支持所有 DEX)
- Raydium (V2/V4)
- Orca (Whirlpool)
- Meteora
- Marinade (流动性)
"""

from dataclasses import dataclass
from typing import Optional

import sys
import os as _os
_backend_dir = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)


# ============================================
# Jupiter API 配置
# ============================================

class JupiterEndpoints:
    """Jupiter API 端点"""
    # 主网 API
    BASE_URL = "https://quote-api.jup.ag/v6"
    SWAP_URL = "https://quote-api.jup.ag/v6/swap"
    
    # 价格 API
    PRICE_URL = "https://price-api.jup.ag/v6/price"
    
    # 替代 API (当主 API 不可用时)
    ALT_BASE_URL = "https://quote-api.jup.xyz/v6"
    
    # User-Agent 请求头 (Jupiter API 要求)
    USER_AGENT = "Mozilla/5.0 (compatible; ArbitrageBot/1.0)"


# ============================================
# Solana Token 配置
# ============================================

class SolanaTokens:
    """Solana 常用代币 Mint 地址"""
    
    # 原生代币
    SOL = "So11111111111111111111111111111111111111112"  # Wrapped SOL
    
    # Stablecoins
    USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"  # USDC (Center)
    USDT = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"  # USDT
    
    # 知名 Solana 原生代币
    RAY = "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R"  # Raydium
    ORCA = "orcaEKTdK7LKz57vaAYr9QeNsVEPfiu6QeMU1kektZE"  # Orca
    MNGO = "MangoCzJ36DyZv9ChUyZh3gJnBGRSiuLLxFcMy3v6ZRA"  # Mango
    FTT = "AGFEad2et2ZJif9jaGpdMixEacwQRRbRUjH9EB7SpJha"  # FTX Token
    SRM = "SRMuApVNdxXokk5GT7XD5cUUgXMBCoAz2LHeuAoKWRt"  # Serum
    USDH = "USDh1GmUViRHwJPBuTL Reactivecoin4uXWxCBKJfk4KoSL5wV"  # USDH (DefiStability)
    STSOL = "7Q4ydnvGcPGqXkCPsv1kSBEeXw3gkJt8hse5D6g3wP8S"  # Lido Staked SOL
    MSOL = "mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So"  # Marinade Staked SOL
    
    # 主流替代币
    WBTC = "3NZ9JMVBmGAqocybic2c7LQCJScmgsAZ6vQqTDzcqmJh"  # Wrapped BTC (Sollet)
    WETH = "7vfCXTUXx5WJV5JADk17DUJ4ksgau7utNKj4b963voxs"  # Wrapped ETH (Sollet)
    ETH = "7vfCXTUXx5WJV5JADk17DUJ4ksgau7utNKj4b963voxs"  # Ethereum
    BTC = "9n4nbM75f5Ui33ZbPYXn59EwSgE8CGsHtAeTH5YFeJ9E"  # Bitcoin (Sollet)
    
    # Memecoins (谨慎)
    DOGE = "oCfbAyJmcKQXvSBuPdPnbNpRGRkD3D1RxB5Nt5UvRfk"  # Dogecoin
    BONK = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"  # Bonk
    WIF = "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm"  # dogwifhat
    POPCAT = "2qHHhJF2xbYJj额头YTY3BjR3TKAEcLeyxRyy7c3YXxHG"  # Popcat
    FLOKI = "ESpdLbgm32QSPXYxnvUNPmL6Tb5FEmZMAhbNKN3R3P8y"  # FLOKI
    
    # 所有代币映射
    ALL_TOKENS = {
        "SOL": SOL,
        "USDC": USDC,
        "USDT": USDT,
        "RAY": RAY,
        "ORCA": ORCA,
        "MNGO": MNGO,
        "FTT": FTT,
        "SRM": SRM,
        "stSOL": STSOL,
        "mSOL": MSOL,
        "WBTC": WBTC,
        "WETH": WETH,
        "BTC": BTC,
        "DOGE": DOGE,
        "BONK": BONK,
        "WIF": WIF,
    }
    
    # 代币精度配置
    TOKEN_DECIMALS = {
        SOL: 9,           # SOL 有 9 位精度
        USDC: 6,          # USDC 有 6 位精度
        USDT: 6,          # USDT 有 6 位精度
        RAY: 6,           # RAY 有 6 位精度
        ORCA: 6,          # ORCA 有 6 位精度
        MNGO: 6,          # MNGO 有 6 位精度
        FTT: 6,           # FTT 有 6 位精度
        SRM: 6,           # SRM 有 6 位精度
        STSOL: 9,         # stSOL 有 9 位精度
        MSOL: 9,          # mSOL 有 9 位精度
        WBTC: 8,          # WBTC 有 8 位精度
        WETH: 8,          # WETH 有 8 位精度
        BTC: 8,           # BTC 有 8 位精度
        "DOGE": 8,
        "BONK": 5,        # BONK 有 5 位精度
        "WIF": 6,         # WIF 有 6 位精度
    }


# ============================================
# DEX 配置
# ============================================

@dataclass
class DEXConfig:
    """单个 DEX 配置"""
    name: str
    program_id: str
    version: str
    description: str
    supports_direct: bool = True  # 是否支持直接交易
    supports_bridges: bool = False  # 是否支持桥接


class SupportedDEX:
    """支持的 DEX 列表"""
    
    # Jupiter Aggregator (聚合器)
    JUPITER = DEXConfig(
        name="Jupiter",
        program_id="JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4",
        version="v6",
        description="Solana's main DEX aggregator, routing across multiple DEXs",
        supports_direct=True,
        supports_bridges=True
    )
    
    # Raydium
    RAYDIUM_V4 = DEXConfig(
        name="Raydium V4",
        program_id="RaydiumV2AMMCoE5yNEDrBywJPuSeEaGEKEVgb5UDXK3x6",
        version="v4",
        description="Raydium's Standard AMM pool",
        supports_direct=True,
        supports_bridges=False
    )
    
    RAYDIUM_CLMM = DEXConfig(
        name="Raydium CLMM",
        program_id="CAMMCzo5YL8w4VFF8KVHrK22ffUbet2tMbDq2mWAEcnX",
        version="clmm",
        description="Raydium's Concentrated Liquidity Market Maker",
        supports_direct=True,
        supports_bridges=False
    )
    
    # Orca
    ORCA_WHIRLPOOL = DEXConfig(
        name="Orca Whirlpool",
        program_id="whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc",
        version="whirlpool",
        description="Orca's concentrated liquidity DEX",
        supports_direct=True,
        supports_bridges=False
    )
    
    # Meteora
    METEORA_DLMM = DEXConfig(
        name="Meteora DLMM",
        program_id="LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo",
        version="dlmm",
        description="Meteora's Dynamic Liquidity Market Maker",
        supports_direct=True,
        supports_bridges=False
    )
    
    # OpenBook (Serum)
    OPENBOOK = DEXConfig(
        name="OpenBook",
        program_id="srmqPvymJeFKQ4zGvz1W8prRHZyVqJTgWLvQPkSja5y",
        version="v3",
        description="Community fork of Serum DEX",
        supports_direct=True,
        supports_bridges=False
    )
    
    # Marinade (流动性池，非 AMM)
    MARINADE = DEXConfig(
        name="Marinade",
        program_id="MarBmsSgKXrdNDsBaegAHfXgWfHZY1eYdPJoGADqS5Lk",
        version="v1",
        description="Liquid staking protocol with liquidity pools",
        supports_direct=False,
        supports_bridges=False
    )
    
    # 所有 DEX 映射
    ALL_DEX = {
        "jupiter": JUPITER,
        "raydium_v4": RAYDIUM_V4,
        "raydium_clmm": RAYDIUM_CLMM,
        "orca": ORCA_WHIRLPOOL,
        "meteora": METEORA_DLMM,
        "openbook": OPENBOOK,
        "marinade": MARINADE,
    }
    
    # 推荐的 DEX 顺序 (用于聚合器)
    RECOMMENDED_ORDER = ["jupiter", "raydium_v4", "orca", "meteora"]


# ============================================
# Solana RPC 配置
# ============================================

class SolanaRPCConfig:
    """Solana RPC 节点配置"""
    
    # 主网 RPC
    MAINNET_RPCS = [
        "https://api.mainnet-beta.solana.com",
        "https://solana.publicnode.com",
        "https://rpc.ankr.com/solana",
        "https://solana-mainnet.rpc.extrnode.com",
    ]
    
    # Devnet RPC (测试)
    DEVNET_RPCS = [
        "https://api.devnet.solana.com",
        "https://solana-devnet.rpc.extrnode.com",
    ]
    
    # 主网 RPC 配置
    MAINNET_CONFIG = {
        "commitment": "confirmed",
        "max_retries": 3,
        "timeout": 30,
    }
    
    # 默认使用的主 RPC
    DEFAULT_MAINNET = "https://api.mainnet-beta.solana.com"


# ============================================
# Solana 程序地址
# ============================================

class SolanaPrograms:
    """Solana 常用程序地址"""
    
    # 系统程序
    SYSTEM_PROGRAM = "11111111111111111111111111111111"
    
    # Token 程序
    TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
    TOKEN_2022_PROGRAM = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
    
    # Associated Token Account 程序
    ASSOCIATED_TOKEN_PROGRAM = "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL"
    
    # Serum / OpenBook
    SERUM_PROGRAM = "srmqPvymJeFKQ4zGvz1W8prRHZyVqJTgWLvQPkSja5y"
    OPENBOOK_PROGRAM = "srmqPvymJeFKQ4zGvz1W8prRHZyVqJTgWLvQPkSja5y"
    
    # 桥接程序
    WORMHOLE_PROGRAM = "worm2ZoG2kUd4vFXhv6ae9UK1U8J2D4vN7aMPDxeWBN"  # Wormhole v2
    CCTT_PROGRAM = "cctpP1uFCRbEN7HtK3WkPgr3b2r2aFXJyK9qWzAcFxu"  # Circle CCTP
    
    # Stake 程序
    STAKE_PROGRAM = "Stake11111111111111111111111111111111111111111"
    STAKE_POOL_PROGRAM = "SPMBhswJb5x6YWmJ8NwT4xJ6mVoS6J1vP1cGvTvLDb"
    
    # Lido
    LIDO_PROGRAM = "Crx2CS9jfqTNtB5s2qhxJJLtP3UqOb1YB4ZDCZS1PzQG"


# ============================================
# 交易配置
# ============================================

class SolanaTxConfig:
    """Solana 交易配置"""
    
    # 最小 SOL 余额要求 (用于支付手续费)
    MIN_SOL_BALANCE = 0.01  # SOL
    
    # 推荐的 SOL 余额 (正常操作)
    RECOMMENDED_SOL_BALANCE = 0.1  # SOL
    
    # 默认手续费 (lamports)
    DEFAULT_FEE = 5000  # 0.000005 SOL
    
    # 超时配置 (秒)
    TX_TIMEOUT = 60
    
    # 确认轮询间隔 (秒)
    CONFIRM_POLL_INTERVAL = 0.5
    
    # 最大确认轮询次数
    MAX_CONFIRM_POLL = 120
    
    # 重试配置
    MAX_RETRIES = 3
    RETRY_DELAY = 2  # 秒
    
    # Slippage 配置 (basis points)
    DEFAULT_SLIPPAGE_BPS = 50  # 0.5%
    MAX_SLIPPAGE_BPS = 500  # 5%
    MIN_SLIPPAGE_BPS = 1  # 0.01%


# ============================================
# 工具函数
# ============================================

def get_token_mint(symbol: str) -> str:
    """获取代币 Mint 地址"""
    return SolanaTokens.ALL_TOKENS.get(symbol.upper())


def get_dex_config(name: str) -> Optional[DEXConfig]:
    """获取 DEX 配置"""
    return SupportedDEX.ALL_DEX.get(name.lower())


def get_token_decimals(mint: str) -> int:
    """获取代币精度"""
    return SolanaTokens.TOKEN_DECIMALS.get(mint, 9)


def lamports_to_sol(lamports: int) -> float:
    """将 lamports 转换为 SOL"""
    return lamports / 1e9


def sol_to_lamports(sol: float) -> int:
    """将 SOL 转换为 lamports"""
    return int(sol * 1e9)
