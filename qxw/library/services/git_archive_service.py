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

import fnmatch
import re
import shutil
import subprocess
import tarfile
import tempfile
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Literal, Sequence

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

# 缺省始终排除的路径：避免下游解包后仍误以为仓库使用 LFS（已实体化的内容
# 不再需要 .gitattributes 中的 filter=lfs 指令；保留反而会让收件人困惑）
DEFAULT_EXCLUDES: tuple[str, ...] = (".gitattributes",)

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
    """打包结果元数据

    ``excluded_count`` 表示因 ``excludes`` 过滤而未写入包的跟踪文件数量
    （含默认的 ``.gitattributes``）。便于调用方在表格 / 日志中提示。
    """

    output_path: Path
    file_count: int
    archive_size: int
    lfs_pulled: bool
    ref: str | None = None
    excluded_count: int = 0


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


def _normalize_excludes(
    excludes: Sequence[str] | None,
    include_defaults: bool = True,
) -> tuple[str, ...]:
    """把传入的 exclude 列表合并默认值并做基本清洗

    - 去掉空白与首尾 ``/``，避免 ``.gitattributes/`` / ``foo/`` 与 ``foo`` 不一致
    - 反斜杠归一为正斜杠，避免 Windows 风格分隔符干扰匹配
    - 排除项中含 ``..`` 的视为非法（防止越界匹配，提示调用方）
    - 全部空白条目过滤掉，避免空字符串误命中所有路径
    """
    items: list[str] = []
    raw: list[str] = list(DEFAULT_EXCLUDES) if include_defaults else []
    if excludes:
        raw.extend(excludes)
    for item in raw:
        if item is None:
            continue
        s = str(item).strip().replace("\\", "/").strip("/")
        if not s:
            continue
        if ".." in s.split("/"):
            raise ValidationError(f"排除项含非法 .. 片段: {item}")
        items.append(s)
    # 去重保留顺序
    seen: set[str] = set()
    unique: list[str] = []
    for it in items:
        if it not in seen:
            seen.add(it)
            unique.append(it)
    return tuple(unique)


def _path_matches_exclude(rel: str, pattern: str) -> bool:
    """判断 git 跟踪路径 ``rel`` 是否命中 ``pattern``

    支持三类形态：

    1. 单段 glob（不含 ``/``，如 ``*.md`` / ``test_*.py``）：对路径的每一段
       做 :func:`fnmatch.fnmatchcase`，命中任意层级的同名段，让 ``*.md`` 能同时
       命中 ``readme.md`` 与 ``docs/sub/b.md``
    2. 多段 glob（含 ``/``，如 ``docs/*.md``）：按 ``/`` 分段，逐段 fnmatch，
       且段数必须相等。即 ``docs/*.md`` 仅命中直接子项 ``docs/a.md``，不会
       命中孙级 ``docs/sub/b.md``（避免 fnmatch 默认 ``*`` 跨过 ``/``）
    3. 非 glob：精确路径 ``a/b/c.txt`` 命中同名路径；目录前缀 ``docs`` 命中
       ``docs/...`` 下的全部文件，亦命中名字恰为 ``docs`` 的文件
    """
    rel_norm = rel.replace("\\", "/").strip("/")
    has_glob = any(c in pattern for c in ("*", "?", "["))
    if has_glob:
        if "/" in pattern:
            pat_segs = pattern.split("/")
            rel_segs = rel_norm.split("/")
            if len(pat_segs) != len(rel_segs):
                return False
            return all(fnmatch.fnmatchcase(r, p) for r, p in zip(rel_segs, pat_segs))
        for seg in rel_norm.split("/"):
            if fnmatch.fnmatchcase(seg, pattern):
                return True
        return False
    if rel_norm == pattern:
        return True
    return rel_norm.startswith(pattern + "/")


def _filter_excluded(files: Iterable[str], excludes: Sequence[str]) -> tuple[list[str], int]:
    """根据 excludes 过滤文件列表，返回 (剩余文件, 被排除数量)"""
    if not excludes:
        return list(files), 0
    kept: list[str] = []
    removed = 0
    for rel in files:
        if any(_path_matches_exclude(rel, p) for p in excludes):
            removed += 1
            continue
        kept.append(rel)
    return kept, removed


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
    excludes: Sequence[str] = (),
) -> tuple[int, bool, int]:
    """把一棵已签出的工作树打成 tar / zip

    返回 ``(file_count, lfs_pulled, excluded_count)``。``file_count`` 是真正写入
    包内的文件数，``excluded_count`` 是被 ``excludes`` 命中而未写入的数量。
    """
    files = _list_tracked_files(worktree)
    if not files:
        raise CommandError("仓库内没有任何被 git 跟踪的文件")

    files, excluded_count = _filter_excluded(files, excludes)
    if not files:
        raise CommandError(
            "排除规则过滤后没有任何可打包文件，请检查 --exclude 是否过宽"
        )

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
    return count, lfs_pulled, excluded_count


def archive_repo(
    repo_path: Path,
    output: Path | None = None,
    fmt: str = DEFAULT_FORMAT,
    pull_lfs: bool = True,
    arcname_prefix: str | None = None,
    ref: str | None = None,
    excludes: Sequence[str] | None = None,
    include_default_excludes: bool = True,
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
    :param excludes: 额外的排除项列表，可重复。支持三种写法：
                     ① 精确路径（``a/b/c.txt``）；
                     ② 目录前缀（``docs`` 命中 ``docs/...``）；
                     ③ glob（``*.md`` / ``test_*.py``）。
    :param include_default_excludes: 是否合入 :data:`DEFAULT_EXCLUDES`（默认包含
                                     ``.gitattributes``），关掉后只用调用方传入的列表

    :raises ValidationError: 路径不存在 / 不是目录 / 格式不支持 / ref 不存在 /
                             排除项含 ``..`` 越界片段
    :raises CommandError: 不在 git 工作树内 / git-lfs 不可用但仓库需要 LFS /
                          排除规则把所有文件都过滤掉
    """
    fmt_ok = _validate_format(fmt)
    repo = _ensure_git_repo(repo_path)

    out_path = _resolve_output(repo, fmt_ok, output, ref)
    prefix = (arcname_prefix or repo.name).strip("/")
    if not prefix:
        raise ValidationError("包内顶层目录名不能为空")

    exc = _normalize_excludes(excludes, include_defaults=include_default_excludes)

    if ref is not None:
        _validate_ref(repo, ref)
        with _temp_worktree(repo, ref) as wt:
            count, lfs_pulled, excluded = _pack_worktree(
                wt, out_path, fmt_ok, pull_lfs, prefix, exc
            )
    else:
        count, lfs_pulled, excluded = _pack_worktree(
            repo, out_path, fmt_ok, pull_lfs, prefix, exc
        )

    return ArchiveResult(
        output_path=out_path,
        file_count=count,
        archive_size=out_path.stat().st_size,
        lfs_pulled=lfs_pulled,
        ref=ref,
        excluded_count=excluded,
    )
