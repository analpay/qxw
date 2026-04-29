"""qxw.library.services.git_archive_service 单元测试

覆盖核心异常路径与边界：
- 不存在 / 非目录 / 非 git 仓库
- 空仓库（无被跟踪文件）
- 不支持的格式 / 空 prefix / 包内默认无 .git
- LFS 检测与 LFS pull 的两条主分支（可用 + 需要 / 不可用 + 需要）
- subprocess 失败、git 不存在
- tar / tar.gz / tar.bz2 / tar.xz / zip 五种格式实际写入
"""

from __future__ import annotations

import os
import subprocess
import tarfile
import zipfile
from pathlib import Path

import pytest

from qxw.library.base.exceptions import CommandError, ValidationError
from qxw.library.services import git_archive_service as svc

# ============================================================
# 辅助
# ============================================================


def _git(args: list[str], cwd: Path) -> None:
    """跑一条 git 命令（测试辅助），错误时抛带上下文的异常"""
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


def _init_repo(path: Path) -> None:
    """初始化一个最小可用的 git 仓库（local 配置，不依赖全局 config）"""
    path.mkdir(parents=True, exist_ok=True)
    _git(["init", "-q", "-b", "main"], cwd=path)
    _git(["config", "user.email", "test@example.com"], cwd=path)
    _git(["config", "user.name", "Test"], cwd=path)
    _git(["config", "commit.gpgsign", "false"], cwd=path)


def _add_and_commit(repo: Path, files: dict[str, str]) -> None:
    for rel, content in files.items():
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    _git(["add", "-A"], cwd=repo)
    _git(["commit", "-q", "-m", "init"], cwd=repo)


# ============================================================
# 校验 / 路径错误
# ============================================================


class TestRepoValidation:
    def test_路径不存在_抛_ValidationError(self, tmp_path: Path) -> None:
        with pytest.raises(ValidationError) as ei:
            svc.archive_repo(tmp_path / "missing")
        assert "不存在" in ei.value.message

    def test_路径是文件_抛_ValidationError(self, tmp_path: Path) -> None:
        f = tmp_path / "f.txt"
        f.write_text("x")
        with pytest.raises(ValidationError) as ei:
            svc.archive_repo(f)
        assert "不是目录" in ei.value.message

    def test_非_git_仓库_抛_CommandError(self, tmp_path: Path) -> None:
        d = tmp_path / "plain"
        d.mkdir()
        with pytest.raises(CommandError) as ei:
            svc.archive_repo(d)
        # 来自 git rev-parse 的错误
        assert "git" in ei.value.message

    def test_空仓库_无被跟踪文件_抛_CommandError(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        with pytest.raises(CommandError) as ei:
            svc.archive_repo(tmp_path)
        assert "没有任何被 git 跟踪的文件" in ei.value.message


# ============================================================
# 格式校验 & 默认输出路径
# ============================================================


class TestFormatValidation:
    def test_未知格式_抛_ValidationError(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        _add_and_commit(tmp_path, {"a.txt": "1"})
        with pytest.raises(ValidationError) as ei:
            svc.archive_repo(tmp_path, fmt="rar")
        assert "不支持的格式" in ei.value.message

    def test_空_prefix_抛_ValidationError(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        _add_and_commit(tmp_path, {"a.txt": "1"})
        with pytest.raises(ValidationError):
            svc.archive_repo(tmp_path, arcname_prefix="///")


# ============================================================
# tar / zip 写入与"不含 .git"约束
# ============================================================


class TestArchiveContents:
    def _setup(self, tmp_path: Path) -> Path:
        repo = tmp_path / "demo"
        _init_repo(repo)
        _add_and_commit(
            repo,
            {
                "README.md": "# demo\n",
                "src/app.py": "print('hi')\n",
                "data/notes.txt": "n",
            },
        )
        return repo

    def test_默认_tar_输出路径在父目录_并且不含_dot_git(self, tmp_path: Path) -> None:
        repo = self._setup(tmp_path)
        result = svc.archive_repo(repo)
        assert result.output_path == repo.parent / "demo.tar"
        assert result.output_path.exists()
        assert result.file_count == 3
        assert result.archive_size > 0
        assert result.lfs_pulled is False

        with tarfile.open(result.output_path) as tar:
            names = tar.getnames()
        # 顶层目录 = 仓库名；不允许出现 .git / .git/ 前缀
        assert all(n.startswith("demo/") for n in names)
        assert all("/.git/" not in f"/{n}" and not n.endswith("/.git") for n in names)
        assert "demo/README.md" in names
        assert "demo/src/app.py" in names

    def test_tar_gz_格式_可用_gzip_打开(self, tmp_path: Path) -> None:
        repo = self._setup(tmp_path)
        result = svc.archive_repo(repo, fmt="tar.gz")
        assert result.output_path.suffix == ".gz"
        with tarfile.open(result.output_path, "r:gz") as tar:
            assert "demo/README.md" in tar.getnames()

    def test_tar_bz2_格式_可读(self, tmp_path: Path) -> None:
        repo = self._setup(tmp_path)
        result = svc.archive_repo(repo, fmt="tar.bz2")
        with tarfile.open(result.output_path, "r:bz2") as tar:
            assert "demo/data/notes.txt" in tar.getnames()

    def test_tar_xz_格式_可读(self, tmp_path: Path) -> None:
        repo = self._setup(tmp_path)
        result = svc.archive_repo(repo, fmt="tar.xz")
        with tarfile.open(result.output_path, "r:xz") as tar:
            assert "demo/src/app.py" in tar.getnames()

    def test_zip_格式_不含_dot_git(self, tmp_path: Path) -> None:
        repo = self._setup(tmp_path)
        out = tmp_path / "out.zip"
        result = svc.archive_repo(repo, output=out, fmt="zip")
        assert result.output_path == out
        with zipfile.ZipFile(out) as zf:
            names = zf.namelist()
        assert all(n.startswith("demo/") for n in names)
        assert all(".git/" not in n for n in names)
        assert "demo/README.md" in names

    def test_自定义_prefix_作为顶层目录(self, tmp_path: Path) -> None:
        repo = self._setup(tmp_path)
        result = svc.archive_repo(repo, arcname_prefix="release-1.0")
        with tarfile.open(result.output_path) as tar:
            names = tar.getnames()
        assert all(n.startswith("release-1.0/") for n in names)

    def test_工作树子路径_自动定位仓库根(self, tmp_path: Path) -> None:
        repo = self._setup(tmp_path)
        # 传入工作树内的子目录，应能自动 rev-parse 回根
        result = svc.archive_repo(repo / "src")
        with tarfile.open(result.output_path) as tar:
            assert "demo/src/app.py" in tar.getnames()


# ============================================================
# 跟踪条目中含子模块 / 缺失文件时的健壮性
# ============================================================


class TestSkipUnusual:
    def test_子模块条目被跳过_不抛异常(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        repo = tmp_path / "host"
        _init_repo(repo)
        _add_and_commit(repo, {"keep.txt": "k"})

        # 伪造一条 ls-files 输出，混入一个不存在的路径与一个目录路径
        (repo / "subdir").mkdir()
        fake_ls = "keep.txt\x00ghost.txt\x00subdir\x00"

        orig = svc._run_git

        def _fake_run_git(args: list[str], cwd: Path):  # type: ignore[no-untyped-def]
            if args[:2] == ["ls-files", "-z"]:
                cp = subprocess.CompletedProcess(args=["git", *args], returncode=0, stdout=fake_ls, stderr="")
                return cp
            return orig(args, cwd)

        monkeypatch.setattr(svc, "_run_git", _fake_run_git)
        result = svc.archive_repo(repo)
        # 仅 keep.txt 应被打包（ghost.txt 不存在 / subdir 是目录都被跳过）
        assert result.file_count == 1
        with tarfile.open(result.output_path) as tar:
            assert tar.getnames() == ["host/keep.txt"]


# ============================================================
# git-lfs 分支
# ============================================================


class TestLfsBranches:
    def test_仓库需要_lfs_但_lfs_不可用_抛_CommandError(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = tmp_path / "lfsrepo"
        _init_repo(repo)
        _add_and_commit(repo, {"a.txt": "x"})

        monkeypatch.setattr(svc, "_detect_lfs", lambda _r: (True, False))
        with pytest.raises(CommandError) as ei:
            svc.archive_repo(repo)
        assert "git-lfs" in ei.value.message

    def test_仓库需要_lfs_且可用_会执行_lfs_pull(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = tmp_path / "lfsrepo2"
        _init_repo(repo)
        _add_and_commit(repo, {"a.txt": "x"})

        monkeypatch.setattr(svc, "_detect_lfs", lambda _r: (True, True))

        recorded: list[list[str]] = []
        orig = svc._run_git

        def _spy(args: list[str], cwd: Path):  # type: ignore[no-untyped-def]
            recorded.append(args)
            if args[:1] == ["lfs"]:
                return subprocess.CompletedProcess(args=["git", *args], returncode=0, stdout="", stderr="")
            return orig(args, cwd)

        monkeypatch.setattr(svc, "_run_git", _spy)
        result = svc.archive_repo(repo)
        assert result.lfs_pulled is True
        assert ["lfs", "pull"] in recorded

    def test_pull_lfs_为_False_即使需要也不调用(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = tmp_path / "lfsrepo3"
        _init_repo(repo)
        _add_and_commit(repo, {"a.txt": "x"})

        monkeypatch.setattr(svc, "_detect_lfs", lambda _r: (True, True))
        called: list[list[str]] = []
        orig = svc._run_git

        def _spy(args: list[str], cwd: Path):  # type: ignore[no-untyped-def]
            called.append(args)
            return orig(args, cwd)

        monkeypatch.setattr(svc, "_run_git", _spy)
        result = svc.archive_repo(repo, pull_lfs=False)
        assert result.lfs_pulled is False
        # 不应包含 lfs 子命令
        assert all(args[:1] != ["lfs"] for args in called)


# ============================================================
# _detect_lfs 内部分支
# ============================================================


class TestDetectLfs:
    def test_lfs_可用_有跟踪文件(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        repo = tmp_path / "r"
        _init_repo(repo)

        def _fake_run(*args, **kw):  # type: ignore[no-untyped-def]
            return subprocess.CompletedProcess(
                args=["git", "lfs", "ls-files"],
                returncode=0,
                stdout="abc *.bin\n",
                stderr="",
            )

        monkeypatch.setattr(svc.subprocess, "run", _fake_run)
        needs, available = svc._detect_lfs(repo)
        assert needs is True
        assert available is True

    def test_lfs_可用_无跟踪文件(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        repo = tmp_path / "r"
        _init_repo(repo)

        def _fake_run(*args, **kw):  # type: ignore[no-untyped-def]
            return subprocess.CompletedProcess(
                args=["git", "lfs", "ls-files"],
                returncode=0,
                stdout="",
                stderr="",
            )

        monkeypatch.setattr(svc.subprocess, "run", _fake_run)
        needs, available = svc._detect_lfs(repo)
        assert needs is False
        assert available is True

    def test_lfs_不可用_但_gitattributes_引用_lfs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = tmp_path / "r"
        _init_repo(repo)
        (repo / ".gitattributes").write_text("*.bin filter=lfs diff=lfs merge=lfs -text\n", encoding="utf-8")

        def _fake_run(*args, **kw):  # type: ignore[no-untyped-def]
            return subprocess.CompletedProcess(args=["git", "lfs"], returncode=1, stdout="", stderr="not a git command")

        monkeypatch.setattr(svc.subprocess, "run", _fake_run)
        needs, available = svc._detect_lfs(repo)
        assert needs is True
        assert available is False

    def test_lfs_不可用_gitattributes_不存在(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = tmp_path / "r"
        _init_repo(repo)

        def _fake_run(*args, **kw):  # type: ignore[no-untyped-def]
            return subprocess.CompletedProcess(args=["git", "lfs"], returncode=1, stdout="", stderr="not a git command")

        monkeypatch.setattr(svc.subprocess, "run", _fake_run)
        needs, available = svc._detect_lfs(repo)
        assert needs is False
        assert available is False

    def test_subprocess_run_FileNotFoundError(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = tmp_path / "r"
        _init_repo(repo)

        def _fake_run(*args, **kw):  # type: ignore[no-untyped-def]
            raise FileNotFoundError("no git")

        monkeypatch.setattr(svc.subprocess, "run", _fake_run)
        needs, available = svc._detect_lfs(repo)
        assert needs is False
        assert available is False


# ============================================================
# _run_git 异常归一化
# ============================================================


class TestRunGitErrors:
    def test_git_命令缺失_映射为_CommandError(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _fake_run(*args, **kw):  # type: ignore[no-untyped-def]
            raise FileNotFoundError("git missing")

        monkeypatch.setattr(svc.subprocess, "run", _fake_run)
        with pytest.raises(CommandError) as ei:
            svc._run_git(["status"], cwd=tmp_path)
        assert "找不到 git" in ei.value.message

    def test_git_返回非零_映射为_CommandError_并保留_stderr(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _fake_run(*args, **kw):  # type: ignore[no-untyped-def]
            raise subprocess.CalledProcessError(
                returncode=128,
                cmd=["git", "status"],
                output="",
                stderr="fatal: not a git repository\n",
            )

        monkeypatch.setattr(svc.subprocess, "run", _fake_run)
        with pytest.raises(CommandError) as ei:
            svc._run_git(["status"], cwd=tmp_path)
        assert "not a git repository" in ei.value.message


# ============================================================
# zip 写入对符号链接 / 缺失目标的处理（仅在支持 symlink 的平台）
# ============================================================


@pytest.mark.skipif(os.name == "nt", reason="Windows symlink 需要管理员权限，跳过")
class TestSymlinkZip:
    def test_zip_中悬空符号链接被跳过(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        repo = tmp_path / "sym"
        _init_repo(repo)
        (repo / "real.txt").write_text("hi", encoding="utf-8")
        link = repo / "broken.lnk"
        link.symlink_to(repo / "does_not_exist")
        _git(["add", "-A"], cwd=repo)
        _git(["commit", "-q", "-m", "init"], cwd=repo)

        result = svc.archive_repo(repo, fmt="zip")
        with zipfile.ZipFile(result.output_path) as zf:
            names = zf.namelist()
        # real.txt 一定在；broken.lnk 因目标不存在被跳过
        assert any(n.endswith("real.txt") for n in names)
        assert all(not n.endswith("broken.lnk") for n in names)


# ============================================================
# ArchiveResult 元数据正确性
# ============================================================


class TestArchiveResult:
    def test_size_等于实际文件大小(self, tmp_path: Path) -> None:
        repo = tmp_path / "sz"
        _init_repo(repo)
        _add_and_commit(repo, {"a.txt": "hello world"})
        result = svc.archive_repo(repo)
        assert result.archive_size == result.output_path.stat().st_size > 0

    def test_文件计数与_ls_files_一致(self, tmp_path: Path) -> None:
        repo = tmp_path / "cnt"
        _init_repo(repo)
        _add_and_commit(repo, {"a.txt": "1", "b/c.txt": "2", "d.txt": "3"})
        result = svc.archive_repo(repo)
        assert result.file_count == 3


# ============================================================
# 私有常量保护：写入 ArchiveResult 后 buffer 仍可被读
# ============================================================


def test_supported_formats_常量包含五种() -> None:
    assert set(svc.SUPPORTED_FORMATS) == {"tar", "tar.gz", "tar.bz2", "tar.xz", "zip"}


def test_default_format_为_tar() -> None:
    assert svc.DEFAULT_FORMAT == "tar"
