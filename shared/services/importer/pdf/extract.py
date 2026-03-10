from __future__ import annotations

import os
from typing import Callable, Optional

from ..models import PDFImportSettings
from .fonts import _compute_body_font_size
from .header_detector import CustomHeaderDetector
from .layout import detect_pdf_hf_layout as detect_pdf_hf_layout_impl
from .reflow import (
    _limit_dot_leaders,
    _merge_smart_page_boundaries,
    _merge_table_page_boundaries,
    _reflow_markdown,
    _replace_html_br_with_space,
    _strip_bold_from_markdown_headings,
)
from .tables import _recover_tables_in_page_markdown

ParsePageRange = Callable[[str, str], Optional[list[int]]]
DetectHfLayout = Callable[[str, PDFImportSettings], dict]
ComputeBodyFontSize = Callable[[object, float, float], float]
CustomHeaderDetectorFactory = Callable[[float, PDFImportSettings], object]
ReflowMarkdown = Callable[[str, PDFImportSettings], str]
StripBoldHeadings = Callable[[str], str]
RecoverTablesInPageMarkdown = Callable[[object, str, float, float], str]
MergeSmartPageBoundaries = Callable[
    [list[tuple[int, str]], PDFImportSettings],
    list[tuple[int, str]],
]
MergeTablePageBoundaries = Callable[[list[tuple[int, str]], bool], list[tuple[int, str]]]
TextTransform = Callable[[str], str]


def _parse_page_range(page_range: str, path: str) -> Optional[list[int]]:
    s = str(page_range or "").strip().lower()
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


def _resolve_selected_pages(doc, pages: Optional[list[int]]) -> list[int]:
    n_pages = len(doc)
    selected_pages = pages if pages is not None else list(range(n_pages))
    return [pi for pi in selected_pages if 0 <= pi < n_pages]


def _build_page_heights(doc, selected_pages: list[int]) -> dict[int, float]:
    return {pi: float(doc[pi].rect.height or 0.0) for pi in selected_pages}


def _apply_hf_detection_state(
    path: str,
    settings: PDFImportSettings,
    detect_pdf_hf_layout: DetectHfLayout,
) -> None:
    if settings.auto_hf_detect:
        detect_result = detect_pdf_hf_layout(path, settings)
        settings.detected_top = float(detect_result.get("top_margin", 0.0))
        settings.detected_bottom = float(detect_result.get("bottom_margin", 0.0))
        settings.detected_info = str(detect_result.get("info", ""))
        settings.detected_top_by_page = dict(detect_result.get("top_by_page", {}))
        settings.detected_bottom_by_page = dict(detect_result.get("bottom_by_page", {}))
        settings.detected_hf_rects_by_page = dict(detect_result.get("hf_rects_by_page", {}))
        return

    settings.detected_top = 0.0
    settings.detected_bottom = 0.0
    settings.detected_info = (
        "Manual scan-zone mode active.\n"
        f"Top: {settings.hf_top_zone * 100:.1f}%   |   "
        f"Bottom: {settings.hf_bottom_zone * 100:.1f}%"
    )
    settings.detected_top_by_page = {}
    settings.detected_bottom_by_page = {}
    settings.detected_hf_rects_by_page = {}


def _build_hdr_info(
    doc,
    settings: PDFImportSettings,
    compute_body_font_size: ComputeBodyFontSize,
    custom_header_detector_factory: CustomHeaderDetectorFactory,
) -> object:
    if settings.heading_mode == "none":
        return False
    if settings.heading_mode == "custom":
        if settings.auto_hf_detect:
            body_top_zone = 0.18
            body_bottom_zone = 0.18
        else:
            body_top_zone = settings.hf_top_zone
            body_bottom_zone = settings.hf_bottom_zone
        body_sz = compute_body_font_size(doc, body_top_zone, body_bottom_zone)
        return custom_header_detector_factory(body_sz, settings)
    return None


def _build_markdown_kwargs(settings: PDFImportSettings, hdr_info: object) -> dict:
    table_strategy = settings.table_strategy if settings.table_strategy != "none" else ""
    graphics_limit = settings.graphics_limit if settings.graphics_limit > 0 else None
    kwargs_base = {
        "page_chunks": True,
        "show_progress": False,
        "write_images": settings.write_images,
        "image_format": settings.image_format,
        "dpi": settings.dpi,
        "graphics_limit": graphics_limit,
        "table_strategy": table_strategy,
    }
    if hdr_info is not None:
        kwargs_base["hdr_info"] = hdr_info
    return kwargs_base


def _resolve_page_margins(
    page_index: int,
    settings: PDFImportSettings,
    page_heights: dict[int, float],
) -> tuple[float, float]:
    if settings.auto_hf_detect:
        top_m = float(settings.detected_top_by_page.get(page_index, 0.0))
        bottom_m = float(settings.detected_bottom_by_page.get(page_index, 0.0))
        return top_m, bottom_m
    page_h = page_heights.get(page_index, 0.0)
    top_m = max(0.0, page_h * settings.hf_top_zone)
    bottom_m = max(0.0, page_h * settings.hf_bottom_zone)
    return top_m, bottom_m


def _run_single_page_markdown(
    path: str,
    page_index: int,
    margins: tuple[float, float, float, float],
    kwargs_base: dict,
    pymupdf4llm,
) -> tuple[object, Optional[str]]:
    try:
        chunks = pymupdf4llm.to_markdown(
            path,
            pages=[page_index],
            margins=margins,
            **kwargs_base,
        )
        return chunks, None
    except TypeError:
        try:
            chunks = pymupdf4llm.to_markdown(
                path,
                pages=[page_index],
                margins=margins,
                page_chunks=True,
                show_progress=False,
            )
            return chunks, None
        except Exception as exc:
            return None, str(exc)
    except Exception as exc:
        return None, str(exc)


def _chunks_to_page_text(
    chunks: object,
    settings: PDFImportSettings,
    reflow_markdown: ReflowMarkdown,
    strip_bold_from_markdown_headings: StripBoldHeadings,
) -> str:
    if isinstance(chunks, str):
        chunks = [{"text": chunks}]
    elif isinstance(chunks, dict):
        chunks = [chunks]

    page_parts: list[str] = []
    for chunk in chunks or []:
        if isinstance(chunk, str):
            text = chunk.strip()
        else:
            text = str(chunk.get("text", "")).strip()
        if not text:
            continue
        if settings.para_mode != "none":
            text = reflow_markdown(text, settings)
        text = strip_bold_from_markdown_headings(text)
        page_parts.append(text)
    return "\n\n".join(page_parts).strip()


def _convert_selected_pages(
    path: str,
    doc,
    selected_pages: list[int],
    settings: PDFImportSettings,
    page_heights: dict[int, float],
    kwargs_base: dict,
    pymupdf4llm,
    reflow_markdown: ReflowMarkdown,
    strip_bold_from_markdown_headings: StripBoldHeadings,
    recover_tables_in_page_markdown: RecoverTablesInPageMarkdown,
) -> tuple[list[tuple[int, str]], Optional[str]]:
    page_entries: list[tuple[int, str]] = []
    for page_index in selected_pages:
        top_m, bottom_m = _resolve_page_margins(page_index, settings, page_heights)
        margins = (0.0, top_m, 0.0, bottom_m)
        chunks, error = _run_single_page_markdown(
            path,
            page_index,
            margins,
            kwargs_base,
            pymupdf4llm,
        )
        if error:
            return [], error

        page_text = _chunks_to_page_text(
            chunks,
            settings,
            reflow_markdown,
            strip_bold_from_markdown_headings,
        )
        if settings.table_strategy != "none" and page_text:
            page_text = recover_tables_in_page_markdown(doc[page_index], page_text, top_m, bottom_m)
        if page_text:
            page_entries.append((page_index, page_text))
    return page_entries, None


def _finalize_pdf_markdown(
    name: str,
    page_entries: list[tuple[int, str]],
    settings: PDFImportSettings,
    merge_smart_page_boundaries: MergeSmartPageBoundaries,
    merge_table_page_boundaries: MergeTablePageBoundaries,
    replace_html_br_with_space: TextTransform,
    limit_dot_leaders: TextTransform,
) -> str:
    page_entries = merge_smart_page_boundaries(page_entries, settings)
    page_entries = merge_table_page_boundaries(page_entries, settings.show_page_markers)

    parts: list[str] = []
    for page_index, page_text in page_entries:
        if not page_text.strip():
            continue
        if settings.show_page_markers:
            parts.append(f"[Seite {page_index + 1}]\n\n{page_text}")
        else:
            parts.append(page_text)

    body = "\n\n".join(parts) if parts else "*No text extracted.*"
    body = replace_html_br_with_space(body)
    body = limit_dot_leaders(body)
    return f"# {name}\n\n---\n\n{body}\n"


def convert_pdf_with_settings(
    path: str,
    settings: PDFImportSettings,
    *,
    parse_page_range: ParsePageRange | None = None,
    detect_pdf_hf_layout: DetectHfLayout | None = None,
    compute_body_font_size: ComputeBodyFontSize | None = None,
    custom_header_detector_factory: CustomHeaderDetectorFactory | None = None,
    reflow_markdown: ReflowMarkdown | None = None,
    strip_bold_from_markdown_headings: StripBoldHeadings | None = None,
    recover_tables_in_page_markdown: RecoverTablesInPageMarkdown | None = None,
    merge_smart_page_boundaries: MergeSmartPageBoundaries | None = None,
    merge_table_page_boundaries: MergeTablePageBoundaries | None = None,
    replace_html_br_with_space: TextTransform | None = None,
    limit_dot_leaders: TextTransform | None = None,
) -> str:
    """Convert a PDF to Markdown using pymupdf4llm with the given settings."""
    parse_page_range_fn = parse_page_range or _parse_page_range
    detect_pdf_hf_layout_fn = detect_pdf_hf_layout or detect_pdf_hf_layout_impl
    compute_body_font_size_fn = compute_body_font_size or _compute_body_font_size
    custom_header_detector_factory_fn = custom_header_detector_factory or CustomHeaderDetector
    reflow_markdown_fn = reflow_markdown or _reflow_markdown
    strip_bold_from_markdown_headings_fn = (
        strip_bold_from_markdown_headings or _strip_bold_from_markdown_headings
    )
    recover_tables_in_page_markdown_fn = (
        recover_tables_in_page_markdown or _recover_tables_in_page_markdown
    )
    merge_smart_page_boundaries_fn = merge_smart_page_boundaries or _merge_smart_page_boundaries
    merge_table_page_boundaries_fn = merge_table_page_boundaries or _merge_table_page_boundaries
    replace_html_br_with_space_fn = replace_html_br_with_space or _replace_html_br_with_space
    limit_dot_leaders_fn = limit_dot_leaders or _limit_dot_leaders

    name = os.path.basename(path)

    try:
        import pymupdf4llm  # type: ignore
        import fitz  # type: ignore
    except ImportError:
        return (
            f"# {name}\n\n"
            "*pymupdf4llm is not installed.*\n\n"
            "```\npip install pymupdf4llm\n```\n"
        )

    try:
        pages = parse_page_range_fn(settings.page_range, path)
    except Exception:
        pages = None

    try:
        doc = fitz.open(path)
    except Exception as exc:
        return f"# {name}\n\n*Conversion failed: {exc}*\n"

    try:
        selected_pages = _resolve_selected_pages(doc, pages)
        if not selected_pages:
            return f"# {name}\n\n*No pages selected.*\n"

        page_heights = _build_page_heights(doc, selected_pages)
        _apply_hf_detection_state(path, settings, detect_pdf_hf_layout_fn)
        hdr_info = _build_hdr_info(
            doc,
            settings,
            compute_body_font_size_fn,
            custom_header_detector_factory_fn,
        )
        kwargs_base = _build_markdown_kwargs(settings, hdr_info)
        page_entries, error = _convert_selected_pages(
            path,
            doc,
            selected_pages,
            settings,
            page_heights,
            kwargs_base,
            pymupdf4llm,
            reflow_markdown_fn,
            strip_bold_from_markdown_headings_fn,
            recover_tables_in_page_markdown_fn,
        )
        if error:
            return f"# {name}\n\n*Conversion failed: {error}*\n"
    finally:
        doc.close()

    return _finalize_pdf_markdown(
        name,
        page_entries,
        settings,
        merge_smart_page_boundaries_fn,
        merge_table_page_boundaries_fn,
        replace_html_br_with_space_fn,
        limit_dot_leaders_fn,
    )
