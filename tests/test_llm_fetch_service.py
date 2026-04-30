"""qxw.library.services.llm_fetch_service 单元测试

服务层在 v2 切换为以官方 SDK 为后端：
- HuggingFace -> ``huggingface_hub.snapshot_download``
- ModelScope  -> ``modelscope.snapshot_download``

测试遵循 0 happy test 原则，重点覆盖：
- 入参校验：空仓库 / 非法 org-name / 非法 source / 空表达式 / .. 越界
- SDK 缺失：huggingface_hub / modelscope 不可用 → CommandError
- HF 异常：RepositoryNotFoundError / RevisionNotFoundError / HfHubHTTPError
- MS 异常：TypeError 触发 allow_file_pattern 回退、未知异常按类名归类
- 收集：只能收集 snapshot_root 下的真实文件，过滤隐藏目录与非文件项
- 端到端：默认输出目录 = $cwd/$org/$name；下载后 0 文件 → CommandError
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

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
    def test_None_视为空(self) -> None:
        # 空 / None 用于触发 config-only 模式，不再视为非法
        assert svc._validate_patterns(None) == []  # type: ignore[arg-type]

    def test_空列表_视为空(self) -> None:
        assert svc._validate_patterns([]) == []

    def test_全空白条目_视为空(self) -> None:
        assert svc._validate_patterns(["", "  ", None]) == []  # type: ignore[list-item]

    def test_含_dotdot(self) -> None:
        with pytest.raises(ValidationError):
            svc._validate_patterns(["../etc/passwd"])

    def test_去重保序(self) -> None:
        assert svc._validate_patterns(["a", "b", "a"]) == ["a", "b"]

    def test_反斜杠归一(self) -> None:
        assert svc._validate_patterns(["dir\\sub\\f.py"]) == ["dir/sub/f.py"]


class TestNormalizeRevision:
    def test_None(self) -> None:
        assert svc._normalize_revision(None) is None

    def test_空白(self) -> None:
        assert svc._normalize_revision("  ") is None

    def test_有效(self) -> None:
        assert svc._normalize_revision("v1.0") == "v1.0"


# ============================================================
# 文件清单收集
# ============================================================


class TestCollectDownloadedFiles:
    def test_不存在的目录(self, tmp_path: Path) -> None:
        assert svc._collect_downloaded_files(tmp_path / "nope", tmp_path) == []

    def test_过滤隐藏目录(self, tmp_path: Path) -> None:
        (tmp_path / ".cache").mkdir()
        (tmp_path / ".cache" / "x").write_bytes(b"x")
        (tmp_path / ".huggingface").mkdir()
        (tmp_path / ".huggingface" / "y").write_bytes(b"y")
        (tmp_path / "config.json").write_bytes(b"data")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "tokenizer.json").write_bytes(b"t")

        files = svc._collect_downloaded_files(tmp_path, tmp_path)
        rels = sorted(f.repo_path for f in files)
        assert rels == ["config.json", "sub/tokenizer.json"]

    def test_size_读取失败_容错(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        f = tmp_path / "broken.bin"
        f.write_bytes(b"abc")
        original_stat = Path.stat

        def bad_stat(self: Path, *args, **kwargs):  # type: ignore[no-untyped-def]
            if self == f:
                raise OSError("permission denied")
            return original_stat(self, *args, **kwargs)

        monkeypatch.setattr(Path, "stat", bad_stat)
        files = svc._collect_downloaded_files(tmp_path, tmp_path)
        assert any(x.repo_path == "broken.bin" and x.size == 0 for x in files)


# ============================================================
# SDK 缺失分支
# ============================================================


def _make_fake_module(name: str, **attrs: object) -> types.ModuleType:
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


class TestHfSdkMissing:
    def test_缺少_huggingface_hub(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setitem(sys.modules, "huggingface_hub", None)
        with pytest.raises(CommandError) as exc:
            svc._hf_snapshot_download(
                repo_id="o/n",
                patterns=["*.json"],
                local_dir=tmp_path,
                revision=None,
                token=None,
            )
        assert "huggingface_hub" in exc.value.message


class TestMsSdkMissing:
    def test_缺少_modelscope(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setitem(sys.modules, "modelscope", None)
        with pytest.raises(CommandError) as exc:
            svc._ms_snapshot_download(
                model_id="o/n",
                patterns=["*.json"],
                local_dir=tmp_path,
                revision=None,
                token=None,
            )
        assert "modelscope" in exc.value.message


# ============================================================
# HF 异常归类
# ============================================================


class _FakeRepoNotFound(Exception):
    pass


class _FakeRevisionNotFound(Exception):
    pass


class _FakeHfHubHTTPError(Exception):
    pass


def _install_fake_hf(monkeypatch: pytest.MonkeyPatch, *, behavior) -> None:
    """安装一个伪造的 huggingface_hub 模块"""
    errors_mod = _make_fake_module(
        "huggingface_hub.errors",
        HfHubHTTPError=_FakeHfHubHTTPError,
        RepositoryNotFoundError=_FakeRepoNotFound,
        RevisionNotFoundError=_FakeRevisionNotFound,
    )
    hf_mod = _make_fake_module(
        "huggingface_hub",
        snapshot_download=behavior,
        errors=errors_mod,
    )
    monkeypatch.setitem(sys.modules, "huggingface_hub", hf_mod)
    monkeypatch.setitem(sys.modules, "huggingface_hub.errors", errors_mod)


class TestHfErrorMapping:
    def test_仓库不存在(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        def boom(**k):
            raise _FakeRepoNotFound("not found")

        _install_fake_hf(monkeypatch, behavior=boom)
        with pytest.raises(CommandError) as exc:
            svc._hf_snapshot_download(
                repo_id="o/n", patterns=["*.json"], local_dir=tmp_path, revision=None, token=None
            )
        assert "仓库不存在" in exc.value.message

    def test_revision_不存在(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        def boom(**k):
            raise _FakeRevisionNotFound("bad")

        _install_fake_hf(monkeypatch, behavior=boom)
        with pytest.raises(CommandError) as exc:
            svc._hf_snapshot_download(
                repo_id="o/n",
                patterns=["*.json"],
                local_dir=tmp_path,
                revision="v9",
                token=None,
            )
        assert "revision 不存在" in exc.value.message

    def test_HTTP_错误归类_NetworkError(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def boom(**k):
            raise _FakeHfHubHTTPError("503")

        _install_fake_hf(monkeypatch, behavior=boom)
        with pytest.raises(NetworkError):
            svc._hf_snapshot_download(
                repo_id="o/n", patterns=["*.json"], local_dir=tmp_path, revision=None, token=None
            )

    def test_OSError_归类_CommandError(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def boom(**k):
            raise OSError("disk full")

        _install_fake_hf(monkeypatch, behavior=boom)
        with pytest.raises(CommandError) as exc:
            svc._hf_snapshot_download(
                repo_id="o/n", patterns=["*.json"], local_dir=tmp_path, revision=None, token=None
            )
        assert "写入文件失败" in exc.value.message

    def test_成功路径_kwargs_透传(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict = {}

        def fake(**kwargs):
            captured.update(kwargs)
            return str(tmp_path)

        _install_fake_hf(monkeypatch, behavior=fake)
        path = svc._hf_snapshot_download(
            repo_id="o/n",
            patterns=["*.json"],
            local_dir=tmp_path,
            revision="v1",
            token="t",
        )
        assert path == tmp_path
        assert captured["repo_id"] == "o/n"
        assert captured["allow_patterns"] == ["*.json"]
        assert captured["revision"] == "v1"
        assert captured["token"] == "t"
        assert captured["local_dir"] == str(tmp_path)
        assert "ignore_patterns" not in captured

    def test_config_only_模式_用_ignore_patterns(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """patterns 为空时，应改用 WEIGHT_IGNORE_PATTERNS 作为 ignore_patterns"""
        captured: dict = {}

        def fake(**kwargs):
            captured.update(kwargs)
            return str(tmp_path)

        _install_fake_hf(monkeypatch, behavior=fake)
        svc._hf_snapshot_download(
            repo_id="o/n",
            patterns=[],
            local_dir=tmp_path,
            revision=None,
            token=None,
        )
        assert "allow_patterns" not in captured
        assert captured["ignore_patterns"] == list(svc.WEIGHT_IGNORE_PATTERNS)
        # 与 msmodeling 保持一致的关键后缀
        assert "*.safetensors" in captured["ignore_patterns"]
        assert "*.bin" in captured["ignore_patterns"]
        assert "*.gguf" in captured["ignore_patterns"]


# ============================================================
# MS 异常归类与回退
# ============================================================


def _install_fake_ms(monkeypatch: pytest.MonkeyPatch, *, behavior) -> None:
    ms_mod = _make_fake_module("modelscope", snapshot_download=behavior)
    monkeypatch.setitem(sys.modules, "modelscope", ms_mod)


class TestMsErrorMapping:
    def test_TypeError_触发_allow_file_pattern_回退(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[dict] = []

        def fake(**kwargs):
            calls.append(kwargs)
            if "allow_patterns" in kwargs:
                raise TypeError("unexpected kwarg")
            return str(tmp_path)

        _install_fake_ms(monkeypatch, behavior=fake)
        path = svc._ms_snapshot_download(
            model_id="o/n",
            patterns=["*.py"],
            local_dir=tmp_path,
            revision="master",
            token=None,
        )
        assert path == tmp_path
        # 第一次用 allow_patterns，第二次回退到 allow_file_pattern
        assert "allow_patterns" in calls[0]
        assert "allow_file_pattern" in calls[1]

    def test_OSError_映射_CommandError(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def boom(**kwargs):
            raise OSError("disk full")

        _install_fake_ms(monkeypatch, behavior=boom)
        with pytest.raises(CommandError) as exc:
            svc._ms_snapshot_download(
                model_id="o/n",
                patterns=["*.json"],
                local_dir=tmp_path,
                revision=None,
                token=None,
            )
        assert "写入文件失败" in exc.value.message

    def test_仓库不存在_按异常类名识别(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class NotExistError(Exception):
            pass

        def boom(**kwargs):
            raise NotExistError("repo gone")

        _install_fake_ms(monkeypatch, behavior=boom)
        with pytest.raises(CommandError) as exc:
            svc._ms_snapshot_download(
                model_id="o/n",
                patterns=["*.json"],
                local_dir=tmp_path,
                revision="v1",
                token=None,
            )
        assert "不存在" in exc.value.message

    def test_其他异常_归类_NetworkError(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def boom(**kwargs):
            raise RuntimeError("connection reset")

        _install_fake_ms(monkeypatch, behavior=boom)
        with pytest.raises(NetworkError):
            svc._ms_snapshot_download(
                model_id="o/n",
                patterns=["*.json"],
                local_dir=tmp_path,
                revision=None,
                token=None,
            )

    def test_token_与_revision_条件透传(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict = {}

        def fake(**kwargs):
            captured.update(kwargs)
            return str(tmp_path)

        _install_fake_ms(monkeypatch, behavior=fake)
        # 不传 revision/token：kwargs 中不应出现这两个键
        svc._ms_snapshot_download(
            model_id="o/n",
            patterns=["*.json"],
            local_dir=tmp_path,
            revision=None,
            token=None,
        )
        assert "revision" not in captured
        assert "token" not in captured

        captured.clear()
        svc._ms_snapshot_download(
            model_id="o/n",
            patterns=["*.json"],
            local_dir=tmp_path,
            revision="v2",
            token="abc",
        )
        assert captured["revision"] == "v2"
        assert captured["token"] == "abc"


# ============================================================
# fetch_files 端到端
# ============================================================


class TestFetchFiles:
    def test_参数校验异常_先于_SDK_调用(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def must_not_call(**kwargs):
            raise AssertionError("不应该调用 SDK")

        monkeypatch.setattr(svc, "_hf_snapshot_download", must_not_call)
        monkeypatch.setattr(svc, "_ms_snapshot_download", must_not_call)
        with pytest.raises(ValidationError):
            svc.fetch_files("bad-repo-no-slash", ["x"], output=tmp_path)

    def test_默认_output_为_org_name(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def fake_hf(**kwargs):
            local = Path(kwargs["local_dir"])
            (local / "config.json").write_bytes(b"data")
            return local

        monkeypatch.setattr(svc, "_hf_snapshot_download", fake_hf)
        monkeypatch.chdir(tmp_path)
        result = svc.fetch_files("Org/Name", ["config.json"])
        assert result.output_dir == tmp_path / "Org" / "Name"
        assert (tmp_path / "Org" / "Name" / "config.json").exists()
        assert len(result.files) == 1
        assert result.files[0].repo_path == "config.json"
        assert result.files[0].size == 4

    def test_来源_modelscope_走_ms_分支(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def must_not_call(**kwargs):
            raise AssertionError("不应该走 HF")

        captured: dict = {}

        def fake_ms(**kwargs):
            captured.update(kwargs)
            local = Path(kwargs["local_dir"])
            (local / "configuration_x.py").write_bytes(b"py")
            return local

        monkeypatch.setattr(svc, "_hf_snapshot_download", must_not_call)
        monkeypatch.setattr(svc, "_ms_snapshot_download", fake_ms)
        result = svc.fetch_files(
            "Qwen/Q",
            ["configuration_*.py"],
            source="modelscope",
            output=tmp_path,
        )
        assert result.source == "modelscope"
        assert captured["model_id"] == "Qwen/Q"
        assert captured["patterns"] == ["configuration_*.py"]
        assert len(result.files) == 1

    def test_下载后_零文件_报错(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def fake_hf(**kwargs):
            return Path(kwargs["local_dir"])  # 不写入任何文件

        monkeypatch.setattr(svc, "_hf_snapshot_download", fake_hf)
        with pytest.raises(CommandError) as exc:
            svc.fetch_files("o/n", ["*.bin"], output=tmp_path)
        assert "未下载到任何文件" in exc.value.message

    def test_无_patterns_走_skip_weights_模式(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """patterns=None 时应转发为 ignore_patterns=WEIGHT_IGNORE_PATTERNS"""
        captured: dict = {}

        def fake_hf(**kwargs):
            captured.update(kwargs)
            local = kwargs["local_dir"]
            (local / "config.json").write_bytes(b"{}")
            (local / "tokenizer.json").write_bytes(b"{}")
            (local / "configuration_x.py").write_bytes(b"# code")
            return local

        monkeypatch.setattr(svc, "_hf_snapshot_download", fake_hf)
        result = svc.fetch_files("o/n", None, output=tmp_path)
        # 服务层把空 patterns 转换为 [] 后透传
        assert captured["patterns"] == []
        # 端到端拉到的 3 个非权重文件全部进入结果
        rels = {f.repo_path for f in result.files}
        assert rels == {"config.json", "tokenizer.json", "configuration_x.py"}

    def test_空列表_等价于_无_patterns(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict = {}

        def fake_hf(**kwargs):
            captured.update(kwargs)
            local = kwargs["local_dir"]
            (local / "config.json").write_bytes(b"{}")
            return local

        monkeypatch.setattr(svc, "_hf_snapshot_download", fake_hf)
        svc.fetch_files("o/n", [], output=tmp_path)
        assert captured["patterns"] == []

    def test_skip_weights_命中_零文件_走专用错误(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """权重纯仓库下，跳过权重后会得到 0 文件，错误信息应能区分模式"""

        def fake_hf(**kwargs):
            return Path(kwargs["local_dir"])  # 啥都不写

        monkeypatch.setattr(svc, "_hf_snapshot_download", fake_hf)
        with pytest.raises(CommandError) as exc:
            svc.fetch_files("o/n", None, output=tmp_path)
        assert "跳过权重" in exc.value.message

    def test_revision_空白_视为_None_透传(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict = {}

        def fake_hf(**kwargs):
            captured.update(kwargs)
            local = Path(kwargs["local_dir"])
            (local / "f.json").write_bytes(b"x")
            return local

        monkeypatch.setattr(svc, "_hf_snapshot_download", fake_hf)
        svc.fetch_files("o/n", ["f.json"], revision="   ", output=tmp_path)
        assert captured["revision"] is None

    def test_保留_snapshot_root_路径(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 模拟 SDK 把文件放到了 cache 路径而不是用户传入的 local_dir
        cache_dir = tmp_path / "cache_pretend"
        cache_dir.mkdir()
        (cache_dir / "config.json").write_bytes(b"abc")

        def fake_hf(**kwargs):
            return cache_dir

        monkeypatch.setattr(svc, "_hf_snapshot_download", fake_hf)
        result = svc.fetch_files(
            "o/n", ["config.json"], output=tmp_path / "user_chose"
        )
        # output_dir 应反映 SDK 实际落盘位置，避免给用户错误的路径暗示
        assert result.output_dir == cache_dir
        assert result.files[0].local_path == cache_dir / "config.json"
