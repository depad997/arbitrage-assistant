"""
跨链套利机会检测服务 - Phase 2 核心功能
识别和评估可盈利的跨链套利机会

功能特性:
- 多链价格差异检测
- 跨链费用计算
- 利润估算
- 风险评估
- 套利路径生成
"""

import asyncio
import logging
from typing import Dict, List, Optional, Tuple, Any, Set
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
import uuid
import heapq

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
    get_chain_config,
    get_evm_chains,
)
from services.price_monitor import PriceMonitorService, TokenPrice
from services.bridge_fee_monitor import BridgeFeeMonitorService, BridgeFee, get_bridge_fee_monitor

logger = logging.getLogger(__name__)


# ============================================
# 枚举和常量
# ============================================

class RiskLevel(Enum):
    """风险等级"""
    VERY_LOW = "very_low"   # 几乎无风险
    LOW = "low"            # 低风险
    MEDIUM = "medium"      # 中等风险
    HIGH = "high"          # 高风险
    VERY_HIGH = "very_high"  # 极高风险

    @property
    def score(self) -> int:
        """风险分数（1-5）"""
        scores = {
            "very_low": 1,
            "low": 2,
            "medium": 3,
            "high": 4,
            "very_high": 5,
        }
        return scores.get(self.value, 3)


class OpportunityStatus(Enum):
    """机会状态"""
    DETECTED = "detected"      # 已检测
    EVALUATING = "evaluating"  # 评估中
    NOTIFIED = "notified"       # 已通知
    EXPIRED = "expired"        # 已过期
    EXECUTED = "executed"      # 已执行
    FAILED = "failed"          # 失败


class ExecutionRecommendation(Enum):
    """执行建议"""
    EXECUTE_NOW = "execute_now"       # 立即执行
    WAIT_AND_MONITOR = "wait_monitor" # 等待并监控
    SKIP = "skip"                      # 跳过
    MANUAL_REVIEW = "manual_review"   # 人工审核


# ============================================
# 数据类定义
# ============================================

@dataclass
class ArbitrageOpportunity:
    """
    跨链套利机会
    
    代表一个检测到的潜在套利机会
    """
    # 基本信息
    id: str
    symbol: str
    source_chain: str
    target_chain: str
    bridge: str
    
    # 价格信息
    buy_price: float          # 买入价 (source chain)
    sell_price: float         # 卖出价 (target chain)
    price_diff_pct: float     # 价差百分比
    price_diff_usd: float     # 价差 (USD)
    
    # 流动性
    source_liquidity: float   # 源链流动性
    target_liquidity: float   # 目标链流动性
    min_liquidity: float      # 最小流动性
    
    # 费用成本
    cross_chain_fee: float     # 跨链费用 (USD)
    gas_fee_source: float     # 源链 Gas 费用 (USD)
    gas_fee_target: float     # 目标链 Gas 费用 (USD)
    estimated_slippage: float # 预估滑点 (USD)
    total_cost: float         # 总成本 (USD)
    
    # 利润计算
    trade_amount_usd: float   # 建议交易金额 (USD)
    gross_profit_usd: float   # 毛利润 (USD)
    net_profit_usd: float     # 净利润 (USD)
    net_profit_pct: float     # 净利润百分比
    
    # 时间估计
    estimated_duration_minutes: int  # 预计完成时间
    time_window_minutes: int        # 有效时间窗口
    
    # 风险评估
    risk_level: RiskLevel = RiskLevel.MEDIUM
    risk_score: float = 0.5        # 风险分数 0-1
    risk_factors: List[str] = field(default_factory=list)
    time_risk: float = 0.0         # 时间窗口风险
    liquidity_risk: float = 0.0   # 流动性风险
    execution_risk: float = 0.0    # 执行失败风险
    
    # 执行建议
    recommendation: ExecutionRecommendation = ExecutionRecommendation.WAIT_AND_MONITOR
    confidence: float = 0.5        # 置信度 0-1
    
    # 时间戳
    detected_at: datetime = field(default_factory=datetime.now)
    expires_at: Optional[datetime] = None
    status: OpportunityStatus = OpportunityStatus.DETECTED
    
    # 附加信息
    source_pair_address: str = ""
    target_pair_address: str = ""
    execution_links: Dict[str, str] = field(default_factory=dict)
    
    @property
    def age_seconds(self) -> float:
        """检测后经过的时间（秒）"""
        return (datetime.now() - self.detected_at).total_seconds()
    
    @property
    def age_minutes(self) -> float:
        """检测后经过的时间（分钟）"""
        return self.age_seconds / 60
    
    @property
    def is_expired(self) -> bool:
        """是否已过期"""
        if self.expires_at:
            return datetime.now() > self.expires_at
        return self.age_minutes > self.time_window_minutes
    
    @property
    def is_profitable(self) -> bool:
        """是否盈利"""
        return self.net_profit_usd > 0
    
    @property
    def roi_annualized(self) -> float:
        """年化收益率"""
        if self.estimated_duration_minutes <= 0:
            return 0
        
        # 假设每天可以执行 24 * 60 / duration 次
        daily_rounds = 24 * 60 / self.estimated_duration_minutes
        daily_roi = self.net_profit_pct / 100
        
        return daily_roi * daily_rounds * 365 * 100
    
    @property
    def profit_cost_ratio(self) -> float:
        """利润成本比"""
        if self.total_cost <= 0:
            return 0
        return self.net_profit_usd / self.total_cost
    
    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            "id": self.id,
            "symbol": self.symbol,
            "source_chain": self.source_chain,
            "target_chain": self.target_chain,
            "bridge": self.bridge,
            "buy_price": self.buy_price,
            "sell_price": self.sell_price,
            "price_diff_pct": self.price_diff_pct,
            "price_diff_usd": self.price_diff_usd,
            "source_liquidity": self.source_liquidity,
            "target_liquidity": self.target_liquidity,
            "cross_chain_fee": self.cross_chain_fee,
            "gas_fee_source": self.gas_fee_source,
            "gas_fee_target": self.gas_fee_target,
            "estimated_slippage": self.estimated_slippage,
            "total_cost": self.total_cost,
            "trade_amount_usd": self.trade_amount_usd,
            "gross_profit_usd": self.gross_profit_usd,
            "net_profit_usd": self.net_profit_usd,
            "net_profit_pct": self.net_profit_pct,
            "estimated_duration_minutes": self.estimated_duration_minutes,
            "time_window_minutes": self.time_window_minutes,
            "risk_level": self.risk_level.value,
            "risk_score": self.risk_score,
            "risk_factors": self.risk_factors,
            "time_risk": self.time_risk,
            "liquidity_risk": self.liquidity_risk,
            "execution_risk": self.execution_risk,
            "recommendation": self.recommendation.value,
            "confidence": self.confidence,
            "detected_at": self.detected_at.isoformat(),
            "age_minutes": self.age_minutes,
            "is_expired": self.is_expired,
            "is_profitable": self.is_profitable,
            "roi_annualized": self.roi_annualized,
            "profit_cost_ratio": self.profit_cost_ratio,
            "status": self.status.value,
        }


@dataclass
class ArbitrageConfig:
    """套利配置"""
    # 利润阈值
    min_profit_threshold_usd: float = 10.0      # 最小绝对利润 (USD)
    min_profit_threshold_pct: float = 0.5       # 最小利润百分比
    
    # 流动性要求
    min_liquidity: float = 50000.0              # 最小流动性 (USD)
    min_liquidity_ratio: float = 0.1             # 流动性与交易额比例
    
    # 风险控制
    max_risk_score: float = 0.8                  # 最大风险分数
    max_cost_ratio: float = 0.5                  # 最大成本比例（成本/利润）
    max_slippage: float = 1.0                     # 最大滑点 (%)
    
    # 时间设置
    min_time_window: int = 5                     # 最小时间窗口（分钟）
    max_execution_time: int = 30                 # 最大执行时间（分钟）
    opportunity_ttl: int = 600                    # 机会有效期（秒）
    
    # 交易参数
    default_trade_amount: float = 10000.0         # 默认交易金额 (USD)
    max_trade_amount: float = 100000.0           # 最大交易金额 (USD)
    
    # 监控设置
    monitoring_chains: List[str] = None          # 监控的链列表
    monitoring_symbols: List[str] = None         # 监控的代币列表
    
    def __post_init__(self):
        if self.monitoring_chains is None:
            self.monitoring_chains = get_evm_chains()
        if self.monitoring_symbols is None:
            self.monitoring_symbols = ["ETH", "WBTC", "USDC", "USDT"]


# ============================================
# 风险评估器
# ============================================

class RiskAssessor:
    """
    风险评估器
    
    评估套利机会的风险等级
    """
    
    # 风险因子权重
    WEIGHTS = {
        "time_window": 0.25,    # 时间窗口风险权重
        "liquidity": 0.30,      # 流动性风险权重
        "execution": 0.25,      # 执行风险权重
        "price_volatility": 0.20,  # 价格波动风险权重
    }
    
    def __init__(self, config: ArbitrageConfig = None):
        self.config = config or ArbitrageConfig()
    
    def assess(
        self,
        opportunity: ArbitrageOpportunity,
        price_volatility: float = 0.02  # 价格波动率（每小时）
    ) -> Tuple[RiskLevel, float, List[str]]:
        """
        评估套利机会的风险
        
        Returns:
            (风险等级, 风险分数, 风险因素列表)
        """
        risk_factors = []
        total_risk = 0.0
        
        # 1. 时间窗口风险
        time_risk = self._assess_time_risk(opportunity)
        total_risk += time_risk * self.WEIGHTS["time_window"]
        if time_risk > 0.5:
            risk_factors.append(f"时间窗口风险高 ({time_risk:.1%})")
        
        # 2. 流动性风险
        liquidity_risk = self._assess_liquidity_risk(opportunity)
        total_risk += liquidity_risk * self.WEIGHTS["liquidity"]
        if liquidity_risk > 0.5:
            risk_factors.append(f"流动性风险 ({liquidity_risk:.1%})")
        
        # 3. 执行失败风险
        execution_risk = self._assess_execution_risk(opportunity)
        total_risk += execution_risk * self.WEIGHTS["execution"]
        if execution_risk > 0.5:
            risk_factors.append(f"执行风险 ({execution_risk:.1%})")
        
        # 4. 价格波动风险
        volatility_risk = self._assess_volatility_risk(
            opportunity, price_volatility
        )
        total_risk += volatility_risk * self.WEIGHTS["price_volatility"]
        if volatility_risk > 0.5:
            risk_factors.append(f"价格波动风险 ({volatility_risk:.1%})")
        
        # 确定风险等级
        risk_level = self._get_risk_level(total_risk)
        
        return risk_level, min(total_risk, 1.0), risk_factors
    
    def _assess_time_risk(self, opp: ArbitrageOpportunity) -> float:
        """评估时间窗口风险"""
        # 剩余可用时间比例
        remaining_ratio = 1.0 - (opp.age_minutes / opp.time_window_minutes)
        remaining_ratio = max(0, min(1, remaining_ratio))
        
        # 跨链耗时与时间窗口的比例
        duration_ratio = opp.estimated_duration_minutes / opp.time_window_minutes
        
        # 时间风险 = 执行时间占比 * (1 - 剩余时间比例)
        time_risk = duration_ratio * (1 - remaining_ratio)
        
        return min(time_risk, 1.0)
    
    def _assess_liquidity_risk(self, opp: ArbitrageOpportunity) -> float:
        """评估流动性风险"""
        # 基于流动性与交易额的比例
        required_liquidity = opp.trade_amount_usd * 2  # 需要两倍流动性
        
        source_risk = 1.0 - min(opp.source_liquidity / required_liquidity, 1.0)
        target_risk = 1.0 - min(opp.target_liquidity / required_liquidity, 1.0)
        
        # 最大流动性风险
        return max(source_risk, target_risk)
    
    def _assess_execution_risk(self, opp: ArbitrageOpportunity) -> float:
        """评估执行失败风险"""
        risk = 0.0
        
        # 跨链费用较高时执行风险增加
        if opp.cross_chain_fee > opp.gross_profit_usd * 0.3:
            risk += 0.2
        
        # 预估滑点较大时风险增加
        slippage_ratio = opp.estimated_slippage / opp.gross_profit_usd
        if slippage_ratio > 0.2:
            risk += 0.3
        
        # 非主流链风险更高
        risky_chains = ["sui", "aptos", "berachain"]
        if opp.source_chain in risky_chains or opp.target_chain in risky_chains:
            risk += 0.15
        
        # 金额较大时执行风险增加
        if opp.trade_amount_usd > self.config.max_trade_amount * 0.5:
            risk += 0.1
        
        return min(risk, 1.0)
    
    def _assess_volatility_risk(
        self,
        opp: ArbitrageOpportunity,
        hourly_volatility: float
    ) -> float:
        """评估价格波动风险"""
        # 预计执行期间的价格波动
        hours = opp.estimated_duration_minutes / 60
        expected_move = hourly_volatility * hours * 2  # 双向波动
        
        # 波动相对于利润的比例
        volatility_risk = expected_move / (opp.price_diff_pct / 100)
        
        return min(volatility_risk, 1.0)
    
    def _get_risk_level(self, risk_score: float) -> RiskLevel:
        """根据风险分数确定风险等级"""
        if risk_score < 0.2:
            return RiskLevel.VERY_LOW
        elif risk_score < 0.4:
            return RiskLevel.LOW
        elif risk_score < 0.6:
            return RiskLevel.MEDIUM
        elif risk_score < 0.8:
            return RiskLevel.HIGH
        else:
            return RiskLevel.VERY_HIGH


# ============================================
# 利润计算器
# ============================================

class ProfitCalculator:
    """
    利润计算器
    
    计算套利机会的预期利润
    """
    
    def __init__(self, config: ArbitrageConfig = None):
        self.config = config or ArbitrageConfig()
    
    def calculate(
        self,
        symbol: str,
        source_chain: str,
        target_chain: str,
        buy_price: float,
        sell_price: float,
        source_liquidity: float,
        target_liquidity: float,
        cross_chain_fee: BridgeFee,
        trade_amount_usd: float = None
    ) -> ArbitrageOpportunity:
        """
        计算套利利润
        
        Args:
            symbol: 代币符号
            source_chain: 源链
            target_chain: 目标链
            buy_price: 买入价
            sell_price: 卖出价
            source_liquidity: 源链流动性
            target_liquidity: 目标链流动性
            cross_chain_fee: 跨链费用
            trade_amount_usd: 交易金额（USD）
            
        Returns:
            ArbitrageOpportunity
        """
        # 确定交易金额
        if trade_amount_usd is None:
            trade_amount_usd = self.config.default_trade_amount
        
        # 根据流动性限制交易金额
        max_by_liquidity = min(source_liquidity, target_liquidity) * self.config.min_liquidity_ratio
        trade_amount_usd = min(trade_amount_usd, max_by_liquidity, self.config.max_trade_amount)
        
        # 计算价差
        price_diff_pct = ((sell_price - buy_price) / buy_price) * 100
        price_diff_usd = (sell_price - buy_price) * (trade_amount_usd / buy_price)
        
        # 毛利润
        gross_profit_usd = price_diff_usd
        
        # 计算成本
        gas_fee_source = cross_chain_fee.gas_fee_source if cross_chain_fee else 0
        gas_fee_target = cross_chain_fee.gas_fee_target if cross_chain_fee else 0
        bridge_fee = cross_chain_fee.total_cost_usd if cross_chain_fee else 0
        
        # 预估滑点（简化计算）
        slippage_pct = self._estimate_slippage(trade_amount_usd, source_liquidity)
        slippage_usd = trade_amount_usd * slippage_pct / 100
        
        total_cost = gas_fee_source + gas_fee_target + bridge_fee + slippage_usd
        
        # 净利润
        net_profit_usd = gross_profit_usd - total_cost
        net_profit_pct = (net_profit_usd / trade_amount_usd) * 100 if trade_amount_usd > 0 else 0
        
        # 估算执行时间
        estimated_duration = cross_chain_fee.estimated_time_minutes if cross_chain_fee else 20
        
        # 创建机会对象
        opportunity = ArbitrageOpportunity(
            id=str(uuid.uuid4())[:8],
            symbol=symbol,
            source_chain=source_chain,
            target_chain=target_chain,
            bridge=cross_chain_fee.bridge if cross_chain_fee else "layerzero",
            buy_price=buy_price,
            sell_price=sell_price,
            price_diff_pct=price_diff_pct,
            price_diff_usd=price_diff_usd,
            source_liquidity=source_liquidity,
            target_liquidity=target_liquidity,
            min_liquidity=self.config.min_liquidity,
            cross_chain_fee=bridge_fee,
            gas_fee_source=gas_fee_source,
            gas_fee_target=gas_fee_target,
            estimated_slippage=slippage_usd,
            total_cost=total_cost,
            trade_amount_usd=trade_amount_usd,
            gross_profit_usd=gross_profit_usd,
            net_profit_usd=net_profit_usd,
            net_profit_pct=net_profit_pct,
            estimated_duration_minutes=estimated_duration,
            time_window_minutes=self.config.min_time_window,
            expires_at=datetime.now() + timedelta(seconds=self.config.opportunity_ttl),
        )
        
        return opportunity
    
    def _estimate_slippage(self, amount_usd: float, liquidity: float) -> float:
        """估算滑点"""
        if liquidity <= 0:
            return 5.0  # 高滑点
        
        # 简化滑点模型：金额占比越高，滑点越大
        amount_ratio = amount_usd / liquidity
        
        # 线性模型，1% 占比约 0.5% 滑点
        slippage = amount_ratio * 50
        return min(slippage, 5.0)  # 最高 5%


# ============================================
# 套利机会检测器
# ============================================

class OpportunityDetector:
    """
    跨链套利机会检测器
    
    核心功能：
    1. 监控多链价格差异
    2. 计算跨链套利利润
    3. 评估风险和时间窗口
    4. 生成执行建议
    """
    
    def __init__(
        self,
        config: ArbitrageConfig = None,
        price_monitor: PriceMonitorService = None,
        fee_monitor: BridgeFeeMonitorService = None
    ):
        """
        初始化检测器
        
        Args:
            config: 套利配置
            price_monitor: 价格监控服务
            fee_monitor: 费用监控服务
        """
        self.config = config or ArbitrageConfig()
        self.price_monitor = price_monitor
        self.fee_monitor = fee_monitor
        
        # 初始化子模块
        self.risk_assessor = RiskAssessor(self.config)
        self.profit_calculator = ProfitCalculator(self.config)
        
        # 机会存储
        self.opportunities: List[ArbitrageOpportunity] = []
        self._opportunity_map: Dict[str, ArbitrageOpportunity] = {}
        
        # 价格缓存
        self._price_cache: Dict[str, TokenPrice] = {}
        self._price_cache_time: Dict[str, datetime] = {}
        
        # 统计
        self.stats = {
            "total_detected": 0,
            "profitable_count": 0,
            "high_confidence_count": 0,
        }
        
        logger.info("[OpportunityDetector] Initialized")
    
    async def detect_opportunities(
        self,
        symbol: str = None,
        chains: List[str] = None
    ) -> List[ArbitrageOpportunity]:
        """
        检测套利机会
        
        Args:
            symbol: 特定代币（可选）
            chains: 特定链列表（可选）
            
        Returns:
            检测到的套利机会列表
        """
        chains = chains or self.config.monitoring_chains
        symbols = [symbol] if symbol else self.config.monitoring_symbols
        
        all_opportunities = []
        
        for sym in symbols:
            for src_chain in chains:
                for dst_chain in chains:
                    if src_chain == dst_chain:
                        continue
                    
                    try:
                        opp = await self._check_pair(
                            symbol=sym,
                            source_chain=src_chain,
                            target_chain=dst_chain
                        )
                        if opp:
                            all_opportunities.append(opp)
                    except Exception as e:
                        logger.debug(f"[Detector] Error checking {sym} {src_chain}->{dst_chain}: {e}")
        
        # 排序和过滤
        all_opportunities = self._filter_and_rank(all_opportunities)
        
        # 更新存储
        self._update_opportunities(all_opportunities)
        
        return all_opportunities
    
    async def _check_pair(
        self,
        symbol: str,
        source_chain: str,
        target_chain: str
    ) -> Optional[ArbitrageOpportunity]:
        """检查特定交易对的套利机会"""
        # 获取价格
        buy_price, buy_liquidity = await self._get_price(source_chain, symbol)
        sell_price, sell_liquidity = await self._get_price(target_chain, symbol)
        
        if not buy_price or not sell_price:
            return None
        
        # 检查是否存在价差
        price_diff_pct = abs((sell_price - buy_price) / buy_price) * 100
        
        # 低于阈值则跳过
        if price_diff_pct < self.config.min_profit_threshold_pct:
            return None
        
        # 获取跨链费用
        fee = await self._get_cross_chain_fee(source_chain, target_chain)
        
        # 计算利润
        opportunity = self.profit_calculator.calculate(
            symbol=symbol,
            source_chain=source_chain,
            target_chain=target_chain,
            buy_price=buy_price,
            sell_price=sell_price,
            source_liquidity=buy_liquidity,
            target_liquidity=sell_liquidity,
            cross_chain_fee=fee,
        )
        
        # 风险评估
        risk_level, risk_score, risk_factors = self.risk_assessor.assess(opportunity)
        opportunity.risk_level = risk_level
        opportunity.risk_score = risk_score
        opportunity.risk_factors = risk_factors
        opportunity.time_risk = self.risk_assessor._assess_time_risk(opportunity)
        opportunity.liquidity_risk = self.risk_assessor._assess_liquidity_risk(opportunity)
        opportunity.execution_risk = self.risk_assessor._assess_execution_risk(opportunity)
        
        # 生成执行建议
        opportunity.recommendation = self._generate_recommendation(opportunity)
        
        # 计算置信度
        opportunity.confidence = self._calculate_confidence(opportunity)
        
        # 更新统计
        self.stats["total_detected"] += 1
        if opportunity.is_profitable:
            self.stats["profitable_count"] += 1
        if opportunity.confidence > 0.7:
            self.stats["high_confidence_count"] += 1
        
        return opportunity
    
    async def _get_price(self, chain: str, symbol: str) -> Tuple[Optional[float], float]:
        """获取代币价格"""
        cache_key = f"{chain}:{symbol}"
        
        # 检查缓存
        if cache_key in self._price_cache:
            cached_time = self._price_cache_time.get(cache_key)
            if cached_time and (datetime.now() - cached_time).total_seconds() < 60:
                price = self._price_cache[cache_key]
                return price.price_usd, price.liquidity_usd
        
        # 优先从链上获取价格（最可靠）
        try:
            from services.onchain_price import get_onchain_price_service
            onchain_svc = await get_onchain_price_service()
            onchain_price = await onchain_svc.get_token_price(chain, symbol)
            if onchain_price:
                logger.info(f"[Detector] Got onchain price for {chain}:{symbol}: ${onchain_price:.2f}")
                # 创建缓存对象
                mock_price = TokenPrice(
                    symbol=symbol,
                    chain=chain,
                    price_usd=onchain_price,
                    price_raw=onchain_price,
                    liquidity_usd=1000000,
                    volume_24h=500000,
                    price_change_24h=0,
                    tx_count_24h=100,
                    pair_address="onchain",
                    dex="uniswap",
                    timestamp=datetime.now(),
                    source="onchain"
                )
                self._price_cache[cache_key] = mock_price
                self._price_cache_time[cache_key] = datetime.now()
                return onchain_price, 1000000
        except Exception as e:
            logger.debug(f"[Detector] Onchain price fetch error for {chain}:{symbol}: {e}")
        
        # 从价格监控服务获取
        if self.price_monitor:
            try:
                price = await self.price_monitor.get_token_price(
                    chain=chain,
                    symbol=symbol
                )
                if price:
                    self._price_cache[cache_key] = price
                    self._price_cache_time[cache_key] = datetime.now()
                    return price.price_usd, price.liquidity_usd
            except Exception as e:
                logger.debug(f"[Detector] Price fetch error for {chain}:{symbol}: {e}")
        
        # 返回模拟数据用于测试
        return self._get_mock_price(chain, symbol)
    
    def _get_mock_price(self, chain: str, symbol: str) -> Tuple[float, float]:
        """获取模拟价格（当无法获取真实价格时）"""
        import random
        
        # 基础价格（基于 Wormhole/LayerZero 跨链代币）
        BASE_PRICES = {
            # 稳定币
            "USDC": 1.0, "USDT": 1.0, "DAI": 1.0, "BUSD": 1.0, "TUSD": 1.0,
            # 主流币
            "ETH": 3500, "WETH": 3500, "WBTC": 65000, "BTC": 65000, "BTC.b": 65000,
            "BNB": 600, "MATIC": 0.85, "AVAX": 35, "SOL": 150,
            "ATOM": 8, "DOT": 7, "ADA": 0.5, "XRP": 0.5, "LTC": 85,
            # DeFi 代币
            "LINK": 14, "UNI": 7, "AAVE": 170, "MKR": 3000,
            "CRV": 0.5, "COMP": 60, "SUSHI": 1.2, "SNX": 3,
            # L2 代币
            "ARB": 1.2, "OP": 3.5,
            # 跨链桥代币
            "W": 0.8, "STG": 0.5, "SYN": 0.8, "AXL": 1.2, "ZRO": 3,
            # 流动性质押
            "stETH": 3500, "wstETH": 4100, "rETH": 3700,
            # Meme 币
            "PEPE": 0.00001, "SHIB": 0.00001, "BONK": 0.00002, "WIF": 2.5, "DOGE": 0.15,
            # GameFi
            "SAND": 0.5, "MANA": 0.4, "AXS": 8, "IMX": 2.5,
            # RWA
            "ONDO": 1.2,
            # 其他
            "CAKE": 2.5, "JOE": 0.5, "GMX": 50,
        }
        
        base_price = BASE_PRICES.get(symbol, 100)
        
        # 添加链间差异（模拟套利机会）
        chain_offset = {
            "ethereum": 0,
            "arbitrum": random.uniform(-0.02, 0.02),
            "optimism": random.uniform(-0.02, 0.02),
            "base": random.uniform(-0.03, 0.03),
            "polygon": random.uniform(-0.01, 0.01),
            "bsc": random.uniform(-0.015, 0.015),
            "avalanche": random.uniform(-0.02, 0.02),
        }
        
        offset = chain_offset.get(chain, 0)
        price = base_price * (1 + offset)
        
        # 流动性模拟
        liquidity = base_price * random.uniform(100000, 5000000)
        
        return price, liquidity
    
    async def _get_cross_chain_fee(
        self,
        source_chain: str,
        target_chain: str
    ) -> Optional[BridgeFee]:
        """获取跨链费用"""
        if self.fee_monitor:
            return await self.fee_monitor.get_best_bridge(source_chain, target_chain)
        
        # 返回默认费用
        from services.bridge_fee_monitor import BridgeFee
        return BridgeFee(
            bridge="layerzero",
            source_chain=source_chain,
            target_chain=target_chain,
            token_symbol="ETH",
            gas_fee_source=5,
            gas_fee_target=2,
            total_cost_usd=10,
            estimated_time_minutes=15,
        )
    
    def _filter_and_rank(
        self,
        opportunities: List[ArbitrageOpportunity]
    ) -> List[ArbitrageOpportunity]:
        """过滤和排序机会"""
        # 过滤无效机会
        valid_opportunities = [
            opp for opp in opportunities
            if self._is_valid_opportunity(opp)
        ]
        
        # 按利润排序
        valid_opportunities.sort(
            key=lambda x: x.net_profit_usd,
            reverse=True
        )
        
        return valid_opportunities
    
    def _is_valid_opportunity(self, opp: ArbitrageOpportunity) -> bool:
        """检查机会是否有效"""
        # 检查利润阈值
        if opp.net_profit_usd < self.config.min_profit_threshold_usd:
            return False
        
        # 检查流动性
        if opp.source_liquidity < self.config.min_liquidity:
            return False
        if opp.target_liquidity < self.config.min_liquidity:
            return False
        
        # 检查风险
        if opp.risk_score > self.config.max_risk_score:
            return False
        
        # 检查成本比例
        cost_ratio = opp.total_cost / opp.gross_profit_usd if opp.gross_profit_usd > 0 else 1
        if cost_ratio > self.config.max_cost_ratio:
            return False
        
        return True
    
    def _generate_recommendation(
        self,
        opportunity: ArbitrageOpportunity
    ) -> ExecutionRecommendation:
        """生成执行建议"""
        # 高利润、低风险 -> 立即执行
        if opportunity.net_profit_usd > 100 and opportunity.risk_score < 0.3:
            return ExecutionRecommendation.EXECUTE_NOW
        
        # 非常高利润 -> 立即执行
        if opportunity.net_profit_usd > 500:
            return ExecutionRecommendation.EXECUTE_NOW
        
        # 高风险 -> 人工审核
        if opportunity.risk_score > 0.6:
            return ExecutionRecommendation.MANUAL_REVIEW
        
        # 中等利润、中等风险 -> 等待监控
        if opportunity.net_profit_usd > 20:
            return ExecutionRecommendation.WAIT_AND_MONITOR
        
        # 低利润 -> 跳过
        return ExecutionRecommendation.SKIP
    
    def _calculate_confidence(self, opportunity: ArbitrageOpportunity) -> float:
        """计算置信度"""
        confidence = 0.5  # 基础置信度
        
        # 流动性高增加置信度
        liquidity_factor = min(
            opportunity.source_liquidity / 1000000,
            opportunity.target_liquidity / 1000000
        )
        confidence += liquidity_factor * 0.2
        
        # 风险低增加置信度
        confidence += (1 - opportunity.risk_score) * 0.2
        
        # 利润高增加置信度
        if opportunity.net_profit_usd > 50:
            confidence += 0.1
        
        return min(max(confidence, 0), 1)
    
    def _update_opportunities(
        self,
        new_opportunities: List[ArbitrageOpportunity]
    ) -> None:
        """更新机会存储"""
        for opp in new_opportunities:
            self._opportunity_map[opp.id] = opp
        
        # 移除过期机会
        expired_ids = [
            opp_id for opp_id, opp in self._opportunity_map.items()
            if opp.is_expired
        ]
        for opp_id in expired_ids:
            del self._opportunity_map[opp_id]
        
        # 更新列表
        self.opportunities = sorted(
            self._opportunity_map.values(),
            key=lambda x: x.net_profit_usd,
            reverse=True
        )
    
    def get_opportunities_by_status(
        self,
        status: OpportunityStatus
    ) -> List[ArbitrageOpportunity]:
        """按状态获取机会"""
        return [opp for opp in self.opportunities if opp.status == status]
    
    def get_top_opportunities(
        self,
        limit: int = 10,
        min_profit: float = None
    ) -> List[ArbitrageOpportunity]:
        """获取最优机会"""
        opps = self.opportunities
        
        if min_profit:
            opps = [o for o in opps if o.net_profit_usd >= min_profit]
        
        return opps[:limit]
    
    def get_stats(self) -> Dict:
        """获取统计信息"""
        return {
            **self.stats,
            "total_opportunities": len(self.opportunities),
            "profitable_opportunities": len([
                o for o in self.opportunities if o.is_profitable
            ]),
            "avg_profit": sum(o.net_profit_usd for o in self.opportunities) / max(len(self.opportunities), 1),
            "max_profit": max((o.net_profit_usd for o in self.opportunities), default=0),
        }
    
    def clear_expired(self) -> int:
        """清理过期机会"""
        before = len(self.opportunities)
        expired = [o for o in self.opportunities if o.is_expired]
        for opp in expired:
            opp.status = OpportunityStatus.EXPIRED
            if opp.id in self._opportunity_map:
                del self._opportunity_map[opp.id]
        self.opportunities = [o for o in self.opportunities if not o.is_expired]
        return before - len(self.opportunities)


# ============================================
# 服务入口
# ============================================

class OpportunityDetectorService:
    """
    套利机会检测服务
    
    提供高层 API
    """
    
    def __init__(self, config: ArbitrageConfig = None):
        self.config = config or ArbitrageConfig()
        self.detector: Optional[OpportunityDetector] = None
        self._initialized = False
    
    async def initialize(
        self,
        price_monitor: PriceMonitorService = None,
        fee_monitor: BridgeFeeMonitorService = None
    ) -> None:
        """初始化服务"""
        if self._initialized:
            return
        
        self.detector = OpportunityDetector(
            config=self.config,
            price_monitor=price_monitor,
            fee_monitor=fee_monitor or get_bridge_fee_monitor(),
        )
        self._initialized = True
        logger.info("[OpportunityDetectorService] Initialized")
    
    async def scan(self) -> List[ArbitrageOpportunity]:
        """扫描套利机会"""
        if not self._initialized:
            await self.initialize()
        
        return await self.detector.detect_opportunities()
    
    async def scan_symbol(
        self,
        symbol: str
    ) -> List[ArbitrageOpportunity]:
        """扫描特定代币的套利机会"""
        if not self._initialized:
            await self.initialize()
        
        return await self.detector.detect_opportunities(symbol=symbol)
    
    def get_opportunities(
        self,
        min_profit: float = None,
        limit: int = 10
    ) -> List[ArbitrageOpportunity]:
        """获取当前机会"""
        if not self._initialized or not self.detector:
            return []
        
        return self.detector.get_top_opportunities(limit=limit, min_profit=min_profit)
    
    def get_stats(self) -> Dict:
        """获取统计"""
        if not self._initialized or not self.detector:
            return {}
        
        return self.detector.get_stats()


# ============================================
# 全局实例
# ============================================

opportunity_detector_service = OpportunityDetectorService()


async def get_opportunities(
    min_profit: float = 10,
    limit: int = 10
) -> List[ArbitrageOpportunity]:
    """获取套利机会的便捷函数"""
    await opportunity_detector_service.scan()
    return opportunity_detector_service.get_opportunities(min_profit=min_profit, limit=limit)
