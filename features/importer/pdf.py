from __future__ import annotations

from typing import Optional

from .models import PDFImportSettings
from .pdf_convert import convert_pdf_with_settings as _convert_pdf_with_settings_impl
from .pdf_fonts import analyze_pdf_fonts as _analyze_pdf_fonts_impl
from .pdf_hf import detect_pdf_hf_layout as _detect_pdf_hf_layout_impl
from .pdf_reflow import (
    _limit_dot_leaders as _limit_dot_leaders_impl,
    _merge_smart_page_boundaries as _merge_smart_page_boundaries_impl,
    _merge_table_page_boundaries as _merge_table_page_boundaries_impl,
    _reflow_markdown as _reflow_markdown_impl,
    _replace_html_br_with_space as _replace_html_br_with_space_impl,
    _strip_bold_from_markdown_headings as _strip_bold_from_markdown_headings_impl,
    extract_markdown_headings_by_page as _extract_markdown_headings_by_page_impl,
)
from .pdf_tables import (
    _extract_table_bboxes as _extract_table_bboxes_impl,
    _recover_tables_in_page_markdown as _recover_tables_in_page_markdown_impl,
    _rect_intersection_ratio as _rect_intersection_ratio_impl,
)

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
    """True when the RGB colour is clearly not black / dark grey."""
    return r > 50 or g > 50 or b > 50


def _fitz_color_not_black(color: int) -> bool:
    """pymupdf stores colour as 0xRRGGBB integer; 0 = black."""
    r = (color >> 16) & 0xFF
    g = (color >> 8) & 0xFF
    b = color & 0xFF
    return _is_not_black_rgb(r, g, b)


def _span_is_bold(span: dict) -> bool:
    flags = span.get("flags", 0)
    if flags & 16:
        return True
    font = span.get("font", "").lower()
    return any(tok in font for tok in _BOLD_TOKENS)


def _compute_body_font_size(doc, top_zone: float = 0.10, bottom_zone: float = 0.10) -> float:
    """Return the median body-text font size, skipping margin zones."""
    sizes: list[float] = []
    for page in doc:
        h = page.rect.height or 1.0
        top_limit = h * top_zone
        bottom_limit = h * (1.0 - bottom_zone)
        for block in page.get_text("dict")["blocks"]:
            if block.get("type") != 0:
                continue
            by0 = block["bbox"][1]
            by1 = block["bbox"][3]
            if by1 <= top_limit or by0 >= bottom_limit:
                continue
            for line in block["lines"]:
                for span in line["spans"]:
                    size = span.get("size", 0)
                    if size > 0:
                        sizes.append(size)
    if not sizes:
        return 11.0
    sizes.sort()
    return sizes[len(sizes) // 2]


class _CustomHeaderDetector:
    """Custom heading detector used by pymupdf4llm."""

    def __init__(self, body_size: float, settings: PDFImportSettings):
        self.body = body_size
        self.s = settings

    def get_header_id(self, span: dict, page=None) -> str:
        del page
        text = (span.get("text") or "").strip()
        max_chars = min(max(1, int(self.s.heading_max_chars)), _HARD_HEADING_MAX_CHARS - 1)
        if not text or len(text) > max_chars:
            return ""

        size = span.get("size", 0)
        is_bold = _span_is_bold(span)
        is_color = _fitz_color_not_black(span.get("color", 0))
        body = self.body
        settings = self.s

        if size >= body * settings.heading_h1_ratio:
            return "#"
        if size >= body * settings.heading_h2_ratio:
            return "##"
        if size >= body * settings.heading_h3_ratio:
            return "###"
        if settings.heading_bold_promotes and is_bold and size >= body * 0.90:
            return "###"
        if settings.heading_color_promotes and is_color and size >= body * 0.90:
            return "###"
        return ""


def _strip_bold_from_markdown_headings(text: str) -> str:
    return _strip_bold_from_markdown_headings_impl(text)


def _replace_html_br_with_space(text: str) -> str:
    return _replace_html_br_with_space_impl(text)


def _limit_dot_leaders(text: str) -> str:
    return _limit_dot_leaders_impl(text)


def extract_markdown_headings_by_page(markdown: str) -> dict[int, list[tuple[int, str]]]:
    return _extract_markdown_headings_by_page_impl(markdown)


def _reflow_markdown(text: str, settings: PDFImportSettings) -> str:
    return _reflow_markdown_impl(text, settings)


def _merge_smart_page_boundaries(
    page_entries: list[tuple[int, str]],
    settings: PDFImportSettings,
) -> list[tuple[int, str]]:
    return _merge_smart_page_boundaries_impl(page_entries, settings)


def _merge_table_page_boundaries(
    page_entries: list[tuple[int, str]],
    show_page_markers: bool,
) -> list[tuple[int, str]]:
    return _merge_table_page_boundaries_impl(page_entries, show_page_markers)


def _rect_intersection_ratio(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> float:
    return _rect_intersection_ratio_impl(a, b)


def _extract_table_bboxes(
    page,
    clip: tuple[float, float, float, float] | None = None,
) -> list[tuple[float, float, float, float]]:
    return _extract_table_bboxes_impl(page, clip)


def _recover_tables_in_page_markdown(
    page,
    page_text: str,
    top_m: float,
    bottom_m: float,
) -> str:
    return _recover_tables_in_page_markdown_impl(page, page_text, top_m, bottom_m)


def analyze_pdf_fonts(path: str, settings: PDFImportSettings) -> dict:
    """Compatibility wrapper for font analysis implementation module."""
    return _analyze_pdf_fonts_impl(path, settings)


def _parse_page_range(page_range: str, path: str) -> Optional[list[int]]:
    s = page_range.strip().lower()
    if s in ("all", ""):
        return None
    try:
        import fitz  # type: ignore

        doc = fitz.open(path)
        n_pages = len(doc)
        doc.close()
    except Exception:
        return None

    pages: set[int] = set()
    for part in s.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo_s, hi_s = part.split("-", 1)
            lo = int(lo_s.strip()) - 1 if lo_s.strip() else 0
            hi = int(hi_s.strip()) - 1 if hi_s.strip() else n_pages - 1
            pages.update(range(max(0, lo), min(n_pages - 1, hi) + 1))
        else:
            page_index = int(part) - 1
            if 0 <= page_index < n_pages:
                pages.add(page_index)
    return sorted(pages) if pages else None


def detect_pdf_hf_layout(path: str, settings: PDFImportSettings) -> dict:
    """Compatibility wrapper for header/footer detection implementation module."""
    return _detect_pdf_hf_layout_impl(
        path,
        settings,
        compute_body_font_size=_compute_body_font_size,
        extract_table_bboxes=_extract_table_bboxes,
        rect_intersection_ratio=_rect_intersection_ratio,
    )


def detect_pdf_hf_margins(
    path: str,
    settings: PDFImportSettings,
) -> tuple[float, float, str]:
    """Backward-compatible wrapper returning global margins + info text."""
    result = detect_pdf_hf_layout(path, settings)
    return (
        float(result.get("top_margin", 0.0)),
        float(result.get("bottom_margin", 0.0)),
        str(result.get("info", "")),
    )


def convert_pdf_with_settings(path: str, settings: PDFImportSettings) -> str:
    """Compatibility wrapper for PDF conversion implementation module."""
    return _convert_pdf_with_settings_impl(
        path,
        settings,
        parse_page_range=_parse_page_range,
        detect_pdf_hf_layout=detect_pdf_hf_layout,
        compute_body_font_size=_compute_body_font_size,
        custom_header_detector_factory=_CustomHeaderDetector,
        reflow_markdown=_reflow_markdown,
        strip_bold_from_markdown_headings=_strip_bold_from_markdown_headings,
        recover_tables_in_page_markdown=_recover_tables_in_page_markdown,
        merge_smart_page_boundaries=_merge_smart_page_boundaries,
        merge_table_page_boundaries=_merge_table_page_boundaries,
        replace_html_br_with_space=_replace_html_br_with_space,
        limit_dot_leaders=_limit_dot_leaders,
    )
