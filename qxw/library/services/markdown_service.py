"""Markdown 处理服务

提供 Markdown 文件中 PlantUML 代码块的提取、本地 plantuml.jar 渲染、
多格式（SVG/PNG/JPG）写盘以及中文字体/背景色后处理等功能。
"""

from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from qxw.library.base.exceptions import QxwError
from qxw.library.base.logger import get_logger
from qxw.library.services.image_service import (
    DEFAULT_SVG_CJK_FONT_FAMILY,
    _inject_svg_font_family,
)

logger = get_logger("qxw.markdown")

# ============================================================
# 常量
# ============================================================

# 匹配 ```plantuml / ```puml / ```uml 代码围栏
# group(1) 捕获围栏前的缩进，用于校验闭合 ``` 的对齐
# group(2) 捕获语言标识，group(3) 捕获围栏内 UML 源码
_PLANTUML_FENCE_RE = re.compile(
    r"^([ \t]*)```(plantuml|puml|uml)[ \t]*\n(.*?)^\1```[ \t]*$",
    re.MULTILINE | re.DOTALL,
)

# 支持的输出图片格式
SUPPORTED_FORMATS = ("svg", "png", "jpg")

# 支持的背景色预设
SUPPORTED_BACKGROUNDS = ("white", "black", "transparent")

_BG_HEX = {
    "white": "#ffffff",
    "black": "#000000",
    "transparent": None,
}

# 默认给 Java 端的 PlantUML 字体名（即便系统未安装，渲染不会失败；
# 最终 SVG/PNG/JPG 还会由 _inject_svg_font_family 再兜底一次）
DEFAULT_PLANTUML_FONT_NAME = "PingFang SC"

# 默认 plantuml.jar 查找路径
DEFAULT_JAR_PATH = Path.home() / ".config" / "qxw" / "plantuml.jar"


# ============================================================
# 数据模型
# ============================================================


@dataclass
class PlantUMLBlock:
    """Markdown 中的一个 PlantUML 代码围栏"""

    start: int       # 围栏整体在原文中的起始偏移（含 ```lang 行首）
    end: int         # 围栏整体在原文中的结束偏移（含末尾 ```）
    indent: str      # 围栏缩进（闭合 ``` 应与之对齐）
    source: str      # 围栏内的 UML 源码（原样，未去缩进）


# ============================================================
# PlantUML 块提取
# ============================================================


def extract_plantuml_blocks(markdown_text: str) -> list[PlantUMLBlock]:
    """扫描 Markdown 文本，按出现顺序返回所有 PlantUML 代码围栏"""
    blocks: list[PlantUMLBlock] = []
    for match in _PLANTUML_FENCE_RE.finditer(markdown_text):
        blocks.append(PlantUMLBlock(
            start=match.start(),
            end=match.end(),
            indent=match.group(1),
            source=match.group(3),
        ))
    return blocks


# ============================================================
# PlantUML 渲染（subprocess -> java -jar plantuml.jar）
# ============================================================


def _ensure_java_and_jar(jar_path: Path, java_bin: str) -> None:
    """确认 java 可用且 plantuml.jar 存在，缺失则抛出用户友好的错误"""
    if shutil.which(java_bin) is None:
        raise QxwError(
            f"未找到 java 可执行文件（{java_bin}）。请先安装 JRE 后重试，"
            "或通过 --java 指定完整路径。"
        )
    if not jar_path.is_file():
        raise QxwError(
            f"未找到 plantuml.jar: {jar_path}\n"
            "请从 https://plantuml.com/download 下载 plantuml.jar，"
            f"放到 {DEFAULT_JAR_PATH} 或通过 --plantuml-jar 指定路径。"
        )


_FONT_NAME_SAFE_RE = re.compile(r"^[A-Za-z0-9 _\-.]+$")


def _sanitize_font_name(font_name: str) -> str:
    """校验并返回 PlantUML ``defaultFontName`` 字体名

    字体名会被注入 UML 源码（``skinparam defaultFontName "<name>"``），
    若含双引号或换行等特殊字符，可被用于提前闭合字符串并注入任意 skinparam /
    指令。通过一个字母、数字、空格、点、横杠、下划线的白名单拦截，既覆盖
    "PingFang SC"、"Noto Sans CJK SC" 等常见合法字体，也足够保守。
    """
    if not isinstance(font_name, str) or not font_name.strip():
        raise QxwError("PlantUML 字体名不能为空")
    if not _FONT_NAME_SAFE_RE.match(font_name):
        raise QxwError(f"非法的 PlantUML 字体名: {font_name!r}（仅允许字母数字、空格、._-）")
    return font_name


def _prepare_plantuml_source(source: str, background: str, font_name: str) -> str:
    """在 PlantUML 源码里注入背景色与默认字体配置

    - 未检测到 @startuml 时自动用 @startuml ... @enduml 包裹（兼容裸内容）
    - 已有 @startuml 时把 skinparam 插在 @startuml 下一行
    """
    bg_value = {"white": "white", "black": "black", "transparent": "transparent"}[background]
    safe_font = _sanitize_font_name(font_name)
    skin_lines = [
        f"skinparam backgroundColor {bg_value}",
        f'skinparam defaultFontName "{safe_font}"',
    ]
    skin_block = "\n".join(skin_lines)

    stripped = source.lstrip()
    if not stripped.lower().startswith("@startuml"):
        return f"@startuml\n{skin_block}\n{source.rstrip()}\n@enduml\n"

    match = re.search(r"^@startuml[^\n]*\n", source, flags=re.MULTILINE | re.IGNORECASE)
    if match is None:
        # startuml 在首行但没匹配上（极少见），退化为包裹
        return f"@startuml\n{skin_block}\n{source.rstrip()}\n@enduml\n"
    insert_at = match.end()
    return source[:insert_at] + skin_block + "\n" + source[insert_at:]


def render_plantuml_to_svg(
    source: str,
    jar_path: Path,
    java_bin: str,
    background: str,
    font_name: str = DEFAULT_PLANTUML_FONT_NAME,
    timeout: int = 60,
) -> bytes:
    """调用本地 plantuml.jar 将单段 PlantUML 源码渲染为 SVG bytes

    Args:
        source: 原始 UML 源码（代码围栏内容）
        jar_path: plantuml.jar 绝对路径
        java_bin: java 可执行文件名或路径
        background: white / black / transparent
        font_name: 注入到 skinparam defaultFontName 的字体名
        timeout: subprocess 超时时间（秒）

    Returns:
        PlantUML 产出的 SVG 字节流

    Raises:
        QxwError: 渲染失败（非零退出码 / 超时 / stderr 有内容）
    """
    prepared = _prepare_plantuml_source(source, background=background, font_name=font_name)

    cmd = [
        java_bin,
        "-Djava.awt.headless=true",
        "-jar",
        str(jar_path),
        "-tsvg",
        "-charset",
        "UTF-8",
        "-pipe",
    ]

    try:
        proc = subprocess.run(
            cmd,
            input=prepared.encode("utf-8"),
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise QxwError(f"plantuml 渲染超时（{timeout}s）") from e
    except FileNotFoundError as e:
        raise QxwError(f"无法执行 java: {e}") from e

    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", errors="replace").strip()
        raise QxwError(f"plantuml 渲染失败 (exit={proc.returncode}): {stderr or '无错误输出'}")

    if not proc.stdout:
        stderr = proc.stderr.decode("utf-8", errors="replace").strip()
        raise QxwError(f"plantuml 未产出任何数据: {stderr or '无错误输出'}")

    return proc.stdout


# ============================================================
# 图片写盘（三种目标格式统一走 SVG 中间态）
# ============================================================


def _inject_svg_background_rect(svg_bytes: bytes, color: str) -> bytes:
    """在 <svg ...> 根节点开头插入一个全尺寸 rect 作为背景

    覆盖场景：SVG 目标输出下，为 white / black 背景预设提供稳定的底色。
    transparent 直接跳过（调用方负责）。
    """
    try:
        svg_text = svg_bytes.decode("utf-8")
    except UnicodeDecodeError:
        svg_text = svg_bytes.decode("utf-8", errors="replace")

    match = re.search(r"<svg\b[^>]*>", svg_text, flags=re.IGNORECASE)
    if not match:
        return svg_bytes

    rect = f'<rect width="100%" height="100%" fill="{color}"/>'
    insert_at = match.end()
    patched = svg_text[:insert_at] + rect + svg_text[insert_at:]
    return patched.encode("utf-8")


def write_image(
    svg_bytes: bytes,
    dest: Path,
    fmt: str,
    scale: float,
    font_family: str | None,
    background: str,
    quality: int,
) -> None:
    """把 plantuml 产出的 SVG bytes 按目标格式写到 dest

    统一逻辑：
    1. 先做中文字体注入（对 SVG/PNG/JPG 三路都生效）
    2. 按 fmt 分流：
       - svg：可选追加背景 rect，直接写文件
       - png：cairosvg.svg2png(bytestring=..., background_color=...)
       - jpg：cairosvg 栅格化到 PNG bytes，再用 PIL 合成背景并存 JPEG
    """
    if fmt not in SUPPORTED_FORMATS:
        raise QxwError(f"不支持的图片格式: {fmt}")
    if background not in SUPPORTED_BACKGROUNDS:
        raise QxwError(f"不支持的背景预设: {background}")

    stack = DEFAULT_SVG_CJK_FONT_FAMILY if font_family is None else font_family
    if stack:
        svg_bytes = _inject_svg_font_family(svg_bytes, stack)

    dest.parent.mkdir(parents=True, exist_ok=True)

    if fmt == "svg":
        if background != "transparent":
            svg_bytes = _inject_svg_background_rect(svg_bytes, _BG_HEX[background])
        dest.write_bytes(svg_bytes)
        return

    try:
        import cairosvg
    except ImportError as e:
        raise QxwError('需要安装 cairosvg: pip install cairosvg 或 pip install "qxw[image]"') from e

    if fmt == "png":
        cairosvg.svg2png(
            bytestring=svg_bytes,
            write_to=str(dest),
            scale=scale,
            background_color=_BG_HEX[background],
        )
        return

    # fmt == "jpg"
    try:
        from PIL import Image
    except ImportError as e:
        raise QxwError('需要安装 Pillow: pip install Pillow 或 pip install "qxw[image]"') from e

    png_buf = io.BytesIO()
    cairosvg.svg2png(
        bytestring=svg_bytes,
        write_to=png_buf,
        scale=scale,
        background_color=None,
    )
    png_buf.seek(0)

    if background == "transparent":
        logger.warning("JPG 不支持透明通道，已改用白色背景: %s", dest.name)
        bg_fill = (255, 255, 255)
    elif background == "black":
        bg_fill = (0, 0, 0)
    else:
        bg_fill = (255, 255, 255)

    with Image.open(png_buf) as im:
        im = im.convert("RGBA")
        canvas = Image.new("RGB", im.size, bg_fill)
        canvas.paste(im, mask=im.split()[-1])
        canvas.save(str(dest), "JPEG", quality=quality, progressive=True)


# ============================================================
# 主编排：Markdown → _wx.md + 图片
# ============================================================


@dataclass
class ConvertResult:
    """convert_markdown_for_wx 的返回值"""

    output_md: Path
    image_paths: list[Path]


def convert_markdown_for_wx(
    md_path: Path,
    fmt: str = "png",
    background: str = "white",
    out_path: Path | None = None,
    jar_path: Path | None = None,
    java_bin: str = "java",
    scale: float = 2.0,
    font_family: str | None = None,
    plantuml_font_name: str = DEFAULT_PLANTUML_FONT_NAME,
    quality: int = 92,
) -> ConvertResult:
    """将 Markdown 中的 PlantUML 代码围栏替换成图片引用，生成 _wx.md

    Args:
        md_path: 源 Markdown 文件绝对路径
        fmt: 目标图片格式（svg / png / jpg）
        background: 背景色预设（white / black / transparent）
        out_path: 输出 Markdown 路径；默认 <md 同目录>/<stem>_wx.md
        jar_path: plantuml.jar 路径；None 时读环境变量 PLANTUML_JAR，再退回 DEFAULT_JAR_PATH
        java_bin: java 可执行文件名/路径
        scale: PNG/JPG 的缩放比例（SVG 忽略）
        font_family: SVG 注入的 CSS CJK 字体栈（None 用默认；"" 禁用注入）
        plantuml_font_name: skinparam defaultFontName 值
        quality: JPG 压缩质量

    Returns:
        ConvertResult(output_md, image_paths)
    """
    if fmt not in SUPPORTED_FORMATS:
        raise QxwError(f"不支持的图片格式: {fmt}")
    if background not in SUPPORTED_BACKGROUNDS:
        raise QxwError(f"不支持的背景预设: {background}")
    if not md_path.is_file():
        raise QxwError(f"Markdown 文件不存在: {md_path}")

    if jar_path is None:
        env_jar = os.environ.get("PLANTUML_JAR")
        jar_path = Path(env_jar).expanduser() if env_jar else DEFAULT_JAR_PATH
    jar_path = jar_path.expanduser().resolve()
    _ensure_java_and_jar(jar_path, java_bin)

    md_text = md_path.read_text(encoding="utf-8")
    blocks = extract_plantuml_blocks(md_text)

    if out_path is None:
        out_path = md_path.with_name(f"{md_path.stem}_wx.md")
    out_path = out_path.expanduser().resolve()
    out_dir = out_path.parent

    if not blocks:
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path.write_text(md_text, encoding="utf-8")
        return ConvertResult(output_md=out_path, image_paths=[])

    image_paths: list[Path] = []
    # 按偏移从后向前替换，避免前面替换改变后面的 start/end
    new_md = md_text
    for index, block in enumerate(blocks, start=1):
        img_name = f"{md_path.stem}_{index}.{fmt}"
        img_path = out_dir / img_name

        svg_bytes = render_plantuml_to_svg(
            block.source,
            jar_path=jar_path,
            java_bin=java_bin,
            background=background,
            font_name=plantuml_font_name,
        )
        write_image(
            svg_bytes,
            dest=img_path,
            fmt=fmt,
            scale=scale,
            font_family=font_family,
            background=background,
            quality=quality,
        )
        image_paths.append(img_path)

    # 从后向前替换围栏
    for index, block in reversed(list(enumerate(blocks, start=1))):
        img_name = f"{md_path.stem}_{index}.{fmt}"
        replacement = f"{block.indent}![](./{img_name})"
        new_md = new_md[:block.start] + replacement + new_md[block.end:]

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path.write_text(new_md, encoding="utf-8")
    return ConvertResult(output_md=out_path, image_paths=image_paths)
