"""qxw.config.init 单元测试

覆盖 check_env / init_env 两个主入口，以及 _get_db_path 的边界。
HOME 已由 conftest 指向 tmp_path，init_env 会在那里创建目录。
"""

from __future__ import annotations

import json
from pathlib import Path

from qxw.config import init as init_mod
from qxw.config.init import _get_db_path, check_env, init_env


class TestGetDbPath:
    def test_sqlite_url_提取文件路径(self) -> None:
        assert _get_db_path("sqlite:////tmp/foo.db") == Path("/tmp/foo.db")

    def test_非_sqlite_返回_None(self) -> None:
        assert _get_db_path("postgresql://user:pw@localhost/db") is None
        assert _get_db_path("mysql+pymysql://x") is None


class TestCheckEnv:
    def test_空环境下所有项都不存在(self, _isolated_home: Path) -> None:
        status = check_env()
        assert status.config_dir_exists is False
        assert status.config_file_exists is False
        assert status.log_dir_exists is False
        assert status.db_file_exists is False
        assert status.all_ready is False

    def test_init_env_完整初始化(self, _isolated_home: Path) -> None:
        status = init_env()

        assert status.all_ready is True
        assert set(status.initialized_items) == {"配置目录", "配置文件", "日志目录", "数据库"}

        cfg_dir = _isolated_home / ".config" / "qxw"
        assert cfg_dir.is_dir()
        assert (cfg_dir / "setting.json").is_file()
        assert (cfg_dir / "logs").is_dir()
        assert (cfg_dir / "qxw.db").is_file()

    def test_init_env_幂等(self, _isolated_home: Path) -> None:
        init_env()
        status = init_env()
        # 二次调用不应报告任何新建项
        assert status.initialized_items == []
        assert status.all_ready is True

    def test_配置文件里的_HOME_占位符会被替换(self, _isolated_home: Path) -> None:
        init_env()
        cfg = json.loads(
            (_isolated_home / ".config" / "qxw" / "setting.json").read_text(encoding="utf-8")
        )
        home_str = str(_isolated_home)
        assert cfg["config_dir"] == f"{home_str}/.config/qxw"
        assert cfg["log_dir"] == f"{home_str}/.config/qxw/logs"
        assert "${HOME}" not in json.dumps(cfg)

    def test_模板缺失时生成最小配置(
        self, _isolated_home: Path, monkeypatch
    ) -> None:
        missing = _isolated_home / "nope" / "setting.json.example"
        monkeypatch.setattr(init_mod, "_SETTING_EXAMPLE_PATH", missing)

        status = init_env()
        assert "配置文件" in status.initialized_items

        cfg = json.loads(
            (_isolated_home / ".config" / "qxw" / "setting.json").read_text(encoding="utf-8")
        )
        assert cfg == {"app_name": "qxw", "debug": False, "log_level": "INFO"}
