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

## 扩展：调色滤镜插件（qxw-image raw --filter）

`qxw/library/services/color_filters.py` 提供了一个极简的插件注册中心，用于扩展 `qxw-image raw` 的调色能力。

### 约定

- 滤镜是一个函数：`(rgb: np.ndarray) -> np.ndarray`
- 输入 / 输出均为 `uint8` RGB 三通道数组，形状 `(H, W, 3)`
- 保留名 `default` 表示"不调色"，不可占用

### 公共 API

```python
from qxw.library.services.color_filters import (
    register_filter,   # 装饰器：注册一个滤镜
    list_filters,      # 返回所有可选名（含 default），按字母序
    get_filter,        # 按名称查函数（default 或未知名返回 None）
    apply_filter,      # 按名称对数组套用滤镜（default 时原样返回）
    DEFAULT_FILTER_NAME,  # = "default"
)
```

### 注册示例

```python
import numpy as np
from qxw.library.services.color_filters import register_filter


@register_filter("warm-sunset")
def _warm_sunset(rgb: np.ndarray) -> np.ndarray:
    arr = rgb.astype(np.float32) / 255.0
    # 抬红降蓝，制造落日感
    arr[..., 0] = np.clip(arr[..., 0] * 1.08, 0, 1)
    arr[..., 2] = np.clip(arr[..., 2] * 0.92, 0, 1)
    return np.clip(arr * 255.0, 0, 255).astype(np.uint8)
```

只要在 `qxw-image raw` 执行前（通常由 Python 包的 `__init__.py` 或一个在启动路径上的模块 import 触发）完成注册，`--filter warm-sunset` 就会被命令识别；非法名会在命令入口处被 `click.BadParameter` 拦截，并列出当前可用的滤镜名。

### CLI 与 `--use-embedded` 的交互

- `--filter default`：保持历史行为，对 `--use-embedded / --no-use-embedded` 无任何影响。
- `--filter <非 default>`：调色需要拿到解码后的像素，嵌入预览路径（原字节直写）无法套用，因此：
  - 自动切换到 `--no-use-embedded`
  - 若用户显式传入 `--use-embedded`，CLI 以 `click.UsageError` 终止（退出码 2），避免静默覆盖用户意图

相关代码：
- 注册中心与内置 `fuji-cc`：`qxw/library/services/color_filters.py`
- 调用点（解码后 → 滤镜 → 保存 JPEG）：`qxw/library/services/image_service.py` `convert_raw()`
- CLI 参数校验与互斥检查：`qxw/bin/image.py` `raw_command()`
