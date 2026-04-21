"""qxw 命令入口

QXW 工具集的主命令。作为 click.group 承载若干内置子命令：

- ``qxw list``       列出 QXW 工具集提供的所有 qxw-* 独立命令
- ``qxw hello``      示例命令（原 qxw-hello）
- ``qxw sbdqf``      🐭 老鼠穿越动画（原 qxw-sbdqf）
- ``qxw completion`` Shell 补全管理（原 qxw-completion）

用法:
    qxw                 # 显示帮助（含子命令列表）
    qxw list            # 列出所有 qxw-* 独立命令
    qxw hello --tui     # 调用子命令
    qxw --help          # 查看帮助信息
"""

import sys
from importlib.metadata import PackageNotFoundError, distribution

import click
from rich.console import Console
from rich.table import Table

from qxw import __version__
from qxw.bin.completion import main as _completion_group
from qxw.bin.hello import main as _hello_command
from qxw.bin.sbdqf import main as _sbdqf_command
from qxw.library.base.exceptions import QxwError
from qxw.library.base.logger import get_logger

logger = get_logger("qxw.commands")
console = Console()


# ============================================================
# 命令收集
# ============================================================


def _collect_commands() -> list[tuple[str, str]]:
    """收集 qxw-* 独立命令

    仅枚举已安装包的 console_scripts 入口点中以 ``qxw-`` 开头的命令，
    不展示 qxw 自身的内置子命令（list / hello / sbdqf / completion）。

    Returns:
        按命令名排序的 (命令名, 说明) 列表
    """
    commands: list[tuple[str, str]] = []

    # qxw-* 独立命令
    try:
        dist = distribution("qxw")
    except PackageNotFoundError:
        logger.warning("qxw 包未安装，无法读取独立命令列表")
        commands.sort(key=lambda x: x[0])
        return commands

    for ep in dist.entry_points:
        if ep.group != "console_scripts":
            continue
        if ep.name == "qxw" or not ep.name.startswith("qxw-"):
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


@click.group(
    name="qxw",
    help="QXW 通用开发命令行工具集合",
    epilog="使用 qxw <子命令> --help 查看各子命令的详细用法；qxw list 可列出全部命令。",
    invoke_without_command=True,
)
@click.version_option(
    version=__version__,
    prog_name="qxw",
    message="%(prog)s 版本 %(version)s",
)
@click.pass_context
def main(ctx: click.Context) -> None:
    """QXW 命令主入口

    不带子命令时等同于 ``qxw --help``。
    """
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@main.command(
    name="list",
    help="列出 QXW 工具集提供的所有 qxw-* 独立命令",
)
def list_command() -> None:
    """列出 QXW 工具集所有 qxw-* 独立命令

    \b
    仅输出通过 console_scripts 注册的 qxw-* 独立命令
    （例如 qxw-chat / qxw-image / qxw-markdown ...），
    不展示 qxw 自身的内置子命令（list / hello / sbdqf / completion）。

    \b
    示例:
        qxw list                 # 列出所有 qxw-* 独立命令
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


# ============================================================
# 挂载原先独立的命令为子命令
# ============================================================

main.add_command(_hello_command, name="hello")
main.add_command(_sbdqf_command, name="sbdqf")
main.add_command(_completion_group, name="completion")


if __name__ == "__main__":
    main()
