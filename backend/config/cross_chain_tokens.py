"""
Wormhole & LayerZero 跨链代币配置
这些代币通过跨链桥在不同链上流通，是套利的理想标的
"""

# ============================================
# Wormhole 支持的代币（可跨链转移）
# ============================================

WORMHOLE_TOKENS = {
    # ==================== 原生跨链代币 ====================
    "W": {
        "name": "Wormhole Token",
        "symbol": "W",
        "chains": ["ethereum", "solana", "bsc", "polygon", "avalanche", "arbitrum", "optimism", "base", "sui", "aptos"],
        "coingecko_id": "wormhole",
        "type": "native_bridge"
    },
    
    # ==================== 稳定币（跨链） ====================
    "USDC": {
        "name": "USD Coin",
        "symbol": "USDC", 
        "chains": ["ethereum", "arbitrum", "optimism", "base", "polygon", "avalanche", "bsc", "solana", "sui", "aptos"],
        "coingecko_id": "usd-coin",
        "type": "stablecoin"
    },
    "USDT": {
        "name": "Tether USD",
        "symbol": "USDT",
        "chains": ["ethereum", "arbitrum", "optimism", "base", "polygon", "avalanche", "bsc", "solana", "aptos"],
        "coingecko_id": "tether",
        "type": "stablecoin"
    },
    "DAI": {
        "name": "Dai Stablecoin",
        "symbol": "DAI",
        "chains": ["ethereum", "arbitrum", "optimism", "base", "polygon", "avalanche", "bsc"],
        "coingecko_id": "dai",
        "type": "stablecoin"
    },
    
    # ==================== ETH 及封装版本 ====================
    "ETH": {
        "name": "Ethereum",
        "symbol": "ETH",
        "chains": ["ethereum", "arbitrum", "optimism", "base", "polygon", "avalanche", "bsc"],
        "coingecko_id": "ethereum",
        "type": "native"
    },
    "WETH": {
        "name": "Wrapped Ethereum",
        "symbol": "WETH",
        "chains": ["ethereum", "arbitrum", "optimism", "base", "polygon", "avalanche", "bsc", "solana"],
        "coingecko_id": "weth",
        "type": "wrapped"
    },
    
    # ==================== BTC 封装版本 ====================
    "WBTC": {
        "name": "Wrapped Bitcoin",
        "symbol": "WBTC",
        "chains": ["ethereum", "arbitrum", "optimism", "base", "polygon", "avalanche", "bsc", "solana"],
        "coingecko_id": "wrapped-bitcoin",
        "type": "wrapped"
    },
    "BTC.b": {
        "name": "Bitcoin on Avalanche",
        "symbol": "BTC.b",
        "chains": ["avalanche", "ethereum", "arbitrum", "optimism", "base", "bsc"],
        "coingecko_id": "bitcoin",
        "type": "wrapped"
    },
    
    # ==================== 主流 DeFi 代币 ====================
    "LINK": {
        "name": "Chainlink",
        "symbol": "LINK",
        "chains": ["ethereum", "arbitrum", "optimism", "base", "polygon", "avalanche", "bsc", "solana"],
        "coingecko_id": "chainlink",
        "type": "oracle"
    },
    "UNI": {
        "name": "Uniswap",
        "symbol": "UNI",
        "chains": ["ethereum", "arbitrum", "optimism", "base", "polygon", "avalanche", "bsc"],
        "coingecko_id": "uniswap",
        "type": "governance"
    },
    "AAVE": {
        "name": "Aave",
        "symbol": "AAVE",
        "chains": ["ethereum", "arbitrum", "optimism", "base", "polygon", "avalanche", "bsc"],
        "coingecko_id": "aave",
        "type": "lending"
    },
    "MKR": {
        "name": "Maker",
        "symbol": "MKR",
        "chains": ["ethereum", "arbitrum", "optimism", "base", "polygon", "avalanche"],
        "coingecko_id": "maker",
        "type": "governance"
    },
    "SNX": {
        "name": "Synthetix",
        "symbol": "SNX",
        "chains": ["ethereum", "arbitrum", "optimism", "base", "polygon", "avalanche"],
        "coingecko_id": "havven",
        "type": "derivatives"
    },
    "CRV": {
        "name": "Curve DAO Token",
        "symbol": "CRV",
        "chains": ["ethereum", "arbitrum", "optimism", "base", "polygon", "avalanche", "bsc"],
        "coingecko_id": "curve-dao-token",
        "type": "dex"
    },
    "COMP": {
        "name": "Compound",
        "symbol": "COMP",
        "chains": ["ethereum", "arbitrum", "optimism", "base", "polygon", "avalanche"],
        "coingecko_id": "compound-governance-token",
        "type": "lending"
    },
    "SUSHI": {
        "name": "Sushi",
        "symbol": "SUSHI",
        "chains": ["ethereum", "arbitrum", "optimism", "base", "polygon", "avalanche", "bsc"],
        "coingecko_id": "sushi",
        "type": "dex"
    },
    
    # ==================== L2 原生代币 ====================
    "ARB": {
        "name": "Arbitrum",
        "symbol": "ARB",
        "chains": ["ethereum", "arbitrum", "optimism", "base", "polygon", "avalanche", "bsc"],
        "coingecko_id": "arbitrum",
        "type": "governance"
    },
    "OP": {
        "name": "Optimism",
        "symbol": "OP",
        "chains": ["ethereum", "arbitrum", "optimism", "base", "polygon", "avalanche", "bsc"],
        "coingecko_id": "optimism",
        "type": "governance"
    },
    
    # ==================== 链原生代币 ====================
    "BNB": {
        "name": "BNB",
        "symbol": "BNB",
        "chains": ["bsc", "ethereum", "arbitrum", "optimism", "polygon", "avalanche", "solana"],
        "coingecko_id": "binancecoin",
        "type": "native"
    },
    "MATIC": {
        "name": "Polygon",
        "symbol": "MATIC",
        "chains": ["polygon", "ethereum", "arbitrum", "optimism", "base", "avalanche", "bsc"],
        "coingecko_id": "matic-network",
        "type": "native"
    },
    "AVAX": {
        "name": "Avalanche",
        "symbol": "AVAX",
        "chains": ["avalanche", "ethereum", "arbitrum", "optimism", "base", "polygon", "bsc"],
        "coingecko_id": "avalanche-2",
        "type": "native"
    },
    "FTM": {
        "name": "Fantom",
        "symbol": "FTM",
        "chains": ["fantom", "ethereum", "arbitrum", "optimism", "polygon", "avalanche", "bsc"],
        "coingecko_id": "fantom",
        "type": "native"
    },
    
    # ==================== 跨链桥代币 ====================
    "STG": {
        "name": "Stargate Finance",
        "symbol": "STG",
        "chains": ["ethereum", "arbitrum", "optimism", "base", "polygon", "avalanche", "bsc", "fantom"],
        "coingecko_id": "stargate-finance",
        "type": "bridge"
    },
    "SYN": {
        "name": "Synapse",
        "symbol": "SYN",
        "chains": ["ethereum", "arbitrum", "optimism", "base", "polygon", "avalanche", "bsc", "fantom"],
        "coingecko_id": "synapse-2",
        "type": "bridge"
    },
    "AXL": {
        "name": "Axelar",
        "symbol": "AXL",
        "chains": ["ethereum", "arbitrum", "optimism", "base", "polygon", "avalanche", "bsc", "sui"],
        "coingecko_id": "axelar",
        "type": "bridge"
    },
    
    # ==================== 流动性质押代币 ====================
    "stETH": {
        "name": "Lido Staked ETH",
        "symbol": "stETH",
        "chains": ["ethereum", "arbitrum", "optimism", "base", "polygon"],
        "coingecko_id": "staked-ether",
        "type": "liquid_staking"
    },
    "wstETH": {
        "name": "Wrapped Staked ETH",
        "symbol": "wstETH",
        "chains": ["ethereum", "arbitrum", "optimism", "base", "polygon", "avalanche"],
        "coingecko_id": "wrapped-steth",
        "type": "liquid_staking"
    },
    "rETH": {
        "name": "Rocket Pool ETH",
        "symbol": "rETH",
        "chains": ["ethereum", "arbitrum", "optimism", "base", "polygon"],
        "coingecko_id": "rocket-pool-eth",
        "type": "liquid_staking"
    },
    
    # ==================== Meme 代币 ====================
    "PEPE": {
        "name": "Pepe",
        "symbol": "PEPE",
        "chains": ["ethereum", "arbitrum", "optimism", "base", "polygon", "bsc"],
        "coingecko_id": "pepe",
        "type": "meme"
    },
    "SHIB": {
        "name": "Shiba Inu",
        "symbol": "SHIB",
        "chains": ["ethereum", "arbitrum", "optimism", "base", "polygon", "avalanche", "bsc"],
        "coingecko_id": "shiba-inu",
        "type": "meme"
    },
    "DOGE": {
        "name": "Dogecoin",
        "symbol": "DOGE",
        "chains": ["ethereum", "bsc", "polygon", "avalanche"],
        "coingecko_id": "dogecoin",
        "type": "meme"
    },
    "BONK": {
        "name": "Bonk",
        "symbol": "BONK",
        "chains": ["solana", "ethereum", "arbitrum", "base", "polygon", "bsc"],
        "coingecko_id": "bonk",
        "type": "meme"
    },
    "WIF": {
        "name": "dogwifhat",
        "symbol": "WIF",
        "chains": ["solana", "ethereum", "arbitrum", "base", "bsc"],
        "coingecko_id": "dogwifhat",
        "type": "meme"
    },
    
    # ==================== 其他热门代币 ====================
    "SOL": {
        "name": "Solana",
        "symbol": "SOL",
        "chains": ["solana", "ethereum", "arbitrum", "optimism", "base", "bsc"],
        "coingecko_id": "solana",
        "type": "native"
    },
    "ATOM": {
        "name": "Cosmos",
        "symbol": "ATOM",
        "chains": ["ethereum", "arbitrum", "optimism", "base", "polygon", "avalanche", "bsc"],
        "coingecko_id": "cosmos",
        "type": "native"
    },
    "DOT": {
        "name": "Polkadot",
        "symbol": "DOT",
        "chains": ["ethereum", "arbitrum", "optimism", "base", "polygon", "avalanche", "bsc"],
        "coingecko_id": "polkadot",
        "type": "native"
    },
    "ADA": {
        "name": "Cardano",
        "symbol": "ADA",
        "chains": ["ethereum", "arbitrum", "optimism", "base", "bsc"],
        "coingecko_id": "cardano",
        "type": "native"
    },
    "XRP": {
        "name": "XRP",
        "symbol": "XRP",
        "chains": ["ethereum", "arbitrum", "optimism", "base", "bsc", "polygon"],
        "coingecko_id": "ripple",
        "type": "native"
    },
    "LTC": {
        "name": "Litecoin",
        "symbol": "LTC",
        "chains": ["ethereum", "bsc", "polygon"],
        "coingecko_id": "litecoin",
        "type": "native"
    },
    "BCH": {
        "name": "Bitcoin Cash",
        "symbol": "BCH",
        "chains": ["ethereum", "bsc"],
        "coingecko_id": "bitcoin-cash",
        "type": "native"
    },
    "TRX": {
        "name": "TRON",
        "symbol": "TRX",
        "chains": ["ethereum", "bsc", "polygon"],
        "coingecko_id": "tron",
        "type": "native"
    },
    
    # ==================== GameFi / Metaverse ====================
    "SAND": {
        "name": "The Sandbox",
        "symbol": "SAND",
        "chains": ["ethereum", "arbitrum", "optimism", "polygon", "avalanche", "bsc"],
        "coingecko_id": "the-sandbox",
        "type": "metaverse"
    },
    "MANA": {
        "name": "Decentraland",
        "symbol": "MANA",
        "chains": ["ethereum", "arbitrum", "optimism", "polygon", "avalanche", "bsc"],
        "coingecko_id": "decentraland",
        "type": "metaverse"
    },
    "AXS": {
        "name": "Axie Infinity",
        "symbol": "AXS",
        "chains": ["ethereum", "arbitrum", "optimism", "polygon", "bsc"],
        "coingecko_id": "axie-infinity",
        "type": "gamefi"
    },
    "IMX": {
        "name": "Immutable X",
        "symbol": "IMX",
        "chains": ["ethereum", "arbitrum", "optimism", "base", "polygon"],
        "coingecko_id": "immutable-x",
        "type": "gamefi"
    },
    
    # ==================== RWA 代币 ====================
    "ONDO": {
        "name": "Ondo Finance",
        "symbol": "ONDO",
        "chains": ["ethereum", "arbitrum", "optimism", "base", "polygon"],
        "coingecko_id": "ondo-finance",
        "type": "rwa"
    },
    "MKR": {
        "name": "Maker",
        "symbol": "MKR",
        "chains": ["ethereum", "arbitrum", "optimism", "base", "polygon"],
        "coingecko_id": "maker",
        "type": "rwa"
    },
}


# ============================================
# LayerZero 支持的代币
# ============================================

LAYERZERO_TOKENS = {
    # 与 Wormhole 重叠的代币
    "USDC": WORMHOLE_TOKENS["USDC"],
    "USDT": WORMHOLE_TOKENS["USDT"],
    "ETH": WORMHOLE_TOKENS["ETH"],
    "WETH": WORMHOLE_TOKENS["WETH"],
    "WBTC": WORMHOLE_TOKENS["WBTC"],
    "STG": WORMHOLE_TOKENS["STG"],
    
    # LayerZero 特有
    "ZRO": {
        "name": "LayerZero",
        "symbol": "ZRO",
        "chains": ["ethereum", "arbitrum", "optimism", "base", "polygon", "avalanche", "bsc"],
        "coingecko_id": "layerzero",
        "type": "native"
    },
}


# ============================================
# 所有支持的跨链代币
# ============================================

ALL_CROSS_CHAIN_TOKENS = {
    **WORMHOLE_TOKENS,
    **LAYERZERO_TOKENS,
}

# 按类型分组
TOKENS_BY_TYPE = {
    "stablecoin": ["USDC", "USDT", "DAI", "BUSD", "TUSD"],
    "native": ["ETH", "BNB", "MATIC", "AVAX", "SOL", "ATOM", "DOT", "ADA", "XRP", "LTC"],
    "wrapped": ["WETH", "WBTC", "BTC.b"],
    "defi": ["LINK", "UNI", "AAVE", "MKR", "CRV", "COMP", "SUSHI", "SNX"],
    "l2": ["ARB", "OP"],
    "bridge": ["W", "STG", "SYN", "AXL", "ZRO"],
    "liquid_staking": ["stETH", "wstETH", "rETH"],
    "meme": ["PEPE", "SHIB", "DOGE", "BONK", "WIF"],
    "gamefi": ["SAND", "MANA", "AXS", "IMX"],
    "rwa": ["ONDO", "MKR"],
}

# 所有代币符号列表
ALL_TOKEN_SYMBOLS = list(ALL_CROSS_CHAIN_TOKENS.keys())

# 主力交易代币（流动性最好）
MAJOR_TRADING_TOKENS = [
    # 稳定币
    "USDC", "USDT", "DAI",
    # 主流
    "ETH", "WETH", "WBTC", "BNB", "MATIC", "AVAX", "SOL",
    # DeFi
    "LINK", "UNI", "AAVE", "MKR", "CRV", "COMP",
    # L2
    "ARB", "OP",
    # 跨链桥
    "STG", "W",
    # 流动性质押
    "wstETH", "stETH",
    # Meme
    "PEPE", "SHIB", "BONK",
]
