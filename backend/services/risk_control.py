"""
风险控制模块 - Phase 2 执行能力核心组件

功能：
- 单笔交易金额限制
- 每日交易次数限制
- 滑点保护
- Gas 价格上限检查
- 紧急停止机制
- 异常交易检测

风险等级：
- 极低风险（分数 0-0.2）
- 低风险（分数 0.2-0.4）
- 中风险（分数 0.4-0.6）
- 高风险（分数 0.6-0.8）
- 极高风险（分数 0.8-1.0）
"""

import os
import time
import logging
from typing import Dict, List, Optional, Tuple, Any, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from collections import defaultdict
from threading import Lock
import threading

import sys
import os as _os
_backend_dir = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from config.settings import SUPPORTED_CHAINS, get_chain_config

logger = logging.getLogger(__name__)


# ============================================
# 枚举和常量
# ============================================

class RiskLevel(Enum):
    """风险等级"""
    VERY_LOW = "very_low"     # 0-0.2
    LOW = "low"               # 0.2-0.4
    MEDIUM = "medium"         # 0.4-0.6
    HIGH = "high"             # 0.6-0.8
    VERY_HIGH = "very_high"   # 0.8-1.0

    @classmethod
    def from_score(cls, score: float) -> 'RiskLevel':
        if score < 0.2:
            return cls.VERY_LOW
        elif score < 0.4:
            return cls.LOW
        elif score < 0.6:
            return cls.MEDIUM
        elif score < 0.8:
            return cls.HIGH
        else:
            return cls.VERY_HIGH


class RiskCheckType(Enum):
    """风险检查类型"""
    BALANCE_CHECK = "balance_check"           # 余额检查
    AMOUNT_LIMIT = "amount_limit"             # 金额限制
    SLIPPAGE_CHECK = "slippage_check"         # 滑点检查
    GAS_PRICE_CHECK = "gas_price_check"       # Gas 价格检查
    DAILY_LIMIT = "daily_limit"               # 每日限制
    EMERGENCY_STOP = "emergency_stop"         # 紧急停止
    ANOMALY_CHECK = "anomaly_check"           # 异常检测
    EXECUTION_MODE = "execution_mode"         # 执行模式检查


class EmergencyState(Enum):
    """紧急状态"""
    NORMAL = "normal"
    WARNING = "warning"
    STOPPED = "stopped"
    MAINTENANCE = "maintenance"


# ============================================
# 数据类定义
# ============================================

@dataclass
class RiskLimits:
    """风险限制配置"""
    # 金额限制
    max_single_trade_usd: float = 50000.0      # 单笔最大交易 (USD)
    min_single_trade_usd: float = 10.0         # 单笔最小交易 (USD)
    max_position_usd: float = 100000.0         # 最大持仓 (USD)
    
    # 每日限制
    max_daily_trades: int = 100                 # 每日最大交易次数
    max_daily_volume_usd: float = 500000.0      # 每日最大交易量 (USD)
    max_daily_loss_usd: float = 10000.0         # 每日最大亏损 (USD)
    
    # 滑点限制
    max_slippage_pct: float = 1.0              # 最大滑点 (%)
    max_price_impact_pct: float = 2.0          # 最大价格影响 (%)
    
    # Gas 限制
    max_gas_price_gwei: float = 100.0          # 最大 Gas 价格 (Gwei)
    max_gas_cost_pct: float = 5.0              # Gas 成本占比最大 (% of 交易额)
    
    # 风险容忍度
    min_profit_threshold_usd: float = 5.0      # 最小利润阈值 (USD)
    min_profit_ratio_pct: float = 0.1         # 最小利润率 (%)
    
    # 链特定限制
    chain_limits: Dict[str, Dict[str, Any]] = None
    
    def __post_init__(self):
        if self.chain_limits is None:
            self.chain_limits = {}
            # 设置一些默认的链限制
            for chain in ["ethereum", "arbitrum", "optimism"]:
                self.chain_limits[chain] = {
                    "max_single_trade_usd": 100000.0,
                    "max_gas_price_gwei": 200.0
                }


@dataclass
class RiskCheckResult:
    """风险检查结果"""
    passed: bool                           # 是否通过
    risk_level: RiskLevel                  # 风险等级
    risk_score: float                       # 风险分数 (0-1)
    checks: List[Dict]                     # 各检查项结果
    warnings: List[str]                     # 警告信息
    errors: List[str]                      # 错误信息
    recommended_action: str = "proceed"     # 建议操作
    
    def to_dict(self) -> Dict:
        return {
            "passed": self.passed,
            "risk_level": self.risk_level.value,
            "risk_score": self.risk_score,
            "checks": self.checks,
            "warnings": self.warnings,
            "errors": self.errors,
            "recommended_action": self.recommended_action
        }
    
    def add_warning(self, message: str):
        """添加警告"""
        self.warnings.append(message)
    
    def add_error(self, message: str):
        """添加错误"""
        self.errors.append(message)


@dataclass
class TradeContext:
    """交易上下文"""
    chain: str
    from_address: str
    to_address: str
    token_in: str                          # 输入代币
    token_out: str                         # 输出代币
    amount_in: float                       # 输入金额 (USD)
    amount_out_estimated: float            # 预估输出金额 (USD)
    amount_out_min: float                   # 最小输出金额 (USD)
    expected_price: float                  # 预期价格
    actual_price: float                    # 实际价格
    slippage_pct: float                    # 滑点 (%)
    gas_price_gwei: float                  # 当前 Gas 价格 (Gwei)
    gas_limit: int                         # Gas 限制
    estimated_gas_cost_usd: float          # 预估 Gas 成本 (USD)
    estimated_profit_usd: float            # 预估利润 (USD)
    opportunity_id: Optional[str] = None


@dataclass
class DailyStats:
    """每日统计"""
    date: str                              # 日期 (YYYY-MM-DD)
    total_trades: int = 0
    successful_trades: int = 0
    failed_trades: int = 0
    total_volume_usd: float = 0.0
    total_profit_usd: float = 0.0
    total_cost_usd: float = 0.0
    total_gas_used: int = 0
    largest_trade_usd: float = 0.0
    largest_loss_usd: float = 0.0


# ============================================
# 紧急停止控制器
# ============================================

class EmergencyStopController:
    """紧急停止控制器"""
    
    def __init__(self):
        self._state = EmergencyState.NORMAL
        self._lock = Lock()
        self._stop_reasons: List[str] = []
        self._resume_conditions: List[str] = []
        self._last_state_change = datetime.now()
    
    @property
    def state(self) -> EmergencyState:
        """获取当前状态"""
        with self._lock:
            return self._state
    
    def stop(self, reason: str):
        """触发紧急停止"""
        with self._lock:
            self._state = EmergencyState.STOPPED
            self._stop_reasons.append(reason)
            self._last_state_change = datetime.now()
            logger.critical(f"EMERGENCY STOP: {reason}")
    
    def warning(self, reason: str):
        """触发警告状态"""
        with self._lock:
            if self._state == EmergencyState.NORMAL:
                self._state = EmergencyState.WARNING
                self._stop_reasons.append(reason)
                self._last_state_change = datetime.now()
                logger.warning(f"WARNING: {reason}")
    
    def resume(self, condition: str = "manual"):
        """恢复运行"""
        with self._lock:
            if self._state == EmergencyState.STOPPED:
                self._state = EmergencyState.NORMAL
                self._resume_conditions.append(condition)
                self._stop_reasons.clear()
                self._last_state_change = datetime.now()
                logger.info(f"RESUMED: {condition}")
    
    def maintenance_mode(self, enabled: bool = True):
        """维护模式"""
        with self._lock:
            if enabled:
                self._state = EmergencyState.MAINTENANCE
            else:
                self._state = EmergencyState.NORMAL
            self._last_state_change = datetime.now()
    
    def is_stopped(self) -> bool:
        """是否停止"""
        return self.state in [EmergencyState.STOPPED, EmergencyState.MAINTENANCE]
    
    def can_proceed(self) -> Tuple[bool, Optional[str]]:
        """是否可以继续"""
        if self.state == EmergencyState.STOPPED:
            return False, f"Emergency stopped: {', '.join(self._stop_reasons)}"
        if self.state == EmergencyState.MAINTENANCE:
            return False, "System in maintenance mode"
        if self.state == EmergencyState.WARNING:
            return True, f"Warning: {', '.join(self._stop_reasons[-1:])}"
        return True, None


# ============================================
# 交易统计管理器
# ============================================

class TradingStatsManager:
    """交易统计管理器"""
    
    def __init__(self):
        self._lock = Lock()
        self._daily_stats: Dict[str, DailyStats] = {}
        self._trade_history: List[Dict] = []
        self._max_history = 10000  # 保留最近10000条
    
    def _get_today_key(self) -> str:
        """获取今天的键"""
        return datetime.now().strftime("%Y-%m-%d")
    
    def _get_or_create_today_stats(self) -> DailyStats:
        """获取或创建今天的统计"""
        key = self._get_today_key()
        if key not in self._daily_stats:
            self._daily_stats[key] = DailyStats(date=key)
        return self._daily_stats[key]
    
    def record_trade(
        self,
        chain: str,
        amount_usd: float,
        profit_usd: float,
        cost_usd: float,
        gas_used: int,
        success: bool
    ):
        """记录交易"""
        with self._lock:
            stats = self._get_or_create_today_stats()
            
            stats.total_trades += 1
            stats.total_volume_usd += amount_usd
            stats.total_profit_usd += profit_usd
            stats.total_cost_usd += cost_usd
            stats.total_gas_used += gas_used
            
            if success:
                stats.successful_trades += 1
            else:
                stats.failed_trades += 1
            
            if amount_usd > stats.largest_trade_usd:
                stats.largest_trade_usd = amount_usd
            
            if profit_usd < 0 and abs(profit_usd) > stats.largest_loss_usd:
                stats.largest_loss_usd = abs(profit_usd)
            
            # 记录历史
            self._trade_history.append({
                "timestamp": datetime.now().isoformat(),
                "chain": chain,
                "amount_usd": amount_usd,
                "profit_usd": profit_usd,
                "cost_usd": cost_usd,
                "gas_used": gas_used,
                "success": success
            })
            
            # 限制历史长度
            if len(self._trade_history) > self._max_history:
                self._trade_history = self._trade_history[-self._max_history:]
    
    def get_today_stats(self) -> DailyStats:
        """获取今天的统计"""
        with self._lock:
            return self._get_or_create_today_stats()
    
    def get_daily_stats(self, days: int = 7) -> List[DailyStats]:
        """获取最近 N 天的统计"""
        with self._lock:
            keys = sorted(self._daily_stats.keys())[-days:]
            return [self._daily_stats[k] for k in keys]
    
    def check_daily_limits(self, limits: RiskLimits) -> Tuple[bool, Optional[str]]:
        """检查每日限制"""
        stats = self.get_today_stats()
        
        if stats.total_trades >= limits.max_daily_trades:
            return False, f"Daily trade limit reached: {stats.total_trades}/{limits.max_daily_trades}"
        
        if stats.total_volume_usd >= limits.max_daily_volume_usd:
            return False, f"Daily volume limit reached: ${stats.total_volume_usd:.2f}/${limits.max_daily_volume_usd:.2f}"
        
        if stats.largest_loss_usd >= limits.max_daily_loss_usd:
            return False, f"Daily loss limit exceeded: ${stats.largest_loss_usd:.2f}/${limits.max_daily_loss_usd:.2f}"
        
        return True, None


# ============================================
# 主风险控制器
# ============================================

class RiskController:
    """
    主风险控制器
    
    协调所有风险检查
    """
    
    def __init__(
        self,
        limits: Optional[RiskLimits] = None,
        emergency_controller: Optional[EmergencyStopController] = None
    ):
        """
        初始化风险控制器
        
        Args:
            limits: 风险限制配置
            emergency_controller: 紧急停止控制器
        """
        self.limits = limits or RiskLimits()
        self.emergency = emergency_controller or EmergencyStopController()
        self.stats_manager = TradingStatsManager()
        
        # 价格监控（从外部传入）
        self._price_cache: Dict[str, float] = {}
        self._price_cache_time: float = 0
        self._price_cache_ttl: int = 60  # 秒
    
    def _check_emergency(self) -> Tuple[bool, Optional[str]]:
        """检查紧急状态"""
        return self.emergency.can_proceed()
    
    def _check_balance(
        self,
        context: TradeContext,
        available_balance: float
    ) -> Tuple[bool, float]:
        """
        检查余额
        
        Returns:
            (是否通过, 风险分数)
        """
        required = context.amount_in + context.estimated_gas_cost_usd
        
        if available_balance < required:
            return False, 1.0
        
        # 计算风险分数
        utilization = required / available_balance
        risk_score = min(utilization * 2, 1.0)  # 利用率越高风险越高
        
        return True, risk_score
    
    def _check_amount_limit(
        self,
        context: TradeContext
    ) -> Tuple[bool, float, Optional[str]]:
        """
        检查金额限制
        
        Returns:
            (是否通过, 风险分数, 错误信息)
        """
        # 获取链特定限制
        chain_limit = self.limits.chain_limits.get(
            context.chain,
            {}
        )
        
        max_trade = chain_limit.get(
            "max_single_trade_usd",
            self.limits.max_single_trade_usd
        )
        min_trade = self.limits.min_single_trade_usd
        
        if context.amount_in > max_trade:
            return False, 0.9, f"Amount exceeds max limit: ${context.amount_in:.2f} > ${max_trade:.2f}"
        
        if context.amount_in < min_trade:
            return False, 0.5, f"Amount below min limit: ${context.amount_in:.2f} < ${min_trade:.2f}"
        
        # 计算风险分数
        risk_score = context.amount_in / max_trade
        
        return True, risk_score, None
    
    def _check_slippage(
        self,
        context: TradeContext
    ) -> Tuple[bool, float, Optional[str]]:
        """
        检查滑点
        
        Returns:
            (是否通过, 风险分数, 错误信息)
        """
        max_slippage = self.limits.max_slippage_pct
        
        if context.slippage_pct > max_slippage:
            return False, 0.8, f"Slippage exceeds limit: {context.slippage_pct:.2f}% > {max_slippage:.2f}%"
        
        # 价格影响检查
        if context.expected_price > 0:
            price_impact = abs(context.actual_price - context.expected_price) / context.expected_price
            if price_impact > self.limits.max_price_impact_pct:
                return False, 0.7, f"Price impact too high: {price_impact:.2f}%"
            
            # 滑点风险分数
            risk_score = context.slippage_pct / max_slippage
            return True, risk_score, None
        
        return True, 0.0, None
    
    def _check_gas_price(
        self,
        context: TradeContext
    ) -> Tuple[bool, float, Optional[str]]:
        """
        检查 Gas 价格
        
        Returns:
            (是否通过, 风险分数, 错误信息)
        """
        max_gas_price = self.limits.max_gas_price_gwei
        
        if context.gas_price_gwei > max_gas_price:
            return False, 0.6, f"Gas price too high: {context.gas_price_gwei:.2f} gwei > {max_gas_price:.2f} gwei"
        
        # 检查 Gas 成本占比
        gas_cost_ratio = context.estimated_gas_cost_usd / context.amount_in * 100
        if gas_cost_ratio > self.limits.max_gas_cost_pct:
            return False, 0.5, f"Gas cost ratio too high: {gas_cost_ratio:.2f}% > {self.limits.max_gas_cost_pct:.2f}%"
        
        # 风险分数
        risk_score = context.gas_price_gwei / max_gas_price
        
        return True, risk_score, None
    
    def _check_profitability(
        self,
        context: TradeContext
    ) -> Tuple[bool, float, Optional[str]]:
        """
        检查盈利能力
        
        Returns:
            (是否通过, 风险分数, 错误信息)
        """
        # 净利润
        net_profit = context.estimated_profit_usd - context.estimated_gas_cost_usd
        
        if net_profit < self.limits.min_profit_threshold_usd:
            return False, 0.4, f"Profit below threshold: ${net_profit:.2f} < ${self.limits.min_profit_threshold_usd:.2f}"
        
        # 利润率
        profit_ratio = net_profit / context.amount_in * 100
        if profit_ratio < self.limits.min_profit_ratio_pct:
            return False, 0.3, f"Profit ratio too low: {profit_ratio:.4f}% < {self.limits.min_profit_ratio_pct:.4f}%"
        
        # 风险分数（利润越高风险越低）
        # 使用反向关系：预期收益/风险比例
        expected_return = context.estimated_profit_usd / context.amount_in
        risk_score = max(0, 1 - expected_return * 10)  # 简单模型
        
        return True, risk_score, None
    
    def _check_anomaly(
        self,
        context: TradeContext
    ) -> Tuple[bool, float, List[str]]:
        """
        异常检测
        
        Returns:
            (是否通过, 风险分数, 警告列表)
        """
        warnings = []
        risk_score = 0.0
        
        # 检查交易金额异常
        stats = self.stats_manager.get_today_stats()
        if stats.largest_trade_usd > 0:
            if context.amount_in > stats.largest_trade_usd * 2:
                warnings.append(f"Trade amount significantly larger than history: ${context.amount_in:.2f}")
                risk_score += 0.1
        
        # 检查频率异常
        if stats.total_trades > 50:  # 过去1小时内超过50笔
            warnings.append(f"High trading frequency: {stats.total_trades} trades today")
            risk_score += 0.1
        
        # 检查价格偏离
        if context.expected_price > 0:
            price_diff_pct = abs(context.actual_price - context.expected_price) / context.expected_price
            if price_diff_pct > 0.05:  # 5%
                warnings.append(f"Significant price deviation: {price_diff_pct:.2%}")
                risk_score += 0.15
        
        # 检查跨链风险
        if context.chain not in ["ethereum", "arbitrum", "bsc", "polygon"]:
            warnings.append(f"Non-mainstream chain: {context.chain}")
            risk_score += 0.1
        
        passed = risk_score < 0.5
        
        return passed, min(risk_score, 1.0), warnings
    
    async def perform_risk_check(
        self,
        context: TradeContext,
        available_balance: Optional[float] = None,
        additional_checks: Optional[List[Callable]] = None
    ) -> RiskCheckResult:
        """
        执行完整风险检查
        
        Args:
            context: 交易上下文
            available_balance: 可用余额
            additional_checks: 额外的检查函数
            
        Returns:
            RiskCheckResult
        """
        result = RiskCheckResult(
            passed=True,
            risk_level=RiskLevel.VERY_LOW,
            risk_score=0.0,
            checks=[],
            warnings=[],
            errors=[]
        )
        
        total_risk_score = 0.0
        weights = {
            "balance": 0.2,
            "amount": 0.15,
            "slippage": 0.2,
            "gas": 0.15,
            "profit": 0.15,
            "anomaly": 0.15
        }
        
        # 1. 紧急状态检查
        can_proceed, reason = self._check_emergency()
        result.checks.append({
            "type": RiskCheckType.EMERGENCY_STOP.value,
            "passed": can_proceed,
            "score": 0 if can_proceed else 1.0
        })
        
        if not can_proceed:
            result.passed = False
            result.errors.append(reason)
            result.risk_score = 1.0
            result.risk_level = RiskLevel.VERY_HIGH
            result.recommended_action = "stop"
            return result
        
        # 2. 每日限制检查
        can_proceed, reason = self.stats_manager.check_daily_limits(self.limits)
        result.checks.append({
            "type": RiskCheckType.DAILY_LIMIT.value,
            "passed": can_proceed,
            "score": 0 if can_proceed else 1.0
        })
        
        if not can_proceed:
            result.passed = False
            result.errors.append(reason)
            total_risk_score += 1.0
        
        # 3. 余额检查
        if available_balance is not None:
            passed, score = self._check_balance(context, available_balance)
            result.checks.append({
                "type": RiskCheckType.BALANCE_CHECK.value,
                "passed": passed,
                "score": score
            })
            total_risk_score += score * weights["balance"]
        
        # 4. 金额限制检查
        passed, score, error = self._check_amount_limit(context)
        result.checks.append({
            "type": RiskCheckType.AMOUNT_LIMIT.value,
            "passed": passed,
            "score": score
        })
        
        if not passed:
            result.errors.append(error)
            total_risk_score += score * weights["amount"]
        else:
            total_risk_score += score * weights["amount"]
        
        # 5. 滑点检查
        passed, score, error = self._check_slippage(context)
        result.checks.append({
            "type": RiskCheckType.SLIPPAGE_CHECK.value,
            "passed": passed,
            "score": score
        })
        
        if not passed:
            result.errors.append(error)
            total_risk_score += score * weights["slippage"]
        else:
            total_risk_score += score * weights["slippage"]
        
        # 6. Gas 价格检查
        passed, score, error = self._check_gas_price(context)
        result.checks.append({
            "type": RiskCheckType.GAS_PRICE_CHECK.value,
            "passed": passed,
            "score": score
        })
        
        if not passed:
            result.errors.append(error)
            total_risk_score += score * weights["gas"]
        else:
            total_risk_score += score * weights["gas"]
        
        # 7. 盈利能力检查
        passed, score, error = self._check_profitability(context)
        result.checks.append({
            "type": RiskCheckType.EXECUTION_MODE.value,
            "passed": passed,
            "score": score
        })
        
        if not passed:
            result.errors.append(error)
            total_risk_score += score * weights["profit"]
        else:
            total_risk_score += score * weights["profit"]
        
        # 8. 异常检测
        passed, score, warnings = self._check_anomaly(context)
        result.checks.append({
            "type": RiskCheckType.ANOMALY_CHECK.value,
            "passed": passed,
            "score": score
        })
        
        if warnings:
            result.warnings.extend(warnings)
        total_risk_score += score * weights["anomaly"]
        
        # 9. 额外检查
        if additional_checks:
            for check_fn in additional_checks:
                try:
                    passed, score, msg = await check_fn(context)
                    result.checks.append({
                        "type": "additional",
                        "passed": passed,
                        "score": score,
                        "message": msg
                    })
                    if not passed:
                        result.errors.append(msg)
                    elif msg:
                        result.warnings.append(msg)
                    total_risk_score += score * 0.1
                except Exception as e:
                    logger.error(f"Additional check failed: {e}")
        
        # 计算最终结果
        result.risk_score = min(total_risk_score, 1.0)
        result.risk_level = RiskLevel.from_score(result.risk_score)
        
        if result.errors:
            result.passed = False
            result.recommended_action = "reject"
        elif result.risk_score > 0.6:
            result.recommended_action = "review"
        elif result.risk_score > 0.4:
            result.recommended_action = "caution"
        else:
            result.recommended_action = "proceed"
        
        return result
    
    def record_execution(
        self,
        chain: str,
        amount_usd: float,
        profit_usd: float,
        cost_usd: float,
        gas_used: int,
        success: bool
    ):
        """记录执行结果"""
        self.stats_manager.record_trade(
            chain, amount_usd, profit_usd, cost_usd, gas_used, success
        )
        
        # 检查是否需要触发警告
        if not success:
            stats = self.stats_manager.get_today_stats()
            if stats.failed_trades > 10:
                self.emergency.warning(f"High failure rate: {stats.failed_trades} failures today")
            
            if stats.largest_loss_usd > self.limits.max_daily_loss_usd * 0.8:
                self.emergency.warning(f"Approaching daily loss limit: ${stats.largest_loss_usd:.2f}")
    
    def get_stats(self) -> Dict:
        """获取统计信息"""
        return {
            "today": self.stats_manager.get_today_stats().__dict__,
            "emergency_state": self.emergency.state.value,
            "limits": {
                "max_single_trade_usd": self.limits.max_single_trade_usd,
                "max_daily_trades": self.limits.max_daily_trades,
                "max_daily_volume_usd": self.limits.max_daily_volume_usd,
                "max_slippage_pct": self.limits.max_slippage_pct,
                "max_gas_price_gwei": self.limits.max_gas_price_gwei
            }
        }


# ============================================
# 单例
# ============================================

_risk_controller_instance: Optional[RiskController] = None


def get_risk_controller() -> RiskController:
    """获取风险控制器单例"""
    global _risk_controller_instance
    if _risk_controller_instance is None:
        _risk_controller_instance = RiskController()
    return _risk_controller_instance


def init_risk_controller(limits: RiskLimits) -> RiskController:
    """初始化风险控制器"""
    global _risk_controller_instance
    _risk_controller_instance = RiskController(limits)
    return _risk_controller_instance
