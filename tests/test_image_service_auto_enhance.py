"""qxw.library.services.image_service.auto_enhance_image 的服务层测试

覆盖文件 IO / EXIF / 格式转换 / 异常分支，真实调用 Pillow（不 mock）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from PIL import Image

from qxw.library.services import image_service as isvc


def _make_rgb_jpeg(path: Path, size: tuple[int, int] = (16, 16), color: tuple[int, int, int] = (120, 80, 60)) -> None:
    """写一张纯色 JPEG 到磁盘（非纯色即可避免单色退化）"""
    img = Image.new("RGB", size, color)
    # 加一个像素噪声，避免方差 0
    img.putpixel((0, 0), (color[0] + 10, color[1] + 5, color[2] + 8))
    img.save(path, "JPEG", quality=90)


def _make_rgba_png(path: Path) -> None:
    img = Image.new("RGBA", (16, 16), (200, 100, 50, 128))
    img.putpixel((0, 0), (50, 150, 200, 255))
    img.save(path, "PNG")


class TestInputValidation:
    def test_源文件不存在_抛_FileNotFoundError(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            isvc.auto_enhance_image(tmp_path / "nope.jpg", tmp_path / "out.jpg")

    def test_非法_intensity_抛_ValueError(self, tmp_path: Path) -> None:
        src = tmp_path / "a.jpg"
        _make_rgb_jpeg(src)
        with pytest.raises(ValueError, match="intensity"):
            isvc.auto_enhance_image(src, tmp_path / "out.jpg", intensity="xxx")

    @pytest.mark.parametrize("bad_q", [0, 101, -5, 200])
    def test_非法_quality_抛_ValueError(self, tmp_path: Path, bad_q: int) -> None:
        src = tmp_path / "a.jpg"
        _make_rgb_jpeg(src)
        with pytest.raises(ValueError, match="quality"):
            isvc.auto_enhance_image(src, tmp_path / "out.jpg", quality=bad_q)


class TestOutputPath:
    def test_父目录自动创建(self, tmp_path: Path) -> None:
        src = tmp_path / "a.jpg"
        _make_rgb_jpeg(src)
        dst = tmp_path / "deeper" / "nested" / "out.jpg"
        isvc.auto_enhance_image(src, dst)
        assert dst.exists()

    def test_输出为_JPEG_格式(self, tmp_path: Path) -> None:
        src = tmp_path / "a.jpg"
        _make_rgb_jpeg(src)
        dst = tmp_path / "out.jpg"
        isvc.auto_enhance_image(src, dst)
        with Image.open(dst) as img:
            assert img.format == "JPEG"

    def test_PNG_源_RGBA_合并白底(self, tmp_path: Path) -> None:
        src = tmp_path / "a.png"
        _make_rgba_png(src)
        dst = tmp_path / "out.jpg"
        isvc.auto_enhance_image(src, dst)
        # 输出应为 3 通道（合并后），且不含 alpha
        with Image.open(dst) as img:
            assert img.mode == "RGB"


class TestExif:
    def _save_with_exif(self, path: Path, orientation: int = 1) -> None:
        img = Image.new("RGB", (16, 24), (150, 100, 50))
        img.putpixel((0, 0), (10, 200, 100))
        exif = img.getexif()
        exif[274] = orientation  # orientation tag
        exif[306] = "2025:01:01 12:00:00"  # DateTime，用于验证保留
        img.save(path, "JPEG", exif=exif.tobytes(), quality=90)

    def test_preserve_exif_默认保留_DateTime(self, tmp_path: Path) -> None:
        src = tmp_path / "a.jpg"
        self._save_with_exif(src)
        dst = tmp_path / "out.jpg"
        isvc.auto_enhance_image(src, dst)
        with Image.open(dst) as img:
            exif = img.getexif()
            assert exif.get(306) == "2025:01:01 12:00:00"

    def test_preserve_exif_关闭时丢弃(self, tmp_path: Path) -> None:
        src = tmp_path / "a.jpg"
        self._save_with_exif(src)
        dst = tmp_path / "out.jpg"
        isvc.auto_enhance_image(src, dst, preserve_exif=False)
        with Image.open(dst) as img:
            exif = img.getexif()
            assert exif.get(306) is None

    def test_orientation_被清为_1_避免双重旋转(self, tmp_path: Path) -> None:
        src = tmp_path / "rot.jpg"
        # orientation 6 = 顺时针旋转 270°（拍摄竖向 / 存储为横向）
        self._save_with_exif(src, orientation=6)
        dst = tmp_path / "out.jpg"
        isvc.auto_enhance_image(src, dst)
        with Image.open(dst) as img:
            exif = img.getexif()
            # orientation 必须被重置为 1（或被删除）；像素已物理旋转
            assert exif.get(274) in (1, None)

    def test_orientation_6_像素被物理旋转(self, tmp_path: Path) -> None:
        """源图 16×24 + orientation=6，物理像素应被旋转为 24×16"""
        src = tmp_path / "rot.jpg"
        self._save_with_exif(src, orientation=6)
        dst = tmp_path / "out.jpg"
        isvc.auto_enhance_image(src, dst)
        with Image.open(dst) as img:
            # 原 16×24 经过 orientation=6 的处理应变为 24×16
            assert img.size == (24, 16)

    def test_无_EXIF_源图不崩(self, tmp_path: Path) -> None:
        src = tmp_path / "a.jpg"
        _make_rgb_jpeg(src)  # 无自定义 EXIF
        dst = tmp_path / "out.jpg"
        isvc.auto_enhance_image(src, dst, preserve_exif=True)
        assert dst.exists()


class TestHeic:
    def test_HEIC_无依赖时_RuntimeError(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # 造一个看起来是 heic 后缀的空文件；_open_heic_as_pil 应返回 None，进而 raise RuntimeError
        src = tmp_path / "a.heic"
        src.write_bytes(b"")
        # 强制 pillow_heif 导入失败
        monkeypatch.setitem(sys.modules, "pillow_heif", None)
        with pytest.raises(RuntimeError, match="HEIC"):
            isvc.auto_enhance_image(src, tmp_path / "out.jpg")


class TestResetExifOrientation:
    def test_空_EXIF_不炸(self) -> None:
        out = isvc._reset_exif_orientation(b"")
        # 空输入返回空，不崩
        assert isinstance(out, bytes)

    def test_损坏_EXIF_原样返回(self) -> None:
        junk = b"not_valid_exif_bytes_xxxxx"
        out = isvc._reset_exif_orientation(junk)
        # 解析失败就原样返回，不抛
        assert isinstance(out, bytes)
        assert out == junk

    def test_含_orientation_被清为_1(self) -> None:
        img = Image.new("RGB", (4, 4), (0, 0, 0))
        exif = img.getexif()
        exif[274] = 6
        exif[306] = "2025:01:01 00:00:00"
        raw = exif.tobytes()
        out = isvc._reset_exif_orientation(raw)
        # 重新解析，orientation 应为 1 且 DateTime 保留
        exif2 = Image.Exif()
        exif2.load(out)
        assert exif2.get(274) == 1
        assert exif2.get(306) == "2025:01:01 00:00:00"
