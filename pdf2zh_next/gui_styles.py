"""Load Gradio custom CSS for the PDFMathTranslate GUI."""

from __future__ import annotations

from pathlib import Path

_CSS_PATH = Path(__file__).with_name("gui_styles.css")


def load_custom_css() -> str:
    """Return the contents of ``gui_styles.css`` next to this module."""
    return _CSS_PATH.read_text(encoding="utf-8")
