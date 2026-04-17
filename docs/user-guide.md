# 使用手册

本文档介绍 QXW 工具集所有命令的详细用法。

## 命令概览

| 命令 | 说明 | 状态 |
|------|------|------|
| `qxw-hello` | 示例命令，验证安装 | ✅ 可用 |
| `qxw-sbdqf` | 老鼠穿越动画（致敬 sl 命令） | ✅ 可用 |
| `qxw-chat` | AI 对话工具 | ✅ 可用 |
| `qxw-chat-provider` | AI 对话提供商管理 | ✅ 可用 |

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
