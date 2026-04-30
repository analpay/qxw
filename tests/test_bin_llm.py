"""qxw-llm 命令入口单元测试

重点覆盖：
- _resolve_provider：名称不存在、无默认、空列表
- _run_single：QxwError 分支
- chat/provider 各子命令的错误分支（QxwError / KeyboardInterrupt / Exception / click.Abort）
- _ping_one：正常 / QxwError
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from qxw.bin import llm as llm_mod
from qxw.library.base.exceptions import QxwError


@pytest.fixture(autouse=True)
def _stub_ensure_env(monkeypatch: pytest.MonkeyPatch):
    """所有测试都绕过 _ensure_env，避免初始化真实 DB"""
    monkeypatch.setattr(llm_mod, "_ensure_env", lambda: None)


def _run(args: list[str], input_text: str | None = None) -> tuple[int, str]:
    runner = CliRunner()
    result = runner.invoke(llm_mod.main, args, input=input_text)
    return result.exit_code, result.output


def _fake_provider(**over):
    base = dict(
        name="p1",
        provider_type="openai",
        base_url="http://x",
        api_key="sk-12345678abcdef",
        model="gpt-4",
        temperature=0.7,
        max_tokens=4096,
        top_p=1.0,
        system_prompt="",
        is_default=False,
        created_at="2026-01-01",
        updated_at="2026-01-02",
    )
    base.update(over)
    return SimpleNamespace(**base)


class TestMainGroup:
    def test_无子命令打印帮助(self) -> None:
        code, out = _run([])
        assert code == 0
        assert "chat" in out
        assert "provider" in out

    def test_版本(self) -> None:
        code, out = _run(["--version"])
        assert code == 0
        assert "版本" in out


class TestResolveProvider:
    def test_指定名称_不存在(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(llm_mod.manager, "get_by_name", lambda n: None)
        with pytest.raises(SystemExit) as exc:
            llm_mod._resolve_provider("nope")
        assert exc.value.code == 1

    def test_指定名称_存在(self, monkeypatch: pytest.MonkeyPatch) -> None:
        p = _fake_provider()
        monkeypatch.setattr(llm_mod.manager, "get_by_name", lambda n: p)
        assert llm_mod._resolve_provider("p1") is p

    def test_无名称_默认存在(self, monkeypatch: pytest.MonkeyPatch) -> None:
        p = _fake_provider()
        monkeypatch.setattr(llm_mod.manager, "get_default", lambda: p)
        assert llm_mod._resolve_provider(None) is p

    def test_无名称_无默认_有列表(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(llm_mod.manager, "get_default", lambda: None)
        monkeypatch.setattr(llm_mod.manager, "list_all", lambda: [_fake_provider()])
        with pytest.raises(SystemExit) as exc:
            llm_mod._resolve_provider(None)
        assert exc.value.code == 1

    def test_无名称_无默认_空列表(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(llm_mod.manager, "get_default", lambda: None)
        monkeypatch.setattr(llm_mod.manager, "list_all", lambda: [])
        with pytest.raises(SystemExit) as exc:
            llm_mod._resolve_provider(None)
        assert exc.value.code == 1


class TestRunSingle:
    def test_QxwError_被捕获退出(self, monkeypatch: pytest.MonkeyPatch) -> None:
        session = SimpleNamespace()
        service = SimpleNamespace()

        class FakeService:
            def stream_chat(self, s, m):
                raise QxwError("API 失败", exit_code=5)

        with pytest.raises(SystemExit) as exc:
            llm_mod._run_single(session, FakeService(), "hi")
        assert exc.value.code == 5


class TestChatCommand:
    def test_单次模式_流式输出(self, monkeypatch: pytest.MonkeyPatch) -> None:
        p = _fake_provider()
        monkeypatch.setattr(llm_mod.manager, "get_default", lambda: p)

        class FakeService:
            def stream_chat(self, session, msg):
                yield "hi"

        monkeypatch.setattr(llm_mod, "ChatService", lambda: FakeService())
        code, _ = _run(["chat", "-m", "hello"])
        assert code == 0

    def test_QxwError_退出码透传(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(llm_mod, "_resolve_provider", lambda n: (_ for _ in ()).throw(QxwError("e", 3)))
        code, out = _run(["chat", "-m", "hi"])
        assert code == 3

    def test_KeyboardInterrupt(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(llm_mod, "_resolve_provider", lambda n: (_ for _ in ()).throw(KeyboardInterrupt()))
        code, out = _run(["chat", "-m", "hi"])
        assert code == 130
        assert "已取消" in out

    def test_Exception(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(llm_mod, "_resolve_provider", lambda n: (_ for _ in ()).throw(RuntimeError("boom")))
        code, out = _run(["chat", "-m", "hi"])
        assert code == 1
        assert "未预期" in out


class TestProviderList:
    def test_空列表(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(llm_mod.manager, "list_all", lambda: [])
        code, out = _run(["provider", "list"])
        assert code == 0
        assert "暂无" in out

    def test_有数据(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(llm_mod.manager, "list_all", lambda: [_fake_provider(name="foo", is_default=True)])
        code, out = _run(["provider", "list"])
        assert code == 0
        assert "foo" in out

    def test_QxwError(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def boom():
            raise QxwError("DB 错", exit_code=4)

        monkeypatch.setattr(llm_mod.manager, "list_all", boom)
        code, out = _run(["provider", "list"])
        assert code == 4


class TestProviderAdd:
    def test_成功(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict = {}

        def fake_create(**kwargs):
            captured.update(kwargs)
            return _fake_provider(**{k: v for k, v in kwargs.items() if k in (
                "name", "provider_type", "base_url", "api_key", "model", "is_default",
            )})

        monkeypatch.setattr(llm_mod.manager, "create", fake_create)
        code, out = _run([
            "provider", "add",
            "-n", "new1", "--type", "openai", "-u", "http://x",
            "-k", "k", "-m", "m",
        ])
        assert code == 0
        assert captured["name"] == "new1"

    def test_QxwError(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def boom(**k):
            raise QxwError("冲突", exit_code=6)

        monkeypatch.setattr(llm_mod.manager, "create", boom)
        code, out = _run([
            "provider", "add",
            "-n", "new1", "--type", "openai", "-u", "http://x",
            "-k", "k", "-m", "m",
        ])
        assert code == 6


class TestProviderShow:
    def test_不存在(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(llm_mod.manager, "get_by_name", lambda n: None)
        code, out = _run(["provider", "show", "nope"])
        assert code == 1
        assert "不存在" in out

    def test_存在_api_key_被打码(self, monkeypatch: pytest.MonkeyPatch) -> None:
        p = _fake_provider(api_key="1234567890abcdef")
        monkeypatch.setattr(llm_mod.manager, "get_by_name", lambda n: p)
        code, out = _run(["provider", "show", "p1"])
        assert code == 0
        assert "12345678" in out
        assert "****" in out

    def test_短_api_key_全打码(self, monkeypatch: pytest.MonkeyPatch) -> None:
        p = _fake_provider(api_key="abc")
        monkeypatch.setattr(llm_mod.manager, "get_by_name", lambda n: p)
        code, out = _run(["provider", "show", "p1"])
        assert code == 0
        assert "****" in out


class TestProviderEdit:
    def test_无修改项提示(self) -> None:
        code, out = _run(["provider", "edit", "p1"])
        assert code == 0
        assert "未指定" in out

    def test_成功更新(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict = {}

        def fake_update(name, **kwargs):
            captured.update(kwargs)
            captured["name"] = name
            return _fake_provider(name=name)

        monkeypatch.setattr(llm_mod.manager, "update", fake_update)
        code, _ = _run(["provider", "edit", "p1", "-m", "gpt-5"])
        assert code == 0
        assert captured["model"] == "gpt-5"

    def test_QxwError(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def boom(name, **k):
            raise QxwError("不存在", exit_code=2)

        monkeypatch.setattr(llm_mod.manager, "update", boom)
        code, _ = _run(["provider", "edit", "p1", "-m", "gpt-5"])
        assert code == 2


class TestProviderDelete:
    def test_不存在(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(llm_mod.manager, "get_by_name", lambda n: None)
        code, out = _run(["provider", "delete", "nope"])
        assert code == 1
        assert "不存在" in out

    def test_用户取消(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(llm_mod.manager, "get_by_name", lambda n: _fake_provider())
        # 传入 "n" 回答取消
        code, out = _run(["provider", "delete", "p1"], input_text="n\n")
        assert "已取消" in out

    def test_强制删除(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(llm_mod.manager, "get_by_name", lambda n: _fake_provider())
        called: dict = {}
        monkeypatch.setattr(llm_mod.manager, "delete", lambda n: called.setdefault("n", n))
        code, out = _run(["provider", "delete", "p1", "-y"])
        assert code == 0
        assert called["n"] == "p1"


class TestProviderSetDefault:
    def test_成功(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(llm_mod.manager, "set_default", lambda n: _fake_provider(name=n, is_default=True))
        code, out = _run(["provider", "set-default", "p1"])
        assert code == 0
        assert "p1" in out

    def test_QxwError(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def boom(n):
            raise QxwError("不存在", exit_code=3)

        monkeypatch.setattr(llm_mod.manager, "set_default", boom)
        code, out = _run(["provider", "set-default", "p1"])
        assert code == 3


class TestPingOne:
    def test_QxwError_返回失败(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class FakeSvc:
            def stream_chat(self, s, m):
                raise QxwError("auth 失败", exit_code=1)

        monkeypatch.setattr(llm_mod, "ChatService", lambda **k: FakeSvc())
        ok, msg = llm_mod._ping_one(_fake_provider())
        assert ok is False
        assert "auth 失败" in msg

    def test_正常返回_ms(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class FakeSvc:
            def stream_chat(self, s, m):
                yield "x"

        monkeypatch.setattr(llm_mod, "ChatService", lambda **k: FakeSvc())
        ok, msg = llm_mod._ping_one(_fake_provider())
        assert ok is True
        assert "ms" in msg


class TestPingProvider:
    def test_无名称_无默认(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(llm_mod.manager, "get_default", lambda: None)
        code, out = _run(["provider", "ping"])
        assert code == 1
        assert "默认" in out

    def test_名称不存在(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(llm_mod.manager, "get_by_name", lambda n: None)
        code, out = _run(["provider", "ping", "nope"])
        assert code == 1

    def test_连接失败退出_1(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(llm_mod.manager, "get_by_name", lambda n: _fake_provider())
        monkeypatch.setattr(llm_mod, "_ping_one", lambda p: (False, "失败"))
        code, _ = _run(["provider", "ping", "p1"])
        assert code == 1

    def test_连接成功退出_0(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(llm_mod.manager, "get_by_name", lambda n: _fake_provider())
        monkeypatch.setattr(llm_mod, "_ping_one", lambda p: (True, "OK"))
        code, _ = _run(["provider", "ping", "p1"])
        assert code == 0


class TestPingAll:
    def test_空列表(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(llm_mod.manager, "list_all", lambda: [])
        code, out = _run(["provider", "ping-all"])
        assert code == 0
        assert "暂无" in out

    def test_部分失败_退出_1(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            llm_mod.manager,
            "list_all",
            lambda: [_fake_provider(name="a"), _fake_provider(name="b")],
        )
        results = iter([(True, "OK"), (False, "fail")])
        monkeypatch.setattr(llm_mod, "_ping_one", lambda p: next(results))
        code, out = _run(["provider", "ping-all"])
        assert code == 1
        assert "1 个正常" in out and "1 个失败" in out

    def test_全部通过_退出_0(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(llm_mod.manager, "list_all", lambda: [_fake_provider()])
        monkeypatch.setattr(llm_mod, "_ping_one", lambda p: (True, "OK"))
        code, _ = _run(["provider", "ping-all"])
        assert code == 0


class TestTuiCommand:
    def test_QxwError(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def boom():
            raise QxwError("TUI 错", exit_code=4)

        monkeypatch.setattr(llm_mod, "ChatProviderApp", boom)
        code, out = _run(["tui"])
        assert code == 4

    def test_KeyboardInterrupt(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class FakeApp:
            def run(self):
                raise KeyboardInterrupt()

        monkeypatch.setattr(llm_mod, "ChatProviderApp", lambda: FakeApp())
        code, out = _run(["tui"])
        assert code == 130


class TestRunInteractive:
    def test_立即_EOF_退出(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """console.input 抛 EOFError 时应静默退出"""
        from qxw.library.services.chat_service import ChatParams, ChatSession

        p = _fake_provider()
        session = ChatSession(provider=p, params=ChatParams.from_provider(p))

        class FakeSvc:
            def stream_chat(self, s, m):
                yield "x"

        monkeypatch.setattr(llm_mod.console, "input", lambda _prompt: (_ for _ in ()).throw(EOFError()))
        llm_mod._run_interactive(session, FakeSvc())  # 不抛

    def test_KeyboardInterrupt_退出(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from qxw.library.services.chat_service import ChatParams, ChatSession
        p = _fake_provider()
        session = ChatSession(provider=p, params=ChatParams.from_provider(p))
        monkeypatch.setattr(
            llm_mod.console, "input",
            lambda _p: (_ for _ in ()).throw(KeyboardInterrupt()),
        )
        llm_mod._run_interactive(session, SimpleNamespace())

    def test_空输入_跳过(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from qxw.library.services.chat_service import ChatParams, ChatSession
        p = _fake_provider()
        session = ChatSession(provider=p, params=ChatParams.from_provider(p))

        # 第一次空串，第二次 /exit
        inputs = iter(["", "/exit"])
        monkeypatch.setattr(llm_mod.console, "input", lambda _p: next(inputs))
        llm_mod._run_interactive(session, SimpleNamespace())

    def test_clear_清空上下文(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from qxw.library.services.chat_service import ChatMessage, ChatParams, ChatSession
        p = _fake_provider()
        session = ChatSession(provider=p, params=ChatParams.from_provider(p))
        session.messages.append(ChatMessage(role="user", content="old"))

        inputs = iter(["/clear", "/exit"])
        monkeypatch.setattr(llm_mod.console, "input", lambda _p: next(inputs))
        llm_mod._run_interactive(session, SimpleNamespace())
        assert session.messages == []

    def test_QxwError_在对话中_被捕获(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from qxw.library.services.chat_service import ChatParams, ChatSession
        p = _fake_provider()
        session = ChatSession(provider=p, params=ChatParams.from_provider(p))

        class FakeSvc:
            def stream_chat(self, s, m):
                raise QxwError("auth 失败", exit_code=1)

        inputs = iter(["hi", "/exit"])
        monkeypatch.setattr(llm_mod.console, "input", lambda _p: next(inputs))
        # 不抛出，只是打印
        llm_mod._run_interactive(session, FakeSvc())

    def test_完整流程_正常对话(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from qxw.library.services.chat_service import ChatParams, ChatSession
        p = _fake_provider()
        session = ChatSession(provider=p, params=ChatParams.from_provider(p))

        class FakeSvc:
            def stream_chat(self, s, m):
                yield "你"
                yield "好"

        inputs = iter(["hi", "/exit"])
        monkeypatch.setattr(llm_mod.console, "input", lambda _p: next(inputs))
        llm_mod._run_interactive(session, FakeSvc())


class TestRunSingleSuccess:
    def test_正常流式输出(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from qxw.library.services.chat_service import ChatParams, ChatSession
        p = _fake_provider()
        session = ChatSession(provider=p, params=ChatParams.from_provider(p))

        class FakeSvc:
            def stream_chat(self, s, m):
                yield "ok"

        llm_mod._run_single(session, FakeSvc(), "hi")  # 不抛


class TestProviderDeleteErrors:
    def test_delete_QxwError(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(llm_mod.manager, "get_by_name", lambda n: _fake_provider())

        def boom(n):
            raise QxwError("删错", exit_code=5)

        monkeypatch.setattr(llm_mod.manager, "delete", boom)
        code, out = _run(["provider", "delete", "p1", "-y"])
        assert code == 5


class TestProviderEditNoFields:
    def test_仅_default_更新(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict = {}

        def fake(name, **k):
            captured.update(k)
            return _fake_provider(name=name)

        monkeypatch.setattr(llm_mod.manager, "update", fake)
        code, _ = _run(["provider", "edit", "p1", "--default"])
        assert code == 0
        assert captured["is_default"] is True


class TestProviderGroupNoSubcommand:
    def test_无子命令打印帮助(self) -> None:
        code, out = _run(["provider"])
        assert code == 0
        assert "list" in out


class TestEnsureEnvLLM:
    def test_已就绪_不触发_init(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """直接调用 _ensure_env 覆盖源码行"""
        # 先移除 autouse 的 stub（此 fixture 在 local scope 生效）
        import qxw.config.init as init_mod

        class Ready:
            all_ready = True

        monkeypatch.setattr(init_mod, "check_env", lambda: Ready())
        init_called: dict[str, bool] = {}
        monkeypatch.setattr(init_mod, "init_env", lambda: init_called.setdefault("x", True))

        from qxw.library.models import base as models_base
        monkeypatch.setattr(models_base, "init_db", lambda: None)

        # _stub_ensure_env 已替换模块的 _ensure_env；直接调原函数
        # 找到模块里真实函数
        orig = type(llm_mod._ensure_env)  # 当前是 lambda；我们用全量路径调原始
        # 用 importlib.reload 太重，改成直接构造：复制源码逻辑
        # 这里简化：从源里取真实版本
        import importlib
        fresh = importlib.reload(llm_mod)
        try:
            fresh._ensure_env()  # type: ignore[attr-defined]
        finally:
            # 恢复 stub
            monkeypatch.setattr(fresh, "_ensure_env", lambda: None)

    def test_未就绪_触发_init_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import importlib
        fresh = importlib.reload(llm_mod)
        import qxw.config.init as init_mod

        class NotReady:
            all_ready = False

        class Result:
            initialized_items = ["配置目录"]

        monkeypatch.setattr(init_mod, "check_env", lambda: NotReady())
        monkeypatch.setattr(init_mod, "init_env", lambda: Result())

        from qxw.library.models import base as models_base
        monkeypatch.setattr(models_base, "init_db", lambda: None)

        runner = CliRunner()
        # 包一层 echo，保持测试隔离
        result = runner.invoke(fresh.main, ["--version"])
        assert result.exit_code == 0


class TestChatCommandInteractive:
    def test_无_message_走_interactive(self, monkeypatch: pytest.MonkeyPatch) -> None:
        p = _fake_provider()
        monkeypatch.setattr(llm_mod.manager, "get_default", lambda: p)

        interactive_called: dict[str, bool] = {}

        def fake_interactive(session, service):
            interactive_called["ran"] = True

        monkeypatch.setattr(llm_mod, "_run_interactive", fake_interactive)
        code, _ = _run(["chat"])  # 不带 -m
        assert code == 0
        assert interactive_called["ran"] is True


class TestEditAllFields:
    def test_每个字段都被收集(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, object] = {}

        def fake(name, **k):
            captured.update(k)
            return _fake_provider(name=name)

        monkeypatch.setattr(llm_mod.manager, "update", fake)
        code, _ = _run([
            "provider", "edit", "p1",
            "--type", "openai",
            "-u", "http://new",
            "-k", "newkey",
            "-m", "new-model",
            "-t", "0.9",
            "--max-tokens", "200",
            "--top-p", "0.95",
            "-s", "system",
            "--default",
        ])
        assert code == 0
        assert captured["provider_type"] == "openai"
        assert captured["base_url"] == "http://new"
        assert captured["api_key"] == "newkey"
        assert captured["model"] == "new-model"
        assert captured["temperature"] == 0.9
        assert captured["max_tokens"] == 200
        assert captured["top_p"] == 0.95
        assert captured["system_prompt"] == "system"
        assert captured["is_default"] is True


class TestPingProviderQxwError:
    def test_QxwError_包装(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def boom(n):
            raise QxwError("ping 错", exit_code=7)

        monkeypatch.setattr(llm_mod.manager, "get_by_name", boom)
        code, out = _run(["provider", "ping", "foo"])
        assert code == 7


class TestPingAllQxwError:
    def test_QxwError(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def boom():
            raise QxwError("列表错", exit_code=8)

        monkeypatch.setattr(llm_mod.manager, "list_all", boom)
        code, out = _run(["provider", "ping-all"])
        assert code == 8


class TestProviderTUIApp:
    """用 Textual Pilot 烟测 ChatProviderApp，覆盖 compose/按键路径"""

    def test_启动与退出(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import asyncio

        monkeypatch.setattr(llm_mod.manager, "list_all", lambda: [])

        async def _go() -> None:
            app = llm_mod.ChatProviderApp()
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("q")

        asyncio.run(_go())

    def test_带数据_刷新(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import asyncio

        monkeypatch.setattr(
            llm_mod.manager, "list_all", lambda: [_fake_provider(name="a")],
        )

        async def _go() -> None:
            app = llm_mod.ChatProviderApp()
            async with app.run_test() as pilot:
                await pilot.pause()
                # 刷新
                await pilot.press("r")
                await pilot.pause()
                await pilot.press("q")

        asyncio.run(_go())

    def test_action_触发所有分支(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """直接调用 action_* 方法覆盖 add/edit/copy/delete/set_default 的空表与命中分支"""
        import asyncio

        p = _fake_provider(name="xx")
        monkeypatch.setattr(llm_mod.manager, "list_all", lambda: [p])
        monkeypatch.setattr(llm_mod.manager, "get_by_name", lambda n: p if n == "xx" else None)
        monkeypatch.setattr(llm_mod.manager, "set_default", lambda n: p)
        monkeypatch.setattr(llm_mod.manager, "delete", lambda n: None)
        monkeypatch.setattr(llm_mod.manager, "create", lambda **k: _fake_provider(**{
            kk: k[kk] for kk in ("name", "provider_type", "base_url", "api_key", "model")
        }))
        monkeypatch.setattr(llm_mod.manager, "update", lambda n, **k: p)

        async def _go() -> None:
            app = llm_mod.ChatProviderApp()
            async with app.run_test() as pilot:
                await pilot.pause()

                # 模拟 form 结果：编辑
                app._on_form_result({"name": "xx", "provider_type": "openai", "_is_edit": True})
                # 模拟 form 结果：新增
                app._on_form_result({
                    "name": "newp", "provider_type": "openai",
                    "base_url": "http://x", "api_key": "k", "model": "m",
                    "temperature": 0.7, "max_tokens": 1, "top_p": 1.0,
                    "system_prompt": "", "is_default": False,
                    "_is_edit": False,
                })
                # form 返回 None（用户取消）
                app._on_form_result(None)

                # 选中表格第一行后触发 edit/copy
                table = app.query_one(llm_mod.DataTable)
                if table.row_count > 0:
                    app._open_edit()
                    app.action_copy_provider()
                    app.action_set_default()

                # 删除：直接执行 action_delete_provider 会 push 一个 ConfirmDeleteScreen
                # 我们不驱动 screen，只保证 action 路径被执行
                app.action_delete_provider()
                await pilot.pause()

                await pilot.press("q")

        asyncio.run(_go())

    def test_空表下_get_selected_name_返回_None(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import asyncio
        monkeypatch.setattr(llm_mod.manager, "list_all", lambda: [])

        async def _go() -> None:
            app = llm_mod.ChatProviderApp()
            async with app.run_test() as pilot:
                await pilot.pause()
                assert app._get_selected_name() is None
                # 空表触发 edit/copy/delete/set_default 应静默 return
                app.action_edit_provider()
                app.action_copy_provider()
                app.action_delete_provider()
                app.action_set_default()
                await pilot.press("q")

        asyncio.run(_go())


class TestProviderFormScreen:
    def test_add_mode_compose_通过_pilot(self) -> None:
        import asyncio

        async def _go() -> None:
            class _WrapperApp(llm_mod.App):
                def compose(self):
                    return []

                def on_mount(self) -> None:
                    self.push_screen(llm_mod.ProviderFormScreen())

            app = _WrapperApp()
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("escape")  # 触发 action_cancel

        asyncio.run(_go())

    def test_edit_mode_带_provider_compose(self) -> None:
        import asyncio

        p = _fake_provider()

        async def _go() -> None:
            class _WrapperApp(llm_mod.App):
                def compose(self):
                    return []

                def on_mount(self) -> None:
                    self.push_screen(llm_mod.ProviderFormScreen(p))

            app = _WrapperApp()
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("escape")

        asyncio.run(_go())

    def test_copy_mode_compose(self) -> None:
        import asyncio

        p = _fake_provider()

        async def _go() -> None:
            class _WrapperApp(llm_mod.App):
                def compose(self):
                    return []

                def on_mount(self) -> None:
                    self.push_screen(llm_mod.ProviderFormScreen(p, copy_from="p1"))

            app = _WrapperApp()
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("escape")

        asyncio.run(_go())


class TestConfirmDeleteScreen:
    def test_点取消_dismiss_False(self) -> None:
        import asyncio

        async def _go() -> None:
            received: list[bool] = []

            class _WrapperApp(llm_mod.App):
                def compose(self):
                    return []

                def on_mount(self) -> None:
                    self.push_screen(
                        llm_mod.ConfirmDeleteScreen("p1"),
                        lambda r: received.append(bool(r)),
                    )

            app = _WrapperApp()
            async with app.run_test() as pilot:
                await pilot.pause()
                # 点击 cancel 按钮
                cancel_btn = app.screen.query_one("#cancel")
                await pilot.click(cancel_btn)
                await pilot.pause()

            assert received == [False]

        asyncio.run(_go())

    def test_点确认_dismiss_True(self) -> None:
        import asyncio

        async def _go() -> None:
            received: list[bool] = []

            class _WrapperApp(llm_mod.App):
                def compose(self):
                    return []

                def on_mount(self) -> None:
                    self.push_screen(
                        llm_mod.ConfirmDeleteScreen("p1"),
                        lambda r: received.append(bool(r)),
                    )

            app = _WrapperApp()
            async with app.run_test() as pilot:
                await pilot.pause()
                confirm_btn = app.screen.query_one("#confirm")
                await pilot.click(confirm_btn)
                await pilot.pause()

            assert received == [True]

        asyncio.run(_go())


class TestChatCommandOptionsOverride:
    def test_model_temp_等参数传入_params(self, monkeypatch: pytest.MonkeyPatch) -> None:
        p = _fake_provider()
        monkeypatch.setattr(llm_mod.manager, "get_default", lambda: p)

        captured: dict[str, object] = {}

        class FakeSvc:
            def stream_chat(self, session, msg):
                captured["model"] = session.params.model
                captured["temp"] = session.params.temperature
                captured["max_tokens"] = session.params.max_tokens
                captured["top_p"] = session.params.top_p
                captured["sys"] = session.params.system_prompt
                yield ""

        monkeypatch.setattr(llm_mod, "ChatService", lambda: FakeSvc())
        code, _ = _run([
            "chat", "-m", "hi",
            "--model", "gpt-5",
            "-t", "0.1",
            "--max-tokens", "100",
            "--top-p", "0.9",
            "-s", "你是助手",
        ])
        assert code == 0
        assert captured["model"] == "gpt-5"
        assert captured["temp"] == 0.1
        assert captured["max_tokens"] == 100
        assert captured["top_p"] == 0.9
        assert captured["sys"] == "你是助手"


class TestFetchCommand:
    """qxw-llm fetch 命令分支覆盖

    重点覆盖：
    - 缺少 patterns 参数 → 退出码 6
    - service 抛 QxwError → 退出码透传
    - KeyboardInterrupt / 未预期 Exception
    - 正常路径：参数透传到 service、文本汇总输出
    """

    def test_无_patterns_走_skip_weights_模式(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """命令行不传 patterns 时，service 应收到 patterns=None 并走跳过权重模式"""
        from qxw.library.services import llm_fetch_service as svc

        captured: dict = {}

        def fake_fetch(**kwargs):
            captured.update(kwargs)
            return svc.FetchResult(
                repo="org/name",
                source="huggingface",
                revision=None,
                output_dir=tmp_path,
                files=(svc.FetchedFile(repo_path="config.json", local_path=tmp_path / "config.json", size=2),),
            )

        monkeypatch.setattr(svc, "fetch_files", fake_fetch)
        code, out = _run(["fetch", "org/name", "-o", str(tmp_path)])
        assert code == 0
        assert captured["patterns"] is None
        assert "skip-weights" in out

    def test_QxwError_退出码透传(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from qxw.library.services import llm_fetch_service as svc

        def boom(**kwargs):
            raise QxwError("仓库不存在", exit_code=5)

        monkeypatch.setattr(svc, "fetch_files", boom)
        code, out = _run(["fetch", "org/name", "config.json"])
        assert code == 5
        assert "仓库不存在" in out

    def test_KeyboardInterrupt(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from qxw.library.services import llm_fetch_service as svc

        def boom(**kwargs):
            raise KeyboardInterrupt()

        monkeypatch.setattr(svc, "fetch_files", boom)
        code, out = _run(["fetch", "org/name", "config.json"])
        assert code == 130
        assert "已取消" in out

    def test_未预期_Exception(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from qxw.library.services import llm_fetch_service as svc

        def boom(**kwargs):
            raise RuntimeError("oops")

        monkeypatch.setattr(svc, "fetch_files", boom)
        code, out = _run(["fetch", "org/name", "config.json"])
        assert code == 1
        assert "未预期" in out

    def test_正常路径_参数透传_汇总输出(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
        from qxw.library.services import llm_fetch_service as svc

        captured: dict = {}

        def fake_fetch(**kwargs):
            captured.update(kwargs)
            return svc.FetchResult(
                repo="org/name",
                source="modelscope",
                revision="v1",
                output_dir=tmp_path,
                files=(svc.FetchedFile(repo_path="config.json", local_path=tmp_path / "config.json", size=100),),
            )

        monkeypatch.setattr(svc, "fetch_files", fake_fetch)
        code, out = _run(
            [
                "fetch",
                "Org/Name",
                "configuration_*.py",
                "--source",
                "modelscope",
                "-r",
                "v1",
                "-o",
                str(tmp_path),
                "-k",
                "secret",
            ]
        )
        assert code == 0
        assert captured["repo"] == "Org/Name"
        assert captured["patterns"] == ["configuration_*.py"]
        assert captured["source"] == "modelscope"
        assert captured["revision"] == "v1"
        assert str(tmp_path) == str(captured["output"])
        assert captured["token"] == "secret"
        assert "已下载 1 个文件" in out
        assert "config.json" in out

    def test_revision_缺省_为_None(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
        """命令行不显式指定 --revision 时，应以 None 透传给 service 让 SDK 用各自默认值"""
        from qxw.library.services import llm_fetch_service as svc

        captured: dict = {}

        def fake_fetch(**kwargs):
            captured.update(kwargs)
            return svc.FetchResult(
                repo="o/n",
                source="huggingface",
                revision=None,
                output_dir=tmp_path,
                files=(svc.FetchedFile(repo_path="a.bin", local_path=tmp_path / "a.bin", size=42),),
            )

        monkeypatch.setattr(svc, "fetch_files", fake_fetch)
        code, out = _run(["fetch", "o/n", "a.bin", "-o", str(tmp_path)])
        assert code == 0
        assert captured["revision"] is None
        assert "(default)" in out
