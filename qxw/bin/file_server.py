"""qxw-file-server 命令入口

文件服务器工具，支持通过 HTTP 或 FTP 协议共享目录文件，并提供鉴权保护。

用法:
    qxw-file-server http             # 启动 HTTP 文件服务（默认 8080 端口）
    qxw-file-server http --dir /tmp  # 指定共享目录
    qxw-file-server ftp              # 启动 FTP 文件服务（默认 2121 端口）
    qxw-file-server --help           # 查看帮助
"""

import base64
import io
import mimetypes
import secrets
import string
import sys
import urllib.parse
import zipfile
from functools import partial
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import click
from pydantic import BaseModel, Field
from rich.console import Console

from qxw import __version__
from qxw.library.base.exceptions import QxwError
from qxw.library.base.logger import get_logger

logger = get_logger("qxw.file_server")
console = Console()


# ============================================================
# 数据模型 (Pydantic)
# ============================================================


def _generate_password(length: int = 12) -> str:
    """生成随机密码"""
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


class AuthConfig(BaseModel):
    """鉴权配置"""

    username: str = Field(default="admin", description="用户名")
    password: str = Field(default_factory=lambda: _generate_password(), description="密码")
    auto_generated: bool = Field(default=False, description="密码是否自动生成")


class FileServerConfig(BaseModel):
    """文件服务器配置"""

    directory: Path = Field(description="共享目录路径")
    host: str = Field(default="0.0.0.0", description="监听地址")
    port: int = Field(description="服务端口")
    auth: AuthConfig = Field(description="鉴权配置")
    writable: bool = Field(default=False, description="是否允许上传/写入")


# ============================================================
# HTTP 文件服务器
# ============================================================

_DIR_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>📂 {title}</title>
<style>
:root {{
  --bg: #f8fafc; --card: #fff; --bd: #e2e8f0;
  --tx: #0f172a; --tm: #64748b; --c1: #6366f1;
  --mono: 'SF Mono',SFMono-Regular,Menlo,Consolas,monospace;
}}
*,*::before,*::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
  font-family: -apple-system,BlinkMacSystemFont,'Segoe UI',
    'Noto Sans SC','PingFang SC',sans-serif;
  background: var(--bg); color: var(--tx); line-height: 1.6;
}}
.header {{
  background: linear-gradient(135deg,#0f172a,#1e293b 80%);
  padding: 18px 28px; color: #fff;
  box-shadow: 0 4px 16px rgba(0,0,0,.3);
}}
.header h1 {{ font-size: 17px; font-weight: 700; letter-spacing: -.01em; }}
.header small {{ font-weight: 400; font-size: 12px; opacity: .6; margin-left: 8px; }}
.breadcrumb {{
  padding: 12px 28px; background: var(--card);
  border-bottom: 1px solid var(--bd); font-size: 14px; color: var(--tm);
}}
.breadcrumb a {{ color: var(--c1); text-decoration: none; }}
.breadcrumb a:hover {{ text-decoration: underline; }}
.content {{ max-width: 960px; margin: 24px auto; padding: 0 28px; }}
table {{
  width: 100%; border-collapse: separate; border-spacing: 0;
  background: var(--card); border: 1px solid var(--bd);
  border-radius: 10px; overflow: hidden;
  box-shadow: 0 1px 3px rgba(0,0,0,.06);
}}
th, td {{ padding: 10px 16px; text-align: left; border-bottom: 1px solid #f1f5f9; }}
th {{
  background: #f6f8fa; font-weight: 600; font-size: 12px;
  color: var(--tm); text-transform: uppercase; letter-spacing: .05em;
}}
tr:last-child td {{ border-bottom: none; }}
tr:hover td {{ background: #f8fafc; }}
td a {{ color: var(--c1); text-decoration: none; font-weight: 500; }}
td a:hover {{ text-decoration: underline; }}
.icon {{ margin-right: 6px; }}
.size {{ font-family: var(--mono); font-size: 13px; color: var(--tm); }}
.mtime {{ font-size: 13px; color: var(--tm); }}
.dl {{
  display: inline-block; padding: 3px 10px; font-size: 12px; font-weight: 500;
  color: var(--c1); border: 1px solid var(--bd); border-radius: 6px;
  text-decoration: none; transition: all .15s;
}}
.dl:hover {{ background: var(--c1); color: #fff; border-color: var(--c1); text-decoration: none; }}
</style>
</head>
<body>
<div class="header">
  <h1>📂 QXW File Server<small>v{version}</small></h1>
</div>
<div class="breadcrumb">{breadcrumb}</div>
<div class="content">
<table>
  <thead><tr><th>名称</th><th>大小</th><th>修改时间</th><th>操作</th></tr></thead>
  <tbody>{rows}</tbody>
</table>
</div>
</body>
</html>
"""


def _human_size(size: int) -> str:
    """将字节数格式化为人类可读的大小"""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024:
            return f"{size:.1f} {unit}" if unit != "B" else f"{size} {unit}"
        size /= 1024
    return f"{size:.1f} PB"


def _build_breadcrumb(rel_path: str) -> str:
    """构建面包屑导航 HTML"""
    parts = ['<a href="/">🏠 根目录</a>']
    if rel_path and rel_path != "/":
        segments = rel_path.strip("/").split("/")
        accumulated = ""
        for seg in segments:
            accumulated += "/" + seg
            href = urllib.parse.quote(accumulated) + "/"
            parts.append(f' / <a href="{href}">{seg}</a>')
    return "".join(parts)


class _FileServerHandler(BaseHTTPRequestHandler):
    """HTTP 文件服务请求处理器，支持 Basic Auth"""

    def __init__(self, config: FileServerConfig, *args, **kwargs):
        self.config = config
        super().__init__(*args, **kwargs)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        logger.debug(format, *args)

    def send_error(self, code: int, message: str | None = None, explain: str | None = None) -> None:
        short_msg = self.responses.get(code, ("Error",))[0]
        self.send_response(code, short_msg)
        body = f"<h1>{code} {short_msg}</h1><p>{message or short_msg}</p>".encode("utf-8")
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _check_auth(self) -> bool:
        """校验 Basic Auth 鉴权"""
        auth_header = self.headers.get("Authorization", "")
        if not auth_header.startswith("Basic "):
            return False
        try:
            decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
            username, password = decoded.split(":", 1)
            return username == self.config.auth.username and password == self.config.auth.password
        except Exception:
            return False

    def _require_auth(self) -> bool:
        """如果鉴权失败，发送 401 响应并返回 False"""
        if self._check_auth():
            return True
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="QXW File Server"')
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write("需要鉴权：请提供用户名和密码".encode("utf-8"))
        return False

    def _resolve_path(self, url_path: str) -> Path | None:
        """将 URL 路径解析为安全的文件系统路径"""
        decoded = urllib.parse.unquote(url_path)
        # 防止路径穿越
        rel = decoded.lstrip("/")
        target = (self.config.directory / rel).resolve()
        try:
            target.relative_to(self.config.directory.resolve())
        except ValueError:
            return None
        return target

    def do_GET(self) -> None:
        if not self._require_auth():
            return

        parsed = urllib.parse.urlparse(self.path)
        url_path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)
        target = self._resolve_path(url_path)

        if target is None:
            self.send_error(403, "禁止访问")
            return

        if not target.exists():
            self.send_error(404, "文件不存在")
            return

        if "dl" in query:
            if query["dl"][0] == "zip" and target.is_dir():
                self._serve_zip(target)
            else:
                self._serve_file(target, force_download=True)
        elif target.is_dir():
            self._serve_directory(target, url_path)
        else:
            self._serve_file(target, force_download=False)

    def _serve_directory(self, dir_path: Path, url_path: str) -> None:
        """列出目录内容"""
        if not url_path.endswith("/"):
            self.send_response(301)
            self.send_header("Location", url_path + "/")
            self.end_headers()
            return

        rows: list[str] = []

        rel_path = url_path.strip("/")
        if rel_path:
            parent = "/" + "/".join(rel_path.split("/")[:-1])
            if parent != "/":
                parent += "/"
            rows.append(
                f'<tr><td><span class="icon">📁</span>'
                f'<a href="{parent}">.. (上级目录)</a></td>'
                f'<td class="size">-</td><td class="mtime">-</td><td></td></tr>'
            )

        entries: list[tuple[str, Path]] = []
        try:
            for entry in sorted(dir_path.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower())):
                if entry.name.startswith("."):
                    continue
                entries.append((entry.name, entry))
        except PermissionError:
            self.send_error(403, "无权限读取目录")
            return

        for name, entry_path in entries:
            stat = entry_path.stat()
            mtime = __import__("datetime").datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            href = urllib.parse.quote(name)

            if entry_path.is_dir():
                zip_href = f"{href}/?dl=zip"
                rows.append(
                    f'<tr><td><span class="icon">📁</span>'
                    f'<a href="{href}/">{name}/</a></td>'
                    f'<td class="size">-</td>'
                    f'<td class="mtime">{mtime}</td>'
                    f'<td><a class="dl" href="{zip_href}">📦 打包下载</a></td></tr>'
                )
            else:
                size = _human_size(stat.st_size)
                dl_href = f"{href}?dl=1"
                rows.append(
                    f'<tr><td><span class="icon">📄</span>'
                    f'<a href="{href}">{name}</a></td>'
                    f'<td class="size">{size}</td>'
                    f'<td class="mtime">{mtime}</td>'
                    f'<td><a class="dl" href="{dl_href}">⬇ 下载</a></td></tr>'
                )

        breadcrumb = _build_breadcrumb(url_path)
        title = url_path if url_path != "/" else "根目录"
        html = _DIR_HTML_TEMPLATE.format(
            title=title,
            version=__version__,
            breadcrumb=breadcrumb,
            rows="\n".join(rows),
        )
        data = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _serve_file(self, file_path: Path, *, force_download: bool = False) -> None:
        try:
            content_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
            stat = file_path.stat()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(stat.st_size))
            if force_download or not content_type.startswith(
                ("text/", "image/", "application/json", "application/pdf")
            ):
                encoded_name = urllib.parse.quote(file_path.name)
                self.send_header(
                    "Content-Disposition",
                    f"attachment; filename*=UTF-8''{encoded_name}",
                )
            self.end_headers()

            with open(file_path, "rb") as f:
                while True:
                    chunk = f.read(65536)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
        except PermissionError:
            self.send_error(403, "无权限读取文件")
        except Exception as e:
            logger.error("文件读取失败: %s", e)
            self.send_error(500, "文件读取失败")

    def _serve_zip(self, dir_path: Path) -> None:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for entry in sorted(dir_path.rglob("*")):
                if entry.is_file() and not entry.name.startswith("."):
                    zf.write(entry, entry.relative_to(dir_path))

        zip_bytes = buf.getvalue()
        encoded_name = urllib.parse.quote(f"{dir_path.name}.zip")
        self.send_response(200)
        self.send_header("Content-Type", "application/zip")
        self.send_header("Content-Length", str(len(zip_bytes)))
        self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{encoded_name}")
        self.end_headers()
        self.wfile.write(zip_bytes)


# ============================================================
# FTP 文件服务器
# ============================================================

_FTP_HINT = "FTP 功能需要安装 pyftpdlib 库: pip install pyftpdlib"


def _start_ftp_server(config: FileServerConfig) -> None:
    """启动 FTP 文件服务器"""
    try:
        from pyftpdlib.authorizers import DummyAuthorizer
        from pyftpdlib.handlers import FTPHandler
        from pyftpdlib.servers import FTPServer
    except ImportError:
        raise QxwError(_FTP_HINT) from None

    authorizer = DummyAuthorizer()

    # pyftpdlib 权限码: e=更改目录, l=列出, r=读取, a=追加, d=删除, f=重命名, m=建目录, w=写入
    perm = "elradfmw" if config.writable else "elr"
    authorizer.add_user(
        config.auth.username,
        config.auth.password,
        str(config.directory),
        perm=perm,
    )

    handler = FTPHandler
    handler.authorizer = authorizer
    handler.banner = f"QXW FTP File Server v{__version__}"
    # 被动模式端口范围
    handler.passive_ports = range(60000, 60100)

    server = FTPServer((config.host, config.port), handler)
    server.max_cons = 128
    server.max_cons_per_ip = 10

    server.serve_forever()


# ============================================================
# CLI 入口 (Click)
# ============================================================


def _print_auth_info(config: FileServerConfig, protocol: str) -> None:
    """打印鉴权信息"""
    console.print("\n🔐 [bold]鉴权信息[/]")
    console.print(f"   用户名: [cyan]{config.auth.username}[/]")
    console.print(f"   密码:   [cyan]{config.auth.password}[/]")
    if config.auth.auto_generated:
        console.print("   [dim]（密码为自动生成，下次启动将会变化）[/]")


def _validate_directory(directory: str) -> Path:
    """校验并返回目录路径"""
    dir_path = Path(directory).resolve()
    if not dir_path.is_dir():
        raise click.BadParameter(f"目录不存在: {directory}")
    return dir_path


@click.group(
    name="qxw-file-server",
    help="QXW 文件服务器（HTTP / FTP 文件共享，支持鉴权）",
    epilog="使用 qxw-file-server <子命令> --help 查看各子命令的详细帮助。",
    invoke_without_command=True,
)
@click.version_option(
    version=__version__,
    prog_name="qxw-file-server",
    message="%(prog)s 版本 %(version)s",
)
@click.pass_context
def main(ctx: click.Context) -> None:
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@main.command(name="http", help="启动 HTTP 文件服务器（带 Basic Auth 鉴权）")
@click.option("--dir", "-d", "directory", default=".", show_default=True, help="共享目录路径")
@click.option("--port", "-p", default=8080, show_default=True, type=int, help="服务端口")
@click.option("--host", "-H", default="127.0.0.1", show_default=True, help="监听地址")
@click.option("--username", "-u", default="admin", show_default=True, help="鉴权用户名")
@click.option("--password", "-P", default=None, help="鉴权密码（不指定则自动生成）")
@click.option("--writable", "-w", is_flag=True, default=False, help="允许上传文件（暂不支持，保留选项）")
def http_command(directory: str, port: int, host: str, username: str, password: str | None, writable: bool) -> None:
    """启动 HTTP 文件服务器

    提供 Web 界面浏览和下载目录中的文件，使用 HTTP Basic Auth 进行鉴权保护。

    \b
    示例:
        qxw-file-server http                       # 共享当前目录（8080 端口）
        qxw-file-server http -d /tmp               # 共享 /tmp 目录
        qxw-file-server http -p 9000               # 指定端口
        qxw-file-server http -u user -P mypass     # 指定用户名和密码
        qxw-file-server http -H 127.0.0.1          # 仅本机访问
    """
    try:
        dir_path = _validate_directory(directory)
        auto_generated = password is None
        auth = AuthConfig(
            username=username,
            password=password if password else _generate_password(),
            auto_generated=auto_generated,
        )
        config = FileServerConfig(
            directory=dir_path,
            host=host,
            port=port,
            auth=auth,
            writable=writable,
        )

        console.print(f"📂 [bold]QXW HTTP File Server[/] v{__version__}")
        console.print(f"📁 共享目录: [cyan]{dir_path}[/]")
        console.print(f"🌐 服务地址: [link=http://{host}:{port}]http://{host}:{port}[/link]")
        _print_auth_info(config, "http")
        console.print("\n按 Ctrl+C 停止服务\n")

        handler = partial(_FileServerHandler, config)
        server = HTTPServer((host, port), handler)
        server.serve_forever()

    except OSError as e:
        if "Address already in use" in str(e) or getattr(e, "errno", 0) == 48:
            click.echo(f"错误: 端口 {port} 已被占用，请使用 -p 指定其他端口", err=True)
        else:
            click.echo(f"错误: {e}", err=True)
        sys.exit(1)
    except QxwError as e:
        logger.error("命令执行失败: %s", e.message)
        click.echo(f"错误: {e.message}", err=True)
        sys.exit(e.exit_code)
    except KeyboardInterrupt:
        click.echo("\n服务已停止")
    except Exception as e:
        logger.exception("未预期的错误")
        click.echo(f"未预期的错误: {e}", err=True)
        sys.exit(1)


@main.command(name="ftp", help="启动 FTP 文件服务器（带用户鉴权）")
@click.option("--dir", "-d", "directory", default=".", show_default=True, help="共享目录路径")
@click.option("--port", "-p", default=2121, show_default=True, type=int, help="服务端口")
@click.option("--host", "-H", default="0.0.0.0", show_default=True, help="监听地址")
@click.option("--username", "-u", default="admin", show_default=True, help="鉴权用户名")
@click.option("--password", "-P", default=None, help="鉴权密码（不指定则自动生成）")
@click.option("--writable", "-w", is_flag=True, default=False, help="允许上传 / 写入 / 删除文件")
def ftp_command(directory: str, port: int, host: str, username: str, password: str | None, writable: bool) -> None:
    """启动 FTP 文件服务器

    使用 FTP 协议共享目录文件，客户端需提供用户名和密码登录。
    默认只读模式，使用 -w 选项开启写入权限。

    \b
    示例:
        qxw-file-server ftp                        # 共享当前目录（2121 端口）
        qxw-file-server ftp -d /tmp                # 共享 /tmp 目录
        qxw-file-server ftp -p 21                  # 指定端口（需 root 权限）
        qxw-file-server ftp -u user -P mypass      # 指定用户名和密码
        qxw-file-server ftp -w                     # 允许写入
    """
    try:
        dir_path = _validate_directory(directory)
        auto_generated = password is None
        auth = AuthConfig(
            username=username,
            password=password if password else _generate_password(),
            auto_generated=auto_generated,
        )
        config = FileServerConfig(
            directory=dir_path,
            host=host,
            port=port,
            auth=auth,
            writable=writable,
        )

        console.print(f"📂 [bold]QXW FTP File Server[/] v{__version__}")
        console.print(f"📁 共享目录: [cyan]{dir_path}[/]")
        console.print(f"🌐 服务地址: [cyan]ftp://{host}:{port}[/]")
        perm_str = "读写（上传/删除/重命名）" if writable else "只读"
        console.print(f"🔒 权限模式: {perm_str}")
        _print_auth_info(config, "ftp")
        console.print("\n按 Ctrl+C 停止服务\n")

        _start_ftp_server(config)

    except OSError as e:
        if "Address already in use" in str(e) or getattr(e, "errno", 0) == 48:
            click.echo(f"错误: 端口 {port} 已被占用，请使用 -p 指定其他端口", err=True)
        else:
            click.echo(f"错误: {e}", err=True)
        sys.exit(1)
    except QxwError as e:
        logger.error("命令执行失败: %s", e.message)
        click.echo(f"错误: {e.message}", err=True)
        sys.exit(e.exit_code)
    except KeyboardInterrupt:
        click.echo("\n服务已停止")
    except Exception as e:
        logger.exception("未预期的错误")
        click.echo(f"未预期的错误: {e}", err=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
