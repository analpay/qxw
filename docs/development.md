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
        ├── serve_gitbook.py   # qxw-serve gitbook 后端
        ├── serve_webtool.py   # qxw-serve webtool 后端
        ├── serve_file.py      # qxw-serve file-web 后端
        ├── serve_image.py     # qxw-serve image-web 后端
        ├── summary_service.py # qxw-markdown summary 目录生成
        └── ...                # image_service / markdown_service / ...
```

### qxw-serve 组织方式

`qxw-serve` 是多个 HTTP 服务的统一入口，`qxw/bin/serve.py` 只负责 Click 子命令注册和打印启动信息，每个服务的 HTML 模板、请求处理器、配置模型都放到 `qxw/library/services/serve_*.py` 下；`serve.py` 在子命令函数内部 `import` 对应模块，`start_server(config)` 启动。新增 `qxw-serve <name>` 子命令时，按此模式新建 `serve_<name>.py`、在 `serve.py` 中注册子命令即可，不要把 HTML/handler 直接塞进 `bin/`。

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

### 两个使用入口

相同的滤镜注册中心被两个 CLI 入口共享：

| 入口 | 解码路径 | Service 函数 | 适用场景 |
|------|----------|--------------|----------|
| `qxw-image raw --filter <name>` | rawpy（解码 + 调色 + JPEG 一次成型） | `convert_raw(color_filter=...)` | 直接从 RAW 出成片，画质最佳 |
| `qxw-image filter -n <name>` | PIL（位图解码 + 调色 + JPEG 重编码） | `apply_filter_to_image(...)` | 对已导出 JPG / 截图 / 手机图批量再调色 |

相关代码：
- 注册中心与内置 `fuji-cc` / `ghibli`：`qxw/library/services/color_filters.py`
- RAW 单遍路径：`qxw/library/services/image_service.py` `convert_raw()`
- 位图路径：`qxw/library/services/image_service.py` `apply_filter_to_image()` + `scan_filterable_images()`
- CLI：`qxw/bin/image.py` `raw_command()`（`--filter` 与 `--use-embedded` 互斥检查）与 `filter_command()`（`--list` / 递归时避免把滤镜叠加到自己身上的防呆）

## 单元测试

项目使用 `pytest` 作为测试框架，测试代码位于 `tests/` 目录。

### 运行测试

```bash
# 先激活虚拟环境
source .venv/bin/activate

# 安装开发依赖（首次）
pip install -e ".[dev]"

# 跑全部测试
pytest

# 单文件 / 单用例
pytest tests/test_chat_provider_manager.py
pytest tests/test_exceptions.py::TestQxwError::test_默认退出码为_1

# 带覆盖率
pytest --cov=qxw --cov-report=term-missing
```

pytest 配置在 `pyproject.toml` 的 `[tool.pytest.ini_options]`，默认读取 `tests/` 目录下的 `test_*.py`。

### 测试目录结构

```
tests/
├── conftest.py                        # 全局 fixtures（HOME 隔离、内存数据库）
├── test_exceptions.py                 # QxwError 及子类
├── test_settings.py                   # 配置加载（默认 / JSON / 环境变量）
├── test_init.py                       # 环境初始化 check_env / init_env
├── test_chat_provider_manager.py      # ChatProvider CRUD（in-memory sqlite）
├── test_color_filters.py              # 调色滤镜注册中心
├── test_markdown_service.py           # PlantUML 围栏提取 / SVG 注入等纯函数
└── test_str_cmd.py                    # qxw-str 命令（click CliRunner）
```

### 编写新测试的约定

1. **用例 / 类 / 文件命名**：`test_*.py` / `Test*` / `test_*`；中文函数名可用于描述具体行为。
2. **隔离 HOME**：`conftest.py` 中的 `_isolated_home` fixture 会把 `$HOME` 以及 `QXW_CONFIG_DIR` / `QXW_LOG_DIR` / `QXW_DB_URL` 指向 `tmp_path`，避免测试污染用户真实 `~/.config/qxw/`。注意：`AppSettings` 中的 `Path.home()` 默认值是在模块导入时冻结的，因此必须靠 `QXW_*` 环境变量覆盖，而不能只改 `HOME`。
3. **隔离数据库**：需要访问 `ChatProvider` 等 ORM 的用例使用 `in_memory_db` fixture。它基于 `sqlite://` + `StaticPool` 创建共享连接，并 monkeypatch 掉 `qxw.library.models.base.get_db_session` 和 `qxw.library.managers.chat_provider_manager.get_db_session` 两处引用。
4. **单例复位**：`_reset_settings_singleton` 在每个用例前后清空 `qxw.config.settings._settings`，确保环境变量改动能被下一次 `get_settings()` 看到。
5. **CLI 测试**：使用 `click.testing.CliRunner.invoke(main, args, input=stdin)` 而非真 subprocess，速度更快、更易断言。
6. **不触发外部进程**：`markdown_service` 仅测试纯函数（围栏提取 / 背景注入 / skinparam 生成），不跑 `java -jar plantuml.jar`。图片服务中依赖 `cairosvg` / `rawpy` 的路径同理暂不覆盖。
