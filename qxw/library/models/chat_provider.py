"""ChatProvider ORM 模型

存储 AI 对话服务提供商的连接信息和默认参数。
支持 OpenAI 和 Anthropic 两种类型。
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from qxw.library.models.base import Base


class ChatProvider(Base):

    __tablename__ = "chat_providers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, comment="提供商名称")
    provider_type: Mapped[str] = mapped_column(String(32), nullable=False, comment="类型: openai / anthropic")
    base_url: Mapped[str] = mapped_column(String(512), nullable=False, comment="API 基础地址")
    api_key: Mapped[str] = mapped_column(String(512), nullable=False, comment="API 密钥")
    model: Mapped[str] = mapped_column(String(128), nullable=False, comment="默认模型名称")
    temperature: Mapped[float] = mapped_column(Float, nullable=False, default=0.7, comment="默认温度")
    max_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=4096, comment="默认最大 token 数")
    top_p: Mapped[float] = mapped_column(Float, nullable=False, default=1.0, comment="默认 top_p")
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False, default="", comment="默认系统提示词")
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, comment="是否为默认提供商")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<ChatProvider(name={self.name!r}, type={self.provider_type!r}, model={self.model!r})>"
