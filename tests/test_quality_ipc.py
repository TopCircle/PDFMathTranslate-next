"""Consumer IPC and the final GUI batch keep per-file quality."""

from __future__ import annotations

import asyncio
import json
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gui_config_isolation import install_home_config_write_guard
from gui_config_isolation import isolate_gui_config
from gui_config_isolation import snapshot_home_config

CALLBACK_OUTPUTS = 19
DEGRADED_MESSAGE = "文件已生成，1 项需复核"
SUCCESS_MESSAGE = "翻译完成"
UNKNOWN_MESSAGE = "文件已生成，未提供质量报告"
FAILED_PARTS_MESSAGE = "文件已生成，部分段落未排入"


class ProgressLog:
    def __init__(self):
        self.calls = []

    def __call__(self, value=None, desc=None, **kwargs):
        self.calls.append({"value": value, "desc": desc})


def _state() -> dict:
    return {
        "session_id": None,
        "current_task": None,
        "results": {},
        "file_order": [],
        "display_map": {},
        "parent_map": {},
        "uploaded_files": [],
    }


def _settings():
    return SimpleNamespace(basic=SimpleNamespace(input_files=set(), debug=False))


@pytest.fixture
def isolated_gui(tmp_path, monkeypatch):
    before = snapshot_home_config()
    config_dir = isolate_gui_config(tmp_path)
    install_home_config_write_guard(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["pytest"])
    import pdf2zh_next.gui as gui

    yield gui, config_dir
    assert snapshot_home_config() == before


def _write_report(path: Path, status: str) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "run_id": path.name.split(".")[1],
                "status": status,
                "issues": [],
            }
        ),
        encoding="utf-8",
    )


def _finish_result(file_path: Path, spec: dict):
    from babeldoc.format.pdf.translation_config import TranslateResult

    stem = file_path.stem
    mono = file_path.with_name(f"{stem}.mono.pdf")
    dual = file_path.with_name(f"{stem}.dual.pdf")
    mono.write_bytes(b"%PDF-mono")
    dual.write_bytes(b"%PDF-dual")
    result = TranslateResult(mono, dual)
    result.original_pdf_path = str(file_path)
    result.total_seconds = 0.2
    if not spec.get("omit_quality"):
        result.quality_status = spec["status"]
        result.quality_warning_count = spec["warning_count"]
        result.quality_report_path = spec.get("report")
    return result


def _patch_translation(monkeypatch, gui, specs: dict, mode: str = "finish"):
    seen = []

    async def fake_stream(_settings, file_path):
        seen.append(Path(file_path))
        if mode == "cancel":
            raise asyncio.CancelledError
        if mode == "error":
            yield {"type": "error", "error": "boom", "details": ""}
            return
        spec = specs[Path(file_path).name]
        result = _finish_result(Path(file_path), spec)
        yield {
            "type": "finish",
            "translate_result": result,
            "token_usage": {
                "main": {
                    "total": 3,
                    "prompt": 2,
                    "cache_hit_prompt": 0,
                    "completion": 1,
                }
            },
        }

    lengths = []
    original = gui._run_translation_task

    async def wrapped(*args, **kwargs):
        result = await original(*args, **kwargs)
        lengths.append(len(result))
        return result

    monkeypatch.setattr(gui, "do_translate_async_stream", fake_stream)
    monkeypatch.setattr(gui, "build_translate_settings", lambda *args, **kwargs: _settings())
    monkeypatch.setattr(gui, "_run_translation_task", wrapped)
    return seen, lengths


async def _collect(gui, state, files, progress):
    holder = {"state": state}

    def fake_ui(*_args):
        return {"state": holder["state"]}

    gui.build_ui_inputs = fake_ui
    items = []
    async for item in gui.translate_files("File", files, "", progress=progress):
        items.append(item)
    return items


def _run(gui, state, files, progress, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    return asyncio.run(_collect(gui, state, files, progress))


def _bind_ui(monkeypatch, gui, state):
    holder = {"state": state}

    def fake_ui(*_args):
        return {"state": holder["state"]}

    monkeypatch.setattr(gui, "build_ui_inputs", fake_ui)
    return holder


def test_quality_fields_survive_real_pipe(tmp_path):
    from multiprocessing import Pipe

    from babeldoc.format.pdf.translation_config import TranslateResult
    from pdf2zh_next.high_level import attach_quality_to_event

    report = tmp_path / "book.runpipe.quality.json"
    report.write_text('{"status":"degraded"}', encoding="utf-8")
    mono = tmp_path / "mono.pdf"
    dual = tmp_path / "dual.pdf"
    mono.write_bytes(b"%PDF")
    dual.write_bytes(b"%PDF")
    result = TranslateResult(mono, dual)
    result.quality_status = "degraded"
    result.quality_warning_count = 1
    result.quality_report_path = report
    event = {"type": "finish", "translate_result": result}
    attach_quality_to_event(event)

    recv, send = Pipe(duplex=False)
    try:
        send.send(event)
    finally:
        send.close()
    got = recv.recv()
    assert got["quality_status"] == "degraded"
    assert got["quality_warning_count"] == 1
    assert got["quality_report_path"] == str(report)
    assert got["translate_result"].quality_status == "degraded"
    assert got["translate_result"].quality_warning_count == 1


def test_do_translate_file_async_logs_quality(tmp_path, monkeypatch, caplog):
    import logging

    from babeldoc.format.pdf.translation_config import TranslateResult
    from pdf2zh_next import high_level

    report = tmp_path / "book.runlog.quality.json"
    report.write_text("{}", encoding="utf-8")
    mono = tmp_path / "mono.pdf"
    dual = tmp_path / "dual.pdf"
    mono.write_bytes(b"%PDF")
    dual.write_bytes(b"%PDF")
    source = tmp_path / "book.pdf"
    source.write_bytes(b"%PDF")

    async def fake_stream(_settings, file):
        result = TranslateResult(mono, dual)
        result.original_pdf_path = str(file)
        result.total_seconds = 0.5
        result.quality_status = "degraded"
        result.quality_warning_count = 1
        result.quality_report_path = report
        yield {"type": "finish", "translate_result": result, "token_usage": {}}

    monkeypatch.setattr(high_level, "do_translate_async_stream", fake_stream)
    settings = _settings()
    settings.basic.input_files = {source}
    with caplog.at_level(logging.INFO, logger="pdf2zh_next.high_level"):
        asyncio.run(high_level.do_translate_file_async(settings))
    text = caplog.text
    assert "degraded" in text
    assert "runlog.quality.json" in text
    assert "1" in text


def test_run_translation_task_keeps_four_tuple(isolated_gui, tmp_path, monkeypatch):
    gui, _config_dir = isolated_gui
    source = tmp_path / "kept.pdf"
    source.write_bytes(b"%PDF")
    report = tmp_path / "kept.runkept.quality.json"
    _write_report(report, "degraded")
    specs = {
        "kept.pdf": {
            "status": "degraded",
            "warning_count": 1,
            "report": report,
        }
    }

    async def fake_stream(_settings, file_path):
        result = _finish_result(Path(file_path), specs["kept.pdf"])
        yield {
            "type": "finish",
            "translate_result": result,
            "token_usage": {"main": {"total": 3, "prompt": 1, "cache_hit_prompt": 0, "completion": 1}},
        }

    monkeypatch.setattr(gui, "do_translate_async_stream", fake_stream)
    state = _state()
    mono, dual, glossary, token_usage = asyncio.run(
        gui._run_translation_task(
            _settings(),
            source,
            state,
            ProgressLog(),
        )
    )
    assert glossary is None
    assert mono is not None and dual is not None
    assert token_usage["main"]["total"] == 3
    stored = state["quality_by_file"][str(source.resolve())]
    assert stored["status"] == "degraded"
    assert stored["warning_count"] == 1
    assert stored["report_path"] == str(report)


def test_final_batch_callback_preserves_degraded_quality(isolated_gui, tmp_path, monkeypatch):
    gui, _config_dir = isolated_gui
    ok = tmp_path / "ok.pdf"
    bad = tmp_path / "bad.pdf"
    ok.write_bytes(b"%PDF-ok")
    bad.write_bytes(b"%PDF-bad")
    ok_report = tmp_path / "ok.runok.quality.json"
    bad_report = tmp_path / "bad.runbad.quality.json"
    _write_report(ok_report, "success")
    _write_report(bad_report, "degraded")
    specs = {
        "ok.pdf": {"status": "success", "warning_count": 0, "report": ok_report},
        "bad.pdf": {"status": "degraded", "warning_count": 1, "report": bad_report},
    }
    _seen, lengths = _patch_translation(monkeypatch, gui, specs)
    state = _state()
    _bind_ui(monkeypatch, gui, state)
    progress = ProgressLog()
    yields = _run(gui, state, [ok, bad], progress, monkeypatch, tmp_path)

    assert len(yields) == 3
    assert all(len(item) == CALLBACK_OUTPUTS for item in yields)
    assert lengths == [4, 4]
    final = yields[-1]
    assert final[7]["value"] == DEGRADED_MESSAGE
    assert progress.calls[-1]["desc"] == DEGRADED_MESSAGE
    assert progress.calls[-1]["value"] == 1.0
    assert "All translations complete" not in (progress.calls[-1]["desc"] or "")
    assert "## Translated" not in final[7]["value"]

    ok_quality = state["results"]["ok.pdf"]["quality"]
    bad_quality = state["results"]["bad.pdf"]["quality"]
    assert ok_quality["status"] == "success"
    assert ok_quality["warning_count"] == 0
    assert bad_quality["status"] == "degraded"
    assert bad_quality["warning_count"] == 1
    assert ok_quality is not bad_quality
    assert state["quality_by_file"] == {}
    assert bad_quality["status"] == "degraded"
    assert Path(state["results"]["bad.pdf"]["mono"]).exists()
    assert Path(state["results"]["bad.pdf"]["dual"]).exists()
    assert Path(final[0]).exists()
    assert final[4]["visible"] is True
    assert final[5]["visible"] is True
    assert state["results"]["bad.pdf"]["token_usage"]["main"]["total"] == 3

    with zipfile.ZipFile(final[11]) as archive:
        names = archive.namelist()
        assert "ok.runok.quality.json" in names
        assert "bad.runbad.quality.json" in names
        bad_payload = json.loads(archive.read("bad.runbad.quality.json"))
        ok_payload = json.loads(archive.read("ok.runok.quality.json"))
    assert bad_payload["status"] == "degraded"
    assert ok_payload["status"] == "success"
    with zipfile.ZipFile(final[13]) as archive:
        assert all(not name.endswith(".quality.json") for name in archive.namelist())
    with zipfile.ZipFile(final[15]) as archive:
        assert all(not name.endswith(".quality.json") for name in archive.namelist())
    assert not hasattr(gui, "quality_by_file")


def test_two_successes_use_completion_message(isolated_gui, tmp_path, monkeypatch):
    gui, _config_dir = isolated_gui
    first = tmp_path / "one.pdf"
    second = tmp_path / "two.pdf"
    first.write_bytes(b"%PDF")
    second.write_bytes(b"%PDF")
    specs = {
        "one.pdf": {"status": "success", "warning_count": 0, "report": None},
        "two.pdf": {"status": "success", "warning_count": 0, "report": None},
    }
    _patch_translation(monkeypatch, gui, specs)
    state = _state()
    _bind_ui(monkeypatch, gui, state)
    progress = ProgressLog()
    yields = _run(gui, state, [first, second], progress, monkeypatch, tmp_path)
    assert len(yields) == 3
    assert yields[-1][7]["value"] == SUCCESS_MESSAGE
    assert progress.calls[-1]["desc"] == SUCCESS_MESSAGE
    assert state["results"]["one.pdf"]["quality"]["status"] == "success"
    assert state["results"]["two.pdf"]["quality"]["status"] == "success"


def test_missing_quality_fields_are_unknown(isolated_gui, tmp_path, monkeypatch):
    gui, _config_dir = isolated_gui
    source = tmp_path / "legacy.pdf"
    source.write_bytes(b"%PDF")
    specs = {"legacy.pdf": {"omit_quality": True}}
    _patch_translation(monkeypatch, gui, specs)
    state = _state()
    _bind_ui(monkeypatch, gui, state)
    progress = ProgressLog()
    yields = _run(gui, state, [source], progress, monkeypatch, tmp_path)
    assert len(yields) == 2
    assert yields[-1][7]["value"] == UNKNOWN_MESSAGE
    assert progress.calls[-1]["desc"] == UNKNOWN_MESSAGE
    quality = state["results"]["legacy.pdf"]["quality"]
    assert quality == {"status": None, "warning_count": 0, "report_path": None}


def test_sessions_and_next_batch_reset_quality(isolated_gui, tmp_path, monkeypatch):
    gui, _config_dir = isolated_gui
    bad = tmp_path / "bad.pdf"
    ok = tmp_path / "ok.pdf"
    nxt = tmp_path / "next.pdf"
    for path in (bad, ok, nxt):
        path.write_bytes(b"%PDF")
    specs = {
        "bad.pdf": {"status": "degraded", "warning_count": 1, "report": None},
        "ok.pdf": {"status": "success", "warning_count": 0, "report": None},
        "next.pdf": {"status": "success", "warning_count": 0, "report": None},
    }
    _patch_translation(monkeypatch, gui, specs)
    state_a = _state()
    state_b = _state()
    holder = _bind_ui(monkeypatch, gui, state_a)
    progress = ProgressLog()
    _run(gui, state_a, [bad], progress, monkeypatch, tmp_path)
    kept = state_a["results"]["bad.pdf"]["quality"]
    assert kept["status"] == "degraded"
    assert state_a["quality_by_file"] == {}

    holder["state"] = state_b
    _run(gui, state_b, [ok], progress, monkeypatch, tmp_path)
    assert "bad.pdf" not in state_b["results"]
    assert state_b["results"]["ok.pdf"]["quality"]["status"] == "success"
    assert kept["status"] == "degraded"

    holder["state"] = state_a
    _run(gui, state_a, [nxt], progress, monkeypatch, tmp_path)
    assert "bad.pdf" not in state_a["results"]
    assert state_a["results"]["next.pdf"]["quality"]["status"] == "success"
    assert state_a["quality_by_file"] == {}
    assert kept["status"] == "degraded"


def test_finished_layout_failure_still_offers_the_pdf(isolated_gui, tmp_path, monkeypatch):
    gui, _config_dir = isolated_gui
    source = tmp_path / "partial.pdf"
    source.write_bytes(b"%PDF")
    report = tmp_path / "partial.runpartial.quality.json"
    _write_report(report, "failed")
    specs = {
        "partial.pdf": {
            "status": "failed",
            "warning_count": 0,
            "report": report,
        }
    }
    _patch_translation(monkeypatch, gui, specs)
    state = _state()
    _bind_ui(monkeypatch, gui, state)
    progress = ProgressLog()
    yields = _run(gui, state, [source], progress, monkeypatch, tmp_path)

    assert yields[-1][7]["value"] == FAILED_PARTS_MESSAGE
    assert progress.calls[-1]["desc"] == FAILED_PARTS_MESSAGE
    assert Path(state["results"]["partial.pdf"]["mono"]).is_file()
    assert Path(state["results"]["partial.pdf"]["dual"]).is_file()
    assert state["results"]["partial.pdf"]["quality"]["status"] == "failed"
    assert state["results"]["partial.pdf"]["quality"]["report_path"] == str(report)


def test_failed_run_has_no_success_message(isolated_gui, tmp_path, monkeypatch):
    gui, _config_dir = isolated_gui
    import gradio as gr

    source = tmp_path / "boom.pdf"
    source.write_bytes(b"%PDF")
    _patch_translation(monkeypatch, gui, {}, mode="error")
    state = _state()
    _bind_ui(monkeypatch, gui, state)
    progress = ProgressLog()
    with pytest.raises(gr.Error):
        _run(gui, state, [source], progress, monkeypatch, tmp_path)
    assert state["results"] == {}
    assert state["quality_by_file"] == {}
    assert all(
        (call["desc"] or "") not in {SUCCESS_MESSAGE, DEGRADED_MESSAGE, UNKNOWN_MESSAGE}
        and "All translations complete" not in (call["desc"] or "")
        for call in progress.calls
    )


def test_cancelled_run_has_no_success_message(isolated_gui, tmp_path, monkeypatch):
    gui, _config_dir = isolated_gui
    source = tmp_path / "stop.pdf"
    source.write_bytes(b"%PDF")
    _patch_translation(monkeypatch, gui, {}, mode="cancel")
    state = _state()
    _bind_ui(monkeypatch, gui, state)
    progress = ProgressLog()
    yields = _run(gui, state, [source], progress, monkeypatch, tmp_path)
    assert len(yields) == 1
    assert len(yields[0]) == CALLBACK_OUTPUTS
    title = yields[0][7]
    assert title.get("visible") is False
    assert title.get("value") not in {SUCCESS_MESSAGE, DEGRADED_MESSAGE, UNKNOWN_MESSAGE}
    assert state["quality_by_file"] == {}
    assert all(
        "All translations complete" not in (call["desc"] or "") for call in progress.calls
    )
