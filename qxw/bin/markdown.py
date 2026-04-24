"""qxw-markdown 命令入口

Markdown 文档优化工具集，提供以下子命令：

- ``wx``：将 Markdown 中的 PlantUML 代码围栏本地渲染为图片，并生成一份
  可直接粘贴到微信公众号编辑器的 ``_wx.md`` 副本。
- ``cover``：通过 ZenMux 接入 Google Gemini 3 Pro Image Preview
  (Nano Banana Pro) 图像模型，为 Markdown 文档生成白皮书风格的封面图。
- ``summary``：扫描目录结构，为每个包含 README.md 的目录生成 SUMMARY.md 和
  INDEX.md 目录文件（适配 Gitbook / 文档站）。

用法:
    qxw-markdown wx path/to/doc.md                    # PNG + 白底（默认）
    qxw-markdown wx doc.md -f svg -b transparent      # 透明背景 SVG
    qxw-markdown wx doc.md -f jpg -b black -q 95      # 黑底高质量 JPG
    qxw-markdown cover path/to/doc.md                 # 生成 <stem>_cover.png
    qxw-markdown summary                              # 为当前目录生成 SUMMARY.md
    qxw-markdown summary -d docs/ --depth 5           # 指定目录和层级深度
    qxw-markdown --help                               # 查看帮助
"""

import os
import sys
from pathlib import Path

import click
from rich.console import Console

from qxw import __version__
from qxw.library.base.exceptions import QxwError
from qxw.library.base.logger import get_logger

logger = get_logger("qxw.markdown")
console = Console()


@click.group(
    name="qxw-markdown",
    help="QXW Markdown 工具集（PlantUML 渲染 / 公众号适配 / AI 封面生成 / SUMMARY 目录生成）",
    epilog="使用 qxw-markdown <子命令> --help 查看各子命令的详细帮助。",
    invoke_without_command=True,
)
@click.version_option(
    version=__version__,
    prog_name="qxw-markdown",
    message="%(prog)s 版本 %(version)s",
)
@click.pass_context
def main(ctx: click.Context) -> None:
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@main.command(name="wx", help="将 Markdown 的 PlantUML 围栏转成图片并生成 _wx.md（适配微信公众号）")
@click.argument("markdown_file", type=click.Path(exists=True, dir_okay=False, path_type=str))
@click.option(
    "--format",
    "-f",
    "fmt",
    type=click.Choice(["png", "svg", "jpg"], case_sensitive=False),
    default="png",
    show_default=True,
    help="输出图片格式",
)
@click.option(
    "--background",
    "-b",
    "background",
    type=click.Choice(["white", "black", "transparent"], case_sensitive=False),
    default="white",
    show_default=True,
    help="图片背景：white（默认）/ black / transparent",
)
@click.option(
    "--output",
    "-o",
    "output",
    default=None,
    help="输出 Markdown 路径（默认 <源>_wx.md，与源文件同目录）",
)
@click.option(
    "--plantuml-jar",
    "jar_path",
    default=None,
    help="plantuml.jar 路径（默认读环境变量 PLANTUML_JAR；再退回 ~/.config/qxw/plantuml.jar）",
)
@click.option(
    "--java",
    "java_bin",
    default="java",
    show_default=True,
    help="java 可执行文件名或完整路径",
)
@click.option(
    "--scale",
    "-s",
    default=2.0,
    show_default=True,
    type=float,
    help="PNG/JPG 的输出缩放比（SVG 忽略）",
)
@click.option(
    "--font-family",
    "font_family",
    default=None,
    help="覆盖输出图片中 text/tspan 的 CSS font-family；传空串 \"\" 禁用 CJK 字体注入",
)
@click.option(
    "--plantuml-font",
    "plantuml_font_name",
    default="PingFang SC",
    show_default=True,
    help="注入到 PlantUML skinparam defaultFontName 的字体名",
)
@click.option(
    "--quality",
    "-q",
    default=92,
    show_default=True,
    type=click.IntRange(1, 100),
    help="JPG 压缩质量 (1-100)，仅对 --format jpg 生效",
)
def wx_command(
    markdown_file: str,
    fmt: str,
    background: str,
    output: str | None,
    jar_path: str | None,
    java_bin: str,
    scale: float,
    font_family: str | None,
    plantuml_font_name: str,
    quality: int,
) -> None:
    """把 Markdown 里的 PlantUML 代码围栏渲染为图片，并生成 _wx.md。

    渲染走本地 plantuml.jar：Python 调用 `java -jar plantuml.jar -tsvg -pipe`
    得到 SVG，再按目标格式分发：

    \b
    - svg：注入跨平台 CJK 字体栈 CSS，按需叠加背景色 rect 后写盘
    - png：cairosvg 栅格化并合成背景色
    - jpg：cairosvg → PIL，合成目标背景后存 JPEG（透明背景会落成白色）

    \b
    识别的代码围栏语言标识：
        ```plantuml ... ```
        ```puml     ... ```
        ```uml      ... ```

    \b
    生成文件命名规则（与源同目录）：
        <stem>_wx.md                    # 新 Markdown（代码围栏被替换为图片引用）
        <stem>_1.<ext> / <stem>_2.<ext> # 按出现顺序编号（从 1 起）

    \b
    中文渲染：
        1. 在 PlantUML 源里注入 skinparam defaultFontName（给 Java 端兜底）
        2. 对最终 SVG 注入 CSS CJK 字体栈（PingFang / YaHei / Noto 等）
        两步叠加，不论 svg / png / jpg 都能避免中文被渲染成方块。

    \b
    示例:
        qxw-markdown wx docs/foo.md                         # 默认 PNG + 白底
        qxw-markdown wx docs/foo.md -f svg -b transparent   # 透明底 SVG
        qxw-markdown wx docs/foo.md -f jpg -b black -q 95   # 黑底高质量 JPG
        qxw-markdown wx docs/foo.md --plantuml-jar ~/bin/plantuml.jar
    """
    try:
        from qxw.library.services.markdown_service import convert_markdown_for_wx

        md_path = Path(markdown_file).expanduser().resolve()
        out_path = Path(output).expanduser().resolve() if output else None
        jar = Path(jar_path).expanduser().resolve() if jar_path else None

        console.print(f"📝 [bold]QXW Markdown → 公众号版[/] v{__version__}")
        console.print(f"📄 源文件: [cyan]{md_path}[/]")
        console.print(f"🖼️  图片格式: {fmt}")
        console.print(f"🎨 背景: {background}")
        if fmt in ("png", "jpg"):
            console.print(f"🔍 缩放比例: {scale}x")
        if fmt == "jpg":
            console.print(f"📊 JPG 质量: {quality}")
        console.print()

        with console.status("[bold blue]正在渲染 PlantUML..."):
            result = convert_markdown_for_wx(
                md_path=md_path,
                fmt=fmt.lower(),
                background=background.lower(),
                out_path=out_path,
                jar_path=jar,
                java_bin=java_bin,
                scale=scale,
                font_family=font_family,
                plantuml_font_name=plantuml_font_name,
                quality=quality,
            )

        if not result.image_paths:
            console.print("📭 未发现任何 PlantUML 代码围栏，已按原样复制为:")
            console.print(f"   [green]{result.output_md}[/]")
            return

        console.print(f"✅ 已生成 [green]{len(result.image_paths)}[/] 张图片:")
        for p in result.image_paths:
            console.print(f"   📎 {p}")
        console.print()
        console.print(f"📘 新 Markdown: [green]{result.output_md}[/]")

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
    name="cover",
    help="调用 ZenMux 的 Gemini 3 Pro Image Preview 为 Markdown 生成封面图",
)
@click.argument("markdown_file", type=click.Path(exists=True, dir_okay=False, path_type=str))
@click.option(
    "--output",
    "-o",
    "output",
    default=None,
    help="输出图片路径（默认 <md 同目录>/<stem>_cover.png）",
)
@click.option(
    "--api-key",
    "api_key",
    default=None,
    help="ZenMux API Key；默认读环境变量 ZENMUX_API_KEY，再回退 setting.json 的 zenmux_api_key",
)
@click.option(
    "--model",
    "-m",
    "model",
    default=None,
    help="覆盖默认模型名（默认 google/gemini-3-pro-image-preview）",
)
@click.option(
    "--base-url",
    "base_url",
    default=None,
    help="覆盖 ZenMux Vertex AI 地址（默认 https://zenmux.ai/api/vertex-ai）",
)
@click.option(
    "--extra-prompt",
    "extra_prompt",
    default=None,
    help="附加到主 prompt 末尾的额外说明（例如：强调主题关键词）",
)
@click.option(
    "--style-prompt",
    "style_prompt",
    default=None,
    help="覆盖主视觉风格 prompt（默认使用内置白皮书 / 技术架构图风格）",
)
@click.option(
    "--truncate",
    default=None,
    type=int,
    help="Markdown 正文截断长度（字符数，<=0 不截断，默认 65536）",
)
def cover_command(
    markdown_file: str,
    output: str | None,
    api_key: str | None,
    model: str | None,
    base_url: str | None,
    extra_prompt: str | None,
    style_prompt: str | None,
    truncate: int | None,
) -> None:
    """读取 Markdown 内容，调用 ZenMux 图像模型生成白皮书风格封面 PNG。

    \b
    API Key 三级回退（优先级从高到低）：
        1. 命令行 --api-key
        2. 环境变量 ZENMUX_API_KEY
        3. ~/.config/qxw/setting.json 的 zenmux_api_key 字段

    \b
    默认行为：
        - 输入 docs/foo.md → 生成 docs/foo_cover.png
        - 模型：google/gemini-3-pro-image-preview（Nano Banana Pro）
        - 风格：技术白皮书 / 浅绿网格 / 青蓝结构 / 橙绿数据流 / LaTeX 公式

    \b
    示例:
        export ZENMUX_API_KEY=sk-zm-xxx
        qxw-markdown cover docs/article.md
        qxw-markdown cover docs/article.md -o out/cover.png
        qxw-markdown cover docs/article.md --extra-prompt "突出网络拓扑与时序"
        qxw-markdown cover docs/article.md --style-prompt "minimalistic flat isometric illustration..."
    """
    try:
        from qxw.config.settings import get_settings
        from qxw.library.services.cover_service import (
            DEFAULT_COVER_STYLE_PROMPT,
            DEFAULT_MARKDOWN_TRUNCATE,
            generate_cover,
        )

        settings = get_settings()

        # API Key 三级回退
        resolved_api_key = (
            (api_key or "").strip()
            or os.environ.get("ZENMUX_API_KEY", "").strip()
            or (settings.zenmux_api_key or "").strip()
        )

        resolved_model = model or settings.zenmux_image_model
        resolved_base_url = base_url or settings.zenmux_base_url
        resolved_style = style_prompt or DEFAULT_COVER_STYLE_PROMPT
        resolved_truncate = truncate if truncate is not None else DEFAULT_MARKDOWN_TRUNCATE

        md_path = Path(markdown_file).expanduser().resolve()
        out_path = Path(output).expanduser().resolve() if output else None

        console.print(f"🎨 [bold]QXW Markdown → 封面生成[/] v{__version__}")
        console.print(f"📄 源文件: [cyan]{md_path}[/]")
        console.print(f"🤖 模型: {resolved_model}")
        if base_url:
            console.print(f"🌐 API: {resolved_base_url}")
        console.print()

        with console.status("[bold blue]正在调用 ZenMux 生成封面..."):
            result = generate_cover(
                md_path=md_path,
                api_key=resolved_api_key,
                output_path=out_path,
                model=resolved_model,
                base_url=resolved_base_url,
                style_prompt=resolved_style,
                extra_prompt=extra_prompt,
                truncate=resolved_truncate,
            )

        console.print(f"✅ 已生成封面: [green]{result.output_path}[/]")
        console.print(f"📝 prompt 长度: {result.prompt_chars} 字符")
        if result.text_response:
            console.print(f"💬 模型附带说明: [dim]{result.text_response}[/]")

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


@main.command(name="summary", help="为目录生成 SUMMARY.md 和 INDEX.md 目录文件")
@click.option("--dir", "-d", "directory", default=".", show_default=True, help="文档根目录")
@click.option("--depth", default=5, show_default=True, type=int, help="目录层级深度")
def summary_command(directory: str, depth: int) -> None:
    """扫描目录结构，为每个包含 README.md 的目录生成目录文件

    \b
    示例:
        qxw-markdown summary              # 为当前目录生成
        qxw-markdown summary -d docs/     # 指定目录
        qxw-markdown summary --depth 5    # 指定深度

    \b
    生成规则:
        SUMMARY.md  = 标题 + 目录结构
        INDEX.md    = README.md 内容 + 目录结构

    \b
    特殊处理:
        - 标题含 (todo) 的条目会被跳过
        - 存在 SUMMARY.md.skip 的目录会被跳过
        - 文件按数字前缀排序（如 1.intro.md, 2.setup.md）
    """
    try:
        from qxw.library.services.summary_service import generate_summary_for_dir

        base_dir = Path(directory).resolve()
        if not base_dir.is_dir():
            click.echo(f"错误: 目录不存在: {directory}", err=True)
            sys.exit(1)

        if not (base_dir / "README.md").is_file():
            click.echo(f"错误: {directory} 下没有 README.md", err=True)
            sys.exit(1)

        generated = generate_summary_for_dir(base_dir, depth=depth)

        for filepath in generated:
            console.print(f"  [green]✓[/] {filepath}")
        console.print(f"\n共生成 {len(generated)} 个文件")

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
