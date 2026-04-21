"""qxw completion 子命令入口

作为 ``qxw`` 命令组的子命令使用（原 ``qxw-completion`` 独立命令已合并）。

为所有已注册的 qxw* 命令一次性生成 Shell 补全脚本（zsh / bash），
并可选择自动写入用户的 shell rc 文件。

用法:
    qxw completion install               # 自动检测 $SHELL 并安装
    qxw completion install --shell zsh   # 指定 shell
    qxw completion uninstall             # 移除补全脚本和 rc 中注入的 source 行
    qxw completion show --shell bash     # 仅打印脚本到 stdout，不落盘
    qxw completion status                # 显示当前安装状态
"""

import contextlib
import datetime as dt
import io
import os
import platform
import sys
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path

import click
from click.shell_completion import get_completion_class
from rich.console import Console
from rich.table import Table

from qxw import __version__
from qxw.library.base.exceptions import QxwError
from qxw.library.base.logger import get_logger

logger = get_logger("qxw.completion")
console = Console()


# ============================================================
# 常量
# ============================================================

SUPPORTED_SHELLS: tuple[str, ...] = ("zsh", "bash")
SELF_NAME = "qxw-completion"
COMPLETIONS_DIR = Path.home() / ".config" / "qxw" / "completions"
MARKER_BEGIN = "# >>> qxw-completion >>>"
MARKER_END = "# <<< qxw-completion <<<"


# ============================================================
# 工具函数
# ============================================================


def _detect_shell(explicit: str) -> str:
    """解析 --shell 参数；auto 时从 $SHELL 推断"""
    if explicit in SUPPORTED_SHELLS:
        return explicit
    if explicit == "auto":
        shell_env = os.environ.get("SHELL", "")
        name = Path(shell_env).name if shell_env else ""
        if name in SUPPORTED_SHELLS:
            return name
        raise QxwError(
            f"无法从 $SHELL={shell_env!r} 自动识别 shell，请使用 --shell 指定 {'/'.join(SUPPORTED_SHELLS)}"
        )
    raise QxwError(f"不支持的 shell: {explicit}，仅支持 {'/'.join(SUPPORTED_SHELLS)}")


def _rc_path(shell: str) -> Path:
    """返回对应 shell 的 rc 文件路径（不保证存在）"""
    home = Path.home()
    if shell == "zsh":
        return home / ".zshrc"
    if shell == "bash":
        # macOS 下交互式登录 shell 读 .bash_profile；Linux 通常是 .bashrc
        if platform.system() == "Darwin":
            bp = home / ".bash_profile"
            if bp.exists():
                return bp
            br = home / ".bashrc"
            if br.exists():
                return br
            return bp
        return home / ".bashrc"
    raise QxwError(f"不支持的 shell: {shell}")


def _completion_file_path(shell: str) -> Path:
    return COMPLETIONS_DIR / f"qxw.{shell}"


def _source_line(shell: str) -> str:
    return f'source "{_completion_file_path(shell)}"'


def _iter_qxw_commands() -> tuple[list[tuple[str, object]], list[tuple[str, str]]]:
    """收集所有 qxw* console_scripts 及其 Click 对象

    Returns:
        (loaded, skipped)
        loaded: [(cmd_name, click_command_object), ...]
        skipped: [(cmd_name, error_repr), ...]
    """
    try:
        dist = distribution("qxw")
    except PackageNotFoundError:
        raise QxwError("qxw 包未安装，无法收集命令入口。请先执行 pipx install . 或 pip install -e .") from None

    loaded: list[tuple[str, object]] = []
    skipped: list[tuple[str, str]] = []
    for ep in sorted(dist.entry_points, key=lambda e: e.name):
        if ep.group != "console_scripts":
            continue
        if not ep.name.startswith("qxw"):
            continue
        try:
            cmd = ep.load()
        except Exception as e:  # 可选依赖缺失等
            skipped.append((ep.name, f"{type(e).__name__}: {e}"))
            logger.warning("加载命令 %s 失败，已跳过: %s", ep.name, e)
            continue
        loaded.append((ep.name, cmd))
    return loaded, skipped


def _generate_source_for(shell: str, cmd_name: str, click_obj: object) -> str:
    """为单个 Click 命令生成补全脚本片段"""
    complete_var = "_" + cmd_name.upper().replace("-", "_") + "_COMPLETE"
    cls = get_completion_class(shell)
    if cls is None:
        raise QxwError(f"Click 未提供 {shell} 补全支持")
    inst = cls(cli=click_obj, ctx_args={}, prog_name=cmd_name, complete_var=complete_var)
    # Click 的 BashComplete.source() 会检测本机 bash 版本并把警告写到 stderr，
    # 这里我们自己在命令结尾统一提示一次即可，先把 stderr 吞掉避免每个命令打印一次。
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        return inst.source()


def _build_script(
    shell: str,
    loaded: list[tuple[str, object]],
    skipped: list[tuple[str, str]],
) -> str:
    """拼接所有命令的补全脚本，带头部元信息"""
    now = dt.datetime.now().isoformat(timespec="seconds")
    header_lines = [
        f"# QXW Shell 补全脚本 ({shell})",
        f"# 生成时间: {now}",
        f"# QXW 版本: {__version__}",
        f"# 收录命令 ({len(loaded)}): {', '.join(n for n, _ in loaded) or '(空)'}",
    ]
    if skipped:
        header_lines.append(f"# 跳过命令 ({len(skipped)}):")
        for name, err in skipped:
            header_lines.append(f"#   - {name}: {err}")
    header_lines.append("# 本文件由 `qxw completion install` 生成，请勿手动编辑；重跑 install 即可刷新。")
    header = "\n".join(header_lines) + "\n"

    sections: list[str] = []
    for cmd_name, click_obj in loaded:
        try:
            src = _generate_source_for(shell, cmd_name, click_obj)
        except Exception as e:
            logger.warning("生成 %s 的 %s 补全脚本失败，已跳过: %s", cmd_name, shell, e)
            sections.append(f"# [WARN] 生成 {cmd_name} 补全失败: {e}")
            continue
        sections.append(f"# ---- {cmd_name} ----\n{src.rstrip()}")

    return header + "\n" + "\n\n".join(sections) + "\n"


def _rc_has_marker(rc: Path) -> bool:
    if not rc.exists():
        return False
    try:
        text = rc.read_text(encoding="utf-8")
    except OSError:
        return False
    return MARKER_BEGIN in text


def _append_to_rc(rc: Path, shell: str) -> None:
    """在 rc 文件末尾追加一段带 marker 的 source 块"""
    rc.parent.mkdir(parents=True, exist_ok=True)
    today = dt.date.today().isoformat()
    block_lines = [
        "",
        MARKER_BEGIN,
        f"# Added by qxw-completion on {today}",
        _source_line(shell),
        MARKER_END,
        "",
    ]
    block = "\n".join(block_lines)
    existing = rc.read_text(encoding="utf-8") if rc.exists() else ""
    if existing and not existing.endswith("\n"):
        existing += "\n"
    rc.write_text(existing + block, encoding="utf-8")


def _remove_from_rc(rc: Path) -> bool:
    """移除 rc 里被 marker 包围的块；返回是否有改动"""
    if not rc.exists():
        return False
    lines = rc.read_text(encoding="utf-8").splitlines(keepends=True)
    out: list[str] = []
    inside = False
    removed = False
    for line in lines:
        stripped = line.rstrip("\n")
        if not inside and stripped == MARKER_BEGIN:
            inside = True
            removed = True
            # 丢弃紧邻 MARKER_BEGIN 之前的一个空行（install 时主动追加的那行）
            while out and out[-1].strip() == "":
                out.pop()
            continue
        if inside:
            if stripped == MARKER_END:
                inside = False
            continue
        out.append(line)
    if inside:
        # 文件损坏：没遇到 END，按原样回退
        logger.warning("rc 文件 %s 中找到 MARKER_BEGIN 但缺失 MARKER_END，未做修改", rc)
        return False
    # 末尾如有紧邻的空行也清理掉一行，保持干净
    while out and out[-1].strip() == "":
        out.pop()
    new_text = "".join(out)
    if new_text and not new_text.endswith("\n"):
        new_text += "\n"
    if removed:
        rc.write_text(new_text, encoding="utf-8")
    return removed


def _print_post_install_hint(shell: str, rc: Path, rc_was_appended: bool) -> None:
    console.print()
    if rc_was_appended:
        console.print(f"✅ 已在 [cyan]{rc}[/] 追加 source 行")
    else:
        console.print(f"[yellow]ℹ️  {rc} 已包含 qxw-completion 源引用，未重复追加[/]")
    console.print(f"📄 补全脚本: [cyan]{_completion_file_path(shell)}[/]")
    console.print()
    console.print("[bold]下一步：让补全立即生效[/]")
    if shell == "zsh":
        console.print(f"  [green]source {rc}[/]   # 或直接 [green]exec zsh[/]")
        console.print(
            "  [dim]若用 oh-my-zsh：请确保 source 行位于 oh-my-zsh 之后，否则 compinit 未加载，补全不会注册。[/]"
        )
    elif shell == "bash":
        console.print(f"  [green]source {rc}[/]   # 或直接 [green]exec bash[/]")
        console.print("  [dim]bash 需要 >= 4.4；macOS 自带 /bin/bash 是 3.2，可 brew install bash 升级。[/]")


# ============================================================
# CLI 入口 (Click)
# ============================================================


@click.group(
    name="completion",
    help="为所有 qxw* 命令生成并安装 Shell 补全脚本 (zsh / bash)",
    epilog="使用 qxw completion <子命令> --help 查看各子命令的详细帮助。",
    invoke_without_command=True,
)
@click.version_option(
    version=__version__,
    prog_name="qxw completion",
    message="%(prog)s 版本 %(version)s",
)
@click.pass_context
def main(ctx: click.Context) -> None:
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


# ---------- show ----------


@main.command(name="show", help="将补全脚本打印到 stdout，不写入任何文件")
@click.option(
    "--shell",
    type=click.Choice(["zsh", "bash", "auto"], case_sensitive=False),
    default="auto",
    show_default=True,
    help="目标 shell；auto 时根据 $SHELL 自动判断",
)
def show_command(shell: str) -> None:
    """打印补全脚本到 stdout

    \b
    示例:
        qxw completion show
        qxw completion show --shell zsh
        qxw completion show --shell bash > qxw.bash
    """
    try:
        resolved = _detect_shell(shell)
        loaded, skipped = _iter_qxw_commands()
        if not loaded:
            raise QxwError("未找到可用的 qxw* 命令，请确认 qxw 已正确安装")
        script = _build_script(resolved, loaded, skipped)
        click.echo(script, nl=False)
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


# ---------- install ----------


@main.command(name="install", help="生成补全脚本并在 shell rc 中追加 source 行")
@click.option(
    "--shell",
    type=click.Choice(["zsh", "bash", "auto"], case_sensitive=False),
    default="auto",
    show_default=True,
    help="目标 shell；auto 时根据 $SHELL 自动判断",
)
@click.option(
    "--yes",
    "-y",
    "assume_yes",
    is_flag=True,
    default=False,
    help="跳过修改 rc 文件前的交互式确认",
)
def install_command(shell: str, assume_yes: bool) -> None:
    """生成并安装补全脚本到用户 shell

    \b
    典型流程:
        qxw completion install          # 自动检测
        source ~/.zshrc                 # 或 exec zsh
        qxw-image <TAB>                 # 子命令被 tab 补全
    """
    try:
        resolved = _detect_shell(shell)
        logger.info("开始安装 %s 补全", resolved)

        loaded, skipped = _iter_qxw_commands()
        if not loaded:
            raise QxwError("未找到可用的 qxw* 命令，请确认 qxw 已正确安装")

        COMPLETIONS_DIR.mkdir(parents=True, exist_ok=True)
        script = _build_script(resolved, loaded, skipped)
        target = _completion_file_path(resolved)
        target.write_text(script, encoding="utf-8")
        console.print(
            f"📄 已写入补全脚本: [cyan]{target}[/] ([green]{len(loaded)}[/] 个命令"
            + (f"，跳过 [yellow]{len(skipped)}[/]" if skipped else "")
            + ")"
        )
        if skipped:
            for name, err in skipped:
                console.print(f"  [yellow]· 跳过 {name}: {err}[/]")

        rc = _rc_path(resolved)
        if _rc_has_marker(rc):
            _print_post_install_hint(resolved, rc, rc_was_appended=False)
            return

        console.print()
        console.print(f"即将在 [cyan]{rc}[/] 末尾追加：")
        console.print(
            f"[dim]{MARKER_BEGIN}\n# Added by qxw-completion on {dt.date.today().isoformat()}"
            f"\n{_source_line(resolved)}\n{MARKER_END}[/]"
        )
        if not assume_yes:
            if not click.confirm("确认追加？", default=True):
                console.print(
                    "[yellow]已跳过 rc 修改。你可以手动把上面的 source 行加进 rc 文件生效。[/]"
                )
                return

        _append_to_rc(rc, resolved)
        _print_post_install_hint(resolved, rc, rc_was_appended=True)

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


# ---------- uninstall ----------


@main.command(name="uninstall", help="移除补全脚本和 rc 中注入的 source 行")
@click.option(
    "--shell",
    type=click.Choice(["zsh", "bash", "auto"], case_sensitive=False),
    default="auto",
    show_default=True,
    help="目标 shell；auto 时根据 $SHELL 自动判断",
)
@click.option(
    "--yes",
    "-y",
    "assume_yes",
    is_flag=True,
    default=False,
    help="跳过确认提示",
)
def uninstall_command(shell: str, assume_yes: bool) -> None:
    """卸载补全

    \b
    会执行:
      1. 删除 ~/.config/qxw/completions/qxw.<shell>
      2. 移除 rc 文件中被 MARKER 包围的 source 块
    """
    try:
        resolved = _detect_shell(shell)
        target = _completion_file_path(resolved)
        rc = _rc_path(resolved)

        console.print(f"将删除补全脚本: [cyan]{target}[/] {'(存在)' if target.exists() else '(不存在，跳过)'}")
        if _rc_has_marker(rc):
            console.print(f"将从 [cyan]{rc}[/] 移除 qxw-completion 注入的 source 块")
        else:
            console.print(f"[dim]{rc} 未发现 qxw-completion 注入块，跳过[/]")

        if not assume_yes:
            if not click.confirm("确认卸载？", default=True):
                console.print("[yellow]已取消卸载[/]")
                return

        file_removed = False
        if target.exists():
            target.unlink()
            file_removed = True
        rc_removed = _remove_from_rc(rc)

        console.print()
        console.print(
            f"✅ 卸载完成：补全脚本 {'已删除' if file_removed else '未删除'}，"
            f"rc 文件 {'已更新' if rc_removed else '未修改'}"
        )
        if rc_removed:
            console.print(f"[dim]请重新打开 shell，或执行 exec {resolved} 让修改生效。[/]")

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


# ---------- status ----------


@main.command(name="status", help="显示补全安装状态")
@click.option(
    "--shell",
    type=click.Choice(["zsh", "bash", "auto"], case_sensitive=False),
    default="auto",
    show_default=True,
    help="目标 shell；auto 时根据 $SHELL 自动判断",
)
def status_command(shell: str) -> None:
    """查看当前安装状态"""
    try:
        resolved = _detect_shell(shell)
        loaded, skipped = _iter_qxw_commands()
        target = _completion_file_path(resolved)
        rc = _rc_path(resolved)

        table = Table(title=f"qxw completion 状态 ({resolved})")
        table.add_column("项目", style="cyan")
        table.add_column("值")
        table.add_row("检测到的 Shell", resolved)
        table.add_row("Shell 环境变量", os.environ.get("SHELL", "(未设置)"))
        table.add_row("补全脚本路径", str(target))
        table.add_row("补全脚本存在", "是" if target.exists() else "否")
        table.add_row("Shell rc 路径", str(rc))
        table.add_row("rc 存在", "是" if rc.exists() else "否")
        table.add_row("rc 已注入 source 行", "是" if _rc_has_marker(rc) else "否")
        table.add_row("收录命令数", str(len(loaded)))
        table.add_row("跳过命令数", str(len(skipped)))
        console.print(table)

        if loaded:
            console.print("\n[bold]收录的命令：[/]")
            for name, _obj in loaded:
                console.print(f"  • {name}")
        if skipped:
            console.print("\n[bold yellow]跳过的命令：[/]")
            for name, err in skipped:
                console.print(f"  · {name}: {err}")

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
