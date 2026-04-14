"""
Aptos 钱包管理模块

功能：
- 从私钥创建 Aptos 地址 (Ed25519)
- 生成新账户
- 查询 APT 和 Token 余额
- 签名交易 (Ed25519)
- BCS 编码支持
- 导入/导出加密密钥

Aptos 技术特点：
- 使用 Ed25519 签名算法
- 地址格式: 0x + 32字节十六进制 (共66个字符，与 Sui 相同)
- Account Model: 使用 Account Address 而非 Object
- 链 ID: 区分主网、测试网、开发网
"""

import asyncio
import base64
import binascii
import hashlib
import json
import logging
import secrets
import struct
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any, Union
from datetime import datetime
from pathlib import Path
import httpx
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad

import sys
import os as _os
_backend_dir = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from config.aptos_dex import (
    AptosAPIConfig,
    AptosTxConfig,
    AptosCoins,
    format_apt_amount,
    parse_apt_amount,
)

logger = logging.getLogger(__name__)


# ============================================
# 错误定义
# ============================================

class AptosWalletError(Exception):
    """Aptos 钱包错误基类"""
    pass


class InvalidPrivateKeyError(AptosWalletError):
    """无效私钥"""
    pass


class InvalidAddressError(AptosWalletError):
    """无效地址"""
    pass


class BalanceQueryError(AptosWalletError):
    """余额查询错误"""
    pass


class SigningError(AptosWalletError):
    """签名错误"""
    pass


# ============================================
# 数据类定义
# ============================================

@dataclass
class AptosAddress:
    """Aptos 地址信息"""
    address: str                         # Aptos 地址 (0x...)
    public_key: Optional[bytes] = None   # 公钥字节
    public_key_hex: Optional[str] = None # 公钥十六进制
    
    def __post_init__(self):
        if not self.address.startswith("0x"):
            self.address = "0x" + self.address
    
    @property
    def is_valid(self) -> bool:
        """检查地址是否有效"""
        addr = self.address[2:] if self.address.startswith("0x") else self.address
        return len(addr) == 64 and all(c in '0123456789abcdef' for c in addr.lower())
    
    @property
    def short_address(self) -> str:
        """返回短地址 (前8位...后8位)"""
        addr = self.address[2:] if self.address.startswith("0x") else self.address
        return f"0x{addr[:8]}...{addr[-8:]}"


@dataclass
class AptosKeyPair:
    """Aptos 密钥对 (Ed25519)"""
    private_key_bytes: bytes             # 私钥字节 (32字节)
    public_key_bytes: bytes             # 公钥字节 (32字节)
    address: str                         # Aptos 地址
    
    @classmethod
    def generate(cls) -> "AptosKeyPair":
        """生成新的密钥对"""
        # Ed25519 私钥是 32 字节
        private_key = secrets.token_bytes(32)
        return cls.from_private_key(private_key)
    
    @classmethod
    def from_private_key(cls, private_key: Union[bytes, str]) -> "AptosKeyPair":
        """
        从私钥创建密钥对
        
        Args:
            private_key: 私钥 (bytes 或 hex string)
        
        Returns:
            AptosKeyPair 对象
        """
        if isinstance(private_key, str):
            # 支持带 0x 前缀或无前缀的十六进制
            if private_key.startswith("0x"):
                private_key = private_key[2:]
            try:
                private_key_bytes = bytes.fromhex(private_key)
            except ValueError as e:
                raise InvalidPrivateKeyError(f"Invalid hex private key: {e}")
        else:
            private_key_bytes = private_key
        
        # 验证私钥长度 (Ed25519 需要 32 字节)
        if len(private_key_bytes) != 32:
            raise InvalidPrivateKeyError(
                f"Invalid private key length: {len(private_key_bytes)}, expected 32"
            )
        
        # 计算公钥 (Ed25519)
        try:
            from nacl.signing import SigningKey
            signing_key = SigningKey(private_key_bytes)
            public_key = signing_key.verify_key.encode()
        except ImportError:
            # 如果 nacl 不可用，使用简化计算 (仅用于测试)
            public_key = hashlib.sha256(private_key_bytes).digest()[:32]
        except Exception as e:
            raise SigningError(f"Failed to derive public key: {e}")
        
        # Aptos 地址 = 32字节公钥的直接十六进制表示
        address = "0x" + public_key.hex()
        
        return cls(
            private_key_bytes=private_key_bytes,
            public_key_bytes=public_key,
            address=address
        )
    
    @property
    def private_key_hex(self) -> str:
        """返回十六进制私钥"""
        return self.private_key_bytes.hex()
    
    @property
    def public_key_hex(self) -> str:
        """返回十六进制公钥"""
        return self.public_key_bytes.hex()
    
    def sign(self, message: bytes) -> bytes:
        """
        签名消息
        
        Args:
            message: 要签名的消息字节
        
        Returns:
            签名结果 (64字节 Ed25519 签名)
        """
        try:
            from nacl.signing import SigningKey
            signing_key = SigningKey(self.private_key_bytes)
            signed = signing_key.sign(message)
            return signed.signature
        except ImportError:
            raise SigningError("nacl library required for signing")
        except Exception as e:
            raise SigningError(f"Signing failed: {e}")
    
    def verify(self, message: bytes, signature: bytes) -> bool:
        """
        验证签名
        
        Args:
            message: 原始消息
            signature: 签名
        
        Returns:
            是否验证通过
        """
        try:
            from nacl.signing import VerifyKey
            from nacl.exceptions import BadSignatureError
            
            verify_key = VerifyKey(self.public_key_bytes)
            verify_key.verify(message, signature)
            return True
        except BadSignatureError:
            return False
        except Exception:
            return False


@dataclass
class CoinBalance:
    """Coin 余额信息"""
    coin_type: str                       # Coin 类型 (如 0x1::aptos_coin::AptosCoin)
    symbol: str                          # 符号 (如 APT, USDC)
    balance: int                         # 余额 (最小单位)
    decimals: int                        # 精度
    usd_value: Optional[float] = None   # USD 价值
    
    @property
    def balance_readable(self) -> float:
        """可读余额"""
        return self.balance / (10 ** self.decimals)
    
    def to_dict(self) -> Dict:
        return {
            "coin_type": self.coin_type,
            "symbol": self.symbol,
            "balance": self.balance,
            "balance_readable": self.balance_readable,
            "decimals": self.decimals,
            "usd_value": self.usd_value
        }


@dataclass
class AptosWalletInfo:
    """Aptos 钱包信息"""
    wallet_id: str                       # 钱包 ID
    name: str                             # 钱包名称
    address: AptosAddress                 # Aptos 地址
    created_at: datetime = field(default_factory=datetime.now)
    last_used: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict:
        return {
            "wallet_id": self.wallet_id,
            "name": self.name,
            "address": self.address.address,
            "short_address": self.address.short_address,
            "public_key": self.address.public_key_hex,
            "created_at": self.created_at.isoformat(),
            "last_used": self.last_used.isoformat()
        }


# ============================================
# 工具函数
# ============================================

def _encrypt_private_key(private_key: bytes, password: str) -> str:
    """加密私钥 (AES-256-GCM)"""
    salt = secrets.token_bytes(16)
    nonce = secrets.token_bytes(12)
    
    # 派生密钥
    key = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 100000, dklen=32)
    
    # 加密
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
    ciphertext, tag = cipher.encrypt_and_digest(private_key)
    
    # 组合: salt + nonce + tag + ciphertext
    encrypted = salt + nonce + tag + ciphertext
    return base64.b64encode(encrypted).decode()


def _decrypt_private_key(encrypted: str, password: str) -> bytes:
    """解密私钥"""
    try:
        data = base64.b64decode(encrypted)
        salt, nonce, tag, ciphertext = data[:16], data[16:28], data[28:44], data[44:]
        
        # 派生密钥
        key = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 100000, dklen=32)
        
        # 解密
        cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
        return cipher.decrypt_and_verify(ciphertext, tag)
    except Exception as e:
        raise InvalidPrivateKeyError(f"Decryption failed: {e}")


# ============================================
# BCS 编码工具
# ============================================

class AptosBcsCodec:
    """Aptos BCS (Binary Canonical Serialization) 编解码器"""
    
    @staticmethod
    def encode_address(address: str) -> bytes:
        """编码 Aptos 地址 (32 字节)"""
        if address.startswith("0x"):
            address = address[2:]
        return bytes.fromhex(address.zfill(64))
    
    @staticmethod
    def encode_u64(value: int) -> bytes:
        """编码 u64 整数 (LEB128)"""
        result = []
        while True:
            byte = value & 0x7f
            value >>= 7
            if value != 0:
                byte |= 0x80
            result.append(byte)
            if value == 0:
                break
        return bytes(result)
    
    @staticmethod
    def encode_u128(value: int) -> bytes:
        """编码 u128 整数 (LEB128)"""
        result = []
        while True:
            byte = value & 0x7f
            value >>= 7
            if value != 0:
                byte |= 0x80
            result.append(byte)
            if value == 0:
                break
        return bytes(result)
    
    @staticmethod
    def encode_bool(value: bool) -> bytes:
        """编码布尔值"""
        return bytes([1 if value else 0])
    
    @staticmethod
    def encode_string(value: str) -> bytes:
        """编码字符串"""
        encoded = value.encode('utf-8')
        return AptosBcsCodec.encode_u64(len(encoded)) + encoded
    
    @staticmethod
    def encode_transaction_authenticator(
        sender: AptosKeyPair,
        raw_txn: bytes
    ) -> Dict[str, Any]:
        """
        编码交易认证器
        
        Args:
            sender: 发送者密钥对
            raw_txn: 原始交易字节
        
        Returns:
            认证器数据
        """
        # Ed25519 签名
        signature = sender.sign(raw_txn)
        
        return {
            "type": "ed25519",
            "public_key": base64.b64encode(sender.public_key_bytes).decode(),
            "signature": base64.b64encode(signature).decode()
        }


# ============================================
# RPC 客户端
# ============================================

class AptosRpcClient:
    """Aptos REST API 客户端"""
    
    def __init__(
        self,
        rpc_url: Optional[str] = None,
        timeout: int = AptosAPIConfig.REQUEST_TIMEOUT
    ):
        self.rpc_url = rpc_url or AptosAPIConfig.MAINNET
        self.timeout = timeout
        self._client = httpx.Client(timeout=timeout)
    
    def close(self):
        """关闭客户端"""
        self._client.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
    
    def _get(self, endpoint: str, params: Dict = None) -> Dict:
        """发送 GET 请求"""
        url = f"{self.rpc_url}/{endpoint.lstrip('/')}"
        
        try:
            response = self._client.get(url, params=params)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            raise AptosWalletError(f"HTTP Error: {e}")
    
    def _post(self, endpoint: str, data: Dict = None) -> Dict:
        """发送 POST 请求"""
        url = f"{self.rpc_url}/{endpoint.lstrip('/')}"
        
        try:
            response = self._client.post(
                url,
                json=data,
                headers={"Content-Type": "application/json"}
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            raise AptosWalletError(f"HTTP Error: {e}")
    
    def get_account(self, address: str) -> Dict:
        """
        获取账户信息
        
        Args:
            address: Aptos 地址
        
        Returns:
            账户信息
        """
        return self._get(f"/accounts/{address}")
    
    def get_account_balance(self, address: str) -> Dict:
        """
        获取 APT 余额
        
        Args:
            address: Aptos 地址
        
        Returns:
            余额信息
        """
        return self._get(f"/accounts/{address}/resource/0x1::coin::CoinStore<0x1::aptos_coin::AptosCoin>")
    
    def get_token_balance(
        self,
        address: str,
        coin_type: str
    ) -> Dict:
        """
        获取 Token 余额
        
        Args:
            address: Aptos 地址
            coin_type: Coin 类型地址
        
        Returns:
            余额信息
        """
        # 格式化 coin type
        coin_store_type = f"0x1::coin::CoinStore<{coin_type}>"
        return self._get(f"/accounts/{address}/resource/{coin_store_type}")
    
    def get_table_item(
        self,
        table_handle: str,
        data: Dict
    ) -> Dict:
        """
        获取 Table 项
        
        Args:
            table_handle: Table Handle
            data: 查询数据
        
        Returns:
            Table 项
        """
        return self._post(f"/tables/{table_handle}/item", data)
    
    def getTransactions(self, limit: int = 25) -> List[Dict]:
        """获取最新交易列表"""
        return self._get("/transactions", {"limit": limit})
    
    def getTransaction(self, tx_hash: str) -> Dict:
        """
        获取交易信息
        
        Args:
            tx_hash: 交易哈希
        
        Returns:
            交易信息
        """
        return self._get(f"/transactions/{tx_hash}")
    
    def submit_transaction(self, txn: Dict) -> Dict:
        """
        提交交易
        
        Args:
            txn: 交易数据
        
        Returns:
            提交结果
        """
        return self._post("/transactions", txn)
    
    def simulate_transaction(self, txn: Dict) -> Dict:
        """
        模拟交易
        
        Args:
            txn: 交易数据
        
        Returns:
            模拟结果
        """
        return self._post("/transactions/simulate", txn)
    
    def getChainId(self) -> int:
        """获取链 ID"""
        return self._get("/").get("chain_id", 1)
    
    def getLedgerInfo(self) -> Dict:
        """获取账本信息"""
        return self._get("/")


# ============================================
# Aptos 钱包管理器
# ============================================

class AptosWalletManager:
    """
    Aptos 钱包管理器
    
    功能：
    - 创建/导入钱包
    - 余额查询
    - 交易签名
    - 密钥加密存储
    """
    
    def __init__(
        self,
        rpc_url: Optional[str] = None,
        tx_config: Optional[AptosTxConfig] = None
    ):
        self.rpc_url = rpc_url or AptosAPIConfig.MAINNET
        self.tx_config = tx_config or AptosTxConfig()
        self.rpc_client = AptosRpcClient(self.rpc_url)
        
        # 内存中的密钥对 (不安全，仅用于演示)
        self._keypair: Optional[AptosKeyPair] = None
        self._wallet_info: Optional[AptosWalletInfo] = None
    
    def close(self):
        """关闭资源"""
        self.rpc_client.close()
    
    @property
    def is_loaded(self) -> bool:
        """是否已加载钱包"""
        return self._keypair is not None
    
    @property
    def address(self) -> Optional[str]:
        """获取当前地址"""
        if self._keypair:
            return self._keypair.address
        return None
    
    @property
    def public_key(self) -> Optional[str]:
        """获取公钥"""
        if self._keypair:
            return self._keypair.public_key_hex
        return None
    
    def create_wallet(
        self,
        name: str = "aptos_wallet"
    ) -> AptosWalletInfo:
        """
        创建新钱包
        
        Args:
            name: 钱包名称
        
        Returns:
            钱包信息
        """
        # 生成新密钥对
        self._keypair = AptosKeyPair.generate()
        
        # 创建钱包信息
        self._wallet_info = AptosWalletInfo(
            wallet_id=f"aptos_{datetime.now().strftime('%Y%m%d%H%M%S')}",
            name=name,
            address=AptosAddress(
                address=self._keypair.address,
                public_key=self._keypair.public_key_bytes,
                public_key_hex=self._keypair.public_key_hex
            )
        )
        
        logger.info(f"Created new Aptos wallet: {self._wallet_info.address.short_address}")
        
        return self._wallet_info
    
    def import_wallet(
        self,
        private_key: Union[str, bytes],
        name: str = "aptos_wallet"
    ) -> AptosWalletInfo:
        """
        导入钱包
        
        Args:
            private_key: 私钥 (hex 或 bytes)
            name: 钱包名称
        
        Returns:
            钱包信息
        """
        # 从私钥创建密钥对
        self._keypair = AptosKeyPair.from_private_key(private_key)
        
        # 创建钱包信息
        self._wallet_info = AptosWalletInfo(
            wallet_id=f"aptos_{datetime.now().strftime('%Y%m%d%H%M%S')}",
            name=name,
            address=AptosAddress(
                address=self._keypair.address,
                public_key=self._keypair.public_key_bytes,
                public_key_hex=self._keypair.public_key_hex
            )
        )
        
        logger.info(f"Imported Aptos wallet: {self._wallet_info.address.short_address}")
        
        return self._wallet_info
    
    def export_private_key(self, password: Optional[str] = None) -> str:
        """
        导出私钥
        
        Args:
            password: 密码 (可选，如果提供则加密返回)
        
        Returns:
            私钥 (hex)
        """
        if not self._keypair:
            raise AptosWalletError("No wallet loaded")
        
        if password:
            return _encrypt_private_key(self._keypair.private_key_bytes, password)
        
        return self._keypair.private_key_hex
    
    def get_balance(
        self,
        address: Optional[str] = None,
        coin_type: Optional[str] = None
    ) -> List[CoinBalance]:
        """
        获取余额
        
        Args:
            address: 地址 (默认使用当前钱包)
            coin_type: Coin 类型 (None 表示 APT)
        
        Returns:
            余额列表
        """
        target_address = address or self.address
        if not target_address:
            raise AptosWalletError("No address provided")
        
        balances = []
        
        if coin_type is None:
            # 查询 APT 余额
            coin_type = AptosCoins.APT
        
        try:
            result = self.rpc_client.get_token_balance(target_address, coin_type)
            
            # 获取符号
            symbol = AptosCoins.COIN_ADDRESSES.get(coin_type, coin_type.split("::")[-1])
            decimals = AptosCoins.DECIMALS.get(coin_type, 8)
            
            balance = CoinBalance(
                coin_type=coin_type,
                symbol=symbol,
                balance=int(result.get("coin", {}).get("value", 0)),
                decimals=decimals
            )
            balances.append(balance)
            
        except Exception as e:
            logger.warning(f"Failed to get balance for {coin_type}: {e}")
            # 返回 0 余额
            symbol = AptosCoins.COIN_ADDRESSES.get(coin_type, coin_type.split("::")[-1])
            decimals = AptosCoins.DECIMALS.get(coin_type, 8)
            balances.append(CoinBalance(
                coin_type=coin_type,
                symbol=symbol,
                balance=0,
                decimals=decimals
            ))
        
        return balances
    
    def get_apt_balance(self, address: Optional[str] = None) -> int:
        """
        获取 APT 余额
        
        Args:
            address: 地址 (默认使用当前钱包)
        
        Returns:
            APT 余额 (Octas)
        """
        balances = self.get_balance(address, AptosCoins.APT)
        if balances:
            return balances[0].balance
        return 0
    
    def get_token_balances(self, address: Optional[str] = None) -> Dict[str, int]:
        """
        获取所有代币余额
        
        Args:
            address: 地址 (默认使用当前钱包)
        
        Returns:
            代币符号 -> 余额映射
        """
        target_address = address or self.address
        if not target_address:
            raise AptosWalletError("No address provided")
        
        result = {}
        
        # 查询常用代币
        for symbol, coin_type in AptosCoins.COIN_SYMBOLS.items():
            balances = self.get_balance(target_address, coin_type)
            if balances and balances[0].balance > 0:
                result[symbol] = balances[0].balance
        
        return result
    
    def sign_transaction(self, transaction: Dict) -> Dict:
        """
        签名交易
        
        Args:
            transaction: 交易数据
        
        Returns:
            带签名的交易
        """
        if not self._keypair:
            raise AptosWalletError("No wallet loaded")
        
        # 这里需要 BCS 编码交易然后签名
        # Aptos SDK 会处理这个，这里只是示意
        raise NotImplementedError("Use AptosTransactionBuilder for full transaction signing")
    
    def get_wallet_info(self) -> Optional[AptosWalletInfo]:
        """获取钱包信息"""
        return self._wallet_info
    
    def get_sequence_number(self, address: Optional[str] = None) -> int:
        """
        获取序列号
        
        Args:
            address: 地址 (默认使用当前钱包)
        
        Returns:
            序列号
        """
        target_address = address or self.address
        if not target_address:
            raise AptosWalletError("No address provided")
        
        try:
            account = self.rpc_client.get_account(target_address)
            return int(account.get("sequence_number", "0"))
        except Exception as e:
            logger.warning(f"Failed to get sequence number: {e}")
            return 0


# ============================================
# 全局单例
# ============================================

_aptos_wallet_manager: Optional[AptosWalletManager] = None


def get_aptos_wallet_manager() -> AptosWalletManager:
    """获取全局 Aptos 钱包管理器"""
    global _aptos_wallet_manager
    if _aptos_wallet_manager is None:
        _aptos_wallet_manager = AptosWalletManager()
    return _aptos_wallet_manager


def init_aptos_wallet_manager(
    rpc_url: Optional[str] = None,
    private_key: Optional[str] = None,
    name: str = "aptos_wallet"
) -> AptosWalletManager:
    """
    初始化 Aptos 钱包管理器
    
    Args:
        rpc_url: RPC URL
        private_key: 私钥 (可选)
        name: 钱包名称
    
    Returns:
        AptosWalletManager 实例
    """
    global _aptos_wallet_manager
    _aptos_wallet_manager = AptosWalletManager(rpc_url=rpc_url)
    
    if private_key:
        _aptos_wallet_manager.import_wallet(private_key, name)
    else:
        _aptos_wallet_manager.create_wallet(name)
    
    return _aptos_wallet_manager
