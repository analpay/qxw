"""qxw.library.services.color_filters 单元测试

color_filters 提供一个可扩展滤镜注册中心。测试点：
- 注册 / 列出 / 查找 / 应用 的正确性
- 保留名 default 与重名校验
- 预置滤镜（fuji-cc / ghibli）不破坏输入形状与 dtype
"""

from __future__ import annotations

from collections.abc import Generator

import numpy as np
import pytest

from qxw.library.services import color_filters as cf


@pytest.fixture(autouse=True)
def _snapshot_registry() -> Generator[None, None, None]:
    """保护全局注册表：每个用例开始前快照、结束后还原"""
    snapshot = dict(cf._FILTER_REGISTRY)
    yield
    cf._FILTER_REGISTRY.clear()
    cf._FILTER_REGISTRY.update(snapshot)


class TestRegistry:
    def test_list_filters_包含_default_与预置滤镜(self) -> None:
        names = cf.list_filters()
        assert names == sorted(names), "应按字母序返回"
        assert "default" in names
        assert "fuji-cc" in names
        assert "ghibli" in names

    def test_register_filter_大小写不敏感(self) -> None:
        @cf.register_filter("  MyFilter  ")
        def my_filter(rgb: np.ndarray) -> np.ndarray:
            return rgb

        assert "myfilter" in cf.list_filters()
        assert cf.get_filter("MYFILTER") is my_filter
        assert cf.get_filter("myfilter") is my_filter

    def test_register_filter_空名拒绝(self) -> None:
        with pytest.raises(ValueError, match="不能为空"):

            @cf.register_filter("")
            def _f(rgb: np.ndarray) -> np.ndarray:
                return rgb

    def test_register_filter_保留名拒绝(self) -> None:
        with pytest.raises(ValueError, match="保留名"):

            @cf.register_filter("default")
            def _f(rgb: np.ndarray) -> np.ndarray:
                return rgb

    def test_register_filter_重名拒绝(self) -> None:
        @cf.register_filter("dup")
        def _a(rgb: np.ndarray) -> np.ndarray:
            return rgb

        with pytest.raises(ValueError, match="重复"):

            @cf.register_filter("dup")
            def _b(rgb: np.ndarray) -> np.ndarray:
                return rgb


class TestGetAndApply:
    def test_get_filter_default_或未知返回_None(self) -> None:
        assert cf.get_filter("default") is None
        assert cf.get_filter("") is None
        assert cf.get_filter("未注册的滤镜") is None

    def test_apply_filter_default_原样返回(self) -> None:
        rgb = np.zeros((4, 4, 3), dtype=np.uint8)
        out = cf.apply_filter(rgb, "default")
        assert out is rgb

    def test_apply_filter_未知名原样返回(self) -> None:
        rgb = np.zeros((4, 4, 3), dtype=np.uint8)
        out = cf.apply_filter(rgb, "不存在")
        assert out is rgb

    def test_apply_filter_命中注册函数(self) -> None:
        @cf.register_filter("invert")
        def invert(rgb: np.ndarray) -> np.ndarray:
            return 255 - rgb

        rgb = np.full((2, 2, 3), 10, dtype=np.uint8)
        out = cf.apply_filter(rgb, "invert")
        assert out.dtype == np.uint8
        assert np.array_equal(out, np.full((2, 2, 3), 245, dtype=np.uint8))


@pytest.mark.parametrize("name", ["fuji-cc", "ghibli"])
def test_预置滤镜保持形状和_dtype(name: str) -> None:
    rgb = np.random.default_rng(0).integers(0, 256, size=(32, 48, 3), dtype=np.uint8)
    out = cf.apply_filter(rgb, name)

    assert out.shape == rgb.shape
    assert out.dtype == np.uint8
    assert out.min() >= 0 and out.max() <= 255


def test_预置滤镜对全黑全白稳定() -> None:
    """边界输入：纯黑 / 纯白不应越界或抛异常"""
    black = np.zeros((8, 8, 3), dtype=np.uint8)
    white = np.full((8, 8, 3), 255, dtype=np.uint8)

    for name in ("fuji-cc", "ghibli"):
        b_out = cf.apply_filter(black, name)
        w_out = cf.apply_filter(white, name)
        assert b_out.dtype == np.uint8 and w_out.dtype == np.uint8
        assert 0 <= int(b_out.min()) and int(w_out.max()) <= 255
