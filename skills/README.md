# QXW Skills

本目录把 QXW 工具集的所有命令封装成 Claude / Agent 可调用的 skill。每个 skill 都对应一个 `qxw-*` 命令（或 `qxw` 主命令组），用于在 LLM 触发对应任务时快速找到正确的命令、参数与常见踩坑点。

## 目录结构

```
skills/
├── qxw/SKILL.md          # 主命令组：list / hello / sbdqf / completion
├── qxw-llm/SKILL.md      # AI 对话 / 提供商管理 / HF & MS 拉取
├── qxw-serve/SKILL.md    # gitbook / webtool / file-web / image-web HTTP 服务
├── qxw-image/SKILL.md    # raw / svg / filter / change / clear 图片处理
├── qxw-markdown/SKILL.md # wx / cover / summary Markdown 工具
├── qxw-str/SKILL.md      # 字符串长度统计
├── qxw-math/SKILL.md     # 安全的数学表达式计算
└── qxw-git/SKILL.md      # git 仓库打包（含 LFS 实体化）
```

## Skill 与命令映射

| Skill | 对应命令 | 主要触发场景 |
|-------|---------|------------|
| `qxw` | `qxw list / hello / sbdqf / completion` | 列出全部命令、初始化配置目录、安装 zsh / bash 补全 |
| `qxw-llm` | `qxw-llm chat / tui / provider / fetch` | 终端 AI 对话、配置 OpenAI / Anthropic Key、从 HuggingFace / ModelScope 拉模型 |
| `qxw-serve` | `qxw-serve gitbook / webtool / file-web / image-web` | 本地预览 Markdown、开发者 Web 工具集、文件共享、图片画廊 |
| `qxw-image` | `qxw-image raw / svg / filter / change / clear` | RAW 转 JPG、SVG 转 PNG、调色滤镜、自动亮度对比饱和、擦除元数据 |
| `qxw-markdown` | `qxw-markdown wx / cover / summary` | PlantUML 渲染 + 公众号适配、Gemini 生成封面、Gitbook 目录树 |
| `qxw-str` | `qxw-str len` | 字符数 / UTF-8 字节数统计 |
| `qxw-math` | `qxw-math` | 终端安全求值（不用 `eval`） |
| `qxw-git` | `qxw-git archive` | git 仓库打包（不含 .git，自动 LFS pull） |

## 描述规范

每个 SKILL.md 的 frontmatter 描述都遵循同一套写法：

1. **第一句话讲做什么**：把命令的核心价值一句话说清
2. **关键能力 / 子命令枚举**：方便 LLM 在用户语义和命令之间建立映射
3. **典型触发短语**：列举用户可能用的口语化说法（"把 RAW 转成 JPG"、"局域网共享文件"、"算根号 2" 等）
4. **直接命令名提示**：当用户直接念到命令名（`qxw-image raw` / `qxw-llm chat` / `qxw-git archive` 等）时也要触发

这样写的目的是让 skill 在用户使用模糊的口语描述、或直接说命令名时都能可靠触发，避免"明明有这个命令，agent 却没用上"的情况。

## 维护规则

新增或修改命令时同步更新对应 skill：

- **新增 `qxw-*` 命令** → 在本目录新建 `<命令名>/SKILL.md`，并把它加进上面的"映射表"和顶层 `README.md`
- **新增子命令 / 参数** → 同步更新对应 skill 的"子命令一览"与"参数"表
- **删除命令** → 删除对应 skill 目录，同步删除映射表中的行
- **修改语义 / 默认值** → 更新 SKILL.md 正文与示例

每次改完 skill 都顺手 `qxw completion install -y` 重生成 shell 补全，确保 skill 文档与实际命令行为一致。

## 触发口径与项目文档的关系

- `docs/user-guide.md` 是**给人读的**完整使用手册，强调结构和详尽
- `skills/<cmd>/SKILL.md` 是**给 LLM 读的**触发手册，强调描述里写满触发短语 + 正文里写死参数与默认值，方便 LLM 直接拼出可执行命令

两份文档都需要保持同步；当二者出现分歧时，**以 `docs/` 下的手册为准**——skill 仅是它的可触发摘要。
