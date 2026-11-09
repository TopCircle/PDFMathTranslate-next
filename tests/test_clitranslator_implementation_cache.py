"""Outer CLI cache must follow the executing script and declared dependencies.

Helpers call the real translator constructor and ``BaseTranslator.translate``.
The constant-printing scripts never open a socket. The two-layer test copies
the real DeepLX adapter and mocks HTTP inside that subprocess.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import logging
import os
import shlex
import sqlite3
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pdf2zh_next.config.model import SettingsModel
from pdf2zh_next.config.model import TranslationSettings
from pdf2zh_next.config.translate_engine_model import BingSettings
from pdf2zh_next.config.translate_engine_model import CLISettings
from pdf2zh_next.translator.cache import TranslationCache
from pdf2zh_next.translator.cache import _TranslationCache
from pdf2zh_next.translator.cache import clean_test_db
from pdf2zh_next.translator.cache import init_test_db
from pdf2zh_next.translator.translator_impl.bing import BingTranslator
from pdf2zh_next.translator.translator_impl.clitranslator import CLITranslatorTranslator

DEEPLX_SHA256 = "9d910f3f603ccf984ab2d8120a2def2724c070787296eade22349de49d6086a9"


def _external_deeplx_dir() -> Path | None:
    """Real adapter tree, if this checkout has one. Never a machine-specific path.

    CI of this repo does not contain ``config/deeplx``. Set
    ``PDF2ZH_DEEPLX_DIR`` to opt in, or check out the adapter as a sibling of
    the consumer repo at ``../config/deeplx``.
    """
    override = os.environ.get("PDF2ZH_DEEPLX_DIR", "").strip()
    candidates: list[Path] = []
    if override:
        candidates.append(Path(override).expanduser())
    candidates.append(Path(__file__).resolve().parents[2] / "config" / "deeplx")
    for path in candidates:
        if (path / "deeplx.py").is_file() and (
            path / "normalize_extracted_en.py"
        ).is_file():
            return path
    return None


def _require_external_deeplx() -> Path:
    path = _external_deeplx_dir()
    if path is None:
        pytest.skip(
            "optional DeepLX integration: set PDF2ZH_DEEPLX_DIR, or provide "
            "config/deeplx beside this repo"
        )
    return path
LAYER_SOURCE = "Please use the API."
STALE_TRANSLATION = "请使用调用服务。"
FULL_TRANSLATION = "请使用 API 调用服务。"
# Pre-schema-2 inner keys. VERSION is included again below if it differs.
_OLD_INNER_VERSIONS = (
    "3.2.2-production-final+norm_en_cache_v7",
    "3.2.2-production-final+norm_en_cache_v8",
)

_SITECUSTOMIZE = """\
import json
import os
import socket
from pathlib import Path

def _blocked(*_args, **_kwargs):
    raise RuntimeError("real socket blocked")

socket.create_connection = _blocked
socket.getaddrinfo = _blocked

def _refuse_connect(self, address):
    raise RuntimeError("real socket blocked: %s" % (address,))

socket.socket.connect = _refuse_connect
socket.socket.connect_ex = _refuse_connect


class _Resp:
    def __init__(self, data, status_code=200):
        self.status_code = status_code
        self._data = data
        self.text = json.dumps(data)
        self.headers = {}

    def json(self):
        return self._data


class _Timeout(Exception):
    pass


class _RequestException(Exception):
    pass


class _HTTPError(_RequestException):
    def __init__(self, message, response=None):
        super().__init__(message)
        self.response = response


def _payload_text(payload):
    if not isinstance(payload, dict):
        return ""
    text = payload.get("text", "")
    if isinstance(text, list):
        return str(text[0]) if text else ""
    if isinstance(text, str):
        return text
    return ""


def _post(url, json=None, headers=None, timeout=None, **kwargs):
    if "127.0.0.1" not in str(url):
        raise RuntimeError("refusing non-local URL %s" % (url,))
    counter = Path(os.environ["PDF2ZH_TEST_HTTP_CALLS"])
    current = int(counter.read_text(encoding="utf-8") or "0")
    counter.write_text(str(current + 1), encoding="utf-8")
    text = _payload_text(json)
    log_path = os.environ.get("PDF2ZH_TEST_PAYLOAD_LOG")
    if log_path:
        with open(log_path, "a", encoding="utf-8") as handle:
            handle.write(text + "\\n")
    expected = os.environ["PDF2ZH_TEST_EXPECT_PAYLOAD"]
    full = os.environ["PDF2ZH_TEST_FULL"]
    if text != expected:
        raise RuntimeError(
            "payload mismatch got=%r expected=%r" % (text, expected)
        )
    if "oneshot" in str(url):
        return _Resp({"translations": [{"text": full}]})
    return _Resp({"code": 200, "data": full})


class _Requests:
    post = staticmethod(_post)
    Timeout = _Timeout
    RequestException = _RequestException
    HTTPError = _HTTPError


import sys
sys.modules["requests"] = _Requests
"""


@pytest.fixture(autouse=True)
def _isolated_translation_cache(monkeypatch: pytest.MonkeyPatch):
    """Temporary SQLite only. Reset the one-time identity hint between tests."""
    monkeypatch.setenv("PYTHONIOENCODING", "utf-8")
    from pdf2zh_next.translator.translator_impl import clitranslator as cli_mod

    test_db = init_test_db()
    had_flag = hasattr(cli_mod, "_IMPL_IDENTITY_WARNED")
    previous = getattr(cli_mod, "_IMPL_IDENTITY_WARNED", False)
    if had_flag:
        cli_mod._IMPL_IDENTITY_WARNED = False
    try:
        yield
    finally:
        if had_flag:
            cli_mod._IMPL_IDENTITY_WARNED = previous
        clean_test_db(test_db)


def _model(settings: CLISettings, translation: TranslationSettings | None = None):
    return SettingsModel(
        translation=translation or TranslationSettings(ignore_cache=False),
        translate_engine_settings=settings,
    )


def _translator(settings: CLISettings, translation: TranslationSettings | None = None):
    return CLITranslatorTranslator(_model(settings, translation), MagicMock())


def _constant_script(text: str) -> str:
    literal = json.dumps(text, ensure_ascii=False)
    return (
        "import sys\n"
        "sys.stdin.read()\n"
        f"sys.stdout.buffer.write({literal}.encode('utf-8'))\n"
    )


def _counting_script(counter: Path, text: str) -> str:
    literal = json.dumps(text, ensure_ascii=False)
    return (
        "import sys\n"
        "from pathlib import Path\n"
        f"counter = Path({str(counter)!r})\n"
        "current = int(counter.read_text(encoding='utf-8') or '0') "
        "if counter.exists() else 0\n"
        "counter.write_text(str(current + 1), encoding='utf-8')\n"
        "sys.stdin.read()\n"
        f"sys.stdout.buffer.write({literal}.encode('utf-8'))\n"
    )


def _passthrough_script(token: str) -> str:
    note = json.dumps(token, ensure_ascii=False)
    return f"_ = {note}\nimport sys\nsys.stdout.write(sys.stdin.read())\n"


def _params(translator: CLITranslatorTranslator) -> dict:
    return json.loads(translator.cache.translate_engine_params)


def script_replacement_case(tmp_path: Path):
    """Same path, new script bytes. Two fresh translators, one shared cache."""
    script = tmp_path / "deeplx.py"
    script.write_text(_constant_script("旧译文"), encoding="utf-8")
    source = "script-replacement-source"

    def run():
        translator = _translator(
            CLISettings(
                clitranslator_program=sys.executable,
                clitranslator_script=str(script),
                clitranslator_timeout="30",
            )
        )
        output = translator.translate(source)
        return output, translator.cache.translate_engine_params

    first_output, first_cache_params = run()
    script.write_text(_constant_script("新译文"), encoding="utf-8")
    second_output, second_cache_params = run()
    return first_output, second_output, first_cache_params, second_cache_params


def dependency_change_case(tmp_path: Path, filename: str):
    """Fingerprint before and after one declared dependency's bytes change."""
    work = tmp_path / filename.replace(".", "_")
    work.mkdir(exist_ok=True)
    script = work / "translator.py"
    script.write_text(_constant_script("译文"), encoding="utf-8")
    dependency = work / filename
    dependency.write_text(_passthrough_script("v1"), encoding="utf-8")
    postprocess = None
    if filename == "postprocess.py":
        postprocess = shlex.join([sys.executable, str(dependency)])

    def fingerprint() -> str:
        translator = _translator(
            CLISettings(
                clitranslator_program=sys.executable,
                clitranslator_script=str(script),
                clitranslator_cache_files=str(dependency),
                clitranslator_postprocess_command=postprocess,
                clitranslator_timeout="30",
            )
        )
        translator.translate(f"dependency-{filename}")
        return _params(translator)["clitranslator_impl_fingerprint"]

    before = fingerprint()
    dependency.write_text(_passthrough_script("v2"), encoding="utf-8")
    after = fingerprint()
    return before, after


def test_same_path_script_replacement_invalidates_outer_cache(tmp_path):
    first_output, second_output, first_cache_params, second_cache_params = (
        script_replacement_case(tmp_path)
    )
    assert first_output == "旧译文"
    assert second_output == "新译文"
    assert first_cache_params != second_cache_params
    stored = {
        row.translation
        for row in _TranslationCache.select().where(
            _TranslationCache.original_text == "script-replacement-source"
        )
    }
    assert stored == {"旧译文", "新译文"}


def test_normalizer_and_postprocess_dependency_change_identity(tmp_path):
    for name in ("normalize_extracted_en.py", "postprocess.py"):
        before, after = dependency_change_case(tmp_path, name)
        assert before != after


@pytest.fixture
def shared_translation() -> TranslationSettings:
    return TranslationSettings(ignore_cache=False)


@pytest.fixture
def cli_without_identity(tmp_path: Path, shared_translation: TranslationSettings):
    script = tmp_path / "legacy.py"
    script.write_text(_constant_script("legacy"), encoding="utf-8")
    command = shlex.join([sys.executable, str(script)])
    return _translator(
        CLISettings(clitranslator_command=command, clitranslator_timeout="30"),
        shared_translation,
    )


@pytest.fixture
def other_engine(shared_translation: TranslationSettings):
    return BingTranslator(
        SettingsModel(
            translation=shared_translation,
            translate_engine_settings=BingSettings(),
        ),
        MagicMock(),
    )


def test_legacy_command_without_identity_disables_only_cli_cache(
    cli_without_identity, other_engine, shared_translation
):
    cli = cli_without_identity
    assert cli.ignore_cache is True
    assert other_engine.ignore_cache is False
    assert shared_translation.ignore_cache is False


def test_uncertain_identity_does_not_read_or_write_cache(tmp_path: Path):
    counter = tmp_path / "calls"
    script = tmp_path / "legacy.py"
    script.write_text(_counting_script(counter, "译文"), encoding="utf-8")
    command = shlex.join([sys.executable, str(script)])

    def make():
        return _translator(
            CLISettings(clitranslator_command=command, clitranslator_timeout="30")
        )

    first = make()
    assert first.ignore_cache is True
    assert first.translate("uncertain-identity") == "译文"
    second = make()
    assert second.translate("uncertain-identity") == "译文"
    assert counter.read_text(encoding="utf-8") == "2"
    assert list(_TranslationCache.select()) == []


def test_postprocess_and_direct_executable_without_identity_disable_cache(
    tmp_path: Path,
):
    script = tmp_path / "run.py"
    script.write_text(_constant_script("译文"), encoding="utf-8")
    echoed = shlex.join(
        [sys.executable, "-c", "import sys; sys.stdout.write(sys.stdin.read())"]
    )
    with_postprocess = _translator(
        CLISettings(
            clitranslator_program=sys.executable,
            clitranslator_script=str(script),
            clitranslator_postprocess_command=echoed,
            clitranslator_timeout="30",
        )
    )
    assert with_postprocess.ignore_cache is True

    direct = _translator(
        CLISettings(
            clitranslator_program=sys.executable,
            clitranslator_extra_args=shlex.quote(str(script)),
            clitranslator_timeout="30",
        )
    )
    assert direct.ignore_cache is True


def test_uncertain_identity_warns_once(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
):
    script = tmp_path / "legacy.py"
    script.write_text(_constant_script("x"), encoding="utf-8")
    command = shlex.join([sys.executable, str(script)])

    def make():
        return _translator(CLISettings(clitranslator_command=command))

    with caplog.at_level(
        logging.WARNING,
        logger="pdf2zh_next.translator.translator_impl.clitranslator",
    ):
        first = make()
        second = make()
    assert first.ignore_cache is True
    assert second.ignore_cache is True
    hints = [
        record.getMessage()
        for record in caplog.records
        if "cache disabled" in record.getMessage()
    ]
    assert len(hints) == 1
    assert "whole book" in hints[0]


def test_dependency_order_and_duplicates_do_not_change_fingerprint(tmp_path: Path):
    from pdf2zh_next.translator.translator_impl.cli_cache_identity import (
        implementation_fingerprint,
    )

    first_dep = tmp_path / "a.py"
    second_dep = tmp_path / "b.py"
    first_dep.write_text("alpha\n", encoding="utf-8")
    second_dep.write_text("beta\n", encoding="utf-8")
    script = tmp_path / "run.py"
    script.write_text(_constant_script("译文"), encoding="utf-8")

    def fingerprint(cache_files: str) -> str:
        translator = _translator(
            CLISettings(
                clitranslator_program=sys.executable,
                clitranslator_script=str(script),
                clitranslator_cache_files=cache_files,
                clitranslator_timeout="30",
            )
        )
        translator.translate("order-source")
        params = _params(translator)
        assert params["clitranslator_impl_schema"] == "1"
        assert params["lang_in"] == "en"
        assert params["lang_out"] == "zh"
        assert "clitranslator_command" in params
        return params["clitranslator_impl_fingerprint"]

    listed = fingerprint(f"{first_dep}\n{second_dep}\n")
    reordered = fingerprint(f"{second_dep}\n{first_dep}\n{first_dep}\n")
    assert listed == reordered
    repeated_script = fingerprint(f"{script}\n{second_dep}\n{first_dep}\n")
    assert repeated_script == listed
    assert listed == implementation_fingerprint(
        [script, second_dep, first_dep, first_dep],
        revision="",
    )


def test_same_content_keeps_outer_hit(tmp_path: Path):
    counter = tmp_path / "calls"
    script = tmp_path / "run.py"
    script.write_text(_counting_script(counter, "译文"), encoding="utf-8")
    normalizer = tmp_path / "normalize_extracted_en.py"
    normalizer.write_text("normalizer-v1\n", encoding="utf-8")

    def make():
        return _translator(
            CLISettings(
                clitranslator_program=sys.executable,
                clitranslator_script=str(script),
                clitranslator_cache_files=str(normalizer),
                clitranslator_timeout="30",
            )
        )

    first = make()
    assert first.translate("same-content") == "译文"
    assert first.translate_cache_call_count == 0
    second = make()
    assert second.translate("same-content") == "译文"
    assert second.translate_cache_call_count == 1
    assert counter.read_text(encoding="utf-8") == "1"
    assert (
        _params(first)["clitranslator_impl_fingerprint"]
        == _params(second)["clitranslator_impl_fingerprint"]
    )


def test_explicit_revision_change_misses_cache(tmp_path: Path):
    counter = tmp_path / "calls"
    script = tmp_path / "run.py"
    script.write_text(_counting_script(counter, "译文"), encoding="utf-8")

    def make(revision: str):
        return _translator(
            CLISettings(
                clitranslator_program=sys.executable,
                clitranslator_script=str(script),
                clitranslator_cache_revision=revision,
                clitranslator_timeout="30",
            )
        )

    first = make("rev-1")
    assert first.translate("revision-source") == "译文"
    assert first.translate_cache_call_count == 0
    second = make("rev-2")
    assert second.translate("revision-source") == "译文"
    assert second.translate_cache_call_count == 0
    assert (
        _params(first)["clitranslator_impl_fingerprint"]
        != _params(second)["clitranslator_impl_fingerprint"]
    )
    third = make("rev-1")
    assert third.translate("revision-source") == "译文"
    assert third.translate_cache_call_count == 1
    assert counter.read_text(encoding="utf-8") == "2"


def test_revision_does_not_guess_argv_script(tmp_path: Path):
    counter = tmp_path / "calls"
    script = tmp_path / "tool.py"
    script.write_text(_counting_script(counter, "译文"), encoding="utf-8")

    def make(revision: str):
        translator = _translator(
            CLISettings(
                clitranslator_program=sys.executable,
                clitranslator_extra_args=shlex.quote(str(script)),
                clitranslator_cache_revision=revision,
                clitranslator_timeout="30",
            )
        )
        assert translator.ignore_cache is False
        return translator

    first = make("exe-1")
    assert first.translate("exe-source") == "译文"
    script.write_text(_counting_script(counter, "新译文"), encoding="utf-8")
    second = make("exe-1")
    assert second.translate("exe-source") == "译文"
    assert second.translate_cache_call_count == 1
    changed = make("exe-2")
    assert changed.translate("exe-source") == "新译文"
    assert changed.translate_cache_call_count == 0


def test_legacy_command_does_not_treat_argv_strings_as_implementation_files(
    tmp_path: Path,
):
    script = tmp_path / "tool.py"
    script.write_text(_constant_script("旧译文"), encoding="utf-8")
    decoy = tmp_path / "not-a-dependency.py"
    decoy.write_text("one\n", encoding="utf-8")
    listed = tmp_path / "listed.py"
    listed.write_text("L1\n", encoding="utf-8")
    command = shlex.join([sys.executable, str(script), "--note", str(decoy)])

    def make():
        return _translator(
            CLISettings(
                clitranslator_command=command,
                clitranslator_cache_files=str(listed),
                clitranslator_timeout="30",
            )
        )

    first = make()
    assert first.ignore_cache is False
    assert first.translate("legacy-argv") == "旧译文"
    script.write_text(_constant_script("新译文"), encoding="utf-8")
    decoy.write_text("two\n", encoding="utf-8")
    second = make()
    assert second.translate("legacy-argv") == "旧译文"
    assert second.translate_cache_call_count == 1
    assert (
        _params(first)["clitranslator_impl_fingerprint"]
        == _params(second)["clitranslator_impl_fingerprint"]
    )
    listed.write_text("L2\n", encoding="utf-8")
    third = make()
    assert third.translate("legacy-argv") == "新译文"
    assert third.translate_cache_call_count == 0
    assert (
        _params(third)["clitranslator_impl_fingerprint"]
        != _params(first)["clitranslator_impl_fingerprint"]
    )


def test_glossary_fingerprint_stays_beside_implementation_identity(tmp_path: Path):
    script = tmp_path / "run.py"
    script.write_text(_constant_script("译文"), encoding="utf-8")
    glossary = tmp_path / "glossary.csv"
    glossary.write_text("a,b\n", encoding="utf-8")

    def make():
        translator = _translator(
            CLISettings(
                clitranslator_program=sys.executable,
                clitranslator_script=str(script),
                clitranslator_glossary=str(glossary),
                clitranslator_timeout="30",
            )
        )
        assert translator.translate("glossary-source") == "译文"
        return _params(translator)

    before = make()
    file_keys = [key for key in before if key.startswith("clitranslator_file:")]
    assert file_keys
    assert "clitranslator_impl_fingerprint" in before
    glossary.write_text("a,b\nc,d\n", encoding="utf-8")
    after = make()
    assert (
        before["clitranslator_impl_fingerprint"]
        == after["clitranslator_impl_fingerprint"]
    )
    assert before[file_keys[0]] != after[file_keys[0]]
    assert after["clitranslator_command"] == before["clitranslator_command"]


def test_old_config_loads_without_identity_fields():
    settings = CLISettings(
        clitranslator_program="python3",
        clitranslator_script="/root/.config/pdf2zh/deeplx/deeplx.py",
    )
    settings.validate_settings()
    assert settings.clitranslator_cache_files is None
    assert settings.clitranslator_cache_revision is None
    assert settings.build_command_parts() == [
        "python3",
        "/root/.config/pdf2zh/deeplx/deeplx.py",
    ]
    loaded = CLISettings.model_validate(
        {
            "clitranslator_program": "python3",
            "clitranslator_command": "python3 /opt/pdf2zh/tool.py",
        }
    )
    loaded.validate_settings()
    assert loaded.clitranslator_cache_files is None
    assert loaded.build_command_parts() == ["python3", "/opt/pdf2zh/tool.py"]


def test_cache_identity_fields_are_not_program_arguments(tmp_path: Path):
    dependency = tmp_path / "normalize_extracted_en.py"
    script = tmp_path / "deeplx.py"
    settings = CLISettings(
        clitranslator_program=sys.executable,
        clitranslator_script=str(script),
        clitranslator_cache_files=str(dependency) + "\n",
        clitranslator_cache_revision="2026-11-06",
        clitranslator_extra_args="--max-retries 1",
    )
    parts = settings.build_command_parts()
    assert parts[:2] == [sys.executable, str(script)]
    assert str(dependency) not in parts
    assert "2026-11-06" not in parts
    assert "--max-retries" in parts
    assert "1" in parts


def test_missing_declared_dependency_prevents_startup(tmp_path: Path):
    script = tmp_path / "run.py"
    script.write_text(_constant_script("译文"), encoding="utf-8")
    missing = tmp_path / "normalize_extracted_en.py"
    settings = CLISettings(
        clitranslator_program=sys.executable,
        clitranslator_script=str(script),
        clitranslator_cache_files=str(missing),
        clitranslator_timeout="30",
    )
    with pytest.raises(ValueError, match="missing|unreadable"):
        _translator(settings)

    absent_script = CLISettings(
        clitranslator_program=sys.executable,
        clitranslator_script=str(tmp_path / "absent.py"),
        clitranslator_timeout="30",
    )
    with pytest.raises(ValueError, match="missing|unreadable"):
        _translator(absent_script)


def test_unreadable_dependency_prevents_startup(tmp_path: Path):
    script = tmp_path / "run.py"
    script.write_text(_constant_script("译文"), encoding="utf-8")
    dependency = tmp_path / "normalize_extracted_en.py"
    dependency.write_text("secret\n", encoding="utf-8")
    dependency.chmod(0)
    try:
        with pytest.raises(ValueError, match="missing|unreadable"):
            _translator(
                CLISettings(
                    clitranslator_program=sys.executable,
                    clitranslator_script=str(script),
                    clitranslator_cache_files=str(dependency),
                    clitranslator_timeout="30",
                )
            )
    finally:
        dependency.chmod(0o644)


def test_fingerprint_rejects_missing_directory_and_honors_revision(tmp_path: Path):
    from pdf2zh_next.translator.translator_impl.cli_cache_identity import (
        implementation_fingerprint,
    )

    present = tmp_path / "present.py"
    present.write_text("ok\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing|unreadable"):
        implementation_fingerprint([tmp_path / "missing.py"], revision="")
    with pytest.raises(ValueError, match="missing|unreadable"):
        implementation_fingerprint([tmp_path], revision="")
    with pytest.raises(ValueError, match="revision"):
        implementation_fingerprint([present], revision=None)  # type: ignore[arg-type]
    assert implementation_fingerprint([present], revision="a") != (
        implementation_fingerprint([present], revision="b")
    )
    assert implementation_fingerprint([], revision="only") != (
        implementation_fingerprint([], revision="other")
    )


def _load_deeplx_copy(script: Path):
    spec = importlib.util.spec_from_file_location("deeplx_outer_cache_copy", script)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load DeepLX copy at {script}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _seed_old_inner_rows(db_path: Path, module, normalized: str) -> set[str]:
    glossary_fp = module.glossary_fingerprint({})
    noun_fp = module.proper_noun_fingerprint([])
    versions = list(_OLD_INNER_VERSIONS)
    if module.VERSION not in versions:
        versions.append(module.VERSION)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS cache(
                hash TEXT PRIMARY KEY,
                source TEXT,
                target TEXT,
                version TEXT,
                created INTEGER
            )
            """
        )
        old_keys: set[str] = set()
        for version in versions:
            raw = (
                f"{version}|{glossary_fp}|{noun_fp}|{module.NORMALIZER_FP}|{normalized}"
            )
            key = hashlib.sha256(raw.encode("utf-8")).hexdigest()
            connection.execute(
                "INSERT OR REPLACE INTO cache VALUES(?,?,?,?,?)",
                (key, normalized, STALE_TRANSLATION, version, 1),
            )
            old_keys.add(key)
        connection.commit()
    finally:
        connection.close()
    return old_keys


def test_two_cache_layers_do_not_promote_old_cleaned_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    deeplx_dir = _require_external_deeplx()
    adapter_dir = tmp_path / "adapter"
    adapter_dir.mkdir()
    script = adapter_dir / "deeplx.py"
    normalizer = adapter_dir / "normalize_extracted_en.py"
    script_bytes = (deeplx_dir / "deeplx.py").read_bytes()
    normalizer_bytes = (deeplx_dir / "normalize_extracted_en.py").read_bytes()
    script.write_bytes(script_bytes)
    normalizer.write_bytes(normalizer_bytes)
    assert hashlib.sha256(script.read_bytes()).hexdigest() == DEEPLX_SHA256

    module = _load_deeplx_copy(script)
    assert module.INNER_CACHE_SCHEMA == "2"
    assert module.ADAPTER_IMPLEMENTATION_FP == DEEPLX_SHA256
    from pdf2zh_next.translator.translator_impl import clitranslator as cli_mod

    monkeypatch.setattr(cli_mod.Path, "home", lambda: tmp_path / "empty-home")
    normalized = module.rewrite_bold_glossary_labels(
        module.fix_pdf_spans(
            module.normalize_for_mt(module.clean_unicode(LAYER_SOURCE))
        ),
        {},
    )
    old_keys = _seed_old_inner_rows(
        adapter_dir / "cache" / "deeplx_cache.db", module, normalized
    )
    new_inner_key = module.TranslationCache.make_key(
        normalized,
        module.glossary_fingerprint({}),
        module.proper_noun_fingerprint([]),
    )
    assert new_inner_key not in old_keys

    counter = tmp_path / "http_calls"
    counter.write_text("0", encoding="utf-8")
    payload_log = tmp_path / "payloads"
    site_dir = tmp_path / "pypath"
    site_dir.mkdir()
    (site_dir / "sitecustomize.py").write_text(_SITECUSTOMIZE, encoding="utf-8")
    previous_pythonpath = os.environ.get("PYTHONPATH")
    pythonpath = str(site_dir)
    if previous_pythonpath:
        pythonpath = pythonpath + os.pathsep + previous_pythonpath
    monkeypatch.setenv("PYTHONPATH", pythonpath)
    monkeypatch.setenv("PYTHONIOENCODING", "utf-8")
    monkeypatch.setenv("PDF2ZH_TEST_HTTP_CALLS", str(counter))
    monkeypatch.setenv("PDF2ZH_TEST_PAYLOAD_LOG", str(payload_log))
    monkeypatch.setenv("PDF2ZH_TEST_EXPECT_PAYLOAD", normalized)
    monkeypatch.setenv("PDF2ZH_TEST_FULL", FULL_TRANSLATION)

    # "oneshot" keeps DeepLX from appending the public fallback URL.
    cooldown = tmp_path / "cooldown"
    extra = " ".join(
        [
            "--max-retries",
            "1",
            "--cooldown-seconds",
            "1",
            "--timeout",
            "10",
            "--cooldown-file",
            shlex.quote(str(cooldown)),
        ]
    )
    settings = CLISettings(
        clitranslator_program=sys.executable,
        clitranslator_script=str(script),
        clitranslator_urls="http://127.0.0.1:9/local-oneshot-mock",
        clitranslator_extra_args=extra,
        clitranslator_cache_files=str(normalizer),
        clitranslator_timeout="30",
    )
    old_outer = TranslationCache(
        "clitranslator",
        {
            "lang_in": "en",
            "lang_out": "zh",
            "clitranslator_command": settings.build_command_string(),
            "clitranslator_timeout": settings.resolved_timeout(),
        },
    )
    _TranslationCache.create(
        translate_engine="clitranslator",
        translate_engine_params=old_outer.translate_engine_params,
        original_text=LAYER_SOURCE,
        translation=STALE_TRANSLATION,
    )

    def make():
        return _translator(settings)

    first = make()
    assert first.translate(LAYER_SOURCE) == FULL_TRANSLATION
    assert first.translate_cache_call_count == 0
    assert counter.read_text(encoding="utf-8") == "1"
    assert normalized in payload_log.read_text(encoding="utf-8")

    from pdf2zh_next.translator.translator_impl.cli_cache_identity import (
        implementation_fingerprint,
    )

    params = _params(first)
    assert params["clitranslator_impl_schema"] == "1"
    assert params["clitranslator_impl_fingerprint"] == implementation_fingerprint(
        [script, normalizer],
        revision="",
    )
    assert params["lang_in"] == "en"
    assert params["lang_out"] == "zh"
    assert params["clitranslator_command"] == settings.build_command_string()
    assert params["clitranslator_timeout"] == 30
    fresh = _TranslationCache.get(
        translate_engine="clitranslator",
        translate_engine_params=first.cache.translate_engine_params,
        original_text=LAYER_SOURCE,
    )
    assert fresh is not None
    assert fresh.translation == FULL_TRANSLATION
    preserved = _TranslationCache.get(
        translate_engine="clitranslator",
        translate_engine_params=old_outer.translate_engine_params,
        original_text=LAYER_SOURCE,
    )
    assert preserved is not None
    assert preserved.translation == STALE_TRANSLATION

    connection = sqlite3.connect(adapter_dir / "cache" / "deeplx_cache.db")
    try:
        rows = connection.execute("SELECT hash, target FROM cache").fetchall()
    finally:
        connection.close()
    by_hash = dict(rows)
    assert by_hash[new_inner_key] == FULL_TRANSLATION
    for key in old_keys:
        assert by_hash[key] == STALE_TRANSLATION
    assert STALE_TRANSLATION in by_hash.values()
    assert list(by_hash.values()).count(STALE_TRANSLATION) == len(old_keys)

    second = make()
    assert second.translate(LAYER_SOURCE) == FULL_TRANSLATION
    assert second.translate_cache_call_count == 1
    assert counter.read_text(encoding="utf-8") == "1"
    assert script.read_bytes() == script_bytes
    assert normalizer.read_bytes() == normalizer_bytes


def _loadable_normalizer(token: str) -> str:
    return (
        "def normalize_for_mt(text):\n"
        "    return text\n"
        f"# token={token}\n"
    )


def _env_output_script(counter: Path, env_name: str, note: str = "") -> str:
    """Script bytes stay fixed while the returned text comes from the environment."""
    return (
        "import os\n"
        "import sys\n"
        "from pathlib import Path\n"
        f"counter = Path({str(counter)!r})\n"
        "current = int(counter.read_text(encoding='utf-8') or '0') "
        "if counter.exists() else 0\n"
        "counter.write_text(str(current + 1), encoding='utf-8')\n"
        "sys.stdin.read()\n"
        f"sys.stdout.buffer.write(os.environ[{env_name!r}].encode('utf-8'))\n"
        f"{note}\n"
    )


def test_undeclared_deeplx_normalizer_edit_misses_outer_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Existing normalizer candidates stay in the key when cache_files is unset."""
    from pdf2zh_next.translator.translator_impl.cli_cache_identity import (
        implementation_fingerprint,
    )
    from pdf2zh_next.translator.translator_impl import clitranslator as cli_mod

    adapter_dir = tmp_path / "adapter"
    adapter_dir.mkdir()
    counter = tmp_path / "calls"
    script = adapter_dir / "deeplx.py"
    normalizer = adapter_dir / "normalize_extracted_en.py"
    script.write_text(
        _env_output_script(
            counter,
            "PDF2ZH_TEST_CLI_OUTPUT",
            note="# loads normalize_extracted_en.py",
        ),
        encoding="utf-8",
    )
    normalizer.write_text(_loadable_normalizer("sibling-v1"), encoding="utf-8")
    home = tmp_path / "home"
    home_normalizer = home / ".config" / "pdf2zh" / "deeplx" / "normalize_extracted_en.py"
    home_normalizer.parent.mkdir(parents=True)
    home_normalizer.write_text(_loadable_normalizer("home-unused"), encoding="utf-8")
    monkeypatch.setattr(cli_mod.Path, "home", lambda: home)
    monkeypatch.setenv("PDF2ZH_TEST_CLI_OUTPUT", "第一次译文")

    def make():
        settings = CLISettings(
            clitranslator_program=sys.executable,
            clitranslator_script=str(script),
            clitranslator_timeout="30",
        )
        assert settings.clitranslator_cache_files is None
        translator = _translator(settings)
        assert translator.ignore_cache is False
        return translator

    assert make().translate("undeclared-normalizer") == "第一次译文"
    assert counter.read_text(encoding="utf-8") == "1"
    again = make()
    assert again.translate("undeclared-normalizer") == "第一次译文"
    assert again.translate_cache_call_count == 1
    assert counter.read_text(encoding="utf-8") == "1"

    normalizer.write_text(_loadable_normalizer("sibling-v2"), encoding="utf-8")
    monkeypatch.setenv("PDF2ZH_TEST_CLI_OUTPUT", "第二次译文")
    edited = make()
    assert edited.translate("undeclared-normalizer") == "第二次译文"
    assert edited.translate_cache_call_count == 0
    assert counter.read_text(encoding="utf-8") == "2"
    assert _params(edited)["clitranslator_impl_fingerprint"] == (
        implementation_fingerprint(
            [script, normalizer, home_normalizer], revision=""
        )
    )


def test_home_normalizer_edit_misses_when_deeplx_has_no_sibling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from pdf2zh_next.translator.translator_impl.cli_cache_identity import (
        implementation_fingerprint,
    )
    from pdf2zh_next.translator.translator_impl import clitranslator as cli_mod

    home = tmp_path / "home"
    normalizer = home / ".config" / "pdf2zh" / "deeplx" / "normalize_extracted_en.py"
    normalizer.parent.mkdir(parents=True)
    normalizer.write_text(_loadable_normalizer("home-v1"), encoding="utf-8")
    monkeypatch.setattr(cli_mod.Path, "home", lambda: home)
    counter = tmp_path / "calls"
    script = tmp_path / "adapter" / "deeplx.py"
    script.parent.mkdir()
    script.write_text(
        _env_output_script(
            counter,
            "PDF2ZH_TEST_CLI_OUTPUT",
            note="# loads normalize_extracted_en.py",
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("PDF2ZH_TEST_CLI_OUTPUT", "第一次译文")

    def make():
        translator = _translator(
            CLISettings(
                clitranslator_program=sys.executable,
                clitranslator_script=str(script),
                clitranslator_timeout="30",
            )
        )
        assert translator.ignore_cache is False
        return translator

    assert make().translate("home-normalizer-source") == "第一次译文"
    assert counter.read_text(encoding="utf-8") == "1"
    hit = make()
    assert hit.translate("home-normalizer-source") == "第一次译文"
    assert hit.translate_cache_call_count == 1
    assert counter.read_text(encoding="utf-8") == "1"

    normalizer.write_text(_loadable_normalizer("home-v2"), encoding="utf-8")
    monkeypatch.setenv("PDF2ZH_TEST_CLI_OUTPUT", "第二次译文")
    missed = make()
    assert missed.translate("home-normalizer-source") == "第二次译文"
    assert missed.translate_cache_call_count == 0
    assert counter.read_text(encoding="utf-8") == "2"
    assert _params(missed)["clitranslator_impl_fingerprint"] == (
        implementation_fingerprint([script, normalizer], revision="")
    )


def test_unrelated_script_ignores_normalizer_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from pdf2zh_next.translator.translator_impl.cli_cache_identity import (
        implementation_fingerprint,
    )
    from pdf2zh_next.translator.translator_impl import clitranslator as cli_mod

    home = tmp_path / "home"
    home_normalizer = home / ".config" / "pdf2zh" / "deeplx" / "normalize_extracted_en.py"
    home_normalizer.parent.mkdir(parents=True)
    home_normalizer.write_text("home-v1\n", encoding="utf-8")
    monkeypatch.setattr(cli_mod.Path, "home", lambda: home)
    counter = tmp_path / "calls"
    script = tmp_path / "run.py"
    script.write_text(
        _env_output_script(counter, "PDF2ZH_TEST_CLI_OUTPUT"),
        encoding="utf-8",
    )
    sibling = tmp_path / "normalize_extracted_en.py"
    sibling.write_text("sibling-v1\n", encoding="utf-8")
    monkeypatch.setenv("PDF2ZH_TEST_CLI_OUTPUT", "第一次译文")

    def make():
        return _translator(
            CLISettings(
                clitranslator_program=sys.executable,
                clitranslator_script=str(script),
                clitranslator_timeout="30",
            )
        )

    assert make().translate("unrelated-source") == "第一次译文"
    sibling.write_text("sibling-v2\n", encoding="utf-8")
    home_normalizer.write_text("home-v2\n", encoding="utf-8")
    monkeypatch.setenv("PDF2ZH_TEST_CLI_OUTPUT", "第二次译文")
    second = make()
    assert second.ignore_cache is False
    assert second.translate("unrelated-source") == "第一次译文"
    assert second.translate_cache_call_count == 1
    assert counter.read_text(encoding="utf-8") == "1"
    assert _params(second)["clitranslator_impl_fingerprint"] == (
        implementation_fingerprint([script], revision="")
    )


def test_symlink_script_tracks_normalizer_beside_the_executed_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from pdf2zh_next.translator.translator_impl.cli_cache_identity import (
        implementation_fingerprint,
    )
    from pdf2zh_next.translator.translator_impl import clitranslator as cli_mod

    real = tmp_path / "real"
    real.mkdir()
    counter = tmp_path / "calls"
    script = real / "deeplx.py"
    script.write_text(
        _env_output_script(
            counter,
            "PDF2ZH_TEST_CLI_OUTPUT",
            note="# loads normalize_extracted_en.py",
        ),
        encoding="utf-8",
    )
    real_normalizer = real / "normalize_extracted_en.py"
    real_normalizer.write_text(_loadable_normalizer("real-v1"), encoding="utf-8")
    executed = tmp_path / "exec"
    executed.mkdir()
    link_script = executed / "deeplx.py"
    link_script.symlink_to(script)
    link_normalizer = executed / "normalize_extracted_en.py"
    link_normalizer.write_text(_loadable_normalizer("link-v1"), encoding="utf-8")
    monkeypatch.setattr(cli_mod.Path, "home", lambda: tmp_path / "empty-home")
    monkeypatch.setenv("PDF2ZH_TEST_CLI_OUTPUT", "第一次译文")

    def make():
        return _translator(
            CLISettings(
                clitranslator_program=sys.executable,
                clitranslator_script=str(link_script),
                clitranslator_timeout="30",
            )
        )

    assert make().translate("symlink-source") == "第一次译文"
    assert counter.read_text(encoding="utf-8") == "1"
    assert make().translate("symlink-source") == "第一次译文"
    assert counter.read_text(encoding="utf-8") == "1"

    real_normalizer.write_text(_loadable_normalizer("real-v2"), encoding="utf-8")
    still = make()
    assert still.translate("symlink-source") == "第一次译文"
    assert still.translate_cache_call_count == 1
    assert counter.read_text(encoding="utf-8") == "1"

    link_normalizer.write_text(_loadable_normalizer("link-v2"), encoding="utf-8")
    monkeypatch.setenv("PDF2ZH_TEST_CLI_OUTPUT", "第二次译文")
    missed = make()
    assert missed.translate("symlink-source") == "第二次译文"
    assert missed.translate_cache_call_count == 0
    assert counter.read_text(encoding="utf-8") == "2"
    assert _params(missed)["clitranslator_impl_fingerprint"] == (
        implementation_fingerprint([link_script, link_normalizer], revision="")
    )


def test_normalizer_candidates_are_hashed_without_running_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Both existing candidates are hashed. Top-level code stays unexecuted."""
    from pdf2zh_next.translator.translator_impl.cli_cache_identity import (
        implementation_fingerprint,
    )
    from pdf2zh_next.translator.translator_impl import clitranslator as cli_mod

    marker = tmp_path / "parent-executed"
    counter = tmp_path / "calls"
    script = tmp_path / "adapter" / "deeplx.py"
    script.parent.mkdir()
    script.write_text(
        _env_output_script(
            counter,
            "PDF2ZH_TEST_CLI_OUTPUT",
            note="# loads normalize_extracted_en.py",
        ),
        encoding="utf-8",
    )
    sibling = script.parent / "normalize_extracted_en.py"
    sibling.write_text(
        "import pathlib\n"
        "import sys\n"
        f"pathlib.Path({str(marker)!r}).write_text('sibling', encoding='utf-8')\n"
        "sys.exit(86)\n",
        encoding="utf-8",
    )
    home = tmp_path / "home"
    home_normalizer = home / ".config" / "pdf2zh" / "deeplx" / "normalize_extracted_en.py"
    home_normalizer.parent.mkdir(parents=True)
    home_normalizer.write_text(
        "import pathlib\n"
        "import sys\n"
        f"pathlib.Path({str(marker)!r}).write_text('home', encoding='utf-8')\n"
        "sys.exit(87)\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(cli_mod.Path, "home", lambda: home)
    monkeypatch.setenv("PDF2ZH_TEST_CLI_OUTPUT", "第一次译文")

    def make():
        return _translator(
            CLISettings(
                clitranslator_program=sys.executable,
                clitranslator_script=str(script),
                clitranslator_timeout="30",
            )
        )

    assert make().translate("no-exec-source") == "第一次译文"
    assert not marker.exists()
    assert make().translate("no-exec-source") == "第一次译文"
    assert counter.read_text(encoding="utf-8") == "1"
    assert not marker.exists()

    sibling.write_text(
        "import pathlib\n"
        "import sys\n"
        f"pathlib.Path({str(marker)!r}).write_text('sibling-2', encoding='utf-8')\n"
        "sys.exit(86)\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("PDF2ZH_TEST_CLI_OUTPUT", "第二次译文")
    missed_sibling = make()
    assert missed_sibling.translate("no-exec-source") == "第二次译文"
    assert missed_sibling.translate_cache_call_count == 0
    assert not marker.exists()

    home_normalizer.write_text(
        "import pathlib\n"
        "import sys\n"
        f"pathlib.Path({str(marker)!r}).write_text('home-2', encoding='utf-8')\n"
        "sys.exit(87)\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("PDF2ZH_TEST_CLI_OUTPUT", "第三次译文")
    missed_home = make()
    assert missed_home.translate("no-exec-source") == "第三次译文"
    assert missed_home.translate_cache_call_count == 0
    assert counter.read_text(encoding="utf-8") == "3"
    assert not marker.exists()
    assert _params(missed_home)["clitranslator_impl_fingerprint"] == (
        implementation_fingerprint([script, sibling, home_normalizer], revision="")
    )


def test_child_import_environment_still_fingerprints_the_normalizer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A sibling import can fail here and succeed in the CLI process."""
    from pdf2zh_next.translator.translator_impl.cli_cache_identity import (
        implementation_fingerprint,
    )
    from pdf2zh_next.translator.translator_impl import clitranslator as cli_mod

    adapter = tmp_path / "adapter"
    adapter.mkdir()
    sidecar = adapter / "pdf2zh_norm_sidecar_for_test.py"
    sidecar.write_text("TOKEN = 'child-ok'\n", encoding="utf-8")
    normalizer = adapter / "normalize_extracted_en.py"
    normalizer.write_text(
        "import pdf2zh_norm_sidecar_for_test as sidecar\n"
        "def normalize_for_mt(text):\n"
        "    return sidecar.TOKEN + ':' + text\n",
        encoding="utf-8",
    )
    spec = importlib.util.spec_from_file_location(
        "pdf2zh_parent_probe_normalizer", normalizer
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    with pytest.raises(ImportError):
        spec.loader.exec_module(module)

    child = adapter / "child_load.py"
    child.write_text(
        "import normalize_extracted_en\n"
        "print(normalize_extracted_en.normalize_for_mt('x'), end='')\n",
        encoding="utf-8",
    )
    completed = subprocess.run(
        [sys.executable, str(child)],
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert completed.stdout == "child-ok:x"

    counter = tmp_path / "calls"
    script = adapter / "deeplx.py"
    script.write_text(
        _env_output_script(
            counter,
            "PDF2ZH_TEST_CLI_OUTPUT",
            note="# loads normalize_extracted_en.py",
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(cli_mod.Path, "home", lambda: tmp_path / "empty-home")
    monkeypatch.setenv("PDF2ZH_TEST_CLI_OUTPUT", "第一次译文")

    def make():
        return _translator(
            CLISettings(
                clitranslator_program=sys.executable,
                clitranslator_script=str(script),
                clitranslator_timeout="30",
            )
        )

    assert make().translate("cross-process-source") == "第一次译文"
    assert make().translate("cross-process-source") == "第一次译文"
    assert counter.read_text(encoding="utf-8") == "1"

    normalizer.write_text(
        "import pdf2zh_norm_sidecar_for_test as sidecar\n"
        "def normalize_for_mt(text):\n"
        "    return 'edited:' + text\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("PDF2ZH_TEST_CLI_OUTPUT", "第二次译文")
    missed = make()
    assert missed.translate("cross-process-source") == "第二次译文"
    assert missed.translate_cache_call_count == 0
    assert counter.read_text(encoding="utf-8") == "2"
    assert _params(missed)["clitranslator_impl_fingerprint"] == (
        implementation_fingerprint([script, normalizer], revision="")
    )
