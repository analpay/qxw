"""自动图像增强算法：自适应亮度 / 对比度 / 饱和度调整

面向 ``qxw-image change`` 子命令的核心算法模块，对一张位图计算图像统计量，
按预设档位（subtle / balanced / punchy）做组合增强，目标是"看着舒服"而不是
"最大化对比"。

设计原则
--------
- **纯 numpy**：与 :mod:`qxw.library.services.color_filters` 保持一致，不引入
  OpenCV；CLAHE、Gaussian 低通、色空间转换全部用 numpy 手写
- **自适应分支**：暗光照片走 IAGCWD-style 自适应 gamma；正常照片走 auto-levels
  + CLAHE + 中位数 gamma；HDR 开关打开时额外做 base/detail 局部 tone mapping
- **保护肤色**：HSV 里识别肤色 hue 区间，对该区域的 vibrance 提升打折，避免脸
  变得过红 / 过橙
- **无副作用纯函数**：输入被视为只读，输出新数组，方便线程池并行调用

公开 API
--------
- :func:`auto_enhance` — 主入口
- :data:`INTENSITY_PRESETS` — 三档预设参数
- :data:`AVAILABLE_INTENSITIES` — 合法 intensity 元组

参考算法
--------
- Simplest Color Balance (Limare et al., IPOL 2011) — auto-levels
- CLAHE (Pizer et al.) — 局部对比限幅均衡化
- IAGCWD (Huang et al.) — 改进自适应加权 gamma
- Durand-Dorsey lite — base/detail 局部 tone mapping
- Adobe Vibrance — 非线性饱和提升

算法里所有阈值 / 系数均已在 :data:`INTENSITY_PRESETS` 中显式列出，便于审阅。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from qxw.library.base.logger import get_logger

if TYPE_CHECKING:
    import numpy as np

logger = get_logger("qxw.image.auto_enhance")


# ============================================================
# 预设档位
# ============================================================

# 三档预设：每项都是一组相互协调的参数，不要单独调任何一项，否则容易失衡
INTENSITY_PRESETS: dict[str, dict[str, float]] = {
    "subtle": {
        "auto_levels_low_pct": 0.3,      # 裁掉最暗 0.3% 像素
        "auto_levels_high_pct": 99.7,    # 裁掉最亮 0.3% 像素
        "clahe_clip_limit": 1.5,         # CLAHE 直方图裁剪阈值（倍数）
        "clahe_tile_grid": 8,            # CLAHE tile 数量（8×8）
        "gamma_target_median": 0.50,     # L 通道中位数目标
        "vibrance_boost": 0.08,          # 饱和提升强度
        "hdr_detail_boost": 1.2,         # HDR 模式下 detail 层放大倍数
        "low_light_threshold": 0.20,     # 暗光判定阈值（L 中位数 / 100）
        "skin_vibrance_damp": 0.6,       # 肤色区域 vibrance 保留比例（越小越保护）
    },
    "balanced": {
        "auto_levels_low_pct": 0.8,
        "auto_levels_high_pct": 99.2,
        "clahe_clip_limit": 2.0,
        "clahe_tile_grid": 8,
        "gamma_target_median": 0.50,
        "vibrance_boost": 0.15,
        "hdr_detail_boost": 1.4,
        "low_light_threshold": 0.25,
        "skin_vibrance_damp": 0.5,
    },
    "punchy": {
        "auto_levels_low_pct": 1.5,
        "auto_levels_high_pct": 98.5,
        "clahe_clip_limit": 3.0,
        "clahe_tile_grid": 10,
        "gamma_target_median": 0.48,
        "vibrance_boost": 0.25,
        "hdr_detail_boost": 1.7,
        "low_light_threshold": 0.30,
        "skin_vibrance_damp": 0.4,
    },
}

AVAILABLE_INTENSITIES: tuple[str, ...] = ("subtle", "balanced", "punchy")

# 肤色 hue 区间（HSV, H ∈ [0, 1]）；典型人类肤色 hue 约 5°–50°，即 0.014–0.14
# 加上高亮的红色系（也会被误判为肤色）一并做软保护
_SKIN_HUE_LOW = 0.01
_SKIN_HUE_HIGH = 0.14
_SKIN_SAT_LOW = 0.15
_SKIN_SAT_HIGH = 0.70
_SKIN_VAL_LOW = 0.25
_SKIN_VAL_HIGH = 0.95


# ============================================================
# 公开入口
# ============================================================


def auto_enhance(
    rgb: "np.ndarray",
    intensity: str = "balanced",
    hdr: bool = False,
) -> "np.ndarray":
    """对 uint8 RGB 图像做自动亮度 / 对比 / 饱和调整

    Args:
        rgb: 形状 ``(H, W, 3)`` 的 uint8 RGB 数组
        intensity: 档位，取 ``subtle`` / ``balanced`` / ``punchy`` 之一
        hdr: 是否启用 HDR 局部 tone mapping（对亮度动态范围大的场景有效）

    Returns:
        形状相同、dtype 仍为 uint8 的新 RGB 数组

    Raises:
        ValueError: 输入 shape / dtype 非法，或 intensity 不在预设中
    """
    import numpy as np

    if not isinstance(intensity, str) or intensity not in INTENSITY_PRESETS:
        raise ValueError(
            f"非法的 intensity: {intensity!r}，可选: {', '.join(AVAILABLE_INTENSITIES)}"
        )
    if not isinstance(rgb, np.ndarray):
        raise ValueError(f"输入必须是 numpy 数组，收到 {type(rgb).__name__}")
    if rgb.dtype != np.uint8:
        raise ValueError(f"输入 dtype 必须是 uint8，收到 {rgb.dtype}")
    if rgb.ndim != 3 or rgb.shape[2] != 3:
        raise ValueError(f"输入形状必须是 (H, W, 3)，收到 {rgb.shape}")
    if rgb.shape[0] == 0 or rgb.shape[1] == 0:
        raise ValueError(f"输入图像不能为空，收到 {rgb.shape}")

    params = INTENSITY_PRESETS[intensity]

    # sRGB [0,255] → float32 [0,1]
    rgb_f = rgb.astype(np.float32) / 255.0

    # 单色 / 近似单色图：所有通道方差都接近 0 时跳过所有亮度 / 对比变换，
    # 否则 auto-levels / gamma / CLAHE 的统计量都会除零或放大噪声
    if float(np.std(rgb_f)) < 1e-4:
        logger.debug("auto_enhance: 单色图检测到，跳过亮度/对比变换，仅做温和饱和")
        return _apply_vibrance_only(rgb_f, params)

    # sRGB → LAB；L ∈ [0, 100]
    lab = _srgb_to_lab(rgb_f)
    l_channel = lab[..., 0]

    # HDR 分支：先做局部 tone mapping 再走后续流程
    if hdr:
        l_channel = _hdr_local_tonemap(l_channel, float(params["hdr_detail_boost"]))

    # 暗光分支 vs 正常分支
    l_median_norm = float(np.median(l_channel)) / 100.0
    if l_median_norm < float(params["low_light_threshold"]):
        logger.debug("auto_enhance: 暗光分支触发 (median=%.3f)", l_median_norm)
        l_channel = _iagcwd_like(l_channel)
    else:
        l_channel = _auto_levels(
            l_channel,
            float(params["auto_levels_low_pct"]),
            float(params["auto_levels_high_pct"]),
        )

    # CLAHE 局部对比增强
    l_channel = _numpy_clahe(
        l_channel,
        clip_limit=float(params["clahe_clip_limit"]),
        tile_grid=int(params["clahe_tile_grid"]),
    )

    # 中位数 gamma 校正到目标
    l_channel = _median_gamma(l_channel, float(params["gamma_target_median"]))

    lab[..., 0] = l_channel
    rgb_f2 = _lab_to_srgb(lab)
    rgb_f2 = np.clip(rgb_f2, 0.0, 1.0)

    # 饱和度处理：转 HSV，计算肤色 mask，非线性 vibrance
    hsv = _rgb_to_hsv(rgb_f2)
    skin_mask = _skin_mask(hsv)
    hsv[..., 1] = _vibrance(
        hsv[..., 1],
        boost=float(params["vibrance_boost"]),
        skin_mask=skin_mask,
        skin_damp=float(params["skin_vibrance_damp"]),
    )
    rgb_out = _hsv_to_rgb(hsv)

    return np.clip(rgb_out * 255.0, 0.0, 255.0).astype(np.uint8)


# ============================================================
# 单色图降级路径
# ============================================================


def _apply_vibrance_only(rgb_f: "np.ndarray", params: dict[str, float]) -> "np.ndarray":
    """单色图仅做温和饱和提升；亮度/对比不动"""
    import numpy as np

    hsv = _rgb_to_hsv(rgb_f)
    skin_mask = _skin_mask(hsv)
    hsv[..., 1] = _vibrance(
        hsv[..., 1],
        boost=float(params["vibrance_boost"]),
        skin_mask=skin_mask,
        skin_damp=float(params["skin_vibrance_damp"]),
    )
    rgb_out = _hsv_to_rgb(hsv)
    return np.clip(rgb_out * 255.0, 0.0, 255.0).astype(np.uint8)


# ============================================================
# sRGB ↔ LAB（D65, 2° 观察者）
# ============================================================

# sRGB → linear RGB 的 inverse gamma 阈值与系数（IEC 61966-2-1）
_SRGB_GAMMA_THRESHOLD = 0.04045
_SRGB_GAMMA_LINEAR = 12.92
_SRGB_GAMMA_A = 0.055
_SRGB_GAMMA_EXP = 2.4

# linear RGB → XYZ（D65 主光源）
_RGB_TO_XYZ = (
    (0.4124564, 0.3575761, 0.1804375),
    (0.2126729, 0.7151522, 0.0721750),
    (0.0193339, 0.1191920, 0.9503041),
)
# D65 白点
_XYZ_WHITE = (0.95047, 1.0, 1.08883)

# XYZ → LAB 的 f(t) 分段常量
_LAB_EPSILON = 216.0 / 24389.0  # (6/29)^3
_LAB_KAPPA = 24389.0 / 27.0     # (29/3)^3


def _srgb_to_linear(srgb: "np.ndarray") -> "np.ndarray":
    import numpy as np

    return np.where(
        srgb <= _SRGB_GAMMA_THRESHOLD,
        srgb / _SRGB_GAMMA_LINEAR,
        np.power((srgb + _SRGB_GAMMA_A) / (1.0 + _SRGB_GAMMA_A), _SRGB_GAMMA_EXP),
    )


def _linear_to_srgb(linear: "np.ndarray") -> "np.ndarray":
    import numpy as np

    return np.where(
        linear <= 0.0031308,
        linear * _SRGB_GAMMA_LINEAR,
        (1.0 + _SRGB_GAMMA_A) * np.power(np.maximum(linear, 0.0), 1.0 / _SRGB_GAMMA_EXP)
        - _SRGB_GAMMA_A,
    )


def _srgb_to_lab(rgb: "np.ndarray") -> "np.ndarray":
    """sRGB (float [0,1]) → LAB (L∈[0,100], a/b ≈ [-128,128])"""
    import numpy as np

    linear = _srgb_to_linear(rgb)
    m = np.array(_RGB_TO_XYZ, dtype=np.float32)
    xyz = linear @ m.T
    white = np.array(_XYZ_WHITE, dtype=np.float32)
    xyz_n = xyz / white

    def _f(t: np.ndarray) -> np.ndarray:
        return np.where(
            t > _LAB_EPSILON,
            np.cbrt(np.maximum(t, 0.0)),
            (_LAB_KAPPA * t + 16.0) / 116.0,
        )

    fxyz = _f(xyz_n)
    L = 116.0 * fxyz[..., 1] - 16.0
    a = 500.0 * (fxyz[..., 0] - fxyz[..., 1])
    b = 200.0 * (fxyz[..., 1] - fxyz[..., 2])
    return np.stack([L, a, b], axis=-1).astype(np.float32)


def _lab_to_srgb(lab: "np.ndarray") -> "np.ndarray":
    """LAB → sRGB (float [0,1])"""
    import numpy as np

    L = lab[..., 0]
    a = lab[..., 1]
    b = lab[..., 2]

    fy = (L + 16.0) / 116.0
    fx = fy + a / 500.0
    fz = fy - b / 200.0

    def _finv(f: np.ndarray) -> np.ndarray:
        f3 = f * f * f
        return np.where(
            f3 > _LAB_EPSILON,
            f3,
            (116.0 * f - 16.0) / _LAB_KAPPA,
        )

    white = np.array(_XYZ_WHITE, dtype=np.float32)
    X = _finv(fx) * white[0]
    Y = _finv(fy) * white[1]
    Z = _finv(fz) * white[2]
    xyz = np.stack([X, Y, Z], axis=-1).astype(np.float32)

    m_inv = np.linalg.inv(np.array(_RGB_TO_XYZ, dtype=np.float32))
    linear = xyz @ m_inv.T
    return _linear_to_srgb(np.clip(linear, 0.0, None)).astype(np.float32)


# ============================================================
# RGB ↔ HSV（纯 numpy 向量化，比 colorsys 快 100×）
# ============================================================


def _rgb_to_hsv(rgb: "np.ndarray") -> "np.ndarray":
    """RGB (float [0,1]) → HSV (H,S,V 均 ∈ [0,1])"""
    import numpy as np

    r = rgb[..., 0]
    g = rgb[..., 1]
    b = rgb[..., 2]
    maxc = np.maximum(np.maximum(r, g), b)
    minc = np.minimum(np.minimum(r, g), b)
    delta = maxc - minc

    v = maxc
    s = np.where(maxc > 0.0, delta / np.maximum(maxc, 1e-12), 0.0)

    # Hue 分段
    delta_safe = np.where(delta > 0.0, delta, 1.0)  # 防除零
    rc = (maxc - r) / delta_safe
    gc = (maxc - g) / delta_safe
    bc = (maxc - b) / delta_safe

    h = np.where(
        r == maxc,
        bc - gc,
        np.where(g == maxc, 2.0 + rc - bc, 4.0 + gc - rc),
    )
    h = (h / 6.0) % 1.0
    h = np.where(delta == 0.0, 0.0, h)
    return np.stack([h, s, v], axis=-1).astype(np.float32)


def _hsv_to_rgb(hsv: "np.ndarray") -> "np.ndarray":
    """HSV → RGB (float [0,1])"""
    import numpy as np

    h = hsv[..., 0] % 1.0
    s = np.clip(hsv[..., 1], 0.0, 1.0)
    v = np.clip(hsv[..., 2], 0.0, 1.0)

    i = np.floor(h * 6.0).astype(np.int32) % 6
    f = h * 6.0 - np.floor(h * 6.0)
    p = v * (1.0 - s)
    q = v * (1.0 - f * s)
    t = v * (1.0 - (1.0 - f) * s)

    # 分段构造 R, G, B
    r = np.select(
        [i == 0, i == 1, i == 2, i == 3, i == 4, i == 5],
        [v, q, p, p, t, v],
    )
    g = np.select(
        [i == 0, i == 1, i == 2, i == 3, i == 4, i == 5],
        [t, v, v, q, p, p],
    )
    b = np.select(
        [i == 0, i == 1, i == 2, i == 3, i == 4, i == 5],
        [p, p, t, v, v, q],
    )
    return np.stack([r, g, b], axis=-1).astype(np.float32)


# ============================================================
# Auto-Levels（L 通道百分位拉伸）
# ============================================================


def _auto_levels(l_channel: "np.ndarray", low_pct: float, high_pct: float) -> "np.ndarray":
    """把 L 通道的 low_pct / high_pct 分位数分别映射到 0 / 100，线性拉伸"""
    import numpy as np

    lo = float(np.percentile(l_channel, low_pct))
    hi = float(np.percentile(l_channel, high_pct))
    if hi - lo < 1e-3:
        # 退化：整图几乎同一亮度，不做拉伸
        return l_channel
    scaled = (l_channel - lo) * (100.0 / (hi - lo))
    return np.clip(scaled, 0.0, 100.0).astype(np.float32)


# ============================================================
# 中位数 Gamma 校正
# ============================================================


def _median_gamma(l_channel: "np.ndarray", target_median: float) -> "np.ndarray":
    """调整 gamma 使 L 通道中位数贴近 target_median × 100"""
    import numpy as np

    # 归一化到 [0, 1] 再做 gamma，之后还原
    l_norm = np.clip(l_channel / 100.0, 1e-6, 1.0)
    median = float(np.median(l_norm))
    if median < 1e-3 or median > 1.0 - 1e-3:
        return l_channel  # 饱和区间内 gamma 无意义，短路
    target = float(np.clip(target_median, 0.05, 0.95))
    # γ 满足 median ** γ = target → γ = log(target)/log(median)
    gamma = float(np.log(target) / np.log(median))
    gamma = float(np.clip(gamma, 0.4, 2.5))  # 防极端
    adjusted = np.power(l_norm, gamma) * 100.0
    return adjusted.astype(np.float32)


# ============================================================
# IAGCWD-style 暗光分支
# ============================================================


def _iagcwd_like(l_channel: "np.ndarray") -> "np.ndarray":
    """面向暗光图的自适应加权 gamma 校正

    简化版 IAGCWD：用 L 通道归一化直方图的 CDF 反函数做非线性映射，
    先把暗部大幅抬升，再用 S 曲线防止高光溢出。
    """
    import numpy as np

    l_norm = np.clip(l_channel / 100.0, 0.0, 1.0)
    # 构造 256 bin 的加权 CDF
    hist, _ = np.histogram(l_norm, bins=256, range=(0.0, 1.0), density=True)
    hist = hist / max(hist.sum(), 1e-12)
    # 加权：低亮度 bin 的权重更高（1 - bin_center 的幂）
    bin_centers = (np.arange(256) + 0.5) / 256.0
    weights = np.power(1.0 - bin_centers, 0.5)
    weighted = hist * weights
    weighted = weighted / max(weighted.sum(), 1e-12)
    cdf = np.cumsum(weighted)
    # 构造查找表：对每个输入亮度 x，查 cdf(x) 作为输出
    lut = cdf  # shape (256,)
    indices = np.clip((l_norm * 255.0).astype(np.int32), 0, 255)
    mapped = lut[indices]
    return (mapped * 100.0).astype(np.float32)


# ============================================================
# 纯 numpy CLAHE
# ============================================================


def _numpy_clahe(
    l_channel: "np.ndarray",
    clip_limit: float,
    tile_grid: int,
) -> "np.ndarray":
    """CLAHE on L channel，使用双线性插值合成避免 tile 边界

    Args:
        l_channel: 形状 (H, W) 的 float32 L 值 ∈ [0, 100]
        clip_limit: 直方图裁剪阈值，以"平均 bin 高度"为单位的倍数（典型 1.5–3.0）
        tile_grid: 每一维的 tile 数（如 8 表示 8×8 tiles）

    返回同 shape 的 float32 数组，值域仍 ∈ [0, 100]。
    """
    import numpy as np

    H, W = l_channel.shape
    if H < 2 or W < 2:
        return l_channel.astype(np.float32)

    # tile 数量不能超过图像尺寸（小图直接降级到全局均衡化）
    ny = max(1, min(tile_grid, H))
    nx = max(1, min(tile_grid, W))

    # 计算每个 tile 边界（闭-开）
    y_edges = np.linspace(0, H, ny + 1, dtype=np.int32)
    x_edges = np.linspace(0, W, nx + 1, dtype=np.int32)
    # 避免 degenerate tile（至少 1 行/列）
    for arr in (y_edges, x_edges):
        for i in range(1, len(arr)):
            if arr[i] <= arr[i - 1]:
                arr[i] = arr[i - 1] + 1

    # 256 bin 直方图，值域 [0, 100] 映射到 [0, 255]
    bins = 256
    scale = (bins - 1) / 100.0

    # 为每个 tile 计算映射 LUT (形状 ny × nx × bins)
    luts = np.zeros((ny, nx, bins), dtype=np.float32)
    for iy in range(ny):
        for ix in range(nx):
            y0, y1 = int(y_edges[iy]), int(y_edges[iy + 1])
            x0, x1 = int(x_edges[ix]), int(x_edges[ix + 1])
            tile = l_channel[y0:y1, x0:x1]
            tile_idx = np.clip(tile * scale, 0, bins - 1).astype(np.int32)
            hist = np.bincount(tile_idx.ravel(), minlength=bins).astype(np.float32)
            n_pixels = tile.size
            if n_pixels == 0:
                # 退化 tile：identity LUT
                luts[iy, ix] = np.linspace(0.0, 100.0, bins, dtype=np.float32)
                continue
            # 裁剪 + 重分布
            clip_height = clip_limit * (n_pixels / bins)
            excess = np.maximum(hist - clip_height, 0.0).sum()
            hist = np.minimum(hist, clip_height)
            hist = hist + excess / bins
            # CDF → 映射到 [0, 100]
            cdf = np.cumsum(hist)
            cdf_total = max(float(cdf[-1]), 1e-12)
            lut = cdf / cdf_total * 100.0
            luts[iy, ix] = lut.astype(np.float32)

    # 对每个像素做 bilinear 插值：先求像素所在 tile 的四角 LUT，再按距离加权
    # tile 中心坐标（像素空间）
    y_centers = 0.5 * (y_edges[:-1] + y_edges[1:])
    x_centers = 0.5 * (x_edges[:-1] + x_edges[1:])

    # 为每个像素找到包围它的 4 个 tile 中心索引
    ys = np.arange(H, dtype=np.float32) + 0.5
    xs = np.arange(W, dtype=np.float32) + 0.5

    def _bracket(centers: np.ndarray, coords: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """给定 tile 中心 centers (N,) 和像素坐标 coords (M,)，返回每个像素
        的左右 tile 索引 (i0, i1) 和线性权重 w1（用于 i1 方向的权重）。"""
        # 对每个像素，找第一个 >= coord 的 tile 中心索引
        idx = np.searchsorted(centers, coords)
        # 左右 tile 索引：clip 到 [0, N-1]
        i1 = np.clip(idx, 0, len(centers) - 1)
        i0 = np.clip(idx - 1, 0, len(centers) - 1)
        left = centers[i0]
        right = centers[i1]
        span = right - left
        # 同 tile 或越界 → 权重 0
        safe_span = np.where(span > 0, span, 1.0)
        w1 = np.where(span > 0, (coords - left) / safe_span, 0.0)
        w1 = np.clip(w1, 0.0, 1.0)
        return i0.astype(np.int32), i1.astype(np.int32), w1.astype(np.float32)

    iy0, iy1, wy = _bracket(y_centers, ys)
    ix0, ix1, wx = _bracket(x_centers, xs)

    # 像素值对应的 bin 索引
    pix_bin = np.clip(l_channel * scale, 0, bins - 1).astype(np.int32)

    # 查四角 LUT（使用花式索引）
    # luts[iy, ix, bin]  —  对每个像素 (y, x) 查四次
    # 先把 iy / ix 广播到 (H, W)
    iy0_2d = iy0[:, None]  # (H, 1)
    iy1_2d = iy1[:, None]
    ix0_2d = ix0[None, :]  # (1, W)
    ix1_2d = ix1[None, :]
    wy_2d = wy[:, None]
    wx_2d = wx[None, :]

    v00 = luts[iy0_2d, ix0_2d, pix_bin]
    v01 = luts[iy0_2d, ix1_2d, pix_bin]
    v10 = luts[iy1_2d, ix0_2d, pix_bin]
    v11 = luts[iy1_2d, ix1_2d, pix_bin]

    top = v00 * (1.0 - wx_2d) + v01 * wx_2d
    bot = v10 * (1.0 - wx_2d) + v11 * wx_2d
    out = top * (1.0 - wy_2d) + bot * wy_2d

    return np.clip(out, 0.0, 100.0).astype(np.float32)


# ============================================================
# HDR 局部 tone mapping
# ============================================================


def _hdr_local_tonemap(l_channel: "np.ndarray", detail_boost: float) -> "np.ndarray":
    """Durand-Dorsey lite：base / detail 分解 + 高光压缩 + 细节放大

    对 L 通道做 Gaussian 低通得到 base 层（大尺度亮度），用 log-domain arctan
    压缩 base 的动态范围，然后把 detail 层（原图 - base）按 detail_boost 放大
    再合成。这是 HDR 观感的最小可工作实现，不需要真正的多曝光融合。
    """
    import numpy as np

    H, W = l_channel.shape
    # Gaussian σ 约 = 图像短边 / 50，对应 ~2% 区域的平均亮度
    sigma = max(3.0, min(H, W) / 50.0)
    base = _gaussian_blur(l_channel, sigma)

    # log-domain 压缩 base，防 log(0)
    base_safe = np.maximum(base, 1e-3)
    # 参考值：整图 log 均值
    log_mean = float(np.mean(np.log(base_safe)))
    # 压缩系数：0.6 相当于动态范围压到原来的 60%
    compression = 0.7
    log_compressed = log_mean + (np.log(base_safe) - log_mean) * compression
    base_compressed = np.exp(log_compressed)

    # detail 层 = 原 - base（在 L 域直接相减）
    detail = l_channel - base

    # 合成：压缩后的 base + 放大后的 detail
    result = base_compressed + detail * float(detail_boost)
    return np.clip(result, 0.0, 100.0).astype(np.float32)


def _gaussian_blur(img: "np.ndarray", sigma: float) -> "np.ndarray":
    """纯 numpy separable Gaussian blur，对 (H, W) 的 float32 2D 数组"""
    import numpy as np

    radius = max(1, int(np.ceil(sigma * 3.0)))
    x = np.arange(-radius, radius + 1, dtype=np.float32)
    kernel_1d = np.exp(-0.5 * (x / sigma) ** 2)
    kernel_1d = kernel_1d / kernel_1d.sum()

    # 水平卷积（reflect padding）
    padded = np.pad(img, ((0, 0), (radius, radius)), mode="reflect")
    # 用 cumulative 乘积的方式做 1D conv 太复杂，直接循环 kernel 长度
    result_h = np.zeros_like(img)
    for k_i, w in enumerate(kernel_1d):
        result_h += padded[:, k_i : k_i + img.shape[1]] * w

    # 垂直卷积
    padded2 = np.pad(result_h, ((radius, radius), (0, 0)), mode="reflect")
    result = np.zeros_like(img)
    for k_i, w in enumerate(kernel_1d):
        result += padded2[k_i : k_i + img.shape[0], :] * w

    return result.astype(np.float32)


# ============================================================
# 肤色 mask + Vibrance
# ============================================================


def _smoothstep(x: "np.ndarray", edge0: float, edge1: float) -> "np.ndarray":
    """Hermite smoothstep：x 在 [edge0, edge1] 之外为 0 / 1，之内平滑过渡"""
    import numpy as np

    if edge1 - edge0 < 1e-9:
        return (x >= edge1).astype(np.float32)
    t = np.clip((x - edge0) / (edge1 - edge0), 0.0, 1.0)
    return (t * t * (3.0 - 2.0 * t)).astype(np.float32)


def _skin_mask(hsv: "np.ndarray") -> "np.ndarray":
    """基于 HSV 识别肤色区域，返回 (H, W) 软 mask ∈ [0, 1]"""
    import numpy as np

    h = hsv[..., 0]
    s = hsv[..., 1]
    v = hsv[..., 2]

    # H 方向：[_SKIN_HUE_LOW, _SKIN_HUE_HIGH] 之内为高权重，两侧各用 ±0.03 的 smoothstep 过渡
    feather = 0.03
    hue_mask = _smoothstep(h, _SKIN_HUE_LOW - feather, _SKIN_HUE_LOW) * (
        1.0 - _smoothstep(h, _SKIN_HUE_HIGH, _SKIN_HUE_HIGH + feather)
    )
    sat_mask = _smoothstep(s, _SKIN_SAT_LOW - 0.05, _SKIN_SAT_LOW) * (
        1.0 - _smoothstep(s, _SKIN_SAT_HIGH, _SKIN_SAT_HIGH + 0.05)
    )
    val_mask = _smoothstep(v, _SKIN_VAL_LOW - 0.05, _SKIN_VAL_LOW) * (
        1.0 - _smoothstep(v, _SKIN_VAL_HIGH, _SKIN_VAL_HIGH + 0.05)
    )
    return (hue_mask * sat_mask * val_mask).astype(np.float32)


def _vibrance(
    s_channel: "np.ndarray",
    boost: float,
    skin_mask: "np.ndarray",
    skin_damp: float,
) -> "np.ndarray":
    """非线性饱和提升：低饱和加得多、高饱和几乎不动，且肤色区域打折

    公式: S' = S + (1 - S) × boost × weight × activation
    - S ≤ 0.02（真实灰度像素）→ activation = 0，保持灰
    - S ∈ [0.02, 0.12] → activation 从 0 平滑过渡到 1
    - S = 1 → (1-S)=0，不动
    - 肤色区域 weight 乘以 skin_damp（<1），抑制变橙
    """
    import numpy as np

    activation = _smoothstep(s_channel, 0.02, 0.12)
    weight = 1.0 - skin_mask * (1.0 - float(skin_damp))
    new_s = s_channel + (1.0 - s_channel) * float(boost) * weight * activation
    return np.clip(new_s, 0.0, 1.0).astype(np.float32)
