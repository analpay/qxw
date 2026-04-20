# 使用手册

本文档介绍 QXW 工具集所有命令的详细用法。

## 命令概览

| 命令 | 说明 | 状态 |
|------|------|------|
| `qxw` | 列出所有可用命令 | ✅ 可用 |
| `qxw-hello` | 示例命令，验证安装 | ✅ 可用 |
| `qxw-sbdqf` | 老鼠穿越动画（致敬 sl 命令） | ✅ 可用 |
| `qxw-chat` | AI 对话工具 | ✅ 可用 |
| `qxw-chat-provider` | AI 对话提供商管理 | ✅ 可用 |
| `qxw-gitbook` | Markdown 文档工具（PDF 转换 / 本地预览） | ✅ 可用 |
| `qxw-webtool` | 开发者 Web 工具集（文本对比 / JSON / 时间戳 / 加解密 / 编解码） | ✅ 可用 |
| `qxw-file-server` | 文件服务器（HTTP / FTP 文件共享，支持鉴权） | ✅ 可用 |
| `qxw-image` | 📷 图片工具集（HTTP 图片浏览 / RAW 批量转换） | ✅ 可用 |

## qxw

列出 QXW 工具集提供的所有命令。从已安装包的元数据中动态读取命令列表，以表格形式展示。

### 基本用法

```bash
qxw
```

### 参数说明

| 参数 | 说明 |
|------|------|
| `--version` | 显示版本号 |
| `--help` | 显示帮助信息 |

### 输出示例

```
       QXW 命令列表 (v0.1.0)
┌───────────────────┬──────────────────────┐
│ 命令              │ 说明                  │
├───────────────────┼──────────────────────┤
│ qxw               │ 列出所有可用命令       │
│ qxw-hello         │ QXW 工具集示例命令     │
│ qxw-sbdqf         │ 🐭 老鼠穿越动画       │
│ qxw-chat          │ 🤖 AI 对话工具        │
│ qxw-chat-provider │ AI 对话提供商管理      │
└───────────────────┴──────────────────────┘

共 5 个命令，使用 <命令> --help 查看详细用法。
```

## qxw-hello

示例命令，用于验证 QXW 工具集安装是否正确。

### 环境初始化

首次运行 `qxw-hello` 时，会自动检测运行环境是否就绪。如果尚未初始化，将自动完成以下操作：

- 创建配置目录 `~/.config/qxw/`
- 生成配置文件 `~/.config/qxw/setting.json`（基于内置模板）
- 创建日志目录 `~/.config/qxw/logs/`
- 初始化数据库文件 `~/.config/qxw/qxw.db`

后续运行时若环境已就绪，则跳过初始化步骤。

### 基本用法

```bash
# 命令行模式（默认）
qxw-hello

# TUI 交互模式
qxw-hello --tui
```

### 参数说明

| 参数 | 缩写 | 默认值 | 说明 |
|------|------|--------|------|
| `--name` | `-n` | 世界 | 问候对象的名称 |
| `--tui` | - | false | 启用 TUI 交互模式 |
| `--version` | - | - | 显示版本号 |
| `--help` | - | - | 显示帮助信息 |

### 示例

```bash
# 自定义问候对象
qxw-hello --name 开发者

# 查看版本
qxw-hello --version

# 查看帮助
qxw-hello --help
```

### TUI 界面快捷键

| 快捷键 | 功能 |
|--------|------|
| `Q` | 退出 |
| `D` | 切换暗色/亮色主题 |

## qxw-sbdqf

老鼠穿越动画命令，致敬经典的 `sl` 命令。一只 ASCII 老鼠从终端屏幕右边飞速跑到左边。

和 `sl` 一样，动画期间 Ctrl+C 无法中断——你必须耐心等待老鼠跑完全程！

### 基本用法

```bash
qxw-sbdqf
```

### 参数说明

| 参数 | 说明 |
|------|------|
| `--version` | 显示版本号 |
| `--help` | 显示帮助信息 |

### 动画说明

- 一只带大耳朵、胡须和长尾巴的 ASCII 老鼠从右往左穿过屏幕
- 老鼠有奔跑腿部动画和尾巴摆动效果
- 动画期间屏蔽 SIGINT 信号，必须等老鼠跑完
- 老鼠垂直居中显示，自动适配终端宽度

## qxw-chat-provider

管理 AI 对话服务提供商，支持 OpenAI 和 Anthropic 两种类型。

### TUI 管理界面

```bash
qxw-chat-provider --tui
```

启动 TUI 管理界面后可通过快捷键操作：

| 快捷键 | 功能 |
|--------|------|
| `A` | 添加提供商 |
| `E` / `Enter` | 编辑选中的提供商 |
| `D` | 删除选中的提供商 |
| `S` | 将选中的提供商设为默认 |
| `Q` | 退出 |

### 命令行用法

```bash
# 列出所有提供商
qxw-chat-provider list

# 添加 OpenAI 提供商
qxw-chat-provider add \
  --name my-openai \
  --type openai \
  --base-url https://api.openai.com/v1 \
  --api-key sk-your-key \
  --model gpt-4o \
  --default

# 添加 Anthropic 提供商
qxw-chat-provider add \
  --name my-claude \
  --type anthropic \
  --base-url https://api.anthropic.com \
  --api-key sk-ant-your-key \
  --model claude-sonnet-4-20250514

# 查看提供商详情
qxw-chat-provider show my-openai

# 编辑提供商
qxw-chat-provider edit my-openai --temperature 0.5 --system-prompt "你是一个有帮助的助手"

# 设为默认提供商
qxw-chat-provider set-default my-claude

# 删除提供商
qxw-chat-provider delete my-openai

# 测试提供商连接（使用默认提供商）
qxw-chat-provider ping

# 测试指定提供商连接
qxw-chat-provider ping my-openai

# 测试所有提供商连接
qxw-chat-provider ping-all
```

### 子命令说明

| 子命令 | 说明 |
|--------|------|
| `list` | 列出所有已配置的提供商 |
| `add` | 添加一个新的提供商 |
| `show <name>` | 查看提供商详情 |
| `edit <name>` | 编辑提供商配置 |
| `delete <name>` | 删除提供商（支持 `-y` 跳过确认） |
| `set-default <name>` | 将指定提供商设为默认 |
| `ping [name]` | 测试提供商连接是否正常（不指定则使用默认提供商） |
| `ping-all` | 测试所有已配置的提供商连接 |

### add 参数说明

| 参数 | 缩写 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `--name` | `-n` | 是 | - | 提供商名称（唯一标识） |
| `--type` | - | 是 | - | 提供商类型：`openai` 或 `anthropic` |
| `--base-url` | `-u` | 是 | - | API 基础地址 |
| `--api-key` | `-k` | 是 | - | API 密钥 |
| `--model` | `-m` | 是 | - | 默认模型名称 |
| `--temperature` | `-t` | 否 | 0.7 | 默认温度参数 |
| `--max-tokens` | - | 否 | 4096 | 默认最大 token 数 |
| `--top-p` | - | 否 | 1.0 | 默认 top_p 参数 |
| `--system-prompt` | `-s` | 否 | (空) | 默认系统提示词 |
| `--default` | - | 否 | false | 设为默认提供商 |

## qxw-chat

与已配置的 AI 对话提供商进行交互式对话，支持流式输出。

### 基本用法

```bash
# 使用默认提供商开始交互式对话
qxw-chat

# 指定提供商
qxw-chat --provider my-openai

# 覆盖默认参数
qxw-chat --model gpt-4o-mini --temperature 0.3

# 单次对话模式（发送一条消息后退出）
qxw-chat -m "用 Python 写一个快速排序"

# 指定系统提示词
qxw-chat --system "你是一个 Python 专家"
```

### 参数说明

| 参数 | 缩写 | 默认值 | 说明 |
|------|------|--------|------|
| `--provider` | `-p` | (默认提供商) | 指定提供商名称 |
| `--model` | - | (提供商默认) | 覆盖默认模型 |
| `--temperature` | `-t` | (提供商默认) | 覆盖默认温度参数 |
| `--max-tokens` | - | (提供商默认) | 覆盖默认最大 token 数 |
| `--top-p` | - | (提供商默认) | 覆盖默认 top_p 参数 |
| `--system` | `-s` | (提供商默认) | 覆盖默认系统提示词 |
| `--message` | `-m` | - | 单次对话模式 |

### 交互式对话命令

| 命令 | 说明 |
|------|------|
| `/exit` | 退出对话 |
| `/clear` | 清空上下文（重新开始对话） |
| `Ctrl+C` | 退出对话 |

## qxw-gitbook

Markdown 文档工具，支持将 Markdown 文件批量转换为 PDF，以及启动本地 HTTP 预览服务。

### 安装 PDF 转换依赖

`serve` 子命令开箱可用。`pdf` 子命令需要额外安装 `weasyprint`：

```bash
# macOS
brew install pango
pip install weasyprint

# 或一步到位
pip install "qxw[gitbook]"
```

### 基本用法

```bash
# 将当前目录下的 .md 文件转换为 PDF
qxw-gitbook pdf

# 递归处理子目录
qxw-gitbook pdf -r

# 指定源目录和输出目录
qxw-gitbook pdf -d docs/ -o output/

# 启动本地预览服务
qxw-gitbook serve

# 指定端口和目录
qxw-gitbook serve -p 3000 -d docs/
```

### 子命令说明

| 子命令 | 说明 |
|--------|------|
| `pdf` | 将目录下的 Markdown 文件批量转换为 PDF |
| `serve` | 启动本地 HTTP 服务预览 Markdown 文件 |
| `summary` | 为目录生成 SUMMARY.md 和 INDEX.md 目录文件 |

### pdf 参数说明

| 参数 | 缩写 | 默认值 | 说明 |
|------|------|--------|------|
| `--dir` | `-d` | `.` | Markdown 文件所在目录 |
| `--output` | `-o` | (与源文件同目录) | PDF 输出目录 |
| `--recursive` | `-r` | false | 递归处理子目录中的文件 |

### serve 参数说明

| 参数 | 缩写 | 默认值 | 说明 |
|------|------|--------|------|
| `--dir` | `-d` | `.` | Markdown 文件所在目录 |
| `--port` | `-p` | 8000 | 服务端口 |
| `--host` | `-H` | 127.0.0.1 | 监听地址 |

### summary 用法

扫描目录结构，为每个包含 `README.md` 的目录自动生成：

- **SUMMARY.md**：标题 + 目录结构
- **INDEX.md**：README.md 内容 + 目录结构

```bash
# 为当前目录生成
qxw-gitbook summary

# 指定目录和深度
qxw-gitbook summary -d docs/ --depth 5
```

### summary 参数说明

| 参数 | 缩写 | 默认值 | 说明 |
|------|------|--------|------|
| `--dir` | `-d` | `.` | 文档根目录 |
| `--depth` | - | 3 | 目录层级深度 |

### summary 特殊规则

- 文件按数字前缀排序（如 `1.intro.md`、`2.setup.md`）
- 标题含 `(todo)` 的文件/目录会被跳过
- 目录下存在 `SUMMARY.md.skip` 文件时跳过该目录的生成

## qxw-webtool

开发者常用 Web 工具集，启动一个本地 HTTP 服务，在浏览器中提供多种实用工具。

### 基本用法

```bash
# 启动服务（默认 9000 端口）
qxw-webtool

# 指定端口
qxw-webtool -p 3000

# 允许局域网访问
qxw-webtool -H 0.0.0.0
```

### 参数说明

| 参数 | 缩写 | 默认值 | 说明 |
|------|------|--------|------|
| `--port` | `-p` | 9000 | 服务端口 |
| `--host` | `-H` | 127.0.0.1 | 监听地址 |
| `--version` | - | - | 显示版本号 |
| `--help` | - | - | 显示帮助信息 |

### 功能列表

#### 文本对比

两段文本的 Unified Diff 差异比较，高亮显示新增（绿色）和删除（红色）行。

#### JSON 格式化

- **格式化**：将 JSON 美化为缩进格式
- **压缩**：将 JSON 压缩为单行
- **校验**：检查 JSON 是否合法

#### 时间戳转换

- 实时显示当前 Unix 时间戳
- Unix 时间戳（秒/毫秒）→ 日期时间
- 日期时间 → Unix 时间戳
- 支持格式：`YYYY-MM-DD HH:MM:SS`、`YYYY-MM-DD`、`YYYY/MM/DD` 等

#### 加解密

| 功能 | 算法 | 说明 |
|------|------|------|
| 哈希 | MD5 / SHA1 / SHA256 / SHA512 | 单向哈希计算 |
| HMAC | HMAC-SHA256 / HMAC-SHA512 | 基于密钥的消息认证码 |
| AES | AES-128/192/256（CBC / ECB） | 对称加密，PKCS7 填充，密钥为 Hex 格式 |
| DES | DES（CBC） | 对称加密，8 字节 Hex 密钥 |
| 3DES | 3DES（CBC） | 对称加密，16/24 字节 Hex 密钥 |
| RSA | RSA-2048/4096（OAEP+SHA256） | 非对称加密，支持密钥对生成 |
| Ed25519 | Ed25519 | 非对称签名，支持密钥对生成 / 签名 / 验证 |

对称加密约定：
- 密钥和 IV 使用 Hex 格式输入
- 加密输出为 Base64（CBC 模式下 IV 前置于密文）
- 解密输入为 Base64（自动提取前置的 IV）

#### URL 编解码

URL Encode / Decode 转换。

#### Base64 编解码

Base64 Encode / Decode 转换。

## qxw-file-server

文件服务器工具，支持通过 HTTP 或 FTP 协议快速共享目录文件。两种协议均内置鉴权保护。

### 安装 FTP 依赖

`http` 子命令开箱可用。`ftp` 子命令需要额外安装 `pyftpdlib`：

```bash
pip install pyftpdlib

# 或一步到位
pip install "qxw[ftp]"
```

### 基本用法

```bash
# 启动 HTTP 文件服务器（共享当前目录）
qxw-file-server http

# 启动 FTP 文件服务器
qxw-file-server ftp

# 指定共享目录
qxw-file-server http -d /tmp
qxw-file-server ftp -d /tmp

# 指定用户名和密码
qxw-file-server http -u myuser -P mypass
qxw-file-server ftp -u myuser -P mypass

# FTP 开启写入权限
qxw-file-server ftp -w
```

### 子命令说明

| 子命令 | 说明 |
|--------|------|
| `http` | 启动 HTTP 文件服务器（带 Basic Auth 鉴权） |
| `ftp` | 启动 FTP 文件服务器（带用户鉴权） |

### http 参数说明

| 参数 | 缩写 | 默认值 | 说明 |
|------|------|--------|------|
| `--dir` | `-d` | `.` | 共享目录路径 |
| `--port` | `-p` | 8080 | 服务端口 |
| `--host` | `-H` | 127.0.0.1 | 监听地址 |
| `--username` | `-u` | admin | 鉴权用户名 |
| `--password` | `-P` | (自动生成) | 鉴权密码，不指定则自动生成随机密码 |

### ftp 参数说明

| 参数 | 缩写 | 默认值 | 说明 |
|------|------|--------|------|
| `--dir` | `-d` | `.` | 共享目录路径 |
| `--port` | `-p` | 2121 | 服务端口 |
| `--host` | `-H` | 0.0.0.0 | 监听地址 |
| `--username` | `-u` | admin | 鉴权用户名 |
| `--password` | `-P` | (自动生成) | 鉴权密码，不指定则自动生成随机密码 |
| `--writable` | `-w` | false | 允许上传 / 写入 / 删除文件 |

### 鉴权说明

- 不指定 `--password` 时，每次启动自动生成随机密码并打印在终端
- HTTP 使用 Basic Auth 鉴权，浏览器访问时弹出登录窗口
- FTP 使用标准 FTP 用户认证，客户端连接时需输入用户名和密码

### 使用示例

```bash
# 在局域网内分享文件
qxw-file-server http -d ~/Downloads

# 仅本机访问
qxw-file-server http -H 127.0.0.1

# FTP 可写模式（允许上传）
qxw-file-server ftp -d /tmp/shared -w -u upload -P secret123

# 使用 FTP 客户端连接
ftp admin@localhost 2121
```

## qxw-image

图片工具集，支持通过 HTTP 服务浏览图片画廊（含缩略图和 Live Photo），并支持将相机 RAW 文件批量转换为 JPG。

### 安装图片处理依赖

```bash
pip install "qxw[image]"
```

这将安装 Pillow（图片处理）和 rawpy（用于 RAW 解码和画廊预览）。如需 HEIC 格式支持，额外安装：

```bash
pip install pillow-heif
```

### 基本用法

```bash
# 启动图片浏览 HTTP 服务（当前目录）
qxw-image http

# 指定图片目录
qxw-image http -d ~/Photos

# 将当前目录 RAW 文件批量转为 JPG（输出到 ./jpg/）
qxw-image raw
```

### 子命令说明

| 子命令 | 说明 |
|--------|------|
| `http` | 启动图片浏览 HTTP 服务（缩略图画廊，支持 Live Photo） |
| `raw`  | 将相机导出的 RAW 图片批量转换为 JPG |

### http 参数说明

| 参数 | 缩写 | 默认值 | 说明 |
|------|------|--------|------|
| `--dir` | `-d` | `.` | 图片目录路径 |
| `--port` | `-p` | 8080 | 服务端口 |
| `--host` | `-H` | 127.0.0.1 | 监听地址 |
| `--thumb-size` | `-s` | 400 | 缩略图尺寸（像素） |
| `--thumb-quality` | - | 85 | 缩略图 JPEG 质量 (1-100) |
| `--recursive` | `-r` | true | 递归扫描子目录 |
| `--no-recursive` | - | - | 不递归扫描子目录 |

### raw 参数说明

| 参数 | 缩写 | 默认值 | 说明 |
|------|------|--------|------|
| `--dir` | `-d` | `.` | RAW 文件所在目录 |
| `--output` | `-o` | `<源目录>/jpg` | 输出目录（保持相对路径结构） |
| `--recursive` | `-r` | false | 是否递归处理子目录 |
| `--quality` | `-q` | 92 | JPEG 压缩质量 (1-100)，仅在 rawpy 解码路径生效 |
| `--overwrite` / `--no-overwrite` | - | `--no-overwrite` | 是否覆盖已存在的输出文件 |
| `--use-embedded` / `--no-use-embedded` | - | `--use-embedded` | 是否优先使用相机内嵌 JPEG 预览 |
| `--fast` | - | false | 快速解码：线性去马赛克 + 半分辨率，仅对 rawpy 解码路径生效（约 8-10x 加速） |
| `--workers` | `-j` | `min(CPU核数, 4)` | 并行处理线程数，`-j 1` 表示串行 |

### raw 转换策略

`raw` 子命令支持两种输出路径，通过 `--use-embedded/--no-use-embedded` 切换：

1. **优先沿用相机嵌入预览（默认 `--use-embedded`）**：如果 RAW 文件中包含尺寸合格（长边 ≥ 1000px）的 JPEG 预览，直接写入其原始字节作为输出。色彩、色调、EXIF 与相机直出（即 Finder / Preview 打开 RAW 时看到的效果）保持一致，`--quality` 和 `--fast` 对此路径无影响。
2. **rawpy 解码（`--no-use-embedded` 或嵌入预览不可用时）**：使用 rawpy 以 sRGB / 8bit / 相机白平衡 / 自动亮度重新解码，此时 `--quality` 生效。此路径不会套用相机厂商的调色，效果可能偏平，但便于后期调色或在相机未嵌入大尺寸预览时使用。加上 `--fast` 后会切换到线性去马赛克 + 半分辨率输出，速度约 8-10x，分辨率降为原始的 1/2。

### 加速建议

- **并行处理**：默认已启用 `min(CPU核数, 4)` 个线程并行处理所有文件（两条路径都受益）。大批量转换时可用 `-j 8` 或更高进一步提速；内存不足时用 `-j 2` 或 `-j 1` 降档。
- **嵌入预览路径极快**：只写字节、无解码，几百张 RAW 也能秒级完成。只要不介意沿用相机直出画质，就保留默认的 `--use-embedded`。
- **rawpy 解码变慢**：AHD 去马赛克是 CPU 密集型操作，全尺寸处理单张需数秒。需要加速时加 `--fast`（代价是半分辨率输出与线性去马赛克）。

### 支持的格式

- **图片格式**：JPG, PNG, GIF, WebP, BMP, TIFF, HEIC
- **RAW 格式**：CR2, CR3 (Canon), NEF (Nikon), ARW (Sony), DNG (Adobe), ORF (Olympus), RW2 (Panasonic), PEF (Pentax), RAF (Fujifilm) 等
- **Live Photo**：自动检测同目录下同名的图片和视频文件（MOV/MP4）

### 使用示例

```bash
# 浏览照片目录
qxw-image http -d ~/Photos

# 局域网分享图片
qxw-image http -d ~/Photos -H 0.0.0.0

# 调整缩略图参数
qxw-image http -s 300 --thumb-quality 70

# 将 ~/Photos 里的 RAW 文件（含子目录）批量转换为 JPG
qxw-image raw -d ~/Photos -r

# 指定输出目录并覆盖已有文件
qxw-image raw -d ~/Photos -o ~/Photos/converted --overwrite
```
