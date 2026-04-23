"""qxw.config.settings 单元测试

conftest 已把 HOME 指向 tmp_path，这里只需关注：
- 默认值与环境变量覆盖
- JSON 配置文件加载（包含 Path 字段的字符串 → Path 转换）
- JSON 解析失败时静默回退
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from qxw.config.settings import AppSettings, get_settings


class TestDefaults:
    def test_默认值基于_HOME(self, _isolated_home: Path) -> None:
        settings = get_settings()
        assert settings.app_name == "qxw"
        assert settings.debug is False
        assert settings.log_level == "INFO"
        assert settings.config_dir == _isolated_home / ".config" / "qxw"
        assert settings.log_dir == _isolated_home / ".config" / "qxw" / "logs"
        assert settings.db_url.endswith("/.config/qxw/qxw.db")

    def test_单例复用(self) -> None:
        a = get_settings()
        b = get_settings()
        assert a is b


class TestJsonOverride:
    def test_JSON_配置覆盖默认值(self, _isolated_home: Path) -> None:
        cfg_dir = _isolated_home / ".config" / "qxw"
        cfg_dir.mkdir(parents=True)
        (cfg_dir / "setting.json").write_text(
            json.dumps(
                {
                    "debug": True,
                    "log_level": "DEBUG",
                    "zenmux_api_key": "sk-test",
                    "log_dir": str(_isolated_home / "custom_logs"),
                }
            ),
            encoding="utf-8",
        )

        settings = AppSettings()

        assert settings.debug is True
        assert settings.log_level == "DEBUG"
        assert settings.zenmux_api_key == "sk-test"
        # 字符串应被自动转换为 Path
        assert isinstance(settings.log_dir, Path)
        assert settings.log_dir == _isolated_home / "custom_logs"

    def test_JSON_解析失败不抛错_静默回退默认值(self, _isolated_home: Path) -> None:
        cfg_dir = _isolated_home / ".config" / "qxw"
        cfg_dir.mkdir(parents=True)
        (cfg_dir / "setting.json").write_text("{ this is not json", encoding="utf-8")

        settings = AppSettings()
        # 依然可得到默认值，不抛异常
        assert settings.log_level == "INFO"

    def test_JSON_中未知键被忽略(self, _isolated_home: Path) -> None:
        cfg_dir = _isolated_home / ".config" / "qxw"
        cfg_dir.mkdir(parents=True)
        (cfg_dir / "setting.json").write_text(
            json.dumps({"unknown_key": "xxx", "debug": True}),
            encoding="utf-8",
        )

        settings = AppSettings()
        assert settings.debug is True
        assert not hasattr(settings, "unknown_key") or getattr(settings, "unknown_key", None) != "xxx"


class TestEnvOverride:
    def test_环境变量_QXW_前缀覆盖(
        self, monkeypatch: pytest.MonkeyPatch, _isolated_home: Path
    ) -> None:
        monkeypatch.setenv("QXW_LOG_LEVEL", "WARNING")
        monkeypatch.setenv("QXW_DEBUG", "true")

        settings = AppSettings()

        assert settings.log_level == "WARNING"
        assert settings.debug is True
