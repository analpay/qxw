"""qxw.library.services.chat_service 单元测试

覆盖：
- ChatParams.from_provider：默认映射 / overrides / None 不覆盖 / 未知 key 不写入
- ChatSession.add_message
- ChatService.__init__：timeout / connect_timeout 触发 httpx.Timeout
- stream_chat：未知 provider_type 抛 ValidationError
- _stream_openai：ImportError 包装、stream 成功产出、temperature/top_p 参数剥离重试、通用异常包装为 NetworkError
- _stream_anthropic：ImportError 包装、stream 成功、通用异常包装
"""

from __future__ import annotations

import sys
import types
from types import SimpleNamespace

import pytest

from qxw.library.base.exceptions import NetworkError, ValidationError
from qxw.library.services import chat_service as cs
from qxw.library.services.chat_service import (
    ChatParams,
    ChatService,
    ChatSession,
)


def _make_provider(provider_type: str = "openai", **over) -> object:
    base = dict(
        name="p",
        provider_type=provider_type,
        base_url="http://x",
        api_key="k",
        model="gpt-x",
        temperature=0.5,
        max_tokens=1000,
        top_p=0.9,
        system_prompt="",
    )
    base.update(over)
    return SimpleNamespace(**base)


class TestChatParams:
    def test_from_provider_映射所有字段(self) -> None:
        p = _make_provider(temperature=0.42)
        cp = ChatParams.from_provider(p)
        assert cp.model == "gpt-x"
        assert cp.temperature == 0.42
        assert cp.max_tokens == 1000
        assert cp.top_p == 0.9

    def test_overrides_覆盖(self) -> None:
        p = _make_provider()
        cp = ChatParams.from_provider(p, temperature=0.1, max_tokens=50)
        assert cp.temperature == 0.1
        assert cp.max_tokens == 50

    def test_None_值不覆盖(self) -> None:
        p = _make_provider(temperature=0.3)
        cp = ChatParams.from_provider(p, temperature=None)
        assert cp.temperature == 0.3

    def test_未知字段被忽略(self) -> None:
        p = _make_provider()
        cp = ChatParams.from_provider(p, not_a_field="x")
        assert not hasattr(cp, "not_a_field")


class TestChatSession:
    def test_add_message_累计(self) -> None:
        p = _make_provider()
        session = ChatSession(provider=p, params=ChatParams.from_provider(p))
        session.add_message("user", "hi")
        session.add_message("assistant", "hello")
        assert len(session.messages) == 2
        assert session.messages[0].role == "user"
        assert session.messages[1].content == "hello"


class TestChatServiceInit:
    def test_无_timeout_时_httpx_timeout_为_None(self) -> None:
        svc = ChatService()
        assert svc._httpx_timeout is None

    def test_带_timeout_构造_httpx_Timeout(self) -> None:
        svc = ChatService(connect_timeout=1.0, timeout=5.0)
        assert svc._httpx_timeout is not None


class TestStreamChatDispatch:
    def test_未知_provider_type_抛_ValidationError(self) -> None:
        p = _make_provider(provider_type="qwen")
        session = ChatSession(provider=p, params=ChatParams.from_provider(p))
        svc = ChatService()
        gen = svc.stream_chat(session, "hi")
        with pytest.raises(ValidationError, match="不支持的提供商类型"):
            list(gen)


class TestStreamOpenAI:
    @pytest.fixture()
    def fake_openai(self, monkeypatch: pytest.MonkeyPatch):
        """注入假的 openai 模块到 sys.modules"""
        holder: dict[str, object] = {}

        class FakeChunk:
            def __init__(self, content: str | None) -> None:
                delta = SimpleNamespace(content=content)
                self.choices = [SimpleNamespace(delta=delta)]

        class FakeCompletions:
            def __init__(self) -> None:
                self.calls: list[dict] = []
                self.raise_on_first: Exception | None = None

            def create(self, **kwargs):
                self.calls.append(kwargs)
                if self.raise_on_first is not None and len(self.calls) == 1:
                    err = self.raise_on_first
                    self.raise_on_first = None
                    raise err
                # 默认返回两个有内容的 chunk + 一个空 chunk
                return iter([FakeChunk("Hel"), FakeChunk("lo"), FakeChunk(None)])

        class FakeChat:
            def __init__(self, completions) -> None:
                self.completions = completions

        class FakeOpenAI:
            def __init__(self, **kwargs) -> None:
                holder["kwargs"] = kwargs
                holder["completions"] = FakeCompletions()
                self.chat = FakeChat(holder["completions"])

        fake_mod = types.ModuleType("openai")
        fake_mod.OpenAI = FakeOpenAI  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "openai", fake_mod)
        return holder

    def test_流式产出并记录_assistant_消息(self, fake_openai) -> None:
        p = _make_provider(system_prompt="你是助手")
        session = ChatSession(provider=p, params=ChatParams.from_provider(p))
        svc = ChatService()
        out = list(svc.stream_chat(session, "hi"))
        assert out == ["Hel", "lo"]
        assert session.messages[-1].role == "assistant"
        assert session.messages[-1].content == "Hello"
        # system prompt 作为 messages[0]
        call = fake_openai["completions"].calls[0]
        assert call["messages"][0]["role"] == "system"

    def test_temperature_top_p_剥离后重试(
        self, fake_openai, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        p = _make_provider()
        session = ChatSession(provider=p, params=ChatParams.from_provider(p))
        svc = ChatService()
        fake_openai["completions"] = None  # 初始化后客户端再访问

        # 构造 FakeOpenAI 创建后才设置 raise_on_first
        original_openai = sys.modules["openai"].OpenAI

        class OpenAIWithRaise(original_openai):  # type: ignore[misc]
            def __init__(self, **kwargs) -> None:
                super().__init__(**kwargs)
                self.chat.completions.raise_on_first = ValueError(
                    "model does not support temperature"
                )

        monkeypatch.setattr(sys.modules["openai"], "OpenAI", OpenAIWithRaise)

        out = list(svc.stream_chat(session, "hi"))
        assert out == ["Hel", "lo"]

    def test_无法识别的异常被包装为_NetworkError(
        self, fake_openai, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        p = _make_provider()
        session = ChatSession(provider=p, params=ChatParams.from_provider(p))
        svc = ChatService()

        original_openai = sys.modules["openai"].OpenAI

        class OpenAIWithRaise(original_openai):  # type: ignore[misc]
            def __init__(self, **kwargs) -> None:
                super().__init__(**kwargs)
                self.chat.completions.raise_on_first = RuntimeError("服务不可用")

        monkeypatch.setattr(sys.modules["openai"], "OpenAI", OpenAIWithRaise)

        with pytest.raises(NetworkError, match="OpenAI"):
            list(svc.stream_chat(session, "hi"))

    def test_ImportError_包装为_NetworkError(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 把 openai 从 sys.modules 移除，并 patch import 机制让其抛 ImportError
        monkeypatch.delitem(sys.modules, "openai", raising=False)

        import builtins

        real_import = builtins.__import__

        def fake_import(name, *a, **k):
            if name == "openai":
                raise ImportError("no module")
            return real_import(name, *a, **k)

        monkeypatch.setattr(builtins, "__import__", fake_import)

        p = _make_provider()
        session = ChatSession(provider=p, params=ChatParams.from_provider(p))
        svc = ChatService()
        with pytest.raises(NetworkError, match="openai"):
            list(svc.stream_chat(session, "hi"))


class TestStreamAnthropic:
    @pytest.fixture()
    def fake_anthropic(self, monkeypatch: pytest.MonkeyPatch):
        class FakeStreamCtx:
            def __init__(self, texts) -> None:
                self.text_stream = iter(texts)

            def __enter__(self):
                return self

            def __exit__(self, *a) -> bool:
                return False

        class FakeMessages:
            def __init__(self, texts, raise_on_stream=None) -> None:
                self._texts = texts
                self._raise = raise_on_stream

            def stream(self, **kwargs):
                if self._raise is not None:
                    raise self._raise
                return FakeStreamCtx(self._texts)

        class FakeAnthropic:
            def __init__(self, **kwargs) -> None:
                self.messages = FakeMessages(["你", "好"])

        fake_mod = types.ModuleType("anthropic")
        fake_mod.Anthropic = FakeAnthropic  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "anthropic", fake_mod)
        return fake_mod

    def test_流式产出(self, fake_anthropic) -> None:
        p = _make_provider(provider_type="anthropic", system_prompt="sys")
        session = ChatSession(provider=p, params=ChatParams.from_provider(p))
        svc = ChatService()
        out = list(svc.stream_chat(session, "hi"))
        assert "".join(out) == "你好"
        assert session.messages[-1].role == "assistant"
        assert session.messages[-1].content == "你好"

    def test_stream_异常被包装_NetworkError(
        self, fake_anthropic, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        original = sys.modules["anthropic"].Anthropic

        class BrokenAnthropic(original):  # type: ignore[misc]
            def __init__(self, **kwargs) -> None:
                super().__init__(**kwargs)
                self.messages._raise = RuntimeError("超时")  # type: ignore[attr-defined]

        monkeypatch.setattr(sys.modules["anthropic"], "Anthropic", BrokenAnthropic)

        p = _make_provider(provider_type="anthropic")
        session = ChatSession(provider=p, params=ChatParams.from_provider(p))
        svc = ChatService()
        with pytest.raises(NetworkError, match="Anthropic"):
            list(svc.stream_chat(session, "hi"))

    def test_ImportError_包装(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delitem(sys.modules, "anthropic", raising=False)

        import builtins

        real_import = builtins.__import__

        def fake_import(name, *a, **k):
            if name == "anthropic":
                raise ImportError("no module")
            return real_import(name, *a, **k)

        monkeypatch.setattr(builtins, "__import__", fake_import)

        p = _make_provider(provider_type="anthropic")
        session = ChatSession(provider=p, params=ChatParams.from_provider(p))
        svc = ChatService()
        with pytest.raises(NetworkError, match="anthropic"):
            list(svc.stream_chat(session, "hi"))
