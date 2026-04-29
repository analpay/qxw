# QXW 命令行工具集合

QXW 是一个通用开发命令行工具集合，采用 Python 开发，提供 TUI（终端用户界面）交互体验。

## 特性

- 🛠️ 模块化命令设计，每个功能独立为 `qxw-xxx` 命令
- 🖥️ 基于 Textual 的 TUI 交互界面
- 📦 Pydantic 强类型数据校验
- 🗄️ SQLAlchemy ORM + SQLite 数据持久化
- 📝 完整的 `--help` 帮助信息

## 快速开始

### 一键安装（推荐）

```bash
git clone <仓库地址>
cd qxw
bash install.sh
```

脚本会自动检测操作系统、安装 Python >= 3.10、pipx 及所有依赖。更多选项见 `bash install.sh --help`。

### 手动安装

#### 方式一：pipx 全局安装

```bash
pipx install .

# 更新（代码改动后重新安装）
pipx install . --force
```

#### 方式二：虚拟环境开发模式

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### 验证安装

```bash
# 查看 qxw 主命令帮助（列出子命令）
qxw --help

# 列出所有 qxw-* 独立命令（不含 qxw 内置子命令）
qxw list

# 运行示例子命令
qxw hello

# TUI 交互模式
qxw hello --tui

# 自定义问候
qxw hello --name 开发者
```

## 命令列表

`qxw` 是命令组主入口，内置若干子命令；其余独立命令以 `qxw-*` 形式分布。

### qxw 命令组子命令

| 子命令 | 说明 |
|--------|------|
| `qxw list` | 📋 列出所有 `qxw-*` 独立命令 |
| `qxw hello` | 示例命令，验证安装是否成功 |
| `qxw sbdqf` | 🐭 老鼠穿越动画，致敬经典 sl 命令 |
| `qxw completion` | 🔑 生成并安装 Shell 补全脚本（zsh / bash） |

### qxw-* 独立命令

| 命令 | 说明 |
|------|------|
| `qxw-llm` | 🤖 AI 对话工具集合（对话 / 提供商管理 / TUI） |
| `qxw-serve` | 🌐 HTTP 服务集合（gitbook 预览 / 开发者工具 / 文件共享 / 图片画廊） |
| `qxw-image` | 📷 图片工具集（RAW 批量转 JPG / SVG 转 PNG / 调色滤镜 / 自动亮度对比饱和调整 / 元数据擦除） |
| `qxw-markdown` | 📝 Markdown 工具集（PlantUML 渲染 / 公众号适配 / AI 封面生成 / SUMMARY 生成） |
| `qxw-str` | 🔤 字符串工具集（长度统计等） |
| `qxw-math` | 🧮 字符串数学表达式计算（四则 / 次方 / 开方） |
| `qxw-git` | 📦 git 仓库工具集（archive 打包 tar/zip，剔除 .git，自动 LFS pull） |

### qxw-serve 子命令

| 子命令 | 说明 |
|--------|------|
| `qxw-serve gitbook` | 📖 Markdown 本地预览，支持从网页下载单页 PDF 与整本 PDF |
| `qxw-serve webtool` | 🧰 开发者 Web 工具集（文本对比 / JSON / 时间戳 / 加解密 / 编解码） |
| `qxw-serve file-web` | 📂 HTTP 文件共享（带 Basic Auth 鉴权） |
| `qxw-serve image-web` | 🖼 图片画廊（缩略图 / Live Photo / RAW） |

### qxw-llm 子命令

| 子命令 | 说明 |
|--------|------|
| `qxw-llm chat` | 🗣 与已配置的提供商进行对话（交互式 / 单次） |
| `qxw-llm tui` | 🖥 提供商 TUI 管理界面 |
| `qxw-llm provider list` | 📋 列出所有已配置的提供商 |
| `qxw-llm provider add` | ➕ 添加提供商 |
| `qxw-llm provider show` | 🔎 查看提供商详情 |
| `qxw-llm provider edit` | ✏️ 编辑提供商配置 |
| `qxw-llm provider delete` | 🗑 删除提供商 |
| `qxw-llm provider set-default` | ⭐ 设为默认提供商 |
| `qxw-llm provider ping` | 📡 测试指定提供商连接 |
| `qxw-llm provider ping-all` | 📡 测试所有提供商连接 |

## 项目结构

```
qxw/
├── bin/           # 命令入口
├── config/        # 配置集合
└── library/
    ├── base/      # 基础依赖、API Kit 封装
    ├── domain/    # 领域驱动层 (command/phrase/step)
    ├── models/    # ORM 映射层
    ├── managers/  # 管理器层
    └── services/  # 业务逻辑
```

## 文档

- [快速开始](docs/quick-start.md)
- [使用手册](docs/user-guide.md)
- [开发手册](docs/development.md)
- [运维手册](docs/operations.md)
- [FAQ](docs/faq.md)
- [规划文档](docs/planning.md)

## 许可证

MIT License
