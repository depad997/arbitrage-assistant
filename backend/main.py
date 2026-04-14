"""
链上套利助手 - Backend 入口文件

FastAPI 应用主入口

Phase 1 功能:
- 多链价格监控 (DexScreener API)
- REST API 端点
- WebSocket 实时价格推送

Phase 2 功能:
- 跨链桥费用监控 (LayerZero, Wormhole)
- 套利机会检测
- 告警推送 (Telegram, 飞书)
- 主监控循环
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, BackgroundTasks, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import List, Optional, Dict, Set, Any
import logging
import asyncio
from datetime import datetime

import sys
import os

# 添加 backend 目录到路径
_backend_dir = os.path.dirname(os.path.abspath(__file__))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from config.settings import settings, ENABLED_CHAINS, SUPPORTED_CHAINS
from config.cross_chain_tokens import MAJOR_TRADING_TOKENS, TOKENS_BY_TYPE, ALL_CROSS_CHAIN_TOKENS
from services.price_monitor import PriceMonitorService, TokenPrice, PriceCache
from services.bridge_fee_monitor import BridgeFeeMonitorService, BridgeFee, get_bridge_fee_monitor
from services.opportunity_detector import (
    OpportunityDetector,
    OpportunityDetectorService,
    ArbitrageConfig,
    ArbitrageOpportunity,
    get_opportunities,
)
from services.alert import (
    AlertService,
    AlertLevel,
    AlertType,
    AlertMessage,
    AlertResult,
    AlertChannel,
    get_alert_service,
)
from services.monitor_loop import MonitorLoop, MonitorConfig, get_monitor_loop
from utils.helpers import setup_logger, format_currency, format_percent

# ============================================
# 日志配置
# ============================================

logger = setup_logger(
    name="arbitrage-assistant",
    level=getattr(logging, settings.LOG_LEVEL),
    log_file=settings.LOG_FILE
)

# ============================================
# 全局服务实例
# ============================================

# 价格监控服务（延迟初始化）
price_service: Optional[PriceMonitorService] = None

# 告警服务（延迟初始化）
alert_service: Optional[AlertService] = None

# 费用监控服务（延迟初始化）
bridge_fee_service: Optional[BridgeFeeMonitorService] = None

# 机会检测服务（延迟初始化）
opportunity_service: Optional[OpportunityDetectorService] = None

# 监控循环（延迟初始化）
monitor_loop: Optional[MonitorLoop] = None

# WebSocket 连接管理器
ws_manager: Optional["ConnectionManager"] = None


class ConnectionManager:
    """WebSocket 连接管理器"""
    
    def __init__(self):
        self.active_connections: Set[WebSocket] = set()
        self._lock = asyncio.Lock()
    
    async def connect(self, websocket: WebSocket):
        """接受并记录 WebSocket 连接"""
        await websocket.accept()
        async with self._lock:
            self.active_connections.add(websocket)
        logger.info(f"[WS] Client connected. Total: {len(self.active_connections)}")
    
    async def disconnect(self, websocket: WebSocket):
        """断开 WebSocket 连接"""
        async with self._lock:
            self.active_connections.discard(websocket)
        logger.info(f"[WS] Client disconnected. Total: {len(self.active_connections)}")
    
    async def broadcast(self, message: dict):
        """广播消息到所有连接"""
        async with self._lock:
            connections = list(self.active_connections)
        
        for connection in connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.warning(f"[WS] Send error: {e}")
                await self.disconnect(connection)


# ============================================
# 应用生命周期
# ============================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    global price_service, alert_service, bridge_fee_service, opportunity_service, ws_manager, monitor_loop
    
    logger.info(f"Starting {settings.APP_NAME} v{settings.APP_VERSION}")
    
    # 初始化 WebSocket 管理器
    ws_manager = ConnectionManager()
    
    # 初始化服务
    try:
        # 价格监控服务（Phase 1 核心）
        price_service = PriceMonitorService(
            redis_client=None,  # TODO: 配置 Redis
            polling_interval=settings.PRICE_POLLING_INTERVAL,
            cache_ttl=settings.CACHE_TTL_PRICE
        )
        await price_service.start()
        logger.info("PriceMonitorService initialized")
        
        # 告警服务
        alert_service = AlertService()
        logger.info("AlertService initialized")
        
        # 费用监控服务（Phase 2）
        bridge_fee_service = get_bridge_fee_monitor()
        logger.info("BridgeFeeMonitorService initialized")
        
        # 机会检测服务（Phase 2）- 使用跨链代币配置
        opportunity_service = OpportunityDetectorService(
            config=ArbitrageConfig(
                monitoring_chains=ENABLED_CHAINS[:8],  # 监控前8条链
                monitoring_symbols=MAJOR_TRADING_TOKENS,  # 使用跨链代币列表
                min_profit_threshold_usd=10.0,
            )
        )
        await opportunity_service.initialize(
            price_monitor=price_service,
            fee_monitor=bridge_fee_service
        )
        logger.info("OpportunityDetectorService initialized")
        
    except Exception as e:
        logger.error(f"Failed to initialize services: {e}")
        raise
    
    logger.info("Application startup complete")

    # Phase 3 组件初始化
    try:
        # 策略管理器
        from services.auto_strategy import init_strategy_manager
        strategy_mgr = await init_strategy_manager()
        logger.info("StrategyManager initialized")
        
        # 资金管理器
        from services.fund_manager import init_fund_manager
        fund_mgr = await init_fund_manager()
        logger.info("FundManager initialized")
        
        # 闪电贷管理器
        from services.flash_loan_manager import init_flash_loan_manager
        flash_loan_mgr = await init_flash_loan_manager()
        logger.info("FlashLoanManager initialized")
        
        # 执行调度器
        from services.execution_scheduler import init_execution_scheduler
        scheduler = await init_execution_scheduler()
        logger.info("ExecutionScheduler initialized")
        
        # 主控制器
        from services.auto_controller import init_auto_controller
        controller = await init_auto_controller()
        logger.info("AutoController initialized")
        
        # 监控器 V2
        from services.monitor_v2 import init_monitor_v2
        monitor_v2 = await init_monitor_v2()
        logger.info("MonitorV2 initialized")
        
    except Exception as e:
        logger.warning(f"Phase 3 components initialization warning: {e}")

    
    yield  # 应用运行中
    
    # 清理
    logger.info("Shutting down...")

    # Phase 3 组件清理
    try:
        from services.monitor_v2 import get_monitor_v2
        monitor_v2 = get_monitor_v2()
        if monitor_v2._is_running:
            await monitor_v2.stop()
        
        from services.auto_controller import get_auto_controller
        controller = get_auto_controller()
        if controller.state.value in ["running", "paused"]:
            await controller.stop()
            
    except Exception as e:
        logger.warning(f"Phase 3 cleanup warning: {e}")

    if price_service:
        await price_service.stop()
    if monitor_loop and monitor_loop.is_running:
        await monitor_loop.stop()


# ============================================
# FastAPI 应用
# ============================================

app = FastAPI(
    title=settings.APP_NAME,
    description="多链、多策略的链上套利分析系统 (Phase 2)",
    version=settings.APP_VERSION,
    lifespan=lifespan
)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境应限制
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)



# Phase 3 自动化执行路由
try:
    from api.routes.automation import router as automation_router
    logger.info("Phase 3 Automation routes loaded")
except ImportError as e:
    logger.warning(f"Phase 3 routes not available: {e}")
    automation_router = None

# ============================================
# Pydantic 模型
# ============================================

class PriceRequest(BaseModel):
    """价格查询请求"""
    chain: str
    token_address: str


class PriceResponse(BaseModel):
    """价格响应"""
    success: bool
    data: Optional[TokenPrice] = None
    error: Optional[str] = None


class ArbitrageCheckRequest(BaseModel):
    """套利检测请求"""
    chain: str
    token_address: Optional[str] = None
    min_profit: float = 10.0
    min_liquidity: float = 10000.0


class AlertRequest(BaseModel):
    """手动告警请求"""
    level: str
    title: str
    message: str
    data: Optional[Dict] = None


class HealthResponse(BaseModel):
    """健康检查响应"""
    status: str
    version: str
    services: Dict[str, bool]


# ============================================
# API 路由
# ============================================

@app.get("/", tags=["Root"])
async def root():
    """根路径"""
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "docs": "/docs",
        "web": "/web",
        "phase": "Phase 2"
    }


@app.get("/web", response_class=HTMLResponse, tags=["Root"])
async def web_dashboard():
    """Web 前端面板"""
    return '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>链上套利助手</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: system-ui, sans-serif; background: #111827; color: #f3f4f6; padding: 20px; }
        .card { background: #1f2937; border-radius: 12px; padding: 20px; margin-bottom: 20px; }
        h1 { color: #60a5fa; margin-bottom: 20px; }
        h2 { color: #9ca3af; font-size: 14px; margin-bottom: 10px; }
        h3 { color: #f3f4f6; font-size: 16px; margin-bottom: 10px; }
        table { width: 100%; border-collapse: collapse; }
        th, td { padding: 12px; text-align: left; border-bottom: 1px solid #374151; }
        th { color: #9ca3af; font-size: 12px; }
        .green { color: #34d399; }
        .red { color: #ef4444; }
        .blue { color: #60a5fa; }
        .purple { color: #a78bfa; }
        .yellow { color: #fbbf24; }
        .btn { background: #3b82f6; color: white; padding: 10px 20px; border: none; border-radius: 8px; cursor: pointer; margin-right: 10px; margin-bottom: 10px; }
        .btn:hover { background: #2563eb; }
        .btn-green { background: #10b981; }
        .btn-green:hover { background: #059669; }
        .btn-sm { padding: 5px 10px; font-size: 12px; }
        #status { padding: 10px; border-radius: 8px; margin-bottom: 20px; }
        .ok { background: #064e3b; color: #34d399; }
        .err { background: #7f1d1d; color: #fca5a5; }
        .stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 15px; margin-bottom: 20px; }
        .stat { background: #1f2937; border-radius: 12px; padding: 20px; }
        .stat-value { font-size: 24px; font-weight: bold; margin: 5px 0; }
        .stat-label { color: #9ca3af; font-size: 12px; }
        .tabs { display: flex; gap: 5px; margin-bottom: 15px; flex-wrap: wrap; }
        .tab { padding: 8px 16px; border-radius: 8px; cursor: pointer; background: #374151; color: #9ca3af; }
        .tab.active { background: #3b82f6; color: white; }
        .price-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 10px; }
        .price-card { background: #374151; border-radius: 8px; padding: 15px; }
        .price-symbol { font-weight: bold; font-size: 16px; }
        .price-value { font-size: 20px; font-weight: bold; margin: 5px 0; }
        .price-change { font-size: 12px; }
        .chain-badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 10px; margin-left: 5px; }
        .chain-eth { background: #627eea; }
        .chain-arb { background: #28a0f0; }
        .chain-bsc { background: #f0b90b; color: #000; }
        .chain-poly { background: #8247e5; }
        .chain-sol { background: #9945ff; }
        .chain-base { background: #0052ff; }
        @media (max-width: 768px) { .stats { grid-template-columns: repeat(2, 1fr); } }
    </style>
</head>
<body>
    <h1>🥥 链上套利助手</h1>
    
    <div id="status" class="card">正在连接后端...</div>
    
    <div class="stats">
        <div class="stat">
            <div class="stat-label">监控状态</div>
            <div class="stat-value" id="statStatus">-</div>
        </div>
        <div class="stat">
            <div class="stat-label">支持链数</div>
            <div class="stat-value" id="statChains">-</div>
        </div>
        <div class="stat">
            <div class="stat-label">套利机会</div>
            <div class="stat-value green" id="statOpps">-</div>
        </div>
        <div class="stat">
            <div class="stat-label">API状态</div>
            <div class="stat-value green" id="statAPI">-</div>
        </div>
    </div>

    <div class="card">
        <button class="btn" onclick="scan()">🔄 扫描机会</button>
        <button class="btn" onclick="fetchPrices()">💰 刷新价格</button>
        <button class="btn btn-green" onclick="startMonitor()">▶ 启动监控</button>
        <button class="btn" onclick="stopMonitor()" style="background:#ef4444">⏹ 停止</button>
        <button class="btn" onclick="testAlert()" style="background:#8b5cf6">🔔 测试通知</button>
    </div>

    <!-- 实时价格模块 -->
    <div class="card">
        <h2>💰 实时价格</h2>
        <div class="tabs" id="chainTabs"></div>
        <div id="priceContent">
            <p style="color:#9ca3af">点击"刷新价格"获取最新数据...</p>
        </div>
    </div>

    <!-- 套利机会模块 -->
    <div class="card">
        <h2>🎯 套利机会 (<span id="oppCount">0</span>)</h2>
        <table>
            <thead>
                <tr>
                    <th>代币</th>
                    <th>路径</th>
                    <th>价差</th>
                    <th>收益率</th>
                    <th>净利润</th>
                    <th>风险</th>
                    <th>操作</th>
                </tr>
            </thead>
            <tbody id="oppTable">
                <tr><td colspan="7">加载中...</td></tr>
            </tbody>
        </table>
    </div>

    <script>
    const API = window.location.origin;
    const CHAINS = [
        { id: 'ethereum', name: 'Ethereum', badge: 'chain-eth' },
        { id: 'arbitrum', name: 'Arbitrum', badge: 'chain-arb' },
        { id: 'bsc', name: 'BSC', badge: 'chain-bsc' },
        { id: 'polygon', name: 'Polygon', badge: 'chain-poly' },
        { id: 'base', name: 'Base', badge: 'chain-base' },
        { id: 'solana', name: 'Solana', badge: 'chain-sol' },
    ];
    let currentChain = 'ethereum';
    let priceData = {};

    // 初始化链标签
    function initChainTabs() {
        document.getElementById('chainTabs').innerHTML = CHAINS.map(c => 
            `<div class="tab ${c.id === currentChain ? 'active' : ''}" onclick="switchChain('${c.id}')">${c.name}</div>`
        ).join('');
    }

    function switchChain(chain) {
        currentChain = chain;
        initChainTabs();
        renderPrices();
    }

    async function fetchPrices() {
        const content = document.getElementById('priceContent');
        content.innerHTML = '<p style="color:#9ca3af">正在从多条链获取实时价格...</p>';
        
        try {
            // 从多条链获取价格
            const chains = ['ethereum', 'arbitrum', 'optimism', 'base', 'bsc', 'polygon', 'avalanche'];
            const allPrices = {};
            
            // 并行请求所有链的价格
            const requests = chains.map(async chain => {
                try {
                    const resp = await fetch(API + '/api/prices/onchain/' + chain);
                    const data = await resp.json();
                    if (data.success && data.data.prices) {
                        return { chain, prices: data.data.prices };
                    }
                } catch (e) {
                    console.log('Failed to fetch ' + chain);
                }
                return null;
            });
            
            const results = await Promise.all(requests);
            
            // 整理数据：{symbol: {chain: price}}
            results.forEach(result => {
                if (result) {
                    Object.entries(result.prices).forEach(([symbol, price]) => {
                        if (!allPrices[symbol]) allPrices[symbol] = {};
                        allPrices[symbol][result.chain] = price;
                    });
                }
            });
            
            window.allPrices = allPrices;
            window.priceSource = 'onchain_dex';
            renderAllPrices();
        } catch (e) {
            content.innerHTML = '<p style="color:#ef4444">获取价格失败: ' + e.message + '</p>';
        }
    }

    function renderAllPrices() {
        const content = document.getElementById('priceContent');
        const allPrices = window.allPrices || {};
        const symbols = Object.keys(allPrices);
        
        if (symbols.length === 0) {
            content.innerHTML = '<p style="color:#9ca3af">点击"刷新价格"获取数据...</p>';
            return;
        }
        
        // 按类别分组
        const categories = {
            '稳定币': ['USDC', 'USDT', 'DAI', 'BUSD', 'TUSD'],
            '主流币': ['ETH', 'WETH', 'WBTC', 'BNB', 'MATIC', 'AVAX', 'SOL', 'ATOM', 'DOT'],
            'DeFi': ['LINK', 'UNI', 'AAVE', 'MKR', 'CRV', 'COMP', 'SUSHI', 'SNX'],
            'L2原生': ['ARB', 'OP'],
            '跨链桥': ['W', 'STG', 'SYN', 'AXL'],
            '流动性质押': ['stETH', 'wstETH', 'rETH'],
            'Meme': ['PEPE', 'SHIB', 'BONK', 'WIF', 'DOGE'],
            'GameFi': ['SAND', 'MANA', 'AXS', 'IMX'],
            'RWA': ['ONDO'],
        };
        
        let html = '<p style="color:#10b981;font-size:12px;margin-bottom:15px">✅ 链上真实价格 - 点击代币查看各链价格对比</p>';
        
        Object.entries(categories).forEach(([cat, catSymbols]) => {
            const inCat = symbols.filter(s => catSymbols.includes(s));
            if (inCat.length === 0) return;
            
            html += `<h3 style="color:#9ca3af;font-size:13px;margin:15px 0 10px">${cat}</h3>`;
            html += '<div class="price-table" style="background:#1f2937;border-radius:8px;overflow:hidden">';
            
            // 表头
            html += '<div style="display:grid;grid-template-columns:80px repeat(7,1fr);padding:10px;background:#374151;font-size:12px;color:#9ca3af">';
            html += '<div>代币</div>';
            ['ETH', 'ARB', 'OP', 'Base', 'BSC', 'Polygon', 'Avalanche'].forEach(c => {
                html += `<div style="text-align:right">${c}</div>`;
            });
            html += '</div>';
            
            // 价格行
            inCat.forEach(symbol => {
                const prices = allPrices[symbol] || {};
                const chainPrices = [
                    prices.ethereum, prices.arbitrum, prices.optimism, 
                    prices.base, prices.bsc, prices.polygon, prices.avalanche
                ];
                
                // 找最高最低价计算价差
                const validPrices = chainPrices.filter(p => p && p > 0);
                const maxPrice = Math.max(...validPrices);
                const minPrice = Math.min(...validPrices);
                const priceDiff = maxPrice > 0 && minPrice > 0 ? ((maxPrice - minPrice) / minPrice * 100) : 0;
                const hasArb = priceDiff > 1;
                
                html += `<div style="display:grid;grid-template-columns:80px repeat(7,1fr);padding:10px;border-top:1px solid #374151;font-size:13px;${hasArb ? 'background:rgba(16,185,129,0.1)' : ''}">`;
                html += `<div style="font-weight:bold;color:${hasArb ? '#10b981' : '#f3f4f6'}">${symbol}${hasArb ? ' 💰' : ''}</div>`;
                
                chainPrices.forEach(p => {
                    if (p && p > 0) {
                        const isMax = p === maxPrice && priceDiff > 1;
                        const isMin = p === minPrice && priceDiff > 1;
                        const color = isMax ? '#ef4444' : isMin ? '#10b981' : '#f3f4f6';
                        html += `<div style="text-align:right;color:${color}">${formatPrice(p)}</div>`;
                    } else {
                        html += '<div style="text-align:right;color:#6b7280">-</div>';
                    }
                });
                html += '</div>';
                
                // 如果有套利机会，显示价差
                if (hasArb) {
                    html += `<div style="padding:5px 10px;font-size:11px;color:#10b981;border-top:1px dashed #374151">→ 价差 ${priceDiff.toFixed(2)}% | 潜在利润 $${(10000 * priceDiff / 100).toFixed(0)}</div>`;
                }
            });
            
            html += '</div>';
        });
        
        content.innerHTML = html;
    }

    function renderPrices() {
        renderAllPrices();
    }

    function formatPrice(p) {
        if (!p) return '-';
        if (p >= 1000) return p.toFixed(2);
        if (p >= 1) return p.toFixed(4);
        return p.toFixed(6);
    }

    function formatNum(n) {
        if (!n) return '-';
        if (n >= 1e9) return (n/1e9).toFixed(2) + 'B';
        if (n >= 1e6) return (n/1e6).toFixed(2) + 'M';
        if (n >= 1e3) return (n/1e3).toFixed(2) + 'K';
        return n.toFixed(2);
    }

    async function load() {
        const status = document.getElementById('status');
        try {
            const r = await fetch(API + '/api/status');
            const d = await r.json();
            
            document.getElementById('statStatus').textContent = d.status?.running ? '运行中 🟢' : '已停止 🔴';
            document.getElementById('statChains').textContent = d.status?.chains?.length || 16;
            
            const opp = await fetch(API + '/api/opportunities');
            const oppData = await opp.json();
            const opportunities = oppData.data?.opportunities || [];
            document.getElementById('statOpps').textContent = opportunities.length;
            document.getElementById('oppCount').textContent = opportunities.length;
            
            document.getElementById('statAPI').textContent = '正常 ✅';
            status.className = 'card ok';
            status.innerHTML = '✅ 后端已连接 | API: ' + API + ' | <a href="/docs" style="color:#60a5fa">API文档</a>';
            
            const tbody = document.getElementById('oppTable');
            if (opportunities.length === 0) {
                tbody.innerHTML = '<tr><td colspan="7">暂无机会，点击"扫描机会"</td></tr>';
            } else {
                tbody.innerHTML = opportunities.slice(0, 15).map(o => `
                    <tr>
                        <td><b>${o.symbol}</b></td>
                        <td><span class="blue">${o.source_chain}</span> → <span class="purple">${o.target_chain}</span></td>
                        <td>${(o.price_diff_pct || 0).toFixed(2)}%</td>
                        <td class="green"><b>${(o.net_profit_pct || o.price_diff_pct || 0).toFixed(2)}%</b></td>
                        <td>$${(o.net_profit_usd || 0).toFixed(2)}</td>
                        <td><span style="color:${o.risk_level === 'very_low' ? '#34d399' : '#fbbf24'}">${o.risk_level === 'very_low' ? '极低' : '低'}</span></td>
                        <td><button class="btn btn-green btn-sm" onclick="execute('${o.id}')">执行</button></td>
                    </tr>
                `).join('');
            }

            // 自动加载价格
            if (opportunities.length > 0) {
                fetchPrices();
            }
        } catch (e) {
            status.className = 'card err';
            status.innerHTML = '❌ 连接失败: ' + e.message + ' <button class="btn" onclick="load()">重试</button>';
            document.getElementById('statAPI').textContent = '离线 ❌';
        }
    }

    async function scan() {
        const btn = event.target;
        btn.textContent = '⏳ 扫描中...';
        btn.disabled = true;
        try {
            const r = await fetch(API + '/api/opportunities/scan', { method: 'POST' });
            const d = await r.json();
            alert('扫描完成: 发现 ' + (d.data?.count || 0) + ' 个套利机会');
            load();
        } catch (e) {
            alert('扫描失败: ' + e.message);
        }
        btn.textContent = '🔄 扫描机会';
        btn.disabled = false;
    }

    async function startMonitor() {
        try {
            await fetch(API + '/api/monitor/start', { method: 'POST' });
            alert('监控已启动');
            load();
        } catch (e) {
            alert('启动失败: ' + e.message);
        }
    }

    async function stopMonitor() {
        try {
            await fetch(API + '/api/monitor/stop', { method: 'POST' });
            alert('监控已停止');
            load();
        } catch (e) {
            alert('停止失败: ' + e.message);
        }
    }

    async function testAlert() {
        try {
            await fetch(API + '/api/alerts/test', { method: 'POST' });
            alert('测试通知已发送到飞书');
        } catch (e) {
            alert('发送失败: ' + e.message);
        }
    }

    function execute(id) {
        alert('即将执行套利: ' + id + '\\n请先在 .env 文件中配置钱包私钥');
    }

    // 初始化
    initChainTabs();
    load();
    setInterval(load, 60000);
    </script>
</body>
</html>'''


@app.get("/health", response_model=HealthResponse, tags=["System"])
async def health_check():
    """健康检查"""
    return HealthResponse(
        status="healthy",
        version=settings.APP_VERSION,
        services={
            "price_monitor": price_service is not None,
            "alert": alert_service is not None,
            "bridge_fee": bridge_fee_service is not None,
            "opportunity": opportunity_service is not None,
            "monitor": monitor_loop is not None and monitor_loop.is_running,
        }
    )


# ----------------------------------------
# 价格相关接口 (Phase 1)
# ----------------------------------------

@app.post("/api/v1/price", response_model=PriceResponse, tags=["Price"])
async def get_token_price(request: PriceRequest):
    """
    获取代币价格
    
    支持的链: ethereum, bsc, arbitrum, polygon, avalanche, optimism, solana
    """
    try:
        price = await price_service.get_token_price(
            chain=request.chain,
            token_address=request.token_address
        )
        
        return PriceResponse(success=True, data=price)
    
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Price fetch error: {e}")
        return PriceResponse(success=False, error=str(e))


# ============================================
# Phase 2: 套利机会 API
# ============================================

class OpportunityResponse(BaseModel):
    """套利机会响应"""
    success: bool
    data: Optional[Dict] = None
    error: Optional[str] = None


@app.get("/api/opportunities", response_model=OpportunityResponse, tags=["Arbitrage (Phase 2)"])
async def get_opportunities(
    min_profit: float = 10.0,
    limit: int = 10,
    symbol: Optional[str] = None
):
    """
    获取当前套利机会
    
    - **min_profit**: 最小利润阈值（USD）
    - **limit**: 返回数量限制
    - **symbol**: 可选，特定代币过滤
    
    返回当前检测到的所有盈利套利机会
    """
    try:
        if opportunity_service is None:
            return OpportunityResponse(
                success=False,
                error="Opportunity service not initialized"
            )
        
        # 扫描新机会
        await opportunity_service.scan()
        
        # 获取机会
        opportunities = opportunity_service.get_opportunities(
            min_profit=min_profit,
            limit=limit
        )
        
        # 如果指定了代币，过滤
        if symbol:
            opportunities = [o for o in opportunities if o.symbol.upper() == symbol.upper()]
        
        return OpportunityResponse(
            success=True,
            data={
                "count": len(opportunities),
                "opportunities": [o.to_dict() for o in opportunities],
                "stats": opportunity_service.get_stats(),
                "timestamp": datetime.now().isoformat()
            }
        )
    
    except Exception as e:
        logger.error(f"Get opportunities error: {e}")
        return OpportunityResponse(success=False, error=str(e))


@app.post("/api/opportunities/scan", response_model=OpportunityResponse, tags=["Arbitrage (Phase 2)"])
async def scan_opportunities(
    symbols: Optional[str] = None,
    chains: Optional[str] = None
):
    """
    扫描套利机会
    
    - **symbols**: 可选，代币列表（逗号分隔）
    - **chains**: 可选，链列表（逗号分隔）
    """
    try:
        if opportunity_service is None:
            return OpportunityResponse(
                success=False,
                error="Opportunity service not initialized"
            )
        
        symbol_list = [s.strip().upper() for s in symbols.split(",")] if symbols else None
        chain_list = [c.strip().lower() for c in chains.split(",")] if chains else None
        
        # 扫描
        all_opportunities = []
        if symbol_list:
            for sym in symbol_list:
                opps = await opportunity_service.scan_symbol(sym)
                all_opportunities.extend(opps)
        else:
            all_opportunities = await opportunity_service.scan()
        
        return OpportunityResponse(
            success=True,
            data={
                "count": len(all_opportunities),
                "opportunities": [o.to_dict() for o in all_opportunities[:10]],
                "profitable_count": len([o for o in all_opportunities if o.is_profitable]),
                "timestamp": datetime.now().isoformat()
            }
        )
    
    except Exception as e:
        logger.error(f"Scan opportunities error: {e}")
        return OpportunityResponse(success=False, error=str(e))


@app.get("/api/opportunities/{opportunity_id}", response_model=OpportunityResponse, tags=["Arbitrage (Phase 2)"])
async def get_opportunity_detail(opportunity_id: str):
    """
    获取套利机会详情
    
    - **opportunity_id**: 机会 ID
    """
    try:
        if opportunity_service is None or opportunity_service.detector is None:
            return OpportunityResponse(
                success=False,
                error="Opportunity service not initialized"
            )
        
        detector = opportunity_service.detector
        if opportunity_id in detector._opportunity_map:
            opp = detector._opportunity_map[opportunity_id]
            return OpportunityResponse(
                success=True,
                data=opp.to_dict()
            )
        
        return OpportunityResponse(
            success=False,
            error=f"Opportunity {opportunity_id} not found"
        )
    
    except Exception as e:
        logger.error(f"Get opportunity detail error: {e}")
        return OpportunityResponse(success=False, error=str(e))


# ============================================
# Phase 2: 跨链桥费用 API
# ============================================

class BridgeFeeResponse(BaseModel):
    """跨链费用响应"""
    success: bool
    data: Optional[Dict] = None
    error: Optional[str] = None


@app.get("/api/bridge-fees/{src}/{dst}", response_model=BridgeFeeResponse, tags=["Bridge Fees (Phase 2)"])
async def get_bridge_fee(
    src: str,
    dst: str,
    bridge: str = "layerzero"
):
    """
    获取跨链费用
    
    - **src**: 源链 (ethereum, arbitrum, bsc, etc.)
    - **dst**: 目标链
    - **bridge**: 桥接类型 (layerzero, wormhole)
    """
    try:
        if bridge_fee_service is None:
            return BridgeFeeResponse(
                success=False,
                error="Bridge fee service not initialized"
            )
        
        # 验证链
        if src not in ENABLED_CHAINS:
            return BridgeFeeResponse(
                success=False,
                error=f"Unsupported source chain: {src}"
            )
        if dst not in ENABLED_CHAINS:
            return BridgeFeeResponse(
                success=False,
                error=f"Unsupported target chain: {dst}"
            )
        
        # 获取费用
        fee = await bridge_fee_service.get_fee(src, dst, bridge)
        
        if fee:
            return BridgeFeeResponse(
                success=True,
                data=fee.to_dict()
            )
        
        return BridgeFeeResponse(
            success=False,
            error=f"Failed to get fee for {src} -> {dst}"
        )
    
    except Exception as e:
        logger.error(f"Get bridge fee error: {e}")
        return BridgeFeeResponse(success=False, error=str(e))


@app.get("/api/bridge-fees/compare/{src}/{dst}", response_model=BridgeFeeResponse, tags=["Bridge Fees (Phase 2)"])
async def compare_bridge_fees(src: str, dst: str):
    """
    比较 LayerZero 和 Wormhole 费用
    
    - **src**: 源链
    - **dst**: 目标链
    """
    try:
        if bridge_fee_service is None:
            return BridgeFeeResponse(
                success=False,
                error="Bridge fee service not initialized"
            )
        
        # 获取两个桥的费用
        lz_fee = await bridge_fee_service.get_fee(src, dst, "layerzero")
        wh_fee = await bridge_fee_service.get_fee(src, dst, "wormhole")
        
        data = {
            "source_chain": src,
            "target_chain": dst,
            "layerzero": lz_fee.to_dict() if lz_fee else None,
            "wormhole": wh_fee.to_dict() if wh_fee else None,
            "best_bridge": None,
            "best_fee": None,
        }
        
        # 确定最优
        if lz_fee and wh_fee:
            if lz_fee.total_cost_usd < wh_fee.total_cost_usd:
                data["best_bridge"] = "layerzero"
                data["best_fee"] = lz_fee.total_cost_usd
            else:
                data["best_bridge"] = "wormhole"
                data["best_fee"] = wh_fee.total_cost_usd
        elif lz_fee:
            data["best_bridge"] = "layerzero"
            data["best_fee"] = lz_fee.total_cost_usd
        elif wh_fee:
            data["best_bridge"] = "wormhole"
            data["best_fee"] = wh_fee.total_cost_usd
        
        return BridgeFeeResponse(success=True, data=data)
    
    except Exception as e:
        logger.error(f"Compare bridge fees error: {e}")
        return BridgeFeeResponse(success=False, error=str(e))


@app.get("/api/bridge-fees/all", response_model=BridgeFeeResponse, tags=["Bridge Fees (Phase 2)"])
async def get_all_bridge_fees(
    chains: Optional[str] = None,
    bridge: str = "layerzero"
):
    """
    获取所有链对的跨链费用
    
    - **chains**: 可选，链列表（逗号分隔）
    - **bridge**: 桥接类型
    """
    try:
        if bridge_fee_service is None:
            return BridgeFeeResponse(
                success=False,
                error="Bridge fee service not initialized"
            )
        
        chain_list = None
        if chains:
            chain_list = [c.strip().lower() for c in chains.split(",")]
        
        # 获取所有费用
        all_fees = await bridge_fee_service.get_all_fees(
            chains=chain_list,
            bridges=[bridge]
        )
        
        # 转换格式
        fees_list = []
        for src_chain, fees in all_fees.items():
            for fee in fees:
                fees_list.append(fee.to_dict())
        
        return BridgeFeeResponse(
            success=True,
            data={
                "count": len(fees_list),
                "fees": fees_list,
                "summary": bridge_fee_service.get_fees_summary(),
                "cache_stats": bridge_fee_service.get_cache_stats(),
                "timestamp": datetime.now().isoformat()
            }
        )
    
    except Exception as e:
        logger.error(f"Get all bridge fees error: {e}")
        return BridgeFeeResponse(success=False, error=str(e))


# ============================================
# Phase 2: 监控 API
# ============================================

class MonitorResponse(BaseModel):
    """监控响应"""
    success: bool
    data: Optional[Dict] = None
    error: Optional[str] = None


@app.get("/api/monitor/status", response_model=MonitorResponse, tags=["Monitor (Phase 2)"])
async def get_monitor_status():
    """获取监控状态"""
    global monitor_loop
    
    if monitor_loop is None:
        monitor_loop = get_monitor_loop()
    
    return MonitorResponse(
        success=True,
        data={
            "is_running": monitor_loop.is_running,
            "status": monitor_loop.status.value if monitor_loop.status else "stopped",
            "stats": monitor_loop.get_stats() if monitor_loop else {},
            "config": {
                "polling_interval": 30,
                "debug_mode": False,
            }
        }
    )


@app.post("/api/monitor/start", response_model=MonitorResponse, tags=["Monitor (Phase 2)"])
async def start_monitor():
    """启动监控循环"""
    global monitor_loop
    
    try:
        if monitor_loop is None:
            monitor_loop = get_monitor_loop()
        
        if monitor_loop.is_running:
            return MonitorResponse(
                success=True,
                data={"message": "Monitor already running"}
            )
        
        await monitor_loop.start()
        
        return MonitorResponse(
            success=True,
            data={
                "message": "Monitor started",
                "status": "running"
            }
        )
    
    except Exception as e:
        logger.error(f"Start monitor error: {e}")
        return MonitorResponse(success=False, error=str(e))


@app.post("/api/monitor/stop", response_model=MonitorResponse, tags=["Monitor (Phase 2)"])
async def stop_monitor():
    """停止监控循环"""
    global monitor_loop
    
    try:
        if monitor_loop is None or not monitor_loop.is_running:
            return MonitorResponse(
                success=True,
                data={"message": "Monitor not running"}
            )
        
        await monitor_loop.stop()
        
        return MonitorResponse(
            success=True,
            data={
                "message": "Monitor stopped",
                "status": "stopped"
            }
        )
    
    except Exception as e:
        logger.error(f"Stop monitor error: {e}")
        return MonitorResponse(success=False, error=str(e))


@app.post("/api/monitor/pause", response_model=MonitorResponse, tags=["Monitor (Phase 2)"])
async def pause_monitor():
    """暂停监控"""
    global monitor_loop
    
    try:
        if monitor_loop is None:
            return MonitorResponse(success=False, error="Monitor not initialized")
        
        await monitor_loop.pause()
        
        return MonitorResponse(
            success=True,
            data={"message": "Monitor paused"}
        )
    
    except Exception as e:
        return MonitorResponse(success=False, error=str(e))


@app.post("/api/monitor/resume", response_model=MonitorResponse, tags=["Monitor (Phase 2)"])
async def resume_monitor():
    """恢复监控"""
    global monitor_loop
    
    try:
        if monitor_loop is None:
            return MonitorResponse(success=False, error="Monitor not initialized")
        
        await monitor_loop.resume()
        
        return MonitorResponse(
            success=True,
            data={"message": "Monitor resumed"}
        )
    
    except Exception as e:
        return MonitorResponse(success=False, error=str(e))


# ============================================
# Phase 2: 告警配置 API
# ============================================

class AlertConfigRequest(BaseModel):
    """告警配置请求"""
    telegram_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    feishu_webhook: Optional[str] = None
    min_profit_threshold: float = 10.0
    enabled_channels: List[str] = ["log"]


class AlertConfigResponse(BaseModel):
    """告警配置响应"""
    success: bool
    data: Optional[Dict] = None
    error: Optional[str] = None


@app.post("/api/alerts/config", response_model=AlertConfigResponse, tags=["Alert (Phase 2)"])
async def configure_alerts(config: AlertConfigRequest):
    """
    配置告警设置
    
    - **telegram_token**: Telegram Bot Token
    - **telegram_chat_id**: Telegram Chat ID
    - **feishu_webhook**: 飞书 Webhook URL
    - **min_profit_threshold**: 最小利润阈值（USD）
    - **enabled_channels**: 启用的渠道 (log, telegram, feishu)
    """
    global alert_service
    
    try:
        if alert_service is None:
            alert_service = get_alert_service()
        
        # 更新配置
        alert_service.config.telegram_bot_token = config.telegram_token or alert_service.config.telegram_bot_token
        alert_service.config.telegram_chat_id = config.telegram_chat_id or alert_service.config.telegram_chat_id
        alert_service.config.feishu_webhook_url = config.feishu_webhook or alert_service.config.feishu_webhook_url
        alert_service.config.min_profit_threshold = config.min_profit_threshold
        
        # 更新渠道
        channels = []
        for ch in config.enabled_channels:
            try:
                channels.append(AlertChannel(ch.lower()))
            except ValueError:
                pass
        if channels:
            alert_service.config.enabled_channels = channels
        
        return AlertConfigResponse(
            success=True,
            data={
                "message": "Alert configuration updated",
                "config": {
                    "min_profit_threshold": alert_service.config.min_profit_threshold,
                    "enabled_channels": [c.value for c in alert_service.config.enabled_channels],
                }
            }
        )
    
    except Exception as e:
        logger.error(f"Configure alerts error: {e}")
        return AlertConfigResponse(success=False, error=str(e))


@app.get("/api/alerts/config", response_model=AlertConfigResponse, tags=["Alert (Phase 2)"])
async def get_alert_config():
    """获取当前告警配置"""
    global alert_service
    
    try:
        if alert_service is None:
            alert_service = get_alert_service()
        
        return AlertConfigResponse(
            success=True,
            data={
                "config": {
                    "min_profit_threshold": alert_service.config.min_profit_threshold,
                    "enabled_channels": [c.value for c in alert_service.config.enabled_channels],
                    "rate_limit_per_minute": alert_service.config.rate_limit_per_minute,
                    "cooldown_seconds": alert_service.config.cooldown_seconds,
                },
                "stats": alert_service.get_stats(),
                "history_count": len(alert_service._history)
            }
        )
    
    except Exception as e:
        return AlertConfigResponse(success=False, error=str(e))


@app.get("/api/alerts/history", response_model=AlertConfigResponse, tags=["Alert (Phase 2)"])
async def get_alert_history(
    limit: int = 100,
    level: Optional[str] = None
):
    """获取告警历史"""
    global alert_service
    
    try:
        if alert_service is None:
            alert_service = get_alert_service()
        
        level_filter = None
        if level:
            try:
                level_filter = AlertLevel(level.lower())
            except ValueError:
                pass
        
        history = alert_service.get_history(limit=limit, level=level_filter)
        
        return AlertConfigResponse(
            success=True,
            data={
                "count": len(history),
                "alerts": [a.to_dict() for a in history]
            }
        )
    
    except Exception as e:
        return AlertConfigResponse(success=False, error=str(e))


@app.post("/api/alerts/test", response_model=AlertConfigResponse, tags=["Alert (Phase 2)"])
async def test_alert(
    channel: str = "log",
    level: str = "info"
):
    """发送测试告警"""
    global alert_service
    
    try:
        if alert_service is None:
            alert_service = get_alert_service()
        
        level_enum = AlertLevel(level.lower())
        
        result = await alert_service.send_alert(
            level=level_enum,
            alert_type=AlertType.SYSTEM_ERROR,
            title="测试告警",
            message=f"这是一条测试告警，级别: {level}",
            data={"test": True},
            force=True
        )
        
        return AlertConfigResponse(
            success=result.success,
            data={
                "message": "Test alert sent",
                "channels": result.channels,
                "error": result.error
            }
        )
    
    except Exception as e:
        return AlertConfigResponse(success=False, error=str(e))


# ============================================
# 价格相关接口 (Phase 1 延续)
# ============================================

class PriceRequestV2(BaseModel):
    """价格查询请求 V2"""
    chain: str
    symbol: str
    quote: str = "USDC"


class PriceResponseV2(BaseModel):
    """价格响应 V2"""
    success: bool
    data: Optional[Dict] = None
    error: Optional[str] = None


@app.get("/api/prices/{chain}", response_model=PriceResponseV2, tags=["Price Monitor"])
async def get_chain_prices(
    chain: str,
    symbols: Optional[str] = None
):
    """获取指定链的价格"""
    try:
        if chain not in ENABLED_CHAINS:
            return PriceResponseV2(
                success=False,
                error=f"Unsupported chain: {chain}"
            )
        
        symbol_list = None
        if symbols:
            symbol_list = [s.strip().upper() for s in symbols.split(",")]
        
        prices = await price_service.get_prices_by_chain(chain, symbol_list)
        
        return PriceResponseV2(
            success=True,
            data={
                "chain": chain,
                "prices": {sym: p.to_dict() for sym, p in prices.items()},
                "count": len(prices),
                "timestamp": datetime.now().isoformat()
            }
        )
    
    except Exception as e:
        logger.error(f"Get chain prices error: {e}")
        return PriceResponseV2(success=False, error=str(e))


@app.get("/api/prices/all", response_model=PriceResponseV2, tags=["Price Monitor"])
async def get_all_prices():
    """获取所有链的价格"""
    try:
        prices = await price_service.get_all_prices()
        
        return PriceResponseV2(
            success=True,
            data={
                "chains": ENABLED_CHAINS,
                "count": sum(len(p) for p in prices.values()),
                "timestamp": datetime.now().isoformat()
            }
        )
    
    except Exception as e:
        logger.error(f"Get all prices error: {e}")
        return PriceResponseV2(success=False, error=str(e))


@app.get("/api/prices/onchain/{chain}", tags=["Price Monitor"])
async def get_onchain_prices(chain: str):
    """从链上DEX获取真实价格（不依赖外部API）"""
    try:
        if chain not in ENABLED_CHAINS:
            return {"success": False, "error": f"Unsupported chain: {chain}"}
        
        from services.onchain_price import get_onchain_price_service
        onchain_svc = await get_onchain_price_service()
        prices = await onchain_svc.get_all_prices(chain)
        
        return {
            "success": True,
            "data": {
                "chain": chain,
                "prices": prices,
                "source": "onchain_dex",
                "timestamp": datetime.now().isoformat()
            }
        }
    
    except Exception as e:
        logger.error(f"Get onchain prices error: {e}")
        return {"success": False, "error": str(e)}


@app.get("/api/status", tags=["Price Monitor"])
async def get_monitor_status_v1():
    """获取价格监控服务状态"""
    try:
        status = await price_service.get_chain_status()
        
        return {
            "success": True,
            "status": status,
            "config": {
                "polling_interval": settings.PRICE_POLLING_INTERVAL,
                "cache_ttl": settings.CACHE_TTL_PRICE,
                "enabled_chains": ENABLED_CHAINS
            }
        }
    
    except Exception as e:
        logger.error(f"Get status error: {e}")
        return {"success": False, "error": str(e)}


# ----------------------------------------
# WebSocket 实时推送
# ----------------------------------------

@app.websocket("/ws/prices")
async def websocket_prices(websocket: WebSocket):
    """WebSocket 实时价格推送"""
    global ws_manager
    
    await ws_manager.connect(websocket)
    
    try:
        # 发送初始数据
        all_prices = price_service.prices
        await websocket.send_json({
            "type": "initial",
            "timestamp": datetime.now().isoformat(),
        })
        
        # 保持连接
        while True:
            try:
                data = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=30.0
                )
                
                if data == "ping":
                    await websocket.send_text("pong")
                    
            except asyncio.TimeoutError:
                await websocket.send_json({
                    "type": "heartbeat",
                    "timestamp": datetime.now().isoformat()
                })
                
    except WebSocketDisconnect:
        logger.info("[WS] Client disconnected")
    except Exception as e:
        logger.error(f"[WS] Error: {e}")
    finally:
        await ws_manager.disconnect(websocket)


@app.websocket("/ws/opportunities")
async def websocket_opportunities(websocket: WebSocket):
    """WebSocket 套利机会推送"""
    global ws_manager
    
    await ws_manager.connect(websocket)
    
    try:
        await websocket.send_json({
            "type": "connected",
            "timestamp": datetime.now().isoformat(),
            "message": "Subscribed to arbitrage opportunities"
        })
        
        while True:
            try:
                data = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=60.0
                )
                
                if data == "ping":
                    await websocket.send_text("pong")
                elif data == "snapshot":
                    # 发送当前机会快照
                    if opportunity_service:
                        opps = opportunity_service.get_opportunities(limit=10)
                        await websocket.send_json({
                            "type": "snapshot",
                            "opportunities": [o.to_dict() for o in opps],
                            "timestamp": datetime.now().isoformat()
                        })
                        
            except asyncio.TimeoutError:
                await websocket.send_json({
                    "type": "heartbeat",
                    "timestamp": datetime.now().isoformat()
                })
                
    except WebSocketDisconnect:
        logger.info("[WS] Opportunities client disconnected")
    except Exception as e:
        logger.error(f"[WS] Opportunities error: {e}")
    finally:
        await ws_manager.disconnect(websocket)


# ----------------------------------------
# 配置相关接口
# ----------------------------------------

@app.get("/api/v1/config/chains", tags=["Config"])
async def get_supported_chains():
    """获取支持的链列表"""
    return {
        "success": True,
        "chains": list(SUPPORTED_CHAINS.keys()),
        "enabled_chains": ENABLED_CHAINS
    }


@app.get("/api/v1/config/bridges", tags=["Config"])
async def get_supported_bridges():
    """获取支持的跨链桥"""
    return {
        "success": True,
        "bridges": ["layerzero", "wormhole"]
    }


# ============================================
# 入口点
# ============================================

if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG,
        log_level=settings.LOG_LEVEL.lower()
    )
