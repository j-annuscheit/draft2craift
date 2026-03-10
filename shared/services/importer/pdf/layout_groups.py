from __future__ import annotations

from collections import defaultdict

from .layout_heading import canonicalize_hf_candidate
from .layout_types import (
    ExtractTableBBoxes,
    GroupDisplayMap,
    GroupKey,
    GroupOccMap,
    GroupOccurrence,
    RectIntersectionRatio,
)


def alignment_bucket(x0: float, x1: float, page_w: float) -> str:
    if page_w <= 0:
        return "left"
    center_x = (x0 + x1) / 2.0
    ratio = center_x / page_w
    if ratio < 0.34:
        return "left"
    if ratio > 0.66:
        return "right"
    return "center"


def alignment_anchor_ratio(x0: float, x1: float, page_w: float, align: str) -> float:
    width = max(page_w, 1.0)
    if align == "left":
        return x0 / width
    if align == "right":
        return (width - x1) / width
    return abs(((x0 + x1) / 2.0) - (width / 2.0)) / width


def candidate_group_is_consistent(occurrences: list[GroupOccurrence]) -> bool:
    if not occurrences:
        return False
    y_values = [float(occ["y_metric"]) for occ in occurrences]
    x_values = [float(occ["x_metric"]) for occ in occurrences]
    h_values = [float(occ["h_ratio"]) for occ in occurrences]
    return (
        max(y_values) - min(y_values) <= 0.035
        and max(x_values) - min(x_values) <= 0.085
        and max(h_values) - min(h_values) <= 0.045
    )


def has_nonrepeating_above(
    key: GroupKey,
    occurrences: list[GroupOccurrence],
    page_side_occ: dict[int, dict[str, list[tuple[GroupKey, GroupOccurrence]]]],
    repeat_pages: dict[GroupKey, int],
    min_count: int,
) -> bool:
    """Header guard: non-repeating text above repeated candidate -> reject candidate."""
    for occurrence in occurrences:
        page_index = int(occurrence["page"])
        y0 = float(occurrence["y0"])
        for other_key, other in page_side_occ.get(page_index, {}).get("top", []):
            if other_key == key:
                continue
            if repeat_pages.get(other_key, 0) >= min_count:
                continue
            if float(other["y1"]) <= (y0 - 1.0):
                return True
    return False


def has_nonrepeating_below(
    key: GroupKey,
    occurrences: list[GroupOccurrence],
    page_side_occ: dict[int, dict[str, list[tuple[GroupKey, GroupOccurrence]]]],
    repeat_pages: dict[GroupKey, int],
    min_count: int,
) -> bool:
    """Footer guard: non-repeating text below repeated candidate -> reject candidate."""
    for occurrence in occurrences:
        page_index = int(occurrence["page"])
        y1 = float(occurrence["y1"])
        for other_key, other in page_side_occ.get(page_index, {}).get("bottom", []):
            if other_key == key:
                continue
            if repeat_pages.get(other_key, 0) >= min_count:
                continue
            if float(other["y0"]) >= (y1 + 1.0):
                return True
    return False


def scan_hf_groups(
    doc,
    heading_terms: list[str],
    body_size: float,
    *,
    top_zone: float,
    bottom_zone: float,
    extract_table_bboxes: ExtractTableBBoxes,
    rect_intersection_ratio: RectIntersectionRatio,
) -> tuple[GroupOccMap, GroupDisplayMap]:
    group_occ: GroupOccMap = defaultdict(list)
    group_display: GroupDisplayMap = {}

    for page_index, page in enumerate(doc):
        page_width = float(page.rect.width or 0.0)
        page_height = float(page.rect.height or 0.0)
        if page_height <= 0:
            continue
        top_limit = page_height * top_zone
        bottom_limit = page_height * (1.0 - bottom_zone)
        table_rects = extract_table_bboxes(page)

        for block in page.get_text("dict")["blocks"]:
            if block.get("type") != 0:
                continue
            bx0, by0, bx1, by1 = [float(value) for value in block.get("bbox", (0, 0, 0, 0))]
            if by1 <= top_limit:
                side = "top"
            elif by0 >= bottom_limit:
                side = "bottom"
            else:
                continue

            block_rect = (bx0, by0, bx1, by1)
            if any(rect_intersection_ratio(block_rect, rect) >= 0.25 for rect in table_rects):
                continue

            lines_text: list[str] = []
            span_sizes: list[float] = []
            for line in block.get("lines", []):
                words = [
                    (span.get("text") or "").strip()
                    for span in line.get("spans", [])
                    if (span.get("text") or "").strip()
                ]
                if words:
                    lines_text.append(" ".join(words))
                for span in line.get("spans", []):
                    size = float(span.get("size", 0) or 0)
                    if size > 0:
                        span_sizes.append(size)

            text = " ".join(lines_text).strip()
            if not text:
                continue

            canonical, had_page, had_heading = canonicalize_hf_candidate(text, heading_terms)
            if not canonical:
                continue

            if span_sizes:
                sorted_sizes = sorted(span_sizes)
                block_size = sorted_sizes[len(sorted_sizes) // 2]
            else:
                block_size = body_size
            if block_size > body_size * 1.30 and not had_page and not had_heading:
                continue
            if canonical == "<HEADING>" and block_size > body_size * 1.12 and not had_page:
                continue

            align = alignment_bucket(bx0, bx1, page_width)
            x_metric = alignment_anchor_ratio(bx0, bx1, page_width, align)
            y_metric = (by1 / page_height) if side == "top" else ((page_height - by0) / page_height)
            h_ratio = max(0.0, (by1 - by0) / page_height)
            key: GroupKey = (side, align, canonical)

            occurrence: GroupOccurrence = {
                "page": page_index,
                "bbox": (bx0, by0, bx1, by1),
                "page_h": page_height,
                "y0": by0,
                "y1": by1,
                "x_metric": x_metric,
                "y_metric": y_metric,
                "h_ratio": h_ratio,
                "had_page": had_page,
                "had_heading": had_heading,
            }
            group_occ[key].append(occurrence)
            group_display.setdefault(key, text)

    return group_occ, group_display


def accept_hf_groups(group_occ: GroupOccMap, min_count: int) -> GroupOccMap:
    accepted: GroupOccMap = {}
    repeat_pages = {
        key: len({int(occurrence["page"]) for occurrence in occurrences})
        for key, occurrences in group_occ.items()
    }
    page_side_occ: dict[int, dict[str, list[tuple[GroupKey, GroupOccurrence]]]] = defaultdict(
        lambda: {"top": [], "bottom": []}
    )
    for key, occurrences in group_occ.items():
        side = key[0]
        for occurrence in occurrences:
            page_index = int(occurrence["page"])
            page_side_occ[page_index][side].append((key, occurrence))

    for key, occurrences in group_occ.items():
        pages_set = {int(occurrence["page"]) for occurrence in occurrences}
        if len(pages_set) < min_count:
            continue
        if not candidate_group_is_consistent(occurrences):
            continue
        if key[0] == "top" and has_nonrepeating_above(
            key,
            occurrences,
            page_side_occ,
            repeat_pages,
            min_count,
        ):
            continue
        if key[0] == "bottom" and has_nonrepeating_below(
            key,
            occurrences,
            page_side_occ,
            repeat_pages,
            min_count,
        ):
            continue
        if key[2] == "<HEADING>" and len(pages_set) < max(min_count + 1, 4):
            continue
        accepted[key] = occurrences

    return accepted
