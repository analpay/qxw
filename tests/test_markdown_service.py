"""qxw.library.services.markdown_service 单元测试

只覆盖纯函数以及错误分支，渲染/图片编码全部使用 mock，
不真正触发 java / plantuml.jar / cairosvg / Pillow。
"""

from __future__ import annotations

import subprocess
import sys
import types
from pathlib import Path

import pytest

from qxw.library.base.exceptions import QxwError
from qxw.library.services import markdown_service as mks
from qxw.library.services.markdown_service import (
    _inject_svg_background_rect,
    _prepare_plantuml_source,
    extract_plantuml_blocks,
)


class TestExtractPlantumlBlocks:
    def test_支持_plantuml_puml_uml_三种围栏(self) -> None:
        md = (
            "# title\n\n"
            "```plantuml\n@startuml\nA -> B\n@enduml\n```\n\n"
            "段落\n\n"
            "```puml\n@startuml\nC -> D\n@enduml\n```\n\n"
            "```uml\nE -> F\n```\n"
        )
        blocks = extract_plantuml_blocks(md)
        assert len(blocks) == 3
        assert "A -> B" in blocks[0].source
        assert "C -> D" in blocks[1].source
        assert "E -> F" in blocks[2].source

    def test_不匹配其他语言围栏(self) -> None:
        md = "```python\nprint('x')\n```\n"
        assert extract_plantuml_blocks(md) == []

    def test_缩进一致才视为围栏(self) -> None:
        md = (
            "    ```plantuml\n"
            "    @startuml\n"
            "    A -> B\n"
            "    @enduml\n"
            "    ```\n"
        )
        blocks = extract_plantuml_blocks(md)
        assert len(blocks) == 1
        assert blocks[0].indent == "    "

    def test_闭合围栏缩进不一致则整段不匹配(self) -> None:
        md = (
            "    ```plantuml\n"
            "    A -> B\n"
            "```\n"  # 闭合缩进不一致
        )
        assert extract_plantuml_blocks(md) == []

    def test_返回的_start_end_可用于原文替换(self) -> None:
        md = "前\n```plantuml\nA -> B\n```\n后"
        block = extract_plantuml_blocks(md)[0]
        fence = md[block.start : block.end]
        assert fence.startswith("```plantuml")
        assert fence.endswith("```")


class TestPreparePlantumlSource:
    def test_裸内容被_startuml_包裹(self) -> None:
        src = _prepare_plantuml_source("A -> B\n", background="white", font_name="PingFang SC")
        assert src.startswith("@startuml\n")
        assert src.rstrip().endswith("@enduml")
        assert "skinparam backgroundColor white" in src
        assert 'skinparam defaultFontName "PingFang SC"' in src

    def test_已有_startuml_时_skinparam_插在第二行(self) -> None:
        raw = "@startuml\nA -> B\n@enduml\n"
        src = _prepare_plantuml_source(raw, background="black", font_name="HeiTi")

        lines = src.splitlines()
        assert lines[0] == "@startuml"
        assert lines[1] == "skinparam backgroundColor black"
        assert lines[2] == 'skinparam defaultFontName "HeiTi"'
        assert "A -> B" in src
        # 不应重复包裹 @enduml
        assert src.count("@enduml") == 1

    @pytest.mark.parametrize("bg", ["white", "black", "transparent"])
    def test_三种背景都被正确注入(self, bg: str) -> None:
        src = _prepare_plantuml_source("A -> B", background=bg, font_name="X")
        assert f"skinparam backgroundColor {bg}" in src


class TestInjectSvgBackgroundRect:
    def test_普通_SVG_会插入_rect(self) -> None:
        svg = b'<?xml version="1.0"?><svg width="10" height="10"><g/></svg>'
        out = _inject_svg_background_rect(svg, "#ffffff")
        text = out.decode("utf-8")
        assert '<rect width="100%" height="100%" fill="#ffffff"/>' in text
        # rect 应紧跟在 <svg ...> 之后
        assert text.index("<rect") < text.index("<g/>")

    def test_找不到_svg_标签时原样返回(self) -> None:
        raw = b"<notsvg/>"
        assert _inject_svg_background_rect(raw, "#000000") is raw

    def test_非_UTF8_字节流_解码兜底(self) -> None:
        svg = b'<svg width="10" height="10">\xff\xfe</svg>'
        out = _inject_svg_background_rect(svg, "#fff")
        assert b"<rect" in out


class TestEnsureJavaAndJar:
    def test_java_缺失_抛_QxwError(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(mks.shutil, "which", lambda _: None)
        with pytest.raises(QxwError, match="java"):
            mks._ensure_java_and_jar(tmp_path / "p.jar", "java")

    def test_jar_缺失_抛_QxwError(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(mks.shutil, "which", lambda _: "/usr/bin/java")
        with pytest.raises(QxwError, match="plantuml.jar"):
            mks._ensure_java_and_jar(tmp_path / "nope.jar", "java")

    def test_正常路径不抛(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(mks.shutil, "which", lambda _: "/usr/bin/java")
        jar = tmp_path / "p.jar"
        jar.write_bytes(b"")
        mks._ensure_java_and_jar(jar, "java")  # 不抛


class TestRenderPlantumlToSvg:
    def test_超时抛_QxwError(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        def fake_run(*a, **k):
            raise subprocess.TimeoutExpired(cmd="x", timeout=1)

        monkeypatch.setattr(mks.subprocess, "run", fake_run)
        with pytest.raises(QxwError, match="超时"):
            mks.render_plantuml_to_svg(
                "A->B", jar_path=tmp_path / "p.jar", java_bin="java", background="white"
            )

    def test_java_文件找不到_抛_QxwError(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        def fake_run(*a, **k):
            raise FileNotFoundError("no java")

        monkeypatch.setattr(mks.subprocess, "run", fake_run)
        with pytest.raises(QxwError, match="无法执行 java"):
            mks.render_plantuml_to_svg(
                "A->B", jar_path=tmp_path / "p.jar", java_bin="java", background="white"
            )

    def test_非零退出抛_QxwError(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        class FakeProc:
            returncode = 2
            stdout = b""
            stderr = b"bad plantuml"

        monkeypatch.setattr(mks.subprocess, "run", lambda *a, **k: FakeProc())
        with pytest.raises(QxwError, match="渲染失败"):
            mks.render_plantuml_to_svg(
                "A->B", jar_path=tmp_path / "p.jar", java_bin="java", background="white"
            )

    def test_无_stdout_抛_QxwError(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        class FakeProc:
            returncode = 0
            stdout = b""
            stderr = b""

        monkeypatch.setattr(mks.subprocess, "run", lambda *a, **k: FakeProc())
        with pytest.raises(QxwError, match="未产出"):
            mks.render_plantuml_to_svg(
                "A->B", jar_path=tmp_path / "p.jar", java_bin="java", background="white"
            )

    def test_正常返回_stdout(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        class FakeProc:
            returncode = 0
            stdout = b"<svg/>"
            stderr = b""

        monkeypatch.setattr(mks.subprocess, "run", lambda *a, **k: FakeProc())
        out = mks.render_plantuml_to_svg(
            "A->B", jar_path=tmp_path / "p.jar", java_bin="java", background="white"
        )
        assert out == b"<svg/>"


class TestWriteImage:
    def test_不支持的格式(self, tmp_path: Path) -> None:
        with pytest.raises(QxwError, match="不支持的图片格式"):
            mks.write_image(
                b"<svg/>", tmp_path / "o.gif", fmt="gif",
                scale=1, font_family=None, background="white", quality=90,
            )

    def test_不支持的背景(self, tmp_path: Path) -> None:
        with pytest.raises(QxwError, match="不支持的背景"):
            mks.write_image(
                b"<svg/>", tmp_path / "o.svg", fmt="svg",
                scale=1, font_family=None, background="pink", quality=90,
            )

    def test_svg_输出_写文件(self, tmp_path: Path) -> None:
        dest = tmp_path / "o.svg"
        mks.write_image(
            b'<svg width="10" height="10"/>', dest, fmt="svg",
            scale=1, font_family="", background="white", quality=90,
        )
        data = dest.read_bytes()
        assert b"<rect" in data  # 白色背景注入

    def test_svg_transparent_不注入_rect(self, tmp_path: Path) -> None:
        dest = tmp_path / "o.svg"
        mks.write_image(
            b'<svg width="10" height="10"/>', dest, fmt="svg",
            scale=1, font_family="", background="transparent", quality=90,
        )
        assert b"<rect" not in dest.read_bytes()

    def test_png_无_cairosvg_ImportError_包装_QxwError(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *a, **k):
            if name == "cairosvg":
                raise ImportError
            return real_import(name, *a, **k)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        with pytest.raises(QxwError, match="cairosvg"):
            mks.write_image(
                b"<svg/>", tmp_path / "o.png", fmt="png",
                scale=1, font_family="", background="white", quality=90,
            )

    def test_png_调用_cairosvg(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, dict] = {}

        class FakeCairosvg:
            @staticmethod
            def svg2png(**kwargs):
                captured["kwargs"] = kwargs
                write_to = kwargs.get("write_to")
                if isinstance(write_to, str):
                    Path(write_to).write_bytes(b"PNG")

        monkeypatch.setitem(sys.modules, "cairosvg", FakeCairosvg)
        dest = tmp_path / "o.png"
        mks.write_image(
            b'<svg width="10" height="10"/>', dest, fmt="png",
            scale=2, font_family="", background="white", quality=90,
        )
        assert dest.read_bytes() == b"PNG"
        assert captured["kwargs"]["scale"] == 2

    def test_jpg_调用_cairosvg_和_PIL(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class FakeCairosvg:
            @staticmethod
            def svg2png(**kwargs):
                write_to = kwargs.get("write_to")
                # write_to 为 BytesIO
                write_to.write(b"\x89PNG\r\n\x1a\n")  # 简化 PNG 签名

        # 构造假 PIL
        class FakeAlphaChannel:
            def split_mock(self):
                return self

        class FakePILImg:
            size = (8, 8)
            mode = "RGBA"

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def convert(self, mode):
                assert mode == "RGBA"
                return self

            def split(self):
                return [self, self, self, self]  # 第 -1 个作为 mask

        class FakeCanvas:
            def __init__(self, mode, size, color) -> None:
                self.mode = mode
                self.size = size
                self.fill = color
                self.pasted = False

            def paste(self, im, mask) -> None:
                self.pasted = True

            def save(self, path, fmt, quality, progressive) -> None:
                Path(path).write_bytes(b"JPG")

        pil_mod = type(sys)("PIL")
        image_pkg = type(sys)("PIL.Image")

        class FakeImageCls:
            @staticmethod
            def open(buf):
                return FakePILImg()

            @staticmethod
            def new(mode, size, color):
                return FakeCanvas(mode, size, color)

        image_pkg.Image = FakeImageCls  # type: ignore[attr-defined]
        # PIL.Image 作为子模块
        pil_mod.Image = FakeImageCls  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "PIL", pil_mod)
        monkeypatch.setitem(sys.modules, "PIL.Image", image_pkg)
        monkeypatch.setitem(sys.modules, "cairosvg", FakeCairosvg)

        dest = tmp_path / "o.jpg"
        mks.write_image(
            b'<svg width="10" height="10"/>', dest, fmt="jpg",
            scale=2, font_family="", background="white", quality=95,
        )
        assert dest.read_bytes() == b"JPG"

    def test_jpg_transparent_背景落白(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class FakeCairosvg:
            @staticmethod
            def svg2png(**kwargs):
                write_to = kwargs.get("write_to")
                write_to.write(b"\x89PNG")

        class FakePILImg:
            size = (4, 4)
            mode = "RGBA"

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def convert(self, mode):
                return self

            def split(self):
                return [self, self, self, self]

        captured: dict[str, tuple] = {}

        class FakeCanvas:
            def __init__(self, mode, size, color) -> None:
                captured["fill"] = color

            def paste(self, im, mask) -> None:
                pass

            def save(self, path, fmt, quality, progressive) -> None:
                Path(path).write_bytes(b"JPG")

        pil_mod = type(sys)("PIL")
        class FakeImageCls:
            @staticmethod
            def open(buf):
                return FakePILImg()

            @staticmethod
            def new(mode, size, color):
                return FakeCanvas(mode, size, color)

        pil_mod.Image = FakeImageCls  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "PIL", pil_mod)
        monkeypatch.setitem(sys.modules, "cairosvg", FakeCairosvg)

        dest = tmp_path / "o.jpg"
        mks.write_image(
            b'<svg width="10" height="10"/>', dest, fmt="jpg",
            scale=1, font_family="", background="transparent", quality=90,
        )
        # transparent 落到白色
        assert captured["fill"] == (255, 255, 255)

    def test_jpg_black_背景(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class FakeCairosvg:
            @staticmethod
            def svg2png(**kwargs):
                kwargs.get("write_to").write(b"\x89PNG")

        class FakePILImg:
            size = (2, 2)
            mode = "RGBA"

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def convert(self, m):
                return self

            def split(self):
                return [self, self, self, self]

        captured: dict[str, tuple] = {}

        class FakeCanvas:
            def __init__(self, mode, size, color) -> None:
                captured["fill"] = color

            def paste(self, im, mask) -> None:
                pass

            def save(self, path, fmt, quality, progressive) -> None:
                Path(path).write_bytes(b"JPG")

        pil_mod = type(sys)("PIL")
        class FakeImageCls:
            @staticmethod
            def open(buf):
                return FakePILImg()

            @staticmethod
            def new(mode, size, color):
                return FakeCanvas(mode, size, color)

        pil_mod.Image = FakeImageCls  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "PIL", pil_mod)
        monkeypatch.setitem(sys.modules, "cairosvg", FakeCairosvg)

        dest = tmp_path / "o.jpg"
        mks.write_image(
            b'<svg width="10" height="10"/>', dest, fmt="jpg",
            scale=1, font_family="", background="black", quality=90,
        )
        assert captured["fill"] == (0, 0, 0)

    def test_jpg_缺_PIL_ImportError(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class FakeCairosvg:
            @staticmethod
            def svg2png(**kwargs):
                kwargs.get("write_to").write(b"\x89PNG")

        monkeypatch.setitem(sys.modules, "cairosvg", FakeCairosvg)

        import builtins as _bi

        real_import = _bi.__import__

        def fake_import(name, *a, **k):
            if name == "PIL":
                raise ImportError
            return real_import(name, *a, **k)

        monkeypatch.setattr(_bi, "__import__", fake_import)
        with pytest.raises(QxwError, match="Pillow"):
            mks.write_image(
                b"<svg/>", tmp_path / "o.jpg", fmt="jpg",
                scale=1, font_family="", background="white", quality=90,
            )


class TestConvertMarkdownForWx:
    def test_不支持的_fmt_抛_QxwError(self, tmp_path: Path) -> None:
        f = tmp_path / "a.md"
        f.write_text("", encoding="utf-8")
        with pytest.raises(QxwError, match="不支持的图片格式"):
            mks.convert_markdown_for_wx(f, fmt="gif")

    def test_不支持的_background(self, tmp_path: Path) -> None:
        f = tmp_path / "a.md"
        f.write_text("", encoding="utf-8")
        with pytest.raises(QxwError, match="不支持的背景"):
            mks.convert_markdown_for_wx(f, fmt="png", background="pink")

    def test_md_文件不存在(self, tmp_path: Path) -> None:
        with pytest.raises(QxwError, match="Markdown 文件不存在"):
            mks.convert_markdown_for_wx(tmp_path / "nope.md")

    def test_无_plantuml_直接拷贝_md(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 绕过 java / jar 校验
        monkeypatch.setattr(mks, "_ensure_java_and_jar", lambda *a, **k: None)
        f = tmp_path / "a.md"
        f.write_text("# 标题\n正文\n", encoding="utf-8")
        result = mks.convert_markdown_for_wx(f)
        assert result.image_paths == []
        assert result.output_md.read_text(encoding="utf-8") == "# 标题\n正文\n"

    def test_正常转换_替换围栏为图片引用(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(mks, "_ensure_java_and_jar", lambda *a, **k: None)

        # 替换渲染与写图，避免真实外部依赖
        rendered_calls: list[str] = []

        def fake_render(source, **k):
            rendered_calls.append(source)
            return b"<svg/>"

        monkeypatch.setattr(mks, "render_plantuml_to_svg", fake_render)

        written: list[Path] = []

        def fake_write(svg_bytes, dest, fmt, **k):
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b"IMG")
            written.append(dest)

        monkeypatch.setattr(mks, "write_image", fake_write)

        f = tmp_path / "a.md"
        f.write_text("前\n\n```plantuml\nA -> B\n```\n\n后\n", encoding="utf-8")
        result = mks.convert_markdown_for_wx(f, fmt="png")

        assert len(result.image_paths) == 1
        assert result.image_paths[0].name == "a_1.png"
        out_md = result.output_md.read_text(encoding="utf-8")
        assert "![](./a_1.png)" in out_md
        assert "```plantuml" not in out_md
