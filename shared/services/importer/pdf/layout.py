from __future__ import annotations

from ..models import PDFImportSettings
from .fonts import _compute_body_font_size
from .layout_groups import accept_hf_groups, scan_hf_groups
from .layout_heading import build_detection_markdown, extract_heading_terms_for_hf
from .layout_pairs import (
    assign_pages_to_pairs,
    build_margins_and_rects,
    build_pair_prototypes,
    collect_pair_samples,
    select_page_choices,
    select_pair_keys,
)
from .layout_report import build_detection_info
from .layout_types import ComputeBodyFontSize, ExtractTableBBoxes, RectIntersectionRatio
from .tables import _extract_table_bboxes, _rect_intersection_ratio

_EMPTY_RESULT = {
    "top_margin": 0.0,
    "bottom_margin": 0.0,
    "info": "",
    "top_by_page": {},
    "bottom_by_page": {},
    "hf_rects_by_page": {},
}


def _empty_result(info: str) -> dict:
    result = dict(_EMPTY_RESULT)
    result["info"] = info
    return result


def detect_pdf_hf_layout(
    path: str,
    settings: PDFImportSettings,
    *,
    compute_body_font_size: ComputeBodyFontSize = _compute_body_font_size,
    extract_table_bboxes: ExtractTableBBoxes = _extract_table_bboxes,
    rect_intersection_ratio: RectIntersectionRatio = _rect_intersection_ratio,
) -> dict:
    """
    Analyse repeated header/footer lines and return per-page margins + geometry.

    Returns a dict with keys:
      top_margin, bottom_margin, info,
      top_by_page, bottom_by_page, hf_rects_by_page
    """
    try:
        import fitz  # type: ignore
    except ImportError:
        return _empty_result("PyMuPDF (fitz) not available.")

    try:
        doc = fitz.open(path)
    except Exception as exc:
        return _empty_result(f"Could not open PDF: {exc}")

    n_pages = len(doc)
    if n_pages == 0:
        doc.close()
        return _empty_result("Empty PDF.")

    top_zone = 0.32
    bottom_zone = 0.32
    min_count = max(settings.hf_min_pages, int(n_pages * settings.hf_threshold))
    max_pairs = max(1, int(getattr(settings, "hf_max_pairs", 3) or 1))

    raw_markdown = build_detection_markdown(path, pages=None)
    heading_terms = extract_heading_terms_for_hf(raw_markdown)

    try:
        body_size = compute_body_font_size(doc, 0.20, 0.20)
        group_occ, group_display = scan_hf_groups(
            doc,
            heading_terms,
            body_size,
            top_zone=top_zone,
            bottom_zone=bottom_zone,
            extract_table_bboxes=extract_table_bboxes,
            rect_intersection_ratio=rect_intersection_ratio,
        )
    finally:
        doc.close()

    accepted = accept_hf_groups(group_occ, min_count)
    page_header_choice, page_footer_choice = select_page_choices(accepted)
    pair_pages, pair_top_samples, pair_bottom_samples = collect_pair_samples(
        n_pages,
        page_header_choice,
        page_footer_choice,
    )
    selected_pair_keys = select_pair_keys(
        pair_pages,
        pair_top_samples,
        pair_bottom_samples,
        max_pairs,
    )
    pair_prototypes = build_pair_prototypes(
        selected_pair_keys,
        pair_top_samples,
        pair_bottom_samples,
    )
    page_assignment = assign_pages_to_pairs(
        n_pages,
        selected_pair_keys,
        page_header_choice,
        page_footer_choice,
        pair_prototypes,
    )
    top_by_page, bottom_by_page, hf_rects_by_page, top_margin, bottom_margin = build_margins_and_rects(
        n_pages,
        page_assignment,
        pair_prototypes,
        page_header_choice,
        page_footer_choice,
    )
    info = build_detection_info(
        n_pages=n_pages,
        min_count=min_count,
        max_pairs=max_pairs,
        settings=settings,
        heading_terms=heading_terms,
        selected_pair_keys=selected_pair_keys,
        page_assignment=page_assignment,
        pair_prototypes=pair_prototypes,
        accepted=accepted,
        group_display=group_display,
        top_by_page=top_by_page,
        bottom_by_page=bottom_by_page,
    )

    return {
        "top_margin": top_margin,
        "bottom_margin": bottom_margin,
        "info": info,
        "top_by_page": top_by_page,
        "bottom_by_page": bottom_by_page,
        "hf_rects_by_page": hf_rects_by_page,
    }
