# QXW 开发规范 (CLAUDE.md)

## 项目语言

- **本项目所有代码注释、文档、提交信息均使用中文**
- 变量名、函数名、类名使用英文，遵循 Python 命名规范

## 核心规则

### 代码与文档同步

> **每次改动代码都必须同步更新相应的文档。**

具体要求：
1. 新增命令：更新 `docs/user-guide.md`（使用手册）和 `docs/quick-start.md`（快速开始），同时新建 `skills/<命令名>/SKILL.md`
2. 修改配置：更新 `docs/operations.md`（运维手册），同时更新 `qxw/config/setting.json.example`
3. 修改 API/接口：更新 `docs/development.md`（开发手册）
4. 修复问题：如果是常见问题，更新 `docs/faq.md`
5. 新增功能规划：更新 `docs/planning.md`（规划文档）
6. 重大变更：更新 `README.md`
7. 修改命令子命令 / 参数 / 默认值 / 退出码：同步更新对应 `skills/<命令名>/SKILL.md`

### 目录结构规范

```
qxw/
├── bin/           # 命令入口 - 每个命令一个文件
├── config/        # 配置集合
├── library/
│   ├── base/      # 基础依赖、apikit 封装
│   ├── domain/    # 领域驱动层 (command/phrase/step)
│   ├── models/    # ORM 映射层 (SQLAlchemy)
│   ├── managers/  # 管理器层
│   └── services/  # 业务逻辑
skills/            # 给 LLM / Agent 触发用的 skill 文件，每个命令一个目录
└── <命令名>/SKILL.md
```

### 命令开发规范

1. **命令命名**: `qxw-xxx` 格式，避免与系统命令冲突
2. **入口文件**: 放在 `qxw/bin/` 目录下，每个命令一个独立文件
3. **注册命令**: 在 `pyproject.toml` 的 `[project.scripts]` 中注册
4. **Help 信息**: 每个命令必须包含完整的 `--help` 信息
5. **TUI 模式**: 使用 Textual 框架实现交互界面
6. **数据模型**: 使用 Pydantic 实体类进行强类型约束
7. **Skill 文件**: 每个命令必须在 `skills/<命令名>/SKILL.md` 提供对应的 skill，详见下文《Skill 规范》

### Skill 规范

> **每个 `qxw-*` 命令（含 `qxw` 主命令组）都必须在 `skills/` 下有对应的 `SKILL.md`，作为 LLM / Agent 的触发摘要。**

#### 目录与命名

```
skills/
├── README.md                  # 总览 + skill 与命令映射表，新增/删除命令时同步更新
├── qxw/SKILL.md               # 主命令组：list / hello / sbdqf / completion
├── qxw-llm/SKILL.md           # 一个命令一个目录，目录名 = 命令名
├── qxw-serve/SKILL.md
├── qxw-image/SKILL.md
├── qxw-markdown/SKILL.md
├── qxw-str/SKILL.md
├── qxw-math/SKILL.md
└── qxw-git/SKILL.md
```

- 目录名与 `pyproject.toml` 的 `[project.scripts]` 注册名严格一致
- 每个目录下入口文件固定叫 `SKILL.md`（大写），方便工具检索
- 如需附带脚本 / 参考文档，按 skill 通用约定放到同目录的 `scripts/` / `references/` / `assets/` 子目录

#### Frontmatter 必填字段

```markdown
---
name: <命令名>
description: <一句话讲做什么 + 子命令枚举 + 典型用户口语化触发短语 + 命令名直呼>
---
```

要点：
- `name` 与目录名一致
- `description` 必须**故意写得"够触发"**：除了能力描述，还要列举用户可能用的口语化说法（"把 RAW 转 JPG"、"算根号 2"、"局域网共享文件"等），并在末尾保留命令名直呼，方便用户直接念命令名时也能命中
- 单条 description 控制在 1500 字以内，超长会被工具截断

#### 正文结构（推荐顺序）

1. **子命令一览**（表格：子命令 / 用途）
2. **每个子命令的基本用法**（带 ` ```bash ` 代码块的真实命令示例）
3. **参数表**（参数 / 缩写 / 默认值 / 说明）
4. **关键行为约束**：默认值含义、自动行为、互斥参数、依赖
5. **退出码表**（如适用）：与命令实际退出码完全一致
6. **常见踩坑**：用户最容易踩的坑 + 修复指引

正文必须做到：**LLM 不查 docs 也能直接拼出可执行命令**，因此参数表与默认值要写死，不能留"详见手册"。

#### 与 `docs/` 的分工

- `docs/user-guide.md`：**给人读的**完整使用手册，强调结构与详尽
- `skills/<cmd>/SKILL.md`：**给 LLM 读的**触发摘要，强调描述里的触发短语 + 正文里的可执行命令
- 二者分歧时**以 `docs/` 为准**，skill 仅是它的可触发摘要；改动时优先改 `docs/`，再同步 skill

#### 维护规则

- **新增 `qxw-*` 命令** → 同时新建 `skills/<命令名>/SKILL.md`，并更新 `skills/README.md` 的映射表
- **新增子命令 / 参数 / 默认值变化** → 同步更新对应 SKILL.md 的子命令一览、参数表、示例
- **修改退出码 / 错误码** → 同步更新对应 SKILL.md 的退出码表
- **删除命令** → 删除对应 skill 目录，同步删除 `skills/README.md` 映射表中的行
- **修改命令名** → skill 目录、`name` frontmatter、映射表三处一起改

### 错误处理规范

1. 所有自定义异常继承自 `QxwError`
2. 命令入口必须捕获 `QxwError`、`KeyboardInterrupt` 和通用 `Exception`
3. 错误信息使用中文，面向用户友好展示

### 代码风格

- Python >= 3.10
- 使用 ruff 进行代码格式化和 lint
- 行宽限制 120 字符
- 使用 type hints

### 调试环境规范

- 调试命令必须在项目根目录下的 `.venv` 虚拟环境中运行
- 使用 Python 3.12 创建虚拟环境：`python3.12 -m venv .venv`
- 运行任何调试命令前必须先激活虚拟环境：`source .venv/bin/activate`

### 单元测试规范

> **每次改动代码都必须编写/更新相应的单元测试。**

核心原则：**0 happy test, 0 happy path**

- **禁止只写"正常流程"（happy path）测试**：仅验证"输入合法 → 输出符合预期"的用例没有价值，不算有效测试
- **必须覆盖异常与边界**：空值、None、空字符串、空列表、超长输入、越界、非法类型、并发冲突、外部依赖失败、事务回滚等
- **必须覆盖错误分支**：所有 `raise`、所有 `if/else` 的失败分支、所有自定义异常都要有对应用例
- **必须覆盖业务规则的反例**：权限不足、状态非法、幂等冲突、约束违反等
- 测试文件放在 `tests/` 目录下，结构镜像 `qxw/` 源码结构
- 使用 `pytest` 作为测试框架，测试需在 `.venv` 环境中运行
- 新增/修改命令、服务、管理器、领域逻辑时，PR 必须附带对应测试文件的变更
