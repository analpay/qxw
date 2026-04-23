"""qxw.library.services.serve_image 单元测试

覆盖：
- ImageServerConfig 默认值
- _ImageServerHandler 的 do_GET 路由分发
- 缩略图/原图/视频接口的路径越权、文件不存在、不存在扩展名等错误分支
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest

from qxw.library.services import serve_image as si
from qxw.library.services.image_service import ImageEntry
from qxw.library.services.serve_image import ImageServerConfig, _ImageServerHandler


class _H(_ImageServerHandler):
    def __init__(self, config: ImageServerConfig, images: list) -> None:
        self.config = config
        self.images = images
        self.path = "/"
        self.rfile = BytesIO()
        self.wfile = BytesIO()
        self._codes: list[int] = []
        self._headers_out: list[tuple[str, str]] = []

    def send_response(self, code: int, message: str | None = None) -> None:  # type: ignore[override]
        self._codes.append(code)

    def send_header(self, name: str, value: str) -> None:  # type: ignore[override]
        self._headers_out.append((name, value))

    def end_headers(self) -> None:  # type: ignore[override]
        return None


class TestImageServerConfig:
    def test_默认值(self, tmp_path: Path) -> None:
        cfg = ImageServerConfig(directory=tmp_path)
        assert cfg.host == "127.0.0.1"
        assert cfg.port == 8080
        assert cfg.thumb_size == 400


class TestDoGet:
    def _cfg(self, tmp_path: Path) -> ImageServerConfig:
        return ImageServerConfig(directory=tmp_path, host="127.0.0.1", port=0)

    def test_未知路径_404(self, tmp_path: Path) -> None:
        h = _H(self._cfg(tmp_path), [])
        h.path = "/api/nope"
        h.do_GET()
        assert 404 in h._codes

    def test_根路径_渲染_画廊(self, tmp_path: Path) -> None:
        h = _H(self._cfg(tmp_path), [])
        h.path = "/"
        h.do_GET()
        assert 200 in h._codes

    def test_空图片时画廊有_empty_提示(self, tmp_path: Path) -> None:
        h = _H(self._cfg(tmp_path), [])
        h.path = "/"
        h.do_GET()
        body = h.wfile.getvalue().decode("utf-8")
        assert "未找到图片" in body

    def test_带图片时显示_card(self, tmp_path: Path) -> None:
        (tmp_path / "a.jpg").write_bytes(b"x")
        img = ImageEntry(
            path=tmp_path / "a.jpg", rel_path="a.jpg", name="a.jpg", size=1, is_raw=False
        )
        h = _H(self._cfg(tmp_path), [img])
        h.path = "/"
        h.do_GET()
        body = h.wfile.getvalue().decode("utf-8")
        assert "a.jpg" in body


class TestResolveSafePath:
    def test_越权_返回_None(self, tmp_path: Path) -> None:
        cfg = ImageServerConfig(directory=tmp_path, port=0)
        h = _H(cfg, [])
        assert h._resolve_safe_path("../secret") is None

    def test_不存在_返回_None(self, tmp_path: Path) -> None:
        cfg = ImageServerConfig(directory=tmp_path, port=0)
        h = _H(cfg, [])
        assert h._resolve_safe_path("nope.jpg") is None

    def test_是目录而非文件_返回_None(self, tmp_path: Path) -> None:
        sub = tmp_path / "sub"
        sub.mkdir()
        cfg = ImageServerConfig(directory=tmp_path, port=0)
        h = _H(cfg, [])
        assert h._resolve_safe_path("sub") is None


class TestServeThumbnail:
    def test_文件不存在_404(self, tmp_path: Path) -> None:
        cfg = ImageServerConfig(directory=tmp_path, port=0)
        h = _H(cfg, [])
        h._serve_thumbnail("nope.jpg")
        assert 404 in h._codes

    def test_生成失败_500(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        (tmp_path / "a.jpg").write_bytes(b"x")

        import qxw.library.services.image_service as isvc_mod

        monkeypatch.setattr(isvc_mod, "generate_thumbnail", lambda *a, **k: False)

        cfg = ImageServerConfig(directory=tmp_path, port=0)
        h = _H(cfg, [])
        h._serve_thumbnail("a.jpg")
        assert 500 in h._codes


class TestServeViewable:
    def test_不存在_404(self, tmp_path: Path) -> None:
        cfg = ImageServerConfig(directory=tmp_path, port=0)
        h = _H(cfg, [])
        h._serve_viewable("nope.jpg")
        assert 404 in h._codes

    def test_无法显示_500(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        (tmp_path / "a.heic").write_bytes(b"x")

        import qxw.library.services.image_service as isvc_mod

        monkeypatch.setattr(isvc_mod, "get_viewable_path", lambda *a, **k: None)

        cfg = ImageServerConfig(directory=tmp_path, port=0)
        h = _H(cfg, [])
        h._serve_viewable("a.heic")
        assert 500 in h._codes


class TestServeVideo:
    def test_不存在_404(self, tmp_path: Path) -> None:
        cfg = ImageServerConfig(directory=tmp_path, port=0)
        h = _H(cfg, [])
        h._serve_video("nope.mov")
        assert 404 in h._codes

    def test_存在时_200(self, tmp_path: Path) -> None:
        (tmp_path / "v.mov").write_bytes(b"VIDEO")
        cfg = ImageServerConfig(directory=tmp_path, port=0)
        h = _H(cfg, [])
        h._serve_video("v.mov")
        assert 200 in h._codes
        assert h.wfile.getvalue() == b"VIDEO"


class TestServeFileError:
    def test_异常时_500(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        cfg = ImageServerConfig(directory=tmp_path, port=0)
        h = _H(cfg, [])

        # file_path.stat 触发异常
        class BadPath:
            def stat(self):
                raise OSError("io")

        h._serve_file(BadPath(), "image/jpeg")  # type: ignore[arg-type]
        assert 500 in h._codes
