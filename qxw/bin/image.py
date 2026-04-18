"""qxw-image 命令入口

图片工具集，支持图片浏览 HTTP 服务和 RAW 批量转换。

用法:
    qxw-image http                        # 启动图片浏览服务（默认 8080 端口）
    qxw-image http --dir ~/Photos         # 指定图片目录
    qxw-image raw                         # 批量转换当前目录 RAW 文件为 JPG
    qxw-image raw --preset warm           # 使用暖色调预设
    qxw-image raw -d ~/Photos -r          # 递归处理子目录
    qxw-image --help                      # 查看帮助
"""

import mimetypes
import sys
import urllib.parse
from functools import partial
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import click
from pydantic import BaseModel, Field
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeRemainingColumn

from qxw import __version__
from qxw.library.base.exceptions import QxwError
from qxw.library.base.logger import get_logger

logger = get_logger("qxw.image")
console = Console()


# ============================================================
# 数据模型
# ============================================================


class ImageServerConfig(BaseModel):
    """图片浏览服务配置"""

    directory: Path
    host: str = Field(default="127.0.0.1")
    port: int = Field(default=8080)
    thumb_size: int = Field(default=400)
    thumb_quality: int = Field(default=85)


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


# ============================================================
# HTML 画廊模板
# ============================================================

_GALLERY_HTML = """\
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>📷 QXW Image Gallery</title>
<style>
:root {{
  --bg:#f1f5f9; --card:#fff; --bd:#e2e8f0;
  --tx:#0f172a; --tm:#64748b; --c1:#6366f1;
  --mono:'SF Mono',SFMono-Regular,Menlo,Consolas,monospace;
}}
*,*::before,*::after {{ box-sizing:border-box; margin:0; padding:0; }}
body {{
  font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','Noto Sans SC','PingFang SC',sans-serif;
  background:var(--bg); color:var(--tx); line-height:1.6;
}}
.header {{
  background:linear-gradient(135deg,#0f172a,#1e293b 80%);
  padding:18px 28px; color:#fff;
  box-shadow:0 4px 16px rgba(0,0,0,.3);
  display:flex; align-items:center; justify-content:space-between;
}}
.header h1 {{ font-size:17px; font-weight:700; }}
.header h1 small {{ font-weight:400; font-size:12px; opacity:.6; margin-left:8px; }}
.stats {{ font-size:13px; opacity:.7; }}
.content {{ max-width:1400px; margin:24px auto; padding:0 20px; }}
.gallery {{
  display:grid;
  grid-template-columns:repeat(auto-fill,minmax(220px,1fr));
  gap:16px;
}}
.card {{
  background:var(--card); border:1px solid var(--bd);
  border-radius:10px; overflow:hidden; cursor:pointer;
  box-shadow:0 1px 3px rgba(0,0,0,.06);
  transition:transform .15s,box-shadow .15s;
  position:relative;
}}
.card:hover {{ transform:translateY(-2px); box-shadow:0 4px 12px rgba(0,0,0,.1); }}
.card img {{
  width:100%; aspect-ratio:1; object-fit:cover;
  display:block; background:#f1f5f9;
}}
.card .info {{
  padding:8px 12px; font-size:12px; color:var(--tm);
  white-space:nowrap; overflow:hidden; text-overflow:ellipsis;
}}
.card .info .name {{ color:var(--tx); font-weight:500; display:block; }}
.badge {{
  position:absolute; top:8px; left:8px;
  padding:2px 8px; border-radius:4px;
  font-size:10px; font-weight:700; letter-spacing:.05em;
  color:#fff; backdrop-filter:blur(4px);
}}
.badge-live {{ background:rgba(255,59,48,.85); }}
.badge-raw {{ background:rgba(99,102,241,.85); }}
/* 灯箱 */
.lightbox {{
  display:none; position:fixed; inset:0; z-index:1000;
  background:rgba(0,0,0,.92); backdrop-filter:blur(8px);
  justify-content:center; align-items:center; flex-direction:column;
}}
.lightbox.active {{ display:flex; }}
.lb-close {{
  position:absolute; top:16px; right:20px;
  background:none; border:none; color:#fff;
  font-size:32px; cursor:pointer; opacity:.7; z-index:1001;
}}
.lb-close:hover {{ opacity:1; }}
.lb-media {{ max-width:90vw; max-height:80vh; border-radius:8px; }}
.lb-video {{ max-width:90vw; max-height:80vh; border-radius:8px; display:none; }}
.lb-info {{
  color:#fff; margin-top:16px; text-align:center; font-size:14px;
}}
.lb-info .name {{ font-weight:600; }}
.lb-info .size {{ opacity:.6; margin-left:12px; font-family:var(--mono); font-size:13px; }}
.lb-live-btn {{
  display:none; margin-top:12px; padding:8px 20px;
  background:rgba(255,59,48,.85); color:#fff; border:none;
  border-radius:8px; font-size:13px; font-weight:600;
  cursor:pointer; transition:background .15s;
}}
.lb-live-btn:hover {{ background:rgba(255,59,48,1); }}
.lb-live-btn.playing {{ background:rgba(99,102,241,.85); }}
.empty {{
  text-align:center; padding:80px 20px; color:var(--tm); font-size:16px;
}}
</style>
</head>
<body>

<div class="header">
  <h1>📷 QXW Image Gallery<small>v{version}</small></h1>
  <div class="stats">{stats}</div>
</div>

<div class="content">
{gallery_content}
</div>

<div class="lightbox" id="lightbox">
  <button class="lb-close" id="lb-close">&times;</button>
  <img class="lb-media" id="lb-img" src="" alt="">
  <video class="lb-video" id="lb-video" controls loop playsinline></video>
  <div class="lb-info">
    <span class="name" id="lb-name"></span>
    <span class="size" id="lb-size"></span>
    <br>
    <button class="lb-live-btn" id="lb-live-btn">▶ 播放 Live Photo</button>
  </div>
</div>

<script>
(function() {{
  var lb = document.getElementById('lightbox');
  var lbImg = document.getElementById('lb-img');
  var lbVideo = document.getElementById('lb-video');
  var lbName = document.getElementById('lb-name');
  var lbSize = document.getElementById('lb-size');
  var lbLiveBtn = document.getElementById('lb-live-btn');
  var currentVideo = null;
  var isPlaying = false;

  document.querySelectorAll('.card').forEach(function(card) {{
    card.addEventListener('click', function() {{
      var orig = card.getAttribute('data-orig');
      var name = card.getAttribute('data-name');
      var size = card.getAttribute('data-size');
      var video = card.getAttribute('data-video');

      lbImg.src = orig;
      lbImg.style.display = 'block';
      lbVideo.style.display = 'none';
      lbVideo.pause();
      lbVideo.src = '';
      lbName.textContent = name;
      lbSize.textContent = size;
      isPlaying = false;
      lbLiveBtn.classList.remove('playing');
      lbLiveBtn.textContent = '▶ 播放 Live Photo';

      if (video) {{
        currentVideo = video;
        lbLiveBtn.style.display = 'inline-block';
      }} else {{
        currentVideo = null;
        lbLiveBtn.style.display = 'none';
      }}
      lb.classList.add('active');
    }});
  }});

  lbLiveBtn.addEventListener('click', function(e) {{
    e.stopPropagation();
    if (!currentVideo) return;
    if (isPlaying) {{
      lbVideo.pause();
      lbVideo.style.display = 'none';
      lbImg.style.display = 'block';
      isPlaying = false;
      lbLiveBtn.classList.remove('playing');
      lbLiveBtn.textContent = '▶ 播放 Live Photo';
    }} else {{
      lbVideo.src = currentVideo;
      lbVideo.style.display = 'block';
      lbImg.style.display = 'none';
      lbVideo.play();
      isPlaying = true;
      lbLiveBtn.classList.add('playing');
      lbLiveBtn.textContent = '⏸ 显示照片';
    }}
  }});

  function closeLightbox() {{
    lb.classList.remove('active');
    lbVideo.pause();
    lbVideo.src = '';
    lbImg.src = '';
  }}

  document.getElementById('lb-close').addEventListener('click', closeLightbox);
  lb.addEventListener('click', function(e) {{
    if (e.target === lb) closeLightbox();
  }});
  document.addEventListener('keydown', function(e) {{
    if (e.key === 'Escape') closeLightbox();
  }});
}})();
</script>
</body>
</html>
"""


# ============================================================
# HTTP 图片浏览服务
# ============================================================


class _ImageServerHandler(BaseHTTPRequestHandler):
    """图片浏览 HTTP 请求处理器"""

    def __init__(self, config: ImageServerConfig, images: list, *args, **kwargs):
        self.config = config
        self.images = images
        super().__init__(*args, **kwargs)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        logger.debug(format, *args)

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        url_path = parsed.path

        if url_path == "/":
            self._serve_gallery()
        elif url_path.startswith("/thumb/"):
            self._serve_thumbnail(urllib.parse.unquote(url_path[7:]))
        elif url_path.startswith("/view/"):
            self._serve_viewable(urllib.parse.unquote(url_path[6:]))
        elif url_path.startswith("/video/"):
            self._serve_video(urllib.parse.unquote(url_path[7:]))
        else:
            self._send_error(404, "页面不存在")

    def _serve_gallery(self) -> None:
        from qxw.library.services.image_service import human_size

        cards: list[str] = []
        live_count = 0
        raw_count = 0

        for img in self.images:
            enc_rel = urllib.parse.quote(img.rel_path)
            size_str = human_size(img.size)

            badges = ""
            if img.is_live:
                badges += '<span class="badge badge-live">LIVE</span>'
                live_count += 1
            if img.is_raw:
                badges += '<span class="badge badge-raw">RAW</span>'
                raw_count += 1

            video_attr = ""
            if img.is_live and img.live_video_rel:
                video_attr = f' data-video="/video/{urllib.parse.quote(img.live_video_rel)}"'

            cards.append(
                f'<div class="card" data-orig="/view/{enc_rel}"'
                f' data-name="{img.name}" data-size="{size_str}"{video_attr}>'
                f'{badges}'
                f'<img src="/thumb/{enc_rel}" loading="lazy" alt="{img.name}">'
                f'<div class="info"><span class="name">{img.name}</span>{size_str}</div>'
                f'</div>'
            )

        if cards:
            gallery_content = f'<div class="gallery">{"".join(cards)}</div>'
        else:
            gallery_content = '<div class="empty">📭 当前目录下未找到图片文件</div>'

        stats_parts = [f"共 {len(self.images)} 张图片"]
        if live_count:
            stats_parts.append(f"{live_count} 张 Live Photo")
        if raw_count:
            stats_parts.append(f"{raw_count} 张 RAW")
        stats = " · ".join(stats_parts)

        html = _GALLERY_HTML.format(
            version=__version__,
            stats=stats,
            gallery_content=gallery_content,
        )
        data = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _serve_thumbnail(self, rel_path: str) -> None:
        from qxw.library.services.image_service import generate_thumbnail

        target = self._resolve_safe_path(rel_path)
        if target is None:
            self._send_error(404, "文件不存在")
            return

        thumb_dir = self.config.directory / ".qxw_thumbs"
        thumb_path = thumb_dir / Path(rel_path).with_suffix(".jpg")
        size = (self.config.thumb_size, self.config.thumb_size)

        if generate_thumbnail(target, thumb_path, size=size, quality=self.config.thumb_quality):
            self._serve_file(thumb_path, content_type="image/jpeg")
        else:
            self._send_error(500, "缩略图生成失败")

    def _serve_viewable(self, rel_path: str) -> None:
        from qxw.library.services.image_service import get_viewable_path

        target = self._resolve_safe_path(rel_path)
        if target is None:
            self._send_error(404, "文件不存在")
            return

        cache_dir = self.config.directory / ".qxw_cache"
        viewable = get_viewable_path(target, cache_dir, self.config.directory)
        if viewable is None:
            self._send_error(500, "无法显示该图片格式")
            return

        content_type = mimetypes.guess_type(str(viewable))[0] or "image/jpeg"
        self._serve_file(viewable, content_type=content_type)

    def _serve_video(self, rel_path: str) -> None:
        target = self._resolve_safe_path(rel_path)
        if target is None:
            self._send_error(404, "文件不存在")
            return

        content_type = mimetypes.guess_type(str(target))[0] or "video/mp4"
        self._serve_file(target, content_type=content_type)

    def _resolve_safe_path(self, rel_path: str) -> Path | None:
        """将相对路径解析为安全的绝对路径，防止路径穿越"""
        target = (self.config.directory / rel_path).resolve()
        try:
            target.relative_to(self.config.directory.resolve())
        except ValueError:
            return None
        if not target.exists() or not target.is_file():
            return None
        return target

    def _serve_file(self, file_path: Path, content_type: str) -> None:
        try:
            stat = file_path.stat()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(stat.st_size))
            self.send_header("Cache-Control", "public, max-age=3600")
            self.end_headers()
            with open(file_path, "rb") as f:
                while True:
                    chunk = f.read(65536)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
        except Exception as e:
            logger.error("文件读取失败: %s", e)
            self._send_error(500, "文件读取失败")

    def _send_error(self, code: int, message: str) -> None:
        self.send_response(code)
        body = f"<h1>{code}</h1><p>{message}</p>".encode("utf-8")
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


# ============================================================
# CLI 入口 (Click)
# ============================================================


@click.group(
    name="qxw-image",
    help="QXW 图片工具集（HTTP 图片浏览 / RAW 批量转换）",
    epilog="使用 qxw-image <子命令> --help 查看各子命令的详细帮助。",
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


@main.command(name="http", help="启动图片浏览 HTTP 服务（缩略图画廊，支持 Live Photo）")
@click.option("--dir", "-d", "directory", default=".", show_default=True, help="图片目录路径")
@click.option("--port", "-p", default=8080, show_default=True, type=int, help="服务端口")
@click.option("--host", "-H", default="127.0.0.1", show_default=True, help="监听地址")
@click.option("--thumb-size", "-s", default=400, show_default=True, type=int, help="缩略图尺寸（像素）")
@click.option("--thumb-quality", default=85, show_default=True, type=int, help="缩略图 JPEG 质量 (1-100)")
@click.option("--recursive/--no-recursive", "-r", default=True, show_default=True, help="是否递归扫描子目录")
def http_command(
    directory: str,
    port: int,
    host: str,
    thumb_size: int,
    thumb_quality: int,
    recursive: bool,
) -> None:
    """启动图片浏览 HTTP 服务

    提供 Web 画廊界面浏览目录中的图片，自动生成缩略图并缓存。
    支持 Live Photo 检测和播放（需要同目录下同名的图片和视频文件）。

    \b
    支持的图片格式：JPG, PNG, GIF, WebP, BMP, TIFF, HEIC
    支持的 RAW 格式：CR2, CR3, NEF, ARW, DNG, ORF, RW2, PEF, RAF 等
    支持的视频格式：MOV, MP4（Live Photo 关联）

    \b
    示例:
        qxw-image http                          # 浏览当前目录图片
        qxw-image http -d ~/Photos              # 指定图片目录
        qxw-image http -p 9000                  # 指定端口
        qxw-image http -s 300 --thumb-quality 70  # 调整缩略图参数
        qxw-image http --no-recursive           # 不递归扫描子目录
    """
    try:
        _require_pillow()

        dir_path = Path(directory).resolve()
        if not dir_path.is_dir():
            raise click.BadParameter(f"目录不存在: {directory}")

        config = ImageServerConfig(
            directory=dir_path,
            host=host,
            port=port,
            thumb_size=thumb_size,
            thumb_quality=thumb_quality,
        )

        from qxw.library.services.image_service import scan_images

        console.print(f"📷 [bold]QXW Image Gallery[/] v{__version__}")
        console.print(f"📁 图片目录: [cyan]{dir_path}[/]")
        console.print("🔍 正在扫描图片...")

        images = scan_images(dir_path, recursive=recursive)

        live_count = sum(1 for img in images if img.is_live)
        raw_count = sum(1 for img in images if img.is_raw)

        console.print(f"   找到 [bold]{len(images)}[/] 张图片", end="")
        if live_count:
            console.print(f"，[red]{live_count}[/] 张 Live Photo", end="")
        if raw_count:
            console.print(f"，[blue]{raw_count}[/] 张 RAW", end="")
        console.print()

        console.print(f"🌐 服务地址: [link=http://{host}:{port}]http://{host}:{port}[/link]")
        console.print("按 Ctrl+C 停止服务\n")

        handler = partial(_ImageServerHandler, config, images)
        server = HTTPServer((host, port), handler)
        server.serve_forever()

    except OSError as e:
        if "Address already in use" in str(e) or getattr(e, "errno", 0) == 48:
            click.echo(f"错误: 端口 {port} 已被占用，请使用 -p 指定其他端口", err=True)
        else:
            click.echo(f"错误: {e}", err=True)
        sys.exit(1)
    except QxwError as e:
        logger.error("命令执行失败: %s", e.message)
        click.echo(f"错误: {e.message}", err=True)
        sys.exit(e.exit_code)
    except KeyboardInterrupt:
        click.echo("\n服务已停止")
    except Exception as e:
        logger.exception("未预期的错误")
        click.echo(f"未预期的错误: {e}", err=True)
        sys.exit(1)


@main.command(name="raw", help="批量将 RAW 图片转换为 JPG（支持调色预设）")
@click.option("--dir", "-d", "directory", default=".", show_default=True, help="RAW 文件所在目录")
@click.option("--output", "-o", "output_dir", default=None, help="输出目录（默认与源文件同目录）")
@click.option("--recursive", "-r", is_flag=True, default=False, help="递归处理子目录")
@click.option("--quality", "-q", default=92, show_default=True, type=int, help="JPEG 压缩质量 (1-100)")
@click.option(
    "--preset",
    "-P",
    default="natural",
    show_default=True,
    type=click.Choice(["natural", "vivid", "warm", "cool", "bw", "film"], case_sensitive=False),
    help="调色预设",
)
@click.option("--overwrite/--no-overwrite", default=False, show_default=True, help="是否覆盖已存在的输出文件")
@click.option("--auto-balance", "-A", is_flag=True, default=False, help="启用 CLAHE 自适应直方图均衡（改善亮度分布）")
def raw_command(
    directory: str,
    output_dir: str | None,
    recursive: bool,
    quality: int,
    preset: str,
    overwrite: bool,
    auto_balance: bool,
) -> None:
    """批量将 RAW 图片转换为 JPG

    扫描目录中的 RAW 文件，使用指定调色预设转换为高质量 JPEG。

    \b
    支持的 RAW 格式：
      Canon (CR2/CR3), Nikon (NEF), Sony (ARW), Adobe (DNG),
      Olympus (ORF), Panasonic (RW2), Pentax (PEF), Fujifilm (RAF),
      Hasselblad (3FR), Phase One (IIQ), Leica (RWL) 等

    \b
    调色预设：
      natural  - 自然色彩（使用相机白平衡，不做额外调色）
      vivid    - 鲜艳（提升饱和度和对比度）
      warm     - 暖色调（适合人像和日落场景）
      cool     - 冷色调（适合风景和建筑场景）
      bw       - 黑白（经典黑白，带轻微对比度增强）
      film     - 胶片风格（模拟胶片质感，低对比度偏暖）

    \b
    示例:
        qxw-image raw                           # 转换当前目录的 RAW 文件
        qxw-image raw -d ~/Photos -r            # 递归处理
        qxw-image raw -P warm                   # 使用暖色调
        qxw-image raw -P bw -q 95               # 黑白预设 + 高质量
        qxw-image raw -o ./output               # 指定输出目录
        qxw-image raw --overwrite               # 覆盖已有文件
        qxw-image raw --auto-balance            # 启用直方图均衡
        qxw-image raw -P warm --auto-balance    # 预设 + 均衡组合
    """
    try:
        _require_pillow()
        _require_rawpy()

        from qxw.library.services.image_service import ColorPreset, convert_raw, scan_raw_files

        dir_path = Path(directory).resolve()
        if not dir_path.is_dir():
            raise click.BadParameter(f"目录不存在: {directory}")

        out_path = Path(output_dir).resolve() if output_dir else None
        color_preset = ColorPreset(preset.lower())

        console.print(f"📷 [bold]QXW RAW Converter[/] v{__version__}")
        console.print(f"📁 源目录: [cyan]{dir_path}[/]")
        if out_path:
            console.print(f"📂 输出目录: [cyan]{out_path}[/]")
        console.print(f"🎨 调色预设: [bold]{color_preset.label}[/] — {color_preset.description}")
        if auto_balance:
            console.print("⚖️  自动均衡: [bold green]已启用[/]（CLAHE 自适应直方图均衡）")
        console.print(f"📊 JPEG 质量: {quality}")
        console.print()

        raw_files = scan_raw_files(dir_path, recursive=recursive)
        if not raw_files:
            console.print("📭 未找到 RAW 文件")
            return

        console.print(f"🔍 找到 [bold]{len(raw_files)}[/] 个 RAW 文件\n")

        success_count = 0
        skip_count = 0
        fail_count = 0

        with Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            TimeRemainingColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("转换中...", total=len(raw_files))

            for raw_file in raw_files:
                if out_path:
                    rel = raw_file.relative_to(dir_path)
                    dest = out_path / rel.with_suffix(".jpg")
                else:
                    dest = raw_file.with_suffix(".jpg")

                if dest.exists() and not overwrite:
                    skip_count += 1
                    progress.advance(task)
                    continue

                try:
                    convert_raw(raw_file, dest, preset=color_preset, quality=quality, auto_balance=auto_balance)
                    success_count += 1
                except Exception as e:
                    logger.warning("转换失败 %s: %s", raw_file.name, e)
                    fail_count += 1

                progress.advance(task)

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


if __name__ == "__main__":
    main()
