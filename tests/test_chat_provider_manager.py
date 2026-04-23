"""qxw.library.managers.chat_provider_manager 单元测试

使用 conftest 提供的 in_memory_db fixture 隔离真实 sqlite 文件。
"""

from __future__ import annotations

import pytest

from qxw.library.base.exceptions import DatabaseError, ValidationError
from qxw.library.managers.chat_provider_manager import ChatProviderManager


@pytest.fixture()
def manager(in_memory_db) -> ChatProviderManager:  # noqa: ARG001 — fixture 负责 monkeypatch
    return ChatProviderManager()


def _make(manager: ChatProviderManager, **overrides):
    kwargs = dict(
        name="openai-main",
        provider_type="openai",
        base_url="https://api.openai.com/v1/",
        api_key="sk-xxx",
        model="gpt-4o",
    )
    kwargs.update(overrides)
    return manager.create(**kwargs)


class TestCreate:
    def test_创建并默认值合理(self, manager: ChatProviderManager) -> None:
        provider = _make(manager)
        assert provider.id is not None
        assert provider.name == "openai-main"
        assert provider.provider_type == "openai"
        # base_url 末尾 / 会被去掉
        assert provider.base_url == "https://api.openai.com/v1"
        assert provider.temperature == 0.7
        assert provider.max_tokens == 4096
        assert provider.is_default is False

    def test_重复名字抛_ValidationError(self, manager: ChatProviderManager) -> None:
        _make(manager)
        with pytest.raises(ValidationError, match="已存在"):
            _make(manager)

    @pytest.mark.parametrize("bad_type", ["gemini", "", "OPENAI"])
    def test_不支持的_provider_type(
        self, manager: ChatProviderManager, bad_type: str
    ) -> None:
        with pytest.raises(ValidationError, match="不支持的提供商类型"):
            _make(manager, name=f"x-{bad_type or 'empty'}", provider_type=bad_type)

    def test_is_default_会清除原先的默认(self, manager: ChatProviderManager) -> None:
        _make(manager, name="a", is_default=True)
        _make(manager, name="b", is_default=True)

        default = manager.get_default()
        assert default is not None
        assert default.name == "b"
        # a 应被取消默认
        a = manager.get_by_name("a")
        assert a is not None and a.is_default is False


class TestList:
    def test_list_all_按_id_排序(self, manager: ChatProviderManager) -> None:
        _make(manager, name="a")
        _make(manager, name="b", provider_type="anthropic", model="claude-opus-4-7")

        items = manager.list_all()
        assert [p.name for p in items] == ["a", "b"]

    def test_list_all_空表返回空列表(self, manager: ChatProviderManager) -> None:
        assert manager.list_all() == []

    def test_get_by_name_不存在返回_None(self, manager: ChatProviderManager) -> None:
        assert manager.get_by_name("not-exist") is None

    def test_get_default_无默认时返回_None(self, manager: ChatProviderManager) -> None:
        _make(manager)
        assert manager.get_default() is None


class TestUpdate:
    def test_更新字段并规范化_base_url(self, manager: ChatProviderManager) -> None:
        _make(manager)
        updated = manager.update(
            "openai-main",
            model="gpt-4o-mini",
            temperature=0.2,
            base_url="https://proxy.example.com/v1/",
        )
        assert updated.model == "gpt-4o-mini"
        assert updated.temperature == pytest.approx(0.2)
        assert updated.base_url == "https://proxy.example.com/v1"

    def test_更新不存在的_provider_抛_DatabaseError(
        self, manager: ChatProviderManager
    ) -> None:
        with pytest.raises(DatabaseError, match="不存在"):
            manager.update("ghost", model="x")

    def test_更新_provider_type_仍校验(self, manager: ChatProviderManager) -> None:
        _make(manager)
        with pytest.raises(ValidationError, match="不支持"):
            manager.update("openai-main", provider_type="gemini")

    def test_受保护字段_id_与_created_at_不被覆盖(
        self, manager: ChatProviderManager
    ) -> None:
        provider = _make(manager)
        original_id = provider.id
        original_created = provider.created_at

        manager.update("openai-main", id=9999, created_at="1999-01-01 00:00:00", model="x")

        reloaded = manager.get_by_name("openai-main")
        assert reloaded is not None
        assert reloaded.id == original_id
        assert reloaded.created_at == original_created
        assert reloaded.model == "x"

    def test_通过_update_将某个置为默认会清空其他默认(
        self, manager: ChatProviderManager
    ) -> None:
        _make(manager, name="a", is_default=True)
        _make(manager, name="b")

        manager.update("b", is_default=True)

        assert manager.get_by_name("a").is_default is False  # type: ignore[union-attr]
        assert manager.get_by_name("b").is_default is True  # type: ignore[union-attr]


class TestDelete:
    def test_正常删除(self, manager: ChatProviderManager) -> None:
        _make(manager)
        manager.delete("openai-main")
        assert manager.get_by_name("openai-main") is None

    def test_删除不存在的抛_DatabaseError(self, manager: ChatProviderManager) -> None:
        with pytest.raises(DatabaseError, match="不存在"):
            manager.delete("ghost")


class TestSetDefault:
    def test_set_default_清空旧默认(self, manager: ChatProviderManager) -> None:
        _make(manager, name="a", is_default=True)
        _make(manager, name="b")

        result = manager.set_default("b")

        assert result.is_default is True
        assert manager.get_by_name("a").is_default is False  # type: ignore[union-attr]
        default = manager.get_default()
        assert default is not None and default.name == "b"

    def test_set_default_不存在的抛_DatabaseError(
        self, manager: ChatProviderManager
    ) -> None:
        with pytest.raises(DatabaseError, match="不存在"):
            manager.set_default("ghost")
