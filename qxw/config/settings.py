"""全局配置管理

使用 Pydantic BaseSettings 进行强类型配置管理，
支持从环境变量、.env 文件和 ~/.config/qxw/setting.json 加载配置。
"""

import json
import logging
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings

# 使用 logging 而非 qxw.library.base.logger，避免 settings → logger → settings 循环依赖
_settings_logger = logging.getLogger("qxw.config.settings")


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

    # ZenMux（Gemini 3 Pro Image Preview / Nano Banana Pro）封面生成配置
    zenmux_api_key: str = Field(
        default="",
        description="ZenMux API Key（qxw-markdown cover 调用 Gemini 3 Pro Image Preview 使用）",
    )
    zenmux_base_url: str = Field(
        default="https://zenmux.ai/api/vertex-ai",
        description="ZenMux Vertex AI 代理地址",
    )
    zenmux_image_model: str = Field(
        default="google/gemini-3-pro-image-preview",
        description="封面生成默认模型名",
    )

    model_config = {
        "env_prefix": "QXW_",
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

    @model_validator(mode="after")
    def load_json_config(self) -> "AppSettings":
        """从 ~/.config/qxw/setting.json 加载配置

        JSON 解析失败（格式错误）会告警但不阻塞启动，落回默认值；
        IO 错误（权限/磁盘等）同样告警，便于用户在日志里发现配置未生效。
        """
        json_config_path = Path.home() / ".config" / "qxw" / "setting.json"
        if not json_config_path.exists():
            return self
        try:
            with open(json_config_path, "r", encoding="utf-8") as f:
                json_config = json.load(f)
        except json.JSONDecodeError as e:
            _settings_logger.warning("配置文件 JSON 解析失败，已忽略 %s: %s", json_config_path, e)
            return self
        except OSError as e:
            _settings_logger.warning("配置文件读取失败，已忽略 %s: %s", json_config_path, e)
            return self

        # 获取字段类型注解，自动进行 Path 类型转换
        field_types = self.model_fields
        for key, value in json_config.items():
            if key in field_types:
                annotation = field_types[key].annotation
                if annotation is Path and isinstance(value, str):
                    setattr(self, key, Path(value))
                else:
                    setattr(self, key, value)
        return self


# 全局配置单例
_settings: AppSettings | None = None


def get_settings() -> AppSettings:
    """获取全局配置单例"""
    global _settings
    if _settings is None:
        _settings = AppSettings()
    return _settings
