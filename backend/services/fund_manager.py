"""
资金管理模块 - Phase 3 全自动执行核心组件

功能：
- 多链资金管理
- 资金分配和再平衡
- 跨链资金调度
- 仓位管理
- 收益追踪
- 资金安全（最大回撤、止损、紧急撤资）

设计原则：
- 安全第一：所有资金操作都有风险评估
- 实时监控：余额和仓位实时追踪
- 可配置：所有参数可调整
"""

import asyncio
import logging
from typing import Dict, List, Optional, Tuple, Any, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from collections import defaultdict
import json

import sys
import os as _os
_backend_dir = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from config.settings import SUPPORTED_CHAINS

logger = logging.getLogger(__name__)


# ============================================
# 枚举定义
# ============================================

class FundStatus(Enum):
    """资金状态"""
    ACTIVE = "active"
    FROZEN = "frozen"
    WITHDRAWING = "withdrawing"
    LOW_BALANCE = "low_balance"
    CRITICAL = "critical"


class AllocationStrategy(Enum):
    """分配策略"""
    EQUAL = "equal"                     # 平均分配
    BY_VOLUME = "by_volume"             # 按交易量分配
    BY_OPPORTUNITY = "by_opportunity"   # 按机会分配
    CUSTOM = "custom"                   # 自定义分配


class RebalanceTrigger(Enum):
    """再平衡触发条件"""
    TIME_BASED = "time_based"           # 时间触发
    THRESHOLD_BASED = "threshold_based" # 阈值触发
    MANUAL = "manual"                   # 手动触发
    EMERGENCY = "emergency"             # 紧急触发


# ============================================
# 数据类定义
# ============================================

@dataclass
class ChainFund:
    """单链资金信息"""
    chain: str
    address: str
    native_balance: float               # 原生代币余额 (USD)
    token_balances: Dict[str, float]   # 代币余额 {symbol: usd_value}
    available_for_trading: float        # 可用于交易的金额
    frozen: float = 0.0                 # 冻结金额
    locked: float = 0.0                 # 锁定金额（保证金等）
    
    @property
    def total_balance(self) -> float:
        """总余额"""
        return self.native_balance + sum(self.token_balances.values())
    
    @property
    def usable_balance(self) -> float:
        """可用余额"""
        return self.total_balance - self.frozen - self.locked


@dataclass
class Position:
    """仓位信息"""
    chain: str
    token: str
    amount: float                       # 数量
    value_usd: float                    # 美元价值
    entry_price: float                  # 入场价格
    current_price: float                # 当前价格
    pnl_usd: float = 0.0               # 盈亏 (USD)
    pnl_pct: float = 0.0                # 盈亏 (%)
    opened_at: datetime = field(default_factory=datetime.now)
    
    def update_pnl(self, current_price: float):
        """更新盈亏"""
        self.current_price = current_price
        self.pnl_usd = (current_price - self.entry_price) * self.amount
        self.pnl_pct = ((current_price - self.entry_price) / self.entry_price) * 100


@dataclass
class FundAllocation:
    """资金分配配置"""
    chain: str
    allocation_pct: float               # 分配比例 (0-1)
    min_balance_usd: float              # 最小余额
    max_balance_usd: float             # 最大余额
    target_balance_usd: float           # 目标余额
    reserved_pct: float = 0.1           # 预留比例


@dataclass
class RiskLimits:
    """风险限制"""
    max_position_usd: float = 10000.0    # 最大单仓位
    max_total_position_usd: float = 50000.0  # 最大总仓位
    max_single_trade_usd: float = 5000.0  # 单笔最大交易
    daily_loss_limit_usd: float = 1000.0  # 每日亏损限制
    max_drawdown_pct: float = 10.0       # 最大回撤比例
    emergency_withdraw_threshold: float = 20.0  # 紧急撤资阈值


@dataclass
class ProfitRecord:
    """收益记录"""
    id: str
    opportunity_id: str
    chain: str
    profit_usd: float
    profit_pct: float
    gas_cost_usd: float
    net_profit_usd: float
    executed_at: datetime
    execution_mode: str = "normal"       # normal / flash_loan


@dataclass
class FundSnapshot:
    """资金快照"""
    timestamp: datetime
    total_balance_usd: float
    chain_balances: Dict[str, float]
    positions: List[Position]
    daily_pnl_usd: float
    total_pnl_usd: float
    frozen_usd: float
    locked_usd: float


# ============================================
# 资金管理器
# ============================================

class FundManager:
    """资金管理器"""
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not hasattr(self, "_initialized"):
            self._initialized = True
            
            # 链资金映射
            self._chain_funds: Dict[str, ChainFund] = {}
            
            # 仓位映射
            self._positions: Dict[str, Position] = {}  # {position_id: Position}
            
            # 收益记录
            self._profit_records: List[ProfitRecord] = []
            
            # 分配配置
            self._allocations: Dict[str, FundAllocation] = {}
            
            # 风险限制
            self._risk_limits = RiskLimits()
            
            # 统计
            self._daily_stats = {
                "profit": 0.0,
                "loss": 0.0,
                "trades": 0,
            }
            self._total_pnl = 0.0
            self._peak_balance = 0.0
            self._current_drawdown = 0.0
            
            # 锁
            self._lock = asyncio.Lock()
            
            # 初始化默认分配
            self._init_default_allocations()
    
    def _init_default_allocations(self):
        """初始化默认分配"""
        default_chains = ["ethereum", "arbitrum", "optimism", "polygon", "bsc"]
        equal_pct = 1.0 / len(default_chains)
        
        for chain in default_chains:
            self._allocations[chain] = FundAllocation(
                chain=chain,
                allocation_pct=equal_pct,
                min_balance_usd=100.0,
                max_balance_usd=20000.0,
                target_balance_usd=10000.0,
            )
    
    async def initialize(self, wallet_manager=None):
        """初始化"""
        logger.info("FundManager initialized")
        
        if wallet_manager:
            await self._sync_with_wallet_manager(wallet_manager)
    
    async def _sync_with_wallet_manager(self, wallet_manager):
        """与钱包管理器同步"""
        for chain, config in SUPPORTED_CHAINS.items():
            if chain in self._allocations:
                # 获取余额
                try:
                    balance = await wallet_manager.get_balance(chain)
                    self.update_chain_balance(chain, balance)
                except Exception as e:
                    logger.warning(f"Failed to sync balance for {chain}: {e}")
    
    # ============================================
    # 链资金管理
    # ============================================
    
    def register_chain(self, chain: str, address: str, initial_balance: float = 0):
        """注册链资金"""
        if chain not in self._chain_funds:
            self._chain_funds[chain] = ChainFund(
                chain=chain,
                address=address,
                native_balance=initial_balance,
                token_balances={},
                available_for_trading=initial_balance,
            )
            logger.info(f"Registered chain fund: {chain}")
    
    def update_chain_balance(
        self,
        chain: str,
        native_balance: float = None,
        token_balances: Dict[str, float] = None
    ):
        """更新链余额"""
        fund = self._chain_funds.get(chain)
        if not fund:
            logger.warning(f"Chain not registered: {chain}")
            return
        
        if native_balance is not None:
            fund.native_balance = native_balance
        
        if token_balances is not None:
            fund.token_balances = token_balances
        
        # 更新可用余额
        fund.available_for_trading = fund.usable_balance
        
        logger.debug(f"Updated balance for {chain}: ${fund.total_balance:.2f}")
    
    def get_chain_fund(self, chain: str) -> Optional[ChainFund]:
        """获取链资金"""
        return self._chain_funds.get(chain)
    
    def get_all_chain_funds(self) -> Dict[str, ChainFund]:
        """获取所有链资金"""
        return self._chain_funds.copy()
    
    def get_total_balance(self) -> float:
        """获取总余额"""
        return sum(fund.total_balance for fund in self._chain_funds.values())
    
    def get_available_balance(self) -> float:
        """获取可用余额"""
        return sum(fund.available_for_trading for fund in self._chain_funds.values())
    
    def get_balance_by_chain(self, chain: str) -> float:
        """获取指定链余额"""
        fund = self._chain_funds.get(chain)
        return fund.total_balance if fund else 0.0
    
    def get_available_by_chain(self, chain: str) -> float:
        """获取指定链可用余额"""
        fund = self._chain_funds.get(chain)
        return fund.available_for_trading if fund else 0.0
    
    # ============================================
    # 仓位管理
    # ============================================
    
    def open_position(
        self,
        chain: str,
        token: str,
        amount: float,
        price: float,
        position_id: str = None
    ) -> Optional[Position]:
        """开仓"""
        if position_id is None:
            position_id = f"{chain}_{token}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        # 检查仓位限制
        if not self._check_position_limits(amount * price):
            logger.warning(f"Position size exceeds limits")
            return None
        
        # 检查余额
        available = self.get_available_by_chain(chain)
        required = amount * price
        if required > available:
            logger.warning(f"Insufficient balance for position: ${available:.2f} < ${required:.2f}")
            return None
        
        position = Position(
            chain=chain,
            token=token,
            amount=amount,
            value_usd=amount * price,
            entry_price=price,
            current_price=price,
        )
        
        self._positions[position_id] = position
        
        # 冻结资金
        fund = self._chain_funds.get(chain)
        if fund:
            fund.frozen += position.value_usd
            fund.available_for_trading = fund.usable_balance
        
        logger.info(
            f"Opened position {position_id}: {amount} {token} @ ${price:.2f} "
            f"(value: ${position.value_usd:.2f})"
        )
        
        return position
    
    def close_position(self, position_id: str, current_price: float = None) -> Optional[float]:
        """平仓，返回盈亏"""
        position = self._positions.pop(position_id, None)
        if not position:
            logger.warning(f"Position not found: {position_id}")
            return None
        
        # 更新当前价格
        if current_price:
            position.update_pnl(current_price)
        
        # 释放冻结资金
        fund = self._chain_funds.get(position.chain)
        if fund:
            fund.frozen = max(0, fund.frozen - position.value_usd)
            fund.available_for_trading = fund.usable_balance
        
        pnl = position.pnl_usd
        logger.info(
            f"Closed position {position_id}: PnL = ${pnl:.2f} ({position.pnl_pct:.2f}%)"
        )
        
        return pnl
    
    def get_position(self, position_id: str) -> Optional[Position]:
        """获取仓位"""
        return self._positions.get(position_id)
    
    def get_all_positions(self) -> List[Position]:
        """获取所有仓位"""
        return list(self._positions.values())
    
    def get_total_position_value(self) -> float:
        """获取总仓位价值"""
        return sum(p.value_usd for p in self._positions.values())
    
    def get_positions_by_chain(self, chain: str) -> List[Position]:
        """获取指定链的仓位"""
        return [p for p in self._positions.values() if p.chain == chain]
    
    def update_position_prices(self, prices: Dict[str, float]):
        """批量更新仓位价格"""
        for position in self._positions.values():
            if position.token in prices:
                position.update_pnl(prices[position.token])
    
    def _check_position_limits(self, value_usd: float) -> bool:
        """检查仓位限制"""
        # 单仓位限制
        if value_usd > self._risk_limits.max_position_usd:
            return False
        
        # 总仓位限制
        total_value = self.get_total_position_value()
        if total_value + value_usd > self._risk_limits.max_total_position_usd:
            return False
        
        return True
    
    # ============================================
    # 收益追踪
    # ============================================
    
    def record_profit(
        self,
        opportunity_id: str,
        chain: str,
        profit_usd: float,
        profit_pct: float,
        gas_cost_usd: float,
        execution_mode: str = "normal"
    ) -> ProfitRecord:
        """记录收益"""
        record = ProfitRecord(
            id=f"profit_{datetime.now().strftime('%Y%m%d%H%M%S%f')}",
            opportunity_id=opportunity_id,
            chain=chain,
            profit_usd=profit_usd,
            profit_pct=profit_pct,
            gas_cost_usd=gas_cost_usd,
            net_profit_usd=profit_usd - gas_cost_usd,
            executed_at=datetime.now(),
            execution_mode=execution_mode,
        )
        
        self._profit_records.append(record)
        
        # 更新统计
        self._daily_stats["trades"] += 1
        if record.net_profit_usd > 0:
            self._daily_stats["profit"] += record.net_profit_usd
        else:
            self._daily_stats["loss"] += abs(record.net_profit_usd)
        
        self._total_pnl += record.net_profit_usd
        
        # 更新峰值
        total_balance = self.get_total_balance()
        if total_balance > self._peak_balance:
            self._peak_balance = total_balance
        
        # 更新回撤
        self._update_drawdown()
        
        logger.info(
            f"Recorded profit: ${record.net_profit_usd:.2f} "
            f"(gross: ${profit_usd:.2f}, gas: ${gas_cost_usd:.2f})"
        )
        
        return record
    
    def get_profit_records(
        self,
        limit: int = 100,
        chain: str = None,
        start_date: datetime = None,
        end_date: datetime = None
    ) -> List[ProfitRecord]:
        """获取收益记录"""
        records = self._profit_records
        
        if chain:
            records = [r for r in records if r.chain == chain]
        
        if start_date:
            records = [r for r in records if r.executed_at >= start_date]
        
        if end_date:
            records = [r for r in records if r.executed_at <= end_date]
        
        return records[-limit:]
    
    def get_profit_summary(
        self,
        period_days: int = 1
    ) -> Dict[str, Any]:
        """获取收益摘要"""
        start_date = datetime.now() - timedelta(days=period_days)
        records = [
            r for r in self._profit_records 
            if r.executed_at >= start_date
        ]
        
        if not records:
            return {
                "period_days": period_days,
                "total_trades": 0,
                "profitable_trades": 0,
                "losing_trades": 0,
                "win_rate": 0.0,
                "total_profit": 0.0,
                "total_loss": 0.0,
                "net_profit": 0.0,
                "avg_profit_per_trade": 0.0,
            }
        
        total_profit = sum(r.net_profit_usd for r in records)
        total_loss = sum(abs(r.net_profit_usd) for r in records if r.net_profit_usd < 0)
        profitable = len([r for r in records if r.net_profit_usd > 0])
        
        return {
            "period_days": period_days,
            "total_trades": len(records),
            "profitable_trades": profitable,
            "losing_trades": len(records) - profitable,
            "win_rate": profitable / len(records) if records else 0,
            "total_profit": total_profit,
            "total_loss": total_loss,
            "net_profit": total_profit - total_loss,
            "avg_profit_per_trade": (total_profit - total_loss) / len(records),
        }
    
    def get_chain_performance(self) -> Dict[str, Dict]:
        """获取各链表现"""
        performance = defaultdict(lambda: {
            "trades": 0,
            "profit": 0.0,
            "loss": 0.0,
            "net": 0.0,
        })
        
        for record in self._profit_records:
            perf = performance[record.chain]
            perf["trades"] += 1
            if record.net_profit_usd > 0:
                perf["profit"] += record.net_profit_usd
            else:
                perf["loss"] += abs(record.net_profit_usd)
            perf["net"] += record.net_profit_usd
        
        return dict(performance)
    
    # ============================================
    # 资金分配和再平衡
    # ============================================
    
    def set_allocation(self, allocation: FundAllocation):
        """设置分配"""
        self._allocations[allocation.chain] = allocation
        logger.info(f"Set allocation for {allocation.chain}: {allocation.allocation_pct:.1%}")
    
    def get_allocation(self, chain: str) -> Optional[FundAllocation]:
        """获取分配"""
        return self._allocations.get(chain)
    
    def get_all_allocations(self) -> Dict[str, FundAllocation]:
        """获取所有分配"""
        return self._allocations.copy()
    
    def calculate_target_balance(self, total_balance: float, chain: str) -> float:
        """计算目标余额"""
        allocation = self._allocations.get(chain)
        if not allocation:
            return 0.0
        
        return total_balance * allocation.allocation_pct
    
    def check_rebalance_needed(self) -> List[Dict]:
        """检查是否需要再平衡"""
        total_balance = self.get_total_balance()
        if total_balance <= 0:
            return []
        
        rebalance_needed = []
        
        for chain, allocation in self._allocations.items():
            current_balance = self.get_balance_by_chain(chain)
            target_balance = total_balance * allocation.allocation_pct
            
            # 计算偏差
            deviation = abs(current_balance - target_balance) / target_balance if target_balance > 0 else 0
            
            # 超过阈值需要再平衡
            if deviation > 0.2:  # 20% 偏差阈值
                rebalance_needed.append({
                    "chain": chain,
                    "current": current_balance,
                    "target": target_balance,
                    "deviation": deviation,
                    "action": "withdraw" if current_balance > target_balance else "deposit",
                    "amount": abs(current_balance - target_balance),
                })
        
        return rebalance_needed
    
    async def rebalance_funds(
        self,
        trigger: RebalanceTrigger = RebalanceTrigger.MANUAL
    ) -> Dict[str, Any]:
        """执行资金再平衡"""
        async with self._lock:
            total_balance = self.get_total_balance()
            rebalance_plan = []
            
            for chain, allocation in self._allocations.items():
                current_balance = self.get_balance_by_chain(chain)
                target_balance = total_balance * allocation.allocation_pct
                
                diff = target_balance - current_balance
                
                if abs(diff) < allocation.min_balance_usd * 0.5:
                    continue
                
                # 检查上下限
                if target_balance < allocation.min_balance_usd:
                    target_balance = allocation.min_balance_usd
                if target_balance > allocation.max_balance_usd:
                    target_balance = allocation.max_balance_usd
                
                if abs(diff) > 10:  # 最小再平衡金额
                    rebalance_plan.append({
                        "chain": chain,
                        "from": current_balance,
                        "to": target_balance,
                        "amount": diff,
                        "action": "deposit" if diff > 0 else "withdraw",
                    })
            
            logger.info(
                f"Rebalance plan: {len(rebalance_plan)} chains affected, "
                f"total balance: ${total_balance:.2f}"
            )
            
            return {
                "trigger": trigger.value,
                "total_balance": total_balance,
                "plan": rebalance_plan,
                "executed_at": datetime.now().isoformat(),
            }
    
    # ============================================
    # 风险控制
    # ============================================
    
    def update_risk_limits(self, limits: RiskLimits):
        """更新风险限制"""
        self._risk_limits = limits
        logger.info("Risk limits updated")
    
    def get_risk_limits(self) -> RiskLimits:
        """获取风险限制"""
        return self._risk_limits
    
    def check_trade_allowed(self, chain: str, amount_usd: float) -> Tuple[bool, str]:
        """检查交易是否允许"""
        # 单笔限制
        if amount_usd > self._risk_limits.max_single_trade_usd:
            return False, f"单笔金额超过限制: ${amount_usd:.2f} > ${self._risk_limits.max_single_trade_usd:.2f}"
        
        # 余额检查
        available = self.get_available_by_chain(chain)
        if amount_usd > available:
            return False, f"余额不足: ${amount_usd:.2f} > ${available:.2f}"
        
        # 每日亏损限制
        if self._daily_stats["loss"] >= self._risk_limits.daily_loss_limit_usd:
            return False, f"每日亏损限制已达: ${self._daily_stats['loss']:.2f}"
        
        return True, "允许交易"
    
    def _update_drawdown(self):
        """更新回撤"""
        current_balance = self.get_total_balance()
        if self._peak_balance > 0:
            self._current_drawdown = (self._peak_balance - current_balance) / self._peak_balance * 100
        else:
            self._peak_balance = current_balance
            self._current_drawdown = 0
    
    def get_drawdown_info(self) -> Dict:
        """获取回撤信息"""
        self._update_drawdown()
        
        return {
            "peak_balance": self._peak_balance,
            "current_balance": self.get_total_balance(),
            "drawdown_usd": self._peak_balance - self.get_total_balance(),
            "drawdown_pct": self._current_drawdown,
            "emergency_threshold": self._risk_limits.max_drawdown_pct,
            "is_emergency": self._current_drawdown >= self._risk_limits.max_drawdown_pct,
        }
    
    async def emergency_withdraw(self, chain: str = None) -> Dict:
        """紧急撤资"""
        async with self._lock:
            logger.critical("EMERGENCY WITHDRAWAL INITIATED")
            
            withdraw_plan = []
            
            chains_to_withdraw = [chain] if chain else list(self._chain_funds.keys())
            
            for c in chains_to_withdraw:
                fund = self._chain_funds.get(c)
                if not fund:
                    continue
                
                # 关闭所有仓位
                chain_positions = self.get_positions_by_chain(c)
                for pos in chain_positions:
                    self.close_position(f"{c}_{pos.token}_{pos.opened_at.strftime('%Y%m%d%H%M%S')}")
                
                # 计算可提取金额
                withdrawable = fund.available_for_trading
                
                withdraw_plan.append({
                    "chain": c,
                    "withdrawable": withdrawable,
                    "positions_closed": len(chain_positions),
                })
                
                # 标记为提取中
                fund.frozen = fund.total_balance  # 冻结全部
            
            return {
                "initiated_at": datetime.now().isoformat(),
                "chains": withdraw_plan,
                "status": "withdrawing",
            }
    
    # ============================================
    # 快照和报告
    # ============================================
    
    def create_snapshot(self) -> FundSnapshot:
        """创建资金快照"""
        return FundSnapshot(
            timestamp=datetime.now(),
            total_balance_usd=self.get_total_balance(),
            chain_balances={
                chain: fund.total_balance 
                for chain, fund in self._chain_funds.items()
            },
            positions=self.get_all_positions(),
            daily_pnl_usd=self._daily_stats["profit"] - self._daily_stats["loss"],
            total_pnl_usd=self._total_pnl,
            frozen_usd=sum(f.frozen for f in self._chain_funds.values()),
            locked_usd=sum(f.locked for f in self._chain_funds.values()),
        )
    
    def get_status_summary(self) -> Dict:
        """获取状态摘要"""
        total = self.get_total_balance()
        available = self.get_available_balance()
        frozen = sum(f.frozen for f in self._chain_funds.values())
        locked = sum(f.locked for f in self._chain_funds.values())
        positions_value = self.get_total_position_value()
        
        drawdown_info = self.get_drawdown_info()
        
        return {
            "total_balance": f"${total:.2f}",
            "available": f"${available:.2f}",
            "frozen": f"${frozen:.2f}",
            "locked": f"${locked:.2f}",
            "positions_value": f"${positions_value:.2f}",
            "daily_pnl": f"${self._daily_stats['profit'] - self._daily_stats['loss']:.2f}",
            "total_pnl": f"${self._total_pnl:.2f}",
            "drawdown": f"{drawdown_info['drawdown_pct']:.2f}%",
            "daily_trades": self._daily_stats["trades"],
            "active_positions": len(self._positions),
            "chains": len(self._chain_funds),
        }
    
    def get_detailed_balance(self) -> Dict:
        """获取详细余额"""
        return {
            "total": self.get_total_balance(),
            "available": self.get_available_balance(),
            "by_chain": {
                chain: {
                    "total": fund.total_balance,
                    "available": fund.available_for_trading,
                    "frozen": fund.frozen,
                    "locked": fund.locked,
                    "native": fund.native_balance,
                    "tokens": fund.token_balances,
                }
                for chain, fund in self._chain_funds.items()
            }
        }
    
    def reset_daily_stats(self):
        """重置每日统计"""
        self._daily_stats = {
            "profit": 0.0,
            "loss": 0.0,
            "trades": 0,
        }
    
    async def cleanup_old_records(self, days: int = 30):
        """清理旧记录"""
        cutoff = datetime.now() - timedelta(days=days)
        self._profit_records = [
            r for r in self._profit_records 
            if r.executed_at >= cutoff
        ]
        logger.info(f"Cleaned up records older than {days} days")


# ============================================
# 单例访问函数
# ============================================

_fund_manager: Optional[FundManager] = None


def get_fund_manager() -> FundManager:
    """获取资金管理器单例"""
    global _fund_manager
    if _fund_manager is None:
        _fund_manager = FundManager()
    return _fund_manager


async def init_fund_manager(wallet_manager=None) -> FundManager:
    """初始化资金管理器"""
    manager = get_fund_manager()
    await manager.initialize(wallet_manager)
    return manager
