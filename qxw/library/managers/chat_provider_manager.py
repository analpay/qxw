"""ChatProvider CRUD 管理器"""

from datetime import datetime

from sqlalchemy import select

from qxw.library.base.exceptions import DatabaseError, ValidationError
from qxw.library.models.base import get_db_session
from qxw.library.models.chat_provider import ChatProvider

SUPPORTED_PROVIDER_TYPES = ("openai", "anthropic")

# 数值参数合法区间（与主流 LLM API 约定一致）
_TEMPERATURE_RANGE = (0.0, 2.0)
_TOP_P_RANGE = (0.0, 1.0)


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
        self._validate_required_str("name", name)
        self._validate_required_str("base_url", base_url)
        self._validate_required_str("api_key", api_key)
        self._validate_required_str("model", model)
        self._validate_temperature(temperature)
        self._validate_max_tokens(max_tokens)
        self._validate_top_p(top_p)

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

        created = self.get_by_name(name)
        if created is None:
            raise DatabaseError(f"提供商 '{name}' 创建后回读失败")
        return created

    def update(self, name: str, **kwargs: object) -> ChatProvider:
        if "provider_type" in kwargs:
            self._validate_provider_type(str(kwargs["provider_type"]))

        if "base_url" in kwargs and isinstance(kwargs["base_url"], str):
            stripped_url = kwargs["base_url"].strip()
            if not stripped_url:
                raise ValidationError("base_url 不能为空")
            kwargs["base_url"] = stripped_url.rstrip("/")

        for field_name in ("name", "api_key", "model"):
            if field_name in kwargs and isinstance(kwargs[field_name], str):
                self._validate_required_str(field_name, str(kwargs[field_name]))

        if "temperature" in kwargs:
            self._validate_temperature(float(kwargs["temperature"]))  # type: ignore[arg-type]
        if "max_tokens" in kwargs:
            self._validate_max_tokens(int(kwargs["max_tokens"]))  # type: ignore[arg-type]
        if "top_p" in kwargs:
            self._validate_top_p(float(kwargs["top_p"]))  # type: ignore[arg-type]

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

        updated = self.get_by_name(name)
        if updated is None:
            raise DatabaseError(f"提供商 '{name}' 更新后回读失败")
        return updated

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

        updated = self.get_by_name(name)
        if updated is None:
            raise DatabaseError(f"提供商 '{name}' 设为默认后回读失败")
        return updated

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

    @staticmethod
    def _validate_required_str(field: str, value: str) -> None:
        # 空值或仅含空白的字符串被视为缺失配置，应直接拒绝而非让其写入数据库
        if not isinstance(value, str) or not value.strip():
            raise ValidationError(f"{field} 不能为空")

    @staticmethod
    def _validate_temperature(value: float) -> None:
        lo, hi = _TEMPERATURE_RANGE
        if not (lo <= value <= hi):
            raise ValidationError(f"temperature 必须在 [{lo}, {hi}] 范围内，当前: {value}")

    @staticmethod
    def _validate_top_p(value: float) -> None:
        lo, hi = _TOP_P_RANGE
        if not (lo <= value <= hi):
            raise ValidationError(f"top_p 必须在 [{lo}, {hi}] 范围内，当前: {value}")

    @staticmethod
    def _validate_max_tokens(value: int) -> None:
        if value <= 0:
            raise ValidationError(f"max_tokens 必须为正整数，当前: {value}")
