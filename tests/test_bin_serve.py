"""qxw-serve 命令入口单元测试

重点验证：
- _handle_serve_error 对 OSError/QxwError/KeyboardInterrupt/Exception 分支的分派
- 各子命令在目录不存在时的错误、端口占用时的错误、以及通过 mock start_server 避免真实开服
"""

from __future__ import annotations

from pathlib import Path

import click
import pytest
from click.testing import CliRunner

from qxw.bin import serve as serve_mod
from qxw.library.base.exceptions import QxwError


def _run(args: list[str]) -> tuple[int, str]:
    runner = CliRunner()
    result = runner.invoke(serve_mod.main, args)
    return result.exit_code, result.output


class TestHandleServeError:
    def test_端口占用_errno_48(self) -> None:
        dec = serve_mod._handle_serve_error("x", 8000)
        err = OSError()
        err.errno = 48
        assert dec(err) == 1

    def test_端口占用_消息包含(self) -> None:
        dec = serve_mod._handle_serve_error("x", 8000)
        assert dec(OSError("Address already in use")) == 1

    def test_其他_OSError(self) -> None:
        dec = serve_mod._handle_serve_error("x", 8000)
        assert dec(OSError("io")) == 1

    def test_QxwError_透传_exit_code(self) -> None:
        dec = serve_mod._handle_serve_error("x", 8000)
        assert dec(QxwError("e", exit_code=7)) == 7

    def test_KeyboardInterrupt_返回_0(self) -> None:
        dec = serve_mod._handle_serve_error("x", 8000)
        assert dec(KeyboardInterrupt()) == 0

    def test_Exception_返回_1(self) -> None:
        dec = serve_mod._handle_serve_error("x", 8000)
        assert dec(RuntimeError("x")) == 1


class TestMainGroup:
    def test_无子命令打印帮助(self) -> None:
        code, out = _run([])
        assert code == 0
        assert "gitbook" in out


class TestGitbookCommand:
    def test_目录不存在_退出_1(self, tmp_path: Path) -> None:
        code, out = _run(["gitbook", "-d", str(tmp_path / "nope")])
        assert code == 1
        assert "目录不存在" in out

    def test_markdown_缺失_透传_QxwError(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *a, **k):
            if name == "markdown":
                raise ImportError
            return real_import(name, *a, **k)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        code, out = _run(["gitbook", "-d", str(tmp_path)])
        # QxwError 对应 exit_code=1
        assert code == 1
        assert "markdown" in out

    def test_正常启动_start_server_被调用(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        called: dict[str, object] = {}

        from qxw.library.services import serve_gitbook as sg

        def fake_start(cfg):
            called["cfg"] = cfg

        monkeypatch.setattr(sg, "start_server", fake_start)
        monkeypatch.setattr(sg, "require_markdown", lambda: None)

        code, _ = _run(["gitbook", "-d", str(tmp_path)])
        assert code == 0
        assert "cfg" in called


class TestWebtoolCommand:
    def test_端口占用(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from qxw.library.services import serve_webtool as sw

        def boom(cfg):
            err = OSError("Address already in use")
            err.errno = 48
            raise err

        monkeypatch.setattr(sw, "start_server", boom)
        code, out = _run(["webtool"])
        assert code == 1
        assert "端口" in out

    def test_正常启动(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from qxw.library.services import serve_webtool as sw

        called: dict[str, object] = {}

        def fake(cfg):
            called["ok"] = True

        monkeypatch.setattr(sw, "start_server", fake)
        code, _ = _run(["webtool"])
        assert code == 0
        assert called["ok"] is True


class TestFileWebCommand:
    def test_目录不存在(self, tmp_path: Path) -> None:
        code, out = _run(["file-web", "-d", str(tmp_path / "nope")])
        # BadParameter 走 click 自身，退出码非 0
        assert code != 0

    def test_正常启动_auto_password(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from qxw.library.services import serve_file as sf

        captured: dict[str, object] = {}

        def fake_start(cfg):
            captured["cfg"] = cfg

        monkeypatch.setattr(sf, "start_server", fake_start)
        code, out = _run(["file-web", "-d", str(tmp_path)])
        assert code == 0
        cfg = captured["cfg"]
        assert cfg.auth.auto_generated is True
        assert cfg.auth.password  # 非空

    def test_指定密码(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from qxw.library.services import serve_file as sf

        captured: dict[str, object] = {}

        def fake_start(cfg):
            captured["cfg"] = cfg

        monkeypatch.setattr(sf, "start_server", fake_start)
        code, _ = _run(["file-web", "-d", str(tmp_path), "-P", "mypw"])
        assert code == 0
        cfg = captured["cfg"]
        assert cfg.auth.password == "mypw"
        assert cfg.auth.auto_generated is False


class TestImageWebCommand:
    def test_Pillow_缺失_退出_1(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *a, **k):
            if name == "PIL":
                raise ImportError
            return real_import(name, *a, **k)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        code, out = _run(["image-web", "-d", str(tmp_path)])
        assert code == 1
        assert "Pillow" in out

    def test_目录不存在_BadParameter_被_click_处理(
        self, tmp_path: Path
    ) -> None:
        code, _ = _run(["image-web", "-d", str(tmp_path / "nope")])
        # BadParameter 由 click 处理，退出码 2
        assert code != 0

    def test_正常启动(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from qxw.library.services import image_service as isvc
        from qxw.library.services import serve_image as si

        monkeypatch.setattr(isvc, "scan_images", lambda d, recursive: [])

        captured: dict[str, object] = {}

        def fake_start(cfg, images):
            captured["cfg"] = cfg
            captured["images"] = images

        monkeypatch.setattr(si, "start_server", fake_start)
        code, _ = _run(["image-web", "-d", str(tmp_path)])
        assert code == 0
        assert captured["images"] == []
