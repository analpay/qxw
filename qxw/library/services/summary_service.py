"""Gitbook 风格目录生成服务

扫描目录结构，按子目录层级与 README.md 标题为每个目录生成：
- SUMMARY.md：标题 + 目录结构（Gitbook 经典形态）
- INDEX.md：README.md 内容 + 目录结构

排序规则参考 flaboy/mmi parser.go 的数字前缀排序（例如 1.intro.md、2.setup.md）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

_SUMMARY_EXCLUDED = {"readme.md", "summary.md", "index.md"}


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

    for child in node.children:
        if not child.is_page:
            generated.extend(_generate_summary_files(child, depth, current_depth + 1))

    return generated


def generate_summary_for_dir(base_dir: Path, depth: int = 5) -> list[str]:
    """为 ``base_dir`` 及其包含 README.md 的子目录生成 SUMMARY.md / INDEX.md

    返回生成的文件路径列表（字符串形式）。
    """
    tree = _scan_dir(base_dir)
    return _generate_summary_files(tree, depth, 0)
