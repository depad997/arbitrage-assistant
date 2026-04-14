"""
链上套利助手 - 配置模块
"""

from .settings import (
    # 数据类
    ChainConfig,
    BridgeConfig,
    # 配置
    SUPPORTED_CHAINS,
    ENABLED_CHAINS,
    BRIDGE_CONFIGS,
    RPC_CONFIGS,
    RPC_URLS,
    RPC_FALLBACK_URLS,
    # Settings 实例
    Settings,
    settings,
    get_settings,
    # 辅助函数
    get_chain_config,
    get_enabled_chains,
    get_evm_chains,
    get_non_evm_chains,
    is_chain_enabled,
    get_rpc_for_chain,
    get_bridge_supported_chains,
)

__all__ = [
    # 数据类
    "ChainConfig",
    "BridgeConfig",
    # 配置
    "SUPPORTED_CHAINS",
    "ENABLED_CHAINS",
    "BRIDGE_CONFIGS",
    "RPC_CONFIGS",
    "RPC_URLS",
    "RPC_FALLBACK_URLS",
    # Settings
    "Settings",
    "settings",
    "get_settings",
    # 辅助函数
    "get_chain_config",
    "get_enabled_chains",
    "get_evm_chains",
    "get_non_evm_chains",
    "is_chain_enabled",
    "get_rpc_for_chain",
    "get_bridge_supported_chains",
]
