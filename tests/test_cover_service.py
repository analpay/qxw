"""qxw.library.services.cover_service 单元测试

覆盖：
- _read_markdown：文件不存在、UTF-8 解码失败、超长截断
- _build_prompt：带/不带 extra_prompt
- _extract_image_and_text：走 parts / 走 candidates / 无图片 / 多文本片段
- generate_cover：缺 api_key、google-genai 未安装（ImportError）、SDK 抛错 → NetworkError、
  模型未返回图片 → QxwError、正常写盘
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

from qxw.library.base.exceptions import NetworkError, QxwError, ValidationError
from qxw.library.services import cover_service as cs


class TestReadMarkdown:
    def test_文件不存在(self, tmp_path: Path) -> None:
        with pytest.raises(ValidationError, match="不存在"):
            cs._read_markdown(tmp_path / "nope.md", truncate=100)

    def test_非_UTF8_报错(self, tmp_path: Path) -> None:
        f = tmp_path / "a.md"
        f.write_bytes(b"\xff\xfe\xfd")
        with pytest.raises(ValidationError, match="编码非 UTF-8"):
            cs._read_markdown(f, truncate=100)

    def test_超长被截断(self, tmp_path: Path) -> None:
        f = tmp_path / "a.md"
        f.write_text("x" * 1000, encoding="utf-8")
        out = cs._read_markdown(f, truncate=100)
        assert len(out) <= 1000  # 原文 1000 字符
        assert "截断" in out

    def test_零或负_truncate_不截断(self, tmp_path: Path) -> None:
        f = tmp_path / "a.md"
        raw = "x" * 500
        f.write_text(raw, encoding="utf-8")
        assert cs._read_markdown(f, truncate=0) == raw
        assert cs._read_markdown(f, truncate=-1) == raw


class TestBuildPrompt:
    def test_无_extra(self) -> None:
        out = cs._build_prompt("正文", style_prompt="STYLE", extra_prompt=None)
        assert "STYLE" in out
        assert "额外要求" not in out
        assert "正文" in out

    def test_带_extra(self) -> None:
        out = cs._build_prompt("正文", style_prompt="STYLE", extra_prompt="要酷")
        assert "额外要求：要酷" in out

    def test_空白_extra_视为无(self) -> None:
        out = cs._build_prompt("正文", style_prompt="STYLE", extra_prompt="   \n")
        assert "额外要求" not in out


class TestExtractImageAndText:
    def _part(self, *, text=None, data=None):
        inline = SimpleNamespace(data=data) if data is not None else None
        return SimpleNamespace(text=text, inline_data=inline)

    def test_仅文字(self) -> None:
        resp = SimpleNamespace(parts=[self._part(text="你好"), self._part(text=" 世界 ")])
        img, txt = cs._extract_image_and_text(resp)
        assert img is None
        assert txt == "你好\n世界"

    def test_直接_parts_图片(self) -> None:
        resp = SimpleNamespace(parts=[self._part(data=b"\x89PNG")])
        img, txt = cs._extract_image_and_text(resp)
        assert img == b"\x89PNG"
        assert txt is None

    def test_从_candidates_回退(self) -> None:
        part = self._part(data=b"img")
        content = SimpleNamespace(parts=[part])
        cand = SimpleNamespace(content=content)
        resp = SimpleNamespace(parts=None, candidates=[cand])
        img, _ = cs._extract_image_and_text(resp)
        assert img == b"img"

    def test_多图只取第一张(self) -> None:
        resp = SimpleNamespace(parts=[self._part(data=b"A"), self._part(data=b"B")])
        img, _ = cs._extract_image_and_text(resp)
        assert img == b"A"

    def test_bytearray_保留原类型(self) -> None:
        # 实现分支：bytes/bytearray 原样返回，其他类型才调 bytes()
        ba = bytearray(b"X")
        resp = SimpleNamespace(parts=[self._part(data=ba)])
        img, _ = cs._extract_image_and_text(resp)
        assert img is ba

    def test_其他序列类型_转_bytes(self) -> None:
        resp = SimpleNamespace(parts=[self._part(data=memoryview(b"M"))])
        img, _ = cs._extract_image_and_text(resp)
        assert isinstance(img, bytes)
        assert bytes(img) == b"M"

    def test_空响应(self) -> None:
        resp = SimpleNamespace(parts=[])
        img, txt = cs._extract_image_and_text(resp)
        assert img is None
        assert txt is None

    def test_部分_inline_data_为_None(self) -> None:
        parts = [self._part(text=None, data=None)]
        resp = SimpleNamespace(parts=parts)
        assert cs._extract_image_and_text(resp) == (None, None)


class _FakeModels:
    def __init__(self, response, raise_exc: Exception | None = None) -> None:
        self._response = response
        self._raise = raise_exc
        self.calls: list[dict] = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        if self._raise is not None:
            raise self._raise
        return self._response


class _FakeClient:
    def __init__(self, response=None, raise_exc: Exception | None = None) -> None:
        self.models = _FakeModels(response, raise_exc)


def _install_fake_genai(
    monkeypatch: pytest.MonkeyPatch,
    response=None,
    raise_exc: Exception | None = None,
    raise_client: Exception | None = None,
) -> dict:
    """把 google.genai 与 google.genai.types 替换成假的模块树"""
    holder: dict[str, object] = {}

    genai_mod = types.ModuleType("google.genai")
    types_mod = types.ModuleType("google.genai.types")

    class HttpOptions:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

    class GenerateContentConfig:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

    types_mod.HttpOptions = HttpOptions  # type: ignore[attr-defined]
    types_mod.GenerateContentConfig = GenerateContentConfig  # type: ignore[attr-defined]

    class Client:
        def __init__(self, **kwargs) -> None:
            holder["client_kwargs"] = kwargs
            if raise_client is not None:
                raise raise_client
            self.models = _FakeModels(response, raise_exc).__dict__ and _FakeModels(response, raise_exc)
            # 重新：简单构造
            self.models = _FakeModels(response, raise_exc)
            holder["client"] = self

    genai_mod.Client = Client  # type: ignore[attr-defined]
    genai_mod.types = types_mod  # type: ignore[attr-defined]

    google_mod = types.ModuleType("google")
    google_mod.genai = genai_mod  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "google", google_mod)
    monkeypatch.setitem(sys.modules, "google.genai", genai_mod)
    monkeypatch.setitem(sys.modules, "google.genai.types", types_mod)
    return holder


class TestGenerateCover:
    def test_缺_api_key(self, tmp_path: Path) -> None:
        f = tmp_path / "a.md"
        f.write_text("# x", encoding="utf-8")
        with pytest.raises(ValidationError, match="API Key"):
            cs.generate_cover(f, api_key="  ")

    def test_ImportError_包装_QxwError(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        f = tmp_path / "a.md"
        f.write_text("# x", encoding="utf-8")
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *a, **k):
            if name == "google" or name.startswith("google."):
                raise ImportError("missing google-genai")
            return real_import(name, *a, **k)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        with pytest.raises(QxwError, match="google-genai"):
            cs.generate_cover(f, api_key="sk-1")

    def test_SDK_抛错_包装_NetworkError(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        f = tmp_path / "a.md"
        f.write_text("# x", encoding="utf-8")
        _install_fake_genai(monkeypatch, raise_client=RuntimeError("auth"))
        with pytest.raises(NetworkError, match="ZenMux"):
            cs.generate_cover(f, api_key="sk-1")

    def test_生成内容阶段异常_包装_NetworkError(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        f = tmp_path / "a.md"
        f.write_text("# x", encoding="utf-8")
        _install_fake_genai(monkeypatch, raise_exc=RuntimeError("429"))
        with pytest.raises(NetworkError, match="ZenMux"):
            cs.generate_cover(f, api_key="sk-1")

    def test_模型未返回图片_抛_QxwError(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        f = tmp_path / "a.md"
        f.write_text("# x", encoding="utf-8")
        resp = SimpleNamespace(parts=[SimpleNamespace(text="仅文字", inline_data=None)])
        _install_fake_genai(monkeypatch, response=resp)
        with pytest.raises(QxwError, match="模型未返回图片"):
            cs.generate_cover(f, api_key="sk-1")

    def test_正常生成_写盘并返回_CoverResult(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        f = tmp_path / "a.md"
        f.write_text("# x\n内容", encoding="utf-8")
        resp = SimpleNamespace(
            parts=[
                SimpleNamespace(text=None, inline_data=SimpleNamespace(data=b"IMG")),
                SimpleNamespace(text="说明", inline_data=None),
            ]
        )
        _install_fake_genai(monkeypatch, response=resp)

        result = cs.generate_cover(f, api_key="sk-1", truncate=0)
        assert result.output_path.read_bytes() == b"IMG"
        assert result.text_response == "说明"
        assert result.prompt_chars > 0
        assert result.output_path.name == "a_cover.png"

    def test_QxwError_在_try_内被原样抛出(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """generate_content 抛 QxwError 不应被包装为 NetworkError"""
        f = tmp_path / "a.md"
        f.write_text("# x", encoding="utf-8")
        _install_fake_genai(monkeypatch, raise_exc=QxwError("自定义", exit_code=7))
        with pytest.raises(QxwError) as exc:
            cs.generate_cover(f, api_key="sk-1")
        assert exc.value.exit_code == 7
        assert "自定义" in exc.value.message
