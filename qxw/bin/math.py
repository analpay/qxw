"""qxw-math 命令入口

数学表达式字符串计算工具。支持四则运算（+ - * /）、次方（** 或 ^）、
开方（sqrt(x) 或 √(x)）以及圆括号分组。

用法:
    qxw-math "1+2*3"              # 直接传入表达式
    qxw-math "2^10"               # 支持 ^ 作为次方
    qxw-math "sqrt(2)"            # 开方
    qxw-math "(1+2)*3 - 4/2"      # 括号 / 混合运算
    echo "2**32" | qxw-math       # 从 stdin 读取
    qxw-math --help               # 查看帮助
"""

from __future__ import annotations

import sys

import click
from rich.console import Console
from rich.table import Table

from qxw import __version__
from qxw.library.base.exceptions import QxwError
from qxw.library.base.logger import get_logger
from qxw.library.services.math_service import evaluate, format_result

logger = get_logger("qxw.math")
console = Console()


# ============================================================
# CLI 入口 (Click)
# ============================================================


@click.command(
    name="qxw-math",
    help="QXW 数学表达式计算器（四则运算 / 次方 / 开方）",
    epilog=(
        "支持的语法：+  -  *  /  //  %  **  ^  sqrt(x)  √(x)  (...)。"
        "使用引号包裹表达式，避免 shell 解释 * / ( ) 等特殊字符。"
    ),
)
@click.argument("expression", required=False)
@click.option(
    "--quiet",
    "-q",
    is_flag=True,
    default=False,
    help="仅输出计算结果（纯数字，便于脚本消费）",
)
@click.version_option(
    version=__version__,
    prog_name="qxw-math",
    message="%(prog)s 版本 %(version)s",
)
def main(expression: str | None, quiet: bool) -> None:
    """对字符串形式的数学表达式进行求值

    \b
    示例:
        qxw-math "1+2*3"                  # 表格输出：表达式 / 结果
        qxw-math "2^10" -q                # 纯数字输出：1024
        qxw-math "sqrt(2)"                # 1.4142135623730951
        qxw-math "(3+4)**2 - 10"          # 39
        echo "100/25" | qxw-math          # 从 stdin 读取
    """
    try:
        if expression is None:
            if sys.stdin.isatty():
                raise QxwError("未提供表达式参数，也未从 stdin 接收到输入", exit_code=2)
            expression = sys.stdin.read()

        result = evaluate(expression)
        rendered = format_result(result)
        logger.info("qxw-math: expr=%r result=%s", expression.strip(), rendered)

        if quiet:
            click.echo(rendered)
            return

        table = Table(title="数学表达式计算", show_header=False)
        table.add_column("字段", style="cyan")
        table.add_column("值", style="green")
        table.add_row("表达式", expression.strip())
        table.add_row("结果", rendered)
        console.print(table)

    except QxwError as e:
        logger.error("命令执行失败: %s", e.message)
        click.echo(f"错误: {e.message}", err=True)
        sys.exit(e.exit_code)
    except KeyboardInterrupt:
        click.echo("\n操作已取消")
        sys.exit(130)
    except Exception as e:
        logger.exception("未预期的错误")
        click.echo(f"未预期的错误: {e}", err=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
