"""qxw-image change 子命令的 Click 层测试

覆盖 CLI 选项校验 / 异常分支 / 扫描与跳过逻辑 / 端到端写出验证。
"""

from __future__ import annotations

import builtins
from pathlib import Path

import pytest
from click.testing import CliRunner
from PIL import Image

from qxw.bin import image as image_mod
from qxw.library.base.exceptions import QxwError


def _run(args: list[str]) -> tuple[int, str]:
    runner = CliRunner()
    result = runner.invoke(image_mod.main, args)
    return result.exit_code, result.output


def _make_jpeg(path: Path) -> None:
    img = Image.new("RGB", (16, 16), (120, 80, 60))
    img.putpixel((0, 0), (200, 100, 30))
    img.save(path, "JPEG", quality=90)


class TestBasic:
    def test_Pillow_缺失(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        real_import = builtins.__import__

        def fake(name, *a, **k):
            if name == "PIL":
                raise ImportError("no PIL")
            return real_import(name, *a, **k)

        monkeypatch.setattr(builtins, "__import__", fake)
        code, out = _run(["change", "-d", str(tmp_path)])
        assert code == 1
        assert "Pillow" in out

    def test_目录不存在(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(image_mod, "_require_pillow", lambda: None)
        code, _ = _run(["change", "-d", str(tmp_path / "nope")])
        assert code != 0

    def test_非法_intensity_click_拒绝(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(image_mod, "_require_pillow", lambda: None)
        code, _ = _run(["change", "-d", str(tmp_path), "-i", "extreme"])
        # click.Choice 会返回非 0（用法错误 2）
        assert code != 0

    @pytest.mark.parametrize("bad_q", ["0", "101", "-1"])
    def test_quality_超出范围_click_拒绝(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bad_q: str
    ) -> None:
        monkeypatch.setattr(image_mod, "_require_pillow", lambda: None)
        code, _ = _run(["change", "-d", str(tmp_path), "-q", bad_q])
        assert code != 0

    def test_空目录_无位图(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(image_mod, "_require_pillow", lambda: None)
        code, out = _run(["change", "-d", str(tmp_path)])
        assert code == 0
        assert "未找到" in out


class TestErrorBranches:
    def test_QxwError_透传(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        def raise_err() -> None:
            raise QxwError("change 错", exit_code=7)

        monkeypatch.setattr(image_mod, "_require_pillow", raise_err)
        code, out = _run(["change", "-d", str(tmp_path)])
        assert code == 7
        assert "change 错" in out

    def test_KeyboardInterrupt(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        def raise_kb() -> None:
            raise KeyboardInterrupt()

        monkeypatch.setattr(image_mod, "_require_pillow", raise_kb)
        code, out = _run(["change", "-d", str(tmp_path)])
        assert code == 130
        assert "已取消" in out

    def test_通用异常(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        def raise_any() -> None:
            raise RuntimeError("boom")

        monkeypatch.setattr(image_mod, "_require_pillow", raise_any)
        code, out = _run(["change", "-d", str(tmp_path)])
        assert code == 1
        assert "未预期" in out


class TestSkipLogic:
    def test_已存在输出_no_overwrite_被跳过(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(image_mod, "_require_pillow", lambda: None)
        src = tmp_path / "a.jpg"
        _make_jpeg(src)
        out_dir = tmp_path / "changed"
        out_dir.mkdir()
        _make_jpeg(out_dir / "a.jpg")  # 预先放一个同名文件
        mtime_before = (out_dir / "a.jpg").stat().st_mtime
        code, out = _run(["change", "-d", str(tmp_path)])
        assert code == 0
        # 跳过计数应显示
        assert "跳过" in out
        assert (out_dir / "a.jpg").stat().st_mtime == mtime_before

    def test_overwrite_时覆盖(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(image_mod, "_require_pillow", lambda: None)
        src = tmp_path / "a.jpg"
        _make_jpeg(src)
        out_dir = tmp_path / "changed"
        out_dir.mkdir()
        existing = out_dir / "a.jpg"
        existing.write_bytes(b"placeholder")
        code, _ = _run(["change", "-d", str(tmp_path), "--overwrite"])
        assert code == 0
        # 应被真正的 JPEG 替换（至少比占位字节大）
        assert existing.read_bytes() != b"placeholder"
        assert existing.stat().st_size > 100

    def test_递归扫描跳过输出目录内的产物(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(image_mod, "_require_pillow", lambda: None)
        src = tmp_path / "a.jpg"
        _make_jpeg(src)
        out_dir = tmp_path / "changed"
        out_dir.mkdir()
        # 输出目录里预放一个图；递归扫描会看到它但必须跳过
        _make_jpeg(out_dir / "leftover.jpg")
        code, out = _run(["change", "-d", str(tmp_path), "-r"])
        assert code == 0
        # leftover.jpg 不应被再处理到 changed/changed/
        assert not (out_dir / "changed").exists()


class TestEndToEnd:
    def test_实际处理一张图_端到端(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(image_mod, "_require_pillow", lambda: None)
        src = tmp_path / "a.jpg"
        _make_jpeg(src)
        code, out = _run(["change", "-d", str(tmp_path), "-i", "subtle"])
        assert code == 0
        # 输出存在且可被 PIL 打开
        dst = tmp_path / "changed" / "a.jpg"
        assert dst.exists()
        with Image.open(dst) as img:
            assert img.size == (16, 16)
            assert img.mode == "RGB"

    def test_HDR_开关_端到端不崩(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(image_mod, "_require_pillow", lambda: None)
        src = tmp_path / "a.jpg"
        _make_jpeg(src)
        code, _ = _run(["change", "-d", str(tmp_path), "--hdr"])
        assert code == 0
        assert (tmp_path / "changed" / "a.jpg").exists()

    def test_no_preserve_exif_端到端(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(image_mod, "_require_pillow", lambda: None)
        src = tmp_path / "a.jpg"
        _make_jpeg(src)
        code, _ = _run([
            "change", "-d", str(tmp_path), "--no-preserve-exif",
        ])
        assert code == 0

    def test_workers_1_串行路径(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(image_mod, "_require_pillow", lambda: None)
        for name in ("a.jpg", "b.jpg"):
            _make_jpeg(tmp_path / name)
        code, _ = _run(["change", "-d", str(tmp_path), "-j", "1"])
        assert code == 0
        assert (tmp_path / "changed" / "a.jpg").exists()
        assert (tmp_path / "changed" / "b.jpg").exists()

    def test_失败文件被统计但不中断(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(image_mod, "_require_pillow", lambda: None)
        _make_jpeg(tmp_path / "ok.jpg")
        # 假的 .jpg 坏文件：PIL 解码时会抛
        (tmp_path / "bad.jpg").write_bytes(b"not a real jpeg")
        code, out = _run(["change", "-d", str(tmp_path)])
        assert code == 0
        assert "失败" in out or "1" in out


class TestMainHelp:
    def test_change_出现在主命令组帮助(self) -> None:
        code, out = _run([])
        assert code == 0
        assert "change" in out

    def test_change_help_包含关键词(self) -> None:
        code, out = _run(["change", "--help"])
        assert code == 0
        for kw in ("intensity", "hdr", "preserve-exif", "subtle", "balanced", "punchy"):
            assert kw in out, f"--help 缺少关键词 {kw}"
