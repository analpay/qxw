"""qxw-hello 命令入口

一个示例命令，展示 QXW 工具集的标准开发模式。
使用 Click 处理命令行参数，使用 Textual 实现 TUI 界面。

用法:
    qxw-hello          # 纯命令行模式输出（默认）
    qxw-hello --tui    # 启动 TUI 界面
    qxw-hello --help   # 查看帮助信息
"""

import sys

import click
from pydantic import BaseModel, Field
from textual.app import App, ComposeResult
from textual.containers import Center, Vertical
from textual.widgets import Footer, Header, Static

from qxw import __version__
from qxw.library.base.exceptions import QxwError
from qxw.library.base.logger import get_logger

logger = get_logger("qxw.hello")


# ============================================================
# 数据模型 (Pydantic)
# ============================================================


class HelloConfig(BaseModel):
    """Hello 命令的配置模型"""

    name: str = Field(default="世界", description="问候对象的名称")
    version: str = Field(default=__version__, description="当前版本号")
    tui_mode: bool = Field(default=False, description="是否使用 TUI 模式")


# ============================================================
# TUI 界面 (Textual)
# ============================================================


class HelloApp(App):
    """Hello World TUI 应用"""

    TITLE = "QXW Hello"
    SUB_TITLE = f"v{__version__}"
    CSS = """
    Screen {
        align: center middle;
    }

    #hello-container {
        width: 60;
        height: auto;
        border: round $accent;
        padding: 2 4;
    }

    #title-text {
        text-align: center;
        text-style: bold;
        color: $text;
        margin-bottom: 1;
    }

    #greeting-text {
        text-align: center;
        color: $accent;
        margin-bottom: 1;
    }

    #info-text {
        text-align: center;
        color: $text-muted;
    }
    """

    BINDINGS = [
        ("q", "quit", "退出"),
        ("d", "toggle_dark", "切换主题"),
    ]

    def __init__(self, config: HelloConfig) -> None:
        super().__init__()
        self.config = config

    def compose(self) -> ComposeResult:
        """构建 TUI 界面"""
        yield Header()
        with Center():
            with Vertical(id="hello-container"):
                yield Static("🛠️  QXW 命令行工具集合", id="title-text")
                yield Static(
                    f"你好, {self.config.name}！",
                    id="greeting-text",
                )
                yield Static(
                    f"版本: {self.config.version}  |  按 Q 退出  |  按 D 切换主题",
                    id="info-text",
                )
        yield Footer()

    def action_toggle_dark(self) -> None:
        """切换暗色/亮色主题"""
        self.theme = (
            "textual-dark" if self.theme == "textual-light" else "textual-light"
        )


# ============================================================
# CLI 入口 (Click)
# ============================================================


@click.command(
    name="qxw-hello",
    help="QXW 工具集示例命令 - Hello World",
    epilog="这是 QXW 命令行工具集合的示例命令，用于验证安装是否成功。",
)
@click.option(
    "--name",
    "-n",
    default="世界",
    show_default=True,
    help="问候对象的名称",
)
@click.option(
    "--tui",
    is_flag=True,
    default=False,
    help="启用 TUI 模式，使用终端交互界面",
)
@click.version_option(
    version=__version__,
    prog_name="qxw-hello",
    message="%(prog)s 版本 %(version)s",
)
def main(name: str, tui: bool) -> None:
    """QXW 工具集示例命令

    启动一个 Hello World 命令，用于验证 QXW 工具集安装是否正确。

    \b
    示例:
        qxw-hello              # 默认命令行输出
        qxw-hello --name 开发者  # 自定义问候名称
        qxw-hello --tui        # TUI 交互模式
    """
    try:
        # 检测并初始化运行环境
        _ensure_env()

        config = HelloConfig(name=name, tui_mode=tui)
        logger.info("启动 qxw-hello 命令, name=%s, tui=%s", name, config.tui_mode)

        if config.tui_mode:
            app = HelloApp(config)
            app.run()
        else:
            click.echo(f"🛠️  QXW 命令行工具集合 v{__version__}")
            click.echo(f"你好, {config.name}！")
            click.echo("安装验证成功 ✅")

    except QxwError as e:
        logger.error("命令执行失败: %s", e.message)
        click.echo(f"错误: {e.message}", err=True)
        sys.exit(e.exit_code)
    except KeyboardInterrupt:
        click.echo("\n操作已取消")
        sys.exit(130)
    except Exception as e:
        logger.exception("未预期的错误")
        click.echo(f"未预期的错误: {e}", err=True)
        sys.exit(1)


def _ensure_env() -> None:
    """检测运行环境，未初始化时自动执行初始化"""
    from qxw.config.init import check_env, init_env

    status = check_env()
    if status.all_ready:
        return

    click.echo("检测到运行环境未完成初始化，正在自动初始化...")
    result = init_env()
    for item in result.initialized_items:
        click.echo(f"  已初始化: {item}")
    click.echo("环境初始化完成\n")


if __name__ == "__main__":
    main()
