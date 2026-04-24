"""图片参数化调整服务

为 ``qxw-serve image-web`` 画廊页上的"调整"面板提供后端实现。15 个调整参数
（曝光 / 鲜明度 / 高光 / 阴影 / 对比度 / 亮度 / 黑点 / 饱和度 / 自然饱和度 /
色温 / 色调 / 锐度 / 清晰度 / 噪点消除 / 晕影）经 :class:`AdjustmentParams`
强类型校验后，传入 :func:`apply_adjustments` 在 NumPy 中实现。

设计约定：
- 锐度 / 清晰度 / 噪点消除 为强度型参数，取值范围 ``[0, 100]``（0 = 关闭）
- 其余均可双向调节，取值范围 ``[-100, 100]``（0 = 无改动）
- 所有调整都在 float32 sRGB 空间顺序应用，最后回到 uint8
- 全 0 参数走快速路径，直接返回输入（避免无意义的浮点往返）
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field, field_validator

from qxw.library.base.exceptions import QxwError, ValidationError
from qxw.library.base.logger import get_logger

if TYPE_CHECKING:
    import numpy as np

logger = get_logger("qxw.image.adjust")


# ============================================================
# 调整参数模型
# ============================================================


_BIDIRECTIONAL_FIELDS = (
    "exposure",
    "brilliance",
    "highlights",
    "shadows",
    "contrast",
    "brightness",
    "blacks",
    "saturation",
    "vibrance",
    "temperature",
    "tint",
    "vignette",
)

_UNIDIRECTIONAL_FIELDS = ("sharpness", "clarity", "noise_reduction")


class AdjustmentParams(BaseModel):
    """图片调整参数集合

    字段中文对照：

    - ``exposure``        曝光   [-100, 100]
    - ``brilliance``      鲜明度 [-100, 100]
    - ``highlights``      高光   [-100, 100]
    - ``shadows``         阴影   [-100, 100]
    - ``contrast``        对比度 [-100, 100]
    - ``brightness``      亮度   [-100, 100]
    - ``blacks``          黑点   [-100, 100]
    - ``saturation``      饱和度 [-100, 100]
    - ``vibrance``        自然饱和度 [-100, 100]
    - ``temperature``     色温   [-100, 100]
    - ``tint``            色调   [-100, 100]
    - ``vignette``        晕影   [-100, 100]
    - ``sharpness``       锐度   [0, 100]
    - ``clarity``         清晰度 [0, 100]
    - ``noise_reduction`` 噪点消除 [0, 100]
    """

    model_config = {"extra": "forbid"}

    exposure: float = Field(default=0.0, ge=-100.0, le=100.0)
    brilliance: float = Field(default=0.0, ge=-100.0, le=100.0)
    highlights: float = Field(default=0.0, ge=-100.0, le=100.0)
    shadows: float = Field(default=0.0, ge=-100.0, le=100.0)
    contrast: float = Field(default=0.0, ge=-100.0, le=100.0)
    brightness: float = Field(default=0.0, ge=-100.0, le=100.0)
    blacks: float = Field(default=0.0, ge=-100.0, le=100.0)
    saturation: float = Field(default=0.0, ge=-100.0, le=100.0)
    vibrance: float = Field(default=0.0, ge=-100.0, le=100.0)
    temperature: float = Field(default=0.0, ge=-100.0, le=100.0)
    tint: float = Field(default=0.0, ge=-100.0, le=100.0)
    vignette: float = Field(default=0.0, ge=-100.0, le=100.0)
    sharpness: float = Field(default=0.0, ge=0.0, le=100.0)
    clarity: float = Field(default=0.0, ge=0.0, le=100.0)
    noise_reduction: float = Field(default=0.0, ge=0.0, le=100.0)

    @field_validator(
        "exposure", "brilliance", "highlights", "shadows", "contrast",
        "brightness", "blacks", "saturation", "vibrance", "temperature",
        "tint", "vignette", "sharpness", "clarity", "noise_reduction",
        mode="before",
    )
    @classmethod
    def _reject_nan_inf(cls, v: object) -> object:
        import math

        if isinstance(v, float):
            if math.isnan(v):
                raise ValueError("参数不能为 NaN")
            if math.isinf(v):
                raise ValueError("参数不能为无穷大")
        return v

    def is_identity(self) -> bool:
        """是否所有参数都是默认值（即不应用任何调整）"""
        for name in _BIDIRECTIONAL_FIELDS + _UNIDIRECTIONAL_FIELDS:
            if getattr(self, name) != 0.0:
                return False
        return True


def parse_from_query(query: dict[str, list[str]]) -> AdjustmentParams:
    """从 ``urllib.parse.parse_qs`` 风格的字典构造 :class:`AdjustmentParams`

    - 多值时取第一个
    - 非数字时抛出 :class:`qxw.library.base.exceptions.ValidationError`
    - 未知键会被拒绝（由 ``model_config.extra="forbid"`` 负责）
    """
    from pydantic import ValidationError as _PydanticValidationError

    kwargs: dict[str, float] = {}
    for key, values in query.items():
        if not values:
            continue
        raw = values[0]
        try:
            kwargs[key] = float(raw)
        except (TypeError, ValueError) as e:
            raise ValidationError(f"参数 {key!r} 不是合法浮点数: {raw!r}") from e
    try:
        return AdjustmentParams(**kwargs)
    except _PydanticValidationError as e:
        raise ValidationError(f"参数校验失败: {e.errors()[0]['msg']}") from e


# ============================================================
# 主算法
# ============================================================


def apply_adjustments(rgb_u8: "np.ndarray", params: AdjustmentParams) -> "np.ndarray":
    """对 ``(H, W, 3) uint8`` 的 RGB 图像应用一组调整，返回 uint8

    所有调整都在顺序管线中完成，不追求与 Lightroom / 苹果照片完全一致，但力求
    方向正确、边界稳定、预览级别开销可控（1200px 长边下单次调用约 100ms 级）。

    - 曝光：线性空间乘 ``2**(v/50)``（±2 级）
    - 亮度：sRGB 空间加偏移 ``v/200``
    - 对比度：围绕 0.5 的线性伸缩
    - 鲜明度：提亮中间调、压暗极值的 S 曲线
    - 高光 / 阴影 / 黑点：按亮度 L 的区间软 mask 做加减
    - 饱和度 / 自然饱和度：HSV 的 S 通道缩放；自然饱和度对低饱和区更敏感
    - 色温：R+B- 交叉偏移（正值偏暖）
    - 色调：G 反向偏移（正值偏洋红）
    - 锐度：小半径 USM（半径 1）
    - 清晰度：大半径 USM（半径 5，强度减半）
    - 噪点消除：高斯模糊（最大 σ≈2）
    - 晕影：径向二次衰减（正值压暗边缘）

    Raises:
        ValidationError: 输入不是 3 通道 uint8、维度不对
        RuntimeError: NumPy 未安装
    """
    try:
        import numpy as np
    except ImportError as e:  # pragma: no cover - dependency missing
        raise RuntimeError("NumPy 未安装，无法执行图片调整") from e

    if not isinstance(rgb_u8, np.ndarray):
        raise ValidationError("输入必须是 numpy ndarray")
    if rgb_u8.dtype != np.uint8:
        raise ValidationError(f"输入 dtype 必须是 uint8，实际: {rgb_u8.dtype}")
    if rgb_u8.ndim != 3 or rgb_u8.shape[2] != 3:
        raise ValidationError(f"输入 shape 必须是 (H, W, 3)，实际: {rgb_u8.shape}")

    if params.is_identity():
        return rgb_u8.copy()

    from qxw.library.services.auto_enhance import (
        _gaussian_blur,
        _hsv_to_rgb,
        _linear_to_srgb,
        _rgb_to_hsv,
        _srgb_to_linear,
    )

    x = rgb_u8.astype(np.float32) / 255.0

    # 1. 曝光（线性空间乘 2^stops）
    if params.exposure != 0.0:
        stops = params.exposure / 50.0
        lin = _srgb_to_linear(x)
        lin = lin * np.float32(2.0 ** stops)
        x = _linear_to_srgb(np.clip(lin, 0.0, 1.0)).astype(np.float32)

    # 2. 对比度（围绕 0.5 线性伸缩）
    if params.contrast != 0.0:
        factor = np.float32(1.0 + params.contrast / 100.0)
        x = np.clip((x - 0.5) * factor + 0.5, 0.0, 1.0)

    # 3. 亮度（直接偏移）
    if params.brightness != 0.0:
        offset = np.float32(params.brightness / 200.0)
        x = np.clip(x + offset, 0.0, 1.0)

    # 4. 鲜明度：y = y + a * y * (1-y) * 2，中段提升、端点无改动
    if params.brilliance != 0.0:
        a = np.float32(params.brilliance / 100.0)
        x = np.clip(x + a * x * (1.0 - x) * 2.0 * 0.5, 0.0, 1.0)

    # 准备亮度 L 用于高光/阴影/黑点 mask
    if params.highlights != 0.0 or params.shadows != 0.0 or params.blacks != 0.0:
        luma = 0.2126 * x[..., 0] + 0.7152 * x[..., 1] + 0.0722 * x[..., 2]

    # 5. 高光：对 L > 0.5 的区域更敏感
    if params.highlights != 0.0:
        factor = np.float32(params.highlights / 100.0)
        mask = np.clip((luma - 0.5) / 0.5, 0.0, 1.0) ** 2
        x = np.clip(x + (factor * 0.3) * mask[..., None], 0.0, 1.0)

    # 6. 阴影：对 L < 0.5 的区域更敏感
    if params.shadows != 0.0:
        factor = np.float32(params.shadows / 100.0)
        mask = np.clip((0.5 - luma) / 0.5, 0.0, 1.0) ** 2
        x = np.clip(x + (factor * 0.3) * mask[..., None], 0.0, 1.0)

    # 7. 黑点：仅最暗的 20%
    if params.blacks != 0.0:
        factor = np.float32(params.blacks / 100.0)
        mask = np.clip((0.2 - luma) / 0.2, 0.0, 1.0) ** 2
        x = np.clip(x + (factor * 0.3) * mask[..., None], 0.0, 1.0)

    # 8. 饱和度 / 自然饱和度
    if params.saturation != 0.0 or params.vibrance != 0.0:
        hsv = _rgb_to_hsv(x)
        s = hsv[..., 1]
        if params.saturation != 0.0:
            s = s * np.float32(1.0 + params.saturation / 100.0)
        if params.vibrance != 0.0:
            v_amt = np.float32(params.vibrance / 100.0)
            s = s + v_amt * (1.0 - s) * 0.5
        hsv[..., 1] = np.clip(s, 0.0, 1.0)
        x = _hsv_to_rgb(hsv).astype(np.float32)

    # 9. 色温（R+ / B-）
    if params.temperature != 0.0:
        t = np.float32(params.temperature / 100.0 * 0.15)
        x[..., 0] = np.clip(x[..., 0] + t, 0.0, 1.0)
        x[..., 2] = np.clip(x[..., 2] - t, 0.0, 1.0)

    # 10. 色调（G-，即正值偏洋红）
    if params.tint != 0.0:
        t = np.float32(params.tint / 100.0 * 0.15)
        x[..., 1] = np.clip(x[..., 1] - t, 0.0, 1.0)

    # 11. 噪点消除（整体高斯模糊，最大 σ≈2）
    if params.noise_reduction > 0.0:
        sigma = float(params.noise_reduction / 100.0 * 2.0)
        x = _blur_rgb(x, sigma, _gaussian_blur)

    # 12. 锐度（小半径 USM）
    if params.sharpness > 0.0:
        amount = np.float32(params.sharpness / 100.0)
        blurred = _blur_rgb(x, 1.0, _gaussian_blur)
        x = np.clip(x + (x - blurred) * amount, 0.0, 1.0)

    # 13. 清晰度（大半径 USM，强度减半避免过锐）
    if params.clarity > 0.0:
        amount = np.float32(params.clarity / 100.0 * 0.5)
        blurred = _blur_rgb(x, 5.0, _gaussian_blur)
        x = np.clip(x + (x - blurred) * amount, 0.0, 1.0)

    # 14. 晕影（正值压暗边缘）
    if params.vignette != 0.0:
        h, w = x.shape[:2]
        ys = np.linspace(-1.0, 1.0, h, dtype=np.float32)
        xs = np.linspace(-1.0, 1.0, w, dtype=np.float32)
        yy, xx = np.meshgrid(ys, xs, indexing="ij")
        r = np.clip(np.sqrt(xx * xx + yy * yy) / np.float32(1.2), 0.0, 1.0)
        intensity = np.float32(params.vignette / 100.0)
        mask = 1.0 - intensity * (r * r)
        x = np.clip(x * mask[..., None], 0.0, 1.0)

    return (x * 255.0 + 0.5).clip(0.0, 255.0).astype(np.uint8)


# ============================================================
# 原尺寸保存
# ============================================================


def save_adjusted_image(
    src: Path,
    dst: Path,
    params: AdjustmentParams,
    *,
    quality: int = 92,
    preserve_exif: bool = True,
) -> None:
    """读取 ``src`` 原尺寸像素、应用 ``params``、以 JPEG 写入 ``dst``

    与 :func:`apply_adjustments` 共享同一套算法，区别在于不做降采样、输入走
    Pillow 完整解码路径，输出时会还原 EXIF 方向（orientation tag 清为 1，避免
    二次旋转）并写回其余 EXIF 元数据。

    Args:
        src: 原图绝对路径（必须已通过 :func:`qxw.library.services.image_service.get_viewable_path`
            规整到 Pillow 可直接 ``Image.open`` 的格式，例如 HEIC/RAW 预先转成
            中间 JPG 再传进来；这里不再重复做解码适配）
        dst: 目标 JPEG 路径（父目录会自动创建，若已存在会被覆盖）
        params: 与预览使用同一份 :class:`AdjustmentParams`
        quality: JPEG 压缩质量 1..100
        preserve_exif: 是否保留源图 EXIF（orientation 会被重置为 1）

    Raises:
        QxwError: 源文件不存在 / PIL 或 NumPy 缺失 / 无法解码图片
        ValidationError: ``quality`` 越界 / params 非法（由调用链上游捕获）
    """
    if not (1 <= int(quality) <= 100):
        raise ValidationError(f"JPEG quality 必须在 [1, 100]，收到 {quality}")
    if not src.exists():
        raise QxwError(f"源文件不存在: {src}", exit_code=2)

    try:
        import numpy as np
        from PIL import Image, ImageOps
    except ImportError as e:
        raise QxwError("缺少 Pillow / NumPy，无法保存调整图片") from e

    try:
        img = Image.open(src)
        img.load()
    except Exception as e:
        raise QxwError(f"无法打开源图片: {e}") from e

    exif_bytes: bytes | None = None
    if preserve_exif:
        raw = img.info.get("exif")
        if isinstance(raw, (bytes, bytearray)):
            exif_bytes = bytes(raw)

    # 按 EXIF orientation 旋转像素，随后再把 tag 清为 1（保存时 orientation=1）
    img = ImageOps.exif_transpose(img)

    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img.convert("RGBA"), mask=img.convert("RGBA").split()[-1])
        img = bg
    elif img.mode != "RGB":
        img = img.convert("RGB")

    rgb = np.asarray(img, dtype=np.uint8)
    rgb_out = apply_adjustments(rgb, params)

    dst.parent.mkdir(parents=True, exist_ok=True)

    save_kwargs: dict[str, object] = {"quality": int(quality), "progressive": True}
    if preserve_exif and exif_bytes:
        from qxw.library.services.image_service import _reset_exif_orientation

        save_kwargs["exif"] = _reset_exif_orientation(exif_bytes)

    Image.fromarray(rgb_out).save(str(dst), "JPEG", **save_kwargs)


def _blur_rgb(rgb: "np.ndarray", sigma: float, gauss: object) -> "np.ndarray":
    """对 (H, W, 3) float32 RGB 逐通道做 Gaussian blur"""
    import numpy as np

    if sigma <= 0:
        return rgb
    out = np.empty_like(rgb)
    for c in range(3):
        out[..., c] = gauss(rgb[..., c], sigma)  # type: ignore[operator]
    return out
