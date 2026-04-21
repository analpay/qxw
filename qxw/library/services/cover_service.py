"""封面生成服务

调用 ZenMux 暴露的 Vertex AI 协议接口（Google Gemini 3 Pro Image Preview /
Nano Banana Pro）为 Markdown 文档生成封面图片。

纯业务逻辑层，不依赖 click / rich，便于被 CLI 层与潜在的测试用例共用。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from qxw.library.base.exceptions import NetworkError, QxwError, ValidationError
from qxw.library.base.logger import get_logger

logger = get_logger("qxw.cover")


# ============================================================
# 默认常量
# ============================================================

DEFAULT_ZENMUX_BASE_URL = "https://zenmux.ai/api/vertex-ai"
DEFAULT_ZENMUX_IMAGE_MODEL = "google/gemini-3-pro-image-preview"

# Markdown 正文默认截断长度（字符数）
# gemini 3 pro image preview 上下文比较宽松，默认 64K 字符足以把大部分长文整篇喂进去；
# 真遇到超长文档时仍可显式 `--truncate` 调小以控制 token 消耗
DEFAULT_MARKDOWN_TRUNCATE = 65536

# 用户指定的默认封面风格：技术白皮书 / 系统架构图
DEFAULT_COVER_STYLE_PROMPT = (
    "A highly-detailed, technical system architecture and data flow diagram, "
    "presented in a clean, professional white-paper visual style. "
    "The background is a soft, light mint-green grid pattern. "
    "All text uses a clean, uniform sans-serif font (like Roboto or Arial). "
    "Colors are limited to a professional palette: primarily teal-blues for structure "
    "and labels, with distinct color-coding (e.g., orange, green) for different data paths. "
    "Arrows are thin, precise, and have labels. "
    "Icons are stylized and distinct (e.g., stylized CPUs, server racks). "
    "Mathematical formulas are rendered cleanly in a LaTeX-style font."
)


# ============================================================
# 数据模型
# ============================================================


@dataclass
class CoverResult:
    """generate_cover 的返回值"""

    output_path: Path
    model: str
    prompt_chars: int
    text_response: str | None


# ============================================================
# 内部辅助
# ============================================================


def _read_markdown(md_path: Path, truncate: int) -> str:
    """读取 Markdown 文件，必要时截断"""
    if not md_path.is_file():
        raise ValidationError(f"Markdown 文件不存在: {md_path}")
    try:
        text = md_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as e:
        raise ValidationError(f"Markdown 文件编码非 UTF-8: {md_path} ({e})") from e

    if truncate > 0 and len(text) > truncate:
        text = text[:truncate] + f"\n\n...（正文已截断，仅保留前 {truncate} 字符用于生成封面）"
    return text


def _build_prompt(
    markdown_text: str,
    style_prompt: str,
    extra_prompt: str | None,
) -> str:
    """拼装最终送给图像模型的 prompt，保留用户原文的中英混合结构"""
    sections = [
        "根据这个markdown内容生成一个封面图片，风格使用这个：",
        style_prompt.strip(),
    ]
    if extra_prompt and extra_prompt.strip():
        sections.append(f"额外要求：{extra_prompt.strip()}")
    sections.append("Markdown 内容：")
    sections.append(markdown_text)
    return "\n\n".join(sections)


def _extract_image_and_text(response: object) -> tuple[bytes | None, str | None]:
    """从 google-genai 的响应里抽出第一张图片的原始字节与顺带的文字说明

    为兼容不同 SDK 版本：优先取 ``response.parts``，回退到
    ``response.candidates[0].content.parts``。
    """
    parts: list = []
    direct = getattr(response, "parts", None)
    if direct:
        parts = list(direct)
    else:
        candidates = getattr(response, "candidates", None) or []
        if candidates:
            content = getattr(candidates[0], "content", None)
            cand_parts = getattr(content, "parts", None) or []
            parts = list(cand_parts)

    image_bytes: bytes | None = None
    text_chunks: list[str] = []

    for part in parts:
        text = getattr(part, "text", None)
        if text:
            text_chunks.append(text)
            continue
        inline = getattr(part, "inline_data", None)
        if inline is None:
            continue
        data = getattr(inline, "data", None)
        if data is None:
            continue
        if image_bytes is None:
            image_bytes = data if isinstance(data, (bytes, bytearray)) else bytes(data)

    text_response = "\n".join(t.strip() for t in text_chunks if t and t.strip()) or None
    return image_bytes, text_response


# ============================================================
# 主入口
# ============================================================


def generate_cover(
    md_path: Path,
    *,
    api_key: str,
    output_path: Path | None = None,
    model: str = DEFAULT_ZENMUX_IMAGE_MODEL,
    base_url: str = DEFAULT_ZENMUX_BASE_URL,
    style_prompt: str = DEFAULT_COVER_STYLE_PROMPT,
    extra_prompt: str | None = None,
    truncate: int = DEFAULT_MARKDOWN_TRUNCATE,
) -> CoverResult:
    """根据 Markdown 内容生成封面图片并落盘为 PNG

    Args:
        md_path: 源 Markdown 文件绝对路径
        api_key: ZenMux API Key
        output_path: 输出 PNG 路径；None 时取 ``<md 同目录>/<stem>_cover.png``
        model: 图像模型名（默认 google/gemini-3-pro-image-preview）
        base_url: ZenMux Vertex AI 代理地址
        style_prompt: 主视觉风格 prompt（英文长句）
        extra_prompt: 附加到主 prompt 末尾的额外说明
        truncate: Markdown 截断长度（字符数）；<=0 表示不截断

    Returns:
        CoverResult
    """
    if not api_key or not api_key.strip():
        raise ValidationError(
            "未配置 ZenMux API Key。请任选一种方式配置：\n"
            "  1. 命令行 --api-key sk-zm-xxx\n"
            "  2. 环境变量 ZENMUX_API_KEY=sk-zm-xxx\n"
            "  3. 写入 ~/.config/qxw/setting.json 的 zenmux_api_key 字段"
        )

    try:
        from google import genai
        from google.genai import types
    except ImportError as e:
        raise QxwError(
            "缺少依赖 google-genai。请重新安装 qxw 或手动安装：\n"
            "  pip install google-genai"
        ) from e

    markdown_text = _read_markdown(md_path, truncate=truncate)
    prompt = _build_prompt(markdown_text, style_prompt=style_prompt, extra_prompt=extra_prompt)

    if output_path is None:
        output_path = md_path.with_name(f"{md_path.stem}_cover.png")
    output_path = output_path.expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    logger.debug("调用 ZenMux: model=%s base_url=%s prompt_chars=%d", model, base_url, len(prompt))

    try:
        client = genai.Client(
            api_key=api_key,
            vertexai=True,
            http_options=types.HttpOptions(api_version="v1", base_url=base_url),
        )
        response = client.models.generate_content(
            model=model,
            contents=[prompt],
            config=types.GenerateContentConfig(response_modalities=["TEXT", "IMAGE"]),
        )
    except QxwError:
        raise
    except Exception as e:
        raise NetworkError(f"ZenMux 调用失败: {e}") from e

    image_bytes, text_response = _extract_image_and_text(response)

    if not image_bytes:
        hint = f"\n模型附带文字：{text_response}" if text_response else ""
        raise QxwError(
            "模型未返回图片，可能被安全策略拦截、配额耗尽或模型名不可用。"
            f"{hint}"
        )

    output_path.write_bytes(image_bytes)

    return CoverResult(
        output_path=output_path,
        model=model,
        prompt_chars=len(prompt),
        text_response=text_response,
    )
