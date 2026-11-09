"""Runtime manifest records imported sources, not the Compose mount."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

CONSUMER = Path(__file__).resolve().parents[1]
COMPOSE = Path("/Users/yun/Nextcloud/Project/PDFMathTranslate-next/docker-compose.yml")
DOCKERFILE = CONSUMER / "Dockerfile"
DOC = CONSUMER / "docs" / "runtime-verification.md"
COMPOSE_EXPR = "${BABELDOC_REF:?BABELDOC_REF must be a full commit SHA}"
COMPOSE_CMD = (
    "BABELDOC_REF=<40位小写SHA> docker compose -f "
    "/Users/yun/Nextcloud/Project/PDFMathTranslate-next/docker-compose.yml "
    "build pdfmt-next"
)
EXPECTED_BABELDOC_SHA = "abf0390bf98efe9c08057b3c1cfca3bb4aa199e8"
FIXTURE_KEY = "fixture-test-key-DO-NOT-LEAK"
FIXTURE_ENDPOINT = "https://fixture.invalid/translate"
MOUNT_MARKERS = ("/app/BabelDOC", "/app/PDFMathTranslate-next")
MANIFEST_KEYS = {
    "schema_version",
    "python_version",
    "babeldoc_path",
    "babeldoc_version",
    "babeldoc_git_revision",
    "pdf2zh_next_path",
    "pdf2zh_next_version",
    "pdf2zh_next_git_revision",
    "babeldoc_distribution_version",
    "pdf2zh_next_distribution_version",
    "deeplx_sha256",
    "clitranslator_impl_schema",
}
_REF_CHECK = "printf '%s' \"$BABELDOC_REF\" | grep -Eq '^[0-9a-f]{40}$'"


def _manifest_module():
    from pdf2zh_next import runtime_manifest

    return runtime_manifest


def _active_lines(text: str) -> list[str]:
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        lines.append(stripped)
    return lines


def _dockerfile_accepts(ref: str) -> bool:
    text = DOCKERFILE.read_text(encoding="utf-8")
    check_at = text.find(_REF_CHECK)
    install_at = text.find(
        "git+https://github.com/TopCircle/BabelDOC.git@${BABELDOC_REF}"
    )
    assert check_at >= 0, "Dockerfile must check ^[0-9a-f]{40}$ before install"
    assert install_at > check_at
    shell = shutil.which("sh")
    assert shell is not None
    completed = subprocess.run(
        [shell, "-c", _REF_CHECK],
        check=False,
        env={"BABELDOC_REF": ref, "PATH": os.environ.get("PATH", "")},
    )
    return completed.returncode == 0


def test_compose_passes_required_babeldoc_ref():
    assert COMPOSE.is_file()
    assert COMPOSE.resolve() == (CONSUMER.parent / "docker-compose.yml").resolve()
    loaded = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    build = loaded["services"]["pdfmt-next"]["build"]
    assert build["args"]["BABELDOC_REF"] == COMPOSE_EXPR
    assert build["context"] == "./PDFMathTranslate-next"
    assert build["dockerfile"] == "Dockerfile"


def test_verification_doc_matches_dockerfile_arg_and_compose_digest():
    doc = DOC.read_text(encoding="utf-8")
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    arg_names = re.findall(r"^ARG\s+([A-Za-z0-9_]+)", dockerfile, re.MULTILINE)
    assert COMPOSE_CMD in doc
    env_name = COMPOSE_CMD.split("=", 1)[0]
    assert env_name in arg_names
    assert env_name == "BABELDOC_REF"
    assert EXPECTED_BABELDOC_SHA in doc
    assert "not pushed" in doc
    digest = hashlib.sha256(COMPOSE.read_bytes()).hexdigest()
    assert digest in doc
    assert "is not deployed" in doc


@pytest.mark.parametrize(
    "ref",
    [
        "",
        "main",
        "98c6336",
        "g" * 40,
        "98C63369382C72A738C289B702EBD46B956569A2",
    ],
)
def test_dockerfile_rejects_bad_babeldoc_ref(ref: str):
    assert _dockerfile_accepts(ref) is False


def test_dockerfile_accepts_one_full_lowercase_sha():
    assert _dockerfile_accepts(EXPECTED_BABELDOC_SHA) is True


def test_dockerfile_pins_ref_without_random_cache_bust():
    text = DOCKERFILE.read_text(encoding="utf-8")
    active = _active_lines(text)
    assert "random.org" not in text
    assert not any("@main" in line for line in active)
    install = next(
        line
        for line in active
        if "git+https://github.com/TopCircle/BabelDOC.git@${BABELDOC_REF}" in line
    )
    assert "babeldoc --warmup" in install
    assert "ARG BABELDOC_REF" in active


def test_manifest_records_imported_paths_not_compose_mount(monkeypatch):
    import babeldoc
    import pdf2zh_next

    runtime_manifest = _manifest_module()
    babel_file = "/imported-babeldoc/babeldoc/__init__.py"
    consumer_file = "/imported-pdf2zh/pdf2zh_next/__init__.py"
    monkeypatch.setattr(babeldoc, "__file__", babel_file, raising=False)
    monkeypatch.setattr(pdf2zh_next, "__file__", consumer_file, raising=False)
    monkeypatch.setattr(babeldoc, "__version__", "0.6.4.101-imported", raising=False)
    monkeypatch.setattr(pdf2zh_next, "__version__", "2.9.0-imported", raising=False)
    calls = []

    def fake_run(args, **kwargs):
        assert Path(args[0]).name == "git"
        assert list(args)[1:] == ["rev-parse", "HEAD"]
        calls.append((list(args), str(kwargs.get("cwd"))))
        cwd = str(kwargs.get("cwd"))
        if cwd.endswith("imported-babeldoc/babeldoc"):
            return SimpleNamespace(
                returncode=0,
                stdout=EXPECTED_BABELDOC_SHA + "\n",
                stderr="",
            )
        if cwd.endswith("imported-pdf2zh/pdf2zh_next"):
            return SimpleNamespace(returncode=1, stdout="", stderr="not a repository")
        raise AssertionError(cwd)

    monkeypatch.setattr(runtime_manifest.subprocess, "run", fake_run)
    manifest = runtime_manifest.collect_runtime_manifest(deeplx_script=None)
    encoded = json.dumps(manifest)
    assert set(manifest) == MANIFEST_KEYS
    assert manifest["schema_version"] == 1
    assert manifest["python_version"] == platform.python_version()
    assert manifest["babeldoc_path"] == babel_file
    assert manifest["pdf2zh_next_path"] == consumer_file
    assert manifest["babeldoc_version"] == "0.6.4.101-imported"
    assert manifest["pdf2zh_next_version"] == "2.9.0-imported"
    assert manifest["babeldoc_git_revision"] == EXPECTED_BABELDOC_SHA
    assert manifest["pdf2zh_next_git_revision"] is None
    assert manifest["deeplx_sha256"] is None
    assert manifest["clitranslator_impl_schema"] == "1"
    for marker in MOUNT_MARKERS:
        assert marker not in encoded
    assert calls[0][1].endswith("imported-babeldoc/babeldoc")
    assert calls[1][1].endswith("imported-pdf2zh/pdf2zh_next")


@pytest.mark.parametrize("stdout", ["main\n", "latest\n", "abc\n"])
def test_non_sha_git_output_is_null(monkeypatch, stdout: str):
    runtime_manifest = _manifest_module()

    def fake_run(args, **kwargs):
        assert Path(args[0]).name == "git"
        assert list(args)[1:] == ["rev-parse", "HEAD"]
        assert "cwd" in kwargs
        return SimpleNamespace(returncode=0, stdout=stdout, stderr="")

    monkeypatch.setattr(runtime_manifest.subprocess, "run", fake_run)
    manifest = runtime_manifest.collect_runtime_manifest(deeplx_script=None)
    assert manifest["babeldoc_git_revision"] is None
    assert manifest["pdf2zh_next_git_revision"] is None


def test_git_failure_does_not_block_collection(monkeypatch):
    runtime_manifest = _manifest_module()

    def fake_run(args, **kwargs):
        assert args
        assert "cwd" in kwargs
        raise OSError("git is unavailable")

    monkeypatch.setattr(runtime_manifest.subprocess, "run", fake_run)
    manifest = runtime_manifest.collect_runtime_manifest(deeplx_script=None)
    assert manifest["babeldoc_git_revision"] is None
    assert manifest["pdf2zh_next_git_revision"] is None
    assert manifest["schema_version"] == 1


def test_distribution_versions_follow_metadata_or_null(monkeypatch):
    import importlib.metadata as metadata

    runtime_manifest = _manifest_module()

    def fake_version(name: str) -> str:
        if name == "babeldoc":
            return "9.9.9-fixture"
        if name == "pdf2zh-next":
            raise metadata.PackageNotFoundError(name)
        raise AssertionError(name)

    monkeypatch.setattr(metadata, "version", fake_version)
    manifest = runtime_manifest.collect_runtime_manifest(deeplx_script=None)
    assert manifest["babeldoc_distribution_version"] == "9.9.9-fixture"
    assert manifest["pdf2zh_next_distribution_version"] is None
    assert "latest" not in json.dumps(manifest)


def test_missing_deeplx_script_names_the_path(tmp_path: Path):
    runtime_manifest = _manifest_module()
    missing = tmp_path / "missing-deeplx.py"
    directory = tmp_path / "not-a-file"
    directory.mkdir()
    with pytest.raises(ValueError, match=re.escape(str(missing))):
        runtime_manifest.collect_runtime_manifest(deeplx_script=missing)
    with pytest.raises(ValueError, match=re.escape(str(directory))):
        runtime_manifest.collect_runtime_manifest(deeplx_script=directory)


def test_deeplx_sha256_changes_with_file_contents(tmp_path: Path):
    runtime_manifest = _manifest_module()
    first = tmp_path / "one.py"
    second = tmp_path / "two.py"
    first.write_bytes(b"alpha\n")
    second.write_bytes(b"beta\n")
    first_digest = runtime_manifest.collect_runtime_manifest(deeplx_script=first)[
        "deeplx_sha256"
    ]
    second_digest = runtime_manifest.collect_runtime_manifest(deeplx_script=second)[
        "deeplx_sha256"
    ]
    assert first_digest == hashlib.sha256(b"alpha\n").hexdigest()
    assert second_digest == hashlib.sha256(b"beta\n").hexdigest()
    assert first_digest != second_digest


def test_manifest_omits_fixture_secret_endpoint_and_script_body(
    tmp_path: Path, monkeypatch
):
    runtime_manifest = _manifest_module()
    script = tmp_path / "deeplx.py"
    script.write_text(
        f"KEY = {FIXTURE_KEY!r}\nENDPOINT = {FIXTURE_ENDPOINT!r}\n",
        encoding="utf-8",
    )
    marker = tmp_path / "executed"
    script.write_text(
        script.read_text(encoding="utf-8")
        + f"open({str(marker)!r}, 'w').write('ran')\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("PDF2ZH_TEST_KEY", FIXTURE_KEY)
    monkeypatch.setenv("PDF2ZH_TEST_ENDPOINT", FIXTURE_ENDPOINT)
    monkeypatch.setattr(
        sys,
        "argv",
        ["pdf2zh", "--key", FIXTURE_KEY, "--endpoint", FIXTURE_ENDPOINT],
    )
    manifest = runtime_manifest.collect_runtime_manifest(deeplx_script=script)
    encoded = json.dumps(manifest)
    assert FIXTURE_KEY not in encoded
    assert FIXTURE_ENDPOINT not in encoded
    assert "fixture.invalid" not in encoded
    assert not marker.exists()
    assert set(manifest) == MANIFEST_KEYS


def test_cli_writes_only_the_requested_report(tmp_path: Path):
    runtime_manifest = _manifest_module()
    script = tmp_path / "deeplx.py"
    script.write_bytes(b"print('not-executed')\n")
    out = tmp_path / "report" / "manifest.json"
    out.parent.mkdir()
    assert (
        runtime_manifest.main(["--out", str(out), "--deeplx-script", str(script)]) == 0
    )
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written == runtime_manifest.collect_runtime_manifest(deeplx_script=script)
    assert list(out.parent.iterdir()) == [out]


def test_cli_does_not_write_a_report_for_a_missing_script(tmp_path: Path):
    runtime_manifest = _manifest_module()
    missing = tmp_path / "absent.py"
    out = tmp_path / "manifest.json"
    with pytest.raises(ValueError, match=re.escape(str(missing))):
        runtime_manifest.main(["--out", str(out), "--deeplx-script", str(missing)])
    assert not out.exists()


def test_collect_rejects_positional_script():
    runtime_manifest = _manifest_module()
    with pytest.raises(TypeError):
        runtime_manifest.collect_runtime_manifest(None)
