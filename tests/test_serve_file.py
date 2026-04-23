"""qxw.library.services.serve_file 单元测试

覆盖：
- generate_password / AuthConfig / FileWebServerConfig
- _human_size / _build_breadcrumb
- _FileWebHandler._check_auth / _require_auth / _resolve_path / send_error
- do_GET 的 403/404 分支、目录重定向、ZIP 下载分支
"""

from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest

from qxw.library.services import serve_file as sf
from qxw.library.services.serve_file import (
    AuthConfig,
    FileWebServerConfig,
    _build_breadcrumb,
    _FileWebHandler,
    _human_size,
    generate_password,
)


class TestGeneratePassword:
    def test_默认_12_位(self) -> None:
        pw = generate_password()
        assert len(pw) == 12
        assert pw.isalnum()

    def test_自定义长度(self) -> None:
        assert len(generate_password(20)) == 20

    def test_长度为_0(self) -> None:
        assert generate_password(0) == ""


class TestHumanSize:
    def test_B(self) -> None:
        assert _human_size(100) == "100 B"

    def test_KB(self) -> None:
        assert _human_size(1024) == "1.0 KB"

    def test_大于_PB(self) -> None:
        assert "PB" in _human_size(1024**5 * 10)


class TestBuildBreadcrumb:
    def test_根路径(self) -> None:
        out = _build_breadcrumb("/")
        assert "根目录" in out
        assert "/" in out

    def test_空路径(self) -> None:
        out = _build_breadcrumb("")
        assert "根目录" in out

    def test_多级(self) -> None:
        out = _build_breadcrumb("/a/b/c/")
        # 每级都有链接
        assert "a" in out and "b" in out and "c" in out
        assert out.count("<a") >= 4

    def test_特殊字符被_URL_编码(self) -> None:
        out = _build_breadcrumb("/中文/")
        assert "%E4%B8%AD%E6%96%87" in out


class TestAuthConfig:
    def test_默认自动生成密码(self) -> None:
        cfg1 = AuthConfig()
        cfg2 = AuthConfig()
        assert len(cfg1.password) == 12
        assert cfg1.password != cfg2.password  # 每次不同

    def test_显式密码(self) -> None:
        cfg = AuthConfig(username="u", password="secret")
        assert cfg.username == "u"
        assert cfg.password == "secret"


class TestFileWebServerConfig:
    def test_必填字段缺失抛错(self) -> None:
        with pytest.raises(Exception):
            FileWebServerConfig()  # type: ignore[call-arg]

    def test_基本构造(self, tmp_path: Path) -> None:
        cfg = FileWebServerConfig(
            directory=tmp_path,
            port=8000,
            auth=AuthConfig(username="u", password="p"),
        )
        assert cfg.host == "0.0.0.0"
        assert cfg.port == 8000
        assert cfg.writable is False


# ------------------------------------------------------------------
# Handler 分支测试
# ------------------------------------------------------------------


class _FakeRequest:
    """模拟 BaseHTTPRequestHandler 需要的 request 最小接口"""

    def makefile(self, mode: str, *a: Any, **k: Any) -> BytesIO:
        return BytesIO()


class _BuiltHandler(_FileWebHandler):
    """跳过 socket 握手的测试用 handler"""

    def __init__(self, config: FileWebServerConfig, headers: dict[str, str] | None = None) -> None:
        self.config = config
        self.path = "/"
        self.headers = _Headers(headers or {})
        self.rfile = BytesIO()
        self.wfile = BytesIO()
        self.responses = {
            200: ("OK", ""),
            301: ("Moved", ""),
            401: ("Unauthorized", ""),
            403: ("Forbidden", ""),
            404: ("Not Found", ""),
            500: ("Server Error", ""),
        }
        self._response_log: list[tuple[int, str | None]] = []
        self._headers_sent: list[tuple[str, str]] = []

    # 替换 BaseHTTPRequestHandler 的响应方法以便断言
    def send_response(self, code: int, message: str | None = None) -> None:  # type: ignore[override]
        self._response_log.append((code, message))

    def send_header(self, name: str, value: str) -> None:  # type: ignore[override]
        self._headers_sent.append((name, value))

    def end_headers(self) -> None:  # type: ignore[override]
        return None


class _Headers(dict):
    def get(self, key: str, default=None):
        # BaseHTTPRequestHandler 会用 .get；我们直接 dict.get
        return super().get(key, default)


@pytest.fixture()
def handler(tmp_path: Path) -> _BuiltHandler:
    cfg = FileWebServerConfig(
        directory=tmp_path,
        port=1,
        auth=AuthConfig(username="user", password="pass"),
    )
    return _BuiltHandler(cfg)


def _basic(user: str, pw: str) -> str:
    return "Basic " + base64.b64encode(f"{user}:{pw}".encode()).decode()


class TestCheckAuth:
    def test_无_Authorization_失败(self, handler: _BuiltHandler) -> None:
        assert handler._check_auth() is False

    def test_非_Basic_方案失败(self, handler: _BuiltHandler) -> None:
        handler.headers["Authorization"] = "Bearer token"
        assert handler._check_auth() is False

    def test_Basic_凭证无效_返回_False(self, handler: _BuiltHandler) -> None:
        handler.headers["Authorization"] = _basic("user", "wrong")
        assert handler._check_auth() is False

    def test_Basic_凭证格式错误_返回_False(self, handler: _BuiltHandler) -> None:
        handler.headers["Authorization"] = "Basic !!!"
        assert handler._check_auth() is False

    def test_凭证正确_返回_True(self, handler: _BuiltHandler) -> None:
        handler.headers["Authorization"] = _basic("user", "pass")
        assert handler._check_auth() is True


class TestRequireAuth:
    def test_失败时发送_401(self, handler: _BuiltHandler) -> None:
        ok = handler._require_auth()
        assert ok is False
        assert 401 in [c for c, _ in handler._response_log]
        assert any(name == "WWW-Authenticate" for name, _ in handler._headers_sent)


class TestResolvePath:
    def test_路径穿越被拒绝(self, handler: _BuiltHandler) -> None:
        assert handler._resolve_path("/../../etc/passwd") is None

    def test_正常相对路径(self, handler: _BuiltHandler, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("x")
        resolved = handler._resolve_path("/a.txt")
        assert resolved == (tmp_path / "a.txt").resolve()


class TestDoGet:
    def test_未鉴权_返回_401(self, handler: _BuiltHandler) -> None:
        handler.path = "/"
        handler.do_GET()
        assert handler._response_log[0][0] == 401

    def test_路径穿越_返回_403(self, handler: _BuiltHandler) -> None:
        handler.headers["Authorization"] = _basic("user", "pass")
        handler.path = "/../../etc"
        handler.do_GET()
        codes = [c for c, _ in handler._response_log]
        assert 403 in codes

    def test_文件不存在_返回_404(self, handler: _BuiltHandler) -> None:
        handler.headers["Authorization"] = _basic("user", "pass")
        handler.path = "/nope.txt"
        handler.do_GET()
        codes = [c for c, _ in handler._response_log]
        assert 404 in codes

    def test_目录无斜杠_301_重定向(
        self, handler: _BuiltHandler, tmp_path: Path
    ) -> None:
        (tmp_path / "sub").mkdir()
        handler.headers["Authorization"] = _basic("user", "pass")
        handler.path = "/sub"
        handler.do_GET()
        codes = [c for c, _ in handler._response_log]
        assert 301 in codes

    def test_zip_下载普通文件_走_attachment(
        self, handler: _BuiltHandler, tmp_path: Path
    ) -> None:
        f = tmp_path / "a.txt"
        f.write_text("hello")
        handler.headers["Authorization"] = _basic("user", "pass")
        handler.path = "/a.txt?dl=1"
        handler.do_GET()
        codes = [c for c, _ in handler._response_log]
        assert 200 in codes

    def test_zip_打包目录(self, handler: _BuiltHandler, tmp_path: Path) -> None:
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "a.txt").write_text("hi")
        handler.headers["Authorization"] = _basic("user", "pass")
        handler.path = "/sub/?dl=zip"
        handler.do_GET()
        codes = [c for c, _ in handler._response_log]
        assert 200 in codes
        # 应带 zip content-type
        assert any(name == "Content-Type" and "zip" in value for name, value in handler._headers_sent)


class TestStartServer:
    def test_端口被占用_抛_OSError(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # 通过 mock HTTPServer 直接抛出 OSError
        from qxw.library.services import serve_file as mod

        def boom(*a, **k):
            raise OSError("port in use")

        monkeypatch.setattr(mod, "HTTPServer", boom)

        cfg = FileWebServerConfig(
            directory=tmp_path,
            port=1,
            auth=AuthConfig(username="u", password="p"),
        )
        with pytest.raises(OSError):
            sf.start_server(cfg)
