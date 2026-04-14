"""
API 路由 - Phase 3 自动化执行核心组件

路由列表：
- POST /api/automation/start - 启动自动执行
- POST /api/automation/stop - 停止自动执行
- POST /api/automation/pause - 暂停自动执行
- POST /api/automation/resume - 恢复自动执行
- GET /api/automation/status - 获取执行状态
- GET /api/automation/stats - 获取统计信息
- POST /api/automation/config - 配置执行参数
- GET /api/automation/history - 获取执行历史
- GET /api/funds/balance - 获取各链资金
- POST /api/funds/rebalance - 资金再平衡
- GET /api/strategy/list - 获取策略列表
- POST /api/strategy/switch - 切换策略
- POST /api/strategy/config - 配置策略参数
- GET /api/scheduler/queue - 获取任务队列
- GET /api/health - 健康检查
"""

import os
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime
from enum import Enum

from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks, Query, Body
from pydantic import BaseModel, Field
from fastapi.responses import JSONResponse

import sys
import os as _os
_backend_dir = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _os.path.dirname(_backend_dir) not in sys.path:
    sys.path.insert(0, _os.path.dirname(_backend_dir))


logger = logging.getLogger(__name__)


# ============================================
# 路由实例
# ============================================

router = APIRouter(prefix="/api", tags=["automation"])


# ============================================
# Pydantic 模型定义
# ============================================

class StartAutomationRequest(BaseModel):
    """启动自动化请求"""
    strategy: Optional[str] = Field(None, description="策略名称 (conservative/balanced/aggressive)")
    monitor_only: bool = Field(False, description="仅监控模式，不自动执行")


class StopAutomationRequest(BaseModel):
    """停止自动化请求"""
    emergency: bool = Field(False, description="紧急停止")


class StrategySwitchRequest(BaseModel):
    """策略切换请求"""
    strategy: str = Field(..., description="策略名称")


class StrategyConfigRequest(BaseModel):
    """策略配置请求"""
    strategy: str = Field(..., description="策略名称")
    parameters: Dict[str, Any] = Field(..., description="策略参数")


class RebalanceRequest(BaseModel):
    """资金再平衡请求"""
    mode: str = Field("manual", description="再平衡模式 (manual/time_based/threshold_based)")


class TaskCancelRequest(BaseModel):
    """取消任务请求"""
    task_id: str = Field(..., description="任务ID")


class AutomationConfigRequest(BaseModel):
    """自动化配置请求"""
    max_concurrent_tasks: Optional[int] = Field(None, ge=1, le=20)
    max_gas_price_gwei: Optional[float] = Field(None, gt=0)
    auto_retry: Optional[bool] = None
    max_retries: Optional[int] = Field(None, ge=0, le=10)


# ============================================
# 自动化控制路由
# ============================================

@router.post("/automation/start")
async def start_automation(request: StartAutomationRequest = None):
    """启动自动执行"""
    try:
        from services.auto_controller import get_auto_controller
        
        controller = get_auto_controller()
        
        if controller.state.value in ["running", "starting"]:
            return JSONResponse({
                "success": False,
                "message": "System already running"
            })
        
        # 切换策略
        if request and request.strategy:
            from services.auto_strategy import get_strategy_manager
            strategy_mgr = get_strategy_manager()
            strategy_mgr.switch_strategy(request.strategy)
        
        # 启动系统
        success = await controller.start()
        
        if success:
            return JSONResponse({
                "success": True,
                "message": "Automation started successfully",
                "status": controller.get_status()
            })
        else:
            return JSONResponse({
                "success": False,
                "message": "Failed to start automation"
            })
            
    except Exception as e:
        logger.error(f"Start automation error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/automation/stop")
async def stop_automation(request: StopAutomationRequest):
    """停止自动执行"""
    try:
        from services.auto_controller import get_auto_controller
        
        controller = get_auto_controller()
        
        await controller.stop(emergency=request.emergency)
        
        return JSONResponse({
            "success": True,
            "message": "Automation stopped" + (" (emergency)" if request.emergency else ""),
            "status": controller.get_status()
        })
        
    except Exception as e:
        logger.error(f"Stop automation error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/automation/pause")
async def pause_automation():
    """暂停自动执行"""
    try:
        from services.auto_controller import get_auto_controller
        
        controller = get_auto_controller()
        success = await controller.pause()
        
        return JSONResponse({
            "success": success,
            "message": "Automation paused" if success else "Cannot pause",
            "status": controller.get_status()
        })
        
    except Exception as e:
        logger.error(f"Pause automation error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/automation/resume")
async def resume_automation():
    """恢复自动执行"""
    try:
        from services.auto_controller import get_auto_controller
        
        controller = get_auto_controller()
        success = await controller.resume()
        
        return JSONResponse({
            "success": success,
            "message": "Automation resumed" if success else "Cannot resume",
            "status": controller.get_status()
        })
        
    except Exception as e:
        logger.error(f"Resume automation error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/automation/status")
async def get_automation_status():
    """获取自动化状态"""
    try:
        from services.auto_controller import get_auto_controller
        
        controller = get_auto_controller()
        status = controller.get_detailed_status()
        
        return JSONResponse({
            "success": True,
            "data": status
        })
        
    except Exception as e:
        logger.error(f"Get status error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/automation/stats")
async def get_automation_stats():
    """获取统计信息"""
    try:
        from services.auto_controller import get_auto_controller
        from services.auto_strategy import get_strategy_manager
        from services.fund_manager import get_fund_manager
        from services.execution_scheduler import get_execution_scheduler
        
        controller = get_auto_controller()
        strategy_mgr = get_strategy_manager()
        fund_mgr = get_fund_manager()
        scheduler = get_execution_scheduler()
        
        stats = {
            "system": controller.get_stats(),
            "strategy": strategy_mgr.get_performance_summary(),
            "funds": fund_mgr.get_status_summary(),
            "scheduler": scheduler.get_stats(),
        }
        
        return JSONResponse({
            "success": True,
            "data": stats
        })
        
    except Exception as e:
        logger.error(f"Get stats error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/automation/config")
async def configure_automation(request: AutomationConfigRequest):
    """配置自动化参数"""
    try:
        from services.execution_scheduler import get_execution_scheduler
        from services.execution_scheduler import SchedulerConfig
        
        scheduler = get_execution_scheduler()
        config = scheduler.get_config()
        
        # 更新配置
        if request.max_concurrent_tasks is not None:
            config.max_concurrent_tasks = request.max_concurrent_tasks
        if request.max_gas_price_gwei is not None:
            config.max_gas_price_gwei = request.max_gas_price_gwei
        if request.auto_retry is not None:
            config.exponential_backoff = request.auto_retry
        if request.max_retries is not None:
            config.retry_delay_seconds = request.max_retries
        
        scheduler.set_config(config)
        
        return JSONResponse({
            "success": True,
            "message": "Configuration updated",
            "config": {
                "max_concurrent_tasks": config.max_concurrent_tasks,
                "max_gas_price_gwei": config.max_gas_price_gwei,
                "exponential_backoff": config.exponential_backoff,
            }
        })
        
    except Exception as e:
        logger.error(f"Configure error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/automation/history")
async def get_execution_history(
    limit: int = Query(100, ge=1, le=1000),
    chain: str = Query(None, description="按链过滤"),
    start_date: str = Query(None, description="开始日期 ISO格式"),
    end_date: str = Query(None, description="结束日期 ISO格式"),
):
    """获取执行历史"""
    try:
        from services.fund_manager import get_fund_manager
        
        fund_mgr = get_fund_manager()
        
        # 解析日期
        start = datetime.fromisoformat(start_date) if start_date else None
        end = datetime.fromisoformat(end_date) if end_date else None
        
        records = fund_mgr.get_profit_records(
            limit=limit,
            chain=chain,
            start_date=start,
            end_date=end,
        )
        
        return JSONResponse({
            "success": True,
            "count": len(records),
            "data": [
                {
                    "id": r.id,
                    "opportunity_id": r.opportunity_id,
                    "chain": r.chain,
                    "profit_usd": r.profit_usd,
                    "profit_pct": r.profit_pct,
                    "gas_cost_usd": r.gas_cost_usd,
                    "net_profit_usd": r.net_profit_usd,
                    "execution_mode": r.execution_mode,
                    "executed_at": r.executed_at.isoformat(),
                }
                for r in records
            ]
        })
        
    except Exception as e:
        logger.error(f"Get history error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# 资金管理路由
# ============================================

@router.get("/funds/balance")
async def get_fund_balance():
    """获取各链资金"""
    try:
        from services.fund_manager import get_fund_manager
        
        fund_mgr = get_fund_manager()
        balance = fund_mgr.get_detailed_balance()
        
        return JSONResponse({
            "success": True,
            "data": balance
        })
        
    except Exception as e:
        logger.error(f"Get balance error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/funds/rebalance")
async def rebalance_funds(request: RebalanceRequest):
    """资金再平衡"""
    try:
        from services.fund_manager import get_fund_manager, RebalanceTrigger
        
        fund_mgr = get_fund_manager()
        
        trigger_map = {
            "manual": RebalanceTrigger.MANUAL,
            "time_based": RebalanceTrigger.TIME_BASED,
            "threshold_based": RebalanceTrigger.THRESHOLD_BASED,
        }
        
        trigger = trigger_map.get(request.mode, RebalanceTrigger.MANUAL)
        result = await fund_mgr.rebalance_funds(trigger=trigger)
        
        return JSONResponse({
            "success": True,
            "message": f"Rebalance initiated ({request.mode})",
            "data": result
        })
        
    except Exception as e:
        logger.error(f"Rebalance error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/funds/snapshot")
async def get_fund_snapshot():
    """获取资金快照"""
    try:
        from services.fund_manager import get_fund_manager
        
        fund_mgr = get_fund_manager()
        snapshot = fund_mgr.create_snapshot()
        
        return JSONResponse({
            "success": True,
            "data": {
                "timestamp": snapshot.timestamp.isoformat(),
                "total_balance_usd": snapshot.total_balance_usd,
                "chain_balances": snapshot.chain_balances,
                "daily_pnl_usd": snapshot.daily_pnl_usd,
                "total_pnl_usd": snapshot.total_pnl_usd,
                "frozen_usd": snapshot.frozen_usd,
                "locked_usd": snapshot.locked_usd,
                "positions_count": len(snapshot.positions),
            }
        })
        
    except Exception as e:
        logger.error(f"Get snapshot error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# 策略管理路由
# ============================================

@router.get("/strategy/list")
async def list_strategies():
    """获取策略列表"""
    try:
        from services.auto_strategy import get_strategy_manager
        
        strategy_mgr = get_strategy_manager()
        strategies = strategy_mgr.list_strategies()
        
        return JSONResponse({
            "success": True,
            "data": strategies
        })
        
    except Exception as e:
        logger.error(f"List strategies error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/strategy/switch")
async def switch_strategy(request: StrategySwitchRequest):
    """切换策略"""
    try:
        from services.auto_strategy import get_strategy_manager
        
        strategy_mgr = get_strategy_manager()
        success = strategy_mgr.switch_strategy(request.strategy)
        
        if success:
            active = strategy_mgr.get_active_strategy()
            return JSONResponse({
                "success": True,
                "message": f"Switched to {request.strategy}",
                "active_strategy": active.name if active else None,
            })
        else:
            raise HTTPException(status_code=400, detail=f"Strategy not found: {request.strategy}")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Switch strategy error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/strategy/config")
async def configure_strategy(request: StrategyConfigRequest):
    """配置策略参数"""
    try:
        from services.auto_strategy import get_strategy_manager, StrategyParameters
        
        strategy_mgr = get_strategy_manager()
        strategy = strategy_mgr.get_strategy(request.strategy)
        
        if not strategy:
            raise HTTPException(status_code=404, detail=f"Strategy not found: {request.strategy}")
        
        # 更新参数
        params = strategy.get_parameters()
        for key, value in request.parameters.items():
            if hasattr(params, key):
                setattr(params, key, value)
        
        strategy.update_parameters(params)
        
        return JSONResponse({
            "success": True,
            "message": f"Strategy {request.strategy} configured",
            "parameters": {
                "min_profit_threshold_usd": params.min_profit_threshold_usd,
                "max_risk_score": params.max_risk_score,
                "max_single_trade_usd": params.max_single_trade_usd,
                "max_daily_trades": params.max_daily_trades,
            }
        })
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Configure strategy error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/strategy/backtest")
async def backtest_strategy(
    strategy: str = Query(..., description="策略名称"),
    days: int = Query(30, ge=1, le=365, description="回测天数"),
):
    """策略回测"""
    try:
        from services.auto_strategy import get_strategy_manager
        
        strategy_mgr = get_strategy_manager()
        
        # 生成模拟历史数据
        import random
        historical_data = []
        for i in range(days * 24):  # 每小时一个数据点
            historical_data.append({
                "id": f"opp_{i}",
                "profit_usd": random.uniform(5, 50),
                "profit_pct": random.uniform(0.3, 3.0),
                "confidence": random.uniform(0.5, 0.9),
                "chain": random.choice(["ethereum", "arbitrum", "polygon"]),
                "gas_price": random.uniform(20, 80),
                "liquidity": random.uniform(100000, 1000000),
                "timestamp": datetime.now() - timedelta(hours=i),
            })
        
        result = strategy_mgr.run_backtest(
            strategy_name=strategy,
            historical_data=historical_data,
            initial_balance=10000.0,
        )
        
        if not result:
            raise HTTPException(status_code=404, detail=f"Strategy not found: {strategy}")
        
        return JSONResponse({
            "success": True,
            "data": {
                "strategy_name": result.strategy_name,
                "period_days": days,
                "total_trades": result.total_trades,
                "successful_trades": result.successful_trades,
                "failed_trades": result.failed_trades,
                "net_profit_usd": result.net_profit_usd,
                "win_rate": f"{result.win_rate:.1%}",
                "max_drawdown_usd": result.max_drawdown_usd,
                "sharpe_ratio": f"{result.sharpe_ratio:.2f}",
            }
        })
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Backtest error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/strategy/daily-stats")
async def get_daily_stats():
    """获取每日统计"""
    try:
        from services.auto_strategy import get_strategy_manager
        
        strategy_mgr = get_strategy_manager()
        stats = strategy_mgr.get_daily_stats()
        
        return JSONResponse({
            "success": True,
            "data": stats
        })
        
    except Exception as e:
        logger.error(f"Get daily stats error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# 任务调度路由
# ============================================

@router.get("/scheduler/queue")
async def get_task_queue(
    limit: int = Query(50, ge=1, le=200),
):
    """获取任务队列"""
    try:
        from services.execution_scheduler import get_execution_scheduler
        
        scheduler = get_execution_scheduler()
        queue = scheduler.get_queue_summary()[:limit]
        
        return JSONResponse({
            "success": True,
            "queue_size": scheduler.get_queue_size(),
            "data": queue
        })
        
    except Exception as e:
        logger.error(f"Get queue error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/scheduler/status")
async def get_scheduler_status():
    """获取调度器状态"""
    try:
        from services.execution_scheduler import get_execution_scheduler
        
        scheduler = get_execution_scheduler()
        stats = scheduler.get_stats()
        chain_status = scheduler.get_chain_status()
        
        return JSONResponse({
            "success": True,
            "data": {
                "stats": stats,
                "chain_status": chain_status,
            }
        })
        
    except Exception as e:
        logger.error(f"Get scheduler status error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/scheduler/cancel")
async def cancel_task(request: TaskCancelRequest):
    """取消任务"""
    try:
        from services.execution_scheduler import get_execution_scheduler
        
        scheduler = get_execution_scheduler()
        success = scheduler.cancel_task(request.task_id)
        
        return JSONResponse({
            "success": success,
            "message": f"Task {request.task_id} cancelled" if success else "Task not found or cannot be cancelled",
        })
        
    except Exception as e:
        logger.error(f"Cancel task error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# 闪电贷路由
# ============================================

@router.get("/flash-loan/quotes")
async def get_flash_loan_quotes(
    token: str = Query(..., description="代币符号"),
    amount: float = Query(..., gt=0, description="金额"),
    chain: str = Query("ethereum", description="链名称"),
):
    """获取闪电贷报价"""
    try:
        from services.flash_loan_manager import get_flash_loan_manager
        
        manager = get_flash_loan_manager()
        quotes = await manager.get_quotes(token, amount, chain)
        
        return JSONResponse({
            "success": True,
            "data": [
                {
                    "source": q.source.value,
                    "fee": q.fee,
                    "fee_pct": q.fee_pct,
                    "gas_estimate": q.gas_estimate,
                    "total_cost": q.total_cost,
                    "available": q.available,
                }
                for q in quotes
            ]
        })
        
    except Exception as e:
        logger.error(f"Get quotes error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/flash-loan/stats")
async def get_flash_loan_stats():
    """获取闪电贷统计"""
    try:
        from services.flash_loan_manager import get_flash_loan_manager
        
        manager = get_flash_loan_manager()
        stats = manager.get_stats()
        history = manager.get_history(limit=20)
        
        return JSONResponse({
            "success": True,
            "data": {
                "stats": stats,
                "recent": history,
            }
        })
        
    except Exception as e:
        logger.error(f"Get flash loan stats error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/flash-loan/supported")
async def get_supported_flash_loans():
    """获取支持的闪电贷来源"""
    try:
        from services.flash_loan_manager import get_flash_loan_manager
        
        manager = get_flash_loan_manager()
        supported = manager.get_supported_chains()
        
        return JSONResponse({
            "success": True,
            "data": supported
        })
        
    except Exception as e:
        logger.error(f"Get supported flash loans error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# 监控路由
# ============================================

@router.get("/monitor/status")
async def get_monitor_status():
    """获取监控状态"""
    try:
        from services.monitor_v2 import get_monitor_v2
        
        monitor = get_monitor_v2()
        status = monitor.get_status()
        stats = monitor.get_stats()
        
        return JSONResponse({
            "success": True,
            "data": {
                "status": status,
                "stats": stats,
            }
        })
        
    except Exception as e:
        logger.error(f"Get monitor status error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# 健康检查路由
# ============================================

@router.get("/health")
async def health_check():
    """健康检查"""
    try:
        from services.auto_controller import get_auto_controller
        
        controller = get_auto_controller()
        status = controller.get_status()
        
        components_healthy = all(
            comp.get("state") in ["ready", "running"]
            for comp in status.get("components", {}).values()
        )
        
        is_healthy = (
            status.get("state") == "running" and
            components_healthy
        )
        
        return JSONResponse({
            "success": True,
            "healthy": is_healthy,
            "state": status.get("state"),
            "components": status.get("components", {}),
        })
        
    except Exception as e:
        logger.error(f"Health check error: {e}")
        return JSONResponse({
            "success": False,
            "healthy": False,
            "error": str(e),
        })


# ============================================
# 紧急停止路由
# ============================================

@router.post("/emergency/stop")
async def emergency_stop(
    reason: str = Body(..., embed=True, description="停止原因"),
):
    """紧急停止"""
    try:
        from services.auto_controller import get_auto_controller
        
        controller = get_auto_controller()
        
        logger.critical(f"Emergency stop triggered: {reason}")
        
        await controller.emergency_stop()
        
        return JSONResponse({
            "success": True,
            "message": "Emergency stop executed",
            "reason": reason,
        })
        
    except Exception as e:
        logger.error(f"Emergency stop error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
