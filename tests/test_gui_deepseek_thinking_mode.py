import sys
from pathlib import Path

from pdf2zh_next.config.cli_env_model import CLIEnvSettingsModel


def _gui(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["pytest"])
    import pdf2zh_next.gui as gui

    return gui


def _base_gui_inputs(**overrides):
    inputs = {
        "service": "DeepSeek",
        "lang_from": "English",
        "lang_to": "Simplified Chinese",
        "page_range": "All",
        "page_input": "",
        "prompt": "",
        "ignore_cache": False,
        "no_mono": False,
        "no_dual": False,
        "dual_translate_first": False,
        "use_alternating_pages_dual": False,
        "watermark_output_mode": "Watermarked",
        "rate_limit_mode": "Custom",
        "custom_qps": 4,
        "custom_pool_workers": None,
        "min_text_length": 5,
        "rpc_doclayout": "",
        "enable_auto_term_extraction": True,
        "primary_font_family": "Auto",
        "skip_clean": False,
        "disable_rich_text_translate": False,
        "enhance_compatibility": False,
        "split_short_lines": False,
        "short_line_split_factor": 0.8,
        "translate_table_text": False,
        "skip_scanned_detection": False,
        "ocr_workaround": False,
        "max_pages_per_part": 0,
        "formular_font_pattern": "",
        "formular_char_pattern": "",
        "auto_enable_ocr_workaround": False,
        "only_include_translated_page": False,
        "merge_alternating_line_numbers": True,
        "remove_non_formula_lines": True,
        "non_formula_line_iou_threshold": 0.5,
        "figure_table_protection_threshold": 0.5,
        "skip_formula_offset_calculation": False,
        "term_service": "Follow main translation engine",
        "term_rate_limit_mode": "Custom",
        "term_rpm_input": 240,
        "term_concurrent_threads": 20,
        "term_custom_qps": 4,
        "term_custom_pool_workers": None,
        "custom_system_prompt_input": "",
        "glossaries": None,
        "save_auto_extracted_glossary": False,
        "deepseek_model": "deepseek-v4-flash",
        "deepseek_api_key": "dummy-key",
        "deepseek_enable_json_mode": False,
        "deepseek_thinking_enabled": False,
        "deepseek_reasoning_effort": "high",
    }
    inputs.update(overrides)
    return inputs


def _build_settings(tmp_path: Path, ui_inputs: dict, gui, save_mode=None):
    if save_mode is None:
        save_mode = gui.SaveMode.never
    input_pdf = tmp_path / "input.pdf"
    input_pdf.write_bytes(b"%PDF-1.4\n")
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    return gui._build_translate_settings(
        CLIEnvSettingsModel(), input_pdf, output_dir, save_mode, ui_inputs
    )


def test_gui_deepseek_thinking_choices_are_explicit_boolean_modes(monkeypatch):
    gui = _gui(monkeypatch)

    assert gui.DEEPSEEK_THINKING_CHOICES == [
        ("Disabled (non-thinking)", False),
        ("Enabled (thinking)", True),
    ]


def test_gui_deepseek_radio_updates_do_not_send_nested_skip(monkeypatch):
    gui = _gui(monkeypatch)

    main_update = gui._deepseek_detail_update("deepseek_thinking_enabled", True)
    term_update = gui._deepseek_detail_update(
        "term_deepseek_thinking_enabled", True
    )
    reasoning_update = gui._deepseek_detail_update(
        "deepseek_reasoning_effort", True
    )

    assert "value" not in main_update
    assert "value" not in term_update
    assert reasoning_update["choices"] == ["high", "max"]
    assert reasoning_update["value"] == "high"


def test_gui_deepseek_reasoning_effort_update_preserves_current_value(monkeypatch):
    gui = _gui(monkeypatch)

    enabled_update = gui._deepseek_reasoning_effort_update(
        visible=True,
        current_value="max",
    )
    disabled_update = gui._deepseek_reasoning_effort_update(
        visible=False,
        current_value="max",
    )

    assert enabled_update["choices"] == ["high", "max"]
    assert enabled_update["value"] == "max"
    assert enabled_update["visible"] is True
    assert disabled_update["value"] == "max"
    assert disabled_update["visible"] is False


def test_gui_disabled_deepseek_current_run_omits_reasoning_effort(tmp_path, monkeypatch):
    gui = _gui(monkeypatch)

    settings = _build_settings(
        tmp_path,
        _base_gui_inputs(
            deepseek_thinking_enabled=False,
            deepseek_reasoning_effort="max",
        ),
        gui,
    )

    assert settings.translate_engine_settings._openai_extra_body == {
        "thinking": {"type": "disabled"}
    }
    assert settings.translate_engine_settings.openai_send_reasoning_effort is None
    assert settings.translate_engine_settings.openai_reasoning_effort is None


def test_gui_enabled_deepseek_defaults_reasoning_effort_to_high(tmp_path, monkeypatch):
    gui = _gui(monkeypatch)

    settings = _build_settings(
        tmp_path,
        _base_gui_inputs(
            deepseek_thinking_enabled=True,
            deepseek_reasoning_effort="high",
        ),
        gui,
    )

    assert settings.translate_engine_settings._openai_extra_body == {
        "thinking": {"type": "enabled"}
    }
    assert settings.translate_engine_settings.openai_send_reasoning_effort is True
    assert settings.translate_engine_settings.openai_reasoning_effort == "high"


def test_gui_enabled_deepseek_accepts_max_reasoning_effort(tmp_path, monkeypatch):
    gui = _gui(monkeypatch)

    settings = _build_settings(
        tmp_path,
        _base_gui_inputs(
            deepseek_thinking_enabled=True,
            deepseek_reasoning_effort="max",
        ),
        gui,
    )

    assert settings.translate_engine_settings.openai_reasoning_effort == "max"


def test_term_deepseek_uses_same_boolean_thinking_controls(tmp_path, monkeypatch):
    gui = _gui(monkeypatch)

    settings = _build_settings(
        tmp_path,
        _base_gui_inputs(
            term_service="DeepSeek",
            term_deepseek_model="deepseek-v4-flash",
            term_deepseek_api_key="dummy-key",
            term_deepseek_enable_json_mode=False,
            term_deepseek_thinking_enabled=True,
            term_deepseek_reasoning_effort="max",
        ),
        gui,
    )

    assert settings.term_extraction_engine_settings._openai_extra_body == {
        "thinking": {"type": "enabled"}
    }
    assert settings.term_extraction_engine_settings.openai_reasoning_effort == "max"


def test_disabled_term_deepseek_current_run_omits_reasoning_effort(
    tmp_path, monkeypatch
):
    gui = _gui(monkeypatch)

    settings = _build_settings(
        tmp_path,
        _base_gui_inputs(
            term_service="DeepSeek",
            term_deepseek_model="deepseek-v4-flash",
            term_deepseek_api_key="dummy-key",
            term_deepseek_enable_json_mode=False,
            term_deepseek_thinking_enabled=False,
            term_deepseek_reasoning_effort="max",
        ),
        gui,
    )

    assert settings.term_extraction_engine_settings._openai_extra_body == {
        "thinking": {"type": "disabled"}
    }
    assert settings.term_extraction_engine_settings.openai_send_reasoning_effort is None
    assert settings.term_extraction_engine_settings.openai_reasoning_effort is None


def test_gui_config_save_persists_selected_deepseek_thinking_settings(
    tmp_path, monkeypatch
):
    gui = _gui(monkeypatch)

    captured = {}

    class FakeConfigManager:
        config_cli_settings = CLIEnvSettingsModel()

        def write_user_default_config_file(self, settings):
            captured["settings"] = settings.clone()

    monkeypatch.setattr(gui, "config_manager", FakeConfigManager())

    _build_settings(
        tmp_path,
        _base_gui_inputs(
            deepseek_thinking_enabled=True,
            deepseek_reasoning_effort="max",
            term_service="DeepSeek",
            term_deepseek_model="deepseek-v4-flash",
            term_deepseek_api_key="dummy-key",
            term_deepseek_enable_json_mode=False,
            term_deepseek_thinking_enabled=False,
            term_deepseek_reasoning_effort="high",
        ),
        gui,
        save_mode=gui.SaveMode.always,
    )

    saved = captured["settings"]
    assert saved.deepseek_detail.deepseek_thinking_enabled is True
    assert saved.deepseek_detail.deepseek_reasoning_effort == "max"
    assert saved.term_deepseek_detail.term_deepseek_thinking_enabled is False
    assert saved.term_deepseek_detail.term_deepseek_reasoning_effort == "high"


def test_gui_config_save_preserves_disabled_deepseek_reasoning_effort(
    tmp_path, monkeypatch
):
    gui = _gui(monkeypatch)

    captured = {}

    class FakeConfigManager:
        config_cli_settings = CLIEnvSettingsModel()

        def write_user_default_config_file(self, settings):
            captured["settings"] = settings.clone()

    monkeypatch.setattr(gui, "config_manager", FakeConfigManager())

    _build_settings(
        tmp_path,
        _base_gui_inputs(
            deepseek_thinking_enabled=False,
            deepseek_reasoning_effort="max",
            term_service="DeepSeek",
            term_deepseek_model="deepseek-v4-flash",
            term_deepseek_api_key="dummy-key",
            term_deepseek_enable_json_mode=False,
            term_deepseek_thinking_enabled=False,
            term_deepseek_reasoning_effort="max",
        ),
        gui,
        save_mode=gui.SaveMode.always,
    )

    saved = captured["settings"]
    assert saved.deepseek_detail.deepseek_thinking_enabled is False
    assert saved.deepseek_detail.deepseek_reasoning_effort == "max"
    assert saved.term_deepseek_detail.term_deepseek_thinking_enabled is False
    assert saved.term_deepseek_detail.term_deepseek_reasoning_effort == "max"
