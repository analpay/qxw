"""git 仓库打包服务

将一个 git 工作树打包成 tar / zip 包，并满足以下约束：

- 包内 **不含** ``.git`` 目录与任何 git 元数据
- 若仓库使用了 git-lfs，先执行 ``git lfs pull`` 让指针文件实体化为真实文件
- 仅打包被 git 跟踪的文件（``git ls-files``），自动忽略未跟踪与 .gitignore 命中的内容
- 支持 ``tar`` / ``tar.gz`` / ``tar.bz2`` / ``tar.xz`` / ``zip`` 五种格式

实现依赖外部 ``git`` 命令（必需）与 ``git-lfs``（仅当仓库引用了 LFS 时必需）。
所有 git 子进程错误统一映射为 :class:`CommandError`，参数 / 路径错误映射为
:class:`ValidationError`，便于 bin/git_cmd.py 入口统一处理。
"""

from __future__ import annotations

import subprocess
import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal

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


@dataclass(frozen=True)
class ArchiveResult:
    """打包结果元数据"""

    output_path: Path
    file_count: int
    archive_size: int
    lfs_pulled: bool


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


def _resolve_output(repo: Path, fmt: ArchiveFormat, output: Path | None) -> Path:
    if output is not None:
        return output
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


def archive_repo(
    repo_path: Path,
    output: Path | None = None,
    fmt: str = DEFAULT_FORMAT,
    pull_lfs: bool = True,
    arcname_prefix: str | None = None,
) -> ArchiveResult:
    """将 git 仓库打包为 tar / zip 包

    :param repo_path: 仓库路径（接受工作树内任意子路径，会自动定位根）
    :param output: 输出文件路径；缺省时落到 ``<repo>/../<repo>.<fmt>``
    :param fmt: 打包格式，见 :data:`SUPPORTED_FORMATS`
    :param pull_lfs: 是否在打包前执行 ``git lfs pull``（仓库使用 LFS 时生效）
    :param arcname_prefix: 包内顶层目录名，缺省 = 仓库目录名

    :raises ValidationError: 路径不存在 / 不是目录 / 格式不支持
    :raises CommandError: 不在 git 工作树内 / git-lfs 不可用但仓库需要 LFS
    """
    fmt_ok = _validate_format(fmt)
    repo = _ensure_git_repo(repo_path)
    files = _list_tracked_files(repo)
    if not files:
        raise CommandError("仓库内没有任何被 git 跟踪的文件")

    needs_lfs, lfs_available = _detect_lfs(repo)
    lfs_pulled = False
    if pull_lfs and needs_lfs:
        if not lfs_available:
            raise CommandError(
                "仓库引用了 git-lfs 文件，但当前环境未安装 git-lfs，"
                "无法实体化 LFS 内容；如需跳过请加 --no-lfs"
            )
        _run_git(["lfs", "pull"], cwd=repo)
        lfs_pulled = True

    out_path = _resolve_output(repo, fmt_ok, output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    prefix = (arcname_prefix or repo.name).strip("/")
    if not prefix:
        raise ValidationError("包内顶层目录名不能为空")

    if fmt_ok == "zip":
        count = _add_files_to_zip(out_path, repo, files, prefix)
    else:
        count = _add_files_to_tar(out_path, repo, files, _TAR_MODES[fmt_ok], prefix)

    return ArchiveResult(
        output_path=out_path,
        file_count=count,
        archive_size=out_path.stat().st_size,
        lfs_pulled=lfs_pulled,
    )
