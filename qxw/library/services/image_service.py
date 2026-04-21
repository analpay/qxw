"""图片处理服务

提供缩略图生成、Live Photo 检测、浏览器可显示格式转换、RAW 批量转换等功能。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from qxw.library.base.logger import get_logger

if TYPE_CHECKING:
    from PIL import Image

logger = get_logger("qxw.image")

# ============================================================
# 常量定义
# ============================================================

# 支持的 RAW 格式
RAW_EXTENSIONS = frozenset({
    ".cr2", ".cr3",          # Canon
    ".nef", ".nrw",          # Nikon
    ".arw", ".srf", ".sr2",  # Sony
    ".dng",                  # Adobe / 通用
    ".orf",                  # Olympus
    ".rw2",                  # Panasonic
    ".pef",                  # Pentax
    ".raf",                  # Fujifilm
    ".3fr",                  # Hasselblad
    ".iiq",                  # Phase One
    ".rwl",                  # Leica
    ".srw",                  # Samsung
    ".x3f",                  # Sigma
})

# 浏览器可直接显示的图片格式
WEB_FRIENDLY_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"})

# 所有支持的图片格式（含 RAW）
IMAGE_EXTENSIONS = frozenset(
    {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".tif", ".heic", ".heif"} | RAW_EXTENSIONS
)

# Live Photo 关联的视频格式
VIDEO_EXTENSIONS = frozenset({".mov", ".mp4"})

# `qxw-image filter` 子命令可直接套用调色滤镜的位图格式（不含 RAW）
FILTERABLE_IMAGE_EXTENSIONS = frozenset({
    ".jpg", ".jpeg", ".png", ".webp", ".bmp",
    ".tiff", ".tif", ".heic", ".heif",
})

# SVG 矢量图格式
SVG_EXTENSIONS = frozenset({".svg"})

# 默认参数
DEFAULT_THUMB_SIZE = (400, 400)
DEFAULT_THUMB_QUALITY = 85
DEFAULT_JPEG_QUALITY = 92


# ============================================================
# 数据模型
# ============================================================


@dataclass
class ImageEntry:
    """图片文件条目"""

    path: Path             # 绝对路径
    rel_path: str          # 相对于基目录的路径
    name: str              # 文件名
    size: int              # 字节数
    is_raw: bool = False
    live_video_path: Path | None = None   # 关联的 Live Photo 视频绝对路径
    live_video_rel: str | None = None     # 关联视频的相对路径

    @property
    def is_live(self) -> bool:
        """是否为 Live Photo"""
        return self.live_video_path is not None

    @property
    def is_web_friendly(self) -> bool:
        """浏览器是否可直接显示"""
        return self.path.suffix.lower() in WEB_FRIENDLY_EXTENSIONS


# ============================================================
# 图片扫描与 Live Photo 检测
# ============================================================


def scan_images(directory: Path, recursive: bool = True) -> list[ImageEntry]:
    """扫描目录获取所有图片文件，自动检测 Live Photo 配对

    Live Photo 配对规则：同目录下同名的图片文件和视频文件自动配对
    （如 IMG_0001.heic + IMG_0001.mov）。

    Args:
        directory: 要扫描的目录
        recursive: 是否递归扫描子目录

    Returns:
        按文件名排序的 ImageEntry 列表
    """
    directory = directory.resolve()
    entries: list[ImageEntry] = []
    # key = "{parent_dir}/{stem_lower}" → video Path
    videos: dict[str, Path] = {}

    # 收集所有文件
    all_files = list(directory.rglob("*")) if recursive else list(directory.iterdir())

    # 第一遍：索引视频文件（用于 Live Photo 配对）
    for f in all_files:
        if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS:
            pair_key = f"{f.parent.resolve()}/{f.stem.lower()}"
            videos[pair_key] = f

    # 第二遍：收集图片文件并配对
    for f in sorted(all_files, key=lambda x: x.name.lower()):
        if not f.is_file():
            continue
        suffix = f.suffix.lower()
        if suffix not in IMAGE_EXTENSIONS:
            continue
        # 跳过隐藏文件和缩略图缓存
        if f.name.startswith("."):
            continue

        rel = str(f.relative_to(directory))
        stat = f.stat()
        is_raw = suffix in RAW_EXTENSIONS

        # 检测 Live Photo 配对
        pair_key = f"{f.parent.resolve()}/{f.stem.lower()}"
        video = videos.get(pair_key)
        video_rel = str(video.relative_to(directory)) if video else None

        entries.append(ImageEntry(
            path=f.resolve(),
            rel_path=rel,
            name=f.name,
            size=stat.st_size,
            is_raw=is_raw,
            live_video_path=video,
            live_video_rel=video_rel,
        ))

    return entries


def scan_svg_files(directory: Path, recursive: bool = True) -> list[Path]:
    """扫描目录获取所有 SVG 文件

    Args:
        directory: 要扫描的目录
        recursive: 是否递归扫描子目录

    Returns:
        按文件名排序的 SVG 文件路径列表
    """
    directory = directory.resolve()
    all_files = list(directory.rglob("*")) if recursive else list(directory.iterdir())
    svg_files = [
        f for f in all_files
        if f.is_file() and f.suffix.lower() in SVG_EXTENSIONS and not f.name.startswith(".")
    ]
    return sorted(svg_files, key=lambda x: x.name.lower())


def scan_raw_files(directory: Path, recursive: bool = False) -> list[Path]:
    """扫描目录获取所有 RAW 文件

    Args:
        directory: 要扫描的目录
        recursive: 是否递归扫描子目录

    Returns:
        按文件名排序的 RAW 文件路径列表
    """
    directory = directory.resolve()
    all_files = list(directory.rglob("*")) if recursive else list(directory.iterdir())
    raw_files = [
        f for f in all_files
        if f.is_file() and f.suffix.lower() in RAW_EXTENSIONS and not f.name.startswith(".")
    ]
    return sorted(raw_files, key=lambda x: x.name.lower())


def scan_filterable_images(directory: Path, recursive: bool = False) -> list[Path]:
    """扫描目录获取所有可进入 ``qxw-image filter`` 流水线的位图文件（不含 RAW）

    仅返回 :data:`FILTERABLE_IMAGE_EXTENSIONS` 列出的常规位图格式；RAW 文件需要
    先经过 ``qxw-image raw`` 解码成 JPG，或直接使用 ``qxw-image raw --filter``
    一步到位，以避免二次编解码造成的画质损失。
    """
    directory = directory.resolve()
    all_files = list(directory.rglob("*")) if recursive else list(directory.iterdir())
    files = [
        f for f in all_files
        if f.is_file()
        and f.suffix.lower() in FILTERABLE_IMAGE_EXTENSIONS
        and not f.name.startswith(".")
    ]
    return sorted(files, key=lambda x: x.name.lower())


# ============================================================
# RAW 转 JPG
# ============================================================


def convert_raw(
    raw_path: Path,
    output_path: Path,
    quality: int = DEFAULT_JPEG_QUALITY,
    use_embedded: bool = True,
    fast: bool = False,
    color_filter: str = "default",
) -> None:
    """将 RAW 文件转换为 JPG

    默认优先提取 RAW 文件内嵌的 JPEG 预览（相机直出色彩、色调曲线与
    Finder/Preview 显示一致）；嵌入预览缺失或尺寸过小时，退化为
    rawpy 重新解码（sRGB/8bit/相机白平衡/自动亮度）。

    Args:
        raw_path: RAW 文件路径
        output_path: 输出 JPG 路径
        quality: JPEG 压缩质量 (1-100)。仅在 rawpy 解码路径下生效；
            使用相机嵌入预览时直接沿用原始 JPEG 字节，保留相机直出画质与 EXIF。
        use_embedded: 是否优先使用相机内嵌 JPEG 预览。关闭时始终走 rawpy 解码。
        fast: 启用快速解码（线性去马赛克 + 半分辨率），约 8-10x 加速，
            仅对 rawpy 解码路径生效；嵌入预览路径始终写入原字节，不受影响。
        color_filter: 调色滤镜名。``default`` 表示不调色（保留历史行为）；
            其他值将在 rawpy 解码后对 RGB 数组套用对应滤镜。调色依赖像素级
            访问，与嵌入预览路径互斥；当 ``color_filter`` 非 ``default`` 时，
            即使 ``use_embedded=True`` 也会自动走 rawpy 解码路径（CLI 层负责
            拦截用户显式指定 ``--use-embedded`` 的情况）。

    Raises:
        ImportError: rawpy 或 Pillow 未安装
        Exception: 转换失败
    """
    import io

    import rawpy
    from PIL import Image

    from qxw.library.services.color_filters import apply_filter, get_filter

    filter_fn = get_filter(color_filter)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with rawpy.imread(str(raw_path)) as raw:
        # 仅当未启用调色时才允许走嵌入预览（原字节直写，无法套用滤镜）
        if use_embedded and filter_fn is None:
            # 优先使用相机内置的 JPEG 预览，与相机直出色彩一致
            thumb = None
            try:
                thumb = raw.extract_thumb()
            except (rawpy.LibRawNoThumbnailError, rawpy.LibRawUnsupportedThumbnailError):
                pass

            if thumb is not None and thumb.format == rawpy.ThumbFormat.JPEG:
                # 嵌入预览长边 >= 1000px 才采用，避免老相机只带 160x120 小图
                preview_img = Image.open(io.BytesIO(thumb.data))
                if max(preview_img.size) >= 1000:
                    output_path.write_bytes(thumb.data)
                    return

        # rawpy 解码路径：不含相机厂商调色，由 --quality 控制 JPEG 压缩
        postprocess_kwargs = {
            "use_camera_wb": True,
            "gamma": (2.222, 4.5),
            "output_color": rawpy.ColorSpace.sRGB,
            "output_bps": 8,
            "no_auto_bright": False,
        }
        if fast:
            postprocess_kwargs["demosaic_algorithm"] = rawpy.DemosaicAlgorithm.LINEAR
            postprocess_kwargs["half_size"] = True

        rgb = raw.postprocess(**postprocess_kwargs)

    if filter_fn is not None:
        rgb = apply_filter(rgb, color_filter)

    Image.fromarray(rgb).save(str(output_path), "JPEG", quality=quality, progressive=True)


# ============================================================
# 对已有位图套用调色滤镜
# ============================================================


def apply_filter_to_image(
    src: Path,
    dst: Path,
    filter_name: str,
    quality: int = DEFAULT_JPEG_QUALITY,
) -> None:
    """对已有位图文件应用命名调色滤镜，并以 JPEG 格式写入目标路径

    与 :func:`convert_raw` 的 ``color_filter`` 参数共享同一个滤镜注册中心
    （:mod:`qxw.library.services.color_filters`），但路径不同：
    本函数**不碰 RAW**，只接受 :data:`FILTERABLE_IMAGE_EXTENSIONS` 列出的
    位图格式（JPG/PNG/WebP/BMP/TIFF/HEIC）。

    Args:
        src: 源图片文件路径
        dst: 目标 JPG 输出路径（若父目录不存在会自动创建）
        filter_name: 调色滤镜名。``default`` 或未注册名会抛出 ValueError，
            避免出现 "运行了半天没效果" 的静默陷阱
        quality: JPEG 压缩质量 (1-100)

    Raises:
        ValueError: filter_name 为 default 或未注册
        Exception: 文件打开 / 解码 / 编码失败
    """
    import numpy as np
    from PIL import Image

    from qxw.library.services.color_filters import (
        DEFAULT_FILTER_NAME,
        apply_filter,
        get_filter,
    )

    fn = get_filter(filter_name)
    if fn is None:
        if (filter_name or "").strip().lower() == DEFAULT_FILTER_NAME:
            raise ValueError(
                f"{DEFAULT_FILTER_NAME!r} 是无操作占位名，请指定具体的滤镜名"
            )
        raise ValueError(f"未知的调色滤镜: {filter_name!r}")

    suffix = src.suffix.lower()
    if suffix in (".heic", ".heif"):
        img = _open_heic_as_pil(src)
        if img is None:
            raise RuntimeError(f"无法打开 HEIC/HEIF 文件: {src}")
    else:
        img = Image.open(src)

    if img.mode != "RGB":
        img = img.convert("RGB")

    rgb = np.asarray(img, dtype=np.uint8)
    rgb = apply_filter(rgb, filter_name)

    dst.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgb).save(str(dst), "JPEG", quality=quality, progressive=True)


# ============================================================
# SVG 转 PNG
# ============================================================


# 跨平台 CJK 字体栈：macOS(PingFang/Hiragino) → Windows(YaHei/SimHei)
# → Linux(Noto/Source Han/WenQuanYi) → 通用 sans-serif 兜底
DEFAULT_SVG_CJK_FONT_FAMILY = (
    '"PingFang SC", "PingFang TC", "Hiragino Sans GB", "Heiti SC", '
    '"Microsoft YaHei", "SimHei", '
    '"Noto Sans CJK SC", "Noto Sans SC", "Source Han Sans SC", '
    '"WenQuanYi Zen Hei", "WenQuanYi Micro Hei", sans-serif'
)


def _inject_svg_font_family(svg_bytes: bytes, font_family: str) -> bytes:
    """在 SVG 根节点开头注入 CSS，把 text/tspan 的 font-family 覆盖为含 CJK 字形的字体栈

    使用 `!important` 覆盖内联 style 与 presentation 属性，确保即使 SVG 声明了
    缺少 CJK 字形的字体也能正确回退渲染。若 SVG 中找不到 <svg ...> 根节点则原样返回。
    """
    import re

    try:
        svg_text = svg_bytes.decode("utf-8")
    except UnicodeDecodeError:
        svg_text = svg_bytes.decode("utf-8", errors="replace")

    match = re.search(r"<svg\b[^>]*>", svg_text, flags=re.IGNORECASE)
    if not match:
        return svg_bytes

    css_block = (
        "<style type=\"text/css\"><![CDATA["
        f"text, tspan, textPath {{ font-family: {font_family} !important; }}"
        "]]></style>"
    )
    insert_at = match.end()
    patched = svg_text[:insert_at] + css_block + svg_text[insert_at:]
    return patched.encode("utf-8")


def convert_svg_to_png(
    svg_path: Path,
    output_path: Path,
    scale: float = 2.0,
    font_family: str | None = None,
    background_color: str | None = None,
) -> None:
    """将 SVG 文件转换为 PNG

    使用 cairosvg 按给定缩放比例栅格化 SVG；当 SVG 未声明 width/height 时
    cairosvg 会按默认视口渲染，再乘以 scale 得到最终像素尺寸。

    为避免中文等 CJK 字符渲染成方块（豆腐），默认会向 SVG 注入一段 CSS，
    把 text/tspan 的 font-family 强制覆盖为跨平台的 CJK 字体栈。

    Args:
        svg_path: SVG 文件路径
        output_path: 输出 PNG 路径
        scale: 输出缩放比例（默认 2.0 适配高 DPI 屏）
        font_family: 自定义字体栈（CSS font-family 语法）。传入空串可禁用注入。
        background_color: 背景色（CSS 颜色，如 "#ffffff"）。为 None 或空串则保持透明。

    Raises:
        ImportError: cairosvg 未安装
        Exception: 转换失败
    """
    import cairosvg

    output_path.parent.mkdir(parents=True, exist_ok=True)

    bg = background_color or None
    stack = DEFAULT_SVG_CJK_FONT_FAMILY if font_family is None else font_family
    if stack:
        svg_bytes = _inject_svg_font_family(svg_path.read_bytes(), stack)
        cairosvg.svg2png(
            bytestring=svg_bytes, write_to=str(output_path), scale=scale, background_color=bg
        )
    else:
        cairosvg.svg2png(
            url=str(svg_path), write_to=str(output_path), scale=scale, background_color=bg
        )


# ============================================================
# 缩略图生成
# ============================================================


def generate_thumbnail(
    image_path: Path,
    thumb_path: Path,
    size: tuple[int, int] = DEFAULT_THUMB_SIZE,
    quality: int = DEFAULT_THUMB_QUALITY,
) -> bool:
    """为图片生成 JPEG 缩略图

    支持常见图片格式，RAW 格式需要安装 rawpy，HEIC 格式需要安装 pillow-heif。
    生成失败时返回 False 并记录日志，不抛出异常。

    Args:
        image_path: 原图路径
        thumb_path: 缩略图保存路径
        size: 缩略图最大尺寸 (宽, 高)
        quality: JPEG 压缩质量 (1-100)

    Returns:
        是否成功生成
    """
    # 检查缓存有效性：缩略图存在且比原图新则直接返回
    if thumb_path.exists():
        try:
            if thumb_path.stat().st_mtime >= image_path.stat().st_mtime:
                return True
        except OSError:
            pass

    try:
        from PIL import Image
    except ImportError:
        logger.warning("Pillow 未安装，无法生成缩略图")
        return False

    try:
        suffix = image_path.suffix.lower()

        if suffix in RAW_EXTENSIONS:
            img = _open_raw_as_pil(image_path)
        elif suffix in (".heic", ".heif"):
            img = _open_heic_as_pil(image_path)
        else:
            img = Image.open(image_path)

        if img is None:
            return False

        # RGBA / 调色板模式转 RGB
        if img.mode in ("RGBA", "P", "LA"):
            img = img.convert("RGB")
        elif img.mode != "RGB":
            img = img.convert("RGB")

        img.thumbnail(size, Image.LANCZOS)
        thumb_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(str(thumb_path), "JPEG", quality=quality, progressive=True)
        return True

    except Exception as e:
        logger.warning("缩略图生成失败 %s: %s", image_path.name, e)
        return False


def get_viewable_path(
    image_path: Path,
    cache_dir: Path,
    base_dir: Path,
    quality: int = DEFAULT_JPEG_QUALITY,
) -> Path | None:
    """获取浏览器可显示的图片路径

    对于浏览器原生支持的格式（JPG/PNG/GIF/WebP/BMP），直接返回原文件路径。
    对于其他格式（HEIC/TIFF/RAW），转换为 JPEG 并缓存，返回缓存路径。

    Args:
        image_path: 原图绝对路径
        cache_dir: 缓存目录根路径
        base_dir: 图片基目录（用于计算相对路径）
        quality: JPEG 压缩质量

    Returns:
        可供浏览器显示的文件路径，失败返回 None
    """
    suffix = image_path.suffix.lower()
    if suffix in WEB_FRIENDLY_EXTENSIONS:
        return image_path

    # 计算缓存路径
    rel = image_path.relative_to(base_dir)
    cache_path = cache_dir / rel.with_suffix(".jpg")

    # 检查缓存有效性
    if cache_path.exists():
        try:
            if cache_path.stat().st_mtime >= image_path.stat().st_mtime:
                return cache_path
        except OSError:
            pass

    try:
        from PIL import Image
    except ImportError:
        return None

    try:
        if suffix in RAW_EXTENSIONS:
            img = _open_raw_as_pil(image_path)
        elif suffix in (".heic", ".heif"):
            img = _open_heic_as_pil(image_path)
        else:
            img = Image.open(image_path)

        if img is None:
            return None

        if img.mode in ("RGBA", "P", "LA"):
            img = img.convert("RGB")
        elif img.mode != "RGB":
            img = img.convert("RGB")

        cache_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(str(cache_path), "JPEG", quality=quality, progressive=True)
        return cache_path

    except Exception as e:
        logger.warning("图片转换失败 %s: %s", image_path.name, e)
        return None


# ============================================================
# 内部辅助函数
# ============================================================


def _open_raw_as_pil(image_path: Path) -> "Image.Image | None":
    """使用 rawpy 打开 RAW 文件并返回 PIL Image"""
    try:
        import rawpy
        from PIL import Image
    except ImportError:
        logger.warning("rawpy 未安装，跳过 RAW 文件: %s", image_path.name)
        return None

    try:
        with rawpy.imread(str(image_path)) as raw:
            rgb = raw.postprocess(
                use_camera_wb=True,
                gamma=(2.222, 4.5),
                output_color=rawpy.ColorSpace.sRGB,
                output_bps=8,
                no_auto_bright=False,
            )
        return Image.fromarray(rgb)
    except Exception as e:
        logger.warning("RAW 文件读取失败 %s: %s", image_path.name, e)
        return None


def _open_heic_as_pil(image_path: Path) -> "Image.Image | None":
    """打开 HEIC 文件并返回 PIL Image"""
    try:
        from PIL import Image
        from pillow_heif import register_heif_opener
        register_heif_opener()
    except ImportError:
        logger.warning("pillow-heif 未安装，跳过 HEIC 文件: %s", image_path.name)
        return None

    try:
        return Image.open(image_path)
    except Exception as e:
        logger.warning("HEIC 文件读取失败 %s: %s", image_path.name, e)
        return None


def human_size(size: int) -> str:
    """将字节数格式化为人类可读的大小"""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024:
            return f"{size:.1f} {unit}" if unit != "B" else f"{size} {unit}"
        size /= 1024
    return f"{size:.1f} PB"
