"""
Phase 3 测试脚本

测试全自动执行引擎的所有组件
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ============================================
# 测试策略引擎
# ============================================

async def test_strategy_engine():
    """测试策略引擎"""
    logger.info("=" * 50)
    logger.info("Testing Strategy Engine")
    logger.info("=" * 50)
    
    try:
        from services.auto_strategy import (
            get_strategy_manager,
            StrategyType,
            OpportunityQuality,
            ExecutionDecision,
        )
        
        manager = get_strategy_manager()
        await manager.initialize()
        
        # 测试列出策略
        strategies = manager.list_strategies()
        logger.info(f"Found {len(strategies)} strategies")
        for s in strategies:
            logger.info(f"  - {s['name']}: {s['state']}")
        
        # 测试切换策略
        success = manager.switch_strategy("conservative")
        logger.info(f"Switched to conservative: {success}")
        
        active = manager.get_active_strategy()
        logger.info(f"Active strategy: {active.name if active else None}")
        
        # 测试评估机会
        opportunity = {
            "id": "test_opp_1",
            "symbol": "ETH",
            "source_chain": "ethereum",
            "target_chain": "arbitrum",
            "estimated_profit_usd": 50.0,
            "estimated_profit_pct": 2.5,
            "confidence": 0.85,
            "liquidity": 100000,
        }
        
        context = {
            "gas_price_gwei": 30,
            "available_balance": 10000,
        }
        
        evaluation = manager.evaluate_opportunity(opportunity, context)
        
        if evaluation:
            logger.info(f"Evaluation result:")
            logger.info(f"  Quality: {evaluation.quality.value}")
            logger.info(f"  Risk: {evaluation.risk_score:.2f}")
            logger.info(f"  Decision: {evaluation.execution_decision.value}")
            logger.info(f"  Recommended amount: ${evaluation.recommended_amount_usd:.2f}")
        
        # 测试每日限制
        can_trade = manager.check_daily_limits()
        logger.info(f"Can trade (daily limits): {can_trade}")
        
        # 测试回测
        import random
        historical_data = []
        for i in range(24 * 7):  # 7天数据
            historical_data.append({
                "id": f"opp_{i}",
                "profit_usd": random.uniform(5, 100),
                "profit_pct": random.uniform(0.3, 5.0),
                "confidence": random.uniform(0.5, 0.95),
                "chain": random.choice(["ethereum", "arbitrum", "polygon"]),
                "gas_price": random.uniform(20, 80),
                "liquidity": random.uniform(50000, 500000),
            })
        
        backtest_result = manager.run_backtest(
            strategy_name="balanced",
            historical_data=historical_data,
            initial_balance=10000.0,
        )
        
        if backtest_result:
            logger.info(f"Backtest result:")
            logger.info(f"  Total trades: {backtest_result.total_trades}")
            logger.info(f"  Win rate: {backtest_result.win_rate:.1%}")
            logger.info(f"  Net profit: ${backtest_result.net_profit_usd:.2f}")
            logger.info(f"  Max drawdown: ${backtest_result.max_drawdown_usd:.2f}")
        
        logger.info("Strategy engine test PASSED")
        return True
        
    except Exception as e:
        logger.error(f"Strategy engine test FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


# ============================================
# 测试资金管理
# ============================================

async def test_fund_manager():
    """测试资金管理"""
    logger.info("=" * 50)
    logger.info("Testing Fund Manager")
    logger.info("=" * 50)
    
    try:
        from services.fund_manager import (
            get_fund_manager,
            FundAllocation,
            RebalanceTrigger,
        )
        
        manager = get_fund_manager()
        await manager.initialize()
        
        # 测试注册链
        manager.register_chain("ethereum", "0x1234...", 5000.0)
        manager.register_chain("arbitrum", "0x5678...", 3000.0)
        manager.register_chain("polygon", "0xabcd...", 2000.0)
        
        # 测试更新余额
        manager.update_chain_balance("ethereum", native_balance=5500.0)
        
        # 测试获取余额
        total = manager.get_total_balance()
        logger.info(f"Total balance: ${total:.2f}")
        
        # 测试资金分配
        allocation = FundAllocation(
            chain="ethereum",
            allocation_pct=0.4,
            min_balance_usd=100.0,
            max_balance_usd=10000.0,
            target_balance_usd=4000.0,
        )
        manager.set_allocation(allocation)
        
        # 测试检查再平衡
        rebalance_needed = manager.check_rebalance_needed()
        logger.info(f"Rebalance needed: {len(rebalance_needed)} chains")
        
        # 测试仓位管理
        position = manager.open_position(
            chain="ethereum",
            token="ETH",
            amount=1.0,
            price=2000.0,
        )
        
        if position:
            logger.info(f"Opened position: {position.amount} {position.token}")
            
            # 平仓
            pnl = manager.close_position(
                f"{position.chain}_{position.token}_{position.opened_at.strftime('%Y%m%d%H%M%S')}",
                current_price=2100.0,
            )
            logger.info(f"Position PnL: ${pnl:.2f}")
        
        # 测试交易检查
        allowed, reason = manager.check_trade_allowed("ethereum", 1000.0)
        logger.info(f"Trade allowed: {allowed} - {reason}")
        
        # 测试回撤信息
        drawdown = manager.get_drawdown_info()
        logger.info(f"Drawdown: {drawdown['drawdown_pct']:.2f}%")
        
        # 测试状态摘要
        status = manager.get_status_summary()
        logger.info(f"Status summary: {status}")
        
        logger.info("Fund manager test PASSED")
        return True
        
    except Exception as e:
        logger.error(f"Fund manager test FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


# ============================================
# 测试执行调度器
# ============================================

async def test_execution_scheduler():
    """测试执行调度器"""
    logger.info("=" * 50)
    logger.info("Testing Execution Scheduler")
    logger.info("=" * 50)
    
    try:
        from services.execution_scheduler import (
            get_execution_scheduler,
            TaskType,
            TaskPriority,
        )
        
        scheduler = get_execution_scheduler()
        await scheduler.initialize()
        
        # 测试创建任务
        async def dummy_callback(task):
            logger.info(f"Executing task {task.id}")
            await asyncio.sleep(0.1)
            return {"success": True}
        
        scheduler.register_callback("arbitrage", dummy_callback)
        
        # 创建多个任务
        tasks = []
        for i in range(5):
            task = scheduler.create_task(
                task_type=TaskType.ARBITRAGE.value,
                chain="ethereum",
                opportunity_id=f"opp_{i}",
                priority=TaskPriority.NORMAL,
                data={"index": i},
            )
            tasks.append(task)
            logger.info(f"Created task {task.id}: priority={task.priority.value}")
        
        # 入队
        for task in tasks[:3]:
            scheduler.queue_task(task)
        
        logger.info(f"Queue size: {scheduler.get_queue_size()}")
        
        # 测试统计
        stats = scheduler.get_stats()
        logger.info(f"Stats: {stats}")
        
        # 测试链状态
        chain_status = scheduler.get_chain_status()
        logger.info(f"Chain status: {len(chain_status)} chains")
        
        logger.info("Execution scheduler test PASSED")
        return True
        
    except Exception as e:
        logger.error(f"Execution scheduler test FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


# ============================================
# 测试闪电贷管理器
# ============================================

async def test_flash_loan_manager():
    """测试闪电贷管理器"""
    logger.info("=" * 50)
    logger.info("Testing Flash Loan Manager")
    logger.info("=" * 50)
    
    try:
        from services.flash_loan_manager import (
            get_flash_loan_manager,
            FlashLoanSource,
        )
        
        manager = get_flash_loan_manager()
        await manager.initialize()
        
        # 测试获取报价
        quotes = await manager.get_quotes(
            token="USDC",
            amount=100000,
            chain="ethereum",
        )
        
        logger.info(f"Found {len(quotes)} quotes:")
        for quote in quotes:
            logger.info(f"  {quote.source.value}: fee=${quote.fee:.2f}, total=${quote.total_cost:.2f}")
        
        # 测试最优源
        best = await manager.get_best_source(
            token="USDC",
            amount=100000,
            chain="ethereum",
        )
        
        if best:
            logger.info(f"Best source: {best.source.value}")
        
        # 测试统计
        stats = manager.get_stats()
        logger.info(f"Stats: {stats}")
        
        # 测试支持的链
        supported = manager.get_supported_chains()
        logger.info(f"Supported: {supported}")
        
        logger.info("Flash loan manager test PASSED")
        return True
        
    except Exception as e:
        logger.error(f"Flash loan manager test FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


# ============================================
# 测试主控制器
# ============================================

async def test_auto_controller():
    """测试主控制器"""
    logger.info("=" * 50)
    logger.info("Testing Auto Controller")
    logger.info("=" * 50)
    
    try:
        from services.auto_controller import (
            get_auto_controller,
            ComponentType,
            EventType,
        )
        
        controller = get_auto_controller()
        await controller.initialize()
        
        # 测试获取状态
        status = controller.get_status()
        logger.info(f"System state: {status['state']}")
        logger.info(f"Components: {len(status['components'])}")
        
        # 测试组件健康检查
        for comp_type in [ComponentType.STRATEGY, ComponentType.FUND_MANAGER]:
            result = await controller.check_component_health(comp_type)
            logger.info(f"Health check {comp_type.value}: {result.healthy}")
        
        # 测试事件总线
        async def test_handler(event):
            logger.info(f"Event received: {event.event_type.value}")
        
        controller.event_bus.subscribe(EventType.HEALTH_CHECK, test_handler)
        
        # 发布测试事件
        from services.auto_controller import SystemEvent
        await controller.event_bus.publish(SystemEvent(
            id="test_1",
            event_type=EventType.HEALTH_CHECK,
            timestamp=datetime.now(),
            data={"test": True},
            source="test",
        ))
        
        logger.info("Auto controller test PASSED")
        return True
        
    except Exception as e:
        logger.error(f"Auto controller test FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


# ============================================
# 测试监控器 V2
# ============================================

async def test_monitor_v2():
    """测试监控器 V2"""
    logger.info("=" * 50)
    logger.info("Testing Monitor V2")
    logger.info("=" * 50)
    
    try:
        from services.monitor_v2 import (
            get_monitor_v2,
            AlertCategory,
            AlertLevel,
        )
        
        monitor = get_monitor_v2()
        await monitor.initialize()
        
        # 测试状态
        status = monitor.get_status()
        logger.info(f"Monitor status: running={status['is_running']}")
        
        # 测试告警回调
        async def test_alert_callback(alert):
            logger.info(f"Alert received: {alert.get('title')}")
        
        monitor.register_alert_callback(
            AlertCategory.OPPORTUNITY,
            test_alert_callback
        )
        
        # 发送测试告警
        await monitor._send_alert(
            category=AlertCategory.OPPORTUNITY,
            level=AlertLevel.INFO,
            title="Test Opportunity",
            message="This is a test opportunity alert",
            data={"test": True},
        )
        
        logger.info("Monitor V2 test PASSED")
        return True
        
    except Exception as e:
        logger.error(f"Monitor V2 test FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


# ============================================
# 测试配置
# ============================================

def test_config():
    """测试配置"""
    logger.info("=" * 50)
    logger.info("Testing Config")
    logger.info("=" * 50)
    
    try:
        from config.automation_config import (
            get_config_manager,
            AutomationConfig,
            StrategyType,
            ExecutionMode,
        )
        
        manager = get_config_manager()
        config = manager.get_config()
        
        logger.info(f"Config enabled: {config.enabled}")
        logger.info(f"Default strategy: {config.default_strategy.value}")
        logger.info(f"Max concurrent tasks: {config.scheduler.max_concurrent_tasks}")
        logger.info(f"Max gas price: {config.flash_loan.max_gas_price_gwei} Gwei")
        
        # 测试更新配置
        config.enabled = True
        config.default_strategy = StrategyType.CONSERVATIVE
        manager.update_config(config)
        
        updated = manager.get_config()
        logger.info(f"Updated config: enabled={updated.enabled}")
        
        # 测试转换为字典
        config_dict = config.to_dict()
        logger.info(f"Config dict keys: {list(config_dict.keys())}")
        
        logger.info("Config test PASSED")
        return True
        
    except Exception as e:
        logger.error(f"Config test FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


# ============================================
# 测试数据模型
# ============================================

def test_models():
    """测试数据模型"""
    logger.info("=" * 50)
    logger.info("Testing Data Models")
    logger.info("=" * 50)
    
    try:
        from models import (
            ExecutionHistory,
            OpportunityLog,
            FundSnapshot,
            ProfitRecord,
            ExecutionStatus,
            ExecutionMode,
            OpportunityStatus,
            OpportunityQuality,
            ChainSnapshot,
            PositionSnapshot,
        )
        
        # 测试执行历史
        history = ExecutionHistory(
            id="exec_1",
            opportunity_id="opp_1",
            strategy_name="balanced",
            chain="ethereum",
            token_in="ETH",
            token_out="USDC",
            amount_in=1.0,
            amount_out=2000.0,
            amount_in_usd=2000.0,
            amount_out_usd=2000.0,
            mode=ExecutionMode.NORMAL,
            status=ExecutionStatus.CONFIRMED,
            tx_hash="0x1234...",
            gas_cost_usd=10.0,
            actual_profit_usd=50.0,
        )
        
        logger.info(f"Execution history: profit=${history.actual_profit_usd}, ROI={history.roi_pct:.2f}%")
        
        # 测试机会日志
        log = OpportunityLog(
            id="opp_1",
            symbol="ETH",
            source_chain="ethereum",
            target_chain="arbitrum",
            source_price=2000.0,
            target_price=2010.0,
            price_diff_pct=0.5,
            estimated_profit_usd=50.0,
            estimated_profit_pct=2.5,
            estimated_gas_cost_usd=5.0,
            estimated_net_profit_usd=45.0,
            quality=OpportunityQuality.GOOD,
            confidence=0.85,
            risk_score=0.3,
        )
        
        logger.info(f"Opportunity log: profitable={log.is_profitable}, high_quality={log.is_high_quality}")
        
        # 测试资金快照
        chain_snapshot = ChainSnapshot(
            chain="ethereum",
            address="0x1234...",
            native_balance=5.0,
            native_balance_usd=10000.0,
            token_balances={"USDC": 5000.0},
            available_usd=14000.0,
            frozen_usd=500.0,
            locked_usd=0.0,
        )
        
        logger.info(f"Chain snapshot: balance=${chain_snapshot.total_balance_usd:.2f}")
        
        # 测试收益记录
        record = ProfitRecord(
            id="profit_1",
            execution_id="exec_1",
            opportunity_id="opp_1",
            chain="ethereum",
            token_in="ETH",
            token_out="USDC",
            amount_in=1.0,
            amount_out=2050.0,
            amount_in_usd=2000.0,
            amount_out_usd=2050.0,
            gas_cost_usd=10.0,
            flash_loan_fee_usd=0.0,
            bridge_fee_usd=0.0,
            other_fees_usd=0.0,
            total_fees_usd=10.0,
            gross_profit_usd=50.0,
            net_profit_usd=40.0,
            profit_pct=2.5,
            execution_mode="normal",
            status="completed",
        )
        
        logger.info(f"Profit record: net=${record.net_profit_usd:.2f}, profitable={record.is_profitable}")
        
        logger.info("Data models test PASSED")
        return True
        
    except Exception as e:
        logger.error(f"Data models test FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


# ============================================
# 运行所有测试
# ============================================

async def run_all_tests():
    """运行所有测试"""
    logger.info("")
    logger.info("*" * 60)
    logger.info(" PHASE 3 COMPONENT TESTS")
    logger.info("*" * 60)
    logger.info("")
    
    results = {}
    
    # 按依赖顺序测试
    results["Config"] = test_config()
    results["Data Models"] = test_models()
    results["Strategy Engine"] = await test_strategy_engine()
    results["Fund Manager"] = await test_fund_manager()
    results["Execution Scheduler"] = await test_execution_scheduler()
    results["Flash Loan Manager"] = await test_flash_loan_manager()
    results["Auto Controller"] = await test_auto_controller()
    results["Monitor V2"] = await test_monitor_v2()
    
    # 汇总结果
    logger.info("")
    logger.info("=" * 60)
    logger.info(" TEST RESULTS SUMMARY")
    logger.info("=" * 60)
    
    passed = 0
    failed = 0
    
    for name, result in results.items():
        status = "PASSED" if result else "FAILED"
        logger.info(f"  {name}: {status}")
        if result:
            passed += 1
        else:
            failed += 1
    
    logger.info("")
    logger.info(f"Total: {len(results)}, Passed: {passed}, Failed: {failed}")
    logger.info("=" * 60)
    
    return all(results.values())


if __name__ == "__main__":
    success = asyncio.run(run_all_tests())
    exit(0 if success else 1)
