"""
机会日志模型

记录所有检测到的套利机会
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any


class OpportunityStatus(Enum):
    """机会状态"""
    DETECTED = "detected"
    EVALUATING = "evaluating"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    EXECUTING = "executing"
    EXECUTED = "executed"
    FAILED = "failed"


class OpportunityQuality(Enum):
    """机会质量"""
    EXCELLENT = "excellent"
    GOOD = "good"
    FAIR = "fair"
    POOR = "poor"
    VERY_POOR = "very_poor"


@dataclass
class OpportunityLog:
    """机会日志"""
    # 基本信息
    id: str
    symbol: str
    source_chain: str
    target_chain: str
    
    # 价格信息
    source_price: float
    target_price: float
    price_diff_pct: float
    
    # 收益估算
    estimated_profit_usd: float
    estimated_profit_pct: float
    estimated_gas_cost_usd: float
    estimated_net_profit_usd: float
    
    # 评估信息
    quality: OpportunityQuality
    confidence: float
    risk_score: float
    evaluation_reason: str = ""
    
    # 状态
    status: OpportunityStatus = OpportunityStatus.DETECTED
    
    # 时间戳
    detected_at: datetime = field(default_factory=datetime.now)
    evaluated_at: Optional[datetime] = None
    approved_at: Optional[datetime] = None
    executed_at: Optional[datetime] = None
    expired_at: Optional[datetime] = None
    
    # 执行信息
    execution_id: Optional[str] = None
    execution_tx_hash: Optional[str] = None
    actual_profit_usd: Optional[float] = None
    
    # 拒绝原因
    rejection_reason: Optional[str] = None
    
    # 附加数据
    liquidity: float = 0.0
    price_impact_pct: float = 0.0
    metadata: Dict = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            "id": self.id,
            "symbol": self.symbol,
            "source_chain": self.source_chain,
            "target_chain": self.target_chain,
            "source_price": self.source_price,
            "target_price": self.target_price,
            "price_diff_pct": self.price_diff_pct,
            "estimated_profit_usd": self.estimated_profit_usd,
            "estimated_profit_pct": self.estimated_profit_pct,
            "estimated_gas_cost_usd": self.estimated_gas_cost_usd,
            "estimated_net_profit_usd": self.estimated_net_profit_usd,
            "quality": self.quality.value,
            "confidence": self.confidence,
            "risk_score": self.risk_score,
            "evaluation_reason": self.evaluation_reason,
            "status": self.status.value,
            "detected_at": self.detected_at.isoformat(),
            "evaluated_at": self.evaluated_at.isoformat() if self.evaluated_at else None,
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "executed_at": self.executed_at.isoformat() if self.executed_at else None,
            "expired_at": self.expired_at.isoformat() if self.expired_at else None,
            "execution_id": self.execution_id,
            "execution_tx_hash": self.execution_tx_hash,
            "actual_profit_usd": self.actual_profit_usd,
            "rejection_reason": self.rejection_reason,
            "liquidity": self.liquidity,
            "price_impact_pct": self.price_impact_pct,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'OpportunityLog':
        """从字典创建"""
        data = data.copy()
        
        # 转换枚举
        if isinstance(data.get("quality"), str):
            data["quality"] = OpportunityQuality(data["quality"])
        if isinstance(data.get("status"), str):
            data["status"] = OpportunityStatus(data["status"])
        
        # 转换时间戳
        for time_field in ["detected_at", "evaluated_at", "approved_at", 
                          "executed_at", "expired_at"]:
            if data.get(time_field) and isinstance(data[time_field], str):
                data[time_field] = datetime.fromisoformat(data[time_field])
        
        return cls(**data)
    
    @property
    def is_profitable(self) -> bool:
        """是否可盈利"""
        return self.estimated_net_profit_usd > 0
    
    @property
    def is_high_quality(self) -> bool:
        """是否高质量"""
        return self.quality in [OpportunityQuality.EXCELLENT, OpportunityQuality.GOOD]
    
    @property
    def ttl_seconds(self) -> int:
        """剩余有效期（秒）"""
        if self.status != OpportunityStatus.DETECTED:
            return 0
        
        elapsed = (datetime.now() - self.detected_at).total_seconds()
        return max(0, 60 - elapsed)  # 默认60秒有效期
    
    @property
    def is_expired(self) -> bool:
        """是否已过期"""
        return self.ttl_seconds <= 0
    
    def approve(self):
        """批准"""
        self.status = OpportunityStatus.APPROVED
        self.approved_at = datetime.now()
    
    def reject(self, reason: str):
        """拒绝"""
        self.status = OpportunityStatus.REJECTED
        self.rejection_reason = reason
        self.evaluated_at = datetime.now()
    
    def mark_expired(self):
        """标记过期"""
        self.status = OpportunityStatus.EXPIRED
        self.expired_at = datetime.now()
    
    def mark_executed(self, execution_id: str, tx_hash: str = None):
        """标记已执行"""
        self.status = OpportunityStatus.EXECUTED
        self.execution_id = execution_id
        self.execution_tx_hash = tx_hash
        self.executed_at = datetime.now()
    
    def mark_failed(self):
        """标记失败"""
        self.status = OpportunityStatus.FAILED
        self.evaluated_at = datetime.now()


# ============================================
# 机会日志存储
# ============================================

class OpportunityLogStore:
    """机会日志存储"""
    
    def __init__(self, max_size: int = 10000):
        self._max_size = max_size
        self._logs: Dict[str, OpportunityLog] = {}
        self._by_symbol: Dict[str, List[str]] = {}
        self._by_chain: Dict[str, List[str]] = {}
        self._by_status: Dict[OpportunityStatus, List[str]] = {}
        self._by_quality: Dict[OpportunityQuality, List[str]] = {}
    
    def add(self, log: OpportunityLog):
        """添加日志"""
        # 检查容量
        if len(self._logs) >= self._max_size:
            self._cleanup_oldest()
        
        self._logs[log.id] = log
        
        # 建立索引
        if log.symbol not in self._by_symbol:
            self._by_symbol[log.symbol] = []
        self._by_symbol[log.symbol].append(log.id)
        
        # 按链索引
        for chain in [log.source_chain, log.target_chain]:
            if chain not in self._by_chain:
                self._by_chain[chain] = []
            self._by_chain[chain].append(log.id)
        
        if log.status not in self._by_status:
            self._by_status[log.status] = []
        self._by_status[log.status].append(log.id)
        
        if log.quality not in self._by_quality:
            self._by_quality[log.quality] = []
        self._by_quality[log.quality].append(log.id)
    
    def get(self, log_id: str) -> Optional[OpportunityLog]:
        """获取日志"""
        return self._logs.get(log_id)
    
    def get_by_symbol(self, symbol: str, limit: int = 100) -> List[OpportunityLog]:
        """按代币获取"""
        log_ids = self._by_symbol.get(symbol, [])[-limit:]
        return [self._logs[lid] for lid in log_ids if lid in self._logs]
    
    def get_by_chain(self, chain: str, limit: int = 100) -> List[OpportunityLog]:
        """按链获取"""
        log_ids = self._by_chain.get(chain, [])[-limit:]
        return [self._logs[lid] for lid in log_ids if lid in self._logs]
    
    def get_by_status(self, status: OpportunityStatus) -> List[OpportunityLog]:
        """按状态获取"""
        log_ids = self._by_status.get(status, [])
        return [self._logs[lid] for lid in log_ids if lid in self._logs]
    
    def get_by_quality(self, quality: OpportunityQuality) -> List[OpportunityLog]:
        """按质量获取"""
        log_ids = self._by_quality.get(quality, [])
        return [self._logs[lid] for lid in log_ids if lid in self._logs]
    
    def get_active(self, limit: int = 100) -> List[OpportunityLog]:
        """获取活跃机会"""
        active_statuses = [
            OpportunityStatus.DETECTED,
            OpportunityStatus.EVALUATING,
            OpportunityStatus.APPROVED,
        ]
        
        active_logs = []
        for status in active_statuses:
            active_logs.extend(self.get_by_status(status))
        
        # 按利润排序
        active_logs.sort(key=lambda x: x.estimated_net_profit_usd, reverse=True)
        return active_logs[:limit]
    
    def get_recent(self, limit: int = 100) -> List[OpportunityLog]:
        """获取最近的日志"""
        sorted_logs = sorted(
            self._logs.values(),
            key=lambda x: x.detected_at,
            reverse=True
        )
        return sorted_logs[:limit]
    
    def update(self, log: OpportunityLog):
        """更新日志"""
        old_log = self._logs.get(log.id)
        if old_log:
            # 更新状态索引
            if old_log.status != log.status:
                if old_log.status in self._by_status:
                    self._by_status[old_log.status].remove(log.id)
                if log.status not in self._by_status:
                    self._by_status[log.status] = []
                self._by_status[log.status].append(log.id)
        
        self._logs[log.id] = log
    
    def _cleanup_oldest(self):
        """清理最旧的日志"""
        if not self._logs:
            return
        
        # 找到最旧的日志
        oldest = min(self._logs.values(), key=lambda x: x.detected_at)
        self.delete(oldest.id)
    
    def delete(self, log_id: str):
        """删除日志"""
        if log_id in self._logs:
            log = self._logs[log_id]
            
            # 移除索引
            if log.symbol in self._by_symbol:
                self._by_symbol[log.symbol].remove(log_id)
            
            for chain in [log.source_chain, log.target_chain]:
                if chain in self._by_chain:
                    self._by_chain[chain].remove(log_id)
            
            if log.status in self._by_status:
                self._by_status[log.status].remove(log_id)
            
            if log.quality in self._by_quality:
                self._by_quality[log.quality].remove(log_id)
            
            del self._logs[log_id]
    
    def count(self) -> int:
        """获取总数"""
        return len(self._logs)
    
    def get_stats(self) -> Dict:
        """获取统计"""
        return {
            "total": len(self._logs),
            "by_status": {
                status.value: len(logs) 
                for status, logs in self._by_status.items()
            },
            "by_quality": {
                quality.value: len(logs)
                for quality, logs in self._by_quality.items()
            },
        }
