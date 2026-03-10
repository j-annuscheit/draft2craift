"""HTML preview widget for the canvas feature."""
from __future__ import annotations

import re
import weakref

from PySide6.QtWidgets import QWidget

from .pane_parts import bind_canvas_preview_pane
from .pane_parts.models import _RenderedHighlight


class CanvasPreviewPane(QWidget):
    """Encapsulates preview editing/rendering, zooming, and cursor sync."""

    _HR_MARKER = "{{__D2C_HR__}}"
    _BLANK_LINE_SENTINEL = "\u200B"
    _ORDERED_ITEM_RE = re.compile(r"^(\s*)\d+[.)]\s+")
    _BULLET_ITEM_RE = re.compile(r"^(\s*)[-+*]\s+")
    _TOKEN_RE = re.compile(r"\w+(?:[+./-]\w+)*", flags=re.UNICODE)
    _INTERNAL_WORD_STAR_RE = re.compile(r"(?<=[^\W\d_])\*(?=[^\W\d_])", flags=re.UNICODE)
    _FENCE_MARKER_RE = re.compile(r"^([`~]{3,})")
    _HARD_BREAK_HTML_RE = re.compile(r"<br\s*/?>\s*$", flags=re.IGNORECASE)
    _HEADING_LINE_RE = re.compile(r"^#{1,6}\s+")
    _BLOCKQUOTE_LINE_RE = re.compile(r"^\s{0,3}(?:>\s?)+")
    _LIST_LINE_RE = re.compile(r"^\s{0,3}(?:[-*+]|\d+[.)])\s+")
    _THEMATIC_BREAK_LINE_RE = re.compile(r"^\s*[-*_]{3,}\s*$")
    _TABLE_ROW_PREFIX_RE = re.compile(r"^\s*\|")
    _HTML_LINE_RE = re.compile(r"^\s*<[^>]+>\s*$")
    _MD_HEADING_PREFIX_RE = re.compile(r"^#{1,6}\s*")
    _MD_BLOCKQUOTE_PREFIX_RE = re.compile(r"^\s{0,3}(?:>\s?)+")
    _MD_LIST_PREFIX_RE = re.compile(r"^\s{0,3}(?:[-*+]|\d+[.)])\s+")
    _MD_IMAGE_LINK_RE = re.compile(r"!\[([^\]]*)\]\([^)]+\)")
    _MD_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
    _MD_INLINE_CODE_RE = re.compile(r"`([^`]*)`")
    _MD_BOLD_STAR_RE = re.compile(r"\*\*([^*]+)\*\*")
    _MD_BOLD_UNDERSCORE_RE = re.compile(r"__([^_]+)__")
    _MD_ITALIC_STAR_RE = re.compile(r"\*([^*]+)\*")
    _MD_ITALIC_UNDERSCORE_RE = re.compile(r"_([^_]+)_")
    _MD_HTML_TAG_RE = re.compile(r"<[^>]+>")
    _WS_RE = re.compile(r"\s+")
    _HR_MARKER_LINE_RE: re.Pattern[str] | None = None
    _ZOOM_MIN = 60
    _ZOOM_MAX = 260
    _ZOOM_STEP = 10
    _BASE_PT = 11.0
    _TITLE_BASE_PT = 11.0
    _PAGE_MARGIN_DEFAULT_EM = 2.2
    _PAGE_MARGIN_PRESETS: tuple[tuple[str, float], ...] = (
        ("Schmal", 1.4),
        ("Normal", 2.2),
        ("Breit", 3.0),
        ("Sehr breit", 4.0),
    )
    _PREVIEW_THEME_DEFAULT = "classic"
    _PREVIEW_THEME_OPTIONS: tuple[tuple[str, str], ...] = (
        ("classic", "Klassisch"),
        ("accent", "Akzent"),
        ("vivid", "Lebhaft"),
    )
    _GLOBAL_PAGE_MARGIN_ENABLED = True
    _GLOBAL_PAGE_MARGIN_EM = _PAGE_MARGIN_DEFAULT_EM
    _GLOBAL_PREVIEW_THEME = _PREVIEW_THEME_DEFAULT
    _INSTANCES: "weakref.WeakSet[CanvasPreviewPane]" = weakref.WeakSet()
    _PREVIEW_TO_MARKDOWN_DELAY_MS = 140
    _HIGHLIGHT_SYNC_DELAY_MS = 240
    _DEFAULT_HOVER_TEXT = "Info"
    _HIGHLIGHT_COLORS = (
        ("Gelb", "#F9E2AF"),
        ("Grün", "#A6E3A1"),
        ("Blau", "#89B4FA"),
        ("Rot", "#F38BA8"),
        ("Lila", "#CBA6F7"),
        ("Orange", "#FAB387"),
    )

    @staticmethod
    def _canonical_markdown(text: str) -> str:
        normalized = text.replace("\r\n", "\n").rstrip()
        normalized = CanvasPreviewPane._replace_hr_markers(normalized)
        normalized = CanvasPreviewPane._normalize_inline_code_backslashes(normalized)
        normalized = CanvasPreviewPane._normalize_ordered_sublist_indent(normalized)
        normalized = CanvasPreviewPane._normalize_table_row_spacing(normalized)
        normalized = CanvasPreviewPane._normalize_pure_pipe_table_blocks(normalized)
        return CanvasPreviewPane._normalize_table_column_mismatch(normalized)

    @staticmethod
    def _normalize_markdown_line(line: str) -> str:
        """Map a markdown source line to plain text for preview matching."""
        text = str(line or "").replace("\u200B", "").replace("\u00A0", " ").strip()
        if not text:
            return ""
        text = CanvasPreviewPane._MD_HEADING_PREFIX_RE.sub("", text)
        text = CanvasPreviewPane._MD_BLOCKQUOTE_PREFIX_RE.sub("", text)
        text = CanvasPreviewPane._MD_LIST_PREFIX_RE.sub("", text)
        text = CanvasPreviewPane._MD_IMAGE_LINK_RE.sub(r"\1", text)
        text = CanvasPreviewPane._MD_LINK_RE.sub(r"\1", text)
        text = CanvasPreviewPane._MD_INLINE_CODE_RE.sub(r"\1", text)
        text = CanvasPreviewPane._MD_BOLD_STAR_RE.sub(r"\1", text)
        text = CanvasPreviewPane._MD_BOLD_UNDERSCORE_RE.sub(r"\1", text)
        text = CanvasPreviewPane._MD_ITALIC_STAR_RE.sub(r"\1", text)
        text = CanvasPreviewPane._MD_ITALIC_UNDERSCORE_RE.sub(r"\1", text)
        text = CanvasPreviewPane._MD_HTML_TAG_RE.sub(" ", text)
        text = CanvasPreviewPane._WS_RE.sub(" ", text).strip()
        return text


bind_canvas_preview_pane(CanvasPreviewPane)

__all__ = ["CanvasPreviewPane", "_RenderedHighlight"]
