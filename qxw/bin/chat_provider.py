"""qxw-chat-provider 命令入口

管理 AI 对话服务提供商（增删改查）。

用法:
    qxw-chat-provider --tui               # TUI 管理界面（推荐）
    qxw-chat-provider list                # 列出所有提供商
    qxw-chat-provider add                 # 添加提供商
    qxw-chat-provider show <name>         # 查看提供商详情
    qxw-chat-provider edit <name>         # 编辑提供商
    qxw-chat-provider delete <name>       # 删除提供商
    qxw-chat-provider set-default <name>  # 设为默认提供商
"""

import sys

import click
from rich.console import Console
from rich.table import Table
from textual.app import App, ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Footer, Header, Input, Label, Select, Static, Switch

from qxw import __version__
from qxw.library.base.exceptions import QxwError
from qxw.library.base.logger import get_logger
from qxw.library.managers.chat_provider_manager import SUPPORTED_PROVIDER_TYPES, ChatProviderManager

logger = get_logger("qxw.chat-provider")
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

    import qxw.library.models  # noqa: F401
    from qxw.library.models.base import init_db

    init_db()


# ============================================================
# TUI 界面 (Textual)
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
    name="qxw-chat-provider",
    help="QXW AI 对话提供商管理",
    epilog="使用 qxw-chat-provider <子命令> --help 查看各子命令的详细帮助。",
    invoke_without_command=True,
)
@click.option("--tui", is_flag=True, default=False, help="启用 TUI 管理界面")
@click.version_option(version=__version__, prog_name="qxw-chat-provider", message="%(prog)s 版本 %(version)s")
@click.pass_context
def main(ctx: click.Context, tui: bool) -> None:
    _ensure_env()

    if tui:
        app = ChatProviderApp()
        app.run()
        return

    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@main.command(name="list", help="列出所有已配置的提供商")
def list_providers() -> None:
    try:
        providers = manager.list_all()
        if not providers:
            click.echo("暂无已配置的提供商，使用 qxw-chat-provider add 添加。")
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


@main.command(name="add", help="添加一个新的提供商")
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


@main.command(name="show", help="查看提供商详情")
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


@main.command(name="edit", help="编辑提供商配置")
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


@main.command(name="delete", help="删除提供商")
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


@main.command(name="set-default", help="将指定提供商设为默认")
@click.argument("name")
def set_default_provider(name: str) -> None:
    try:
        provider = manager.set_default(name)
        click.echo(f"已将 '{provider.name}' 设为默认提供商")

    except QxwError as e:
        click.echo(f"错误: {e.message}", err=True)
        sys.exit(e.exit_code)


if __name__ == "__main__":
    main()
