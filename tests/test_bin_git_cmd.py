"""qxw-git CLI 端到端测试

通过 click.testing.CliRunner 执行，覆盖：
- top-level 不带子命令时打印帮助
- archive 成功路径（mock 服务层，断言渲染 / quiet 模式）
- archive 路径默认值（CWD）
- 不支持的格式由 Click Choice 拦截，退出码 2
- QxwError / KeyboardInterrupt / 未预期 Exception 三个分支
- --no-lfs 透传 pull_lfs=False
- --version 输出
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from qxw.bin import git_cmd as git_mod
from qxw.bin.git_cmd import main
from qxw.library.base.exceptions import CommandError, ValidationError
from qxw.library.services.git_archive_service import ArchiveResult


def _run(args: list[str]) -> tuple[int, str]:
    runner = CliRunner()
    result = runner.invoke(main, args)
    return result.exit_code, result.output


# ============================================================
# 顶层
# ============================================================


class TestTopLevel:
    def test_无子命令_打印帮助(self) -> None:
        code, out = _run([])
        assert code == 0
        assert "qxw-git" in out
        assert "archive" in out

    def test_version(self) -> None:
        code, out = _run(["--version"])
        assert code == 0
        assert "版本" in out


# ============================================================
# 成功路径（mock 服务层）
# ============================================================


def _fake_result(
    tmp_path: Path, ref: str | None = None, excluded: int = 0
) -> ArchiveResult:
    out = tmp_path / "demo.tar"
    out.write_bytes(b"x" * 2048)
    return ArchiveResult(
        output_path=out,
        file_count=42,
        archive_size=2048,
        lfs_pulled=True,
        ref=ref,
        excluded_count=excluded,
    )


class TestArchiveSuccess:
    def test_默认输出表格_含关键字段(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, object] = {}

        def _spy(**kwargs):  # type: ignore[no-untyped-def]
            captured.update(kwargs)
            return _fake_result(tmp_path)

        monkeypatch.setattr(git_mod, "archive_repo", _spy)
        # Rich Console 在窄宽下会截断长路径，统一拉宽，避免误伤断言
        monkeypatch.setattr(git_mod.console, "width", 240, raising=False)
        code, out = _run(["archive", str(tmp_path)])
        assert code == 0
        assert "git 仓库打包结果" in out
        assert "42" in out
        assert "LFS" in out
        # 默认 fmt = tar，pull_lfs = True
        assert captured["fmt"] == "tar"
        assert captured["pull_lfs"] is True
        assert captured["repo_path"] == tmp_path

    def test_quiet_只打印路径(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(git_mod, "archive_repo", lambda **_: _fake_result(tmp_path))
        code, out = _run(["archive", str(tmp_path), "--quiet"])
        assert code == 0
        assert out.strip() == str(tmp_path / "demo.tar")

    def test_no_lfs_透传_pull_lfs_为_False(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, object] = {}

        def _spy(**kwargs):  # type: ignore[no-untyped-def]
            captured.update(kwargs)
            return _fake_result(tmp_path)

        monkeypatch.setattr(git_mod, "archive_repo", _spy)
        code, _ = _run(["archive", str(tmp_path), "--no-lfs"])
        assert code == 0
        assert captured["pull_lfs"] is False

    def test_format_选项_透传(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, object] = {}

        def _spy(**kwargs):  # type: ignore[no-untyped-def]
            captured.update(kwargs)
            return _fake_result(tmp_path)

        monkeypatch.setattr(git_mod, "archive_repo", _spy)
        code, _ = _run(["archive", str(tmp_path), "-f", "zip"])
        assert code == 0
        assert captured["fmt"] == "zip"

    def test_不传_repo_使用_cwd(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, object] = {}

        def _spy(**kwargs):  # type: ignore[no-untyped-def]
            captured.update(kwargs)
            return _fake_result(tmp_path)

        monkeypatch.setattr(git_mod, "archive_repo", _spy)
        monkeypatch.chdir(tmp_path)
        code, _ = _run(["archive"])
        assert code == 0
        # Path.cwd() 在不同平台下可能含 /private 等前缀，直接对比 resolve
        assert Path(captured["repo_path"]).resolve() == tmp_path.resolve()

    def test_prefix_选项_透传(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, object] = {}

        def _spy(**kwargs):  # type: ignore[no-untyped-def]
            captured.update(kwargs)
            return _fake_result(tmp_path)

        monkeypatch.setattr(git_mod, "archive_repo", _spy)
        code, _ = _run(["archive", str(tmp_path), "--prefix", "release-1.0"])
        assert code == 0
        assert captured["arcname_prefix"] == "release-1.0"

    def test_ref_长选项透传(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, object] = {}

        def _spy(**kwargs):  # type: ignore[no-untyped-def]
            captured.update(kwargs)
            return _fake_result(tmp_path, ref="main")

        monkeypatch.setattr(git_mod, "archive_repo", _spy)
        code, _ = _run(["archive", str(tmp_path), "--ref", "main"])
        assert code == 0
        assert captured["ref"] == "main"

    def test_ref_短选项_r_等价(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, object] = {}

        def _spy(**kwargs):  # type: ignore[no-untyped-def]
            captured.update(kwargs)
            return _fake_result(tmp_path, ref="v1.2.0")

        monkeypatch.setattr(git_mod, "archive_repo", _spy)
        code, _ = _run(["archive", str(tmp_path), "-r", "v1.2.0"])
        assert code == 0
        assert captured["ref"] == "v1.2.0"

    def test_未指定_ref_时透传_None(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, object] = {}

        def _spy(**kwargs):  # type: ignore[no-untyped-def]
            captured.update(kwargs)
            return _fake_result(tmp_path)

        monkeypatch.setattr(git_mod, "archive_repo", _spy)
        code, _ = _run(["archive", str(tmp_path)])
        assert code == 0
        assert captured["ref"] is None

    def test_table_中包含_Ref_行_默认显示当前工作树(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(git_mod, "archive_repo", lambda **_: _fake_result(tmp_path))
        monkeypatch.setattr(git_mod.console, "width", 240, raising=False)
        code, out = _run(["archive", str(tmp_path)])
        assert code == 0
        assert "Ref" in out
        assert "当前工作树" in out

    def test_table_中包含_Ref_行_显示_ref(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            git_mod, "archive_repo", lambda **_: _fake_result(tmp_path, ref="release-1.2")
        )
        monkeypatch.setattr(git_mod.console, "width", 240, raising=False)
        code, out = _run(["archive", str(tmp_path), "-r", "release-1.2"])
        assert code == 0
        assert "release-1.2" in out

    def test_未指定_exclude_时透传_None(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, object] = {}

        def _spy(**kwargs):  # type: ignore[no-untyped-def]
            captured.update(kwargs)
            return _fake_result(tmp_path)

        monkeypatch.setattr(git_mod, "archive_repo", _spy)
        code, _ = _run(["archive", str(tmp_path)])
        assert code == 0
        # 未传 -e 时，CLI 应把 excludes 透传成 None（让服务层走默认排除）
        assert captured["excludes"] is None

    def test_单个_exclude_透传(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, object] = {}

        def _spy(**kwargs):  # type: ignore[no-untyped-def]
            captured.update(kwargs)
            return _fake_result(tmp_path)

        monkeypatch.setattr(git_mod, "archive_repo", _spy)
        code, _ = _run(["archive", str(tmp_path), "-e", "docs"])
        assert code == 0
        assert captured["excludes"] == ["docs"]

    def test_多个_exclude_累积透传_顺序保留(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, object] = {}

        def _spy(**kwargs):  # type: ignore[no-untyped-def]
            captured.update(kwargs)
            return _fake_result(tmp_path)

        monkeypatch.setattr(git_mod, "archive_repo", _spy)
        code, _ = _run(
            [
                "archive",
                str(tmp_path),
                "-e",
                "docs",
                "--exclude",
                "*.md",
                "-e",
                "tests/fixtures",
            ]
        )
        assert code == 0
        assert captured["excludes"] == ["docs", "*.md", "tests/fixtures"]

    def test_table_显示_已排除_数量(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            git_mod, "archive_repo", lambda **_: _fake_result(tmp_path, excluded=7)
        )
        monkeypatch.setattr(git_mod.console, "width", 240, raising=False)
        code, out = _run(["archive", str(tmp_path)])
        assert code == 0
        assert "已排除" in out
        assert "7" in out

    def test_exclude_后跟_ValidationError_退出码_6(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _raise(**_):  # type: ignore[no-untyped-def]
            raise ValidationError("排除项含非法 .. 片段: ../etc")

        monkeypatch.setattr(git_mod, "archive_repo", _raise)
        code, out = _run(["archive", str(tmp_path), "-e", "../etc"])
        assert code == 6
        assert ".." in out


# ============================================================
# 错误分支
# ============================================================


class TestArchiveErrors:
    def test_不支持的格式_由_Click_拦截_退出码_2(self, tmp_path: Path) -> None:
        code, out = _run(["archive", str(tmp_path), "-f", "rar"])
        assert code == 2
        # Click 的错误信息中通常会出现 'Invalid value' 或选项名
        assert "rar" in out.lower() or "Invalid" in out

    def test_QxwError_退出码沿用_message_里给出错误(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _raise(**_):  # type: ignore[no-untyped-def]
            raise ValidationError("路径不存在: /no/such")

        monkeypatch.setattr(git_mod, "archive_repo", _raise)
        code, out = _run(["archive", str(tmp_path)])
        # ValidationError 的 exit_code = 6
        assert code == 6
        assert "错误" in out
        assert "路径不存在" in out

    def test_CommandError_退出码_4(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        def _raise(**_):  # type: ignore[no-untyped-def]
            raise CommandError("不在 git 仓库内")

        monkeypatch.setattr(git_mod, "archive_repo", _raise)
        code, out = _run(["archive", str(tmp_path)])
        assert code == 4
        assert "不在 git 仓库内" in out

    def test_KeyboardInterrupt_退出码_130(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _raise(**_):  # type: ignore[no-untyped-def]
            raise KeyboardInterrupt()

        monkeypatch.setattr(git_mod, "archive_repo", _raise)
        code, out = _run(["archive", str(tmp_path)])
        assert code == 130
        assert "已取消" in out

    def test_未预期_Exception_退出码_1(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _raise(**_):  # type: ignore[no-untyped-def]
            raise RuntimeError("boom")

        monkeypatch.setattr(git_mod, "archive_repo", _raise)
        code, out = _run(["archive", str(tmp_path)])
        assert code == 1
        assert "未预期" in out


# ============================================================
# _human_size 辅助
# ============================================================


class TestHumanSize:
    def test_字节(self) -> None:
        assert git_mod._human_size(0).endswith("B")
        assert "1023" in git_mod._human_size(1023)

    def test_KB(self) -> None:
        assert "KB" in git_mod._human_size(2048)

    def test_MB(self) -> None:
        assert "MB" in git_mod._human_size(5 * 1024 * 1024)

    def test_GB(self) -> None:
        assert "GB" in git_mod._human_size(2 * 1024 * 1024 * 1024)

    def test_TB(self) -> None:
        assert "TB" in git_mod._human_size(2 * 1024**4)

    def test_PB_上限(self) -> None:
        assert "PB" in git_mod._human_size(3 * 1024**5)

    def test_负数也能格式化_不抛异常(self) -> None:
        # 实际不会发生（stat().st_size 不会为负），仅守护边界
        out = git_mod._human_size(-1)
        assert "B" in out
