"""Heading detector used by pymupdf4llm custom header mode."""
from __future__ import annotations

from ..models import PDFImportSettings

_BOLD_TOKENS = frozenset(
    {
        "bold",
        "bd",
        "heavy",
        "hv",
        "black",
        "blk",
        "demi",
        "semibold",
        "extrabold",
        "ultrabold",
    }
)
_HARD_HEADING_MAX_CHARS = 120


def _is_not_black_rgb(r: int, g: int, b: int) -> bool:
    return r > 50 or g > 50 or b > 50


def _fitz_color_not_black(color: int) -> bool:
    r = (color >> 16) & 0xFF
    g = (color >> 8) & 0xFF
    b = color & 0xFF
    return _is_not_black_rgb(r, g, b)


def _span_is_bold(span: dict) -> bool:
    flags = span.get("flags", 0)
    if flags & 16:
        return True
    font = str(span.get("font", "") or "").lower()
    return any(token in font for token in _BOLD_TOKENS)


class CustomHeaderDetector:
    """Custom heading detector passed into pymupdf4llm via ``hdr_info``."""

    def __init__(self, body_size: float, settings: PDFImportSettings):
        self._body = body_size
        self._settings = settings

    def get_header_id(self, span: dict, page=None) -> str:
        del page
        text = str(span.get("text") or "").strip()
        max_chars = min(
            max(1, int(self._settings.heading_max_chars)),
            _HARD_HEADING_MAX_CHARS - 1,
        )
        if not text or len(text) > max_chars:
            return ""

        size = span.get("size", 0)
        is_bold = _span_is_bold(span)
        is_color = _fitz_color_not_black(span.get("color", 0))

        if size >= self._body * self._settings.heading_h1_ratio:
            return "#"
        if size >= self._body * self._settings.heading_h2_ratio:
            return "##"
        if size >= self._body * self._settings.heading_h3_ratio:
            return "###"
        if self._settings.heading_bold_promotes and is_bold and size >= self._body * 0.90:
            return "###"
        if self._settings.heading_color_promotes and is_color and size >= self._body * 0.90:
            return "###"
        return ""
