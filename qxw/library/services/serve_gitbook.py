"""Gitbook 预览服务

提供本地 HTTP 服务预览目录下的 Markdown 文件，支持：
- 左侧目录树 + 右侧内容区的 Gitbook 风格页面
- 单页 PDF 下载（当前页 Markdown → PDF）
- 整本 PDF 下载（按目录顺序合并所有 Markdown → 单个 PDF）
"""

from __future__ import annotations

import mimetypes
import urllib.parse
from dataclasses import dataclass, field
from functools import partial
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from qxw.library.base.exceptions import QxwError
from qxw.library.base.logger import get_logger

logger = get_logger("qxw.serve.gitbook")


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
.page-break { page-break-before: always; }
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
.sidebar-actions {
    padding: .8em 1.5em; border-bottom: 1px solid #e8ecf0;
    display: flex; flex-direction: column; gap: .4em;
}
.sidebar-actions a {
    display: inline-block; padding: .45em .8em;
    font-size: .82em; font-weight: 600;
    color: #0969da; background: #ddf4ff;
    border-radius: 6px; text-align: center;
    transition: all .15s;
}
.sidebar-actions a:hover {
    background: #0969da; color: #fff; text-decoration: none;
}
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
.page-actions {
    display: flex; gap: .5em; margin-bottom: 1.5em;
    padding-bottom: 1em; border-bottom: 1px solid #eaeef2;
}
.page-actions a {
    display: inline-block; padding: .4em .9em;
    font-size: .82em; font-weight: 600;
    color: #636c76; background: #f6f8fa;
    border: 1px solid #d1d9e0; border-radius: 6px;
    transition: all .15s;
}
.page-actions a:hover {
    color: #0969da; border-color: #0969da;
    background: #ddf4ff; text-decoration: none;
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
    <div class="sidebar-actions">
      <a href="/__pdf__/all">⬇ 下载整本 PDF</a>
    </div>
    <ul class="nav-tree">{sidebar}</ul>
  </nav>
  <main class="content">
    {page_actions}
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
# Markdown 扫描与渲染工具
# ============================================================


_STATIC_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico",
    ".css", ".js", ".woff", ".woff2", ".ttf", ".eot",
}

_NAV_EXCLUDED = {"index.md", "summary.md", "readme.md"}


def _find_markdown_files(directory: Path, recursive: bool = False) -> list[Path]:
    pattern = "**/*.md" if recursive else "*.md"
    return sorted(directory.glob(pattern))


def _render_markdown(text: str) -> str:
    import markdown

    extensions = ["tables", "fenced_code", "codehilite", "toc", "sane_lists"]
    extension_configs = {"codehilite": {"noclasses": True, "linenums": False}}
    return markdown.markdown(text, extensions=extensions, extension_configs=extension_configs)


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


# ============================================================
# PDF 导出
# ============================================================


def _require_weasyprint() -> None:
    try:
        import weasyprint  # noqa: F401
    except (ImportError, OSError) as e:
        raise QxwError(
            "PDF 下载功能需要安装 weasyprint 库:\n"
            "  macOS:  brew install pango && pip install weasyprint\n"
            "  Linux:  apt install libpango-1.0-0 && pip install weasyprint\n"
            "  详见: https://doc.courtbouillon.org/weasyprint/stable/first_steps.html"
        ) from e


def _render_md_to_pdf(md_path: Path) -> bytes:
    """将单个 Markdown 文件渲染为 PDF 字节流"""
    from weasyprint import HTML

    html_body = _render_markdown(md_path.read_text(encoding="utf-8"))
    full_html = _PDF_PAGE.format(title=md_path.stem, css=_PDF_CSS, content=html_body)
    return HTML(string=full_html, base_url=str(md_path.parent)).write_pdf()


def _render_all_md_to_pdf(base_dir: Path) -> bytes:
    """扫描目录下全部 Markdown 并合并渲染为单个 PDF"""
    from weasyprint import HTML

    files = _find_markdown_files(base_dir, recursive=True)
    if not files:
        raise QxwError("目录下未找到 Markdown 文件")

    fragments: list[str] = []
    for idx, md in enumerate(files):
        body = _render_markdown(md.read_text(encoding="utf-8"))
        wrapper = "" if idx == 0 else '<div class="page-break"></div>'
        fragments.append(f'{wrapper}<article>{body}</article>')

    root_readme = base_dir / "README.md"
    title = _extract_title(root_readme) if root_readme.is_file() else base_dir.name
    full_html = _PDF_PAGE.format(title=title, css=_PDF_CSS, content="\n".join(fragments))
    return HTML(string=full_html, base_url=str(base_dir)).write_pdf()


# ============================================================
# HTTP 处理器
# ============================================================


@dataclass
class GitbookServerConfig:
    directory: Path
    host: str = "127.0.0.1"
    port: int = 8000
    file_count: int = field(default=0)


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
        elif path == "/__pdf__/all":
            self._serve_all_pdf()
        elif path.startswith("/__pdf__/"):
            self._serve_page_pdf(path[len("/__pdf__/"):])
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

    def _render_page(self, rel_path: str, content: str, title: str, *, show_page_pdf: bool) -> None:
        root_readme = self.base_dir / "README.md"
        root_title = _extract_title(root_readme) if root_readme.is_file() else "QXW Gitbook"
        sidebar = _build_sidebar(self.base_dir, self.base_dir, rel_path)

        if show_page_pdf and rel_path:
            pdf_href = "/__pdf__/" + urllib.parse.quote(rel_path)
            page_actions = f'<div class="page-actions"><a href="{pdf_href}">⬇ 下载本页 PDF</a></div>'
        else:
            page_actions = ""

        html = _WEB_PAGE.format(
            title=title, css=_WEB_CSS, root_title=root_title,
            sidebar=sidebar, content=content, page_actions=page_actions,
        )
        self._respond(html)

    def _serve_index(self):
        readme = self.base_dir / "README.md"
        if readme.is_file():
            content = _render_markdown(readme.read_text(encoding="utf-8"))
            self._render_page("README.md", content, "首页", show_page_pdf=True)
        else:
            content = "<h1>📖 QXW Gitbook</h1><p>请从左侧目录选择文件。</p>"
            self._render_page("", content, "首页", show_page_pdf=False)

    def _serve_markdown(self, rel_path: str):
        file_path = self._check_path(rel_path)
        if not file_path:
            return
        rendered = _render_markdown(file_path.read_text(encoding="utf-8"))
        self._render_page(rel_path, rendered, _extract_title(file_path), show_page_pdf=True)

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

    def _serve_page_pdf(self, rel_path: str) -> None:
        file_path = self._check_path(rel_path)
        if not file_path:
            return
        try:
            _require_weasyprint()
            pdf_bytes = _render_md_to_pdf(file_path)
        except QxwError as e:
            self._send_text_error(500, str(e))
            return
        except Exception as e:
            logger.exception("PDF 生成失败")
            self._send_text_error(500, f"PDF 生成失败: {e}")
            return

        filename = f"{file_path.stem}.pdf"
        self._respond_pdf(pdf_bytes, filename)

    def _serve_all_pdf(self) -> None:
        try:
            _require_weasyprint()
            pdf_bytes = _render_all_md_to_pdf(self.base_dir)
        except QxwError as e:
            self._send_text_error(500, str(e))
            return
        except Exception as e:
            logger.exception("整本 PDF 生成失败")
            self._send_text_error(500, f"整本 PDF 生成失败: {e}")
            return

        root_readme = self.base_dir / "README.md"
        root_title = _extract_title(root_readme) if root_readme.is_file() else self.base_dir.name
        filename = f"{root_title}.pdf"
        self._respond_pdf(pdf_bytes, filename)

    def _respond(self, html: str):
        data = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _respond_pdf(self, data: bytes, filename: str) -> None:
        encoded_name = urllib.parse.quote(filename)
        self.send_response(200)
        self.send_header("Content-Type", "application/pdf")
        self.send_header("Content-Length", str(len(data)))
        self.send_header(
            "Content-Disposition",
            f"attachment; filename*=UTF-8''{encoded_name}",
        )
        self.end_headers()
        self.wfile.write(data)

    def _send_text_error(self, code: int, message: str) -> None:
        body = message.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


# ============================================================
# 入口
# ============================================================


def require_markdown() -> None:
    """检查 markdown 库是否已安装"""
    try:
        import markdown  # noqa: F401
    except ImportError as e:
        raise QxwError("需要安装 markdown 库: pip install markdown") from e


def scan_markdown_count(base_dir: Path) -> int:
    """统计目录下（递归）Markdown 文件数"""
    return len(_find_markdown_files(base_dir, recursive=True))


def start_server(config: GitbookServerConfig) -> None:
    """启动 Gitbook 预览 HTTP 服务（阻塞）"""
    handler = partial(_GitbookHandler, config.directory)
    server = HTTPServer((config.host, config.port), handler)
    server.serve_forever()
