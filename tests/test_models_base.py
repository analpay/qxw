"""qxw.library.models.base 单元测试

覆盖：
- get_engine / get_session_factory 读取 settings.db_url
- get_db_session 的提交、异常回滚、会话关闭路径
- init_db 创建所有表
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.pool import StaticPool

from qxw.library.models import base as models_base
from qxw.library.models.base import Base


@pytest.fixture()
def memory_engine(monkeypatch: pytest.MonkeyPatch):
    """提供单连接 in-memory sqlite，并替换 get_engine"""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    # conftest 的 _dispose_engines 已经包了一层 tracking，这里替换真实工厂
    import qxw.library.models.base as _mod

    monkeypatch.setattr(_mod, "get_engine", lambda: engine, raising=True)
    yield engine
    engine.dispose()


class TestGetEngine:
    def test_引擎_url_使用设置中的_db_url(self) -> None:
        # conftest 已把 QXW_DB_URL 指向 tmp_path/.config/qxw/qxw.db
        engine = models_base.get_engine()
        try:
            assert "sqlite" in str(engine.url)
        finally:
            engine.dispose()

    def test_session_factory_能创建可用_session(self, memory_engine) -> None:
        factory = models_base.get_session_factory()
        session = factory()
        try:
            assert session.execute(text("SELECT 1")).scalar() == 1
        finally:
            session.close()


class TestGetDbSession:
    def test_提交路径__可见于后续_session(self, memory_engine) -> None:
        with models_base.get_db_session() as session:
            session.execute(text(
                "INSERT INTO chat_providers "
                "(name, provider_type, base_url, api_key, model, "
                " temperature, max_tokens, top_p, system_prompt, is_default) "
                "VALUES ('p1', 'openai', 'http://x', 'k', 'm', 0.7, 4096, 1.0, '', 0)"
            ))

        with models_base.get_db_session() as session2:
            count = session2.execute(text("SELECT COUNT(*) FROM chat_providers")).scalar()
            assert count == 1

    def test_异常路径__自动_rollback_且原样抛出(self, memory_engine) -> None:
        with pytest.raises(ValueError, match="boom"):
            with models_base.get_db_session() as session:
                session.execute(text(
                    "INSERT INTO chat_providers "
                    "(name, provider_type, base_url, api_key, model, "
                    " temperature, max_tokens, top_p, system_prompt, is_default) "
                    "VALUES ('p2', 'openai', 'http://x', 'k', 'm', 0.7, 4096, 1.0, '', 0)"
                ))
                raise ValueError("boom")

        with models_base.get_db_session() as session2:
            count = session2.execute(text("SELECT COUNT(*) FROM chat_providers")).scalar()
            assert count == 0

    def test_finally_分支__session_一定被_close(self, memory_engine, monkeypatch) -> None:
        closed: list[bool] = []
        real_factory = models_base.get_session_factory()

        def spy_factory():
            class Wrapper:
                def __call__(self):
                    session = real_factory()
                    orig_close = session.close

                    def close_spy(*a, **k):
                        closed.append(True)
                        return orig_close(*a, **k)

                    session.close = close_spy
                    return session
            return Wrapper()

        monkeypatch.setattr(models_base, "get_session_factory", spy_factory)

        # 异常分支也要关闭
        with pytest.raises(RuntimeError):
            with models_base.get_db_session():
                raise RuntimeError("x")
        assert closed == [True]

    def test_sql_异常时_rollback_并向上传递(self, memory_engine) -> None:
        with pytest.raises(OperationalError):
            with models_base.get_db_session() as session:
                session.execute(text("SELECT * FROM 不存在的表"))


class TestInitDb:
    def test_创建所有已注册表(self, monkeypatch) -> None:
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        try:
            monkeypatch.setattr(models_base, "get_engine", lambda: engine)
            models_base.init_db()
            tables = inspect(engine).get_table_names()
            assert "chat_providers" in tables
        finally:
            engine.dispose()

    def test_幂等__二次调用不报错(self, monkeypatch) -> None:
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        try:
            monkeypatch.setattr(models_base, "get_engine", lambda: engine)
            models_base.init_db()
            models_base.init_db()  # 不应抛错
        finally:
            engine.dispose()
