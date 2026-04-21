"""图片浏览 HTTP 画廊服务

扫描目录下的图片，生成带缩略图的画廊页，支持 Live Photo 播放与 RAW 预览。
"""

from __future__ import annotations

import mimetypes
import urllib.parse
from dataclasses import dataclass
from functools import partial
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from pydantic import BaseModel, Field

from qxw import __version__
from qxw.library.base.logger import get_logger

logger = get_logger("qxw.serve.image")


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
# HTTP 处理器
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


@dataclass
class _ImageServeContext:
    config: ImageServerConfig
    images: list


def start_server(config: ImageServerConfig, images: list) -> None:
    """启动图片画廊 HTTP 服务（阻塞）"""
    handler = partial(_ImageServerHandler, config, images)
    server = HTTPServer((config.host, config.port), handler)
    server.serve_forever()
