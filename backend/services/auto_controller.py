"""
主控制器 - Phase 3 全自动执行核心组件

功能：
- 系统启动/停止
- 安全启动流程
- 优雅停止流程
- 紧急停止
- 状态管理
- 组件健康检查
- 异常恢复
- 组件间协调
- 事件驱动调度
- 消息队列

设计原则：
- 安全第一：所有操作都有确认和日志
- 可观测：完整的状态追踪
- 可恢复：异常自动恢复
"""

import asyncio
import logging
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from collections import defaultdict
import json
import signal

import sys
import os as _os
_backend_dir = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)


logger = logging.getLogger(__name__)


# ============================================
# 枚举定义
# ============================================

class SystemState(Enum):
    """系统状态"""
    STOPPED = "stopped"               # 已停止
    STARTING = "starting"              # 启动中
    RUNNING = "running"               # 运行中
    PAUSED = "paused"                 # 暂停
    STOPPING = "stopping"             # 停止中
    EMERGENCY = "emergency"           # 紧急状态
    ERROR = "error"                   # 错误状态


class ComponentType(Enum):
    """组件类型"""
    MONITOR = "monitor"
    STRATEGY = "strategy"
    FUND_MANAGER = "fund_manager"
    EXECUTION_SCHEDULER = "execution_scheduler"
    FLASH_LOAN = "flash_loan"
    EXECUTION_ENGINE = "execution_engine"
    ALERT = "alert"


class ComponentState(Enum):
    """组件状态"""
    UNINITIALIZED = "uninitialized"
    INITIALIZING = "initializing"
    READY = "ready"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"
    ERROR = "error"


class EventType(Enum):
    """事件类型"""
    OPPORTUNITY_DETECTED = "opportunity_detected"
    OPPORTUNITY_EXPIRED = "opportunity_expired"
    TRADE_STARTED = "trade_started"
    TRADE_COMPLETED = "trade_completed"
    TRADE_FAILED = "trade_failed"
    BALANCE_CHANGED = "balance_changed"
    RISK_ALERT = "risk_alert"
    SYSTEM_ERROR = "system_error"
    EMERGENCY_STOP = "emergency_stop"
    HEALTH_CHECK = "health_check"


# ============================================
# 数据类定义
# ============================================

@dataclass
class ComponentInfo:
    """组件信息"""
    name: str
    component_type: ComponentType
    state: ComponentState
    last_heartbeat: Optional[datetime] = None
    error: Optional[str] = None
    stats: Dict = field(default_factory=dict)


@dataclass
class SystemEvent:
    """系统事件"""
    id: str
    event_type: EventType
    timestamp: datetime
    data: Dict
    source: str
    processed: bool = False


@dataclass
class HealthCheckResult:
    """健康检查结果"""
    component: str
    healthy: bool
    latency_ms: float
    message: str
    details: Dict = field(default_factory=dict)


@dataclass
class ControllerConfig:
    """控制器配置"""
    # 健康检查
    health_check_interval_seconds: int = 30
    heartbeat_timeout_seconds: int = 120
    
    # 事件处理
    event_queue_size: int = 1000
    event_processing_timeout: int = 10
    
    # 恢复策略
    max_auto_restart_attempts: int = 3
    restart_delay_seconds: int = 5
    
    # 日志
    log_level: str = "INFO"


# ============================================
# 事件总线
# ============================================

class EventBus:
    """事件总线 - 组件间通信"""
    
    def __init__(self):
        self._subscribers: Dict[EventType, List[Callable]] = defaultdict(list)
        self._event_queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._processing = False
    
    def subscribe(self, event_type: EventType, callback: Callable):
        """订阅事件"""
        self._subscribers[event_type].append(callback)
        logger.debug(f"Subscribed to {event_type.value}")
    
    def unsubscribe(self, event_type: EventType, callback: Callable):
        """取消订阅"""
        if callback in self._subscribers[event_type]:
            self._subscribers[event_type].remove(callback)
    
    async def publish(self, event: SystemEvent):
        """发布事件"""
        try:
            self._event_queue.put_nowait(event)
            logger.debug(f"Event published: {event.event_type.value}")
        except asyncio.QueueFull:
            logger.warning("Event queue full, dropping event")
    
    async def process_events(self):
        """处理事件队列"""
        self._processing = True
        
        while self._processing:
            try:
                event = await asyncio.wait_for(
                    self._event_queue.get(),
                    timeout=1.0
                )
                
                # 获取订阅者
                callbacks = self._subscribers.get(event.event_type, [])
                
                for callback in callbacks:
                    try:
                        if asyncio.iscoroutinefunction(callback):
                            await asyncio.wait_for(
                                callback(event),
                                timeout=10.0
                            )
                        else:
                            callback(event)
                    except Exception as e:
                        logger.error(f"Event callback error: {e}")
                
                event.processed = True
                
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"Event processing error: {e}")
    
    def stop_processing(self):
        """停止处理"""
        self._processing = False


# ============================================
# 主控制器
# ============================================

class AutoController:
    """自动执行主控制器"""
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not hasattr(self, "_initialized"):
            self._initialized = True
            
            # 系统状态
            self._state = SystemState.STOPPED
            
            # 组件
            self._components: Dict[ComponentType, ComponentInfo] = {}
            
            # 事件总线
            self._event_bus = EventBus()
            
            # 配置
            self._config = ControllerConfig()
            
            # 任务
            self._controller_task: Optional[asyncio.Task] = None
            self._health_check_task: Optional[asyncio.Task] = None
            
            # 事件处理器
            self._event_handlers: Dict[EventType, Callable] = {}
            
            # 启动时间
            self._started_at: Optional[datetime] = None
            
            # 统计
            self._stats = {
                "events_processed": 0,
                "opportunities_detected": 0,
                "trades_executed": 0,
                "trades_succeeded": 0,
                "trades_failed": 0,
            }
    
    @property
    def state(self) -> SystemState:
        """获取系统状态"""
        return self._state
    
    @property
    def event_bus(self) -> EventBus:
        """获取事件总线"""
        return self._event_bus
    
    async def initialize(self):
        """初始化"""
        logger.info("AutoController initializing...")
        
        # 初始化事件处理器
        self._init_event_handlers()
        
        # 初始化组件信息
        for comp_type in ComponentType:
            self._components[comp_type] = ComponentInfo(
                name=comp_type.value,
                component_type=comp_type,
                state=ComponentState.UNINITIALIZED,
            )
        
        logger.info("AutoController initialized")
    
    def _init_event_handlers(self):
        """初始化事件处理器"""
        self.register_event_handler(
            EventType.OPPORTUNITY_DETECTED,
            self._handle_opportunity
        )
        self.register_event_handler(
            EventType.EMERGENCY_STOP,
            self._handle_emergency
        )
        self.register_event_handler(
            EventType.TRADE_COMPLETED,
            self._handle_trade_completed
        )
        self.register_event_handler(
            EventType.TRADE_FAILED,
            self._handle_trade_failed
        )
        self.register_event_handler(
            EventType.RISK_ALERT,
            self._handle_risk_alert
        )
    
    def register_event_handler(self, event_type: EventType, handler: Callable):
        """注册事件处理器"""
        self._event_handlers[event_type] = handler
        self._event_bus.subscribe(event_type, handler)
    
    # ============================================
    # 启动和停止
    # ============================================
    
    async def start(self) -> bool:
        """启动系统"""
        if self._state in [SystemState.RUNNING, SystemState.STARTING]:
            logger.warning("System already running or starting")
            return False
        
        logger.info("=" * 50)
        logger.info("Starting Phase 3 Auto Execution System")
        logger.info("=" * 50)
        
        self._state = SystemState.STARTING
        
        try:
            # 1. 初始化所有组件
            await self._initialize_components()
            
            # 2. 健康检查
            health_ok = await self._health_check()
            if not health_ok:
                raise Exception("Health check failed")
            
            # 3. 启动事件处理循环
            asyncio.create_task(self._event_bus.process_events())
            
            # 4. 启动健康检查任务
            self._health_check_task = asyncio.create_task(self._health_check_loop())
            
            # 5. 启动监控循环（如果启用）
            # monitor = await self._get_component(ComponentType.MONITOR)
            # if monitor and monitor.state == ComponentState.READY:
            #     asyncio.create_task(self._start_monitor())
            
            self._state = SystemState.RUNNING
            self._started_at = datetime.now()
            
            logger.info("=" * 50)
            logger.info("System started successfully")
            logger.info("=" * 50)
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to start system: {e}")
            self._state = SystemState.ERROR
            return False
    
    async def stop(self, emergency: bool = False):
        """停止系统"""
        if self._state == SystemState.STOPPED:
            return
        
        mode = "EMERGENCY" if emergency else "GRACEFUL"
        logger.info(f"Initiating {mode} shutdown...")
        
        self._state = SystemState.STOPPING
        
        try:
            # 1. 停止接受新任务
            scheduler = await self._get_component(ComponentType.EXECUTION_SCHEDULER)
            if scheduler:
                await scheduler.stop()
            
            # 2. 等待进行中的任务完成（非紧急模式）
            if not emergency:
                await self._wait_for_completion(timeout=60)
            
            # 3. 停止所有组件
            await self._stop_components()
            
            # 4. 停止事件处理
            self._event_bus.stop_processing()
            
            # 5. 停止健康检查
            if self._health_check_task:
                self._health_check_task.cancel()
                try:
                    await self._health_check_task
                except asyncio.CancelledError:
                    pass
            
            self._state = SystemState.STOPPED
            
            logger.info("System stopped successfully")
            
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")
            self._state = SystemState.ERROR
    
    async def pause(self):
        """暂停系统"""
        if self._state != SystemState.RUNNING:
            return False
        
        logger.info("Pausing system...")
        
        for comp_type, comp in self._components.items():
            if comp.state == ComponentState.RUNNING:
                comp.state = ComponentState.PAUSED
        
        self._state = SystemState.PAUSED
        logger.info("System paused")
        return True
    
    async def resume(self):
        """恢复系统"""
        if self._state != SystemState.PAUSED:
            return False
        
        logger.info("Resuming system...")
        
        for comp_type, comp in self._components.items():
            if comp.state == ComponentState.PAUSED:
                comp.state = ComponentState.RUNNING
        
        self._state = SystemState.RUNNING
        logger.info("System resumed")
        return True
    
    async def emergency_stop(self):
        """紧急停止"""
        logger.critical("EMERGENCY STOP TRIGGERED")
        
        # 发布紧急停止事件
        await self._event_bus.publish(SystemEvent(
            id=str(datetime.now().timestamp()),
            event_type=EventType.EMERGENCY_STOP,
            timestamp=datetime.now(),
            data={},
            source="auto_controller",
        ))
        
        self._state = SystemState.EMERGENCY
        await self.stop(emergency=True)
    
    # ============================================
    # 组件管理
    # ============================================
    
    async def register_component(
        self,
        component_type: ComponentType,
        component
    ):
        """注册组件"""
        comp_info = self._components.get(component_type)
        if not comp_info:
            comp_info = ComponentInfo(
                name=component_type.value,
                component_type=component_type,
                state=ComponentState.INITIALIZING,
            )
            self._components[component_type] = comp_info
        
        comp_info.state = ComponentState.READY
        comp_info.last_heartbeat = datetime.now()
        
        logger.info(f"Component registered: {component_type.value}")
    
    async def unregister_component(self, component_type: ComponentType):
        """注销组件"""
        comp_info = self._components.get(component_type)
        if comp_info:
            comp_info.state = ComponentState.STOPPED
            logger.info(f"Component unregistered: {component_type.value}")
    
    async def _get_component(self, component_type: ComponentType):
        """获取组件"""
        return self._components.get(component_type)
    
    async def _initialize_components(self):
        """初始化所有组件"""
        from services.auto_strategy import init_strategy_manager
        from services.fund_manager import init_fund_manager
        from services.execution_scheduler import init_execution_scheduler
        from services.flash_loan_manager import init_flash_loan_manager
        
        # 初始化顺序很重要
        init_tasks = [
            (ComponentType.STRATEGY, init_strategy_manager()),
            (ComponentType.FUND_MANAGER, init_fund_manager()),
            (ComponentType.FLASH_LOAN, init_flash_loan_manager()),
            (ComponentType.EXECUTION_SCHEDULER, init_execution_scheduler()),
        ]
        
        for comp_type, init_coro in init_tasks:
            try:
                comp_info = self._components.get(comp_type)
                if comp_info:
                    comp_info.state = ComponentState.INITIALIZING
                
                component = await init_coro
                await self.register_component(comp_type, component)
                
                logger.info(f"Component initialized: {comp_type.value}")
                
            except Exception as e:
                logger.error(f"Failed to initialize {comp_type.value}: {e}")
                raise
    
    async def _stop_components(self):
        """停止所有组件"""
        for comp_type, comp_info in self._components.items():
            if comp_info.state not in [ComponentState.STOPPED, ComponentState.UNINITIALIZED]:
                comp_info.state = ComponentState.STOPPED
                logger.debug(f"Component stopped: {comp_type.value}")
    
    async def _wait_for_completion(self, timeout: int = 60):
        """等待任务完成"""
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            scheduler = self._components.get(ComponentType.EXECUTION_SCHEDULER)
            
            if scheduler:
                running = scheduler.get_running_tasks()
                if not running:
                    break
            
            await asyncio.sleep(1)
        
        logger.info("Wait for completion finished")
    
    # ============================================
    # 健康检查
    # ============================================
    
    async def _health_check_loop(self):
        """健康检查循环"""
        while self._state in [SystemState.RUNNING, SystemState.PAUSED]:
            try:
                await self._health_check()
                await asyncio.sleep(self._config.health_check_interval_seconds)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Health check error: {e}")
                await asyncio.sleep(5)
    
    async def _health_check(self) -> bool:
        """执行健康检查"""
        all_healthy = True
        
        for comp_type, comp_info in self._components.items():
            if comp_info.state not in [ComponentState.READY, ComponentState.RUNNING]:
                continue
            
            # 检查心跳
            if comp_info.last_heartbeat:
                elapsed = (datetime.now() - comp_info.last_heartbeat).seconds
                if elapsed > self._config.heartbeat_timeout_seconds:
                    logger.warning(
                        f"Component {comp_type.value} heartbeat timeout: "
                        f"{elapsed}s"
                    )
                    all_healthy = False
        
        if not all_healthy:
            logger.warning("Health check: some components unhealthy")
        
        return all_healthy
    
    async def check_component_health(
        self,
        component_type: ComponentType
    ) -> HealthCheckResult:
        """检查单个组件健康状态"""
        comp_info = self._components.get(component_type)
        
        if not comp_info:
            return HealthCheckResult(
                component=component_type.value,
                healthy=False,
                latency_ms=0,
                message="Component not found",
            )
        
        start = asyncio.get_event_loop().time()
        
        healthy = comp_info.state in [
            ComponentState.READY,
            ComponentState.RUNNING
        ]
        
        latency = (asyncio.get_event_loop().time() - start) * 1000
        
        return HealthCheckResult(
            component=component_type.value,
            healthy=healthy,
            latency_ms=latency,
            message="OK" if healthy else f"State: {comp_info.state.value}",
            details={
                "state": comp_info.state.value,
                "last_heartbeat": comp_info.last_heartbeat.isoformat() if comp_info.last_heartbeat else None,
                "error": comp_info.error,
            }
        )
    
    # ============================================
    # 事件处理
    # ============================================
    
    async def _handle_opportunity(self, event: SystemEvent):
        """处理机会检测事件"""
        self._stats["opportunities_detected"] += 1
        
        opportunity = event.data.get("opportunity")
        if not opportunity:
            return
        
        # 获取策略管理器评估
        from services.auto_strategy import get_strategy_manager
        from services.fund_manager import get_fund_manager
        
        strategy_mgr = get_strategy_manager()
        fund_mgr = get_fund_manager()
        
        # 评估机会
        context = {
            "available_balance": fund_mgr.get_available_balance(),
            "gas_price_gwei": 30,  # 默认值
        }
        
        evaluation = strategy_mgr.evaluate_opportunity(opportunity, context)
        
        if evaluation and strategy_mgr.should_execute(evaluation):
            # 创建执行任务
            from services.execution_scheduler import get_execution_scheduler
            
            scheduler = get_execution_scheduler()
            task = scheduler.create_task(
                task_type="arbitrage",
                chain=opportunity.get("source_chain"),
                opportunity_id=opportunity.get("id"),
                priority="high" if evaluation.quality.value in ["excellent", "good"] else "normal",
                data={
                    "opportunity": opportunity,
                    "evaluation": evaluation,
                    "execution_amount": evaluation.recommended_amount_usd,
                }
            )
            
            scheduler.queue_task(task)
    
    async def _handle_trade_completed(self, event: SystemEvent):
        """处理交易完成事件"""
        self._stats["trades_executed"] += 1
        self._stats["trades_succeeded"] += 1
        
        data = event.data
        if data.get("profit"):
            # 记录收益
            from services.fund_manager import get_fund_manager
            fund_mgr = get_fund_manager()
            fund_mgr.record_profit(
                opportunity_id=data.get("opportunity_id"),
                chain=data.get("chain"),
                profit_usd=data.get("profit", 0),
                profit_pct=data.get("profit_pct", 0),
                gas_cost_usd=data.get("gas_cost", 0),
            )
    
    async def _handle_trade_failed(self, event: SystemEvent):
        """处理交易失败事件"""
        self._stats["trades_executed"] += 1
        self._stats["trades_failed"] += 1
        
        data = event.data
        logger.error(
            f"Trade failed: {data.get('error')}, "
            f"chain: {data.get('chain')}, "
            f"opportunity: {data.get('opportunity_id')}"
        )
    
    async def _handle_risk_alert(self, event: SystemEvent):
        """处理风险告警"""
        alert_level = event.data.get("level", "warning")
        
        if alert_level in ["critical", "emergency"]:
            logger.critical(f"Risk alert: {event.data}")
            await self.emergency_stop()
        else:
            logger.warning(f"Risk alert: {event.data}")
    
    async def _handle_emergency(self, event: SystemEvent):
        """处理紧急停止事件"""
        logger.critical("Emergency stop event received")
        await self.emergency_stop()
    
    # ============================================
    # 状态和统计
    # ============================================
    
    def get_status(self) -> Dict:
        """获取系统状态"""
        uptime = None
        if self._started_at:
            uptime = (datetime.now() - self._started_at).total_seconds()
        
        return {
            "state": self._state.value,
            "uptime_seconds": uptime,
            "started_at": self._started_at.isoformat() if self._started_at else None,
            "components": {
                comp_type.value: {
                    "state": comp.state.value,
                    "last_heartbeat": comp.last_heartbeat.isoformat() if comp.last_heartbeat else None,
                }
                for comp_type, comp in self._components.items()
            },
        }
    
    def get_detailed_status(self) -> Dict:
        """获取详细状态"""
        status = self.get_status()
        
        # 添加组件统计
        for comp_type in ComponentType:
            comp_info = self._components.get(comp_type)
            if comp_info:
                status["components"][comp_type.value]["stats"] = comp_info.stats
        
        # 添加系统统计
        status["stats"] = self._stats
        
        # 添加队列状态
        scheduler = self._components.get(ComponentType.EXECUTION_SCHEDULER)
        if scheduler:
            status["scheduler"] = scheduler.get_stats()
        
        return status
    
    def get_stats(self) -> Dict:
        """获取统计信息"""
        return {
            "system": {
                "state": self._state.value,
                "uptime": (datetime.now() - self._started_at).total_seconds() if self._started_at else 0,
            },
            "operations": self._stats,
        }
    
    def update_component_stats(self, component_type: ComponentType, stats: Dict):
        """更新组件统计"""
        comp_info = self._components.get(component_type)
        if comp_info:
            comp_info.stats.update(stats)
    
    def heartbeat(self, component_type: ComponentType):
        """心跳"""
        comp_info = self._components.get(component_type)
        if comp_info:
            comp_info.last_heartbeat = datetime.now()


# ============================================
# 单例访问函数
# ============================================

_controller: Optional[AutoController] = None


def get_auto_controller() -> AutoController:
    """获取自动控制器单例"""
    global _controller
    if _controller is None:
        _controller = AutoController()
    return _controller


async def init_auto_controller() -> AutoController:
    """初始化自动控制器"""
    controller = get_auto_controller()
    await controller.initialize()
    return controller


# ============================================
# 信号处理
# ============================================

def setup_signal_handlers():
    """设置信号处理器"""
    controller = get_auto_controller()
    
    def signal_handler(signum, frame):
        logger.info(f"Received signal {signum}")
        asyncio.create_task(controller.emergency_stop())
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
