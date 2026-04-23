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
