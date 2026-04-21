"""调色滤镜插件系统

提供一个可扩展的色彩滤镜注册中心，用于在 RGB 像素层做二次调色，模拟不同
相机 / 胶片 / 动画的色彩风格（如富士 Classic Chrome、吉卜力水彩感）。

使用入口
--------
- :func:`qxw.library.services.image_service.convert_raw`（由
  ``qxw-image raw --filter <name>`` 调用）：RAW → rawpy 解码 → 调色 → JPEG，
  单遍流水线，画质最佳
- :func:`qxw.library.services.image_service.apply_filter_to_image`（由
  ``qxw-image filter -n <name>`` 调用）：位图 → PIL 解码 → 调色 → JPEG，
  适合对已导出 JPG / 截图 / 手机图批量再调色

两个入口共享本模块的同一套插件注册表。

插件约定
--------
- 每个滤镜是一个函数：``(rgb: np.ndarray) -> np.ndarray``
- 输入 / 输出均为 uint8 RGB 三通道数组，形状 ``(H, W, 3)``
- 通过 :func:`register_filter` 装饰器注册自定义滤镜
- 通过 :func:`apply_filter` 应用滤镜，:func:`list_filters` 列出全部已注册名称
- 预留名 ``default``：表示"不做任何调色"（no-op）

扩展方式
--------
第三方包可在导入时调用 :func:`register_filter` 追加滤镜；命令行
``--filter <name>`` / ``-n <name>`` 会在运行时按名称查找，因此只要在命令
执行前完成注册即可。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from qxw.library.base.logger import get_logger

if TYPE_CHECKING:
    import numpy as np

logger = get_logger("qxw.image.filter")

# 滤镜签名：(rgb uint8 HxWx3) -> rgb uint8 HxWx3
ColorFilterFn = Callable[["np.ndarray"], "np.ndarray"]

# 全局注册中心
_FILTER_REGISTRY: dict[str, ColorFilterFn] = {}

# 预留名：default 表示不调色
DEFAULT_FILTER_NAME = "default"


def register_filter(name: str) -> Callable[[ColorFilterFn], ColorFilterFn]:
    """装饰器：注册一个调色滤镜到全局注册中心

    Args:
        name: 滤镜名称（大小写不敏感，统一转小写）。不可使用保留名 ``default``。

    Raises:
        ValueError: 名称为空、与保留名冲突或已被注册
    """
    key = (name or "").strip().lower()
    if not key:
        raise ValueError("滤镜名称不能为空")
    if key == DEFAULT_FILTER_NAME:
        raise ValueError(f"{DEFAULT_FILTER_NAME!r} 是保留名，不能用于自定义滤镜")
    if key in _FILTER_REGISTRY:
        raise ValueError(f"滤镜名称重复: {key}")

    def _decorator(fn: ColorFilterFn) -> ColorFilterFn:
        _FILTER_REGISTRY[key] = fn
        return fn

    return _decorator


def list_filters() -> list[str]:
    """返回所有可选滤镜名（含 ``default``），按字母序排列"""
    return sorted({DEFAULT_FILTER_NAME, *_FILTER_REGISTRY.keys()})


def get_filter(name: str) -> ColorFilterFn | None:
    """按名称查找滤镜函数；``default`` 或未知名称返回 None"""
    key = (name or "").strip().lower()
    if not key or key == DEFAULT_FILTER_NAME:
        return None
    return _FILTER_REGISTRY.get(key)


def apply_filter(rgb: "np.ndarray", name: str) -> "np.ndarray":
    """按名称将滤镜应用到 RGB 数组

    ``default`` 或未注册名直接返回原数组。输入被视为只读：滤镜内部若需
    修改应自行拷贝或转浮点再裁剪回 uint8。
    """
    fn = get_filter(name)
    if fn is None:
        return rgb
    return fn(rgb)


# ============================================================
# 预置滤镜：富士 Classic Chrome
# ============================================================


@register_filter("fuji-cc")
def _fuji_classic_chrome(rgb: "np.ndarray") -> "np.ndarray":
    """富士 Classic Chrome（经典正片）近似滤镜

    参考富士 Classic Chrome 胶片模拟的典型视觉特征，用纯 numpy 做一个
    轻量近似，**不是**精确的色彩科学还原，而是一组互相协调的调整：

    1. S 曲线：抬升阴影、压缩高光，整体更"平"但保留暗部细节
    2. 整体饱和度下调至约 0.8（Classic Chrome 的"寡淡"感来源）
    3. 红 / 橙通道进一步降饱和（富士 CC 对肤色与红旗色特别收敛）
    4. Split-tone：阴影偏暖（加红 / 减蓝）、高光偏冷（减红 / 加蓝）
    5. 绿色推向青色方向（新闻纪实感）
    """
    import numpy as np

    arr = rgb.astype(np.float32) / 255.0

    # 1) S 曲线（抬黑 + 压白）
    tone_x = np.array([0.0, 0.15, 0.50, 0.85, 1.0], dtype=np.float32)
    tone_y = np.array([0.04, 0.18, 0.50, 0.82, 0.96], dtype=np.float32)
    for c in range(3):
        arr[..., c] = np.interp(arr[..., c], tone_x, tone_y)

    # 2) 整体降饱和
    gray = (
        0.299 * arr[..., 0:1]
        + 0.587 * arr[..., 1:2]
        + 0.114 * arr[..., 2:3]
    )
    arr = gray + (arr - gray) * 0.82

    # 3) Split-tone：按亮度蒙版分别加暖 / 加冷
    lum = 0.299 * arr[..., 0] + 0.587 * arr[..., 1] + 0.114 * arr[..., 2]
    shadow_mask = np.clip(1.0 - lum * 1.8, 0.0, 1.0)[..., None]
    highlight_mask = np.clip((lum - 0.55) * 1.8, 0.0, 1.0)[..., None]
    warm_tint = np.array([0.020, 0.008, -0.012], dtype=np.float32)
    cool_tint = np.array([-0.012, 0.000, 0.015], dtype=np.float32)
    arr = arr + shadow_mask * warm_tint + highlight_mask * cool_tint

    # 4) 红 / 橙区域再降点饱和
    r = arr[..., 0]
    g = arr[..., 1]
    b = arr[..., 2]
    red_mask = np.clip((r - g) * 4.0, 0.0, 1.0)
    gray_1c = gray[..., 0]
    arr[..., 0] = r - red_mask * (r - gray_1c) * 0.12

    # 5) 绿色向青偏
    green_dom = np.clip(g - np.maximum(r, b), 0.0, 1.0)
    arr[..., 2] = b + green_dom * 0.04
    arr[..., 1] = g - green_dom * 0.015

    return np.clip(arr * 255.0, 0.0, 255.0).astype(np.uint8)


@register_filter("ghibli")
def _ghibli(rgb: "np.ndarray") -> "np.ndarray":
    """吉卜力 / 宫崎骏动画近似滤镜

    参考工作室吉卜力动画的典型视觉语言（水彩 / 水粉 + 自然色板）做的近似调色：

    1. 抬黑 + 压白：无纯黑、高光柔和，模仿水彩 / 水粉的"无金属光泽"质感
    2. 整体轻微降饱和 (~0.92) + 全局淡淡暖色偏移：golden-hour 梦感
    3. 天空蓝柔化：推向 #D2E3EF / #a3c5e0 这类吉卜力"清澈天空"色
    4. 绿植物增饱和 + 偏黄：森林、草原的温暖绿感
    5. 阴影轻微偏冷紫 / 蓝：plein-air 写生常用手法，增加湿润与层次
    """
    import numpy as np

    arr = rgb.astype(np.float32) / 255.0

    # 1) 抬黑 + 柔压白（水彩曲线）
    tone_x = np.array([0.0, 0.20, 0.50, 0.80, 1.0], dtype=np.float32)
    tone_y = np.array([0.08, 0.26, 0.54, 0.83, 0.95], dtype=np.float32)
    for c in range(3):
        arr[..., c] = np.interp(arr[..., c], tone_x, tone_y)

    # 2) 轻微降饱和，整体偏暖
    gray = (
        0.299 * arr[..., 0:1]
        + 0.587 * arr[..., 1:2]
        + 0.114 * arr[..., 2:3]
    )
    arr = gray + (arr - gray) * 0.92
    warm_shift = np.array([0.012, 0.006, -0.010], dtype=np.float32)
    arr = arr + warm_shift

    r = arr[..., 0]
    g = arr[..., 1]
    b = arr[..., 2]

    # 3) 天空柔化：B 主导区域 → 推向柔和粉彩蓝
    sky_mask = np.clip((b - np.maximum(r, g)) * 3.0, 0.0, 1.0)
    arr[..., 0] = r + sky_mask * (0.78 - r) * 0.18
    arr[..., 1] = g + sky_mask * (0.88 - g) * 0.15

    # 4) 绿植：G 主导区域 → 更暖的绿（加点红；绿通道略加）
    green_dom = np.clip(g - np.maximum(r, b), 0.0, 1.0)
    arr[..., 0] = arr[..., 0] + green_dom * 0.05
    arr[..., 1] = arr[..., 1] + green_dom * 0.020

    # 5) 阴影略偏冷紫 / 蓝
    lum = 0.299 * arr[..., 0] + 0.587 * arr[..., 1] + 0.114 * arr[..., 2]
    shadow_mask = np.clip(1.0 - lum * 2.2, 0.0, 1.0)[..., None]
    shadow_tint = np.array([-0.005, -0.008, 0.012], dtype=np.float32)
    arr = arr + shadow_mask * shadow_tint

    return np.clip(arr * 255.0, 0.0, 255.0).astype(np.uint8)
