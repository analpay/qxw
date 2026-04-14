"""日志工具

提供统一的日志配置和获取方法，支持控制台和文件输出。
"""

import logging
import sys
from pathlib import Path

from qxw.config.settings import get_settings


def setup_logger(
    name: str = "qxw",
    log_file: str | None = None,
) -> logging.Logger:
    """配置并返回 Logger 实例

    Args:
        name: Logger 名称，默认为 "qxw"
        log_file: 日志文件名（可选），存放在配置的日志目录下

    Returns:
        配置好的 Logger 实例
    """
    settings = get_settings()
    logger = logging.getLogger(name)

    # 避免重复添加 handler
    if logger.handlers:
        return logger

    logger.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))

    # 日志格式
    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 控制台输出
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # 文件输出（可选）
    if log_file:
        log_dir: Path = settings.log_dir
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(
            log_dir / log_file,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


def get_logger(name: str = "qxw") -> logging.Logger:
    """获取已配置的 Logger 实例

    如果 Logger 尚未配置，会自动调用 setup_logger 进行初始化。

    Args:
        name: Logger 名称

    Returns:
        Logger 实例
    """
    logger = logging.getLogger(name)
    if not logger.handlers:
        return setup_logger(name)
    return logger
