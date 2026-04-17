"""qxw-chat 命令入口

与 AI 对话服务提供商进行交互式对话，支持流式输出。

用法:
    qxw-chat                          # 使用默认提供商开始交互式对话
    qxw-chat --provider <name>        # 指定提供商
    qxw-chat --model <model>          # 覆盖默认模型
    qxw-chat -m "你好"                # 单次对话模式
    qxw-chat --help                   # 查看帮助信息
"""

import sys

import click
from rich.console import Console
from rich.markdown import Markdown

from qxw import __version__
from qxw.library.base.exceptions import QxwError
from qxw.library.base.logger import get_logger
from qxw.library.managers.chat_provider_manager import ChatProviderManager
from qxw.library.services.chat_service import ChatParams, ChatService, ChatSession

logger = get_logger("qxw.chat")
console = Console()


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


def _resolve_provider(provider_name: str | None):
    mgr = ChatProviderManager()

    if provider_name:
        provider = mgr.get_by_name(provider_name)
        if not provider:
            click.echo(f"提供商 '{provider_name}' 不存在，使用 qxw-chat-provider list 查看已配置的提供商。", err=True)
            sys.exit(1)
        return provider

    provider = mgr.get_default()
    if not provider:
        providers = mgr.list_all()
        if not providers:
            click.echo("暂无已配置的提供商，请先使用 qxw-chat-provider add 添加。", err=True)
            sys.exit(1)
        click.echo(
            "未设置默认提供商，请使用 --provider 指定，或使用 qxw-chat-provider set-default 设置默认。",
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
            for chunk in service.stream_chat(session, user_input):
                console.print(chunk, end="", highlight=False)
            console.print("\n")
        except QxwError as e:
            console.print(f"\n[red]错误: {e.message}[/]\n")


def _run_single(session: ChatSession, service: ChatService, message: str) -> None:
    full_response = ""
    try:
        for chunk in service.stream_chat(session, message):
            full_response += chunk

        console.print(Markdown(full_response))
    except QxwError as e:
        click.echo(f"错误: {e.message}", err=True)
        sys.exit(e.exit_code)


@click.command(
    name="qxw-chat",
    help="QXW AI 对话工具 - 与已配置的提供商进行对话",
    epilog="使用 qxw-chat-provider 命令管理对话提供商。",
)
@click.option("--provider", "-p", "provider_name", default=None, help="指定提供商名称（默认使用已设置的默认提供商）")
@click.option("--model", default=None, help="覆盖提供商的默认模型")
@click.option("--temperature", "-t", type=float, default=None, help="覆盖默认温度参数")
@click.option("--max-tokens", type=int, default=None, help="覆盖默认最大 token 数")
@click.option("--top-p", type=float, default=None, help="覆盖默认 top_p 参数")
@click.option("--system", "-s", "system_prompt", default=None, help="覆盖默认系统提示词")
@click.option("--message", "-m", default=None, help="单次对话模式：发送一条消息并输出回复后退出")
@click.version_option(version=__version__, prog_name="qxw-chat", message="%(prog)s 版本 %(version)s")
def main(
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


if __name__ == "__main__":
    main()
