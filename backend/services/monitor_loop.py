"""
主监控循环 - Phase 2 核心功能
协调价格监控、费用获取、机会检测和告警推送

功能特性:
- 轮询式监控循环
- 可配置的轮询间隔
- 并发执行优化
- 优雅停止
"""

import asyncio
import logging
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
import signal

import sys
import os

# 添加 backend 目录到路径以支持相对导入
_backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from config.settings import (
    settings,
    ENABLED_CHAINS,
    get_evm_chains,
)
from services.price_monitor import PriceMonitorService
from services.bridge_fee_monitor import BridgeFeeMonitorService, get_bridge_fee_monitor
from services.opportunity_detector import (
    OpportunityDetector,
    OpportunityDetectorService,
    ArbitrageConfig,
    ArbitrageOpportunity,
    get_opportunities,
)
from services.alert import AlertService, get_alert_service, AlertLevel, AlertType

logger = logging.getLogger(__name__)


# ============================================
# 配置类
# ============================================

@dataclass
class MonitorConfig:
    """监控配置"""
    # 轮询间隔（秒）
    polling_interval: int = 30           # 默认 30 秒
    fast_polling_interval: int = 10     # 快速轮询 10 秒
    
    # 价格刷新间隔（秒）
    price_refresh_interval: int = 60     # 价格每 60 秒刷新
    
    # 费用刷新间隔（秒）
    fee_refresh_interval: int = 120      # 费用每 120 秒刷新
    
    # 机会检测间隔（秒）
    opportunity_scan_interval: int = 30  # 每 30 秒检测
    
    # 告警发送设置
    alert_on_profit_threshold: float = 10.0   # 利润超过此值时告警
    alert_on_high_confidence: float = 0.7      # 置信度超过此值时告警
    
    # 监控的代币
    monitoring_symbols: List[str] = None
    
    # 监控的链
    monitoring_chains: List[str] = None
    
    # 是否启用
    enabled: bool = True
    
    # 调试模式
    debug_mode: bool = False
    
    def __post_init__(self):
        if self.monitoring_symbols is None:
            self.monitoring_symbols = ["ETH", "WBTC", "USDC", "USDT", "BNB", "MATIC", "AVAX"]
        if self.monitoring_chains is None:
            self.monitoring_chains = get_evm_chains()


@dataclass
class MonitorStats:
    """监控统计"""
    # 运行状态
    is_running: bool = False
    started_at: Optional[datetime] = None
    last_update: Optional[datetime] = None
    total_cycles: int = 0
    errors: int = 0
    
    # 性能指标
    avg_cycle_time_ms: float = 0
    max_cycle_time_ms: float = 0
    
    # 检测统计
    opportunities_detected: int = 0
    alerts_sent: int = 0
    high_profit_opportunities: int = 0
    
    # 缓存状态
    price_cache_size: int = 0
    fee_cache_size: int = 0
    
    def to_dict(self) -> Dict:
        return {
            "is_running": self.is_running,
            "uptime_seconds": (datetime.now() - self.started_at).total_seconds() if self.started_at else 0,
            "total_cycles": self.total_cycles,
            "errors": self.errors,
            "avg_cycle_time_ms": self.avg_cycle_time_ms,
            "max_cycle_time_ms": self.max_cycle_time_ms,
            "opportunities_detected": self.opportunities_detected,
            "alerts_sent": self.alerts_sent,
            "high_profit_opportunities": self.high_profit_opportunities,
            "price_cache_size": self.price_cache_size,
            "fee_cache_size": self.fee_cache_size,
        }


class MonitorStatus(Enum):
    """监控状态"""
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPING = "stopping"
    ERROR = "error"


# ============================================
# 监控循环
# ============================================

class MonitorLoop:
    """
    主监控循环
    
    协调所有监控任务：
    1. 价格监控
    2. 跨链费用获取
    3. 套利机会检测
    4. 告警推送
    """
    
    def __init__(
        self,
        config: MonitorConfig = None,
        price_monitor: PriceMonitorService = None,
        fee_monitor: BridgeFeeMonitorService = None,
        alert_service: AlertService = None
    ):
        """
        初始化监控循环
        
        Args:
            config: 监控配置
            price_monitor: 价格监控服务
            fee_monitor: 费用监控服务
            alert_service: 告警服务
        """
        self.config = config or MonitorConfig()
        
        # 服务引用
        self._price_monitor = price_monitor
        self._fee_monitor = fee_monitor
        self._alert_service = alert_service
        
        # 套利检测器
        self._detector_service = OpportunityDetectorService(
            config=ArbitrageConfig(
                monitoring_chains=self.config.monitoring_chains,
                monitoring_symbols=self.config.monitoring_symbols,
                min_profit_threshold_usd=self.config.alert_on_profit_threshold,
            )
        )
        
        # 状态
        self._status = MonitorStatus.STOPPED
        self._running = False
        self._paused = False
        self._tasks: List[asyncio.Task] = []
        
        # 统计
        self.stats = MonitorStats()
        
        # 回调
        self._on_opportunity_found: Optional[Callable] = None
        self._on_alert_sent: Optional[Callable] = None
        self._on_cycle_complete: Optional[Callable] = None
        
        # 循环计时
        self._cycle_times: List[float] = []
        self._max_cycle_history = 100
        
        # 锁
        self._lock = asyncio.Lock()
        
        logger.info("[MonitorLoop] Initialized")
    
    @property
    def status(self) -> MonitorStatus:
        """当前状态"""
        return self._status
    
    @property
    def is_running(self) -> bool:
        """是否正在运行"""
        return self._status == MonitorStatus.RUNNING
    
    def set_callbacks(
        self,
        on_opportunity: Callable = None,
        on_alert: Callable = None,
        on_cycle: Callable = None
    ) -> None:
        """设置回调函数"""
        self._on_opportunity_found = on_opportunity
        self._on_alert_sent = on_alert
        self._on_cycle_complete = on_cycle
    
    async def start(self) -> None:
        """启动监控循环"""
        if self._status == MonitorStatus.RUNNING:
            logger.warning("[MonitorLoop] Already running")
            return
        
        logger.info("[MonitorLoop] Starting...")
        self._status = MonitorStatus.STARTING
        
        # 初始化服务
        await self._initialize_services()
        
        # 启动主循环
        self._running = True
        self._status = MonitorStatus.RUNNING
        self.stats = MonitorStats(
            is_running=True,
            started_at=datetime.now()
        )
        
        # 创建主任务
        main_task = asyncio.create_task(self._main_loop())
        self._tasks.append(main_task)
        
        logger.info("[MonitorLoop] Started")
    
    async def stop(self) -> None:
        """停止监控循环"""
        if self._status == MonitorStatus.STOPPED:
            return
        
        logger.info("[MonitorLoop] Stopping...")
        self._status = MonitorStatus.STOPPING
        self._running = False
        
        # 取消所有任务
        for task in self._tasks:
            if not task.done():
                task.cancel()
        
        # 等待任务完成
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        
        self._tasks = []
        self._status = MonitorStatus.STOPPED
        self.stats.is_running = False
        
        logger.info("[MonitorLoop] Stopped")
    
    async def pause(self) -> None:
        """暂停监控"""
        self._paused = True
        self._status = MonitorStatus.PAUSED
        logger.info("[MonitorLoop] Paused")
    
    async def resume(self) -> None:
        """恢复监控"""
        self._paused = False
        self._status = MonitorStatus.RUNNING
        logger.info("[MonitorLoop] Resumed")
    
    async def _initialize_services(self) -> None:
        """初始化服务"""
        try:
            # 初始化价格监控
            if self._price_monitor is None:
                self._price_monitor = PriceMonitorService(
                    polling_interval=self.config.polling_interval,
                    cache_ttl=settings.CACHE_TTL_PRICE
                )
                await self._price_monitor.start()
            
            # 初始化费用监控
            if self._fee_monitor is None:
                self._fee_monitor = get_bridge_fee_monitor()
            
            # 初始化告警服务
            if self._alert_service is None:
                self._alert_service = get_alert_service()
            
            # 初始化机会检测器
            await self._detector_service.initialize(
                price_monitor=self._price_monitor,
                fee_monitor=self._fee_monitor
            )
            
            logger.info("[MonitorLoop] Services initialized")
            
        except Exception as e:
            logger.error(f"[MonitorLoop] Service initialization failed: {e}")
            self._status = MonitorStatus.ERROR
            raise
    
    async def _main_loop(self) -> None:
        """主监控循环"""
        logger.info("[MonitorLoop] Main loop started")
        
        last_price_update = datetime.now()
        last_fee_update = datetime.now()
        last_opportunity_scan = datetime.now()
        
        cycle_count = 0
        
        while self._running:
            try:
                # 暂停时等待
                if self._paused:
                    await asyncio.sleep(1)
                    continue
                
                cycle_start = datetime.now()
                self.stats.total_cycles += 1
                
                # 确定轮询间隔
                interval = self._determine_polling_interval()
                
                # 执行监控步骤
                await self._run_cycle(
                    now=cycle_start,
                    last_price_update=last_price_update,
                    last_fee_update=last_fee_update,
                    last_opportunity_scan=last_opportunity_scan
                )
                
                # 更新时间戳
                if self.stats.opportunities_detected > 0:
                    last_opportunity_scan = cycle_start
                
                # 计算循环时间
                cycle_time = (datetime.now() - cycle_start).total_seconds() * 1000
                self._update_cycle_time(cycle_time)
                
                # 调用周期完成回调
                if self._on_cycle_complete:
                    try:
                        await self._on_cycle_complete(self.stats)
                    except Exception as e:
                        logger.debug(f"[MonitorLoop] Cycle callback error: {e}")
                
                # 等待下一轮
                await asyncio.sleep(interval)
                cycle_count += 1
                
            except asyncio.CancelledError:
                logger.info("[MonitorLoop] Loop cancelled")
                break
            except Exception as e:
                logger.error(f"[MonitorLoop] Loop error: {e}")
                self.stats.errors += 1
                await asyncio.sleep(5)
        
        logger.info("[MonitorLoop] Main loop ended")
    
    def _determine_polling_interval(self) -> int:
        """确定轮询间隔"""
        # 如果有高置信度机会，使用快速轮询
        opportunities = self._detector_service.get_opportunities(min_profit=50)
        if opportunities and opportunities[0].confidence > 0.8:
            return self.config.fast_polling_interval
        
        return self.config.polling_interval
    
    async def _run_cycle(
        self,
        now: datetime,
        last_price_update: datetime,
        last_fee_update: datetime,
        last_opportunity_scan: datetime
    ) -> None:
        """执行单个监控周期"""
        
        # 1. 扫描套利机会
        opportunities = await self._detector_service.scan()
        
        if opportunities:
            self.stats.opportunities_detected += len(opportunities)
            
            # 统计高利润机会
            high_profit = [o for o in opportunities if o.net_profit_usd > 100]
            self.stats.high_profit_opportunities += len(high_profit)
            
            # 发送告警
            for opp in opportunities[:5]:  # 最多发送 5 个
                if opp.net_profit_usd >= self.config.alert_on_profit_threshold:
                    if opp.confidence >= self.config.alert_on_high_confidence or opp.net_profit_usd > 50:
                        result = await self._alert_service.send_arbitrage_alert(opp)
                        if result.success:
                            self.stats.alerts_sent += 1
                            
                            # 调用回调
                            if self._on_alert_sent:
                                try:
                                    await self._on_alert_sent(opp, result)
                                except Exception as e:
                                    logger.debug(f"[MonitorLoop] Alert callback error: {e}")
            
            # 调用机会回调
            if self._on_opportunity_found:
                try:
                    await self._on_opportunity_found(opportunities)
                except Exception as e:
                    logger.debug(f"[MonitorLoop] Opportunity callback error: {e}")
            
            # 调试模式打印
            if self.config.debug_mode:
                self._print_opportunities(opportunities)
        
        # 2. 定期刷新费用缓存
        if (now - last_fee_update).total_seconds() >= self.config.fee_refresh_interval:
            if self._fee_monitor:
                await self._fee_monitor.refresh_all_fees()
                last_fee_update = now
                logger.debug("[MonitorLoop] Fee cache refreshed")
        
        # 更新缓存统计
        if self._fee_monitor:
            fee_stats = self._fee_monitor.get_cache_stats()
            self.stats.fee_cache_size = fee_stats.get("size", 0)
        
        # 更新最后更新时间
        self.stats.last_update = now
    
    def _update_cycle_time(self, cycle_time_ms: float) -> None:
        """更新循环时间统计"""
        self._cycle_times.append(cycle_time_ms)
        if len(self._cycle_times) > self._max_cycle_history:
            self._cycle_times = self._cycle_times[-self._max_cycle_history:]
        
        self.stats.avg_cycle_time_ms = sum(self._cycle_times) / len(self._cycle_times)
        self.stats.max_cycle_time_ms = max(self._cycle_times)
    
    def _print_opportunities(self, opportunities: List[ArbitrageOpportunity]) -> None:
        """打印机会信息（调试模式）"""
        print("\n" + "=" * 80)
        print(f"🔍 套利机会检测 - {datetime.now().strftime('%H:%M:%S')}")
        print("=" * 80)
        
        for i, opp in enumerate(opportunities[:5], 1):
            print(f"\n#{i} {opp.symbol}")
            print(f"   路径: {opp.source_chain} → {opp.target_chain}")
            print(f"   价差: {opp.price_diff_pct:.2f}%")
            print(f"   利润: ${opp.net_profit_usd:.2f} (置信度: {opp.confidence:.0%})")
            print(f"   风险: {opp.risk_level.value} ({opp.risk_score:.2f})")
            print(f"   建议: {opp.recommendation.value}")
        
        print("\n" + "=" * 80 + "\n")
    
    async def run_once(self) -> List[ArbitrageOpportunity]:
        """执行一次监控（用于测试）"""
        opportunities = await self._detector_service.scan()
        
        for opp in opportunities:
            await self._alert_service.send_arbitrage_alert(opp)
        
        return opportunities
    
    def get_opportunities(
        self,
        min_profit: float = None,
        limit: int = 10
    ) -> List[ArbitrageOpportunity]:
        """获取当前机会"""
        return self._detector_service.get_opportunities(
            min_profit=min_profit,
            limit=limit
        )
    
    def get_stats(self) -> Dict:
        """获取统计信息"""
        return {
            **self.stats.to_dict(),
            "detector": self._detector_service.get_stats(),
            "alert": self._alert_service.get_stats() if self._alert_service else {},
        }


# ============================================
# 独立运行器
# ============================================

class MonitorRunner:
    """
    监控运行器
    
    提供独立的监控运行能力
    """
    
    def __init__(self, config: MonitorConfig = None):
        self.config = config or MonitorConfig()
        self.monitor = MonitorLoop(config=self.config)
        self._shutdown_event = asyncio.Event()
    
    async def run(self) -> None:
        """运行监控"""
        # 设置信号处理
        loop = asyncio.get_event_loop()
        
        def signal_handler():
            logger.info("Received shutdown signal")
            asyncio.create_task(self.shutdown())
        
        try:
            loop.add_signal_handler(signal.SIGINT, signal_handler)
            loop.add_signal_handler(signal.SIGTERM, signal_handler)
        except NotImplementedError:
            # Windows 不支持 add_signal_handler
            pass
        
        # 启动监控
        await self.monitor.start()
        
        # 设置回调
        self.monitor.set_callbacks(
            on_opportunity=self._on_opportunity,
            on_alert=self._on_alert,
            on_cycle=self._on_cycle
        )
        
        # 等待停止信号
        await self._shutdown_event.wait()
    
    async def shutdown(self) -> None:
        """关闭监控"""
        logger.info("Shutting down monitor...")
        await self.monitor.stop()
        self._shutdown_event.set()
    
    async def _on_opportunity(self, opportunities: List[ArbitrageOpportunity]) -> None:
        """机会发现回调"""
        pass
    
    async def _on_alert(self, opportunity: ArbitrageOpportunity, result: Any) -> None:
        """告警发送回调"""
        logger.info(f"Alert sent for {opportunity.symbol}: ${opportunity.net_profit_usd:.2f}")
    
    async def _on_cycle(self, stats: MonitorStats) -> None:
        """周期完成回调"""
        pass


# ============================================
# 全局实例和便捷函数
# ============================================

# 全局监控循环实例
monitor_loop: Optional[MonitorLoop] = None


def get_monitor_loop() -> MonitorLoop:
    """获取监控循环实例"""
    global monitor_loop
    
    if monitor_loop is None:
        monitor_loop = MonitorLoop()
    
    return monitor_loop


async def start_monitoring(config: MonitorConfig = None) -> MonitorLoop:
    """启动监控的便捷函数"""
    monitor = MonitorLoop(config=config)
    await monitor.start()
    return monitor


async def stop_monitoring() -> None:
    """停止监控的便捷函数"""
    global monitor_loop
    if monitor_loop:
        await monitor_loop.stop()
        monitor_loop = None


# ============================================
# 主入口（用于测试）
# ============================================

async def main():
    """主入口函数（用于测试）"""
    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    )
    
    logger.info("Starting Monitor Loop Test...")
    
    # 创建配置
    config = MonitorConfig(
        polling_interval=15,
        debug_mode=True,
        monitoring_symbols=["ETH", "WBTC"],
        monitoring_chains=["ethereum", "arbitrum", "optimism"],
    )
    
    # 创建并运行监控
    runner = MonitorRunner(config)
    
    try:
        await runner.run()
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        await runner.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
