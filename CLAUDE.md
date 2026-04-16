# QXW 开发规范 (CLAUDE.md)

## 项目语言

- **本项目所有代码注释、文档、提交信息均使用中文**
- 变量名、函数名、类名使用英文，遵循 Python 命名规范

## 核心规则

### 代码与文档同步

> **每次改动代码都必须同步更新相应的文档。**

具体要求：
1. 新增命令：更新 `docs/user-guide.md`（使用手册）和 `docs/quick-start.md`（快速开始）
2. 修改配置：更新 `docs/operations.md`（运维手册），同时更新 `qxw/config/setting.json.example`
3. 修改 API/接口：更新 `docs/development.md`（开发手册）
4. 修复问题：如果是常见问题，更新 `docs/faq.md`
5. 新增功能规划：更新 `docs/planning.md`（规划文档）
6. 重大变更：更新 `README.md`

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
```

### 命令开发规范

1. **命令命名**: `qxw-xxx` 格式，避免与系统命令冲突
2. **入口文件**: 放在 `qxw/bin/` 目录下，每个命令一个独立文件
3. **注册命令**: 在 `pyproject.toml` 的 `[project.scripts]` 中注册
4. **Help 信息**: 每个命令必须包含完整的 `--help` 信息
5. **TUI 模式**: 使用 Textual 框架实现交互界面
6. **数据模型**: 使用 Pydantic 实体类进行强类型约束

### 错误处理规范

1. 所有自定义异常继承自 `QxwError`
2. 命令入口必须捕获 `QxwError`、`KeyboardInterrupt` 和通用 `Exception`
3. 错误信息使用中文，面向用户友好展示

### 代码风格

- Python >= 3.10
- 使用 ruff 进行代码格式化和 lint
- 行宽限制 120 字符
- 使用 type hints
