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
