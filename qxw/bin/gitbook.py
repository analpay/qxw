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
from dataclasses import dataclass, field
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
* { box-sizing: border-box; }
body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans SC",
                 "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei",
                 Helvetica, Arial, sans-serif;
    line-height: 1.8; color: #1f2328; margin: 0; padding: 0;
    -webkit-font-smoothing: antialiased;
}
h1, h2, h3, h4, h5, h6 {
    margin-top: 1.8em; margin-bottom: .6em;
    font-weight: 600; line-height: 1.25; color: #1f2328;
}
h1 { font-size: 2em; padding-bottom: .3em; border-bottom: 2px solid #eaeef2; }
h2 { font-size: 1.5em; padding-bottom: .25em; border-bottom: 1px solid #eaeef2; }
h3 { font-size: 1.25em; }
p { margin: 1em 0; }
a { color: #0969da; text-decoration: none; transition: color .15s; }
a:hover { color: #0550ae; text-decoration: underline; }
code {
    font-family: "SF Mono", SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace;
    font-size: .875em; background: #eff1f3;
    padding: .2em .45em; border-radius: 6px; border: 1px solid #d1d9e0;
}
pre {
    background: #f6f8fa; padding: 1.2em 1.5em;
    border-radius: 10px; border: 1px solid #d1d9e0;
    overflow-x: auto; line-height: 1.55; margin: 1.2em 0;
}
pre code { background: none; padding: 0; border: none; font-size: .875em; }
table {
    border-collapse: separate; border-spacing: 0;
    width: 100%; margin: 1.2em 0;
    border-radius: 8px; overflow: hidden; border: 1px solid #d1d9e0;
}
th, td { padding: .65em 1em; text-align: left; border-bottom: 1px solid #eaeef2; }
th {
    background: #f6f8fa; font-weight: 600; font-size: .9em; color: #636c76;
    border-bottom: 2px solid #d1d9e0;
}
tr:last-child td { border-bottom: none; }
tr:hover td { background: #f6f8fa; }
blockquote {
    margin: 1.2em 0; padding: .8em 1.2em;
    border-left: 4px solid #0969da; background: #f6f8fa;
    color: #636c76; border-radius: 0 8px 8px 0;
}
blockquote p:first-child { margin-top: 0; }
blockquote p:last-child { margin-bottom: 0; }
img { max-width: 100%; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,.08); }
hr { border: none; height: 2px; background: #eaeef2; margin: 2.5em 0; }
ul, ol { padding-left: 1.8em; }
li { margin: .35em 0; }
li::marker { color: #636c76; }
::selection { background: #ddf4ff; color: #1f2328; }
"""

_PDF_CSS = _COMMON_CSS + """\
@page { size: A4; margin: 2cm; }
body { max-width: none; padding: 0; }
"""

_WEB_EXTRA_CSS = """\
html { scroll-behavior: smooth; }
body { background: #fff; }
.layout { display: flex; min-height: 100vh; }
.sidebar {
    width: 280px; flex-shrink: 0;
    background: #f8f9fb; border-right: 1px solid #e8ecf0;
    overflow-y: auto; position: fixed; top: 0; bottom: 0; left: 0;
}
.sidebar::-webkit-scrollbar { width: 5px; }
.sidebar::-webkit-scrollbar-thumb { background: #d1d9e0; border-radius: 4px; }
.sidebar::-webkit-scrollbar-thumb:hover { background: #afb8c1; }
.sidebar::-webkit-scrollbar-track { background: transparent; }
.sidebar-header {
    padding: 1.4em 1.5em; border-bottom: 1px solid #e8ecf0;
    background: #fff; position: sticky; top: 0; z-index: 1;
}
.sidebar-header a {
    font-weight: 700; font-size: 1.05em; color: #1f2328; letter-spacing: -.01em;
}
.sidebar-header a:hover { text-decoration: none; color: #0969da; }
.nav-tree { list-style: none; padding: .8em 0; margin: 0; }
.nav-tree ul { list-style: none; padding: 0; margin: 0; }
.nav-tree a {
    display: block; padding: .4em 1.5em;
    color: #424a53; font-size: .9em;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    border-right: 3px solid transparent;
    transition: all .15s ease;
}
.nav-tree a:hover { background: #eaeef2; color: #1f2328; text-decoration: none; }
.nav-tree a.active {
    color: #0969da; font-weight: 600; background: #ddf4ff;
    border-right-color: #0969da;
}
.nav-group-title {
    display: block; padding: .9em 1.5em .3em;
    font-weight: 600; font-size: .75em; color: #8b949e;
    text-transform: uppercase; letter-spacing: .06em;
}
a.nav-group-title {
    font-size: .75em; text-transform: uppercase; letter-spacing: .06em;
    font-weight: 600; color: #8b949e;
    border-right: 3px solid transparent; transition: all .15s ease;
}
a.nav-group-title:hover { color: #1f2328; background: #eaeef2; text-decoration: none; }
a.nav-group-title.active { color: #0969da; background: #ddf4ff; border-right-color: #0969da; }
.nav-group > ul > li > a { padding-left: 2.2em; }
.nav-group > ul > li > .nav-group-title { padding-left: 2.2em; }
.nav-group > ul > li.nav-group > ul > li > a { padding-left: 3em; }
.content {
    flex: 1; margin-left: 280px; padding: 3em 4em;
    max-width: 960px; min-width: 0;
}
.content > h1:first-child { margin-top: 0; }
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
# Summary 生成（参考 flaboy/mmi parser.go）
# ============================================================


@dataclass
class _DocNode:
    title: str
    filepath: Path
    rel_parts: list[str]
    is_page: bool
    children: list["_DocNode"] = field(default_factory=list)


def _numeric_sort_key(name: str) -> tuple[int, str]:
    dot = name.find(".")
    if dot > 0:
        try:
            return (int(name[:dot]), name)
        except ValueError:
            pass
    return (0, name)


_SUMMARY_EXCLUDED = {"readme.md", "summary.md", "index.md"}


def _scan_dir(dirpath: Path, rel_parts: list[str] | None = None) -> _DocNode:
    if rel_parts is None:
        rel_parts = []

    readme = dirpath / "README.md"
    title = _extract_title(readme) if readme.is_file() else dirpath.name
    node = _DocNode(title=title, filepath=dirpath, rel_parts=list(rel_parts), is_page=False)

    entries = sorted(dirpath.iterdir(), key=lambda e: _numeric_sort_key(e.name))
    for entry in entries:
        if entry.name.startswith("."):
            continue

        sub_parts = rel_parts + [entry.name]

        if entry.is_dir():
            sub_readme = entry / "README.md"
            if sub_readme.is_file():
                sub_title = _extract_title(sub_readme)
                if "(todo)" not in sub_title:
                    node.children.append(_scan_dir(entry, sub_parts))
        elif entry.suffix == ".md" and entry.name.lower() not in _SUMMARY_EXCLUDED:
            child_title = _extract_title(entry)
            if "(todo)" not in child_title:
                node.children.append(
                    _DocNode(title=child_title, filepath=entry, rel_parts=sub_parts, is_page=True)
                )

    return node


def _toc_markdown(node: _DocNode, depth: int, start_depth: int, prefix: str = "") -> str:
    depth -= 1
    if depth <= 0:
        return ""

    lines: list[str] = []
    for child in node.children:
        rel_path = "/".join(child.rel_parts[start_depth:])
        if not child.is_page:
            rel_path += "/INDEX.md"
        lines.append(f"{prefix}1. [{child.title}]({rel_path})")
        if not child.is_page:
            sub = _toc_markdown(child, depth, start_depth, prefix + "    ")
            if sub:
                lines.append(sub)

    return "\n".join(lines)


def _generate_summary_files(node: _DocNode, depth: int, current_depth: int) -> list[str]:
    generated: list[str] = []

    if (node.filepath / "SUMMARY.md.skip").exists():
        return generated

    toc = _toc_markdown(node, depth, current_depth)

    summary_path = node.filepath / "SUMMARY.md"
    summary_path.write_text(f"{node.title}\n{'=' * 48}\n\n{toc}\n", encoding="utf-8")
    generated.append(str(summary_path))

    index_path = node.filepath / "INDEX.md"
    readme_path = node.filepath / "README.md"
    readme_content = readme_path.read_text(encoding="utf-8") if readme_path.is_file() else ""
    index_path.write_text(f"{readme_content}\n## 目录\n\n{toc}\n", encoding="utf-8")
    generated.append(str(index_path))

    remaining = depth - 1
    if remaining > 0:
        for child in node.children:
            if not child.is_page:
                generated.extend(_generate_summary_files(child, remaining, current_depth + 1))

    return generated


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


@main.command(name="summary", help="为目录生成 SUMMARY.md 和 INDEX.md 目录文件")
@click.option("--dir", "-d", "directory", default=".", show_default=True, help="文档根目录")
@click.option("--depth", default=3, show_default=True, type=int, help="目录层级深度")
def summary_command(directory: str, depth: int) -> None:
    """扫描目录结构，为每个包含 README.md 的目录生成目录文件

    \b
    示例:
        qxw-gitbook summary              # 为当前目录生成
        qxw-gitbook summary -d docs/     # 指定目录
        qxw-gitbook summary --depth 5    # 指定深度

    \b
    生成规则:
        SUMMARY.md  = 标题 + 目录结构
        INDEX.md    = README.md 内容 + 目录结构

    \b
    特殊处理:
        - 标题含 (todo) 的条目会被跳过
        - 存在 SUMMARY.md.skip 的目录会被跳过
        - 文件按数字前缀排序（如 1.intro.md, 2.setup.md）
    """
    try:
        base_dir = Path(directory).resolve()
        if not base_dir.is_dir():
            click.echo(f"错误: 目录不存在: {directory}", err=True)
            sys.exit(1)

        if not (base_dir / "README.md").is_file():
            click.echo(f"错误: {directory} 下没有 README.md", err=True)
            sys.exit(1)

        tree = _scan_dir(base_dir)
        generated = _generate_summary_files(tree, depth, 0)

        for filepath in generated:
            console.print(f"  [green]✓[/] {filepath}")
        console.print(f"\n共生成 {len(generated)} 个文件")

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
