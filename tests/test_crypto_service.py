"""crypto_service 单元测试

遵循 CLAUDE.md 的 "0 happy test, 0 happy path" 原则：
- 不写"加密再解密能还原"这种仅验证主流程的用例
- 重点覆盖异常、边界、密钥来源差异、密文篡改、非法输入等错误分支
- 仅保留少量往返锚点用于证明加解密是同一套算法
"""

from __future__ import annotations

import base64

import pytest

from qxw.library.base.exceptions import ValidationError
from qxw.library.services import crypto_service
from qxw.library.services.crypto_service import decrypt, encrypt

# ============================================================
# 密钥来源 / _load_key
# ============================================================


class TestLoadKey:
    def test_显式参数优先于环境变量(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("QXW_STR_ENCRYPT_KEY", "env_value")
        k1 = crypto_service._load_key("explicit_value")
        k2 = crypto_service._load_key(None)
        assert k1 != k2
        # 显式参数应该与"explicit_value"的 SHA-256 一致
        import hashlib

        assert k1 == hashlib.sha256(b"explicit_value").digest()

    def test_环境变量优先于默认值(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("QXW_STR_ENCRYPT_KEY", "env_value")
        k = crypto_service._load_key(None)
        import hashlib

        assert k == hashlib.sha256(b"env_value").digest()

    def test_无环境变量回退默认_sbdqf(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("QXW_STR_ENCRYPT_KEY", raising=False)
        k = crypto_service._load_key(None)
        import hashlib

        assert k == hashlib.sha256(b"sbdqf").digest()

    def test_空环境变量也回退默认值(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # 空串环境变量与缺失语义一致，避免空串导致不可预期行为
        monkeypatch.setenv("QXW_STR_ENCRYPT_KEY", "")
        k = crypto_service._load_key(None)
        import hashlib

        assert k == hashlib.sha256(b"sbdqf").digest()

    def test_空显式参数也回退默认值(self) -> None:
        k = crypto_service._load_key("")
        import hashlib

        assert k == hashlib.sha256(b"sbdqf").digest()

    def test_密钥始终是_32_字节(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for case in (None, "x", "a" * 100, "中文密钥🔑"):
            k = crypto_service._load_key(case)
            assert len(k) == 32
        monkeypatch.setenv("QXW_STR_ENCRYPT_KEY", "env")
        assert len(crypto_service._load_key(None)) == 32


# ============================================================
# encrypt 输入校验
# ============================================================


class TestEncryptInput:
    def test_非字符串明文_抛出_ValidationError(self) -> None:
        with pytest.raises(ValidationError, match="必须是字符串"):
            encrypt(123)  # type: ignore[arg-type]

    def test_None_明文_抛出_ValidationError(self) -> None:
        with pytest.raises(ValidationError, match="必须是字符串"):
            encrypt(None)  # type: ignore[arg-type]

    def test_空字符串明文可加密(self) -> None:
        # 空串是合法边界，加密应产出非空密文（nonce + tag 至少 28 字节 base64）
        ct = encrypt("")
        assert ct != ""
        assert len(ct) > 0


# ============================================================
# decrypt 输入校验
# ============================================================


class TestDecryptInput:
    def test_非字符串密文_抛出_ValidationError(self) -> None:
        with pytest.raises(ValidationError, match="必须是字符串"):
            decrypt(123)  # type: ignore[arg-type]

    def test_None_密文_抛出_ValidationError(self) -> None:
        with pytest.raises(ValidationError, match="必须是字符串"):
            decrypt(None)  # type: ignore[arg-type]

    def test_空字符串密文_抛出_ValidationError(self) -> None:
        with pytest.raises(ValidationError, match="不能为空"):
            decrypt("")

    def test_纯空白密文_抛出_ValidationError(self) -> None:
        with pytest.raises(ValidationError, match="不能为空"):
            decrypt("   \t\n  ")

    def test_非法base64_抛出_ValidationError(self) -> None:
        # 包含 base64 不接受的字符
        with pytest.raises(ValidationError, match="不是合法的 base64"):
            decrypt("!!!不是base64!!!")

    def test_base64长度不足_抛出_ValidationError(self) -> None:
        # nonce(12) + tag(16) = 28 字节是下限；构造恰好 10 字节的 blob
        short_blob = base64.b64encode(b"\x00" * 10).decode("ascii")
        with pytest.raises(ValidationError, match="长度不足"):
            decrypt(short_blob)

    def test_base64恰好_28_字节但内容非法_抛出_ValidationError(self) -> None:
        # 长度达标但 tag 校验必然失败
        blob = base64.b64encode(b"\x00" * 28).decode("ascii")
        with pytest.raises(ValidationError, match="解密失败|密钥不匹配|篡改"):
            decrypt(blob)


# ============================================================
# 密钥不匹配 / 篡改
# ============================================================


class TestKeyMismatchAndTamper:
    def test_密钥不匹配解密失败(self) -> None:
        ct = encrypt("secret", key="key_a")
        with pytest.raises(ValidationError, match="解密失败|密钥不匹配|篡改"):
            decrypt(ct, key="key_b")

    def test_环境变量密钥与默认密钥不同时无法互通(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # 用默认密钥加密
        monkeypatch.delenv("QXW_STR_ENCRYPT_KEY", raising=False)
        ct = encrypt("secret")
        # 切换环境变量后解密应失败
        monkeypatch.setenv("QXW_STR_ENCRYPT_KEY", "another_key")
        with pytest.raises(ValidationError, match="解密失败|密钥不匹配|篡改"):
            decrypt(ct)

    def test_篡改密文字节_认证标签失败(self) -> None:
        ct = encrypt("hello world long enough", key="k")
        # 解码后翻转 ciphertext 区域的一个字节（nonce=12 之后），再重新编码
        # 这样 base64 仍合法，但 GCM 认证标签必然校验失败
        blob = bytearray(base64.b64decode(ct))
        blob[13] ^= 0xFF
        tampered = base64.b64encode(bytes(blob)).decode("ascii")
        with pytest.raises(ValidationError, match="解密失败|密钥不匹配|篡改"):
            decrypt(tampered, key="k")

    def test_篡改nonce前缀_认证标签失败(self) -> None:
        # 直接构造一个合法长度的 base64 但 nonce 被改
        import os as _os

        blob = _os.urandom(12) + b"padding_to_reach_min_length!!"  # 12 + 28 = 40 bytes
        ct = base64.b64encode(blob).decode("ascii")
        with pytest.raises(ValidationError, match="解密失败|密钥不匹配|篡改"):
            decrypt(ct, key="k")


# ============================================================
# 往返锚点（仅证明加解密是同一套算法，不算 happy path 覆盖）
# ============================================================


class TestRoundtripAnchors:
    @pytest.mark.parametrize(
        "plaintext",
        ["a", "hello world", "你好，世界🔑", "x" * 1000, ""],
    )
    def test_往返一致性锚点(self, plaintext: str) -> None:
        ct = encrypt(plaintext, key="anchor_key")
        assert decrypt(ct, key="anchor_key") == plaintext

    def test_同一明文多次加密密文不同(self) -> None:
        # nonce 随机，相同明文应产生不同密文
        ct1 = encrypt("same", key="k")
        ct2 = encrypt("same", key="k")
        assert ct1 != ct2
        # 但都能解回同一明文
        assert decrypt(ct1, key="k") == "same"
        assert decrypt(ct2, key="k") == "same"

    def test_密文是合法base64且可解码(self) -> None:
        ct = encrypt("hello", key="k")
        # 不抛异常即说明是合法 base64
        decoded = base64.b64decode(ct, validate=True)
        # nonce(12) + 至少 0 字节密文 + tag(16) >= 28
        assert len(decoded) >= 28
