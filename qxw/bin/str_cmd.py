"""qxw-str 命令入口

字符串工具集。提供 ``len`` / ``encrypt`` / ``decrypt`` 子命令。

用法:
    qxw-str len "hello"                 # 统计字符串长度
    qxw-str len "你好，世界"             # 支持中文 / emoji
    echo "hello" | qxw-str len          # 从 stdin 读取

    qxw-str encrypt "secret"            # AES-256-GCM 加密
    qxw-str decrypt "base64密文"         # 解密
    echo "secret" | qxw-str encrypt     # 从 stdin 读取
    qxw-str --help                      # 查看帮助
"""

import sys

import click
from rich.console import Console
from rich.table import Table

from qxw import __version__
from qxw.library.base.exceptions import QxwError
from qxw.library.base.logger import get_logger
from qxw.library.services.crypto_service import decrypt as crypto_decrypt
from qxw.library.services.crypto_service import encrypt as crypto_encrypt

logger = get_logger("qxw.str")
console = Console()


# ============================================================
# CLI 入口 (Click)
# ============================================================


@click.group(
    name="qxw-str",
    help="QXW 字符串工具集（长度统计 / 加解密）",
    epilog="使用 qxw-str <子命令> --help 查看各子命令的详细帮助。",
    invoke_without_command=True,
)
@click.version_option(
    version=__version__,
    prog_name="qxw-str",
    message="%(prog)s 版本 %(version)s",
)
@click.pass_context
def main(ctx: click.Context) -> None:
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@main.command(name="len", help="统计字符串的长度（字符数 / 字节数）")
@click.argument("text", required=False)
@click.option(
    "--quiet",
    "-q",
    is_flag=True,
    default=False,
    help="仅输出字符数（纯数字，便于脚本消费）",
)
@click.option(
    "--bytes",
    "-b",
    "bytes_only",
    is_flag=True,
    default=False,
    help="仅输出 UTF-8 字节数（纯数字，便于脚本消费）",
)
def len_command(text: str | None, quiet: bool, bytes_only: bool) -> None:
    """统计输入字符串的长度

    \b
    字符数：Python len()，按 Unicode 码点计算
    字节数：UTF-8 编码后的字节长度（中文通常 3 字节、emoji 通常 4 字节）

    \b
    示例:
        qxw-str len "hello"              # 字符数: 5 / 字节数: 5
        qxw-str len "你好，世界"          # 字符数: 5 / 字节数: 15
        echo -n "hello world" | qxw-str len
        qxw-str len "你好" -q            # 纯数字 2，适合 $(...) 捕获
    """
    try:
        if quiet and bytes_only:
            raise QxwError("--quiet 与 --bytes 不能同时使用", exit_code=2)

        if text is None:
            if sys.stdin.isatty():
                raise QxwError("未提供字符串参数，也未从 stdin 接收到输入", exit_code=2)
            text = sys.stdin.read()

        char_count = len(text)
        byte_count = len(text.encode("utf-8"))
        logger.info("qxw-str len: char=%d byte=%d", char_count, byte_count)

        if bytes_only:
            click.echo(byte_count)
            return
        if quiet:
            click.echo(char_count)
            return

        table = Table(title="字符串长度统计", show_header=False)
        table.add_column("指标", style="cyan")
        table.add_column("数值", style="green")
        table.add_row("字符数", str(char_count))
        table.add_row("UTF-8 字节数", str(byte_count))
        console.print(table)

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


@main.command(name="encrypt", help="使用 AES-256-GCM 加密字符串")
@click.argument("text", required=False)
@click.option(
    "--quiet",
    "-q",
    is_flag=True,
    default=False,
    help="仅输出密文（单行 base64，便于脚本消费）",
)
@click.option(
    "--key",
    "-k",
    "key",
    default=None,
    help='显式指定加密密钥；缺省时读取环境变量 QXW_STR_ENCRYPT_KEY，再缺省回退到 "sbdqf"',
)
def encrypt_command(text: str | None, quiet: bool, key: str | None) -> None:
    """对字符串进行 AES-256-GCM 加密

    \b
    密钥来源（按优先级）：
      1. --key 参数显式传入
      2. 环境变量 QXW_STR_ENCRYPT_KEY
      3. 默认值 "sbdqf"
    密文格式为 base64(nonce || ciphertext || tag)，可直接传给 qxw-str decrypt 还原。

    \b
    示例:
        qxw-str encrypt "hello"               # 表格输出
        qxw-str encrypt "secret" -q           # 纯密文输出
        echo "hello" | qxw-str encrypt -q     # 从 stdin 读取
        qxw-str encrypt "x" -k "mykey" -q     # 指定密钥
    """
    try:
        if text is None:
            if sys.stdin.isatty():
                raise QxwError("未提供字符串参数，也未从 stdin 接收到输入", exit_code=2)
            text = sys.stdin.read()

        ciphertext = crypto_encrypt(text, key=key)
        logger.info("qxw-str encrypt: plaintext_len=%d ciphertext_len=%d", len(text), len(ciphertext))

        if quiet:
            click.echo(ciphertext)
            return

        table = Table(title="AES-256-GCM 加密", show_header=False)
        table.add_column("字段", style="cyan")
        table.add_column("值", style="green")
        table.add_row("密文", ciphertext)
        console.print(table)

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


@main.command(name="decrypt", help="使用 AES-256-GCM 解密字符串")
@click.argument("text", required=False)
@click.option(
    "--quiet",
    "-q",
    is_flag=True,
    default=False,
    help="仅输出明文（便于脚本消费）",
)
@click.option(
    "--key",
    "-k",
    "key",
    default=None,
    help='显式指定解密密钥；缺省时读取环境变量 QXW_STR_ENCRYPT_KEY，再缺省回退到 "sbdqf"',
)
def decrypt_command(text: str | None, quiet: bool, key: str | None) -> None:
    """对 base64 密文进行 AES-256-GCM 解密

    \b
    密钥来源（按优先级）：
      1. --key 参数显式传入
      2. 环境变量 QXW_STR_ENCRYPT_KEY
      3. 默认值 "sbdqf"
    解密时密钥必须与加密时一致，否则会因认证标签校验失败而报错。

    \b
    示例:
        qxw-str decrypt "base64密文"              # 表格输出
        qxw-str decrypt "base64密文" -q           # 纯明文输出
        CT=$(qxw-str encrypt "x" -q)
        qxw-str decrypt "$CT" -q                  # 往返
        qxw-str decrypt "$CT" -k "mykey" -q      # 指定密钥
    """
    try:
        if text is None:
            if sys.stdin.isatty():
                raise QxwError("未提供字符串参数，也未从 stdin 接收到输入", exit_code=2)
            text = sys.stdin.read()

        plaintext = crypto_decrypt(text, key=key)
        logger.info("qxw-str decrypt: ciphertext_len=%d plaintext_len=%d", len(text), len(plaintext))

        if quiet:
            click.echo(plaintext)
            return

        table = Table(title="AES-256-GCM 解密", show_header=False)
        table.add_column("字段", style="cyan")
        table.add_column("值", style="green")
        table.add_row("明文", plaintext)
        console.print(table)

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
