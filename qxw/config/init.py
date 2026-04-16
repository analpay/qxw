"""环境初始化模块

负责检测和初始化 QXW 运行环境，包括：
- 配置目录 (~/.config/qxw/)
- 配置文件 (~/.config/qxw/setting.json)
- 日志目录 (~/.config/qxw/logs/)
- 数据库文件 (qxw.db)
"""

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from qxw.config.settings import get_settings
from qxw.library.base.logger import get_logger

logger = get_logger("qxw.init")

# setting.json.example 所在路径（项目内置模板）
_SETTING_EXAMPLE_PATH = Path(__file__).parent / "setting.json.example"


@dataclass
class InitStatus:
    """环境初始化状态"""

    config_dir_exists: bool = False
    config_file_exists: bool = False
    log_dir_exists: bool = False
    db_file_exists: bool = False
    initialized_items: list[str] = field(default_factory=list)

    @property
    def all_ready(self) -> bool:
        """所有环境是否已就绪"""
        return (
            self.config_dir_exists
            and self.config_file_exists
            and self.log_dir_exists
            and self.db_file_exists
        )


def check_env() -> InitStatus:
    """检测当前环境初始化状态

    Returns:
        InitStatus: 各项环境的就绪情况
    """
    settings = get_settings()
    status = InitStatus()

    status.config_dir_exists = settings.config_dir.is_dir()
    status.config_file_exists = (settings.config_dir / "setting.json").is_file()
    status.log_dir_exists = settings.log_dir.is_dir()

    # 从 db_url 中提取数据库文件路径（仅 sqlite）
    db_path = _get_db_path(settings.db_url)
    status.db_file_exists = db_path.is_file() if db_path else True  # 非 sqlite 跳过检测

    return status


def init_env() -> InitStatus:
    """执行环境初始化

    检测缺失的环境组件并自动创建，返回初始化结果。

    Returns:
        InitStatus: 初始化后的状态，包含本次初始化的项目列表
    """
    settings = get_settings()
    status = check_env()

    # 1. 创建配置目录
    if not status.config_dir_exists:
        settings.config_dir.mkdir(parents=True, exist_ok=True)
        status.config_dir_exists = True
        status.initialized_items.append("配置目录")
        logger.info("已创建配置目录: %s", settings.config_dir)

    # 2. 复制配置文件
    if not status.config_file_exists:
        target = settings.config_dir / "setting.json"
        if _SETTING_EXAMPLE_PATH.is_file():
            # 读取模板并替换 ${HOME} 占位符为实际路径
            with open(_SETTING_EXAMPLE_PATH, "r", encoding="utf-8") as f:
                content = json.load(f)
            home_str = str(Path.home())
            resolved = {}
            for key, value in content.items():
                if isinstance(value, str) and "${HOME}" in value:
                    resolved[key] = value.replace("${HOME}", home_str)
                else:
                    resolved[key] = value
            with open(target, "w", encoding="utf-8") as f:
                json.dump(resolved, f, ensure_ascii=False, indent=4)
        else:
            # 模板文件缺失时生成最小配置
            minimal_config = {
                "app_name": "qxw",
                "debug": False,
                "log_level": "INFO",
            }
            with open(target, "w", encoding="utf-8") as f:
                json.dump(minimal_config, f, ensure_ascii=False, indent=4)
        status.config_file_exists = True
        status.initialized_items.append("配置文件")
        logger.info("已创建配置文件: %s", target)

    # 3. 创建日志目录
    if not status.log_dir_exists:
        settings.log_dir.mkdir(parents=True, exist_ok=True)
        status.log_dir_exists = True
        status.initialized_items.append("日志目录")
        logger.info("已创建日志目录: %s", settings.log_dir)

    # 4. 初始化数据库
    if not status.db_file_exists:
        from qxw.library.models.base import init_db

        init_db()
        status.db_file_exists = True
        status.initialized_items.append("数据库")
        logger.info("已初始化数据库")

    return status


def _get_db_path(db_url: str) -> Path | None:
    """从 SQLite 连接字符串中提取文件路径

    Args:
        db_url: 数据库连接地址

    Returns:
        Path 或 None（非 sqlite 时返回 None）
    """
    if not db_url.startswith("sqlite:///"):
        return None
    return Path(db_url.replace("sqlite:///", ""))
