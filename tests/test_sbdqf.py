"""qxw sbdqf 子命令单元测试

覆盖：
- _build_frames 结构
- CLI 参数校验错误（-r 0 / -d 0）
- QxwError / KeyboardInterrupt / 通用 Exception 分支
- 正常路径：curses.wrapper 被调用
"""

from __future__ import annotations

import curses

import pytest
from click.testing import CliRunner

from qxw.bin import sbdqf as sbdqf_mod
from qxw.library.base.exceptions import QxwError


def _run(args: list[str]) -> tuple[int, str]:
    runner = CliRunner()
    result = runner.invoke(sbdqf_mod.main, args)
    return result.exit_code, result.output


class TestBuildFrames:
    def test_生成_2_帧(self) -> None:
        frames = sbdqf_mod._build_frames()
        assert len(frames) == 2
        for frame in frames:
            assert isinstance(frame, list)
            assert all(isinstance(line, str) for line in frame)

    def test_每帧包含老鼠身体(self) -> None:
        frames = sbdqf_mod._build_frames()
        for frame in frames:
            text = "\n".join(frame)
            assert "@@" in text  # 眼睛
            assert "mimi" in text  # 气泡

    def test_两帧尾巴不同(self) -> None:
        frames = sbdqf_mod._build_frames()
        # 最后一行（尾巴）应不同
        assert frames[0][-1] != frames[1][-1]


class TestCLIArgValidation:
    def test_rounds_为_0_拒绝(self) -> None:
        code, _ = _run(["-r", "0"])
        assert code == 2

    def test_duration_为_0_拒绝(self) -> None:
        code, _ = _run(["-d", "0"])
        assert code == 2

    def test_rounds_为负数_拒绝(self) -> None:
        code, _ = _run(["-r", "-5"])
        assert code == 2

    def test_rounds_非整数_拒绝(self) -> None:
        code, _ = _run(["-r", "abc"])
        assert code == 2


class TestCLIErrorBranches:
    def test_QxwError_被捕获并透传退出码(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def raise_err(_fn) -> None:
            raise QxwError("错啦", exit_code=9)

        monkeypatch.setattr(curses, "wrapper", raise_err)
        code, out = _run([])
        assert code == 9
        assert "错啦" in out

    def test_KeyboardInterrupt_静默退出_0(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def raise_kb(_fn) -> None:
            raise KeyboardInterrupt()

        monkeypatch.setattr(curses, "wrapper", raise_kb)
        code, _ = _run([])
        # KeyboardInterrupt 分支是 pass，等同于正常退出
        assert code == 0

    def test_通用异常退出_1(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def raise_any(_fn) -> None:
            raise RuntimeError("boom")

        monkeypatch.setattr(curses, "wrapper", raise_any)
        code, out = _run([])
        assert code == 1
        assert "未预期" in out


class TestCLIHappyWrap:
    def test_无参数调用_不抛错(self, monkeypatch: pytest.MonkeyPatch) -> None:
        called: dict[str, bool] = {}

        def fake_wrapper(fn) -> None:
            called["wrapped"] = True  # 不真正调 fn，避免 curses 初始化

        monkeypatch.setattr(curses, "wrapper", fake_wrapper)
        code, _ = _run([])
        assert code == 0
        assert called["wrapped"] is True


class TestRunAnimation:
    def test_屏幕过小直接返回(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """mouse_height 约 7 行，屏幕 5 行时应提前 return，且不进入单次扫描"""
        monkeypatch.setattr(curses, "curs_set", lambda _v: None)

        scan_called: dict[str, bool] = {}

        def spy_scan(*a, **k) -> bool:
            scan_called["in"] = True
            return False

        monkeypatch.setattr(sbdqf_mod, "_run_single_pass", spy_scan)

        class FakeStdscr:
            def getmaxyx(self) -> tuple[int, int]:
                return (5, 80)

            def nodelay(self, _v: bool) -> None:
                return None

            def timeout(self, _v: int) -> None:
                return None

        out = sbdqf_mod._run_animation(FakeStdscr(), rounds=1, duration=None)  # type: ignore[arg-type]
        assert out is None
        assert "in" not in scan_called  # 提前 return，不进 single_pass
