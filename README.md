# QXW 命令行工具集合

QXW 是一个通用开发命令行工具集合，采用 Python 开发，提供 TUI（终端用户界面）交互体验。

## 特性

- 🛠️ 模块化命令设计，每个功能独立为 `qxw-xxx` 命令
- 🖥️ 基于 Textual 的 TUI 交互界面
- 📦 Pydantic 强类型数据校验
- 🗄️ SQLAlchemy ORM + SQLite 数据持久化
- 📝 完整的 `--help` 帮助信息

## 快速开始

### 环境要求

- Python >= 3.10
- pip
- pipx（推荐，用于全局安装）

### 安装

#### 方式一：pipx 全局安装（推荐）

使用 pipx 安装后命令全局可用，无需手动激活虚拟环境：

```bash
# 安装 pipx（如未安装）
brew install pipx    # macOS
# 或 pip install pipx

# 全局安装
pipx install .

# 更新（代码改动后重新安装）
pipx install . --force
```

#### 方式二：虚拟环境开发模式

```bash
python3 -m venv .venv
source .venv/bin/activate

# 安装（开发模式）
pip install -e .

# 安装开发依赖（可选）
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
| `qxw-hello` | 示例命令，验证安装是否成功 |
| `qxw-sbdqf` | 🐭 老鼠穿越动画，致敬经典 sl 命令 |
| `qxw-chat` | 🤖 AI 对话工具，支持 OpenAI / Anthropic 提供商 |
| `qxw-chat-provider` | ⚙️ AI 对话提供商管理（增删改查） |

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
