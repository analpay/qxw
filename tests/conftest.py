"""全局 pytest fixtures

关键隔离：
- 将 HOME 指向 tmp_path，防止污染真实的 ~/.config/qxw
- 重置 qxw.config.settings 的单例，保证每个用例拿到干净的 Settings
- 提供 in-memory sqlite 会话工厂，并 monkeypatch 到 models.base.get_db_session
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """把 HOME 与 QXW_* 路径变量指向临时目录

    注意：AppSettings 的路径默认值在模块导入时已通过 ``Path.home()`` 求值并冻结，
    仅设置 HOME 不会改动这些默认。这里通过环境变量前缀 ``QXW_`` 覆盖对应字段。
    """
    monkeypatch.setenv("HOME", str(tmp_path))

    # 清理可能影响 Settings 的非路径环境变量
    for key in (
        "QXW_APP_NAME",
        "QXW_DEBUG",
        "QXW_LOG_LEVEL",
        "QXW_ZENMUX_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)

    # 路径类字段通过 env var 覆盖，强制落到 tmp_path
    cfg_dir = tmp_path / ".config" / "qxw"
    monkeypatch.setenv("QXW_CONFIG_DIR", str(cfg_dir))
    monkeypatch.setenv("QXW_LOG_DIR", str(cfg_dir / "logs"))
    monkeypatch.setenv("QXW_DB_URL", f"sqlite:///{cfg_dir / 'qxw.db'}")
    return tmp_path


@pytest.fixture(autouse=True)
def _reset_settings_singleton() -> Generator[None, None, None]:
    """每个用例前后都清空 get_settings 的全局缓存"""
    import qxw.config.settings as settings_mod

    settings_mod._settings = None
    yield
    settings_mod._settings = None


@pytest.fixture(autouse=True)
def _dispose_engines() -> Generator[None, None, None]:
    """追踪并在用例结束时 dispose 所有经 ``get_engine`` 创建的 engine

    避免 sqlite 连接在 GC 阶段才关闭，产生 ResourceWarning。
    """
    from qxw.library.models import base as models_base

    created: list = []
    orig = models_base.get_engine

    def _tracking() -> object:
        eng = orig()
        created.append(eng)
        return eng

    monkey = pytest.MonkeyPatch()
    monkey.setattr(models_base, "get_engine", _tracking)
    try:
        yield
    finally:
        monkey.undo()
        for eng in created:
            try:
                eng.dispose()
            except Exception:  # noqa: BLE001
                pass


@pytest.fixture()
def in_memory_db(monkeypatch: pytest.MonkeyPatch) -> Generator[sessionmaker[Session], None, None]:
    """提供一个共享连接的 sqlite in-memory 引擎，并替换 get_db_session

    注意：`sqlite:///:memory:` 每次 connect 都是新库，所以这里用
    StaticPool 让所有连接共享同一个底层连接。
    """
    from sqlalchemy.pool import StaticPool

    from qxw.library.models import base as models_base
    from qxw.library.models.base import Base

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    @contextmanager
    def _session() -> Generator[Session, None, None]:
        session = factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    monkeypatch.setattr(models_base, "get_db_session", _session)
    # manager 模块在 import 时已绑定符号，需同步替换
    from qxw.library.managers import chat_provider_manager as mgr_mod

    monkeypatch.setattr(mgr_mod, "get_db_session", _session)

    yield factory

    engine.dispose()
