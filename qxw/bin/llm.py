"""qxw-llm 命令入口

QXW AI 对话工具统一入口（合并自 qxw-chat / qxw-chat-provider）。

用法:
    qxw-llm chat                      # 与默认提供商进行交互式对话
    qxw-llm chat --provider <name>    # 指定提供商对话
    qxw-llm chat -m "你好"            # 单次对话
    qxw-llm provider list             # 列出提供商
    qxw-llm provider add ...          # 添加提供商
    qxw-llm provider show <name>      # 查看提供商详情
    qxw-llm provider edit <name>      # 编辑提供商
    qxw-llm provider delete <name>    # 删除提供商
    qxw-llm provider set-default <n>  # 设为默认提供商
    qxw-llm provider ping [name]      # 测试提供商连接
    qxw-llm provider ping-all         # 测试全部提供商连接
    qxw-llm tui                       # 提供商 TUI 管理界面
    qxw-llm fetch <repo> <files...>   # 从 HF / ModelScope 拉取仓库文件
"""

import sys
import time
from pathlib import Path

import click
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)
from rich.table import Table
from textual.app import App, ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Footer, Header, Input, Label, Select, Static, Switch

from qxw import __version__
from qxw.library.base.exceptions import QxwError
from qxw.library.base.logger import get_logger
from qxw.library.managers.chat_provider_manager import SUPPORTED_PROVIDER_TYPES, ChatProviderManager
from qxw.library.services import llm_fetch_service
from qxw.library.services.chat_service import ChatParams, ChatService, ChatSession

logger = get_logger("qxw.llm")
console = Console()
manager = ChatProviderManager()

PROVIDER_TYPE_OPTIONS: list[tuple[str, str]] = [("OpenAI", "openai"), ("Anthropic", "anthropic")]


def _ensure_env() -> None:
    from qxw.config.init import check_env, init_env

    status = check_env()
    if not status.all_ready:
        click.echo("检测到运行环境未完成初始化，正在自动初始化...")
        result = init_env()
        for item in result.initialized_items:
            click.echo(f"  已初始化: {item}")
        click.echo("环境初始化完成\n")

    import qxw.library.models  # noqa: F401  # 确保模型注册到 Base.metadata
    from qxw.library.models.base import init_db

    init_db()


# ============================================================
# chat 子命令
# ============================================================


def _resolve_provider(provider_name: str | None):
    if provider_name:
        provider = manager.get_by_name(provider_name)
        if not provider:
            click.echo(f"提供商 '{provider_name}' 不存在，使用 qxw-llm provider list 查看已配置的提供商。", err=True)
            sys.exit(1)
        return provider

    provider = manager.get_default()
    if not provider:
        providers = manager.list_all()
        if not providers:
            click.echo("暂无已配置的提供商，请先使用 qxw-llm provider add 添加。", err=True)
            sys.exit(1)
        click.echo(
            "未设置默认提供商，请使用 --provider 指定，或使用 qxw-llm provider set-default 设置默认。",
            err=True,
        )
        sys.exit(1)
    return provider


def _run_interactive(session: ChatSession, service: ChatService) -> None:
    provider = session.provider
    console.print(
        f"[bold cyan]已连接: {provider.name}[/] ([green]{provider.provider_type}[/] / {session.params.model})"
    )
    console.print("[dim]输入消息开始对话，Ctrl+C 或输入 /exit 退出，/clear 清空上下文[/]\n")

    while True:
        try:
            user_input = console.input("[bold green]> [/]").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]对话结束[/]")
            break

        if not user_input:
            continue
        if user_input == "/exit":
            console.print("[dim]对话结束[/]")
            break
        if user_input == "/clear":
            session.messages.clear()
            console.print("[dim]上下文已清空[/]\n")
            continue

        console.print()
        try:
            full_response = ""
            with Live(console=console, vertical_overflow="visible") as live:
                for chunk in service.stream_chat(session, user_input):
                    full_response += chunk
                    live.update(Markdown(full_response))
            console.print()
        except QxwError as e:
            console.print(f"\n[red]错误: {e.message}[/]\n")


def _run_single(session: ChatSession, service: ChatService, message: str) -> None:
    try:
        full_response = ""
        with Live(console=console, vertical_overflow="visible") as live:
            for chunk in service.stream_chat(session, message):
                full_response += chunk
                live.update(Markdown(full_response))
    except QxwError as e:
        click.echo(f"错误: {e.message}", err=True)
        sys.exit(e.exit_code)


# ============================================================
# provider TUI 界面 (Textual)
# ============================================================


class ConfirmDeleteScreen(ModalScreen[bool]):

    CSS = """
    ConfirmDeleteScreen {
        align: center middle;
    }
    #confirm-dialog {
        width: 56;
        height: auto;
        border: thick $error;
        padding: 1 2;
        background: $surface;
    }
    #confirm-message {
        width: 100%;
        text-align: center;
        padding: 1 0;
    }
    #confirm-buttons {
        height: auto;
        margin-top: 1;
        align-horizontal: center;
    }
    #confirm-buttons Button {
        margin: 0 2;
    }
    """

    def __init__(self, provider_name: str) -> None:
        super().__init__()
        self._provider_name = provider_name

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="confirm-dialog"):
            yield Static(f"确认删除提供商 [bold red]'{self._provider_name}'[/] ？", id="confirm-message")
            with Horizontal(id="confirm-buttons"):
                yield Button("删除", variant="error", id="confirm")
                yield Button("取消", variant="primary", id="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm")


class ProviderFormScreen(ModalScreen[dict | None]):

    CSS = """
    ProviderFormScreen {
        align: center middle;
    }
    #form-container {
        width: 72;
        max-height: 85%;
        border: thick $accent;
        padding: 1 2;
        background: $surface;
    }
    #form-title {
        width: 100%;
        text-align: center;
        text-style: bold;
        padding: 1 0;
    }
    .form-label {
        margin-top: 1;
        color: $text-muted;
    }
    .switch-row {
        height: auto;
        margin-top: 1;
    }
    .switch-row Label {
        padding: 1 1 1 0;
    }
    #form-buttons {
        height: auto;
        margin-top: 1;
        align-horizontal: center;
    }
    #form-buttons Button {
        margin: 0 2;
    }
    """

    BINDINGS = [("escape", "cancel", "取消")]

    def __init__(self, provider=None, *, copy_from: str | None = None) -> None:
        super().__init__()
        self._provider = provider
        self._is_edit = provider is not None and copy_from is None
        self._copy_from = copy_from

    def compose(self) -> ComposeResult:
        p = self._provider
        if self._is_edit:
            title = f"编辑提供商: {p.name}"
        elif self._copy_from:
            title = f"复制提供商: {self._copy_from}"
        else:
            title = "添加提供商"

        name_value = f"{self._copy_from}-copy" if self._copy_from else (p.name if p else "")

        with VerticalScroll(id="form-container"):
            yield Static(title, id="form-title")

            yield Label("名称", classes="form-label")
            yield Input(
                value=name_value,
                placeholder="my-openai",
                id="f-name",
                disabled=self._is_edit,
            )

            yield Label("类型", classes="form-label")
            yield Select[str](
                options=PROVIDER_TYPE_OPTIONS,
                value=p.provider_type if p else "openai",
                allow_blank=False,
                id="f-type",
            )

            yield Label("Base URL", classes="form-label")
            yield Input(
                value=p.base_url if p else "",
                placeholder="https://api.openai.com/v1",
                id="f-base-url",
            )

            yield Label("API Key", classes="form-label")
            yield Input(
                value=p.api_key if p else "",
                placeholder="sk-...",
                password=True,
                id="f-api-key",
            )

            yield Label("模型", classes="form-label")
            yield Input(
                value=p.model if p else "",
                placeholder="gpt-4o",
                id="f-model",
            )

            yield Label("Temperature", classes="form-label")
            yield Input(value=str(p.temperature) if p else "0.7", id="f-temperature")

            yield Label("Max Tokens", classes="form-label")
            yield Input(value=str(p.max_tokens) if p else "4096", id="f-max-tokens")

            yield Label("Top P", classes="form-label")
            yield Input(value=str(p.top_p) if p else "1.0", id="f-top-p")

            yield Label("系统提示词", classes="form-label")
            yield Input(value=p.system_prompt if p else "", id="f-system-prompt")

            with Horizontal(classes="switch-row"):
                yield Label("设为默认")
                yield Switch(value=p.is_default if p else False, id="f-is-default")

            with Horizontal(id="form-buttons"):
                yield Button("保存", variant="primary", id="save")
                yield Button("取消", id="cancel")

    def _collect_form_data(self) -> dict | None:
        try:
            name = self.query_one("#f-name", Input).value.strip()
            base_url = self.query_one("#f-base-url", Input).value.strip()
            api_key = self.query_one("#f-api-key", Input).value.strip()
            model_name = self.query_one("#f-model", Input).value.strip()

            if not name:
                self.notify("名称不能为空", severity="error")
                return None
            if not base_url:
                self.notify("Base URL 不能为空", severity="error")
                return None
            if not api_key:
                self.notify("API Key 不能为空", severity="error")
                return None
            if not model_name:
                self.notify("模型不能为空", severity="error")
                return None

            type_val = self.query_one("#f-type", Select).value
            if type_val is Select.BLANK:
                self.notify("请选择提供商类型", severity="error")
                return None

            return {
                "name": name,
                "provider_type": str(type_val),
                "base_url": base_url,
                "api_key": api_key,
                "model": model_name,
                "temperature": float(self.query_one("#f-temperature", Input).value),
                "max_tokens": int(self.query_one("#f-max-tokens", Input).value),
                "top_p": float(self.query_one("#f-top-p", Input).value),
                "system_prompt": self.query_one("#f-system-prompt", Input).value,
                "is_default": self.query_one("#f-is-default", Switch).value,
                "_is_edit": self._is_edit,
            }
        except (ValueError, TypeError):
            self.notify("数值参数格式错误（temperature/max_tokens/top_p）", severity="error")
            return None

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save":
            data = self._collect_form_data()
            if data is not None:
                self.dismiss(data)
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class ChatProviderApp(App):

    TITLE = "QXW 对话提供商管理"
    SUB_TITLE = f"v{__version__}"

    CSS = """
    #providers-table {
        height: 1fr;
    }
    #empty-hint {
        width: 100%;
        height: 100%;
        content-align: center middle;
        color: $text-muted;
    }
    """

    BINDINGS = [
        ("a", "add_provider", "添加"),
        ("e", "edit_provider", "编辑"),
        ("c", "copy_provider", "复制"),
        ("d", "delete_provider", "删除"),
        ("s", "set_default", "设为默认"),
        ("q", "quit", "退出"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield DataTable(id="providers-table")
        yield Footer()

    def on_mount(self) -> None:
        self._refresh_table()

    def _refresh_table(self) -> None:
        table = self.query_one(DataTable)
        table.clear(columns=True)
        table.cursor_type = "row"
        table.zebra_stripes = True
        table.add_columns("名称", "类型", "模型", "Base URL", "默认")

        for p in manager.list_all():
            table.add_row(
                p.name,
                p.provider_type,
                p.model,
                p.base_url,
                "✓" if p.is_default else "",
                key=p.name,
            )

    def _get_selected_name(self) -> str | None:
        table = self.query_one(DataTable)
        if table.row_count == 0:
            self.notify("暂无提供商，按 A 添加", severity="warning")
            return None
        row = table.get_row_at(table.cursor_row)
        return str(row[0])

    def action_add_provider(self) -> None:
        self.push_screen(ProviderFormScreen(), self._on_form_result)

    def action_edit_provider(self) -> None:
        self._open_edit()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self._open_edit()

    def _open_edit(self) -> None:
        name = self._get_selected_name()
        if not name:
            return
        provider = manager.get_by_name(name)
        if not provider:
            self.notify(f"提供商 '{name}' 不存在", severity="error")
            return
        self.push_screen(ProviderFormScreen(provider), self._on_form_result)

    def _on_form_result(self, result: dict | None) -> None:
        if result is None:
            return

        is_edit = result.pop("_is_edit", False)
        try:
            if is_edit:
                name = result.pop("name")
                manager.update(name, **result)
                self.notify(f"已更新: {name}")
            else:
                manager.create(**result)
                self.notify(f"已添加: {result['name']}")
        except QxwError as e:
            self.notify(f"错误: {e.message}", severity="error")
            return

        self._refresh_table()

    def action_copy_provider(self) -> None:
        name = self._get_selected_name()
        if not name:
            return
        provider = manager.get_by_name(name)
        if not provider:
            self.notify(f"提供商 '{name}' 不存在", severity="error")
            return
        self.push_screen(ProviderFormScreen(provider, copy_from=name), self._on_form_result)

    def action_delete_provider(self) -> None:
        name = self._get_selected_name()
        if not name:
            return

        def on_confirm(confirmed: bool) -> None:
            if not confirmed:
                return
            try:
                manager.delete(name)
                self._refresh_table()
                self.notify(f"已删除: {name}")
            except QxwError as e:
                self.notify(f"错误: {e.message}", severity="error")

        self.push_screen(ConfirmDeleteScreen(name), on_confirm)

    def action_set_default(self) -> None:
        name = self._get_selected_name()
        if not name:
            return
        try:
            manager.set_default(name)
            self._refresh_table()
            self.notify(f"已将 '{name}' 设为默认")
        except QxwError as e:
            self.notify(f"错误: {e.message}", severity="error")


# ============================================================
# CLI 入口 (Click)
# ============================================================


@click.group(
    name="qxw-llm",
    help="QXW AI 对话工具集合 - 对话 / 提供商管理",
    epilog="使用 qxw-llm <子命令> --help 查看各子命令的详细帮助。",
    invoke_without_command=True,
)
@click.version_option(version=__version__, prog_name="qxw-llm", message="%(prog)s 版本 %(version)s")
@click.pass_context
def main(ctx: click.Context) -> None:
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


# ------------------------------------------------------------
# qxw-llm chat
# ------------------------------------------------------------


@main.command(
    name="chat",
    help="与已配置的提供商进行对话（交互式或单次）",
    epilog="使用 qxw-llm provider 管理对话提供商。",
)
@click.option("--provider", "-p", "provider_name", default=None, help="指定提供商名称（默认使用已设置的默认提供商）")
@click.option("--model", default=None, help="覆盖提供商的默认模型")
@click.option("--temperature", "-t", type=float, default=None, help="覆盖默认温度参数")
@click.option("--max-tokens", type=int, default=None, help="覆盖默认最大 token 数")
@click.option("--top-p", type=float, default=None, help="覆盖默认 top_p 参数")
@click.option("--system", "-s", "system_prompt", default=None, help="覆盖默认系统提示词")
@click.option("--message", "-m", default=None, help="单次对话模式：发送一条消息并输出回复后退出")
def chat_command(
    provider_name: str | None,
    model: str | None,
    temperature: float | None,
    max_tokens: int | None,
    top_p: float | None,
    system_prompt: str | None,
    message: str | None,
) -> None:
    try:
        _ensure_env()

        provider = _resolve_provider(provider_name)
        params = ChatParams.from_provider(
            provider,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            top_p=top_p,
            system_prompt=system_prompt,
        )

        service = ChatService()
        session = ChatSession(provider=provider, params=params)

        if message:
            _run_single(session, service, message)
        else:
            _run_interactive(session, service)

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


# ------------------------------------------------------------
# qxw-llm tui
# ------------------------------------------------------------


@main.command(name="tui", help="启动提供商 TUI 管理界面")
def tui_command() -> None:
    try:
        _ensure_env()
        app = ChatProviderApp()
        app.run()
    except QxwError as e:
        click.echo(f"错误: {e.message}", err=True)
        sys.exit(e.exit_code)
    except KeyboardInterrupt:
        click.echo("\n操作已取消")
        sys.exit(130)


# ------------------------------------------------------------
# qxw-llm provider ...
# ------------------------------------------------------------


@main.group(
    name="provider",
    help="QXW AI 对话提供商管理",
    epilog="使用 qxw-llm provider <子命令> --help 查看各子命令的详细帮助。",
    invoke_without_command=True,
)
@click.pass_context
def provider_group(ctx: click.Context) -> None:
    _ensure_env()
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@provider_group.command(name="list", help="列出所有已配置的提供商")
def list_providers() -> None:
    try:
        providers = manager.list_all()
        if not providers:
            click.echo("暂无已配置的提供商，使用 qxw-llm provider add 添加。")
            return

        table = Table(title="AI 对话提供商列表")
        table.add_column("名称", style="cyan")
        table.add_column("类型", style="green")
        table.add_column("模型", style="yellow")
        table.add_column("Base URL")
        table.add_column("默认", style="bold magenta")

        for p in providers:
            table.add_row(
                p.name,
                p.provider_type,
                p.model,
                p.base_url,
                "✓" if p.is_default else "",
            )

        console.print(table)

    except QxwError as e:
        click.echo(f"错误: {e.message}", err=True)
        sys.exit(e.exit_code)


@provider_group.command(name="add", help="添加一个新的提供商")
@click.option("--name", "-n", required=True, help="提供商名称（唯一标识）")
@click.option(
    "--type",
    "provider_type",
    required=True,
    type=click.Choice(list(SUPPORTED_PROVIDER_TYPES)),
    help="提供商类型",
)
@click.option("--base-url", "-u", required=True, help="API 基础地址")
@click.option("--api-key", "-k", required=True, help="API 密钥")
@click.option("--model", "-m", required=True, help="默认模型名称")
@click.option("--temperature", "-t", type=float, default=0.7, show_default=True, help="默认温度参数")
@click.option("--max-tokens", type=int, default=4096, show_default=True, help="默认最大 token 数")
@click.option("--top-p", type=float, default=1.0, show_default=True, help="默认 top_p 参数")
@click.option("--system-prompt", "-s", default="", help="默认系统提示词")
@click.option("--default", "is_default", is_flag=True, default=False, help="设为默认提供商")
def add_provider(
    name: str,
    provider_type: str,
    base_url: str,
    api_key: str,
    model: str,
    temperature: float,
    max_tokens: int,
    top_p: float,
    system_prompt: str,
    is_default: bool,
) -> None:
    try:
        provider = manager.create(
            name=name,
            provider_type=provider_type,
            base_url=base_url,
            api_key=api_key,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            top_p=top_p,
            system_prompt=system_prompt,
            is_default=is_default,
        )
        click.echo(f"已添加提供商: {provider.name} ({provider.provider_type})")
        if provider.is_default:
            click.echo("  已设为默认提供商")

    except QxwError as e:
        click.echo(f"错误: {e.message}", err=True)
        sys.exit(e.exit_code)


@provider_group.command(name="show", help="查看提供商详情")
@click.argument("name")
def show_provider(name: str) -> None:
    try:
        provider = manager.get_by_name(name)
        if not provider:
            click.echo(f"提供商 '{name}' 不存在", err=True)
            sys.exit(1)

        table = Table(title=f"提供商详情: {provider.name}", show_header=False)
        table.add_column("字段", style="cyan")
        table.add_column("值")

        table.add_row("名称", provider.name)
        table.add_row("类型", provider.provider_type)
        table.add_row("Base URL", provider.base_url)
        table.add_row("API Key", provider.api_key[:8] + "****" if len(provider.api_key) > 8 else "****")
        table.add_row("模型", provider.model)
        table.add_row("Temperature", str(provider.temperature))
        table.add_row("Max Tokens", str(provider.max_tokens))
        table.add_row("Top P", str(provider.top_p))
        table.add_row("系统提示词", provider.system_prompt or "(无)")
        table.add_row("默认", "是" if provider.is_default else "否")
        table.add_row("创建时间", str(provider.created_at))
        table.add_row("更新时间", str(provider.updated_at))

        console.print(table)

    except QxwError as e:
        click.echo(f"错误: {e.message}", err=True)
        sys.exit(e.exit_code)


@provider_group.command(name="edit", help="编辑提供商配置")
@click.argument("name")
@click.option("--type", "provider_type", type=click.Choice(list(SUPPORTED_PROVIDER_TYPES)), help="提供商类型")
@click.option("--base-url", "-u", help="API 基础地址")
@click.option("--api-key", "-k", help="API 密钥")
@click.option("--model", "-m", help="默认模型名称")
@click.option("--temperature", "-t", type=float, help="默认温度参数")
@click.option("--max-tokens", type=int, help="默认最大 token 数")
@click.option("--top-p", type=float, help="默认 top_p 参数")
@click.option("--system-prompt", "-s", help="默认系统提示词")
@click.option("--default", "is_default", is_flag=True, default=False, help="设为默认提供商")
def edit_provider(
    name: str,
    provider_type: str | None,
    base_url: str | None,
    api_key: str | None,
    model: str | None,
    temperature: float | None,
    max_tokens: int | None,
    top_p: float | None,
    system_prompt: str | None,
    is_default: bool,
) -> None:
    try:
        updates: dict[str, object] = {}
        if provider_type is not None:
            updates["provider_type"] = provider_type
        if base_url is not None:
            updates["base_url"] = base_url
        if api_key is not None:
            updates["api_key"] = api_key
        if model is not None:
            updates["model"] = model
        if temperature is not None:
            updates["temperature"] = temperature
        if max_tokens is not None:
            updates["max_tokens"] = max_tokens
        if top_p is not None:
            updates["top_p"] = top_p
        if system_prompt is not None:
            updates["system_prompt"] = system_prompt
        if is_default:
            updates["is_default"] = True

        if not updates:
            click.echo("未指定任何修改项，使用 --help 查看可修改的选项。")
            return

        provider = manager.update(name, **updates)
        click.echo(f"已更新提供商: {provider.name}")

    except QxwError as e:
        click.echo(f"错误: {e.message}", err=True)
        sys.exit(e.exit_code)


@provider_group.command(name="delete", help="删除提供商")
@click.argument("name")
@click.option("--yes", "-y", is_flag=True, default=False, help="跳过确认提示")
def delete_provider(name: str, yes: bool) -> None:
    try:
        provider = manager.get_by_name(name)
        if not provider:
            click.echo(f"提供商 '{name}' 不存在", err=True)
            sys.exit(1)

        if not yes:
            click.confirm(f"确认删除提供商 '{name}'？", abort=True)

        manager.delete(name)
        click.echo(f"已删除提供商: {name}")

    except click.Abort:
        click.echo("已取消")
    except QxwError as e:
        click.echo(f"错误: {e.message}", err=True)
        sys.exit(e.exit_code)


@provider_group.command(name="set-default", help="将指定提供商设为默认")
@click.argument("name")
def set_default_provider(name: str) -> None:
    try:
        provider = manager.set_default(name)
        click.echo(f"已将 '{provider.name}' 设为默认提供商")

    except QxwError as e:
        click.echo(f"错误: {e.message}", err=True)
        sys.exit(e.exit_code)


def _ping_one(provider) -> tuple[bool, str]:
    params = ChatParams(
        model=provider.model,
        temperature=provider.temperature,
        max_tokens=1,
        top_p=provider.top_p,
    )
    service = ChatService(connect_timeout=60.0, timeout=600.0)
    session = ChatSession(provider=provider, params=params)

    try:
        start = time.perf_counter()
        for _ in service.stream_chat(session, "ping"):
            pass
        elapsed_ms = (time.perf_counter() - start) * 1000
        return True, f"✓ 连接正常 ({elapsed_ms:.0f}ms)"
    except QxwError as e:
        return False, f"✗ 连接失败: {e.message}"


@provider_group.command(name="ping", help="测试提供商连接是否正常（向模型发送最小请求）")
@click.argument("name", required=False, default=None)
def ping_provider(name: str | None) -> None:
    try:
        if name:
            provider = manager.get_by_name(name)
            if not provider:
                click.echo(f"提供商 '{name}' 不存在", err=True)
                sys.exit(1)
        else:
            provider = manager.get_default()
            if not provider:
                click.echo("未指定提供商且未设置默认提供商，请指定名称或先设置默认提供商。", err=True)
                sys.exit(1)

        click.echo(f"正在测试 {provider.name} ({provider.provider_type} / {provider.model}) ...")
        ok, msg = _ping_one(provider)
        click.echo(msg)
        if not ok:
            sys.exit(1)

    except QxwError as e:
        click.echo(f"错误: {e.message}", err=True)
        sys.exit(e.exit_code)


@provider_group.command(name="ping-all", help="测试所有已配置的提供商连接")
def ping_all_providers() -> None:
    try:
        providers = manager.list_all()
        if not providers:
            click.echo("暂无已配置的提供商，使用 qxw-llm provider add 添加。")
            return

        failed = 0
        for provider in providers:
            label = f"{provider.name} ({provider.provider_type} / {provider.model})"
            click.echo(f"  {label} ... ", nl=False)
            ok, msg = _ping_one(provider)
            click.echo(msg)
            if not ok:
                failed += 1

        total = len(providers)
        passed = total - failed
        click.echo(f"\n共 {total} 个提供商，{passed} 个正常，{failed} 个失败")
        if failed:
            sys.exit(1)

    except QxwError as e:
        click.echo(f"错误: {e.message}", err=True)
        sys.exit(e.exit_code)


# ------------------------------------------------------------
# qxw-llm fetch
# ------------------------------------------------------------


def _human_size(n: int) -> str:
    """把字节数渲染为带单位的可读字符串"""
    units = ("B", "KB", "MB", "GB", "TB")
    size = float(n)
    idx = 0
    while size >= 1024 and idx < len(units) - 1:
        size /= 1024
        idx += 1
    return f"{size:.2f} {units[idx]}" if idx else f"{int(size)} {units[idx]}"


@main.command(
    name="fetch",
    help="从 HuggingFace / ModelScope 拉取仓库内文件（支持精确名与 glob 表达式）",
    epilog=(
        "示例: qxw-llm fetch bert-base/uncased 'config.json' 'tokenizer*.json'\n"
        "      qxw-llm fetch Qwen/Qwen2-7B 'configuration_*.py' --source modelscope"
    ),
)
@click.argument("repo")
@click.argument("patterns", nargs=-1)
@click.option(
    "--source",
    "-s",
    type=click.Choice(list(llm_fetch_service.SUPPORTED_SOURCES)),
    default=llm_fetch_service.DEFAULT_SOURCE,
    show_default=True,
    help="模型仓库来源",
)
@click.option(
    "--revision",
    "-r",
    default=llm_fetch_service.DEFAULT_REVISION,
    show_default=True,
    help="分支 / tag / commit-ish",
)
@click.option(
    "--output",
    "-o",
    "output",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="输出目录（默认：当前目录下 $org/$name）",
)
@click.option("--token", "-k", default=None, help="访问令牌（用于私有仓库）")
@click.option(
    "--timeout",
    type=float,
    default=60.0,
    show_default=True,
    help="单次 HTTP 请求超时秒数",
)
def fetch_command(
    repo: str,
    patterns: tuple[str, ...],
    source: str,
    revision: str,
    output: Path | None,
    token: str | None,
    timeout: float,
) -> None:
    try:
        if not patterns:
            click.echo("错误: 至少需要指定一个文件名或表达式", err=True)
            sys.exit(6)

        progress = Progress(
            TextColumn("[bold cyan]{task.description}"),
            BarColumn(bar_width=None),
            DownloadColumn(),
            TransferSpeedColumn(),
            TimeRemainingColumn(),
            console=console,
            transient=False,
        )

        # 当前文件对应的 progress task_id，由 on_file_start 创建，
        # on_progress 负责持续刷新，on_file_done 收尾
        state: dict[str, object] = {"task_id": None}

        def on_file_start(rel: str, idx: int, total_files: int) -> None:
            state["task_id"] = progress.add_task(
                f"[{idx}/{total_files}] {rel}", total=None
            )

        def on_progress(written: int, total: int) -> None:
            tid = state.get("task_id")
            if tid is None:
                return
            progress.update(tid, completed=written, total=total or None)  # type: ignore[arg-type]

        def on_file_done(rel: str, idx: int, total_files: int) -> None:
            tid = state.get("task_id")
            if tid is None:
                return
            task_obj = progress.tasks[tid]  # type: ignore[index]
            if task_obj.total is None:
                # 服务端未返回 Content-Length，按已写入字节数收尾以让进度条显示完成
                progress.update(tid, total=task_obj.completed)
            state["task_id"] = None

        with progress:
            result = llm_fetch_service.fetch_files(
                repo=repo,
                patterns=list(patterns),
                source=source,
                revision=revision,
                output=output,
                token=token,
                timeout=timeout,
                progress_cb=on_progress,
                on_file_start=on_file_start,
                on_file_done=on_file_done,
            )

        click.echo(
            f"\n来源: {result.source} | 仓库: {result.repo} | 版本: {result.revision}\n"
            f"输出目录: {result.output_dir}\n"
            f"已下载 {len(result.files)} 个文件，总大小 {_human_size(result.total_size)}"
        )
        for f in result.files:
            click.echo(f"  {f.repo_path} -> {f.local_path}  ({_human_size(f.size)})")

    except QxwError as e:
        logger.error("fetch 命令失败: %s", e.message)
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
