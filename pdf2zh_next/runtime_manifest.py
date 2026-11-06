"""Collect the code this process actually imported.

The manifest is a whitelist. It does not read settings, the environment,
argv, or the DeepLX script body, and it does not start a translation.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import re
import shutil
import subprocess
import types
from pathlib import Path

import babeldoc

import pdf2zh_next
from pdf2zh_next.translator.translator_impl.cli_cache_identity import (
    CLITRANSLATOR_IMPL_SCHEMA,
)

_FULL_SHA = re.compile(r"^[0-9a-f]{40}$")


def _module_file(module: types.ModuleType) -> str | None:
    module_file = getattr(module, "__file__", None)
    if not isinstance(module_file, str) or module_file == "":
        return None
    return module_file


def _module_version(module: types.ModuleType) -> str | None:
    version = getattr(module, "__version__", None)
    if not isinstance(version, str) or version == "":
        return None
    return version


def _distribution_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _git_revision(module_file: str | None) -> str | None:
    """Return ``git rev-parse HEAD`` beside the imported module.

    A missing git binary, a non-repository, or any answer that is not a
    full lowercase SHA becomes null. Branch names are not revisions.
    """
    if module_file is None:
        return None
    git = shutil.which("git")
    if git is None:
        return None
    try:
        completed = subprocess.run(
            [git, "rev-parse", "HEAD"],
            cwd=Path(module_file).parent,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    revision = completed.stdout.strip()
    if _FULL_SHA.fullmatch(revision):
        return revision
    return None


def _deeplx_sha256(script: Path | None) -> str | None:
    if script is None:
        return None
    path = Path(script)
    if not path.is_file():
        raise ValueError(f"DeepLX script is not a file: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def collect_runtime_manifest(*, deeplx_script: Path | None) -> dict[str, object]:
    """Return the whitelist manifest for the modules this process imported."""
    babeldoc_file = _module_file(babeldoc)
    consumer_file = _module_file(pdf2zh_next)
    return {
        "schema_version": 1,
        "python_version": platform.python_version(),
        "babeldoc_path": babeldoc_file,
        "babeldoc_version": _module_version(babeldoc),
        "babeldoc_git_revision": _git_revision(babeldoc_file),
        "pdf2zh_next_path": consumer_file,
        "pdf2zh_next_version": _module_version(pdf2zh_next),
        "pdf2zh_next_git_revision": _git_revision(consumer_file),
        "babeldoc_distribution_version": _distribution_version("babeldoc"),
        "pdf2zh_next_distribution_version": _distribution_version("pdf2zh-next"),
        "deeplx_sha256": _deeplx_sha256(deeplx_script),
        "clitranslator_impl_schema": CLITRANSLATOR_IMPL_SCHEMA,
    }


def main(argv: list[str] | None = None) -> int:
    """Write one manifest JSON file. Do not translate."""
    parser = argparse.ArgumentParser(
        description="Write a runtime provenance manifest. Does not translate.",
    )
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--deeplx-script", type=Path, default=None)
    args = parser.parse_args(argv)
    manifest = collect_runtime_manifest(deeplx_script=args.deeplx_script)
    args.out.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
