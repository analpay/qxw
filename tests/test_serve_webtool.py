"""qxw.library.services.serve_webtool 单元测试

重点：纯函数 API 的错误分支 + handler do_POST/do_GET 路由分支。
"""

from __future__ import annotations

import json
from io import BytesIO

import pytest

from qxw.library.services import serve_webtool as sw
from qxw.library.services.serve_webtool import (
    WebtoolServerConfig,
    _aes_process,
    _base64_process,
    _build_routes,
    _cert_parse,
    _des_process,
    _hash_text,
    _hmac_text,
    _json_format,
    _text_diff,
    _timestamp_convert,
    _url_process,
    _WebtoolHandler,
)


class TestTextDiff:
    def test_完全相同(self) -> None:
        assert "相同" in _text_diff("abc\n", "abc\n")

    def test_不同时生成_diff(self) -> None:
        out = _text_diff("a\nb\n", "a\nc\n")
        assert "-b" in out or "b" in out
        assert "+c" in out or "c" in out


class TestJsonFormat:
    def test_format(self) -> None:
        out = _json_format('{"a":1}', "format")
        assert "\n" in out

    def test_minify(self) -> None:
        out = _json_format('{"a": 1}', "minify")
        assert out == '{"a":1}'

    def test_validate(self) -> None:
        assert "正确" in _json_format("[]", "validate")

    def test_escape_非法_JSON_抛错(self) -> None:
        with pytest.raises(json.JSONDecodeError):
            _json_format("not json", "escape")

    def test_unescape_非字符串原样返回(self) -> None:
        # [1,2,3] 反转义后是 list，不是 str，按原文返回
        assert _json_format("[1,2,3]", "unescape") == "[1,2,3]"

    def test_unescape_字符串_返回原串(self) -> None:
        # "\"abc\"" 反转义后就是 abc
        assert _json_format('"abc"', "unescape") == "abc"

    def test_未知_action_抛错(self) -> None:
        with pytest.raises(ValueError, match="未知操作"):
            _json_format('{"a":1}', "xxx")

    def test_非法_JSON_抛错(self) -> None:
        with pytest.raises(json.JSONDecodeError):
            _json_format("{", "format")


class TestTimestampConvert:
    def test_now(self) -> None:
        out = _timestamp_convert("", "now")
        assert "秒级时间戳" in out

    def test_to_datetime_秒级(self) -> None:
        out = _timestamp_convert("0", "to_datetime")
        assert "1970" in out["UTC 时间"]

    def test_to_datetime_毫秒级(self) -> None:
        out = _timestamp_convert(str(1_700_000_000_000), "to_datetime")
        assert "秒级时间戳" in out
        assert out["秒级时间戳"] == 1_700_000_000

    def test_to_timestamp_支持多种格式(self) -> None:
        assert _timestamp_convert("2024-01-01 12:34:56", "to_timestamp")["秒级时间戳"] > 0
        assert _timestamp_convert("2024-01-01", "to_timestamp")["秒级时间戳"] > 0

    def test_to_timestamp_非法格式_抛_ValueError(self) -> None:
        with pytest.raises(ValueError, match="无法解析"):
            _timestamp_convert("not a date", "to_timestamp")

    def test_未知_action(self) -> None:
        with pytest.raises(ValueError, match="未知操作"):
            _timestamp_convert("", "xxx")


class TestHash:
    def test_md5(self) -> None:
        assert _hash_text("hello", "md5") == "5d41402abc4b2a76b9719d911017c592"

    def test_不支持的算法(self) -> None:
        with pytest.raises(ValueError, match="不支持"):
            _hash_text("x", "blake2")


class TestHmac:
    def test_sha256(self) -> None:
        out = _hmac_text("msg", "key", "hmac-sha256")
        assert len(out) == 64

    def test_不支持的算法(self) -> None:
        with pytest.raises(ValueError, match="不支持"):
            _hmac_text("x", "k", "hmac-md5")

    def test_空密钥(self) -> None:
        with pytest.raises(ValueError, match="密钥"):
            _hmac_text("msg", "", "hmac-sha256")


class TestUrlProcess:
    def test_encode(self) -> None:
        assert _url_process("a b/c", "encode") == "a%20b%2Fc"

    def test_decode(self) -> None:
        assert _url_process("a%20b", "decode") == "a b"

    def test_未知_action(self) -> None:
        with pytest.raises(ValueError, match="未知操作"):
            _url_process("x", "xxx")


class TestBase64Process:
    def test_encode_decode_往返(self) -> None:
        enc = _base64_process("hello", "encode")
        assert _base64_process(enc, "decode") == "hello"

    def test_未知_action(self) -> None:
        with pytest.raises(ValueError, match="未知操作"):
            _base64_process("x", "xxx")

    def test_非法_base64_解码为非_UTF8(self) -> None:
        # 合法 base64 但解出来不是合法 UTF-8 时 decode 抛 UnicodeDecodeError
        import base64 as b64
        non_utf8 = b64.b64encode(b"\xff\xfe").decode()
        with pytest.raises(UnicodeDecodeError):
            _base64_process(non_utf8, "decode")


class TestAesProcess:
    def _key_hex(self) -> str:
        return "00" * 32

    def _iv_hex(self) -> str:
        return "00" * 16

    def test_cbc_往返(self) -> None:
        enc = _aes_process("hello", self._key_hex(), self._iv_hex(), "cbc", "encrypt")
        assert _aes_process(enc, self._key_hex(), "", "cbc", "decrypt") == "hello"

    def test_ecb_往返(self) -> None:
        enc = _aes_process("hi", self._key_hex(), "", "ecb", "encrypt")
        assert _aes_process(enc, self._key_hex(), "", "ecb", "decrypt") == "hi"

    def test_密钥长度非法(self) -> None:
        with pytest.raises(ValueError, match="密钥长度"):
            _aes_process("x", "1234", "", "cbc", "encrypt")

    def test_CBC_IV_长度非法(self) -> None:
        with pytest.raises(ValueError, match="IV"):
            _aes_process("x", self._key_hex(), "00" * 8, "cbc", "encrypt")

    def test_未知_action(self) -> None:
        with pytest.raises(ValueError, match="未知操作"):
            _aes_process("x", self._key_hex(), "", "cbc", "xxx")


class TestDesProcess:
    def test_DES_往返(self) -> None:
        key = "00" * 8
        enc = _des_process("abc", key, "", "encrypt", triple=False)
        assert _des_process(enc, key, "", "decrypt", triple=False) == "abc"

    def test_3DES_密钥长度错(self) -> None:
        with pytest.raises(ValueError, match="3DES"):
            _des_process("x", "00" * 8, "", "encrypt", triple=True)

    def test_DES_密钥长度错(self) -> None:
        with pytest.raises(ValueError, match="DES"):
            _des_process("x", "00" * 4, "", "encrypt", triple=False)

    def test_DES_IV_长度错(self) -> None:
        with pytest.raises(ValueError, match="IV"):
            _des_process("x", "00" * 8, "00" * 4, "encrypt", triple=False)

    def test_未知_action(self) -> None:
        with pytest.raises(ValueError, match="未知操作"):
            _des_process("x", "00" * 8, "", "xxx", triple=False)


class TestRsaProcess:
    def test_generate_返回_PEM_对(self) -> None:
        res = sw._rsa_process("generate", key_size=2048)
        assert "BEGIN" in res["private_key"]
        assert "BEGIN" in res["public_key"]

    def test_encrypt_decrypt_往返(self) -> None:
        res = sw._rsa_process("generate", key_size=2048)
        enc = sw._rsa_process("encrypt", public_key=res["public_key"], data="hi")
        dec = sw._rsa_process("decrypt", private_key=res["private_key"], data=enc["result"])
        assert dec["result"] == "hi"

    def test_未知_action(self) -> None:
        with pytest.raises(ValueError, match="未知操作"):
            sw._rsa_process("xxx")


class TestEd25519Process:
    def test_signverify(self) -> None:
        keys = sw._ed25519_process("generate")
        sig = sw._ed25519_process("sign", private_key=keys["private_key"], data="hi")
        ok = sw._ed25519_process(
            "verify", public_key=keys["public_key"], data="hi", signature=sig["signature"]
        )
        assert ok["valid"] is True

    def test_verify_失败返回_False(self) -> None:
        keys = sw._ed25519_process("generate")
        ok = sw._ed25519_process(
            "verify",
            public_key=keys["public_key"],
            data="hi",
            signature="YWJjZA==",  # 无效签名
        )
        assert ok["valid"] is False

    def test_未知_action(self) -> None:
        with pytest.raises(ValueError, match="未知操作"):
            sw._ed25519_process("xxx")


class TestCertParse:
    def test_非法_PEM_抛错(self) -> None:
        with pytest.raises(Exception):
            _cert_parse("-----BEGIN CERTIFICATE-----\nnotacert\n-----END CERTIFICATE-----\n")

    def test_非_PEM_输入被当作_DER_base64_解析(self) -> None:
        with pytest.raises(Exception):
            _cert_parse("notbase64!!!")


class TestBuildRoutes:
    def test_路由完整(self) -> None:
        routes = _build_routes()
        for path in [
            "/api/diff", "/api/json", "/api/timestamp", "/api/hash", "/api/hmac",
            "/api/aes", "/api/des", "/api/3des", "/api/rsa", "/api/ed25519",
            "/api/cert", "/api/url", "/api/base64",
        ]:
            assert path in routes


# ------------------------------------------------------------------
# Handler
# ------------------------------------------------------------------


class _H(_WebtoolHandler):
    def __init__(self, body: bytes = b"", path: str = "/", headers: dict | None = None) -> None:
        # 绕过 socket 初始化
        self.rfile = BytesIO(body)
        self.wfile = BytesIO()
        self.path = path
        self.headers = _Hdr(headers or {"Content-Length": str(len(body))})
        self._codes: list[int] = []
        self._headers_out: list[tuple[str, str]] = []

    def send_response(self, code: int, message: str | None = None) -> None:  # type: ignore[override]
        self._codes.append(code)

    def send_error(self, code, message=None, explain=None) -> None:  # type: ignore[override]
        self._codes.append(code)

    def send_header(self, name: str, value: str) -> None:  # type: ignore[override]
        self._headers_out.append((name, value))

    def end_headers(self) -> None:  # type: ignore[override]
        return None


class _Hdr(dict):
    def get(self, key, default=None):
        return super().get(key, default)


class TestDoGet:
    def test_根路径_返回_html(self) -> None:
        _WebtoolHandler._page_html = "<html>x</html>"
        h = _H(path="/")
        h.do_GET()
        assert 200 in h._codes

    def test_favicon_204(self) -> None:
        h = _H(path="/favicon.ico")
        h.do_GET()
        assert 204 in h._codes

    def test_未知路径_404(self) -> None:
        h = _H(path="/nope")
        h.do_GET()
        assert 404 in h._codes


class TestDoPost:
    def test_非法_JSON_400(self) -> None:
        _WebtoolHandler._routes = _build_routes()
        body = b"{invalid"
        h = _H(body=body, path="/api/hash")
        h.do_POST()
        assert 400 in h._codes
        body_out = h.wfile.getvalue().decode("utf-8")
        assert "无效的 JSON" in body_out

    def test_未知_API_404(self) -> None:
        _WebtoolHandler._routes = _build_routes()
        body = json.dumps({}).encode("utf-8")
        h = _H(body=body, path="/api/nope")
        h.do_POST()
        assert 404 in h._codes

    def test_处理器抛异常_400_带_error(self) -> None:
        _WebtoolHandler._routes = _build_routes()
        # hash 传无效算法走 ValueError
        body = json.dumps({"text": "x", "algorithm": "not_algo"}).encode("utf-8")
        h = _H(body=body, path="/api/hash")
        h.do_POST()
        assert 400 in h._codes
        out = json.loads(h.wfile.getvalue().decode("utf-8"))
        assert "error" in out

    def test_正常请求_200(self) -> None:
        _WebtoolHandler._routes = _build_routes()
        body = json.dumps({"text": "hello", "algorithm": "md5"}).encode("utf-8")
        h = _H(body=body, path="/api/hash")
        h.do_POST()
        assert 200 in h._codes
        out = json.loads(h.wfile.getvalue().decode("utf-8"))
        assert out["result"].endswith("17c592")


class TestWebtoolServerConfig:
    def test_默认值(self) -> None:
        cfg = WebtoolServerConfig()
        assert cfg.host == "127.0.0.1"
        assert cfg.port == 9000
