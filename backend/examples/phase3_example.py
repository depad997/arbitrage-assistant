"""
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
