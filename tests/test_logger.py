"""qxw.library.base.logger 单元测试

覆盖：
- setup_logger：重复调用不加 handler、未知 log_level 回退 INFO、log_file 触发 FileHandler 并创建目录
- get_logger：未配置时自动 setup，已配置时复用
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from qxw.library.base import logger as logger_mod


def _reset(name: str) -> None:
    lg = logging.getLogger(name)
    for h in list(lg.handlers):
        try:
            h.close()
        except Exception:
            pass
        lg.removeHandler(h)


class TestSetupLogger:
    def test_默认无_log_file_只建_stream_handler(self) -> None:
        name = "qxw.test_logger.no_file"
        _reset(name)
        log = logger_mod.setup_logger(name)
        try:
            assert len(log.handlers) == 1
            assert isinstance(log.handlers[0], logging.StreamHandler)
            assert not any(isinstance(h, logging.FileHandler) for h in log.handlers)
        finally:
            _reset(name)

    def test_重复调用不重复添加_handler(self) -> None:
        name = "qxw.test_logger.reuse"
        _reset(name)
        log1 = logger_mod.setup_logger(name)
        log2 = logger_mod.setup_logger(name)
        try:
            assert log1 is log2
            assert len(log1.handlers) == 1
        finally:
            _reset(name)

    def test_未知_log_level_回退_INFO(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("QXW_LOG_LEVEL", "NOT_A_LEVEL")
        name = "qxw.test_logger.bad_level"
        _reset(name)
        log = logger_mod.setup_logger(name)
        try:
            assert log.level == logging.INFO
        finally:
            _reset(name)

    def test_log_level_小写也支持(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("QXW_LOG_LEVEL", "debug")
        name = "qxw.test_logger.lowercase"
        _reset(name)
        log = logger_mod.setup_logger(name)
        try:
            assert log.level == logging.DEBUG
        finally:
            _reset(name)

    def test_log_file_触发_FileHandler_并自动创建目录(self, tmp_path: Path) -> None:
        name = "qxw.test_logger.with_file"
        _reset(name)
        log = logger_mod.setup_logger(name, log_file="run.log")
        try:
            file_handlers = [h for h in log.handlers if isinstance(h, logging.FileHandler)]
            assert len(file_handlers) == 1
            # 日志目录由 settings.log_dir 决定，conftest 已把它指向 tmp_path 下
            from qxw.config.settings import get_settings

            assert get_settings().log_dir.is_dir()
            assert Path(file_handlers[0].baseFilename).name == "run.log"
        finally:
            _reset(name)


class TestGetLogger:
    def test_未配置时自动_setup(self) -> None:
        name = "qxw.test_logger.get_auto"
        _reset(name)
        log = logger_mod.get_logger(name)
        try:
            assert len(log.handlers) >= 1
        finally:
            _reset(name)

    def test_已配置时直接返回_不新加_handler(self) -> None:
        name = "qxw.test_logger.get_exist"
        _reset(name)
        first = logger_mod.setup_logger(name)
        before = list(first.handlers)
        second = logger_mod.get_logger(name)
        try:
            assert first is second
            assert list(first.handlers) == before
        finally:
            _reset(name)

    def test_默认名_qxw(self) -> None:
        log = logger_mod.get_logger()
        assert log.name == "qxw"
