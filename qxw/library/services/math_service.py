"""数学表达式求值服务

对用户输入的字符串表达式进行安全求值，支持以下运算：

- 四则运算：``+`` ``-`` ``*`` ``/``
- 取整除 / 取余：``//`` ``%``
- 次方：``**`` 或 ``^``
- 开方：``sqrt(x)`` 或 ``√x`` / ``√(表达式)``
- 一元正负号：``+x`` ``-x``
- 圆括号分组：``(1 + 2) * 3``

实现上基于 ``ast`` 白名单遍历，不使用 ``eval`` / ``exec`` 等危险函数，
未出现在白名单里的节点（属性访问、函数调用、变量名等）一律抛出
:class:`qxw.library.base.exceptions.ValidationError`。
"""

from __future__ import annotations

import ast
import math
import operator
import re
from typing import Callable

from qxw.library.base.exceptions import ValidationError

Number = int | float

_BIN_OPS: dict[type[ast.operator], Callable[[Number, Number], Number]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

_UNARY_OPS: dict[type[ast.unaryop], Callable[[Number], Number]] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}

_ALLOWED_FUNCS: dict[str, Callable[[Number], Number]] = {
    "sqrt": math.sqrt,
}


def evaluate(expression: str) -> Number:
    """计算字符串形式的数学表达式并返回数值结果

    :param expression: 待计算的数学表达式，如 ``"1 + 2 * 3"`` / ``"sqrt(2)"``
    :raises ValidationError: 表达式为空、语法错误、含不支持的节点、除零、开方负数等
    :return: 计算结果（整数或浮点数）
    """
    if not isinstance(expression, str):
        raise ValidationError(f"表达式必须是字符串，实际类型: {type(expression).__name__}")
    stripped = expression.strip()
    if not stripped:
        raise ValidationError("表达式不能为空")
    normalized = _normalize(stripped)
    try:
        tree = ast.parse(normalized, mode="eval")
    except SyntaxError as e:
        raise ValidationError(f"表达式语法错误: {e.msg}") from e
    return _eval_node(tree.body)


def format_result(value: Number) -> str:
    """将计算结果格式化为字符串

    - 整数值的浮点数（如 ``4.0``）渲染为 ``"4"``
    - 其它浮点数保留 Python 原生 ``repr`` 表达
    """
    if isinstance(value, bool):  # bool 是 int 的子类，单独挡一下避免 True/False 混入
        raise ValidationError("表达式结果不应为布尔值")
    if isinstance(value, float):
        if math.isnan(value):
            raise ValidationError("结果为 NaN")
        if math.isinf(value):
            raise ValidationError("结果为无穷大")
        if value.is_integer():
            return str(int(value))
    return str(value)


def _normalize(expr: str) -> str:
    """将用户友好的写法归一化为 Python 可解析的形式

    - ``^`` → ``**``
    - ``√(x)`` → ``sqrt(x)``
    - ``√<数值>`` → ``sqrt(<数值>)``（不支持 ``√x`` 这种裸表达式，显式要求括号，歧义更少）
    """
    out = expr.replace("^", "**")
    out = re.sub(r"√\s*\(", "sqrt(", out)
    out = re.sub(r"√\s*(\d+(?:\.\d+)?)", r"sqrt(\1)", out)
    return out


def _eval_node(node: ast.AST) -> Number:
    if isinstance(node, ast.Expression):
        return _eval_node(node.body)
    if isinstance(node, ast.Constant):
        value = node.value
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValidationError(f"不支持的常量类型: {type(value).__name__}")
        return value
    if isinstance(node, ast.BinOp):
        op_type = type(node.op)
        if op_type not in _BIN_OPS:
            raise ValidationError(f"不支持的运算符: {op_type.__name__}")
        left = _eval_node(node.left)
        right = _eval_node(node.right)
        try:
            return _BIN_OPS[op_type](left, right)
        except ZeroDivisionError as e:
            raise ValidationError("除数不能为 0") from e
        except OverflowError as e:
            raise ValidationError("计算结果超出数值范围") from e
    if isinstance(node, ast.UnaryOp):
        op_type = type(node.op)
        if op_type not in _UNARY_OPS:
            raise ValidationError(f"不支持的一元运算符: {op_type.__name__}")
        return _UNARY_OPS[op_type](_eval_node(node.operand))
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise ValidationError("只允许直接以函数名调用（例如 sqrt(9)）")
        func_name = node.func.id
        if func_name not in _ALLOWED_FUNCS:
            raise ValidationError(f"不支持的函数: {func_name}")
        if node.keywords:
            raise ValidationError(f"函数 {func_name} 不支持关键字参数")
        if len(node.args) != 1:
            raise ValidationError(f"函数 {func_name} 需要 1 个参数，实际传入 {len(node.args)} 个")
        arg = _eval_node(node.args[0])
        if func_name == "sqrt" and arg < 0:
            raise ValidationError("开方运算不支持负数")
        return _ALLOWED_FUNCS[func_name](arg)
    raise ValidationError(f"不支持的表达式节点: {type(node).__name__}")
