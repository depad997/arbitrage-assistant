"""
资金快照模型

记录资金状态快照
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any


@dataclass
class ChainSnapshot:
    """单链快照"""
    chain: str
    address: str
    
    # 余额
    native_balance: float
    native_balance_usd: float
    token_balances: Dict[str, float]  # {symbol: usd_value}
    
    # 可用资金
    available_usd: float
    frozen_usd: float
    locked_usd: float
    
    # 统计
    total_deposited_usd: float = 0.0
    total_withdrawn_usd: float = 0.0
    total_trades: int = 0
    total_profit_usd: float = 0.0
    
    def to_dict(self) -> Dict:
        return {
            "chain": self.chain,
            "address": self.address,
            "native_balance": self.native_balance,
            "native_balance_usd": self.native_balance_usd,
            "token_balances": self.token_balances,
            "available_usd": self.available_usd,
            "frozen_usd": self.frozen_usd,
            "locked_usd": self.locked_usd,
            "total_deposited_usd": self.total_deposited_usd,
            "total_withdrawn_usd": self.total_withdrawn_usd,
            "total_trades": self.total_trades,
            "total_profit_usd": self.total_profit_usd,
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'ChainSnapshot':
        return cls(**data)
    
    @property
    def total_balance_usd(self) -> float:
        return self.native_balance_usd + sum(self.token_balances.values())
    
    @property
    def utilization_pct(self) -> float:
        """资金利用率"""
        if self.total_balance_usd > 0:
            return ((self.frozen_usd + self.locked_usd) / self.total_balance_usd) * 100
        return 0.0


@dataclass
class PositionSnapshot:
    """仓位快照"""
    position_id: str
    chain: str
    token: str
    
    # 数量
    amount: float
    value_usd: float
    
    # 价格
    entry_price: float
    current_price: float
    
    # 盈亏
    pnl_usd: float
    pnl_pct: float
    
    # 时间
    opened_at: datetime
    updated_at: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict:
        return {
            "position_id": self.position_id,
            "chain": self.chain,
            "token": self.token,
            "amount": self.amount,
            "value_usd": self.value_usd,
            "entry_price": self.entry_price,
            "current_price": self.current_price,
            "pnl_usd": self.pnl_usd,
            "pnl_pct": self.pnl_pct,
            "opened_at": self.opened_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'PositionSnapshot':
        data = data.copy()
        for time_field in ["opened_at", "updated_at"]:
            if isinstance(data.get(time_field), str):
                data[time_field] = datetime.fromisoformat(data[time_field])
        return cls(**data)


@dataclass
class FundSnapshot:
    """资金快照"""
    id: str
    timestamp: datetime
    
    # 总览
    total_balance_usd: float
    available_usd: float
    frozen_usd: float
    locked_usd: float
    
    # 链详情
    chain_snapshots: List[ChainSnapshot]
    
    # 仓位
    positions: List[PositionSnapshot]
    
    # PnL
    daily_pnl_usd: float
    weekly_pnl_usd: float
    total_pnl_usd: float
    
    # 统计
    total_trades: int
    successful_trades: int
    failed_trades: int
    win_rate: float
    
    # 风险指标
    max_drawdown_pct: float = 0.0
    sharpe_ratio: float = 0.0
    
    # 附加信息
    metadata: Dict = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat(),
            "total_balance_usd": self.total_balance_usd,
            "available_usd": self.available_usd,
            "frozen_usd": self.frozen_usd,
            "locked_usd": self.locked_usd,
            "chain_snapshots": [cs.to_dict() for cs in self.chain_snapshots],
            "positions": [p.to_dict() for p in self.positions],
            "daily_pnl_usd": self.daily_pnl_usd,
            "weekly_pnl_usd": self.weekly_pnl_usd,
            "total_pnl_usd": self.total_pnl_usd,
            "total_trades": self.total_trades,
            "successful_trades": self.successful_trades,
            "failed_trades": self.failed_trades,
            "win_rate": self.win_rate,
            "max_drawdown_pct": self.max_drawdown_pct,
            "sharpe_ratio": self.sharpe_ratio,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'FundSnapshot':
        data = data.copy()
        
        if isinstance(data.get("timestamp"), str):
            data["timestamp"] = datetime.fromisoformat(data["timestamp"])
        
        if data.get("chain_snapshots"):
            data["chain_snapshots"] = [
                ChainSnapshot.from_dict(cs) for cs in data["chain_snapshots"]
            ]
        
        if data.get("positions"):
            data["positions"] = [
                PositionSnapshot.from_dict(p) for p in data["positions"]
            ]
        
        return cls(**data)
    
    @property
    def position_value_usd(self) -> float:
        """仓位总价值"""
        return sum(p.value_usd for p in self.positions)
    
    @property
    def active_positions(self) -> int:
        """活跃仓位"""
        return len([p for p in self.positions if p.pnl_usd >= 0])
    
    @property
    def losing_positions(self) -> int:
        """亏损仓位"""
        return len([p for p in self.positions if p.pnl_usd < 0])


# ============================================
# 快照存储
# ============================================

class FundSnapshotStore:
    """资金快照存储"""
    
    def __init__(self, max_snapshots: int = 1000):
        self._max_snapshots = max_snapshots
        self._snapshots: Dict[str, FundSnapshot] = {}
        self._by_date: Dict[str, List[str]] = {}  # date -> snapshot_ids
    
    def add(self, snapshot: FundSnapshot):
        """添加快照"""
        # 检查容量
        if len(self._snapshots) >= self._max_snapshots:
            self._cleanup_oldest()
        
        self._snapshots[snapshot.id] = snapshot
        
        # 按日期索引
        date_key = snapshot.timestamp.date().isoformat()
        if date_key not in self._by_date:
            self._by_date[date_key] = []
        self._by_date[date_key].append(snapshot.id)
    
    def get(self, snapshot_id: str) -> Optional[FundSnapshot]:
        """获取快照"""
        return self._snapshots.get(snapshot_id)
    
    def get_by_date(self, date: str) -> List[FundSnapshot]:
        """按日期获取"""
        snapshot_ids = self._by_date.get(date, [])
        return [self._snapshots[sid] for sid in snapshot_ids if sid in self._snapshots]
    
    def get_latest(self) -> Optional[FundSnapshot]:
        """获取最新快照"""
        if not self._snapshots:
            return None
        
        return max(self._snapshots.values(), key=lambda x: x.timestamp)
    
    def get_recent(self, limit: int = 100) -> List[FundSnapshot]:
        """获取最近的快照"""
        sorted_snapshots = sorted(
            self._snapshots.values(),
            key=lambda x: x.timestamp,
            reverse=True
        )
        return sorted_snapshots[:limit]
    
    def get_date_range(
        self, 
        start_date: datetime, 
        end_date: datetime
    ) -> List[FundSnapshot]:
        """获取日期范围内的快照"""
        snapshots = []
        for snapshot in self._snapshots.values():
            if start_date <= snapshot.timestamp <= end_date:
                snapshots.append(snapshot)
        
        return sorted(snapshots, key=lambda x: x.timestamp)
    
    def _cleanup_oldest(self):
        """清理最旧的快照"""
        if not self._snapshots:
            return
        
        oldest = min(self._snapshots.values(), key=lambda x: x.timestamp)
        self.delete(oldest.id)
    
    def delete(self, snapshot_id: str):
        """删除快照"""
        if snapshot_id in self._snapshots:
            snapshot = self._snapshots[snapshot_id]
            date_key = snapshot.timestamp.date().isoformat()
            
            if date_key in self._by_date:
                self._by_date[date_key].remove(snapshot_id)
            
            del self._snapshots[snapshot_id]
    
    def count(self) -> int:
        """获取总数"""
        return len(self._snapshots)
    
    def clear(self):
        """清空"""
        self._snapshots.clear()
        self._by_date.clear()
