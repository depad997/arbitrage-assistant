"""
Solana 交易构建模块

功能：
- Jupiter 聚合器集成（Quote API, Swap API）
- 原生交易构建（使用 solders）
- 跨链桥接交易（Wormhole, CCTP）
- DEX 交易指令构建

支持的去中心化交易所：
- Jupiter Aggregator
- Raydium
- Orca
- Meteora
- OpenBook
"""

import json
import logging
from typing import Dict, List, Optional, Tuple, Any, Union
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
import asyncio
import hashlib

import httpx

import sys
import os as _os
_backend_dir = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

# Solana SDK
try:
    from solders.keypair import Keypair as SolanaKeypair
    from solders.pubkey import Pubkey as SolanaPubkey
    from solders.transaction import Transaction as SolanaTransaction
    from solders.message import Message
    from solders.system_program import (
        CreateAccountParams,
        create_account,
        transfer,
        TransferParams
    )
    from solders.token.instructions import (
        InitializeAccountParams,
        InitializeAccount,
        TransferParams as TokenTransferParams,
        Transfer as TokenTransfer,
        CloseAccountParams,
        CloseAccount,
        get_associated_token_address,
        create_associated_token_account,
        CreateAssociatedTokenAccountParams,
        CreateIdempotent
    )
    from solders import system_program as sysprog
    from solders import token as tokenprog
    from solders import hash as hashprog
    SOLANA_SDK_AVAILABLE = True
except ImportError:
    SOLANA_SDK_AVAILABLE = False
    logging.warning("Solana SDK (solders) not installed")

from config.solana_dex import (
    JupiterEndpoints,
    SolanaTokens,
    SolanaPrograms,
    SolanaTxConfig,
    SolanaRPCConfig,
    SupportedDEX,
    get_token_decimals,
    lamports_to_sol,
    sol_to_lamports,
    get_token_mint
)

logger = logging.getLogger(__name__)


# ============================================
# 枚举和常量
# ============================================

class SwapMode(Enum):
    """Swap 模式"""
    EXACT_IN = "exactIn"
    EXACT_OUT = "exactOut"


class BridgeType(Enum):
    """桥接类型"""
    WORMHOLE = "wormhole"
    CCTP = "cctp"  # Circle Cross-Chain Transfer


# ============================================
# 数据类定义
# ============================================

@dataclass
class SwapQuote:
    """Jupiter Quote 结果"""
    input_mint: str
    output_mint: str
    input_amount: int
    output_amount: int
    price_impact_pct: float
    route_plan: List[Dict]
    other_amount_threshold: int  # 最小输出金额（exactIn）或 最大输入金额（exactOut）
    swap_mode: SwapMode
    slippage_bps: int
    
    # 额外信息
    platform_fee: Optional[Dict] = None
    price_api_price: Optional[float] = None
    
    # 解析路由信息
    @property
    def dexes_used(self) -> List[str]:
        """获取使用的 DEX 列表"""
        dexes = []
        for step in self.route_plan:
            if "swapInfo" in step:
                dexes.append(step["swapInfo"].get("label", "unknown"))
        return list(set(dexes))
    
    @property
    def swap_instructions(self) -> List[Dict]:
        """获取 Swap 指令列表"""
        instructions = []
        for step in self.route_plan:
            if "swapInfo" in step:
                instructions.append(step["swapInfo"])
        return instructions


@dataclass
class SwapTransaction:
    """Swap 交易构建结果"""
    swap_transaction: str  # 序列化的交易 hex
    last_valid_block_height: int
    prioritization_fee_lamports: int
    compute_unit_limit: Optional[int] = None
    compute_unit_price: Optional[int] = None
    
    @property
    def tx_bytes(self) -> bytes:
        """获取交易字节"""
        return bytes.fromhex(self.swap_transaction)


@dataclass
class SolanaInstruction:
    """Solana 指令"""
    program_id: str
    keys: List[Dict]  # [{"pubkey": str, "is_signer": bool, "is_writable": bool}]
    data: str  # hex encoded
    
    def to_dict(self) -> Dict:
        return {
            "programId": self.program_id,
            "keys": self.keys,
            "data": self.data
        }


@dataclass
class TransactionBuildResult:
    """交易构建结果"""
    transaction: SolanaTransaction
    recent_blockhash: str
    fee_payer: str
    signers: List[SolanaKeypair]
    estimated_fee_lamports: int
    
    # 序列化
    def serialize(self) -> str:
        """序列化交易为 hex"""
        return self.transaction.serialize().__str__()[2:]  # 去掉 0x
    
    def to_json(self) -> str:
        """转为 JSON"""
        return json.dumps({
            "recent_blockhash": str(self.recent_blockhash),
            "fee_payer": str(self.fee_payer),
            "estimated_fee_lamports": self.estimated_fee_lamports
        })


@dataclass
class TokenBalance:
    """Token 余额"""
    mint: str
    amount: int
    decimals: int
    
    @property
    def amount_normalized(self) -> float:
        """标准化金额"""
        return self.amount / (10 ** self.decimals)


@dataclass
class WalletState:
    """钱包状态"""
    address: str
    sol_balance: int  # lamports
    tokens: Dict[str, TokenBalance] = field(default_factory=dict)
    
    @property
    def sol_normalized(self) -> float:
        """SOL 余额（标准化）"""
        return lamports_to_sol(self.sol_balance)


# ============================================
# Jupiter API 客户端
# ============================================

class JupiterClient:
    """
    Jupiter Aggregator API 客户端
    
    使用 Jupiter API 进行：
    - 获取报价 (Quote)
    - 构建 Swap 交易
    - 获取价格
    """
    
    def __init__(
        self,
        base_url: str = JupiterEndpoints.BASE_URL,
        user_agent: str = JupiterEndpoints.USER_AGENT,
        timeout: int = 30
    ):
        self.base_url = base_url
        self.timeout = timeout
        self._client = httpx.AsyncClient(
            timeout=timeout,
            headers={"User-Agent": user_agent}
        )
    
    async def close(self):
        """关闭客户端"""
        await self._client.aclose()
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
    
    async def get_quote(
        self,
        input_mint: str,
        output_mint: str,
        amount: int,
        slippage_bps: int = SolanaTxConfig.DEFAULT_SLIPPAGE_BPS,
        swap_mode: SwapMode = SwapMode.EXACT_IN,
        only_direct_routes: bool = False,
        as_legacy_transaction: bool = False,
        as_token2022_transaction: bool = False,
        max_accounts: Optional[int] = None,
        use_shared_accounts: bool = True,
    ) -> SwapQuote:
        """
        获取 Jupiter Quote
        
        Args:
            input_mint: 输入代币 Mint 地址
            output_mint: 输出代币 Mint 地址
            amount: 金额（最小单位）
            slippage_bps: 滑点容忍度 (basis points)
            swap_mode: Swap 模式
            only_direct_routes: 只使用直接路由
            as_legacy_transaction: 使用传统交易格式
            as_token2022_transaction: 使用 Token-2022
            max_accounts: 最大账户数
            use_shared_accounts: 使用共享账户
        
        Returns:
            SwapQuote 对象
        """
        params = {
            "inputMint": input_mint,
            "outputMint": output_mint,
            "amount": amount,
            "slippageBps": slippage_bps,
            "swapMode": swap_mode.value,
            "onlyDirectRoutes": str(only_direct_routes).lower(),
            "asLegacyTransaction": str(as_legacy_transaction).lower(),
            "asToken2022Transaction": str(as_token2022_transaction).lower(),
            "maxAccounts": max_accounts,
            "useSharedAccounts": str(use_shared_accounts).lower(),
        }
        
        # 移除 None 值
        params = {k: v for k, v in params.items() if v is not None}
        
        url = f"{self.base_url}/quote"
        response = await self._client.get(url, params=params)
        response.raise_for_status()
        
        data = response.json()
        
        return SwapQuote(
            input_mint=data["inputMint"],
            output_mint=data["outputMint"],
            input_amount=int(data["inAmount"]),
            output_amount=int(data["outAmount"]),
            price_impact_pct=float(data.get("priceImpactPct", 0)),
            route_plan=data.get("routePlan", []),
            other_amount_threshold=int(data["otherAmountThreshold"]),
            swap_mode=SwapMode(swap_mode.value),
            slippage_bps=slippage_bps,
            platform_fee=data.get("platformFee"),
            price_api_price=data.get("priceImpactPct")
        )
    
    async def get_swap_transaction(
        self,
        quote: SwapQuote,
        user_public_key: str,
        wrap_and_unwrap_sol: bool = True,
        compute_unit_price_micro_lamports: Optional[int] = None,
        dynamic_compute_unit_limit: bool = True,
        prioritization_fee_lamports: Optional[int] = None,
        as_legacy_transaction: bool = False,
        as_token2022_transaction: bool = False,
        use_token_ledger: bool = False,
        destination_token_account: Optional[str] = None,
        source_token_account: Optional[str] = None,
        can_bypass_token_account_creation_check: bool = False,
    ) -> SwapTransaction:
        """
        获取 Swap 交易
        
        Args:
            quote: SwapQuote 对象
            user_public_key: 用户公钥
            wrap_and_unwrap_sol: 是否包装/解包 SOL
            compute_unit_price_micro_lamports: 计算单元价格 (micro lamports)
            dynamic_compute_unit_limit: 动态计算单元限制
            prioritization_fee_lamports: 优先费用
            as_legacy_transaction: 使用传统交易格式
            as_token2022_transaction: 使用 Token-2022
            use_token_ledger: 使用 Token 账本
            destination_token_account: 目标代币账户
            source_token_account: 源代币账户
            can_bypass_token_account_creation_check: 绕过代币账户创建检查
        
        Returns:
            SwapTransaction 对象
        """
        params = {
            "quoteResponse": quote.__dict__,
            "userPublicKey": user_public_key,
            "wrapAndUnwrapSol": str(wrap_and_unwrap_sol).lower(),
            "computeUnitPriceMicroLamports": compute_unit_price_micro_lamports,
            "dynamicComputeUnitLimit": str(dynamic_compute_unit_limit).lower(),
            "prioritizationFeeLamports": prioritization_fee_lamports,
            "asLegacyTransaction": str(as_legacy_transaction).lower(),
            "asToken2022Transaction": str(as_token2022_transaction).lower(),
            "useTokenLedger": str(use_token_ledger).lower(),
            "destinationTokenAccount": destination_token_account,
            "sourceTokenAccount": source_token_account,
            "canBypassTokenAccountCreationCheck": str(can_bypass_token_account_creation_check).lower(),
        }
        
        # 移除 None 值
        params = {k: v for k, v in params.items() if v is not None}
        
        url = f"{self.base_url}/swap"
        response = await self._client.post(url, json=params)
        response.raise_for_status()
        
        data = response.json()
        
        return SwapTransaction(
            swap_transaction=data["swapTransaction"],
            last_valid_block_height=data["lastValidBlockHeight"],
            prioritization_fee_lamports=data.get("prioritizationFeeLamports", 0),
            compute_unit_limit=data.get("computeUnitLimit"),
            compute_unit_price=compute_unit_price_micro_lamports
        )
    
    async def get_price(
        self,
        mints: List[str],
        vs_token: str = "USDC"
    ) -> Dict[str, float]:
        """
        获取代币价格
        
        Args:
            mints: 代币 Mint 地址列表
            vs_token: 计价代币 (默认 USDC)
        
        Returns:
            {mint: price} 字典
        """
        params = {
            "ids": ",".join(mints),
            "vsToken": vs_token
        }
        
        url = JupiterEndpoints.PRICE_URL
        response = await self._client.get(url, params=params)
        response.raise_for_status()
        
        data = response.json()
        return {mint: float(info["price"]) for mint, info in data.get("data", {}).items()}


# ============================================
# Solana 交易构建器
# ============================================

class SolanaTransactionBuilder:
    """
    Solana 原生交易构建器
    
    用于：
    - 创建基础交易
    - 添加指令
    - 设置 Fee Payer
    - 计算手续费
    """
    
    def __init__(
        self,
        rpc_url: str = SolanaRPCConfig.DEFAULT_MAINNET,
        commitment: str = "confirmed"
    ):
        self.rpc_url = rpc_url
        self.commitment = commitment
        self._client = httpx.Client(timeout=30)
    
    def close(self):
        """关闭客户端"""
        self._client.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
    
    def get_recent_blockhash(self) -> Tuple[str, int]:
        """
        获取最近的 blockhash
        
        Returns:
            (blockhash, last_valid_block_height)
        """
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getLatestBlockhash",
            "params": [{"commitment": self.commitment}]
        }
        
        response = self._client.post(
            self.rpc_url,
            json=payload,
            headers={"Content-Type": "application/json"}
        )
        data = response.json()
        
        blockhash = data["result"]["value"]["blockhash"]
        last_valid_height = data["result"]["value"]["lastValidBlockHeight"]
        
        return blockhash, last_valid_height
    
    def get_fee_calculator(self) -> int:
        """
        获取当前手续费率
        
        Returns:
            fee in lamports
        """
        _, last_valid_height = self.get_recent_blockhash()
        
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getFeeCalculatorForBlockhash",
            "params": [
                self.get_recent_blockhash()[0],
                {"commitment": self.commitment}
            ]
        }
        
        response = self._client.post(
            self.rpc_url,
            json=payload,
            headers={"Content-Type": "application/json"}
        )
        data = response.json()
        
        if "result" in data and "value" in data["result"]:
            return data["result"]["value"]["lamportsPerSignature"]
        return SolanaTxConfig.DEFAULT_FEE
    
    def build_transaction(
        self,
        instructions: List[Any],
        fee_payer: str,
        signers: List[SolanaKeypair],
        recent_blockhash: Optional[str] = None
    ) -> TransactionBuildResult:
        """
        构建交易
        
        Args:
            instructions: 指令列表
            fee_payer: 手续费付款人地址
            signers: 签名者列表
            recent_blockhash: 最近的 blockhash
        
        Returns:
            TransactionBuildResult 对象
        """
        # 获取 blockhash
        if recent_blockhash is None:
            recent_blockhash, _ = self.get_recent_blockhash()
        
        # 创建消息
        fee_payer_pubkey = SolanaPubkey.from_string(fee_payer)
        instructions_data = []
        
        for instr in instructions:
            if hasattr(instr, 'to_dict'):
                # 如果是指令对象
                instructions_data.append(instr)
            else:
                instructions_data.append(instr)
        
        # 创建交易
        msg = Message.new_with_compiled_instructions(
            payer=fee_payer_pubkey,
            keys=[SolanaPubkey.from_string(k["pubkey"]) for k in instructions_data[0].keys] if instructions_data else [],
            instructions=instructions_data if instructions_data else [],
            recent_blockhash=hashprog.Hash.from_string(recent_blockhash)
        )
        
        # 创建交易对象
        tx = SolanaTransaction(fee_payer=fee_payer_pubkey, instructions=instructions_data, recent_blockhash=hashprog.Hash.from_string(recent_blockhash))
        
        # 签名
        if signers:
            tx.sign(signers, recent_blockhash)
        
        # 估算手续费
        estimated_fee = SolanaTxConfig.DEFAULT_FEE
        
        return TransactionBuildResult(
            transaction=tx,
            recent_blockhash=recent_blockhash,
            fee_payer=fee_payer,
            signers=signers,
            estimated_fee_lamports=estimated_fee
        )
    
    def build_transfer_instruction(
        self,
        from_pubkey: str,
        to_pubkey: str,
        amount: int,  # lamports for SOL
        owner: SolanaKeypair
    ) -> Any:
        """
        构建 SOL 转账指令
        
        Args:
            from_pubkey: 发送方地址
            to_pubkey: 接收方地址
            amount: 金额 (lamports)
            owner: 签名者
        
        Returns:
            指令对象
        """
        return transfer(
            TransferParams(
                from_pubkey=SolanaPubkey.from_string(from_pubkey),
                to_pubkey=SolanaPubkey.from_string(to_pubkey),
                lamports=amount
            )
        )
    
    def build_token_transfer_instruction(
        self,
        source: str,
        mint: str,
        destination: str,
        owner: SolanaKeypair,
        amount: int,
        decimals: int
    ) -> Any:
        """
        构建 SPL Token 转账指令
        
        Args:
            source: 源代币账户
            mint: 代币 Mint
            destination: 目标代币账户
            owner: 所有者密钥对
            amount: 金额（最小单位）
            decimals: 代币精度
        
        Returns:
            指令对象
        """
        return TokenTransfer(
            TokenTransferParams(
                program_id=SolanaPubkey.from_string(SolanaPrograms.TOKEN_PROGRAM),
                source=SolanaPubkey.from_string(source),
                dest=SolanaPubkey.from_string(destination),
                owner=owner.pubkey(),
                amount=amount,
                decimals=decimals
            )
        )
    
    def get_token_accounts(self, owner: str) -> List[Dict]:
        """
        获取钱包的所有代币账户
        
        Args:
            owner: 钱包地址
        
        Returns:
            代币账户列表
        """
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getTokenAccountsByOwner",
            "params": [
                owner,
                {"programId": SolanaPrograms.TOKEN_PROGRAM},
                {"encoding": "jsonParsed"}
            ]
        }
        
        response = self._client.post(
            self.rpc_url,
            json=payload,
            headers={"Content-Type": "application/json"}
        )
        data = response.json()
        
        accounts = []
        if "result" in data and "value" in data["result"]:
            for account in data["result"]["value"]:
                try:
                    parsed = account["account"]["data"]["parsed"]["info"]
                    accounts.append({
                        "mint": parsed["mint"],
                        "address": parsed["address"],
                        "amount": int(parsed["tokenAmount"]["amount"]),
                        "decimals": parsed["tokenAmount"]["decimals"],
                        "ui_amount": parsed["tokenAmount"]["uiAmount"]
                    })
                except (KeyError, ValueError):
                    continue
        
        return accounts


# ============================================
# Solana Swap 交易构建器
# ============================================

class SolanaSwapBuilder:
    """
    Solana Swap 交易构建器
    
    整合 Jupiter API 和原生交易构建
    """
    
    def __init__(
        self,
        rpc_url: str = SolanaRPCConfig.DEFAULT_MAINNET,
        commitment: str = "confirmed"
    ):
        self.rpc_url = rpc_url
        self.commitment = commitment
        self.tx_builder = SolanaTransactionBuilder(rpc_url, commitment)
        self._client = httpx.Client(timeout=30)
    
    def close(self):
        """关闭客户端"""
        self.tx_builder.close()
        self._client.close()
    
    async def get_quote(
        self,
        input_token: str,
        output_token: str,
        amount: int,
        slippage_bps: int = SolanaTxConfig.DEFAULT_SLIPPAGE_BPS,
        swap_mode: SwapMode = SwapMode.EXACT_IN
    ) -> SwapQuote:
        """
        获取 Swap 报价
        
        Args:
            input_token: 输入代币符号或 Mint 地址
            output_token: 输出代币符号或 Mint 地址
            amount: 金额（最小单位）
            slippage_bps: 滑点容忍度
            swap_mode: Swap 模式
        
        Returns:
            SwapQuote 对象
        """
        async with JupiterClient() as jupiter:
            # 解析代币
            input_mint = get_token_mint(input_token) if len(input_token) < 44 else input_token
            output_mint = get_token_mint(output_token) if len(output_token) < 44 else output_token
            
            if not input_mint:
                raise ValueError(f"Unknown input token: {input_token}")
            if not output_mint:
                raise ValueError(f"Unknown output token: {output_token}")
            
            return await jupiter.get_quote(
                input_mint=input_mint,
                output_mint=output_mint,
                amount=amount,
                slippage_bps=slippage_bps,
                swap_mode=swap_mode
            )
    
    async def build_swap_transaction(
        self,
        quote: SwapQuote,
        user_public_key: str,
        signer: SolanaKeypair,
        prioritization_fee_lamports: Optional[int] = None
    ) -> Tuple[bytes, str]:
        """
        构建 Swap 交易
        
        Args:
            quote: SwapQuote 对象
            user_public_key: 用户公钥
            signer: 签名者
            prioritization_fee_lamports: 优先费用
        
        Returns:
            (交易字节, transaction_id)
        """
        async with JupiterClient() as jupiter:
            swap_tx = await jupiter.get_swap_transaction(
                quote=quote,
                user_public_key=user_public_key,
                prioritization_fee_lamports=prioritization_fee_lamports,
                wrap_and_unwrap_sol=True
            )
            
            return bytes.fromhex(swap_tx.swap_transaction), swap_tx.last_valid_block_height
    
    async def execute_swap(
        self,
        input_token: str,
        output_token: str,
        amount: int,
        signer: SolanaKeypair,
        slippage_bps: int = SolanaTxConfig.DEFAULT_SLIPPAGE_BPS,
        prioritization_fee_lamports: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        执行完整的 Swap 流程
        
        Args:
            input_token: 输入代币
            output_token: 输出代币
            amount: 金额（最小单位）
            signer: 签名者
            slippage_bps: 滑点容忍度
            prioritization_fee_lamports: 优先费用
        
        Returns:
            执行结果字典
        """
        user_pubkey = str(signer.pubkey())
        
        # 1. 获取报价
        quote = await self.get_quote(
            input_token=input_token,
            output_token=output_token,
            amount=amount,
            slippage_bps=slippage_bps
        )
        
        # 2. 构建交易
        tx_bytes, last_valid_block = await self.build_swap_transaction(
            quote=quote,
            user_public_key=user_pubkey,
            signer=signer,
            prioritization_fee_lamports=prioritization_fee_lamports
        )
        
        return {
            "quote": {
                "input_mint": quote.input_mint,
                "output_mint": quote.output_mint,
                "input_amount": quote.input_amount,
                "output_amount": quote.output_amount,
                "price_impact_pct": quote.price_impact_pct,
                "dexes_used": quote.dexes_used,
                "slippage_bps": quote.slippage_bps
            },
            "transaction": tx_bytes.hex(),
            "last_valid_block_height": last_valid_block,
            "user_public_key": user_pubkey
        }


# ============================================
# 跨链桥交易构建器
# ============================================

class SolanaBridgeBuilder:
    """
    Solana 跨链桥交易构建器
    
    支持：
    - Wormhole 桥接
    - CCTP (Circle Cross-Chain Transfer)
    """
    
    def __init__(
        self,
        rpc_url: str = SolanaRPCConfig.DEFAULT_MAINNET
    ):
        self.rpc_url = rpc_url
        self._client = httpx.Client(timeout=30)
    
    def close(self):
        """关闭客户端"""
        self._client.close()
    
    def build_wormhole_transfer_instruction(
        self,
        source: str,
        destination_chain: int,  # Wormhole chain ID
        destination_address: bytes,  # 32 bytes
        fee: int,  # lamports
        mint: str,
        amount: int,
        payer: SolanaKeypair
    ) -> List[Any]:
        """
        构建 Wormhole 转账指令
        
        Args:
            source: 源代币账户
            destination_chain: 目标链 Wormhole ID
            destination_address: 目标地址 (32 bytes)
            fee: 手续费 (lamports)
            mint: 代币 Mint
            amount: 金额
            payer: 付款人
        
        Returns:
            指令列表
        """
        # Wormhole Transfer Account 指令
        # 注意：实际实现需要完整的 Wormhole SDK
        raise NotImplementedError("Wormhole integration requires wormhole-sdk")
    
    def build_cctp_transfer_instruction(
        self,
        source_token_account: str,
        destination_domain: int,  # Circle domain
        recipient: bytes,  # 32 bytes
        amount: int,
        payer: SolanaKeypair
    ) -> List[Any]:
        """
        构建 CCTP 转账指令
        
        Args:
            source_token_account: 源代币账户
            destination_domain: 目标域 (Circle domain)
            recipient: 接收者地址
            amount: 金额
            payer: 付款人
        
        Returns:
            指令列表
        """
        # CCTP Transfer 指令
        # Circle 的跨链传输协议
        # 需要使用 @coral-xyz/anchor 或 wormhole SDK
        
        instructions = []
        
        # 1. approve (如果是 Token Program)
        # 2. deposit_for_burn
        # 3. 其他 CCTP 特定指令
        
        return instructions


# ============================================
# 工具函数
# ============================================

def decode_transaction(base64_tx: str) -> Dict:
    """
    解码交易
    
    Args:
        base64_tx: Base64 编码的交易
    
    Returns:
        交易解析结果
    """
    import base64
    
    try:
        tx_bytes = base64.b64decode(base64_tx)
        # 使用 solders 解析
        tx = SolanaTransaction.from_bytes(tx_bytes)
        return {
            "signatures": [str(sig) for sig in tx.signatures],
            "fee_payer": str(tx.fee_payer()),
            "instructions": len(tx.message.instructions),
            "recent_blockhash": str(tx.message.recent_blockhash)
        }
    except Exception as e:
        logger.error(f"Failed to decode transaction: {e}")
        return {}


async def simulate_transaction(
    rpc_url: str,
    tx_bytes: bytes
) -> Dict[str, Any]:
    """
    模拟交易
    
    Args:
        rpc_url: RPC URL
        tx_bytes: 交易字节
    
    Returns:
        模拟结果
    """
    import base64
    
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "simulateTransaction",
        "params": [
            base64.b64encode(tx_bytes).decode(),
            {
                "encoding": "base64",
                "sigVerify": False,
                "replaceRecentBlockhash": True
            }
        ]
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.post(
            rpc_url,
            json=payload,
            headers={"Content-Type": "application/json"}
        )
        return response.json()


def estimate_transaction_fee(
    instruction_count: int,
    account_count: int,
    fee_per_signature: int = SolanaTxConfig.DEFAULT_FEE
) -> int:
    """
    估算交易手续费
    
    Args:
        instruction_count: 指令数量
        account_count: 账户数量
        fee_per_signature: 每个签名的费用
    
    Returns:
        估算的手续费 (lamports)
    """
    # Solana 手续费 = 签名数 * fee_per_signature
    # 每个指令可能涉及多个签名
    return instruction_count * fee_per_signature


# ============================================
# 单例访问器
# ============================================

_solana_swap_builder: Optional[SolanaSwapBuilder] = None


def get_solana_swap_builder(
    rpc_url: Optional[str] = None
) -> SolanaSwapBuilder:
    """
    获取 SolanaSwapBuilder 单例
    
    Args:
        rpc_url: RPC URL
    
    Returns:
        SolanaSwapBuilder 实例
    """
    global _solana_swap_builder
    
    if _solana_swap_builder is None:
        _solana_swap_builder = SolanaSwapBuilder(
            rpc_url=rpc_url or SolanaRPCConfig.DEFAULT_MAINNET
        )
    
    return _solana_swap_builder


def close_solana_swap_builder():
    """关闭 SolanaSwapBuilder"""
    global _solana_swap_builder
    
    if _solana_swap_builder is not None:
        _solana_swap_builder.close()
        _solana_swap_builder = None
