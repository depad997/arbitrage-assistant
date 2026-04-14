"""
数据模型 - Phase 3 全自动执行核心组件

包含：
- execution_history.py - 执行历史记录
- opportunity_log.py - 机会日志
- fund_snapshot.py - 资金快照
- profit_record.py - 收益记录

设计原则：
- 结构化数据存储
- 支持序列化和反序列化
- 便于持久化和查询
"""

from .execution_history import (
    ExecutionHistory,
    ExecutionStatus,
    ExecutionMode,
)
from .opportunity_log import (
    OpportunityLog,
    OpportunityStatus,
    OpportunityQuality,
)
from .fund_snapshot import (
    FundSnapshot,
    ChainSnapshot,
    PositionSnapshot,
)
from .profit_record import (
    ProfitRecord,
    ProfitSummary,
)

__all__ = [
    "ExecutionHistory",
    "ExecutionStatus",
    "ExecutionMode",
    "OpportunityLog",
    "OpportunityStatus",
    "OpportunityQuality",
    "FundSnapshot",
    "ChainSnapshot",
    "PositionSnapshot",
    "ProfitRecord",
    "ProfitSummary",
]
