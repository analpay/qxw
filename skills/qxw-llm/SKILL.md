---
name: qxw-llm
description: 使用 `qxw-llm` 命令进行 AI 对话、管理 OpenAI / Anthropic 提供商配置、以及从 HuggingFace / ModelScope 拉取模型仓库文件。当用户说"和 GPT/Claude 聊天 / 用命令行调 LLM / 配置 OpenAI Key / 配置 Anthropic / 加一个 LLM 提供商 / 测一下 API key 通不通 / 切换默认模型 / 在终端跑 chat / 启动 LLM TUI / 从 HuggingFace 拉模型配置 / 跳过权重只拉 config 和 tokenizer / 从 ModelScope 下 Qwen / 拉 bert-base-chinese 的 config.json"，或者直接念到 `qxw-llm chat`、`qxw-llm provider add`、`qxw-llm provider ping`、`qxw-llm fetch`、`qxw-llm tui` 时，使用此 skill。
---

# qxw-llm

QXW 的 AI 对话工具集合，前身是 `qxw-chat` / `qxw-chat-provider`，现在以单命令组形式承载 chat / 提供商管理 / TUI / 模型仓库拉取。

## 子命令一览

| 子命令 | 用途 |
|--------|------|
| `qxw-llm chat` | 与已配置提供商对话（流式输出 / 单次模式 / 交互式） |
| `qxw-llm tui` | 提供商管理的 Textual TUI 界面 |
| `qxw-llm provider list / show / add / edit / delete / set-default / ping / ping-all` | 提供商 CRUD + 连接测试 |
| `qxw-llm fetch <repo> [patterns...]` | 从 HuggingFace / ModelScope 拉文件，支持 glob 与"跳过权重"模式 |

## provider：提供商管理

### add（添加）

仅支持 `openai` / `anthropic` 两种 type。所有数值字段会在写库前做 Pydantic 校验，越界 / 空字符串 / 非法类型会以 ValidationError 拒绝。

```bash
# OpenAI
qxw-llm provider add \
  --name my-openai \
  --type openai \
  --base-url https://api.openai.com/v1 \
  --api-key sk-your-key \
  --model gpt-4o \
  --default

# Anthropic
qxw-llm provider add \
  --name my-claude \
  --type anthropic \
  --base-url https://api.anthropic.com \
  --api-key sk-ant-your-key \
  --model claude-sonnet-4-20250514
```

| 参数 | 缩写 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `--name` | `-n` | 是 | - | 提供商名（唯一标识） |
| `--type` | - | 是 | - | `openai` / `anthropic` |
| `--base-url` | `-u` | 是 | - | API 基础地址 |
| `--api-key` | `-k` | 是 | - | API Key |
| `--model` | `-m` | 是 | - | 默认模型名 |
| `--temperature` | `-t` | 否 | 0.7 | 0.0–2.0 |
| `--max-tokens` | - | 否 | 4096 | 正整数 |
| `--top-p` | - | 否 | 1.0 | 0.0–1.0 |
| `--system-prompt` | `-s` | 否 | (空) | 默认系统提示词 |
| `--default` | - | 否 | false | 设为默认提供商 |

### 其它子命令

```bash
qxw-llm provider list                        # 列出全部
qxw-llm provider show my-openai              # 详情
qxw-llm provider edit my-openai -t 0.5 -s "你是一个 Python 专家"
qxw-llm provider delete my-openai            # 默认会确认；-y 跳过
qxw-llm provider set-default my-claude       # 切换默认
qxw-llm provider ping                        # 测默认提供商
qxw-llm provider ping my-openai              # 测指定提供商
qxw-llm provider ping-all                    # 全测一遍
```

### TUI 管理

```bash
qxw-llm tui
```

| 快捷键 | 功能 |
|--------|------|
| `A` | 添加提供商 |
| `E` / `Enter` | 编辑选中项 |
| `C` | 复制选中项 |
| `D` | 删除选中项 |
| `S` | 设为默认 |
| `Q` | 退出 |

## chat：对话

```bash
qxw-llm chat                                          # 默认提供商，交互式
qxw-llm chat --provider my-openai                     # 指定提供商
qxw-llm chat --model gpt-4o-mini --temperature 0.3    # 临时覆盖
qxw-llm chat -m "用 Python 写一个快速排序"            # 单次模式（发送即退出）
qxw-llm chat --system "你是一个 Python 专家"          # 临时系统提示词
```

| 参数 | 缩写 | 默认 | 说明 |
|------|------|------|------|
| `--provider` | `-p` | 默认提供商 | 指定提供商名 |
| `--model` | - | 提供商默认 | 临时覆盖模型 |
| `--temperature` | `-t` | 提供商默认 | 临时覆盖温度 |
| `--max-tokens` | - | 提供商默认 | 临时覆盖 max tokens |
| `--top-p` | - | 提供商默认 | 临时覆盖 top_p |
| `--system` | `-s` | 提供商默认 | 临时覆盖系统提示词 |
| `--message` | `-m` | - | 单次模式：发完一条退出 |

交互式模式内部命令：`/exit` 退出、`/clear` 清上下文、`Ctrl+C` 退出。

## fetch：从 HuggingFace / ModelScope 拉文件

底层直接调用官方 SDK 的 `snapshot_download`，重点是支持 **"跳过权重"模式**（不传 patterns）和 **glob 白名单模式**（传 patterns）。

```bash
# 不传 patterns → 跳过权重，拉其余所有文件（config / 代码 / tokenizer / license / README）
qxw-llm fetch bert-base-chinese

# 传 patterns → 只拉命中的文件（默认 HF 源，输出到 ./$org/$name/）
qxw-llm fetch bert-base-chinese config.json tokenizer.json
qxw-llm fetch Qwen/Qwen2-7B 'configuration_*.py' 'tokenizer*.json'

# 切到 ModelScope
qxw-llm fetch Qwen/Qwen2-7B 'configuration_*.py' --source modelscope

# 指定 revision + 输出目录 + 私有仓库 token
qxw-llm fetch org/repo '*.json' --revision v1.0 --output ./weights --token <hf_token>
```

| 参数 | 缩写 | 默认 | 说明 |
|------|------|------|------|
| `REPO` | - | - | `org/name`，必填 |
| `PATTERNS…` | - | （跳过权重） | 文件名 / glob，可重复；非空时透传为 SDK 的 `allow_patterns` |
| `--source` | `-s` | `huggingface` | `huggingface` / `modelscope` |
| `--revision` | `-r` | SDK 默认 | 分支 / tag / commit；HF=`main`，MS=`master` |
| `--output` | `-o` | `./$org/$name` | 输出目录（保留仓库内相对路径） |
| `--token` | `-k` | (无) | 私有仓库 token |

### "跳过权重"模式忽略列表

未指定 patterns 时，以下后缀被作为 SDK 的 `ignore_patterns`：

```
*.safetensors  *.safetensors.index.json
*.bin  *.pt  *.pth  *.ckpt
*.h5  *.npz  *.onnx  *.gguf
*.zip  *.tar  *.tar.gz
```

无论哪种模式，**最终命中文件数为 0 时整个调用以错误退出**，避免静默不下载。

### 退出码

| 退出码 | 触发场景 |
|--------|----------|
| 4 | 仓库 / revision 不存在；命令错误 |
| 5 | SDK 内部 HTTP 错误 |
| 6 | `org/name` 格式非法 / patterns 含 `..` 越界 / 其它 ValidationError |

### 依赖

- HF 来源 → `pip install huggingface_hub`
- MS 来源 → `pip install modelscope`

依赖缺失时命令会以错误退出，并打印精确的 `pip install` 提示。

## 注意事项

- **Key 不要写在命令行历史里**：长期使用更建议 `qxw-llm provider add` 一次落库，或用 `qxw-llm provider edit --api-key ...`，避免裸 `qxw-llm chat --api-key ...` 这种用法（实际上 chat 也不接受 `--api-key`）。
- **加完提供商先 `ping` 一次**：`provider ping` 会真实发一次最小请求；很多 base-url / Key 拼错都能在这里被立刻发现，免得到 chat 里才报错。
- **同时配多个提供商**：`set-default` 切换默认，`chat -p <name>` 一次性指定不影响默认。
