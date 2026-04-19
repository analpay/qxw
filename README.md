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
# 查看帮助
qxw-hello --help

# 运行示例命令（默认命令行模式）
qxw-hello

# TUI 交互模式
qxw-hello --tui

# 自定义问候
qxw-hello --name 开发者
```

## 命令列表

| 命令 | 说明 |
|------|------|
| `qxw` | 📋 列出所有可用命令 |
| `qxw-hello` | 示例命令，验证安装是否成功 |
| `qxw-sbdqf` | 🐭 老鼠穿越动画，致敬经典 sl 命令 |
| `qxw-chat` | 🤖 AI 对话工具，支持 OpenAI / Anthropic 提供商 |
| `qxw-chat-provider` | ⚙️ AI 对话提供商管理（增删改查） |
| `qxw-gitbook` | 📖 Markdown 文档工具（PDF 转换 / 本地预览） |
| `qxw-webtool` | 🧰 开发者 Web 工具集（文本对比 / JSON / 时间戳 / 加解密 / 编解码） |
| `qxw-file-server` | 📂 文件服务器（HTTP / FTP 文件共享，支持鉴权） |
| `qxw-image` | 📷 图片工具集（HTTP 图片浏览 / RAW 批量转 JPG） |

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
