"""图片处理服务

提供缩略图生成、Live Photo 检测、浏览器可显示格式转换等功能。
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
