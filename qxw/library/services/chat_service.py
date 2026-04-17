"""ChatService - OpenAI / Anthropic 流式对话服务"""

from collections.abc import Generator
from dataclasses import dataclass, field

from qxw.library.base.exceptions import NetworkError, ValidationError
from qxw.library.models.chat_provider import ChatProvider


@dataclass
class ChatMessage:
    role: str
    content: str


@dataclass
class ChatParams:
    model: str
    temperature: float = 0.7
    max_tokens: int = 4096
    top_p: float = 1.0
    system_prompt: str = ""

    @classmethod
    def from_provider(cls, provider: ChatProvider, **overrides: object) -> "ChatParams":
        params = cls(
            model=provider.model,
            temperature=provider.temperature,
            max_tokens=provider.max_tokens,
            top_p=provider.top_p,
            system_prompt=provider.system_prompt,
        )
        for key, value in overrides.items():
            if value is not None and hasattr(params, key):
                setattr(params, key, value)
        return params


@dataclass
class ChatSession:
    provider: ChatProvider
    params: ChatParams
    messages: list[ChatMessage] = field(default_factory=list)

    def add_message(self, role: str, content: str) -> None:
        self.messages.append(ChatMessage(role=role, content=content))


class ChatService:

    def stream_chat(self, session: ChatSession, user_input: str) -> Generator[str, None, None]:
        session.add_message("user", user_input)

        if session.provider.provider_type == "openai":
            yield from self._stream_openai(session)
        elif session.provider.provider_type == "anthropic":
            yield from self._stream_anthropic(session)
        else:
            raise ValidationError(f"不支持的提供商类型: {session.provider.provider_type}")

    def _stream_openai(self, session: ChatSession) -> Generator[str, None, None]:
        try:
            from openai import OpenAI
        except ImportError:
            raise NetworkError("请先安装 openai 依赖: pip install openai")

        client = OpenAI(
            api_key=session.provider.api_key,
            base_url=session.provider.base_url,
        )

        messages: list[dict[str, str]] = []
        if session.params.system_prompt:
            messages.append({"role": "system", "content": session.params.system_prompt})
        for msg in session.messages:
            messages.append({"role": msg.role, "content": msg.content})

        kwargs: dict[str, object] = {
            "model": session.params.model,
            "messages": messages,
            "max_tokens": session.params.max_tokens,
            "stream": True,
        }
        if session.params.temperature is not None:
            kwargs["temperature"] = session.params.temperature
        if session.params.top_p is not None:
            kwargs["top_p"] = session.params.top_p

        try:
            try:
                response = client.chat.completions.create(**kwargs)  # type: ignore[arg-type]
            except Exception as e:
                # 部分模型（如 o1/o3）不支持 temperature/top_p，自动去除后重试
                err = str(e)
                if "temperature" in err or "top_p" in err:
                    kwargs.pop("temperature", None)
                    kwargs.pop("top_p", None)
                    response = client.chat.completions.create(**kwargs)  # type: ignore[arg-type]
                else:
                    raise

            full_content = ""
            for chunk in response:
                if chunk.choices and chunk.choices[0].delta.content:
                    text = chunk.choices[0].delta.content
                    full_content += text
                    yield text

            session.add_message("assistant", full_content)

        except NetworkError:
            raise
        except Exception as e:
            raise NetworkError(f"OpenAI API 调用失败: {e}") from e

    def _stream_anthropic(self, session: ChatSession) -> Generator[str, None, None]:
        try:
            import anthropic
        except ImportError:
            raise NetworkError("请先安装 anthropic 依赖: pip install anthropic")

        client = anthropic.Anthropic(
            api_key=session.provider.api_key,
            base_url=session.provider.base_url,
        )

        messages: list[dict[str, str]] = []
        for msg in session.messages:
            messages.append({"role": msg.role, "content": msg.content})

        kwargs: dict[str, object] = {
            "model": session.params.model,
            "messages": messages,
            "temperature": session.params.temperature,
            "max_tokens": session.params.max_tokens,
            "top_p": session.params.top_p,
        }
        if session.params.system_prompt:
            kwargs["system"] = session.params.system_prompt

        try:
            full_content = ""
            with client.messages.stream(**kwargs) as stream:  # type: ignore[arg-type]
                for text in stream.text_stream:
                    full_content += text
                    yield text

            session.add_message("assistant", full_content)

        except Exception as e:
            raise NetworkError(f"Anthropic API 调用失败: {e}") from e
