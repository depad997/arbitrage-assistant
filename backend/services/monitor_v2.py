"""
监控告警升级模块 - Phase 3 全自动执行核心组件

基于 Phase 1 monitor_loop.py 升级，实现：
- 实时监控（多链并发监控）
- 价格变动追踪
- 机会实时推送
- 智能告警（分级告警、告警聚合、关键指标推送）
- 状态报告（定时运行报告、收益日报/周报、异常报告）

设计原则：
- 低延迟：快速发现机会
- 低噪音：智能聚合告警
- 可观测：完整的状态追踪
"""

import asyncio
import logging
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from collections import defaultdict
import json

import sys
import os as _os
_backend_dir = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from config.settings import (
    settings,
    SUPPORTED_CHAINS,
    ENABLED_CHAINS,
    get_evm_chains,
)

logger = logging.getLogger(__name__)


# ============================================
# 枚举定义
# ============================================

class AlertLevel(Enum):
    """告警级别"""
    DEBUG = "debug"
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    CRITICAL = "critical"
    EMERGENCY = "emergency"


class AlertCategory(Enum):
    """告警类别"""
    OPPORTUNITY = "opportunity"           # 机会告警
    EXECUTION = "execution"               # 执行告警
    SYSTEM = "system"                      # 系统告警
    RISK = "risk"                         # 风险告警
    PERFORMANCE = "performance"          # 性能告警


class ReportType(Enum):
    """报告类型"""
    HOURLY = "hourly"                     # 每小时报告
    DAILY = "daily"                       # 每日报告
    WEEKLY = "weekly"                     # 每周报告
    EXCEPTION = "exception"               # 异常报告


# ============================================
# 数据类定义
# ============================================

@dataclass
class PriceChange:
    """价格变动"""
    symbol: str
    chain: str
    old_price: float
    new_price: float
    change_pct: float
    change_usd: float
    timestamp: datetime


@dataclass
class OpportunityAlert:
    """机会告警"""
    opportunity_id: str
    symbol: str
    source_chain: str
    target_chain: str
    profit_usd: float
    profit_pct: float
    confidence: float
    quality: str
    timestamp: datetime
    ttl_seconds: int = 60


@dataclass
class ExecutionAlert:
    """执行告警"""
    alert_type: str                        # started / success / failed
    opportunity_id: str
    chain: str
    tx_hash: str
    amount_usd: float
    profit_usd: float
    gas_cost_usd: float
    status: str
    error: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class SystemAlert:
    """系统告警"""
    alert_type: str                        # health_check / error / maintenance
    component: str
    message: str
    details: Dict = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class AggregatedAlert:
    """聚合告警"""
    category: AlertCategory
    level: AlertLevel
    title: str
    message: str
    alerts: List[Dict]
    count: int
    first_timestamp: datetime
    last_timestamp: datetime
    is_muted: bool = False


@dataclass
class SystemReport:
    """系统报告"""
    report_type: ReportType
    period_start: datetime
    period_end: datetime
    generated_at: datetime
    
    # 运行状态
    uptime_seconds: float
    total_cycles: int
    errors: int
    
    # 监控统计
    opportunities_detected: int
    opportunities_executed: int
    
    # 收益统计
    total_profit_usd: float
    total_loss_usd: float
    net_profit_usd: float
    trades_count: int
    win_rate: float
    
    # 链统计
    chain_stats: Dict[str, Dict]
    
    # 告警统计
    alerts_count: int
    critical_alerts: int
    
    # 附加信息
    details: Dict = field(default_factory=dict)


@dataclass
class MonitorConfig:
    """监控配置"""
    # 轮询间隔
    polling_interval_seconds: int = 30
    fast_polling_interval_seconds: int = 10
    
    # 价格监控
    price_change_threshold_pct: float = 1.0
    price_refresh_interval_seconds: int = 60
    
    # 机会监控
    opportunity_scan_interval_seconds: int = 30
    min_profit_threshold_usd: float = 5.0
    
    # 告警设置
    alert_cooldown_seconds: int = 300
    alert_aggregation_window_seconds: int = 60
    max_alerts_per_window: int = 10
    
    # 报告设置
    hourly_report_enabled: bool = True
    daily_report_enabled: bool = True
    weekly_report_enabled: bool = True
    
    # 调试
    debug_mode: bool = False


@dataclass
class MonitorStats:
    """监控统计"""
    is_running: bool = False
    started_at: Optional[datetime] = None
    total_cycles: int = 0
    errors: int = 0
    
    opportunities_detected: int = 0
    opportunities_executed: int = 0
    opportunities_failed: int = 0
    
    alerts_sent: int = 0
    alerts_suppressed: int = 0
    
    last_cycle_time: Optional[datetime] = None
    avg_cycle_time_ms: float = 0.0


# ============================================
# 告警聚合器
# ============================================

class AlertAggregator:
    """告警聚合器 - 避免告警刷屏"""
    
    def __init__(self, window_seconds: int = 60, max_alerts: int = 10):
        self._window_seconds = window_seconds
        self._max_alerts = max_alerts
        
        # 告警窗口
        self._alert_windows: Dict[str, List[Dict]] = defaultdict(list)
        
        # 聚合缓存
        self._aggregated: Dict[str, AggregatedAlert] = {}
        
        # 静音列表
        self._muted_categories: set = set()
    
    def add_alert(self, category: str, alert: Dict) -> Optional[AggregatedAlert]:
        """添加告警并检查聚合"""
        window_key = f"{category}_{alert.get('key', 'default')}"
        now = datetime.now()
        
        # 清理过期告警
        self._clean_window(window_key, now)
        
        # 添加到窗口
        self._alert_windows[window_key].append({
            **alert,
            "timestamp": now,
        })
        
        # 检查是否需要聚合
        alerts_in_window = len(self._alert_windows[window_key])
        
        if alerts_in_window >= self._max_alerts:
            # 聚合告警
            return self._aggregate(window_key, category)
        
        return None
    
    def _clean_window(self, window_key: str, now: datetime):
        """清理过期告警"""
        cutoff = now - timedelta(seconds=self._window_seconds)
        self._alert_windows[window_key] = [
            a for a in self._alert_windows[window_key]
            if a.get("timestamp", datetime.min) > cutoff
        ]
    
    def _aggregate(self, window_key: str, category: str) -> AggregatedAlert:
        """聚合告警"""
        alerts = self._alert_windows[window_key]
        
        if not alerts:
            return None
        
        first = alerts[0]
        last = alerts[-1]
        
        # 确定级别
        levels = [AlertLevel(a.get("level", "info")) for a in alerts]
        max_level = max(levels, key=lambda x: x.priority if hasattr(x, 'priority') else 0)
        
        aggregated = AggregatedAlert(
            category=AlertCategory(category),
            level=max_level,
            title=first.get("title", "Alert"),
            message=first.get("message", ""),
            alerts=alerts,
            count=len(alerts),
            first_timestamp=first.get("timestamp", datetime.now()),
            last_timestamp=last.get("timestamp", datetime.now()),
        )
        
        self._aggregated[window_key] = aggregated
        
        # 清空窗口
        self._alert_windows[window_key] = []
        
        return aggregated
    
    def get_aggregated(self, category: str, key: str = "default") -> Optional[AggregatedAlert]:
        """获取聚合告警"""
        window_key = f"{category}_{key}"
        return self._aggregated.get(window_key)
    
    def clear(self):
        """清空"""
        self._alert_windows.clear()
        self._aggregated.clear()


# ============================================
# 监控器 V2
# ============================================

class MonitorV2:
    """监控器 V2"""
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not hasattr(self, "_initialized"):
            self._initialized = True
            
            # 配置
            self._config = MonitorConfig()
            
            # 统计
            self._stats = MonitorStats()
            
            # 告警聚合器
            self._alert_aggregator = AlertAggregator(
                window_seconds=self._config.alert_aggregation_window_seconds,
                max_alerts=self._config.max_alerts_per_window
            )
            
            # 告警回调
            self._alert_callbacks: Dict[AlertCategory, List[Callable]] = defaultdict(list)
            
            # 报告回调
            self._report_callbacks: Dict[ReportType, List[Callable]] = defaultdict(list)
            
            # 状态
            self._is_running = False
            self._monitor_task: Optional[asyncio.Task] = None
            self._report_tasks: List[asyncio.Task] = []
            
            # 价格缓存
            self._price_cache: Dict[str, float] = {}
            self._price_history: Dict[str, List[PriceChange]] = defaultdict(list)
            
            # 冷却追踪
            self._alert_cooldowns: Dict[str, datetime] = {}
            
            # 组件引用
            self._price_monitor = None
            self._opportunity_detector = None
            self._alert_service = None
    
    async def initialize(self):
        """初始化"""
        logger.info("MonitorV2 initializing...")
        
        # 导入依赖
        try:
            from services.price_monitor import PriceMonitorService
            from services.opportunity_detector import OpportunityDetector
            from services.alert import AlertService
            
            self._price_monitor = PriceMonitorService()
            self._opportunity_detector = OpportunityDetector()
            self._alert_service = AlertService()
            
            logger.info("MonitorV2 dependencies loaded")
        except ImportError as e:
            logger.warning(f"Could not load dependencies: {e}")
        
        logger.info("MonitorV2 initialized")
    
    def set_config(self, config: MonitorConfig):
        """设置配置"""
        self._config = config
        self._alert_aggregator = AlertAggregator(
            window_seconds=config.alert_aggregation_window_seconds,
            max_alerts=config.max_alerts_per_window
        )
    
    def get_config(self) -> MonitorConfig:
        """获取配置"""
        return self._config
    
    # ============================================
    # 启动和停止
    # ============================================
    
    async def start(self):
        """启动监控"""
        if self._is_running:
            return
        
        logger.info("Starting MonitorV2...")
        
        self._stats.is_running = True
        self._stats.started_at = datetime.now()
        self._is_running = True
        
        # 启动主监控循环
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        
        # 启动报告任务
        if self._config.hourly_report_enabled:
            self._report_tasks.append(asyncio.create_task(self._hourly_report_loop()))
        
        if self._config.daily_report_enabled:
            self._report_tasks.append(asyncio.create_task(self._daily_report_loop()))
        
        logger.info("MonitorV2 started")
    
    async def stop(self):
        """停止监控"""
        if not self._is_running:
            return
        
        logger.info("Stopping MonitorV2...")
        
        self._is_running = False
        self._stats.is_running = False
        
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        
        for task in self._report_tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        
        logger.info("MonitorV2 stopped")
    
    # ============================================
    # 监控循环
    # ============================================
    
    async def _monitor_loop(self):
        """主监控循环"""
        while self._is_running:
            try:
                cycle_start = datetime.now()
                
                # 1. 价格监控
                await self._check_prices()
                
                # 2. 机会检测
                await self._check_opportunities()
                
                # 3. 系统健康检查
                await self._check_system_health()
                
                # 更新统计
                self._stats.total_cycles += 1
                self._stats.last_cycle_time = datetime.now()
                
                # 计算平均周期时间
                if self._stats.avg_cycle_time_ms == 0:
                    self._stats.avg_cycle_time_ms = 100
                else:
                    elapsed = (datetime.now() - cycle_start).total_seconds() * 1000
                    self._stats.avg_cycle_time_ms = (
                        self._stats.avg_cycle_time_ms * 0.9 + elapsed * 0.1
                    )
                
                await asyncio.sleep(self._config.polling_interval_seconds)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Monitor loop error: {e}")
                self._stats.errors += 1
                await asyncio.sleep(5)
    
    async def _check_prices(self):
        """检查价格变动"""
        if not self._price_monitor:
            return
        
        try:
            # 获取价格
            prices = await self._price_monitor.get_all_prices()
            
            for symbol, chain_price in prices.items():
                for chain, price in chain_price.items():
                    old_price = self._price_cache.get(f"{symbol}_{chain}")
                    
                    if old_price and old_price > 0:
                        change_pct = ((price - old_price) / old_price) * 100
                        
                        # 检查是否超过阈值
                        if abs(change_pct) >= self._config.price_change_threshold_pct:
                            change = PriceChange(
                                symbol=symbol,
                                chain=chain,
                                old_price=old_price,
                                new_price=price,
                                change_pct=change_pct,
                                change_usd=price - old_price,
                                timestamp=datetime.now(),
                            )
                            
                            self._price_history[f"{symbol}_{chain}"].append(change)
                            
                            # 触发告警
                            await self._send_alert(
                                category=AlertCategory.OPPORTUNITY,
                                level=AlertLevel.INFO if abs(change_pct) < 5 else AlertLevel.WARNING,
                                title=f"价格变动: {symbol}",
                                message=f"{chain} {symbol} 价格变动 {change_pct:.2f}%",
                                data={
                                    "type": "price_change",
                                    "change": change.__dict__,
                                }
                            )
                    
                    # 更新缓存
                    self._price_cache[f"{symbol}_{chain}"] = price
                    
        except Exception as e:
            logger.error(f"Price check error: {e}")
    
    async def _check_opportunities(self):
        """检查套利机会"""
        if not self._opportunity_detector:
            return
        
        try:
            opportunities = await self._opportunity_detector.detect_all()
            
            for opp in opportunities:
                # 检查利润阈值
                if opp.estimated_profit_usd < self._config.min_profit_threshold_usd:
                    continue
                
                self._stats.opportunities_detected += 1
                
                # 发送机会告警
                alert_key = f"opp_{opp.id}"
                
                if not self._is_in_cooldown(alert_key):
                    await self._send_opportunity_alert(opp)
                    self._set_cooldown(alert_key)
                
        except Exception as e:
            logger.error(f"Opportunity check error: {e}")
    
    async def _check_system_health(self):
        """检查系统健康"""
        try:
            # 检查各组件心跳
            from services.auto_controller import get_auto_controller
            
            controller = get_auto_controller()
            status = controller.get_status()
            
            # 检查是否有组件不健康
            for comp_name, comp_status in status.get("components", {}).items():
                if comp_status.get("state") not in ["ready", "running"]:
                    await self._send_alert(
                        category=AlertCategory.SYSTEM,
                        level=AlertLevel.WARNING,
                        title=f"组件异常: {comp_name}",
                        message=f"组件状态: {comp_status.get('state')}",
                        data={"component": comp_name, "status": comp_status}
                    )
                    
        except Exception as e:
            logger.error(f"Health check error: {e}")
    
    async def _send_opportunity_alert(self, opportunity):
        """发送机会告警"""
        alert = OpportunityAlert(
            opportunity_id=opportunity.id,
            symbol=opportunity.symbol,
            source_chain=opportunity.source_chain,
            target_chain=opportunity.target_chain,
            profit_usd=opportunity.estimated_profit_usd,
            profit_pct=opportunity.estimated_profit_pct,
            confidence=opportunity.confidence,
            quality=opportunity.risk_level.value if hasattr(opportunity, 'risk_level') else "medium",
            timestamp=datetime.now(),
        )
        
        # 确定告警级别
        if alert.profit_usd >= 100:
            level = AlertLevel.CRITICAL
        elif alert.profit_usd >= 50:
            level = AlertLevel.WARNING
        else:
            level = AlertLevel.INFO
        
        await self._send_alert(
            category=AlertCategory.OPPORTUNITY,
            level=level,
            title=f"套利机会: {alert.symbol}",
            message=(
                f"💰 利润: ${alert.profit_usd:.2f} ({alert.profit_pct:.2f}%)\n"
                f"📍 {alert.source_chain} → {alert.target_chain}\n"
                f"🎯 置信度: {alert.confidence:.0%}\n"
                f"⏱️ 剩余: {alert.ttl_seconds}s"
            ),
            data={
                "type": "opportunity",
                "opportunity": alert.__dict__,
            }
        )
    
    # ============================================
    # 告警管理
    # ============================================
    
    async def _send_alert(
        self,
        category: AlertCategory,
        level: AlertLevel,
        title: str,
        message: str,
        data: Dict = None
    ):
        """发送告警"""
        # 检查冷却
        cooldown_key = f"{category.value}_{title}"
        if self._is_in_cooldown(cooldown_key):
            self._stats.alerts_suppressed += 1
            return
        
        # 尝试聚合
        aggregated = self._alert_aggregator.add_alert(
            category.value,
            {
                "level": level.value,
                "title": title,
                "message": message,
                "key": title,
                "data": data,
            }
        )
        
        if aggregated:
            # 发送聚合告警
            await self._dispatch_alert(aggregated)
        else:
            # 发送单个告警
            await self._dispatch_alert({
                "category": category,
                "level": level,
                "title": title,
                "message": message,
                "data": data,
                "timestamp": datetime.now(),
            })
        
        self._stats.alerts_sent += 1
        self._set_cooldown(cooldown_key)
    
    async def _dispatch_alert(self, alert: Dict):
        """分发告警"""
        category = alert.get("category", AlertCategory.SYSTEM)
        
        # 调用注册的回调
        callbacks = self._alert_callbacks.get(category, [])
        for callback in callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(alert)
                else:
                    callback(alert)
            except Exception as e:
                logger.error(f"Alert callback error: {e}")
        
        # 同时发送给告警服务
        if self._alert_service:
            try:
                level_map = {
                    AlertLevel.DEBUG: "info",
                    AlertLevel.INFO: "info",
                    AlertLevel.SUCCESS: "info",
                    AlertLevel.WARNING: "warning",
                    AlertLevel.CRITICAL: "critical",
                    AlertLevel.EMERGENCY: "emergency",
                }
                
                await self._alert_service.send(
                    level=level_map.get(alert.get("level", AlertLevel.INFO), "info"),
                    title=alert.get("title", "Alert"),
                    message=alert.get("message", ""),
                )
            except Exception as e:
                logger.error(f"Alert service error: {e}")
    
    def _is_in_cooldown(self, key: str) -> bool:
        """检查是否在冷却期"""
        if key not in self._alert_cooldowns:
            return False
        
        if datetime.now() >= self._alert_cooldowns[key]:
            del self._alert_cooldowns[key]
            return False
        
        return True
    
    def _set_cooldown(self, key: str, seconds: int = None):
        """设置冷却期"""
        seconds = seconds or self._config.alert_cooldown_seconds
        self._alert_cooldowns[key] = datetime.now() + timedelta(seconds=seconds)
    
    def register_alert_callback(self, category: AlertCategory, callback: Callable):
        """注册告警回调"""
        self._alert_callbacks[category].append(callback)
    
    def register_report_callback(self, report_type: ReportType, callback: Callable):
        """注册报告回调"""
        self._report_callbacks[report_type].append(callback)
    
    # ============================================
    # 报告生成
    # ============================================
    
    async def _hourly_report_loop(self):
        """每小时报告循环"""
        while self._is_running:
            try:
                # 等待到下一个整点
                now = datetime.now()
                next_hour = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
                wait_seconds = (next_hour - now).total_seconds()
                
                await asyncio.sleep(wait_seconds)
                
                if self._is_running:
                    report = await self._generate_report(ReportType.HOURLY)
                    await self._dispatch_report(report)
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Hourly report error: {e}")
                await asyncio.sleep(60)
    
    async def _daily_report_loop(self):
        """每日报告循环"""
        while self._is_running:
            try:
                # 等待到次日零点
                now = datetime.now()
                tomorrow = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
                wait_seconds = (tomorrow - now).total_seconds()
                
                await asyncio.sleep(wait_seconds)
                
                if self._is_running:
                    report = await self._generate_report(ReportType.DAILY)
                    await self._dispatch_report(report)
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Daily report error: {e}")
                await asyncio.sleep(3600)
    
    async def _generate_report(self, report_type: ReportType) -> SystemReport:
        """生成报告"""
        # 计算时间范围
        now = datetime.now()
        
        if report_type == ReportType.HOURLY:
            period_start = now - timedelta(hours=1)
        elif report_type == ReportType.DAILY:
            period_start = now - timedelta(days=1)
        elif report_type == ReportType.WEEKLY:
            period_start = now - timedelta(weeks=1)
        else:
            period_start = now - timedelta(hours=1)
        
        # 获取统计数据
        from services.auto_controller import get_auto_controller
        from services.fund_manager import get_fund_manager
        from services.auto_strategy import get_strategy_manager
        
        controller = get_auto_controller()
        fund_mgr = get_fund_manager()
        strategy_mgr = get_strategy_manager()
        
        status = controller.get_status()
        uptime = status.get("uptime_seconds", 0)
        
        # 获取收益统计
        profit_summary = fund_mgr.get_profit_summary(period_days=1)
        
        # 获取链统计
        chain_stats = fund_mgr.get_chain_performance()
        
        report = SystemReport(
            report_type=report_type,
            period_start=period_start,
            period_end=now,
            generated_at=now,
            uptime_seconds=uptime,
            total_cycles=self._stats.total_cycles,
            errors=self._stats.errors,
            opportunities_detected=self._stats.opportunities_detected,
            opportunities_executed=self._stats.opportunities_executed,
            total_profit_usd=profit_summary.get("total_profit", 0),
            total_loss_usd=profit_summary.get("total_loss", 0),
            net_profit_usd=profit_summary.get("net_profit", 0),
            trades_count=profit_summary.get("total_trades", 0),
            win_rate=profit_summary.get("win_rate", 0),
            chain_stats=chain_stats,
            alerts_count=self._stats.alerts_sent,
            critical_alerts=0,
        )
        
        return report
    
    async def _dispatch_report(self, report: SystemReport):
        """分发报告"""
        callbacks = self._report_callbacks.get(report.report_type, [])
        
        report_data = {
            "type": report.report_type.value,
            "period": f"{report.period_start.strftime('%Y-%m-%d %H:%M')} - {report.period_end.strftime('%H:%M')}",
            "uptime": f"{report.uptime_seconds / 3600:.1f}h",
            "cycles": report.total_cycles,
            "errors": report.errors,
            "opportunities": report.opportunities_detected,
            "trades": report.trades_count,
            "net_profit": f"${report.net_profit_usd:.2f}",
            "win_rate": f"{report.win_rate:.1%}",
            "alerts": report.alerts_count,
        }
        
        message = self._format_report_message(report_data)
        
        # 发送到告警服务
        await self._send_alert(
            category=AlertCategory.PERFORMANCE,
            level=AlertLevel.INFO,
            title=f"{report.report_type.value.capitalize()} Report",
            message=message,
            data=report_data,
        )
        
        for callback in callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(report)
                else:
                    callback(report)
            except Exception as e:
                logger.error(f"Report callback error: {e}")
    
    def _format_report_message(self, data: Dict) -> str:
        """格式化报告消息"""
        return f"""
📊 {data['type'].upper()} REPORT - {data['period']}

⏱️ 运行时间: {data['uptime']}
🔄 监控周期: {data['cycles']}
❌ 错误: {data['errors']}

💰 收益:
   净利润: {data['net_profit']}
   交易数: {data['trades']}
   胜率: {data['win_rate']}

🎯 机会: {data['opportunities']}
🔔 告警: {data['alerts']}
        """.strip()
    
    # ============================================
    # 状态和统计
    # ============================================
    
    def get_status(self) -> Dict:
        """获取状态"""
        return {
            "is_running": self._is_running,
            "started_at": self._stats.started_at.isoformat() if self._stats.started_at else None,
            "total_cycles": self._stats.total_cycles,
            "errors": self._stats.errors,
            "opportunities_detected": self._stats.opportunities_detected,
            "alerts_sent": self._stats.alerts_sent,
            "alerts_suppressed": self._stats.alerts_suppressed,
            "avg_cycle_time_ms": f"{self._stats.avg_cycle_time_ms:.2f}",
        }
    
    def get_stats(self) -> Dict:
        """获取统计"""
        return {
            "cycles": self._stats.total_cycles,
            "opportunities": self._stats.opportunities_detected,
            "alerts": {
                "sent": self._stats.alerts_sent,
                "suppressed": self._stats.alerts_suppressed,
            },
            "performance": {
                "avg_cycle_time_ms": self._stats.avg_cycle_time_ms,
            }
        }


# ============================================
# 单例访问函数
# ============================================

_monitor_v2: Optional[MonitorV2] = None


def get_monitor_v2() -> MonitorV2:
    """获取监控器 V2 单例"""
    global _monitor_v2
    if _monitor_v2 is None:
        _monitor_v2 = MonitorV2()
    return _monitor_v2


async def init_monitor_v2() -> MonitorV2:
    """初始化监控器 V2"""
    monitor = get_monitor_v2()
    await monitor.initialize()
    return monitor
