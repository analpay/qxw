"""qxw.library.services.summary_service 单元测试

覆盖：
- _numeric_sort_key：纯字母 / 数字前缀 / 非法数字前缀
- _extract_title：首行 # 标题 / 非 markdown / 文件不存在 / 文件前 30 行
- _scan_dir：忽略隐藏文件、(todo) 标题、非 md 文件、嵌套
- _toc_markdown：depth 控制递归深度、start_depth 影响相对路径
- _generate_summary_files：SUMMARY.md.skip 跳过、正常生成
- generate_summary_for_dir 端到端
"""

from __future__ import annotations

from pathlib import Path

import pytest

from qxw.library.services import summary_service as svc


class TestNumericSortKey:
    def test_纯字母_返回_0(self) -> None:
        assert svc._numeric_sort_key("intro.md") == (0, "intro.md")

    def test_数字前缀(self) -> None:
        assert svc._numeric_sort_key("10.setup.md") == (10, "10.setup.md")

    def test_点前不是数字_返回_0(self) -> None:
        assert svc._numeric_sort_key("foo.1.md") == (0, "foo.1.md")

    def test_无点(self) -> None:
        assert svc._numeric_sort_key("README") == (0, "README")

    def test_排序顺序_数字优先(self) -> None:
        names = ["z.md", "10.x.md", "2.y.md", "a.md"]
        names.sort(key=svc._numeric_sort_key)
        assert names == ["a.md", "z.md", "2.y.md", "10.x.md"]


class TestExtractTitle:
    def test_首行_H1_作为标题(self, tmp_path: Path) -> None:
        f = tmp_path / "a.md"
        f.write_text("# 我的标题\n正文\n", encoding="utf-8")
        assert svc._extract_title(f) == "我的标题"

    def test_H2_不被误识别(self, tmp_path: Path) -> None:
        f = tmp_path / "a.md"
        f.write_text("## 次级\n", encoding="utf-8")
        assert svc._extract_title(f) == "a"  # 回退 stem

    def test_文件不存在_回退_stem(self, tmp_path: Path) -> None:
        assert svc._extract_title(tmp_path / "nope.md") == "nope"

    def test_仅扫描前_30_行(self, tmp_path: Path) -> None:
        f = tmp_path / "a.md"
        content = "\n" * 40 + "# 太晚了\n"  # 第 41 行才是 H1
        f.write_text(content, encoding="utf-8")
        assert svc._extract_title(f) == "a"  # 回退 stem

    def test_编码异常_回退_stem(self, tmp_path: Path) -> None:
        f = tmp_path / "bad.md"
        # 非 UTF-8 字节，_extract_title 会吞掉异常回退到 stem
        f.write_bytes(b"\xff\xff\xfe# luan\n")
        assert svc._extract_title(f) == "bad"


class TestScanDir:
    def test_忽略隐藏文件(self, tmp_path: Path) -> None:
        (tmp_path / ".hidden.md").write_text("# x", encoding="utf-8")
        (tmp_path / "a.md").write_text("# A", encoding="utf-8")
        node = svc._scan_dir(tmp_path)
        names = [c.filepath.name for c in node.children]
        assert names == ["a.md"]

    def test_todo_标题的子项被跳过(self, tmp_path: Path) -> None:
        (tmp_path / "ok.md").write_text("# 正常\n", encoding="utf-8")
        (tmp_path / "todo.md").write_text("# 待办 (todo)\n", encoding="utf-8")
        node = svc._scan_dir(tmp_path)
        titles = [c.title for c in node.children]
        assert "正常" in titles
        assert all("(todo)" not in t for t in titles)

    def test_排除_summary_readme_index_自身(self, tmp_path: Path) -> None:
        for name in ("README.md", "SUMMARY.md", "INDEX.md", "a.md"):
            (tmp_path / name).write_text("# x\n", encoding="utf-8")
        node = svc._scan_dir(tmp_path)
        assert [c.filepath.name for c in node.children] == ["a.md"]

    def test_无_README_的子目录不被收录(self, tmp_path: Path) -> None:
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "x.md").write_text("# x", encoding="utf-8")  # 没有 README.md
        (tmp_path / "root.md").write_text("# root", encoding="utf-8")
        node = svc._scan_dir(tmp_path)
        names = [c.filepath.name for c in node.children]
        assert "sub" not in names
        assert "root.md" in names

    def test_有_README_的子目录被递归(self, tmp_path: Path) -> None:
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "README.md").write_text("# 子区\n", encoding="utf-8")
        (sub / "detail.md").write_text("# 细节\n", encoding="utf-8")
        node = svc._scan_dir(tmp_path)
        sub_nodes = [c for c in node.children if c.filepath.name == "sub"]
        assert len(sub_nodes) == 1
        assert sub_nodes[0].title == "子区"
        assert [c.title for c in sub_nodes[0].children] == ["细节"]

    def test_非_md_文件被忽略(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("x")
        (tmp_path / "a.md").write_text("# x\n")
        node = svc._scan_dir(tmp_path)
        assert [c.filepath.name for c in node.children] == ["a.md"]

    def test_符号链接目录被跳过避免环(self, tmp_path: Path) -> None:
        # 构造一个典型的符号链接环：sub/loop -> sub（指向父目录）
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "README.md").write_text("# 子\n", encoding="utf-8")
        (sub / "x.md").write_text("# X\n", encoding="utf-8")
        loop = sub / "loop"
        try:
            loop.symlink_to(sub, target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip("当前文件系统不支持符号链接")

        node = svc._scan_dir(tmp_path)
        sub_node = next(c for c in node.children if c.filepath.name == "sub")
        # 实体文件 x.md 仍被收录，但符号链接子目录被忽略，不会无限递归
        names = [c.filepath.name for c in sub_node.children]
        assert "x.md" in names
        assert "loop" not in names

    def test_递归深度上限保护(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # 把上限压低到 3，再构造 5 层目录，确认第 4 层之后不再递归
        monkeypatch.setattr(svc, "_MAX_SCAN_DEPTH", 3)
        current = tmp_path
        for i in range(5):
            current = current / f"lvl{i}"
            current.mkdir()
            (current / "README.md").write_text(f"# L{i}\n", encoding="utf-8")

        node = svc._scan_dir(tmp_path)
        # 逐层下钻，统计实际递归的层数（children 非空才算递归通过）
        depth = 0
        cursor = node
        while cursor.children:
            cursor = cursor.children[0]
            depth += 1
        assert depth <= 3


class TestTocMarkdown:
    def _make_node(self, children: list[svc._DocNode]) -> svc._DocNode:
        return svc._DocNode(
            title="根",
            filepath=Path("/x"),
            rel_parts=[],
            is_page=False,
            children=children,
        )

    def test_depth_为_0_返回空(self, tmp_path: Path) -> None:
        node = self._make_node([
            svc._DocNode("A", tmp_path / "a.md", ["a.md"], is_page=True),
        ])
        assert svc._toc_markdown(node, 1, 0) == ""

    def test_page_使用相对路径(self, tmp_path: Path) -> None:
        node = self._make_node([
            svc._DocNode("A", tmp_path / "a.md", ["a.md"], is_page=True),
        ])
        out = svc._toc_markdown(node, 2, 0)
        assert "1. [A](a.md)" in out

    def test_非_page_追加_INDEX_md(self, tmp_path: Path) -> None:
        child = svc._DocNode("B", tmp_path / "b", ["b"], is_page=False)
        node = self._make_node([child])
        out = svc._toc_markdown(node, 2, 0)
        assert "1. [B](b/INDEX.md)" in out

    def test_深度截断(self, tmp_path: Path) -> None:
        grand = svc._DocNode("孙", tmp_path / "a/b.md", ["a", "b.md"], is_page=True)
        child = svc._DocNode("子", tmp_path / "a", ["a"], is_page=False, children=[grand])
        node = self._make_node([child])
        # depth=2 只渲染一层子节点
        out = svc._toc_markdown(node, 2, 0)
        assert "子" in out
        assert "孙" not in out


class TestGenerateSummaryFiles:
    def test_skip_文件存在_跳过生成(self, tmp_path: Path) -> None:
        (tmp_path / "SUMMARY.md.skip").write_text("")
        (tmp_path / "a.md").write_text("# A\n", encoding="utf-8")
        result = svc.generate_summary_for_dir(tmp_path)
        assert result == []
        assert not (tmp_path / "SUMMARY.md").exists()

    def test_生成_SUMMARY_与_INDEX(self, tmp_path: Path) -> None:
        (tmp_path / "README.md").write_text("# 根\n正文\n", encoding="utf-8")
        (tmp_path / "a.md").write_text("# A 页\n", encoding="utf-8")
        result = svc.generate_summary_for_dir(tmp_path)

        summary = (tmp_path / "SUMMARY.md").read_text(encoding="utf-8")
        index = (tmp_path / "INDEX.md").read_text(encoding="utf-8")
        assert "根" in summary
        assert "[A 页](a.md)" in summary
        assert "正文" in index
        assert "## 目录" in index
        assert str(tmp_path / "SUMMARY.md") in result
        assert str(tmp_path / "INDEX.md") in result

    def test_递归生成_子目录_summary(self, tmp_path: Path) -> None:
        (tmp_path / "README.md").write_text("# 根\n", encoding="utf-8")
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "README.md").write_text("# 子\n", encoding="utf-8")
        (sub / "x.md").write_text("# X\n", encoding="utf-8")

        svc.generate_summary_for_dir(tmp_path)
        assert (sub / "SUMMARY.md").exists()
        assert "X" in (sub / "SUMMARY.md").read_text(encoding="utf-8")

    def test_readme_缺失时_INDEX_仅有目录(self, tmp_path: Path) -> None:
        (tmp_path / "a.md").write_text("# A\n", encoding="utf-8")
        svc.generate_summary_for_dir(tmp_path)
        index = (tmp_path / "INDEX.md").read_text(encoding="utf-8")
        assert index.startswith("\n## 目录")
