"""LLM 模型仓库文件拉取服务

实现参考 msmodeling 项目（``tensor_cast/transformers/utils.py``）的下载逻辑：

- HuggingFace 来源使用 :func:`huggingface_hub.snapshot_download`
- ModelScope 来源使用 :func:`modelscope.snapshot_download`

两套官方 SDK 自带：分片并发下载、断点续传、本地缓存、tqdm 进度条、token 鉴权
等成熟能力，比手写 urllib 流式下载稳健得多。命令行的 glob 表达式直接转发为
SDK 的 ``allow_patterns`` 参数，由 SDK 统一做匹配与下载。

公共行为：

- 接受 ``org/name`` 形式的仓库名
- 至少一个文件名 / glob 表达式（如 ``configuration_*.py``），多个时按 OR 取并集
- 默认输出目录 = ``$cwd/$org/$name``
- ``revision`` 默认值由各来源 SDK 决定（HF=main / MS=master），命令行显式指定时透传
- 网络错误统一映射为 :class:`NetworkError`，参数错误为 :class:`ValidationError`，
  下载完后未匹配到任何文件的情况为 :class:`CommandError`
- 缺少对应 SDK 时抛 :class:`CommandError`，提示用户按需安装
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Sequence

from qxw.library.base.exceptions import CommandError, NetworkError, ValidationError
from qxw.library.base.logger import get_logger

logger = get_logger("qxw.llm_fetch")

Source = Literal["huggingface", "modelscope"]
SUPPORTED_SOURCES: tuple[Source, ...] = ("huggingface", "modelscope")
DEFAULT_SOURCE: Source = "huggingface"

# org/name 容许的字符集合（与 HuggingFace / ModelScope 命名规则的交集）
_REPO_RE = re.compile(r"^[A-Za-z0-9._\-]+/[A-Za-z0-9._\-]+$")

# 当用户未指定 patterns 时启用的"跳过权重"模式：以这份列表作为
# ``ignore_patterns`` 透传给 SDK，把 config / 代码 / tokenizer / license /
# README 等仓库内"非权重张量"的文件全部拉下来，仅排除大体积的权重二进制。
# 列表与 msmodeling 项目 `tensor_cast/transformers/utils.py` 中
# ``_MODELSCOPE_WEIGHT_IGNORE_PATTERNS`` 完全一致（其函数名 ``_config_only``
# 是历史命名，实际行为同样是"非权重的所有文件"，并非仅 config.json）。
WEIGHT_IGNORE_PATTERNS: tuple[str, ...] = (
    "*.safetensors",
    "*.safetensors.index.json",
    "*.bin",
    "*.pt",
    "*.pth",
    "*.ckpt",
    "*.h5",
    "*.npz",
    "*.onnx",
    "*.gguf",
    "*.zip",
    "*.tar",
    "*.tar.gz",
)


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
    revision: str | None
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


def _validate_patterns(patterns: Sequence[str] | None) -> list[str]:
    """清洗并去重 patterns 列表

    patterns 允许整体为空（None / [] / 全空白）：上层会把空列表解释为
    "跳过权重"模式，使用 :data:`WEIGHT_IGNORE_PATTERNS` 排除权重二进制，
    其余文件（config / 代码 / tokenizer / license 等）一并拉取。
    """
    if not patterns:
        return []
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
    seen: set[str] = set()
    out: list[str] = []
    for s in cleaned:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _normalize_revision(revision: str | None) -> str | None:
    """空白 revision 视为未指定，交给 SDK 用各自的默认值（HF=main / MS=master）"""
    if revision is None:
        return None
    rev = str(revision).strip()
    return rev or None


# ============================================================
# SDK 调用
# ============================================================


def _hf_snapshot_download(
    *,
    repo_id: str,
    patterns: list[str],
    local_dir: Path,
    revision: str | None,
    token: str | None,
) -> Path:
    """通过 huggingface_hub 拉取文件到 local_dir，返回最终落盘的根目录

    ``patterns`` 非空时作为 ``allow_patterns`` 透传；空时改用
    :data:`WEIGHT_IGNORE_PATTERNS` 作为 ``ignore_patterns`` —— 与 msmodeling
    "跳过权重、拉取其余所有文件"的规则一致。
    """
    try:
        from huggingface_hub import snapshot_download
    except ImportError as e:
        raise CommandError(
            "缺少依赖 huggingface_hub，请先安装：pip install huggingface_hub"
        ) from e

    try:
        from huggingface_hub.errors import (
            HfHubHTTPError,
            RepositoryNotFoundError,
            RevisionNotFoundError,
        )
    except ImportError:
        # 兼容旧版本：errors 模块可能在 utils 下
        try:
            from huggingface_hub.utils import (
                HfHubHTTPError,
                RepositoryNotFoundError,
                RevisionNotFoundError,
            )
        except ImportError:
            HfHubHTTPError = Exception  # type: ignore[assignment,misc]
            RepositoryNotFoundError = Exception  # type: ignore[assignment,misc]
            RevisionNotFoundError = Exception  # type: ignore[assignment,misc]

    sdk_kwargs: dict[str, object] = {
        "repo_id": repo_id,
        "revision": revision,
        "local_dir": str(local_dir),
        "token": token,
    }
    if patterns:
        sdk_kwargs["allow_patterns"] = patterns
    else:
        sdk_kwargs["ignore_patterns"] = list(WEIGHT_IGNORE_PATTERNS)

    try:
        path = snapshot_download(**sdk_kwargs)
    except RepositoryNotFoundError as e:
        raise CommandError(f"HuggingFace 仓库不存在: {repo_id}") from e
    except RevisionNotFoundError as e:
        raise CommandError(f"HuggingFace 仓库 revision 不存在: {repo_id}@{revision}") from e
    except HfHubHTTPError as e:
        raise NetworkError(f"HuggingFace 下载失败: {e}") from e
    except OSError as e:
        raise CommandError(f"HuggingFace 写入文件失败: {e}") from e
    return Path(path)


def _ms_snapshot_download(
    *,
    model_id: str,
    patterns: list[str],
    local_dir: Path,
    revision: str | None,
    token: str | None,
) -> Path:
    """通过 modelscope 拉取文件到 local_dir，返回最终落盘的根目录

    - ``patterns`` 非空：透传为 ``allow_patterns`` / ``allow_file_pattern``
      （旧版 ModelScope 只识别后者，:class:`TypeError` 时回退）
    - ``patterns`` 为空：透传为 ``ignore_patterns`` / ``ignore_file_pattern``
      并使用 :data:`WEIGHT_IGNORE_PATTERNS`，等价于 msmodeling 的
      ``_modelscope_snapshot_config_only`` 行为：拉取仓库内除权重之外的
      全部文件（config / 代码 / tokenizer / license / README 等）
    """
    try:
        from modelscope import snapshot_download
    except ImportError as e:
        raise CommandError(
            "缺少依赖 modelscope，请先安装：pip install modelscope"
        ) from e

    base_kwargs: dict[str, object] = {
        "model_id": model_id,
        "local_dir": str(local_dir),
    }
    if revision is not None:
        base_kwargs["revision"] = revision
    if token is not None:
        base_kwargs["token"] = token

    if patterns:
        new_key, legacy_key = "allow_patterns", "allow_file_pattern"
        value: list[str] = patterns
    else:
        new_key, legacy_key = "ignore_patterns", "ignore_file_pattern"
        value = list(WEIGHT_IGNORE_PATTERNS)

    try:
        try:
            path = snapshot_download(**{new_key: value}, **base_kwargs)
        except TypeError:
            path = snapshot_download(**{legacy_key: value}, **base_kwargs)
    except OSError as e:
        raise CommandError(f"ModelScope 写入文件失败: {e}") from e
    except Exception as e:
        # ModelScope 自定义异常体系不稳定，按异常类名兜底归类
        cls_name = type(e).__name__
        if "NotExist" in cls_name or "NotFound" in cls_name:
            raise CommandError(f"ModelScope 仓库或 revision 不存在: {model_id}@{revision}") from e
        raise NetworkError(f"ModelScope 下载失败: {e}") from e
    return Path(path)


# ============================================================
# 下载结果收集
# ============================================================


def _collect_downloaded_files(snapshot_root: Path, output_dir: Path) -> list[FetchedFile]:
    """枚举本次落盘后的真实文件清单

    ``snapshot_download`` 可能返回 ``cache_dir`` 下的快照路径而不是用户指定的
    ``local_dir``（旧版本 / 特定缓存策略下会出现）。这里以快照路径为准枚举，
    最终把 ``local_path`` 用 ``output_dir`` 与 ``snapshot_root`` 中较窄的那个
    呈现给用户，避免给出 ``~/.cache`` 下让人困惑的路径。
    """
    if not snapshot_root.exists() or not snapshot_root.is_dir():
        return []

    files: list[FetchedFile] = []
    for p in sorted(snapshot_root.rglob("*")):
        if not p.is_file():
            continue
        # 隐藏的 SDK 内部文件（``.cache`` / ``.huggingface`` / ``.locks`` 等）一律跳过
        rel_parts = p.relative_to(snapshot_root).parts
        if any(part.startswith(".") for part in rel_parts):
            continue
        rel = "/".join(rel_parts)
        try:
            size = p.stat().st_size
        except OSError:
            size = 0
        files.append(FetchedFile(repo_path=rel, local_path=p, size=size))
    return files


# ============================================================
# 公共入口
# ============================================================


def fetch_files(
    repo: str,
    patterns: Sequence[str] | None = None,
    *,
    source: str = DEFAULT_SOURCE,
    revision: str | None = None,
    output: Path | None = None,
    token: str | None = None,
) -> FetchResult:
    """从 HuggingFace / ModelScope 拉取仓库内文件

    内部委托给官方 SDK 的 ``snapshot_download``：
    HuggingFace -> :mod:`huggingface_hub`，ModelScope -> :mod:`modelscope`。

    :param repo: 仓库名，``org/name`` 形式
    :param patterns: 文件名 / glob 表达式列表，可选。
                     - 非空：作为 ``allow_patterns`` 透传，多个按 OR 取并集
                     - 空 / None：进入"跳过权重"模式，使用
                       :data:`WEIGHT_IGNORE_PATTERNS` 作为 ``ignore_patterns``，
                       拉取仓库内除权重二进制之外的全部文件（config / 代码 /
                       tokenizer / license / README 等），与 msmodeling 项目的
                       ``_modelscope_snapshot_config_only`` 规则保持一致
    :param source: 来源，``huggingface``（默认）或 ``modelscope``
    :param revision: 分支 / tag / commit；缺省时由各 SDK 用其默认值
                     （HF=``main`` / MS=``master``）
    :param output: 输出目录；缺省为 ``$cwd/$org/$name``
    :param token: 访问令牌（私有仓库时使用）

    :raises ValidationError: 仓库名 / 来源 / 表达式 不合法
    :raises CommandError: 缺少对应 SDK / 仓库或 revision 不存在 / 下载完成后
                          按规则过滤后 0 个文件
    :raises NetworkError: SDK 内部 HTTP 请求失败
    """
    org, name = _validate_repo(repo)
    src = _validate_source(source)
    pats = _validate_patterns(patterns)
    rev = _normalize_revision(revision)

    out_dir = Path(output) if output is not None else Path.cwd() / org / name
    out_dir.mkdir(parents=True, exist_ok=True)

    repo_id = f"{org}/{name}"
    mode = "allow=" + ",".join(pats) if pats else "skip-weights (ignore weight binaries)"
    logger.info("开始拉取 %s @ %s [%s] -> %s", repo_id, rev or "(default)", mode, out_dir)

    if src == "huggingface":
        snapshot_root = _hf_snapshot_download(
            repo_id=repo_id,
            patterns=pats,
            local_dir=out_dir,
            revision=rev,
            token=token,
        )
    else:
        snapshot_root = _ms_snapshot_download(
            model_id=repo_id,
            patterns=pats,
            local_dir=out_dir,
            revision=rev,
            token=token,
        )

    files = _collect_downloaded_files(snapshot_root, out_dir)
    if not files:
        if pats:
            raise CommandError(
                f"按表达式过滤后未下载到任何文件: {', '.join(pats)}"
                f"（请检查仓库 {repo_id} 是否包含目标文件）"
            )
        raise CommandError(
            f"跳过权重模式下未下载到任何文件（仓库 {repo_id} 可能只含权重二进制文件）"
        )

    return FetchResult(
        repo=repo_id,
        source=src,
        revision=rev,
        output_dir=snapshot_root,
        files=tuple(files),
    )
