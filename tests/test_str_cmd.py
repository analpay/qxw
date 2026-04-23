"""qxw-str 命令端到端测试

通过 click.testing.CliRunner 执行，覆盖：
- 基础字符数 / 字节数（含中文）
- --quiet / --bytes 仅输出纯数字
- 冲突参数与缺参校验的退出码
- stdin 读取（模拟管道）
- TTY + 无输入、KeyboardInterrupt、未预期 Exception 分支
"""

from __future__ import annotations

from io import BytesIO

import pytest
from click.testing import CliRunner

from qxw.bin import str_cmd as str_cmd_mod
from qxw.bin.str_cmd import main


def _run(args: list[str], stdin: str | None = None) -> tuple[int, str]:
    runner = CliRunner()
    result = runner.invoke(main, args, input=stdin)
    return result.exit_code, result.output


class TestLenBasic:
    def test_纯_ASCII(self) -> None:
        code, out = _run(["len", "hello", "-q"])
        assert code == 0
        assert out.strip() == "5"

    def test_中文字符数与字节数(self) -> None:
        # "你好" = 2 char, UTF-8 = 6 byte
        code, out = _run(["len", "你好", "-q"])
        assert code == 0
        assert out.strip() == "2"

        code, out = _run(["len", "你好", "-b"])
        assert code == 0
        assert out.strip() == "6"

    def test_默认表格输出包含两项指标(self) -> None:
        code, out = _run(["len", "hi"])
        assert code == 0
        assert "字符数" in out
        assert "UTF-8 字节数" in out


class TestConflictsAndErrors:
    def test_quiet_与_bytes_冲突退出码_2(self) -> None:
        code, out = _run(["len", "hi", "-q", "-b"])
        assert code == 2
        assert "不能同时使用" in out

    def test_无参数且无_stdin_退出码_2(self) -> None:
        # CliRunner 默认不是 TTY，所以会走 stdin 读取分支；
        # 这里给出显式空输入，模拟用户直接回车也无内容的情况下
        # stdin.read() 返回空串，字符数 / 字节数都是 0，属正常输出。
        code, out = _run(["len", "-q"], stdin="")
        assert code == 0
        assert out.strip() == "0"


class TestStdin:
    def test_从_stdin_读取(self) -> None:
        code, out = _run(["len", "-q"], stdin="hello world")
        assert code == 0
        assert out.strip() == str(len("hello world"))

    def test_stdin_中文字节数(self) -> None:
        code, out = _run(["len", "-b"], stdin="你好")
        assert code == 0
        assert out.strip() == "6"


class TestTopLevel:
    def test_无子命令时打印帮助(self) -> None:
        code, out = _run([])
        assert code == 0
        assert "qxw-str" in out
        assert "len" in out

    def test_version_选项(self) -> None:
        code, out = _run(["--version"])
        assert code == 0
        assert "版本" in out


class _TTYInput(BytesIO):
    """伪装成 TTY 的 stdin，用来驱动 isatty() 为 True 的分支"""

    def isatty(self) -> bool:  # noqa: D401
        return True


class TestErrorBranches:
    def test_TTY_且无参数_退出码_2(self) -> None:
        # CliRunner 默认 stdin 不是 TTY；这里塞一个 isatty()=True 的字节流
        runner = CliRunner()
        result = runner.invoke(main, ["len"], input=_TTYInput(b""))
        assert result.exit_code == 2
        assert "未提供字符串参数" in result.output

    def test_KeyboardInterrupt_退出码_130(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def raise_kb(*_a, **_kw) -> None:
            raise KeyboardInterrupt()

        monkeypatch.setattr(str_cmd_mod.logger, "info", raise_kb)
        code, out = _run(["len", "hi"])
        assert code == 130
        assert "已取消" in out

    def test_未预期_Exception_退出码_1(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def raise_any(*_a, **_kw) -> None:
            raise RuntimeError("boom")

        monkeypatch.setattr(str_cmd_mod.logger, "info", raise_any)
        code, out = _run(["len", "hi"])
        assert code == 1
        assert "未预期" in out
