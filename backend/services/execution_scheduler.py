"""
执行调度器 - Phase 3 全自动执行核心组件

功能：
- 任务队列管理
- 优先级排序
- 任务去重
- 并发控制
- 链级并发控制
- 资源竞争处理
- 最优执行时机
- Gas 价格监控
- 网络拥堵避让
- 自动重试
- 失败回滚
- 异常告警

设计原则：
- 高效调度：基于优先级的任务调度
- 资源保护：避免资源竞争和过载
- 可靠性：失败重试和回滚
"""

import asyncio
import logging
from typing import Dict, List, Optional, Tuple, Any, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from collections import deque
from heapq import heappush, heappop
import json
import uuid
import time

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

class TaskStatus(Enum):
    """任务状态"""
    PENDING = "pending"              # 待执行
    QUEUED = "queued"                # 已入队
    RUNNING = "running"              # 执行中
    COMPLETED = "completed"          # 已完成
    FAILED = "failed"               # 失败
    CANCELLED = "cancelled"          # 已取消
    RETRYING = "retrying"           # 重试中
    BLOCKED = "blocked"              # 被阻塞


class TaskPriority(Enum):
    """任务优先级 (数字越大优先级越高)"""
    LOW = 1
    NORMAL = 2
    HIGH = 3
    URGENT = 4
    CRITICAL = 5


class TaskType(Enum):
    """任务类型"""
    ARBITRAGE = "arbitrage"          # 套利交易
    REBALANCE = "rebalance"          # 资金再平衡
    WITHDRAW = "withdraw"            # 提款
    EMERGENCY = "emergency"          # 紧急操作
    MONITORING = "monitoring"        # 监控任务


class CongestionLevel(Enum):
    """网络拥堵等级"""
    LOW = "low"                      # 畅通
    MEDIUM = "medium"                # 一般
    HIGH = "high"                    # 拥堵
    SEVERE = "severe"                # 严重拥堵


# ============================================
# 数据类定义
# ============================================

@dataclass
class Task:
    """执行任务"""
    id: str
    task_type: TaskType
    priority: TaskPriority
    chain: str
    opportunity_id: str
    
    # 任务数据
    data: Dict = field(default_factory=dict)
    
    # 状态
    status: TaskStatus = TaskStatus.PENDING
    
    # 时间戳
    created_at: datetime = field(default_factory=datetime.now)
    scheduled_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    # 重试
    retry_count: int = 0
    max_retries: int = 3
    last_error: Optional[str] = None
    
    # 依赖
    dependencies: List[str] = field(default_factory=list)
    blocking_tasks: List[str] = field(default_factory=list)
    
    # 优先级队列比较键
    def __lt__(self, other):
        # 优先级高的先执行，相同时按创建时间早的先执行
        if self.priority.value != other.priority.value:
            return self.priority.value > other.priority.value
        return self.created_at < other.created_at


@dataclass
class GasInfo:
    """Gas 信息"""
    chain: str
    current_gwei: float
    base_fee_gwei: float
    priority_fee_gwei: float
    max_fee_gwei: float
    congestion: CongestionLevel
    estimated_time_seconds: int = 0
    
    @property
    def is_high(self) -> bool:
        """是否高 Gas"""
        return self.current_gwei > 50
    
    @property
    def is_very_high(self) -> bool:
        """是否非常高 Gas"""
        return self.current_gwei > 100


@dataclass
class SchedulerConfig:
    """调度器配置"""
    # 并发控制
    max_concurrent_tasks: int = 5
    max_concurrent_per_chain: int = 2
    
    # Gas 设置
    max_gas_price_gwei: float = 100.0
    gas_price_threshold_high: float = 50.0
    gas_price_threshold_very_high: float = 100.0
    
    # 时间控制
    task_timeout_seconds: int = 300
    queue_check_interval_seconds: int = 1
    
    # 重试配置
    retry_delay_seconds: int = 5
    max_retry_delay_seconds: int = 60
    exponential_backoff: bool = True
    
    # 拥堵避让
    congestion_avoidance_enabled: bool = True
    max_congestion_wait_seconds: int = 300
    
    # 任务限制
    max_queue_size: int = 1000
    task_expiry_seconds: int = 3600


@dataclass
class ExecutionStats:
    """执行统计"""
    total_tasks: int = 0
    completed_tasks: int = 0
    failed_tasks: int = 0
    cancelled_tasks: int = 0
    retry_tasks: int = 0
    total_execution_time: float = 0.0
    avg_execution_time: float = 0.0


# ============================================
# 链级锁
# ============================================

class ChainLock:
    """链级锁 - 防止同一链上的并发冲突"""
    
    def __init__(self):
        self._locks: Dict[str, asyncio.Lock] = {}
        self._counters: Dict[str, int] = {}
        self._max_concurrent: Dict[str, int] = {}
    
    def set_max_concurrent(self, chain: str, max_count: int):
        """设置最大并发数"""
        self._max_concurrent[chain] = max_count
        if chain not in self._locks:
            self._locks[chain] = asyncio.Lock()
            self._counters[chain] = 0
    
    def get_lock(self, chain: str) -> asyncio.Lock:
        """获取链锁"""
        if chain not in self._locks:
            self._locks[chain] = asyncio.Lock()
            self._counters[chain] = 0
        return self._locks[chain]
    
    def is_locked(self, chain: str) -> bool:
        """检查是否锁定"""
        return self._counters.get(chain, 0) >= self._max_concurrent.get(chain, 2)
    
    def acquire(self, chain: str) -> bool:
        """获取锁"""
        if chain not in self._locks:
            self._locks[chain] = asyncio.Lock()
            self._counters[chain] = 0
        
        max_count = self._max_concurrent.get(chain, 2)
        if self._counters.get(chain, 0) >= max_count:
            return False
        
        self._counters[chain] = self._counters.get(chain, 0) + 1
        return True
    
    def release(self, chain: str):
        """释放锁"""
        if chain in self._counters and self._counters[chain] > 0:
            self._counters[chain] -= 1
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


# ============================================
# 执行调度器
# ============================================

class ExecutionScheduler:
    """执行调度器"""
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not hasattr(self, "_initialized"):
            self._initialized = True
            
            # 任务队列 (优先级堆)
            self._task_queue: List[Task] = []
            
            # 任务存储
            self._tasks: Dict[str, Task] = {}
            
            # 链锁
            self._chain_lock = ChainLock()
            
            # 配置
            self._config = SchedulerConfig()
            
            # Gas 信息缓存
            self._gas_cache: Dict[str, GasInfo] = {}
            self._gas_cache_time: Dict[str, datetime] = {}
            
            # 运行状态
            self._is_running = False
            self._scheduler_task: Optional[asyncio.Task] = None
            
            # 统计数据
            self._stats = ExecutionStats()
            
            # 回调
            self._task_callbacks: Dict[str, Callable] = {}
            
            # 告警回调
            self._alert_callback: Optional[Callable] = None
    
    async def initialize(self):
        """初始化"""
        logger.info("ExecutionScheduler initialized")
        
        # 初始化链锁
        for chain in SUPPORTED_CHAINS.keys():
            self._chain_lock.set_max_concurrent(
                chain, 
                self._config.max_concurrent_per_chain
            )
    
    def set_config(self, config: SchedulerConfig):
        """设置配置"""
        self._config = config
        
        # 更新链锁
        for chain in SUPPORTED_CHAINS.keys():
            self._chain_lock.set_max_concurrent(
                chain,
                config.max_concurrent_per_chain
            )
        
        logger.info("SchedulerConfig updated")
    
    def get_config(self) -> SchedulerConfig:
        """获取配置"""
        return self._config
    
    # ============================================
    # 任务管理
    # ============================================
    
    def create_task(
        self,
        task_type: TaskType,
        chain: str,
        opportunity_id: str,
        priority: TaskPriority = TaskPriority.NORMAL,
        data: Dict = None,
        dependencies: List[str] = None,
        max_retries: int = None
    ) -> Task:
        """创建任务"""
        task_id = str(uuid.uuid4())[:8]
        
        task = Task(
            id=task_id,
            task_type=task_type,
            priority=priority,
            chain=chain,
            opportunity_id=opportunity_id,
            data=data or {},
            dependencies=dependencies or [],
            max_retries=max_retries or self._config.max_retries,
        )
        
        self._tasks[task_id] = task
        self._stats.total_tasks += 1
        
        logger.debug(f"Created task {task_id}: {task_type.value} on {chain}")
        
        return task
    
    def queue_task(self, task: Task) -> bool:
        """将任务加入队列"""
        if len(self._task_queue) >= self._config.max_queue_size:
            logger.warning("Task queue is full")
            return False
        
        # 检查是否已存在
        for existing_task in self._task_queue:
            if existing_task.opportunity_id == task.opportunity_id:
                logger.info(f"Task already in queue for opportunity {task.opportunity_id}")
                return False
        
        # 检查依赖
        for dep_id in task.dependencies:
            dep_task = self._tasks.get(dep_id)
            if dep_task and dep_task.status not in [TaskStatus.COMPLETED, TaskStatus.FAILED]:
                task.status = TaskStatus.BLOCKED
                dep_task.blocking_tasks.append(task.id)
                logger.debug(f"Task {task.id} blocked by dependency {dep_id}")
                return False
        
        task.status = TaskStatus.QUEUED
        heappush(self._task_queue, task)
        
        logger.info(
            f"Task {task.id} queued: {task.task_type.value}, "
            f"priority={task.priority.value}, chain={task.chain}"
        )
        
        return True
    
    def cancel_task(self, task_id: str) -> bool:
        """取消任务"""
        task = self._tasks.get(task_id)
        if not task:
            return False
        
        if task.status in [TaskStatus.RUNNING, TaskStatus.COMPLETED]:
            return False
        
        task.status = TaskStatus.CANCELLED
        self._stats.cancelled_tasks += 1
        
        # 从队列中移除
        self._task_queue = [t for t in self._task_queue if t.id != task_id]
        
        logger.info(f"Task {task_id} cancelled")
        return True
    
    def get_task(self, task_id: str) -> Optional[Task]:
        """获取任务"""
        return self._tasks.get(task_id)
    
    def get_pending_tasks(self) -> List[Task]:
        """获取待执行任务"""
        return [t for t in self._tasks.values() if t.status == TaskStatus.PENDING]
    
    def get_running_tasks(self) -> List[Task]:
        """获取运行中任务"""
        return [t for t in self._tasks.values() if t.status == TaskStatus.RUNNING]
    
    def get_queue_size(self) -> int:
        """获取队列大小"""
        return len(self._task_queue)
    
    # ============================================
    # Gas 价格管理
    # ============================================
    
    async def update_gas_info(self, chain: str, gas_info: GasInfo):
        """更新 Gas 信息"""
        self._gas_cache[chain] = gas_info
        self._gas_cache_time[chain] = datetime.now()
        
        # 缓存有效期 30 秒
        cache_valid_seconds = 30
    
    async def get_gas_info(self, chain: str) -> Optional[GasInfo]:
        """获取 Gas 信息"""
        if chain not in self._gas_cache:
            return None
        
        # 检查缓存过期
        cache_time = self._gas_cache_time.get(chain)
        if cache_time and (datetime.now() - cache_time).seconds > 30:
            return None
        
        return self._gas_cache.get(chain)
    
    def should_delay_due_to_gas(self, chain: str) -> Tuple[bool, int]:
        """检查是否应该因 Gas 延迟
        
        返回: (是否延迟, 建议延迟秒数)
        """
        gas_info = self._gas_cache.get(chain)
        if not gas_info:
            return False, 0
        
        config = self._config
        
        if gas_info.is_very_high:
            return True, min(config.max_congestion_wait_seconds, 120)
        
        if gas_info.is_high:
            return True, 30
        
        if gas_info.congestion == CongestionLevel.HIGH:
            return True, 60
        
        return False, 0
    
    # ============================================
    # 调度执行
    # ============================================
    
    async def start(self):
        """启动调度器"""
        if self._is_running:
            return
        
        self._is_running = True
        self._scheduler_task = asyncio.create_task(self._scheduler_loop())
        
        logger.info("ExecutionScheduler started")
    
    async def stop(self):
        """停止调度器"""
        self._is_running = False
        
        if self._scheduler_task:
            self._scheduler_task.cancel()
            try:
                await self._scheduler_task
            except asyncio.CancelledError:
                pass
        
        logger.info("ExecutionScheduler stopped")
    
    async def _scheduler_loop(self):
        """调度循环"""
        while self._is_running:
            try:
                await self._process_queue()
                await asyncio.sleep(self._config.queue_check_interval_seconds)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Scheduler loop error: {e}")
                await asyncio.sleep(1)
    
    async def _process_queue(self):
        """处理队列"""
        while self._task_queue and self._is_running:
            # 检查全局并发限制
            running_count = len(self.get_running_tasks())
            if running_count >= self._config.max_concurrent_tasks:
                break
            
            # 获取最高优先级任务
            task = heappop(self._task_queue)
            
            # 检查任务状态
            if task.status == TaskStatus.CANCELLED:
                continue
            
            # 检查是否过期
            if task.created_at < datetime.now() - timedelta(seconds=self._config.task_expiry_seconds):
                task.status = TaskStatus.CANCELLED
                self._stats.cancelled_tasks += 1
                logger.info(f"Task {task.id} expired")
                continue
            
            # 检查 Gas 条件
            should_delay, delay_seconds = self.should_delay_due_to_gas(task.chain)
            if should_delay:
                # 重新放回队列，稍后处理
                task.status = TaskStatus.PENDING
                heappush(self._task_queue, task)
                await asyncio.sleep(delay_seconds)
                continue
            
            # 检查链锁
            if self._chain_lock.is_locked(task.chain):
                # 等待链锁释放
                await asyncio.sleep(1)
                heappush(self._task_queue, task)
                continue
            
            # 执行任务
            await self._execute_task(task)
    
    async def _execute_task(self, task: Task):
        """执行任务"""
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.now()
        
        # 获取链锁
        if not self._chain_lock.acquire(task.chain):
            task.status = TaskStatus.QUEUED
            heappush(self._task_queue, task)
            return
        
        logger.info(f"Executing task {task.id}: {task.task_type.value} on {task.chain}")
        
        start_time = time.time()
        
        try:
            # 调用任务回调
            callback = self._task_callbacks.get(task.task_type.value)
            if callback:
                result = await callback(task)
                
                if result.get("success"):
                    task.status = TaskStatus.COMPLETED
                    task.completed_at = datetime.now()
                    self._stats.completed_tasks += 1
                    logger.info(f"Task {task.id} completed successfully")
                else:
                    raise Exception(result.get("error", "Unknown error"))
            else:
                raise Exception(f"No callback for task type {task.task_type.value}")
        
        except asyncio.CancelledError:
            task.status = TaskStatus.CANCELLED
            self._stats.cancelled_tasks += 1
            raise
        
        except Exception as e:
            error_msg = str(e)
            task.last_error = error_msg
            self._handle_task_failure(task)
        
        finally:
            # 释放链锁
            self._chain_lock.release(task.chain)
            
            # 更新执行时间
            execution_time = time.time() - start_time
            self._stats.total_execution_time += execution_time
            if self._stats.completed_tasks > 0:
                self._stats.avg_execution_time = (
                    self._stats.total_execution_time / self._stats.completed_tasks
                )
    
    def _handle_task_failure(self, task: Task):
        """处理任务失败"""
        task.retry_count += 1
        self._stats.retry_tasks += 1
        
        if task.retry_count < task.max_retries:
            # 重试
            task.status = TaskStatus.RETRYING
            
            # 计算延迟
            delay = self._calculate_retry_delay(task.retry_count)
            
            logger.warning(
                f"Task {task.id} failed (attempt {task.retry_count}/{task.max_retries}), "
                f"retrying in {delay}s: {task.last_error}"
            )
            
            # 重新入队
            asyncio.create_task(self._schedule_retry(task, delay))
        else:
            # 最终失败
            task.status = TaskStatus.FAILED
            self._stats.failed_tasks += 1
            
            logger.error(
                f"Task {task.id} permanently failed after {task.retry_count} attempts: "
                f"{task.last_error}"
            )
            
            # 触发告警
            if self._alert_callback:
                asyncio.create_task(self._alert_callback({
                    "type": "task_failed",
                    "task_id": task.id,
                    "error": task.last_error,
                    "chain": task.chain,
                    "opportunity_id": task.opportunity_id,
                }))
    
    def _calculate_retry_delay(self, retry_count: int) -> int:
        """计算重试延迟"""
        if self._config.exponential_backoff:
            delay = self._config.retry_delay_seconds * (2 ** (retry_count - 1))
        else:
            delay = self._config.retry_delay_seconds
        
        return min(delay, self._config.max_retry_delay_seconds)
    
    async def _schedule_retry(self, task: Task, delay: int):
        """调度重试"""
        await asyncio.sleep(delay)
        
        if task.status == TaskStatus.RETRYING:
            task.status = TaskStatus.QUEUED
            heappush(self._task_queue, task)
    
    # ============================================
    # 回调管理
    # ============================================
    
    def register_callback(self, task_type: str, callback: Callable):
        """注册任务回调"""
        self._task_callbacks[task_type] = callback
        logger.info(f"Registered callback for task type: {task_type}")
    
    def set_alert_callback(self, callback: Callable):
        """设置告警回调"""
        self._alert_callback = callback
    
    # ============================================
    # 统计和状态
    # ============================================
    
    def get_stats(self) -> Dict:
        """获取统计"""
        return {
            "total_tasks": self._stats.total_tasks,
            "completed": self._stats.completed_tasks,
            "failed": self._stats.failed_tasks,
            "cancelled": self._stats.cancelled_tasks,
            "retry_tasks": self._stats.retry_tasks,
            "running": len(self.get_running_tasks()),
            "queued": self.get_queue_size(),
            "avg_execution_time": f"{self._stats.avg_execution_time:.2f}s",
        }
    
    def get_queue_summary(self) -> List[Dict]:
        """获取队列摘要"""
        return [
            {
                "id": t.id,
                "type": t.task_type.value,
                "priority": t.priority.value,
                "chain": t.chain,
                "status": t.status.value,
                "created_at": t.created_at.isoformat(),
                "retry_count": t.retry_count,
            }
            for t in sorted(self._task_queue)
        ]
    
    def get_chain_status(self) -> Dict[str, Dict]:
        """获取各链状态"""
        status = {}
        
        for chain in SUPPORTED_CHAINS.keys():
            running_tasks = [t for t in self.get_running_tasks() if t.chain == chain]
            
            status[chain] = {
                "running": len(running_tasks),
                "locked": self._chain_lock.is_locked(chain),
                "gas": self._gas_cache.get(chain).__dict__ if self._gas_cache.get(chain) else None,
            }
        
        return status
    
    async def force_cleanup(self):
        """强制清理"""
        # 取消所有待处理任务
        for task in self._task_queue[:]:
            task.status = TaskStatus.CANCELLED
            self._stats.cancelled_tasks += 1
        
        self._task_queue.clear()
        
        logger.info("Scheduler force cleanup completed")


# ============================================
# 单例访问函数
# ============================================

_scheduler: Optional[ExecutionScheduler] = None


def get_execution_scheduler() -> ExecutionScheduler:
    """获取执行调度器单例"""
    global _scheduler
    if _scheduler is None:
        _scheduler = ExecutionScheduler()
    return _scheduler


async def init_execution_scheduler() -> ExecutionScheduler:
    """初始化执行调度器"""
    scheduler = get_execution_scheduler()
    await scheduler.initialize()
    return scheduler
