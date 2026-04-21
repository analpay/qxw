# 快速开始

本文档帮助你在 5 分钟内完成 QXW 工具集的安装和首次使用。

## 1. 一键安装（推荐）

```bash
git clone <仓库地址>
cd qxw
bash install.sh
```

脚本会自动完成以下工作：

- 检测操作系统和包管理器（macOS / Ubuntu / CentOS / Arch 等）
- 安装 Python >= 3.10（如缺失）
- 安装 pipx（如缺失）
- 通过 pipx 全局安装 qxw 工具集
- 验证所有命令是否可用

更多选项：

```bash
bash install.sh --dev        # 开发模式（虚拟环境 + dev 依赖）
bash install.sh --force      # 强制重装
bash install.sh --gitbook    # 同时安装 gitbook PDF 导出依赖
bash install.sh --uninstall  # 卸载 qxw
bash install.sh --help       # 查看帮助
```

## 2. 手动安装

如果你更习惯手动操作，也可以按以下步骤进行。

### 环境要求

- Python >= 3.10
- pipx（推荐）或 pip

### 方式一：pipx 全局安装（推荐）

```bash
git clone <仓库地址>
cd qxw
pipx install .
```

代码更新后重新安装：

```bash
pipx install . --force
```

### 方式二：虚拟环境开发模式

```bash
git clone <仓库地址>
cd qxw
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## 3. 验证安装

```bash
# 运行示例命令（默认命令行模式）
qxw-hello

# 或使用 TUI 交互模式
qxw-hello --tui

# 看一只老鼠跑过屏幕（致敬 sl 命令）
qxw-sbdqf
```

首次运行时会自动初始化运行环境（创建配置目录、配置文件、日志目录和数据库），输出类似：

```
检测到运行环境未完成初始化，正在自动初始化...
  已初始化: 配置目录
  已初始化: 配置文件
  已初始化: 日志目录
  已初始化: 数据库
环境初始化完成
```

如果看到 "你好, 世界！" 的输出，说明安装成功。

## 4. 查看所有命令

```bash
# 列出所有可用命令
qxw
```

每个命令都支持 `--help` 参数：

```bash
qxw-hello --help
```

## 5. AI 对话快速体验

```bash
# 添加一个 OpenAI 提供商
qxw-chat-provider add \
  --name my-openai \
  --type openai \
  --base-url https://api.openai.com/v1 \
  --api-key sk-your-key \
  --model gpt-4o \
  --default

# 验证连接是否正常
qxw-chat-provider ping

# 开始交互式对话
qxw-chat

# 或发送单条消息
qxw-chat -m "你好"
```

## 6. Markdown 文档工具

```bash
# 预览当前目录下的 Markdown 文件
qxw-gitbook serve

# 将 Markdown 文件转换为 PDF（需先安装 weasyprint）
qxw-gitbook pdf
```

## 7. 开发者 Web 工具集

```bash
# 启动 Web 工具服务
qxw-webtool

# 指定端口
qxw-webtool -p 3000
```

在浏览器中打开 http://127.0.0.1:9000 即可使用文本对比、JSON 格式化、时间戳转换、加解密、URL/Base64 编解码等工具。

## 8. 文件服务器

```bash
# 启动 HTTP 文件服务器，共享当前目录
qxw-file-server http

# 启动 FTP 文件服务器（需安装 pyftpdlib）
pip install pyftpdlib
qxw-file-server ftp
```

启动后终端会打印自动生成的用户名和密码，用浏览器访问 http://0.0.0.0:8080 即可浏览文件。

## 9. 图片工具

```bash
# 安装图片处理依赖
pip install "qxw[image]"

# 启动图片浏览 HTTP 服务
qxw-image http

# 指定目录
qxw-image http -d ~/Photos

# 将相机 RAW 文件批量转换为 JPG（输出到源目录下的 jpg/）
qxw-image raw -d ~/Photos -r

# 导出 RAW 时套用富士 Classic Chrome 滤镜（自动走 rawpy 解码 + 调色）
qxw-image raw -d ~/Photos --filter fuji-cc

# 对已有 JPG/PNG 批量套滤镜（与 raw --filter 共享同一套插件）
qxw-image filter --list                             # 查看所有可用滤镜
qxw-image filter -n ghibli -d ~/Photos/exports      # 吉卜力风格，输出到 exports/filtered/

# 将目录下所有 SVG 批量转成同名 PNG（默认递归、2x 缩放、覆盖同名文件、白底）
qxw-image svg -d ./assets

# SVG 转 PNG 但保留透明背景
qxw-image svg -d ./assets -b transparent
```

浏览器打开 http://127.0.0.1:8080 即可浏览图片画廊，点击缩略图查看原图，支持 Live Photo 播放。

## 10. Markdown → 公众号适配

将 Markdown 里的 PlantUML 代码围栏本地渲染为图片，并生成一份可直接粘贴到微信公众号编辑器的 `_wx.md` 副本（渲染走本地 `plantuml.jar`，需要先装好 Java 运行时）。

```bash
# 一次性准备：下载 plantuml.jar 到默认位置
mkdir -p ~/.config/qxw
curl -L https://github.com/plantuml/plantuml/releases/download/v1.2024.7/plantuml-1.2024.7.jar \
  -o ~/.config/qxw/plantuml.jar

# 生成 docs/article_wx.md + docs/article_1.png / article_2.png ...（默认白底 PNG）
qxw-markdown wx docs/article.md

# 透明底 SVG / 黑底 JPG 等
qxw-markdown wx docs/article.md -f svg -b transparent
qxw-markdown wx docs/article.md -f jpg -b black -q 95
```

## 11. Markdown → AI 封面生成

通过 [ZenMux](https://zenmux.ai/) 接入 Google **Gemini 3 Pro Image Preview（Nano Banana Pro）** 图像模型，为 Markdown 文档一键生成白皮书 / 技术架构图风格的封面 PNG。

```bash
# 一次性准备：设置 ZenMux API Key（任选其一）
export ZENMUX_API_KEY=sk-zm-xxx
# 或写入 ~/.config/qxw/setting.json 的 zenmux_api_key 字段

# 生成 docs/article_cover.png（与源文件同目录）
qxw-markdown cover docs/article.md

# 指定输出路径 + 额外提示词
qxw-markdown cover docs/article.md -o out/cover.png --extra-prompt "突出网络拓扑与时序"
```

默认风格：浅绿网格背景 / 青蓝结构与标签 / 橙绿色数据流箭头 / 精致 CPU/机架图标 / LaTeX 公式。可用 `--style-prompt` 整段替换主视觉描述。详见 [使用手册](user-guide.md#cover-子命令)。

## 12. 下一步

- 阅读 [使用手册](user-guide.md) 了解所有可用命令
- 阅读 [开发手册](development.md) 了解如何开发新命令
