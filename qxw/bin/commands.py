"""qxw 命令入口

列出 QXW 工具集提供的所有命令。
通过读取已安装包的元数据，动态获取所有注册的命令入口并展示。

用法:
    qxw          # 列出所有命令
    qxw --help   # 查看帮助信息
"""

import sys
from importlib.metadata import PackageNotFoundError, distribution

import click
from rich.console import Console
from rich.table import Table

from qxw import __version__
from qxw.library.base.exceptions import QxwError
from qxw.library.base.logger import get_logger

logger = get_logger("qxw.commands")
console = Console()


# ============================================================
# 命令收集
# ============================================================


def _collect_commands() -> list[tuple[str, str]]:
    """从已安装包的元数据中收集所有命令及其说明

    遍历 qxw 包注册的 console_scripts 入口点，
    尝试加载对应的 Click 命令对象以提取帮助文本。

    Returns:
        按命令名排序的 (命令名, 说明) 列表
    """
    try:
        dist = distribution("qxw")
    except PackageNotFoundError:
        logger.warning("qxw 包未安装，无法读取命令列表")
        return []

    commands: list[tuple[str, str]] = []
    for ep in dist.entry_points:
        if ep.group != "console_scripts":
            continue

        help_text = ""
        try:
            cmd = ep.load()
            if hasattr(cmd, "help") and cmd.help:
                help_text = cmd.help.split("\n")[0].strip()
        except Exception:
            logger.debug("无法加载命令 %s 的帮助信息", ep.name)

        commands.append((ep.name, help_text))

    commands.sort(key=lambda x: x[0])
    return commands


# ============================================================
# CLI 入口 (Click)
# ============================================================


@click.command(
    name="qxw",
    help="列出 QXW 工具集提供的所有命令",
    epilog="使用 <命令> --help 查看各命令的详细用法。",
)
@click.version_option(
    version=__version__,
    prog_name="qxw",
    message="%(prog)s 版本 %(version)s",
)
def main() -> None:
    """列出 QXW 工具集提供的所有命令

    从已安装包的元数据中读取所有注册的命令入口，
    以表格形式展示命令名称和简要说明。

    \b
    示例:
        qxw              # 列出所有命令
        qxw --version    # 查看版本号
    """
    try:
        commands = _collect_commands()

        if not commands:
            click.echo("未找到已注册的命令。请确认 qxw 已正确安装。")
            return

        table = Table(title=f"QXW 命令列表 (v{__version__})")
        table.add_column("命令", style="cyan")
        table.add_column("说明")

        for name, help_text in commands:
            table.add_row(name, help_text)

        console.print(table)
        console.print(f"\n共 {len(commands)} 个命令，使用 [cyan]<命令> --help[/] 查看详细用法。")

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
