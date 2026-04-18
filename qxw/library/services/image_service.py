"""图片处理服务

提供 RAW 图片转换、缩略图生成、Live Photo 检测、调色预设等功能。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
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

# 默认参数
DEFAULT_THUMB_SIZE = (400, 400)
DEFAULT_THUMB_QUALITY = 85
DEFAULT_JPEG_QUALITY = 92


# ============================================================
# 数据模型
# ============================================================


class ColorPreset(str, Enum):
    """RAW 转换调色预设"""

    NATURAL = "natural"
    VIVID = "vivid"
    WARM = "warm"
    COOL = "cool"
    BW = "bw"
    FILM = "film"

    @property
    def label(self) -> str:
        """返回预设的中文名称"""
        return {
            "natural": "自然色彩",
            "vivid": "鲜艳",
            "warm": "暖色调",
            "cool": "冷色调",
            "bw": "黑白",
            "film": "胶片风格",
        }[self.value]

    @property
    def description(self) -> str:
        """返回预设的详细说明"""
        return {
            "natural": "使用相机白平衡，不做额外调色",
            "vivid": "提升饱和度和对比度，色彩更鲜明",
            "warm": "偏暖色调，适合人像和日落场景",
            "cool": "偏冷色调，适合风景和建筑场景",
            "bw": "经典黑白，带轻微对比度增强",
            "film": "模拟胶片质感，低对比度偏暖",
        }[self.value]


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
# RAW 转换
# ============================================================


def convert_raw(
    raw_path: Path,
    output_path: Path,
    preset: ColorPreset = ColorPreset.NATURAL,
    quality: int = DEFAULT_JPEG_QUALITY,
) -> None:
    """将 RAW 文件转换为 JPG

    使用 rawpy 解析 RAW 数据，应用指定调色预设后保存为 JPEG。

    Args:
        raw_path: RAW 文件路径
        output_path: 输出 JPG 路径
        preset: 调色预设
        quality: JPEG 压缩质量 (1-100)

    Raises:
        ImportError: rawpy 或 Pillow 未安装
        Exception: 转换失败
    """
    import rawpy
    from PIL import Image

    with rawpy.imread(str(raw_path)) as raw:
        rgb = raw.postprocess(
            use_camera_wb=True,
            gamma=(2.222, 4.5),
            output_color=rawpy.ColorSpace.sRGB,
            output_bps=8,
            no_auto_bright=True,
        )

    img = Image.fromarray(rgb)
    img = _apply_preset(img, preset)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(output_path), "JPEG", quality=quality, progressive=True)


# ============================================================
# 调色预设实现
# ============================================================


def _apply_preset(img: "Image.Image", preset: ColorPreset) -> "Image.Image":
    """应用调色预设到 PIL Image

    Args:
        img: 输入图片（RGB 模式）
        preset: 调色预设

    Returns:
        处理后的图片
    """
    from PIL import Image, ImageEnhance, ImageOps

    match preset:
        case ColorPreset.NATURAL:
            return img

        case ColorPreset.VIVID:
            # 鲜艳：提升对比度 +20%、饱和度 +30%
            img = ImageEnhance.Contrast(img).enhance(1.2)
            img = ImageEnhance.Color(img).enhance(1.3)
            return img

        case ColorPreset.WARM:
            # 暖色调：增强红色通道、减弱蓝色通道、轻微提亮
            r, g, b = img.split()
            r = r.point(lambda x: min(255, int(x * 1.08)))
            b = b.point(lambda x: int(x * 0.92))
            img = Image.merge("RGB", (r, g, b))
            img = ImageEnhance.Brightness(img).enhance(1.03)
            return img

        case ColorPreset.COOL:
            # 冷色调：减弱红色通道、增强蓝色通道
            r, g, b = img.split()
            r = r.point(lambda x: int(x * 0.93))
            b = b.point(lambda x: min(255, int(x * 1.07)))
            img = Image.merge("RGB", (r, g, b))
            return img

        case ColorPreset.BW:
            # 黑白：灰度化后轻微增强对比度
            img = ImageOps.grayscale(img).convert("RGB")
            img = ImageEnhance.Contrast(img).enhance(1.1)
            return img

        case ColorPreset.FILM:
            # 胶片：降低对比度、偏暖色、降低饱和度、轻微提亮
            img = ImageEnhance.Contrast(img).enhance(0.88)
            r, g, b = img.split()
            r = r.point(lambda x: min(255, int(x * 1.04)))
            b = b.point(lambda x: int(x * 0.96))
            img = Image.merge("RGB", (r, g, b))
            img = ImageEnhance.Color(img).enhance(0.88)
            img = ImageEnhance.Brightness(img).enhance(1.02)
            return img

    return img


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
                no_auto_bright=True,
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
