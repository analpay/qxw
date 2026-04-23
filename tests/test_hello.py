"""qxw hello 子命令单元测试

覆盖：
- CLI 各异常分支（QxwError / KeyboardInterrupt / Exception）
- _ensure_env 的已就绪/未就绪两条路径
- --name 参数传递到 HelloConfig
"""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from qxw.bin import hello as hello_mod
from qxw.library.base.exceptions import QxwError


def _run(args: list[str]) -> tuple[int, str]:
    runner = CliRunner()
    result = runner.invoke(hello_mod.main, args)
    return result.exit_code, result.output


class TestHelloCLI:
    def test_默认输出包含问候(self) -> None:
        code, out = _run([])
        assert code == 0
        assert "世界" in out

    def test_自定义_name(self) -> None:
        code, out = _run(["--name", "Alice"])
        assert code == 0
        assert "Alice" in out

    def test_QxwError_退出码透传(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def raise_err() -> None:
            raise QxwError("测试错误", exit_code=7)

        monkeypatch.setattr(hello_mod, "_ensure_env", raise_err)
        code, out = _run([])
        assert code == 7
        assert "测试错误" in out

    def test_KeyboardInterrupt_退出_130(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def raise_kb() -> None:
            raise KeyboardInterrupt()

        monkeypatch.setattr(hello_mod, "_ensure_env", raise_kb)
        code, out = _run([])
        assert code == 130
        assert "已取消" in out

    def test_未预期异常退出_1(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def raise_any() -> None:
            raise RuntimeError("explode")

        monkeypatch.setattr(hello_mod, "_ensure_env", raise_any)
        code, out = _run([])
        assert code == 1
        assert "未预期" in out

    def test_tui_模式会实例化_HelloApp_并运行(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: dict[str, object] = {}

        class FakeApp:
            def __init__(self, config) -> None:
                calls["config"] = config

            def run(self) -> None:
                calls["ran"] = True

        monkeypatch.setattr(hello_mod, "HelloApp", FakeApp)
        monkeypatch.setattr(hello_mod, "_ensure_env", lambda: None)

        code, _ = _run(["--tui", "--name", "Bob"])
        assert code == 0
        assert calls.get("ran") is True
        assert calls["config"].name == "Bob"
        assert calls["config"].tui_mode is True


class TestEnsureEnv:
    def test_已就绪时直接返回_不写入任何目录(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        import qxw.config.init as init_mod

        class FakeStatus:
            all_ready = True

        called: dict[str, bool] = {}

        def fake_init() -> None:
            called["init"] = True

        monkeypatch.setattr(init_mod, "check_env", lambda: FakeStatus())
        monkeypatch.setattr(init_mod, "init_env", fake_init)

        hello_mod._ensure_env()  # 不抛且不触发 init_env
        assert "init" not in called

    def test_未就绪时打印初始化项(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import qxw.config.init as init_mod

        class FakeStatus:
            all_ready = False

        class FakeResult:
            initialized_items = ["配置目录", "日志目录"]

        monkeypatch.setattr(init_mod, "check_env", lambda: FakeStatus())
        monkeypatch.setattr(init_mod, "init_env", lambda: FakeResult())

        runner = CliRunner()
        result = runner.invoke(hello_mod.main, [])
        assert result.exit_code == 0
        assert "配置目录" in result.output
        assert "日志目录" in result.output
        assert "初始化完成" in result.output


class TestHelloConfig:
    def test_默认值(self) -> None:
        cfg = hello_mod.HelloConfig()
        assert cfg.name == "世界"
        assert cfg.tui_mode is False

    def test_非法类型被_Pydantic_拒绝(self) -> None:
        with pytest.raises(Exception):
            hello_mod.HelloConfig(name=123, tui_mode="not_bool")  # type: ignore[arg-type]


class TestHelloApp:
    def test_config_被存入_app(self) -> None:
        cfg = hello_mod.HelloConfig(name="Bob", tui_mode=True)
        app = hello_mod.HelloApp(cfg)
        assert app.config is cfg
        assert app.SUB_TITLE.startswith("v")

    def test_action_toggle_dark_切换_theme(self) -> None:
        cfg = hello_mod.HelloConfig()
        app = hello_mod.HelloApp(cfg)
        app.theme = "textual-light"
        app.action_toggle_dark()
        assert app.theme == "textual-dark"
        app.action_toggle_dark()
        assert app.theme == "textual-light"

    def test_compose_通过_pilot_运行(self) -> None:
        """用 Pilot 驱动 HelloApp，确保 compose/Footer/quit 路径能跑通"""
        import asyncio

        cfg = hello_mod.HelloConfig(name="Tester")

        async def _go() -> None:
            app = hello_mod.HelloApp(cfg)
            async with app.run_test() as pilot:
                await pilot.pause()
                # 触发切主题
                await pilot.press("d")
                await pilot.pause()
                # 退出
                await pilot.press("q")

        asyncio.run(_go())
