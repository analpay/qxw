"""qxw.library.services.llm_fetch_service 单元测试

聚焦异常路径与边界，遵循 0 happy test 原则：
- 入参校验：空仓库名 / 非法 org-name / 非法 source / 空表达式 / .. 越界 / 空 revision
- 文件清单：HF 返回结构非预期 / ModelScope Code != 0 / 列表为空
- 表达式匹配：精确不命中 / 单段 glob 与多段 glob / 至少一个表达式未命中应失败
- 下载：HTTPError / URLError / TimeoutError / OSError 时清理 .part 临时文件
- 端到端：mock 文件清单与下载，验证回调顺序、目录结构、空 Content-Length 处理
"""

from __future__ import annotations

import json
import urllib.error
from io import BytesIO
from pathlib import Path
from typing import Iterable
from unittest.mock import MagicMock, patch

import pytest

from qxw.library.base.exceptions import CommandError, NetworkError, ValidationError
from qxw.library.services import llm_fetch_service as svc


# ============================================================
# 入参校验
# ============================================================


class TestValidateRepo:
    def test_空字符串(self) -> None:
        with pytest.raises(ValidationError):
            svc._validate_repo("")

    def test_仅空白(self) -> None:
        with pytest.raises(ValidationError):
            svc._validate_repo("   ")

    def test_None(self) -> None:
        with pytest.raises(ValidationError):
            svc._validate_repo(None)  # type: ignore[arg-type]

    def test_缺少斜杠(self) -> None:
        with pytest.raises(ValidationError):
            svc._validate_repo("just-name")

    def test_含非法字符(self) -> None:
        with pytest.raises(ValidationError):
            svc._validate_repo("org/name with space")

    def test_多于一个斜杠(self) -> None:
        with pytest.raises(ValidationError):
            svc._validate_repo("a/b/c")

    def test_合法(self) -> None:
        assert svc._validate_repo("Qwen/Qwen2-7B") == ("Qwen", "Qwen2-7B")


class TestValidateSource:
    def test_未知来源(self) -> None:
        with pytest.raises(ValidationError):
            svc._validate_source("github")

    def test_合法(self) -> None:
        assert svc._validate_source("modelscope") == "modelscope"


class TestValidatePatterns:
    def test_None(self) -> None:
        with pytest.raises(ValidationError):
            svc._validate_patterns(None)  # type: ignore[arg-type]

    def test_空列表(self) -> None:
        with pytest.raises(ValidationError):
            svc._validate_patterns([])

    def test_全空白条目(self) -> None:
        with pytest.raises(ValidationError):
            svc._validate_patterns(["", "  ", None])  # type: ignore[list-item]

    def test_含_dotdot(self) -> None:
        with pytest.raises(ValidationError):
            svc._validate_patterns(["../etc/passwd"])

    def test_去重保序(self) -> None:
        assert svc._validate_patterns(["a", "b", "a"]) == ("a", "b")

    def test_反斜杠归一(self) -> None:
        assert svc._validate_patterns(["dir\\sub\\f.py"]) == ("dir/sub/f.py",)


class TestValidateRevision:
    def test_空(self) -> None:
        with pytest.raises(ValidationError):
            svc._validate_revision("")

    def test_None(self) -> None:
        with pytest.raises(ValidationError):
            svc._validate_revision(None)

    def test_仅空白(self) -> None:
        with pytest.raises(ValidationError):
            svc._validate_revision("   ")

    def test_合法(self) -> None:
        assert svc._validate_revision("v1.0") == "v1.0"


# ============================================================
# 表达式匹配
# ============================================================


class TestFileMatchesPattern:
    def test_精确路径(self) -> None:
        assert svc._file_matches_pattern("config.json", "config.json")
        assert not svc._file_matches_pattern("config.json", "configuration.json")

    def test_单段_glob_命中任意层级(self) -> None:
        assert svc._file_matches_pattern("configuration_qwen.py", "configuration_*.py")
        assert svc._file_matches_pattern("nested/configuration_x.py", "configuration_*.py")
        assert not svc._file_matches_pattern("configuration.txt", "configuration_*.py")

    def test_多段_glob_严格段数(self) -> None:
        assert svc._file_matches_pattern("configs/a.py", "configs/*.py")
        # 段数不等：多段 glob 不跨级
        assert not svc._file_matches_pattern("configs/sub/a.py", "configs/*.py")

    def test_问号_中括号(self) -> None:
        assert svc._file_matches_pattern("a1.py", "a?.py")
        assert svc._file_matches_pattern("a1.py", "a[0-9].py")
        assert not svc._file_matches_pattern("ab.py", "a[0-9].py")


class TestMatchPatterns:
    def test_未命中任意一个表达式_整体失败(self) -> None:
        with pytest.raises(CommandError) as exc:
            svc._match_patterns(["a.py", "b.py"], ["c.py", "d.py"])
        assert "未匹配" in exc.value.message

    def test_部分未命中_仍然失败(self) -> None:
        with pytest.raises(CommandError):
            svc._match_patterns(["a.py", "b.py"], ["a.py", "missing.py"])

    def test_重叠去重(self) -> None:
        # *.py 命中 a.py 和 b.py，a.py 单独再命中一次，去重后还是 [a.py, b.py]
        result = svc._match_patterns(["a.py", "b.py"], ["*.py", "a.py"])
        assert result == ["a.py", "b.py"]


# ============================================================
# HTTP / 文件清单
# ============================================================


def _fake_resp(payload: bytes, content_length: int | None = None) -> MagicMock:
    """构造一个伪造的 urlopen 上下文管理器返回值"""

    class _Resp:
        def __init__(self) -> None:
            self._buf = BytesIO(payload)
            self.headers = {"Content-Length": str(content_length)} if content_length is not None else {}

        def __enter__(self):  # type: ignore[no-untyped-def]
            return self

        def __exit__(self, *a, **kw):  # type: ignore[no-untyped-def]
            return False

        def read(self, size: int = -1) -> bytes:
            return self._buf.read(size)

    return _Resp()  # type: ignore[return-value]


class TestHttpGetJson:
    def test_HTTPError(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def boom(*a, **kw):
            raise urllib.error.HTTPError("http://x", 404, "Not Found", {}, None)  # type: ignore[arg-type]

        monkeypatch.setattr(svc.urllib.request, "urlopen", boom)
        with pytest.raises(NetworkError) as exc:
            svc._http_get_json("http://x", token=None, timeout=1.0)
        assert "404" in exc.value.message

    def test_URLError(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def boom(*a, **kw):
            raise urllib.error.URLError("dns failed")

        monkeypatch.setattr(svc.urllib.request, "urlopen", boom)
        with pytest.raises(NetworkError):
            svc._http_get_json("http://x", token=None, timeout=1.0)

    def test_TimeoutError(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def boom(*a, **kw):
            raise TimeoutError()

        monkeypatch.setattr(svc.urllib.request, "urlopen", boom)
        with pytest.raises(NetworkError) as exc:
            svc._http_get_json("http://x", token=None, timeout=1.0)
        assert "超时" in exc.value.message

    def test_非_JSON(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            svc.urllib.request, "urlopen", lambda *a, **kw: _fake_resp(b"<html>")
        )
        with pytest.raises(NetworkError) as exc:
            svc._http_get_json("http://x", token=None, timeout=1.0)
        assert "非 JSON" in exc.value.message


class TestListHuggingface:
    def test_返回非列表(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(svc, "_http_get_json", lambda *a, **kw: {"oops": True})
        with pytest.raises(NetworkError):
            svc._list_huggingface("o", "n", "main", None, 1.0)

    def test_过滤目录_只保留_file(self, monkeypatch: pytest.MonkeyPatch) -> None:
        payload = [
            {"type": "directory", "path": "subdir"},
            {"type": "file", "path": "config.json"},
            {"type": "file", "path": "tokenizer.json"},
            {"type": "file"},  # 缺 path：应被忽略
            "garbage",  # 非 dict：应被忽略
        ]
        monkeypatch.setattr(svc, "_http_get_json", lambda *a, **kw: payload)
        files = svc._list_huggingface("o", "n", "main", None, 1.0)
        assert files == ["config.json", "tokenizer.json"]


class TestListModelscope:
    def test_返回非_dict(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(svc, "_http_get_json", lambda *a, **kw: [])
        with pytest.raises(NetworkError):
            svc._list_modelscope("o", "n", "main", None, 1.0)

    def test_API_错误码非零(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            svc,
            "_http_get_json",
            lambda *a, **kw: {"Code": 10001, "Message": "repo not found"},
        )
        with pytest.raises(NetworkError) as exc:
            svc._list_modelscope("o", "n", "main", None, 1.0)
        assert "repo not found" in exc.value.message

    def test_Files_缺失(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            svc,
            "_http_get_json",
            lambda *a, **kw: {"Code": 0, "Data": {"NoFiles": []}},
        )
        with pytest.raises(NetworkError):
            svc._list_modelscope("o", "n", "main", None, 1.0)

    def test_只保留_blob(self, monkeypatch: pytest.MonkeyPatch) -> None:
        payload = {
            "Code": 0,
            "Data": {
                "Files": [
                    {"Type": "tree", "Path": "subdir"},
                    {"Type": "blob", "Path": "config.json"},
                    {"type": "file", "path": "lower_case.json"},
                    {"Type": "blob"},  # 缺 path：忽略
                ]
            },
        }
        monkeypatch.setattr(svc, "_http_get_json", lambda *a, **kw: payload)
        files = svc._list_modelscope("o", "n", "main", None, 1.0)
        assert "config.json" in files
        assert "lower_case.json" in files
        assert "subdir" not in files


# ============================================================
# 单文件下载
# ============================================================


class TestDownloadOne:
    def test_HTTPError_清理_part(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        def boom(*a, **kw):
            raise urllib.error.HTTPError("http://x", 403, "Forbidden", {}, None)  # type: ignore[arg-type]

        monkeypatch.setattr(svc.urllib.request, "urlopen", boom)
        dest = tmp_path / "sub" / "a.bin"
        # 提前放一个 .part 文件，验证不会被错误地保留
        dest.parent.mkdir(parents=True, exist_ok=True)
        (dest.parent / "a.bin.part").write_bytes(b"stale")
        with pytest.raises(NetworkError):
            svc._download_one("http://x", dest, token=None, timeout=1.0, progress_cb=None)
        assert not (dest.parent / "a.bin.part").exists()

    def test_URLError_清理_part(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            svc.urllib.request,
            "urlopen",
            lambda *a, **kw: (_ for _ in ()).throw(urllib.error.URLError("net down")),
        )
        dest = tmp_path / "f.bin"
        with pytest.raises(NetworkError):
            svc._download_one("http://x", dest, token=None, timeout=1.0, progress_cb=None)
        assert not (tmp_path / "f.bin.part").exists()

    def test_TimeoutError(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            svc.urllib.request,
            "urlopen",
            lambda *a, **kw: (_ for _ in ()).throw(TimeoutError()),
        )
        with pytest.raises(NetworkError) as exc:
            svc._download_one("http://x", tmp_path / "g.bin", token=None, timeout=1.0, progress_cb=None)
        assert "超时" in exc.value.message

    def test_OSError_映射_CommandError(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            svc.urllib.request, "urlopen", lambda *a, **kw: _fake_resp(b"data", 4)
        )

        def bad_replace(self: Path, target: Path) -> None:
            raise OSError("disk full")

        monkeypatch.setattr(Path, "replace", bad_replace)
        with pytest.raises(CommandError):
            svc._download_one("http://x", tmp_path / "z.bin", token=None, timeout=1.0, progress_cb=None)

    def test_成功_无_Content_Length(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        progress_calls: list[tuple[int, int]] = []
        monkeypatch.setattr(
            svc.urllib.request, "urlopen", lambda *a, **kw: _fake_resp(b"hello", None)
        )
        size = svc._download_one(
            "http://x",
            tmp_path / "o" / "h.txt",
            token="t",
            timeout=1.0,
            progress_cb=lambda w, t: progress_calls.append((w, t)),
        )
        assert size == 5
        assert (tmp_path / "o" / "h.txt").read_bytes() == b"hello"
        assert progress_calls and progress_calls[-1] == (5, 0)

    def test_成功_带_token_鉴权头(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict = {}

        def fake_urlopen(req, timeout):  # type: ignore[no-untyped-def]
            captured["headers"] = dict(req.header_items())
            return _fake_resp(b"data", 4)

        monkeypatch.setattr(svc.urllib.request, "urlopen", fake_urlopen)
        svc._download_one("http://x", tmp_path / "a.bin", token="abc", timeout=1.0, progress_cb=None)
        # urllib 把 header 名字转成 title-case
        assert captured["headers"].get("Authorization") == "Bearer abc"


# ============================================================
# fetch_files 端到端（mock 网络）
# ============================================================


class TestFetchFiles:
    def test_无文件_报错(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(svc, "_list_repo_files", lambda *a, **kw: [])
        with pytest.raises(CommandError) as exc:
            svc.fetch_files("o/n", ["x"], output=tmp_path)
        assert "没有可拉取" in exc.value.message

    def test_表达式未命中(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(svc, "_list_repo_files", lambda *a, **kw: ["config.json"])
        with pytest.raises(CommandError):
            svc.fetch_files("o/n", ["weights*.bin"], output=tmp_path)

    def test_默认_output_目录_为_org_name(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(svc, "_list_repo_files", lambda *a, **kw: ["config.json"])
        monkeypatch.setattr(svc, "_download_one", lambda url, dest, **kw: dest.write_bytes(b"x") or 1)
        monkeypatch.chdir(tmp_path)
        result = svc.fetch_files("Org/Name", ["config.json"])
        assert result.output_dir == tmp_path / "Org" / "Name"
        assert (tmp_path / "Org" / "Name" / "config.json").exists()

    def test_glob_命中多个_保留路径结构(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        files = ["configuration_a.py", "configuration_b.py", "model.bin", "src/configuration_inner.py"]
        monkeypatch.setattr(svc, "_list_repo_files", lambda *a, **kw: files)

        downloaded: list[str] = []

        def fake_dl(url, dest, **kw):  # type: ignore[no-untyped-def]
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b"py")
            downloaded.append(str(dest.relative_to(tmp_path)))
            return 2

        monkeypatch.setattr(svc, "_download_one", fake_dl)
        result = svc.fetch_files("o/n", ["configuration_*.py"], output=tmp_path)
        # 单段 glob 命中任意层级，3 个 .py 文件都应被下载
        assert {f.repo_path for f in result.files} == {
            "configuration_a.py",
            "configuration_b.py",
            "src/configuration_inner.py",
        }
        assert (tmp_path / "src" / "configuration_inner.py").exists()

    def test_文件级回调顺序(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(svc, "_list_repo_files", lambda *a, **kw: ["a.json", "b.json"])
        monkeypatch.setattr(svc, "_download_one", lambda url, dest, **kw: dest.write_bytes(b"x") or 1)

        events: list[tuple[str, str, int, int]] = []
        svc.fetch_files(
            "o/n",
            ["*.json"],
            output=tmp_path,
            on_file_start=lambda rel, idx, total: events.append(("start", rel, idx, total)),
            on_file_done=lambda rel, idx, total: events.append(("done", rel, idx, total)),
        )
        assert events == [
            ("start", "a.json", 1, 2),
            ("done", "a.json", 1, 2),
            ("start", "b.json", 2, 2),
            ("done", "b.json", 2, 2),
        ]

    def test_modelscope_来源_构造_url(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(svc, "_list_repo_files", lambda *a, **kw: ["config.json"])
        captured: dict = {}

        def fake_dl(url, dest, **kw):  # type: ignore[no-untyped-def]
            captured["url"] = url
            dest.write_bytes(b"x")
            return 1

        monkeypatch.setattr(svc, "_download_one", fake_dl)
        svc.fetch_files("Qwen/Q", ["config.json"], source="modelscope", output=tmp_path)
        assert "modelscope.cn" in captured["url"]
        assert "FilePath=config.json" in captured["url"]

    def test_input_校验异常_先于网络(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # 即使 _list_repo_files 会抛异常，参数校验应先生效
        def must_not_call(*a, **kw):
            raise AssertionError("不应该调用网络层")

        monkeypatch.setattr(svc, "_list_repo_files", must_not_call)
        with pytest.raises(ValidationError):
            svc.fetch_files("bad-repo-no-slash", ["x"], output=tmp_path)
