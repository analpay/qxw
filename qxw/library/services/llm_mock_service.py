"""OpenAI 兼容的 Mock LLM Web 服务

提供一个本地 HTTP 服务，模拟 OpenAI Chat Completions / Responses 接口的行为，
不调用任何真实模型，仅按可配置的 ``TTFT`` / ``TPOT`` 节奏返回预置的占位 token。

用途：
    - 客户端联调（验证 SSE 解析、超时处理、断流恢复）
    - 压测代理 / 网关
    - CI 环境下提供稳定的"假"上游

支持的接口：
    - ``POST /v1/chat/completions``  / ``POST /api/v1/chat/completions``
    - ``POST /v1/responses``         / ``POST /api/v1/responses``
    - ``GET  /v1/models``            / ``GET  /api/v1/models``
    - ``GET  /health``

时间模型：
    - ``ttft_ms``: 第一个 token 到达前的固定延迟（time-to-first-token）
    - ``tpot_ms``: 相邻两个 token 之间的延迟（time-per-output-token）
    - ``chunk_min`` / ``chunk_max``: 单个 SSE 事件包含的 token 个数，在 [min, max]
      区间随机均匀采样（chunk_min == chunk_max 时为固定大小）。无论怎么分块，**响应
      总耗时保持等于 `TTFT + (N - 1) * TPOT`**——分块只影响"事件粒度"，不影响节奏。
    - 流式请求严格按上述节奏 emit 事件
    - 非流式请求一次性 ``sleep(ttft + (n - 1) * tpot)`` 后整体返回

按请求路由：
    通过配置文件 ``rules`` 段可按 ``model`` / 消息内容 / 请求头匹配，命中即覆盖
    默认 profile 的部分字段（任一字段未指定则继承 default）。匹配顺序按 ``rules``
    定义顺序，首条命中即返回；无规则命中时使用 ``default`` profile。

注意：本模块只依赖 Python 标准库 + pydantic，避免引入新依赖。
"""

from __future__ import annotations

import json
import random
import re
import secrets
import time
from collections.abc import Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic import ValidationError as PydanticValidationError

from qxw import __version__
from qxw.library.base.exceptions import ValidationError
from qxw.library.base.logger import get_logger

logger = get_logger("qxw.llm_mock")


# ============================================================
# 配置
# ============================================================


# Mock 输出使用的 token 池（中英文混排，便于直观核对）
_MOCK_TOKEN_POOL: tuple[str, ...] = (
    "Lorem ",
    "ipsum ",
    "dolor ",
    "sit ",
    "amet, ",
    "consectetur ",
    "adipiscing ",
    "elit. ",
    "这是 ",
    "一个 ",
    "由 ",
    "qxw-llm ",
    "mock ",
    "返回的 ",
    "模拟 ",
    "响应。 ",
)


class MockResponseProfile(BaseModel):
    """单次响应的节奏配置（被 default + 规则覆盖共同决定）"""

    ttft_ms: int = Field(default=2000, description="首 token 延迟（毫秒）", ge=0, le=600_000)
    tpot_ms: int = Field(default=15, description="相邻 token 间延迟（毫秒）", ge=0, le=600_000)
    tokens: int = Field(default=64, description="单次响应的 token 数", ge=1, le=100_000)
    chunk_min: int = Field(default=1, description="单个 SSE 事件包含的最少 token 数", ge=1, le=100_000)
    chunk_max: int = Field(default=1, description="单个 SSE 事件包含的最多 token 数", ge=1, le=100_000)

    @model_validator(mode="after")
    def _check_chunk_range(self) -> "MockResponseProfile":
        if self.chunk_min > self.chunk_max:
            raise ValueError(f"chunk_min({self.chunk_min}) 不能大于 chunk_max({self.chunk_max})")
        return self


class MockRuleMatch(BaseModel):
    """规则匹配条件——所有非空字段做 AND；至少要有一个条件，否则报错"""

    model: str | None = Field(default=None, description="精确匹配 request.model")
    content_contains: str | None = Field(default=None, description="用户消息文本子串包含")
    content_regex: str | None = Field(default=None, description="用户消息文本正则匹配（re.search）")
    header_name: str | None = Field(default=None, description="请求头名（大小写不敏感）")
    header_value: str | None = Field(
        default=None,
        description="请求头值（与 header_name 一起；省略则只要求该 header 存在且非空）",
    )

    @field_validator("content_regex")
    @classmethod
    def _validate_regex(cls, v: str | None) -> str | None:
        if v is None:
            return v
        try:
            re.compile(v)
        except re.error as e:
            raise ValueError(f"content_regex 不是合法正则: {e}") from e
        return v

    @model_validator(mode="after")
    def _require_any(self) -> "MockRuleMatch":
        if not any(
            [self.model, self.content_contains, self.content_regex, self.header_name]
        ):
            raise ValueError("match 至少需要一个非空字段（model / content_contains / content_regex / header_name）")
        if self.header_value is not None and not self.header_name:
            raise ValueError("header_value 必须与 header_name 一起使用")
        return self


class MockRule(BaseModel):
    """单条响应规则：命中即用本规则的 profile 字段覆盖 default（未指定则继承）"""

    name: str = Field(default="", description="规则名（用于日志，可省略）")
    match: MockRuleMatch
    ttft_ms: int | None = Field(default=None, ge=0, le=600_000)
    tpot_ms: int | None = Field(default=None, ge=0, le=600_000)
    tokens: int | None = Field(default=None, ge=1, le=100_000)
    chunk_min: int | None = Field(default=None, ge=1, le=100_000)
    chunk_max: int | None = Field(default=None, ge=1, le=100_000)

    @model_validator(mode="after")
    def _check_chunk_range(self) -> "MockRule":
        if (
            self.chunk_min is not None
            and self.chunk_max is not None
            and self.chunk_min > self.chunk_max
        ):
            raise ValueError(
                f"规则 '{self.name or '<unnamed>'}': chunk_min({self.chunk_min}) 不能大于 chunk_max({self.chunk_max})"
            )
        return self

    def apply_to(self, base: "MockResponseProfile") -> "MockResponseProfile":
        """把本规则的非 None 字段覆盖到 base profile 上，返回新的 profile"""
        return MockResponseProfile(
            ttft_ms=self.ttft_ms if self.ttft_ms is not None else base.ttft_ms,
            tpot_ms=self.tpot_ms if self.tpot_ms is not None else base.tpot_ms,
            tokens=self.tokens if self.tokens is not None else base.tokens,
            chunk_min=self.chunk_min if self.chunk_min is not None else base.chunk_min,
            chunk_max=self.chunk_max if self.chunk_max is not None else base.chunk_max,
        )


class MockServerConfig(BaseModel):
    """Mock LLM 服务配置

    保留 ``ttft_ms`` / ``tpot_ms`` / ``tokens`` 等顶层字段以兼容旧 API；它们组成
    "默认 profile"，可被 ``rules`` 中按请求命中的规则覆盖。
    """

    host: str = Field(default="127.0.0.1", description="监听地址")
    port: int = Field(default=8080, description="监听端口", ge=0, le=65535)
    model: str = Field(default="qxw-mock-1", description="返回的 model 字段值")
    # —— 默认 profile 的扁平字段（向后兼容） ——
    ttft_ms: int = Field(default=2000, description="首 token 延迟（毫秒）", ge=0, le=600_000)
    tpot_ms: int = Field(default=15, description="相邻 token 间延迟（毫秒）", ge=0, le=600_000)
    tokens: int = Field(default=64, description="单次响应的 token 数", ge=1, le=100_000)
    chunk_min: int = Field(default=1, description="SSE 事件含 token 数下限", ge=1, le=100_000)
    chunk_max: int = Field(default=1, description="SSE 事件含 token 数上限", ge=1, le=100_000)
    # —— 按请求路由的规则 ——
    rules: list[MockRule] = Field(default_factory=list, description="按请求路由的规则列表，命中则覆盖默认 profile")

    @field_validator("host")
    @classmethod
    def _validate_host(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("host 不能为空")
        return v

    @model_validator(mode="after")
    def _check_chunk_range(self) -> "MockServerConfig":
        if self.chunk_min > self.chunk_max:
            raise ValueError(f"chunk_min({self.chunk_min}) 不能大于 chunk_max({self.chunk_max})")
        return self

    @property
    def default_profile(self) -> MockResponseProfile:
        """把扁平字段聚合为 :class:`MockResponseProfile`"""
        return MockResponseProfile(
            ttft_ms=self.ttft_ms,
            tpot_ms=self.tpot_ms,
            tokens=self.tokens,
            chunk_min=self.chunk_min,
            chunk_max=self.chunk_max,
        )

    def resolve_profile(
        self, body: dict[str, Any], headers: Mapping[str, str]
    ) -> tuple[MockResponseProfile, str | None]:
        """根据请求体 + 请求头匹配规则，返回 (profile, 命中规则名 | None)"""
        for rule in self.rules:
            if _match_rule(rule, body, headers):
                return rule.apply_to(self.default_profile), rule.name or "<unnamed>"
        return self.default_profile, None


# 项目内置示例文件路径（用于 `qxw-llm mock-config` 输出）
EXAMPLE_CONFIG_PATH: Path = (
    Path(__file__).resolve().parent.parent.parent / "config" / "mock_profile.json.example"
)


def read_example_config() -> str:
    """读取项目内置的 mock 配置示例文件文本

    :raises ValidationError: 模板文件意外缺失（一般是打包问题）
    """
    if not EXAMPLE_CONFIG_PATH.exists():
        raise ValidationError(f"内置示例配置文件不存在: {EXAMPLE_CONFIG_PATH}")
    try:
        return EXAMPLE_CONFIG_PATH.read_text(encoding="utf-8")
    except OSError as e:
        raise ValidationError(f"读取内置示例配置文件失败: {e}") from e


def load_config_from_file(path: Path) -> MockServerConfig:
    """从 JSON 文件加载 :class:`MockServerConfig`

    支持的结构（``host`` / ``port`` / ``model`` 为可选；``default`` 与 ``rules`` 为可选）::

        {
          "host": "127.0.0.1",
          "port": 8080,
          "model": "qxw-mock-1",
          "default": {
            "ttft_ms": 2000, "tpot_ms": 15, "tokens": 64,
            "chunk_min": 1, "chunk_max": 1
          },
          "rules": [
            {
              "name": "slow-model",
              "match": {"model": "slow-gpt"},
              "ttft_ms": 5000, "tokens": 200
            }
          ]
        }

    :raises ValidationError: 文件不存在 / JSON 非法 / schema 校验失败
    """
    if not isinstance(path, Path):
        path = Path(path)
    if not path.exists():
        raise ValidationError(f"配置文件不存在: {path}")
    if not path.is_file():
        raise ValidationError(f"配置文件路径不是文件: {path}")
    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise ValidationError(f"读取配置文件失败: {e}") from e
    try:
        raw = json.loads(raw_text)
    except json.JSONDecodeError as e:
        raise ValidationError(f"配置文件不是合法 JSON: {e}") from e
    if not isinstance(raw, dict):
        raise ValidationError("配置文件根必须是 JSON 对象")

    init_kwargs: dict[str, Any] = {}
    for k in ("host", "port", "model"):
        if k in raw:
            init_kwargs[k] = raw[k]

    defaults = raw.get("default", {})
    if not isinstance(defaults, dict):
        raise ValidationError("配置文件 'default' 必须是 JSON 对象")
    for k in ("ttft_ms", "tpot_ms", "tokens", "chunk_min", "chunk_max"):
        if k in defaults:
            init_kwargs[k] = defaults[k]

    if "rules" in raw:
        if not isinstance(raw["rules"], list):
            raise ValidationError("配置文件 'rules' 必须是 JSON 数组")
        init_kwargs["rules"] = raw["rules"]

    try:
        return MockServerConfig.model_validate(init_kwargs)
    except PydanticValidationError as e:
        raise ValidationError(f"配置文件校验失败: {e}") from e


# ============================================================
# 工具函数
# ============================================================


def _generate_tokens(n: int) -> list[str]:
    """按 token 池循环生成 ``n`` 个 mock token"""
    pool = _MOCK_TOKEN_POOL
    return [pool[i % len(pool)] for i in range(n)]


def _sleep_ms(ms: int) -> None:
    """毫秒级 sleep；0 / 负数直接跳过"""
    if ms > 0:
        time.sleep(ms / 1000.0)


def _new_chat_id() -> str:
    return f"chatcmpl-{secrets.token_hex(12)}"


def _new_response_id() -> str:
    return f"resp_{secrets.token_hex(12)}"


def _new_message_id() -> str:
    return f"msg_{secrets.token_hex(12)}"


def _extract_match_text(body: dict[str, Any]) -> str:
    """从请求体抽取"用户给出的文本"，用于 content_contains / content_regex 匹配

    覆盖：
    - chat completions: 取 ``messages[*].content``（字符串）或多模态 part 里
      ``{"type": "text", "text": "..."}`` 的 text 字段；不会把 role 等元字段计入。
    - responses API: ``input`` 字段。字符串原样取；列表 / 字典递归取 ``text`` 字段。
    - 兜底：``prompt`` 字段（字符串）。
    """

    def _flatten_content_part(obj: Any) -> list[str]:
        if isinstance(obj, str):
            return [obj]
        if isinstance(obj, list):
            out: list[str] = []
            for x in obj:
                out.extend(_flatten_content_part(x))
            return out
        if isinstance(obj, dict):
            out: list[str] = []
            # 优先取 text 字段（OpenAI 多模态 part 的 text）
            txt = obj.get("text")
            if isinstance(txt, str):
                out.append(txt)
            # 递归下钻 content 字段（responses API 的 input item 形态）
            inner = obj.get("content")
            if inner is not None:
                out.extend(_flatten_content_part(inner))
            return out
        return []

    parts: list[str] = []
    messages = body.get("messages")
    if isinstance(messages, list):
        for msg in messages:
            if isinstance(msg, dict):
                parts.extend(_flatten_content_part(msg.get("content")))
    if "input" in body:
        parts.extend(_flatten_content_part(body["input"]))
    prompt = body.get("prompt")
    if isinstance(prompt, str):
        parts.append(prompt)
    return "\n".join(p for p in parts if p)


def _match_rule(
    rule: MockRule, body: dict[str, Any], headers: Mapping[str, str]
) -> bool:
    """判定单条规则是否命中。多个非空条件做 AND，全部命中才返回 True。"""
    m = rule.match
    if m.model is not None:
        if str(body.get("model", "")) != m.model:
            return False
    if m.content_contains is not None or m.content_regex is not None:
        text = _extract_match_text(body)
        if m.content_contains is not None and m.content_contains not in text:
            return False
        if m.content_regex is not None and not re.search(m.content_regex, text):
            return False
    if m.header_name is not None:
        # 大小写不敏感地查 header
        actual = _get_header_ci(headers, m.header_name)
        if actual is None or actual == "":
            return False
        if m.header_value is not None and actual != m.header_value:
            return False
    return True


def _get_header_ci(headers: Mapping[str, str], name: str) -> str | None:
    """大小写不敏感地从 headers 取值"""
    lower = name.lower()
    for k, v in headers.items():
        if k.lower() == lower:
            return v
    return None


def _group_into_chunks(
    tokens: list[str],
    chunk_min: int,
    chunk_max: int,
    *,
    rng: random.Random | None = None,
) -> list[list[str]]:
    """按 ``[chunk_min, chunk_max]`` 区间均匀随机分组

    - chunk_min == chunk_max 时退化为定长分组
    - 最后一组允许短于 chunk_min（自然剩余）
    - 空 token 列表 -> 空结果
    """
    if not tokens:
        return []
    if chunk_min < 1:
        raise ValueError("chunk_min 必须 >= 1")
    if chunk_min > chunk_max:
        raise ValueError("chunk_min 不能大于 chunk_max")
    use_rng = rng if rng is not None else random
    groups: list[list[str]] = []
    i = 0
    n = len(tokens)
    while i < n:
        if chunk_min == chunk_max:
            size = chunk_min
        else:
            size = use_rng.randint(chunk_min, chunk_max)
        size = min(size, n - i)
        groups.append(tokens[i : i + size])
        i += size
    return groups


def _estimate_prompt_tokens(body: dict[str, Any]) -> int:
    """对入参做最朴素的 prompt 字符数估算，仅用于填充 usage 字段

    不追求精度，仅保证：相同输入得到相同数值、长输入得到更大数值。
    """

    def _count_text(obj: Any) -> int:
        if isinstance(obj, str):
            return len(obj)
        if isinstance(obj, dict):
            return sum(_count_text(v) for v in obj.values())
        if isinstance(obj, list):
            return sum(_count_text(v) for v in obj)
        return 0

    chars = 0
    for key in ("messages", "input", "prompt", "instructions"):
        if key in body:
            chars += _count_text(body[key])
    # 4 char ≈ 1 token 的常见估算
    return max(1, chars // 4)


# ============================================================
# HTTP Handler
# ============================================================


class _MockHandler(BaseHTTPRequestHandler):
    """OpenAI 兼容 Mock 服务请求处理器"""

    server_version = f"QXWMock/{__version__}"
    config: MockServerConfig  # 由 server 注入

    # ----- 通用工具 -----

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        logger.debug("[%s] " + format, self.address_string(), *args)

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_error_json(self, status: int, message: str, err_type: str = "invalid_request_error") -> None:
        self._send_json(status, {"error": {"message": message, "type": err_type, "code": status}})

    def _begin_sse(self) -> None:
        # 流式响应不写 Content-Length / Transfer-Encoding，因此必须显式 Connection: close，
        # 让客户端在底层 socket 关闭时识别为流结束；保留 keep-alive 会导致 urllib 等
        # 客户端误以为还有更多数据而无限等待。
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-store")
        self.send_header("Connection", "close")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        # 显式标记请求处理完毕后立即关闭连接
        self.close_connection = True

    def _write_sse(self, data: str, event: str | None = None) -> bool:
        """写一个 SSE 事件；返回 False 表示对端已断开"""
        try:
            if event is not None:
                self.wfile.write(f"event: {event}\n".encode("utf-8"))
            for line in data.splitlines() or [""]:
                self.wfile.write(f"data: {line}\n".encode("utf-8"))
            self.wfile.write(b"\n")
            self.wfile.flush()
            return True
        except (BrokenPipeError, ConnectionResetError):
            return False

    def _read_json_body(self) -> dict[str, Any] | None:
        """读取并解析 JSON 请求体；解析失败时已就地回写 400 并返回 None"""
        length_header = self.headers.get("Content-Length", "0")
        try:
            length = int(length_header)
        except ValueError:
            self._send_error_json(400, f"非法 Content-Length: {length_header!r}")
            return None
        if length < 0:
            self._send_error_json(400, "Content-Length 不能为负数")
            return None
        if length == 0:
            return {}
        try:
            raw = self.rfile.read(length)
        except OSError as e:
            self._send_error_json(400, f"读取请求体失败: {e}")
            return None
        try:
            data = json.loads(raw.decode("utf-8"))
        except UnicodeDecodeError:
            self._send_error_json(400, "请求体不是合法的 UTF-8")
            return None
        except json.JSONDecodeError as e:
            self._send_error_json(400, f"请求体不是合法的 JSON: {e}")
            return None
        if not isinstance(data, dict):
            self._send_error_json(400, "请求体必须是 JSON 对象")
            return None
        return data

    # ----- 路由 -----

    @staticmethod
    def _normalize_path(path: str) -> str:
        """剥掉 query string 与可选 ``/api`` 前缀"""
        path = path.split("?", 1)[0]
        if path.startswith("/api/"):
            path = path[len("/api") :]
        return path or "/"

    def do_OPTIONS(self) -> None:  # noqa: N802
        # CORS 预检
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Max-Age", "86400")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        path = self._normalize_path(self.path)
        if path == "/health":
            self._send_json(200, {"status": "ok", "service": "qxw-llm-mock", "version": __version__})
            return
        if path in {"/v1/models", "/models"}:
            self._send_json(
                200,
                {
                    "object": "list",
                    "data": [
                        {
                            "id": self.config.model,
                            "object": "model",
                            "created": int(time.time()),
                            "owned_by": "qxw-llm-mock",
                        }
                    ],
                },
            )
            return
        if path == "/":
            self._send_json(
                200,
                {
                    "service": "qxw-llm-mock",
                    "version": __version__,
                    "endpoints": [
                        "POST /v1/chat/completions",
                        "POST /v1/responses",
                        "GET /v1/models",
                        "GET /health",
                    ],
                    "model": self.config.model,
                    "default": {
                        "ttft_ms": self.config.ttft_ms,
                        "tpot_ms": self.config.tpot_ms,
                        "tokens": self.config.tokens,
                        "chunk_min": self.config.chunk_min,
                        "chunk_max": self.config.chunk_max,
                    },
                    "rules": [
                        {
                            "name": r.name,
                            "match": r.match.model_dump(exclude_none=True),
                            "override": {
                                k: getattr(r, k)
                                for k in ("ttft_ms", "tpot_ms", "tokens", "chunk_min", "chunk_max")
                                if getattr(r, k) is not None
                            },
                        }
                        for r in self.config.rules
                    ],
                },
            )
            return
        self._send_error_json(404, f"未实现的 GET 路径: {path}", err_type="not_found")

    def do_POST(self) -> None:  # noqa: N802
        path = self._normalize_path(self.path)
        if path == "/v1/chat/completions":
            self._handle_chat_completions()
        elif path == "/v1/responses":
            self._handle_responses()
        else:
            # 先读掉请求体，避免连接被半挂
            length_header = self.headers.get("Content-Length", "0")
            try:
                length = int(length_header)
            except ValueError:
                length = 0
            if length > 0:
                try:
                    self.rfile.read(length)
                except OSError:
                    pass
            self._send_error_json(404, f"未实现的 POST 路径: {path}", err_type="not_found")

    # ----- 通用 -----

    def _resolve(self, body: dict[str, Any]) -> MockResponseProfile:
        """根据请求体 + 请求头匹配规则，返回当前请求生效的 profile"""
        profile, rule_name = self.config.resolve_profile(body, self.headers)
        if rule_name is not None:
            logger.debug(
                "[%s] 命中规则 %r → ttft=%dms tpot=%dms tokens=%d chunk=[%d,%d]",
                self.address_string(),
                rule_name,
                profile.ttft_ms,
                profile.tpot_ms,
                profile.tokens,
                profile.chunk_min,
                profile.chunk_max,
            )
        return profile

    # ----- /v1/chat/completions -----

    def _handle_chat_completions(self) -> None:
        body = self._read_json_body()
        if body is None:
            return

        profile = self._resolve(body)
        stream = bool(body.get("stream", False))
        prompt_tokens = _estimate_prompt_tokens(body)
        completion_tokens = profile.tokens
        tokens = _generate_tokens(completion_tokens)
        chat_id = _new_chat_id()
        created = int(time.time())
        model = self.config.model

        if not stream:
            _sleep_ms(profile.ttft_ms + max(0, completion_tokens - 1) * profile.tpot_ms)
            full_text = "".join(tokens)
            self._send_json(
                200,
                {
                    "id": chat_id,
                    "object": "chat.completion",
                    "created": created,
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": full_text},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": prompt_tokens,
                        "completion_tokens": completion_tokens,
                        "total_tokens": prompt_tokens + completion_tokens,
                    },
                },
            )
            return

        # 流式：SSE chunk by chunk
        self._begin_sse()

        # role chunk 占用 TTFT 时延
        role_chunk = {
            "id": chat_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "delta": {"role": "assistant", "content": ""},
                    "finish_reason": None,
                }
            ],
        }
        _sleep_ms(profile.ttft_ms)
        if not self._write_sse(json.dumps(role_chunk, ensure_ascii=False)):
            return

        # 把 tokens 按 chunk 分布分组；每组合成一条 SSE 事件
        groups = _group_into_chunks(tokens, profile.chunk_min, profile.chunk_max)
        for idx, group in enumerate(groups):
            # 第 idx 组的最后一个 token 相对首 token 的"自然到达时延" =
            #   sum(K[:idx]) + (K[idx] - 1)         （以 TPOT 为单位）
            # 因此 chunk 间应 sleep K[idx] * TPOT；首组特殊：sleep (K[0]-1)*TPOT
            if idx == 0:
                _sleep_ms((len(group) - 1) * profile.tpot_ms)
            else:
                _sleep_ms(len(group) * profile.tpot_ms)
            content = "".join(group)
            chunk = {
                "id": chat_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "delta": {"content": content},
                        "finish_reason": None,
                    }
                ],
            }
            if not self._write_sse(json.dumps(chunk, ensure_ascii=False)):
                return

        final_chunk = {
            "id": chat_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "delta": {},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
        }
        if not self._write_sse(json.dumps(final_chunk, ensure_ascii=False)):
            return
        self._write_sse("[DONE]")

    # ----- /v1/responses -----

    def _handle_responses(self) -> None:
        body = self._read_json_body()
        if body is None:
            return

        profile = self._resolve(body)
        stream = bool(body.get("stream", False))
        prompt_tokens = _estimate_prompt_tokens(body)
        completion_tokens = profile.tokens
        tokens = _generate_tokens(completion_tokens)
        resp_id = _new_response_id()
        msg_id = _new_message_id()
        created = int(time.time())
        model = self.config.model

        full_text_preview = ""  # 串流中累计文本（流式分支用）

        if not stream:
            _sleep_ms(profile.ttft_ms + max(0, completion_tokens - 1) * profile.tpot_ms)
            full_text = "".join(tokens)
            self._send_json(
                200,
                {
                    "id": resp_id,
                    "object": "response",
                    "created_at": created,
                    "status": "completed",
                    "model": model,
                    "output": [
                        {
                            "id": msg_id,
                            "type": "message",
                            "role": "assistant",
                            "status": "completed",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": full_text,
                                    "annotations": [],
                                }
                            ],
                        }
                    ],
                    "usage": {
                        "input_tokens": prompt_tokens,
                        "output_tokens": completion_tokens,
                        "total_tokens": prompt_tokens + completion_tokens,
                    },
                },
            )
            return

        # 流式：仿 OpenAI Responses 事件序列
        self._begin_sse()

        base_resp = {
            "id": resp_id,
            "object": "response",
            "created_at": created,
            "status": "in_progress",
            "model": model,
            "output": [],
        }

        _sleep_ms(profile.ttft_ms)
        if not self._write_sse(json.dumps({"type": "response.created", "response": base_resp}, ensure_ascii=False),
                                event="response.created"):
            return
        if not self._write_sse(
            json.dumps(
                {
                    "type": "response.output_item.added",
                    "output_index": 0,
                    "item": {
                        "id": msg_id,
                        "type": "message",
                        "role": "assistant",
                        "status": "in_progress",
                        "content": [],
                    },
                },
                ensure_ascii=False,
            ),
            event="response.output_item.added",
        ):
            return
        if not self._write_sse(
            json.dumps(
                {
                    "type": "response.content_part.added",
                    "item_id": msg_id,
                    "output_index": 0,
                    "content_index": 0,
                    "part": {"type": "output_text", "text": "", "annotations": []},
                },
                ensure_ascii=False,
            ),
            event="response.content_part.added",
        ):
            return

        groups = _group_into_chunks(tokens, profile.chunk_min, profile.chunk_max)
        for idx, group in enumerate(groups):
            if idx == 0:
                _sleep_ms((len(group) - 1) * profile.tpot_ms)
            else:
                _sleep_ms(len(group) * profile.tpot_ms)
            delta_text = "".join(group)
            full_text_preview += delta_text
            delta_event = {
                "type": "response.output_text.delta",
                "item_id": msg_id,
                "output_index": 0,
                "content_index": 0,
                "delta": delta_text,
            }
            if not self._write_sse(
                json.dumps(delta_event, ensure_ascii=False), event="response.output_text.delta"
            ):
                return

        final_text = full_text_preview
        if not self._write_sse(
            json.dumps(
                {
                    "type": "response.output_text.done",
                    "item_id": msg_id,
                    "output_index": 0,
                    "content_index": 0,
                    "text": final_text,
                },
                ensure_ascii=False,
            ),
            event="response.output_text.done",
        ):
            return
        if not self._write_sse(
            json.dumps(
                {
                    "type": "response.content_part.done",
                    "item_id": msg_id,
                    "output_index": 0,
                    "content_index": 0,
                    "part": {"type": "output_text", "text": final_text, "annotations": []},
                },
                ensure_ascii=False,
            ),
            event="response.content_part.done",
        ):
            return
        if not self._write_sse(
            json.dumps(
                {
                    "type": "response.output_item.done",
                    "output_index": 0,
                    "item": {
                        "id": msg_id,
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [
                            {"type": "output_text", "text": final_text, "annotations": []}
                        ],
                    },
                },
                ensure_ascii=False,
            ),
            event="response.output_item.done",
        ):
            return

        completed_resp = dict(base_resp)
        completed_resp["status"] = "completed"
        completed_resp["output"] = [
            {
                "id": msg_id,
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": final_text, "annotations": []}],
            }
        ]
        completed_resp["usage"] = {
            "input_tokens": prompt_tokens,
            "output_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        }
        self._write_sse(
            json.dumps({"type": "response.completed", "response": completed_resp}, ensure_ascii=False),
            event="response.completed",
        )


# ============================================================
# 服务入口
# ============================================================


class _ThreadingHTTPServer(ThreadingHTTPServer):
    """显式声明 daemon 线程，避免 KeyboardInterrupt 时遗留挂起子线程"""

    daemon_threads = True
    allow_reuse_address = True


def build_server(config: MockServerConfig) -> _ThreadingHTTPServer:
    """构造并返回一个绑定好的 server（不阻塞）

    主要给单元测试使用：测试里需要拿到真实端口号、在后台线程跑 ``serve_forever``，
    最后再 ``shutdown()``，避免阻塞主线程。
    """

    handler_cls = type(
        "_BoundMockHandler",
        (_MockHandler,),
        {"config": config},
    )
    server = _ThreadingHTTPServer((config.host, config.port), handler_cls)
    return server


def start_server(config: MockServerConfig) -> None:
    """启动 Mock 服务（阻塞，直到 KeyboardInterrupt）"""
    server = build_server(config)
    try:
        server.serve_forever()
    finally:
        server.server_close()
