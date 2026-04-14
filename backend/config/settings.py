"""
应用配置文件
所有敏感信息使用占位符，请根据实际环境配置
"""

from pydantic_settings import BaseSettings
from typing import Dict, List, Optional
from functools import lru_cache
from dataclasses import dataclass


# ============================================
# 链配置数据类
# ============================================

@dataclass
class ChainConfig:
    """单链配置"""
    chain_id: int                          # 链 ID
    rpc_url: str                           # RPC URL（占位符）
    wormhole_chain_id: int                 # Wormhole 链 ID
    layerzero_endpoint_id: int             # LayerZero Endpoint ID
    native_token: str                      # 原始代币符号
    is_evm: bool                           # 是否为 EVM 链
    # 附加信息
    rpc_fallback: Optional[List[str]] = None  # 备用 RPC
    explorer_url: str = ""                 # 区块浏览器 URL
    dex_list: Optional[List[str]] = None   # 主要 DEX


# ============================================
# 支持的链完整配置（基于 Wormhole + LayerZero）
# ============================================
# 支持标准：
# - Wormhole 和 LayerZero 都支持的链
# - 覆盖主流 EVM 链和非 EVM 链

SUPPORTED_CHAINS: Dict[str, ChainConfig] = {
    # ==================== EVM 链 ====================
    
    # Ethereum Mainnet
    "ethereum": ChainConfig(
        chain_id=1,
        rpc_url="https://eth.llamarpc.com",
        wormhole_chain_id=2,
        layerzero_endpoint_id=101,
        native_token="ETH",
        is_evm=True,
        rpc_fallback=[
            "https://rpc.ankr.com/eth",
            "https://cloudflare-eth.com",
            "https://ethereum.publicnode.com"
        ],
        explorer_url="https://etherscan.io",
        dex_list=["Uniswap V3", "SushiSwap", "Curve", "Balancer"]
    ),
    
    # Arbitrum One
    "arbitrum": ChainConfig(
        chain_id=42161,
        rpc_url="https://arb1.arbitrum.io/rpc",
        wormhole_chain_id=23,
        layerzero_endpoint_id=110,
        native_token="ETH",
        is_evm=True,
        rpc_fallback=[
            "https://rpc.ankr.com/arbitrum",
            "https://arbitrum.publicnode.com"
        ],
        explorer_url="https://arbiscan.io",
        dex_list=["Uniswap V3", "SushiSwap", "Camelot", "Trader Joe"]
    ),
    
    # Optimism Mainnet
    "optimism": ChainConfig(
        chain_id=10,
        rpc_url="https://mainnet.optimism.io",
        wormhole_chain_id=24,
        layerzero_endpoint_id=111,
        native_token="ETH",
        is_evm=True,
        rpc_fallback=[
            "https://rpc.ankr.com/optimism",
            "https://optimism.publicnode.com"
        ],
        explorer_url="https://optimistic.etherscan.io",
        dex_list=["Uniswap V3", "Velodrome", "Curve", "Synthetix"]
    ),
    
    # Base
    "base": ChainConfig(
        chain_id=8453,
        rpc_url="https://mainnet.base.org",
        wormhole_chain_id=30,
        layerzero_endpoint_id=184,
        native_token="ETH",
        is_evm=True,
        rpc_fallback=[
            "https://base.publicnode.com",
            "https://rpc.ankr.com/base"
        ],
        explorer_url="https://basescan.org",
        dex_list=["Uniswap V3", "Baseswap", "RocketSwap", "LeetSwap"]
    ),
    
    # BNB Smart Chain
    "bsc": ChainConfig(
        chain_id=56,
        rpc_url="https://bsc.publicnode.com",
        wormhole_chain_id=4,
        layerzero_endpoint_id=102,
        native_token="BNB",
        is_evm=True,
        rpc_fallback=[
            "https://rpc.ankr.com/bsc",
            "https://bsc-dataseed.binance.org"
        ],
        explorer_url="https://bscscan.com",
        dex_list=["PancakeSwap", "Biswap", "Apeswap", "MDEX"]
    ),
    
    # Polygon PoS
    "polygon": ChainConfig(
        chain_id=137,
        rpc_url="https://polygon.llamarpc.com",
        wormhole_chain_id=5,
        layerzero_endpoint_id=109,
        native_token="MATIC",
        is_evm=True,
        rpc_fallback=[
            "https://rpc.ankr.com/polygon",
            "https://polygon-rpc.com"
        ],
        explorer_url="https://polygonscan.com",
        dex_list=["QuickSwap", "Uniswap V3", "Curve", "SushiSwap"]
    ),
    
    # Avalanche C-Chain
    "avalanche": ChainConfig(
        chain_id=43114,
        rpc_url="https://api.avax.network/ext/bc/C/rpc",
        wormhole_chain_id=6,
        layerzero_endpoint_id=106,
        native_token="AVAX",
        is_evm=True,
        rpc_fallback=[
            "https://rpc.ankr.com/avalanche",
            "https://avalanche.publicnode.com"
        ],
        explorer_url="https://snowtrace.io",
        dex_list=["Trader Joe", "Pangolin", "GMX", "Benqi"]
    ),
    
    # Fantom Opera
    "fantom": ChainConfig(
        chain_id=250,
        rpc_url="https://rpc.fantom.network",
        wormhole_chain_id=3,
        layerzero_endpoint_id=112,
        native_token="FTM",
        is_evm=True,
        rpc_fallback=[
            "https://rpc.ankr.com/fantom",
            "https://fantom.publicnode.com"
        ],
        explorer_url="https://ftmscan.com",
        dex_list=["SpookySwap", "SpiritSwap", "Equalizer", "Solidly"]
    ),
    
    # Scroll
    "scroll": ChainConfig(
        chain_id=534352,
        rpc_url="https://rpc.scroll.io",
        wormhole_chain_id=534,
        layerzero_endpoint_id=188,
        native_token="ETH",
        is_evm=True,
        rpc_fallback=[
            "https://rpc.ankr.com/scroll",
            "https://scroll.publicnode.com"
        ],
        explorer_url="https://scrollscan.com",
        dex_list=["藕片Swap", "Uniswap V3", "Skydrome", "Zebra"]
    ),
    
    # Mantle
    "mantle": ChainConfig(
        chain_id=5000,
        rpc_url="https://rpc.mantle.xyz",
        wormhole_chain_id=181,
        layerzero_endpoint_id=229,
        native_token="MNT",
        is_evm=True,
        rpc_fallback=[
            "https://rpc.ankr.com/mantle",
            "https://mantle.publicnode.com"
        ],
        explorer_url="https://explorer.mantle.xyz",
        dex_list=["Velocore", "NetSwap", "AgniFinance", "Hammer"]
    ),
    
    # Linea
    "linea": ChainConfig(
        chain_id=59144,
        rpc_url="https://rpc.linea.build",
        wormhole_chain_id=183,
        layerzero_endpoint_id=183,
        native_token="ETH",
        is_evm=True,
        rpc_fallback=[
            "https://rpc.ankr.com/linea",
            "https://linea.publicnode.com"
        ],
        explorer_url="https://lineascan.build",
        dex_list=["LineaSwap", "Lynex", "OpenDEX", "Velocore"]
    ),
    
    # Berachain (Artio testnet, 主网即将上线)
    "berachain": ChainConfig(
        chain_id=80094,
        rpc_url="https://artio.rpc.berachain.com",
        wormhole_chain_id=202,
        layerzero_endpoint_id=208,
        native_token="BERA",
        is_evm=True,
        rpc_fallback=[
            "https://rpc.ankr.com/berachain"
        ],
        explorer_url="https://artio.berascan.io",
        dex_list=["BeraSwap", "LiquidMINI"]
    ),
    
    # Moonbeam
    "moonbeam": ChainConfig(
        chain_id=1284,
        rpc_url="https://rpc.api.moonbeam.network",
        wormhole_chain_id=16,
        layerzero_endpoint_id=126,
        native_token="GLMR",
        is_evm=True,
        rpc_fallback=[
            "https://rpc.ankr.com/moonbeam",
            "https://moonbeam.publicnode.com"
        ],
        explorer_url="https://moonscan.io",
        dex_list=["StellaSwap", "Beamswap", "Solarflare", "Huckleberry"]
    ),
    
    # ==================== 非 EVM 链 ====================
    
    # Solana
    "solana": ChainConfig(
        chain_id=0,  # Solana 不使用 EVM Chain ID
        rpc_url="https://api.mainnet-beta.solana.com",
        wormhole_chain_id=1,
        layerzero_endpoint_id=115,
        native_token="SOL",
        is_evm=False,
        rpc_fallback=[
            "https://solana.publicnode.com",
            "https://rpc.ankr.com/solana"
        ],
        explorer_url="https://solscan.io",
        dex_list=["Raydium", "Orca", "Jupiter", "Meteora"]
    ),
    
    # Sui
    "sui": ChainConfig(
        chain_id=0,  # Sui 不使用 EVM Chain ID
        rpc_url="https://fullnode.mainnet.sui.io",
        wormhole_chain_id=21,
        layerzero_endpoint_id=117,
        native_token="SUI",
        is_evm=False,
        rpc_fallback=[
            "https://sui.publicnode.com",
            "https://rpc.ankr.com/sui"
        ],
        explorer_url="https://suiscan.xyz",
        dex_list=["Cetus", "FlowX", "Aftermath", "Turbos"]
    ),
    
    # Aptos
    "aptos": ChainConfig(
        chain_id=0,  # Aptos 不使用 EVM Chain ID
        rpc_url="https://fullnode.mainnet.aptoslabs.com",
        wormhole_chain_id=22,
        layerzero_endpoint_id=108,
        native_token="APT",
        is_evm=False,
        rpc_fallback=[
            "https://aptos.publicnode.com",
            "https://rpc.ankr.com/aptos"
        ],
        explorer_url="https://explorer.aptoslabs.com",
        dex_list=["Liquidswap", "Thala Labs", "Aptin", "Movex"]
    ),
}


# ============================================
# 便捷访问：RPC URLs（从配置提取）
# ============================================

RPC_URLS: Dict[str, str] = {
    chain_name: config.rpc_url 
    for chain_name, config in SUPPORTED_CHAINS.items()
}

# 备用 RPC URLs
RPC_FALLBACK_URLS: Dict[str, List[str]] = {
    chain_name: config.rpc_fallback or []
    for chain_name, config in SUPPORTED_CHAINS.items()
}


# ============================================
# 桥接配置
# ============================================

@dataclass
class BridgeConfig:
    """跨链桥配置"""
    name: str
    supported_chains: List[str]
    contract_addresses: Dict[str, str]  # chain_name -> contract_address


BRIDGE_CONFIGS: Dict[str, BridgeConfig] = {
    "layerzero": BridgeConfig(
        name="LayerZero",
        supported_chains=[name for name in SUPPORTED_CHAINS if SUPPORTED_CHAINS[name].layerzero_endpoint_id > 0],
        contract_addresses={
            "ethereum": "0x66A71Dcef29A0fFBDBE3c6a460a3B5BC225Cd679",
            "arbitrum": "0x3c2269811836af69497E5F486A85D7316753cf72",
            "optimism": "0x56D71c2431E7dD84f2e8a3D0E78e1e5D3b1D5d5D",
            "base": "0x4200000000000000000000000000000000000000",  # 简化
            "bsc": "0x6F6c7615F0D4aB22c2fE7c1A1a1D1C1e1E1e1e1E",
            "polygon": "0x9740FF91F1985D8d2C714c2EA0F4b7B7b7b7b7b7",
            "avalanche": "0x6D7F7c7F7E7D7C7B7A79796B7B7B7B7B7B7B7B7",
            "fantom": "0x7F7e7D7C7B7A7F7D7F7A7D7F7D7F7A7D7F7A7D",
            "scroll": "0x9F7e7D7C7B7A7F7D7F7A7D7F7D7F7A7D7F7A7D",
            "mantle": "0x8E7d7D7C7B7A7F7D7F7A7D7F7D7F7A7D7F7A7D",
            "linea": "0x7D7e7D7C7B7A7F7D7F7A7D7F7D7F7A7D7F7A7D",
            "berachain": "0x6C7e7D7C7B7A7F7D7F7A7D7F7D7F7A7D7F7A7D",
            "moonbeam": "0x5D7e7D7C7B7A7F7D7F7A7D7F7D7F7A7D7F7A7D",
            "solana": "",  # Solana 使用不同架构
            "sui": "",     # Sui 使用不同架构
            "aptos": "",   # Aptos 使用不同架构
        }
    ),
    "wormhole": BridgeConfig(
        name="Wormhole",
        supported_chains=[name for name in SUPPORTED_CHAINS if SUPPORTED_CHAINS[name].wormhole_chain_id > 0],
        contract_addresses={
            "ethereum": "0x3ee18B2214AFF97000D974cf647E7C347E8fa585",
            "arbitrum": "0xFbF394163BPcE4E4f0F0f0E0D0E0E0D0E0E0E0D",
            "optimism": "0xCeE4E0E0F0E0E0E0E0E0E0E0E0E0E0E0E0E0E0",
            "base": "0xBdE0E0E0E0E0E0E0E0E0E0E0E0E0E0E0E0E0E0",
            "bsc": "0xB8E0E0E0E0E0E0E0E0E0E0E0E0E0E0E0E0E0E0",
            "polygon": "0xA7D0E0E0E0E0E0E0E0E0E0E0E0E0E0E0E0E0E0",
            "avalanche": "0x96D0E0E0E0E0E0E0E0E0E0E0E0E0E0E0E0E0E0",
            "fantom": "0x85D0E0E0E0E0E0E0E0E0E0E0E0E0E0E0E0E0E0",
            "scroll": "0x74C0E0E0E0E0E0E0E0E0E0E0E0E0E0E0E0E0E0",
            "mantle": "0x63B0E0E0E0E0E0E0E0E0E0E0E0E0E0E0E0E0E0",
            "linea": "0x52A0E0E0E0E0E0E0E0E0E0E0E0E0E0E0E0E0E0",
            "berachain": "0x41A0E0E0E0E0E0E0E0E0E0E0E0E0E0E0E0E0E0",
            "moonbeam": "0x30A0E0E0E0E0E0E0E0E0E0E0E0E0E0E0E0E0E0",
            "solana": "wormDT UCLAiFc7eccBGqUfHXA7y8oY6C7bF5bE6",
            "sui": "0xae0E0E0E0E0E0E0E0E0E0E0E0E0E0E0E0E0E0E0",
            "aptos": "0x9DA0E0E0E0E0E0E0E0E0E0E0E0E0E0E0E0E0E0",
        }
    ),
}


# ============================================
# 启用的链列表（可在运行时动态修改）
# ============================================

ENABLED_CHAINS: List[str] = [
    "ethereum",
    "arbitrum",
    "optimism",
    "base",
    "bsc",
    "polygon",
    "avalanche",
    "fantom",
    "scroll",
    "mantle",
    "linea",
    "berachain",
    "moonbeam",
    "solana",
    "sui",
    "aptos",
]


class Settings(BaseSettings):
    """应用配置类
    
    配置优先级：环境变量 > .env 文件 > 默认值
    """
    
    # ============================================
    # 应用基础配置
    # ============================================
    APP_NAME: str = "链上套利助手"
    APP_VERSION: str = "0.2.0"
    DEBUG: bool = False
    
    # ============================================
    # RPC 节点配置（从 SUPPORTED_CHAINS 动态生成）
    # ============================================
    # 注意：RPC URLs 现已移至 SUPPORTED_CHAINS 配置
    # 通过 RPC_URLS 访问
    
    # ============================================
    # DexScreener API 配置（免费，无需 Key）
    # ============================================
    DEXSCREENER_BASE_URL: str = "https://api.dexscreener.com"
    DEXSCREENER_RATE_LIMIT: int = 300  # 300 req/min
    DEXSCREENER_TIMEOUT: int = 10  # 请求超时（秒）
    
    # ============================================
    # 1inch API (获取最优交易路径)
    # ============================================
    INCH_API_KEY: str = "YOUR_1INCH_API_KEY"
    INCH_BASE_URL: str = "https://api.1inch.dev/swap/v6.0"
    
    # ============================================
    # CoinGecko API (获取代币 USD 价格)
    # ============================================
    COINGECKO_API_KEY: str = "YOUR_COINGECKO_API_KEY"
    COINGECKO_BASE_URL: str = "https://pro-api.coingecko.com/api/v3"
    
    # ============================================
    # Redis 配置
    # ============================================
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: Optional[str] = None
    
    # Redis Key 前缀
    REDIS_KEY_PREFIX: str = "arbitrage:"
    
    # 缓存过期时间（秒）
    CACHE_TTL_PRICE: int = 30       # 价格数据缓存 30s
    CACHE_TTL_PAIR: int = 60        # 交易对信息缓存 60s
    CACHE_TTL_OPPORTUNITY: int = 120  # 套利机会缓存 2min
    
    # ============================================
    # 监控配置
    # ============================================
    
    # 轮询间隔（秒）
    POLLING_INTERVAL_DEFAULT: int = 30
    POLLING_INTERVAL_FAST: int = 10
    
    # 价格变动阈值
    PRICE_CHANGE_THRESHOLD: float = 0.02  # 2%
    PRICE_CHANGE_SIGNIFICANT: float = 0.05  # 5% - 重大变动
    
    # 最小流动性阈值（USD）
    MIN_LIQUIDITY: float = 10000
    
    # 最小套利利润阈值（USD）
    MIN_ARBITRAGE_PROFIT: float = 10
    
    # ============================================
    # Telegram Bot 配置
    # ============================================
    TELEGRAM_BOT_TOKEN: str = "YOUR_TELEGRAM_BOT_TOKEN"
    TELEGRAM_CHAT_ID: str = "YOUR_CHAT_ID"
    TELEGRAM_ALERT_ENABLED: bool = True
    
    # 告警限流
    ALERT_RATE_LIMIT: int = 5  # 每分钟最多发送消息数
    ALERT_COOLDOWN: int = 300  # 相同告警冷却时间（秒）= 5分钟
    
    # ============================================
    # 飞书机器人配置
    # ============================================
    FEISHU_WEBHOOK_URL: str = ""
    FEISHU_SECRET: str = ""  # 签名密钥（可选，用于增强安全性）
    FEISHU_ENABLED: bool = True
    FEISHU_BOT_NAME: str = "套利助手"
    
    # ============================================
    # Gas 成本估算
    # ============================================
    # 各链 Gas 价格上限（超过则不推荐套利）
    MAX_GAS_PRICE: Dict[str, float] = {
        "ethereum": 100,      # Gwei
        "arbitrum": 1.0,      # Gwei
        "optimism": 0.5,      # Gwei
        "base": 1.0,          # Gwei
        "bsc": 5,             # Gwei
        "polygon": 500,       # Gwei
        "avalanche": 30,      # nAVAX (1e-9)
        "fantom": 100,        # Gwei
        "scroll": 10,         # Gwei
        "mantle": 0.1,        # Gwei
        "linea": 10,          # Gwei
        "berachain": 10,      # Gwei
        "moonbeam": 100,      # Gwei
    }
    
    # ============================================
    # 监控的交易对列表
    # ============================================
    # 格式: (chain, base_token, quote_token)
    # 例如: ETH/USDC 表示用 USDC 购买 ETH 的交易对
    MONITORED_PAIRS: List[tuple] = [
        # 主流交易对 - Ethereum
        ("ethereum", "ETH", "USDC"),
        ("ethereum", "WBTC", "USDC"),
        ("ethereum", "ETH", "USDT"),
        # Arbitrum
        ("arbitrum", "ETH", "USDC"),
        ("arbitrum", "ARB", "ETH"),
        # Optimism  
        ("optimism", "ETH", "USDC"),
        ("optimism", "OP", "ETH"),
        # Base
        ("base", "ETH", "USDC"),
        ("base", "DEGEN", "ETH"),
        # BSC
        ("bsc", "BNB", "USDT"),
        ("bsc", "CAKE", "BNB"),
        # Polygon
        ("polygon", "MATIC", "USDC"),
        ("polygon", "WETH", "USDC"),
        # Avalanche
        ("avalanche", "AVAX", "USDC"),
        ("avalanche", "BTC", "USDC"),
        # Fantom
        ("fantom", "FTM", "USUSDL"),
        # Scroll
        ("scroll", "ETH", "USDC"),
        # Mantle
        ("mantle", "MNT", "USDC"),
        # Linea
        ("linea", "ETH", "USDC"),
        # Solana
        ("solana", "SOL", "USDC"),
        ("solana", "BTC", "USDC"),
        # Sui
        ("sui", "SUI", "USDC"),
        # Aptos
        ("aptos", "APT", "USDC"),
    ]
    
    # 默认轮询间隔（秒）
    PRICE_POLLING_INTERVAL: int = 30
    
    # ============================================
    # 执行模式配置
    # ============================================
    
    # 支持的执行模式
    EXECUTION_MODES: List[str] = ["preset", "flashloan"]  # 预置资金 / 闪电贷
    
    # 默认执行模式
    DEFAULT_EXECUTION_MODE: str = "preset"
    
    # 闪电贷配置（适用于支持闪电贷的链）
    FLASHLOAN_PROVIDERS: Dict[str, List[str]] = {
        "ethereum": ["Aave V3", "Dydx", "MakerDAO"],
        "arbitrum": ["Aave V3", "GMX", "dYdX"],
        "optimism": ["Aave V3", "Velodrome"],
        "polygon": ["Aave V3", "QuickSwap"],
        "avalanche": ["Aave V3", "GMX"],
        "bsc": ["PancakeSwap", "Venus"],
        "fantom": ["Aave V3", "SpookySwap"],
        "base": ["Aave V3"],
        "scroll": ["Aave V3"],
        "mantle": ["Aave V3"],
        "linea": ["Aave V3"],
    }
    
    # ============================================
    # 日志配置
    # ============================================
    LOG_LEVEL: str = "INFO"
    LOG_FILE: Optional[str] = "logs/app.log"
    LOG_FORMAT: str = "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
    
    # ============================================
    # API 请求配置
    # ============================================
    REQUEST_TIMEOUT: int = 30
    REQUEST_MAX_RETRIES: int = 3
    REQUEST_RETRY_DELAY: float = 1.0
    
    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": True,
        "extra": "ignore"  # 忽略 .env 中的额外字段
    }


@lru_cache()
def get_settings() -> Settings:
    """获取配置单例（带缓存）"""
    return Settings()


# 导出便捷访问
settings = get_settings()


# ============================================
# 辅助函数
# ============================================

def get_chain_config(chain_name: str) -> Optional[ChainConfig]:
    """获取链配置"""
    return SUPPORTED_CHAINS.get(chain_name)


def get_enabled_chains() -> List[str]:
    """获取当前启用的链列表"""
    return [c for c in ENABLED_CHAINS if c in SUPPORTED_CHAINS]


def get_evm_chains() -> List[str]:
    """获取所有 EVM 链"""
    return [c for c, cfg in SUPPORTED_CHAINS.items() if cfg.is_evm]


def get_non_evm_chains() -> List[str]:
    """获取所有非 EVM 链"""
    return [c for c, cfg in SUPPORTED_CHAINS.items() if not cfg.is_evm]


def is_chain_enabled(chain_name: str) -> bool:
    """检查链是否启用"""
    return chain_name in ENABLED_CHAINS


def get_rpc_for_chain(chain_name: str) -> Optional[str]:
    """获取链的 RPC URL（带备用）"""
    config = SUPPORTED_CHAINS.get(chain_name)
    if not config:
        return None
    
    # TODO: 实现健康检查，返回可用的 RPC
    return config.rpc_url


def get_bridge_supported_chains(bridge: str) -> List[str]:
    """获取特定桥接支持的链"""
    bridge_config = BRIDGE_CONFIGS.get(bridge)
    if not bridge_config:
        return []
    
    return [c for c in bridge_config.supported_chains if c in ENABLED_CHAINS]


# RPC_CONFIGS 保持向后兼容
RPC_CONFIGS = {
    chain_name: type('RPCConfig', (), {
        'rpc_url': config.rpc_url,
        'chain_id': config.chain_id,
        'is_evm': config.is_evm,
        'native_token': config.native_token,
    })()
    for chain_name, config in SUPPORTED_CHAINS.items()
}
