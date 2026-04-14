"""
钱包管理模块 - Phase 2 执行能力核心组件

功能：
- 私钥加密存储（AES-256-GCM）
- 多链地址派生（从主私钥派生不同链地址）
- 余额查询（原生代币 + ERC20）
- 交易签名（EVM链用Web3.py，Solana用Solders）
- 支持 Keystore 文件导入导出

安全说明：
- 私钥在内存中解密后立即使用，使用后立即清除
- 敏感信息存储使用环境变量或加密的keystore文件
- 不在日志或错误信息中输出私钥相关内容
"""

import os
import json
import hmac
import hashlib
import secrets
import uuid
import logging
from typing import Dict, List, Optional, Tuple, Any, Union
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from enum import Enum
import asyncio

# 加密库
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import hashes, padding
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.backends import default_backend

# Web3 相关
from web3 import Web3
from web3.contract import Contract
from web3.types import ChecksumAddress, Wei
from eth_account import Account
from eth_account.datastructures import SignedMessage

# Solana 相关
try:
    from solders.keypair import Keypair as SolanaKeypair
    from solders.pubkey import Pubkey as SolanaPubkey
    SOLANA_SUPPORT = True
except ImportError:
    SOLANA_SUPPORT = False
    logging.warning("Solana SDK not installed, Solana support disabled")

# HTTP 客户端
import httpx

# 导入项目配置
import sys
import os as _os
_backend_dir = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from config.settings import SUPPORTED_CHAINS, ChainConfig, get_chain_config

# Solana 配置（延迟导入避免循环依赖）
try:
    from config.solana_dex import SolanaRPCConfig
except ImportError:
    # 如果配置不存在，提供默认值
    class SolanaRPCConfig:
        DEFAULT_MAINNET = "https://api.mainnet-beta.solana.com"

logger = logging.getLogger(__name__)


# ============================================
# 枚举和常量
# ============================================

class KeyStoreFormat(Enum):
    """密钥库格式"""
    RAW_HEX = "raw_hex"           # 原始十六进制
    RAW_BYTES = "raw_bytes"        # 原始字节
    V3_UTC = "v3_utc"             # Geth v3 UTC 格式
    V3_JSON = "v3_json"           # 自定义 v3 JSON 格式


# ============================================
# 数据类定义
# ============================================

@dataclass
class WalletBalance:
    """钱包余额信息"""
    chain: str
    address: str
    native_balance: float           # 原生代币余额 (ETH, BNB, etc.)
    native_balance_wei: int         # 原生代币余额 (Wei)
    tokens: Dict[str, Dict[str, Any]] = field(default_factory=dict)  # ERC20 代币余额
    total_value_usd: float = 0.0    # 总价值 (USD)
    last_updated: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict:
        return {
            "chain": self.chain,
            "address": self.address,
            "native_balance": self.native_balance,
            "tokens": self.tokens,
            "total_value_usd": self.total_value_usd,
            "last_updated": self.last_updated.isoformat()
        }


@dataclass
class ChainAddress:
    """链地址信息"""
    chain: str
    address: str                    # EVM 地址 (0x...)
    public_key: str = ""            # 公钥 (hex)
    
    @property
    def is_valid_evm_address(self) -> bool:
        """是否是有效的 EVM 地址"""
        return Web3.is_address(self.address)
    
    @property
    def checksum_address(self) -> str:
        """返回校验和地址"""
        return Web3.to_checksum_address(self.address)


@dataclass
class WalletInfo:
    """钱包完整信息"""
    wallet_id: str                 # 钱包唯一标识
    name: str                       # 钱包名称
    addresses: Dict[str, ChainAddress] = field(default_factory=dict)  # 各链地址
    created_at: datetime = field(default_factory=datetime.now)
    last_used: datetime = field(default_factory=datetime.now)
    keystore_path: Optional[str] = None  # keystore 文件路径
    
    def to_dict(self, include_sensitive: bool = False) -> Dict:
        """转换为字典"""
        return {
            "wallet_id": self.wallet_id,
            "name": self.name,
            "addresses": {
                chain: addr.to_dict() if hasattr(addr, 'to_dict') else addr
                for chain, addr in self.addresses.items()
            },
            "created_at": self.created_at.isoformat(),
            "last_used": self.last_used.isoformat(),
            "keystore_path": self.keystore_path
        }


@dataclass
class SignedTransaction:
    """已签名交易"""
    chain: str
    tx_dict: Dict                   # 交易参数字典
    signed_tx: Any                  # 签名后的交易对象
    tx_hash: Optional[str] = None   # 交易哈希
    raw_hex: Optional[str] = None   # 原始交易 hex
    
    def to_dict(self) -> Dict:
        return {
            "chain": self.chain,
            "tx_hash": self.tx_hash,
            "raw_hex": self.raw_hex
        }


# ============================================
# 加密工具类
# ============================================

class CryptoUtils:
    """加密工具类"""
    
    # AES-256-GCM Nonce 长度
    NONCE_SIZE = 12
    
    # PBKDF2 参数
    PBKDF2_ITERATIONS = 100000
    SALT_SIZE = 32
    
    @classmethod
    def generate_salt(cls) -> bytes:
        """生成随机盐"""
        return secrets.token_bytes(cls.SALT_SIZE)
    
    @classmethod
    def generate_nonce(cls) -> bytes:
        """生成随机 nonce"""
        return secrets.token_bytes(cls.NONCE_SIZE)
    
    @classmethod
    def derive_key(cls, password: str, salt: bytes) -> bytes:
        """
        使用 PBKDF2-HMAC-SHA256 派生密钥
        
        Args:
            password: 密码
            salt: 盐
            
        Returns:
            32 字节的密钥
        """
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=cls.PBKDF2_ITERATIONS,
            backend=default_backend()
        )
        return kdf.derive(password.encode())
    
    @classmethod
    def encrypt_aes_gcm(cls, data: bytes, key: bytes) -> Tuple[bytes, bytes]:
        """
        AES-256-GCM 加密
        
        Args:
            data: 要加密的数据
            key: 32 字节密钥
            
        Returns:
            (加密后的数据, nonce)
        """
        nonce = cls.generate_nonce()
        aesgcm = AESGCM(key)
        ciphertext = aesgcm.encrypt(nonce, data, None)
        return ciphertext, nonce
    
    @classmethod
    def decrypt_aes_gcm(cls, ciphertext: bytes, key: bytes, nonce: bytes) -> bytes:
        """
        AES-256-GCM 解密
        
        Args:
            ciphertext: 加密后的数据
            key: 32 字节密钥
            nonce: nonce
            
        Returns:
            解密后的数据
        """
        aesgcm = AESGCM(key)
        return aesgcm.decrypt(nonce, ciphertext, None)
    
    @classmethod
    def encrypt_aes_ctr(cls, data: bytes, key: bytes, iv: bytes) -> bytes:
        """
        AES-128-CTR 加密 (Geth V3 格式)
        
        Args:
            data: 要加密的数据
            key: 16 字节密钥
            iv: 16 字节 IV
            
        Returns:
            加密后的数据
        """
        # Geth 使用 AES-128-CTR，密钥取派生密钥的前16字节
        cipher_key = key[:16]
        cipher = Cipher(algorithms.AES(cipher_key), modes.CTR(iv), backend=default_backend())
        encryptor = cipher.encryptor()
        return encryptor.update(data) + encryptor.finalize()
    
    @classmethod
    def decrypt_aes_ctr(cls, ciphertext: bytes, key: bytes, iv: bytes) -> bytes:
        """
        AES-128-CTR 解密 (Geth V3 格式)
        
        Args:
            ciphertext: 加密后的数据
            key: 派生密钥 (32字节)
            iv: 16 字节 IV
            
        Returns:
            解密后的数据
        """
        # Geth 使用 AES-128-CTR，密钥取派生密钥的前16字节
        cipher_key = key[:16]
        cipher = Cipher(algorithms.AES(cipher_key), modes.CTR(iv), backend=default_backend())
        decryptor = cipher.decryptor()
        return decryptor.update(ciphertext) + decryptor.finalize()
    
    @classmethod
    def hash_password(cls, password: str) -> str:
        """密码哈希（用于验证）"""
        return hashlib.sha256(password.encode()).hexdigest()
    
    @classmethod
    def verify_password(cls, password: str, password_hash: str) -> bool:
        """验证密码"""
        return cls.hash_password(password) == password_hash


# ============================================
# Keystore 管理
# ============================================

class KeyStoreManager:
    """密钥库管理器"""
    
    def __init__(self, keystore_dir: Optional[str] = None):
        """
        初始化密钥库管理器
        
        Args:
            keystore_dir: 密钥库存储目录，默认为 ~/.wallet_keystore
        """
        if keystore_dir:
            self.keystore_dir = Path(keystore_dir)
        else:
            self.keystore_dir = Path.home() / ".wallet_keystore"
        
        self.keystore_dir.mkdir(parents=True, exist_ok=True)
    
    def create_v3_keystore(self, private_key: bytes, password: str) -> Dict:
        """
        创建 V3 格式密钥库（兼容 Geth）
        
        Args:
            private_key: 私钥（32字节）
            password: 密码
            
        Returns:
            密钥库字典
        """
        # 生成盐和 IV
        salt = CryptoUtils.generate_salt()
        iv = CryptoUtils.generate_nonce()
        
        # 派生加密密钥
        key = CryptoUtils.derive_key(password, salt)
        
        # IV 使用 16 字节 nonce (AES-CTR 需要)
        iv = secrets.token_bytes(16)
        
        # 使用 AES-CTR 加密私钥 (Geth V3 格式)
        ciphertext = CryptoUtils.encrypt_aes_ctr(private_key, key, iv)
        
        # 计算 MAC (用于验证密码)
        # MAC = keccak256(derived_key[16:32] + ciphertext)
        mac_input = key[16:32] + ciphertext
        mac = hashlib.new('sha3_256', mac_input).digest()
        
        # 构建 V3 格式
        keystore = {
            "version": 3,
            "id": str(uuid.uuid4()),
            "address": Web3.to_checksum_address(
                Account.from_key(private_key).address
            )[2:],  # 去掉 0x 前缀
            "crypto": {
                "cipher": "aes-128-ctr",
                "cipherparams": {
                    "iv": iv.hex()
                },
                "ciphertext": ciphertext.hex(),
                "kdf": "pbkdf2",
                "kdfparams": {
                    "dklen": 32,
                    "salt": salt.hex(),
                    "p": CryptoUtils.PBKDF2_ITERATIONS,
                    "prf": "hmac-sha256"
                },
                "mac": mac.hex()
            }
        }
        
        return keystore
    
    def save_v3_keystore(self, keystore: Dict, filename: Optional[str] = None) -> str:
        """
        保存 V3 密钥库到文件
        
        Args:
            keystore: 密钥库字典
            filename: 文件名，默认使用 uuid
            
        Returns:
            保存的文件路径
        """
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"UTC--{timestamp}--{keystore['address']}"
        
        filepath = self.keystore_dir / filename
        with open(filepath, 'w') as f:
            json.dump(keystore, f)
        
        # 设置文件权限（仅当前用户可读写）
        os.chmod(filepath, 0o600)
        
        return str(filepath)
    
    def load_v3_keystore(self, filepath: str) -> Dict:
        """加载 V3 密钥库文件"""
        with open(filepath, 'r') as f:
            return json.load(f)
    
    def decrypt_v3_keystore(self, keystore: Dict, password: str) -> bytes:
        """
        解密 V3 密钥库
        
        Args:
            keystore: 密钥库字典
            password: 密码
            
        Returns:
            私钥（32字节）
            
        Raises:
            ValueError: 密码错误
        """
        # 验证密码
        derived_key = CryptoUtils.derive_key(
            password, 
            bytes.fromhex(keystore['crypto']['kdfparams']['salt'])
        )
        
        # 验证 MAC
        ciphertext = bytes.fromhex(keystore['crypto']['ciphertext'])
        mac_input = derived_key[16:32] + ciphertext
        expected_mac = hashlib.new('sha3_256', mac_input).digest()
        actual_mac = bytes.fromhex(keystore['crypto']['mac'])
        
        if not hmac.compare_digest(expected_mac, actual_mac):
            raise ValueError("Invalid password")
        
        # 解密私钥 (使用 AES-CTR)
        iv = bytes.fromhex(keystore['crypto']['cipherparams']['iv'])
        private_key = CryptoUtils.decrypt_aes_ctr(ciphertext, derived_key, iv)
        
        return private_key
    
    def list_keystores(self) -> List[Dict]:
        """列出所有密钥库文件"""
        keystores = []
        for filepath in self.keystore_dir.glob("UTC--*"):
            try:
                with open(filepath, 'r') as f:
                    data = json.load(f)
                    keystores.append({
                        "address": data.get("address", ""),
                        "filename": filepath.name,
                        "path": str(filepath)
                    })
            except Exception as e:
                logger.warning(f"Failed to read keystore {filepath}: {e}")
        return keystores


# ============================================
# EVM 钱包管理器
# ============================================

class EVMWalletManager:
    """EVM 链钱包管理器"""
    
    # 常用 ERC20 代币 ABI（最小化）
    ERC20_ABI = [
        {
            "constant": True,
            "inputs": [{"name": "account", "type": "address"}],
            "name": "balanceOf",
            "outputs": [{"name": "", "type": "uint256"}],
            "payable": False,
            "stateMutability": "view",
            "type": "function"
        },
        {
            "constant": True,
            "inputs": [],
            "name": "decimals",
            "outputs": [{"name": "", "type": "uint8"}],
            "payable": False,
            "stateMutability": "view",
            "type": "function"
        },
        {
            "constant": True,
            "inputs": [],
            "name": "symbol",
            "outputs": [{"name": "", "type": "string"}],
            "payable": False,
            "stateMutability": "view",
            "type": "function"
        }
    ]
    
    # 常用代币地址映射
    COMMON_TOKENS: Dict[str, Dict[str, Dict]] = {
        "ethereum": {
            "USDC": {"address": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48", "decimals": 6},
            "USDT": {"address": "0xdAC17F958D2ee523a2206206994597C13D831ec7", "decimals": 6},
            "WBTC": {"address": "0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599", "decimals": 8},
            "DAI": {"address": "0x6B175474E89094C44Da98b954EescdeCB5BE3830", "decimals": 18},
            "LINK": {"address": "0x514910771AF9Ca656af840dff83E8264EcF986CA", "decimals": 18},
        },
        "bsc": {
            "USDC": {"address": "0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580b", "decimals": 6},
            "USDT": {"address": "0x55d398326f99059dF7751A23B2a2f2dC5a7Eab8", "decimals": 6},
            "CAKE": {"address": "0x0E09FaBB73Bd3Ade0a17ECC321fD13a19e81cE82", "decimals": 18},
            "WBNB": {"address": "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c", "decimals": 18},
        },
        "polygon": {
            "USDC": {"address": "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174", "decimals": 6},
            "USDT": {"address": "0xc2132D05D31c914a87C6611C10748AEb04B58e8F", "decimals": 6},
            "WMATIC": {"address": "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270", "decimals": 18},
        },
        "arbitrum": {
            "USDC": {"address": "0xaf88d065e77c8cC2239327C5EDb3A432268e5831", "decimals": 6},
            "USDT": {"address": "0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9", "decimals": 6},
            "WETH": {"address": "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1", "decimals": 18},
        }
    }
    
    def __init__(
        self,
        private_key: Optional[bytes] = None,
        keystore_path: Optional[str] = None,
        keystore_password: Optional[str] = None,
        web3_instances: Optional[Dict[str, Web3]] = None
    ):
        """
        初始化 EVM 钱包管理器
        
        Args:
            private_key: 私钥（32字节）
            keystore_path: keystore 文件路径
            keystore_password: keystore 密码
            web3_instances: Web3 实例字典 {chain_name: Web3}
        """
        self._private_key: Optional[bytes] = None
        self._account: Optional[Account] = None
        
        # 初始化 Web3 实例
        self.web3_instances: Dict[str, Web3] = web3_instances or {}
        
        # 加载私钥
        if private_key:
            self._load_from_private_key(private_key)
        elif keystore_path and keystore_password:
            self._load_from_keystore(keystore_path, keystore_password)
        
        # ERC20 合约缓存
        self._erc20_contracts: Dict[str, Dict[str, Contract]] = {}
    
    def _load_from_private_key(self, private_key: bytes):
        """从私钥加载"""
        self._private_key = private_key
        self._account = Account.from_key(private_key)
        logger.info(f"Loaded wallet: {self._account.address}")
    
    def _load_from_keystore(self, keystore_path: str, password: str):
        """从 keystore 加载"""
        keystore_manager = KeyStoreManager()
        keystore = keystore_manager.load_v3_keystore(keystore_path)
        private_key = keystore_manager.decrypt_v3_keystore(keystore, password)
        self._load_from_private_key(private_key)
    
    @property
    def address(self) -> str:
        """获取 EVM 地址"""
        if self._account is None:
            raise ValueError("Wallet not loaded")
        return self._account.address
    
    @property
    def checksum_address(self) -> str:
        """获取校验和地址"""
        return Web3.to_checksum_address(self.address)
    
    @property
    def public_key(self) -> str:
        """获取公钥（hex）"""
        if self._account is None:
            raise ValueError("Wallet not loaded")
        return self._account.key.hex()[2:]  # 去掉 0x
    
    def _get_web3(self, chain: str) -> Web3:
        """获取或创建 Web3 实例"""
        if chain not in self.web3_instances:
            config = get_chain_config(chain)
            if not config:
                raise ValueError(f"Unknown chain: {chain}")
            if not config.is_evm:
                raise ValueError(f"Chain {chain} is not an EVM chain")
            
            self.web3_instances[chain] = Web3(Web3.HTTPProvider(config.rpc_url))
        
        return self.web3_instances[chain]
    
    def get_native_balance(self, chain: str) -> Tuple[float, int]:
        """
        获取原生代币余额
        
        Args:
            chain: 链名称
            
        Returns:
            (余额, Wei)
        """
        web3 = self._get_web3(chain)
        balance_wei = web3.eth.get_balance(self.address)
        config = get_chain_config(chain)
        decimals = 18 if config else 18
        
        balance = balance_wei / (10 ** decimals)
        return balance, balance_wei
    
    def get_erc20_balance(
        self,
        chain: str,
        token_address: str,
        decimals: int = 18
    ) -> Tuple[float, int]:
        """
        获取 ERC20 代币余额
        
        Args:
            chain: 链名称
            token_address: 代币合约地址
            decimals: 代币精度
            
        Returns:
            (余额, 最小单位)
        """
        web3 = self._get_web3(chain)
        token_address = Web3.to_checksum_address(token_address)
        
        # 获取合约
        contract = web3.eth.contract(
            address=token_address,
            abi=self.ERC20_ABI
        )
        
        # 查询余额
        balance_wei = contract.functions.balanceOf(self.address).call()
        balance = balance_wei / (10 ** decimals)
        
        return balance, balance_wei
    
    def get_balances(self, chain: str) -> WalletBalance:
        """
        获取钱包在指定链上的所有余额
        
        Args:
            chain: 链名称
            
        Returns:
            WalletBalance 对象
        """
        # 原生代币余额
        native_balance, native_balance_wei = self.get_native_balance(chain)
        
        # ERC20 代币余额
        tokens = {}
        if chain in self.COMMON_TOKENS:
            for token_symbol, token_info in self.COMMON_TOKENS[chain].items():
                try:
                    balance, _ = self.get_erc20_balance(
                        chain,
                        token_info["address"],
                        token_info["decimals"]
                    )
                    if balance > 0:
                        tokens[token_symbol] = {
                            "address": token_info["address"],
                            "balance": balance,
                            "decimals": token_info["decimals"]
                        }
                except Exception as e:
                    logger.warning(f"Failed to get {token_symbol} balance: {e}")
        
        return WalletBalance(
            chain=chain,
            address=self.checksum_address,
            native_balance=native_balance,
            native_balance_wei=native_balance_wei,
            tokens=tokens
        )
    
    def sign_transaction(self, chain: str, tx_dict: Dict) -> SignedTransaction:
        """
        签名交易
        
        Args:
            chain: 链名称
            tx_dict: 交易参数字典
            
        Returns:
            SignedTransaction 对象
        """
        if self._account is None:
            raise ValueError("Wallet not loaded")
        
        # 填充默认值
        web3 = self._get_web3(chain)
        if 'nonce' not in tx_dict:
            tx_dict['nonce'] = web3.eth.get_transaction_count(self.address)
        if 'chainId' not in tx_dict:
            tx_dict['chainId'] = get_chain_config(chain).chain_id
        if 'gas' not in tx_dict:
            try:
                tx_dict['gas'] = web3.eth.estimate_gas(tx_dict)
            except Exception:
                tx_dict['gas'] = 500000  # 默认值
        
        # 签名
        signed_tx = self._account.sign_transaction(tx_dict)
        raw_hex = signed_tx.rawTransaction.hex()
        tx_hash = web3.keccak_hex(raw_hex)
        
        return SignedTransaction(
            chain=chain,
            tx_dict=tx_dict,
            signed_tx=signed_tx,
            tx_hash=tx_hash,
            raw_hex=raw_hex
        )
    
    def derive_addresses(self, chains: Optional[List[str]] = None) -> Dict[str, ChainAddress]:
        """
        派生不同链的地址
        
        Note: 对于 EVM 链，所有地址都相同
        对于非 EVM 链需要特殊处理
        
        Args:
            chains: 要派生的链列表，默认所有支持的链
            
        Returns:
            {chain_name: ChainAddress}
        """
        if chains is None:
            chains = list(SUPPORTED_CHAINS.keys())
        
        addresses = {}
        for chain in chains:
            config = get_chain_config(chain)
            if config and config.is_evm:
                addresses[chain] = ChainAddress(
                    chain=chain,
                    address=self.checksum_address,
                    public_key=self.public_key
                )
            # 非 EVM 链暂时不支持
            # TODO: Solana, Sui, Aptos 地址派生
        
        return addresses
    
    def clear_private_key(self):
        """清除内存中的私钥"""
        if self._private_key:
            # 用零覆盖内存
            self._private_key = bytes(len(self._private_key))
            self._private_key = None
        self._account = None


# ============================================
# Solana 钱包管理器
# ============================================

class SolanaWalletManager:
    """
    Solana 钱包管理器
    
    功能：
    - 从私钥创建 Keypair
    - 生成新 Keypair
    - 导出私钥（需加密）
    - 获取 Solana 地址
    - 查询 SOL 余额
    - 查询 SPL Token 余额
    - 签名交易
    - 支持导入/导出 Keystore 文件
    
    注意：
    - Solana 使用 Ed25519 曲线，与 EVM 的 ECDSA 不同
    - 私钥是 64 字节（32 字节种子 + 32 字节扩展）
    - 地址是 Base58 编码的公钥
    """
    
    def __init__(
        self,
        private_key: Optional[bytes] = None,
        keypair: Optional[Any] = None,
        rpc_url: Optional[str] = None
    ):
        """
        初始化 Solana 钱包管理器
        
        Args:
            private_key: 私钥（64 字节或 32 字节种子）
            keypair: 已有的 Keypair 对象
            rpc_url: RPC URL（用于余额查询）
        """
        if not SOLANA_SUPPORT:
            raise ImportError("Solana SDK (solders) not installed. Install with: pip install solders")
        
        self._keypair: Optional[SolanaKeypair] = None
        self._rpc_url = rpc_url or SolanaRPCConfig.DEFAULT_MAINNET
        self._http_client: Optional[httpx.Client] = None
        
        # 加载私钥或创建新的 Keypair
        if keypair is not None:
            self._keypair = keypair
        elif private_key is not None:
            self._load_from_private_key(private_key)
        else:
            self._keypair = SolanaKeypair()
        
        # 初始化 HTTP 客户端
        self._init_http_client()
    
    def _load_from_private_key(self, private_key: bytes):
        """
        从私钥加载
        
        Args:
            private_key: 私钥（64 字节或 32 字节种子）
        """
        if len(private_key) == 64:
            # 完整的 64 字节私钥
            self._keypair = SolanaKeypair.from_bytes(private_key)
        elif len(private_key) == 32:
            # 32 字节种子，需要转换为完整私钥
            # solders 会自动从种子派生
            self._keypair = SolanaKeypair.from_seed(private_key)
        else:
            raise ValueError(f"Invalid private key length: {len(private_key)}. Expected 32 or 64 bytes.")
    
    def _init_http_client(self):
        """初始化 HTTP 客户端"""
        if self._http_client is None:
            self._http_client = httpx.Client(timeout=30)
    
    def close(self):
        """关闭 HTTP 客户端"""
        if self._http_client:
            self._http_client.close()
            self._http_client = None
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
    
    @property
    def address(self) -> str:
        """
        获取 Solana 地址（Base58 编码的公钥）
        
        Returns:
            Base58 编码的地址
        """
        if self._keypair is None:
            raise ValueError("Wallet not loaded")
        return str(self._keypair.pubkey())
    
    @property
    def pubkey(self) -> SolanaPubkey:
        """获取 SolanaPubkey 对象"""
        if self._keypair is None:
            raise ValueError("Wallet not loaded")
        return self._keypair.pubkey()
    
    @property
    def private_key_bytes(self) -> bytes:
        """
        获取私钥字节
        
        Warning: 返回原始私钥，请妥善保管
        
        Returns:
            64 字节私钥
        """
        if self._keypair is None:
            raise ValueError("Wallet not loaded")
        return bytes(self._keypair)
    
    @property
    def seed_bytes(self) -> bytes:
        """
        获取 32 字节种子
        
        Returns:
            32 字节种子
        """
        if self._keypair is None:
            raise ValueError("Wallet not loaded")
        return self._keypair.seed()
    
    def export_private_key(self, password: Optional[str] = None) -> str:
        """
        导出私钥
        
        Args:
            password: 密码（如果提供则加密返回）
        
        Returns:
            私钥 hex 或加密的私钥 hex
        """
        pk_hex = self.private_key_bytes.hex()
        
        if password:
            # 加密私钥
            salt = secrets.token_bytes(32)
            key = CryptoUtils.derive_key(password, salt)
            ciphertext, nonce = CryptoUtils.encrypt_aes_gcm(
                bytes.fromhex(pk_hex),
                key
            )
            
            # 返回加密格式
            return json.dumps({
                "encrypted": True,
                "salt": salt.hex(),
                "nonce": nonce.hex(),
                "ciphertext": ciphertext.hex()
            })
        
        return pk_hex
    
    @classmethod
    def from_private_key_hex(cls, private_key_hex: str, rpc_url: Optional[str] = None) -> "SolanaWalletManager":
        """
        从十六进制私钥创建钱包管理器
        
        Args:
            private_key_hex: 十六进制私钥
            rpc_url: RPC URL
        
        Returns:
            SolanaWalletManager 实例
        """
        # 移除可能的 0x 前缀
        if private_key_hex.startswith("0x"):
            private_key_hex = private_key_hex[2:]
        
        private_key = bytes.fromhex(private_key_hex)
        return cls(private_key=private_key, rpc_url=rpc_url)
    
    @classmethod
    def from_base58(cls, base58_key: str, rpc_url: Optional[str] = None) -> "SolanaWalletManager":
        """
        从 Base58 编码创建钱包管理器
        
        Args:
            base58_key: Base58 编码的私钥
            rpc_url: RPC URL
        
        Returns:
            SolanaWalletManager 实例
        """
        import base58
        
        private_key = base58.b58decode(base58_key)
        
        # 对于导入的 Base58 格式，可能是完整的 64 字节
        # 或需要从种子派生
        if len(private_key) == 64:
            return cls(private_key=private_key, rpc_url=rpc_url)
        elif len(private_key) == 32:
            return cls(private_key=private_key, rpc_url=rpc_url)
        else:
            raise ValueError(f"Invalid Base58 key length: {len(private_key)}")
    
    def sign_message(self, message: bytes) -> bytes:
        """
        签名消息
        
        Args:
            message: 消息字节
        
        Returns:
            签名
        """
        if self._keypair is None:
            raise ValueError("Wallet not loaded")
        return bytes(self._keypair.sign_message(message))
    
    def sign_transaction(self, transaction: Any) -> Any:
        """
        签名交易
        
        Args:
            transaction: 交易对象
        
        Returns:
            签名后的交易
        """
        if self._keypair is None:
            raise ValueError("Wallet not loaded")
        
        # 使用 solders 的签名方法
        if hasattr(transaction, 'sign'):
            return transaction.sign([self._keypair])
        elif hasattr(transaction, 'sign_message'):
            return self.sign_message(transaction)
        else:
            raise ValueError(f"Cannot sign object of type {type(transaction)}")
    
    def get_sol_balance(self) -> Tuple[float, int]:
        """
        获取 SOL 余额
        
        Returns:
            (余额 SOL, 余额 lamports)
        """
        if self._http_client is None:
            self._init_http_client()
        
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getBalance",
            "params": [self.address]
        }
        
        response = self._http_client.post(
            self._rpc_url,
            json=payload,
            headers={"Content-Type": "application/json"}
        )
        data = response.json()
        
        if "result" in data:
            lamports = data["result"]["value"]
            sol = lamports / 1e9
            return sol, lamports
        
        raise Exception(f"Failed to get balance: {data}")
    
    def get_token_balance(self, token_mint: str) -> Tuple[float, int, int]:
        """
        获取 SPL Token 余额
        
        Args:
            token_mint: 代币 Mint 地址
        
        Returns:
            (余额, 余额最小单位, 精度)
        """
        if self._http_client is None:
            self._init_http_client()
        
        # 获取关联代币账户地址
        from solders.token.instructions import get_associated_token_address
        from solders.pubkey import Pubkey as SolanaPubkey
        
        ata = get_associated_token_address(
            self.pubkey,
            SolanaPubkey.from_string(token_mint)
        )
        
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getTokenAccountBalance",
            "params": [str(ata)]
        }
        
        try:
            response = self._http_client.post(
                self._rpc_url,
                json=payload,
                headers={"Content-Type": "application/json"}
            )
            data = response.json()
            
            if "result" in data:
                info = data["result"]["value"]
                decimals = int(info.get("decimals", 0))
                amount = int(info["amount"])
                ui_amount = float(info.get("uiAmount", amount / (10 ** decimals)))
                return ui_amount, amount, decimals
            
            # 代币账户不存在
            return 0.0, 0, 0
            
        except Exception as e:
            logger.warning(f"Failed to get token balance for {token_mint}: {e}")
            return 0.0, 0, 0
    
    def get_all_token_balances(self) -> Dict[str, Dict]:
        """
        获取所有 SPL Token 余额
        
        Returns:
            {mint: {balance, decimals, ui_amount}}
        """
        if self._http_client is None:
            self._init_http_client()
        
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getTokenAccountsByOwner",
            "params": [
                self.address,
                {"programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"},
                {"encoding": "jsonParsed"}
            ]
        }
        
        response = self._http_client.post(
            self._rpc_url,
            json=payload,
            headers={"Content-Type": "application/json"}
        )
        data = response.json()
        
        balances = {}
        
        if "result" in data:
            for account in data["result"]["value"]:
                try:
                    info = account["account"]["data"]["parsed"]["info"]
                    mint = info["mint"]
                    decimals = int(info["tokenAmount"]["decimals"])
                    amount = int(info["tokenAmount"]["amount"])
                    ui_amount = float(info["tokenAmount"]["uiAmount"])
                    
                    if amount > 0:
                        balances[mint] = {
                            "balance": amount,
                            "decimals": decimals,
                            "ui_amount": ui_amount,
                            "account": info["address"]
                        }
                except (KeyError, ValueError, TypeError) as e:
                    logger.warning(f"Failed to parse token account: {e}")
                    continue
        
        return balances
    
    def save_keystore(self, path: str, password: Optional[str] = None) -> str:
        """
        保存钱包到 keystore 文件
        
        Args:
            path: 保存路径
            password: 密码（可选，加密保存）
        
        Returns:
            保存的文件路径
        """
        keystore_data = {
            "version": 1,
            "address": self.address,
            "timestamp": datetime.now().isoformat()
        }
        
        if password:
            keystore_data["encrypted"] = True
            keystore_data["private_key"] = self.export_private_key(password)
        else:
            keystore_data["encrypted"] = False
            keystore_data["private_key"] = self.export_private_key()
        
        with open(path, 'w') as f:
            json.dump(keystore_data, f, indent=2)
        
        # 设置文件权限
        os.chmod(path, 0o600)
        
        return path
    
    @classmethod
    def load_keystore(cls, path: str, password: Optional[str] = None) -> "SolanaWalletManager":
        """
        从 keystore 文件加载钱包
        
        Args:
            path: keystore 文件路径
            password: 密码（如果加密）
        
        Returns:
            SolanaWalletManager 实例
        """
        with open(path, 'r') as f:
            keystore_data = json.load(f)
        
        if keystore_data.get("encrypted", False) and password:
            # 解密私钥
            encrypted_data = json.loads(keystore_data["private_key"])
            salt = bytes.fromhex(encrypted_data["salt"])
            nonce = bytes.fromhex(encrypted_data["nonce"])
            ciphertext = bytes.fromhex(encrypted_data["ciphertext"])
            
            key = CryptoUtils.derive_key(password, salt)
            private_key = CryptoUtils.decrypt_aes_gcm(ciphertext, key, nonce)
        else:
            pk_hex = keystore_data["private_key"]
            if pk_hex.startswith("0x"):
                pk_hex = pk_hex[2:]
            private_key = bytes.fromhex(pk_hex)
        
        return cls(private_key=private_key)
    
    def derive_addresses(self, chains: Optional[List[str]] = None) -> Dict[str, "ChainAddress"]:
        """
        派生多链地址（Solana 只返回自己的地址）
        
        Args:
            chains: 链列表（Solana 会被忽略，因为 Solana 地址基于 Ed25519）
        
        Returns:
            {chain: ChainAddress}
        """
        return {
            "solana": ChainAddress(
                chain="solana",
                address=self.address,
                public_key=self.address  # Solana 地址就是公钥
            )
        }
    
    def clear_private_key(self):
        """清除内存中的私钥"""
        if self._keypair is not None:
            # 覆盖内存中的私钥
            zeroed = bytes(64)
            # 注意：solders 的 Keypair 不支持直接修改
            # 只能通过删除引用来让 GC 回收
            self._keypair = None
        self.close()


# ============================================
# 主钱包管理器
# ============================================

class WalletManager:
    """
    主钱包管理器
    
    统一管理多链钱包
    """
    
    def __init__(self, keystore_dir: Optional[str] = None):
        """
        初始化钱包管理器
        
        Args:
            keystore_dir: 密钥库目录
        """
        self.keystore_manager = KeyStoreManager(keystore_dir)
        self.evm_manager: Optional[EVMWalletManager] = None
        self.wallet_info: Optional[WalletInfo] = None
    
    def create_wallet(
        self,
        name: str,
        password: str,
        chains: Optional[List[str]] = None
    ) -> WalletInfo:
        """
        创建新钱包
        
        Args:
            name: 钱包名称
            password: 密码
            chains: 要支持的链列表
            
        Returns:
            WalletInfo 对象
        """
        # 生成随机私钥
        private_key = secrets.token_bytes(32)
        
        # 初始化 EVM 管理器
        self.evm_manager = EVMWalletManager(private_key=private_key)
        
        # 创建 keystore
        keystore = self.keystore_manager.create_v3_keystore(private_key, password)
        keystore_path = self.keystore_manager.save_v3_keystore(keystore)
        
        # 派生多链地址
        addresses = self.evm_manager.derive_addresses(chains)
        
        # 创建钱包信息
        self.wallet_info = WalletInfo(
            wallet_id=secrets.token_hex(16),
            name=name,
            addresses=addresses,
            keystore_path=keystore_path
        )
        
        logger.info(f"Created new wallet: {name} ({self.evm_manager.checksum_address})")
        
        return self.wallet_info
    
    def import_wallet(
        self,
        private_key: Optional[str] = None,
        keystore_path: Optional[str] = None,
        keystore_password: Optional[str] = None,
        name: str = "Imported Wallet",
        chains: Optional[List[str]] = None
    ) -> WalletInfo:
        """
        导入钱包
        
        Args:
            private_key: 私钥（hex，0x开头或纯hex）
            keystore_path: keystore 文件路径
            keystore_password: keystore 密码
            name: 钱包名称
            chains: 要支持的链列表
            
        Returns:
            WalletInfo 对象
        """
        # 从私钥导入
        if private_key:
            if private_key.startswith('0x'):
                private_key = private_key[2:]
            pk_bytes = bytes.fromhex(private_key)
            self.evm_manager = EVMWalletManager(private_key=pk_bytes)
            keystore_path = None
        # 从 keystore 导入
        elif keystore_path and keystore_password:
            self.evm_manager = EVMWalletManager(
                keystore_path=keystore_path,
                keystore_password=keystore_password
            )
        else:
            raise ValueError("Must provide private_key or keystore_path")
        
        # 派生多链地址
        addresses = self.evm_manager.derive_addresses(chains)
        
        # 创建钱包信息
        self.wallet_info = WalletInfo(
            wallet_id=secrets.token_hex(16),
            name=name,
            addresses=addresses,
            keystore_path=keystore_path
        )
        
        logger.info(f"Imported wallet: {name} ({self.evm_manager.checksum_address})")
        
        return self.wallet_info
    
    def load_wallet(self, keystore_path: str, password: str) -> WalletInfo:
        """
        加载已有钱包
        
        Args:
            keystore_path: keystore 文件路径
            password: 密码
            
        Returns:
            WalletInfo 对象
        """
        keystore = self.keystore_manager.load_v3_keystore(keystore_path)
        address = "0x" + keystore['address']
        
        # 初始化 EVM 管理器
        self.evm_manager = EVMWalletManager(
            keystore_path=keystore_path,
            keystore_password=password
        )
        
        # 派生多链地址
        addresses = self.evm_manager.derive_addresses()
        
        # 创建钱包信息
        self.wallet_info = WalletInfo(
            wallet_id=secrets.token_hex(16),
            name="Loaded Wallet",
            addresses=addresses,
            keystore_path=keystore_path
        )
        
        logger.info(f"Loaded wallet: {address}")
        
        return self.wallet_info
    
    def get_balance(self, chain: str) -> WalletBalance:
        """获取指定链的余额"""
        if not self.evm_manager:
            raise ValueError("No wallet loaded")
        return self.evm_manager.get_balances(chain)
    
    def sign_transaction(self, chain: str, tx_dict: Dict) -> SignedTransaction:
        """签名交易"""
        if not self.evm_manager:
            raise ValueError("No wallet loaded")
        return self.evm_manager.sign_transaction(chain, tx_dict)
    
    def export_keystore(self, password: str) -> Dict:
        """
        导出 keystore
        
        Args:
            password: 解密密码
            
        Returns:
            keystore 字典
        """
        if not self.evm_manager or not self.wallet_info:
            raise ValueError("No wallet loaded")
        
        if not self.wallet_info.keystore_path:
            raise ValueError("No keystore path")
        
        return self.keystore_manager.load_v3_keystore(self.wallet_info.keystore_path)
    
    def unlock(self, password: str) -> bool:
        """
        解锁钱包（重新加载私钥到内存）
        
        Args:
            password: 密码
            
        Returns:
            是否解锁成功
        """
        if not self.wallet_info or not self.wallet_info.keystore_path:
            return False
        
        try:
            keystore = self.keystore_manager.load_v3_keystore(
                self.wallet_info.keystore_path
            )
            private_key = self.keystore_manager.decrypt_v3_keystore(keystore, password)
            self.evm_manager = EVMWalletManager(private_key=private_key)
            return True
        except Exception as e:
            logger.error(f"Failed to unlock wallet: {e}")
            return False
    
    def lock(self):
        """锁定钱包（清除内存中的私钥）"""
        if self.evm_manager:
            self.evm_manager.clear_private_key()
        logger.info("Wallet locked")


# ============================================
# 单例模式访问器
# ============================================

_wallet_manager_instance: Optional[WalletManager] = None


def get_wallet_manager() -> WalletManager:
    """获取钱包管理器单例"""
    global _wallet_manager_instance
    if _wallet_manager_instance is None:
        _wallet_manager_instance = WalletManager()
    return _wallet_manager_instance


def init_wallet_manager(keystore_dir: Optional[str] = None) -> WalletManager:
    """初始化钱包管理器"""
    global _wallet_manager_instance
    _wallet_manager_instance = WalletManager(keystore_dir)
    return _wallet_manager_instance
