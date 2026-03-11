"""Highlight mapping helpers for export rendering."""
from __future__ import annotations

from shared.services.highlights.store import get_highlight_store
from shared.services.highlights.store_models import HighlightMatch

from .markdown_blocks import ParsedMarkdownBlock
from .models import ExportOptions


def resolve_matches_for_parsed(
    parsed: list[ParsedMarkdownBlock],
    *,
    options: ExportOptions,
    panel_scope: str,
    tab_name: str,
) -> list[HighlightMatch]:
    """Resolve highlight matches against normalized export text."""
    if not (options.include_highlights or options.include_comments):
        return []
    plain_text = "\n".join(item[0] for item in parsed)
    if not plain_text:
        return []
    return get_highlight_store().resolve_matches(
        panel_scope=panel_scope,
        tab_name=tab_name,
        full_text=plain_text,
    )


def local_matches_for_range(
    matches: list[HighlightMatch],
    *,
    start: int,
    end: int,
) -> list[HighlightMatch]:
    """Return matches overlapping a text range."""
    return [item for item in matches if item.end > start and item.start < end]


def segments_for_block(
    *,
    text: str,
    para_start: int,
    local_matches: list[HighlightMatch],
) -> list[tuple[str, HighlightMatch | None]]:
    """Split a block into highlight-aware segments."""
    if not local_matches:
        return [(text, None)]
    boundaries = {0, len(text)}
    for item in local_matches:
        boundaries.add(max(0, item.start - para_start))
        boundaries.add(min(len(text), item.end - para_start))
    points = sorted(boundaries)

    out: list[tuple[str, HighlightMatch | None]] = []
    for left, right in zip(points, points[1:]):
        if right <= left:
            continue
        active = match_for_segment(
            local_matches,
            para_start + left,
            para_start + right,
        )
        out.append((text[left:right], active))
    return out


def match_for_segment(
    matches: list[HighlightMatch],
    seg_start: int,
    seg_end: int,
) -> HighlightMatch | None:
    """Pick one match for a segment, preferring the widest overlap span."""
    selected: HighlightMatch | None = None
    best_span = -1
    for item in matches:
        if item.start >= seg_end or item.end <= seg_start:
            continue
        span = item.end - item.start
        if span > best_span:
            selected = item
            best_span = span
    return selected


def css_color(value: str) -> str:
    """Normalize a hex color to CSS form."""
    text = str(value or "").strip().lstrip("#")
    if len(text) == 3:
        text = "".join(ch * 2 for ch in text)
    if len(text) != 6:
        return "#F9E2AF"
    try:
        int(text, 16)
    except ValueError:
        return "#F9E2AF"
    return f"#{text}"


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    """Parse hex color into RGB tuple with safe fallback."""
    text = str(value or "").strip().lstrip("#")
    if len(text) == 3:
        text = "".join(ch * 2 for ch in text)
    if len(text) != 6:
        return (249, 226, 175)
    try:
        return (
            int(text[0:2], 16),
            int(text[2:4], 16),
            int(text[4:6], 16),
        )
    except ValueError:
        return (249, 226, 175)


def to_word_highlight_color(color_enum, hex_color: str):
    """Map arbitrary RGB to closest Word highlight palette entry."""
    rgb = hex_to_rgb(hex_color)
    palette = [
        ((255, 255, 0), color_enum.YELLOW),
        ((0, 255, 0), color_enum.BRIGHT_GREEN),
        ((0, 255, 255), color_enum.TURQUOISE),
        ((255, 0, 255), color_enum.PINK),
        ((0, 0, 255), color_enum.BLUE),
        ((255, 0, 0), color_enum.RED),
        ((128, 0, 128), color_enum.VIOLET),
        ((255, 165, 0), color_enum.DARK_YELLOW),
    ]
    best = color_enum.YELLOW
    best_dist = 10**9
    for target_rgb, word_color in palette:
        dist = (
            (rgb[0] - target_rgb[0]) ** 2
            + (rgb[1] - target_rgb[1]) ** 2
            + (rgb[2] - target_rgb[2]) ** 2
        )
        if dist < best_dist:
            best_dist = dist
            best = word_color
    return best
