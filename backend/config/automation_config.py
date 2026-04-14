"""
自动化配置 - Phase 3 全自动执行核心组件

定义自动执行相关的所有配置参数
"""

from pydantic import BaseModel, Field, ConfigDict
from typing import Dict, List, Optional
from enum import Enum


class StrategyType(str, Enum):
    """策略类型"""
    CONSERVATIVE = "conservative"
    BALANCED = "balanced"
    AGGRESSIVE = "aggressive"
    CUSTOM = "custom"


class ExecutionMode(str, Enum):
    """执行模式"""
    NORMAL = "normal"
    FLASH_LOAN = "flash_loan"
    AUTO = "auto"


# ============================================
# 策略配置
# ============================================

class StrategyParameters(BaseModel):
    """策略参数"""
    model_config = ConfigDict(extra="ignore")
    
    # 利润阈值
    min_profit_threshold_usd: float = 10.0
    min_profit_threshold_pct: float = 0.5
    target_profit_threshold_pct: float = 2.0
    
    # 风险参数
    max_risk_score: float = 0.7
    max_single_trade_usd: float = 10000.0
    max_daily_trades: int = 10
    max_daily_loss_usd: float = 500.0
    
    # 执行参数
    max_gas_price_gwei: float = 50.0
    max_slippage_pct: float = 0.5
    execution_timeout_seconds: int = 300
    
    # 置信度参数
    min_confidence_score: float = 0.6
    auto_execute_confidence: float = 0.8
    
    # 时间参数
    opportunity_validity_seconds: int = 60
    cooldown_seconds: int = 300


class StrategyConfig(BaseModel):
    """策略配置"""
    model_config = ConfigDict(extra="ignore")
    
    name: str
    strategy_type: StrategyType
    enabled: bool = True
    parameters: StrategyParameters = Field(default_factory=StrategyParameters)
    enabled_chains: List[str] = []
    enabled_tokens: List[str] = []


# ============================================
# 执行调度配置
# ============================================

class SchedulerConfig(BaseModel):
    """执行调度器配置"""
    model_config = ConfigDict(extra="ignore")
    
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
    max_retries: int = 3
    
    # 拥堵避让
    congestion_avoidance_enabled: bool = True
    max_congestion_wait_seconds: int = 300
    
    # 任务限制
    max_queue_size: int = 1000
    task_expiry_seconds: int = 3600


# ============================================
# 资金管理配置
# ============================================

class FundAllocationConfig(BaseModel):
    """资金分配配置"""
    model_config = ConfigDict(extra="ignore")
    
    chain: str
    allocation_pct: float = 0.2
    min_balance_usd: float = 100.0
    max_balance_usd: float = 20000.0
    target_balance_usd: float = 10000.0
    reserved_pct: float = 0.1


class FundRiskLimits(BaseModel):
    """资金风险限制"""
    model_config = ConfigDict(extra="ignore")
    
    max_position_usd: float = 10000.0
    max_total_position_usd: float = 50000.0
    max_single_trade_usd: float = 5000.0
    daily_loss_limit_usd: float = 1000.0
    max_drawdown_pct: float = 10.0
    emergency_withdraw_threshold: float = 20.0


class FundManagementConfig(BaseModel):
    """资金管理配置"""
    model_config = ConfigDict(extra="ignore")
    
    allocations: List[FundAllocationConfig] = []
    risk_limits: FundRiskLimits = Field(default_factory=FundRiskLimits)
    rebalance_threshold_pct: float = 20.0
    auto_rebalance_enabled: bool = True
    rebalance_interval_hours: int = 24


# ============================================
# 闪电贷配置
# ============================================

class FlashLoanConfig(BaseModel):
    """闪电贷配置"""
    model_config = ConfigDict(extra="ignore")
    
    # 启用状态
    aave_v3_enabled: bool = True
    uniswap_v3_enabled: bool = True
    dydx_enabled: bool = True
    
    # 费用设置
    aave_v3_fee_pct: float = 0.09
    uniswap_v3_fee_pct: float = 0.0
    dydx_fee_pct: float = 0.0
    
    # 通用设置
    max_gas_price_gwei: float = 100.0
    max_gas_cost_usd: float = 100.0
    min_profit_threshold_usd: float = 5.0
    slippage_tolerance_pct: float = 0.5
    
    # 金额限制
    min_flash_loan_amount_usd: float = 100.0
    max_flash_loan_amount_usd: float = 1000000.0


# ============================================
# 监控配置
# ============================================

class MonitorConfig(BaseModel):
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


# ============================================
# 告警配置
# ============================================

class AlertConfig(BaseModel):
    """告警配置"""
    # 告警级别阈值
    opportunity_alert_min_profit_usd: float = 10.0
    opportunity_alert_min_confidence: float = 0.7
    
    # 告警开关
    enable_opportunity_alerts: bool = True
    enable_execution_alerts: bool = True
    enable_system_alerts: bool = True
    enable_risk_alerts: bool = True
    enable_performance_alerts: bool = True
    
    # 通知渠道
    notification_channels: List[str] = ["feishu"]  # feishu, telegram, email
    
    # 紧急告警
    emergency_alert_loss_threshold_usd: float = 500.0
    emergency_alert_drawdown_threshold_pct: float = 15.0


# ============================================
# 自动化主配置
# ============================================

class AutomationConfig(BaseModel):
    """自动化主配置"""
    # 基础设置
    enabled: bool = False
    default_strategy: StrategyType = StrategyType.BALANCED
    execution_mode: ExecutionMode = ExecutionMode.AUTO
    
    # 子配置
    strategy: StrategyConfig = Field(default_factory=lambda: StrategyConfig(
        name="balanced",
        strategy_type=StrategyType.BALANCED,
        enabled_chains=["ethereum", "arbitrum", "optimism", "polygon", "bsc"],
    ))
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    fund_management: FundManagementConfig = Field(default_factory=FundManagementConfig)
    flash_loan: FlashLoanConfig = Field(default_factory=FlashLoanConfig)
    monitor: MonitorConfig = Field(default_factory=MonitorConfig)
    alert: AlertConfig = Field(default_factory=AlertConfig)
    
    # 系统设置
    health_check_interval_seconds: int = 30
    heartbeat_timeout_seconds: int = 120
    max_auto_restart_attempts: int = 3
    restart_delay_seconds: int = 5
    
    # 日志设置
    log_level: str = "INFO"
    log_trades: bool = True
    log_opportunities: bool = True
    
    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            "enabled": self.enabled,
            "default_strategy": self.default_strategy.value,
            "execution_mode": self.execution_mode.value,
            "strategy": {
                "name": self.strategy.name,
                "type": self.strategy.strategy_type.value,
                "enabled": self.strategy.enabled,
                "parameters": self.strategy.parameters.model_dump(),
                "enabled_chains": self.strategy.enabled_chains,
            },
            "scheduler": self.scheduler.model_dump(),
            "fund_management": {
                "allocations": [a.model_dump() for a in self.fund_management.allocations],
                "risk_limits": self.fund_management.risk_limits.model_dump(),
                "rebalance_threshold_pct": self.fund_management.rebalance_threshold_pct,
            },
            "flash_loan": self.flash_loan.model_dump(),
            "monitor": self.monitor.model_dump(),
            "alert": self.alert.model_dump(),
            "system": {
                "health_check_interval_seconds": self.health_check_interval_seconds,
                "heartbeat_timeout_seconds": self.heartbeat_timeout_seconds,
                "log_level": self.log_level,
            },
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'AutomationConfig':
        """从字典创建"""
        from typing import Any
        
        config = cls()
        
        if "enabled" in data:
            config.enabled = data["enabled"]
        if "default_strategy" in data:
            config.default_strategy = StrategyType(data["default_strategy"])
        if "execution_mode" in data:
            config.execution_mode = ExecutionMode(data["execution_mode"])
        
        if "strategy" in data:
            s = data["strategy"]
            config.strategy.name = s.get("name", config.strategy.name)
            config.strategy.strategy_type = StrategyType(s.get("type", config.strategy.strategy_type.value))
            config.strategy.enabled = s.get("enabled", config.strategy.enabled)
            config.strategy.enabled_chains = s.get("enabled_chains", config.strategy.enabled_chains)
            
            if "parameters" in s:
                for key, value in s["parameters"].items():
                    if hasattr(config.strategy.parameters, key):
                        setattr(config.strategy.parameters, key, value)
        
        if "scheduler" in data:
            for key, value in data["scheduler"].items():
                if hasattr(config.scheduler, key):
                    setattr(config.scheduler, key, value)
        
        if "flash_loan" in data:
            for key, value in data["flash_loan"].items():
                if hasattr(config.flash_loan, key):
                    setattr(config.flash_loan, key, value)
        
        if "monitor" in data:
            for key, value in data["monitor"].items():
                if hasattr(config.monitor, key):
                    setattr(config.monitor, key, value)
        
        if "alert" in data:
            for key, value in data["alert"].items():
                if hasattr(config.alert, key):
                    setattr(config.alert, key, value)
        
        return config


# ============================================
# 默认配置
# ============================================

DEFAULT_AUTOMATION_CONFIG = AutomationConfig(
    enabled=False,
    default_strategy=StrategyType.BALANCED,
    execution_mode=ExecutionMode.AUTO,
)


# ============================================
# 配置管理器
# ============================================

class ConfigManager:
    """配置管理器"""
    
    _instance = None
    _config: AutomationConfig = DEFAULT_AUTOMATION_CONFIG
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def get_config(self) -> AutomationConfig:
        """获取配置"""
        return self._config
    
    def update_config(self, config: AutomationConfig):
        """更新配置"""
        self._config = config
    
    def update_from_dict(self, data: Dict):
        """从字典更新配置"""
        self._config = AutomationConfig.from_dict(data)
    
    def reset_to_default(self):
        """重置为默认配置"""
        self._config = DEFAULT_AUTOMATION_CONFIG


# ============================================
# 单例访问函数
# ============================================

_config_manager: Optional[ConfigManager] = None


def get_config_manager() -> ConfigManager:
    """获取配置管理器"""
    global _config_manager
    if _config_manager is None:
        _config_manager = ConfigManager()
    return _config_manager


def get_automation_config() -> AutomationConfig:
    """获取自动化配置"""
    return get_config_manager().get_config()


def update_automation_config(config: AutomationConfig):
    """更新自动化配置"""
    get_config_manager().update_config(config)
