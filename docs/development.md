# 开发手册

本文档面向 QXW 工具集的开发者，介绍如何开发新命令和扩展功能。

## 开发环境搭建

```bash
# 安装开发依赖
pip install -e ".[dev]"
```

## 项目架构

```
qxw/
├── bin/           # 命令入口 - 每个命令一个独立文件
├── config/        # 配置集合 - 全局配置管理
└── library/
    ├── base/      # 基础依赖、异常定义、日志、API Kit 封装
    ├── domain/    # 领域驱动层
    │   ├── command/   # 命令层
    │   ├── phrase/    # 阶段层
    │   └── step/      # 步骤层
    ├── models/    # ORM 映射层 (SQLAlchemy)
    ├── managers/  # 管理器层
    └── services/  # 业务逻辑
```

## 新增命令步骤

### 1. 创建命令入口文件

在 `qxw/bin/` 下创建新文件，例如 `qxw/bin/mycommand.py`：

```python
"""qxw-mycommand 命令入口

命令说明...
"""

import sys
import click
from pydantic import BaseModel, Field
from textual.app import App, ComposeResult

from qxw.library.base.exceptions import QxwError
from qxw.library.base.logger import get_logger

logger = get_logger("qxw.mycommand")


class MyCommandConfig(BaseModel):
    """命令配置模型 (Pydantic 强类型)"""
    param1: str = Field(default="默认值", description="参数说明")


class MyCommandApp(App):
    """TUI 应用"""
    # ... Textual TUI 实现


@click.command(name="qxw-mycommand", help="命令说明")
@click.option("--param1", "-p", default="默认值", help="参数说明")
def main(param1: str) -> None:
    """命令主函数"""
    try:
        config = MyCommandConfig(param1=param1)
        app = MyCommandApp(config)
        app.run()
    except QxwError as e:
        click.echo(f"错误: {e.message}", err=True)
        sys.exit(e.exit_code)
    except KeyboardInterrupt:
        click.echo("\n操作已取消")
        sys.exit(130)
    except Exception as e:
        logger.exception("未预期的错误")
        click.echo(f"未预期的错误: {e}", err=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
```

### 2. 注册命令

在 `pyproject.toml` 的 `[project.scripts]` 中添加：

```toml
[project.scripts]
qxw-mycommand = "qxw.bin.mycommand:main"
```

### 3. 重新安装

```bash
pip install -e .
```

### 4. 更新文档

> ⚠️ 每次改动代码都必须同步更新相应的文档！

- 更新 `docs/user-guide.md` 添加新命令说明
- 更新 `docs/quick-start.md` 如有必要
- 更新 `README.md` 命令列表

## 数据模型规范

所有数据结构体使用 Pydantic 实体类进行强类型约束：

```python
from pydantic import BaseModel, Field

class MyModel(BaseModel):
    name: str = Field(..., description="名称")
    count: int = Field(default=0, ge=0, description="计数")
```

## 错误处理规范

所有自定义异常继承自 `QxwError`：

```python
from qxw.library.base.exceptions import QxwError, CommandError

# 抛出命令错误
raise CommandError("参数格式不正确")
```

## 代码风格

- 使用 ruff 进行代码检查: `ruff check qxw/`
- 使用 ruff 进行格式化: `ruff format qxw/`
- 使用 mypy 进行类型检查: `mypy qxw/`
