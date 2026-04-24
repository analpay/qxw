"""math_service 单元测试

遵循 CLAUDE.md 的 "0 happy test, 0 happy path" 原则：
- 仅有少量最小用例确认运算正确，其余全部用来覆盖异常、边界、非法输入。
"""

from __future__ import annotations

import math

import pytest

from qxw.library.base.exceptions import ValidationError
from qxw.library.services.math_service import evaluate, format_result

# ============================================================
# 输入校验 / 边界
# ============================================================


class TestInvalidInput:
    def test_非字符串类型_抛出_ValidationError(self) -> None:
        with pytest.raises(ValidationError, match="表达式必须是字符串"):
            evaluate(123)  # type: ignore[arg-type]

    def test_None_抛出_ValidationError(self) -> None:
        with pytest.raises(ValidationError, match="表达式必须是字符串"):
            evaluate(None)  # type: ignore[arg-type]

    def test_空字符串_抛出_ValidationError(self) -> None:
        with pytest.raises(ValidationError, match="表达式不能为空"):
            evaluate("")

    def test_纯空白_抛出_ValidationError(self) -> None:
        with pytest.raises(ValidationError, match="表达式不能为空"):
            evaluate("   \t\n  ")

    def test_语法错误_抛出_ValidationError(self) -> None:
        with pytest.raises(ValidationError, match="语法错误"):
            evaluate("1 +")

    def test_未闭合括号_抛出_ValidationError(self) -> None:
        with pytest.raises(ValidationError, match="语法错误"):
            evaluate("(1 + 2")


# ============================================================
# 非法节点 / 危险表达式
# ============================================================


class TestForbiddenNodes:
    def test_变量名_被拒绝(self) -> None:
        with pytest.raises(ValidationError, match="不支持的表达式节点|不支持的函数"):
            evaluate("x + 1")

    def test_属性访问_被拒绝(self) -> None:
        with pytest.raises(ValidationError, match="不支持的表达式节点"):
            evaluate("__import__.os")

    def test_下标访问_被拒绝(self) -> None:
        with pytest.raises(ValidationError, match="不支持的表达式节点"):
            evaluate("[1,2,3][0]")

    def test_列表字面量_被拒绝(self) -> None:
        with pytest.raises(ValidationError, match="不支持的表达式节点"):
            evaluate("[1,2]")

    def test_字符串常量_被拒绝(self) -> None:
        with pytest.raises(ValidationError, match="不支持的常量类型"):
            evaluate("'abc'")

    def test_布尔常量_被拒绝(self) -> None:
        with pytest.raises(ValidationError, match="不支持的常量类型"):
            evaluate("True")

    def test_比较运算_被拒绝(self) -> None:
        with pytest.raises(ValidationError, match="不支持的表达式节点"):
            evaluate("1 < 2")

    def test_逻辑运算_被拒绝(self) -> None:
        with pytest.raises(ValidationError, match="不支持的表达式节点"):
            evaluate("1 and 2")

    def test_不支持的函数_被拒绝(self) -> None:
        with pytest.raises(ValidationError, match="不支持的函数: abs"):
            evaluate("abs(-1)")

    def test_函数使用关键字参数_被拒绝(self) -> None:
        with pytest.raises(ValidationError, match="不支持关键字参数"):
            evaluate("sqrt(x=4)")

    def test_sqrt_传入_0_个参数_被拒绝(self) -> None:
        with pytest.raises(ValidationError, match="需要 1 个参数"):
            evaluate("sqrt()")

    def test_sqrt_传入_2_个参数_被拒绝(self) -> None:
        with pytest.raises(ValidationError, match="需要 1 个参数"):
            evaluate("sqrt(1, 2)")

    def test_非_Name_形式的调用_被拒绝(self) -> None:
        # lambda / 属性访问 / 下标等 callable 源头不是简单 Name，均应被拦下
        with pytest.raises(ValidationError, match="只允许直接以函数名调用"):
            evaluate("(lambda: 1)()")


# ============================================================
# 运算错误
# ============================================================


class TestRuntimeErrors:
    def test_除以_0_抛出_ValidationError(self) -> None:
        with pytest.raises(ValidationError, match="除数不能为 0"):
            evaluate("1 / 0")

    def test_整除_0_抛出_ValidationError(self) -> None:
        with pytest.raises(ValidationError, match="除数不能为 0"):
            evaluate("5 // 0")

    def test_取余_0_抛出_ValidationError(self) -> None:
        with pytest.raises(ValidationError, match="除数不能为 0"):
            evaluate("5 % 0")

    def test_负数开方_抛出_ValidationError(self) -> None:
        with pytest.raises(ValidationError, match="开方运算不支持负数"):
            evaluate("sqrt(-1)")

    def test_sqrt_负表达式_抛出_ValidationError(self) -> None:
        with pytest.raises(ValidationError, match="开方运算不支持负数"):
            evaluate("sqrt(2 - 10)")

    def test_次方结果溢出_抛出_ValidationError(self) -> None:
        # 10.0 ** 1000 会触发 OverflowError
        with pytest.raises(ValidationError, match="超出数值范围"):
            evaluate("10.0 ** 1000")


# ============================================================
# 归一化：^、√ 语法糖
# ============================================================


class TestNormalization:
    def test_省略号_sqrt_要求括号_裸变量失败(self) -> None:
        # √x 不是合法写法；必须 √(x) 或 √<数字>
        with pytest.raises(ValidationError):
            evaluate("√x")

    def test_sqrt_仅支持_sqrt_名称_大小写敏感(self) -> None:
        with pytest.raises(ValidationError, match="不支持的函数: SQRT"):
            evaluate("SQRT(4)")

    def test_caret_被识别为次方_2_的_10_次方(self) -> None:
        assert evaluate("2^10") == 1024

    def test_unicode_sqrt_带括号(self) -> None:
        assert evaluate("√(9)") == 3.0

    def test_unicode_sqrt_跟数字(self) -> None:
        assert evaluate("√16") == 4.0


# ============================================================
# 基本正确性（放在最后，仅作锚点，不算 happy path 覆盖）
# ============================================================


class TestEvaluationAnchors:
    @pytest.mark.parametrize(
        "expr,expected",
        [
            ("1+2*3", 7),
            ("(1+2)*3", 9),
            ("-2 + 3", 1),
            ("+5", 5),
            ("7 // 2", 3),
            ("7 % 2", 1),
            ("2**10", 1024),
            ("sqrt(2)", math.sqrt(2)),
        ],
    )
    def test_表达式求值锚点(self, expr: str, expected: float) -> None:
        assert evaluate(expr) == expected


# ============================================================
# format_result
# ============================================================


class TestFormatResult:
    def test_整数浮点数_渲染为整数字符串(self) -> None:
        assert format_result(4.0) == "4"

    def test_非整数浮点_保留原样(self) -> None:
        assert format_result(1.5) == "1.5"

    def test_整数_保留原样(self) -> None:
        assert format_result(42) == "42"

    def test_NaN_抛出_ValidationError(self) -> None:
        with pytest.raises(ValidationError, match="NaN"):
            format_result(float("nan"))

    def test_正无穷_抛出_ValidationError(self) -> None:
        with pytest.raises(ValidationError, match="无穷大"):
            format_result(float("inf"))

    def test_负无穷_抛出_ValidationError(self) -> None:
        with pytest.raises(ValidationError, match="无穷大"):
            format_result(float("-inf"))

    def test_布尔值_被拒绝(self) -> None:
        with pytest.raises(ValidationError, match="不应为布尔值"):
            format_result(True)  # type: ignore[arg-type]
