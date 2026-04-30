---
name: qxw-serve
description: 使用 `qxw-serve` 启动一个本地 HTTP 服务，下挂 4 个子命令：`gitbook`（Markdown 在线预览 + 单页/整本 PDF 下载）、`webtool`（开发者 Web 工具集：文本对比 / JSON 格式化 / 时间戳转换 / AES-DES-3DES-RSA-Ed25519-哈希-HMAC 加解密 / URL & Base64 编解码）、`file-web`（Basic Auth 鉴权的 HTTP 文件共享 + 打包下载）、`image-web`（图片画廊 + 灯箱 + 15 档调色面板，支持 Live Photo & RAW 预览）。当用户说"在浏览器里看 markdown / 本地预览 docs / 把 md 转 PDF / 启动 gitbook 服务 / 局域网共享文件 / 给同事看一组照片 / 启动图片画廊 / 浏览 RAW / 在线 JSON 美化 / 在线 AES 加密 / 在线时间戳转换 / 看 Live Photo"，或直接念到 `qxw-serve gitbook`、`qxw-serve webtool`、`qxw-serve file-web`、`qxw-serve image-web` 时，使用此 skill。
---

# qxw-serve

本地 HTTP 服务集合。每个子命令都是独立 server，互不依赖；端口 / 监听地址 / 共享目录都用统一的 `-p / -H / -d` 选项。

| 子命令 | 默认端口 | 用途 |
|--------|---------|------|
| `gitbook`   | 8000 | Markdown 预览 + 单页/整本 PDF |
| `webtool`   | 9000 | 开发者 Web 工具集 |
| `file-web`  | 8080 | Basic Auth 鉴权的 HTTP 文件共享 |
| `image-web` | 8080 | 图片画廊 + 灯箱 + 15 档调色 |

> 不再提供 FTP；`qxw-gitbook pdf` 本地批量 PDF 已删除。如需批量转 PDF，启动 `gitbook` 后在浏览器侧边栏点"⬇ 下载整本 PDF"。

## qxw-serve gitbook

启动 Markdown 预览 server，浏览器访问后：
- 每页右上角 **⬇ 下载本页 PDF**：把当前 `.md` 渲染成单 PDF
- 侧边栏顶部 **⬇ 下载整本 PDF**：递归收集目录下所有 `.md`，按路径合并成一个 PDF

```bash
qxw-serve gitbook                # 当前目录，:8000
qxw-serve gitbook -p 3000        # 换端口
qxw-serve gitbook -d docs/       # 预览 docs/
qxw-serve gitbook -H 0.0.0.0     # 允许局域网访问（注意：服务无鉴权）
```

| 参数 | 缩写 | 默认 |
|------|------|------|
| `--dir` | `-d` | `.` |
| `--port` | `-p` | 8000 |
| `--host` | `-H` | 127.0.0.1 |

### PDF 下载依赖

PDF 功能依赖 `weasyprint`。**未装时预览页面照常用，仅点 PDF 按钮时才返回 500 + 安装提示**：

```bash
# macOS
brew install pango && pip install weasyprint

# Linux (Debian/Ubuntu)
sudo apt install libpango-1.0-0 && pip install weasyprint

# 一步到位
pip install "qxw[pdf]"
```

## qxw-serve webtool

```bash
qxw-serve webtool                # :9000
qxw-serve webtool -p 3000
qxw-serve webtool -H 0.0.0.0
```

| 参数 | 缩写 | 默认 |
|------|------|------|
| `--port` | `-p` | 9000 |
| `--host` | `-H` | 127.0.0.1 |

### 内置工具

| 模块 | 能力 |
|------|------|
| 文本对比 | Unified Diff，新增绿 / 删除红 |
| JSON | 格式化 / 压缩 / 校验 / 转义 / 去转义 |
| 时间戳 | 实时 now / unix(s/ms) ↔ 多格式日期 |
| 哈希 | MD5 / SHA1 / SHA256 / SHA512 |
| HMAC | HMAC-SHA256 / HMAC-SHA512 |
| AES | 128 / 192 / 256，CBC / ECB，PKCS7，**Hex Key**，输出 Base64（CBC 时 IV 前置于密文） |
| DES | CBC，8 字节 Hex Key |
| 3DES | CBC，16 / 24 字节 Hex Key |
| RSA | RSA-2048 / 4096，OAEP+SHA256，支持密钥对生成 |
| Ed25519 | 密钥对生成 / 签名 / 验证 |
| 证书解析 | X.509 PEM / Base64 DER（颁发者 / 有效期 / SAN / 指纹） |
| URL | Encode / Decode |
| Base64 | Encode / Decode |

### 对称加密约定（要点）

- 密钥 / IV 用 **Hex** 输入
- 加密输出 Base64；CBC 模式下 IV 前置于密文
- 解密输入 Base64；自动从前缀提取 IV

## qxw-serve file-web

Basic Auth 鉴权的目录共享。

```bash
qxw-serve file-web                       # 当前目录，:8080
qxw-serve file-web -d /tmp
qxw-serve file-web -p 9000
qxw-serve file-web -u user -P mypass
qxw-serve file-web -H 0.0.0.0            # 局域网
```

| 参数 | 缩写 | 默认 |
|------|------|------|
| `--dir` | `-d` | `.` |
| `--port` | `-p` | 8080 |
| `--host` | `-H` | 127.0.0.1 |
| `--username` | `-u` | `admin` |
| `--password` | `-P` | （每次启动随机生成并打印） |

### 鉴权 / 浏览体验

- 不传 `--password` 每次启动会生成新的随机密码并打印到终端
- 浏览器访问弹 Basic Auth 登录窗
- 目录列表支持 **⬇ 下载** 单文件、**📦 打包下载**（zip 流式生成整个子目录）

## qxw-serve image-web

图片画廊 + 灯箱预览，支持 Live Photo（同名图+视频）和 RAW 预览。**画廊已从原 `qxw-image http` 迁到这里**。

```bash
qxw-serve image-web                              # 当前目录，:8080
qxw-serve image-web -d ~/Photos
qxw-serve image-web -p 9000
qxw-serve image-web -s 300 --thumb-quality 70   # 调缩略图尺寸 / 质量
qxw-serve image-web --no-recursive              # 只看顶层目录
```

| 参数 | 缩写 | 默认 |
|------|------|------|
| `--dir` | `-d` | `.` |
| `--port` | `-p` | 8080 |
| `--host` | `-H` | 127.0.0.1 |
| `--thumb-size` | `-s` | 400（50–4096） |
| `--thumb-quality` | - | 85（1–100） |
| `--recursive` / `--no-recursive` | `-r` | `--recursive` |

### 支持的格式

- 图片：JPG / PNG / GIF / WebP / BMP / TIFF / HEIC
- RAW：CR2 / CR3 / NEF / ARW / DNG / ORF / RW2 / PEF / RAF
- Live Photo 配对视频：MOV / MP4

### 灯箱内 15 档实时调色

单击图片打开灯箱 → 右上角 **🎚 调整** → 15 档滑块，debounce 150ms 即时渲染（服务端把底图降采样到最长边 1200px 后叠加参数）：

| 参数 | 英文键 | 范围 |
|------|--------|------|
| 曝光 | `exposure` | -100 – 100 |
| 鲜明度 | `brilliance` | -100 – 100 |
| 高光 | `highlights` | -100 – 100 |
| 阴影 | `shadows` | -100 – 100 |
| 对比度 | `contrast` | -100 – 100 |
| 亮度 | `brightness` | -100 – 100 |
| 黑点 | `blacks` | -100 – 100 |
| 饱和度 | `saturation` | -100 – 100 |
| 自然饱和度 | `vibrance` | -100 – 100 |
| 色温 | `temperature` | -100 – 100 |
| 色调 | `tint` | -100 – 100 |
| 锐度 | `sharpness` | **0 – 100** |
| 清晰度 | `clarity` | **0 – 100** |
| 噪点消除 | `noise_reduction` | **0 – 100** |
| 晕影 | `vignette` | -100 – 100 |

底部按钮：
- **重置**：所有滑块归 0；关闭灯箱也会自动重置
- **💾 保存原尺寸**：以原分辨率重新应用一遍，写到源目录下的 `<原名>_adjusted_<时间戳>.jpg`，至少需要一档非 0

### HTTP 路由

| 路由 | 方法 | 用途 |
|------|------|------|
| `/adjust/<相对路径>?...` | GET | 1200px 长边降采样实时预览 JPEG |
| `/save/<相对路径>?...` | POST | 应用到原尺寸，返回 `{path, absolute, size}` |

参数集合两条路由相同。非法参数（非数字、越界、未知键）→ 400；路径不存在 → 404；PIL/NumPy 缺失 / 写盘失败 → 500；`/save` 上若所有参数都为 0（`is_identity`）→ 400（避免无意义重编码）。

## 常见踩坑

- **想给同事一个 Wi-Fi 直连的入口**：所有子命令都默认 `-H 127.0.0.1`，必须显式 `-H 0.0.0.0` 才走外部网卡。`gitbook` / `image-web` 没有鉴权，公网或共享 Wi-Fi 上要谨慎。
- **`gitbook` PDF 按钮 500**：缺 weasyprint 或它的系统依赖（pango），按上面的安装提示装一次即可。
- **`file-web` 启动后看不到密码**：被滚屏冲掉了；终端里搜一下 "password" 或重启服务再看。
- **`image-web` 看不到 RAW 缩略图**：缺 `rawpy`，`pip install rawpy`。
- **HEIC 不显示**：装 `pillow-heif`。
