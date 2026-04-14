"""
告警服务 - Phase 2 增强版
负责告警规则管理、消息格式化、通知发送

功能特性:
- 多渠道通知（Telegram、飞书、终端日志）
- 告警限流和去重
- 按机会质量分级提醒
- 冷却时间控制
"""

import asyncio
import logging
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
import json

import sys
import os

# 添加 backend 目录到路径以支持相对导入
_backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from config.settings import settings, ENABLED_CHAINS

logger = logging.getLogger(__name__)


# ============================================
# 枚举定义
# ============================================

class AlertLevel(Enum):
    """告警级别"""
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    EMERGENCY = "emergency"  # 紧急（最高优先级）

    @property
    def priority(self) -> int:
        """优先级（数字越大优先级越高）"""
        priorities = {
            "debug": 0,
            "info": 1,
            "warning": 2,
            "critical": 3,
            "emergency": 4,
        }
        return priorities.get(self.value, 0)

    @property
    def emoji(self) -> str:
        """级别对应的 emoji"""
        emojis = {
            "debug": "🔍",
            "info": "ℹ️",
            "warning": "⚠️",
            "critical": "🚨",
            "emergency": "🔥",
        }
        return emojis.get(self.value, "📢")


class AlertType(Enum):
    """告警类型"""
    PRICE_CHANGE = "price_change"               # 价格变动
    ARBITRAGE_OPPORTUNITY = "arbitrage"         # 套利机会
    HIGH_PROFIT = "high_profit"                 # 高利润
    LIQUIDITY_LOW = "liquidity_low"             # 流动性不足
    GAS_HIGH = "gas_high"                       # Gas 过高
    SYSTEM_ERROR = "system_error"               # 系统错误
    OPPORTUNITY_EXPIRED = "opportunity_expired"  # 机会过期
    MONITORING_STATUS = "monitoring_status"     # 监控状态


class AlertChannel(Enum):
    """通知渠道"""
    LOG = "log"           # 终端日志
    TELEGRAM = "telegram"  # Telegram
    FEISHU = "feishu"     # 飞书
    WEBHOOK = "webhook"   # Webhook


# ============================================
# 数据类定义
# ============================================

@dataclass
class AlertMessage:
    """告警消息"""
    level: AlertLevel
    alert_type: AlertType
    title: str
    message: str
    data: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
    
    # 发送控制
    opportunity_id: Optional[str] = None  # 关联的机会 ID
    retry_count: int = 0
    max_retries: int = 3
    
    # 元数据
    source: str = "system"
    tags: List[str] = field(default_factory=list)
    
    @property
    def cache_key(self) -> str:
        """生成去重的缓存 key"""
        return f"{self.alert_type.value}:{self.opportunity_id or ''}:{self.level.value}"
    
    @property
    def age_seconds(self) -> float:
        return (datetime.now() - self.timestamp).total_seconds()
    
    def to_markdown(self) -> str:
        """转换为 Markdown 格式"""
        emoji = self.level.emoji
        
        md = f"{emoji} **{self.title}**\n\n"
        md += f"{self.message}\n\n"
        
        if self.data:
            md += "**详情:**\n"
            for key, value in self.data.items():
                if isinstance(value, float):
                    md += f"- {key}: `{value:.4f}`\n"
                else:
                    md += f"- {key}: `{value}`\n"
        
        md += f"\n_{self.timestamp.strftime('%Y-%m-%d %H:%M:%S')}_"
        
        return md
    
    def to_telegram(self) -> str:
        """转换为 Telegram 格式"""
        emoji = self.level.emoji
        
        text = f"{emoji} *{self.title}*\n\n"
        text += f"{self.message}\n\n"
        
        if self.data:
            for key, value in self.data.items():
                if isinstance(value, float):
                    text += f"• {key}: `{value:.4f}`\n"
                else:
                    text += f"• {key}: `{value}`\n"
        
        return text
    
    def to_feishu(self) -> Dict:
        """转换为飞书消息格式"""
        return {
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {
                        "tag": "plain_text",
                        "content": f"{self.level.emoji} {self.title}"
                    },
                    "template": self._get_feishu_template()
                },
                "elements": [
                    {
                        "tag": "div",
                        "text": {
                            "tag": "lark_md",
                            "content": self.message
                        }
                    },
                    {
                        "tag": "hr"
                    },
                    {
                        "tag": "div",
                        "text": {
                            "tag": "lark_md",
                            "content": self._format_data_for_feishu()
                        }
                    }
                ]
            }
        }
    
    def _get_feishu_template(self) -> str:
        """获取飞书卡片模板颜色"""
        templates = {
            "debug": "grey",
            "info": "blue",
            "warning": "yellow",
            "critical": "red",
            "emergency": "red",
        }
        return templates.get(self.level.value, "blue")
    
    def _format_data_for_feishu(self) -> str:
        """格式化数据为飞书文本"""
        if not self.data:
            return ""
        
        lines = ["**详情:**"]
        for key, value in self.data.items():
            if isinstance(value, float):
                lines.append(f"- {key}: `{value:.4f}`")
            else:
                lines.append(f"- {key}: `{value}`")
        
        return "\n".join(lines)
    
    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            "level": self.level.value,
            "type": self.alert_type.value,
            "title": self.title,
            "message": self.message,
            "data": self.data,
            "timestamp": self.timestamp.isoformat(),
            "opportunity_id": self.opportunity_id,
            "source": self.source,
            "tags": self.tags,
        }
    
    def to_json(self) -> str:
        """转换为 JSON 字符串"""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


@dataclass
class AlertConfig:
    """告警配置"""
    # 渠道配置
    enabled_channels: List[AlertChannel] = field(
        default_factory=lambda: [AlertChannel.LOG]
    )
    
    # Telegram 配置
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    
    # 飞书配置
    feishu_webhook_url: Optional[str] = None
    feishu_bot_name: str = "套利助手"
    
    # 限流配置
    rate_limit_per_minute: int = 10       # 每分钟最大告警数
    cooldown_seconds: int = 300           # 相同告警冷却时间
    opportunity_cooldown: int = 300        # 相同机会冷却时间
    
    # 过滤配置
    min_level: AlertLevel = AlertLevel.INFO
    min_profit_threshold: float = 10.0     # 最小利润阈值
    
    def __post_init__(self):
        # 从全局配置加载
        if not self.telegram_bot_token:
            self.telegram_bot_token = settings.TELEGRAM_BOT_TOKEN
        if not self.telegram_chat_id:
            self.telegram_chat_id = settings.TELEGRAM_CHAT_ID
        # 飞书配置也从全局配置加载
        if not self.feishu_webhook_url:
            self.feishu_webhook_url = settings.FEISHU_WEBHOOK_URL


@dataclass
class AlertResult:
    """告警发送结果"""
    success: bool
    message: Optional[AlertMessage] = None
    error: Optional[str] = None
    channels: List[str] = field(default_factory=list)
    sent_at: datetime = field(default_factory=datetime.now)


# ============================================
# 告警发送器
# ============================================

class AlertSender:
    """告警发送器基类"""
    
    async def send(self, alert: AlertMessage) -> bool:
        """发送告警，返回是否成功"""
        raise NotImplementedError


class LogAlertSender(AlertSender):
    """日志告警发送器"""
    
    def __init__(self, logger_instance: logging.Logger = None):
        self.logger = logger_instance or logging.getLogger("alert")
    
    async def send(self, alert: AlertMessage) -> bool:
        """发送日志告警"""
        log_level_map = {
            AlertLevel.DEBUG: self.logger.debug,
            AlertLevel.INFO: self.logger.info,
            AlertLevel.WARNING: self.logger.warning,
            AlertLevel.CRITICAL: self.logger.critical,
            AlertLevel.EMERGENCY: self.logger.critical,
        }
        
        log_func = log_level_map.get(alert.level, self.logger.info)
        log_func(f"[{alert.alert_type.value}] {alert.title}: {alert.message}")
        
        return True


class TelegramAlertSender(AlertSender):
    """Telegram 告警发送器"""
    
    def __init__(
        self,
        bot_token: str = None,
        chat_id: str = None,
        session: Any = None
    ):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.session = session
        self._base_url = f"https://api.telegram.org/bot{bot_token}" if bot_token else None
    
    async def send(self, alert: AlertMessage) -> bool:
        """发送 Telegram 告警"""
        if not self._base_url or not self.chat_id:
            return False
        
        try:
            import aiohttp
            
            url = f"{self._base_url}/sendMessage"
            payload = {
                "chat_id": self.chat_id,
                "text": alert.to_telegram(),
                "parse_mode": "Markdown"
            }
            
            if self.session:
                async with self.session.post(url, json=payload) as resp:
                    return resp.status == 200
            else:
                async with aiohttp.ClientSession() as session:
                    async with session.post(url, json=payload) as resp:
                        return resp.status == 200
                        
        except Exception as e:
            logger.error(f"[Telegram] Send failed: {e}")
            return False


class FeishuAlertSender(AlertSender):
    """飞书告警发送器
    
    支持富文本卡片消息和签名验证
    """
    
    def __init__(self, webhook_url: str = None, secret: str = None, session: Any = None):
        self.webhook_url = webhook_url
        self.secret = secret
        self.session = session
    
    async def send(self, alert: AlertMessage) -> bool:
        """发送飞书告警"""
        if not self.webhook_url:
            logger.warning("[Feishu] Webhook URL not configured")
            return False
        
        try:
            import aiohttp
            import time
            import hmac
            import hashlib
            import base64
            
            # 构建消息内容
            payload = alert.to_feishu()
            
            # 如果配置了签名密钥，添加签名
            if self.secret:
                timestamp = str(int(time.time()))
                sign = self._generate_sign(timestamp, self.secret)
                payload["timestamp"] = timestamp
                payload["sign"] = sign
            
            if self.session:
                async with self.session.post(self.webhook_url, json=payload) as resp:
                    result = await resp.json()
                    if resp.status == 200 and result.get("code") == 0:
                        logger.debug(f"[Feishu] Message sent successfully")
                        return True
                    else:
                        logger.error(f"[Feishu] Send failed: {result}")
                        return False
            else:
                async with aiohttp.ClientSession() as session:
                    async with session.post(self.webhook_url, json=payload) as resp:
                        result = await resp.json()
                        if resp.status == 200 and result.get("code") == 0:
                            logger.debug(f"[Feishu] Message sent successfully")
                            return True
                        else:
                            logger.error(f"[Feishu] Send failed: {result}")
                            return False
                        
        except Exception as e:
            logger.error(f"[Feishu] Send failed: {e}")
            return False
    
    @staticmethod
    def _generate_sign(timestamp: str, secret: str) -> str:
        """生成签名
        
        Args:
            timestamp: 时间戳字符串
            secret: 签名密钥
        
        Returns:
            签名字符串
        """
        import hmac
        import hashlib
        import base64
        
        string_to_sign = f"{timestamp}\n{secret}"
        secret_encoded = secret.encode('utf-8')
        string_to_sign_encoded = string_to_sign.encode('utf-8')
        hmac_code = hmac.new(secret_encoded, string_to_sign_encoded, digestmod=hashlib.sha256).digest()
        sign = base64.b64encode(hmac_code).decode('utf-8')
        return sign


class FeishuAlerter:
    """飞书机器人通知类
    
    提供独立的飞书通知功能，支持：
    - 富文本卡片消息
    - 签名验证
    - 套利机会专用卡片
    """
    
    def __init__(self, webhook_url: str, secret: str = None, bot_name: str = "套利助手"):
        """
        初始化飞书通知器
        
        Args:
            webhook_url: 飞书机器人 Webhook 地址
            secret: 签名密钥（可选）
            bot_name: 机器人名称
        """
        self.webhook_url = webhook_url
        self.secret = secret
        self.bot_name = bot_name
        self._session = None
    
    async def _get_session(self):
        """获取或创建 HTTP 会话"""
        if self._session is None:
            import aiohttp
            self._session = aiohttp.ClientSession()
        return self._session
    
    async def close(self):
        """关闭 HTTP 会话"""
        if self._session:
            await self._session.close()
            self._session = None
    
    async def send_message(
        self,
        title: str,
        content: str,
        alert_level: str = "INFO",
        elements: list = None
    ) -> bool:
        """
        发送飞书消息
        
        Args:
            title: 消息标题
            content: 消息内容（支持 Markdown）
            alert_level: 告警级别 (INFO, WARNING, CRITICAL)
            elements: 额外的卡片元素列表
        
        Returns:
            是否发送成功
        """
        if not self.webhook_url:
            logger.warning("[FeishuAlerter] Webhook URL not configured")
            return False
        
        try:
            import aiohttp
            import time
            import hmac
            import hashlib
            import base64
            
            # 根据告警级别选择卡片颜色
            level_templates = {
                "DEBUG": "grey",
                "INFO": "blue",
                "WARNING": "yellow",
                "CRITICAL": "red",
                "EMERGENCY": "red",
            }
            template = level_templates.get(alert_level.upper(), "blue")
            
            # 获取 emoji
            level_emojis = {
                "DEBUG": "🔍",
                "INFO": "ℹ️",
                "WARNING": "⚠️",
                "CRITICAL": "🚨",
                "EMERGENCY": "🔥",
            }
            emoji = level_emojis.get(alert_level.upper(), "📢")
            
            # 构建卡片元素
            card_elements = [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": content
                    }
                }
            ]
            
            # 添加额外元素
            if elements:
                card_elements.extend(elements)
            
            # 添加底部信息
            card_elements.extend([
                {"tag": "hr"},
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": f"🤖 {self.bot_name} | {time.strftime('%Y-%m-%d %H:%M:%S')}"
                    }
                }
            ])
            
            payload = {
                "msg_type": "interactive",
                "card": {
                    "header": {
                        "title": {
                            "tag": "plain_text",
                            "content": f"{emoji} {title}"
                        },
                        "template": template
                    },
                    "elements": card_elements
                }
            }
            
            # 添加签名
            if self.secret:
                timestamp = str(int(time.time()))
                sign = self._generate_sign(timestamp, self.secret)
                payload["timestamp"] = timestamp
                payload["sign"] = sign
            
            session = await self._get_session()
            async with session.post(self.webhook_url, json=payload) as resp:
                result = await resp.json()
                if resp.status == 200 and result.get("code") == 0:
                    logger.info(f"[FeishuAlerter] Message sent: {title}")
                    return True
                else:
                    logger.error(f"[FeishuAlerter] Send failed: {result}")
                    return False
                    
        except Exception as e:
            logger.error(f"[FeishuAlerter] Send failed: {e}")
            return False
    
    async def send_arbitrage_alert(self, opportunity: Any) -> bool:
        """
        发送套利机会提醒
        
        Args:
            opportunity: 套利机会对象，应包含以下属性：
                - path: 交易路径，如 "ETH → Arbitrum → BSC"
                - price_diff: 价差百分比
                - expected_profit: 预期利润（USD）
                - source_chain: 源链
                - dest_chain: 目标链
                - gas_cost: Gas 成本估算
                - timestamp: 发现时间
        
        Returns:
            是否发送成功
        """
        if not self.webhook_url:
            return False
        
        try:
            # 构建路径展示
            if hasattr(opportunity, 'path'):
                path_str = opportunity.path
            elif hasattr(opportunity, 'source_chain') and hasattr(opportunity, 'dest_chain'):
                path_str = f"{opportunity.source_chain} → {opportunity.dest_chain}"
            else:
                path_str = "未知路径"
            
            # 获取关键数据
            price_diff = getattr(opportunity, 'price_diff', 0)
            expected_profit = getattr(opportunity, 'expected_profit', 0)
            gas_cost = getattr(opportunity, 'gas_cost', 0)
            token_symbol = getattr(opportunity, 'token_symbol', 'TOKEN')
            token_amount = getattr(opportunity, 'token_amount', 0)
            
            # 判断机会质量
            if price_diff >= 3.0:
                alert_level = "CRITICAL"
                quality_tag = "🔥 高收益"
            elif price_diff >= 1.5:
                alert_level = "WARNING"
                quality_tag = "⚡ 中等收益"
            else:
                alert_level = "INFO"
                quality_tag = "📊 低风险"
            
            # 构建消息内容
            content_lines = [
                f"**交易路径**: {path_str}",
                f"**代币**: {token_symbol}",
                f"**数量**: {token_amount:.4f}",
                "",
                f"📈 **价差**: `{price_diff:.2f}%`",
                f"💰 **预期利润**: `${expected_profit:.2f}`",
                f"⛽ **Gas 成本**: `${gas_cost:.2f}`",
                "",
                f"{quality_tag}",
            ]
            content = "\n".join(content_lines)
            
            # 构建额外元素
            elements = [
                {
                    "tag": "note",
                    "elements": [
                        {
                            "tag": "lark_md",
                            "content": "💡 提示: 请在实际执行前验证数据准确性"
                        }
                    ]
                }
            ]
            
            return await self.send_message(
                title="🔔 套利机会发现",
                content=content,
                alert_level=alert_level,
                elements=elements
            )
            
        except Exception as e:
            logger.error(f"[FeishuAlerter] Send arbitrage alert failed: {e}")
            return False
    
    @staticmethod
    def _generate_sign(timestamp: str, secret: str) -> str:
        """生成签名"""
        import hmac
        import hashlib
        import base64
        
        string_to_sign = f"{timestamp}\n{secret}"
        secret_encoded = secret.encode('utf-8')
        string_to_sign_encoded = string_to_sign.encode('utf-8')
        hmac_code = hmac.new(secret_encoded, string_to_sign_encoded, digestmod=hashlib.sha256).digest()
        sign = base64.b64encode(hmac_code).decode('utf-8')
        return sign
    
    def __del__(self):
        """析构时关闭会话"""
        if self._session:
            try:
                import asyncio
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(self.close())
                else:
                    loop.run_until_complete(self.close())
            except:
                pass


class WebhookAlertSender(AlertSender):
    """Webhook 告警发送器"""
    
    def __init__(
        self,
        webhook_url: str = None,
        headers: Dict[str, str] = None,
        session: Any = None
    ):
        self.webhook_url = webhook_url
        self.headers = headers or {"Content-Type": "application/json"}
        self.session = session
    
    async def send(self, alert: AlertMessage) -> bool:
        """发送 Webhook 告警"""
        if not self.webhook_url:
            return False
        
        try:
            import aiohttp
            
            payload = alert.to_dict()
            
            if self.session:
                async with self.session.post(
                    self.webhook_url,
                    json=payload,
                    headers=self.headers
                ) as resp:
                    return resp.status == 200
            else:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        self.webhook_url,
                        json=payload,
                        headers=self.headers
                    ) as resp:
                        return resp.status == 200
                        
        except Exception as e:
            logger.error(f"[Webhook] Send failed: {e}")
            return False


# ============================================
# 告警服务
# ============================================

class AlertService:
    """
    告警服务
    
    功能：
    - 多渠道通知
    - 告警限流和去重
    - 按机会质量分级提醒
    - 历史记录管理
    """
    
    def __init__(self, config: AlertConfig = None):
        """
        初始化告警服务
        
        Args:
            config: 告警配置
        """
        self.config = config or AlertConfig()
        
        # 初始化发送器
        self._senders: Dict[AlertChannel, AlertSender] = {}
        self._init_senders()
        
        # 限流控制
        self._rate_limit_counter: int = 0
        self._rate_limit_window: datetime = datetime.now()
        self._lock = asyncio.Lock()
        
        # 冷却时间控制
        self._cooldown_cache: Dict[str, datetime] = {}
        
        # 机会冷却（避免重复提醒）
        self._opportunity_cooldown: Dict[str, datetime] = {}
        
        # 历史记录
        self._history: List[AlertMessage] = []
        self._history_max_size: int = 1000
        
        logger.info(f"[AlertService] Initialized with channels: {[c.value for c in self.config.enabled_channels]}")
    
    def _init_senders(self) -> None:
        """初始化发送器"""
        # 日志发送器（总是启用）
        self._senders[AlertChannel.LOG] = LogAlertSender(logger)
        
        # Telegram
        if AlertChannel.TELEGRAM in self.config.enabled_channels:
            if self.config.telegram_bot_token and self.config.telegram_bot_token != "YOUR_TELEGRAM_BOT_TOKEN":
                self._senders[AlertChannel.TELEGRAM] = TelegramAlertSender(
                    bot_token=self.config.telegram_bot_token,
                    chat_id=self.config.telegram_chat_id
                )
        
        # 飞书
        if AlertChannel.FEISHU in self.config.enabled_channels:
            if self.config.feishu_webhook_url:
                self._senders[AlertChannel.FEISHU] = FeishuAlertSender(
                    webhook_url=self.config.feishu_webhook_url,
                    secret=settings.FEISHU_SECRET if settings.FEISHU_SECRET else None
                )
    
    async def send_alert(
        self,
        level: AlertLevel,
        alert_type: AlertType,
        title: str,
        message: str,
        data: Optional[Dict] = None,
        opportunity_id: Optional[str] = None,
        force: bool = False
    ) -> AlertResult:
        """
        发送告警
        
        Args:
            level: 告警级别
            alert_type: 告警类型
            title: 标题
            message: 消息内容
            data: 附加数据
            opportunity_id: 关联的机会 ID
            force: 强制发送（跳过冷却检查）
            
        Returns:
            AlertResult
        """
        # 检查最小级别
        if level.priority < self.config.min_level.priority:
            return AlertResult(
                success=True,
                error="Below minimum level"
            )
        
        # 创建消息
        alert = AlertMessage(
            level=level,
            alert_type=alert_type,
            title=title,
            message=message,
            data=data or {},
            opportunity_id=opportunity_id
        )
        
        # 检查限流
        if not force and not await self._check_rate_limit():
            return AlertResult(
                success=False,
                message=alert,
                error="Rate limit exceeded"
            )
        
        # 检查冷却时间
        if not force and not await self._check_cooldown(alert):
            return AlertResult(
                success=True,
                message=alert,
                error="Cooldown active",
                channels=["suppressed"]
            )
        
        # 发送到各渠道
        success_channels = []
        errors = []
        
        for channel, sender in self._senders.items():
            try:
                sent = await sender.send(alert)
                if sent:
                    success_channels.append(channel.value)
            except Exception as e:
                errors.append(f"{channel.value}: {e}")
        
        # 更新状态
        await self._mark_sent(alert)
        
        # 记录历史
        self._history.append(alert)
        if len(self._history) > self._history_max_size:
            self._history = self._history[-self._history_max_size:]
        
        return AlertResult(
            success=len(success_channels) > 0,
            message=alert,
            error="; ".join(errors) if errors else None,
            channels=success_channels
        )
    
    async def send_arbitrage_alert(
        self,
        opportunity: Any,
        force: bool = False
    ) -> AlertResult:
        """
        发送套利机会告警
        
        Args:
            opportunity: ArbitrageOpportunity 对象
            force: 强制发送
            
        Returns:
            AlertResult
        """
        # 检查利润阈值
        if opportunity.net_profit_usd < self.config.min_profit_threshold:
            return AlertResult(
                success=True,
                error="Below profit threshold"
            )
        
        # 确定告警级别
        level = self._get_opportunity_level(opportunity)
        
        # 生成消息
        emoji = level.emoji
        
        title = f"{emoji} 套利机会: {opportunity.symbol}"
        
        message = self._format_opportunity_message(opportunity)
        
        data = {
            "代币": opportunity.symbol,
            "路径": f"{opportunity.source_chain} → {opportunity.target_chain}",
            "跨链桥": opportunity.bridge,
            "买入价": f"${opportunity.buy_price:.4f}",
            "卖出价": f"${opportunity.sell_price:.4f}",
            "价差": f"{opportunity.price_diff_pct:.2f}%",
            "交易金额": f"${opportunity.trade_amount_usd:,.0f}",
            "毛利润": f"${opportunity.gross_profit_usd:.2f}",
            "总成本": f"${opportunity.total_cost:.2f}",
            "净利润": f"${opportunity.net_profit_usd:.2f}",
            "风险等级": opportunity.risk_level.value,
            "风险分数": f"{opportunity.risk_score:.2f}",
            "预计时间": f"{opportunity.estimated_duration_minutes} 分钟",
        }
        
        return await self.send_alert(
            level=level,
            alert_type=AlertType.ARBITRAGE_OPPORTUNITY,
            title=title,
            message=message,
            data=data,
            opportunity_id=opportunity.id,
            force=force
        )
    
    def _get_opportunity_level(self, opportunity: Any) -> AlertLevel:
        """根据机会确定告警级别"""
        # 极高利润 -> 紧急
        if opportunity.net_profit_usd > 500:
            return AlertLevel.EMERGENCY
        
        # 高利润、低风险 -> 严重
        if opportunity.net_profit_usd > 100 and opportunity.risk_score < 0.3:
            return AlertLevel.CRITICAL
        
        # 中等利润 -> 警告
        if opportunity.net_profit_usd > 50:
            return AlertLevel.WARNING
        
        # 一般机会 -> 信息
        return AlertLevel.INFO
    
    def _format_opportunity_message(self, opportunity: Any) -> str:
        """格式化机会消息"""
        lines = [
            f"🔥 **{opportunity.symbol}** 跨链套利",
            "",
            f"📍 路径: `{opportunity.source_chain}` → `{opportunity.target_chain}`",
            f"🌉 桥接: `{opportunity.bridge.upper()}`",
            "",
            f"💰 价差: `{opportunity.price_diff_pct:.2f}%`",
            f"💵 交易: `${opportunity.trade_amount_usd:,.0f}`",
            f"📈 毛利: `${opportunity.gross_profit_usd:.2f}`",
            f"📉 成本: `${opportunity.total_cost:.2f}`",
            "",
            f"✨ **净利润: ${opportunity.net_profit_usd:.2f}**",
            "",
            f"⏱️ 预计: {opportunity.estimated_duration_minutes} 分钟",
        ]
        
        if opportunity.risk_factors:
            lines.append("")
            lines.append("⚠️ 风险因素:")
            for factor in opportunity.risk_factors[:3]:
                lines.append(f"  • {factor}")
        
        lines.append("")
        lines.append(f"🎯 建议: `{opportunity.recommendation.value}`")
        
        return "\n".join(lines)
    
    async def _check_rate_limit(self) -> bool:
        """检查限流"""
        async with self._lock:
            now = datetime.now()
            
            # 重置窗口
            if (now - self._rate_limit_window).total_seconds() >= 60:
                self._rate_limit_counter = 0
                self._rate_limit_window = now
            
            # 检查限制
            if self._rate_limit_counter >= self.config.rate_limit_per_minute:
                return False
            
            self._rate_limit_counter += 1
            return True
    
    async def _check_cooldown(self, alert: AlertMessage) -> bool:
        """检查冷却时间"""
        # 检查机会冷却
        if alert.opportunity_id:
            if alert.opportunity_id in self._opportunity_cooldown:
                last_sent = self._opportunity_cooldown[alert.opportunity_id]
                if (datetime.now() - last_sent).total_seconds() < self.config.opportunity_cooldown:
                    return False
        
        # 检查通用冷却
        cache_key = alert.cache_key
        if cache_key in self._cooldown_cache:
            last_sent = self._cooldown_cache[cache_key]
            if (datetime.now() - last_sent).total_seconds() < self.config.cooldown_seconds:
                return False
        
        return True
    
    async def _mark_sent(self, alert: AlertMessage) -> None:
        """标记已发送"""
        async with self._lock:
            if alert.opportunity_id:
                self._opportunity_cooldown[alert.opportunity_id] = datetime.now()
            
            self._cooldown_cache[alert.cache_key] = datetime.now()
    
    async def send_system_alert(
        self,
        title: str,
        message: str,
        level: AlertLevel = AlertLevel.INFO
    ) -> AlertResult:
        """发送系统告警"""
        return await self.send_alert(
            level=level,
            alert_type=AlertType.MONITORING_STATUS,
            title=title,
            message=message,
            force=True
        )
    
    def get_history(
        self,
        limit: int = 100,
        level: AlertLevel = None,
        alert_type: AlertType = None
    ) -> List[AlertMessage]:
        """获取历史告警"""
        history = self._history
        
        if level:
            history = [h for h in history if h.level == level]
        
        if alert_type:
            history = [h for h in history if h.alert_type == alert_type]
        
        return history[-limit:]
    
    def get_stats(self) -> Dict:
        """获取统计信息"""
        if not self._history:
            return {
                "total": 0,
                "by_level": {},
                "by_type": {},
            }
        
        by_level = {}
        by_type = {}
        
        for alert in self._history:
            level = alert.level.value
            alert_type = alert.alert_type.value
            
            by_level[level] = by_level.get(level, 0) + 1
            by_type[alert_type] = by_type.get(alert_type, 0) + 1
        
        return {
            "total": len(self._history),
            "by_level": by_level,
            "by_type": by_type,
            "rate_limit_remaining": self.config.rate_limit_per_minute - self._rate_limit_counter,
        }
    
    def clear_history(self) -> int:
        """清空历史记录"""
        count = len(self._history)
        self._history = []
        return count


# ============================================
# 全局实例
# ============================================

# 全局告警服务实例
alert_service: Optional[AlertService] = None


def get_alert_service() -> AlertService:
    """获取告警服务实例"""
    global alert_service
    
    if alert_service is None:
        alert_service = AlertService()
    
    return alert_service


async def send_arbitrage_alert(opportunity: Any) -> AlertResult:
    """发送套利告警的便捷函数"""
    service = get_alert_service()
    return await service.send_arbitrage_alert(opportunity)
