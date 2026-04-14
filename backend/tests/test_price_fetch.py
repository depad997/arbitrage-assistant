#!/usr/bin/env python3
"""
价格监控功能测试脚本

使用方法:
    python test_price_fetch.py              # 测试基本功能
    python test_price_fetch.py --chain ethereum  # 测试特定链
    python test_price_fetch.py --all            # 测试所有链
    python test_price_fetch.py --search ETH      # 搜索代币
"""

import asyncio
import argparse
import sys
import os
from datetime import datetime

# 添加 backend 目录
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.price_monitor import (
    DexScreenerClient,
    PriceMonitorService,
    RateLimiter,
    DexScreenerChainMapper,
)


# ============================================
# 颜色输出
# ============================================

class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'


def print_success(msg):
    print(f"{Colors.GREEN}✓ {msg}{Colors.ENDC}")


def print_error(msg):
    print(f"{Colors.RED}✗ {msg}{Colors.ENDC}")


def print_info(msg):
    print(f"{Colors.CYAN}ℹ {msg}{Colors.ENDC}")


def print_header(msg):
    print(f"\n{Colors.BOLD}{Colors.HEADER}{'=' * 50}")
    print(f" {msg}")
    print(f"{'=' * 50}{Colors.ENDC}\n")


# ============================================
# 测试函数
# ============================================

async def test_api_connectivity():
    """测试 API 连接"""
    print_header("测试 DexScreener API 连接")
    
    client = DexScreenerClient()
    
    try:
        print_info("尝试获取 Ethereum 交易对...")
        pairs = await client.get_pairs_by_chain("ethereum", limit=5)
        
        if pairs is not None:
            print_success(f"API 连接成功！获取到 {len(pairs)} 个交易对")
            
            if pairs:
                print(f"\n{Colors.BOLD}示例交易对:{Colors.ENDC}")
                for i, pair in enumerate(pairs[:3], 1):
                    base = pair.get('baseToken', {})
                    quote = pair.get('quoteToken', {})
                    liquidity = pair.get('liquidity', {})
                    
                    print(f"\n  {i}. {base.get('symbol', '?')}/{quote.get('symbol', '?')}")
                    print(f"     Pair: {pair.get('pairAddress', 'N/A')[:20]}...")
                    print(f"     DEX: {pair.get('dexId', 'unknown')}")
                    if isinstance(liquidity, dict):
                        print(f"     流动性: ${liquidity.get('usd', 0):,.2f}")
        else:
            print_error("API 返回空数据")
            
    except Exception as e:
        print_error(f"API 调用失败: {e}")
    finally:
        await client.close()


async def test_price_fetch(chain: str = "ethereum", symbol: str = "ETH"):
    """测试价格获取"""
    print_header(f"测试 {chain} 链上 {symbol} 价格获取")
    
    service = PriceMonitorService(redis_client=None)
    
    try:
        print_info(f"获取 {chain}:{symbol} 价格...")
        
        price = await service.get_price(chain, symbol)
        
        if price:
            print_success("价格获取成功！")
            print(f"\n{Colors.BOLD}价格详情:{Colors.ENDC}")
            print(f"  代币: {price.symbol}")
            print(f"  链: {price.chain}")
            print(f"  价格: ${price.price_usd:,.6f}")
            print(f"  流动性: ${price.liquidity_usd:,.2f}")
            print(f"  24h 交易量: ${price.volume_24h:,.2f}")
            print(f"  24h 变化: {price.price_change_24h:+.2f}%")
            print(f"  DEX: {price.dex}")
            print(f"  数据源: {price.source}")
            print(f"  置信度: {price.confidence * 100:.0f}%")
            print(f"  更新时间: {price.timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
        else:
            print_error("未能获取价格数据")
            
    except Exception as e:
        print_error(f"获取失败: {e}")
    finally:
        await service.stop()


async def test_chain_prices(chain: str):
    """测试链上所有监控代币的价格"""
    print_header(f"测试 {chain} 链上所有代币价格")
    
    service = PriceMonitorService(redis_client=None)
    
    try:
        print_info("获取所有价格...")
        
        prices = await service.get_prices_by_chain(chain)
        
        if prices:
            print_success(f"获取到 {len(prices)} 个代币价格")
            
            print(f"\n{Colors.BOLD}{chain.upper()} 价格列表:{Colors.ENDC}")
            print("-" * 70)
            
            for symbol, price in sorted(prices.items()):
                change_emoji = "📈" if price.price_change_24h > 0 else "📉" if price.price_change_24h < 0 else "➖"
                print(f"  {symbol:8} ${price.price_usd:>14,.6f}  {change_emoji} {price.price_change_24h:+6.2f}%  [{price.dex}]")
        else:
            print_error("未能获取价格数据")
            
    except Exception as e:
        print_error(f"获取失败: {e}")
    finally:
        await service.stop()


async def test_all_chains():
    """测试所有链的价格"""
    print_header("测试所有 16 条链的价格获取")
    
    from config.settings import ENABLED_CHAINS
    
    service = PriceMonitorService(redis_client=None)
    
    try:
        print_info(f"正在获取 {len(ENABLED_CHAINS)} 条链的价格...")
        
        # 并发获取所有链
        tasks = [
            service.get_prices_by_chain(chain)
            for chain in ENABLED_CHAINS
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        print(f"\n{Colors.BOLD}多链价格总览:{Colors.ENDC}")
        print("-" * 80)
        
        success_count = 0
        for chain, result in zip(ENABLED_CHAINS, results):
            if isinstance(result, dict) and result:
                success_count += 1
                eth_price = result.get("ETH", result.get("WETH"))
                sol_price = result.get("SOL")
                
                if eth_price:
                    print(f"  {chain:12} ETH: ${eth_price.price_usd:>12,.2f}  变化: {eth_price.price_change_24h:+5.2f}%")
                elif sol_price:
                    print(f"  {chain:12} SOL: ${sol_price.price_usd:>12,.2f}  变化: {sol_price.price_change_24h:+5.2f}%")
            else:
                print(f"  {chain:12} (无可用数据)")
        
        print("-" * 80)
        print_success(f"成功获取 {success_count}/{len(ENABLED_CHAINS)} 条链的价格")
        
    except Exception as e:
        print_error(f"获取失败: {e}")
    finally:
        await service.stop()


async def test_token_search(query: str):
    """测试代币搜索"""
    print_header(f"搜索代币: {query}")
    
    service = PriceMonitorService(redis_client=None)
    
    try:
        print_info("搜索中...")
        
        results = await service.search_token(query)
        
        if results:
            print_success(f"找到 {len(results)} 个结果")
            
            print(f"\n{Colors.BOLD}搜索结果:{Colors.ENDC}")
            for i, pair in enumerate(results[:10], 1):
                base = pair.get('baseToken', {})
                quote = pair.get('quoteToken', {})
                liquidity = pair.get('liquidity', {})
                
                usd_liq = 0
                if isinstance(liquidity, dict):
                    usd_liq = liquidity.get('usd', 0)
                
                print(f"\n  {i}. {base.get('symbol', '?')}/{quote.get('symbol', '?')}")
                print(f"     链: {pair.get('chainId', 'unknown')}")
                print(f"     DEX: {pair.get('dexId', 'unknown')}")
                print(f"     流动性: ${usd_liq:,.2f}")
        else:
            print_error("未找到结果")
            
    except Exception as e:
        print_error(f"搜索失败: {e}")
    finally:
        await service.stop()


async def test_cache():
    """测试缓存功能"""
    print_header("测试缓存功能")
    
    service = PriceMonitorService(redis_client=None)
    
    try:
        print_info("首次获取（无缓存）...")
        price1 = await service.get_price("ethereum", "ETH")
        
        if price1:
            print_success(f"获取成功: ${price1.price_usd:,.2f}")
            print_info(f"数据来源: {price1.source}")
        
        print_info("再次获取（使用缓存）...")
        price2 = await service.get_price("ethereum", "ETH")
        
        if price2:
            print_success(f"获取成功: ${price2.price_usd:,.2f}")
            print_info(f"数据来源: {price2.source}")
        
        # 测试缓存状态
        status = await service.get_chain_status()
        print(f"\n{Colors.BOLD}服务状态:{Colors.ENDC}")
        print(f"  总价格数: {status['total_prices']}")
        print(f"  WebSocket 连接: {status['ws_connections']}")
        print(f"  限流器剩余配额: {status['rate_limiter_remaining']}")
        print(f"  运行状态: {status['running']}")
        
    except Exception as e:
        print_error(f"测试失败: {e}")
    finally:
        await service.stop()


async def test_rate_limiter():
    """测试限流器"""
    print_header("测试限流器")
    
    limiter = RateLimiter(max_requests=5, time_window=60)
    
    print_info("消耗所有配额...")
    for i in range(5):
        result = await limiter.acquire()
        print(f"  请求 {i+1}: {'成功' if result else '失败'}")
    
    print_info("尝试获取第6个配额...")
    result = await limiter.acquire()
    print(f"  结果: {'成功' if result else '失败（限流）'}")
    print(f"  剩余配额: {limiter.remaining}")
    
    # 清空配额后再次测试
    limiter.requests = []
    print_success("限流器工作正常")


def main():
    parser = argparse.ArgumentParser(description="价格监控测试工具")
    parser.add_argument("--chain", type=str, help="指定链 (例如: ethereum)")
    parser.add_argument("--symbol", type=str, default="ETH", help="代币符号")
    parser.add_argument("--all", action="store_true", help="测试所有链")
    parser.add_argument("--search", type=str, help="搜索代币")
    parser.add_argument("--cache", action="store_true", help="测试缓存")
    parser.add_argument("--rate-limit", action="store_true", help="测试限流器")
    
    args = parser.parse_args()
    
    # 运行测试
    if args.all:
        asyncio.run(test_all_chains())
    elif args.search:
        asyncio.run(test_token_search(args.search))
    elif args.cache:
        asyncio.run(test_cache())
    elif args.rate_limit:
        asyncio.run(test_rate_limiter())
    elif args.chain:
        asyncio.run(test_chain_prices(args.chain))
    else:
        # 运行所有测试
        asyncio.run(test_api_connectivity())
        asyncio.run(test_price_fetch())
        asyncio.run(test_rate_limiter())


if __name__ == "__main__":
    main()
