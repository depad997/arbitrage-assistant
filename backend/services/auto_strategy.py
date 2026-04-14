"""
自动化策略引擎 - Phase 3 全自动执行核心组件

功能：
- 多策略支持（保守/激进/平衡）
- 策略参数配置
- 策略切换和动态调整
- 机会评估
- 风险评分计算
- 执行决策
- 策略回测

设计原则：
- 安全第一：所有决策都有风险评估
- 可配置：所有参数可调整
- 可观测：完整的日志和统计
"""

import asyncio
import logging
from typing import Dict, List, Optional, Tuple, Any, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from collections import defaultdict
import json
import statistics
from abc import ABC, abstractmethod

import sys
import os as _os
_backend_dir = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from config.settings import SUPPORTED_CHAINS

logger = logging.getLogger(__name__)


# ============================================
# 枚举定义
# ============================================

class StrategyType(Enum):
    """策略类型"""
    CONSERVATIVE = "conservative"   # 保守策略
    BALANCED = "balanced"           # 平衡策略
    AGGRESSIVE = "aggressive"       # 激进策略
    CUSTOM = "custom"               # 自定义策略


class StrategyState(Enum):
    """策略状态"""
    ACTIVE = "active"
    PAUSED = "paused"
    STOPPED = "stopped"


class ExecutionDecision(Enum):
    """执行决策"""
    EXECUTE_IMMEDIATELY = "execute_immediately"   # 立即执行
    EXECUTE_WITH_DELAY = "execute_with_delay"    # 延迟执行
    MONITOR = "monitor"                          # 监控等待
    SKIP = "skip"                                # 跳过
    MANUAL_REVIEW = "manual_review"              # 人工审核


class OpportunityQuality(Enum):
    """机会质量评级"""
    EXCELLENT = "excellent"     # 优秀 (>0.8)
    GOOD = "good"              # 良好 (0.6-0.8)
    FAIR = "fair"              # 一般 (0.4-0.6)
    POOR = "poor"              # 较差 (0.2-0.4)
    VERY_POOR = "very_poor"    # 很差 (<0.2)


# ============================================
# 数据类定义
# ============================================

@dataclass
class StrategyParameters:
    """策略参数"""
    # 利润阈值
    min_profit_threshold_usd: float = 10.0        # 最小利润阈值 (USD)
    min_profit_threshold_pct: float = 0.5         # 最小利润阈值 (%)
    target_profit_threshold_pct: float = 2.0     # 目标利润阈值 (%)
    
    # 风险参数
    max_risk_score: float = 0.7                   # 最大风险评分
    max_single_trade_usd: float = 10000.0         # 单笔最大金额
    max_daily_trades: int = 10                     # 每日最大交易数
    max_daily_loss_usd: float = 500.0             # 每日最大亏损
    
    # 执行参数
    max_gas_price_gwei: float = 50.0              # 最大 Gas 价格
    max_slippage_pct: float = 0.5                 # 最大滑点
    execution_timeout_seconds: int = 300          # 执行超时
    
    # 置信度参数
    min_confidence_score: float = 0.6             # 最小置信度
    auto_execute_confidence: float = 0.8          # 自动执行置信度
    
    # 时间参数
    opportunity_validity_seconds: int = 60        # 机会有效期
    cooldown_seconds: int = 300                   # 冷却时间
    trading_hours_start: Optional[str] = None    # 交易开始时间 (UTC)
    trading_hours_end: Optional[str] = None       # 交易结束时间 (UTC)
    
    # 链级限制
    chain_max_trades: Dict[str, int] = field(default_factory=lambda: {
        "ethereum": 5, "arbitrum": 3, "optimism": 3,
        "base": 3, "polygon": 3, "bsc": 3
    })
    
    # 策略类型
    strategy_type: StrategyType = StrategyType.BALANCED


@dataclass
class StrategyPerformance:
    """策略表现统计"""
    total_trades: int = 0
    successful_trades: int = 0
    failed_trades: int = 0
    total_profit_usd: float = 0.0
    total_loss_usd: float = 0.0
    max_drawdown_usd: float = 0.0
    avg_profit_usd: float = 0.0
    avg_execution_time_seconds: float = 0.0
    win_rate: float = 0.0
    
    # 历史数据
    profit_history: List[float] = field(default_factory=list)
    trade_history: List[Dict] = field(default_factory=list)


@dataclass
class OpportunityEvaluation:
    """机会评估结果"""
    opportunity_id: str
    quality_score: float                          # 质量评分 (0-1)
    quality: OpportunityQuality
    risk_score: float                             # 风险评分 (0-1)
    profit_estimate_usd: float                    # 预估利润 (USD)
    profit_estimate_pct: float                    # 预估利润 (%)
    confidence: float                             # 置信度 (0-1)
    execution_decision: ExecutionDecision
    recommended_amount_usd: float                 # 推荐金额
    execution_priority: int                       # 执行优先级 (1-5)
    reasons: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    evaluated_at: datetime = field(default_factory=datetime.now)


@dataclass
class StrategyConfig:
    """策略配置"""
    name: str
    strategy_type: StrategyType
    parameters: StrategyParameters
    enabled_chains: List[str] = field(default_factory=list)
    enabled_tokens: List[str] = field(default_factory=list)
    state: StrategyState = StrategyState.PAUSED
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)


@dataclass
class BacktestResult:
    """回测结果"""
    strategy_name: str
    period_start: datetime
    period_end: datetime
    total_trades: int
    successful_trades: int
    failed_trades: int
    total_profit_usd: float
    total_loss_usd: float
    net_profit_usd: float
    max_drawdown_usd: float
    win_rate: float
    avg_profit_per_trade: float
    sharpe_ratio: float = 0.0
    avg_execution_time: float = 0.0
    chain_performance: Dict[str, Dict] = field(default_factory=dict)


# ============================================
# 基础策略类
# ============================================

class BaseStrategy(ABC):
    """策略基类"""
    
    def __init__(self, name: str, strategy_type: StrategyType):
        self.name = name
        self.strategy_type = strategy_type
        self.state = StrategyState.PAUSED
        self.performance = StrategyPerformance()
        
    @abstractmethod
    def evaluate(self, opportunity: Dict, context: Dict) -> OpportunityEvaluation:
        """评估机会"""
        pass
    
    @abstractmethod
    def should_execute(self, evaluation: OpportunityEvaluation) -> bool:
        """判断是否执行"""
        pass
    
    @abstractmethod
    def calculate_execution_amount(
        self, 
        evaluation: OpportunityEvaluation,
        available_balance: float
    ) -> float:
        """计算执行金额"""
        pass
    
    def get_parameters(self) -> StrategyParameters:
        """获取策略参数"""
        return self._parameters
    
    def update_parameters(self, params: StrategyParameters):
        """更新策略参数"""
        self._parameters = params
        logger.info(f"Strategy {self.name} parameters updated")


# ============================================
# 预置策略实现
# ============================================

class ConservativeStrategy(BaseStrategy):
    """保守策略 - 低风险低收益"""
    
    def __init__(self):
        super().__init__("Conservative", StrategyType.CONSERVATIVE)
        self._parameters = StrategyParameters(
            strategy_type=StrategyType.CONSERVATIVE,
            min_profit_threshold_usd=20.0,
            min_profit_threshold_pct=1.0,
            target_profit_threshold_pct=3.0,
            max_risk_score=0.4,
            max_single_trade_usd=5000.0,
            max_daily_trades=5,
            max_daily_loss_usd=200.0,
            max_gas_price_gwei=30.0,
            max_slippage_pct=0.3,
            min_confidence_score=0.75,
            auto_execute_confidence=0.85,
            cooldown_seconds=600,
        )
    
    def evaluate(self, opportunity: Dict, context: Dict) -> OpportunityEvaluation:
        """评估机会 - 保守策略更严格"""
        params = self._parameters
        
        # 基础评分计算
        quality_score = 0.5
        risk_score = 0.3
        reasons = []
        warnings = []
        
        # 利润评估
        profit_usd = opportunity.get("estimated_profit_usd", 0)
        profit_pct = opportunity.get("estimated_profit_pct", 0)
        
        if profit_pct >= params.target_profit_threshold_pct:
            quality_score += 0.3
            reasons.append(f"高利润: {profit_pct:.2f}%")
        elif profit_pct >= params.min_profit_threshold_pct:
            quality_score += 0.1
            reasons.append(f"达标利润: {profit_pct:.2f}%")
        else:
            quality_score -= 0.2
            warnings.append(f"利润偏低: {profit_pct:.2f}%")
        
        # 风险评估
        chain = opportunity.get("source_chain", "")
        gas_price = context.get("gas_price_gwei", 0)
        
        if gas_price > params.max_gas_price_gwei:
            risk_score += 0.3
            warnings.append(f"Gas价格较高: {gas_price} Gwei")
        
        # 流动性风险
        liquidity = opportunity.get("liquidity", 0)
        if liquidity < profit_usd * 10:
            risk_score += 0.2
            warnings.append("流动性可能不足")
        
        # 置信度评估
        confidence = opportunity.get("confidence", 0.5)
        if confidence >= params.auto_execute_confidence:
            quality_score += 0.2
            reasons.append(f"高置信度: {confidence:.0%}")
        
        # 机会质量
        quality_score = max(0, min(1, quality_score))
        risk_score = max(0, min(1, risk_score))
        
        quality = OpportunityQuality.EXCELLENT if quality_score >= 0.8 else \
                  OpportunityQuality.GOOD if quality_score >= 0.6 else \
                  OpportunityQuality.FAIR if quality_score >= 0.4 else \
                  OpportunityQuality.POOR
        
        # 执行决策
        decision = self._make_decision(quality_score, risk_score, confidence, params)
        
        # 推荐金额
        recommended = min(
            params.max_single_trade_usd,
            profit_usd * 5,  # 保守杠杆
            context.get("available_balance", 0) * 0.1  # 不超过余额的10%
        )
        
        return OpportunityEvaluation(
            opportunity_id=opportunity.get("id", ""),
            quality_score=quality_score,
            quality=quality,
            risk_score=risk_score,
            profit_estimate_usd=profit_usd,
            profit_estimate_pct=profit_pct,
            confidence=confidence,
            execution_decision=decision,
            recommended_amount_usd=recommended,
            execution_priority=self._calculate_priority(quality_score, risk_score),
            reasons=reasons,
            warnings=warnings,
        )
    
    def _make_decision(
        self, 
        quality_score: float, 
        risk_score: float, 
        confidence: float,
        params: StrategyParameters
    ) -> ExecutionDecision:
        """做出执行决策"""
        if quality_score < 0.4 or risk_score > params.max_risk_score:
            return ExecutionDecision.SKIP
        
        if confidence >= params.auto_execute_confidence and risk_score < 0.3:
            return ExecutionDecision.EXECUTE_IMMEDIATELY
        
        if confidence >= params.min_confidence_score:
            return ExecutionDecision.MONITOR
        
        return ExecutionDecision.MANUAL_REVIEW
    
    def _calculate_priority(self, quality_score: float, risk_score: float) -> int:
        """计算优先级 (1-5)"""
        score = quality_score - risk_score * 0.5
        return max(1, min(5, int(score * 5)))
    
    def should_execute(self, evaluation: OpportunityEvaluation) -> bool:
        """判断是否执行"""
        params = self._parameters
        
        if evaluation.risk_score > params.max_risk_score:
            return False
        if evaluation.confidence < params.min_confidence_score:
            return False
        if evaluation.profit_estimate_usd < params.min_profit_threshold_usd:
            return False
        
        return evaluation.execution_decision in [
            ExecutionDecision.EXECUTE_IMMEDIATELY,
            ExecutionDecision.EXECUTE_WITH_DELAY
        ]
    
    def calculate_execution_amount(
        self, 
        evaluation: OpportunityEvaluation,
        available_balance: float
    ) -> float:
        """计算执行金额"""
        params = self._parameters
        
        # 保守策略：使用较低的比例
        base_amount = min(
            available_balance * 0.2,  # 不超过余额的20%
            params.max_single_trade_usd,
            evaluation.profit_estimate_usd * 10  # 利润的10倍
        )
        
        # 根据质量调整
        if evaluation.quality == OpportunityQuality.EXCELLENT:
            base_amount *= 1.0
        elif evaluation.quality == OpportunityQuality.GOOD:
            base_amount *= 0.8
        else:
            base_amount *= 0.5
        
        return max(0, base_amount)


class BalancedStrategy(BaseStrategy):
    """平衡策略 - 中等风险中等收益"""
    
    def __init__(self):
        super().__init__("Balanced", StrategyType.BALANCED)
        self._parameters = StrategyParameters(
            strategy_type=StrategyType.BALANCED,
            min_profit_threshold_usd=10.0,
            min_profit_threshold_pct=0.5,
            target_profit_threshold_pct=2.0,
            max_risk_score=0.6,
            max_single_trade_usd=10000.0,
            max_daily_trades=10,
            max_daily_loss_usd=500.0,
            max_gas_price_gwei=50.0,
            max_slippage_pct=0.5,
            min_confidence_score=0.6,
            auto_execute_confidence=0.75,
            cooldown_seconds=300,
        )
    
    def evaluate(self, opportunity: Dict, context: Dict) -> OpportunityEvaluation:
        """评估机会 - 平衡策略"""
        params = self._parameters
        
        quality_score = 0.5
        risk_score = 0.4
        reasons = []
        warnings = []
        
        # 利润评估
        profit_usd = opportunity.get("estimated_profit_usd", 0)
        profit_pct = opportunity.get("estimated_profit_pct", 0)
        
        if profit_pct >= params.target_profit_threshold_pct:
            quality_score += 0.3
            reasons.append(f"高利润: {profit_pct:.2f}%")
        elif profit_pct >= params.min_profit_threshold_pct:
            quality_score += 0.15
            reasons.append(f"达标利润: {profit_pct:.2f}%")
        else:
            quality_score -= 0.1
            warnings.append(f"利润偏低: {profit_pct:.2f}%")
        
        # 风险评估
        gas_price = context.get("gas_price_gwei", 0)
        if gas_price > params.max_gas_price_gwei:
            risk_score += 0.2
            warnings.append(f"Gas价格较高: {gas_price} Gwei")
        
        liquidity = opportunity.get("liquidity", 0)
        if liquidity < profit_usd * 5:
            risk_score += 0.15
            warnings.append("流动性偏低")
        
        confidence = opportunity.get("confidence", 0.5)
        if confidence >= params.auto_execute_confidence:
            quality_score += 0.2
            reasons.append(f"高置信度: {confidence:.0%}")
        
        quality_score = max(0, min(1, quality_score))
        risk_score = max(0, min(1, risk_score))
        
        quality = OpportunityQuality.EXCELLENT if quality_score >= 0.8 else \
                  OpportunityQuality.GOOD if quality_score >= 0.6 else \
                  OpportunityQuality.FAIR if quality_score >= 0.4 else \
                  OpportunityQuality.POOR
        
        decision = self._make_decision(quality_score, risk_score, confidence, params)
        
        recommended = min(
            params.max_single_trade_usd,
            profit_usd * 20,
            context.get("available_balance", 0) * 0.3
        )
        
        return OpportunityEvaluation(
            opportunity_id=opportunity.get("id", ""),
            quality_score=quality_score,
            quality=quality,
            risk_score=risk_score,
            profit_estimate_usd=profit_usd,
            profit_estimate_pct=profit_pct,
            confidence=confidence,
            execution_decision=decision,
            recommended_amount_usd=recommended,
            execution_priority=self._calculate_priority(quality_score, risk_score),
            reasons=reasons,
            warnings=warnings,
        )
    
    def _make_decision(
        self, 
        quality_score: float, 
        risk_score: float, 
        confidence: float,
        params: StrategyParameters
    ) -> ExecutionDecision:
        if quality_score < 0.3 or risk_score > params.max_risk_score:
            return ExecutionDecision.SKIP
        
        if confidence >= params.auto_execute_confidence and risk_score < 0.4:
            return ExecutionDecision.EXECUTE_IMMEDIATELY
        
        if confidence >= params.min_confidence_score:
            return ExecutionDecision.MONITOR
        
        return ExecutionDecision.MANUAL_REVIEW
    
    def _calculate_priority(self, quality_score: float, risk_score: float) -> int:
        score = quality_score - risk_score * 0.3
        return max(1, min(5, int(score * 5)))
    
    def should_execute(self, evaluation: OpportunityEvaluation) -> bool:
        params = self._parameters
        
        if evaluation.risk_score > params.max_risk_score:
            return False
        if evaluation.confidence < params.min_confidence_score:
            return False
        if evaluation.profit_estimate_usd < params.min_profit_threshold_usd:
            return False
        
        return evaluation.execution_decision in [
            ExecutionDecision.EXECUTE_IMMEDIATELY,
            ExecutionDecision.EXECUTE_WITH_DELAY
        ]
    
    def calculate_execution_amount(
        self, 
        evaluation: OpportunityEvaluation,
        available_balance: float
    ) -> float:
        params = self._parameters
        
        base_amount = min(
            available_balance * 0.3,
            params.max_single_trade_usd,
            evaluation.profit_estimate_usd * 20
        )
        
        if evaluation.quality == OpportunityQuality.EXCELLENT:
            base_amount *= 1.0
        elif evaluation.quality == OpportunityQuality.GOOD:
            base_amount *= 0.85
        else:
            base_amount *= 0.6
        
        return max(0, base_amount)


class AggressiveStrategy(BaseStrategy):
    """激进策略 - 高风险高收益"""
    
    def __init__(self):
        super().__init__("Aggressive", StrategyType.AGGRESSIVE)
        self._parameters = StrategyParameters(
            strategy_type=StrategyType.AGGRESSIVE,
            min_profit_threshold_usd=5.0,
            min_profit_threshold_pct=0.3,
            target_profit_threshold_pct=1.0,
            max_risk_score=0.8,
            max_single_trade_usd=20000.0,
            max_daily_trades=20,
            max_daily_loss_usd=1000.0,
            max_gas_price_gwei=100.0,
            max_slippage_pct=1.0,
            min_confidence_score=0.5,
            auto_execute_confidence=0.65,
            cooldown_seconds=60,
        )
    
    def evaluate(self, opportunity: Dict, context: Dict) -> OpportunityEvaluation:
        """评估机会 - 激进策略"""
        params = self._parameters
        
        quality_score = 0.5
        risk_score = 0.5
        reasons = []
        warnings = []
        
        profit_usd = opportunity.get("estimated_profit_usd", 0)
        profit_pct = opportunity.get("estimated_profit_pct", 0)
        
        if profit_pct >= params.target_profit_threshold_pct:
            quality_score += 0.35
            reasons.append(f"利润达标: {profit_pct:.2f}%")
        elif profit_pct >= params.min_profit_threshold_pct:
            quality_score += 0.2
            reasons.append(f"有利润: {profit_pct:.2f}%")
        else:
            warnings.append(f"利润较低: {profit_pct:.2f}%")
        
        gas_price = context.get("gas_price_gwei", 0)
        if gas_price > params.max_gas_price_gwei:
            risk_score += 0.15
            warnings.append(f"Gas较高: {gas_price} Gwei")
        
        confidence = opportunity.get("confidence", 0.5)
        if confidence >= params.auto_execute_confidence:
            quality_score += 0.25
            reasons.append(f"置信度: {confidence:.0%}")
        
        quality_score = max(0, min(1, quality_score))
        risk_score = max(0, min(1, risk_score))
        
        quality = OpportunityQuality.EXCELLENT if quality_score >= 0.8 else \
                  OpportunityQuality.GOOD if quality_score >= 0.6 else \
                  OpportunityQuality.FAIR if quality_score >= 0.4 else \
                  OpportunityQuality.POOR
        
        decision = self._make_decision(quality_score, risk_score, confidence, params)
        
        recommended = min(
            params.max_single_trade_usd,
            profit_usd * 50,
            context.get("available_balance", 0) * 0.5
        )
        
        return OpportunityEvaluation(
            opportunity_id=opportunity.get("id", ""),
            quality_score=quality_score,
            quality=quality,
            risk_score=risk_score,
            profit_estimate_usd=profit_usd,
            profit_estimate_pct=profit_pct,
            confidence=confidence,
            execution_decision=decision,
            recommended_amount_usd=recommended,
            execution_priority=self._calculate_priority(quality_score, risk_score),
            reasons=reasons,
            warnings=warnings,
        )
    
    def _make_decision(
        self, 
        quality_score: float, 
        risk_score: float, 
        confidence: float,
        params: StrategyParameters
    ) -> ExecutionDecision:
        if quality_score < 0.2 or risk_score > params.max_risk_score:
            return ExecutionDecision.SKIP
        
        if confidence >= params.auto_execute_confidence and risk_score < 0.5:
            return ExecutionDecision.EXECUTE_IMMEDIATELY
        
        if confidence >= params.min_confidence_score:
            return ExecutionDecision.EXECUTE_IMMEDIATELY
        
        return ExecutionDecision.MONITOR
    
    def _calculate_priority(self, quality_score: float, risk_score: float) -> int:
        score = quality_score - risk_score * 0.2
        return max(1, min(5, int(score * 5)))
    
    def should_execute(self, evaluation: OpportunityEvaluation) -> bool:
        params = self._parameters
        
        if evaluation.risk_score > params.max_risk_score:
            return False
        if evaluation.confidence < params.min_confidence_score:
            return False
        if evaluation.profit_estimate_usd < params.min_profit_threshold_usd:
            return False
        
        return evaluation.execution_decision in [
            ExecutionDecision.EXECUTE_IMMEDIATELY,
            ExecutionDecision.EXECUTE_WITH_DELAY,
            ExecutionDecision.MONITOR
        ]
    
    def calculate_execution_amount(
        self, 
        evaluation: OpportunityEvaluation,
        available_balance: float
    ) -> float:
        params = self._parameters
        
        base_amount = min(
            available_balance * 0.5,
            params.max_single_trade_usd,
            evaluation.profit_estimate_usd * 50
        )
        
        if evaluation.quality == OpportunityQuality.EXCELLENT:
            base_amount *= 1.0
        elif evaluation.quality == OpportunityQuality.GOOD:
            base_amount *= 0.9
        else:
            base_amount *= 0.7
        
        return max(0, base_amount)


# ============================================
# 策略管理器
# ============================================

class StrategyManager:
    """策略管理器"""
    
    _instance = None
    _lock = asyncio.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not hasattr(self, "_initialized"):
            self._initialized = True
            self._strategies: Dict[str, BaseStrategy] = {}
            self._active_strategy: Optional[BaseStrategy] = None
            self._strategy_configs: Dict[str, StrategyConfig] = {}
            self._daily_stats: Dict[str, Any] = defaultdict(lambda: {
                "trades": 0,
                "profit": 0.0,
                "loss": 0.0
            })
            self._cooldowns: Dict[str, datetime] = {}
            
            # 初始化预置策略
            self._init_preset_strategies()
    
    def _init_preset_strategies(self):
        """初始化预置策略"""
        self._strategies["conservative"] = ConservativeStrategy()
        self._strategies["balanced"] = BalancedStrategy()
        self._strategies["aggressive"] = AggressiveStrategy()
        
        # 默认激活平衡策略
        self._active_strategy = self._strategies["balanced"]
        self._active_strategy.state = StrategyState.ACTIVE
        
        # 创建默认配置
        for name, strategy in self._strategies.items():
            self._strategy_configs[name] = StrategyConfig(
                name=strategy.name,
                strategy_type=strategy.strategy_type,
                parameters=strategy.get_parameters(),
                enabled_chains=list(SUPPORTED_CHAINS.keys()),
            )
    
    async def initialize(self):
        """初始化管理器"""
        logger.info("StrategyManager initialized")
        await self._load_strategy_configs()
    
    async def _load_strategy_configs(self):
        """加载策略配置"""
        # TODO: 从数据库或配置文件加载
        pass
    
    def get_strategy(self, name: str) -> Optional[BaseStrategy]:
        """获取策略"""
        return self._strategies.get(name.lower())
    
    def get_active_strategy(self) -> Optional[BaseStrategy]:
        """获取当前激活的策略"""
        return self._active_strategy
    
    def list_strategies(self) -> List[Dict]:
        """列出所有策略"""
        return [
            {
                "name": s.name,
                "type": s.strategy_type.value,
                "state": s.state.value,
                "performance": {
                    "total_trades": s.performance.total_trades,
                    "win_rate": s.performance.win_rate,
                    "total_profit": s.performance.total_profit_usd,
                }
            }
            for s in self._strategies.values()
        ]
    
    def switch_strategy(self, name: str) -> bool:
        """切换策略"""
        strategy = self._strategies.get(name.lower())
        if not strategy:
            logger.error(f"Strategy not found: {name}")
            return False
        
        if self._active_strategy:
            self._active_strategy.state = StrategyState.PAUSED
        
        self._active_strategy = strategy
        self._active_strategy.state = StrategyState.ACTIVE
        
        logger.info(f"Switched to strategy: {name}")
        return True
    
    def create_custom_strategy(
        self,
        name: str,
        parameters: StrategyParameters
    ) -> Optional[BaseStrategy]:
        """创建自定义策略"""
        if name.lower() in self._strategies:
            logger.error(f"Strategy already exists: {name}")
            return None
        
        class CustomStrategy(BaseStrategy):
            def __init__(self, name, params):
                super().__init__(name, StrategyType.CUSTOM)
                self._parameters = params
            
            def evaluate(self, opportunity: Dict, context: Dict) -> OpportunityEvaluation:
                params = self._parameters
                quality_score = 0.5
                risk_score = 0.4
                reasons = []
                warnings = []
                
                profit_pct = opportunity.get("estimated_profit_pct", 0)
                if profit_pct >= params.target_profit_threshold_pct:
                    quality_score += 0.3
                elif profit_pct >= params.min_profit_threshold_pct:
                    quality_score += 0.1
                
                confidence = opportunity.get("confidence", 0.5)
                if confidence >= params.auto_execute_confidence:
                    quality_score += 0.2
                
                quality_score = max(0, min(1, quality_score))
                
                decision = ExecutionDecision.EXECUTE_IMMEDIATELY if (
                    quality_score > 0.5 and risk_score < params.max_risk_score
                ) else ExecutionDecision.SKIP
                
                return OpportunityEvaluation(
                    opportunity_id=opportunity.get("id", ""),
                    quality_score=quality_score,
                    quality=OpportunityQuality.GOOD,
                    risk_score=risk_score,
                    profit_estimate_usd=opportunity.get("estimated_profit_usd", 0),
                    profit_estimate_pct=profit_pct,
                    confidence=confidence,
                    execution_decision=decision,
                    recommended_amount_usd=min(
                        params.max_single_trade_usd,
                        opportunity.get("estimated_profit_usd", 0) * 20
                    ),
                    execution_priority=3,
                    reasons=reasons,
                    warnings=warnings,
                )
            
            def should_execute(self, evaluation: OpportunityEvaluation) -> bool:
                params = self._parameters
                return (
                    evaluation.risk_score <= params.max_risk_score and
                    evaluation.confidence >= params.min_confidence_score and
                    evaluation.profit_estimate_usd >= params.min_profit_threshold_usd
                )
            
            def calculate_execution_amount(self, evaluation, available):
                params = self._parameters
                return min(
                    available * 0.3,
                    params.max_single_trade_usd,
                    evaluation.profit_estimate_usd * 20
                )
        
        strategy = CustomStrategy(name, parameters)
        self._strategies[name.lower()] = strategy
        logger.info(f"Created custom strategy: {name}")
        return strategy
    
    def evaluate_opportunity(
        self,
        opportunity: Dict,
        context: Dict
    ) -> OpportunityEvaluation:
        """评估机会"""
        strategy = self._active_strategy
        if not strategy:
            logger.error("No active strategy")
            return None
        
        evaluation = strategy.evaluate(opportunity, context)
        logger.info(
            f"Evaluated opportunity {evaluation.opportunity_id}: "
            f"quality={evaluation.quality.value}, decision={evaluation.execution_decision.value}"
        )
        return evaluation
    
    def is_in_cooldown(self, opportunity_id: str) -> bool:
        """检查是否在冷却期"""
        if opportunity_id not in self._cooldowns:
            return False
        
        cooldown_end = self._cooldowns[opportunity_id]
        if datetime.now() >= cooldown_end:
            del self._cooldowns[opportunity_id]
            return False
        
        return True
    
    def set_cooldown(self, opportunity_id: str, seconds: int):
        """设置冷却期"""
        self._cooldowns[opportunity_id] = datetime.now() + timedelta(seconds=seconds)
    
    def check_daily_limits(self, chain: str = None) -> bool:
        """检查每日限制"""
        today = datetime.now().date().isoformat()
        stats = self._daily_stats[today]
        
        strategy = self._active_strategy
        if not strategy:
            return False
        
        params = strategy.get_parameters()
        
        if stats["trades"] >= params.max_daily_trades:
            logger.warning(f"Daily trade limit reached: {stats['trades']}")
            return False
        
        if stats["loss"] >= params.max_daily_loss_usd:
            logger.warning(f"Daily loss limit reached: ${stats['loss']}")
            return False
        
        if chain and chain in params.chain_max_trades:
            chain_stats = self._daily_stats[f"{today}_{chain}"]
            if chain_stats.get("trades", 0) >= params.chain_max_trades[chain]:
                logger.warning(f"Chain {chain} daily limit reached")
                return False
        
        return True
    
    def record_trade_result(
        self,
        success: bool,
        profit_usd: float = 0,
        chain: str = None
    ):
        """记录交易结果"""
        today = datetime.now().date().isoformat()
        stats = self._daily_stats[today]
        
        stats["trades"] = stats.get("trades", 0) + 1
        
        if success:
            stats["profit"] = stats.get("profit", 0) + profit_usd
        else:
            stats["loss"] = stats.get("loss", 0) + abs(profit_usd)
        
        if chain:
            chain_stats = self._daily_stats[f"{today}_{chain}"]
            chain_stats["trades"] = chain_stats.get("trades", 0) + 1
        
        # 更新策略表现
        strategy = self._active_strategy
        if strategy:
            strategy.performance.total_trades += 1
            if success:
                strategy.performance.successful_trades += 1
                strategy.performance.total_profit_usd += profit_usd
            else:
                strategy.performance.failed_trades += 1
                strategy.performance.total_loss_usd += abs(profit_usd)
            
            if strategy.performance.total_trades > 0:
                strategy.performance.win_rate = (
                    strategy.performance.successful_trades / 
                    strategy.performance.total_trades
                )
            
            strategy.performance.profit_history.append(profit_usd)
    
    def get_daily_stats(self) -> Dict:
        """获取每日统计"""
        today = datetime.now().date().isoformat()
        stats = self._daily_stats[today]
        
        return {
            "date": today,
            "trades": stats.get("trades", 0),
            "profit": stats.get("profit", 0),
            "loss": stats.get("loss", 0),
            "net": stats.get("profit", 0) - stats.get("loss", 0),
        }
    
    def get_performance_summary(self) -> Dict:
        """获取策略表现摘要"""
        strategy = self._active_strategy
        if not strategy:
            return {}
        
        p = strategy.performance
        
        return {
            "strategy": strategy.name,
            "state": strategy.state.value,
            "total_trades": p.total_trades,
            "successful_trades": p.successful_trades,
            "failed_trades": p.failed_trades,
            "win_rate": f"{p.win_rate:.1%}",
            "total_profit": f"${p.total_profit_usd:.2f}",
            "total_loss": f"${p.total_loss_usd:.2f}",
            "net_profit": f"${p.total_profit_usd - p.total_loss_usd:.2f}",
        }
    
    def run_backtest(
        self,
        strategy_name: str,
        historical_data: List[Dict],
        initial_balance: float = 10000.0
    ) -> BacktestResult:
        """策略回测"""
        strategy = self._strategies.get(strategy_name.lower())
        if not strategy:
            logger.error(f"Strategy not found: {strategy_name}")
            return None
        
        balance = initial_balance
        trades = []
        profits = []
        chain_stats = defaultdict(lambda: {"trades": 0, "profit": 0.0})
        
        period_start = datetime.now()
        period_end = datetime.now()
        
        for i, data in enumerate(historical_data):
            if i > 0:
                period_start = data.get("timestamp", period_start)
            
            opportunity = {
                "id": data.get("id", f"trade_{i}"),
                "estimated_profit_usd": data.get("profit_usd", 0),
                "estimated_profit_pct": data.get("profit_pct", 0),
                "confidence": data.get("confidence", 0.5),
                "source_chain": data.get("chain", "ethereum"),
                "liquidity": data.get("liquidity", 100000),
            }
            
            context = {
                "gas_price_gwei": data.get("gas_price", 30),
                "available_balance": balance,
            }
            
            evaluation = strategy.evaluate(opportunity, context)
            
            if strategy.should_execute(evaluation):
                profit = evaluation.profit_estimate_usd
                balance += profit
                profits.append(profit)
                
                trades.append({
                    "timestamp": data.get("timestamp", datetime.now()),
                    "profit": profit,
                    "chain": opportunity["source_chain"],
                })
                
                chain = opportunity["source_chain"]
                chain_stats[chain]["trades"] += 1
                chain_stats[chain]["profit"] += profit
        
        # 计算统计数据
        total_profit = sum(p for p in profits if p > 0)
        total_loss = sum(abs(p) for p in profits if p < 0)
        
        # 最大回撤
        max_drawdown = 0.0
        peak = initial_balance
        for profit in profits:
            peak = max(peak, peak + profit)
            drawdown = peak - (peak + profit)
            max_drawdown = max(max_drawdown, drawdown)
        
        # 夏普比率
        sharpe = 0.0
        if len(profits) > 1 and statistics.stdev(profits) > 0:
            mean_return = statistics.mean(profits)
            std_dev = statistics.stdev(profits)
            sharpe = mean_return / std_dev if std_dev > 0 else 0
        
        result = BacktestResult(
            strategy_name=strategy.name,
            period_start=period_start,
            period_end=period_end,
            total_trades=len(trades),
            successful_trades=len([p for p in profits if p > 0]),
            failed_trades=len([p for p in profits if p < 0]),
            total_profit_usd=total_profit,
            total_loss_usd=total_loss,
            net_profit_usd=total_profit - total_loss,
            max_drawdown_usd=max_drawdown,
            win_rate=len([p for p in profits if p > 0]) / len(trades) if trades else 0,
            avg_profit_per_trade=statistics.mean(profits) if profits else 0,
            sharpe_ratio=sharpe,
            chain_performance=dict(chain_stats),
        )
        
        logger.info(
            f"Backtest completed for {strategy.name}: "
            f"{result.total_trades} trades, "
            f"net profit: ${result.net_profit_usd:.2f}, "
            f"win rate: {result.win_rate:.1%}"
        )
        
        return result


# ============================================
# 单例访问函数
# ============================================

_strategy_manager: Optional[StrategyManager] = None


def get_strategy_manager() -> StrategyManager:
    """获取策略管理器单例"""
    global _strategy_manager
    if _strategy_manager is None:
        _strategy_manager = StrategyManager()
    return _strategy_manager


async def init_strategy_manager() -> StrategyManager:
    """初始化策略管理器"""
    manager = get_strategy_manager()
    await manager.initialize()
    return manager
