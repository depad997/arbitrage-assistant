"""
Phase 2 功能测试脚本

测试内容：
1. 钱包管理功能
2. 交易构建功能
3. 风险控制功能
4. 执行引擎（模拟）
"""

import asyncio
import os
import sys
from decimal import Decimal
from datetime import datetime

# 添加路径
_backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)


async def test_wallet_manager():
    """测试钱包管理"""
    print("\n" + "="*60)
    print("测试 1: 钱包管理")
    print("="*60)
    
    from services.wallet_manager import (
        WalletManager,
        KeyStoreManager,
        CryptoUtils,
        EVMWalletManager
    )
    
    # 1. 测试加密工具
    print("\n1.1 测试加密工具...")
    password = "test_password_123"
    data = b"hello_world"
    
    salt = CryptoUtils.generate_salt()
    key = CryptoUtils.derive_key(password, salt)
    ciphertext, nonce = CryptoUtils.encrypt_aes_gcm(data, key)
    decrypted = CryptoUtils.decrypt_aes_gcm(ciphertext, key, nonce)
    
    assert decrypted == data, "Decryption failed"
    print("   ✓ AES-256-GCM 加密解密测试通过")
    
    # 2. 测试 Keystore 管理
    print("\n1.2 测试 Keystore 管理...")
    keystore_dir = "./test_keystore"
    os.makedirs(keystore_dir, exist_ok=True)
    
    km = KeyStoreManager(keystore_dir)
    
    # 生成测试私钥
    private_key = os.urandom(32)
    keystore = km.create_v3_keystore(private_key, password)
    filepath = km.save_v3_keystore(keystore)
    
    print(f"   ✓ Keystore 已保存: {filepath}")
    
    # 解密验证
    decrypted_pk = km.decrypt_v3_keystore(keystore, password)
    assert decrypted_pk == private_key, "Keystore decryption failed"
    print("   ✓ Keystore 解密测试通过")
    
    # 3. 测试钱包管理器
    print("\n1.3 测试钱包管理器...")
    wm = WalletManager(keystore_dir)
    
    # 创建钱包
    wallet_info = wm.create_wallet(
        name="Test Wallet",
        password=password,
        chains=["ethereum", "arbitrum", "bsc"]
    )
    
    print(f"   ✓ 钱包创建成功:")
    print(f"     - ID: {wallet_info.wallet_id}")
    print(f"     - 名称: {wallet_info.name}")
    print(f"     - Ethereum 地址: {wallet_info.addresses['ethereum'].address}")
    print(f"     - 支持链: {list(wallet_info.addresses.keys())}")
    
    # 测试余额查询（需要网络连接）
    try:
        balance = wm.get_balance("ethereum")
        print(f"\n1.4 测试余额查询...")
        print(f"   ✓ ETH 余额: {balance.native_balance}")
        print(f"   ✓ Token 数量: {len(balance.tokens)}")
    except Exception as e:
        print(f"   ⚠ 余额查询跳过（网络不可用）: {e}")
    
    # 清理
    import shutil
    shutil.rmtree(keystore_dir)
    print("\n   ✓ 测试环境清理完成")
    
    return True


async def test_tx_builder():
    """测试交易构建"""
    print("\n" + "="*60)
    print("测试 2: 交易构建")
    print("="*60)
    
    from services.tx_builder import (
        TransactionBuilder,
        SwapParams,
        DEX_ROUTERS,
        WETH_ADDRESSES,
        UNISWAP_V2_ROUTER_ABI,
        ERC20_ABI
    )
    from web3 import Web3
    
    # 1. 检查 DEX 配置
    print("\n2.1 检查 DEX 配置...")
    ethereum_dex = DEX_ROUTERS.get("ethereum", {})
    print(f"   ✓ Ethereum 支持的 DEX: {list(ethereum_dex.keys())}")
    
    bsc_dex = DEX_ROUTERS.get("bsc", {})
    print(f"   ✓ BSC 支持的 DEX: {list(bsc_dex.keys())}")
    
    # 2. 检查 WETH 地址
    print("\n2.2 检查 WETH 地址映射...")
    print(f"   ✓ Ethereum WETH: {WETH_ADDRESSES.get('ethereum')}")
    print(f"   ✓ BSC WETH: {WETH_ADDRESSES.get('bsc')}")
    
    # 3. 构建 Swap 参数
    print("\n2.3 测试 Swap 参数构建...")
    swap_params = SwapParams(
        token_in=Web3.to_checksum_address("0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"),
        token_out=Web3.to_checksum_address("0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"),
        amount_in=1000 * 10**6,  # 1000 USDC
        amount_out_min=0,
        recipient="0x1234567890123456789012345678901234567890",
        deadline=int(datetime.now().timestamp()) + 600
    )
    print(f"   ✓ Swap 参数构建成功")
    print(f"     - 输入代币: {swap_params.token_in}")
    print(f"     - 输出代币: {swap_params.token_out}")
    print(f"     - 输入金额: {swap_params.amount_in}")
    
    # 4. 检查 ABI
    print("\n2.4 检查合约 ABI...")
    print(f"   ✓ Uniswap V2 Router ABI: {len(UNISWAP_V2_ROUTER_ABI)} 个函数")
    print(f"   ✓ ERC20 ABI: {len(ERC20_ABI)} 个函数")
    
    return True


async def test_risk_control():
    """测试风险控制"""
    print("\n" + "="*60)
    print("测试 3: 风险控制")
    print("="*60)
    
    from services.risk_control import (
        RiskController,
        RiskLimits,
        RiskLevel,
        TradeContext,
        EmergencyStopController,
        EmergencyState
    )
    
    # 1. 测试风险限制
    print("\n3.1 测试风险限制配置...")
    limits = RiskLimits(
        max_single_trade_usd=50000.0,
        min_single_trade_usd=10.0,
        max_daily_trades=100,
        max_slippage_pct=1.0,
        max_gas_price_gwei=100.0,
        min_profit_threshold_usd=5.0
    )
    print(f"   ✓ 风险限制配置成功")
    print(f"     - 单笔最大: ${limits.max_single_trade_usd}")
    print(f"     - 单笔最小: ${limits.min_single_trade_usd}")
    print(f"     - 每日最大交易: {limits.max_daily_trades}")
    print(f"     - 最大滑点: {limits.max_slippage_pct}%")
    
    # 2. 测试紧急停止
    print("\n3.2 测试紧急停止控制器...")
    emergency = EmergencyStopController()
    
    # 测试警告
    emergency.warning("High gas price detected")
    assert emergency.state == EmergencyState.WARNING
    print("   ✓ 警告状态测试通过")
    
    # 测试停止
    emergency.stop("Critical failure")
    assert emergency.state == EmergencyState.STOPPED
    print("   ✓ 停止状态测试通过")
    
    # 测试恢复
    can_proceed, reason = emergency.can_proceed()
    assert not can_proceed
    print(f"   ✓ 停止状态检查通过: {reason}")
    
    emergency.resume("Issue resolved")
    assert emergency.state == EmergencyState.NORMAL
    can_proceed, _ = emergency.can_proceed()
    assert can_proceed
    print("   ✓ 恢复状态测试通过")
    
    # 3. 测试风险控制器
    print("\n3.3 测试风险控制器...")
    risk_ctrl = RiskController(limits=limits)
    
    # 创建交易上下文
    context = TradeContext(
        chain="ethereum",
        from_address="0x1234567890123456789012345678901234567890",
        to_address="0x2345678901234567890123456789012345678901",
        token_in="0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
        token_out="0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
        amount_in=10000.0,
        amount_out_estimated=10050.0,
        amount_out_min=10000.0,
        expected_price=1.005,
        actual_price=1.005,
        slippage_pct=0.3,
        gas_price_gwei=30.0,
        gas_limit=150000,
        estimated_gas_cost_usd=5.0,
        estimated_profit_usd=45.0
    )
    
    # 执行风险检查
    result = await risk_ctrl.perform_risk_check(
        context=context,
        available_balance=20000.0
    )
    
    print(f"   ✓ 风险检查结果:")
    print(f"     - 通过: {result.passed}")
    print(f"     - 风险等级: {result.risk_level.value}")
    print(f"     - 风险分数: {result.risk_score:.4f}")
    print(f"     - 建议: {result.recommended_action}")
    
    if result.warnings:
        print(f"     - 警告: {result.warnings}")
    if result.errors:
        print(f"     - 错误: {result.errors}")
    
    # 4. 测试统计记录
    print("\n3.4 测试交易统计...")
    risk_ctrl.record_execution(
        chain="ethereum",
        amount_usd=10000.0,
        profit_usd=40.0,
        cost_usd=5.0,
        gas_used=150000,
        success=True
    )
    
    stats = risk_ctrl.get_stats()
    print(f"   ✓ 统计信息:")
    print(f"     - 今日交易: {stats['today']['total_trades']}")
    print(f"     - 今日利润: ${stats['today']['total_profit_usd']:.2f}")
    
    return True


async def test_execution_engine():
    """测试执行引擎（模拟）"""
    print("\n" + "="*60)
    print("测试 4: 执行引擎（模拟）")
    print("="*60)
    
    from services.execution_engine import (
        ExecutionEngine,
        ExecutionPlan,
        ExecutionPlanBuilder,
        ExecutionStatus,
        ExecutionResult,
        GasConfig,
        RetryConfig,
        ExecutionMode
    )
    from services.tx_builder import TransactionParams
    from services.wallet_manager import WalletManager
    
    # 1. 创建模拟钱包
    print("\n4.1 创建模拟环境...")
    
    # 注意：这里不真正连接网络，仅测试结构
    class MockWallet:
        def __init__(self):
            self.evm_manager = None
    
    mock_wallet = MockWallet()
    
    # 2. 测试执行计划构建
    print("\n4.2 测试执行计划构建...")
    
    builder = ExecutionPlanBuilder()
    
    # 添加步骤
    tx_params1 = TransactionParams(
        chain="ethereum",
        from_address="0x1234567890123456789012345678901234567890",
        to_address="0x68b3465833fb72A70ecDF485E0e4C7bD8665Fc45",
        value=0,
        data="0x",
        gas_limit=150000
    )
    
    tx_params2 = TransactionParams(
        chain="arbitrum",
        from_address="0x1234567890123456789012345678901234567890",
        to_address="0x68b3465833fb72A70ecDF485E0e4C7bD8665Fc45",
        value=0,
        data="0x",
        gas_limit=150000
    )
    
    builder.add_step(
        step_type="swap",
        chain="ethereum",
        tx_params=tx_params1
    ).add_step(
        step_type="bridge",
        chain="arbitrum",
        tx_params=tx_params2,
        depends_on=["step1"]  # 需要先完成 swap
    ).set_mode(ExecutionMode.NORMAL)
    
    plan = builder.build()
    
    print(f"   ✓ 执行计划构建成功:")
    print(f"     - 计划 ID: {plan.plan_id}")
    print(f"     - 执行模式: {plan.mode.value}")
    print(f"     - 步骤数量: {len(plan.steps)}")
    
    # 3. 测试 Gas 配置
    print("\n4.3 测试 Gas 配置...")
    gas_config = GasConfig(
        max_gas_price_gwei=100.0,
        max_total_gas_cost_usd=50.0,
        priority_fee_boost=1.2
    )
    print(f"   ✓ Gas 配置:")
    print(f"     - 最大 Gas Price: {gas_config.max_gas_price_gwei} Gwei")
    print(f"     - 最大 Gas 成本: ${gas_config.max_total_gas_cost_usd}")
    
    # 4. 测试 Retry 配置
    print("\n4.4 测试重试配置...")
    retry_config = RetryConfig(
        max_retries=3,
        retry_delay_seconds=5,
        exponential_backoff=True
    )
    print(f"   ✓ 重试配置:")
    print(f"     - 最大重试: {retry_config.max_retries}")
    print(f"     - 重试延迟: {retry_config.retry_delay_seconds}秒")
    print(f"     - 指数退避: {retry_config.exponential_backoff}")
    
    # 5. 测试执行结果
    print("\n4.5 测试执行结果...")
    result = ExecutionResult(
        tx_hash="0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
        chain="ethereum",
        status=ExecutionStatus.CONFIRMED,
        block_number=18500000,
        gas_used=150000,
        effective_gas_price=30000000000,
        gas_cost=0.0045,
        gas_cost_usd=15.0,
        success=True,
        submitted_at=datetime.now(),
        confirmed_at=datetime.now()
    )
    
    print(f"   ✓ 执行结果:")
    print(f"     - Tx Hash: {result.tx_hash[:20]}...")
    print(f"     - 状态: {result.status.value}")
    print(f"     - 成功: {result.success}")
    print(f"     - Gas 使用: {result.gas_used}")
    
    return True


async def test_cross_chain():
    """测试跨链功能"""
    print("\n" + "="*60)
    print("测试 5: 跨链功能")
    print("="*60)
    
    from services.tx_builder import (
        CrossChainTransactionBuilder,
        LAYERZERO_ENDPOINTS,
        WORMHOLE_CHAIN_IDS
    )
    from config.settings import SUPPORTED_CHAINS
    
    # 1. 检查 LayerZero 支持
    print("\n5.1 检查 LayerZero 支持...")
    print(f"   ✓ LayerZero 支持的链: {list(LAYERZERO_ENDPOINTS.keys())}")
    
    # 2. 检查 Wormhole 支持
    print("\n5.2 检查 Wormhole 支持...")
    print(f"   ✓ Wormhole 支持的链数量: {len(WORMHOLE_CHAIN_IDS)}")
    
    # 3. 测试跨链构建器初始化
    print("\n5.3 测试跨链交易构建器...")
    cross_builder = CrossChainTransactionBuilder(
        source_chain="arbitrum",
        target_chain="bsc"
    )
    print(f"   ✓ 跨链构建器初始化成功")
    print(f"     - 源链: {cross_builder.source_chain}")
    print(f"     - 目标链: {cross_builder.target_chain}")
    
    # 4. 检查链配置
    print("\n5.4 检查链配置...")
    for chain_name in ["arbitrum", "bsc", "polygon"]:
        config = SUPPORTED_CHAINS.get(chain_name)
        if config:
            print(f"   ✓ {chain_name}:")
            print(f"     - Chain ID: {config.chain_id}")
            print(f"     - LayerZero ID: {config.layerzero_endpoint_id}")
            print(f"     - Wormhole ID: {config.wormhole_chain_id}")
            print(f"     - 原生代币: {config.native_token}")
            print(f"     - EVM: {config.is_evm}")
    
    return True


async def main():
    """主测试函数"""
    print("\n" + "="*60)
    print("链上套利助手 Phase 2 功能测试")
    print("="*60)
    
    tests = [
        ("钱包管理", test_wallet_manager),
        ("交易构建", test_tx_builder),
        ("风险控制", test_risk_control),
        ("执行引擎", test_execution_engine),
        ("跨链功能", test_cross_chain)
    ]
    
    results = []
    
    for name, test_func in tests:
        try:
            success = await test_func()
            results.append((name, success))
        except Exception as e:
            print(f"\n❌ {name} 测试失败: {e}")
            import traceback
            traceback.print_exc()
            results.append((name, False))
    
    # 打印总结
    print("\n" + "="*60)
    print("测试总结")
    print("="*60)
    
    for name, success in results:
        status = "✓ 通过" if success else "❌ 失败"
        print(f"  {name}: {status}")
    
    all_passed = all(success for _, success in results)
    
    print("\n" + "-"*60)
    if all_passed:
        print("🎉 所有测试通过！")
    else:
        print("⚠ 部分测试失败，请检查错误信息")
    print("-"*60 + "\n")
    
    return all_passed


if __name__ == "__main__":
    asyncio.run(main())
