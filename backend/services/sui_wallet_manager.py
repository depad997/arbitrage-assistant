"""
Sui 钱包管理模块

功能：
- 从私钥/助记词创建 Sui 地址
- 生成新密钥对 (Ed25519)
- 查询 SUI 和其他 Coin 余额
- 签名交易
- 导入/导出密钥

Sui 技术特点：
- 使用 Ed25519 签名算法
- 地址格式: 0x + 32字节十六进制 (共66个字符)
- 对象模型: 所有资产都是 Object
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

from config.sui_dex import (
    SuiRPCConfig,
    SuiTxConfig,
    SuiCoins,
    SuiConfig,
    format_sui_amount,
    parse_sui_amount,
)

logger = logging.getLogger(__name__)


# ============================================
# 错误定义
# ============================================

class SuiWalletError(Exception):
    """Sui 钱包错误基类"""
    pass


class InvalidPrivateKeyError(SuiWalletError):
    """无效私钥"""
    pass


class InvalidAddressError(SuiWalletError):
    """无效地址"""
    pass


class BalanceQueryError(SuiWalletError):
    """余额查询错误"""
    pass


class SigningError(SuiWalletError):
    """签名错误"""
    pass


# ============================================
# 数据类定义
# ============================================

@dataclass
class SuiAddress:
    """Sui 地址信息"""
    address: str                        # Sui 地址 (0x...)
    public_key: Optional[bytes] = None  # 公钥字节
    public_key_hex: Optional[str] = None  # 公钥十六进制
    
    def __post_init__(self):
        if not self.address.startswith("0x"):
            self.address = "0x" + self.address
    
    @property
    def is_valid(self) -> bool:
        """检查地址是否有效"""
        addr = self.address[2:] if self.address.startswith("0x") else self.address
        return len(addr) == 64 and all(c in '0123456789abcdef' for c in addr.lower())


@dataclass
class SuiKeyPair:
    """Sui 密钥对"""
    private_key_bytes: bytes            # 私钥字节
    public_key_bytes: bytes             # 公钥字节
    address: str                         # Sui 地址
    
    @classmethod
    def generate(cls) -> "SuiKeyPair":
        """生成新的密钥对"""
        # Ed25519 私钥是 32 字节
        private_key = secrets.token_bytes(32)
        return cls.from_private_key(private_key)
    
    @classmethod
    def from_private_key(cls, private_key: Union[bytes, str]) -> "SuiKeyPair":
        """
        从私钥创建密钥对
        
        Args:
            private_key: 私钥 (bytes 或 hex string)
        
        Returns:
            SuiKeyPair 对象
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
        
        # 计算 Sui 地址 (Blake2b hash of public key)
        address = _compute_sui_address(public_key)
        
        return cls(
            private_key_bytes=private_key_bytes,
            public_key_bytes=public_key,
            address=address
        )
    
    @property
    def private_key_hex(self) -> str:
        """返回十六进制私钥"""
        return private_key_bytes.hex()
    
    @property
    def public_key_hex(self) -> str:
        """返回十六进制公钥"""
        return self.public_key_bytes.hex()


@dataclass
class CoinBalance:
    """Coin 余额信息"""
    coin_type: str                      # Coin 类型
    symbol: str                          # 符号 (如 SUI, USDC)
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
class SuiWalletInfo:
    """Sui 钱包信息"""
    wallet_id: str                      # 钱包 ID
    name: str                            # 钱包名称
    address: SuiAddress                  # Sui 地址
    created_at: datetime = field(default_factory=datetime.now)
    last_used: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict:
        return {
            "wallet_id": self.wallet_id,
            "name": self.name,
            "address": self.address.address,
            "created_at": self.created_at.isoformat(),
            "last_used": self.last_used.isoformat()
        }


# ============================================
# 工具函数
# ============================================

def _compute_sui_address(public_key: bytes) -> str:
    """计算 Sui 地址 (Blake2b hash of public key)"""
    try:
        import pycryptodome
        from Crypto.Hash import BLAKE2b
        h = BLAKE2b.new(digest_bits=256)
        h.update(public_key)
        return "0x" + h.hexdigest()
    except ImportError:
        # 备用: 使用 SHA256 (仅用于测试)
        return "0x" + hashlib.sha256(public_key).hexdigest()


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
# RPC 客户端
# ============================================

class SuiRpcClient:
    """Sui RPC 客户端"""
    
    def __init__(
        self,
        rpc_url: Optional[str] = None,
        timeout: int = SuiRPCConfig.REQUEST_TIMEOUT
    ):
        self.rpc_url = rpc_url or SuiConfig.get_rpc()
        self.timeout = timeout
        self._client = httpx.Client(timeout=timeout)
    
    def close(self):
        """关闭客户端"""
        self._client.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
    
    def _post(self, method: str, params: List = None) -> Dict:
        """发送 RPC 请求"""
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params or []
        }
        
        try:
            response = self._client.post(
                self.rpc_url,
                json=payload,
                headers={"Content-Type": "application/json"}
            )
            response.raise_for_status()
            result = response.json()
            
            if "error" in result:
                raise SuiWalletError(f"RPC Error: {result['error']}")
            
            return result.get("result", {})
        except httpx.HTTPError as e:
            raise SuiWalletError(f"HTTP Error: {e}")
    
    def get_balance(self, address: str, coin_type: Optional[str] = None) -> Dict:
        """
        获取地址余额
        
        Args:
            address: Sui 地址
            coin_type: Coin 类型 (None 表示原生 SUI)
        
        Returns:
            余额信息
        """
        params = [address]
        if coin_type:
            params.append(coin_type)
        
        return self._post("suix_getBalance", params)
    
    def get_coins(self, address: str, coin_type: Optional[str] = None) -> Dict:
        """
        获取地址的所有 Coin 对象
        
        Args:
            address: Sui 地址
            coin_type: Coin 类型 (None 表示所有)
        
        Returns:
            Coin 列表
        """
        params = [address]
        if coin_type:
            params.append(coin_type)
        
        return self._post("suix_getCoins", params)
    
    def get_all_balances(self, address: str) -> List[Dict]:
        """获取地址所有 Coin 余额"""
        return self._post("suix_getAllBalances", [address])
    
    def get_object(self, object_id: str) -> Dict:
        """获取对象信息"""
        return self._post("sui_getObject", [object_id])
    
    def get_transaction(self, digest: str) -> Dict:
        """获取交易信息"""
        return self._post("sui_getTransactionBlock", [digest])
    
    def execute_transaction(self, tx_bytes: str, signature: str) -> Dict:
        """执行交易"""
        return self._post("sui_executeTransactionBlock", [
            tx_bytes,
            [signature],
            {"showInput": True, "showEffects": True, "showEvents": True}
        ])
    
    def dry_run_transaction(self, tx_bytes: str) -> Dict:
        """模拟交易"""
        return self._post("sui_dryRunTransactionBlock", [tx_bytes])
    
    def get_latest_epoch(self) -> Dict:
        """获取最新 Epoch 信息"""
        return self._post("sui_getLatestEpoch", [])
    
    def get_reference_gas_price(self) -> int:
        """获取参考 Gas 价格"""
        return self._post("suix_getReferenceGasPrice", [])


# ============================================
# Sui 钱包管理器
# ============================================

class SuiWalletManager:
    """
    Sui 钱包管理器
    
    功能：
    - 创建/导入钱包
    - 余额查询
    - 交易签名
    - 密钥加密存储
    """
    
    def __init__(
        self,
        rpc_url: Optional[str] = None,
        keystore_dir: Optional[Path] = None
    ):
        self.rpc_url = rpc_url or SuiConfig.get_rpc()
        self.keystore_dir = keystore_dir or Path.home() / ".sui_wallet"
        self.keystore_dir.mkdir(parents=True, exist_ok=True)
        
        self._client: Optional[SuiRpcClient] = None
        self._current_wallet: Optional[SuiWalletInfo] = None
        self._keypair: Optional[SuiKeyPair] = None
        self._unlocked = False
    
    @property
    def client(self) -> SuiRpcClient:
        """获取 RPC 客户端"""
        if self._client is None:
            self._client = SuiRpcClient(self.rpc_url)
        return self._client
    
    def generate_wallet(self, name: str = "default") -> SuiWalletInfo:
        """
        生成新钱包
        
        Args:
            name: 钱包名称
        
        Returns:
            SuiWalletInfo 对象
        """
        keypair = SuiKeyPair.generate()
        wallet_id = secrets.token_hex(16)
        
        wallet_info = SuiWalletInfo(
            wallet_id=wallet_id,
            name=name,
            address=SuiAddress(
                address=keypair.address,
                public_key_bytes=keypair.public_key_bytes,
                public_key_hex=keypair.public_key_hex
            )
        )
        
        self._current_wallet = wallet_info
        self._keypair = keypair
        self._unlocked = True
        
        logger.info(f"Generated new Sui wallet: {wallet_info.address.address}")
        return wallet_info
    
    def import_wallet(
        self,
        private_key: Union[str, bytes],
        name: str = "imported"
    ) -> SuiWalletInfo:
        """
        导入钱包
        
        Args:
            private_key: 私钥 (hex string 或 bytes)
            name: 钱包名称
        
        Returns:
            SuiWalletInfo 对象
        """
        keypair = SuiKeyPair.from_private_key(private_key)
        wallet_id = secrets.token_hex(16)
        
        wallet_info = SuiWalletInfo(
            wallet_id=wallet_id,
            name=name,
            address=SuiAddress(
                address=keypair.address,
                public_key_bytes=keypair.public_key_bytes,
                public_key_hex=keypair.public_key_hex
            )
        )
        
        self._current_wallet = wallet_info
        self._keypair = keypair
        self._unlocked = True
        
        logger.info(f"Imported Sui wallet: {wallet_info.address.address}")
        return wallet_info
    
    def load_encrypted_wallet(
        self,
        keystore_path: str,
        password: str
    ) -> SuiWalletInfo:
        """
        加载加密的钱包
        
        Args:
            keystore_path: Keystore 文件路径
            password: 解密密码
        
        Returns:
            SuiWalletInfo 对象
        """
        with open(keystore_path, 'r') as f:
            keystore = json.load(f)
        
        # 解密私钥
        private_key = _decrypt_private_key(keystore["encrypted_key"], password)
        
        return self.import_wallet(private_key, keystore.get("name", "loaded"))
    
    def save_encrypted_wallet(
        self,
        keystore_path: Optional[str] = None,
        password: Optional[str] = None
    ) -> str:
        """
        保存加密的钱包
        
        Args:
            keystore_path: 保存路径 (默认使用地址命名)
            password: 加密密码
        
        Returns:
            保存的文件路径
        """
        if not self._current_wallet or not self._keypair:
            raise SuiWalletError("No wallet loaded")
        
        if not password:
            raise SuiWalletError("Password required for encryption")
        
        if not keystore_path:
            keystore_path = str(self.keystore_dir / f"sui_{self._current_wallet.address.address}.json")
        
        encrypted_key = _encrypt_private_key(
            self._keypair.private_key_bytes,
            password
        )
        
        keystore_data = {
            "address": self._current_wallet.address.address,
            "name": self._current_wallet.name,
            "encrypted_key": encrypted_key,
            "created_at": datetime.now().isoformat()
        }
        
        with open(keystore_path, 'w') as f:
            json.dump(keystore_data, f, indent=2)
        
        logger.info(f"Saved encrypted wallet to: {keystore_path}")
        return keystore_path
    
    @property
    def current_address(self) -> Optional[str]:
        """获取当前钱包地址"""
        if self._current_wallet:
            return self._current_wallet.address.address
        return None
    
    @property
    def is_unlocked(self) -> bool:
        """检查钱包是否已解锁"""
        return self._unlocked
    
    def lock(self):
        """锁定钱包"""
        self._keypair = None
        self._unlocked = False
        logger.info("Wallet locked")
    
    def get_balance(
        self,
        address: Optional[str] = None,
        coin_type: Optional[str] = None
    ) -> CoinBalance:
        """
        查询余额
        
        Args:
            address: 地址 (默认使用当前钱包)
            coin_type: Coin 类型 (默认 SUI)
        
        Returns:
            CoinBalance 对象
        """
        target_address = address or self.current_address
        if not target_address:
            raise SuiWalletError("No address provided")
        
        # 获取 coin_type 的 symbol
        if coin_type is None:
            coin_type = SuiCoins.SUI
            decimals = 9
            symbol = "SUI"
        else:
            symbol = SuiCoins.COIN_ADDRESSES.get(coin_type, coin_type.split("::")[-1])
            decimals = SuiCoins.DECIMALS.get(coin_type, 9)
        
        try:
            result = self.client.get_balance(target_address, coin_type)
            total_balance = int(result.get("totalBalance", "0"))
            
            return CoinBalance(
                coin_type=coin_type,
                symbol=symbol,
                balance=total_balance,
                decimals=decimals
            )
        except Exception as e:
            raise BalanceQueryError(f"Failed to query balance: {e}")
    
    def get_all_balances(self, address: Optional[str] = None) -> List[CoinBalance]:
        """查询所有代币余额"""
        target_address = address or self.current_address
        if not target_address:
            raise SuiWalletError("No address provided")
        
        try:
            results = self.client.get_all_balances(target_address)
            balances = []
            
            for item in results:
                coin_type = item.get("coinType", "")
                symbol = SuiCoins.COIN_ADDRESSES.get(coin_type, coin_type.split("::")[-1])
                decimals = SuiCoins.DECIMALS.get(coin_type, 9)
                balance = int(item.get("totalBalance", "0"))
                
                balances.append(CoinBalance(
                    coin_type=coin_type,
                    symbol=symbol,
                    balance=balance,
                    decimals=decimals
                ))
            
            return balances
        except Exception as e:
            raise BalanceQueryError(f"Failed to query all balances: {e}")
    
    def sign_transaction(self, transaction_bytes: bytes) -> str:
        """
        签名交易
        
        Args:
            transaction_bytes: 交易字节数据
        
        Returns:
            Base64 编码的签名
        """
        if not self._keypair:
            raise SigningError("Wallet not unlocked")
        
        try:
            from nacl.signing import SigningKey
            from nacl.encoding import RawEncoder
            
            signing_key = SigningKey(self._keypair.private_key_bytes)
            signed = signing_key.sign(transaction_bytes, encoder=RawEncoder)
            # 签名结果包含 64 字节签名
            signature = base64.b64encode(signed.signature).decode()
            
            logger.debug(f"Transaction signed: {signature[:32]}...")
            return signature
        except ImportError:
            raise SigningError("nacl library required for signing")
        except Exception as e:
            raise SigningError(f"Signing failed: {e}")
    
    def sign_message(self, message: bytes) -> str:
        """
        签名消息 (Personal Sign)
        
        Args:
            message: 消息字节
        
        Returns:
            Base64 编码的签名
        """
        if not self._keypair:
            raise SigningError("Wallet not unlocked")
        
        try:
            from nacl.signing import SigningKey
            from nacl.encoding import RawEncoder
            
            signing_key = SigningKey(self._keypair.private_key_bytes)
            signed = signing_key.sign(message, encoder=RawEncoder)
            return base64.b64encode(signed.signature).decode()
        except ImportError:
            raise SigningError("nacl library required for signing")
        except Exception as e:
            raise SigningError(f"Signing failed: {e}")
    
    def get_wallet_info(self) -> Optional[SuiWalletInfo]:
        """获取当前钱包信息"""
        return self._current_wallet
    
    def close(self):
        """关闭并清理资源"""
        self.lock()
        if self._client:
            self._client.close()


# ============================================
# 全局单例
# ============================================

_sui_wallet_manager: Optional[SuiWalletManager] = None


def get_sui_wallet_manager() -> SuiWalletManager:
    """获取 Sui 钱包管理器单例"""
    global _sui_wallet_manager
    if _sui_wallet_manager is None:
        _sui_wallet_manager = SuiWalletManager()
    return _sui_wallet_manager


def init_sui_wallet_manager(
    rpc_url: Optional[str] = None,
    keystore_dir: Optional[Path] = None
) -> SuiWalletManager:
    """初始化 Sui 钱包管理器"""
    global _sui_wallet_manager
    _sui_wallet_manager = SuiWalletManager(rpc_url=rpc_url, keystore_dir=keystore_dir)
    return _sui_wallet_manager
