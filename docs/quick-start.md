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
bash install.sh --pdf        # 同时安装 PDF 导出依赖（qxw-serve gitbook 的 PDF 下载）
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
qxw hello

# 或使用 TUI 交互模式
qxw hello --tui

# 看一只老鼠跑过屏幕（致敬 sl 命令）
qxw sbdqf
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
# 列出所有 qxw-* 独立命令（不含 qxw 内置子命令）
qxw list

# 查看 qxw 命令组的子命令（list / hello / sbdqf / completion）
qxw --help
```

每个命令都支持 `--help` 参数：

```bash
qxw hello --help
qxw-image --help
```

## 5. AI 对话快速体验

```bash
# 添加一个 OpenAI 提供商
qxw-llm provider add \
  --name my-openai \
  --type openai \
  --base-url https://api.openai.com/v1 \
  --api-key sk-your-key \
  --model gpt-4o \
  --default

# 验证连接是否正常
qxw-llm provider ping

# 启动提供商 TUI 管理界面（可视化增删改查）
qxw-llm tui

# 开始交互式对话
qxw-llm chat

# 或发送单条消息
qxw-llm chat -m "你好"
```

## 6. HTTP 服务集合（qxw-serve）

把常用 HTTP 小服务统一到 `qxw-serve <子命令>` 下，包含 gitbook 预览、开发者工具、文件共享与图片画廊。

```bash
# Markdown 本地预览（侧边目录树 + 单页 / 整本 PDF 下载按钮）
qxw-serve gitbook -d docs/

# 开发者 Web 工具集（文本对比 / JSON / 时间戳 / 加解密 / 编解码）
qxw-serve webtool -p 3000

# HTTP 文件共享（Basic Auth，密码不指定时启动时自动生成并打印）
qxw-serve file-web -d ~/Downloads

# 图片画廊（缩略图 + 灯箱 + Live Photo + RAW 预览 + 灯箱内 15 档参数调整预览）
pip install "qxw[image]"
qxw-serve image-web -d ~/Photos
# 打开任意图片后点击 "🎚 调整" 展开：曝光 / 鲜明度 / 高光 / 阴影 / 对比度 / 亮度 / 黑点
# / 饱和度 / 自然饱和度 / 色温 / 色调 / 锐度 / 清晰度 / 噪点消除 / 晕影
# 满意后点击 "💾 保存原尺寸" → 源目录下生成 <原名>_adjusted_<时间戳>.jpg
```

> `qxw-serve gitbook` 的"下载本页 PDF / 下载整本 PDF"按钮依赖 `weasyprint`。若未安装，预览依然可用，仅 PDF 下载会返回错误并提示：
>
> - macOS：`brew install pango && pip install weasyprint`
> - Linux：`sudo apt install libpango-1.0-0 && pip install weasyprint`
> - 或一步到位：`pip install "qxw[pdf]"`

## 7. 图片批处理（qxw-image）

```bash
# 安装图片处理依赖
pip install "qxw[image]"

# 将相机 RAW 文件批量转换为 JPG（输出到源目录下的 jpg/）
qxw-image raw -d ~/Photos -r

# 导出 RAW 时套用富士 Classic Chrome 滤镜（自动走 rawpy 解码 + 调色）
qxw-image raw -d ~/Photos --filter fuji-cc

# 对已有 JPG/PNG 批量套滤镜（与 raw --filter 共享同一套插件）
qxw-image filter --list                             # 查看所有可用滤镜
qxw-image filter -n ghibli -d ~/Photos/exports      # 吉卜力风格，输出到 exports/filtered/

# 自动调整亮度/对比/饱和（按档位预设，HDR 默认开启，保留 EXIF）
qxw-image change -d ~/Photos/exports                # 默认 balanced 档 + HDR，输出到 exports/changed/
qxw-image change -d ~/Photos/exports --no-hdr       # 关闭 HDR 局部 tone mapping

# 原地擦除 EXIF / IPTC / XMP / ICC 等元数据（不可逆，先要二次确认或加 --yes）
qxw-image clear -d ~/Photos/exports --yes           # JPEG 走 quality="keep" 真正无损
qxw-image clear -d ~/Photos/exports -r -j 8 --yes   # 递归 + 8 线程并行

# 将目录下所有 SVG 批量转成同名 PNG（默认递归、2x 缩放、覆盖同名文件、白底）
qxw-image svg -d ./assets

# SVG 转 PNG 但保留透明背景
qxw-image svg -d ./assets -b transparent
```

## 8. Markdown → 公众号适配

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

## 9. Markdown → AI 封面生成

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

## 10. Shell 自动补全

为所有 `qxw` / `qxw-*` 命令一次性开启 zsh / bash 的子命令与选项 tab 补全：

```bash
# 自动检测 $SHELL，生成补全脚本并在 rc 末尾追加 source 行（改 rc 前有确认提示）
qxw completion install

# 让当前 shell 立即生效
source ~/.zshrc                # zsh
# 或 exec zsh / exec bash

# 验证
qxw <TAB>                      # 应补出 list / hello / sbdqf / completion
qxw-image <TAB>                # 应补出 raw / svg / filter / change / clear
qxw-serve <TAB>                # 应补出 gitbook / webtool / file-web / image-web
qxw-llm <TAB>                  # 应补出 chat / tui / provider
qxw-llm provider <TAB>         # 应补出 list / add / show / edit / delete / ...

# 随时查看状态
qxw completion status
```

新增或修改命令后，再跑一次 `qxw completion install -y` 即可刷新（脚本整体覆盖，无需卸载）。详见 [使用手册 · qxw completion](user-guide.md#qxw-completion)。

## 11. 字符串工具

```bash
# 统计字符串的字符数（Unicode 码点）与 UTF-8 字节数
qxw-str len "hello"
qxw-str len "你好，世界"

# 从 stdin 读取（支持管道 / 文件）
echo -n "hello world" | qxw-str len
cat README.md | qxw-str len

# 纯数字输出，方便脚本捕获
LEN=$(qxw-str len -q "你好世界")      # 字符数
BYTES=$(qxw-str len -b "你好世界")    # UTF-8 字节数
```

## 12. 数学表达式计算

```bash
# 四则运算（shell 下务必用引号包裹，避免 * ( ) 被解释）
qxw-math "1 + 2 * 3"          # 7
qxw-math "(3 + 4) / 2"        # 3.5

# 次方：** 或 ^
qxw-math "2^10"               # 1024
qxw-math "2**32"              # 4294967296

# 开方：sqrt(x) / √(x) / √<数字>
qxw-math "sqrt(2)"            # 1.4142135623730951
qxw-math "√16"                # 4

# 从 stdin 读取 + 纯数字输出
RESULT=$(echo "100/25" | qxw-math -q)
echo "$RESULT"                # 4
```

> 底层用 `ast` 白名单遍历实现，不调用 `eval`，对不可信输入安全；属性访问、变量名、未授权的函数都会被拒绝。

## 13. git 仓库打包

把当前 git 项目打包成一个 tar / zip 包，包内 **不含 `.git` 目录**，且 git-lfs 文件已提前 `git lfs pull` 实体化（不会留下指针文件）：

```bash
# 当前仓库 → ../<repo>.tar（默认 tar）
qxw-git archive

# 切换格式
qxw-git archive -f tar.gz
qxw-git archive -f zip

# 自定义输出路径 + 包内顶层目录名
qxw-git archive -f zip -o /tmp/myrepo.zip --prefix release-1.0

# 跳过 git lfs pull（仓库无 LFS 或不想实体化时）
qxw-git archive --no-lfs

# 指定要打包的分支 / tag / commit（不会动主工作树）
qxw-git archive -r main
qxw-git archive --ref v1.2.0 -f tar.gz
qxw-git archive -r feature/foo               # 含 / 的分支名也支持

# 排除文件 / 目录 / glob（默认已自动排除 .gitattributes）
qxw-git archive -e docs                      # 排除 docs/ 目录
qxw-git archive -e '*.md' -e tests/fixtures  # 同时排除多个

# 脚本捕获生成包路径
ARCHIVE=$(qxw-git archive --quiet)
```

> 打包的文件清单来自 `git ls-files`，自动忽略 `.git` 与 `.gitignore` 命中的内容；并默认追加排除 `.gitattributes`（已实体化的 LFS 内容不再需要它）。
> 仓库引用了 LFS 但当前环境未装 git-lfs 时，命令会拒绝继续，避免输出"看起来是 LFS 文件，实际只是指针"的损坏包；想绕过加 `--no-lfs` 即可。

## 14. 下一步

- 阅读 [使用手册](user-guide.md) 了解所有可用命令
- 阅读 [开发手册](development.md) 了解如何开发新命令
