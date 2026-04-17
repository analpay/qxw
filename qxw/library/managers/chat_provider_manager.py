"""ChatProvider CRUD 管理器"""

from datetime import datetime

from sqlalchemy import select

from qxw.library.base.exceptions import DatabaseError, ValidationError
from qxw.library.models.base import get_db_session
from qxw.library.models.chat_provider import ChatProvider

SUPPORTED_PROVIDER_TYPES = ("openai", "anthropic")


class ChatProviderManager:

    def list_all(self) -> list[ChatProvider]:
        with get_db_session() as session:
            stmt = select(ChatProvider).order_by(ChatProvider.id)
            return list(session.execute(stmt).scalars().all())

    def get_by_name(self, name: str) -> ChatProvider | None:
        with get_db_session() as session:
            stmt = select(ChatProvider).where(ChatProvider.name == name)
            return session.execute(stmt).scalar_one_or_none()

    def get_default(self) -> ChatProvider | None:
        with get_db_session() as session:
            stmt = select(ChatProvider).where(ChatProvider.is_default.is_(True))
            return session.execute(stmt).scalar_one_or_none()

    def create(
        self,
        *,
        name: str,
        provider_type: str,
        base_url: str,
        api_key: str,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        top_p: float = 1.0,
        system_prompt: str = "",
        is_default: bool = False,
    ) -> ChatProvider:
        self._validate_provider_type(provider_type)

        if self.get_by_name(name):
            raise ValidationError(f"提供商 '{name}' 已存在")

        with get_db_session() as session:
            if is_default:
                self._clear_default(session)

            provider = ChatProvider(
                name=name,
                provider_type=provider_type,
                base_url=base_url.rstrip("/"),
                api_key=api_key,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                top_p=top_p,
                system_prompt=system_prompt,
                is_default=is_default,
            )
            session.add(provider)

        return self.get_by_name(name)  # type: ignore[return-value]

    def update(self, name: str, **kwargs: object) -> ChatProvider:
        if "provider_type" in kwargs:
            self._validate_provider_type(str(kwargs["provider_type"]))

        if "base_url" in kwargs and isinstance(kwargs["base_url"], str):
            kwargs["base_url"] = kwargs["base_url"].rstrip("/")

        with get_db_session() as session:
            stmt = select(ChatProvider).where(ChatProvider.name == name)
            provider = session.execute(stmt).scalar_one_or_none()
            if not provider:
                raise DatabaseError(f"提供商 '{name}' 不存在")

            if kwargs.get("is_default"):
                self._clear_default(session)

            for key, value in kwargs.items():
                if hasattr(provider, key) and key not in ("id", "created_at"):
                    setattr(provider, key, value)
            provider.updated_at = datetime.now()

        return self.get_by_name(name)  # type: ignore[return-value]

    def delete(self, name: str) -> None:
        with get_db_session() as session:
            stmt = select(ChatProvider).where(ChatProvider.name == name)
            provider = session.execute(stmt).scalar_one_or_none()
            if not provider:
                raise DatabaseError(f"提供商 '{name}' 不存在")
            session.delete(provider)

    def set_default(self, name: str) -> ChatProvider:
        with get_db_session() as session:
            stmt = select(ChatProvider).where(ChatProvider.name == name)
            provider = session.execute(stmt).scalar_one_or_none()
            if not provider:
                raise DatabaseError(f"提供商 '{name}' 不存在")

            self._clear_default(session)
            provider.is_default = True
            provider.updated_at = datetime.now()

        return self.get_by_name(name)  # type: ignore[return-value]

    @staticmethod
    def _clear_default(session) -> None:
        stmt = select(ChatProvider).where(ChatProvider.is_default.is_(True))
        for p in session.execute(stmt).scalars().all():
            p.is_default = False

    @staticmethod
    def _validate_provider_type(provider_type: str) -> None:
        if provider_type not in SUPPORTED_PROVIDER_TYPES:
            raise ValidationError(
                f"不支持的提供商类型 '{provider_type}'，支持的类型: {', '.join(SUPPORTED_PROVIDER_TYPES)}"
            )
