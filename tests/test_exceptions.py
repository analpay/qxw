"""qxw.library.base.exceptions 单元测试

验证每种自定义异常的退出码与消息前缀是稳定契约，
命令入口依赖这些 exit_code 将失败分类给用户。
"""

from __future__ import annotations

import pytest

from qxw.library.base.exceptions import (
    CommandError,
    ConfigError,
    DatabaseError,
    NetworkError,
    QxwError,
    ValidationError,
)


class TestQxwError:
    def test_默认退出码为_1(self) -> None:
        err = QxwError("出错了")
        assert err.message == "出错了"
        assert err.exit_code == 1
        assert str(err) == "出错了"

    def test_支持自定义退出码(self) -> None:
        err = QxwError("参数错误", exit_code=42)
        assert err.exit_code == 42

    def test_可被_except_Exception_捕获(self) -> None:
        with pytest.raises(Exception) as info:
            raise QxwError("boom")
        assert isinstance(info.value, QxwError)


@pytest.mark.parametrize(
    "exc_cls, expected_prefix, expected_exit_code",
    [
        (ConfigError, "配置错误: ", 2),
        (DatabaseError, "数据库错误: ", 3),
        (CommandError, "命令错误: ", 4),
        (NetworkError, "网络错误: ", 5),
        (ValidationError, "校验错误: ", 6),
    ],
)
def test_子类前缀与退出码(
    exc_cls: type[QxwError],
    expected_prefix: str,
    expected_exit_code: int,
) -> None:
    err = exc_cls("foo")
    assert err.message == f"{expected_prefix}foo"
    assert err.exit_code == expected_exit_code
    # 所有子类都应可被 QxwError 兜底捕获
    assert isinstance(err, QxwError)
