"""字符串加解密服务

基于 AES-256-GCM 对称加密，提供可逆的字符串加密 / 解密能力。

密钥来源（按优先级）：
1. 函数调用时显式传入的 ``key`` 参数
2. 环境变量 ``QXW_STR_ENCRYPT_KEY``
3. 兜底默认值 ``"sbdqf"``

由于用户传入的密钥长度不固定，统一使用 SHA-256 派生出 32 字节 AES 密钥，
因此任意长度的密钥都能被规范化为合法的 AES-256 密钥。

密文格式为 ``base64(nonce || ciphertext || tag)``：
- ``nonce``：12 字节随机数（AES-GCM 标准推荐长度）
- ``ciphertext``：与明文等长的密文
- ``tag``：16 字节认证标签

解密时从同一 base64 串中拆出三段即可，调用方无需单独保存 nonce。
"""

from __future__ import annotations

import base64
import hashlib
import os

from qxw.library.base.exceptions import ValidationError

# 环境变量名与默认密钥
_ENV_KEY_NAME = "QXW_STR_ENCRYPT_KEY"
_DEFAULT_KEY = "sbdqf"

# AES-GCM 参数
_NONCE_LEN = 12  # bytes，AES-GCM 推荐 96-bit nonce
_TAG_LEN = 16  # bytes，AES-GCM 认证标签长度


def _load_key(explicit: str | None) -> bytes:
    """加载并派生 AES-256 密钥

    :param explicit: 调用方显式传入的密钥；为 ``None`` 时读取环境变量，
        环境变量缺失或为空串时回落到默认值 ``"sbdqf"``。
    :return: 32 字节 AES-256 密钥（SHA-256 派生）
    """
    raw = explicit if explicit is not None else os.environ.get(_ENV_KEY_NAME, _DEFAULT_KEY)
    # 环境变量被显式置空时也回落到默认值，避免空串导致行为不可预期
    if raw is None or raw == "":
        raw = _DEFAULT_KEY
    return hashlib.sha256(raw.encode("utf-8")).digest()


def encrypt(plaintext: str, key: str | None = None) -> str:
    """对字符串进行 AES-256-GCM 加密

    :param plaintext: 待加密的明文（UTF-8 编码）
    :param key: 可选密钥；为 ``None`` 时读取 ``QXW_STR_ENCRYPT_KEY`` 环境变量
    :raises ValidationError: 明文不是字符串
    :return: base64 编码的密文串（含 nonce 与认证标签）
    """
    if not isinstance(plaintext, str):
        raise ValidationError(f"待加密的明文必须是字符串，实际类型: {type(plaintext).__name__}")
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError as e:  # pragma: no cover - cryptography 是硬依赖，正常不会触发
        raise ValidationError("缺少 cryptography 依赖，请先安装: pip install cryptography") from e

    aes_key = _load_key(key)
    nonce = os.urandom(_NONCE_LEN)
    aesgcm = AESGCM(aes_key)
    # AESGCM.encrypt 返回 ciphertext || tag，tag 固定 16 字节
    ct_and_tag = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    blob = nonce + ct_and_tag
    return base64.b64encode(blob).decode("ascii")


def decrypt(ciphertext: str, key: str | None = None) -> str:
    """对 base64 密文串进行 AES-256-GCM 解密

    :param ciphertext: ``encrypt`` 产出的 base64 密文串
    :param key: 可选密钥；为 ``None`` 时读取 ``QXW_STR_ENCRYPT_KEY`` 环境变量
    :raises ValidationError: 密文不是字符串、base64 非法、长度不足、密钥不匹配、
        标签校验失败（被篡改）等
    :return: 解密后的明文
    """
    if not isinstance(ciphertext, str):
        raise ValidationError(f"待解密的密文必须是字符串，实际类型: {type(ciphertext).__name__}")
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError as e:  # pragma: no cover - cryptography 是硬依赖，正常不会触发
        raise ValidationError("缺少 cryptography 依赖，请先安装: pip install cryptography") from e

    # 去掉复制粘贴常见的外部空白，再严格校验 base64
    stripped = ciphertext.strip()
    if stripped == "":
        raise ValidationError("密文不能为空")
    try:
        blob = base64.b64decode(stripped, validate=True)
    except (base64.binascii.Error, ValueError) as e:
        raise ValidationError(f"密文不是合法的 base64: {e}") from e

    if len(blob) < _NONCE_LEN + _TAG_LEN:
        raise ValidationError(f"密文长度不足，至少需要 {_NONCE_LEN + _TAG_LEN} 字节，实际 {len(blob)} 字节")
    nonce = blob[:_NONCE_LEN]
    ct_and_tag = blob[_NONCE_LEN:]

    aes_key = _load_key(key)
    aesgcm = AESGCM(aes_key)
    try:
        plaintext = aesgcm.decrypt(nonce, ct_and_tag, None)
    except Exception as e:
        # InvalidTag / 密钥不匹配等都统一映射为用户可读的校验错误
        raise ValidationError(f"解密失败，密钥不匹配或密文已被篡改: {e}") from e
    try:
        return plaintext.decode("utf-8")
    except UnicodeDecodeError as e:
        # 密钥正确但解出的字节不是合法 UTF-8（理论罕见，但仍需兜底）
        raise ValidationError("解密后的数据不是合法的 UTF-8 字符串") from e
