"""全局配置管理

使用 Pydantic BaseSettings 进行强类型配置管理，
支持从环境变量和 .env 文件加载配置。
"""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings


class AppSettings(BaseSettings):
    """应用全局配置"""

    # 应用基础配置
    app_name: str = Field(default="qxw", description="应用名称")
    app_version: str = Field(default="0.1.0", description="应用版本")
    debug: bool = Field(default=False, description="是否开启调试模式")

    # 数据库配置
    db_url: str = Field(
        default="sqlite:///qxw.db",
        description="数据库连接地址",
    )

    # 日志配置
    log_level: str = Field(default="INFO", description="日志级别")
    log_dir: Path = Field(
        default=Path.home() / ".qxw" / "logs",
        description="日志目录",
    )

    # 配置文件目录
    config_dir: Path = Field(
        default=Path.home() / ".qxw",
        description="配置文件目录",
    )

    model_config = {
        "env_prefix": "QXW_",
        "env_file": ".env",
        "env_file_encoding": "utf-8",
    }


# 全局配置单例
_settings: AppSettings | None = None


def get_settings() -> AppSettings:
    """获取全局配置单例"""
    global _settings
    if _settings is None:
        _settings = AppSettings()
    return _settings
