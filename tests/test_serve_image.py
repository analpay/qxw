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


class TestGalleryStats:
    def test_带_Live_与_RAW_统计(self, tmp_path: Path) -> None:
        (tmp_path / "a.heic").write_bytes(b"x")
        (tmp_path / "a.mov").write_bytes(b"x")
        (tmp_path / "b.cr3").write_bytes(b"x")
        img_live = ImageEntry(
            path=tmp_path / "a.heic", rel_path="a.heic", name="a.heic", size=1,
            live_video_path=tmp_path / "a.mov", live_video_rel="a.mov",
        )
        img_raw = ImageEntry(
            path=tmp_path / "b.cr3", rel_path="b.cr3", name="b.cr3", size=1, is_raw=True,
        )
        cfg = ImageServerConfig(directory=tmp_path, port=0)
        h = _H(cfg, [img_live, img_raw])
        h.path = "/"
        h.do_GET()
        body = h.wfile.getvalue().decode("utf-8")
        assert "LIVE" in body
        assert "RAW" in body
        assert "1 张 Live Photo" in body
        assert "1 张 RAW" in body


class TestLogMessage:
    def test_log_不抛错(self, tmp_path: Path) -> None:
        cfg = ImageServerConfig(directory=tmp_path, port=0)
        h = _H(cfg, [])
        h.log_message("%s", "ok")


class TestServeThumbnailSuccess:
    def test_正常返回_缩略图(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "a.jpg").write_bytes(b"x")

        import qxw.library.services.image_service as isvc_mod

        def fake_gen(src, thumb_path, size, quality):
            thumb_path.parent.mkdir(parents=True, exist_ok=True)
            thumb_path.write_bytes(b"T")
            return True

        monkeypatch.setattr(isvc_mod, "generate_thumbnail", fake_gen)
        cfg = ImageServerConfig(directory=tmp_path, port=0)
        h = _H(cfg, [])
        h._serve_thumbnail("a.jpg")
        assert 200 in h._codes
        assert h.wfile.getvalue() == b"T"


class TestStartServer:
    def test_HTTPServer_被调用(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        called: dict[str, bool] = {}

        class FakeServer:
            def __init__(self, addr, handler_cls) -> None:
                called["addr"] = addr

            def serve_forever(self) -> None:
                called["served"] = True

        monkeypatch.setattr(si, "HTTPServer", FakeServer)
        cfg = ImageServerConfig(directory=tmp_path, port=1234)
        si.start_server(cfg, [])
        assert called["served"] is True
