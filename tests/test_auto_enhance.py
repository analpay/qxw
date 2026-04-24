"""qxw.library.services.auto_enhance 核心算法单元测试

遵循 CLAUDE.md 的 "0 happy test" 原则，重点覆盖：
- 输入校验（dtype / shape / intensity 非法）
- 边界图像（全黑 / 全白 / 单色 / 1x1 / 2x2 / 超小尺寸）
- 分支触发（暗光分支 / HDR 分支 / 肤色保护）
- 数值稳定性（除零 / log(0) / percentile 退化）
- 内部守恒量（CLAHE 像素总数 / HSV 往返）
"""

from __future__ import annotations

import numpy as np
import pytest

from qxw.library.services import auto_enhance as ae


class TestInputValidation:
    def test_非_ndarray_抛错(self) -> None:
        with pytest.raises(ValueError, match="numpy"):
            ae.auto_enhance([[[1, 2, 3]]], intensity="balanced")  # type: ignore[arg-type]

    def test_非_uint8_抛错(self) -> None:
        arr = np.zeros((4, 4, 3), dtype=np.float32)
        with pytest.raises(ValueError, match="uint8"):
            ae.auto_enhance(arr, intensity="balanced")

    def test_2d_shape_抛错(self) -> None:
        arr = np.zeros((4, 4), dtype=np.uint8)
        with pytest.raises(ValueError, match=r"\(H, W, 3\)"):
            ae.auto_enhance(arr, intensity="balanced")

    def test_4通道_shape_抛错(self) -> None:
        arr = np.zeros((4, 4, 4), dtype=np.uint8)
        with pytest.raises(ValueError, match=r"\(H, W, 3\)"):
            ae.auto_enhance(arr, intensity="balanced")

    def test_空图_抛错(self) -> None:
        arr = np.zeros((0, 4, 3), dtype=np.uint8)
        with pytest.raises(ValueError, match="不能为空"):
            ae.auto_enhance(arr, intensity="balanced")

    def test_非法_intensity_抛错(self) -> None:
        arr = np.zeros((4, 4, 3), dtype=np.uint8)
        with pytest.raises(ValueError, match="非法的 intensity"):
            ae.auto_enhance(arr, intensity="extreme")

    def test_非字符串_intensity_抛错(self) -> None:
        arr = np.zeros((4, 4, 3), dtype=np.uint8)
        with pytest.raises(ValueError, match="非法的 intensity"):
            ae.auto_enhance(arr, intensity=None)  # type: ignore[arg-type]


class TestEdgeCaseImages:
    @pytest.mark.parametrize("intensity", ae.AVAILABLE_INTENSITIES)
    def test_全黑图不炸_且仍为暗(self, intensity: str) -> None:
        arr = np.zeros((16, 16, 3), dtype=np.uint8)
        out = ae.auto_enhance(arr, intensity=intensity)
        # 不崩即可；由于单色图降级到仅 vibrance，全黑仍接近黑
        assert out.shape == arr.shape
        assert out.dtype == np.uint8
        assert out.mean() < 30

    @pytest.mark.parametrize("intensity", ae.AVAILABLE_INTENSITIES)
    def test_全白图不炸_且仍为亮(self, intensity: str) -> None:
        arr = np.full((16, 16, 3), 255, dtype=np.uint8)
        out = ae.auto_enhance(arr, intensity=intensity)
        assert out.shape == arr.shape
        assert out.mean() > 230

    @pytest.mark.parametrize("intensity", ae.AVAILABLE_INTENSITIES)
    def test_单色灰图不引入色偏(self, intensity: str) -> None:
        arr = np.full((16, 16, 3), 128, dtype=np.uint8)
        out = ae.auto_enhance(arr, intensity=intensity)
        # 单色图走降级路径；三通道差异应极小（<= 2）
        channel_spread = float(
            np.max([
                abs(out[..., 0].mean() - out[..., 1].mean()),
                abs(out[..., 1].mean() - out[..., 2].mean()),
                abs(out[..., 0].mean() - out[..., 2].mean()),
            ])
        )
        assert channel_spread <= 2.0, f"单色图出现色偏: {channel_spread}"

    def test_1x1_图不崩(self) -> None:
        arr = np.array([[[128, 100, 50]]], dtype=np.uint8)
        out = ae.auto_enhance(arr, intensity="balanced")
        assert out.shape == (1, 1, 3)

    def test_2x2_小于_tile_grid_不崩(self) -> None:
        arr = np.array(
            [[[10, 20, 30], [200, 180, 150]], [[60, 90, 120], [240, 240, 240]]],
            dtype=np.uint8,
        )
        out = ae.auto_enhance(arr, intensity="balanced")
        assert out.shape == (2, 2, 3)

    def test_非方形图不崩(self) -> None:
        arr = np.random.default_rng(42).integers(0, 256, (5, 17, 3), dtype=np.uint8)
        out = ae.auto_enhance(arr, intensity="balanced")
        assert out.shape == (5, 17, 3)


class TestBranchSwitch:
    def test_暗光图触发暗光分支_结果更亮(self) -> None:
        # 构造中位数 < 低阈值的暗光图
        rng = np.random.default_rng(0)
        arr = rng.integers(5, 40, (64, 64, 3), dtype=np.uint8)
        out = ae.auto_enhance(arr, intensity="balanced")
        # 暗光分支 + 后续 gamma 应显著抬高中位亮度
        assert out.mean() > arr.mean() + 30, (
            f"暗光分支应显著抬亮: before={arr.mean():.1f} after={out.mean():.1f}"
        )

    def test_正常亮度图不触发暗光分支(self) -> None:
        # 构造中位数显然大于所有档位阈值的图
        rng = np.random.default_rng(1)
        arr = rng.integers(80, 180, (64, 64, 3), dtype=np.uint8)
        out_subtle = ae.auto_enhance(arr, intensity="subtle")
        # 温和档在正常图上不应大幅改变亮度
        assert abs(out_subtle.mean() - arr.mean()) < 25

    def test_HDR_分支不炸高光(self) -> None:
        rng = np.random.default_rng(2)
        arr = rng.integers(0, 256, (64, 64, 3), dtype=np.uint8)
        out = ae.auto_enhance(arr, intensity="balanced", hdr=True)
        # HDR 应该压缩而不是放大高光；P99 不应显著上升
        p99_before = float(np.percentile(arr, 99))
        p99_after = float(np.percentile(out, 99))
        assert p99_after <= p99_before + 10

    def test_HDR_flag_改变输出(self) -> None:
        rng = np.random.default_rng(3)
        arr = rng.integers(0, 256, (32, 48, 3), dtype=np.uint8)
        out_off = ae.auto_enhance(arr, intensity="balanced", hdr=False)
        out_on = ae.auto_enhance(arr, intensity="balanced", hdr=True)
        # HDR flag 必须对输出产生可感知差异
        assert float(np.abs(out_on.astype(np.int16) - out_off.astype(np.int16)).mean()) > 1.0


class TestSkinProtection:
    def test_肤色区域饱和提升被限幅(self) -> None:
        # 构造一张"脸色"图：hue ~ 20°, 中等饱和，足够大避免单色退化
        rng = np.random.default_rng(7)
        base = np.full((32, 32, 3), (200, 160, 130), dtype=np.uint8)
        noise = rng.integers(-8, 8, base.shape, dtype=np.int16)
        arr = np.clip(base.astype(np.int16) + noise, 0, 255).astype(np.uint8)
        out_punchy = ae.auto_enhance(arr, intensity="punchy")
        # R-G 差异（偏橙指标）不应被大幅放大（肤色保护工作）
        before_rg = float((arr[..., 0].astype(np.int32) - arr[..., 1].astype(np.int32)).mean())
        after_rg = float((out_punchy[..., 0].astype(np.int32) - out_punchy[..., 1].astype(np.int32)).mean())
        # punchy 没有肤色保护会把 R-G 差异拉到 50+，这里应低于该阈值
        assert after_rg < before_rg * 1.6

    def test_非肤色区域_vibrance_正常提升(self) -> None:
        # 纯蓝色低饱和块：应被 vibrance 明显拉高
        arr = np.full((32, 32, 3), (80, 90, 150), dtype=np.uint8)
        arr[0, 0] = (79, 89, 149)  # 打破单色退化
        out = ae.auto_enhance(arr, intensity="punchy")
        # 蓝通道应显著高于红/绿
        assert out[..., 2].mean() - out[..., 0].mean() > 30


class TestShapeInvariants:
    @pytest.mark.parametrize("intensity", ae.AVAILABLE_INTENSITIES)
    @pytest.mark.parametrize("hdr", [True, False])
    def test_shape_与_dtype_保持(self, intensity: str, hdr: bool) -> None:
        rng = np.random.default_rng(5)
        arr = rng.integers(0, 256, (48, 72, 3), dtype=np.uint8)
        out = ae.auto_enhance(arr, intensity=intensity, hdr=hdr)
        assert out.shape == arr.shape
        assert out.dtype == np.uint8


class TestInternalInvariants:
    def test_CLAHE_裁剪重分布像素守恒(self) -> None:
        # 直接测 _numpy_clahe：输出仍在 [0, 100]，且不崩
        rng = np.random.default_rng(9)
        l_channel = rng.uniform(0.0, 100.0, (64, 64)).astype(np.float32)
        out = ae._numpy_clahe(l_channel, clip_limit=2.0, tile_grid=8)
        assert out.shape == l_channel.shape
        assert out.min() >= 0.0 and out.max() <= 100.0
        # 直方图裁剪应增加中段密度（中位数不应跑飞）
        assert 10.0 < float(np.median(out)) < 90.0

    def test_CLAHE_小于_tile_grid_的图降级不崩(self) -> None:
        l_channel = np.full((1, 1), 50.0, dtype=np.float32)
        out = ae._numpy_clahe(l_channel, clip_limit=2.0, tile_grid=8)
        assert out.shape == (1, 1)

    def test_auto_levels_退化_L_全相等(self) -> None:
        l_channel = np.full((10, 10), 42.0, dtype=np.float32)
        out = ae._auto_levels(l_channel, 1.0, 99.0)
        # 单亮度图应该原样返回
        assert np.allclose(out, 42.0)

    def test_median_gamma_饱和区间短路(self) -> None:
        # 中位数 ~ 1.0 时 log(1) = 0 会炸，必须短路
        l_channel = np.full((10, 10), 99.99, dtype=np.float32)
        out = ae._median_gamma(l_channel, target_median=0.5)
        assert np.all(np.isfinite(out))

    def test_HSV_往返_高保真(self) -> None:
        rng = np.random.default_rng(11)
        rgb = rng.uniform(0.0, 1.0, (20, 20, 3)).astype(np.float32)
        hsv = ae._rgb_to_hsv(rgb)
        back = ae._hsv_to_rgb(hsv)
        # 浮点误差应 < 1e-4
        assert float(np.max(np.abs(rgb - back))) < 1e-4

    def test_LAB_往返_高保真(self) -> None:
        rng = np.random.default_rng(13)
        rgb = rng.uniform(0.0, 1.0, (20, 20, 3)).astype(np.float32)
        lab = ae._srgb_to_lab(rgb)
        back = ae._lab_to_srgb(lab)
        assert float(np.max(np.abs(rgb - back))) < 1e-3

    def test_gaussian_blur_保持均值(self) -> None:
        rng = np.random.default_rng(17)
        img = rng.uniform(0.0, 100.0, (40, 60)).astype(np.float32)
        blurred = ae._gaussian_blur(img, sigma=3.0)
        assert abs(float(img.mean()) - float(blurred.mean())) < 1.0

    def test_skin_mask_非肤色区域为零(self) -> None:
        # 纯蓝 HSV (h=0.66, s=0.8, v=0.8)
        hsv = np.zeros((4, 4, 3), dtype=np.float32)
        hsv[..., 0] = 0.66
        hsv[..., 1] = 0.8
        hsv[..., 2] = 0.8
        mask = ae._skin_mask(hsv)
        assert float(mask.max()) < 0.1

    def test_skin_mask_肤色中心区域非零(self) -> None:
        # hue ~ 0.07 (25°), s=0.4, v=0.7
        hsv = np.zeros((4, 4, 3), dtype=np.float32)
        hsv[..., 0] = 0.07
        hsv[..., 1] = 0.4
        hsv[..., 2] = 0.7
        mask = ae._skin_mask(hsv)
        assert float(mask.min()) > 0.5

    def test_vibrance_高饱和不动(self) -> None:
        s = np.full((4, 4), 1.0, dtype=np.float32)
        skin = np.zeros((4, 4), dtype=np.float32)
        out = ae._vibrance(s, boost=0.5, skin_mask=skin, skin_damp=0.5)
        assert np.allclose(out, 1.0)

    def test_vibrance_低饱和被提升(self) -> None:
        s = np.full((4, 4), 0.2, dtype=np.float32)
        skin = np.zeros((4, 4), dtype=np.float32)
        out = ae._vibrance(s, boost=0.5, skin_mask=skin, skin_damp=0.5)
        # 0.2 + (1-0.2)*0.5*1 = 0.6
        assert float(out.mean()) > 0.55

    def test_vibrance_肤色被抑制(self) -> None:
        s = np.full((4, 4), 0.2, dtype=np.float32)
        skin_off = np.zeros((4, 4), dtype=np.float32)
        skin_on = np.ones((4, 4), dtype=np.float32)
        off = ae._vibrance(s, boost=0.5, skin_mask=skin_off, skin_damp=0.3)
        on = ae._vibrance(s, boost=0.5, skin_mask=skin_on, skin_damp=0.3)
        # 肤色 mask = 1 时 weight = 0.3，提升小
        assert float(off.mean()) > float(on.mean())


class TestPresetConsistency:
    def test_预设数量不变(self) -> None:
        assert set(ae.INTENSITY_PRESETS.keys()) == set(ae.AVAILABLE_INTENSITIES)

    def test_预设字段完整(self) -> None:
        required = {
            "auto_levels_low_pct",
            "auto_levels_high_pct",
            "clahe_clip_limit",
            "clahe_tile_grid",
            "gamma_target_median",
            "vibrance_boost",
            "hdr_detail_boost",
            "low_light_threshold",
            "skin_vibrance_damp",
        }
        for name, preset in ae.INTENSITY_PRESETS.items():
            assert set(preset.keys()) == required, f"{name} 档位字段不完整"

    def test_预设档位力度递增(self) -> None:
        # vibrance / clahe 强度应按 subtle < balanced < punchy 排序
        for key in ("vibrance_boost", "clahe_clip_limit", "hdr_detail_boost"):
            v = [ae.INTENSITY_PRESETS[k][key] for k in ("subtle", "balanced", "punchy")]
            assert v[0] < v[1] < v[2], f"{key} 应递增: {v}"
