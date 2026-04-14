"""
执行历史记录模型

记录所有交易执行的详细信息
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any
import json


class ExecutionStatus(Enum):
    """执行状态"""
    PENDING = "pending"
    SUBMITTED = "submitted"
    CONFIRMING = "confirming"
    CONFIRMED = "confirmed"
    FAILED = "failed"
    REVERTED = "reverted"
    CANCELLED = "cancelled"


class ExecutionMode(Enum):
    """执行模式"""
    NORMAL = "normal"
    FLASH_LOAN = "flash_loan"
    CROSS_CHAIN = "cross_chain"


@dataclass
class ExecutionHistory:
    """执行历史记录"""
    # 基本信息
    id: str
    opportunity_id: str
    strategy_name: str
    
    # 交易信息
    chain: str
    token_in: str
    token_out: str
    amount_in: float
    amount_out: float
    amount_in_usd: float
    amount_out_usd: float
    
    # 执行详情
    mode: ExecutionMode
    status: ExecutionStatus
    tx_hash: str
    block_number: int = 0
    
    # 费用
    gas_price_gwei: float = 0.0
    gas_used: float = 0.0
    gas_cost_usd: float = 0.0
    flash_loan_fee_usd: float = 0.0
    bridge_fee_usd: float = 0.0
    total_fees_usd: float = 0.0
    
    # 收益
    estimated_profit_usd: float = 0.0
    actual_profit_usd: float = 0.0
    slippage_pct: float = 0.0
    
    # 时间戳
    created_at: datetime = field(default_factory=datetime.now)
    submitted_at: Optional[datetime] = None
    confirmed_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    failed_at: Optional[datetime] = None
    
    # 错误信息
    error_message: Optional[str] = None
    revert_reason: Optional[str] = None
    
    # 附加数据
    dex_routes: List[Dict] = field(default_factory=list)
    metadata: Dict = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            "id": self.id,
            "opportunity_id": self.opportunity_id,
            "strategy_name": self.strategy_name,
            "chain": self.chain,
            "token_in": self.token_in,
            "token_out": self.token_out,
            "amount_in": self.amount_in,
            "amount_out": self.amount_out,
            "amount_in_usd": self.amount_in_usd,
            "amount_out_usd": self.amount_out_usd,
            "mode": self.mode.value,
            "status": self.status.value,
            "tx_hash": self.tx_hash,
            "block_number": self.block_number,
            "gas_price_gwei": self.gas_price_gwei,
            "gas_used": self.gas_used,
            "gas_cost_usd": self.gas_cost_usd,
            "flash_loan_fee_usd": self.flash_loan_fee_usd,
            "bridge_fee_usd": self.bridge_fee_usd,
            "total_fees_usd": self.total_fees_usd,
            "estimated_profit_usd": self.estimated_profit_usd,
            "actual_profit_usd": self.actual_profit_usd,
            "slippage_pct": self.slippage_pct,
            "created_at": self.created_at.isoformat(),
            "submitted_at": self.submitted_at.isoformat() if self.submitted_at else None,
            "confirmed_at": self.confirmed_at.isoformat() if self.confirmed_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "failed_at": self.failed_at.isoformat() if self.failed_at else None,
            "error_message": self.error_message,
            "revert_reason": self.revert_reason,
            "dex_routes": self.dex_routes,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'ExecutionHistory':
        """从字典创建"""
        data = data.copy()
        
        # 转换枚举
        if isinstance(data.get("mode"), str):
            data["mode"] = ExecutionMode(data["mode"])
        if isinstance(data.get("status"), str):
            data["status"] = ExecutionStatus(data["status"])
        
        # 转换时间戳
        for time_field in ["created_at", "submitted_at", "confirmed_at", 
                          "completed_at", "failed_at"]:
            if data.get(time_field) and isinstance(data[time_field], str):
                data[time_field] = datetime.fromisoformat(data[time_field])
        
        return cls(**data)
    
    @property
    def is_successful(self) -> bool:
        """是否成功"""
        return self.status == ExecutionStatus.CONFIRMED
    
    @property
    def is_failed(self) -> bool:
        """是否失败"""
        return self.status in [ExecutionStatus.FAILED, ExecutionStatus.REVERTED]
    
    @property
    def execution_time_ms(self) -> float:
        """执行时间（毫秒）"""
        if self.submitted_at and self.confirmed_at:
            return (self.confirmed_at - self.submitted_at).total_seconds() * 1000
        return 0.0
    
    @property
    def net_profit_usd(self) -> float:
        """净利润"""
        return self.actual_profit_usd - self.total_fees_usd
    
    @property
    def roi_pct(self) -> float:
        """投资回报率"""
        if self.amount_in_usd > 0:
            return (self.net_profit_usd / self.amount_in_usd) * 100
        return 0.0


# ============================================
# 执行历史存储（内存实现，可扩展为数据库）
# ============================================

class ExecutionHistoryStore:
    """执行历史存储"""
    
    def __init__(self):
        self._history: Dict[str, ExecutionHistory] = {}
        self._by_opportunity: Dict[str, List[str]] = {}
        self._by_chain: Dict[str, List[str]] = {}
        self._by_status: Dict[ExecutionStatus, List[str]] = {}
    
    def add(self, record: ExecutionHistory):
        """添加记录"""
        self._history[record.id] = record
        
        # 建立索引
        if record.opportunity_id not in self._by_opportunity:
            self._by_opportunity[record.opportunity_id] = []
        self._by_opportunity[record.opportunity_id].append(record.id)
        
        if record.chain not in self._by_chain:
            self._by_chain[record.chain] = []
        self._by_chain[record.chain].append(record.id)
        
        if record.status not in self._by_status:
            self._by_status[record.status] = []
        self._by_status[record.status].append(record.id)
    
    def get(self, record_id: str) -> Optional[ExecutionHistory]:
        """获取记录"""
        return self._history.get(record_id)
    
    def get_by_opportunity(self, opportunity_id: str) -> List[ExecutionHistory]:
        """按机会ID获取"""
        record_ids = self._by_opportunity.get(opportunity_id, [])
        return [self._history[rid] for rid in record_ids if rid in self._history]
    
    def get_by_chain(self, chain: str, limit: int = 100) -> List[ExecutionHistory]:
        """按链获取"""
        record_ids = self._by_chain.get(chain, [])[-limit:]
        return [self._history[rid] for rid in record_ids if rid in self._history]
    
    def get_by_status(self, status: ExecutionStatus) -> List[ExecutionHistory]:
        """按状态获取"""
        record_ids = self._by_status.get(status, [])
        return [self._history[rid] for rid in record_ids if rid in self._history]
    
    def get_recent(self, limit: int = 100) -> List[ExecutionHistory]:
        """获取最近的记录"""
        sorted_records = sorted(
            self._history.values(),
            key=lambda x: x.created_at,
            reverse=True
        )
        return sorted_records[:limit]
    
    def update(self, record: ExecutionHistory):
        """更新记录"""
        self._history[record.id] = record
    
    def delete(self, record_id: str):
        """删除记录"""
        if record_id in self._history:
            record = self._history[record_id]
            
            # 移除索引
            if record.opportunity_id in self._by_opportunity:
                self._by_opportunity[record.opportunity_id].remove(record_id)
            
            if record.chain in self._by_chain:
                self._by_chain[record.chain].remove(record_id)
            
            if record.status in self._by_status:
                self._by_status[record.status].remove(record_id)
            
            del self._history[record_id]
    
    def count(self) -> int:
        """获取总数"""
        return len(self._history)
    
    def clear(self):
        """清空"""
        self._history.clear()
        self._by_opportunity.clear()
        self._by_chain.clear()
        self._by_status.clear()
