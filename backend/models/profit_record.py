"""
收益记录模型

记录交易收益详情
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from collections import defaultdict


@dataclass
class ProfitRecord:
    """收益记录"""
    id: str
    execution_id: str
    opportunity_id: str
    
    # 链和代币
    chain: str
    token_in: str
    token_out: str
    
    # 金额
    amount_in: float
    amount_out: float
    amount_in_usd: float
    amount_out_usd: float
    
    # 费用
    gas_cost_usd: float
    flash_loan_fee_usd: float
    bridge_fee_usd: float
    other_fees_usd: float
    total_fees_usd: float
    
    # 收益
    gross_profit_usd: float
    net_profit_usd: float
    profit_pct: float
    
    # 执行模式
    execution_mode: str  # normal, flash_loan, cross_chain
    
    # 状态
    status: str  # pending, completed, failed, rolled_back
    
    # 时间
    executed_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None
    
    # 附加信息
    tx_hash: Optional[str] = None
    error: Optional[str] = None
    metadata: Dict = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "execution_id": self.execution_id,
            "opportunity_id": self.opportunity_id,
            "chain": self.chain,
            "token_in": self.token_in,
            "token_out": self.token_out,
            "amount_in": self.amount_in,
            "amount_out": self.amount_out,
            "amount_in_usd": self.amount_in_usd,
            "amount_out_usd": self.amount_out_usd,
            "gas_cost_usd": self.gas_cost_usd,
            "flash_loan_fee_usd": self.flash_loan_fee_usd,
            "bridge_fee_usd": self.bridge_fee_usd,
            "other_fees_usd": self.other_fees_usd,
            "total_fees_usd": self.total_fees_usd,
            "gross_profit_usd": self.gross_profit_usd,
            "net_profit_usd": self.net_profit_usd,
            "profit_pct": self.profit_pct,
            "execution_mode": self.execution_mode,
            "status": self.status,
            "executed_at": self.executed_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "tx_hash": self.tx_hash,
            "error": self.error,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'ProfitRecord':
        data = data.copy()
        
        for time_field in ["executed_at", "completed_at"]:
            if data.get(time_field) and isinstance(data[time_field], str):
                data[time_field] = datetime.fromisoformat(data[time_field])
        
        return cls(**data)
    
    @property
    def is_profitable(self) -> bool:
        return self.net_profit_usd > 0
    
    @property
    def execution_time_ms(self) -> float:
        if self.completed_at and self.executed_at:
            return (self.completed_at - self.executed_at).total_seconds() * 1000
        return 0.0


@dataclass
class ProfitSummary:
    """收益摘要"""
    period_start: datetime
    period_end: datetime
    period_days: int
    
    # 数量统计
    total_trades: int
    profitable_trades: int
    losing_trades: int
    
    # 金额统计
    total_gross_profit: float
    total_net_profit: float
    total_fees: float
    
    # 比率
    win_rate: float
    avg_profit_per_trade: float
    avg_profit_per_winning_trade: float
    avg_loss_per_losing_trade: float
    profit_factor: float  # 总利润 / 总亏损
    
    # 极值
    max_single_profit: float
    max_single_loss: float
    max_consecutive_wins: int
    max_consecutive_losses: int
    
    # 链分布
    chain_stats: Dict[str, Dict]
    
    # 趋势
    daily_profit: List[Dict]  # [{date, profit}]
    
    def to_dict(self) -> Dict:
        return {
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "period_days": self.period_days,
            "total_trades": self.total_trades,
            "profitable_trades": self.profitable_trades,
            "losing_trades": self.losing_trades,
            "total_gross_profit": self.total_gross_profit,
            "total_net_profit": self.total_net_profit,
            "total_fees": self.total_fees,
            "win_rate": self.win_rate,
            "avg_profit_per_trade": self.avg_profit_per_trade,
            "avg_profit_per_winning_trade": self.avg_profit_per_winning_trade,
            "avg_loss_per_losing_trade": self.avg_loss_per_losing_trade,
            "profit_factor": self.profit_factor,
            "max_single_profit": self.max_single_profit,
            "max_single_loss": self.max_single_loss,
            "max_consecutive_wins": self.max_consecutive_wins,
            "max_consecutive_losses": self.max_consecutive_losses,
            "chain_stats": self.chain_stats,
            "daily_profit": self.daily_profit,
        }


# ============================================
# 收益记录存储
# ============================================

class ProfitRecordStore:
    """收益记录存储"""
    
    def __init__(self, max_records: int = 10000):
        self._max_records = max_records
        self._records: Dict[str, ProfitRecord] = {}
        self._by_chain: Dict[str, List[str]] = {}
        self._by_date: Dict[str, List[str]] = {}
        self._by_status: Dict[str, List[str]] = {}
    
    def add(self, record: ProfitRecord):
        """添加记录"""
        # 检查容量
        if len(self._records) >= self._max_records:
            self._cleanup_oldest()
        
        self._records[record.id] = record
        
        # 建立索引
        if record.chain not in self._by_chain:
            self._by_chain[record.chain] = []
        self._by_chain[record.chain].append(record.id)
        
        date_key = record.executed_at.date().isoformat()
        if date_key not in self._by_date:
            self._by_date[date_key] = []
        self._by_date[date_key].append(record.id)
        
        if record.status not in self._by_status:
            self._by_status[record.status] = []
        self._by_status[record.status].append(record.id)
    
    def get(self, record_id: str) -> Optional[ProfitRecord]:
        return self._records.get(record_id)
    
    def get_by_chain(self, chain: str, limit: int = 100) -> List[ProfitRecord]:
        record_ids = self._by_chain.get(chain, [])[-limit:]
        return [self._records[rid] for rid in record_ids if rid in self._records]
    
    def get_by_date(self, date: str) -> List[ProfitRecord]:
        record_ids = self._by_date.get(date, [])
        return [self._records[rid] for rid in record_ids if rid in self._records]
    
    def get_date_range(
        self, 
        start_date: datetime, 
        end_date: datetime
    ) -> List[ProfitRecord]:
        records = []
        for record in self._records.values():
            if start_date <= record.executed_at <= end_date:
                records.append(record)
        return sorted(records, key=lambda x: x.executed_at)
    
    def get_recent(self, limit: int = 100) -> List[ProfitRecord]:
        sorted_records = sorted(
            self._records.values(),
            key=lambda x: x.executed_at,
            reverse=True
        )
        return sorted_records[:limit]
    
    def update(self, record: ProfitRecord):
        self._records[record.id] = record
    
    def _cleanup_oldest(self):
        if not self._records:
            return
        
        oldest = min(self._records.values(), key=lambda x: x.executed_at)
        self.delete(oldest.id)
    
    def delete(self, record_id: str):
        if record_id in self._records:
            record = self._records[record_id]
            
            if record.chain in self._by_chain:
                self._by_chain[record.chain].remove(record_id)
            
            date_key = record.executed_at.date().isoformat()
            if date_key in self._by_date:
                self._by_date[date_key].remove(record_id)
            
            if record.status in self._by_status:
                self._by_status[record.status].remove(record_id)
            
            del self._records[record_id]
    
    def count(self) -> int:
        return len(self._records)
    
    def calculate_summary(
        self, 
        start_date: datetime, 
        end_date: datetime
    ) -> ProfitSummary:
        """计算收益摘要"""
        records = self.get_date_range(start_date, end_date)
        
        if not records:
            return ProfitSummary(
                period_start=start_date,
                period_end=end_date,
                period_days=(end_date - start_date).days,
                total_trades=0,
                profitable_trades=0,
                losing_trades=0,
                total_gross_profit=0,
                total_net_profit=0,
                total_fees=0,
                win_rate=0,
                avg_profit_per_trade=0,
                avg_profit_per_winning_trade=0,
                avg_loss_per_losing_trade=0,
                profit_factor=0,
                max_single_profit=0,
                max_single_loss=0,
                max_consecutive_wins=0,
                max_consecutive_losses=0,
                chain_stats={},
                daily_profit=[],
            )
        
        # 基本统计
        profitable = [r for r in records if r.net_profit_usd > 0]
        losing = [r for r in records if r.net_profit_usd <= 0]
        
        total_gross = sum(r.gross_profit_usd for r in records)
        total_net = sum(r.net_profit_usd for r in records)
        total_fees = sum(r.total_fees_usd for r in records)
        
        win_rate = len(profitable) / len(records) if records else 0
        
        avg_profit = total_net / len(records) if records else 0
        avg_win = sum(r.net_profit_usd for r in profitable) / len(profitable) if profitable else 0
        avg_loss = sum(r.net_profit_usd for r in losing) / len(losing) if losing else 0
        
        total_profit = sum(r.net_profit_usd for r in profitable)
        total_loss = abs(sum(r.net_profit_usd for r in losing))
        profit_factor = total_profit / total_loss if total_loss > 0 else float('inf')
        
        max_profit = max((r.net_profit_usd for r in records), default=0)
        max_loss = min((r.net_profit_usd for r in records), default=0)
        
        # 连续胜败
        sorted_records = sorted(records, key=lambda x: x.executed_at)
        max_consecutive_wins = 0
        max_consecutive_losses = 0
        current_wins = 0
        current_losses = 0
        
        for r in sorted_records:
            if r.net_profit_usd > 0:
                current_wins += 1
                current_losses = 0
                max_consecutive_wins = max(max_consecutive_wins, current_wins)
            else:
                current_losses += 1
                current_wins = 0
                max_consecutive_losses = max(max_consecutive_losses, current_losses)
        
        # 链统计
        chain_stats = defaultdict(lambda: {
            "trades": 0,
            "profit": 0.0,
            "loss": 0.0,
            "net": 0.0,
        })
        
        for r in records:
            stats = chain_stats[r.chain]
            stats["trades"] += 1
            if r.net_profit_usd > 0:
                stats["profit"] += r.net_profit_usd
            else:
                stats["loss"] += abs(r.net_profit_usd)
            stats["net"] += r.net_profit_usd
        
        # 每日利润
        daily_profit = []
        current_date = start_date.date()
        while current_date <= end_date.date():
            date_key = current_date.isoformat()
            day_records = self.get_by_date(date_key)
            day_profit = sum(r.net_profit_usd for r in day_records)
            
            daily_profit.append({
                "date": date_key,
                "profit": day_profit,
                "trades": len(day_records),
            })
            
            current_date += timedelta(days=1)
        
        return ProfitSummary(
            period_start=start_date,
            period_end=end_date,
            period_days=(end_date - start_date).days,
            total_trades=len(records),
            profitable_trades=len(profitable),
            losing_trades=len(losing),
            total_gross_profit=total_gross,
            total_net_profit=total_net,
            total_fees=total_fees,
            win_rate=win_rate,
            avg_profit_per_trade=avg_profit,
            avg_profit_per_winning_trade=avg_win,
            avg_loss_per_losing_trade=avg_loss,
            profit_factor=profit_factor,
            max_single_profit=max_profit,
            max_single_loss=max_loss,
            max_consecutive_wins=max_consecutive_wins,
            max_consecutive_losses=max_consecutive_losses,
            chain_stats=dict(chain_stats),
            daily_profit=daily_profit,
        )
