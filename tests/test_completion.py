"""qxw completion 子命令单元测试

覆盖：
- _detect_shell：显式/auto/未知
- _rc_path：zsh、bash（Linux/Darwin）各分支
- _iter_qxw_commands：包未安装、load 失败、过滤
- rc 文件读写（_rc_has_marker / _append_to_rc / _remove_from_rc）
- show / install / uninstall / status 的 QxwError / KeyboardInterrupt / Exception 分支
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from pathlib import Path

import pytest
from click.testing import CliRunner

from qxw.bin import completion as comp
from qxw.library.base.exceptions import QxwError


def _run(args: list[str]) -> tuple[int, str]:
    runner = CliRunner()
    result = runner.invoke(comp.main, args)
    return result.exit_code, result.output


class _EP:
    def __init__(self, name: str, group: str = "console_scripts", loader=None) -> None:
        self.name = name
        self.group = group
        self._loader = loader

    def load(self):
        if self._loader is None:
            raise RuntimeError("load failed")
        return self._loader()


class _Dist:
    def __init__(self, eps) -> None:
        self.entry_points = eps


class TestDetectShell:
    def test_显式_zsh(self) -> None:
        assert comp._detect_shell("zsh") == "zsh"

    def test_显式_bash(self) -> None:
        assert comp._detect_shell("bash") == "bash"

    def test_auto_无_SHELL_报错(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SHELL", raising=False)
        with pytest.raises(QxwError, match="无法"):
            comp._detect_shell("auto")

    def test_auto_SHELL_识别_zsh(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SHELL", "/bin/zsh")
        assert comp._detect_shell("auto") == "zsh"

    def test_auto_SHELL_识别_bash(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SHELL", "/usr/local/bin/bash")
        assert comp._detect_shell("auto") == "bash"

    def test_auto_SHELL_不支持的_shell_报错(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SHELL", "/usr/bin/fish")
        with pytest.raises(QxwError, match="无法"):
            comp._detect_shell("auto")

    def test_不支持的显式_shell(self) -> None:
        with pytest.raises(QxwError, match="不支持"):
            comp._detect_shell("fish")


class TestRcPath:
    def test_zsh_指向_zshrc(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        assert comp._rc_path("zsh") == tmp_path / ".zshrc"

    def test_bash_Linux_指向_bashrc(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setattr(comp.platform, "system", lambda: "Linux")
        assert comp._rc_path("bash") == tmp_path / ".bashrc"

    def test_bash_Darwin_优先_bash_profile(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setattr(comp.platform, "system", lambda: "Darwin")
        (tmp_path / ".bash_profile").write_text("")
        assert comp._rc_path("bash") == tmp_path / ".bash_profile"

    def test_bash_Darwin_仅_bashrc_存在(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setattr(comp.platform, "system", lambda: "Darwin")
        (tmp_path / ".bashrc").write_text("")
        assert comp._rc_path("bash") == tmp_path / ".bashrc"

    def test_bash_Darwin_都不存在_回退_bash_profile(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setattr(comp.platform, "system", lambda: "Darwin")
        assert comp._rc_path("bash") == tmp_path / ".bash_profile"

    def test_不支持的_shell(self) -> None:
        with pytest.raises(QxwError, match="不支持"):
            comp._rc_path("fish")


class TestIterQxwCommands:
    def test_包未安装_抛_QxwError(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def raise_nf(_: str) -> None:
            raise PackageNotFoundError

        monkeypatch.setattr(comp, "distribution", raise_nf)
        with pytest.raises(QxwError, match="未安装"):
            comp._iter_qxw_commands()

    def test_load_失败归入_skipped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        eps = [
            _EP("qxw-good", loader=lambda: "ok"),
            _EP("qxw-bad", loader=None),  # load 抛错
        ]
        monkeypatch.setattr(comp, "distribution", lambda _: _Dist(eps))
        loaded, skipped = comp._iter_qxw_commands()
        assert [n for n, _ in loaded] == ["qxw-good"]
        assert [n for n, _ in skipped] == ["qxw-bad"]
        assert "RuntimeError" in skipped[0][1]

    def test_过滤非_qxw_前缀与非_console_scripts(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        eps = [
            _EP("foo", loader=lambda: "ok"),
            _EP("qxw-gui", group="gui_scripts", loader=lambda: "ok"),
            _EP("qxw-real", loader=lambda: "ok"),
        ]
        monkeypatch.setattr(comp, "distribution", lambda _: _Dist(eps))
        loaded, skipped = comp._iter_qxw_commands()
        assert [n for n, _ in loaded] == ["qxw-real"]
        assert skipped == []

    def test_按名字排序(self, monkeypatch: pytest.MonkeyPatch) -> None:
        eps = [
            _EP("qxw-z", loader=lambda: "z"),
            _EP("qxw-a", loader=lambda: "a"),
            _EP("qxw-m", loader=lambda: "m"),
        ]
        monkeypatch.setattr(comp, "distribution", lambda _: _Dist(eps))
        loaded, _ = comp._iter_qxw_commands()
        assert [n for n, _ in loaded] == ["qxw-a", "qxw-m", "qxw-z"]


class TestRcMarkerHelpers:
    def test_marker_文件不存在(self, tmp_path: Path) -> None:
        assert comp._rc_has_marker(tmp_path / "nope") is False

    def test_marker_无_marker(self, tmp_path: Path) -> None:
        rc = tmp_path / ".rc"
        rc.write_text("alias ll=ls\n")
        assert comp._rc_has_marker(rc) is False

    def test_marker_有_marker(self, tmp_path: Path) -> None:
        rc = tmp_path / ".rc"
        rc.write_text(f"{comp.MARKER_BEGIN}\nfoo\n{comp.MARKER_END}\n")
        assert comp._rc_has_marker(rc) is True

    def test_marker_读文件_OSError_返回_False(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rc = tmp_path / ".rc"
        rc.write_text("foo")
        orig_read = Path.read_text

        def fail_read(self, *a, **k):
            if self == rc:
                raise OSError("denied")
            return orig_read(self, *a, **k)

        monkeypatch.setattr(Path, "read_text", fail_read)
        assert comp._rc_has_marker(rc) is False


class TestAppendToRc:
    def test_新文件直接创建(self, tmp_path: Path) -> None:
        rc = tmp_path / ".rc"
        comp._append_to_rc(rc, "zsh")
        text = rc.read_text()
        assert comp.MARKER_BEGIN in text
        assert comp.MARKER_END in text
        assert "source" in text

    def test_已有内容_不以换行结尾_会补齐(self, tmp_path: Path) -> None:
        rc = tmp_path / ".rc"
        rc.write_text("alias ll=ls")  # 无结尾 \n
        comp._append_to_rc(rc, "bash")
        text = rc.read_text()
        assert text.startswith("alias ll=ls\n")
        assert comp.MARKER_BEGIN in text


class TestRemoveFromRc:
    def test_文件不存在(self, tmp_path: Path) -> None:
        assert comp._remove_from_rc(tmp_path / "nope") is False

    def test_无_marker(self, tmp_path: Path) -> None:
        rc = tmp_path / ".rc"
        rc.write_text("alias ll=ls\n")
        assert comp._remove_from_rc(rc) is False
        assert rc.read_text() == "alias ll=ls\n"

    def test_完整块被移除(self, tmp_path: Path) -> None:
        rc = tmp_path / ".rc"
        original = "alias ll=ls\n"
        block = f"\n{comp.MARKER_BEGIN}\nsource x\n{comp.MARKER_END}\n"
        rc.write_text(original + block)
        assert comp._remove_from_rc(rc) is True
        assert "qxw-completion" not in rc.read_text()
        assert rc.read_text().rstrip() == "alias ll=ls"

    def test_begin_缺_end_不修改(self, tmp_path: Path) -> None:
        rc = tmp_path / ".rc"
        rc.write_text(f"{comp.MARKER_BEGIN}\nsource x\n")
        assert comp._remove_from_rc(rc) is False

    def test_块在文件末尾_且无末尾换行(self, tmp_path: Path) -> None:
        rc = tmp_path / ".rc"
        rc.write_text(f"alias x=y\n\n{comp.MARKER_BEGIN}\nsource z\n{comp.MARKER_END}")
        assert comp._remove_from_rc(rc) is True
        assert rc.read_text().endswith("\n")


class TestShowCommand:
    def test_auto_SHELL_未识别_退出非_0(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SHELL", raising=False)
        code, out = _run(["show"])
        assert code != 0
        assert "无法" in out

    def test_无命令时退出非_0(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SHELL", "/bin/zsh")
        monkeypatch.setattr(comp, "_iter_qxw_commands", lambda: ([], []))
        code, out = _run(["show"])
        assert code != 0
        assert "未找到" in out

    def test_KeyboardInterrupt_退出_130(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SHELL", "/bin/zsh")

        def raise_kb():
            raise KeyboardInterrupt()

        monkeypatch.setattr(comp, "_iter_qxw_commands", raise_kb)
        code, out = _run(["show"])
        assert code == 130
        assert "已取消" in out

    def test_通用异常退出_1(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SHELL", "/bin/zsh")

        def raise_any():
            raise RuntimeError("boom")

        monkeypatch.setattr(comp, "_iter_qxw_commands", raise_any)
        code, out = _run(["show"])
        assert code == 1
        assert "未预期" in out


class TestInstallCommand:
    def test_无命令_退出非_0(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("SHELL", "/bin/zsh")
        monkeypatch.setattr(comp, "COMPLETIONS_DIR", tmp_path / "completions")
        monkeypatch.setattr(comp, "_iter_qxw_commands", lambda: ([], []))
        code, _ = _run(["install", "-y"])
        assert code != 0

    def test_QxwError_透传退出码(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SHELL", "/bin/zsh")

        def raise_e():
            raise QxwError("安装失败", exit_code=9)

        monkeypatch.setattr(comp, "_iter_qxw_commands", raise_e)
        code, out = _run(["install", "-y"])
        assert code == 9
        assert "安装失败" in out

    def test_KeyboardInterrupt(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SHELL", "/bin/zsh")

        def raise_kb():
            raise KeyboardInterrupt()

        monkeypatch.setattr(comp, "_iter_qxw_commands", raise_kb)
        code, _ = _run(["install", "-y"])
        assert code == 130

    def test_Exception(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SHELL", "/bin/zsh")

        def raise_any():
            raise RuntimeError("boom")

        monkeypatch.setattr(comp, "_iter_qxw_commands", raise_any)
        code, _ = _run(["install", "-y"])
        assert code == 1


class TestUninstallCommand:
    def test_auto_未识别_退出非_0(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SHELL", raising=False)
        code, _ = _run(["uninstall", "-y"])
        assert code != 0

    def test_KeyboardInterrupt(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SHELL", "/bin/zsh")

        def raise_kb(_shell):
            raise KeyboardInterrupt()

        monkeypatch.setattr(comp, "_rc_path", raise_kb)
        code, _ = _run(["uninstall", "-y"])
        assert code == 130

    def test_Exception(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SHELL", "/bin/zsh")

        def raise_any(_shell):
            raise RuntimeError("boom")

        monkeypatch.setattr(comp, "_rc_path", raise_any)
        code, _ = _run(["uninstall", "-y"])
        assert code == 1


class TestStatusCommand:
    def test_auto_未识别_退出非_0(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SHELL", raising=False)
        code, _ = _run(["status"])
        assert code != 0

    def test_KeyboardInterrupt(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SHELL", "/bin/zsh")

        def raise_kb():
            raise KeyboardInterrupt()

        monkeypatch.setattr(comp, "_iter_qxw_commands", raise_kb)
        code, _ = _run(["status"])
        assert code == 130

    def test_Exception(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SHELL", "/bin/zsh")

        def raise_any():
            raise RuntimeError("boom")

        monkeypatch.setattr(comp, "_iter_qxw_commands", raise_any)
        code, _ = _run(["status"])
        assert code == 1


class TestMainGroup:
    def test_无子命令打印帮助(self) -> None:
        code, out = _run([])
        assert code == 0
        assert "补全" in out or "completion" in out

    def test_版本输出(self) -> None:
        code, out = _run(["--version"])
        assert code == 0
        assert "版本" in out


class TestGenerateSource:
    def test_不支持的_shell_抛_QxwError(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(comp, "get_completion_class", lambda _s: None)
        with pytest.raises(QxwError, match="补全支持"):
            comp._generate_source_for("zsh", "qxw-foo", object())
