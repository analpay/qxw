"""qxw-str 命令入口

字符串工具集。目前提供 ``len`` 子命令，用于统计输入字符串的长度。

用法:
    qxw-str len "hello"          # 直接传入字符串
    qxw-str len "你好，世界"      # 支持中文 / emoji
    echo "hello" | qxw-str len   # 从 stdin 读取
    qxw-str --help               # 查看帮助
"""

import sys

import click
from rich.console import Console
from rich.table import Table

from qxw import __version__
from qxw.library.base.exceptions import QxwError
from qxw.library.base.logger import get_logger

logger = get_logger("qxw.str")
console = Console()


# ============================================================
# CLI 入口 (Click)
# ============================================================


@click.group(
    name="qxw-str",
    help="QXW 字符串工具集（长度统计等）",
    epilog="使用 qxw-str <子命令> --help 查看各子命令的详细帮助。",
    invoke_without_command=True,
)
@click.version_option(
    version=__version__,
    prog_name="qxw-str",
    message="%(prog)s 版本 %(version)s",
)
@click.pass_context
def main(ctx: click.Context) -> None:
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@main.command(name="len", help="统计字符串的长度（字符数 / 字节数）")
@click.argument("text", required=False)
@click.option(
    "--quiet",
    "-q",
    is_flag=True,
    default=False,
    help="仅输出字符数（纯数字，便于脚本消费）",
)
@click.option(
    "--bytes",
    "-b",
    "bytes_only",
    is_flag=True,
    default=False,
    help="仅输出 UTF-8 字节数（纯数字，便于脚本消费）",
)
def len_command(text: str | None, quiet: bool, bytes_only: bool) -> None:
    """统计输入字符串的长度

    \b
    字符数：Python len()，按 Unicode 码点计算
    字节数：UTF-8 编码后的字节长度（中文通常 3 字节、emoji 通常 4 字节）

    \b
    示例:
        qxw-str len "hello"              # 字符数: 5 / 字节数: 5
        qxw-str len "你好，世界"          # 字符数: 5 / 字节数: 15
        echo -n "hello world" | qxw-str len
        qxw-str len "你好" -q            # 纯数字 2，适合 $(...) 捕获
    """
    try:
        if quiet and bytes_only:
            raise QxwError("--quiet 与 --bytes 不能同时使用", exit_code=2)

        if text is None:
            if sys.stdin.isatty():
                raise QxwError("未提供字符串参数，也未从 stdin 接收到输入", exit_code=2)
            text = sys.stdin.read()

        char_count = len(text)
        byte_count = len(text.encode("utf-8"))
        logger.info("qxw-str len: char=%d byte=%d", char_count, byte_count)

        if bytes_only:
            click.echo(byte_count)
            return
        if quiet:
            click.echo(char_count)
            return

        table = Table(title="字符串长度统计", show_header=False)
        table.add_column("指标", style="cyan")
        table.add_column("数值", style="green")
        table.add_row("字符数", str(char_count))
        table.add_row("UTF-8 字节数", str(byte_count))
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
