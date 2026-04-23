"""qxw-markdown 命令入口测试

覆盖各子命令的：参数校验错误、QxwError / KeyboardInterrupt / Exception 分支、
以及通过 mock 的正常路径。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from qxw.bin import markdown as md_mod
from qxw.library.base.exceptions import QxwError


def _run(args: list[str]) -> tuple[int, str]:
    runner = CliRunner()
    result = runner.invoke(md_mod.main, args)
    return result.exit_code, result.output


class TestMainGroup:
    def test_无子命令打印帮助(self) -> None:
        code, out = _run([])
        assert code == 0
        assert "wx" in out
        assert "cover" in out
        assert "summary" in out

    def test_版本(self) -> None:
        code, out = _run(["--version"])
        assert code == 0
        assert "版本" in out


class TestWxCommand:
    def test_文件不存在_点击校验拒绝(self, tmp_path: Path) -> None:
        code, _ = _run(["wx", str(tmp_path / "nope.md")])
        assert code != 0

    def test_正常流程_无_plantuml_复制原文(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        md = tmp_path / "a.md"
        md.write_text("# 仅文字\n", encoding="utf-8")

        from qxw.library.services import markdown_service as ms

        class FakeResult:
            image_paths: list[Path] = []
            output_md = tmp_path / "a_wx.md"

        monkeypatch.setattr(ms, "convert_markdown_for_wx", lambda **k: FakeResult())

        code, out = _run(["wx", str(md)])
        assert code == 0
        assert "未发现" in out

    def test_QxwError_透传退出码(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        md = tmp_path / "a.md"
        md.write_text("# x", encoding="utf-8")

        from qxw.library.services import markdown_service as ms

        def boom(**k):
            raise QxwError("命令失败", exit_code=6)

        monkeypatch.setattr(ms, "convert_markdown_for_wx", boom)
        code, out = _run(["wx", str(md)])
        assert code == 6
        assert "命令失败" in out

    def test_KeyboardInterrupt(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        md = tmp_path / "a.md"
        md.write_text("# x", encoding="utf-8")

        from qxw.library.services import markdown_service as ms

        def boom(**k):
            raise KeyboardInterrupt()

        monkeypatch.setattr(ms, "convert_markdown_for_wx", boom)
        code, out = _run(["wx", str(md)])
        assert code == 130
        assert "已取消" in out

    def test_通用异常退出_1(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        md = tmp_path / "a.md"
        md.write_text("# x", encoding="utf-8")

        from qxw.library.services import markdown_service as ms

        def boom(**k):
            raise RuntimeError("oops")

        monkeypatch.setattr(ms, "convert_markdown_for_wx", boom)
        code, out = _run(["wx", str(md)])
        assert code == 1
        assert "未预期" in out

    def test_非法_format(self, tmp_path: Path) -> None:
        md = tmp_path / "a.md"
        md.write_text("# x", encoding="utf-8")
        code, _ = _run(["wx", str(md), "-f", "gif"])
        assert code != 0


class TestCoverCommand:
    def test_QxwError_透传(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        md = tmp_path / "a.md"
        md.write_text("# x", encoding="utf-8")
        from qxw.library.services import cover_service as cs

        def boom(**k):
            raise QxwError("cover 失败", exit_code=7)

        monkeypatch.setattr(cs, "generate_cover", boom)
        code, out = _run(["cover", str(md)])
        assert code == 7
        assert "cover 失败" in out

    def test_KeyboardInterrupt(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        md = tmp_path / "a.md"
        md.write_text("# x", encoding="utf-8")
        from qxw.library.services import cover_service as cs

        def boom(**k):
            raise KeyboardInterrupt()

        monkeypatch.setattr(cs, "generate_cover", boom)
        code, _ = _run(["cover", str(md)])
        assert code == 130

    def test_通用异常(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        md = tmp_path / "a.md"
        md.write_text("# x", encoding="utf-8")
        from qxw.library.services import cover_service as cs

        def boom(**k):
            raise RuntimeError("x")

        monkeypatch.setattr(cs, "generate_cover", boom)
        code, _ = _run(["cover", str(md)])
        assert code == 1

    def test_正常生成_输出封面信息(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        md = tmp_path / "a.md"
        md.write_text("# x", encoding="utf-8")
        from qxw.library.services import cover_service as cs

        class FakeResult:
            output_path = tmp_path / "a_cover.png"
            prompt_chars = 100
            text_response = "附带说明"

        monkeypatch.setattr(cs, "generate_cover", lambda **k: FakeResult())
        code, out = _run(["cover", str(md)])
        assert code == 0
        assert "已生成封面" in out
        assert "附带说明" in out


class TestSummaryCommand:
    def test_目录不存在_退出_1(self, tmp_path: Path) -> None:
        code, out = _run(["summary", "-d", str(tmp_path / "nope")])
        assert code == 1
        assert "目录不存在" in out

    def test_缺少_README_退出_1(self, tmp_path: Path) -> None:
        code, out = _run(["summary", "-d", str(tmp_path)])
        assert code == 1
        assert "README" in out

    def test_QxwError(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        (tmp_path / "README.md").write_text("# 根", encoding="utf-8")
        from qxw.library.services import summary_service as ss

        def boom(*a, **k):
            raise QxwError("summary 失败", exit_code=5)

        monkeypatch.setattr(ss, "generate_summary_for_dir", boom)
        code, out = _run(["summary", "-d", str(tmp_path)])
        assert code == 5
        assert "summary 失败" in out

    def test_KeyboardInterrupt(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        (tmp_path / "README.md").write_text("# 根", encoding="utf-8")
        from qxw.library.services import summary_service as ss

        def boom(*a, **k):
            raise KeyboardInterrupt()

        monkeypatch.setattr(ss, "generate_summary_for_dir", boom)
        code, _ = _run(["summary", "-d", str(tmp_path)])
        assert code == 130

    def test_Exception(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        (tmp_path / "README.md").write_text("# 根", encoding="utf-8")
        from qxw.library.services import summary_service as ss

        def boom(*a, **k):
            raise RuntimeError("x")

        monkeypatch.setattr(ss, "generate_summary_for_dir", boom)
        code, _ = _run(["summary", "-d", str(tmp_path)])
        assert code == 1

    def test_正常路径(self, tmp_path: Path) -> None:
        (tmp_path / "README.md").write_text("# 根\n", encoding="utf-8")
        (tmp_path / "a.md").write_text("# A\n", encoding="utf-8")
        code, out = _run(["summary", "-d", str(tmp_path)])
        assert code == 0
        assert "SUMMARY.md" in out
