"""
链上套利助手 - 服务模块

导出所有服务类供外部使用
"""

# Phase 1: 价格监控
from .price_monitor import (
    PriceMonitorService,
    TokenPrice,
    PriceCache,
    PriceSource,
)

# Phase 2: 跨链桥费用监控
from .bridge_fee_monitor import (
    BridgeFeeMonitorService,
    BridgeFee,
    FeeCache,
    LayerZeroFeeEstimator,
    WormholeFeeEstimator,
    get_bridge_fee_monitor,
    get_cross_chain_fee,
    get_all_cross_chain_fees,
)

# Phase 2: 套利机会检测
from .opportunity_detector import (
    OpportunityDetector,
    OpportunityDetectorService,
    ArbitrageConfig,
    ArbitrageOpportunity,
    RiskLevel,
    OpportunityStatus,
    ExecutionRecommendation,
    get_opportunities,
)

# Phase 2: 告警服务
from .alert import (
    AlertService,
    AlertConfig,
    AlertLevel,
    AlertType,
    AlertChannel,
    AlertMessage,
    AlertResult,
    get_alert_service,
    send_arbitrage_alert,
)

# Phase 2: 主监控循环
from .monitor_loop import (
    MonitorLoop,
    MonitorConfig,
    MonitorStatus,
    MonitorStats,
    get_monitor_loop,
    start_monitoring,
    stop_monitoring,
)

__all__ = [
    # 价格监控
    "PriceMonitorService",
    "TokenPrice",
    "PriceCache",
    "PriceSource",
    
    # 跨链桥费用
    "BridgeFeeMonitorService",
    "BridgeFee",
    "FeeCache",
    "LayerZeroFeeEstimator",
    "WormholeFeeEstimator",
    "get_bridge_fee_monitor",
    "get_cross_chain_fee",
    "get_all_cross_chain_fees",
    
    # 套利机会
    "OpportunityDetector",
    "OpportunityDetectorService",
    "ArbitrageConfig",
    "ArbitrageOpportunity",
    "RiskLevel",
    "OpportunityStatus",
    "ExecutionRecommendation",
    "get_opportunities",
    
    # 告警
    "AlertService",
    "AlertConfig",
    "AlertLevel",
    "AlertType",
    "AlertChannel",
    "AlertMessage",
    "AlertResult",
    "get_alert_service",
    "send_arbitrage_alert",
    
    # 监控循环
    "MonitorLoop",
    "MonitorConfig",
    "MonitorStatus",
    "MonitorStats",
    "get_monitor_loop",
    "start_monitoring",
    "stop_monitoring",
]
