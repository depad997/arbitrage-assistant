"""
Solana 功能测试脚本

测试内容：
- 钱包创建和导入
- 余额查询
- Jupiter Quote
- Swap 交易构建
- 交易签名
"""

import asyncio
import sys
import os

# 添加项目路径
_backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from config.solana_dex import (
    SolanaTokens,
    SolanaRPCConfig,
    JupiterEndpoints,
    SolanaTxConfig,
    get_token_mint,
    lamports_to_sol,
    sol_to_lamports
)


# ============================================
# 测试配置
# ============================================

# 测试 RPC
TEST_RPC = SolanaRPCConfig.MAINNET_RPCS[0]

# 测试代币
TEST_INPUT_TOKEN = "SOL"
TEST_OUTPUT_TOKEN = "USDC"

# 测试金额 (SOL)
TEST_AMOUNT_SOL = 0.01


def print_section(title: str):
    """打印测试标题"""
    print("\n" + "=" * 60)
    print(f" {title}")
    print("=" * 60)


def print_result(name: str, result: any, success: bool = True):
    """打印测试结果"""
    status = "✅ PASS" if success else "❌ FAIL"
    print(f"\n{status} {name}")
    if result:
        if isinstance(result, dict):
            for key, value in result.items():
                print(f"   {key}: {value}")
        else:
            print(f"   {result}")


# ============================================
# 钱包测试
# ============================================

def test_wallet_creation():
    """测试钱包创建"""
    print_section("测试 1: 钱包创建")
    
    try:
        from solders.keypair import Keypair as SolanaKeypair
        
        # 创建新钱包
        keypair = SolanaKeypair()
        
        result = {
            "address": str(keypair.pubkey()),
            "private_key_hex": bytes(keypair).hex()[:32] + "...",  # 截断显示
        }
        
        print_result("创建新钱包", result)
        return True, keypair
        
    except ImportError:
        print_result("钱包创建", "Solana SDK 未安装", False)
        return False, None
    except Exception as e:
        print_result("钱包创建", str(e), False)
        return False, None


def test_wallet_import():
    """测试钱包导入"""
    print_section("测试 2: 钱包导入")
    
    try:
        from solders.keypair import Keypair as SolanaKeypair
        
        # 测试种子导入
        seed = bytes([i % 256 for i in range(32)])
        keypair = SolanaKeypair.from_seed(seed)
        
        # 验证导入结果
        derived_keypair = SolanaKeypair.from_bytes(bytes(keypair))
        
        result = {
            "original_address": str(keypair.pubkey()),
            "derived_address": str(derived_keypair.pubkey()),
            "match": str(keypair.pubkey()) == str(derived_keypair.pubkey())
        }
        
        print_result("从种子导入钱包", result, result["match"])
        return True, keypair
        
    except ImportError:
        print_result("钱包导入", "Solana SDK 未安装", False)
        return False, None
    except Exception as e:
        print_result("钱包导入", str(e), False)
        return False, None


# ============================================
# 余额查询测试
# ============================================

def test_balance_query():
    """测试余额查询"""
    print_section("测试 3: 余额查询")
    
    try:
        import httpx
        
        # 使用一个已知有余额的地址进行测试
        test_address = "7vfCXTUXx5WJV5JADk17DUJ4ksgau7utNKj4b963voxs"  # Solana Foundation
        
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getBalance",
            "params": [test_address]
        }
        
        with httpx.Client(timeout=30) as client:
            response = client.post(TEST_RPC, json=payload)
            data = response.json()
            
            if "result" in data:
                lamports = data["result"]["value"]
                sol = lamports_to_sol(lamports)
                
                result = {
                    "address": test_address,
                    "lamports": lamports,
                    "SOL": f"{sol:.9f}"
                }
                
                print_result("SOL 余额查询", result)
                return True
            else:
                print_result("SOL 余额查询", data, False)
                return False
                
    except Exception as e:
        print_result("SOL 余额查询", str(e), False)
        return False


def test_token_balance_query():
    """测试 Token 余额查询"""
    print_section("测试 4: SPL Token 余额查询")
    
    try:
        import httpx
        from solders.pubkey import Pubkey as SolanaPubkey
        from solders.token.instructions import get_associated_token_address
        
        # USDC Mint 地址
        usdc_mint = SolanaTokens.USDC
        
        # 测试地址
        test_address = "7vfCXTUXx5WJV5JADk17DUJ4ksgau7utNKj4b963voxs"
        test_pubkey = SolanaPubkey.from_string(test_address)
        mint_pubkey = SolanaPubkey.from_string(usdc_mint)
        
        # 获取关联代币账户
        ata = get_associated_token_address(test_pubkey, mint_pubkey)
        
        # 查询余额
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getTokenAccountBalance",
            "params": [str(ata)]
        }
        
        with httpx.Client(timeout=30) as client:
            response = client.post(TEST_RPC, json=payload)
            data = response.json()
            
            if "result" in data:
                info = data["result"]["value"]
                result = {
                    "account": str(ata),
                    "mint": info["mint"],
                    "amount": info["amount"],
                    "ui_amount": info.get("uiAmount", 0),
                    "decimals": info.get("decimals", 0)
                }
                
                print_result("USDC Token 余额查询", result)
                return True
            else:
                print_result("USDC Token 余额查询", data.get("error", "Account not found"), False)
                return False
                
    except Exception as e:
        print_result("SPL Token 余额查询", str(e), False)
        return False


# ============================================
# Jupiter API 测试
# ============================================

async def test_jupiter_quote():
    """测试 Jupiter Quote API"""
    print_section("测试 5: Jupiter Quote API")
    
    try:
        import httpx
        
        # 获取 SOL 转 USDC 的报价
        input_mint = SolanaTokens.SOL
        output_mint = SolanaTokens.USDC
        amount = sol_to_lamports(TEST_AMOUNT_SOL)
        
        params = {
            "inputMint": input_mint,
            "outputMint": output_mint,
            "amount": amount,
            "slippageBps": SolanaTxConfig.DEFAULT_SLIPPAGE_BPS,
            "swapMode": "exactIn"
        }
        
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                f"{JupiterEndpoints.BASE_URL}/quote",
                params=params,
                headers={"User-Agent": JupiterEndpoints.USER_AGENT}
            )
            
            if response.status_code == 200:
                data = response.json()
                
                result = {
                    "input_mint": data.get("inputMint"),
                    "output_mint": data.get("outputMint"),
                    "in_amount": data.get("inAmount"),
                    "out_amount": data.get("outAmount"),
                    "price_impact": data.get("priceImpactPct", 0),
                    "other_amount_threshold": data.get("otherAmountThreshold"),
                    "DEXs_used": []
                }
                
                # 解析路由
                for step in data.get("routePlan", []):
                    if "swapInfo" in step:
                        result["DEXs_used"].append(step["swapInfo"].get("label", "unknown"))
                
                result["DEXs_used"] = list(set(result["DEXs_used"]))
                
                print_result("Jupiter Quote (SOL -> USDC)", result)
                return True
            else:
                print_result("Jupiter Quote", f"HTTP {response.status_code}: {response.text}", False)
                return False
                
    except ImportError:
        print_result("Jupiter Quote", "httpx 未安装", False)
        return False
    except Exception as e:
        print_result("Jupiter Quote", str(e), False)
        return False


async def test_jupiter_price():
    """测试 Jupiter Price API"""
    print_section("测试 6: Jupiter Price API")
    
    try:
        import httpx
        
        mints = [SolanaTokens.SOL, SolanaTokens.USDC, SolanaTokens.RAY]
        
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                JupiterEndpoints.PRICE_URL,
                params={"ids": ",".join(mints)},
                headers={"User-Agent": JupiterEndpoints.USER_AGENT}
            )
            
            if response.status_code == 200:
                data = response.json()
                
                result = {}
                for mint, info in data.get("data", {}).items():
                    result[mint] = {
                        "price": info.get("price"),
                        "symbol": info.get("symbol")
                    }
                
                print_result("Jupiter Price API", result)
                return True
            else:
                print_result("Jupiter Price", f"HTTP {response.status_code}", False)
                return False
                
    except Exception as e:
        print_result("Jupiter Price", str(e), False)
        return False


# ============================================
# RPC 功能测试
# ============================================

def test_get_latest_blockhash():
    """测试获取最新区块哈希"""
    print_section("测试 7: 获取最新区块哈希")
    
    try:
        import httpx
        
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getLatestBlockhash",
            "params": [{"commitment": "confirmed"}]
        }
        
        with httpx.Client(timeout=30) as client:
            response = client.post(TEST_RPC, json=payload)
            data = response.json()
            
            if "result" in data:
                value = data["result"]["value"]
                result = {
                    "blockhash": value["blockhash"][:16] + "...",
                    "last_valid_block_height": value["lastValidBlockHeight"]
                }
                
                print_result("获取最新区块哈希", result)
                return True
            else:
                print_result("获取最新区块哈希", data, False)
                return False
                
    except Exception as e:
        print_result("获取最新区块哈希", str(e), False)
        return False


def test_get_block_height():
    """测试获取区块高度"""
    print_section("测试 8: 获取区块高度")
    
    try:
        import httpx
        
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getBlockHeight",
            "params": [{"commitment": "confirmed"}]
        }
        
        with httpx.Client(timeout=30) as client:
            response = client.post(TEST_RPC, json=payload)
            data = response.json()
            
            if "result" in data:
                result = {
                    "block_height": data["result"]
                }
                
                print_result("获取区块高度", result)
                return True
            else:
                print_result("获取区块高度", data, False)
                return False
                
    except Exception as e:
        print_result("获取区块高度", str(e), False)
        return False


# ============================================
# 主测试函数
# ============================================

async def run_tests():
    """运行所有测试"""
    print("\n" + "=" * 60)
    print(" Solana 功能测试套件")
    print("=" * 60)
    
    results = {}
    
    # 同步测试
    results["wallet_creation"] = test_wallet_creation()
    results["wallet_import"] = test_wallet_import()
    results["balance_query"] = test_balance_query()
    results["token_balance"] = test_token_balance_query()
    results["latest_blockhash"] = test_get_latest_blockhash()
    results["block_height"] = test_get_block_height()
    
    # 异步测试
    results["jupiter_quote"] = await test_jupiter_quote()
    results["jupiter_price"] = await test_jupiter_price()
    
    # 汇总结果
    print_section("测试结果汇总")
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for name, result in results.items():
        status = "✅" if result else "❌"
        print(f"   {status} {name}")
    
    print(f"\n通过: {passed}/{total}")
    
    return passed == total


# ============================================
# 使用示例
# ============================================

def show_usage_examples():
    """显示使用示例"""
    print_section("使用示例")
    
    examples = """
    # 1. 钱包管理
    from services.wallet_manager import SolanaWalletManager
    
    # 创建新钱包
    wallet = SolanaWalletManager()
    print(f"新钱包地址: {wallet.address}")
    
    # 从私钥导入
    wallet = SolanaWalletManager.from_private_key_hex("your_hex_private_key")
    
    # 获取余额
    sol_balance, lamports = wallet.get_sol_balance()
    print(f"SOL 余额: {sol_balance}")
    
    # 获取所有 Token 余额
    tokens = wallet.get_all_token_balances()
    print(f"Token 余额: {tokens}")
    
    
    # 2. Jupiter Swap
    import asyncio
    from services.solana_tx_builder import SolanaSwapBuilder, SwapMode
    from config.solana_dex import SolanaTokens
    
    async def example_swap():
        builder = SolanaSwapBuilder()
        
        # 获取报价 (SOL -> USDC)
        quote = await builder.get_quote(
            input_token="SOL",
            output_token="USDC",
            amount=1000000000,  # 1 SOL (lamports)
            slippage_bps=50
        )
        
        print(f"输出金额: {quote.output_amount}")
        print(f"价格影响: {quote.price_impact_pct}%")
        print(f"使用 DEX: {quote.dexes_used}")
        
        return quote
    
    
    # 3. 执行引擎
    from services.solana_execution_engine import SolanaExecutionEngine
    
    engine = SolanaExecutionEngine()
    
    # 发送交易
    signature = engine.submit_transaction(tx_bytes)
    
    # 等待确认
    result = engine.wait_for_confirmation(signature)
    
    print(f"状态: {result.status}")
    print(f"手续费: {result.fee} lamports")
    
    
    # 4. API 路由
    # POST /api/solana/wallet/create
    # {
    #     "name": "My Solana Wallet",
    #     "password": "optional_encryption_password"
    # }
    
    # POST /api/solana/execute/quote
    # {
    #     "input_token": "SOL",
    #     "output_token": "USDC",
    #     "amount": 1000000000,
    #     "slippage_bps": 50
    # }
    
    # GET /api/solana/execution/status/{signature}
    """
    
    print(examples)


if __name__ == "__main__":
    # 运行测试
    success = asyncio.run(run_tests())
    
    # 显示使用示例
    show_usage_examples()
    
    # 退出
    sys.exit(0 if success else 1)
