"""qxw.library.services.serve_gitbook 单元测试

覆盖：
- 纯函数：_find_markdown_files / _extract_title / _render_markdown / _build_sidebar /
  require_markdown / scan_markdown_count
- _require_weasyprint：依赖缺失抛 QxwError
- _GitbookHandler._check_path 的 403 / 404 / 正常三分支
- _serve_all_pdf / _serve_page_pdf：weasyprint 缺失（QxwError）、内部异常（Exception）
"""

from __future__ import annotations

import sys
from io import BytesIO
from pathlib import Path

import pytest

from qxw.library.base.exceptions import QxwError
from qxw.library.services import serve_gitbook as sg
from qxw.library.services.serve_gitbook import (
    GitbookServerConfig,
    _build_sidebar,
    _extract_title,
    _find_markdown_files,
    _GitbookHandler,
    _render_markdown,
    _require_weasyprint,
    require_markdown,
    scan_markdown_count,
)


class TestFindMarkdownFiles:
    def test_非递归只看顶层(self, tmp_path: Path) -> None:
        (tmp_path / "a.md").write_text("#")
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "b.md").write_text("#")
        res = _find_markdown_files(tmp_path, recursive=False)
        assert [p.name for p in res] == ["a.md"]

    def test_递归(self, tmp_path: Path) -> None:
        (tmp_path / "a.md").write_text("#")
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "b.md").write_text("#")
        res = _find_markdown_files(tmp_path, recursive=True)
        names = [p.name for p in res]
        assert "a.md" in names and "b.md" in names

    def test_空目录(self, tmp_path: Path) -> None:
        assert _find_markdown_files(tmp_path) == []


class TestExtractTitle:
    def test_H1_被提取(self, tmp_path: Path) -> None:
        f = tmp_path / "a.md"
        f.write_text("# 我的标题\n", encoding="utf-8")
        assert _extract_title(f) == "我的标题"

    def test_无_H1_回退_stem(self, tmp_path: Path) -> None:
        f = tmp_path / "a.md"
        f.write_text("正文\n", encoding="utf-8")
        assert _extract_title(f) == "a"

    def test_文件读取失败_回退_stem(self, tmp_path: Path) -> None:
        # 指向不存在的文件
        assert _extract_title(tmp_path / "nope.md") == "nope"


class TestRenderMarkdown:
    def test_基础渲染(self) -> None:
        html = _render_markdown("# 标题\n段落")
        assert "<h1" in html and "标题" in html

    def test_表格扩展(self) -> None:
        html = _render_markdown("| a | b |\n|---|---|\n| 1 | 2 |\n")
        assert "<table" in html

    def test_markdown_缺失抛_ImportError(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *a, **k):
            if name == "markdown":
                raise ImportError
            return real_import(name, *a, **k)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        with pytest.raises(ImportError):
            _render_markdown("# x")


class TestBuildSidebar:
    def test_空目录(self, tmp_path: Path) -> None:
        assert _build_sidebar(tmp_path, tmp_path, "") == ""

    def test_顶层文件生成_li(self, tmp_path: Path) -> None:
        (tmp_path / "a.md").write_text("# A\n", encoding="utf-8")
        html = _build_sidebar(tmp_path, tmp_path, "a.md")
        assert "<li>" in html
        assert "A" in html
        assert 'class="active"' in html  # 当前页

    def test_子目录有_README_显示标题(self, tmp_path: Path) -> None:
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "README.md").write_text("# 子区\n", encoding="utf-8")
        html = _build_sidebar(tmp_path, tmp_path, "")
        assert "子区" in html

    def test_子目录无_README_显示目录名(self, tmp_path: Path) -> None:
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "a.md").write_text("# A\n", encoding="utf-8")
        html = _build_sidebar(tmp_path, tmp_path, "")
        assert "sub" in html
        assert "nav-group-title" in html


class TestRequireMarkdown:
    def test_已安装不抛(self) -> None:
        require_markdown()  # markdown 已在项目依赖中

    def test_缺失包装为_QxwError(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *a, **k):
            if name == "markdown":
                raise ImportError
            return real_import(name, *a, **k)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        with pytest.raises(QxwError, match="markdown"):
            require_markdown()


class TestRequireWeasyprint:
    def test_缺失包装为_QxwError(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *a, **k):
            if name == "weasyprint":
                raise ImportError
            return real_import(name, *a, **k)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        with pytest.raises(QxwError, match="weasyprint"):
            _require_weasyprint()

    def test_OSError_也包装(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *a, **k):
            if name == "weasyprint":
                raise OSError("libpango missing")
            return real_import(name, *a, **k)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        with pytest.raises(QxwError, match="weasyprint"):
            _require_weasyprint()


class TestScanMarkdownCount:
    def test_递归计数(self, tmp_path: Path) -> None:
        (tmp_path / "a.md").write_text("")
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "b.md").write_text("")
        (sub / "c.md").write_text("")
        assert scan_markdown_count(tmp_path) == 3


# ------------------------------------------------------------------
# Handler 分支
# ------------------------------------------------------------------


class _TestHandler(_GitbookHandler):
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.path = "/"
        self.headers: dict = {}
        self.rfile = BytesIO()
        self.wfile = BytesIO()
        self._codes: list[int] = []
        self._headers_out: list[tuple[str, str]] = []

    def send_response(self, code: int, message: str | None = None) -> None:  # type: ignore[override]
        self._codes.append(code)

    def send_error(self, code, message=None, explain=None) -> None:  # type: ignore[override]
        self._codes.append(code)

    def send_header(self, name: str, value: str) -> None:  # type: ignore[override]
        self._headers_out.append((name, value))

    def end_headers(self) -> None:  # type: ignore[override]
        return None


class TestCheckPath:
    def test_越权_返回_None_并_send_error(self, tmp_path: Path) -> None:
        h = _TestHandler(tmp_path)
        assert h._check_path("../etc/passwd") is None
        assert 403 in h._codes

    def test_不存在_返回_None(self, tmp_path: Path) -> None:
        h = _TestHandler(tmp_path)
        assert h._check_path("nope.md") is None
        assert 404 in h._codes

    def test_正常文件_返回_Path(self, tmp_path: Path) -> None:
        (tmp_path / "a.md").write_text("# x\n")
        h = _TestHandler(tmp_path)
        out = h._check_path("a.md")
        assert out == (tmp_path / "a.md").resolve()


class TestServePagePdf:
    def test_weasyprint_缺失_500_文本错误(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *a, **k):
            if name == "weasyprint":
                raise ImportError
            return real_import(name, *a, **k)

        monkeypatch.setattr(builtins, "__import__", fake_import)

        md = tmp_path / "a.md"
        md.write_text("# x", encoding="utf-8")
        h = _TestHandler(tmp_path)
        h._serve_page_pdf("a.md")
        assert 500 in h._codes

    def test_内部异常被捕获_500(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sg, "_require_weasyprint", lambda: None)

        def boom(_md: Path) -> bytes:
            raise RuntimeError("boom")

        monkeypatch.setattr(sg, "_render_md_to_pdf", boom)

        md = tmp_path / "a.md"
        md.write_text("# x", encoding="utf-8")
        h = _TestHandler(tmp_path)
        h._serve_page_pdf("a.md")
        assert 500 in h._codes


class TestServeAllPdf:
    def test_空目录_QxwError_500(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sg, "_require_weasyprint", lambda: None)
        h = _TestHandler(tmp_path)
        h._serve_all_pdf()
        assert 500 in h._codes


class TestGitbookServerConfig:
    def test_默认值(self, tmp_path: Path) -> None:
        cfg = GitbookServerConfig(directory=tmp_path)
        assert cfg.host == "127.0.0.1"
        assert cfg.port == 8000
