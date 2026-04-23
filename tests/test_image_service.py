"""qxw.library.services.image_service 单元测试

重点覆盖纯扫描 / 格式化辅助函数，外部依赖（rawpy / Pillow / pillow-heif / cairosvg）
以 mock 注入，避免真实图像 IO。
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from qxw.library.services import image_service as isvc


class TestHumanSize:
    def test_B(self) -> None:
        assert isvc.human_size(0) == "0 B"
        assert isvc.human_size(500) == "500 B"

    def test_KB(self) -> None:
        assert isvc.human_size(1024) == "1.0 KB"

    def test_MB(self) -> None:
        assert isvc.human_size(1024 * 1024) == "1.0 MB"

    def test_GB(self) -> None:
        assert isvc.human_size(1024**3) == "1.0 GB"

    def test_超大数值走_PB(self) -> None:
        assert "PB" in isvc.human_size(1024**5 * 3)


class TestImageEntry:
    def test_is_live_对应_live_video_path(self, tmp_path: Path) -> None:
        e = isvc.ImageEntry(
            path=tmp_path / "a.jpg",
            rel_path="a.jpg",
            name="a.jpg",
            size=1,
            live_video_path=None,
        )
        assert e.is_live is False
        e.live_video_path = tmp_path / "a.mov"
        assert e.is_live is True

    def test_is_web_friendly(self, tmp_path: Path) -> None:
        for ext in [".jpg", ".png", ".webp"]:
            e = isvc.ImageEntry(path=tmp_path / f"x{ext}", rel_path=f"x{ext}", name=f"x{ext}", size=0)
            assert e.is_web_friendly is True
        for ext in [".heic", ".tiff", ".cr3"]:
            e = isvc.ImageEntry(path=tmp_path / f"x{ext}", rel_path=f"x{ext}", name=f"x{ext}", size=0)
            assert e.is_web_friendly is False


class TestScanImages:
    def test_空目录(self, tmp_path: Path) -> None:
        assert isvc.scan_images(tmp_path) == []

    def test_跳过隐藏文件(self, tmp_path: Path) -> None:
        (tmp_path / ".hidden.jpg").write_bytes(b"x")
        (tmp_path / "a.jpg").write_bytes(b"x")
        names = [e.name for e in isvc.scan_images(tmp_path)]
        assert names == ["a.jpg"]

    def test_忽略非图片扩展名(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_bytes(b"x")
        (tmp_path / "b.jpg").write_bytes(b"x")
        names = [e.name for e in isvc.scan_images(tmp_path)]
        assert names == ["b.jpg"]

    def test_递归与非递归(self, tmp_path: Path) -> None:
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "deep.jpg").write_bytes(b"x")
        (tmp_path / "top.jpg").write_bytes(b"x")

        non_rec = [e.name for e in isvc.scan_images(tmp_path, recursive=False)]
        rec = [e.name for e in isvc.scan_images(tmp_path, recursive=True)]
        assert "deep.jpg" not in non_rec
        assert "deep.jpg" in rec

    def test_Live_Photo_配对(self, tmp_path: Path) -> None:
        (tmp_path / "IMG_1.heic").write_bytes(b"x")
        (tmp_path / "IMG_1.mov").write_bytes(b"x")
        (tmp_path / "IMG_2.jpg").write_bytes(b"x")
        by_name = {e.name: e for e in isvc.scan_images(tmp_path)}
        assert by_name["IMG_1.heic"].is_live is True
        assert by_name["IMG_1.heic"].live_video_rel == "IMG_1.mov"
        assert by_name["IMG_2.jpg"].is_live is False

    def test_RAW_标记(self, tmp_path: Path) -> None:
        (tmp_path / "a.CR2").write_bytes(b"x")
        (tmp_path / "b.jpg").write_bytes(b"x")
        by_name = {e.name: e for e in isvc.scan_images(tmp_path)}
        assert by_name["a.CR2"].is_raw is True
        assert by_name["b.jpg"].is_raw is False


class TestScanSvgFiles:
    def test_只收_svg_且排除隐藏(self, tmp_path: Path) -> None:
        (tmp_path / "a.svg").write_bytes(b"<svg/>")
        (tmp_path / ".hidden.svg").write_bytes(b"<svg/>")
        (tmp_path / "b.png").write_bytes(b"x")
        res = isvc.scan_svg_files(tmp_path)
        assert [p.name for p in res] == ["a.svg"]

    def test_不递归时忽略子目录(self, tmp_path: Path) -> None:
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "x.svg").write_bytes(b"<svg/>")
        assert isvc.scan_svg_files(tmp_path, recursive=False) == []


class TestScanRawFiles:
    def test_仅_RAW_扩展名(self, tmp_path: Path) -> None:
        (tmp_path / "a.arw").write_bytes(b"x")
        (tmp_path / "b.jpg").write_bytes(b"x")
        assert [p.name for p in isvc.scan_raw_files(tmp_path)] == ["a.arw"]

    def test_排除隐藏(self, tmp_path: Path) -> None:
        (tmp_path / ".h.nef").write_bytes(b"x")
        (tmp_path / "v.nef").write_bytes(b"x")
        assert [p.name for p in isvc.scan_raw_files(tmp_path)] == ["v.nef"]


class TestScanFilterableImages:
    def test_排除_RAW(self, tmp_path: Path) -> None:
        (tmp_path / "a.jpg").write_bytes(b"x")
        (tmp_path / "b.cr3").write_bytes(b"x")
        assert [p.name for p in isvc.scan_filterable_images(tmp_path)] == ["a.jpg"]


class TestInjectSvgFontFamily:
    def test_无_svg_标签原样返回(self) -> None:
        raw = b"<notsvg/>"
        assert isvc._inject_svg_font_family(raw, "Arial") is raw

    def test_注入_style(self) -> None:
        svg = '<svg width="10" height="10"><text>你好</text></svg>'.encode("utf-8")
        out = isvc._inject_svg_font_family(svg, '"PingFang SC"')
        text = out.decode("utf-8")
        assert "<style" in text
        assert '"PingFang SC"' in text
        assert "!important" in text

    def test_非_UTF8_字节流_兜底解码(self) -> None:
        svg = b'<svg width="10" height="10">\xff</svg>'
        # 不报错
        out = isvc._inject_svg_font_family(svg, "X")
        assert b"<style" in out


class TestConvertSvgToPng:
    def test_字体栈禁用时_走_url_分支(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: dict[str, dict] = {}

        class FakeCairosvg:
            @staticmethod
            def svg2png(**kwargs):
                calls["kwargs"] = kwargs
                write_to = kwargs.get("write_to")
                if isinstance(write_to, str):
                    Path(write_to).write_bytes(b"PNG")

        monkeypatch.setitem(sys.modules, "cairosvg", FakeCairosvg)
        svg = tmp_path / "a.svg"
        svg.write_bytes(b'<svg width="10" height="10"/>')
        png = tmp_path / "out.png"

        isvc.convert_svg_to_png(svg, png, font_family="")

        assert png.read_bytes() == b"PNG"
        assert "url" in calls["kwargs"]
        assert "bytestring" not in calls["kwargs"]

    def test_默认字体栈_走_bytestring_分支(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: dict[str, dict] = {}

        class FakeCairosvg:
            @staticmethod
            def svg2png(**kwargs):
                calls["kwargs"] = kwargs
                write_to = kwargs.get("write_to")
                if isinstance(write_to, str):
                    Path(write_to).write_bytes(b"PNG")

        monkeypatch.setitem(sys.modules, "cairosvg", FakeCairosvg)
        svg = tmp_path / "a.svg"
        svg.write_bytes(b'<svg width="10" height="10"/>')
        png = tmp_path / "out.png"

        isvc.convert_svg_to_png(svg, png)

        assert "bytestring" in calls["kwargs"]
        assert "url" not in calls["kwargs"]


class TestGenerateThumbnail:
    def test_Pillow_未安装_返回_False(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delitem(sys.modules, "PIL", raising=False)
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *a, **k):
            if name == "PIL":
                raise ImportError
            return real_import(name, *a, **k)

        monkeypatch.setattr(builtins, "__import__", fake_import)

        src = tmp_path / "a.jpg"
        src.write_bytes(b"x")
        assert isvc.generate_thumbnail(src, tmp_path / "t.jpg") is False

    def test_缓存命中_跳过生成(self, tmp_path: Path) -> None:
        src = tmp_path / "a.jpg"
        src.write_bytes(b"x")
        thumb = tmp_path / "t.jpg"
        thumb.write_bytes(b"old")

        import os
        os.utime(thumb, None)  # mtime now
        # 人为把 src 改旧
        os.utime(src, (thumb.stat().st_mtime - 10, thumb.stat().st_mtime - 10))

        assert isvc.generate_thumbnail(src, thumb) is True
        # 文件没被重写
        assert thumb.read_bytes() == b"old"

    def test_生成失败返回_False(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class FakeImage:
            LANCZOS = 1

            @staticmethod
            def open(p):
                raise RuntimeError("broken")

        fake_pil = types.ModuleType("PIL")
        fake_pil.Image = FakeImage  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "PIL", fake_pil)

        src = tmp_path / "a.jpg"
        src.write_bytes(b"x")
        assert isvc.generate_thumbnail(src, tmp_path / "t.jpg") is False


class TestGetViewablePath:
    def test_浏览器友好直接返回原路径(self, tmp_path: Path) -> None:
        src = tmp_path / "a.jpg"
        src.write_bytes(b"x")
        out = isvc.get_viewable_path(src, tmp_path / "cache", tmp_path)
        assert out == src

    def test_缓存命中(self, tmp_path: Path) -> None:
        src = tmp_path / "a.heic"
        src.write_bytes(b"x")
        cache_dir = tmp_path / "cache"
        cache_path = cache_dir / "a.jpg"
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(b"cached")

        import os
        os.utime(src, (cache_path.stat().st_mtime - 10, cache_path.stat().st_mtime - 10))

        assert isvc.get_viewable_path(src, cache_dir, tmp_path) == cache_path

    def test_Pillow_未安装_返回_None(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        src = tmp_path / "a.heic"
        src.write_bytes(b"x")

        import builtins

        real_import = builtins.__import__

        def fake_import(name, *a, **k):
            if name == "PIL":
                raise ImportError
            return real_import(name, *a, **k)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        assert isvc.get_viewable_path(src, tmp_path / "c", tmp_path) is None


class TestOpenHelpers:
    def test_open_raw_rawpy_缺失返回_None(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *a, **k):
            if name == "rawpy":
                raise ImportError
            return real_import(name, *a, **k)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        assert isvc._open_raw_as_pil(tmp_path / "x.cr3") is None

    def test_open_heic_pillow_heif_缺失返回_None(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *a, **k):
            if name == "pillow_heif":
                raise ImportError
            return real_import(name, *a, **k)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        assert isvc._open_heic_as_pil(tmp_path / "x.heic") is None


class TestApplyFilterToImage:
    def test_default_filter_拒绝(self, tmp_path: Path) -> None:
        src = tmp_path / "a.jpg"
        dst = tmp_path / "b.jpg"
        src.write_bytes(b"x")
        with pytest.raises(ValueError, match="无操作占位名"):
            isvc.apply_filter_to_image(src, dst, "default")

    def test_未知_filter_拒绝(self, tmp_path: Path) -> None:
        src = tmp_path / "a.jpg"
        dst = tmp_path / "b.jpg"
        src.write_bytes(b"x")
        with pytest.raises(ValueError, match="未知"):
            isvc.apply_filter_to_image(src, dst, "完全不存在_xxx")


class TestConvertRaw:
    def test_缺失_rawpy_ImportError(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *a, **k):
            if name == "rawpy":
                raise ImportError("missing")
            return real_import(name, *a, **k)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        with pytest.raises(ImportError):
            isvc.convert_raw(tmp_path / "x.cr3", tmp_path / "x.jpg")
