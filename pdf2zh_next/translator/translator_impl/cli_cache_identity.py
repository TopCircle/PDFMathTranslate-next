"""Identity of the code a CLITranslator process will actually run.

The digest is fixed when the translator is constructed. Callers pass the
decomposed script (the same file the inner adapter hashes) plus any
explicit dependency paths. It does not inspect argv.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

# Bump when the canonical form below changes. Stored cache rows are left in
# place; a new schema simply misses them.
CLITRANSLATOR_IMPL_SCHEMA = "1"


def _sha256_file(path: Path) -> str:
    if not path.is_file():
        raise ValueError(f"implementation file is missing: {path}")
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ValueError(f"implementation file is unreadable: {path}") from exc
    return digest.hexdigest()


def implementation_fingerprint(paths: list[Path], *, revision: str) -> str:
    """Digest of sorted, deduplicated path contents plus ``revision``.

    Each entry is the resolved path and the SHA-256 of that file. Missing
    or unreadable files raise ValueError instead of a forged digest.
    """
    if not isinstance(revision, str):
        raise ValueError("revision must be a string")

    entries: dict[str, Path] = {}
    for raw in paths:
        path = Path(raw)
        try:
            resolved = path.expanduser().resolve(strict=False)
        except OSError as exc:
            raise ValueError(f"implementation file is unreadable: {path}") from exc
        entries.setdefault(str(resolved), resolved)

    lines = [f"{key}:{_sha256_file(entries[key])}" for key in sorted(entries)]
    lines.append(f"revision:{revision}")
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()
