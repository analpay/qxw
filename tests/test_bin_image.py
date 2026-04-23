"""qxw-image 命令入口单元测试

覆盖：
- _require_pillow / _require_rawpy / _require_cairosvg：依赖缺失抛 QxwError
- 各子命令：目录不存在、参数非法、依赖缺失、QxwError / KeyboardInterrupt / Exception 分支
- raw 命令：--filter 与 --use-embedded 互斥逻辑、空目录分支
- filter 命令：--list 分支、未知滤镜、default 占位拒绝
"""

from __future__ import annotations

import builtins
from pathlib import Path

import pytest
from click.testing import CliRunner

from qxw.bin import image as image_mod
from qxw.library.base.exceptions import QxwError


def _run(args: list[str]) -> tuple[int, str]:
    runner = CliRunner()
    result = runner.invoke(image_mod.main, args)
    return result.exit_code, result.output


def _block_import(monkeypatch: pytest.MonkeyPatch, *modules: str) -> None:
    """让指定模块的 import 抛 ImportError"""
    real_import = builtins.__import__

    def fake(name, *a, **k):
        if name in modules:
            raise ImportError(f"no {name}")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake)


class TestMainGroup:
    def test_无子命令打印帮助(self) -> None:
        code, out = _run([])
        assert code == 0
        assert "raw" in out
        assert "svg" in out
        assert "filter" in out


class TestRequireHelpers:
    def test_require_pillow_缺失(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _block_import(monkeypatch, "PIL")
        with pytest.raises(QxwError, match="Pillow"):
            image_mod._require_pillow()

    def test_require_rawpy_缺失(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _block_import(monkeypatch, "rawpy")
        with pytest.raises(QxwError, match="rawpy"):
            image_mod._require_rawpy()

    def test_require_cairosvg_缺失(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _block_import(monkeypatch, "cairosvg")
        with pytest.raises(QxwError, match="cairosvg"):
            image_mod._require_cairosvg()


class TestRawCommand:
    def test_Pillow_缺失(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _block_import(monkeypatch, "PIL")
        code, out = _run(["raw", "-d", str(tmp_path)])
        assert code == 1
        assert "Pillow" in out

    def test_rawpy_缺失(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _block_import(monkeypatch, "rawpy")
        code, out = _run(["raw", "-d", str(tmp_path)])
        assert code == 1
        assert "rawpy" in out

    def test_目录不存在_click_拒绝(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # 绕过依赖检查
        monkeypatch.setattr(image_mod, "_require_pillow", lambda: None)
        monkeypatch.setattr(image_mod, "_require_rawpy", lambda: None)
        code, _ = _run(["raw", "-d", str(tmp_path / "nope")])
        assert code != 0

    def test_未知滤镜(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(image_mod, "_require_pillow", lambda: None)
        monkeypatch.setattr(image_mod, "_require_rawpy", lambda: None)
        code, out = _run(["raw", "-d", str(tmp_path), "--filter", "完全不存在_xxx"])
        assert code != 0

    def test_filter_与_use_embedded_冲突(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(image_mod, "_require_pillow", lambda: None)
        monkeypatch.setattr(image_mod, "_require_rawpy", lambda: None)
        # fuji-cc 是内置滤镜；显式 --use-embedded 会触发 UsageError
        code, out = _run([
            "raw", "-d", str(tmp_path),
            "--filter", "fuji-cc", "--use-embedded",
        ])
        assert code != 0
        assert "互斥" in out or "use-embedded" in out

    def test_空目录_无_RAW(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(image_mod, "_require_pillow", lambda: None)
        monkeypatch.setattr(image_mod, "_require_rawpy", lambda: None)
        code, out = _run(["raw", "-d", str(tmp_path)])
        assert code == 0
        assert "未找到" in out

    def test_QxwError_透传(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        def raise_err():
            raise QxwError("自定义失败", exit_code=9)

        monkeypatch.setattr(image_mod, "_require_pillow", raise_err)
        code, out = _run(["raw", "-d", str(tmp_path)])
        assert code == 9
        assert "自定义失败" in out

    def test_KeyboardInterrupt(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def raise_kb():
            raise KeyboardInterrupt()

        monkeypatch.setattr(image_mod, "_require_pillow", raise_kb)
        code, out = _run(["raw", "-d", str(tmp_path)])
        assert code == 130
        assert "已取消" in out

    def test_通用异常(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def raise_any():
            raise RuntimeError("boom")

        monkeypatch.setattr(image_mod, "_require_pillow", raise_any)
        code, out = _run(["raw", "-d", str(tmp_path)])
        assert code == 1
        assert "未预期" in out


class TestSvgCommand:
    def test_cairosvg_缺失(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _block_import(monkeypatch, "cairosvg")
        code, out = _run(["svg", "-d", str(tmp_path)])
        assert code == 1
        assert "cairosvg" in out

    def test_目录不存在(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(image_mod, "_require_cairosvg", lambda: None)
        code, _ = _run(["svg", "-d", str(tmp_path / "nope")])
        assert code != 0

    def test_scale_非正数(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(image_mod, "_require_cairosvg", lambda: None)
        code, out = _run(["svg", "-d", str(tmp_path), "-s", "0"])
        assert code != 0

    def test_空目录_无_SVG(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(image_mod, "_require_cairosvg", lambda: None)
        code, out = _run(["svg", "-d", str(tmp_path)])
        assert code == 0
        assert "未找到" in out

    def test_KeyboardInterrupt(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def raise_kb():
            raise KeyboardInterrupt()

        monkeypatch.setattr(image_mod, "_require_cairosvg", raise_kb)
        code, _ = _run(["svg", "-d", str(tmp_path)])
        assert code == 130

    def test_通用异常(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        def raise_any():
            raise RuntimeError("boom")

        monkeypatch.setattr(image_mod, "_require_cairosvg", raise_any)
        code, _ = _run(["svg", "-d", str(tmp_path)])
        assert code == 1

    def test_QxwError(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        def raise_err():
            raise QxwError("sgv error", exit_code=7)

        monkeypatch.setattr(image_mod, "_require_cairosvg", raise_err)
        code, out = _run(["svg", "-d", str(tmp_path)])
        assert code == 7


class TestFilterCommand:
    def test_list_分支(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(image_mod, "_require_pillow", lambda: None)
        code, out = _run(["filter", "--list"])
        assert code == 0
        assert "滤镜" in out

    def test_缺少_name_参数(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(image_mod, "_require_pillow", lambda: None)
        code, out = _run(["filter"])
        assert code != 0
        assert "--name" in out or "name" in out or "--list" in out

    def test_未知_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(image_mod, "_require_pillow", lambda: None)
        code, out = _run(["filter", "-n", "not_a_real_filter_xxx"])
        assert code != 0

    def test_default_被拒绝(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(image_mod, "_require_pillow", lambda: None)
        code, out = _run(["filter", "-n", "default"])
        assert code != 0

    def test_目录不存在(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(image_mod, "_require_pillow", lambda: None)
        code, _ = _run(["filter", "-n", "fuji-cc", "-d", str(tmp_path / "nope")])
        assert code != 0

    def test_空目录_无位图(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(image_mod, "_require_pillow", lambda: None)
        code, out = _run(["filter", "-n", "fuji-cc", "-d", str(tmp_path)])
        assert code == 0
        assert "未找到" in out

    def test_QxwError(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def raise_err():
            raise QxwError("filter 错", exit_code=5)

        monkeypatch.setattr(image_mod, "_require_pillow", raise_err)
        code, out = _run(["filter", "-n", "fuji-cc"])
        assert code == 5

    def test_KeyboardInterrupt(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def raise_kb():
            raise KeyboardInterrupt()

        monkeypatch.setattr(image_mod, "_require_pillow", raise_kb)
        code, _ = _run(["filter", "-n", "fuji-cc"])
        assert code == 130

    def test_通用异常(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def raise_any():
            raise RuntimeError("boom")

        monkeypatch.setattr(image_mod, "_require_pillow", raise_any)
        code, _ = _run(["filter", "-n", "fuji-cc"])
        assert code == 1


class TestRawCommandSuccess:
    def test_正常流程_串行(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(image_mod, "_require_pillow", lambda: None)
        monkeypatch.setattr(image_mod, "_require_rawpy", lambda: None)

        # 伪 RAW 文件
        r1 = tmp_path / "a.CR3"
        r1.write_bytes(b"x")
        r2 = tmp_path / "b.ARW"
        r2.write_bytes(b"x")

        from qxw.library.services import image_service as isvc

        processed: list[Path] = []

        def fake_convert(src, dst, **k):
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(b"JPG")
            processed.append(src)

        monkeypatch.setattr(isvc, "convert_raw", fake_convert)

        code, out = _run(["raw", "-d", str(tmp_path), "-j", "1"])
        assert code == 0
        assert "2 成功" in out
        assert len(processed) == 2

    def test_正常流程_部分失败(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(image_mod, "_require_pillow", lambda: None)
        monkeypatch.setattr(image_mod, "_require_rawpy", lambda: None)

        (tmp_path / "a.CR3").write_bytes(b"x")
        (tmp_path / "b.ARW").write_bytes(b"x")

        from qxw.library.services import image_service as isvc

        def fake_convert(src, dst, **k):
            if "b." in src.name:
                raise RuntimeError("broken")
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(b"JPG")

        monkeypatch.setattr(isvc, "convert_raw", fake_convert)

        code, out = _run(["raw", "-d", str(tmp_path), "-j", "1"])
        assert code == 0
        assert "1 成功" in out
        assert "1 失败" in out

    def test_已有输出_skip_分支(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(image_mod, "_require_pillow", lambda: None)
        monkeypatch.setattr(image_mod, "_require_rawpy", lambda: None)

        (tmp_path / "a.CR3").write_bytes(b"x")
        # 预先存在输出文件
        out_dir = tmp_path / "jpg"
        out_dir.mkdir()
        (out_dir / "a.jpg").write_bytes(b"exist")

        from qxw.library.services import image_service as isvc

        def fake(src, dst, **k):
            raise AssertionError("不应被调用")

        monkeypatch.setattr(isvc, "convert_raw", fake)

        code, out = _run(["raw", "-d", str(tmp_path), "-j", "1"])
        assert code == 0
        assert "1 跳过" in out

    def test_filter_自动关闭_use_embedded(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(image_mod, "_require_pillow", lambda: None)
        monkeypatch.setattr(image_mod, "_require_rawpy", lambda: None)
        (tmp_path / "a.CR3").write_bytes(b"x")

        captured: dict[str, object] = {}

        def fake(src, dst, **k):
            captured.update(k)
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(b"JPG")

        from qxw.library.services import image_service as isvc
        monkeypatch.setattr(isvc, "convert_raw", fake)

        code, _ = _run(["raw", "-d", str(tmp_path), "-j", "1", "--filter", "fuji-cc"])
        assert code == 0
        assert captured["use_embedded"] is False
        assert captured["color_filter"] == "fuji-cc"


class TestSvgCommandSuccess:
    def test_正常转换(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(image_mod, "_require_cairosvg", lambda: None)
        (tmp_path / "a.svg").write_bytes(b"<svg/>")

        from qxw.library.services import image_service as isvc

        def fake(src, dst, **k):
            dst.write_bytes(b"PNG")

        monkeypatch.setattr(isvc, "convert_svg_to_png", fake)
        code, out = _run(["svg", "-d", str(tmp_path), "-j", "1"])
        assert code == 0
        assert "1 成功" in out

    def test_已存在_PNG_跳过(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(image_mod, "_require_cairosvg", lambda: None)
        (tmp_path / "a.svg").write_bytes(b"<svg/>")
        (tmp_path / "a.png").write_bytes(b"x")

        from qxw.library.services import image_service as isvc
        monkeypatch.setattr(isvc, "convert_svg_to_png", lambda *a, **k: (_ for _ in ()).throw(AssertionError()))
        code, out = _run(["svg", "-d", str(tmp_path), "-j", "1", "--no-overwrite"])
        assert code == 0
        assert "1 跳过" in out

    def test_转换失败_fail_count(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(image_mod, "_require_cairosvg", lambda: None)
        (tmp_path / "a.svg").write_bytes(b"<svg/>")

        from qxw.library.services import image_service as isvc
        monkeypatch.setattr(
            isvc, "convert_svg_to_png", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")),
        )
        code, out = _run(["svg", "-d", str(tmp_path), "-j", "1"])
        assert code == 0
        assert "1 失败" in out


class TestFilterCommandSuccess:
    def test_正常调色(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(image_mod, "_require_pillow", lambda: None)
        (tmp_path / "a.jpg").write_bytes(b"x")

        from qxw.library.services import image_service as isvc

        def fake(src, dst, name, quality):
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(b"OK")

        monkeypatch.setattr(isvc, "apply_filter_to_image", fake)
        code, out = _run(["filter", "-n", "fuji-cc", "-d", str(tmp_path), "-j", "1"])
        assert code == 0
        assert "1 成功" in out

    def test_跳过输出目录内部(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(image_mod, "_require_pillow", lambda: None)
        # 预先创建 filtered 子目录及其中的图片，递归扫描会把它们也扫进来
        out_dir = tmp_path / "filtered"
        out_dir.mkdir()
        (out_dir / "old.jpg").write_bytes(b"old")
        # 无顶层文件
        code, out = _run([
            "filter", "-n", "fuji-cc", "-d", str(tmp_path), "-r", "-j", "1",
        ])
        assert code == 0
        # 所有被扫到的文件都位于 out_dir，应该被跳过
        assert "1 跳过" in out or "未找到" in out
