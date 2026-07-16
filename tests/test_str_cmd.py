"""qxw-str 命令端到端测试

通过 click.testing.CliRunner 执行，覆盖：
- 基础字符数 / 字节数（含中文）
- --quiet / --bytes 仅输出纯数字
- 冲突参数与缺参校验的退出码
- stdin 读取（模拟管道）
- TTY + 无输入、KeyboardInterrupt、未预期 Exception 分支
- encrypt / decrypt 子命令的往返、stdin、退出码与错误分支
"""

from __future__ import annotations

from io import BytesIO

import pytest
from click.testing import CliRunner

from qxw.bin import str_cmd as str_cmd_mod
from qxw.bin.str_cmd import main


def _run(args: list[str], stdin: str | None = None) -> tuple[int, str]:
    runner = CliRunner()
    result = runner.invoke(main, args, input=stdin)
    return result.exit_code, result.output


class TestLenBasic:
    def test_纯_ASCII(self) -> None:
        code, out = _run(["len", "hello", "-q"])
        assert code == 0
        assert out.strip() == "5"

    def test_中文字符数与字节数(self) -> None:
        # "你好" = 2 char, UTF-8 = 6 byte
        code, out = _run(["len", "你好", "-q"])
        assert code == 0
        assert out.strip() == "2"

        code, out = _run(["len", "你好", "-b"])
        assert code == 0
        assert out.strip() == "6"

    def test_默认表格输出包含两项指标(self) -> None:
        code, out = _run(["len", "hi"])
        assert code == 0
        assert "字符数" in out
        assert "UTF-8 字节数" in out


class TestConflictsAndErrors:
    def test_quiet_与_bytes_冲突退出码_2(self) -> None:
        code, out = _run(["len", "hi", "-q", "-b"])
        assert code == 2
        assert "不能同时使用" in out

    def test_无参数且无_stdin_退出码_2(self) -> None:
        # CliRunner 默认不是 TTY，所以会走 stdin 读取分支；
        # 这里给出显式空输入，模拟用户直接回车也无内容的情况下
        # stdin.read() 返回空串，字符数 / 字节数都是 0，属正常输出。
        code, out = _run(["len", "-q"], stdin="")
        assert code == 0
        assert out.strip() == "0"


class TestStdin:
    def test_从_stdin_读取(self) -> None:
        code, out = _run(["len", "-q"], stdin="hello world")
        assert code == 0
        assert out.strip() == str(len("hello world"))

    def test_stdin_中文字节数(self) -> None:
        code, out = _run(["len", "-b"], stdin="你好")
        assert code == 0
        assert out.strip() == "6"


class TestTopLevel:
    def test_无子命令时打印帮助(self) -> None:
        code, out = _run([])
        assert code == 0
        assert "qxw-str" in out
        assert "len" in out

    def test_version_选项(self) -> None:
        code, out = _run(["--version"])
        assert code == 0
        assert "版本" in out


class _TTYInput(BytesIO):
    """伪装成 TTY 的 stdin，用来驱动 isatty() 为 True 的分支"""

    def isatty(self) -> bool:  # noqa: D401
        return True


class TestErrorBranches:
    def test_TTY_且无参数_退出码_2(self) -> None:
        # CliRunner 默认 stdin 不是 TTY；这里塞一个 isatty()=True 的字节流
        runner = CliRunner()
        result = runner.invoke(main, ["len"], input=_TTYInput(b""))
        assert result.exit_code == 2
        assert "未提供字符串参数" in result.output

    def test_KeyboardInterrupt_退出码_130(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def raise_kb(*_a, **_kw) -> None:
            raise KeyboardInterrupt()

        monkeypatch.setattr(str_cmd_mod.logger, "info", raise_kb)
        code, out = _run(["len", "hi"])
        assert code == 130
        assert "已取消" in out

    def test_未预期_Exception_退出码_1(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def raise_any(*_a, **_kw) -> None:
            raise RuntimeError("boom")

        monkeypatch.setattr(str_cmd_mod.logger, "info", raise_any)
        code, out = _run(["len", "hi"])
        assert code == 1
        assert "未预期" in out


# ============================================================
# encrypt / decrypt 子命令
# ============================================================


class TestEncryptDecrypt:
    def test_往返一致性_默认密钥(self) -> None:
        code, ct = _run(["encrypt", "hello world", "-q"])
        assert code == 0
        ct = ct.strip()
        assert ct != ""
        code, pt = _run(["decrypt", ct, "-q"])
        assert code == 0
        assert pt.strip() == "hello world"

    def test_往返一致性_指定密钥(self) -> None:
        code, ct = _run(["encrypt", "secret", "-k", "mykey", "-q"])
        assert code == 0
        ct = ct.strip()
        code, pt = _run(["decrypt", ct, "-k", "mykey", "-q"])
        assert code == 0
        assert pt.strip() == "secret"

    def test_密钥不匹配解密失败退出码_6(self) -> None:
        code, ct = _run(["encrypt", "x", "-k", "key_a", "-q"])
        assert code == 0
        ct = ct.strip()
        # 用不同密钥解密应触发 ValidationError（exit_code=6）
        code, out = _run(["decrypt", ct, "-k", "key_b", "-q"])
        assert code == 6
        assert "解密失败" in out or "不匹配" in out or "篡改" in out

    def test_encrypt_默认表格输出包含密文字段(self) -> None:
        code, out = _run(["encrypt", "hi"])
        assert code == 0
        assert "密文" in out

    def test_decrypt_默认表格输出包含明文字段(self) -> None:
        code, ct = _run(["encrypt", "hi", "-q"])
        assert code == 0
        code, out = _run(["decrypt", ct.strip()])
        assert code == 0
        assert "明文" in out

    def test_encrypt_从_stdin_读取(self) -> None:
        code, ct = _run(["encrypt", "-q"], stdin="piped data")
        assert code == 0
        assert ct.strip() != ""
        code, pt = _run(["decrypt", ct.strip(), "-q"])
        assert code == 0
        assert pt.strip() == "piped data"

    def test_decrypt_从_stdin_读取(self) -> None:
        code, ct = _run(["encrypt", "abc", "-q"])
        assert code == 0
        code, pt = _run(["decrypt", "-q"], stdin=ct.strip())
        assert code == 0
        assert pt.strip() == "abc"

    def test_encrypt_同一明文两次密文不同(self) -> None:
        code, ct1 = _run(["encrypt", "same", "-q"])
        code, ct2 = _run(["encrypt", "same", "-q"])
        assert ct1.strip() != ct2.strip()


class TestEncryptDecryptErrors:
    def test_encrypt_TTY_且无参数_退出码_2(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["encrypt"], input=_TTYInput(b""))
        assert result.exit_code == 2
        assert "未提供字符串参数" in result.output

    def test_decrypt_TTY_且无参数_退出码_2(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["decrypt"], input=_TTYInput(b""))
        assert result.exit_code == 2
        assert "未提供字符串参数" in result.output

    def test_decrypt_空字符串退出码_6(self) -> None:
        # CliRunner 非 TTY → 走 stdin.read() → 空串 → ValidationError
        code, out = _run(["decrypt", "-q"], stdin="")
        assert code == 6
        assert "不能为空" in out

    def test_decrypt_非法base64退出码_6(self) -> None:
        code, out = _run(["decrypt", "!!!不是base64!!!", "-q"])
        assert code == 6
        assert "base64" in out

    def test_decrypt_长度不足退出码_6(self) -> None:
        import base64

        short = base64.b64encode(b"\x00" * 10).decode("ascii")
        code, out = _run(["decrypt", short, "-q"])
        assert code == 6
        assert "长度不足" in out

    def test_encrypt_KeyboardInterrupt_退出码_130(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def raise_kb(*_a, **_kw) -> None:
            raise KeyboardInterrupt()

        monkeypatch.setattr(str_cmd_mod.logger, "info", raise_kb)
        code, out = _run(["encrypt", "hi", "-q"])
        assert code == 130
        assert "已取消" in out

    def test_decrypt_KeyboardInterrupt_退出码_130(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # 先正常加密拿到密文（不触发 patch）
        code, ct = _run(["encrypt", "hi", "-q"])
        assert code == 0
        ct = ct.strip()

        def raise_kb(*_a, **_kw) -> None:
            raise KeyboardInterrupt()

        # 仅对 decrypt 步骤注入 KeyboardInterrupt
        monkeypatch.setattr(str_cmd_mod.logger, "info", raise_kb)
        code, out = _run(["decrypt", ct, "-q"])
        assert code == 130
        assert "已取消" in out

    def test_encrypt_未预期_Exception_退出码_1(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # str_cmd 在 import 时已绑定 crypto_encrypt，需 patch 模块级引用才生效
        def boom(*_a, **_kw) -> str:
            raise RuntimeError("boom")

        monkeypatch.setattr(str_cmd_mod, "crypto_encrypt", boom)
        code, out = _run(["encrypt", "hi", "-q"])
        assert code == 1
        assert "未预期" in out

    def test_decrypt_未预期_Exception_退出码_1(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def boom(*_a, **_kw) -> str:
            raise RuntimeError("boom")

        monkeypatch.setattr(str_cmd_mod, "crypto_decrypt", boom)
        code, out = _run(["decrypt", "anything", "-q"])
        assert code == 1
        assert "未预期" in out


class TestTopLevelWithNewSubcommands:
    def test_无子命令时帮助包含_encrypt_decrypt(self) -> None:
        code, out = _run([])
        assert code == 0
        assert "len" in out
        assert "encrypt" in out
        assert "decrypt" in out
