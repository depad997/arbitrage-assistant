"""
Phase 3 路由注册脚本

将自动化 API 路由添加到主应用中
"""

import os
import sys

_backend_dir = os.path.dirname(os.path.abspath(__file__))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

# ============================================
# 需要在 main.py 中添加的导入和路由
# ============================================

ROUTE_IMPORTS = '''
# Phase 3 自动化执行路由
try:
    from api.routes.automation import router as automation_router
    logger.info("Phase 3 Automation routes loaded")
except ImportError as e:
    logger.warning(f"Phase 3 routes not available: {e}")
    automation_router = None
'''

ROUTE_REGISTRATION = '''
# Phase 3: 自动化执行路由
if automation_router:
    app.include_router(automation_router)
    logger.info("Automation router registered")
'''

LIFESPAN_UPDATE = '''
    # Phase 3 组件初始化
    try:
        # 策略管理器
        from services.auto_strategy import init_strategy_manager
        strategy_mgr = await init_strategy_manager()
        logger.info("StrategyManager initialized")
        
        # 资金管理器
        from services.fund_manager import init_fund_manager
        fund_mgr = await init_fund_manager()
        logger.info("FundManager initialized")
        
        # 闪电贷管理器
        from services.flash_loan_manager import init_flash_loan_manager
        flash_loan_mgr = await init_flash_loan_manager()
        logger.info("FlashLoanManager initialized")
        
        # 执行调度器
        from services.execution_scheduler import init_execution_scheduler
        scheduler = await init_execution_scheduler()
        logger.info("ExecutionScheduler initialized")
        
        # 主控制器
        from services.auto_controller import init_auto_controller
        controller = await init_auto_controller()
        logger.info("AutoController initialized")
        
        # 监控器 V2
        from services.monitor_v2 import init_monitor_v2
        monitor_v2 = await init_monitor_v2()
        logger.info("MonitorV2 initialized")
        
    except Exception as e:
        logger.warning(f"Phase 3 components initialization warning: {e}")
'''

SHUTDOWN_UPDATE = '''
    # Phase 3 组件清理
    try:
        from services.monitor_v2 import get_monitor_v2
        monitor_v2 = get_monitor_v2()
        if monitor_v2._is_running:
            await monitor_v2.stop()
        
        from services.auto_controller import get_auto_controller
        controller = get_auto_controller()
        if controller.state.value in ["running", "paused"]:
            await controller.stop()
            
    except Exception as e:
        logger.warning(f"Phase 3 cleanup warning: {e}")
'''


def update_main_py():
    """更新 main.py 添加 Phase 3 支持"""
    main_py_path = os.path.join(_backend_dir, "main.py")
    
    # 读取现有文件
    with open(main_py_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 检查是否已添加
    if "Phase 3" in content and "automation_router" in content:
        print("Phase 3 routes already integrated")
        return False
    
    # 添加导入
    if "from api.routes.automation" not in content:
        # 在适当位置添加导入
        import_marker = "# ============================================\n# Pydantic 模型"
        if import_marker in content:
            content = content.replace(
                import_marker,
                ROUTE_IMPORTS + "\n" + import_marker
            )
    
    # 添加路由注册
    if "automation_router" not in content:
        config_marker = "# ----------------------------------------\n# 配置相关接口"
        if config_marker in content:
            content = content.replace(
                config_marker,
                ROUTE_REGISTRATION + "\n\n" + config_marker
            )
    
    # 更新 lifespan 初始化
    if "Phase 3 组件初始化" not in content:
        lifespan_marker = "logger.info(\"Application startup complete\")"
        if lifespan_marker in content:
            content = content.replace(
                lifespan_marker,
                lifespan_marker + "\n" + LIFESPAN_UPDATE
            )
    
    # 更新 shutdown
    if "Phase 3 组件清理" not in content:
        shutdown_marker = 'logger.info("Shutting down...")'
        if shutdown_marker in content:
            content = content.replace(
                shutdown_marker,
                shutdown_marker + "\n" + SHUTDOWN_UPDATE
            )
    
    # 写回文件
    with open(main_py_path, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print("main.py updated with Phase 3 routes")
    return True


def create_integration_example():
    """创建集成示例"""
    example_code = '''"""
Phase 3 全自动执行示例

展示如何使用自动执行引擎
"""

import asyncio
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main():
    """主函数"""
    from services.auto_controller import init_auto_controller, get_auto_controller
    from services.auto_strategy import get_strategy_manager
    from services.fund_manager import get_fund_manager
    from services.execution_scheduler import get_execution_scheduler
    
    # 初始化控制器
    controller = await init_auto_controller()
    
    # 配置资金
    fund_mgr = get_fund_manager()
    fund_mgr.register_chain("ethereum", "0x...", 10000.0)
    fund_mgr.register_chain("arbitrum", "0x...", 5000.0)
    
    # 切换策略
    strategy_mgr = get_strategy_manager()
    strategy_mgr.switch_strategy("balanced")
    
    # 启动系统
    success = await controller.start()
    
    if success:
        logger.info("Auto execution system started")
        
        # 运行一段时间
        await asyncio.sleep(60)
        
        # 获取状态
        status = controller.get_status()
        logger.info(f"Status: {status['state']}")
        
        # 停止系统
        await controller.stop()
        logger.info("System stopped")
    else:
        logger.error("Failed to start system")


if __name__ == "__main__":
    asyncio.run(main())
'''
    
    with open("examples/phase3_example.py", 'w', encoding='utf-8') as f:
        f.write(example_code)
    
    print("Example created: examples/phase3_example.py")
    return True


if __name__ == "__main__":
    print("=" * 50)
    print("Phase 3 Integration Script")
    print("=" * 50)
    
    # 创建示例目录
    os.makedirs("examples", exist_ok=True)
    
    # 更新 main.py
    update_main_py()
    
    # 创建示例
    create_integration_example()
    
    print("=" * 50)
    print("Integration complete!")
    print("=" * 50)
