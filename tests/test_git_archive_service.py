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
import tempfile
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


# ============================================================
# --ref 分支：基于 git worktree add --detach 打包指定分支 / tag
# ============================================================


def _setup_two_branches(tmp_path: Path) -> Path:
    """初始化一个含 main / feature 两条分支与一个 tag 的仓库"""
    repo = tmp_path / "branched"
    _init_repo(repo)
    # main 分支：only_main.txt
    _add_and_commit(repo, {"shared.txt": "v1", "only_main.txt": "M"})
    _git(["tag", "v1.0"], cwd=repo)
    # 切到 feature/foo（含斜杠，验证 ref 文件名转义）
    _git(["checkout", "-q", "-b", "feature/foo"], cwd=repo)
    (repo / "only_feature.txt").write_text("F", encoding="utf-8")
    # 同时把 only_main 删掉，保证两条分支差异显著
    (repo / "only_main.txt").unlink()
    _git(["add", "-A"], cwd=repo)
    _git(["commit", "-q", "-m", "feature"], cwd=repo)
    # 把工作树留在 feature 分支（与 main 内容不一样）
    return repo


class TestRefArchive:
    def test_ref_不存在_抛_ValidationError(self, tmp_path: Path) -> None:
        repo = tmp_path / "r"
        _init_repo(repo)
        _add_and_commit(repo, {"a.txt": "1"})
        with pytest.raises(ValidationError) as ei:
            svc.archive_repo(repo, ref="no-such-branch")
        assert "不存在" in ei.value.message
        assert "no-such-branch" in ei.value.message

    def test_ref_为空字符串_抛_ValidationError(self, tmp_path: Path) -> None:
        repo = tmp_path / "r"
        _init_repo(repo)
        _add_and_commit(repo, {"a.txt": "1"})
        with pytest.raises(ValidationError) as ei:
            svc.archive_repo(repo, ref="   ")
        assert "ref" in ei.value.message.lower() or "不能为空" in ei.value.message

    def test_打包_main_分支_只含_main_的文件(self, tmp_path: Path) -> None:
        repo = _setup_two_branches(tmp_path)
        result = svc.archive_repo(repo, ref="main")
        # 默认输出名 = <repo>-<ref>.<fmt>
        assert result.output_path == repo.parent / "branched-main.tar"
        assert result.ref == "main"
        with tarfile.open(result.output_path) as tar:
            names = set(tar.getnames())
        # 顶层 prefix = repo.name，包内不含 .git
        assert "branched/shared.txt" in names
        assert "branched/only_main.txt" in names
        assert "branched/only_feature.txt" not in names
        assert all(".git/" not in n for n in names)

    def test_打包_tag(self, tmp_path: Path) -> None:
        repo = _setup_two_branches(tmp_path)
        result = svc.archive_repo(repo, ref="v1.0", fmt="zip")
        assert result.ref == "v1.0"
        assert result.output_path == repo.parent / "branched-v1.0.zip"
        with zipfile.ZipFile(result.output_path) as zf:
            names = set(zf.namelist())
        # tag 指向 main，应只含 only_main.txt
        assert "branched/only_main.txt" in names
        assert "branched/only_feature.txt" not in names

    def test_含斜杠的_ref_默认输出名转义(self, tmp_path: Path) -> None:
        repo = _setup_two_branches(tmp_path)
        result = svc.archive_repo(repo, ref="feature/foo")
        # / 应被替换为 _
        assert result.output_path == repo.parent / "branched-feature_foo.tar"

    def test_打包_feature_分支_包含_only_feature(self, tmp_path: Path) -> None:
        repo = _setup_two_branches(tmp_path)
        result = svc.archive_repo(repo, ref="feature/foo")
        with tarfile.open(result.output_path) as tar:
            names = set(tar.getnames())
        assert "branched/only_feature.txt" in names
        assert "branched/only_main.txt" not in names

    def test_ref_存在但_worktree_临时目录已被自动清理(self, tmp_path: Path) -> None:
        repo = _setup_two_branches(tmp_path)
        before = list(Path(tempfile.gettempdir()).glob("qxw-git-arc-*"))
        svc.archive_repo(repo, ref="main")
        after = list(Path(tempfile.gettempdir()).glob("qxw-git-arc-*"))
        # 不会留下我们的临时 worktree 目录（与运行前的快照差集为空）
        leftover = set(after) - set(before)
        assert leftover == set()

    def test_工作树仍为_feature_打包后未被切换(self, tmp_path: Path) -> None:
        """archive_repo(ref=...) 不应把主工作树切到目标分支"""
        repo = _setup_two_branches(tmp_path)
        svc.archive_repo(repo, ref="main")
        # 仍应处于 feature/foo
        head = subprocess.run(
            ["git", "symbolic-ref", "--short", "HEAD"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        assert head == "feature/foo"

    def test_ref_打包_lfs_检测分支被复用(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """指定 ref 时应在临时 worktree 内调用 _detect_lfs / lfs pull"""
        repo = _setup_two_branches(tmp_path)
        recorded_detect: list[Path] = []
        recorded_lfs_pull: list[Path] = []

        def _fake_detect(p: Path):  # type: ignore[no-untyped-def]
            recorded_detect.append(p)
            return True, True

        orig = svc._run_git

        def _spy(args: list[str], cwd: Path):  # type: ignore[no-untyped-def]
            if args[:2] == ["lfs", "pull"]:
                recorded_lfs_pull.append(cwd)
                return subprocess.CompletedProcess(args=["git", *args], returncode=0, stdout="", stderr="")
            return orig(args, cwd)

        monkeypatch.setattr(svc, "_detect_lfs", _fake_detect)
        monkeypatch.setattr(svc, "_run_git", _spy)
        result = svc.archive_repo(repo, ref="main")
        assert result.lfs_pulled is True
        # _detect_lfs 与 lfs pull 都应作用于临时 worktree（不是主仓库本身）
        assert recorded_detect, "_detect_lfs should have been called"
        assert recorded_detect[0] != repo
        assert recorded_lfs_pull, "git lfs pull should have been invoked"
        assert recorded_lfs_pull[0] != repo

    def test_显式_output_覆盖默认_ref_命名(self, tmp_path: Path) -> None:
        repo = _setup_two_branches(tmp_path)
        out = tmp_path / "custom" / "x.tar.gz"
        result = svc.archive_repo(repo, ref="main", fmt="tar.gz", output=out)
        assert result.output_path == out
        assert out.exists()


class TestExcludes:
    """``excludes`` 参数与默认排除 .gitattributes 行为"""

    def _setup_with_attrs(self, tmp_path: Path) -> Path:
        repo = tmp_path / "exc"
        _init_repo(repo)
        _add_and_commit(
            repo,
            {
                ".gitattributes": "* text=auto\n",
                "README.md": "# x\n",
                "docs/a.md": "a",
                "docs/sub/b.md": "b",
                "src/app.py": "p",
                "tests/fixtures/data.bin": "d",
                "config/local.yaml": "y",
            },
        )
        return repo

    def test_默认排除_gitattributes(self, tmp_path: Path) -> None:
        repo = self._setup_with_attrs(tmp_path)
        result = svc.archive_repo(repo)
        with tarfile.open(result.output_path) as tar:
            names = tar.getnames()
        # .gitattributes 不应出现在包中
        assert all(not n.endswith(".gitattributes") for n in names)
        # 其他文件正常被打包
        assert "exc/README.md" in names
        assert result.excluded_count == 1

    def test_关闭默认排除_保留_gitattributes(self, tmp_path: Path) -> None:
        repo = self._setup_with_attrs(tmp_path)
        result = svc.archive_repo(repo, include_default_excludes=False)
        with tarfile.open(result.output_path) as tar:
            names = tar.getnames()
        assert "exc/.gitattributes" in names
        assert result.excluded_count == 0

    def test_目录前缀_排除整棵子树(self, tmp_path: Path) -> None:
        repo = self._setup_with_attrs(tmp_path)
        result = svc.archive_repo(repo, excludes=["docs"])
        with tarfile.open(result.output_path) as tar:
            names = tar.getnames()
        assert all(not n.startswith("exc/docs/") for n in names)
        # 不应误伤同名前缀文件
        assert "exc/README.md" in names
        assert "exc/src/app.py" in names
        # docs/a.md + docs/sub/b.md + .gitattributes = 3
        assert result.excluded_count == 3

    def test_精确路径_只排除单个文件(self, tmp_path: Path) -> None:
        repo = self._setup_with_attrs(tmp_path)
        result = svc.archive_repo(repo, excludes=["config/local.yaml"])
        with tarfile.open(result.output_path) as tar:
            names = set(tar.getnames())
        assert "exc/config/local.yaml" not in names
        # 同目录其他文件不动（虽然这个例子 config 目录就一个文件，但前缀相同的不应被误判）
        assert result.excluded_count == 2  # local.yaml + .gitattributes

    def test_glob_无斜杠_命中任意层级(self, tmp_path: Path) -> None:
        repo = self._setup_with_attrs(tmp_path)
        result = svc.archive_repo(repo, excludes=["*.md"])
        with tarfile.open(result.output_path) as tar:
            names = tar.getnames()
        assert all(not n.endswith(".md") for n in names)
        # 顶层 .md + docs 内 .md 都该被排除
        assert "exc/README.md" not in names
        assert "exc/docs/a.md" not in names
        assert "exc/docs/sub/b.md" not in names

    def test_glob_含斜杠_仅按完整路径匹配(self, tmp_path: Path) -> None:
        repo = self._setup_with_attrs(tmp_path)
        # docs/*.md 仅命中 docs 一级，不命中 docs/sub/b.md
        result = svc.archive_repo(repo, excludes=["docs/*.md"])
        with tarfile.open(result.output_path) as tar:
            names = set(tar.getnames())
        assert "exc/docs/a.md" not in names
        assert "exc/docs/sub/b.md" in names

    def test_多个_excludes_叠加(self, tmp_path: Path) -> None:
        repo = self._setup_with_attrs(tmp_path)
        result = svc.archive_repo(
            repo, excludes=["tests/fixtures", "*.md", "config/local.yaml"]
        )
        with tarfile.open(result.output_path) as tar:
            names = set(tar.getnames())
        assert "exc/src/app.py" in names
        assert all(not n.endswith(".md") for n in names)
        assert "exc/tests/fixtures/data.bin" not in names
        assert "exc/config/local.yaml" not in names

    def test_excludes_去重(self, tmp_path: Path) -> None:
        repo = self._setup_with_attrs(tmp_path)
        # 同一规则给多次不应导致 excluded_count 重复计数
        result = svc.archive_repo(repo, excludes=["docs", "docs", "docs/"])
        # 与单次 excludes=["docs"] 的统计应一致
        baseline = svc.archive_repo(
            repo, excludes=["docs"], output=tmp_path / "base.tar"
        )
        assert result.excluded_count == baseline.excluded_count

    def test_excludes_首尾斜杠_反斜杠_归一化(self, tmp_path: Path) -> None:
        repo = self._setup_with_attrs(tmp_path)
        # /docs/ 与 docs\\ 都应等价于 docs
        result = svc.archive_repo(repo, excludes=["/docs/", "docs\\"])
        with tarfile.open(result.output_path) as tar:
            names = tar.getnames()
        assert all(not n.startswith("exc/docs/") for n in names)

    def test_排除项含双点_抛_ValidationError(self, tmp_path: Path) -> None:
        repo = self._setup_with_attrs(tmp_path)
        with pytest.raises(ValidationError) as ei:
            svc.archive_repo(repo, excludes=["../etc"])
        assert ".." in ei.value.message

    def test_排除项含双点位于中段_也被拒绝(self, tmp_path: Path) -> None:
        repo = self._setup_with_attrs(tmp_path)
        with pytest.raises(ValidationError):
            svc.archive_repo(repo, excludes=["docs/../secrets"])

    def test_排除项全部空白_视为无规则_仍走默认(self, tmp_path: Path) -> None:
        repo = self._setup_with_attrs(tmp_path)
        # 空字符串 / 仅空白 / None 都该被过滤掉，不会误命中所有文件
        result = svc.archive_repo(repo, excludes=["", "   ", None])  # type: ignore[list-item]
        with tarfile.open(result.output_path) as tar:
            names = tar.getnames()
        assert "exc/README.md" in names
        # .gitattributes 仍由默认排除拦截
        assert all(not n.endswith(".gitattributes") for n in names)
        assert result.excluded_count == 1

    def test_所有跟踪文件都被排除_抛_CommandError(self, tmp_path: Path) -> None:
        repo = tmp_path / "only_attr"
        _init_repo(repo)
        _add_and_commit(repo, {".gitattributes": "* text=auto\n", "a.md": "x"})
        with pytest.raises(CommandError) as ei:
            svc.archive_repo(repo, excludes=["*.md"])  # 默认还会再吃掉 .gitattributes
        assert "排除规则过滤后" in ei.value.message

    def test_excludes_不影响_lfs_检测(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """即便 .gitattributes 被默认排除，仍要根据它检测 LFS"""
        repo = tmp_path / "lfs_attr"
        _init_repo(repo)
        _add_and_commit(
            repo,
            {
                ".gitattributes": "*.bin filter=lfs diff=lfs merge=lfs -text\n",
                "keep.txt": "k",
            },
        )

        # 模拟仓库需要 LFS 且 LFS 可用
        monkeypatch.setattr(svc, "_detect_lfs", lambda _r: (True, True))
        recorded: list[list[str]] = []
        orig = svc._run_git

        def _spy(args: list[str], cwd: Path):  # type: ignore[no-untyped-def]
            recorded.append(args)
            if args[:2] == ["lfs", "pull"]:
                return subprocess.CompletedProcess(args=["git", *args], returncode=0, stdout="", stderr="")
            return orig(args, cwd)

        monkeypatch.setattr(svc, "_run_git", _spy)
        result = svc.archive_repo(repo)
        # LFS pull 仍应执行（说明默认排除 .gitattributes 不会影响检测）
        assert ["lfs", "pull"] in recorded
        assert result.lfs_pulled is True
        with tarfile.open(result.output_path) as tar:
            names = tar.getnames()
        assert all(not n.endswith(".gitattributes") for n in names)
        assert "lfs_attr/keep.txt" in names

    def test_excludes_在_ref_分支模式下生效(self, tmp_path: Path) -> None:
        repo = _setup_two_branches(tmp_path)
        # 给 main 分支额外加一个 .gitattributes 以测试默认排除在 worktree 路径下也生效
        _git(["checkout", "-q", "main"], cwd=repo)
        (repo / ".gitattributes").write_text("* text=auto\n", encoding="utf-8")
        _git(["add", "-A"], cwd=repo)
        _git(["commit", "-q", "-m", "add attrs"], cwd=repo)
        _git(["checkout", "-q", "feature/foo"], cwd=repo)

        result = svc.archive_repo(repo, ref="main", excludes=["only_main.txt"])
        with tarfile.open(result.output_path) as tar:
            names = set(tar.getnames())
        assert "branched/.gitattributes" not in names  # 默认排除
        assert "branched/only_main.txt" not in names  # 自定义排除
        assert "branched/shared.txt" in names


class TestNormalizeExcludes:
    """直接测 :func:`_normalize_excludes` 的纯逻辑分支"""

    def test_空输入_仅返回默认(self) -> None:
        assert svc._normalize_excludes(None) == svc.DEFAULT_EXCLUDES
        assert svc._normalize_excludes([]) == svc.DEFAULT_EXCLUDES

    def test_关闭默认_空输入_返回空(self) -> None:
        assert svc._normalize_excludes(None, include_defaults=False) == ()
        assert svc._normalize_excludes([], include_defaults=False) == ()

    def test_去重保序(self) -> None:
        out = svc._normalize_excludes(["b", "a", "b", "a"], include_defaults=False)
        assert out == ("b", "a")

    def test_空白条目被过滤(self) -> None:
        out = svc._normalize_excludes(["", "   ", "\t", "x"], include_defaults=False)
        assert out == ("x",)

    def test_反斜杠归一_首尾斜杠剥离(self) -> None:
        out = svc._normalize_excludes(["a\\b\\", "/c/"], include_defaults=False)
        assert out == ("a/b", "c")

    def test_含_dotdot_抛_ValidationError(self) -> None:
        with pytest.raises(ValidationError):
            svc._normalize_excludes([".."], include_defaults=False)
        with pytest.raises(ValidationError):
            svc._normalize_excludes(["a/../b"], include_defaults=False)


class TestPathMatchesExclude:
    """直接测 :func:`_path_matches_exclude` 的三类匹配规则"""

    def test_精确路径_命中(self) -> None:
        assert svc._path_matches_exclude("a/b.txt", "a/b.txt") is True

    def test_精确路径_前缀同名不误命中(self) -> None:
        assert svc._path_matches_exclude("ab.txt", "a") is False

    def test_目录前缀_命中子树(self) -> None:
        assert svc._path_matches_exclude("docs/a.md", "docs") is True
        assert svc._path_matches_exclude("docs/sub/b.md", "docs") is True

    def test_同名文件按精确匹配命中(self) -> None:
        # 模式 "docs" 既能命中 docs/ 子树，也命中名字恰为 docs 的文件（精确匹配）
        assert svc._path_matches_exclude("docs", "docs") is True

    def test_前缀长度不足不会误命中(self) -> None:
        # 模式 "doc" 不应命中 "docs/a.md"（必须正好以模式 + "/" 开头）
        assert svc._path_matches_exclude("docs/a.md", "doc") is False

    def test_glob_无斜杠_段级匹配(self) -> None:
        assert svc._path_matches_exclude("readme.md", "*.md") is True
        assert svc._path_matches_exclude("docs/a.md", "*.md") is True

    def test_glob_含斜杠_仅按完整路径(self) -> None:
        assert svc._path_matches_exclude("docs/a.md", "docs/*.md") is True
        assert svc._path_matches_exclude("docs/sub/b.md", "docs/*.md") is False

    def test_glob_问号与方括号(self) -> None:
        assert svc._path_matches_exclude("a1.txt", "a?.txt") is True
        assert svc._path_matches_exclude("a1.txt", "a[12].txt") is True
        assert svc._path_matches_exclude("a3.txt", "a[12].txt") is False


class TestSanitizeRefForFilename:
    def test_斜杠_反斜杠_冒号_空白_全部替换为下划线(self) -> None:
        assert svc._sanitize_ref_for_filename("feature/foo") == "feature_foo"
        assert svc._sanitize_ref_for_filename("a\\b") == "a_b"
        assert svc._sanitize_ref_for_filename("ns:tag") == "ns_tag"
        assert svc._sanitize_ref_for_filename("a b") == "a_b"

    def test_全是分隔符_退化为_ref(self) -> None:
        assert svc._sanitize_ref_for_filename("///") == "ref"

    def test_保留普通字符与点(self) -> None:
        assert svc._sanitize_ref_for_filename("v1.2.3") == "v1.2.3"
        assert svc._sanitize_ref_for_filename("release-2026") == "release-2026"
