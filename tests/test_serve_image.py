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


class TestServeAdjust:
    """/adjust/<path>?... 路由：调整预览"""

    def _cfg(self, tmp_path: Path) -> ImageServerConfig:
        return ImageServerConfig(directory=tmp_path, host="127.0.0.1", port=0)

    def test_文件不存在_404(self, tmp_path: Path) -> None:
        h = _H(self._cfg(tmp_path), [])
        h.path = "/adjust/nope.jpg?exposure=10"
        h.do_GET()
        assert 404 in h._codes

    def test_路径穿越_404(self, tmp_path: Path) -> None:
        h = _H(self._cfg(tmp_path), [])
        h.path = "/adjust/../secret?exposure=10"
        h.do_GET()
        assert 404 in h._codes

    def test_非法参数值_400(self, tmp_path: Path) -> None:
        (tmp_path / "a.jpg").write_bytes(b"x")
        h = _H(self._cfg(tmp_path), [])
        h.path = "/adjust/a.jpg?exposure=abc"
        # 让 get_viewable_path 以为找得到，只跑到参数解析就退出
        h.do_GET()
        assert 400 in h._codes

    def test_越界参数_400(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        (tmp_path / "a.jpg").write_bytes(b"x")
        h = _H(self._cfg(tmp_path), [])
        h.path = "/adjust/a.jpg?exposure=500"
        h.do_GET()
        assert 400 in h._codes

    def test_未知参数_400(self, tmp_path: Path) -> None:
        (tmp_path / "a.jpg").write_bytes(b"x")
        h = _H(self._cfg(tmp_path), [])
        h.path = "/adjust/a.jpg?nope=10"
        h.do_GET()
        assert 400 in h._codes

    def test_viewable_返回_None_500(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "a.jpg").write_bytes(b"x")
        import qxw.library.services.image_service as isvc_mod

        monkeypatch.setattr(isvc_mod, "get_viewable_path", lambda *a, **k: None)
        h = _H(self._cfg(tmp_path), [])
        h.path = "/adjust/a.jpg?exposure=10"
        h.do_GET()
        assert 500 in h._codes

    def test_预览底图缺失_500(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # PIL 已安装，但强制让 _get_preview_base 返回 None 触发 500
        jpg = tmp_path / "a.jpg"
        jpg.write_bytes(b"x")
        import qxw.library.services.image_service as isvc_mod
        import qxw.library.services.serve_image as si_mod

        monkeypatch.setattr(isvc_mod, "get_viewable_path", lambda *a, **k: jpg)
        monkeypatch.setattr(si_mod, "_get_preview_base", lambda *a, **k: None)

        h = _H(self._cfg(tmp_path), [])
        h.path = "/adjust/a.jpg?exposure=10"
        h.do_GET()
        assert 500 in h._codes

    def test_端到端_返回_JPEG(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 用一张真 JPG（PIL 生成）触发 apply_adjustments 全链路
        pil = pytest.importorskip("PIL.Image")
        import numpy as np

        img_arr = np.zeros((32, 32, 3), dtype=np.uint8)
        img_arr[..., 0] = 200  # 红底
        jpg = tmp_path / "a.jpg"
        pil.fromarray(img_arr).save(str(jpg), "JPEG", quality=80)

        # 清缓存避免上一条用例污染
        import qxw.library.services.serve_image as si_mod

        si_mod._PREVIEW_CACHE["key"] = None
        si_mod._PREVIEW_CACHE["ndarray"] = None
        si_mod._PREVIEW_CACHE["mtime"] = None

        h = _H(self._cfg(tmp_path), [])
        h.path = "/adjust/a.jpg?exposure=30&saturation=-100"
        h.do_GET()
        assert 200 in h._codes
        body = h.wfile.getvalue()
        # JPEG SOI 魔数
        assert body[:2] == b"\xff\xd8"


class TestServeSave:
    """POST /save/<path>?... 路由：原尺寸保存"""

    def _cfg(self, tmp_path: Path) -> ImageServerConfig:
        return ImageServerConfig(directory=tmp_path, host="127.0.0.1", port=0)

    def test_GET_到_save_路径_404(self, tmp_path: Path) -> None:
        h = _H(self._cfg(tmp_path), [])
        # do_GET 不路由 /save
        h.path = "/save/a.jpg?exposure=10"
        h.do_GET()
        assert 404 in h._codes

    def test_POST_文件不存在_404(self, tmp_path: Path) -> None:
        h = _H(self._cfg(tmp_path), [])
        h.path = "/save/nope.jpg?exposure=10"
        h.do_POST()
        assert 404 in h._codes

    def test_POST_路径穿越_404(self, tmp_path: Path) -> None:
        h = _H(self._cfg(tmp_path), [])
        h.path = "/save/../secret?exposure=10"
        h.do_POST()
        assert 404 in h._codes

    def test_POST_未知路径_404(self, tmp_path: Path) -> None:
        h = _H(self._cfg(tmp_path), [])
        h.path = "/api/unknown"
        h.do_POST()
        assert 404 in h._codes

    def test_POST_非法参数_400(self, tmp_path: Path) -> None:
        (tmp_path / "a.jpg").write_bytes(b"x")
        h = _H(self._cfg(tmp_path), [])
        h.path = "/save/a.jpg?exposure=abc"
        h.do_POST()
        assert 400 in h._codes

    def test_POST_越界参数_400(self, tmp_path: Path) -> None:
        (tmp_path / "a.jpg").write_bytes(b"x")
        h = _H(self._cfg(tmp_path), [])
        h.path = "/save/a.jpg?exposure=999"
        h.do_POST()
        assert 400 in h._codes

    def test_POST_无调整_400(self, tmp_path: Path) -> None:
        # is_identity() 被服务端拦下
        (tmp_path / "a.jpg").write_bytes(b"x")
        h = _H(self._cfg(tmp_path), [])
        h.path = "/save/a.jpg"  # 无 query
        h.do_POST()
        assert 400 in h._codes
        body = h.wfile.getvalue().decode("utf-8")
        assert "未设置任何调整" in body

    def test_POST_viewable_None_500(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "a.jpg").write_bytes(b"x")
        import qxw.library.services.image_service as isvc_mod

        monkeypatch.setattr(isvc_mod, "get_viewable_path", lambda *a, **k: None)
        h = _H(self._cfg(tmp_path), [])
        h.path = "/save/a.jpg?exposure=10"
        h.do_POST()
        assert 500 in h._codes

    def test_POST_save_adjusted_image_抛_QxwError_500(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "a.jpg").write_bytes(b"x")
        import qxw.library.services.image_adjust as ia_mod
        import qxw.library.services.image_service as isvc_mod

        monkeypatch.setattr(isvc_mod, "get_viewable_path", lambda *a, **k: tmp_path / "a.jpg")

        def boom(*a, **k):
            from qxw.library.base.exceptions import QxwError as QE
            raise QE("磁盘满", exit_code=5)

        monkeypatch.setattr(ia_mod, "save_adjusted_image", boom)
        h = _H(self._cfg(tmp_path), [])
        h.path = "/save/a.jpg?exposure=10"
        h.do_POST()
        assert 500 in h._codes
        body = h.wfile.getvalue().decode("utf-8")
        assert "磁盘满" in body

    def test_POST_意外_Exception_500(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "a.jpg").write_bytes(b"x")
        import qxw.library.services.image_adjust as ia_mod
        import qxw.library.services.image_service as isvc_mod

        monkeypatch.setattr(isvc_mod, "get_viewable_path", lambda *a, **k: tmp_path / "a.jpg")
        monkeypatch.setattr(ia_mod, "save_adjusted_image",
                             lambda *a, **k: (_ for _ in ()).throw(RuntimeError("oops")))
        h = _H(self._cfg(tmp_path), [])
        h.path = "/save/a.jpg?exposure=10"
        h.do_POST()
        assert 500 in h._codes

    def test_POST_端到端_写出原尺寸_JPG(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pil = pytest.importorskip("PIL.Image")
        import json as _json

        pil.new("RGB", (120, 80), (128, 64, 200)).save(str(tmp_path / "a.jpg"), "JPEG", quality=90)

        h = _H(self._cfg(tmp_path), [])
        h.path = "/save/a.jpg?exposure=25&contrast=10"
        h.do_POST()
        assert 200 in h._codes
        body = h.wfile.getvalue().decode("utf-8")
        payload = _json.loads(body)
        saved = tmp_path / payload["path"]
        assert saved.exists()
        assert saved.suffix == ".jpg"
        assert "_adjusted_" in saved.name
        # 保留原尺寸
        with pil.open(saved) as im:
            assert im.size == (120, 80)


class TestPreviewCache:
    def test_mtime_变化_触发重解码(self, tmp_path: Path) -> None:
        pil = pytest.importorskip("PIL.Image")
        import numpy as np

        import qxw.library.services.serve_image as si_mod

        jpg = tmp_path / "a.jpg"
        pil.fromarray(np.zeros((16, 16, 3), dtype=np.uint8)).save(str(jpg), "JPEG")
        si_mod._PREVIEW_CACHE["key"] = None

        a = si_mod._get_preview_base(jpg, "k", max_side=1200)
        assert a is not None
        # 再次请求相同 mtime 命中缓存
        b = si_mod._get_preview_base(jpg, "k", max_side=1200)
        assert b is a

    def test_文件打开失败_返回_None(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import qxw.library.services.serve_image as si_mod

        # stat 失败模拟磁盘错误
        bad = tmp_path / "ghost.jpg"
        # 文件不存在 → stat 抛 OSError → 返回 None
        result = si_mod._get_preview_base(bad, "k", max_side=1200)
        assert result is None


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
