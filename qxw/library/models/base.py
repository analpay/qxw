"""SQLAlchemy 数据库基础配置

提供数据库引擎、会话工厂和模型基类。
使用 SQLAlchemy 2.0 风格。
"""

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from qxw.config.settings import get_settings


class Base(DeclarativeBase):
    """SQLAlchemy ORM 模型基类

    所有 ORM 模型都应继承此类。
    """

    pass


def get_engine():
    """获取数据库引擎

    Returns:
        SQLAlchemy 引擎实例
    """
    settings = get_settings()
    return create_engine(
        settings.db_url,
        echo=settings.debug,
        pool_pre_ping=True,
    )


def get_session_factory() -> sessionmaker[Session]:
    """获取会话工厂

    Returns:
        SQLAlchemy 会话工厂
    """
    engine = get_engine()
    return sessionmaker(bind=engine, expire_on_commit=False)


@contextmanager
def get_db_session() -> Generator[Session, None, None]:
    """获取数据库会话上下文管理器

    使用方式:
        with get_db_session() as session:
            session.query(...)

    Yields:
        SQLAlchemy 会话实例

    Raises:
        Exception: 当数据库操作出错时，自动回滚事务
    """
    session_factory = get_session_factory()
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> None:
    """初始化数据库

    创建所有已注册的表。应在应用启动时调用。
    """
    engine = get_engine()
    Base.metadata.create_all(bind=engine)
