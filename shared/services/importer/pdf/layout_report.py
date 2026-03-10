from __future__ import annotations

from collections import defaultdict

from ..models import PDFImportSettings
from .layout_types import (
    GroupDisplayMap,
    GroupOccMap,
    PageAssignmentMap,
    PairKey,
    PairPagesMap,
    PairPrototypesMap,
)


def format_page_ranges(pages: list[int], max_len: int = 42) -> str:
    """Format 0-based page indices into compact 1-based ranges."""
    if not pages:
        return "—"

    ordered = sorted(set(pages))
    ranges: list[str] = []
    start = prev = ordered[0]
    for current in ordered[1:]:
        if current == prev + 1:
            prev = current
            continue
        ranges.append(f"{start + 1}" if start == prev else f"{start + 1}-{prev + 1}")
        start = prev = current
    ranges.append(f"{start + 1}" if start == prev else f"{start + 1}-{prev + 1}")

    output = ", ".join(ranges)
    if len(output) <= max_len:
        return output
    return output[: max_len - 1].rstrip(", ") + "…"


def _collect_used_groups(selected_pair_keys: list[PairKey]) -> tuple[set, set]:
    used_headers = {pair[0] for pair in selected_pair_keys if pair[0] is not None}
    used_footers = {pair[1] for pair in selected_pair_keys if pair[1] is not None}
    return used_headers, used_footers


def _build_found_headers(
    used_header_groups: set,
    accepted: GroupOccMap,
    group_display: GroupDisplayMap,
) -> list[tuple[str, int, float, list[int], str]]:
    found_headers: list[tuple[str, int, float, list[int], str]] = []
    for key in used_header_groups:
        occurrences = accepted.get(key, [])
        pages_set = sorted({int(occurrence["page"]) for occurrence in occurrences})
        count = len(pages_set)
        max_y = max((float(occurrence["y1"]) for occurrence in occurrences), default=0.0)
        found_headers.append((group_display.get(key, key[2]), count, max_y, pages_set, key[1]))
    return found_headers


def _build_found_footers(
    used_footer_groups: set,
    accepted: GroupOccMap,
    group_display: GroupDisplayMap,
) -> list[tuple[str, int, float, list[int], str]]:
    found_footers: list[tuple[str, int, float, list[int], str]] = []
    for key in used_footer_groups:
        occurrences = accepted.get(key, [])
        pages_set = sorted({int(occurrence["page"]) for occurrence in occurrences})
        count = len(pages_set)
        margins = [
            max(0.0, float(occurrence["page_h"]) - float(occurrence["y0"]) + 6.0)
            for occurrence in occurrences
        ]
        max_margin = max(margins, default=0.0)
        found_footers.append((group_display.get(key, key[2]), count, max_margin, pages_set, key[1]))
    return found_footers


def build_detection_info(
    *,
    n_pages: int,
    min_count: int,
    max_pairs: int,
    settings: PDFImportSettings,
    heading_terms: list[str],
    selected_pair_keys: list[PairKey],
    page_assignment: PageAssignmentMap,
    pair_prototypes: PairPrototypesMap,
    accepted: GroupOccMap,
    group_display: GroupDisplayMap,
    top_by_page: dict[int, float],
    bottom_by_page: dict[int, float],
) -> str:
    used_header_groups, used_footer_groups = _collect_used_groups(selected_pair_keys)
    found_headers = _build_found_headers(used_header_groups, accepted, group_display)
    found_footers = _build_found_footers(used_footer_groups, accepted, group_display)

    lines: list[str] = [
        f"Pages: {n_pages} | Min repeats: {min_count} "
        f"(>= {settings.hf_min_pages} pages or >= {settings.hf_threshold * 100:.0f}% of doc)",
        f"Max header/footer pairs: {max_pairs}",
        f"Markdown headings considered: {len(heading_terms)}",
        "Rule: text match + stable position + alignment (left/center/right).",
        "Guard: non-repeating above excludes header candidates; non-repeating below excludes footer candidates.",
    ]

    if found_headers:
        lines.append(f"\nDetected HEADER groups ({len(found_headers)}):")
        for display, count, max_y, pages_set, align in sorted(found_headers, key=lambda item: -item[1]):
            lines.append(
                f'  • [{align}] "{display[:60]}" ({count} pages: {format_page_ranges(pages_set)}, '
                f"max bottom {max_y:.1f} pt)"
            )
    else:
        lines.append("\nNo repeated header groups detected.")

    if found_footers:
        lines.append(f"\nDetected FOOTER groups ({len(found_footers)}):")
        for display, count, max_margin, pages_set, align in sorted(found_footers, key=lambda item: -item[1]):
            lines.append(
                f'  • [{align}] "{display[:60]}" ({count} pages: {format_page_ranges(pages_set)}, '
                f"max margin {max_margin:.1f} pt)"
            )
    else:
        lines.append("\nNo repeated footer groups detected.")

    assigned_pages_by_pair: PairPagesMap = defaultdict(list)
    for page_index, key in page_assignment.items():
        assigned_pages_by_pair[key].append(page_index)

    lines.append(f"\nSelected pairs: {len(selected_pair_keys)}")
    for index, key in enumerate(selected_pair_keys, start=1):
        header_key, footer_key = key
        pair_top, pair_bottom = pair_prototypes.get(key, (0.0, 0.0))
        pages = format_page_ranges(assigned_pages_by_pair.get(key, []))
        header_name = group_display.get(header_key, "—") if header_key else "—"
        footer_name = group_display.get(footer_key, "—") if footer_key else "—"

        lines.append(f"  {index}. pages {pages} | top {pair_top:.1f} pt | bottom {pair_bottom:.1f} pt")
        lines.append(f'     H: "{header_name[:60]}"')
        lines.append(f'     F: "{footer_name[:60]}"')

    lines.append("\nPer-page assigned margins (top / bottom):")
    for page_index in range(min(40, n_pages)):
        lines.append(
            f"  • Page {page_index + 1}: "
            f"{top_by_page[page_index]:.1f} pt / {bottom_by_page[page_index]:.1f} pt"
        )
    if n_pages > 40:
        lines.append(f"  • … {n_pages - 40} more pages")

    return "\n".join(lines)
