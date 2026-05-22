"""qxw.library.services.llm_mock_service 单元测试

覆盖点（遵循 0 happy test 原则）：
- 配置校验：host 空 / port 越界 / tpot 负数 / tokens=0 等
- 路径归一化：``/api`` 前缀、query string、空路径
- 工具函数：_generate_tokens 边界、_estimate_prompt_tokens 嵌套结构、_sleep_ms 非正
- HTTP 路由分支：未知路径、未知 POST、非法 JSON、非 dict body、负 Content-Length
- 业务行为（启服务真实跑）：
    - 非流式 chat 的 usage 字段
    - 流式 chat 的 chunk 数量与 [DONE] 终止
    - 流式 responses 的事件序列
    - `/v1/models`、`/health`、`/` 索引、CORS 预检
    - TTFT 实测下限（首事件不会早于 ttft）
"""

from __future__ import annotations

import json
import socket
import threading
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from typing import Generator

import pytest
from pydantic import ValidationError as PydanticValidationError

from qxw.library.services import llm_mock_service as svc

# ============================================================
# 配置与工具函数：纯函数边界
# ============================================================


class TestMockServerConfig:
    def test_host_空字符串_被拒绝(self) -> None:
        with pytest.raises(PydanticValidationError):
            svc.MockServerConfig(host="")

    def test_host_仅空白_被拒绝(self) -> None:
        with pytest.raises(PydanticValidationError):
            svc.MockServerConfig(host="   ")

    def test_port_越界(self) -> None:
        with pytest.raises(PydanticValidationError):
            svc.MockServerConfig(port=70000)

    def test_port_负数(self) -> None:
        with pytest.raises(PydanticValidationError):
            svc.MockServerConfig(port=-1)

    def test_ttft_负数(self) -> None:
        with pytest.raises(PydanticValidationError):
            svc.MockServerConfig(ttft_ms=-1)

    def test_tpot_负数(self) -> None:
        with pytest.raises(PydanticValidationError):
            svc.MockServerConfig(tpot_ms=-1)

    def test_tokens_零_拒绝(self) -> None:
        with pytest.raises(PydanticValidationError):
            svc.MockServerConfig(tokens=0)

    def test_tokens_超大_拒绝(self) -> None:
        with pytest.raises(PydanticValidationError):
            svc.MockServerConfig(tokens=100_001)


class TestGenerateTokens:
    def test_零个_返回空(self) -> None:
        assert svc._generate_tokens(0) == []

    def test_循环回绕(self) -> None:
        n = len(svc._MOCK_TOKEN_POOL) * 2 + 3
        toks = svc._generate_tokens(n)
        assert len(toks) == n
        assert toks[: len(svc._MOCK_TOKEN_POOL)] == list(svc._MOCK_TOKEN_POOL)
        assert toks[-1] == svc._MOCK_TOKEN_POOL[(n - 1) % len(svc._MOCK_TOKEN_POOL)]


class TestSleepMs:
    def test_零_不睡眠(self, monkeypatch: pytest.MonkeyPatch) -> None:
        called: list[float] = []
        monkeypatch.setattr(svc.time, "sleep", lambda s: called.append(s))
        svc._sleep_ms(0)
        assert called == []

    def test_负数_不睡眠(self, monkeypatch: pytest.MonkeyPatch) -> None:
        called: list[float] = []
        monkeypatch.setattr(svc.time, "sleep", lambda s: called.append(s))
        svc._sleep_ms(-10)
        assert called == []

    def test_正数_按秒换算(self, monkeypatch: pytest.MonkeyPatch) -> None:
        called: list[float] = []
        monkeypatch.setattr(svc.time, "sleep", lambda s: called.append(s))
        svc._sleep_ms(250)
        assert called == [0.25]


class TestEstimatePromptTokens:
    def test_空_body_至少_1(self) -> None:
        assert svc._estimate_prompt_tokens({}) == 1

    def test_messages_嵌套字典(self) -> None:
        n = svc._estimate_prompt_tokens(
            {"messages": [{"role": "user", "content": "hello world"}, {"role": "assistant", "content": "hi"}]}
        )
        # 至少把 "hello world" / "hi" / "user" / "assistant" / "role" / "content" 都计入
        assert n >= 5

    def test_input_字段_命中(self) -> None:
        assert svc._estimate_prompt_tokens({"input": "x" * 40}) >= 10

    def test_非字符串字段_不抛(self) -> None:
        # 数字、布尔、None 不计入字符数，不应抛异常
        n = svc._estimate_prompt_tokens({"messages": [123, True, None, {"content": "ok"}]})
        assert n >= 1


class TestNormalizePath:
    def test_去除_query(self) -> None:
        assert svc._MockHandler._normalize_path("/v1/models?x=1") == "/v1/models"

    def test_api_前缀剥离(self) -> None:
        assert svc._MockHandler._normalize_path("/api/v1/chat/completions") == "/v1/chat/completions"

    def test_空路径_归一为根(self) -> None:
        assert svc._MockHandler._normalize_path("") == "/"

    def test_仅_api_无后缀(self) -> None:
        # "/api/" 会被截断为 "/"
        assert svc._MockHandler._normalize_path("/api/") == "/"

    def test_非_api_前缀_不影响(self) -> None:
        assert svc._MockHandler._normalize_path("/health") == "/health"


# ============================================================
# 业务流程：启服务真实跑
# ============================================================


@contextmanager
def _run_server(**overrides: object) -> Generator[tuple[svc._ThreadingHTTPServer, int], None, None]:
    """启动一个 ephemeral port 的 mock server，跑在后台线程

    使用极低的 ttft/tpot，避免拖慢测试。
    """
    init_kwargs: dict[str, object] = {
        "host": "127.0.0.1",
        "port": 0,
        "ttft_ms": overrides.pop("ttft_ms", 5),
        "tpot_ms": overrides.pop("tpot_ms", 1),
        "tokens": overrides.pop("tokens", 4),
        "model": overrides.pop("model", "test-mock"),
    }
    for k in ("chunk_min", "chunk_max", "rules"):
        if k in overrides:
            init_kwargs[k] = overrides.pop(k)
    config = svc.MockServerConfig(**init_kwargs)
    server = svc.build_server(config)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        yield server, port
    finally:
        server.shutdown()
        server.server_close()


def _post_json(port: int, path: str, body: dict, *, timeout: float = 5.0) -> tuple[int, dict]:
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def _stream_sse(port: int, path: str, body: dict, *, timeout: float = 5.0) -> list[tuple[str | None, str]]:
    """读 SSE 流，返回 [(event, raw_data_payload), ...]，data 为 [DONE] 时原样保留"""
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    events: list[tuple[str | None, str]] = []
    with urllib.request.urlopen(req, timeout=timeout) as r:
        current_event: str | None = None
        for raw in r:
            line = raw.decode("utf-8").rstrip("\r\n")
            if line.startswith("event: "):
                current_event = line[7:]
            elif line.startswith("data: "):
                events.append((current_event, line[6:]))
                current_event = None
    return events


class TestHealthAndIndex:
    def test_health(self) -> None:
        with _run_server() as (_s, port):
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=3) as r:
                payload = json.loads(r.read())
            assert payload["status"] == "ok"
            assert payload["service"] == "qxw-llm-mock"

    def test_未知_GET_404(self) -> None:
        with _run_server() as (_s, port):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/wat", timeout=3)
                pytest.fail("应抛 HTTPError")
            except urllib.error.HTTPError as e:
                payload = json.loads(e.read())
                assert e.code == 404
                assert payload["error"]["type"] == "not_found"

    def test_models_列表(self) -> None:
        with _run_server(model="my-mock") as (_s, port):
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/v1/models", timeout=3) as r:
                payload = json.loads(r.read())
            assert payload["object"] == "list"
            assert payload["data"][0]["id"] == "my-mock"

    def test_api_前缀兼容(self) -> None:
        with _run_server() as (_s, port):
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/v1/models", timeout=3) as r:
                payload = json.loads(r.read())
            assert payload["object"] == "list"

    def test_根路径_返回元信息(self) -> None:
        with _run_server(ttft_ms=11, tpot_ms=7, tokens=3, model="x") as (_s, port):
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=3) as r:
                payload = json.loads(r.read())
            assert payload["model"] == "x"
            assert payload["default"]["ttft_ms"] == 11
            assert payload["default"]["tpot_ms"] == 7
            assert payload["default"]["tokens"] == 3
            assert payload["default"]["chunk_min"] == 1
            assert payload["default"]["chunk_max"] == 1
            assert payload["rules"] == []

    def test_OPTIONS_预检(self) -> None:
        with _run_server() as (_s, port):
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/v1/chat/completions", method="OPTIONS"
            )
            with urllib.request.urlopen(req, timeout=3) as r:
                assert r.status == 204
                assert r.headers.get("Access-Control-Allow-Origin") == "*"


class TestChatCompletionsErrors:
    def test_非法_JSON_400(self) -> None:
        with _run_server() as (_s, port):
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/v1/chat/completions",
                data=b"not json",
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                urllib.request.urlopen(req, timeout=3)
                pytest.fail("应 400")
            except urllib.error.HTTPError as e:
                assert e.code == 400
                payload = json.loads(e.read())
                assert "JSON" in payload["error"]["message"]

    def test_非_dict_body_400(self) -> None:
        with _run_server() as (_s, port):
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/v1/chat/completions",
                data=b'["a","b"]',
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                urllib.request.urlopen(req, timeout=3)
                pytest.fail("应 400")
            except urllib.error.HTTPError as e:
                assert e.code == 400

    def test_未知_POST_404(self) -> None:
        with _run_server() as (_s, port):
            code, payload = _post_json(port, "/v1/embeddings", {"input": "x"})
            assert code == 404
            assert payload["error"]["type"] == "not_found"

    def test_非法_Content_Length_400(self) -> None:
        """手工构造 HTTP 请求，让 Content-Length 不是数字"""
        with _run_server() as (_s, port):
            with socket.create_connection(("127.0.0.1", port), timeout=3) as sock:
                sock.sendall(
                    b"POST /v1/chat/completions HTTP/1.0\r\n"
                    b"Content-Length: abc\r\n"
                    b"Content-Type: application/json\r\n"
                    b"\r\n"
                )
                resp = b""
                while True:
                    chunk = sock.recv(4096)
                    if not chunk:
                        break
                    resp += chunk
            assert b"400" in resp.split(b"\r\n", 1)[0]
            assert b"Content-Length" in resp

    def test_负_Content_Length_400(self) -> None:
        with _run_server() as (_s, port):
            with socket.create_connection(("127.0.0.1", port), timeout=3) as sock:
                sock.sendall(
                    b"POST /v1/chat/completions HTTP/1.0\r\n"
                    b"Content-Length: -1\r\n"
                    b"\r\n"
                )
                resp = b""
                while True:
                    chunk = sock.recv(4096)
                    if not chunk:
                        break
                    resp += chunk
            assert b"400" in resp.split(b"\r\n", 1)[0]


class TestChatCompletionsBehavior:
    def test_非流式_usage_与_文本(self) -> None:
        with _run_server(tokens=4, ttft_ms=5, tpot_ms=1) as (_s, port):
            code, payload = _post_json(
                port,
                "/v1/chat/completions",
                {"messages": [{"role": "user", "content": "hi"}], "stream": False},
            )
            assert code == 200
            assert payload["object"] == "chat.completion"
            assert payload["model"] == "test-mock"
            assert payload["choices"][0]["finish_reason"] == "stop"
            assert payload["usage"]["completion_tokens"] == 4
            assert payload["usage"]["total_tokens"] == (
                payload["usage"]["prompt_tokens"] + payload["usage"]["completion_tokens"]
            )
            text = payload["choices"][0]["message"]["content"]
            assert text == "".join(svc._generate_tokens(4))

    def test_流式_chunk_数与_DONE_终止(self) -> None:
        with _run_server(tokens=3, ttft_ms=5, tpot_ms=1) as (_s, port):
            events = _stream_sse(
                port,
                "/v1/chat/completions",
                {"messages": [{"role": "user", "content": "hi"}], "stream": True},
            )
            payloads = [p for _e, p in events]
            assert payloads[-1] == "[DONE]"
            # 第一个 chunk 是 role chunk（delta.role=assistant，content=""）
            first = json.loads(payloads[0])
            assert first["choices"][0]["delta"]["role"] == "assistant"
            # 中间 N 个 content chunk
            content_chunks = [
                json.loads(p) for p in payloads[1:-2] if p != "[DONE]"
            ]
            assert len(content_chunks) == 3
            # 最后一个非 DONE chunk 是 finish_reason=stop
            stop_chunk = json.loads(payloads[-2])
            assert stop_chunk["choices"][0]["finish_reason"] == "stop"
            # usage 字段在 stop chunk 中
            assert stop_chunk["usage"]["completion_tokens"] == 3

    def test_TTFT_下限(self) -> None:
        """首事件不会比 ttft 显著更早；用 80ms ttft，预留 50ms 误差"""
        ttft = 80
        with _run_server(tokens=2, ttft_ms=ttft, tpot_ms=1) as (_s, port):
            t0 = time.perf_counter()
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/v1/chat/completions",
                data=json.dumps({"messages": [{"role": "u", "content": "h"}], "stream": True}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            first_at: float | None = None
            with urllib.request.urlopen(req, timeout=5) as r:
                for raw in r:
                    if raw.startswith(b"data: ") and first_at is None:
                        first_at = (time.perf_counter() - t0) * 1000
                        break
            assert first_at is not None
            # 允许一点点误差，主要是验证"没有提前"——下限严格，上限宽松
            assert first_at >= ttft - 5


class TestResponsesEndpoint:
    def test_非流式_status_与_文本(self) -> None:
        with _run_server(tokens=3, ttft_ms=2, tpot_ms=1) as (_s, port):
            code, payload = _post_json(
                port,
                "/v1/responses",
                {"input": "hi", "stream": False},
            )
            assert code == 200
            assert payload["status"] == "completed"
            assert payload["object"] == "response"
            text = payload["output"][0]["content"][0]["text"]
            assert text == "".join(svc._generate_tokens(3))
            assert payload["usage"]["output_tokens"] == 3

    def test_流式_事件序列(self) -> None:
        with _run_server(tokens=2, ttft_ms=2, tpot_ms=1) as (_s, port):
            events = _stream_sse(
                port, "/v1/responses", {"input": "hi", "stream": True}
            )
            event_names = [e for e, _ in events]
            # 期望顺序
            assert event_names[0] == "response.created"
            assert event_names[-1] == "response.completed"
            delta_events = [e for e, _ in events if e == "response.output_text.delta"]
            assert len(delta_events) == 2
            # 末事件携带 status=completed
            last = json.loads(events[-1][1])
            assert last["response"]["status"] == "completed"
            # 输出文本拼回原 token 序列
            assert last["response"]["output"][0]["content"][0]["text"] == "".join(svc._generate_tokens(2))


# ============================================================
# 新增：profile / rule / chunk / 配置加载
# ============================================================


class TestMockResponseProfile:
    def test_chunk_min_大于_max_被拒绝(self) -> None:
        with pytest.raises(PydanticValidationError):
            svc.MockResponseProfile(chunk_min=5, chunk_max=3)

    def test_chunk_min_零_拒绝(self) -> None:
        with pytest.raises(PydanticValidationError):
            svc.MockResponseProfile(chunk_min=0, chunk_max=1)

    def test_chunk_等长_OK(self) -> None:
        p = svc.MockResponseProfile(chunk_min=4, chunk_max=4)
        assert p.chunk_min == p.chunk_max == 4


class TestMockRuleMatch:
    def test_全空_被拒绝(self) -> None:
        with pytest.raises(PydanticValidationError):
            svc.MockRuleMatch()

    def test_仅_header_value_无_name_被拒绝(self) -> None:
        with pytest.raises(PydanticValidationError):
            svc.MockRuleMatch(header_value="v")

    def test_非法正则_被拒绝(self) -> None:
        with pytest.raises(PydanticValidationError):
            svc.MockRuleMatch(content_regex="(unclosed")

    def test_有一个字段_即可(self) -> None:
        svc.MockRuleMatch(model="x")
        svc.MockRuleMatch(content_contains="foo")
        svc.MockRuleMatch(header_name="X-Y")


class TestMockRule:
    def test_chunk_min_大于_max_被拒绝(self) -> None:
        with pytest.raises(PydanticValidationError):
            svc.MockRule(
                name="bad", match=svc.MockRuleMatch(model="x"), chunk_min=5, chunk_max=3
            )

    def test_apply_to_部分覆盖(self) -> None:
        base = svc.MockResponseProfile(ttft_ms=100, tpot_ms=10, tokens=10, chunk_min=1, chunk_max=1)
        rule = svc.MockRule(match=svc.MockRuleMatch(model="m"), ttft_ms=999, chunk_max=5)
        # 单独 chunk_max 大于默认 chunk_min(1) → 合法
        out = rule.apply_to(base)
        assert out.ttft_ms == 999
        assert out.tpot_ms == 10  # 继承
        assert out.tokens == 10
        assert out.chunk_min == 1
        assert out.chunk_max == 5

    def test_apply_to_产生非法组合_抛错(self) -> None:
        """rule 单独看是 chunk_max=5；合并到 base.chunk_min=8 时不合法（5<8）"""
        base = svc.MockResponseProfile(ttft_ms=100, tpot_ms=10, tokens=10, chunk_min=8, chunk_max=10)
        rule = svc.MockRule(match=svc.MockRuleMatch(model="m"), chunk_max=5)
        with pytest.raises(PydanticValidationError):
            rule.apply_to(base)


class TestExtractMatchText:
    def test_空_body(self) -> None:
        assert svc._extract_match_text({}) == ""

    def test_messages_只取_content(self) -> None:
        text = svc._extract_match_text({
            "messages": [
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "hi"},
            ]
        })
        assert "hello" in text
        assert "hi" in text
        assert "user" not in text  # role 不应出现

    def test_messages_多模态_part(self) -> None:
        text = svc._extract_match_text({
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": "alpha"},
                {"type": "image_url", "image_url": {"url": "http://x"}},
            ]}]
        })
        assert "alpha" in text
        assert "http" not in text  # url 不应被纳入

    def test_input_字符串(self) -> None:
        assert svc._extract_match_text({"input": "raw"}) == "raw"

    def test_input_嵌套对象(self) -> None:
        text = svc._extract_match_text({
            "input": [{"role": "user", "content": [{"type": "text", "text": "nested"}]}]
        })
        assert "nested" in text

    def test_prompt_兜底(self) -> None:
        assert svc._extract_match_text({"prompt": "raw"}) == "raw"

    def test_prompt_非字符串_忽略(self) -> None:
        assert svc._extract_match_text({"prompt": 123}) == ""


class TestMatchRule:
    def _rule(self, **match_kwargs) -> svc.MockRule:
        return svc.MockRule(match=svc.MockRuleMatch(**match_kwargs))

    def test_model_精确(self) -> None:
        r = self._rule(model="gpt-4")
        assert svc._match_rule(r, {"model": "gpt-4"}, {})
        assert not svc._match_rule(r, {"model": "gpt-5"}, {})
        assert not svc._match_rule(r, {}, {})  # 缺 model

    def test_content_contains(self) -> None:
        r = self._rule(content_contains="翻译")
        assert svc._match_rule(r, {"messages": [{"role": "u", "content": "请翻译这段"}]}, {})
        assert not svc._match_rule(r, {"messages": [{"role": "u", "content": "hello"}]}, {})

    def test_content_regex(self) -> None:
        r = self._rule(content_regex=r"(?i)translate")
        assert svc._match_rule(r, {"messages": [{"role": "u", "content": "Translate this"}]}, {})
        assert not svc._match_rule(r, {"messages": [{"role": "u", "content": "no match"}]}, {})

    def test_header_存在(self) -> None:
        r = self._rule(header_name="X-Mock")
        assert svc._match_rule(r, {}, {"x-mock": "anything"})  # 大小写不敏感
        assert not svc._match_rule(r, {}, {})
        assert not svc._match_rule(r, {}, {"x-mock": ""})  # 空值视作不存在

    def test_header_精确值(self) -> None:
        r = self._rule(header_name="X-Mock", header_value="burst")
        assert svc._match_rule(r, {}, {"X-Mock": "burst"})
        assert not svc._match_rule(r, {}, {"X-Mock": "other"})

    def test_AND_全部命中才算命中(self) -> None:
        r = self._rule(model="m", content_contains="hi")
        assert svc._match_rule(
            r,
            {"model": "m", "messages": [{"role": "u", "content": "hi there"}]},
            {},
        )
        # model 对但 content 不含
        assert not svc._match_rule(
            r, {"model": "m", "messages": [{"role": "u", "content": "bye"}]}, {}
        )
        # content 对但 model 不对
        assert not svc._match_rule(
            r, {"model": "n", "messages": [{"role": "u", "content": "hi"}]}, {}
        )


class TestResolveProfile:
    def test_首条命中_即返回(self) -> None:
        cfg = svc.MockServerConfig(
            ttft_ms=100, tpot_ms=10, tokens=8,
            rules=[
                svc.MockRule(name="a", match=svc.MockRuleMatch(model="x"), tokens=20),
                svc.MockRule(name="b", match=svc.MockRuleMatch(model="x"), tokens=999),
            ],
        )
        profile, name = cfg.resolve_profile({"model": "x"}, {})
        assert name == "a"
        assert profile.tokens == 20

    def test_无命中_用_default(self) -> None:
        cfg = svc.MockServerConfig(
            ttft_ms=100, tpot_ms=10, tokens=8,
            rules=[svc.MockRule(name="a", match=svc.MockRuleMatch(model="x"), tokens=20)],
        )
        profile, name = cfg.resolve_profile({"model": "y"}, {})
        assert name is None
        assert profile.tokens == 8

    def test_未命名规则_返回标签字符串(self) -> None:
        cfg = svc.MockServerConfig(
            rules=[svc.MockRule(match=svc.MockRuleMatch(model="x"), tokens=20)]
        )
        _, name = cfg.resolve_profile({"model": "x"}, {})
        assert name == "<unnamed>"


class TestGroupIntoChunks:
    def test_空_token_列表(self) -> None:
        assert svc._group_into_chunks([], 1, 1) == []

    def test_定长_chunk(self) -> None:
        assert svc._group_into_chunks(["a", "b", "c", "d", "e"], 2, 2) == [
            ["a", "b"], ["c", "d"], ["e"]
        ]

    def test_chunk_大于总长度(self) -> None:
        # chunk_min/max = 10，但只有 3 个 token：第一组直接装满全部
        assert svc._group_into_chunks(["a", "b", "c"], 10, 10) == [["a", "b", "c"]]

    def test_随机区间_总和等于输入(self) -> None:
        import random as _r
        rng = _r.Random(42)
        tokens = ["x"] * 50
        groups = svc._group_into_chunks(tokens, 2, 6, rng=rng)
        assert sum(len(g) for g in groups) == 50
        # 除最后一组外都应在 [2, 6]
        for g in groups[:-1]:
            assert 2 <= len(g) <= 6

    def test_chunk_min_零_拒绝(self) -> None:
        with pytest.raises(ValueError):
            svc._group_into_chunks(["a"], 0, 1)

    def test_chunk_min_大于_max_拒绝(self) -> None:
        with pytest.raises(ValueError):
            svc._group_into_chunks(["a"], 3, 2)


class TestLoadConfigFromFile:
    def test_文件不存在(self, tmp_path) -> None:
        from qxw.library.base.exceptions import ValidationError as QxwVE
        with pytest.raises(QxwVE):
            svc.load_config_from_file(tmp_path / "nope.json")

    def test_目录不是文件(self, tmp_path) -> None:
        from qxw.library.base.exceptions import ValidationError as QxwVE
        with pytest.raises(QxwVE):
            svc.load_config_from_file(tmp_path)

    def test_非法_JSON(self, tmp_path) -> None:
        from qxw.library.base.exceptions import ValidationError as QxwVE
        p = tmp_path / "bad.json"
        p.write_text("not json", encoding="utf-8")
        with pytest.raises(QxwVE):
            svc.load_config_from_file(p)

    def test_根不是对象(self, tmp_path) -> None:
        from qxw.library.base.exceptions import ValidationError as QxwVE
        p = tmp_path / "arr.json"
        p.write_text("[1,2]", encoding="utf-8")
        with pytest.raises(QxwVE):
            svc.load_config_from_file(p)

    def test_default_必须是对象(self, tmp_path) -> None:
        from qxw.library.base.exceptions import ValidationError as QxwVE
        p = tmp_path / "x.json"
        p.write_text('{"default": "string"}', encoding="utf-8")
        with pytest.raises(QxwVE):
            svc.load_config_from_file(p)

    def test_rules_必须是数组(self, tmp_path) -> None:
        from qxw.library.base.exceptions import ValidationError as QxwVE
        p = tmp_path / "x.json"
        p.write_text('{"rules": {"x": 1}}', encoding="utf-8")
        with pytest.raises(QxwVE):
            svc.load_config_from_file(p)

    def test_schema_错误_包装为_QxwVE(self, tmp_path) -> None:
        from qxw.library.base.exceptions import ValidationError as QxwVE
        p = tmp_path / "x.json"
        p.write_text(
            '{"default": {"ttft_ms": -1}}',
            encoding="utf-8",
        )
        with pytest.raises(QxwVE):
            svc.load_config_from_file(p)

    def test_正常加载(self, tmp_path) -> None:
        p = tmp_path / "x.json"
        p.write_text(
            '{"host":"0.0.0.0","port":9999,"model":"m",'
            '"default":{"ttft_ms":500,"tpot_ms":10,"tokens":20,"chunk_min":2,"chunk_max":4},'
            '"rules":[{"name":"r","match":{"model":"x"},"tokens":100}]}',
            encoding="utf-8",
        )
        cfg = svc.load_config_from_file(p)
        assert cfg.host == "0.0.0.0"
        assert cfg.port == 9999
        assert cfg.ttft_ms == 500
        assert cfg.chunk_min == 2 and cfg.chunk_max == 4
        assert len(cfg.rules) == 1
        assert cfg.rules[0].tokens == 100


class TestReadExampleConfig:
    def test_文件存在且可解析(self) -> None:
        text = svc.read_example_config()
        data = json.loads(text)
        # 示例必须包含所有关键字段，否则 mock-config 输出就不完整
        assert "default" in data
        assert "rules" in data and len(data["rules"]) >= 3
        # 通过示例文件能成功构造 MockServerConfig
        cfg = svc.load_config_from_file(svc.EXAMPLE_CONFIG_PATH)
        assert cfg.rules
        # 至少有一个 header / content / model / regex 风格的规则
        match_kinds = set()
        for r in cfg.rules:
            for k in ("model", "content_contains", "content_regex", "header_name"):
                if getattr(r.match, k) is not None:
                    match_kinds.add(k)
        assert {"model", "content_contains", "content_regex", "header_name"} <= match_kinds


class TestChunkEndToEnd:
    """实启动 server，验证 chunk 配置真的改变了 SSE 事件数量"""

    def test_chat_chunk_等长(self) -> None:
        # tokens=10, chunk=5 → 2 个 content chunk + role + stop + DONE = 5
        with _run_server(tokens=10, ttft_ms=2, tpot_ms=1, chunk_min=5, chunk_max=5) as (_s, port):
            events = _stream_sse(
                port, "/v1/chat/completions",
                {"messages": [{"role": "user", "content": "x"}], "stream": True},
            )
            payloads = [p for _e, p in events]
            assert payloads[-1] == "[DONE]"
            # content chunks: 过滤出 delta.content 非空
            content_chunks = []
            for p in payloads[:-1]:
                if p == "[DONE]":
                    continue
                obj = json.loads(p)
                d = obj["choices"][0]["delta"]
                if d.get("content"):
                    content_chunks.append(d["content"])
            assert len(content_chunks) == 2
            assert all(len(c) > 0 for c in content_chunks)

    def test_chat_chunk_随机(self) -> None:
        # tokens=20, chunk in [3,6] → 应有 4~7 个 content chunk
        with _run_server(tokens=20, ttft_ms=2, tpot_ms=1, chunk_min=3, chunk_max=6) as (_s, port):
            events = _stream_sse(
                port, "/v1/chat/completions",
                {"messages": [{"role": "user", "content": "x"}], "stream": True},
            )
            content_chunks = []
            for _e, p in events:
                if p == "[DONE]":
                    continue
                obj = json.loads(p)
                d = obj["choices"][0]["delta"]
                if d.get("content"):
                    content_chunks.append(d["content"])
            assert 4 <= len(content_chunks) <= 7

    def test_responses_chunk_等长(self) -> None:
        with _run_server(tokens=9, ttft_ms=2, tpot_ms=1, chunk_min=3, chunk_max=3) as (_s, port):
            events = _stream_sse(port, "/v1/responses", {"input": "x", "stream": True})
            deltas = [e for e, _ in events if e == "response.output_text.delta"]
            assert len(deltas) == 3

    def test_chat_总时间_chunk_无关(self) -> None:
        """chunk 配置不应改变响应总耗时（容差宽放）"""
        with _run_server(tokens=10, ttft_ms=20, tpot_ms=10, chunk_min=5, chunk_max=5) as (_s, port):
            t0 = time.perf_counter()
            _ = _stream_sse(
                port, "/v1/chat/completions",
                {"messages": [{"role": "user", "content": "x"}], "stream": True},
            )
            elapsed = (time.perf_counter() - t0) * 1000
            # 预期 = 20 + (10-1)*10 = 110ms，允许 100ms 误差
            assert 90 <= elapsed <= 250, f"unexpected elapsed: {elapsed}ms"


class TestRuleEndToEnd:
    def test_命中_model_规则_改变_tokens(self) -> None:
        cfg = svc.MockServerConfig(
            host="127.0.0.1", port=0, ttft_ms=2, tpot_ms=1, tokens=4,
            rules=[svc.MockRule(name="big", match=svc.MockRuleMatch(model="big"), tokens=12)],
        )
        server = svc.build_server(cfg)
        port = server.server_address[1]
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            _, big = _post_json(port, "/v1/chat/completions",
                                {"model": "big", "messages": [{"role": "u", "content": "x"}],
                                 "stream": False})
            assert big["usage"]["completion_tokens"] == 12
            _, small = _post_json(port, "/v1/chat/completions",
                                  {"model": "small", "messages": [{"role": "u", "content": "x"}],
                                   "stream": False})
            assert small["usage"]["completion_tokens"] == 4
        finally:
            server.shutdown()
            server.server_close()

    def test_命中_header_规则(self) -> None:
        cfg = svc.MockServerConfig(
            host="127.0.0.1", port=0, ttft_ms=2, tpot_ms=1, tokens=4,
            rules=[svc.MockRule(name="hdr", match=svc.MockRuleMatch(header_name="X-Mock"),
                                tokens=7)],
        )
        server = svc.build_server(cfg)
        port = server.server_address[1]
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/v1/chat/completions",
                data=json.dumps({"messages": [{"role": "u", "content": "x"}], "stream": False}).encode(),
                headers={"Content-Type": "application/json", "X-Mock": "any"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=3) as r:
                payload = json.loads(r.read())
            assert payload["usage"]["completion_tokens"] == 7
        finally:
            server.shutdown()
            server.server_close()


class TestStartServer:
    def test_start_server_可被_shutdown(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """启动 start_server 后通过 shutdown 让 serve_forever 退出"""
        config = svc.MockServerConfig(host="127.0.0.1", port=0, ttft_ms=1, tpot_ms=1, tokens=1)

        # 构造一个 build_server 返回的 server，并在另一个线程触发 shutdown
        server = svc.build_server(config)
        port = server.server_address[1]
        assert port > 0

        def _stop() -> None:
            time.sleep(0.1)
            server.shutdown()

        threading.Thread(target=_stop, daemon=True).start()

        # 用 monkeypatch 让 start_server 使用我们已构造好的 server
        monkeypatch.setattr(svc, "build_server", lambda c: server)
        # 不应抛
        svc.start_server(config)
