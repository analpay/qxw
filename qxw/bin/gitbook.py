"""qxw-gitbook 命令入口

Markdown 文档工具：支持批量转换 PDF 和本地预览服务。

用法:
    qxw-gitbook pdf             # 将当前目录的 .md 文件转换为 PDF
    qxw-gitbook pdf -r          # 递归处理子目录
    qxw-gitbook serve           # 启动本地预览服务（默认 8000 端口）
    qxw-gitbook serve -p 3000   # 指定端口
    qxw-gitbook --help          # 查看帮助
"""

import mimetypes
import sys
import urllib.parse
from functools import partial
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import click
from rich.console import Console

from qxw import __version__
from qxw.library.base.exceptions import QxwError
from qxw.library.base.logger import get_logger

logger = get_logger("qxw.gitbook")
console = Console()


# ============================================================
# HTML / CSS 模板
# ============================================================

_COMMON_CSS = """\
body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans SC",
                 "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei",
                 Helvetica, Arial, sans-serif;
    line-height: 1.8;
    color: #24292f;
    margin: 0;
    padding: 0;
}
h1, h2, h3, h4, h5, h6 {
    margin-top: 1.5em; margin-bottom: 0.5em;
    font-weight: 600; line-height: 1.3;
}
h1 { font-size: 2em; border-bottom: 1px solid #d1d9e0; padding-bottom: .3em; }
h2 { font-size: 1.5em; border-bottom: 1px solid #d1d9e0; padding-bottom: .3em; }
h3 { font-size: 1.25em; }
p { margin: .8em 0; }
a { color: #0969da; text-decoration: none; }
a:hover { text-decoration: underline; }
code {
    font-family: "SF Mono", SFMono-Regular, Menlo, Consolas, monospace;
    font-size: .9em; background: #f6f8fa;
    padding: .2em .4em; border-radius: 4px;
}
pre {
    background: #f6f8fa; padding: 1em;
    border-radius: 8px; overflow-x: auto; line-height: 1.5;
}
pre code { background: none; padding: 0; }
table { border-collapse: collapse; width: 100%; margin: 1em 0; }
th, td { border: 1px solid #d1d9e0; padding: .5em 1em; text-align: left; }
th { background: #f6f8fa; font-weight: 600; }
blockquote {
    margin: 1em 0; padding: .5em 1em;
    border-left: 4px solid #d1d9e0; color: #656d76; background: #f6f8fa;
}
img { max-width: 100%; }
hr { border: none; border-top: 1px solid #d1d9e0; margin: 2em 0; }
ul, ol { padding-left: 2em; }
li { margin: .3em 0; }
"""

_PDF_CSS = _COMMON_CSS + """\
@page { size: A4; margin: 2cm; }
body { max-width: none; padding: 0; }
"""

_WEB_EXTRA_CSS = """\
body { background: #fff; }
.layout { display: flex; min-height: 100vh; }
.sidebar {
    width: 280px; flex-shrink: 0;
    background: #f6f8fa; border-right: 1px solid #d1d9e0;
    overflow-y: auto; position: fixed; top: 0; bottom: 0; left: 0;
}
.sidebar-header {
    padding: 1.2em 1.5em; border-bottom: 1px solid #d1d9e0;
}
.sidebar-header a {
    font-weight: 700; font-size: 1.1em; color: #24292f;
}
.nav-tree { list-style: none; padding: .5em 0; margin: 0; }
.nav-tree ul { list-style: none; padding: 0; margin: 0; }
.nav-tree a {
    display: block; padding: .35em 1.5em;
    color: #24292f; font-size: .93em;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.nav-tree a:hover { background: #e8ecf0; text-decoration: none; }
.nav-tree a.active {
    color: #0969da; font-weight: 600; background: #ddf4ff;
    border-right: 3px solid #0969da;
}
.nav-group-title {
    display: block; padding: .7em 1.5em .2em;
    font-weight: 600; font-size: .8em; color: #656d76;
    text-transform: uppercase; letter-spacing: .04em;
}
a.nav-group-title {
    font-size: .8em; text-transform: uppercase; letter-spacing: .04em;
    font-weight: 600; color: #656d76;
}
a.nav-group-title:hover { color: #24292f; background: #e8ecf0; text-decoration: none; }
a.nav-group-title.active { color: #0969da; background: #ddf4ff; }
.nav-group > ul > li > a { padding-left: 2.2em; }
.nav-group > ul > li > .nav-group-title { padding-left: 2.2em; }
.nav-group > ul > li.nav-group > ul > li > a { padding-left: 3em; }
.content {
    flex: 1; margin-left: 280px; padding: 2.5em 3em;
    max-width: 900px; min-width: 0;
}
"""

_WEB_CSS = _COMMON_CSS + _WEB_EXTRA_CSS

_WEB_PAGE = """\
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} - QXW Gitbook</title>
<style>{css}</style>
</head>
<body>
<div class="layout">
  <nav class="sidebar">
    <div class="sidebar-header"><a href="/">📖 {root_title}</a></div>
    <ul class="nav-tree">{sidebar}</ul>
  </nav>
  <main class="content">
{content}
  </main>
</div>
</body>
</html>"""

_PDF_PAGE = """\
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>{css}</style>
</head>
<body>
{content}
</body>
</html>"""


# ============================================================
# 核心功能
# ============================================================


def _find_markdown_files(directory: Path, recursive: bool = False) -> list[Path]:
    pattern = "**/*.md" if recursive else "*.md"
    return sorted(directory.glob(pattern))


def _render_markdown(text: str) -> str:
    import markdown

    extensions = ["tables", "fenced_code", "codehilite", "toc", "sane_lists"]
    extension_configs = {"codehilite": {"noclasses": True, "linenums": False}}
    return markdown.markdown(text, extensions=extensions, extension_configs=extension_configs)


def _convert_one_pdf(md_path: Path, output_dir: Path) -> Path:
    from weasyprint import HTML

    html_body = _render_markdown(md_path.read_text(encoding="utf-8"))
    full_html = _PDF_PAGE.format(title=md_path.stem, css=_PDF_CSS, content=html_body)
    pdf_path = output_dir / f"{md_path.stem}.pdf"
    HTML(string=full_html, base_url=str(md_path.parent)).write_pdf(str(pdf_path))
    return pdf_path


# ============================================================
# HTTP 预览服务
# ============================================================


_STATIC_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico",
    ".css", ".js", ".woff", ".woff2", ".ttf", ".eot",
}

_NAV_EXCLUDED = {"index.md", "summary.md", "readme.md"}


def _extract_title(md_path: Path) -> str:
    try:
        with md_path.open(encoding="utf-8") as f:
            for _ in range(30):
                line = f.readline()
                if not line:
                    break
                stripped = line.strip()
                if stripped.startswith("# ") and not stripped.startswith("## "):
                    return stripped[2:].strip()
    except Exception:
        pass
    return md_path.stem


def _build_sidebar(base_dir: Path, root_dir: Path, current_path: str) -> str:
    parts: list[str] = []

    files = sorted(
        f for f in base_dir.glob("*.md")
        if f.name.lower() not in _NAV_EXCLUDED
    )
    for f in files:
        rel = str(f.relative_to(root_dir))
        href = "/" + urllib.parse.quote(rel)
        title = _extract_title(f)
        cls = ' class="active"' if rel == current_path else ""
        parts.append(f'<li><a href="{href}"{cls}>{title}</a></li>')

    subdirs = sorted(
        d for d in base_dir.iterdir()
        if d.is_dir() and not d.name.startswith((".", "_")) and any(d.rglob("*.md"))
    )
    for d in subdirs:
        readme = d / "README.md"
        if readme.is_file():
            dir_title = _extract_title(readme)
            rel = str(readme.relative_to(root_dir))
            href = "/" + urllib.parse.quote(rel)
            cls = "nav-group-title active" if rel == current_path else "nav-group-title"
            title_html = f'<a href="{href}" class="{cls}">{dir_title}</a>'
        else:
            title_html = f'<span class="nav-group-title">{d.name}</span>'

        children = _build_sidebar(d, root_dir, current_path)
        parts.append(f'<li class="nav-group">{title_html}<ul>{children}</ul></li>')

    return "".join(parts)


class _GitbookHandler(BaseHTTPRequestHandler):

    def __init__(self, base_dir: Path, *args, **kwargs):
        self.base_dir = base_dir
        super().__init__(*args, **kwargs)

    def log_message(self, format, *args):  # noqa: A002
        logger.debug(format, *args)

    def do_GET(self):
        path = urllib.parse.unquote(self.path.split("?")[0])

        if path == "/":
            self._serve_index()
        elif path.endswith(".md"):
            self._serve_markdown(path.lstrip("/"))
        else:
            self._serve_static(path.lstrip("/"))

    def _check_path(self, rel_path: str) -> Path | None:
        file_path = (self.base_dir / rel_path).resolve()
        try:
            file_path.relative_to(self.base_dir.resolve())
        except ValueError:
            self.send_error(403)
            return None
        if not file_path.is_file():
            self.send_error(404)
            return None
        return file_path

    def _render_page(self, rel_path: str, content: str, title: str) -> None:
        root_readme = self.base_dir / "README.md"
        root_title = _extract_title(root_readme) if root_readme.is_file() else "QXW Gitbook"
        sidebar = _build_sidebar(self.base_dir, self.base_dir, rel_path)
        html = _WEB_PAGE.format(
            title=title, css=_WEB_CSS, root_title=root_title,
            sidebar=sidebar, content=content,
        )
        self._respond(html)

    def _serve_index(self):
        readme = self.base_dir / "README.md"
        if readme.is_file():
            content = _render_markdown(readme.read_text(encoding="utf-8"))
        else:
            content = "<h1>📖 QXW Gitbook</h1><p>请从左侧目录选择文件。</p>"
        self._render_page("", content, "首页")

    def _serve_markdown(self, rel_path: str):
        file_path = self._check_path(rel_path)
        if not file_path:
            return
        rendered = _render_markdown(file_path.read_text(encoding="utf-8"))
        self._render_page(rel_path, rendered, _extract_title(file_path))

    def _serve_static(self, rel_path: str):
        file_path = self._check_path(rel_path)
        if not file_path:
            return
        if file_path.suffix.lower() not in _STATIC_EXTENSIONS:
            self.send_error(403)
            return
        content_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
        data = file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _respond(self, html: str):
        data = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


# ============================================================
# CLI 入口 (Click)
# ============================================================


def _require_markdown() -> None:
    try:
        import markdown  # noqa: F401
    except ImportError:
        click.echo("错误: 需要安装 markdown 库。请运行: pip install markdown", err=True)
        sys.exit(1)


def _require_weasyprint() -> None:
    try:
        import weasyprint  # noqa: F401
    except (ImportError, OSError):
        click.echo(
            "错误: 需要安装 weasyprint 库。\n"
            "  macOS:  brew install pango && pip install weasyprint\n"
            "  Linux:  apt install libpango-1.0-0 && pip install weasyprint\n"
            "  详见: https://doc.courtbouillon.org/weasyprint/stable/first_steps.html",
            err=True,
        )
        sys.exit(1)


@click.group(
    name="qxw-gitbook",
    help="QXW Markdown 文档工具（PDF 转换 / 本地预览）",
    epilog="使用 qxw-gitbook <子命令> --help 查看各子命令的详细帮助。",
    invoke_without_command=True,
)
@click.version_option(
    version=__version__,
    prog_name="qxw-gitbook",
    message="%(prog)s 版本 %(version)s",
)
@click.pass_context
def main(ctx: click.Context) -> None:
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@main.command(name="pdf", help="将目录下的 Markdown 文件批量转换为 PDF")
@click.option("--dir", "-d", "directory", default=".", show_default=True, help="Markdown 文件所在目录")
@click.option("--output", "-o", "output_dir", default=None, help="PDF 输出目录（默认与源文件同目录）")
@click.option("--recursive", "-r", is_flag=True, default=False, help="递归处理子目录中的文件")
def pdf_command(directory: str, output_dir: str | None, recursive: bool) -> None:
    """将 Markdown 文件批量转换为 PDF

    \b
    示例:
        qxw-gitbook pdf                  # 转换当前目录下的 .md 文件
        qxw-gitbook pdf -d docs/         # 转换 docs/ 下的 .md 文件
        qxw-gitbook pdf -r               # 递归处理子目录
        qxw-gitbook pdf -o output/       # 指定 PDF 输出目录
    """
    try:
        _require_markdown()
        _require_weasyprint()

        base_dir = Path(directory).resolve()
        if not base_dir.is_dir():
            click.echo(f"错误: 目录不存在: {directory}", err=True)
            sys.exit(1)

        files = _find_markdown_files(base_dir, recursive=recursive)
        if not files:
            click.echo(f"目录 {directory} 下未找到 Markdown 文件。")
            return

        out = Path(output_dir).resolve() if output_dir else None
        if out:
            out.mkdir(parents=True, exist_ok=True)

        from rich.progress import Progress

        succeeded, failed = 0, 0
        with Progress(console=console) as progress:
            task = progress.add_task("转换 PDF", total=len(files))
            for md_file in files:
                target = out if out else md_file.parent
                try:
                    pdf_path = _convert_one_pdf(md_file, target)
                    logger.info("已转换: %s -> %s", md_file.name, pdf_path.name)
                    succeeded += 1
                except Exception as e:
                    logger.error("转换失败 %s: %s", md_file.name, e)
                    console.print(f"  [red]✗[/] {md_file.name}: {e}")
                    failed += 1
                progress.advance(task)

        summary = f"\n转换完成: [green]{succeeded} 成功[/]"
        if failed:
            summary += f", [red]{failed} 失败[/]"
        console.print(summary)

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


@main.command(name="serve", help="启动本地 HTTP 服务预览 Markdown 文件")
@click.option("--dir", "-d", "directory", default=".", show_default=True, help="Markdown 文件所在目录")
@click.option("--port", "-p", default=8000, show_default=True, type=int, help="服务端口")
@click.option("--host", "-H", default="127.0.0.1", show_default=True, help="监听地址")
def serve_command(directory: str, port: int, host: str) -> None:
    """启动本地 HTTP 预览服务

    \b
    示例:
        qxw-gitbook serve                # 预览当前目录（8000 端口）
        qxw-gitbook serve -p 3000        # 指定端口
        qxw-gitbook serve -d docs/       # 预览 docs/ 目录
        qxw-gitbook serve -H 0.0.0.0     # 允许局域网访问
    """
    try:
        _require_markdown()

        base_dir = Path(directory).resolve()
        if not base_dir.is_dir():
            click.echo(f"错误: 目录不存在: {directory}", err=True)
            sys.exit(1)

        file_count = len(_find_markdown_files(base_dir, recursive=True))
        console.print(f"📖 在 [cyan]{base_dir}[/] 下找到 {file_count} 个 Markdown 文件")
        console.print(f"🌐 服务地址: [link=http://{host}:{port}]http://{host}:{port}[/link]")
        console.print("按 Ctrl+C 停止服务\n")

        handler = partial(_GitbookHandler, base_dir)
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


if __name__ == "__main__":
    main()
