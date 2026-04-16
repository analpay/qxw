"""全局配置管理

使用 Pydantic BaseSettings 进行强类型配置管理，
支持从环境变量、.env 文件和 ~/.config/qxw/setting.json 加载配置。
"""

import json
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings


class AppSettings(BaseSettings):
    """应用全局配置"""

    # 应用基础配置
    app_name: str = Field(default="qxw", description="应用名称")
    app_version: str = Field(default="0.1.0", description="应用版本")
    debug: bool = Field(default=False, description="是否开启调试模式")

    # 数据库配置
    db_url: str = Field(
        default=f"sqlite:///{Path.home() / '.config' / 'qxw' / 'qxw.db'}",
        description="数据库连接地址",
    )

    # 日志配置
    log_level: str = Field(default="INFO", description="日志级别")
    log_dir: Path = Field(
        default=Path.home() / ".config" / "qxw" / "logs",
        description="日志目录",
    )

    # 配置文件目录
    config_dir: Path = Field(
        default=Path.home() / ".config" / "qxw",
        description="配置文件目录",
    )

    model_config = {
        "env_prefix": "QXW_",
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

    @model_validator(mode="after")
    def load_json_config(self) -> "AppSettings":
        """从 ~/.config/qxw/setting.json 加载配置"""
        json_config_path = Path.home() / ".config" / "qxw" / "setting.json"
        if json_config_path.exists():
            try:
                with open(json_config_path, "r", encoding="utf-8") as f:
                    json_config = json.load(f)
                for key, value in json_config.items():
                    if hasattr(self, key):
                        if key == "log_dir":
                            setattr(self, key, Path(value))
                        else:
                            setattr(self, key, value)
            except (json.JSONDecodeError, IOError):
                pass
        return self


# 全局配置单例
_settings: AppSettings | None = None


def get_settings() -> AppSettings:
    """获取全局配置单例"""
    global _settings
    if _settings is None:
        _settings = AppSettings()
    return _settings
