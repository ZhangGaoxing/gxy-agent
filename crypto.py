"""工学云 API 加密工具模块。

AES-128-ECB-PKCS5 加密，MD5 签名（与工学云 App 源码保持一致）。
"""
import binascii
import hashlib
import time

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad

_AES_KEY = b'23DbtQHR2UMbH6mJ'
_SIGN_SALT = '3478cbbc33f84bd00d75d7dfa69e0daa'


def aes_encrypt(text: str) -> str:
    """AES-128-ECB 加密，返回大写十六进制字符串（32字符）。"""
    cipher = AES.new(_AES_KEY, AES.MODE_ECB)
    encrypted = cipher.encrypt(pad(text.encode('utf-8'), AES.block_size))
    return binascii.hexlify(encrypted).decode('ascii').upper()


def make_sign(*args) -> str:
    """MD5 签名：将所有参数拼接后加盐，返回 MD5 hex 字符串。"""
    raw = ''.join(str(a) for a in args) + _SIGN_SALT
    return hashlib.md5(raw.encode('utf-8')).hexdigest()


def make_t() -> str:
    """生成 API 请求所需的 t 参数（当前毫秒时间戳的 AES 加密结果）。"""
    return aes_encrypt(str(int(time.time() * 1000)))
