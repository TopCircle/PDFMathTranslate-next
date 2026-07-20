"""Build SettingsModel from Gradio UI inputs.

Extracted from gui.py for maintainability.
"""

from __future__ import annotations

import logging
import typing
from enum import Enum
from pathlib import Path
from string import Template

import gradio as gr

from pdf2zh_next.config.cli_env_model import CLIEnvSettingsModel
from pdf2zh_next.config.model import SettingsModel
from pdf2zh_next.config.translate_engine_model import GUI_PASSWORD_FIELDS
from pdf2zh_next.config.translate_engine_model import GUI_SENSITIVE_FIELDS
from pdf2zh_next.config.translate_engine_model import TERM_EXTRACTION_ENGINE_METADATA
from pdf2zh_next.config.translate_engine_model import TERM_EXTRACTION_ENGINE_METADATA_MAP
from pdf2zh_next.config.translate_engine_model import TRANSLATION_ENGINE_METADATA
from pdf2zh_next.config.translate_engine_model import TRANSLATION_ENGINE_METADATA_MAP

logger = logging.getLogger(__name__)


class SaveMode(Enum):
    """Enum for configuration save behavior."""

    follow_settings = "follow_settings"
    never = "never"
    always = "always"


def _type_hint_allows_none(type_hint: typing.Any) -> bool:
    return type(None) in typing.get_args(type_hint)


def _validate_rate_limit_inputs(
    true_rate_limit_mode: str, **inputs
) -> tuple[bool, str]:
    """
    Validate rate limit inputs

    Returns:
        tuple: (is_valid, error_message)
    """
    if true_rate_limit_mode == "RPM":
        rpm = inputs.get("rpm_input", 0)
        if not isinstance(rpm, int | float) or rpm <= 0:
            return False, "RPM must be a positive integer"

        if isinstance(rpm, float):
            if not rpm.is_integer():
                return False, "RPM must be a positive integer"

    elif true_rate_limit_mode == "Concurrent Threads":
        threads = inputs.get("concurrent_threads", 0)
        if not isinstance(threads, int | float) or threads <= 0:
            return False, "Concurrent threads must be a positive integer"

        if isinstance(threads, float):
            if not threads.is_integer():
                return False, "Concurrent threads must be a positive integer"

    elif true_rate_limit_mode == "Custom":
        qps = inputs.get("custom_qps", 0)
        pool_workers = inputs.get("custom_pool_workers")

        if not isinstance(qps, int | float) or qps <= 0:
            return False, "QPS must be a positive integer"

        if isinstance(qps, float):
            if not qps.is_integer():
                return False, "QPS must be a positive integer"

        if pool_workers is not None and (
            not isinstance(pool_workers, int | float) or pool_workers < 0
        ):
            return False, "Pool workers must be a non-negative integer"

        if isinstance(pool_workers, float):
            if not pool_workers.is_integer():
                return False, "Pool workers must be a non-negative integer"

    return True, ""


def _calculate_rate_limit_params(
    rate_limit_mode: str, ui_inputs: dict, default_qps: int = 4
) -> tuple[int, int | None]:
    """
    Calculate QPS and pool workers based on rate limit mode

    Args:
        rate_limit_mode: Rate limit mode ("RPM", "Concurrent Threads", "Custom")
        ui_inputs: User input parameters dictionary
        default_qps: Default QPS value

    Returns:
        tuple: (qps, pool_max_workers)

    Raises:
        ValueError: When input parameter validation fails
    """
    # Validate input parameters
    is_valid, error_msg = _validate_rate_limit_inputs(
        true_rate_limit_mode=rate_limit_mode, **ui_inputs
    )
    if not is_valid:
        logger.warning(f"Rate limit validation failed: {error_msg}")
        raise ValueError(error_msg)

    if rate_limit_mode == "RPM":
        rpm: int = ui_inputs.get("rpm_input", 240)
        qps = max(1, rpm // 60)
        pool_workers = min(1000, qps * 10)

    elif rate_limit_mode == "Concurrent Threads":
        # NOTE: ui_inputs keys are normalized by build_ui_inputs():
        # - concurrent_threads (mapped from concurrent_threads_input in UI)
        threads: int = ui_inputs.get("concurrent_threads", 40)
        # Ensure at least 1 worker, at most 1000 workers, using a safer calculation method
        pool_workers = min(1000, max(1, min(int(threads * 0.9), max(1, threads - 20))))
        qps = max(1, pool_workers)

    else:  # Custom
        # NOTE: ui_inputs keys are normalized by build_ui_inputs():
        # - custom_qps (mapped from custom_qps_input in UI)
        # - custom_pool_workers (mapped from custom_pool_max_workers_input in UI)
        qps = ui_inputs.get("custom_qps", default_qps)
        pool_workers = ui_inputs.get("custom_pool_workers")
        qps = int(qps)
        pool_workers = int(pool_workers) if pool_workers and pool_workers > 0 else None

    logger.info(f"QPS: {qps}, Pool Workers: {pool_workers}")

    return qps, pool_workers if pool_workers and pool_workers > 0 else None


def build_translate_settings(
    base_settings: CLIEnvSettingsModel,
    file_path: Path,
    output_dir: Path,
    save_mode: SaveMode,
    ui_inputs: dict,
) -> SettingsModel:
    """
    This function builds translation settings from UI inputs.

    Inputs:
        - base_settings: The base settings model to build upon
        - file_path: The path to the input file
        - output_dir: The output directory
        - save_mode: SaveMode enum indicating when to save config
        - ui_inputs: A dictionary of UI inputs

    Returns:
        - A configured SettingsModel instance
    """
    # Clone base settings to avoid modifying the original
    translate_settings = base_settings.clone()

    from pdf2zh_next import gui as gui_mod

    config_manager = gui_mod.config_manager
    lang_map = gui_mod.lang_map
    page_map = gui_mod.page_map
    disable_gui_sensitive_input = gui_mod.disable_gui_sensitive_input
    original_output = translate_settings.translation.output
    original_pages = translate_settings.pdf.pages
    original_gui_settings = config_manager.config_cli_settings.gui_settings

    # Extract UI values
    service = ui_inputs.get("service")
    lang_from = ui_inputs.get("lang_from")
    lang_to = ui_inputs.get("lang_to")
    page_range = ui_inputs.get("page_range")
    page_input = ui_inputs.get("page_input")
    prompt = ui_inputs.get("prompt")
    ignore_cache = ui_inputs.get("ignore_cache")

    # PDF Output Options
    no_mono = ui_inputs.get("no_mono")
    no_dual = ui_inputs.get("no_dual")
    dual_translate_first = ui_inputs.get("dual_translate_first")
    use_alternating_pages_dual = ui_inputs.get("use_alternating_pages_dual")
    watermark_output_mode = ui_inputs.get("watermark_output_mode")

    # Rate Limit Options
    rate_limit_mode = ui_inputs.get("rate_limit_mode")

    # Advanced Translation Options
    min_text_length = ui_inputs.get("min_text_length")
    rpc_doclayout = ui_inputs.get("rpc_doclayout")
    enable_auto_term_extraction = ui_inputs.get("enable_auto_term_extraction")
    primary_font_family = ui_inputs.get("primary_font_family")

    # Advanced PDF Options
    skip_clean = ui_inputs.get("skip_clean")
    disable_rich_text_translate = ui_inputs.get("disable_rich_text_translate")
    enhance_compatibility = ui_inputs.get("enhance_compatibility")
    split_short_lines = ui_inputs.get("split_short_lines")
    short_line_split_factor = ui_inputs.get("short_line_split_factor")
    translate_table_text = ui_inputs.get("translate_table_text")
    translate_figure_text = ui_inputs.get("translate_figure_text")
    skip_scanned_detection = ui_inputs.get("skip_scanned_detection")
    ocr_workaround = ui_inputs.get("ocr_workaround")
    max_pages_per_part = ui_inputs.get("max_pages_per_part")
    formular_font_pattern = ui_inputs.get("formular_font_pattern")
    formular_char_pattern = ui_inputs.get("formular_char_pattern")
    auto_enable_ocr_workaround = ui_inputs.get("auto_enable_ocr_workaround")
    only_include_translated_page = ui_inputs.get("only_include_translated_page")

    # BabelDOC v0.5.1 new options
    merge_alternating_line_numbers = ui_inputs.get("merge_alternating_line_numbers")
    remove_non_formula_lines = ui_inputs.get("remove_non_formula_lines")
    non_formula_line_iou_threshold = ui_inputs.get("non_formula_line_iou_threshold")
    figure_table_protection_threshold = ui_inputs.get(
        "figure_table_protection_threshold"
    )
    skip_formula_offset_calculation = ui_inputs.get("skip_formula_offset_calculation")
    enable_post_layout_optimization = ui_inputs.get("enable_post_layout_optimization")
    skip_header = ui_inputs.get("skip_header")
    skip_footer = ui_inputs.get("skip_footer")
    header_height = ui_inputs.get("header_height")
    footer_height = ui_inputs.get("footer_height")
    quote_narrow_threshold = ui_inputs.get("quote_narrow_threshold")
    quote_indent_threshold = ui_inputs.get("quote_indent_threshold")
    quote_right_margin_threshold = ui_inputs.get("quote_right_margin_threshold")

    # Term extraction options
    term_service = ui_inputs.get("term_service")
    term_rate_limit_mode = ui_inputs.get("term_rate_limit_mode")
    term_rpm_input = ui_inputs.get("term_rpm_input")
    term_concurrent_threads = ui_inputs.get("term_concurrent_threads")
    term_custom_qps = ui_inputs.get("term_custom_qps")
    term_custom_pool_workers = ui_inputs.get("term_custom_pool_workers")

    # New input for custom_system_prompt
    custom_system_prompt_input = ui_inputs.get("custom_system_prompt_input")
    glossaries = ui_inputs.get("glossaries")
    save_auto_extracted_glossary = ui_inputs.get("save_auto_extracted_glossary")

    # Map UI language selections to language codes
    source_lang = lang_map.get(lang_from, "auto")
    target_lang = lang_map.get(lang_to, "zh")

    # Set up page selection
    if page_range == "Range" and page_input:
        pages = page_input  # The backend parser handles the format
    else:
        # Use predefined ranges from page_map
        selected_pages = page_map[page_range]
        if selected_pages is None:
            pages = None  # All pages
        else:
            # Convert page indices to comma-separated string
            pages = ",".join(
                str(p + 1) for p in selected_pages
            )  # +1 because UI is 1-indexed

    # Update settings with UI values
    translate_settings.basic.input_files = {str(file_path)}
    translate_settings.report_interval = 0.2
    translate_settings.translation.lang_in = source_lang
    translate_settings.translation.lang_out = target_lang
    translate_settings.translation.output = str(output_dir)
    translate_settings.translation.ignore_cache = ignore_cache

    # Update Translation Settings
    if min_text_length is not None:
        translate_settings.translation.min_text_length = int(min_text_length)
    if rpc_doclayout:
        translate_settings.translation.rpc_doclayout = rpc_doclayout

    # UI uses positive switch, config uses negative flag, so we invert here
    if enable_auto_term_extraction is not None:
        translate_settings.translation.no_auto_extract_glossary = (
            not enable_auto_term_extraction
        )
    if primary_font_family:
        if primary_font_family == "Auto":
            translate_settings.translation.primary_font_family = None
        else:
            translate_settings.translation.primary_font_family = primary_font_family

    # Calculate and update rate limit settings
    if service != "SiliconFlowFree":
        qps, pool_workers = _calculate_rate_limit_params(
            rate_limit_mode, ui_inputs, translate_settings.translation.qps or 4
        )

        # Update translation settings
        translate_settings.translation.qps = int(qps)
        translate_settings.translation.pool_max_workers = (
            int(pool_workers) if pool_workers is not None else None
        )

    # Calculate and update term extraction rate limit settings
    if term_rate_limit_mode:
        term_rate_inputs = {
            "rpm_input": term_rpm_input,
            "concurrent_threads": term_concurrent_threads,
            "custom_qps": term_custom_qps,
            "custom_pool_workers": term_custom_pool_workers,
        }
        term_qps, term_pool_workers = _calculate_rate_limit_params(
            term_rate_limit_mode,
            term_rate_inputs,
            translate_settings.translation.term_qps
            or translate_settings.translation.qps
            or 4,
        )
        translate_settings.translation.term_qps = int(term_qps)
        translate_settings.translation.term_pool_max_workers = (
            int(term_pool_workers) if term_pool_workers is not None else None
        )

    # Reset all term extraction engine flags
    for term_metadata in TERM_EXTRACTION_ENGINE_METADATA:
        term_flag_name = f"term_{term_metadata.cli_flag_name}"
        if hasattr(translate_settings, term_flag_name):
            setattr(translate_settings, term_flag_name, False)

    # Configure term extraction engine settings from UI when not following main engine
    if (
        term_service
        and term_service != "Follow main translation engine"
        and not translate_settings.translation.no_auto_extract_glossary
        and term_service in TERM_EXTRACTION_ENGINE_METADATA_MAP
    ):
        term_metadata = TERM_EXTRACTION_ENGINE_METADATA_MAP[term_service]

        # Enable selected term extraction engine flag
        term_flag_name = f"term_{term_metadata.cli_flag_name}"
        if hasattr(translate_settings, term_flag_name):
            setattr(translate_settings, term_flag_name, True)

        # Update term extraction engine detail settings
        if term_metadata.cli_detail_field_name:
            term_detail_field_name = f"term_{term_metadata.cli_detail_field_name}"
            term_detail_settings = getattr(translate_settings, term_detail_field_name)
            term_model_type = term_metadata.term_setting_model_type

            for field_name, field in term_model_type.model_fields.items():
                if field_name in ("translate_engine_type", "support_llm"):
                    continue

                if field_name not in ui_inputs:
                    continue
                value = ui_inputs[field_name]

                type_hint = field.annotation
                type_args = typing.get_args(type_hint)

                if value is None:
                    if _type_hint_allows_none(type_hint):
                        setattr(term_detail_settings, field_name, None)
                    continue

                if type_hint is str or str in type_args:
                    pass
                elif type_hint is int or int in type_args:
                    value = int(value)
                elif type_hint is bool or bool in type_args:
                    value = bool(value)
                else:
                    raise Exception(
                        f"Unsupported type {type_hint} for field {field_name} in gui term extraction engine settings"
                    )

                setattr(term_detail_settings, field_name, value)

    # Update PDF Settings
    translate_settings.pdf.pages = pages
    translate_settings.pdf.no_mono = no_mono
    translate_settings.pdf.no_dual = no_dual
    translate_settings.pdf.dual_translate_first = dual_translate_first
    translate_settings.pdf.use_alternating_pages_dual = use_alternating_pages_dual

    # Map watermark mode from UI to enum
    translate_settings.pdf.watermark_output_mode = (
        watermark_output_mode.lower().replace(" ", "_")
    )

    # Update Advanced PDF Settings
    translate_settings.pdf.skip_clean = skip_clean
    translate_settings.pdf.disable_rich_text_translate = disable_rich_text_translate
    translate_settings.pdf.enhance_compatibility = enhance_compatibility
    translate_settings.pdf.split_short_lines = split_short_lines
    translate_settings.pdf.ocr_workaround = ocr_workaround
    if short_line_split_factor is not None:
        translate_settings.pdf.short_line_split_factor = float(short_line_split_factor)

    translate_settings.pdf.translate_table_text = translate_table_text
    if translate_figure_text is not None:
        translate_settings.pdf.translate_figure_text = bool(translate_figure_text)
    translate_settings.pdf.skip_scanned_detection = skip_scanned_detection
    translate_settings.pdf.auto_enable_ocr_workaround = auto_enable_ocr_workaround
    translate_settings.pdf.only_include_translated_page = only_include_translated_page

    if max_pages_per_part is not None and max_pages_per_part > 0:
        translate_settings.pdf.max_pages_per_part = int(max_pages_per_part)

    if formular_font_pattern:
        translate_settings.pdf.formular_font_pattern = formular_font_pattern

    if formular_char_pattern:
        translate_settings.pdf.formular_char_pattern = formular_char_pattern

    # Apply BabelDOC v0.5.1 new options
    if merge_alternating_line_numbers is not None:
        translate_settings.pdf.no_merge_alternating_line_numbers = (
            not merge_alternating_line_numbers
        )
    if remove_non_formula_lines is not None:
        translate_settings.pdf.no_remove_non_formula_lines = not remove_non_formula_lines
    if non_formula_line_iou_threshold is not None:
        translate_settings.pdf.non_formula_line_iou_threshold = float(
            non_formula_line_iou_threshold
        )
    if figure_table_protection_threshold is not None:
        translate_settings.pdf.figure_table_protection_threshold = float(
            figure_table_protection_threshold
        )
    if skip_formula_offset_calculation is not None:
        translate_settings.pdf.skip_formula_offset_calculation = (
            skip_formula_offset_calculation
        )
    if enable_post_layout_optimization is not None:
        translate_settings.pdf.enable_post_layout_optimization = (
            enable_post_layout_optimization
        )
    if skip_header is not None:
        translate_settings.pdf.skip_header = skip_header
    if skip_footer is not None:
        translate_settings.pdf.skip_footer = skip_footer
    if header_height is not None:
        translate_settings.pdf.header_height = float(header_height)
    if footer_height is not None:
        translate_settings.pdf.footer_height = float(footer_height)
    if quote_narrow_threshold is not None:
        translate_settings.pdf.quote_narrow_threshold = float(quote_narrow_threshold)
    if quote_indent_threshold is not None:
        translate_settings.pdf.quote_indent_threshold = float(quote_indent_threshold)
    if quote_right_margin_threshold is not None:
        translate_settings.pdf.quote_right_margin_threshold = float(quote_right_margin_threshold)

    assert service in TRANSLATION_ENGINE_METADATA_MAP, "UNKNOW TRANSLATION ENGINE!"

    for metadata in TRANSLATION_ENGINE_METADATA:
        cli_flag = metadata.cli_flag_name
        setattr(translate_settings, cli_flag, False)

    metadata = TRANSLATION_ENGINE_METADATA_MAP[service]
    cli_flag = metadata.cli_flag_name
    setattr(translate_settings, cli_flag, True)
    if metadata.cli_detail_field_name:
        detail_setting = getattr(translate_settings, metadata.cli_detail_field_name)
        if metadata.setting_model_type:
            for field_name in metadata.setting_model_type.model_fields:
                if field_name == "translate_engine_type" or field_name == "support_llm":
                    continue
                if disable_gui_sensitive_input:
                    if field_name in GUI_PASSWORD_FIELDS:
                        continue
                    if field_name in GUI_SENSITIVE_FIELDS:
                        continue
                value = ui_inputs.get(field_name)
                type_hint = detail_setting.model_fields[field_name].annotation
                original_type = typing.get_origin(type_hint)
                type_args = typing.get_args(type_hint)
                if type_hint is str or str in type_args:
                    pass
                elif type_hint is int or int in type_args:
                    value = int(value)
                elif type_hint is bool or bool in type_args:
                    value = bool(value)
                else:
                    raise Exception(
                        f"Unsupported type {type_hint} for field {field_name} in gui translation engine settings"
                    )
                setattr(detail_setting, field_name, value)

    # Add custom prompt if provided
    if prompt:
        # This might need adjustment based on how prompt is handled in the new system
        translate_settings.custom_prompt = Template(prompt)

    # Add custom system prompt if provided
    if custom_system_prompt_input:
        translate_settings.translation.custom_system_prompt = custom_system_prompt_input
    else:
        translate_settings.translation.custom_system_prompt = None

    if glossaries:
        translate_settings.translation.glossaries = glossaries
    else:
        translate_settings.translation.glossaries = None

    translate_settings.translation.save_auto_extracted_glossary = (
        save_auto_extracted_glossary
    )

    # Validate settings before proceeding
    try:
        translate_settings.validate_settings()
        temp_settings = translate_settings.to_settings_model()
        translate_settings.translation.output = original_output
        translate_settings.pdf.pages = original_pages
        translate_settings.gui_settings = original_gui_settings
        translate_settings.basic.gui = False
        translate_settings.basic.debug = False
        translate_settings.translation.glossaries = None

        # Determine if config should be saved based on save_mode
        should_save = False
        if save_mode == SaveMode.always:
            should_save = True
        elif save_mode == SaveMode.follow_settings:
            should_save = not temp_settings.gui_settings.disable_config_auto_save
        # SaveMode.never: should_save remains False

        if should_save:
            # Lazy import avoids circular import with gui.py module init
            from pdf2zh_next import gui as gui_mod

            gui_mod.config_manager.write_user_default_config_file(
                settings=translate_settings
            )
            gui_mod.settings = translate_settings
        temp_settings.validate_settings()
        return temp_settings
    except ValueError as e:
        raise gr.Error(f"Invalid settings: {e}") from e

