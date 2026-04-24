"""qxw-math 命令端到端测试

通过 click.testing.CliRunner 执行，覆盖：
- 基础表达式输出（表格 / 纯数字）
- 不合法表达式的退出码 与 错误文本
- stdin 读取（模拟管道）
- TTY + 无输入、KeyboardInterrupt、未预期 Exception 分支
"""

from __future__ import annotations

from io import BytesIO

import pytest
from click.testing import CliRunner

from qxw.bin import math as math_mod
from qxw.bin.math import main


def _run(args: list[str], stdin: str | None = None) -> tuple[int, str]:
    runner = CliRunner()
    result = runner.invoke(main, args, input=stdin)
    return result.exit_code, result.output


# ============================================================
# 错误与边界
# ============================================================


class TestInputErrors:
    def test_空字符串参数_退出码_6(self) -> None:
        # ValidationError 的 exit_code 为 6
        code, out = _run(["", "-q"])
        assert code == 6
        assert "表达式不能为空" in out

    def test_非法语法_退出码_6(self) -> None:
        code, out = _run(["1 +", "-q"])
        assert code == 6
        assert "语法错误" in out

    def test_除零_退出码_6(self) -> None:
        code, out = _run(["1/0", "-q"])
        assert code == 6
        assert "除数不能为 0" in out

    def test_负数开方_退出码_6(self) -> None:
        code, out = _run(["sqrt(-4)", "-q"])
        assert code == 6
        assert "开方运算不支持负数" in out

    def test_不支持的函数_退出码_6(self) -> None:
        code, out = _run(["abs(-1)", "-q"])
        assert code == 6
        assert "不支持的函数" in out

    def test_非法节点_退出码_6(self) -> None:
        code, out = _run(["x+1", "-q"])
        assert code == 6
        assert "不支持" in out


# ============================================================
# stdin 分支
# ============================================================


class TestStdin:
    def test_从_stdin_读取并求值(self) -> None:
        code, out = _run(["-q"], stdin="2**10")
        assert code == 0
        assert out.strip() == "1024"

    def test_stdin_带换行和空白(self) -> None:
        code, out = _run(["-q"], stdin="  (1+2)*3  \n")
        assert code == 0
        assert out.strip() == "9"

    def test_stdin_空输入走空表达式错误(self) -> None:
        code, out = _run(["-q"], stdin="")
        assert code == 6
        assert "表达式不能为空" in out


# ============================================================
# 输出格式
# ============================================================


class TestOutputFormat:
    def test_默认表格输出_包含字段与结果(self) -> None:
        code, out = _run(["1+2*3"])
        assert code == 0
        assert "表达式" in out
        assert "结果" in out
        assert "7" in out

    def test_quiet_模式_仅输出数字_整数开方(self) -> None:
        code, out = _run(["sqrt(9)", "-q"])
        assert code == 0
        assert out.strip() == "3"

    def test_quiet_模式_次方_shell_需引号(self) -> None:
        code, out = _run(["2^16", "-q"])
        assert code == 0
        assert out.strip() == "65536"

    def test_quiet_模式_浮点结果保留小数(self) -> None:
        code, out = _run(["sqrt(2)", "-q"])
        assert code == 0
        # 浮点结果不做截断
        assert out.strip().startswith("1.4142")


# ============================================================
# 顶层 / 错误分支
# ============================================================


class _TTYInput(BytesIO):
    """伪装成 TTY 的 stdin，用来驱动 isatty() 为 True 的分支"""

    def isatty(self) -> bool:  # noqa: D401
        return True


class TestTopLevel:
    def test_version_选项(self) -> None:
        code, out = _run(["--version"])
        assert code == 0
        assert "版本" in out

    def test_TTY_且无参数_退出码_2(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, [], input=_TTYInput(b""))
        assert result.exit_code == 2
        assert "未提供表达式参数" in result.output

    def test_KeyboardInterrupt_退出码_130(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def raise_kb(*_a, **_kw) -> None:
            raise KeyboardInterrupt()

        monkeypatch.setattr(math_mod.logger, "info", raise_kb)
        code, out = _run(["1+1"])
        assert code == 130
        assert "已取消" in out

    def test_未预期_Exception_退出码_1(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def raise_any(*_a, **_kw) -> None:
            raise RuntimeError("boom")

        monkeypatch.setattr(math_mod.logger, "info", raise_any)
        code, out = _run(["1+1"])
        assert code == 1
        assert "未预期" in out
