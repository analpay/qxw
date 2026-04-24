"""qxw-image 命令入口

图片工具集，提供 RAW 批量转 JPG、SVG 转 PNG 以及对已有位图套用调色滤镜的功能。
图片浏览 HTTP 服务已迁移到 ``qxw-serve image-web`` 子命令。

用法:
    qxw-image raw                         # 将当前目录 RAW 文件批量转换为 JPG
    qxw-image raw -d ~/Photos -r          # 递归处理子目录
    qxw-image raw --filter fuji-cc        # RAW→JPG 时一步到位套用调色滤镜（单遍解码，画质更好）
    qxw-image svg                         # 将当前目录 SVG 文件批量转换为 PNG
    qxw-image filter -n fuji-cc -d imgs   # 对已有位图（JPG/PNG/TIFF/HEIC 等）批量套用调色滤镜
    qxw-image filter --list               # 列出所有已注册的调色滤镜
    qxw-image change -d imgs              # 自动亮度/对比/饱和调整 + HDR 观感（HDR 默认开启）
    qxw-image change -d imgs --no-hdr     # 关闭 HDR 局部 tone mapping
    qxw-image --help                      # 查看帮助
"""

import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import click
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeRemainingColumn

from qxw import __version__
from qxw.library.base.exceptions import QxwError
from qxw.library.base.logger import get_logger

logger = get_logger("qxw.image")
console = Console()


# ============================================================
# 依赖检测
# ============================================================


def _require_pillow() -> None:
    try:
        from PIL import Image  # noqa: F401
    except ImportError:
        raise QxwError('需要安装 Pillow 库: pip install Pillow 或 pip install "qxw[image]"') from None


def _require_rawpy() -> None:
    try:
        import rawpy  # noqa: F401
    except ImportError:
        raise QxwError('需要安装 rawpy 库: pip install rawpy 或 pip install "qxw[image]"') from None


def _require_cairosvg() -> None:
    try:
        import cairosvg  # noqa: F401
    except ImportError:
        raise QxwError('需要安装 cairosvg 库: pip install cairosvg 或 pip install "qxw[image]"') from None


# ============================================================
# CLI 入口 (Click)
# ============================================================


@click.group(
    name="qxw-image",
    help="QXW 图片工具集（RAW 批量转换 / SVG 转 PNG / 调色滤镜）",
    epilog="使用 qxw-image <子命令> --help 查看各子命令的详细帮助。图片浏览服务请使用 qxw-serve image-web。",
    invoke_without_command=True,
)
@click.version_option(
    version=__version__,
    prog_name="qxw-image",
    message="%(prog)s 版本 %(version)s",
)
@click.pass_context
def main(ctx: click.Context) -> None:
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@main.command(name="raw", help="将相机导出的 RAW 图片批量转换为 JPG")
@click.option("--dir", "-d", "directory", default=".", show_default=True, help="RAW 文件所在目录")
@click.option("--output", "-o", "output_dir", default=None, help="输出目录（默认写入源目录下的 jpg/ 子目录）")
@click.option("--recursive", "-r", is_flag=True, default=False, help="递归处理子目录")
@click.option(
    "--quality",
    "-q",
    default=92,
    show_default=True,
    type=click.IntRange(1, 100),
    help="JPEG 压缩质量 (1-100)",
)
@click.option("--overwrite/--no-overwrite", default=False, show_default=True, help="是否覆盖已存在的输出文件")
@click.option(
    "--use-embedded/--no-use-embedded",
    default=True,
    show_default=True,
    help="是否优先使用相机内嵌 JPEG 预览（默认开启，色彩与相机直出一致；关闭后始终走 rawpy 解码）",
)
@click.option(
    "--fast",
    is_flag=True,
    default=False,
    help="快速解码模式：线性去马赛克 + 半分辨率，仅对 rawpy 解码路径生效（约 8-10x 加速）",
)
@click.option(
    "--filter",
    "color_filter",
    default="default",
    show_default=True,
    help=(
        "调色滤镜插件名（可通过 qxw.library.services.color_filters.register_filter 扩展）。"
        "default=不调色、对 --use-embedded/--no-use-embedded 无影响；"
        "任意其他值会强制走 --no-use-embedded 解码路径，"
        "若同时显式指定了 --use-embedded 则直接报错退出。"
        "内置: fuji-cc（富士 Classic Chrome 胶片模拟近似）、"
        "ghibli（吉卜力动画水彩风近似：抬黑压白 + 暖调 + 柔和天空蓝 + 暖绿）。"
        "注：此路径是 RAW→滤镜→JPG 单遍流水线、画质最佳；若想对已有 JPG/PNG 批量调色，"
        "使用 `qxw-image filter` 子命令。"
    ),
)
@click.option(
    "--workers",
    "-j",
    default=None,
    type=int,
    help="并行处理线程数（默认 min(CPU 核数, 4)；-j 1 表示串行）",
)
@click.pass_context
def raw_command(
    ctx: click.Context,
    directory: str,
    output_dir: str | None,
    recursive: bool,
    quality: int,
    overwrite: bool,
    use_embedded: bool,
    fast: bool,
    color_filter: str,
    workers: int | None,
) -> None:
    """将 RAW 图片批量转换为 JPG

    扫描目录中的 RAW 文件，使用 rawpy 按相机白平衡解码并输出 JPEG。
    默认写入源目录下的 jpg/ 子目录，保持相对路径结构不变。

    \b
    支持的 RAW 格式：
      Canon (CR2/CR3), Nikon (NEF), Sony (ARW), Adobe (DNG),
      Olympus (ORF), Panasonic (RW2), Pentax (PEF), Fujifilm (RAF),
      Hasselblad (3FR), Phase One (IIQ), Leica (RWL) 等

    \b
    示例:
        qxw-image raw                          # 转换当前目录 RAW 文件到 ./jpg/
        qxw-image raw -d ~/Photos -r           # 递归处理子目录
        qxw-image raw -o ./converted           # 指定输出目录
        qxw-image raw -q 95 --overwrite        # 高质量 + 覆盖已有文件
        qxw-image raw --no-use-embedded        # 跳过嵌入预览，强制 rawpy 解码
        qxw-image raw --no-use-embedded --fast # 解码路径下再叠加半分辨率 + 线性去马赛克
        qxw-image raw --filter fuji-cc         # 套用富士 Classic Chrome 滤镜（自动 --no-use-embedded）
        qxw-image raw -j 8                     # 使用 8 个线程并行处理
    """
    try:
        _require_pillow()
        _require_rawpy()

        from qxw.library.services.color_filters import (
            DEFAULT_FILTER_NAME,
            list_filters,
        )
        from qxw.library.services.image_service import convert_raw, scan_raw_files

        dir_path = Path(directory).resolve()
        if not dir_path.is_dir():
            raise click.BadParameter(f"目录不存在: {directory}")

        # 校验滤镜名
        color_filter_norm = (color_filter or "").strip().lower()
        available_filters = list_filters()
        if color_filter_norm not in available_filters:
            raise click.BadParameter(
                f"未知的调色滤镜: {color_filter!r}。可选: {', '.join(available_filters)}",
                param_hint="--filter",
            )

        # 按需求处理滤镜与 --use-embedded 的互斥关系：
        # - default：保持历史行为，不改变 use_embedded
        # - 非 default：
        #     * 若用户显式传入 --use-embedded，直接报错退出（避免静默覆盖用户意图）
        #     * 否则强制 use_embedded = False
        filter_enabled = color_filter_norm != DEFAULT_FILTER_NAME
        if filter_enabled:
            src = ctx.get_parameter_source("use_embedded")
            if src == click.core.ParameterSource.COMMANDLINE and use_embedded:
                raise click.UsageError(
                    f"--filter {color_filter_norm} 需要对解码后的像素调色，"
                    "与 --use-embedded 互斥。请移除 --use-embedded 或改用 --no-use-embedded。"
                )
            use_embedded = False

        out_path = Path(output_dir).resolve() if output_dir else dir_path / "jpg"

        if workers is None:
            workers = min(os.cpu_count() or 4, 4)
        workers = max(1, workers)

        console.print(f"📷 [bold]QXW RAW Converter[/] v{__version__}")
        console.print(f"📁 源目录: [cyan]{dir_path}[/]")
        console.print(f"📂 输出目录: [cyan]{out_path}[/]")
        console.print(f"📊 JPEG 质量: {quality}")
        if use_embedded:
            console.print("🎨 嵌入预览: [green]优先使用[/]（与相机直出色彩一致）")
        else:
            if filter_enabled:
                console.print("🎨 嵌入预览: [yellow]已禁用[/]（调色需解码路径，自动切换）")
            else:
                console.print("🎨 嵌入预览: [yellow]已禁用[/]（强制 rawpy 解码）")
        if filter_enabled:
            console.print(f"🎛️  调色滤镜: [magenta]{color_filter_norm}[/]")
        if fast:
            console.print("⚡ 快速模式: [green]已启用[/]（半分辨率 + 线性去马赛克，仅解码路径生效）")
        console.print(f"🧵 并行线程: {workers}")
        console.print()

        raw_files = scan_raw_files(dir_path, recursive=recursive)
        if not raw_files:
            console.print("📭 未找到 RAW 文件")
            return

        console.print(f"🔍 找到 [bold]{len(raw_files)}[/] 个 RAW 文件\n")

        # 预筛选：已存在且未开启覆盖的直接计入 skip，减少线程池调度开销
        tasks: list[tuple[Path, Path]] = []
        skip_count = 0
        for raw_file in raw_files:
            rel_dir = raw_file.relative_to(dir_path).parent
            dest = out_path / rel_dir / f"{raw_file.stem}.jpg"
            if dest.exists() and not overwrite:
                skip_count += 1
                continue
            tasks.append((raw_file, dest))

        success_count = 0
        fail_count = 0

        def _run_one(item: tuple[Path, Path]) -> tuple[Path, Exception | None]:
            src, dst = item
            try:
                convert_raw(
                    src,
                    dst,
                    quality=quality,
                    use_embedded=use_embedded,
                    fast=fast,
                    color_filter=color_filter_norm,
                )
                return src, None
            except Exception as e:
                return src, e

        with Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            TimeRemainingColumn(),
            console=console,
        ) as progress:
            task_id = progress.add_task("转换中...", total=len(raw_files))
            if skip_count:
                progress.advance(task_id, skip_count)

            if workers == 1 or len(tasks) <= 1:
                for item in tasks:
                    src, err = _run_one(item)
                    if err is None:
                        success_count += 1
                    else:
                        logger.warning("转换失败 %s: %s", src.name, err)
                        fail_count += 1
                    progress.advance(task_id)
            else:
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    futures = [pool.submit(_run_one, item) for item in tasks]
                    for future in as_completed(futures):
                        src, err = future.result()
                        if err is None:
                            success_count += 1
                        else:
                            logger.warning("转换失败 %s: %s", src.name, err)
                            fail_count += 1
                        progress.advance(task_id)

        console.print()
        console.print(f"✅ 转换完成: [green]{success_count}[/] 成功", end="")
        if skip_count:
            console.print(f"，[yellow]{skip_count}[/] 跳过（已存在）", end="")
        if fail_count:
            console.print(f"，[red]{fail_count}[/] 失败", end="")
        console.print()

    except click.UsageError:
        raise  # 交给 click 自己做格式化输出和退出码（默认 2）
    except QxwError as e:
        logger.error("命令执行失败: %s", e.message)
        click.echo(f"错误: {e.message}", err=True)
        sys.exit(e.exit_code)
    except KeyboardInterrupt:
        click.echo("\n操作已取消")
        sys.exit(130)
    except Exception as e:
        logger.exception("未预期的错误")
        click.echo(f"未预期的错误: {e}", err=True)
        sys.exit(1)


@main.command(name="svg", help="将目录中的 SVG 文件批量转换为同名 PNG（同目录输出）")
@click.option("--dir", "-d", "directory", default=".", show_default=True, help="SVG 文件所在目录")
@click.option("--recursive/--no-recursive", "-r", default=True, show_default=True, help="是否递归处理子目录")
@click.option("--scale", "-s", default=2.0, show_default=True, type=float, help="输出缩放比例（1.0 为原始像素）")
@click.option(
    "--overwrite/--no-overwrite",
    default=True,
    show_default=True,
    help="是否覆盖已存在的同名 PNG（默认覆盖）",
)
@click.option(
    "--font-family",
    "font_family",
    default=None,
    help="覆盖 SVG 文本字体（CSS font-family 语法）；默认注入跨平台 CJK 字体栈避免中文变方块；传空串禁用注入",
)
@click.option(
    "--background",
    "-b",
    "background",
    type=click.Choice(["white", "transparent", "dark"], case_sensitive=False),
    default="white",
    show_default=True,
    help="PNG 背景：white（纯白 #ffffff，默认）/ transparent（透明）/ dark（深色 #0f172a）",
)
@click.option(
    "--workers",
    "-j",
    default=None,
    type=int,
    help="并行处理线程数（默认 min(CPU 核数, 4)；-j 1 表示串行）",
)
def svg_command(
    directory: str,
    recursive: bool,
    scale: float,
    overwrite: bool,
    font_family: str | None,
    background: str,
    workers: int | None,
) -> None:
    """将 SVG 文件批量转换为同名 PNG

    扫描目录中的 `.svg` 文件，使用 cairosvg 按指定缩放比例栅格化为 PNG，
    结果输出到 SVG 所在目录（同名不同后缀）。

    \b
    中文渲染:
        默认会向 SVG 注入一段 CSS，把 text/tspan 的 font-family 覆盖为含 CJK
        字形的跨平台字体栈（PingFang / YaHei / Noto CJK / Source Han 等），
        避免中文、日韩文字被渲染成方块（豆腐）。若希望保留 SVG 原始 font-family，
        可传 --font-family ""（空串）禁用注入。

    \b
    示例:
        qxw-image svg                          # 转换当前目录（含子目录）的 SVG
        qxw-image svg -d ./assets              # 指定目录
        qxw-image svg --no-recursive           # 仅处理当前目录
        qxw-image svg -s 1.0                   # 1x 输出（默认 2x 适配高 DPI 屏）
        qxw-image svg --no-overwrite           # 跳过已存在的 PNG
        qxw-image svg --font-family '"Noto Sans CJK SC", sans-serif'  # 自定义字体栈
        qxw-image svg --font-family ""         # 禁用 CJK 字体注入
        qxw-image svg -b transparent           # 输出透明底 PNG（默认为白底）
        qxw-image svg -b dark                  # 输出深色底 PNG（#0f172a）
        qxw-image svg -j 8                     # 使用 8 个线程并行处理
    """
    try:
        _require_cairosvg()

        from qxw.library.services.image_service import (
            DEFAULT_SVG_CJK_FONT_FAMILY,
            convert_svg_to_png,
            scan_svg_files,
        )

        dir_path = Path(directory).resolve()
        if not dir_path.is_dir():
            raise click.BadParameter(f"目录不存在: {directory}")

        if scale <= 0:
            raise click.BadParameter(f"--scale 必须为正数: {scale}")

        if workers is None:
            workers = min(os.cpu_count() or 4, 4)
        workers = max(1, workers)

        if font_family is None:
            font_summary = "默认 CJK 字体栈（避免中文变方块）"
        elif font_family == "":
            font_summary = "未注入（使用 SVG 原始 font-family）"
        else:
            font_summary = font_family

        bg_key = background.lower()
        bg_map = {"transparent": None, "white": "#ffffff", "dark": "#0f172a"}
        bg_color = bg_map[bg_key]
        bg_summary = {
            "transparent": "透明",
            "white": "白色 (#ffffff)",
            "dark": "深色 (#0f172a)",
        }[bg_key]

        console.print(f"🖼️  [bold]QXW SVG → PNG[/] v{__version__}")
        console.print(f"📁 源目录: [cyan]{dir_path}[/]")
        console.print(f"🔁 递归子目录: {'是' if recursive else '否'}")
        console.print(f"🔍 缩放比例: {scale}x")
        console.print(f"♻️  覆盖模式: {'覆盖' if overwrite else '跳过已存在'}")
        console.print(f"🔤 字体策略: {font_summary}")
        console.print(f"🎨 背景: {bg_summary}")
        console.print(f"🧵 并行线程: {workers}")
        console.print()

        effective_font = DEFAULT_SVG_CJK_FONT_FAMILY if font_family is None else font_family

        svg_files = scan_svg_files(dir_path, recursive=recursive)
        if not svg_files:
            console.print("📭 未找到 SVG 文件")
            return

        console.print(f"🔍 找到 [bold]{len(svg_files)}[/] 个 SVG 文件\n")

        tasks: list[tuple[Path, Path]] = []
        skip_count = 0
        for svg_file in svg_files:
            dest = svg_file.with_suffix(".png")
            if dest.exists() and not overwrite:
                skip_count += 1
                continue
            tasks.append((svg_file, dest))

        success_count = 0
        fail_count = 0

        def _run_one(item: tuple[Path, Path]) -> tuple[Path, Exception | None]:
            src, dst = item
            try:
                convert_svg_to_png(
                    src, dst, scale=scale, font_family=effective_font, background_color=bg_color
                )
                return src, None
            except Exception as e:
                return src, e

        with Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            TimeRemainingColumn(),
            console=console,
        ) as progress:
            task_id = progress.add_task("转换中...", total=len(svg_files))
            if skip_count:
                progress.advance(task_id, skip_count)

            if workers == 1 or len(tasks) <= 1:
                for item in tasks:
                    src, err = _run_one(item)
                    if err is None:
                        success_count += 1
                    else:
                        logger.warning("转换失败 %s: %s", src.name, err)
                        fail_count += 1
                    progress.advance(task_id)
            else:
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    futures = [pool.submit(_run_one, item) for item in tasks]
                    for future in as_completed(futures):
                        src, err = future.result()
                        if err is None:
                            success_count += 1
                        else:
                            logger.warning("转换失败 %s: %s", src.name, err)
                            fail_count += 1
                        progress.advance(task_id)

        console.print()
        console.print(f"✅ 转换完成: [green]{success_count}[/] 成功", end="")
        if skip_count:
            console.print(f"，[yellow]{skip_count}[/] 跳过（已存在）", end="")
        if fail_count:
            console.print(f"，[red]{fail_count}[/] 失败", end="")
        console.print()

    except QxwError as e:
        logger.error("命令执行失败: %s", e.message)
        click.echo(f"错误: {e.message}", err=True)
        sys.exit(e.exit_code)
    except KeyboardInterrupt:
        click.echo("\n操作已取消")
        sys.exit(130)
    except Exception as e:
        logger.exception("未预期的错误")
        click.echo(f"未预期的错误: {e}", err=True)
        sys.exit(1)


@main.command(name="filter", help="对已有位图批量套用调色滤镜（JPG/PNG/WebP/BMP/TIFF/HEIC）")
@click.option("--dir", "-d", "directory", default=".", show_default=True, help="输入目录")
@click.option("--output", "-o", "output_dir", default=None, help="输出目录（默认 <源目录>/filtered）")
@click.option("--recursive", "-r", is_flag=True, default=False, help="递归处理子目录")
@click.option(
    "--name",
    "-n",
    "filter_name",
    default=None,
    help="调色滤镜名（必填，除非用 --list）。可用名见 --list，可通过 register_filter 扩展。",
)
@click.option(
    "--quality",
    "-q",
    default=92,
    show_default=True,
    type=click.IntRange(1, 100),
    help="JPEG 压缩质量 (1-100)",
)
@click.option(
    "--overwrite/--no-overwrite",
    default=False,
    show_default=True,
    help="是否覆盖已存在的输出文件",
)
@click.option(
    "--workers",
    "-j",
    default=None,
    type=int,
    help="并行处理线程数（默认 min(CPU 核数, 4)；-j 1 表示串行）",
)
@click.option(
    "--list",
    "list_filters_flag",
    is_flag=True,
    default=False,
    help="列出所有已注册的调色滤镜名后退出",
)
def filter_command(
    directory: str,
    output_dir: str | None,
    recursive: bool,
    filter_name: str | None,
    quality: int,
    overwrite: bool,
    workers: int | None,
    list_filters_flag: bool,
) -> None:
    """对已有位图批量套用调色滤镜

    对 :func:`qxw.library.services.image_service.scan_filterable_images` 找到
    的每个位图文件，调用 :func:`apply_filter_to_image` 执行"PIL 解码 → numpy →
    apply_filter → JPEG 编码"一次，输出到 ``<output>/<rel_path_stem>.jpg``。

    \b
    不支持 RAW 输入：
      如果你想对 RAW 文件一次到位地"解码 + 调色"，请使用：
          qxw-image raw --filter <name>
      这条路径是 RAW→滤镜→JPG 的单遍流水线，避免 JPEG 的二次编解码损失。

    \b
    支持格式：
      JPG, PNG, WebP, BMP, TIFF, HEIC, HEIF

    \b
    示例:
        qxw-image filter --list                          # 查看所有可用滤镜
        qxw-image filter -n fuji-cc                      # 当前目录 → ./filtered/
        qxw-image filter -n ghibli -d ~/Photos -r        # 递归处理子目录
        qxw-image filter -n fuji-cc -o out --overwrite   # 指定输出目录并覆盖已有文件
        qxw-image filter -n ghibli -q 95 -j 8            # 高质量 + 8 线程
    """
    try:
        _require_pillow()

        from qxw.library.services.color_filters import (
            DEFAULT_FILTER_NAME,
            list_filters,
        )

        if list_filters_flag:
            console.print(f"🎛️  [bold]QXW 调色滤镜[/] v{__version__}")
            console.print("已注册滤镜（default 为保留名，表示不调色）:\n")
            for name in list_filters():
                if name == DEFAULT_FILTER_NAME:
                    console.print(f"  • [dim]{name}[/] [dim](无操作占位)[/]")
                else:
                    console.print(f"  • [magenta]{name}[/]")
            console.print()
            return

        if not filter_name:
            raise click.UsageError(
                "缺少 --name/-n 参数。使用 --list 查看所有可用滤镜。"
            )

        filter_name_norm = filter_name.strip().lower()
        available = list_filters()
        if filter_name_norm not in available:
            raise click.BadParameter(
                f"未知的调色滤镜: {filter_name!r}。可选: {', '.join(available)}",
                param_hint="--name",
            )
        if filter_name_norm == DEFAULT_FILTER_NAME:
            raise click.BadParameter(
                "filter 子命令不接受 default（default 是无操作占位名）。"
                "请指定具体滤镜名，或用 --list 查看全部可选。",
                param_hint="--name",
            )

        from qxw.library.services.image_service import (
            apply_filter_to_image,
            scan_filterable_images,
        )

        dir_path = Path(directory).resolve()
        if not dir_path.is_dir():
            raise click.BadParameter(f"目录不存在: {directory}")

        out_path = Path(output_dir).resolve() if output_dir else dir_path / "filtered"

        if workers is None:
            workers = min(os.cpu_count() or 4, 4)
        workers = max(1, workers)

        console.print(f"🎛️  [bold]QXW Image Filter[/] v{__version__}")
        console.print(f"📁 源目录: [cyan]{dir_path}[/]")
        console.print(f"📂 输出目录: [cyan]{out_path}[/]")
        console.print(f"🎨 调色滤镜: [magenta]{filter_name_norm}[/]")
        console.print(f"📊 JPEG 质量: {quality}")
        console.print(f"🧵 并行线程: {workers}")
        console.print()

        image_files = scan_filterable_images(dir_path, recursive=recursive)
        if not image_files:
            console.print("📭 未找到可调色的位图文件")
            return

        console.print(f"🔍 找到 [bold]{len(image_files)}[/] 个位图文件\n")

        tasks: list[tuple[Path, Path]] = []
        skip_count = 0
        out_resolved = out_path.resolve()
        for src in image_files:
            # 递归扫描 + 输出在源目录内部时，跳过输出目录里的旧产物，避免把滤镜叠加到自己身上
            try:
                src.resolve().relative_to(out_resolved)
                skip_count += 1
                continue
            except ValueError:
                pass

            rel_dir = src.relative_to(dir_path).parent
            dst = out_path / rel_dir / f"{src.stem}.jpg"
            if dst.exists() and not overwrite:
                skip_count += 1
                continue
            tasks.append((src, dst))

        success_count = 0
        fail_count = 0

        def _run_one(item: tuple[Path, Path]) -> tuple[Path, Exception | None]:
            src, dst = item
            try:
                apply_filter_to_image(src, dst, filter_name_norm, quality=quality)
                return src, None
            except Exception as e:
                return src, e

        with Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            TimeRemainingColumn(),
            console=console,
        ) as progress:
            task_id = progress.add_task("调色中...", total=len(image_files))
            if skip_count:
                progress.advance(task_id, skip_count)

            if workers == 1 or len(tasks) <= 1:
                for item in tasks:
                    src, err = _run_one(item)
                    if err is None:
                        success_count += 1
                    else:
                        logger.warning("调色失败 %s: %s", src.name, err)
                        fail_count += 1
                    progress.advance(task_id)
            else:
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    futures = [pool.submit(_run_one, item) for item in tasks]
                    for future in as_completed(futures):
                        src, err = future.result()
                        if err is None:
                            success_count += 1
                        else:
                            logger.warning("调色失败 %s: %s", src.name, err)
                            fail_count += 1
                        progress.advance(task_id)

        console.print()
        console.print(f"✅ 调色完成: [green]{success_count}[/] 成功", end="")
        if skip_count:
            console.print(f"，[yellow]{skip_count}[/] 跳过（已存在或输出即自身）", end="")
        if fail_count:
            console.print(f"，[red]{fail_count}[/] 失败", end="")
        console.print()

    except click.UsageError:
        raise  # 交给 click 做格式化输出
    except QxwError as e:
        logger.error("命令执行失败: %s", e.message)
        click.echo(f"错误: {e.message}", err=True)
        sys.exit(e.exit_code)
    except KeyboardInterrupt:
        click.echo("\n操作已取消")
        sys.exit(130)
    except Exception as e:
        logger.exception("未预期的错误")
        click.echo(f"未预期的错误: {e}", err=True)
        sys.exit(1)


@main.command(
    name="change",
    help="对已有位图做自动亮度/对比/饱和调整（可选 HDR 观感）",
)
@click.option("--dir", "-d", "directory", default=".", show_default=True, help="输入目录")
@click.option("--output", "-o", "output_dir", default=None, help="输出目录（默认 <源目录>/changed）")
@click.option("--recursive", "-r", is_flag=True, default=False, help="递归处理子目录")
@click.option(
    "--intensity",
    "-i",
    type=click.Choice(["subtle", "balanced", "punchy"], case_sensitive=False),
    default="balanced",
    show_default=True,
    help="档位预设：subtle 温和 / balanced 平衡 / punchy 强烈",
)
@click.option(
    "--hdr/--no-hdr",
    default=True,
    show_default=True,
    help="启用 HDR 局部 tone mapping（base/detail 分解 + 高光压缩 + 细节放大）；默认开启",
)
@click.option(
    "--preserve-exif/--no-preserve-exif",
    default=True,
    show_default=True,
    help="是否保留源图 EXIF（orientation tag 会自动清为 1，像素已实际旋转）",
)
@click.option(
    "--quality",
    "-q",
    default=92,
    show_default=True,
    type=click.IntRange(1, 100),
    help="JPEG 压缩质量 (1-100)",
)
@click.option(
    "--overwrite/--no-overwrite",
    default=False,
    show_default=True,
    help="是否覆盖已存在的输出文件",
)
@click.option(
    "--workers",
    "-j",
    default=None,
    type=int,
    help="并行处理线程数（默认 min(CPU 核数, 4)；-j 1 表示串行）",
)
def change_command(
    directory: str,
    output_dir: str | None,
    recursive: bool,
    intensity: str,
    hdr: bool,
    preserve_exif: bool,
    quality: int,
    overwrite: bool,
    workers: int | None,
) -> None:
    """对已有位图做自动亮度/对比/饱和调整

    采用 :mod:`qxw.library.services.auto_enhance` 的算法：

    \b
    核心流程：
      1. sRGB → LAB
      2. 暗光照片走 IAGCWD-style 自适应 gamma；
         正常照片走 auto-levels（百分位拉伸）+ CLAHE（局部对比度）+ 中位数 gamma
      3. HDR 开启时额外做 base/detail 分解 + 高光压缩 + 细节放大
      4. LAB → sRGB → HSV，肤色区域 vibrance 打折后做饱和提升
      5. 回 RGB 并编码为 JPEG

    \b
    档位说明：
      subtle    参数保守，输出接近原图，适合本身已经不错只想微调
      balanced  默认档，日常照片 90% 情况最合适
      punchy    参数激进，细节 / 饱和 / 对比都更强，适合压缩明显或灰度大的图

    \b
    支持格式：
      JPG, PNG, WebP, BMP, TIFF, HEIC, HEIF

    \b
    示例:
        qxw-image change                                 # 当前目录 → ./changed/（HDR 默认开启）
        qxw-image change -d ~/Photos -r                  # 递归处理子目录
        qxw-image change -i punchy                       # 强力档 + HDR（HDR 默认开启）
        qxw-image change --no-hdr                        # 关闭 HDR 局部 tone mapping
        qxw-image change -i subtle --no-preserve-exif    # 温和档 + 去 EXIF
        qxw-image change -q 95 -j 8 --overwrite          # 高质量 + 8 线程 + 覆盖
    """
    try:
        _require_pillow()

        from qxw.library.services.auto_enhance import AVAILABLE_INTENSITIES
        from qxw.library.services.image_service import (
            auto_enhance_image,
            scan_filterable_images,
        )

        intensity_norm = intensity.strip().lower()
        if intensity_norm not in AVAILABLE_INTENSITIES:
            raise click.BadParameter(
                f"未知的 intensity: {intensity!r}。可选: {', '.join(AVAILABLE_INTENSITIES)}",
                param_hint="--intensity",
            )

        dir_path = Path(directory).resolve()
        if not dir_path.is_dir():
            raise click.BadParameter(f"目录不存在: {directory}")

        out_path = Path(output_dir).resolve() if output_dir else dir_path / "changed"

        if workers is None:
            workers = min(os.cpu_count() or 4, 4)
        workers = max(1, workers)

        console.print(f"✨ [bold]QXW Image Auto-Enhance[/] v{__version__}")
        console.print(f"📁 源目录: [cyan]{dir_path}[/]")
        console.print(f"📂 输出目录: [cyan]{out_path}[/]")
        console.print(f"🎚️  档位: [magenta]{intensity_norm}[/]")
        console.print(f"🌄 HDR: {'开启' if hdr else '关闭'}")
        console.print(f"🏷️  EXIF: {'保留' if preserve_exif else '丢弃'}")
        console.print(f"📊 JPEG 质量: {quality}")
        console.print(f"🧵 并行线程: {workers}")
        console.print()

        image_files = scan_filterable_images(dir_path, recursive=recursive)
        if not image_files:
            console.print("📭 未找到可增强的位图文件")
            return

        console.print(f"🔍 找到 [bold]{len(image_files)}[/] 个位图文件\n")

        tasks: list[tuple[Path, Path]] = []
        skip_count = 0
        out_resolved = out_path.resolve()
        for src in image_files:
            # 递归扫描时跳过输出目录里的旧产物（避免把增强叠加到自己身上）
            try:
                src.resolve().relative_to(out_resolved)
                skip_count += 1
                continue
            except ValueError:
                pass

            rel_dir = src.relative_to(dir_path).parent
            dst = out_path / rel_dir / f"{src.stem}.jpg"
            if dst.exists() and not overwrite:
                skip_count += 1
                continue
            tasks.append((src, dst))

        success_count = 0
        fail_count = 0

        def _run_one(item: tuple[Path, Path]) -> tuple[Path, Exception | None]:
            src, dst = item
            try:
                auto_enhance_image(
                    src,
                    dst,
                    intensity=intensity_norm,
                    hdr=hdr,
                    quality=quality,
                    preserve_exif=preserve_exif,
                )
                return src, None
            except Exception as e:
                return src, e

        with Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            TimeRemainingColumn(),
            console=console,
        ) as progress:
            task_id = progress.add_task("增强中...", total=len(image_files))
            if skip_count:
                progress.advance(task_id, skip_count)

            if workers == 1 or len(tasks) <= 1:
                for item in tasks:
                    src, err = _run_one(item)
                    if err is None:
                        success_count += 1
                    else:
                        logger.warning("增强失败 %s: %s", src.name, err)
                        fail_count += 1
                    progress.advance(task_id)
            else:
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    futures = [pool.submit(_run_one, item) for item in tasks]
                    for future in as_completed(futures):
                        src, err = future.result()
                        if err is None:
                            success_count += 1
                        else:
                            logger.warning("增强失败 %s: %s", src.name, err)
                            fail_count += 1
                        progress.advance(task_id)

        console.print()
        console.print(f"✅ 增强完成: [green]{success_count}[/] 成功", end="")
        if skip_count:
            console.print(f"，[yellow]{skip_count}[/] 跳过（已存在或输出即自身）", end="")
        if fail_count:
            console.print(f"，[red]{fail_count}[/] 失败", end="")
        console.print()

    except click.UsageError:
        raise
    except QxwError as e:
        logger.error("命令执行失败: %s", e.message)
        click.echo(f"错误: {e.message}", err=True)
        sys.exit(e.exit_code)
    except KeyboardInterrupt:
        click.echo("\n操作已取消")
        sys.exit(130)
    except Exception as e:
        logger.exception("未预期的错误")
        click.echo(f"未预期的错误: {e}", err=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
