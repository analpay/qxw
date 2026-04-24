"""qxw-serve 命令入口

聚合本项目提供的 HTTP 服务类工具，统一对外暴露 ``qxw-serve <子命令>``。

子命令:
    qxw-serve gitbook     # Markdown 本地预览（支持从网页下载 PDF）
    qxw-serve webtool     # 开发者 Web 工具集（文本对比 / JSON / 加解密 等）
    qxw-serve file-web    # HTTP 文件共享（带 Basic Auth）
    qxw-serve image-web   # 图片画廊（缩略图 / Live Photo / RAW）
    qxw-serve --help      # 查看帮助
"""

from __future__ import annotations

import sys
from pathlib import Path

import click
from rich.console import Console

from qxw import __version__
from qxw.library.base.exceptions import QxwError
from qxw.library.base.logger import get_logger

logger = get_logger("qxw.serve")
console = Console()


# ============================================================
# 公共异常处理
# ============================================================


def _handle_serve_error(func_name: str, port: int):
    """统一打印端口占用 / QxwError / KeyboardInterrupt 的错误信息"""

    def decorate(e: Exception) -> int:
        if isinstance(e, OSError):
            if "Address already in use" in str(e) or getattr(e, "errno", 0) == 48:
                click.echo(f"错误: 端口 {port} 已被占用，请使用 -p 指定其他端口", err=True)
            else:
                click.echo(f"错误: {e}", err=True)
            return 1
        if isinstance(e, QxwError):
            logger.error("命令执行失败: %s", e.message)
            click.echo(f"错误: {e.message}", err=True)
            return e.exit_code
        if isinstance(e, KeyboardInterrupt):
            click.echo("\n服务已停止")
            return 0
        logger.exception("未预期的错误 (%s)", func_name)
        click.echo(f"未预期的错误: {e}", err=True)
        return 1

    return decorate


# ============================================================
# CLI 入口
# ============================================================


@click.group(
    name="qxw-serve",
    help="QXW HTTP 服务集合（gitbook 预览 / 开发者工具 / 文件共享 / 图片画廊）",
    epilog="使用 qxw-serve <子命令> --help 查看各子命令的详细帮助。",
    invoke_without_command=True,
)
@click.version_option(
    version=__version__,
    prog_name="qxw-serve",
    message="%(prog)s 版本 %(version)s",
)
@click.pass_context
def main(ctx: click.Context) -> None:
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


# ============================================================
# gitbook 子命令
# ============================================================


@main.command(name="gitbook", help="启动本地 HTTP 服务预览 Markdown 文件（支持下载 PDF）")
@click.option("--dir", "-d", "directory", default=".", show_default=True, help="Markdown 文件所在目录")
@click.option("--port", "-p", default=8000, show_default=True, type=int, help="服务端口")
@click.option("--host", "-H", default="127.0.0.1", show_default=True, help="监听地址")
def gitbook_command(directory: str, port: int, host: str) -> None:
    """启动 Gitbook 风格的 Markdown 预览服务

    \b
    特性:
        - 左侧自动生成的目录树（按 README.md 标题分组）
        - 每页右上角"下载本页 PDF"按钮（当前 Markdown → 单页 PDF）
        - 侧边栏"下载整本 PDF"按钮（全部 Markdown 合并为单个 PDF）

    \b
    PDF 下载依赖 weasyprint：
        macOS:  brew install pango && pip install weasyprint
        Linux:  apt install libpango-1.0-0 && pip install weasyprint

    \b
    示例:
        qxw-serve gitbook                # 预览当前目录（8000 端口）
        qxw-serve gitbook -p 3000        # 指定端口
        qxw-serve gitbook -d docs/       # 预览 docs/ 目录
        qxw-serve gitbook -H 0.0.0.0     # 允许局域网访问
    """
    try:
        from qxw.library.services.serve_gitbook import (
            GitbookServerConfig,
            require_markdown,
            scan_markdown_count,
            start_server,
        )

        require_markdown()

        base_dir = Path(directory).resolve()
        if not base_dir.is_dir():
            click.echo(f"错误: 目录不存在: {directory}", err=True)
            sys.exit(1)

        file_count = scan_markdown_count(base_dir)
        console.print(f"📖 在 [cyan]{base_dir}[/] 下找到 {file_count} 个 Markdown 文件")
        console.print(f"🌐 服务地址: [link=http://{host}:{port}]http://{host}:{port}[/link]")
        console.print("📥 支持下载: 单页 PDF / 整本 PDF（需 weasyprint）")
        console.print("按 Ctrl+C 停止服务\n")

        config = GitbookServerConfig(directory=base_dir, host=host, port=port, file_count=file_count)
        start_server(config)

    except (OSError, QxwError, KeyboardInterrupt, Exception) as e:
        sys.exit(_handle_serve_error("gitbook", port)(e))


# ============================================================
# webtool 子命令
# ============================================================


@main.command(name="webtool", help="启动开发者 Web 工具集（文本对比 / JSON / 时间戳 / 加解密 / 编解码）")
@click.option("--port", "-p", default=9000, show_default=True, type=int, help="服务端口")
@click.option("--host", "-H", default="127.0.0.1", show_default=True, help="监听地址")
def webtool_command(port: int, host: str) -> None:
    """启动开发者 Web 工具集

    \b
    提供以下工具：
      - 文本对比：两段文本 Unified Diff 差异比较
      - JSON 格式化：格式化 / 压缩 / 校验 / 转义 / 去转义
      - 时间戳转换：Unix 时间戳 ↔ 日期时间
      - 加解密：MD5 / SHA / HMAC / AES / DES / 3DES / RSA / Ed25519 / 证书解析
      - URL 编解码：URL Encode / Decode
      - Base64 编解码：Base64 Encode / Decode

    \b
    示例:
        qxw-serve webtool              # 默认 9000 端口
        qxw-serve webtool -p 3000      # 指定端口
        qxw-serve webtool -H 0.0.0.0   # 允许局域网访问
    """
    try:
        from qxw.library.services.serve_webtool import WebtoolServerConfig, start_server

        console.print(f"🛠️  [bold]QXW WebTool[/] v{__version__}")
        console.print(f"🌐 服务地址: [link=http://{host}:{port}]http://{host}:{port}[/link]")
        console.print("按 Ctrl+C 停止服务\n")

        start_server(WebtoolServerConfig(host=host, port=port))

    except (OSError, QxwError, KeyboardInterrupt, Exception) as e:
        sys.exit(_handle_serve_error("webtool", port)(e))


# ============================================================
# file-web 子命令
# ============================================================


@main.command(name="file-web", help="启动 HTTP 文件服务器（带 Basic Auth 鉴权）")
@click.option("--dir", "-d", "directory", default=".", show_default=True, help="共享目录路径")
@click.option("--port", "-p", default=8080, show_default=True, type=int, help="服务端口")
@click.option("--host", "-H", default="127.0.0.1", show_default=True, help="监听地址")
@click.option("--username", "-u", default="admin", show_default=True, help="鉴权用户名")
@click.option("--password", "-P", default=None, help="鉴权密码（不指定则自动生成）")
@click.option("--writable", "-w", is_flag=True, default=False, help="允许上传文件（暂不支持，保留选项）")
def file_web_command(directory: str, port: int, host: str, username: str, password: str | None, writable: bool) -> None:
    """启动 HTTP 文件服务器

    提供 Web 界面浏览和下载目录中的文件，使用 HTTP Basic Auth 进行鉴权保护。

    \b
    示例:
        qxw-serve file-web                       # 共享当前目录（8080 端口）
        qxw-serve file-web -d /tmp               # 共享 /tmp 目录
        qxw-serve file-web -p 9000               # 指定端口
        qxw-serve file-web -u user -P mypass     # 指定用户名和密码
        qxw-serve file-web -H 127.0.0.1          # 仅本机访问
    """
    try:
        from qxw.library.services.serve_file import (
            AuthConfig,
            FileWebServerConfig,
            generate_password,
            start_server,
        )

        dir_path = Path(directory).resolve()
        if not dir_path.is_dir():
            raise click.BadParameter(f"目录不存在: {directory}")

        auto_generated = password is None
        auth = AuthConfig(
            username=username,
            password=password if password else generate_password(),
            auto_generated=auto_generated,
        )
        config = FileWebServerConfig(
            directory=dir_path,
            host=host,
            port=port,
            auth=auth,
            writable=writable,
        )

        console.print(f"📂 [bold]QXW File Server[/] v{__version__}")
        console.print(f"📁 共享目录: [cyan]{dir_path}[/]")
        console.print(f"🌐 服务地址: [link=http://{host}:{port}]http://{host}:{port}[/link]")
        console.print("\n🔐 [bold]鉴权信息[/]")
        console.print(f"   用户名: [cyan]{config.auth.username}[/]")
        console.print(f"   密码:   [cyan]{config.auth.password}[/]")
        if config.auth.auto_generated:
            console.print("   [dim]（密码为自动生成，下次启动将会变化）[/]")
        console.print("\n按 Ctrl+C 停止服务\n")

        start_server(config)

    except (OSError, QxwError, KeyboardInterrupt, Exception) as e:
        sys.exit(_handle_serve_error("file-web", port)(e))


# ============================================================
# image-web 子命令
# ============================================================


@main.command(name="image-web", help="启动图片浏览 HTTP 服务（缩略图画廊，支持 Live Photo）")
@click.option("--dir", "-d", "directory", default=".", show_default=True, help="图片目录路径")
@click.option("--port", "-p", default=8080, show_default=True, type=int, help="服务端口")
@click.option("--host", "-H", default="127.0.0.1", show_default=True, help="监听地址")
@click.option(
    "--thumb-size",
    "-s",
    default=400,
    show_default=True,
    type=click.IntRange(50, 4096),
    help="缩略图尺寸（像素，50-4096）",
)
@click.option(
    "--thumb-quality",
    default=85,
    show_default=True,
    type=click.IntRange(1, 100),
    help="缩略图 JPEG 质量 (1-100)",
)
@click.option("--recursive/--no-recursive", "-r", default=True, show_default=True, help="是否递归扫描子目录")
def image_web_command(
    directory: str,
    port: int,
    host: str,
    thumb_size: int,
    thumb_quality: int,
    recursive: bool,
) -> None:
    """启动图片浏览 HTTP 服务

    提供 Web 画廊界面浏览目录中的图片，自动生成缩略图并缓存。
    支持 Live Photo 检测和播放（需要同目录下同名的图片和视频文件）。

    \b
    支持的图片格式：JPG, PNG, GIF, WebP, BMP, TIFF, HEIC
    支持的 RAW 格式：CR2, CR3, NEF, ARW, DNG, ORF, RW2, PEF, RAF 等
    支持的视频格式：MOV, MP4（Live Photo 关联）

    \b
    示例:
        qxw-serve image-web                           # 浏览当前目录图片
        qxw-serve image-web -d ~/Photos               # 指定图片目录
        qxw-serve image-web -p 9000                   # 指定端口
        qxw-serve image-web -s 300 --thumb-quality 70 # 调整缩略图参数
        qxw-serve image-web --no-recursive            # 不递归扫描子目录
    """
    try:
        try:
            from PIL import Image  # noqa: F401
        except ImportError as e:
            raise QxwError('需要安装 Pillow 库: pip install Pillow 或 pip install "qxw[image]"') from e

        from qxw.library.services.image_service import scan_images
        from qxw.library.services.serve_image import ImageServerConfig, start_server

        dir_path = Path(directory).resolve()
        if not dir_path.is_dir():
            raise click.BadParameter(f"目录不存在: {directory}")

        config = ImageServerConfig(
            directory=dir_path,
            host=host,
            port=port,
            thumb_size=thumb_size,
            thumb_quality=thumb_quality,
        )

        console.print(f"📷 [bold]QXW Image Gallery[/] v{__version__}")
        console.print(f"📁 图片目录: [cyan]{dir_path}[/]")
        console.print("🔍 正在扫描图片...")

        images = scan_images(dir_path, recursive=recursive)
        live_count = sum(1 for img in images if img.is_live)
        raw_count = sum(1 for img in images if img.is_raw)

        console.print(f"   找到 [bold]{len(images)}[/] 张图片", end="")
        if live_count:
            console.print(f"，[red]{live_count}[/] 张 Live Photo", end="")
        if raw_count:
            console.print(f"，[blue]{raw_count}[/] 张 RAW", end="")
        console.print()

        console.print(f"🌐 服务地址: [link=http://{host}:{port}]http://{host}:{port}[/link]")
        console.print("按 Ctrl+C 停止服务\n")

        start_server(config, images)

    except (OSError, QxwError, KeyboardInterrupt, Exception) as e:
        # BadParameter 交回给 click 自己处理
        if isinstance(e, click.ClickException):
            raise
        sys.exit(_handle_serve_error("image-web", port)(e))


if __name__ == "__main__":
    main()
