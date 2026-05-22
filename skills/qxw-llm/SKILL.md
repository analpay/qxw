---
name: qxw-llm
description: 使用 `qxw-llm` 命令进行 AI 对话、管理 OpenAI / Anthropic 提供商配置、从 HuggingFace / ModelScope 拉取模型仓库文件，以及启动一个 OpenAI 兼容的 Mock LLM Web 服务用于本地联调 / 压测（可配置 TTFT / TPOT / chunk 分布 / 按请求内容路由的多 profile 规则）。当用户说"和 GPT/Claude 聊天 / 用命令行调 LLM / 配置 OpenAI Key / 配置 Anthropic / 加一个 LLM 提供商 / 测一下 API key 通不通 / 切换默认模型 / 在终端跑 chat / 启动 LLM TUI / 从 HuggingFace 拉模型配置 / 跳过权重只拉 config 和 tokenizer / 从 ModelScope 下 Qwen / 拉 bert-base-chinese 的 config.json / 启动一个假的 OpenAI 接口 / mock 一个 chat completions / 跑一个本地 LLM 假服务 / 模拟 2 秒 TTFT 的 SSE 流 / openai 兼容的 mock 服务器 / 测一下客户端的 SSE 解析 / 根据 model 名返回不同 mock / 不同 prompt 返回不同延迟 / 模拟随机分块的 SSE / 生成 mock 配置文件 / mock-config 示例"，或者直接念到 `qxw-llm chat`、`qxw-llm provider add`、`qxw-llm provider ping`、`qxw-llm fetch`、`qxw-llm tui`、`qxw-llm mock`、`qxw-llm mock-config` 时，使用此 skill。
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
| `qxw-llm mock` | 启动 OpenAI 兼容的 Mock LLM Web 服务（可配置 TTFT/TPOT/chunk 分布 + 按请求内容路由的规则） |
| `qxw-llm mock-config` | 打印 / 导出 mock 服务的示例配置 JSON（带规则与 chunk 分布示例） |

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

## mock：OpenAI 兼容的 Mock LLM Web 服务

启动一个本地 HTTP 服务，模拟 OpenAI `Chat Completions` / `Responses` 接口，**不调用任何真实模型**，按可配置的 `TTFT`（首 token 延迟）和 `TPOT`（token 间间隔）节奏返回预置占位 token，专门用于：

- 客户端联调（SSE 解析、超时、断流恢复）
- 网关 / 代理压测
- CI 环境提供稳定的"假"上游

### 启动

```bash
# 默认：127.0.0.1:8080，TTFT=2000ms，TPOT=15ms，tokens=64
qxw-llm mock

# 局域网访问 + 自定义端口
qxw-llm mock -H 0.0.0.0 -p 9000

# 客户端压测：把节奏调快
qxw-llm mock --ttft 200 --tpot 5

# 输出更长 / 自定义 model 字段
qxw-llm mock --tokens 256 --model my-mock
```

### 接口（同时兼容 `/api` 前缀）

| 方法 + 路径 | 行为 |
|------|------|
| `POST /v1/chat/completions` | OpenAI Chat Completions，`stream=true` 时 SSE，`stream=false` 时一次性返回 |
| `POST /v1/responses` | OpenAI Responses API，`stream=true` 时按 `response.*` 事件流式输出 |
| `GET /v1/models` | 列出 mock 模型（id = `--model` 指定的值） |
| `GET /health` | 健康检查 |
| `GET /` | 服务元信息（含当前 TTFT / TPOT / tokens / model） |
| `OPTIONS *` | CORS 预检（`Access-Control-Allow-Origin: *`） |

### 参数

| 参数 | 缩写 | 默认 | 说明 |
|------|------|------|------|
| `--host` | `-H` | `127.0.0.1` | 监听地址 |
| `--port` | `-p` | `8080` | 监听端口（0–65535） |
| `--ttft` | - | `2000` | 首 token 延迟（毫秒，0–600000） |
| `--tpot` | - | `15` | 相邻 token 间延迟（毫秒，0–600000） |
| `--tokens` | `-n` | `64` | 单次响应的 token 数（1–100000） |
| `--chunk-min` | - | `1` | 单个 SSE 事件包含的最少 token 数 |
| `--chunk-max` | - | `1` | 单个 SSE 事件包含的最多 token 数（>= chunk-min） |
| `--model` | - | `qxw-mock-1` | 返回的 `model` 字段值 |
| `--config` | `-c` | (无) | JSON 配置文件路径；提供时上面所有节奏字段被忽略 |

> 命令行参数与 `--config` 互斥：传 `--config` 时一切节奏 / 规则都从文件取，CLI flag 仅 host / port / model 仍可生效作为横幅展示（实际监听值以最终的 config 为准）。

### 时间模型 & chunk 分布

- **流式**：sleep `TTFT` → 写 role chunk → 按 `[chunk_min, chunk_max]` 随机分组 tokens；
  组 0 之前再 sleep `(K[0]-1)*TPOT`，之后每组之前 sleep `K[i]*TPOT` → 写 stop chunk → `[DONE]`
- **非流式**：sleep `TTFT + (N - 1) * TPOT` → 一次性返回 JSON
- **核心不变量**：chunk 分布只改变事件粒度（SSE 事件个数），**总耗时永远等于 `TTFT + (N-1)*TPOT`**

### 按请求路由（`--config`）

通过 `-c <file>` 加载 JSON 配置文件后，可基于以下"标识"把请求路由到不同 profile：

| 标识字段 | 含义 |
|----------|------|
| `model` | 精确匹配请求体的 `model` 字段 |
| `content_contains` | 用户消息文本含某子串（取自 `messages[*].content` / multi-modal 的 `text` part / `input` / `prompt`） |
| `content_regex` | 用户消息文本匹配正则（`re.search` 语义） |
| `header_name` | 请求头存在（大小写不敏感）；与 `header_value` 组合做精确匹配 |

> 同一规则的多个标识做 **AND**；规则按 `rules` 列表顺序匹配，**首个命中即生效**；未命中走 `default`。

配置文件结构：

```json
{
    "host": "127.0.0.1",
    "port": 8080,
    "model": "qxw-mock-1",
    "default": {
        "ttft_ms": 2000, "tpot_ms": 15, "tokens": 64,
        "chunk_min": 1, "chunk_max": 1
    },
    "rules": [
        {"name": "slow-model",       "match": {"model": "slow-gpt"},                       "ttft_ms": 5000, "tokens": 200},
        {"name": "essay-by-content", "match": {"content_contains": "写一篇"},               "tokens": 512},
        {"name": "translate-regex",  "match": {"content_regex": "(?i)\\btranslate\\b|翻译"}, "ttft_ms": 1000},
        {"name": "burst-by-header",  "match": {"header_name": "X-Mock-Profile", "header_value": "burst"}, "chunk_min": 3, "chunk_max": 8},
        {"name": "any-debug-header", "match": {"header_name": "X-Debug"},                  "ttft_ms": 0, "tpot_ms": 0, "tokens": 4}
    ]
}
```

每条 rule 的 profile 字段（`ttft_ms` / `tpot_ms` / `tokens` / `chunk_min` / `chunk_max`）**都是可选的**，未指定则继承 `default`。

直接生成可改的示例文件：

```bash
qxw-llm mock-config > mock.json        # 打印到 stdout 再重定向
qxw-llm mock-config -o mock.json       # 直接写入（已存在拒绝）
qxw-llm mock-config -o mock.json -f    # 强制覆盖
```

### 客户端示例

```bash
# OpenAI Python SDK 直接指向 mock 服务
OPENAI_BASE_URL=http://127.0.0.1:8080/v1 OPENAI_API_KEY=anything \
  python -c "from openai import OpenAI; c=OpenAI(); print(c.chat.completions.create(model='m', messages=[{'role':'user','content':'hi'}]).choices[0].message.content)"

# 直接用 curl 验证 SSE
curl -N http://127.0.0.1:8080/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"m","messages":[{"role":"user","content":"hi"}],"stream":true}'
```

### 退出码

| 退出码 | 触发场景 |
|--------|----------|
| 0 | `Ctrl+C` 正常停止 |
| 1 | 端口占用 / 未预期错误 |
| QxwError.exit_code | 内部业务异常透传（一般遇不到） |

### 注意事项

- mock 服务**不做 token 鉴权**，监听 `0.0.0.0` 时请确保仅暴露在可信网络
- 占位 token 由固定 token 池循环生成，相同 `--tokens` 总是返回相同文本，便于断言
- TTFT / TPOT 用 `time.sleep` 实现；超低延迟（<1ms）的压测建议直接用其他专用工具

## 注意事项

- **Key 不要写在命令行历史里**：长期使用更建议 `qxw-llm provider add` 一次落库，或用 `qxw-llm provider edit --api-key ...`，避免裸 `qxw-llm chat --api-key ...` 这种用法（实际上 chat 也不接受 `--api-key`）。
- **加完提供商先 `ping` 一次**：`provider ping` 会真实发一次最小请求；很多 base-url / Key 拼错都能在这里被立刻发现，免得到 chat 里才报错。
- **同时配多个提供商**：`set-default` 切换默认，`chat -p <name>` 一次性指定不影响默认。
