"""image_adjust 单元测试

遵循 CLAUDE.md 的 "0 happy test, 0 happy path" 原则：
- AdjustmentParams 校验：越界 / NaN / Inf / 未知字段 / 非数字
- apply_adjustments 输入类型 / dtype / 形状防呆
- parse_from_query 解析 / 越界 / 非数字 / 未知字段
- 全 0 参数走 identity 快速路径
- 单项参数确实改变像素（基础 sanity）
"""

from __future__ import annotations

import numpy as np
import pytest

from qxw.library.base.exceptions import QxwError, ValidationError
from qxw.library.services.image_adjust import (
    AdjustmentParams,
    apply_adjustments,
    parse_from_query,
    save_adjusted_image,
)

# ============================================================
# AdjustmentParams 校验
# ============================================================


class TestParamsValidation:
    def test_默认全_0_是_identity(self) -> None:
        assert AdjustmentParams().is_identity()

    def test_任一参数非_0_都不是_identity(self) -> None:
        assert not AdjustmentParams(exposure=1).is_identity()
        assert not AdjustmentParams(sharpness=1).is_identity()
        assert not AdjustmentParams(vignette=-0.5).is_identity()

    @pytest.mark.parametrize(
        "field",
        [
            "exposure", "brilliance", "highlights", "shadows", "contrast",
            "brightness", "blacks", "saturation", "vibrance", "temperature",
            "tint", "vignette",
        ],
    )
    def test_双向参数上限越界_被拒绝(self, field: str) -> None:
        with pytest.raises(Exception):  # pydantic.ValidationError
            AdjustmentParams(**{field: 100.1})

    @pytest.mark.parametrize(
        "field",
        [
            "exposure", "brilliance", "highlights", "shadows", "contrast",
            "brightness", "blacks", "saturation", "vibrance", "temperature",
            "tint", "vignette",
        ],
    )
    def test_双向参数下限越界_被拒绝(self, field: str) -> None:
        with pytest.raises(Exception):
            AdjustmentParams(**{field: -100.1})

    @pytest.mark.parametrize("field", ["sharpness", "clarity", "noise_reduction"])
    def test_单向参数负值_被拒绝(self, field: str) -> None:
        # 锐度 / 清晰度 / 噪点消除 下限为 0
        with pytest.raises(Exception):
            AdjustmentParams(**{field: -0.1})

    @pytest.mark.parametrize("field", ["sharpness", "clarity", "noise_reduction"])
    def test_单向参数上限越界_被拒绝(self, field: str) -> None:
        with pytest.raises(Exception):
            AdjustmentParams(**{field: 100.1})

    def test_NaN_被拒绝(self) -> None:
        with pytest.raises(Exception, match="NaN"):
            AdjustmentParams(exposure=float("nan"))

    def test_正无穷_被拒绝(self) -> None:
        with pytest.raises(Exception, match="无穷"):
            AdjustmentParams(contrast=float("inf"))

    def test_负无穷_被拒绝(self) -> None:
        with pytest.raises(Exception, match="无穷"):
            AdjustmentParams(contrast=float("-inf"))

    def test_未知字段_被拒绝(self) -> None:
        with pytest.raises(Exception):
            AdjustmentParams(foo=1)  # type: ignore[call-arg]


# ============================================================
# parse_from_query
# ============================================================


class TestParseFromQuery:
    def test_空字典_得到默认参数(self) -> None:
        p = parse_from_query({})
        assert p.is_identity()

    def test_解析多参数(self) -> None:
        p = parse_from_query({"exposure": ["10"], "sharpness": ["50"]})
        assert p.exposure == 10
        assert p.sharpness == 50

    def test_多值取第一个(self) -> None:
        p = parse_from_query({"exposure": ["5", "99"]})
        assert p.exposure == 5

    def test_非数字_抛出_ValidationError(self) -> None:
        with pytest.raises(ValidationError, match="不是合法浮点数"):
            parse_from_query({"exposure": ["abc"]})

    def test_越界_抛出_ValidationError(self) -> None:
        with pytest.raises(ValidationError, match="参数校验失败"):
            parse_from_query({"exposure": ["150"]})

    def test_单向参数负值_抛出_ValidationError(self) -> None:
        with pytest.raises(ValidationError, match="参数校验失败"):
            parse_from_query({"sharpness": ["-1"]})

    def test_未知键_抛出_ValidationError(self) -> None:
        with pytest.raises(ValidationError, match="参数校验失败"):
            parse_from_query({"foobar": ["1"]})

    def test_空值列表_被忽略(self) -> None:
        p = parse_from_query({"exposure": []})
        assert p.is_identity()


# ============================================================
# apply_adjustments 输入防呆
# ============================================================


class TestApplyInputValidation:
    def test_非_ndarray_抛错(self) -> None:
        with pytest.raises(ValidationError, match="numpy ndarray"):
            apply_adjustments([[0, 0, 0]], AdjustmentParams())  # type: ignore[arg-type]

    def test_错误_dtype_抛错(self) -> None:
        arr = np.zeros((8, 8, 3), dtype=np.float32)
        with pytest.raises(ValidationError, match="uint8"):
            apply_adjustments(arr, AdjustmentParams())

    def test_错误_shape_抛错(self) -> None:
        arr = np.zeros((8, 8), dtype=np.uint8)
        with pytest.raises(ValidationError, match=r"\(H, W, 3\)"):
            apply_adjustments(arr, AdjustmentParams())

    def test_通道数_非_3_抛错(self) -> None:
        arr = np.zeros((8, 8, 4), dtype=np.uint8)
        with pytest.raises(ValidationError, match=r"\(H, W, 3\)"):
            apply_adjustments(arr, AdjustmentParams())


# ============================================================
# apply_adjustments 行为
# ============================================================


def _rand_img(h: int = 16, w: int = 16, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.integers(0, 256, size=(h, w, 3), dtype=np.uint8)


class TestApplyBehavior:
    def test_identity_参数_返回相同像素(self) -> None:
        img = _rand_img()
        out = apply_adjustments(img, AdjustmentParams())
        assert np.array_equal(out, img)
        # 必须是 copy，不能返回同一对象（避免调用方意外改动缓存）
        assert out is not img

    def test_输出_dtype_始终_uint8(self) -> None:
        img = _rand_img()
        out = apply_adjustments(img, AdjustmentParams(exposure=30))
        assert out.dtype == np.uint8
        assert out.shape == img.shape

    def test_极端曝光_不溢出(self) -> None:
        img = _rand_img()
        out_pos = apply_adjustments(img, AdjustmentParams(exposure=100))
        out_neg = apply_adjustments(img, AdjustmentParams(exposure=-100))
        assert out_pos.min() >= 0 and out_pos.max() <= 255
        assert out_neg.min() >= 0 and out_neg.max() <= 255
        # 正向曝光让均值不下降；负向曝光让均值不上升
        assert out_pos.mean() >= img.mean() - 1
        assert out_neg.mean() <= img.mean() + 1

    def test_极端对比度_不溢出(self) -> None:
        img = _rand_img()
        out = apply_adjustments(img, AdjustmentParams(contrast=100))
        assert out.dtype == np.uint8
        assert out.min() >= 0 and out.max() <= 255

    def test_饱和度为_负_100_变灰度(self) -> None:
        img = _rand_img()
        out = apply_adjustments(img, AdjustmentParams(saturation=-100))
        # 全通道方差显著下降（偏向灰度）
        assert out.std(axis=2).mean() < img.std(axis=2).mean()

    def test_色温正向_偏红_偏少蓝(self) -> None:
        img = np.full((8, 8, 3), 128, dtype=np.uint8)
        out = apply_adjustments(img, AdjustmentParams(temperature=100))
        assert out[..., 0].mean() > img[..., 0].mean()
        assert out[..., 2].mean() < img[..., 2].mean()

    def test_色温负向_偏蓝_偏少红(self) -> None:
        img = np.full((8, 8, 3), 128, dtype=np.uint8)
        out = apply_adjustments(img, AdjustmentParams(temperature=-100))
        assert out[..., 0].mean() < img[..., 0].mean()
        assert out[..., 2].mean() > img[..., 2].mean()

    def test_晕影正向_边角比中心暗(self) -> None:
        img = np.full((32, 32, 3), 200, dtype=np.uint8)
        out = apply_adjustments(img, AdjustmentParams(vignette=100))
        center = out[15:17, 15:17].mean()
        corner = out[0:2, 0:2].mean()
        assert corner < center

    def test_噪点消除正值_降低方差(self) -> None:
        img = _rand_img(32, 32)
        out = apply_adjustments(img, AdjustmentParams(noise_reduction=100))
        assert out.std() < img.std()

    def test_锐度为_0_不触发_USM(self) -> None:
        img = _rand_img()
        # 仅调 exposure，sharpness=0 — 不应额外引入 USM 开销造成像素差异
        base = apply_adjustments(img, AdjustmentParams(exposure=5))
        also = apply_adjustments(img, AdjustmentParams(exposure=5, sharpness=0))
        assert np.array_equal(base, also)

    def test_清晰度为_0_不触发_USM(self) -> None:
        img = _rand_img()
        base = apply_adjustments(img, AdjustmentParams(exposure=5))
        also = apply_adjustments(img, AdjustmentParams(exposure=5, clarity=0))
        assert np.array_equal(base, also)


# ============================================================
# save_adjusted_image
# ============================================================


class TestSaveAdjustedImage:
    def _make_jpg(self, path, size=(64, 48), color=(200, 100, 50)) -> None:
        from PIL import Image

        Image.new("RGB", size, color).save(str(path), "JPEG", quality=90)

    def test_源文件不存在_抛_QxwError(self, tmp_path) -> None:
        dst = tmp_path / "out.jpg"
        with pytest.raises(QxwError, match="源文件不存在"):
            save_adjusted_image(
                tmp_path / "ghost.jpg", dst, AdjustmentParams(exposure=10)
            )

    def test_quality_越界_抛_ValidationError(self, tmp_path) -> None:
        from qxw.library.base.exceptions import ValidationError as VE

        self._make_jpg(tmp_path / "a.jpg")
        with pytest.raises(VE, match=r"\[1, 100\]"):
            save_adjusted_image(
                tmp_path / "a.jpg",
                tmp_path / "out.jpg",
                AdjustmentParams(exposure=10),
                quality=0,
            )
        with pytest.raises(VE, match=r"\[1, 100\]"):
            save_adjusted_image(
                tmp_path / "a.jpg",
                tmp_path / "out.jpg",
                AdjustmentParams(exposure=10),
                quality=101,
            )

    def test_无法打开源图_抛_QxwError(self, tmp_path) -> None:
        bad = tmp_path / "a.jpg"
        bad.write_bytes(b"not an image")
        with pytest.raises(QxwError, match="无法打开源图片"):
            save_adjusted_image(bad, tmp_path / "out.jpg", AdjustmentParams(exposure=10))

    def test_正常写出_JPEG_且尺寸保持(self, tmp_path) -> None:
        from PIL import Image

        src = tmp_path / "a.jpg"
        self._make_jpg(src, size=(128, 96))
        dst = tmp_path / "nested" / "out.jpg"

        save_adjusted_image(src, dst, AdjustmentParams(exposure=20, saturation=-50))
        assert dst.exists()
        assert dst.stat().st_size > 0

        with Image.open(dst) as out:
            assert out.size == (128, 96)
            assert out.format == "JPEG"

    def test_父目录自动创建(self, tmp_path) -> None:
        src = tmp_path / "a.jpg"
        self._make_jpg(src)
        dst = tmp_path / "a" / "b" / "c" / "out.jpg"
        save_adjusted_image(src, dst, AdjustmentParams(exposure=5))
        assert dst.exists()

    def test_identity_也会写出文件(self, tmp_path) -> None:
        # save_adjusted_image 不做 is_identity 短路判断，服务端在 /save 路由外层拦，
        # 函数本身即使 params 全 0 也应把原图重编码写到 dst
        src = tmp_path / "a.jpg"
        self._make_jpg(src)
        dst = tmp_path / "out.jpg"
        save_adjusted_image(src, dst, AdjustmentParams())
        assert dst.exists()

    def test_PNG_带_alpha_被合到白底(self, tmp_path) -> None:
        from PIL import Image

        src = tmp_path / "a.png"
        # 红色 + 半透明
        Image.new("RGBA", (32, 32), (255, 0, 0, 128)).save(str(src), "PNG")
        dst = tmp_path / "out.jpg"
        save_adjusted_image(src, dst, AdjustmentParams(exposure=0))
        with Image.open(dst) as out:
            assert out.mode == "RGB"
