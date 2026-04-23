"""qxw 主入口（qxw.bin.commands）单元测试

覆盖：
- _collect_commands：包未安装、load 失败、过滤非 qxw-*/非 console_scripts、help 去多行
- main group：无子命令打印帮助
- list 子命令：空列表提示、QxwError/KeyboardInterrupt/Exception 分支、表格渲染
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError

import pytest
from click.testing import CliRunner

from qxw.bin import commands as commands_mod
from qxw.library.base.exceptions import QxwError


def _run(args: list[str]) -> tuple[int, str]:
    runner = CliRunner()
    result = runner.invoke(commands_mod.main, args)
    return result.exit_code, result.output


class _FakeEP:
    def __init__(self, name: str, group: str = "console_scripts", loader=None) -> None:
        self.name = name
        self.group = group
        self._loader = loader

    def load(self):
        if self._loader is None:
            raise RuntimeError("load failed")
        return self._loader()


class _FakeDist:
    def __init__(self, eps) -> None:
        self.entry_points = eps


class TestCollectCommands:
    def test_qxw_包未安装_返回空列表(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def raise_not_found(_: str) -> None:
            raise PackageNotFoundError("missing")

        monkeypatch.setattr(commands_mod, "distribution", raise_not_found)
        assert commands_mod._collect_commands() == []

    def test_过滤非_console_scripts_与_qxw_自身(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class FakeCmd:
            help = "示例帮助\n第二行应被丢弃"

        eps = [
            _FakeEP("qxw", "console_scripts", loader=lambda: FakeCmd()),  # 自身，过滤
            _FakeEP("qxw-abc", "other", loader=lambda: FakeCmd()),  # 非 console_scripts，过滤
            _FakeEP("foo", "console_scripts", loader=lambda: FakeCmd()),  # 非 qxw- 前缀，过滤
            _FakeEP("qxw-real", "console_scripts", loader=lambda: FakeCmd()),  # 保留
        ]
        monkeypatch.setattr(commands_mod, "distribution", lambda _: _FakeDist(eps))

        result = commands_mod._collect_commands()
        assert result == [("qxw-real", "示例帮助")]

    def test_load_失败的命令仍被收录__help_为空(self, monkeypatch: pytest.MonkeyPatch) -> None:
        eps = [_FakeEP("qxw-bad", "console_scripts", loader=None)]  # loader None => load 抛错
        monkeypatch.setattr(commands_mod, "distribution", lambda _: _FakeDist(eps))

        result = commands_mod._collect_commands()
        assert result == [("qxw-bad", "")]

    def test_load_成功但_help_缺失或为空(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class NoHelpCmd:
            pass

        class EmptyHelpCmd:
            help = ""

        eps = [
            _FakeEP("qxw-a", loader=lambda: NoHelpCmd()),
            _FakeEP("qxw-b", loader=lambda: EmptyHelpCmd()),
        ]
        monkeypatch.setattr(commands_mod, "distribution", lambda _: _FakeDist(eps))
        result = commands_mod._collect_commands()
        assert result == [("qxw-a", ""), ("qxw-b", "")]

    def test_按命令名排序(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class H:
            help = "h"

        eps = [
            _FakeEP("qxw-zzz", loader=lambda: H()),
            _FakeEP("qxw-aaa", loader=lambda: H()),
            _FakeEP("qxw-mmm", loader=lambda: H()),
        ]
        monkeypatch.setattr(commands_mod, "distribution", lambda _: _FakeDist(eps))
        names = [n for n, _ in commands_mod._collect_commands()]
        assert names == ["qxw-aaa", "qxw-mmm", "qxw-zzz"]


class TestMainGroup:
    def test_无子命令时打印帮助(self) -> None:
        code, out = _run([])
        assert code == 0
        assert "QXW" in out
        assert "list" in out  # 帮助中应列出 list 子命令

    def test_version_选项(self) -> None:
        code, out = _run(["--version"])
        assert code == 0
        assert "版本" in out


class TestListSubcommand:
    def test_空命令提示未找到(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(commands_mod, "_collect_commands", lambda: [])
        code, out = _run(["list"])
        assert code == 0
        assert "未找到" in out

    def test_QxwError_退出码透传(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def boom() -> list:
            raise QxwError("自定义错误", exit_code=42)

        monkeypatch.setattr(commands_mod, "_collect_commands", boom)
        code, out = _run(["list"])
        assert code == 42
        assert "自定义错误" in out

    def test_KeyboardInterrupt_退出_130(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def boom() -> list:
            raise KeyboardInterrupt()

        monkeypatch.setattr(commands_mod, "_collect_commands", boom)
        code, out = _run(["list"])
        assert code == 130
        assert "已取消" in out

    def test_通用异常退出_1(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def boom() -> list:
            raise RuntimeError("explode")

        monkeypatch.setattr(commands_mod, "_collect_commands", boom)
        code, out = _run(["list"])
        assert code == 1
        assert "未预期" in out

    def test_有命令时输出表格__包含版本与命令名(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            commands_mod,
            "_collect_commands",
            lambda: [("qxw-foo", "foo 说明"), ("qxw-bar", "bar 说明")],
        )
        code, out = _run(["list"])
        assert code == 0
        assert "qxw-foo" in out
        assert "qxw-bar" in out
        assert "共 2 个命令" in out
