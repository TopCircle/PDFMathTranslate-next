"""CLITranslator cache must change when glossary/proper-nouns file content changes."""

from pathlib import Path

from pdf2zh_next.config.translate_engine_model import CLISettings
from pdf2zh_next.translator.translator_impl.clitranslator import (
    _collect_cache_file_paths,
)
from pdf2zh_next.translator.translator_impl.clitranslator import (
    _file_content_fingerprint,
)


def test_file_content_fingerprint_changes_with_content(tmp_path: Path):
    glossary = tmp_path / "glossary.csv"
    glossary.write_text("a,b\n", encoding="utf-8")
    fp1 = _file_content_fingerprint(str(glossary))
    glossary.write_text("a,b\nc,d\n", encoding="utf-8")
    fp2 = _file_content_fingerprint(str(glossary))
    assert fp1 != fp2
    assert fp1.startswith(str(glossary))
    assert ":" in fp1


def test_file_content_fingerprint_missing(tmp_path: Path):
    missing = tmp_path / "nope.csv"
    fp = _file_content_fingerprint(str(missing))
    assert fp.startswith("missing:")


def test_collect_paths_from_settings_and_argv(tmp_path: Path):
    g = tmp_path / "g.csv"
    p = tmp_path / "p.csv"
    g.write_text("x\n", encoding="utf-8")
    p.write_text("y\n", encoding="utf-8")
    extra = tmp_path / "extra.csv"
    extra.write_text("z\n", encoding="utf-8")

    settings = CLISettings(
        clitranslator_program="python3",
        clitranslator_glossary=str(g),
        clitranslator_proper_nouns=str(p),
    )
    # Same paths again via argv should not duplicate
    parts = [
        "python3",
        "deeplx.py",
        "--glossary",
        str(g),
        "--proper-nouns",
        str(p),
        "--glossary",
        str(extra),
    ]
    paths = _collect_cache_file_paths(settings, parts)
    assert paths == [str(g), str(p), str(extra)]


def test_collect_paths_from_equals_form_flag():
    settings = CLISettings(clitranslator_program="python3")
    parts = ["tool", "--glossary=/data/g.csv", "--proper-nouns=/data/p.csv"]
    assert _collect_cache_file_paths(settings, parts) == [
        "/data/g.csv",
        "/data/p.csv",
    ]
