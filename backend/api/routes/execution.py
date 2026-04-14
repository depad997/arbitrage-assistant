"""
API 路由 - Phase 2 执行能力核心组件

路由列表：
- POST /api/wallet/create - 创建钱包
- POST /api/wallet/import - 导入钱包
- GET /api/wallet/balance/{chain} - 查询余额
- POST /api/execute/swap - 执行单链swap
- POST /api/execute/cross-chain - 执行跨链swap
- POST /api/execute/flash-loan - 执行闪电贷套利
- GET /api/execution/status/{tx_hash} - 查询执行状态
"""

import os
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime
from enum import Enum

from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks, Query, Body
from pydantic import BaseModel, Field, validator
from fastapi.responses import JSONResponse

import sys
import os as _os
_backend_dir = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _os.path.dirname(_backend_dir) not in sys.path:
    sys.path.insert(0, _os.path.dirname(_backend_dir))

from services.wallet_manager import (
    WalletManager,
    WalletInfo,
    WalletBalance,
    get_wallet_manager,
    init_wallet_manager,
    EVMWalletManager
)
from services.tx_builder import (
    TransactionBuilder,
    SwapParams,
    TransactionParams,
    CrossChainTransactionBuilder,
    DEXType,
    DEX_ROUTERS
)
from services.execution_engine import (
    ExecutionEngine,
    ExecutionResult,
    ExecutionPlan,
    ExecutionPlanBuilder,
    ExecutionStatus,
    TransactionPriority,
    GasConfig,
    RetryConfig,
    get_execution_engine,
    init_execution_engine
)
from services.risk_control import (
    RiskController,
    RiskCheckResult,
    RiskLimits,
    TradeContext,
    EmergencyState,
    get_risk_controller,
    init_risk_controller
)

logger = logging.getLogger(__name__)


# ============================================
# Pydantic 模型定义
# ============================================

class CreateWalletRequest(BaseModel):
    """创建钱包请求"""
    name: str = Field(..., min_length=1, max_length=50, description="钱包名称")
    password: str = Field(..., min_length=8, description="钱包密码")
    chains: Optional[List[str]] = Field(None, description="要支持的链列表")
    
    @validator('password')
    def validate_password(cls, v):
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


class ImportWalletRequest(BaseModel):
    """导入钱包请求"""
    name: str = Field(..., min_length=1, max_length=50, description="钱包名称")
    password: str = Field(..., min_length=8, description="钱包密码")
    private_key: Optional[str] = Field(None, description="私钥 (hex)")
    keystore_path: Optional[str] = Field(None, description="Keystore 文件路径")
    chains: Optional[List[str]] = Field(None, description="要支持的链列表")
    
    @validator('private_key', 'keystore_path')
    def validate_source(cls, v, values):
        if values.get('private_key') is None and v is None:
            raise ValueError("Must provide either private_key or keystore_path")
        return v


class UnlockWalletRequest(BaseModel):
    """解锁钱包请求"""
    password: str = Field(..., description="钱包密码")


class SwapRequest(BaseModel):
    """Swap 请求"""
    chain: str = Field(..., description="链名称")
    dex: str = Field(..., description="DEX 名称 (e.g., uniswap_v3, pancakeswap)")
    token_in: str = Field(..., description="输入代币地址")
    token_out: str = Field(..., description="输出代币地址")
    amount_in: Optional[int] = Field(None, description="输入金额 (最小单位)")
    amount_out_min: Optional[int] = Field(None, description="最小输出金额")
    slippage_bps: int = Field(100, ge=1, le=10000, description="滑点容忍 (basis points)")
    priority: str = Field("normal", description="优先级: low, normal, high, urgent")
    wait_confirm: bool = Field(True, description="是否等待确认")
    
    @validator('priority')
    def validate_priority(cls, v):
        allowed = ["low", "normal", "high", "urgent"]
        if v.lower() not in allowed:
            raise ValueError(f"Priority must be one of {allowed}")
        return v.lower()


class CrossChainSwapRequest(BaseModel):
    """跨链Swap请求"""
    source_chain: str = Field(..., description="源链")
    target_chain: str = Field(..., description="目标链")
    bridge: str = Field(..., description="跨链桥: layerzero, wormhole")
    token_in: str = Field(..., description="输入代币地址")
    amount: int = Field(..., description="跨链金额 (最小单位)")
    min_amount_out: int = Field(0, description="目标链最小收到金额")
    recipient: str = Field(..., description="目标链接收地址")
    slippage_bps: int = Field(100, ge=1, le=10000, description="滑点容忍")


class FlashLoanRequest(BaseModel):
    """闪电贷请求"""
    chain: str = Field(..., description="链名称")
    assets: List[str] = Field(..., description="要借的代币地址列表")
    amounts: List[int] = Field(..., description="要借的金额列表")
    profit_address: str = Field(..., description="利润接收地址")
    swap_data: List[Dict] = Field(..., description="Swap 操作数据")


class RiskCheckRequest(BaseModel):
    """风险检查请求"""
    chain: str
    from_address: str
    to_address: str
    token_in: str
    token_out: str
    amount_in_usd: float
    amount_out_estimated_usd: float
    slippage_pct: float
    gas_price_gwei: float
    estimated_gas_cost_usd: float
    estimated_profit_usd: float


class EmergencyStopRequest(BaseModel):
    """紧急停止请求"""
    action: str = Field(..., description="操作: stop, resume, warning")
    reason: Optional[str] = Field(None, description="原因")


# ============================================
# 响应模型
# ============================================

class WalletResponse(BaseModel):
    """钱包响应"""
    wallet_id: str
    name: str
    address: str
    addresses: Dict[str, str]
    created_at: str
    keystore_path: Optional[str] = None


class BalanceResponse(BaseModel):
    """余额响应"""
    chain: str
    address: str
    native_balance: float
    native_balance_usd: Optional[float] = None
    tokens: Dict[str, Dict[str, Any]]
    total_value_usd: float


class ExecutionResponse(BaseModel):
    """执行响应"""
    execution_id: str
    tx_hash: str
    chain: str
    status: str
    success: bool
    submitted_at: Optional[str] = None
    confirmed_at: Optional[str] = None
    gas_used: Optional[int] = None
    gas_cost_usd: Optional[float] = None
    error_message: Optional[str] = None


class RiskCheckResponse(BaseModel):
    """风险检查响应"""
    passed: bool
    risk_level: str
    risk_score: float
    checks: List[Dict]
    warnings: List[str]
    errors: List[str]
    recommended_action: str


class StatsResponse(BaseModel):
    """统计响应"""
    total_executions: int
    successful_executions: int
    failed_executions: int
    success_rate: float
    total_profit_usd: float
    total_cost_usd: float
    avg_profit_usd: float


# ============================================
# 路由定义
# ============================================

# 创建主路由
router = APIRouter(prefix="/api", tags=["Phase 2 - Execution"])


# ============================================
# 辅助函数
# ============================================

def get_current_wallet() -> WalletManager:
    """获取当前钱包管理器"""
    wallet = get_wallet_manager()
    if not wallet.evm_manager:
        raise HTTPException(status_code=401, detail="Wallet not loaded")
    return wallet


def get_engine() -> ExecutionEngine:
    """获取执行引擎"""
    return get_execution_engine()


def get_risk_ctrl() -> RiskController:
    """获取风险控制器"""
    return get_risk_controller()


def parse_priority(priority: str) -> TransactionPriority:
    """解析优先级"""
    mapping = {
        "low": TransactionPriority.LOW,
        "normal": TransactionPriority.NORMAL,
        "high": TransactionPriority.HIGH,
        "urgent": TransactionPriority.URGENT
    }
    return mapping.get(priority.lower(), TransactionPriority.NORMAL)


# ============================================
# 钱包管理路由
# ============================================

@router.post("/wallet/create", response_model=WalletResponse)
async def create_wallet(request: CreateWalletRequest):
    """
    创建新钱包
    
    - 生成随机私钥
    - 使用密码加密
    - 派生多链地址
    """
    try:
        wallet = get_wallet_manager()
        
        # 创建钱包
        wallet_info = wallet.create_wallet(
            name=request.name,
            password=request.password,
            chains=request.chains
        )
        
        # 获取主地址
        main_address = ""
        for chain, addr in wallet_info.addresses.items():
            if addr:
                main_address = addr.address
                break
        
        return WalletResponse(
            wallet_id=wallet_info.wallet_id,
            name=wallet_info.name,
            address=main_address,
            addresses={chain: addr.address for chain, addr in wallet_info.addresses.items()},
            created_at=wallet_info.created_at.isoformat(),
            keystore_path=wallet_info.keystore_path
        )
        
    except Exception as e:
        logger.error(f"Failed to create wallet: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/wallet/import", response_model=WalletResponse)
async def import_wallet(request: ImportWalletRequest):
    """
    导入钱包
    
    - 支持私钥导入
    - 支持 Keystore 文件导入
    """
    try:
        wallet = get_wallet_manager()
        
        # 导入钱包
        wallet_info = wallet.import_wallet(
            private_key=request.private_key,
            keystore_path=request.keystore_path,
            name=request.name,
            chains=request.chains
        )
        
        # 尝试用密码解锁
        wallet.unlock(request.password)
        
        # 获取主地址
        main_address = ""
        for chain, addr in wallet_info.addresses.items():
            if addr:
                main_address = addr.address
                break
        
        return WalletResponse(
            wallet_id=wallet_info.wallet_id,
            name=wallet_info.name,
            address=main_address,
            addresses={chain: addr.address for chain, addr in wallet_info.addresses.items()},
            created_at=wallet_info.created_at.isoformat(),
            keystore_path=wallet_info.keystore_path
        )
        
    except Exception as e:
        logger.error(f"Failed to import wallet: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/wallet/unlock")
async def unlock_wallet(request: UnlockWalletRequest):
    """
    解锁钱包
    
    - 使用密码解锁 keystore
    """
    try:
        wallet = get_wallet_manager()
        
        if not wallet.wallet_info:
            raise HTTPException(status_code=400, detail="No wallet loaded")
        
        success = wallet.unlock(request.password)
        
        if success:
            return {"status": "unlocked", "address": wallet.evm_manager.checksum_address}
        else:
            raise HTTPException(status_code=401, detail="Invalid password")
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to unlock wallet: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/wallet/lock")
async def lock_wallet():
    """锁定钱包"""
    try:
        wallet = get_wallet_manager()
        wallet.lock()
        return {"status": "locked"}
    except Exception as e:
        logger.error(f"Failed to lock wallet: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/wallet/balance/{chain}", response_model=BalanceResponse)
async def get_balance(chain: str):
    """
    查询余额
    
    - 原生代币余额
    - ERC20 代币余额
    """
    try:
        wallet = get_current_wallet()
        balance = wallet.get_balance(chain)
        
        return BalanceResponse(
            chain=balance.chain,
            address=balance.address,
            native_balance=balance.native_balance,
            tokens=balance.tokens,
            total_value_usd=balance.total_value_usd
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get balance: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/wallet/info")
async def get_wallet_info():
    """获取钱包信息"""
    try:
        wallet = get_current_wallet()
        
        if not wallet.wallet_info:
            raise HTTPException(status_code=400, detail="No wallet loaded")
        
        return wallet.wallet_info.to_dict()
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get wallet info: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# 交易执行路由
# ============================================

@router.post("/execute/swap", response_model=ExecutionResponse)
async def execute_swap(request: SwapRequest, background_tasks: BackgroundTasks):
    """
    执行单链 Swap
    
    - 构建交易
    - 执行风险检查
    - 提交交易
    """
    try:
        wallet = get_current_wallet()
        engine = get_engine()
        risk_ctrl = get_risk_ctrl()
        
        # 检查 DEX 是否可用
        if request.dex not in DEX_ROUTERS.get(request.chain, {}):
            raise HTTPException(status_code=400, detail=f"DEX {request.dex} not available on {request.chain}")
        
        # 构建交易
        builder = TransactionBuilder(request.chain)
        builder.set_sender(wallet.evm_manager.checksum_address)
        
        # 获取 DEX builder
        dex_builder = builder.get_dex_builder(request.dex)
        if not dex_builder:
            raise HTTPException(status_code=400, detail=f"DEX {request.dex} not found")
        
        # 构建 swap 参数
        from web3 import Web3
        
        swap_params = SwapParams(
            token_in=Web3.to_checksum_address(request.token_in),
            token_out=Web3.to_checksum_address(request.token_out),
            amount_in=request.amount_in,
            amount_out_min=request.amount_out_min,
            recipient=wallet.evm_manager.checksum_address,
            deadline=int(datetime.now().timestamp()) + 600
        )
        
        # 构建交易
        tx_params = await builder.build_swap_transaction(
            dex_name=request.dex,
            params=swap_params,
            sender=wallet.evm_manager.checksum_address
        )
        
        # 风险检查
        risk_result = await risk_ctrl.perform_risk_check(
            context=TradeContext(
                chain=request.chain,
                from_address=tx_params.from_address,
                to_address=tx_params.to_address,
                token_in=request.token_in,
                token_out=request.token_out,
                amount_in=request.amount_in or 0,
                amount_out_estimated=request.amount_out_min or 0,
                amount_out_min=request.amount_out_min or 0,
                expected_price=0,
                actual_price=0,
                slippage_pct=request.slippage_bps / 100,
                gas_price_gwei=0,
                gas_limit=tx_params.gas_limit,
                estimated_gas_cost_usd=0,
                estimated_profit_usd=0
            ),
            available_balance=wallet.get_balance(request.chain).native_balance
        )
        
        if not risk_result.passed:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "Risk check failed",
                    "errors": risk_result.errors,
                    "warnings": risk_result.warnings,
                    "risk_score": risk_result.risk_score
                }
            )
        
        # 提交交易
        result = await engine.execute_swap(
            chain=request.chain,
            tx_params=tx_params,
            wait_confirm=request.wait_confirm,
            priority=parse_priority(request.priority)
        )
        
        # 记录执行结果
        risk_ctrl.record_execution(
            chain=request.chain,
            amount_usd=0,
            profit_usd=0,
            cost_usd=result.gas_cost_usd or 0,
            gas_used=result.gas_used or 0,
            success=result.success
        )
        
        return ExecutionResponse(
            execution_id=result.tx_hash[:16],
            tx_hash=result.tx_hash,
            chain=result.chain,
            status=result.status.value,
            success=result.success,
            submitted_at=result.submitted_at.isoformat() if result.submitted_at else None,
            confirmed_at=result.confirmed_at.isoformat() if result.confirmed_at else None,
            gas_used=result.gas_used,
            gas_cost_usd=result.gas_cost_usd,
            error_message=result.error_message or result.revert_reason
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Swap execution failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/execute/cross-chain", response_model=ExecutionResponse)
async def execute_cross_chain_swap(request: CrossChainSwapRequest):
    """
    执行跨链 Swap
    
    - 使用 LayerZero 或 Wormhole
    """
    try:
        wallet = get_current_wallet()
        engine = get_engine()
        
        # 构建跨链交易
        cross_builder = CrossChainTransactionBuilder(
            source_chain=request.source_chain,
            target_chain=request.target_chain
        )
        
        tx_params = cross_builder.build_layerzero_send_transaction(
            token_address=request.token_in,
            amount=request.amount,
            recipient_address=request.recipient,
            min_amount_out=request.min_amount_out,
            gas_limit=300000
        )
        
        # 提交交易
        result = await engine.execute_swap(
            chain=request.source_chain,
            tx_params=tx_params,
            wait_confirm=True
        )
        
        return ExecutionResponse(
            execution_id=result.tx_hash[:16],
            tx_hash=result.tx_hash,
            chain=result.chain,
            status=result.status.value,
            success=result.success,
            submitted_at=result.submitted_at.isoformat() if result.submitted_at else None,
            confirmed_at=result.confirmed_at.isoformat() if result.confirmed_at else None,
            gas_used=result.gas_used,
            gas_cost_usd=result.gas_cost_usd,
            error_message=result.error_message
        )
        
    except Exception as e:
        logger.error(f"Cross-chain swap failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/execute/flash-loan")
async def execute_flash_loan(request: FlashLoanRequest):
    """
    执行闪电贷套利
    
    - 使用 Aave V3 闪电贷
    - 执行套利步骤
    - 归还贷款并提取利润
    """
    try:
        wallet = get_current_wallet()
        engine = get_engine()
        
        # 执行闪电贷套利
        success, results = await engine.execute_flash_loan_arbitrage(
            chain=request.chain,
            flash_loan_params={
                "assets": request.assets,
                "amounts": request.amounts
            },
            swap_steps=[],  # 从请求中构建
            profit_address=request.profit_address
        )
        
        return {
            "success": success,
            "results": [r.to_dict() for r in results]
        }
        
    except Exception as e:
        logger.error(f"Flash loan execution failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/execution/status/{tx_hash}")
async def get_execution_status(tx_hash: str, chain: str = Query(...)):
    """
    查询执行状态
    
    - 交易哈希
    - 所属链
    """
    try:
        sender = get_engine()._senders.get(chain)
        if not sender:
            raise HTTPException(status_code=404, detail="Chain not found")
        
        # 检查本地缓存
        for pending in sender.tracker._pending_txs.values():
            if pending.tx_hash == tx_hash:
                return pending.to_dict()
        
        # 从链上获取
        status, receipt = await sender.tracker.check_status(tx_hash)
        
        return {
            "tx_hash": tx_hash,
            "chain": chain,
            "status": status.value,
            "confirmed": status == ExecutionStatus.CONFIRMED
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# 风险控制路由
# ============================================

@router.post("/risk/check", response_model=RiskCheckResponse)
async def check_risk(request: RiskCheckRequest):
    """
    执行风险检查
    
    - 金额限制
    - 滑点检查
    - Gas 价格检查
    - 每日限制
    """
    try:
        risk_ctrl = get_risk_controller()
        
        result = await risk_ctrl.perform_risk_check(
            context=TradeContext(
                chain=request.chain,
                from_address=request.from_address,
                to_address=request.to_address,
                token_in=request.token_in,
                token_out=request.token_out,
                amount_in=request.amount_in_usd,
                amount_out_estimated=request.amount_out_estimated_usd,
                amount_out_min=0,
                expected_price=0,
                actual_price=0,
                slippage_pct=request.slippage_pct,
                gas_price_gwei=request.gas_price_gwei,
                gas_limit=0,
                estimated_gas_cost_usd=request.estimated_gas_cost_usd,
                estimated_profit_usd=request.estimated_profit_usd
            )
        )
        
        return RiskCheckResponse(
            passed=result.passed,
            risk_level=result.risk_level.value,
            risk_score=result.risk_score,
            checks=result.checks,
            warnings=result.warnings,
            errors=result.errors,
            recommended_action=result.recommended_action
        )
        
    except Exception as e:
        logger.error(f"Risk check failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/risk/emergency")
async def emergency_action(request: EmergencyStopRequest):
    """
    紧急操作
    
    - stop: 立即停止所有交易
    - resume: 恢复交易
    - warning: 切换到警告模式
    """
    try:
        risk_ctrl = get_risk_controller()
        
        if request.action == "stop":
            risk_ctrl.emergency.stop(request.reason or "Manual stop")
        elif request.action == "resume":
            risk_ctrl.emergency.resume(request.reason or "Manual resume")
        elif request.action == "warning":
            risk_ctrl.emergency.warning(request.reason or "Manual warning")
        else:
            raise HTTPException(status_code=400, detail="Invalid action")
        
        return {
            "status": "success",
            "action": request.action,
            "state": risk_ctrl.emergency.state.value,
            "reason": request.reason
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Emergency action failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/risk/stats")
async def get_risk_stats():
    """获取风险统计"""
    try:
        risk_ctrl = get_risk_controller()
        return risk_ctrl.get_stats()
    except Exception as e:
        logger.error(f"Failed to get stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# 统计路由
# ============================================

@router.get("/stats", response_model=StatsResponse)
async def get_stats():
    """获取执行统计"""
    try:
        engine = get_engine()
        stats = engine.get_stats()
        
        return StatsResponse(**stats)
        
    except Exception as e:
        logger.error(f"Failed to get stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/execution/history")
async def get_execution_history(limit: int = Query(10, ge=1, le=100)):
    """获取执行历史"""
    try:
        engine = get_engine()
        history = engine.get_execution_history(limit)
        return {"history": [h.to_dict() for h in history]}
    except Exception as e:
        logger.error(f"Failed to get history: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/execution/pending")
async def get_pending_transactions(chain: Optional[str] = None):
    """获取待确认交易"""
    try:
        engine = get_engine()
        pending = engine.get_pending_transactions(chain)
        return {"pending": [p.to_dict() for p in pending]}
    except Exception as e:
        logger.error(f"Failed to get pending: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# DEX 信息路由
# ============================================

@router.get("/dex/list/{chain}")
async def list_dex(chain: str):
    """列出链上可用的 DEX"""
    try:
        if chain not in DEX_ROUTERS:
            return {"dexes": []}
        
        dexes = []
        for name, config in DEX_ROUTERS[chain].items():
            dexes.append({
                "name": config.name,
                "type": config.type.value,
                "router_address": config.router_address,
                "quoter_address": config.quoter_address
            })
        
        return {"chain": chain, "dexes": dexes}
        
    except Exception as e:
        logger.error(f"Failed to list DEX: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tokens/{chain}")
async def get_common_tokens(chain: str):
    """获取常用代币列表"""
    try:
        from services.wallet_manager import EVMWalletManager
        
        if chain in EVMWalletManager.COMMON_TOKENS:
            return {
                "chain": chain,
                "tokens": EVMWalletManager.COMMON_TOKENS[chain]
            }
        return {"chain": chain, "tokens": {}}
        
    except Exception as e:
        logger.error(f"Failed to get tokens: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# Solana 专用路由
# ============================================

# Solana 导入
try:
    from services.wallet_manager import SolanaWalletManager, SOLANA_SUPPORT
    from services.solana_tx_builder import (
        SolanaSwapBuilder,
        JupiterClient,
        SwapMode,
        get_token_mint
    )
    from services.solana_execution_engine import (
        SolanaExecutionEngine,
        SolanaExecutionStatus,
        get_solana_execution_engine
    )
except ImportError as e:
    logger.warning(f"Solana modules not available: {e}")
    SOLANA_SUPPORT = False


# Solana 请求模型
class SolanaCreateWalletRequest(BaseModel):
    """创建 Solana 钱包请求"""
    name: str = Field(..., min_length=1, max_length=50, description="钱包名称")
    password: Optional[str] = Field(None, description="加密密码（可选）")


class SolanaImportWalletRequest(BaseModel):
    """导入 Solana 钱包请求"""
    name: str = Field(..., min_length=1, max_length=50, description="钱包名称")
    private_key: Optional[str] = Field(None, description="私钥（hex）")
    keystore_path: Optional[str] = Field(None, description="Keystore 文件路径")
    password: Optional[str] = Field(None, description="Keystore 密码")


class SolanaSwapRequest(BaseModel):
    """Solana Swap 请求"""
    input_token: str = Field(..., description="输入代币符号或 Mint 地址")
    output_token: str = Field(..., description="输出代币符号或 Mint 地址")
    amount: int = Field(..., gt=0, description="输入金额（最小单位）")
    slippage_bps: int = Field(50, ge=1, le=5000, description="滑点容忍度 (basis points)")
    priority_fee_lamports: Optional[int] = Field(None, description="优先费用 (lamports)")
    wait_confirm: bool = Field(True, description="是否等待确认")


class JupiterQuoteRequest(BaseModel):
    """Jupiter Quote 请求"""
    input_token: str = Field(..., description="输入代币符号或 Mint 地址")
    output_token: str = Field(..., description="输出代币符号或 Mint 地址")
    amount: int = Field(..., gt=0, description="金额（最小单位）")
    slippage_bps: int = Field(50, ge=1, le=5000, description="滑点容忍度")
    swap_mode: str = Field("exactIn", description="Swap 模式: exactIn 或 exactOut")


# Solana 响应模型
class SolanaWalletResponse(BaseModel):
    """Solana 钱包响应"""
    name: str
    address: str
    sol_balance: float
    tokens: Dict[str, Any] = {}
    created_at: Optional[str] = None


class SolanaSwapResponse(BaseModel):
    """Solana Swap 响应"""
    success: bool
    signature: Optional[str] = None
    input_token: str
    output_token: str
    input_amount: int
    output_amount: int
    price_impact_pct: float
    dexes_used: List[str] = []
    fee_lamports: int = 0
    status: str
    error_message: Optional[str] = None
    explorer_url: Optional[str] = None


class JupiterQuoteResponse(BaseModel):
    """Jupiter Quote 响应"""
    input_mint: str
    output_mint: str
    input_amount: int
    output_amount: int
    price_impact_pct: float
    other_amount_threshold: int
    route_plan: List[Dict]
    dexes_used: List[str]


# Solana 钱包管理路由
@router.post("/solana/wallet/create", response_model=SolanaWalletResponse)
async def create_solana_wallet(request: SolanaCreateWalletRequest):
    """
    创建 Solana 钱包
    
    - 生成新的 Ed25519 密钥对
    - 可选使用密码加密保存
    """
    if not SOLANA_SUPPORT:
        raise HTTPException(status_code=501, detail="Solana support not available")
    
    try:
        # 创建新的 Solana 钱包
        wallet = SolanaWalletManager()
        
        # 保存 keystore（如果提供了密码）
        keystore_path = None
        if request.password:
            from pathlib import Path
            keystore_dir = Path.home() / ".wallet_keystore" / "solana"
            keystore_dir.mkdir(parents=True, exist_ok=True)
            keystore_path = keystore_dir / f"solana_{wallet.address[:8]}.json"
            wallet.save_keystore(str(keystore_path), request.password)
        
        # 获取余额
        sol_balance, _ = wallet.get_sol_balance()
        tokens = wallet.get_all_token_balances()
        
        return SolanaWalletResponse(
            name=request.name,
            address=wallet.address,
            sol_balance=sol_balance,
            tokens=tokens,
            created_at=datetime.now().isoformat()
        )
        
    except Exception as e:
        logger.error(f"Failed to create Solana wallet: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/solana/wallet/import", response_model=SolanaWalletResponse)
async def import_solana_wallet(request: SolanaImportWalletRequest):
    """
    导入 Solana 钱包
    
    - 支持私钥导入
    - 支持 Keystore 文件导入
    """
    if not SOLANA_SUPPORT:
        raise HTTPException(status_code=501, detail="Solana support not available")
    
    try:
        wallet = None
        
        if request.private_key:
            # 从私钥导入
            wallet = SolanaWalletManager.from_private_key_hex(request.private_key)
        elif request.keystore_path:
            # 从 keystore 导入
            wallet = SolanaWalletManager.load_keystore(
                request.keystore_path,
                request.password
            )
        else:
            raise HTTPException(status_code=400, detail="Must provide private_key or keystore_path")
        
        # 获取余额
        sol_balance, _ = wallet.get_sol_balance()
        tokens = wallet.get_all_token_balances()
        
        return SolanaWalletResponse(
            name=request.name,
            address=wallet.address,
            sol_balance=sol_balance,
            tokens=tokens
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to import Solana wallet: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/solana/wallet/balance", response_model=SolanaWalletResponse)
async def get_solana_balance(address: str = Query(..., description="Solana 地址")):
    """
    查询 Solana 钱包余额
    
    - SOL 余额
    - SPL Token 余额
    """
    if not SOLANA_SUPPORT:
        raise HTTPException(status_code=501, detail="Solana support not available")
    
    try:
        # 创建只读钱包管理器（不需要私钥）
        from solders.pubkey import Pubkey as SolanaPubkey
        
        # 使用公开信息创建
        wallet = SolanaWalletManager()
        
        # 获取 SOL 余额
        sol_balance, lamports = wallet.get_sol_balance()
        tokens = wallet.get_all_token_balances()
        
        return SolanaWalletResponse(
            name="Query Wallet",
            address=address,
            sol_balance=sol_balance,
            tokens=tokens
        )
        
    except Exception as e:
        logger.error(f"Failed to get Solana balance: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/solana/dex/list")
async def list_solana_dex():
    """列出 Solana 上支持的 DEX"""
    if not SOLANA_SUPPORT:
        raise HTTPException(status_code=501, detail="Solana support not available")
    
    try:
        from config.solana_dex import SupportedDEX
        
        dexes = []
        for key, dex in SupportedDEX.ALL_DEX.items():
            dexes.append({
                "id": key,
                "name": dex.name,
                "version": dex.version,
                "description": dex.description,
                "program_id": dex.program_id
            })
        
        return {"dexes": dexes}
        
    except Exception as e:
        logger.error(f"Failed to list DEX: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/solana/tokens")
async def list_solana_tokens():
    """列出 Solana 常用代币"""
    if not SOLANA_SUPPORT:
        raise HTTPException(status_code=501, detail="Solana support not available")
    
    try:
        from config.solana_dex import SolanaTokens, SolanaTokens as TokenConfig
        
        tokens = []
        for symbol, mint in SolanaTokens.ALL_TOKENS.items():
            decimals = TokenConfig.TOKEN_DECIMALS.get(mint, 9)
            tokens.append({
                "symbol": symbol,
                "mint": mint,
                "decimals": decimals
            })
        
        return {"tokens": tokens}
        
    except Exception as e:
        logger.error(f"Failed to list tokens: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/solana/execute/quote", response_model=JupiterQuoteResponse)
async def get_jupiter_quote(request: JupiterQuoteRequest):
    """
    获取 Jupiter Quote
    
    - 获取最佳交易路径和报价
    - 不执行交易
    """
    if not SOLANA_SUPPORT:
        raise HTTPException(status_code=501, detail="Solana support not available")
    
    try:
        swap_mode = SwapMode.EXACT_IN if request.swap_mode == "exactIn" else SwapMode.EXACT_OUT
        
        async with JupiterClient() as jupiter:
            # 解析代币
            input_mint = get_token_mint(request.input_token) if len(request.input_token) < 44 else request.input_token
            output_mint = get_token_mint(request.output_token) if len(request.output_token) < 44 else request.output_token
            
            quote = await jupiter.get_quote(
                input_mint=input_mint,
                output_mint=output_mint,
                amount=request.amount,
                slippage_bps=request.slippage_bps,
                swap_mode=swap_mode
            )
            
            return JupiterQuoteResponse(
                input_mint=quote.input_mint,
                output_mint=quote.output_mint,
                input_amount=quote.input_amount,
                output_amount=quote.output_amount,
                price_impact_pct=quote.price_impact_pct,
                other_amount_threshold=quote.other_amount_threshold,
                route_plan=quote.route_plan,
                dexes_used=quote.dexes_used
            )
        
    except Exception as e:
        logger.error(f"Failed to get Jupiter quote: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/solana/execute/swap", response_model=SolanaSwapResponse)
async def execute_solana_swap(request: SolanaSwapRequest):
    """
    执行 Solana Swap (通过 Jupiter)
    
    - 获取最佳路径
    - 构建交易
    - 签名并发送
    """
    if not SOLANA_SUPPORT:
        raise HTTPException(status_code=501, detail="Solana support not available")
    
    try:
        # 需要获取签名者
        # 注意：实际使用中需要从钱包管理器获取签名者
        # 这里需要结合钱包导入来使用
        
        return SolanaSwapResponse(
            success=False,
            input_token=request.input_token,
            output_token=request.output_token,
            input_amount=request.amount,
            output_amount=0,
            price_impact_pct=0,
            status="pending",
            error_message="Wallet not connected. Please import wallet first."
        )
        
    except Exception as e:
        logger.error(f"Failed to execute Solana swap: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/solana/execution/status/{signature}")
async def get_solana_execution_status(signature: str):
    """
    查询 Solana 交易状态
    
    - 交易签名
    - 确认状态
    - 手续费
    """
    if not SOLANA_SUPPORT:
        raise HTTPException(status_code=501, detail="Solana support not available")
    
    try:
        engine = get_solana_execution_engine()
        result = engine.get_execution_status(signature)
        
        if result is None:
            return {
                "signature": signature,
                "status": "not_found",
                "message": "Transaction not found"
            }
        
        explorer_url = f"https://solscan.io/tx/{signature}"
        
        return {
            "signature": signature,
            "status": result.status.value,
            "success": result.status in [SolanaExecutionStatus.CONFIRMED, SolanaExecutionStatus.FINALIZED],
            "block_height": result.block_height,
            "slot": result.slot,
            "fee_lamports": result.fee,
            "fee_sol": result.fee / 1e9,
            "logs": result.logs[:10] if result.logs else [],  # 只返回前10条日志
            "error_message": result.error_message,
            "submitted_at": result.submitted_at.isoformat() if result.submitted_at else None,
            "confirmed_at": result.confirmed_at.isoformat() if result.confirmed_at else None,
            "finalized_at": result.finalized_at.isoformat() if result.finalized_at else None,
            "execution_time_ms": result.execution_time_ms,
            "explorer_url": explorer_url
        }
        
    except Exception as e:
        logger.error(f"Failed to get Solana execution status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/solana/price")
async def get_token_prices(mints: str = Query(..., description="代币 Mint 地址列表，逗号分隔")):
    """
    获取代币价格
    
    - 使用 Jupiter Price API
    - 以 USDC 计价
    """
    if not SOLANA_SUPPORT:
        raise HTTPException(status_code=501, detail="Solana support not available")
    
    try:
        mint_list = [m.strip() for m in mints.split(",")]
        
        async with JupiterClient() as jupiter:
            prices = await jupiter.get_price(mint_list)
            
            return {
                "prices": prices,
                "unit": "USDC"
            }
        
    except Exception as e:
        logger.error(f"Failed to get token prices: {e}")
        raise HTTPException(status_code=500, detail=str(e))



# ============================================
# Sui 链支持路由
# ============================================

# 尝试导入 Sui 模块
try:
    from services.sui_wallet_manager import (
        SuiWalletManager,
        SuiRpcClient,
        SuiKeyPair,
        SUI_SUPPORT,
        get_sui_wallet_manager,
        init_sui_wallet_manager,
    )
    from services.sui_tx_builder import (
        SuiTransactionBuilder,
        SuiSwapQuote,
    )
    from services.sui_execution_engine import (
        SuiExecutionEngine,
        SuiExecutionStatus,
        get_sui_execution_engine,
    )
    _SUI_SUPPORT = True
except ImportError:
    _SUI_SUPPORT = False
    logger.warning("Sui modules not available")


@router.post("/sui/wallet/create")
async def create_sui_wallet():
    """
    创建 Sui 钱包
    
    - 生成随机私钥
    - 派生 Sui 地址 (Ed25519)
    """
    if not _SUI_SUPPORT:
        raise HTTPException(status_code=501, detail="Sui support not available")
    
    try:
        wallet = SuiWalletManager()
        wallet_info = wallet.create_wallet()
        
        return {
            "status": "success",
            "address": wallet_info.address.address,
            "public_key": wallet_info.address.public_key_hex,
            "short_address": wallet_info.address.short_address,
            "wallet_id": wallet_info.wallet_id,
            "name": wallet_info.name
        }
        
    except Exception as e:
        logger.error(f"Failed to create Sui wallet: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sui/wallet/import")
async def import_sui_wallet(private_key: str = Body(..., description="私钥 (hex)")):
    """
    导入 Sui 钱包
    
    Args:
        private_key: 私钥 (hex 格式)
    """
    if not _SUI_SUPPORT:
        raise HTTPException(status_code=501, detail="Sui support not available")
    
    try:
        wallet = SuiWalletManager()
        wallet_info = wallet.import_wallet(private_key)
        
        return {
            "status": "success",
            "address": wallet_info.address.address,
            "public_key": wallet_info.address.public_key_hex,
            "short_address": wallet_info.address.short_address,
            "wallet_id": wallet_info.wallet_id,
            "name": wallet_info.name
        }
        
    except Exception as e:
        logger.error(f"Failed to import Sui wallet: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sui/wallet/balance")
async def get_sui_balance(address: str = Query(..., description="Sui 地址")):
    """
    查询 Sui 余额
    
    - 原生 SUI 余额
    - 其他 Coin 余额
    """
    if not _SUI_SUPPORT:
        raise HTTPException(status_code=501, detail="Sui support not available")
    
    try:
        wallet = SuiWalletManager()
        
        # 获取 SUI 余额
        balance_info = wallet.rpc_client.get_balance(address)
        
        return {
            "address": address,
            "sui_balance": int(balance_info.get("totalBalance", 0)),
            "sui_balance_readable": int(balance_info.get("totalBalance", 0)) / 1e9,
            "coin_type": balance_info.get("coinType", "0x2::sui::SUI")
        }
        
    except Exception as e:
        logger.error(f"Failed to get Sui balance: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sui/execute/swap")
async def execute_sui_swap(
    request: Dict = Body(...),
    background_tasks: BackgroundTasks = None
):
    """
    执行 Sui Swap
    
    Args:
        private_key: 私钥
        dex: DEX 名称 (cetus, afterglow, flowx)
        token_in: 输入代币类型
        token_out: 输出代币类型
        amount_in: 输入金额
        slippage_bps: 滑点容忍 (默认 50 bps)
    """
    if not _SUI_SUPPORT:
        raise HTTPException(status_code=501, detail="Sui support not available")
    
    try:
        private_key = request.get("private_key")
        dex = request.get("dex", "cetus")
        token_in = request.get("token_in")
        token_out = request.get("token_out")
        amount_in = request.get("amount_in")
        slippage_bps = request.get("slippage_bps", 50)
        
        if not all([private_key, token_in, token_out, amount_in]):
            raise HTTPException(status_code=400, detail="Missing required parameters")
        
        # 创建钱包
        wallet = SuiWalletManager()
        keypair = SuiKeyPair.from_private_key(private_key)
        
        # 构建交易
        builder = SuiTransactionBuilder()
        builder.set_sender(keypair.address)
        
        # 构建 Swap
        tx_bytes = builder.build_swap_transaction(
            dex_name=dex,
            token_in=token_in,
            token_out=token_out,
            amount_in=amount_in,
            slippage_bps=slippage_bps,
            sender=keypair.address
        )
        
        # 签名
        signature = keypair.sign_transaction(tx_bytes)
        
        # 提交
        engine = SuiExecutionEngine()
        result = engine.execute_transaction_sync(tx_bytes, signature)
        
        return {
            "status": "success",
            "digest": result.get("digest", ""),
            "status": result.get("effects", {}).get("status", {}).get("status", "unknown"),
            "explorer_url": f"https://suiexplorer.com/txblock/{result.get('digest', '')}"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to execute Sui swap: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sui/execution/status/{digest}")
async def get_sui_execution_status(digest: str):
    """
    查询 Sui 交易状态
    
    Args:
        digest: 交易摘要
    """
    if not _SUI_SUPPORT:
        raise HTTPException(status_code=501, detail="Sui support not available")
    
    try:
        wallet = SuiWalletManager()
        result = wallet.rpc_client.get_transaction(digest)
        
        if not result:
            return {
                "digest": digest,
                "status": "not_found",
                "message": "Transaction not found"
            }
        
        effects = result.get("effects", {})
        status = effects.get("status", {}).get("status", "unknown")
        
        return {
            "digest": digest,
            "status": status,
            "success": status == "success",
            "gas_used": effects.get("gasUsed", {}).get("gasBudget", 0),
            "gas_fee": effects.get("gasUsed", {}).get("totalGas", 0),
            "explorer_url": f"https://suiexplorer.com/txblock/{digest}"
        }
        
    except Exception as e:
        logger.error(f"Failed to get Sui execution status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# Aptos 链支持路由
# ============================================

# 尝试导入 Aptos 模块
try:
    from services.aptos_wallet_manager import (
        AptosWalletManager,
        AptosRpcClient,
        AptosKeyPair,
        get_aptos_wallet_manager,
        init_aptos_wallet_manager,
    )
    from services.aptos_tx_builder import (
        AptosTransactionBuilder,
    )
    from services.aptos_execution_engine import (
        AptosExecutionEngine,
        AptosExecutionStatus,
        get_aptos_execution_engine,
        init_aptos_execution_engine,
    )
    _APTOS_SUPPORT = True
except ImportError as e:
    _APTOS_SUPPORT = False
    logger.warning(f"Aptos modules not available: {e}")


class AptosSwapRequest(BaseModel):
    """Aptos Swap 请求"""
    private_key: str = Field(..., description="私钥 (hex)")
    dex: str = Field("liquidswap", description="DEX 名称 (liquidswap, thala)")
    token_in: str = Field(..., description="输入代币类型")
    token_out: str = Field(..., description="输出代币类型")
    amount_in: int = Field(..., description="输入金额 (最小单位)")
    slippage_bps: int = Field(50, ge=1, le=1000, description="滑点容忍 (basis points)")


class AptosTransferRequest(BaseModel):
    """Aptos 转账请求"""
    private_key: str = Field(..., description="私钥 (hex)")
    to_address: str = Field(..., description="接收地址")
    amount: int = Field(..., description="金额 (最小单位)")
    coin_type: str = Field("0x1::aptos_coin::AptosCoin", description="Coin 类型")


@router.post("/aptos/wallet/create")
async def create_aptos_wallet():
    """
    创建 Aptos 钱包
    
    - 生成随机私钥
    - 派生 Aptos 地址 (Ed25519)
    """
    if not _APTOS_SUPPORT:
        raise HTTPException(status_code=501, detail="Aptos support not available")
    
    try:
        wallet = AptosWalletManager()
        wallet_info = wallet.create_wallet()
        
        return {
            "status": "success",
            "address": wallet_info.address.address,
            "public_key": wallet_info.address.public_key_hex,
            "short_address": wallet_info.address.short_address,
            "wallet_id": wallet_info.wallet_id,
            "name": wallet_info.name
        }
        
    except Exception as e:
        logger.error(f"Failed to create Aptos wallet: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/aptos/wallet/import")
async def import_aptos_wallet(private_key: str = Body(..., description="私钥 (hex)")):
    """
    导入 Aptos 钱包
    
    Args:
        private_key: 私钥 (hex 格式)
    """
    if not _APTOS_SUPPORT:
        raise HTTPException(status_code=501, detail="Aptos support not available")
    
    try:
        wallet = AptosWalletManager()
        wallet_info = wallet.import_wallet(private_key)
        
        return {
            "status": "success",
            "address": wallet_info.address.address,
            "public_key": wallet_info.address.public_key_hex,
            "short_address": wallet_info.address.short_address,
            "wallet_id": wallet_info.wallet_id,
            "name": wallet_info.name
        }
        
    except Exception as e:
        logger.error(f"Failed to import Aptos wallet: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/aptos/wallet/balance")
async def get_aptos_balance(
    address: str = Query(..., description="Aptos 地址"),
    coin_type: Optional[str] = Query(None, description="Coin 类型 (默认 APT)")
):
    """
    查询 Aptos 余额
    
    - APT 余额
    - 其他 Coin 余额
    """
    if not _APTOS_SUPPORT:
        raise HTTPException(status_code=501, detail="Aptos support not available")
    
    try:
        wallet = AptosWalletManager()
        
        # 获取余额
        balances = wallet.get_balance(address, coin_type)
        
        if not balances:
            return {
                "address": address,
                "coin_type": coin_type or "0x1::aptos_coin::AptosCoin",
                "balance": 0,
                "balance_readable": 0.0
            }
        
        result = {
            "address": address,
            "balances": [b.to_dict() for b in balances]
        }
        
        # 如果是 APT，添加特殊字段
        apt_balance = wallet.get_apt_balance(address)
        result["apt_balance"] = apt_balance
        result["apt_balance_readable"] = apt_balance / 1e8
        
        return result
        
    except Exception as e:
        logger.error(f"Failed to get Aptos balance: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/aptos/execute/swap", response_model=ExecutionResponse)
async def execute_aptos_swap(request: AptosSwapRequest):
    """
    执行 Aptos Swap
    
    - 构建 Liquidswap/Thala Swap 交易
    - 签名并提交
    - 等待确认
    """
    if not _APTOS_SUPPORT:
        raise HTTPException(status_code=501, detail="Aptos support not available")
    
    try:
        # 创建钱包
        wallet = AptosWalletManager()
        keypair = wallet.import_wallet(request.private_key)
        sender = keypair.address.address
        
        # 创建执行引擎
        engine = get_aptos_execution_engine()
        
        # 执行 Swap
        result = await engine.execute_swap(
            sender=sender,
            keypair=wallet._keypair,
            dex_name=request.dex,
            token_in=request.token_in,
            token_out=request.token_out,
            amount_in=request.amount_in,
            slippage_bps=request.slippage_bps
        )
        
        return ExecutionResponse(
            execution_id=result.hash,
            tx_hash=result.hash,
            chain="aptos",
            status=result.status.value,
            success=result.success,
            submitted_at=result.submitted_at.isoformat() if result.submitted_at else None,
            confirmed_at=result.confirmed_at.isoformat() if result.confirmed_at else None,
            gas_used=result.gas_used,
            gas_cost_usd=result.total_gas_cost / 1e8,
            error_message=result.error_message
        )
        
    except Exception as e:
        logger.error(f"Failed to execute Aptos swap: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/aptos/execute/transfer", response_model=ExecutionResponse)
async def execute_aptos_transfer(request: AptosTransferRequest):
    """
    执行 Aptos 转账
    
    - 构建 Coin 转账交易
    - 签名并提交
    - 等待确认
    """
    if not _APTOS_SUPPORT:
        raise HTTPException(status_code=501, detail="Aptos support not available")
    
    try:
        # 创建钱包
        wallet = AptosWalletManager()
        keypair = wallet.import_wallet(request.private_key)
        sender = keypair.address.address
        
        # 创建执行引擎
        engine = get_aptos_execution_engine()
        
        # 执行转账
        result = await engine.execute_coin_transfer(
            sender=sender,
            keypair=wallet._keypair,
            to_address=request.to_address,
            amount=request.amount,
            coin_type=request.coin_type
        )
        
        return ExecutionResponse(
            execution_id=result.hash,
            tx_hash=result.hash,
            chain="aptos",
            status=result.status.value,
            success=result.success,
            submitted_at=result.submitted_at.isoformat() if result.submitted_at else None,
            confirmed_at=result.confirmed_at.isoformat() if result.confirmed_at else None,
            gas_used=result.gas_used,
            gas_cost_usd=result.total_gas_cost / 1e8,
            error_message=result.error_message
        )
        
    except Exception as e:
        logger.error(f"Failed to execute Aptos transfer: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/aptos/execution/status/{tx_hash}")
async def get_aptos_execution_status(tx_hash: str):
    """
    查询 Aptos 交易状态
    
    Args:
        tx_hash: 交易哈希
    """
    if not _APTOS_SUPPORT:
        raise HTTPException(status_code=501, detail="Aptos support not available")
    
    try:
        engine = get_aptos_execution_engine()
        result = engine.get_execution_status(tx_hash)
        
        if result is None:
            return {
                "hash": tx_hash,
                "status": "not_found",
                "message": "Transaction not found"
            }
        
        return {
            "hash": tx_hash,
            "version": result.version,
            "status": result.status.value,
            "success": result.success,
            "gas_used": result.gas_used,
            "gas_unit_price": result.gas_unit_price,
            "gas_cost_octas": result.total_gas_cost,
            "gas_cost_apt": result.total_gas_cost / 1e8,
            "vm_status": result.vm_status,
            "error_message": result.error_message,
            "events_count": len(result.events),
            "submitted_at": result.submitted_at.isoformat() if result.submitted_at else None,
            "processed_at": result.processed_at.isoformat() if result.processed_at else None,
            "confirmed_at": result.confirmed_at.isoformat() if result.confirmed_at else None,
            "execution_time_ms": result.execution_time_ms,
            "explorer_url": result.explorer_url
        }
        
    except Exception as e:
        logger.error(f"Failed to get Aptos execution status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/aptos/price")
async def get_aptos_token_prices(
    symbols: str = Query(..., description="代币符号列表，逗号分隔")
):
    """
    获取 Aptos 代币价格
    
    - 使用外部价格 API
    - 以 USD 计价
    """
    if not _APTOS_SUPPORT:
        raise HTTPException(status_code=501, detail="Aptos support not available")
    
    try:
        symbol_list = [s.strip().upper() for s in symbols.split(",")]
        
        # 这里需要接入价格 API (如 CoinGecko)
        # 简化实现：返回模拟数据
        prices = {}
        for symbol in symbol_list:
            prices[symbol] = {
                "usd": 1.0,
                "change_24h": 0.0
            }
        
        return {
            "prices": prices,
            "unit": "USD",
            "source": "mock"
        }
        
    except Exception as e:
        logger.error(f"Failed to get Aptos token prices: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/aptos/pools")
async def get_aptos_pools(
    dex: str = Query("liquidswap", description="DEX 名称"),
    token0: Optional[str] = Query(None, description="代币0类型"),
    token1: Optional[str] = Query(None, description="代币1类型")
):
    """
    获取 Aptos DEX 池子信息
    
    Args:
        dex: DEX 名称 (liquidswap, thala)
        token0: 代币0类型 (可选)
        token1: 代币1类型 (可选)
    """
    if not _APTOS_SUPPORT:
        raise HTTPException(status_code=501, detail="Aptos support not available")
    
    try:
        # 这里需要查询 DEX 合约获取池子信息
        # 简化实现：返回示例数据
        pools = []
        
        if dex.lower() == "liquidswap":
            pools = [
                {
                    "pool_address": "0xexample_pool_1",
                    "token0": "0x1::aptos_coin::AptosCoin",
                    "token1": "0xf22bede237a07e121b56d91a491eb7bcdfd1f371792464a502a87400000000001::usdc::USDC",
                    "reserve0": "1000000000000000000",
                    "reserve1": "1000000000",
                    "fee_bps": 30,
                    "stable": False
                }
            ]
        
        return {
            "dex": dex,
            "pools": pools,
            "count": len(pools)
        }
        
    except Exception as e:
        logger.error(f"Failed to get Aptos pools: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# 多链统一接口
# ============================================

@router.get("/chains")
async def get_supported_chains():
    """
    获取支持的链列表
    
    Returns:
        支持的链及其状态
    """
    chains = {
        "evm": {
            "name": "Ethereum/兼容EVM链",
            "supported": True,
            "features": ["swap", "bridge", "flashloan"]
        },
        "solana": {
            "name": "Solana",
            "supported": SOLANA_SUPPORT,
            "features": ["swap", "jupiter"]
        },
        "sui": {
            "name": "Sui",
            "supported": _SUI_SUPPORT,
            "features": ["swap", "cetus", "aftermath"]
        },
        "aptos": {
            "name": "Aptos",
            "supported": _APTOS_SUPPORT,
            "features": ["swap", "liquidswap", "thala"]
        }
    }
    
    return {
        "chains": chains,
        "total": len(chains),
        "active": sum(1 for c in chains.values() if c["supported"])
    }
