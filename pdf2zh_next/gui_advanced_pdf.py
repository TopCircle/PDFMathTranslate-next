"""Gradio components for Advanced PDF / BabelDOC options.

Extracted from gui.py Advanced Options accordion (PDF Options section).
"""

from __future__ import annotations

from typing import Any

import gradio as gr

from pdf2zh_next.config.cli_env_model import CLIEnvSettingsModel
from pdf2zh_next.i18n import gettext as _


def create_pdf_advanced_components(
    settings: CLIEnvSettingsModel,
) -> dict[str, Any]:
    """Build PDF advanced Gradio controls; returns name -> component.

    Must be called inside an active ``gr.Blocks`` / Accordion context.
    """
    gr.Markdown(_("### PDF Options"))

    skip_clean = gr.Checkbox(
        label=_("Skip clean (maybe improve compatibility)"),
        value=settings.pdf.skip_clean,
        interactive=True,
    )
    disable_rich_text_translate = gr.Checkbox(
        label=_(
            "Disable rich text translation (maybe improve compatibility)"
        ),
        value=settings.pdf.disable_rich_text_translate,
        interactive=True,
    )
    enhance_compatibility = gr.Checkbox(
        label=_(
            "Enhance compatibility (auto-enables skip_clean and disable_rich_text)"
        ),
        value=settings.pdf.enhance_compatibility,
        interactive=True,
    )
    split_short_lines = gr.Checkbox(
        label=_("Force split short lines into different paragraphs"),
        value=settings.pdf.split_short_lines,
        interactive=True,
    )
    short_line_split_factor = gr.Slider(
        label=_("Split threshold factor for short lines"),
        value=settings.pdf.short_line_split_factor,
        minimum=0.1,
        maximum=1.0,
        step=0.1,
        interactive=True,
        visible=settings.pdf.split_short_lines,
    )
    translate_table_text = gr.Checkbox(
        label=_("Translate table text (experimental)"),
        value=settings.pdf.translate_table_text,
        interactive=True,
    )
    translate_figure_text = gr.Checkbox(
        label=_("Translate figure text"),
        info=_(
            "Translate labels drawn inside figures (e.g. chart axes). "
            "Off by default — keeps Ancilla/Data labels in the source language. "
            "Independent of “Translate table text”."
        ),
        value=settings.pdf.translate_figure_text,
        interactive=True,
    )
    skip_scanned_detection = gr.Checkbox(
        label=_("Skip scanned detection"),
        value=settings.pdf.skip_scanned_detection,
        interactive=True,
    )
    ocr_workaround = gr.Checkbox(
        label=_(
            "OCR workaround (experimental, will auto enable Skip scanned detection in backend)"
        ),
        value=settings.pdf.ocr_workaround,
        interactive=True,
    )
    auto_enable_ocr_workaround = gr.Checkbox(
        label=_(
            "Auto enable OCR workaround (enable automatic OCR workaround for heavily scanned documents)"
        ),
        value=settings.pdf.auto_enable_ocr_workaround,
        interactive=True,
    )
    max_pages_per_part = gr.Number(
        label=_(
            "Maximum pages per part (for auto-split translation, 0 means no limit)"
        ),
        value=settings.pdf.max_pages_per_part,
        precision=0,
        minimum=0,
        interactive=True,
    )
    formular_font_pattern = gr.Textbox(
        label=_(
            "Font pattern to identify formula text (regex, not recommended to change)"
        ),
        value=settings.pdf.formular_font_pattern or "",
        interactive=True,
        placeholder="e.g., CMMI|CMR",
    )
    formular_char_pattern = gr.Textbox(
        label=_(
            "Character pattern to identify formula text (regex, not recommended to change)"
        ),
        value=settings.pdf.formular_char_pattern or "",
        interactive=True,
        placeholder="e.g., [∫∬∭∮∯∰∇∆]",
    )
    ignore_cache = gr.Checkbox(
        label=_("Ignore cache"),
        value=settings.translation.ignore_cache,
        interactive=True,
    )

    gr.Markdown(_("#### BabelDOC Advanced Options"))

    merge_alternating_line_numbers = gr.Checkbox(
        label=_("Merge alternating line numbers"),
        info=_(
            "Handle alternating line numbers and text paragraphs in documents with line numbers"
        ),
        value=not settings.pdf.no_merge_alternating_line_numbers,
        interactive=True,
    )
    remove_non_formula_lines = gr.Checkbox(
        label=_("Remove non-formula lines"),
        info=_("Remove non-formula lines within paragraph areas"),
        value=not settings.pdf.no_remove_non_formula_lines,
        interactive=True,
    )
    non_formula_line_iou_threshold = gr.Slider(
        label=_("Non-formula line IoU threshold"),
        info=_("IoU threshold for identifying non-formula lines"),
        value=settings.pdf.non_formula_line_iou_threshold,
        minimum=0.0,
        maximum=1.0,
        step=0.05,
        interactive=True,
    )
    figure_table_protection_threshold = gr.Slider(
        label=_("Figure/table protection threshold"),
        info=_(
            "Protection threshold for figures and tables (lines within figures/tables will not be processed)"
        ),
        value=settings.pdf.figure_table_protection_threshold,
        minimum=0.0,
        maximum=1.0,
        step=0.05,
        interactive=True,
    )
    skip_formula_offset_calculation = gr.Checkbox(
        label=_("Skip formula offset calculation"),
        info=_("Skip formula offset calculation during processing"),
        value=settings.pdf.skip_formula_offset_calculation,
        interactive=True,
    )
    enable_post_layout_optimization = gr.Checkbox(
        label=_("Enable post-layout optimization"),
        info=_("Fix overlapping text after typesetting (experimental)"),
        value=settings.pdf.enable_post_layout_optimization,
        interactive=True,
    )

    gr.Markdown(_("#### Header/Footer Filtering"))

    with gr.Row():
        skip_header = gr.Checkbox(
            label=_("Skip Header"),
            value=settings.pdf.skip_header,
            interactive=True,
        )
        skip_footer = gr.Checkbox(
            label=_("Skip Footer"),
            value=settings.pdf.skip_footer,
            interactive=True,
        )

    with gr.Row():
        header_height = gr.Number(
            label=_("Header Height (pt)"),
            value=settings.pdf.header_height,
            precision=1,
            minimum=0,
            interactive=True,
        )
        footer_height = gr.Number(
            label=_("Footer Height (pt)"),
            value=settings.pdf.footer_height,
            precision=1,
            minimum=0,
            interactive=True,
        )

    gr.Markdown(_("#### Quote Block Detection"))

    quote_narrow_threshold = gr.Slider(
        label=_("Quote Narrow Threshold"),
        info=_(
            "Width ratio threshold for Quote detection (paragraph width / page width)"
        ),
        value=settings.pdf.quote_narrow_threshold,
        minimum=0.1,
        maximum=1.0,
        step=0.05,
        interactive=True,
    )

    with gr.Row():
        quote_indent_threshold = gr.Slider(
            label=_("Quote Indent Threshold"),
            info=_("Left indent ratio threshold (indent / page width)"),
            value=settings.pdf.quote_indent_threshold,
            minimum=0.0,
            maximum=0.5,
            step=0.01,
            interactive=True,
        )
        quote_right_margin_threshold = gr.Slider(
            label=_("Quote Right Margin Threshold"),
            info=_("Right margin ratio threshold (margin / page width)"),
            value=settings.pdf.quote_right_margin_threshold,
            minimum=0.0,
            maximum=0.5,
            step=0.01,
            interactive=True,
        )

    return {
        "skip_clean": skip_clean,
        "disable_rich_text_translate": disable_rich_text_translate,
        "enhance_compatibility": enhance_compatibility,
        "split_short_lines": split_short_lines,
        "short_line_split_factor": short_line_split_factor,
        "translate_table_text": translate_table_text,
        "translate_figure_text": translate_figure_text,
        "skip_scanned_detection": skip_scanned_detection,
        "ocr_workaround": ocr_workaround,
        "auto_enable_ocr_workaround": auto_enable_ocr_workaround,
        "max_pages_per_part": max_pages_per_part,
        "formular_font_pattern": formular_font_pattern,
        "formular_char_pattern": formular_char_pattern,
        "ignore_cache": ignore_cache,
        "merge_alternating_line_numbers": merge_alternating_line_numbers,
        "remove_non_formula_lines": remove_non_formula_lines,
        "non_formula_line_iou_threshold": non_formula_line_iou_threshold,
        "figure_table_protection_threshold": figure_table_protection_threshold,
        "skip_formula_offset_calculation": skip_formula_offset_calculation,
        "enable_post_layout_optimization": enable_post_layout_optimization,
        "skip_header": skip_header,
        "skip_footer": skip_footer,
        "header_height": header_height,
        "footer_height": footer_height,
        "quote_narrow_threshold": quote_narrow_threshold,
        "quote_indent_threshold": quote_indent_threshold,
        "quote_right_margin_threshold": quote_right_margin_threshold,
    }
