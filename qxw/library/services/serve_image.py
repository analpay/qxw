"""图片浏览 HTTP 画廊服务

扫描目录下的图片，生成带缩略图的画廊页，支持 Live Photo 播放、RAW 预览，
以及在灯箱内用滑块实时预览 15 项参数调整（曝光 / 鲜明度 / 高光 / 阴影 /
对比度 / 亮度 / 黑点 / 饱和度 / 自然饱和度 / 色温 / 色调 / 锐度 / 清晰度 /
噪点消除 / 晕影）。
"""

from __future__ import annotations

import io
import json
import mimetypes
import threading
import time
import urllib.parse
from dataclasses import dataclass
from functools import partial
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from pydantic import BaseModel, Field

from qxw import __version__
from qxw.library.base.exceptions import QxwError, ValidationError
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
    adjust_preview_size: int = Field(default=1200, description="调整预览图最长边像素")
    adjust_preview_quality: int = Field(default=85, description="调整预览 JPEG 质量")
    save_quality: int = Field(default=92, description="原尺寸保存 JPEG 质量")


# ============================================================
# 调整预览缓存
# ============================================================


# 单图缓存：只缓存最近一张打开的图片的降采样 ndarray，避免每拖动一次滑块就
# 重新解码整张原图。灯箱一次只打开一张，所以单元足够。
_PREVIEW_CACHE_LOCK = threading.Lock()
_PREVIEW_CACHE: dict[str, object] = {"key": None, "ndarray": None, "mtime": None}


def _get_preview_base(
    src: Path, rel_key: str, max_side: int
) -> "object | None":
    """读取 / 解码并缓存降采样后的 RGB uint8 ndarray

    Args:
        src: 原图（或中间 JPG）文件绝对路径
        rel_key: 缓存主键（通常是 ``directory:rel_path``）
        max_side: 最长边像素数；超过则等比缩小

    返回 ``np.ndarray`` 或 ``None``（PIL/NumPy 缺失或打开失败）
    """
    try:
        import numpy as np
        from PIL import Image
    except ImportError:
        return None

    try:
        mtime = src.stat().st_mtime
    except OSError:
        return None

    with _PREVIEW_CACHE_LOCK:
        if (
            _PREVIEW_CACHE["key"] == rel_key
            and _PREVIEW_CACHE["mtime"] == mtime
            and _PREVIEW_CACHE["ndarray"] is not None
        ):
            return _PREVIEW_CACHE["ndarray"]

    try:
        img = Image.open(src)
        img.load()
    except Exception as e:
        logger.warning("打开预览基准图失败 %s: %s", src.name, e)
        return None

    if img.mode != "RGB":
        img = img.convert("RGB")

    w, h = img.size
    long_side = max(w, h)
    if long_side > max_side:
        scale = max_side / float(long_side)
        new_size = (max(1, int(round(w * scale))), max(1, int(round(h * scale))))
        img = img.resize(new_size, Image.LANCZOS)

    arr = np.asarray(img, dtype=np.uint8)

    with _PREVIEW_CACHE_LOCK:
        _PREVIEW_CACHE["key"] = rel_key
        _PREVIEW_CACHE["mtime"] = mtime
        _PREVIEW_CACHE["ndarray"] = arr

    return arr


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
}}
.lightbox.active {{ display:flex; }}
.lb-main {{
  flex:1 1 auto; display:flex; flex-direction:column;
  align-items:center; justify-content:center;
  min-width:0; padding:48px 24px 24px; position:relative;
}}
.lb-close {{
  position:absolute; top:16px; right:20px;
  background:none; border:none; color:#fff;
  font-size:32px; cursor:pointer; opacity:.7; z-index:1001;
}}
.lb-close:hover {{ opacity:1; }}
.lb-media {{ max-width:100%; max-height:78vh; border-radius:8px; object-fit:contain; }}
.lb-video {{ max-width:100%; max-height:78vh; border-radius:8px; display:none; object-fit:contain; }}
.lb-info {{ color:#fff; margin-top:16px; text-align:center; font-size:14px; }}
.lb-info .name {{ font-weight:600; }}
.lb-info .size {{ opacity:.6; margin-left:12px; font-family:var(--mono); font-size:13px; }}
.lb-btns {{ display:flex; gap:10px; justify-content:center; margin-top:12px; flex-wrap:wrap; }}
.lb-btn {{
  display:inline-block; padding:8px 20px;
  color:#fff; border:none; border-radius:8px;
  font-size:13px; font-weight:600; cursor:pointer;
  background:rgba(148,163,184,.25); transition:background .15s;
}}
.lb-btn:hover {{ background:rgba(148,163,184,.45); }}
.lb-btn.primary {{ background:rgba(99,102,241,.85); }}
.lb-btn.primary:hover {{ background:rgba(99,102,241,1); }}
.lb-btn.live {{ background:rgba(255,59,48,.85); display:none; }}
.lb-btn.live:hover {{ background:rgba(255,59,48,1); }}
.lb-btn.live.playing {{ background:rgba(99,102,241,.85); }}
/* 调整面板 */
.lb-adjust {{
  flex:0 0 320px; background:#0f172a; color:#fff;
  border-left:1px solid #1e293b;
  display:none; flex-direction:column; overflow:hidden;
}}
.lb-adjust.active {{ display:flex; }}
.lb-adjust-head {{
  padding:14px 18px; border-bottom:1px solid #1e293b;
  display:flex; align-items:center; justify-content:space-between;
  flex:0 0 auto;
}}
.lb-adjust-head h2 {{ font-size:14px; font-weight:600; }}
.lb-adjust-body {{
  flex:1 1 auto; overflow-y:auto; padding:8px 18px 18px;
}}
.lb-slider-row {{
  display:flex; align-items:center; gap:10px;
  padding:8px 0; border-bottom:1px solid rgba(148,163,184,.15);
}}
.lb-slider-row label {{
  flex:0 0 80px; font-size:12px; color:#cbd5e1;
}}
.lb-slider-row input[type=range] {{
  flex:1 1 auto; min-width:0; accent-color:#6366f1;
  cursor:pointer;
}}
.lb-slider-row .val {{
  flex:0 0 38px; text-align:right; font-family:var(--mono);
  font-size:12px; color:#f1f5f9;
}}
.lb-slider-row .val.modified {{ color:#818cf8; font-weight:600; }}
.lb-adjust-foot {{
  padding:12px 18px; border-top:1px solid #1e293b;
  display:flex; gap:10px; flex:0 0 auto;
}}
.lb-adjust-foot button {{ flex:1 1 auto; }}
.lb-adjust-foot button:disabled {{ opacity:.4; cursor:not-allowed; }}
/* Toast */
.toast {{
  position:fixed; left:50%; bottom:40px; transform:translateX(-50%);
  background:rgba(15,23,42,.95); color:#fff;
  padding:12px 20px; border-radius:8px;
  font-size:13px; box-shadow:0 4px 20px rgba(0,0,0,.3);
  z-index:2000; opacity:0; pointer-events:none;
  transition:opacity .2s, transform .2s;
  max-width:90vw;
}}
.toast.active {{ opacity:1; transform:translateX(-50%) translateY(-6px); }}
.toast.ok {{ background:rgba(22,163,74,.95); }}
.toast.err {{ background:rgba(220,38,38,.95); }}
.lb-media-wrap {{ position:relative; display:flex; align-items:center; justify-content:center; width:100%; }}
.lb-media-wrap .loading {{
  position:absolute; color:#fff; font-size:12px;
  background:rgba(15,23,42,.7); padding:4px 10px; border-radius:12px;
  display:none;
}}
.lb-media-wrap .loading.active {{ display:inline-block; }}
.empty {{
  text-align:center; padding:80px 20px; color:var(--tm); font-size:16px;
}}
@media (max-width: 900px) {{
  .lightbox.active {{ flex-direction:column; }}
  .lb-adjust {{ flex:0 0 50vh; border-left:none; border-top:1px solid #1e293b; }}
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
  <div class="lb-main">
    <button class="lb-close" id="lb-close">&times;</button>
    <div class="lb-media-wrap">
      <img class="lb-media" id="lb-img" src="" alt="">
      <video class="lb-video" id="lb-video" controls loop playsinline></video>
      <span class="loading" id="lb-loading">调整中...</span>
    </div>
    <div class="lb-info">
      <span class="name" id="lb-name"></span>
      <span class="size" id="lb-size"></span>
    </div>
    <div class="lb-btns">
      <button class="lb-btn primary" id="lb-adjust-btn">🎚 调整</button>
      <button class="lb-btn live" id="lb-live-btn">▶ 播放 Live Photo</button>
    </div>
  </div>
  <aside class="lb-adjust" id="lb-adjust">
    <div class="lb-adjust-head">
      <h2>🎚 图片调整</h2>
      <button class="lb-btn" id="lb-adjust-close">收起</button>
    </div>
    <div class="lb-adjust-body" id="lb-adjust-body"></div>
    <div class="lb-adjust-foot">
      <button class="lb-btn" id="lb-adjust-reset">重置</button>
      <button class="lb-btn primary" id="lb-adjust-save" disabled>💾 保存原尺寸</button>
    </div>
  </aside>
</div>
<div class="toast" id="toast"></div>

<script>
(function() {{
  var SLIDERS = [
    {{ key:'exposure',        label:'曝光',       min:-100, max:100 }},
    {{ key:'brilliance',      label:'鲜明度',     min:-100, max:100 }},
    {{ key:'highlights',      label:'高光',       min:-100, max:100 }},
    {{ key:'shadows',         label:'阴影',       min:-100, max:100 }},
    {{ key:'contrast',        label:'对比度',     min:-100, max:100 }},
    {{ key:'brightness',      label:'亮度',       min:-100, max:100 }},
    {{ key:'blacks',          label:'黑点',       min:-100, max:100 }},
    {{ key:'saturation',      label:'饱和度',     min:-100, max:100 }},
    {{ key:'vibrance',        label:'自然饱和度', min:-100, max:100 }},
    {{ key:'temperature',     label:'色温',       min:-100, max:100 }},
    {{ key:'tint',            label:'色调',       min:-100, max:100 }},
    {{ key:'sharpness',       label:'锐度',       min:0,    max:100 }},
    {{ key:'clarity',         label:'清晰度',     min:0,    max:100 }},
    {{ key:'noise_reduction', label:'噪点消除',   min:0,    max:100 }},
    {{ key:'vignette',        label:'晕影',       min:-100, max:100 }}
  ];

  var lb = document.getElementById('lightbox');
  var lbImg = document.getElementById('lb-img');
  var lbVideo = document.getElementById('lb-video');
  var lbName = document.getElementById('lb-name');
  var lbSize = document.getElementById('lb-size');
  var lbLiveBtn = document.getElementById('lb-live-btn');
  var lbAdjustBtn = document.getElementById('lb-adjust-btn');
  var lbAdjustPanel = document.getElementById('lb-adjust');
  var lbAdjustClose = document.getElementById('lb-adjust-close');
  var lbAdjustReset = document.getElementById('lb-adjust-reset');
  var lbAdjustBody = document.getElementById('lb-adjust-body');
  var lbAdjustSave = document.getElementById('lb-adjust-save');
  var lbLoading = document.getElementById('lb-loading');
  var toastEl = document.getElementById('toast');
  var toastTimer = null;
  var currentVideo = null;
  var currentOrig = null;
  var currentRel = null;
  var isPlaying = false;
  var debounceTimer = null;

  // 构建滑块 DOM
  SLIDERS.forEach(function(s) {{
    var row = document.createElement('div');
    row.className = 'lb-slider-row';
    row.innerHTML =
      '<label for="sl-' + s.key + '">' + s.label + '</label>' +
      '<input type="range" id="sl-' + s.key + '" data-key="' + s.key +
      '" min="' + s.min + '" max="' + s.max + '" value="0" step="1">' +
      '<span class="val" id="vl-' + s.key + '">0</span>';
    lbAdjustBody.appendChild(row);
  }});

  function getParams() {{
    var p = {{}};
    SLIDERS.forEach(function(s) {{
      var v = parseFloat(document.getElementById('sl-' + s.key).value) || 0;
      if (v !== 0) p[s.key] = v;
    }});
    return p;
  }}

  function buildQuery(p) {{
    var parts = [];
    for (var k in p) {{
      if (Object.prototype.hasOwnProperty.call(p, k)) {{
        parts.push(encodeURIComponent(k) + '=' + encodeURIComponent(p[k]));
      }}
    }}
    return parts.join('&');
  }}

  function schedulePreview() {{
    if (!currentRel) return;
    if (debounceTimer) clearTimeout(debounceTimer);
    lbLoading.classList.add('active');
    debounceTimer = setTimeout(function() {{
      var p = getParams();
      var url;
      if (Object.keys(p).length === 0) {{
        url = currentOrig;
      }} else {{
        url = '/adjust/' + currentRel + '?' + buildQuery(p);
      }}
      var tmp = new Image();
      tmp.onload = function() {{
        lbImg.src = url;
        lbLoading.classList.remove('active');
      }};
      tmp.onerror = function() {{
        lbLoading.classList.remove('active');
      }};
      tmp.src = url;
    }}, 150);
  }}

  function updateSliderValText(el) {{
    var key = el.getAttribute('data-key');
    var v = parseFloat(el.value) || 0;
    var valEl = document.getElementById('vl-' + key);
    valEl.textContent = v;
    if (v === 0) valEl.classList.remove('modified');
    else valEl.classList.add('modified');
  }}

  function refreshSaveBtn() {{
    var p = getParams();
    lbAdjustSave.disabled = Object.keys(p).length === 0;
  }}

  function showToast(msg, kind) {{
    toastEl.textContent = msg;
    toastEl.classList.remove('ok', 'err');
    if (kind) toastEl.classList.add(kind);
    toastEl.classList.add('active');
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(function() {{
      toastEl.classList.remove('active');
    }}, 3500);
  }}

  function resetSliders() {{
    SLIDERS.forEach(function(s) {{
      var el = document.getElementById('sl-' + s.key);
      el.value = 0;
      updateSliderValText(el);
    }});
    refreshSaveBtn();
    if (currentOrig) lbImg.src = currentOrig;
  }}

  SLIDERS.forEach(function(s) {{
    var el = document.getElementById('sl-' + s.key);
    el.addEventListener('input', function() {{
      updateSliderValText(el);
      refreshSaveBtn();
      schedulePreview();
    }});
  }});

  lbAdjustSave.addEventListener('click', function() {{
    if (!currentRel || lbAdjustSave.disabled) return;
    var p = getParams();
    var q = buildQuery(p);
    lbAdjustSave.disabled = true;
    var origLabel = lbAdjustSave.textContent;
    lbAdjustSave.textContent = '保存中...';
    fetch('/save/' + currentRel + '?' + q, {{ method: 'POST' }})
      .then(function(r) {{ return r.json().then(function(j) {{ return {{ status: r.status, body: j }}; }}); }})
      .then(function(res) {{
        if (res.status === 200 && res.body && res.body.path) {{
          showToast('✓ 已保存: ' + res.body.path, 'ok');
        }} else {{
          var msg = (res.body && res.body.error) ? res.body.error : ('HTTP ' + res.status);
          showToast('✗ 保存失败: ' + msg, 'err');
        }}
      }})
      .catch(function(err) {{
        showToast('✗ 网络错误: ' + err, 'err');
      }})
      .finally(function() {{
        lbAdjustSave.textContent = origLabel;
        refreshSaveBtn();
      }});
  }});

  lbAdjustBtn.addEventListener('click', function() {{
    lbAdjustPanel.classList.toggle('active');
  }});
  lbAdjustClose.addEventListener('click', function() {{
    lbAdjustPanel.classList.remove('active');
  }});
  lbAdjustReset.addEventListener('click', resetSliders);

  document.querySelectorAll('.card').forEach(function(card) {{
    card.addEventListener('click', function() {{
      var orig = card.getAttribute('data-orig');
      var rel = card.getAttribute('data-rel');
      var name = card.getAttribute('data-name');
      var size = card.getAttribute('data-size');
      var video = card.getAttribute('data-video');

      currentOrig = orig;
      currentRel = rel;
      resetSliders();
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
      lbAdjustPanel.classList.remove('active');

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
    lbAdjustPanel.classList.remove('active');
    lbVideo.pause();
    lbVideo.src = '';
    lbImg.src = '';
    currentOrig = null;
    currentRel = null;
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
        elif url_path.startswith("/adjust/"):
            self._serve_adjust(
                urllib.parse.unquote(url_path[8:]),
                urllib.parse.parse_qs(parsed.query),
            )
        else:
            self._send_error(404, "页面不存在")

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        url_path = parsed.path
        if url_path.startswith("/save/"):
            self._serve_save(
                urllib.parse.unquote(url_path[6:]),
                urllib.parse.parse_qs(parsed.query),
            )
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
                f'<div class="card" data-orig="/view/{enc_rel}" data-rel="{enc_rel}"'
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

    def _serve_adjust(self, rel_path: str, query: dict[str, list[str]]) -> None:
        """返回应用了一组调整参数后的预览 JPEG"""
        from qxw.library.services.image_adjust import apply_adjustments, parse_from_query
        from qxw.library.services.image_service import get_viewable_path

        target = self._resolve_safe_path(rel_path)
        if target is None:
            self._send_error(404, "文件不存在")
            return

        try:
            params = parse_from_query(query)
        except ValidationError as e:
            self._send_error(400, e.message)
            return

        cache_dir = self.config.directory / ".qxw_cache"
        viewable = get_viewable_path(target, cache_dir, self.config.directory)
        if viewable is None:
            self._send_error(500, "无法解码该图片格式")
            return

        cache_key = f"{self.config.directory.resolve()}:{rel_path}"
        base = _get_preview_base(viewable, cache_key, self.config.adjust_preview_size)
        if base is None:
            self._send_error(500, "无法生成预览底图（缺少 PIL / NumPy）")
            return

        try:
            result = apply_adjustments(base, params)
        except ValidationError as e:
            self._send_error(400, e.message)
            return
        except Exception as e:
            logger.exception("应用调整失败")
            self._send_error(500, f"应用调整失败: {e}")
            return

        try:
            from PIL import Image
        except ImportError:
            self._send_error(500, "PIL 未安装")
            return

        buf = io.BytesIO()
        Image.fromarray(result).save(
            buf, "JPEG",
            quality=self.config.adjust_preview_quality,
            progressive=True,
        )
        data = buf.getvalue()

        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _serve_save(self, rel_path: str, query: dict[str, list[str]]) -> None:
        """把调整后的原尺寸图写到源目录，返回 JSON ``{path, size}``"""
        from qxw.library.services.image_adjust import parse_from_query, save_adjusted_image
        from qxw.library.services.image_service import get_viewable_path

        target = self._resolve_safe_path(rel_path)
        if target is None:
            self._send_json(404, {"error": "文件不存在"})
            return

        try:
            params = parse_from_query(query)
        except ValidationError as e:
            self._send_json(400, {"error": e.message})
            return

        if params.is_identity():
            self._send_json(400, {"error": "未设置任何调整，不保存"})
            return

        cache_dir = self.config.directory / ".qxw_cache"
        viewable = get_viewable_path(target, cache_dir, self.config.directory)
        if viewable is None:
            self._send_json(500, {"error": "无法解码该图片格式"})
            return

        ts = time.strftime("%Y%m%d_%H%M%S", time.localtime())
        dst = target.parent / f"{target.stem}_adjusted_{ts}.jpg"

        try:
            save_adjusted_image(viewable, dst, params, quality=self.config.save_quality)
        except QxwError as e:
            self._send_json(500, {"error": e.message})
            return
        except Exception as e:
            logger.exception("保存调整图片失败")
            self._send_json(500, {"error": f"保存失败: {e}"})
            return

        try:
            rel_saved = str(dst.relative_to(self.config.directory.resolve()))
        except ValueError:
            rel_saved = str(dst)
        self._send_json(200, {
            "path": rel_saved,
            "absolute": str(dst),
            "size": dst.stat().st_size,
        })

    def _send_json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

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
