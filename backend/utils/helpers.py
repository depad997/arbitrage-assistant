"""
通用工具函数
"""

from datetime import datetime
from typing import Optional
import re
import logging

logger = logging.getLogger(__name__)


# ============================================
# 格式化函数
# ============================================

def format_currency(value: float, currency: str = "USD", decimals: int = 2) -> str:
    """
    格式化货币数值
    
    Args:
        value: 数值
        currency: 货币符号，默认 USD
        decimals: 小数位数
        
    Returns:
        str: 格式化后的字符串
        
    Examples:
        >>> format_currency(1234.567)
        '$1,234.57'
        >>> format_currency(0.00001234, decimals=6)
        '$0.000012'
    """
    if value >= 1_000_000:
        return f"${value / 1_000_000:,.{decimals}f}M"
    elif value >= 1_000:
        return f"${value / 1_000:,.{decimals}f}K"
    else:
        return f"${value:,.{decimals}f}"


def format_percent(value: float, decimals: int = 2, show_sign: bool = True) -> str:
    """
    格式化百分比
    
    Args:
        value: 数值（0.05 表示 5%）
        decimals: 小数位数
        show_sign: 是否显示正负号
        
    Returns:
        str: 格式化后的百分比字符串
        
    Examples:
        >>> format_percent(0.0567)
        '+5.67%'
        >>> format_percent(-0.03, show_sign=False)
        '-3.00%'
    """
    percent = value * 100
    sign = "+" if show_sign and percent > 0 else ""
    return f"{sign}{percent:.{decimals}f}%"


def format_timestamp(dt: Optional[datetime] = None, format_str: str = "%Y-%m-%d %H:%M:%S") -> str:
    """
    格式化时间戳
    
    Args:
        dt: datetime 对象，None 则使用当前时间
        format_str: 格式字符串
        
    Returns:
        str: 格式化后的时间字符串
    """
    if dt is None:
        dt = datetime.utcnow()
    return dt.strftime(format_str)


def format_address(address: str, start: int = 6, end: int = 4) -> str:
    """
    格式化地址（只显示首尾部分）
    
    Args:
        address: 完整地址
        start: 前面显示的字符数
        end: 后面显示的字符数
        
    Returns:
        str: 格式化后的地址
        
    Examples:
        >>> format_address("0x1234567890abcdef1234567890abcdef12345678")
        '0x123456...5678'
    """
    if len(address) <= start + end:
        return address
    return f"{address[:start]}...{address[-end:]}"


# ============================================
# 验证函数
# ============================================

SUPPORTED_CHAINS = {
    "ethereum": ["eth", "ether", "mainnet"],
    "bsc": ["bsc", "bnb", "binance"],
    "arbitrum": ["arb", "arbitrum"],
    "polygon": ["matic", "polygon"],
    "avalanche": ["avax", "avalanche"],
    "optimism": ["op", "optimism"],
    "solana": ["sol", "solana"],
}


def validate_chain(chain: str) -> str:
    """
    验证并规范化链名称
    
    Args:
        chain: 链名称（支持别名）
        
    Returns:
        str: 标准链名称
        
    Raises:
        ValueError: 不支持的链
        
    Examples:
        >>> validate_chain("eth")
        'ethereum'
        >>> validate_chain("BSC")
        'bsc'
    """
    chain_lower = chain.lower().strip()
    
    for standard_name, aliases in SUPPORTED_CHAINS.items():
        if chain_lower == standard_name or chain_lower in aliases:
            return standard_name
    
    raise ValueError(
        f"不支持的链: {chain}\n"
        f"支持的链: {', '.join(SUPPORTED_CHAINS.keys())}"
    )


def is_valid_address(chain: str, address: str) -> bool:
    """
    验证链上地址格式
    
    Args:
        chain: 链名称
        address: 地址字符串
        
    Returns:
        bool: 是否有效
        
    Examples:
        >>> is_valid_address("ethereum", "0x1234567890123456789012345678901234567890")
        True
        >>> is_valid_address("ethereum", "0x123")  # 太短
        False
    """
    chain = validate_chain(chain)
    
    if chain in ["ethereum", "bsc", "arbitrum", "polygon", "avalanche", "optimism"]:
        # EVM 地址：0x 开头，42 位
        pattern = r"^0x[a-fA-F0-9]{40}$"
        return bool(re.match(pattern, address))
    
    elif chain == "solana":
        # Solana 地址：32-44 个字符
        pattern = r"^[1-9A-HJ-NP-Za-km-z]{32,44}$"
        return bool(re.match(pattern, address))
    
    return False


def parse_address(address: str) -> Optional[dict]:
    """
    解析地址，自动识别链类型
    
    Args:
        address: 地址字符串
        
    Returns:
        Optional[dict]: {"chain": str, "address": str} 或 None
    """
    # EVM 地址
    evm_pattern = r"^0x[a-fA-F0-9]{40}$"
    if re.match(evm_pattern, address):
        # Ethereum
        return {"chain": "ethereum", "address": address}
    
    # Solana 地址
    solana_pattern = r"^[1-9A-HJ-NP-Za-km-z]{32,44}$"
    if re.match(solana_pattern, address):
        return {"chain": "solana", "address": address}
    
    return None


# ============================================
# 计算函数
# ============================================

def calculate_price_impact(
    amount_in: float,
    reserve_in: float,
    reserve_out: float
) -> float:
    """
    计算交易价格影响
    
    Args:
        amount_in: 输入金额
        reserve_in: 输入池储量
        reserve_out: 输出池储量
        
    Returns:
        float: 价格影响比例
    """
    amount_in_with_fee = amount_in * 0.997  # 假设 0.3% 手续费
    numerator = amount_in_with_fee * reserve_out
    denominator = reserve_in + amount_in_with_fee
    amount_out = numerator / denominator
    
    spot_price = reserve_out / reserve_in
    execution_price = amount_out / amount_in
    price_impact = (spot_price - execution_price) / spot_price
    
    return price_impact


def calculate_arbitrage_profit(
    buy_price: float,
    sell_price: float,
    amount: float,
    gas_cost: float,
    fee_rate: float = 0.003
) -> dict:
    """
    计算套利利润
    
    Args:
        buy_price: 买入价格
        sell_price: 卖出价格
        amount: 交易数量
        gas_cost: Gas 成本
        fee_rate: 交易费率（默认 0.3%）
        
    Returns:
        dict: 利润计算结果
    """
    cost = amount * buy_price
    gross_proceeds = amount * sell_price
    
    # 扣除交易费用
    trading_fees = cost * fee_rate + gross_proceeds * fee_rate
    
    # 净利润
    net_profit = gross_proceeds - cost - trading_fees - gas_cost
    
    # ROI
    total_investment = cost + gas_cost
    roi = (net_profit / total_investment * 100) if total_investment > 0 else 0
    
    return {
        "cost": cost,
        "gross_proceeds": gross_proceeds,
        "trading_fees": trading_fees,
        "gas_cost": gas_cost,
        "net_profit": net_profit,
        "roi_percent": roi,
        "spread_percent": ((sell_price - buy_price) / buy_price) * 100,
    }


# ============================================
# 工具类
# ============================================

class Timer:
    """简单计时器"""
    
    def __init__(self):
        self.start_time: Optional[datetime] = None
        self.end_time: Optional[datetime] = None
    
    def __enter__(self):
        self.start_time = datetime.utcnow()
        return self
    
    def __exit__(self, *args):
        self.end_time = datetime.utcnow()
    
    @property
    def elapsed(self) -> float:
        """返回经过的秒数"""
        if self.start_time is None:
            return 0
        end = self.end_time or datetime.utcnow()
        return (end - self.start_time).total_seconds()


# ============================================
# 日志增强
# ============================================

def setup_logger(
    name: str,
    level: int = logging.INFO,
    log_file: Optional[str] = None
) -> logging.Logger:
    """
    配置日志记录器
    
    Args:
        name: 日志记录器名称
        level: 日志级别
        log_file: 日志文件路径
        
    Returns:
        logging.Logger: 配置好的日志记录器
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)
    
    # 避免重复添加 handler
    if logger.handlers:
        return logger
    
    # Console Handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_format = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%H:%M:%S"
    )
    console_handler.setFormatter(console_format)
    logger.addHandler(console_handler)
    
    # File Handler
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(level)
        file_format = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | %(funcName)s:%(lineno)d | %(message)s"
        )
        file_handler.setFormatter(file_format)
        logger.addHandler(file_handler)
    
    return logger
