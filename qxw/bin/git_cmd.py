"""qxw-git 命令入口

git 仓库相关工具集合。当前提供：

- ``archive``: 把 git 仓库打包为 tar / zip 包，包内不含 ``.git`` 目录，
  且 git-lfs 文件已实体化下载

用法::

    qxw-git archive                                 # 当前仓库 → ../<repo>.tar
    qxw-git archive -f tar.gz                       # 输出 .tar.gz
    qxw-git archive -f zip -o /tmp/repo.zip         # 自定义路径
    qxw-git archive --no-lfs                        # 跳过 git lfs pull
    qxw-git archive /path/to/repo                   # 打包指定路径
    qxw-git archive -r v1.2.0                       # 打包 tag v1.2.0
    qxw-git archive --ref main                      # 打包 main 分支当前提交
    qxw-git --help                                  # 查看帮助
"""

from __future__ import annotations

import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from qxw import __version__
from qxw.library.base.exceptions import QxwError
from qxw.library.base.logger import get_logger
from qxw.library.services.git_archive_service import (
    DEFAULT_FORMAT,
    SUPPORTED_FORMATS,
    archive_repo,
)

logger = get_logger("qxw.git")
console = Console()


# ============================================================
# 辅助
# ============================================================


def _human_size(n: int) -> str:
    """把字节数格式化为人类可读字符串"""
    if n < 0:
        return f"{n} B"
    units = ["B", "KB", "MB", "GB", "TB"]
    val = float(n)
    for u in units:
        if val < 1024:
            return f"{val:.2f} {u}"
        val /= 1024
    return f"{val:.2f} PB"


# ============================================================
# CLI 入口 (Click)
# ============================================================


@click.group(
    name="qxw-git",
    help="QXW git 工具集（仓库打包等）",
    epilog="使用 qxw-git <子命令> --help 查看各子命令的详细帮助。",
    invoke_without_command=True,
)
@click.version_option(
    version=__version__,
    prog_name="qxw-git",
    message="%(prog)s 版本 %(version)s",
)
@click.pass_context
def main(ctx: click.Context) -> None:
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@main.command(
    name="archive",
    help="将 git 仓库打包为 tar / zip 包（不含 .git，LFS 文件已实体化下载）",
)
@click.argument(
    "repo",
    required=False,
    type=click.Path(exists=False, file_okay=False, dir_okay=True, path_type=Path),
)
@click.option(
    "--format",
    "-f",
    "fmt",
    type=click.Choice(list(SUPPORTED_FORMATS), case_sensitive=False),
    default=DEFAULT_FORMAT,
    show_default=True,
    help="打包格式（tar / tar.gz / tar.bz2 / tar.xz / zip）",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="输出文件路径；缺省时在仓库父目录生成 <仓库名>.<格式>",
)
@click.option(
    "--prefix",
    type=str,
    default=None,
    help="包内顶层目录名，缺省 = 仓库目录名",
)
@click.option(
    "--ref",
    "-r",
    "ref",
    type=str,
    default=None,
    help="要打包的分支 / tag / commit-ish（任意 git rev-parse 可解析的引用）；缺省 = 当前工作树",
)
@click.option(
    "--no-lfs",
    "no_lfs",
    is_flag=True,
    default=False,
    help="跳过 git lfs pull（不需要实体化 LFS 文件时使用）",
)
@click.option(
    "--quiet",
    "-q",
    is_flag=True,
    default=False,
    help="仅输出生成包路径（纯文本），便于脚本 $(...) 捕获",
)
def archive_command(
    repo: Path | None,
    fmt: str,
    output: Path | None,
    prefix: str | None,
    ref: str | None,
    no_lfs: bool,
    quiet: bool,
) -> None:
    """把 git 项目打包为 tar / zip 包

    \b
    要点:
    - 包内不含 .git 目录（仅打包 git ls-files 列出的跟踪文件）
    - 默认在打包前执行 git lfs pull，确保 LFS 指针文件已实体化为真实内容
    - 默认格式 tar；可通过 -f 切换为 tar.gz / tar.bz2 / tar.xz / zip

    \b
    示例:
        qxw-git archive
        qxw-git archive -f tar.gz
        qxw-git archive -f zip -o /tmp/myrepo.zip
        qxw-git archive --no-lfs --quiet
        qxw-git archive /path/to/repo --prefix release-1.0
        qxw-git archive -r main                 # 打包 main 分支当前提交
        qxw-git archive -r v1.2.0 -f tar.gz     # 打包 tag v1.2.0 为 tar.gz
        qxw-git archive --ref feature/x         # 含 / 的分支名也支持
    """
    try:
        repo_path = repo if repo is not None else Path.cwd()
        result = archive_repo(
            repo_path=repo_path,
            output=output,
            fmt=fmt.lower(),
            pull_lfs=not no_lfs,
            arcname_prefix=prefix,
            ref=ref,
        )

        logger.info(
            "qxw-git archive: src=%s ref=%s out=%s files=%d size=%d lfs_pulled=%s",
            repo_path,
            ref or "<working-tree>",
            result.output_path,
            result.file_count,
            result.archive_size,
            result.lfs_pulled,
        )

        if quiet:
            click.echo(str(result.output_path))
            return

        table = Table(title="git 仓库打包结果", show_header=False)
        table.add_column("字段", style="cyan")
        table.add_column("值", style="green")
        table.add_row("输出路径", str(result.output_path))
        table.add_row("Ref", result.ref or "(当前工作树)")
        table.add_row("文件数", str(result.file_count))
        table.add_row("包大小", _human_size(result.archive_size))
        table.add_row("LFS 已 pull", "是" if result.lfs_pulled else "否")
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
