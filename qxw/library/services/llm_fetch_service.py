"""LLM 模型仓库文件拉取服务

支持从 HuggingFace / ModelScope 拉取仓库内的文件：

- 接受 ``org/name`` 形式的仓库名
- 接受一个或多个文件名 / glob 表达式（如 ``configuration_*.py``）
- 自动通过仓库 API 列出全部文件清单，再用 :mod:`fnmatch` 做表达式匹配
- 默认输出目录为当前目录下的 ``$org/$name``，保留仓库内相对路径结构
- 下载使用 ``.part`` 临时文件 + 原子重命名，避免中断时残留半成品
- 网络错误统一映射为 :class:`NetworkError`，参数错误为 :class:`ValidationError`，
  仓库内容错误（无文件 / 表达式未命中等）为 :class:`CommandError`

实现仅依赖标准库 ``urllib``，不引入额外 SDK，避免给整体安装链路增加体积。
"""

from __future__ import annotations

import fnmatch
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Sequence

from qxw.library.base.exceptions import CommandError, NetworkError, ValidationError
from qxw.library.base.logger import get_logger

logger = get_logger("qxw.llm_fetch")

Source = Literal["huggingface", "modelscope"]
SUPPORTED_SOURCES: tuple[Source, ...] = ("huggingface", "modelscope")
DEFAULT_SOURCE: Source = "huggingface"
DEFAULT_REVISION: str = "main"

# org/name 容许的字符集合（与 HuggingFace / ModelScope 命名规则的交集）
_REPO_RE = re.compile(r"^[A-Za-z0-9._\-]+/[A-Za-z0-9._\-]+$")
_HF_BASE = "https://huggingface.co"
_MS_BASE = "https://modelscope.cn"
_CHUNK = 1024 * 64
_USER_AGENT = "qxw-llm-fetch/1.0"

# 进度回调签名: (已写入字节, 总字节)，总字节为 0 表示服务端未返回 Content-Length
ProgressCallback = Callable[[int, int], None]

# 文件级回调: (相对路径, 当前序号 1-based, 总数)
FileLifecycleCallback = Callable[[str, int, int], None]


@dataclass(frozen=True)
class FetchedFile:
    """单个已下载文件的元数据"""

    repo_path: str
    local_path: Path
    size: int


@dataclass(frozen=True)
class FetchResult:
    """fetch 调用结果"""

    repo: str
    source: Source
    revision: str
    output_dir: Path
    files: tuple[FetchedFile, ...]

    @property
    def total_size(self) -> int:
        return sum(f.size for f in self.files)


# ============================================================
# 入参校验
# ============================================================


def _validate_repo(repo: str) -> tuple[str, str]:
    if repo is None or not str(repo).strip():
        raise ValidationError("仓库名不能为空")
    repo = str(repo).strip()
    if not _REPO_RE.match(repo):
        raise ValidationError(f"仓库名格式非法（应为 org/name）: {repo}")
    org, name = repo.split("/", 1)
    return org, name


def _validate_source(source: str) -> Source:
    if source not in SUPPORTED_SOURCES:
        raise ValidationError(
            f"不支持的来源: {source}（支持: {', '.join(SUPPORTED_SOURCES)})"
        )
    return source  # type: ignore[return-value]


def _validate_patterns(patterns: Sequence[str] | None) -> tuple[str, ...]:
    if not patterns:
        raise ValidationError("至少需要指定一个文件名或表达式")
    cleaned: list[str] = []
    for p in patterns:
        if p is None:
            continue
        s = str(p).strip().replace("\\", "/").lstrip("/")
        if not s:
            continue
        if ".." in s.split("/"):
            raise ValidationError(f"文件名含非法 .. 片段: {p}")
        cleaned.append(s)
    if not cleaned:
        raise ValidationError("文件名列表全部为空")
    seen: set[str] = set()
    out: list[str] = []
    for s in cleaned:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return tuple(out)


def _validate_revision(revision: str | None) -> str:
    rev = (revision or "").strip()
    if not rev:
        raise ValidationError("revision 不能为空")
    return rev


# ============================================================
# HTTP 工具
# ============================================================


def _build_request(url: str, token: str | None) -> urllib.request.Request:
    headers = {"User-Agent": _USER_AGENT, "Accept": "*/*"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return urllib.request.Request(url, headers=headers)


def _http_get_json(url: str, *, token: str | None, timeout: float) -> object:
    """GET 一个 JSON 接口，把 urllib 的多种异常归一化为 NetworkError"""
    req = _build_request(url, token)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
    except urllib.error.HTTPError as e:
        raise NetworkError(f"GET {url} 失败: HTTP {e.code} {e.reason}") from e
    except urllib.error.URLError as e:
        raise NetworkError(f"GET {url} 失败: {e.reason}") from e
    except TimeoutError as e:
        raise NetworkError(f"GET {url} 超时") from e
    try:
        return json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        raise NetworkError(f"GET {url} 返回非 JSON 数据") from e


# ============================================================
# 仓库文件清单
# ============================================================


def _list_huggingface(org: str, name: str, revision: str, token: str | None, timeout: float) -> list[str]:
    url = (
        f"{_HF_BASE}/api/models/{org}/{name}/tree/"
        f"{urllib.parse.quote(revision, safe='')}?recursive=true"
    )
    data = _http_get_json(url, token=token, timeout=timeout)
    if not isinstance(data, list):
        raise NetworkError(f"HuggingFace 文件清单结构非预期: {url}")
    files: list[str] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        if item.get("type") != "file":
            continue
        path = item.get("path")
        if isinstance(path, str) and path:
            files.append(path)
    return files


def _list_modelscope(org: str, name: str, revision: str, token: str | None, timeout: float) -> list[str]:
    url = (
        f"{_MS_BASE}/api/v1/models/{org}/{name}/repo/files"
        f"?Revision={urllib.parse.quote(revision, safe='')}&Recursive=True"
    )
    data = _http_get_json(url, token=token, timeout=timeout)
    if not isinstance(data, dict):
        raise NetworkError(f"ModelScope 文件清单结构非预期: {url}")
    code = data.get("Code")
    if code not in (0, None, "0"):
        msg = data.get("Message") or f"Code={code}"
        raise NetworkError(f"ModelScope API 错误: {msg}")
    container = data.get("Data") if isinstance(data.get("Data"), dict) else data
    raw_files = container.get("Files") if isinstance(container, dict) else None
    if not isinstance(raw_files, list):
        raise NetworkError(f"ModelScope 文件清单结构非预期: {url}")
    files: list[str] = []
    for item in raw_files:
        if not isinstance(item, dict):
            continue
        ftype = item.get("Type") or item.get("type")
        # ModelScope 用 "blob" 表示文件，"tree" 表示目录
        if ftype not in ("blob", "file"):
            continue
        path = item.get("Path") or item.get("path")
        if isinstance(path, str) and path:
            files.append(path)
    return files


def _list_repo_files(
    source: Source,
    org: str,
    name: str,
    revision: str,
    token: str | None,
    timeout: float,
) -> list[str]:
    if source == "huggingface":
        return _list_huggingface(org, name, revision, token, timeout)
    return _list_modelscope(org, name, revision, token, timeout)


# ============================================================
# 表达式匹配
# ============================================================


def _file_matches_pattern(file_path: str, pattern: str) -> bool:
    """判断文件路径是否命中模式

    - 单段 glob（``*.py``）：对路径任意一段 fnmatch，命中任意层级
    - 多段 glob（``configs/*.py``）：按 ``/`` 分段且段数相等
    - 非 glob：精确等值
    """
    has_glob = any(c in pattern for c in ("*", "?", "["))
    if not has_glob:
        return file_path == pattern
    if "/" in pattern:
        pat_segs = pattern.split("/")
        f_segs = file_path.split("/")
        if len(pat_segs) != len(f_segs):
            return False
        return all(fnmatch.fnmatchcase(s, p) for s, p in zip(f_segs, pat_segs))
    for seg in file_path.split("/"):
        if fnmatch.fnmatchcase(seg, pattern):
            return True
    return False


def _match_patterns(files: Sequence[str], patterns: Sequence[str]) -> list[str]:
    """按表达式列表把 files 匹配为最终目标列表

    - 任意一个表达式没匹配到，整个调用以 :class:`CommandError` 失败
      （避免静默忽略用户意图）
    - 多个表达式可能命中重叠文件，结果会去重并保留首次出现的顺序
    """
    matched: list[str] = []
    seen: set[str] = set()
    unmatched: list[str] = []
    for pat in patterns:
        hits = [f for f in files if _file_matches_pattern(f, pat)]
        if not hits:
            unmatched.append(pat)
            continue
        for h in hits:
            if h not in seen:
                seen.add(h)
                matched.append(h)
    if unmatched:
        raise CommandError(
            f"以下表达式未匹配到任何文件: {', '.join(unmatched)}"
        )
    return matched


# ============================================================
# 单文件下载
# ============================================================


def _build_download_url(
    source: Source,
    org: str,
    name: str,
    revision: str,
    file_path: str,
) -> str:
    quoted_rev = urllib.parse.quote(revision, safe="")
    if source == "huggingface":
        quoted_path = urllib.parse.quote(file_path, safe="/")
        return f"{_HF_BASE}/{org}/{name}/resolve/{quoted_rev}/{quoted_path}"
    return (
        f"{_MS_BASE}/api/v1/models/{org}/{name}/repo"
        f"?Revision={quoted_rev}&FilePath={urllib.parse.quote(file_path, safe='')}"
    )


def _download_one(
    url: str,
    dest: Path,
    *,
    token: str | None,
    timeout: float,
    progress_cb: ProgressCallback | None,
) -> int:
    req = _build_request(url, token)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            total_hdr = resp.headers.get("Content-Length") or "0"
            try:
                total = int(total_hdr)
            except ValueError:
                total = 0
            written = 0
            with tmp.open("wb") as f:
                while True:
                    chunk = resp.read(_CHUNK)
                    if not chunk:
                        break
                    f.write(chunk)
                    written += len(chunk)
                    if progress_cb is not None:
                        progress_cb(written, total)
        tmp.replace(dest)
        return written
    except urllib.error.HTTPError as e:
        _safe_unlink(tmp)
        raise NetworkError(f"下载 {url} 失败: HTTP {e.code} {e.reason}") from e
    except urllib.error.URLError as e:
        _safe_unlink(tmp)
        raise NetworkError(f"下载 {url} 失败: {e.reason}") from e
    except TimeoutError as e:
        _safe_unlink(tmp)
        raise NetworkError(f"下载 {url} 超时") from e
    except OSError as e:
        _safe_unlink(tmp)
        raise CommandError(f"写入文件失败 {dest}: {e}") from e


def _safe_unlink(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError as e:
        logger.warning("清理临时文件失败 %s: %s", path, e)


# ============================================================
# 公共入口
# ============================================================


def fetch_files(
    repo: str,
    patterns: Sequence[str],
    *,
    source: str = DEFAULT_SOURCE,
    revision: str = DEFAULT_REVISION,
    output: Path | None = None,
    token: str | None = None,
    timeout: float = 60.0,
    progress_cb: ProgressCallback | None = None,
    on_file_start: FileLifecycleCallback | None = None,
    on_file_done: FileLifecycleCallback | None = None,
) -> FetchResult:
    """从 HuggingFace / ModelScope 拉取仓库内文件

    :param repo: 仓库名，``org/name`` 形式
    :param patterns: 文件名 / glob 表达式列表，至少一个
    :param source: 来源，``huggingface`` 或 ``modelscope``
    :param revision: 分支 / tag / commit，默认 ``main``
    :param output: 输出目录；缺省为 ``$cwd/$org/$name``
    :param token: 访问令牌（私有仓库时使用）
    :param timeout: 单次 HTTP 请求超时秒数
    :param progress_cb: 单文件下载进度回调 ``(written, total)``
    :param on_file_start: 每个文件开始下载前调用 ``(rel, idx, total)``
    :param on_file_done: 每个文件下载完成后调用 ``(rel, idx, total)``

    :raises ValidationError: 仓库名 / 来源 / 表达式 / revision 不合法
    :raises NetworkError: 列表 / 下载 HTTP 失败或超时
    :raises CommandError: 仓库无文件、表达式未命中、写入失败
    """
    org, name = _validate_repo(repo)
    src = _validate_source(source)
    rev = _validate_revision(revision)
    pats = _validate_patterns(patterns)

    out_dir = Path(output) if output is not None else Path.cwd() / org / name
    out_dir.mkdir(parents=True, exist_ok=True)

    all_files = _list_repo_files(src, org, name, rev, token, timeout)
    if not all_files:
        raise CommandError(f"仓库 {repo} (revision={rev}) 内没有可拉取的文件")

    targets = _match_patterns(all_files, pats)
    total = len(targets)

    fetched: list[FetchedFile] = []
    for idx, rel in enumerate(targets, 1):
        if on_file_start is not None:
            on_file_start(rel, idx, total)
        url = _build_download_url(src, org, name, rev, rel)
        dest = out_dir / rel
        size = _download_one(url, dest, token=token, timeout=timeout, progress_cb=progress_cb)
        fetched.append(FetchedFile(repo_path=rel, local_path=dest, size=size))
        logger.info("已下载 %s -> %s (%d bytes)", rel, dest, size)
        if on_file_done is not None:
            on_file_done(rel, idx, total)

    return FetchResult(
        repo=f"{org}/{name}",
        source=src,
        revision=rev,
        output_dir=out_dir,
        files=tuple(fetched),
    )
