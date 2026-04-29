"""git 仓库打包服务

将一个 git 工作树打包成 tar / zip 包，并满足以下约束：

- 包内 **不含** ``.git`` 目录与任何 git 元数据
- 若仓库使用了 git-lfs，先执行 ``git lfs pull`` 让指针文件实体化为真实文件
- 仅打包被 git 跟踪的文件（``git ls-files``），自动忽略未跟踪与 .gitignore 命中的内容
- 支持 ``tar`` / ``tar.gz`` / ``tar.bz2`` / ``tar.xz`` / ``zip`` 五种格式
- 支持 ``ref`` 参数：基于 ``git worktree add --detach <ref>`` 在临时目录里
  签出指定分支 / tag / commit-ish 后再打包，结束时自动清理 worktree

实现依赖外部 ``git`` 命令（必需）与 ``git-lfs``（仅当仓库引用了 LFS 时必需）。
所有 git 子进程错误统一映射为 :class:`CommandError`，参数 / 路径错误映射为
:class:`ValidationError`，便于 bin/git_cmd.py 入口统一处理。
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tarfile
import tempfile
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Literal

from qxw.library.base.exceptions import CommandError, ValidationError
from qxw.library.base.logger import get_logger

logger = get_logger("qxw.git_archive")

ArchiveFormat = Literal["tar", "tar.gz", "tar.bz2", "tar.xz", "zip"]
SUPPORTED_FORMATS: tuple[ArchiveFormat, ...] = (
    "tar",
    "tar.gz",
    "tar.bz2",
    "tar.xz",
    "zip",
)
DEFAULT_FORMAT: ArchiveFormat = "tar"

_TAR_MODES: dict[str, str] = {
    "tar": "w",
    "tar.gz": "w:gz",
    "tar.bz2": "w:bz2",
    "tar.xz": "w:xz",
}

# ref 名内可能含有 / : \ 等不适合文件名的字符，统一替换为 _
_REF_FILENAME_SANITIZER = re.compile(r"[\\/:\s]+")


@dataclass(frozen=True)
class ArchiveResult:
    """打包结果元数据"""

    output_path: Path
    file_count: int
    archive_size: int
    lfs_pulled: bool
    ref: str | None = None


def _run_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    """运行 git 子命令并把异常归一化"""
    try:
        return subprocess.run(
            ["git", *args],
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as e:
        raise CommandError("找不到 git 命令，请先安装 git") from e
    except subprocess.CalledProcessError as e:
        msg = (e.stderr or e.stdout or "").strip()
        raise CommandError(f"git {' '.join(args)} 失败: {msg}") from e


def _ensure_git_repo(repo_path: Path) -> Path:
    """校验路径并返回工作树根目录"""
    if not repo_path.exists():
        raise ValidationError(f"路径不存在: {repo_path}")
    if not repo_path.is_dir():
        raise ValidationError(f"路径不是目录: {repo_path}")
    res = _run_git(["rev-parse", "--show-toplevel"], cwd=repo_path)
    top = res.stdout.strip()
    if not top:
        raise CommandError(f"无法定位 git 仓库根目录: {repo_path}")
    return Path(top)


def _validate_ref(repo: Path, ref: str) -> None:
    """校验 ref 在仓库内可解析为某个 commit"""
    if not ref or not ref.strip():
        raise ValidationError("ref 不能为空")
    try:
        _run_git(["rev-parse", "--verify", f"{ref}^{{commit}}"], cwd=repo)
    except CommandError as e:
        raise ValidationError(f"分支 / tag / commit 不存在: {ref}") from e


@contextmanager
def _temp_worktree(repo: Path, ref: str) -> Iterator[Path]:
    """在临时目录中签出指定 ref 为 detached worktree，退出时自动清理

    使用 ``git worktree add --detach`` 而不是 ``git checkout``，避免污染主工作树
    的状态；同时与主仓库共享 ``.git/lfs``、``.git/objects``，已 pull 过的 LFS
    对象不会重复下载。
    """
    tmp_root = Path(tempfile.mkdtemp(prefix="qxw-git-arc-"))
    wt_path = tmp_root / "wt"
    try:
        try:
            _run_git(
                ["worktree", "add", "--detach", str(wt_path), ref],
                cwd=repo,
            )
        except CommandError:
            shutil.rmtree(tmp_root, ignore_errors=True)
            raise
        yield wt_path
    finally:
        # remove --force：worktree 内可能残留 LFS pull 之后的临时改动
        try:
            _run_git(["worktree", "remove", "--force", str(wt_path)], cwd=repo)
        except CommandError as e:
            logger.warning("清理临时 worktree 失败（将直接 rmtree）: %s", e)
        shutil.rmtree(tmp_root, ignore_errors=True)


def _list_tracked_files(repo: Path) -> list[str]:
    """以 NUL 分隔安全地列出全部被 git 跟踪的文件"""
    res = _run_git(["ls-files", "-z"], cwd=repo)
    raw = res.stdout
    if not raw:
        return []
    return [p for p in raw.split("\0") if p]


def _detect_lfs(repo: Path) -> tuple[bool, bool]:
    """检测仓库是否使用了 git-lfs

    返回值: ``(needs_lfs, lfs_available)``

    - 优先调用 ``git lfs ls-files``：若返回码 0，则 git-lfs 可用，是否使用 LFS
      由 stdout 是否非空决定
    - 若 git-lfs 不可用，再扫描 ``.gitattributes`` 中是否含 ``filter=lfs``，
      用以判断"仓库引用了 LFS 但当前环境无法 pull"的失败场景
    """
    try:
        proc = subprocess.run(
            ["git", "lfs", "ls-files"],
            cwd=repo,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        proc = None

    if proc is not None and proc.returncode == 0:
        return bool(proc.stdout.strip()), True

    needs_lfs = False
    gitattributes = repo / ".gitattributes"
    if gitattributes.exists():
        try:
            content = gitattributes.read_text(encoding="utf-8", errors="ignore")
            needs_lfs = "filter=lfs" in content
        except OSError as e:
            logger.warning("读取 .gitattributes 失败: %s", e)
    return needs_lfs, False


def _validate_format(fmt: str) -> ArchiveFormat:
    if fmt not in SUPPORTED_FORMATS:
        raise ValidationError(
            f"不支持的格式: {fmt}（支持: {', '.join(SUPPORTED_FORMATS)})"
        )
    return fmt  # type: ignore[return-value]


def _sanitize_ref_for_filename(ref: str) -> str:
    """把 ref 名转成可用的文件名片段（替换 / \\ : 空白为 _）"""
    return _REF_FILENAME_SANITIZER.sub("_", ref).strip("_") or "ref"


def _resolve_output(
    repo: Path,
    fmt: ArchiveFormat,
    output: Path | None,
    ref: str | None,
) -> Path:
    if output is not None:
        return output
    if ref is not None:
        return repo.parent / f"{repo.name}-{_sanitize_ref_for_filename(ref)}.{fmt}"
    return repo.parent / f"{repo.name}.{fmt}"


def _add_files_to_tar(
    tar_path: Path,
    repo: Path,
    files: Iterable[str],
    mode: str,
    arcname_prefix: str,
) -> int:
    count = 0
    skipped: list[str] = []
    with tarfile.open(tar_path, mode) as tar:
        for rel in files:
            src = repo / rel
            if src.is_symlink():
                tar.add(src, arcname=f"{arcname_prefix}/{rel}", recursive=False)
                count += 1
                continue
            if not src.exists():
                skipped.append(rel)
                continue
            if src.is_dir():
                # gitlink（子模块）也会被 ls-files 列出，这里仅打包文件
                skipped.append(rel)
                continue
            tar.add(src, arcname=f"{arcname_prefix}/{rel}", recursive=False)
            count += 1
    if skipped:
        logger.warning("打包过程中跳过 %d 个非常规条目（如子模块 / 缺失文件）", len(skipped))
    return count


def _add_files_to_zip(
    zip_path: Path,
    repo: Path,
    files: Iterable[str],
    arcname_prefix: str,
) -> int:
    count = 0
    skipped: list[str] = []
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for rel in files:
            src = repo / rel
            if src.is_symlink():
                # zip 不能很好保留符号链接，统一按链接目标的内容写入；
                # 这里先 resolve 取实体路径，避免循环链接造成的 RecursionError
                target = src.resolve(strict=False)
                if not target.exists() or target.is_dir():
                    skipped.append(rel)
                    continue
                zf.write(target, arcname=f"{arcname_prefix}/{rel}")
                count += 1
                continue
            if not src.exists():
                skipped.append(rel)
                continue
            if src.is_dir():
                skipped.append(rel)
                continue
            zf.write(src, arcname=f"{arcname_prefix}/{rel}")
            count += 1
    if skipped:
        logger.warning("打包过程中跳过 %d 个非常规条目（如子模块 / 缺失文件）", len(skipped))
    return count


def _pack_worktree(
    worktree: Path,
    out_path: Path,
    fmt_ok: ArchiveFormat,
    pull_lfs: bool,
    prefix: str,
) -> tuple[int, bool]:
    """把一棵已签出的工作树打成 tar / zip，返回 (file_count, lfs_pulled)"""
    files = _list_tracked_files(worktree)
    if not files:
        raise CommandError("仓库内没有任何被 git 跟踪的文件")

    needs_lfs, lfs_available = _detect_lfs(worktree)
    lfs_pulled = False
    if pull_lfs and needs_lfs:
        if not lfs_available:
            raise CommandError(
                "仓库引用了 git-lfs 文件，但当前环境未安装 git-lfs，"
                "无法实体化 LFS 内容；如需跳过请加 --no-lfs"
            )
        _run_git(["lfs", "pull"], cwd=worktree)
        lfs_pulled = True

    out_path.parent.mkdir(parents=True, exist_ok=True)
    if fmt_ok == "zip":
        count = _add_files_to_zip(out_path, worktree, files, prefix)
    else:
        count = _add_files_to_tar(out_path, worktree, files, _TAR_MODES[fmt_ok], prefix)
    return count, lfs_pulled


def archive_repo(
    repo_path: Path,
    output: Path | None = None,
    fmt: str = DEFAULT_FORMAT,
    pull_lfs: bool = True,
    arcname_prefix: str | None = None,
    ref: str | None = None,
) -> ArchiveResult:
    """将 git 仓库打包为 tar / zip 包

    :param repo_path: 仓库路径（接受工作树内任意子路径，会自动定位根）
    :param output: 输出文件路径；缺省时落到 ``<repo>/../<repo>.<fmt>``，
                   指定 ``ref`` 时为 ``<repo>/../<repo>-<sanitized_ref>.<fmt>``
    :param fmt: 打包格式，见 :data:`SUPPORTED_FORMATS`
    :param pull_lfs: 是否在打包前执行 ``git lfs pull``（仓库使用 LFS 时生效）
    :param arcname_prefix: 包内顶层目录名，缺省 = 仓库目录名
    :param ref: 要打包的分支 / tag / commit-ish；缺省 = 当前工作树。
                指定时会在临时目录中以 ``git worktree add --detach <ref>`` 签出，
                打包结束后自动清理临时 worktree

    :raises ValidationError: 路径不存在 / 不是目录 / 格式不支持 / ref 不存在
    :raises CommandError: 不在 git 工作树内 / git-lfs 不可用但仓库需要 LFS
    """
    fmt_ok = _validate_format(fmt)
    repo = _ensure_git_repo(repo_path)

    out_path = _resolve_output(repo, fmt_ok, output, ref)
    prefix = (arcname_prefix or repo.name).strip("/")
    if not prefix:
        raise ValidationError("包内顶层目录名不能为空")

    if ref is not None:
        _validate_ref(repo, ref)
        with _temp_worktree(repo, ref) as wt:
            count, lfs_pulled = _pack_worktree(wt, out_path, fmt_ok, pull_lfs, prefix)
    else:
        count, lfs_pulled = _pack_worktree(repo, out_path, fmt_ok, pull_lfs, prefix)

    return ArchiveResult(
        output_path=out_path,
        file_count=count,
        archive_size=out_path.stat().st_size,
        lfs_pulled=lfs_pulled,
        ref=ref,
    )
