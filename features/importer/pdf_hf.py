from __future__ import annotations

from collections import defaultdict
import re
from typing import Callable, Optional

from .models import PDFImportSettings

_MD_HEADING = re.compile(r"^#{1,6}\s")
_MD_CODE_FENCE = re.compile(r"^```")

_HF_LEAD_NUM_RE = re.compile(
    r"^\s*(?:\d+(?:\s*[.\-:)]\s*\d+)*\s*[.\-:)]?\s+)+",
    re.IGNORECASE,
)
_HF_PAGE_INLINE_RE = re.compile(
    r"\b(?:seite|page|pag(?:e|ina)|p\.?)\s*\d+(?:\s*(?:/|\\|\||\-|–)\s*\d+)?\b",
    re.IGNORECASE,
)
_HF_PAGE_RATIO_RE = re.compile(r"\b\d+\s*(?:/|\\|\||\-|–)\s*\d+\b")
_HF_STANDALONE_NUM_RE = re.compile(r"\b\d+\b")
_HF_NON_WORD_RE = re.compile(r"[^\w\s<>]", flags=re.UNICODE)

BBox = tuple[float, float, float, float]
ComputeBodyFontSize = Callable[[object, float, float], float]
ExtractTableBBoxes = Callable[[object], list[BBox]]
RectIntersectionRatio = Callable[[BBox, BBox], float]
GroupKey = tuple[str, str, str]
PairKey = tuple[Optional[GroupKey], Optional[GroupKey]]
GroupOccMap = dict[GroupKey, list[dict]]
GroupDisplayMap = dict[GroupKey, str]
PageChoiceMap = dict[int, tuple[GroupKey, float, BBox]]
PairPagesMap = dict[PairKey, list[int]]
PairSamplesMap = dict[PairKey, list[float]]
PairPrototypesMap = dict[PairKey, tuple[float, float]]
PageAssignmentMap = dict[int, PairKey]
RectsByPage = dict[int, dict[str, list[BBox]]]


def _format_page_ranges(pages: list[int], max_len: int = 42) -> str:
    """Format 0-based page indices into compact 1-based ranges."""
    if not pages:
        return "—"
    ordered = sorted(set(pages))
    ranges: list[str] = []
    start = prev = ordered[0]
    for cur in ordered[1:]:
        if cur == prev + 1:
            prev = cur
            continue
        ranges.append(f"{start + 1}" if start == prev else f"{start + 1}-{prev + 1}")
        start = prev = cur
    ranges.append(f"{start + 1}" if start == prev else f"{start + 1}-{prev + 1}")

    out = ", ".join(ranges)
    if len(out) <= max_len:
        return out
    return out[: max_len - 1].rstrip(", ") + "…"


def _robust_quantile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(v) for v in values)
    if len(ordered) == 1:
        return ordered[0]
    q = max(0.0, min(1.0, q))
    idx = int(round(q * (len(ordered) - 1)))
    return ordered[idx]


def _normalize_heading_for_hf(text: str) -> str:
    t = re.sub(r"\s+", " ", text or "").strip().casefold()
    if not t:
        return ""
    t = _HF_LEAD_NUM_RE.sub("", t)
    t = _HF_NON_WORD_RE.sub(" ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _extract_heading_terms_for_hf(markdown: str) -> list[str]:
    """Extract normalized markdown heading titles (without leading numbering)."""
    if not markdown:
        return []

    lines = markdown.splitlines()
    first_nonempty = next((i for i, line in enumerate(lines) if line.strip()), 0)
    in_code_fence = False
    terms: list[str] = []

    for i, line in enumerate(lines):
        stripped = line.strip()
        if _MD_CODE_FENCE.match(stripped):
            in_code_fence = not in_code_fence
            continue
        if in_code_fence:
            continue
        if not _MD_HEADING.match(line):
            continue

        level = len(line) - len(line.lstrip("#"))
        level = max(1, min(level, 6))
        title = line[level:].strip()
        if not title:
            continue
        if i == first_nonempty and level == 1:
            continue

        norm = _normalize_heading_for_hf(title)
        if len(norm) >= 3:
            terms.append(norm)

    seen: set[str] = set()
    out: list[str] = []
    for term in sorted(terms, key=lambda s: (-len(s), s)):
        if term in seen:
            continue
        seen.add(term)
        out.append(term)
    return out


def _build_detection_markdown(path: str, pages: Optional[list[int]] = None) -> str:
    """Generate a raw markdown pass used only for heading extraction in H/F detection."""
    try:
        import pymupdf4llm  # type: ignore
    except Exception:
        return ""

    kwargs = dict(
        pages=pages,
        margins=0,
        page_chunks=True,
        show_progress=False,
    )

    try:
        chunks = pymupdf4llm.to_markdown(path, **kwargs)
    except TypeError:
        try:
            chunks = pymupdf4llm.to_markdown(
                path,
                pages=pages,
                margins=0,
                page_chunks=True,
                show_progress=False,
            )
        except Exception:
            return ""
    except Exception:
        return ""

    if isinstance(chunks, str):
        return chunks
    if isinstance(chunks, dict):
        chunks = [chunks]

    parts: list[str] = []
    for chunk in chunks or []:
        if isinstance(chunk, str):
            text = chunk.strip()
        elif isinstance(chunk, dict):
            text = str(chunk.get("text", "")).strip()
        else:
            text = str(chunk).strip()
        if text:
            parts.append(text)
    return "\n\n".join(parts)


def _alignment_bucket(x0: float, x1: float, page_w: float) -> str:
    if page_w <= 0:
        return "left"
    cx = (x0 + x1) / 2.0
    ratio = cx / page_w
    if ratio < 0.34:
        return "left"
    if ratio > 0.66:
        return "right"
    return "center"


def _alignment_anchor_ratio(x0: float, x1: float, page_w: float, align: str) -> float:
    w = max(page_w, 1.0)
    if align == "left":
        return x0 / w
    if align == "right":
        return (w - x1) / w
    return abs(((x0 + x1) / 2.0) - (w / 2.0)) / w


def _canonicalize_hf_candidate(text: str, heading_terms: list[str]) -> tuple[str, bool, bool]:
    """Canonicalize candidate text: page numbers -> <PAGE>, heading names -> <HEADING>."""
    t = re.sub(r"\s+", " ", text or "").strip().casefold()
    if not t:
        return "", False, False

    t = t.replace("–", "-").replace("—", "-")

    had_page = bool(_HF_PAGE_INLINE_RE.search(t) or _HF_PAGE_RATIO_RE.search(t))
    t = _HF_PAGE_INLINE_RE.sub(" <PAGE> ", t)
    t = _HF_PAGE_RATIO_RE.sub(" <PAGE> ", t)

    t = _HF_NON_WORD_RE.sub(" ", t)
    t = re.sub(r"\s+", " ", t).strip()

    had_heading = False
    for heading in heading_terms:
        if len(heading) < 4:
            continue
        if heading in t:
            t = t.replace(heading, " <HEADING> ")
            had_heading = True

    t = _HF_STANDALONE_NUM_RE.sub(" ", t)
    t = re.sub(r"\s+", " ", t).strip()
    t = t.replace("<page>", "<PAGE>").replace("<heading>", "<HEADING>")

    if not t:
        if had_page and had_heading:
            return "<HEADING> <PAGE>", True, True
        if had_page:
            return "<PAGE>", True, False
        if had_heading:
            return "<HEADING>", False, True
        return "", False, False

    return t, had_page, had_heading


def _candidate_group_is_consistent(occurrences: list[dict]) -> bool:
    if not occurrences:
        return False
    ys = [float(occ["y_metric"]) for occ in occurrences]
    xs = [float(occ["x_metric"]) for occ in occurrences]
    hs = [float(occ["h_ratio"]) for occ in occurrences]
    return (max(ys) - min(ys) <= 0.035 and max(xs) - min(xs) <= 0.085 and max(hs) - min(hs) <= 0.045)


def _has_nonrepeating_above(
    key: tuple[str, str, str],
    occs: list[dict],
    page_side_occ: dict[int, dict[str, list[tuple[tuple[str, str, str], dict]]]],
    repeat_pages: dict[tuple[str, str, str], int],
    min_count: int,
) -> bool:
    """Header guard: non-repeating text above repeated candidate -> reject candidate."""
    for occ in occs:
        pi = int(occ["page"])
        y0 = float(occ["y0"])
        for other_key, other in page_side_occ.get(pi, {}).get("top", []):
            if other_key == key:
                continue
            if repeat_pages.get(other_key, 0) >= min_count:
                continue
            if float(other["y1"]) <= (y0 - 1.0):
                return True
    return False


def _has_nonrepeating_below(
    key: tuple[str, str, str],
    occs: list[dict],
    page_side_occ: dict[int, dict[str, list[tuple[tuple[str, str, str], dict]]]],
    repeat_pages: dict[tuple[str, str, str], int],
    min_count: int,
) -> bool:
    """Footer guard: non-repeating text below repeated candidate -> reject candidate."""
    for occ in occs:
        pi = int(occ["page"])
        y1 = float(occ["y1"])
        for other_key, other in page_side_occ.get(pi, {}).get("bottom", []):
            if other_key == key:
                continue
            if repeat_pages.get(other_key, 0) >= min_count:
                continue
            if float(other["y0"]) >= (y1 + 1.0):
                return True
    return False


def _scan_hf_groups(
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

    for pi, page in enumerate(doc):
        w = float(page.rect.width or 0.0)
        h = float(page.rect.height or 0.0)
        if h <= 0:
            continue
        top_limit = h * top_zone
        bottom_limit = h * (1.0 - bottom_zone)
        table_rects = extract_table_bboxes(page)

        for block in page.get_text("dict")["blocks"]:
            if block.get("type") != 0:
                continue
            bx0, by0, bx1, by1 = [float(v) for v in block.get("bbox", (0, 0, 0, 0))]
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
                    sz = float(span.get("size", 0) or 0)
                    if sz > 0:
                        span_sizes.append(sz)

            text = " ".join(lines_text).strip()
            if not text:
                continue

            canonical, had_page, had_heading = _canonicalize_hf_candidate(text, heading_terms)
            if not canonical:
                continue

            if span_sizes:
                s_sorted = sorted(span_sizes)
                block_size = s_sorted[len(s_sorted) // 2]
            else:
                block_size = body_size
            if block_size > body_size * 1.30 and not had_page and not had_heading:
                continue
            if canonical == "<HEADING>" and block_size > body_size * 1.12 and not had_page:
                continue

            align = _alignment_bucket(bx0, bx1, w)
            x_metric = _alignment_anchor_ratio(bx0, bx1, w, align)
            y_metric = (by1 / h) if side == "top" else ((h - by0) / h)
            h_ratio = max(0.0, (by1 - by0) / h)
            key: GroupKey = (side, align, canonical)
            group_occ[key].append(
                {
                    "page": pi,
                    "bbox": (bx0, by0, bx1, by1),
                    "page_h": h,
                    "y0": by0,
                    "y1": by1,
                    "x_metric": x_metric,
                    "y_metric": y_metric,
                    "h_ratio": h_ratio,
                    "had_page": had_page,
                    "had_heading": had_heading,
                }
            )
            group_display.setdefault(key, text)

    return group_occ, group_display


def _accept_hf_groups(group_occ: GroupOccMap, min_count: int) -> GroupOccMap:
    accepted: GroupOccMap = {}
    repeat_pages = {key: len({int(occ["page"]) for occ in occs}) for key, occs in group_occ.items()}
    page_side_occ: dict[int, dict[str, list[tuple[GroupKey, dict]]]] = defaultdict(
        lambda: {"top": [], "bottom": []}
    )
    for key, occs in group_occ.items():
        side = key[0]
        for occ in occs:
            pi = int(occ["page"])
            page_side_occ[pi][side].append((key, occ))

    for key, occs in group_occ.items():
        pages_set = {int(occ["page"]) for occ in occs}
        if len(pages_set) < min_count:
            continue
        if not _candidate_group_is_consistent(occs):
            continue
        if key[0] == "top" and _has_nonrepeating_above(
            key, occs, page_side_occ, repeat_pages, min_count
        ):
            continue
        if key[0] == "bottom" and _has_nonrepeating_below(
            key, occs, page_side_occ, repeat_pages, min_count
        ):
            continue
        if key[2] == "<HEADING>" and len(pages_set) < max(min_count + 1, 4):
            continue
        accepted[key] = occs

    return accepted


def _select_page_choices(accepted: GroupOccMap) -> tuple[PageChoiceMap, PageChoiceMap]:
    page_header_choice: PageChoiceMap = {}
    page_footer_choice: PageChoiceMap = {}

    for key, occs in accepted.items():
        side = key[0]
        for occ in occs:
            pi = int(occ["page"])
            bbox = occ["bbox"]
            if side == "top":
                margin = max(0.0, float(occ["y1"]) + 6.0)
                prev = page_header_choice.get(pi)
                if prev is None or margin > prev[1]:
                    page_header_choice[pi] = (key, margin, bbox)
            else:
                margin = max(0.0, float(occ["page_h"]) - float(occ["y0"]) + 6.0)
                prev = page_footer_choice.get(pi)
                if prev is None or margin > prev[1]:
                    page_footer_choice[pi] = (key, margin, bbox)

    return page_header_choice, page_footer_choice


def _collect_pair_samples(
    n_pages: int,
    page_header_choice: PageChoiceMap,
    page_footer_choice: PageChoiceMap,
) -> tuple[PairPagesMap, PairSamplesMap, PairSamplesMap]:
    pair_pages: PairPagesMap = defaultdict(list)
    pair_top_samples: PairSamplesMap = defaultdict(list)
    pair_bottom_samples: PairSamplesMap = defaultdict(list)

    for pi in range(n_pages):
        h_entry = page_header_choice.get(pi)
        f_entry = page_footer_choice.get(pi)
        h_key = h_entry[0] if h_entry else None
        f_key = f_entry[0] if f_entry else None
        pair_key: PairKey = (h_key, f_key)
        pair_pages[pair_key].append(pi)
        pair_top_samples[pair_key].append(h_entry[1] if h_entry else 0.0)
        pair_bottom_samples[pair_key].append(f_entry[1] if f_entry else 0.0)

    return pair_pages, pair_top_samples, pair_bottom_samples


def _select_pair_keys(
    pair_pages: PairPagesMap,
    pair_top_samples: PairSamplesMap,
    pair_bottom_samples: PairSamplesMap,
    max_pairs: int,
) -> list[PairKey]:
    all_pairs = list(pair_pages.keys())
    all_pairs.sort(
        key=lambda key: (
            len(pair_pages.get(key, [])),
            (1 if key[0] else 0) + (1 if key[1] else 0),
            _robust_quantile(pair_top_samples.get(key, [0.0]), 0.50) + _robust_quantile(
                pair_bottom_samples.get(key, [0.0]), 0.50
            ),
        ),
        reverse=True,
    )

    selected_pair_keys = all_pairs[:max_pairs] if all_pairs else [(None, None)]
    non_empty_pairs = [key for key in all_pairs if (key[0] is not None or key[1] is not None)]
    if selected_pair_keys and selected_pair_keys[0] == (None, None) and non_empty_pairs:
        selected_pair_keys[0] = non_empty_pairs[0]
    return selected_pair_keys


def _build_pair_prototypes(
    selected_pair_keys: list[PairKey],
    pair_top_samples: PairSamplesMap,
    pair_bottom_samples: PairSamplesMap,
) -> PairPrototypesMap:
    pair_prototypes: PairPrototypesMap = {}
    for key in selected_pair_keys:
        tvals = pair_top_samples.get(key, [0.0])
        bvals = pair_bottom_samples.get(key, [0.0])
        pair_prototypes[key] = (
            max(0.0, _robust_quantile(tvals, 0.85)),
            max(0.0, _robust_quantile(bvals, 0.85)),
        )
    return pair_prototypes


def _pair_distance(
    pi: int,
    pair_key: PairKey,
    page_header_choice: PageChoiceMap,
    page_footer_choice: PageChoiceMap,
    pair_prototypes: PairPrototypesMap,
) -> float:
    h_entry = page_header_choice.get(pi)
    f_entry = page_footer_choice.get(pi)
    raw_top = h_entry[1] if h_entry else 0.0
    raw_bottom = f_entry[1] if f_entry else 0.0
    proto_top, proto_bottom = pair_prototypes[pair_key]
    dist = abs(raw_top - proto_top) + abs(raw_bottom - proto_bottom)

    h_raw = h_entry[0] if h_entry else None
    f_raw = f_entry[0] if f_entry else None
    h_proto, f_proto = pair_key
    if h_raw and h_proto and h_raw != h_proto:
        dist += 22.0
    elif h_raw and not h_proto:
        dist += 28.0
    elif not h_raw and h_proto:
        dist += 10.0
    if f_raw and f_proto and f_raw != f_proto:
        dist += 22.0
    elif f_raw and not f_proto:
        dist += 28.0
    elif not f_raw and f_proto:
        dist += 10.0
    return dist


def _assign_pages_to_pairs(
    n_pages: int,
    selected_pair_keys: list[PairKey],
    page_header_choice: PageChoiceMap,
    page_footer_choice: PageChoiceMap,
    pair_prototypes: PairPrototypesMap,
) -> PageAssignmentMap:
    page_assignment: PageAssignmentMap = {}
    for pi in range(n_pages):
        best = min(
            selected_pair_keys,
            key=lambda key: _pair_distance(
                pi,
                key,
                page_header_choice,
                page_footer_choice,
                pair_prototypes,
            ),
        )
        page_assignment[pi] = best

    for pi in range(1, n_pages - 1):
        left = page_assignment[pi - 1]
        cur = page_assignment[pi]
        right = page_assignment[pi + 1]
        if left == right and cur != left:
            if _pair_distance(pi, left, page_header_choice, page_footer_choice, pair_prototypes) <= (
                _pair_distance(pi, cur, page_header_choice, page_footer_choice, pair_prototypes) + 6.0
            ):
                page_assignment[pi] = left

    return page_assignment


def _build_margins_and_rects(
    n_pages: int,
    page_assignment: PageAssignmentMap,
    pair_prototypes: PairPrototypesMap,
    page_header_choice: PageChoiceMap,
    page_footer_choice: PageChoiceMap,
) -> tuple[dict[int, float], dict[int, float], RectsByPage, float, float]:
    top_by_page: dict[int, float] = {}
    bottom_by_page: dict[int, float] = {}
    hf_rects_by_page: RectsByPage = {}

    for pi in range(n_pages):
        pair_key = page_assignment[pi]
        p_top, p_bottom = pair_prototypes.get(pair_key, (0.0, 0.0))
        top_by_page[pi] = p_top
        bottom_by_page[pi] = p_bottom

        h_proto, f_proto = pair_key
        page_rects = {"header": [], "footer": []}
        h_entry = page_header_choice.get(pi)
        f_entry = page_footer_choice.get(pi)
        if h_entry and h_proto and h_entry[0] == h_proto:
            page_rects["header"].append(h_entry[2])
        if f_entry and f_proto and f_entry[0] == f_proto:
            page_rects["footer"].append(f_entry[2])
        if page_rects["header"] or page_rects["footer"]:
            hf_rects_by_page[pi] = page_rects

    top_margin = max(top_by_page.values(), default=0.0)
    bottom_margin = max(bottom_by_page.values(), default=0.0)
    return top_by_page, bottom_by_page, hf_rects_by_page, top_margin, bottom_margin


def _build_detection_info(
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
    used_header_groups = {pair[0] for pair in selected_pair_keys if pair[0] is not None}
    used_footer_groups = {pair[1] for pair in selected_pair_keys if pair[1] is not None}

    found_headers: list[tuple[str, int, float, list[int], str]] = []
    for key in used_header_groups:
        occs = accepted.get(key, [])
        pages_set = sorted({int(occ["page"]) for occ in occs})
        count = len(pages_set)
        max_y = max((float(occ["y1"]) for occ in occs), default=0.0)
        found_headers.append((group_display.get(key, key[2]), count, max_y, pages_set, key[1]))

    found_footers: list[tuple[str, int, float, list[int], str]] = []
    for key in used_footer_groups:
        occs = accepted.get(key, [])
        pages_set = sorted({int(occ["page"]) for occ in occs})
        count = len(pages_set)
        margins = [max(0.0, float(occ["page_h"]) - float(occ["y0"]) + 6.0) for occ in occs]
        max_m = max(margins, default=0.0)
        found_footers.append((group_display.get(key, key[2]), count, max_m, pages_set, key[1]))

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
        for disp, count, max_y, pages_set, align in sorted(found_headers, key=lambda x: -x[1]):
            lines.append(
                f'  • [{align}] "{disp[:60]}" ({count} pages: {_format_page_ranges(pages_set)}, '
                f"max bottom {max_y:.1f} pt)"
            )
    else:
        lines.append("\nNo repeated header groups detected.")

    if found_footers:
        lines.append(f"\nDetected FOOTER groups ({len(found_footers)}):")
        for disp, count, max_m, pages_set, align in sorted(found_footers, key=lambda x: -x[1]):
            lines.append(
                f'  • [{align}] "{disp[:60]}" ({count} pages: {_format_page_ranges(pages_set)}, '
                f"max margin {max_m:.1f} pt)"
            )
    else:
        lines.append("\nNo repeated footer groups detected.")

    assigned_pages_by_pair: PairPagesMap = defaultdict(list)
    for pi, key in page_assignment.items():
        assigned_pages_by_pair[key].append(pi)

    lines.append(f"\nSelected pairs: {len(selected_pair_keys)}")
    for idx, key in enumerate(selected_pair_keys, start=1):
        h_key, f_key = key
        p_top, p_bottom = pair_prototypes.get(key, (0.0, 0.0))
        pages_str = _format_page_ranges(assigned_pages_by_pair.get(key, []))
        h_name = group_display.get(h_key, "—") if h_key else "—"
        f_name = group_display.get(f_key, "—") if f_key else "—"
        lines.append(f"  {idx}. pages {pages_str} | top {p_top:.1f} pt | bottom {p_bottom:.1f} pt")
        lines.append(f'     H: "{h_name[:60]}"')
        lines.append(f'     F: "{f_name[:60]}"')

    lines.append("\nPer-page assigned margins (top / bottom):")
    for pi in range(min(40, n_pages)):
        lines.append(f"  • Page {pi + 1}: {top_by_page[pi]:.1f} pt / {bottom_by_page[pi]:.1f} pt")
    if n_pages > 40:
        lines.append(f"  • … {n_pages - 40} more pages")
    return "\n".join(lines)


def detect_pdf_hf_layout(
    path: str,
    settings: PDFImportSettings,
    *,
    compute_body_font_size: ComputeBodyFontSize,
    extract_table_bboxes: ExtractTableBBoxes,
    rect_intersection_ratio: RectIntersectionRatio,
) -> dict:
    """
    Analyse repeated header/footer lines and return per-page margins + geometry.

    Returns a dict with keys:
      top_margin, bottom_margin, info,
      top_by_page, bottom_by_page, hf_rects_by_page
    """
    empty = {
        "top_margin": 0.0,
        "bottom_margin": 0.0,
        "info": "",
        "top_by_page": {},
        "bottom_by_page": {},
        "hf_rects_by_page": {},
    }

    try:
        import fitz  # type: ignore
    except ImportError:
        empty["info"] = "PyMuPDF (fitz) not available."
        return empty

    try:
        doc = fitz.open(path)
    except Exception as exc:
        empty["info"] = f"Could not open PDF: {exc}"
        return empty

    n_pages = len(doc)
    if n_pages == 0:
        doc.close()
        empty["info"] = "Empty PDF."
        return empty

    top_zone = 0.32
    bottom_zone = 0.32
    min_count = max(settings.hf_min_pages, int(n_pages * settings.hf_threshold))
    max_pairs = max(1, int(getattr(settings, "hf_max_pairs", 3) or 1))
    raw_markdown = _build_detection_markdown(path, pages=None)
    heading_terms = _extract_heading_terms_for_hf(raw_markdown)

    try:
        body_size = compute_body_font_size(doc, 0.20, 0.20)
        group_occ, group_display = _scan_hf_groups(
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

    accepted = _accept_hf_groups(group_occ, min_count)
    page_header_choice, page_footer_choice = _select_page_choices(accepted)
    pair_pages, pair_top_samples, pair_bottom_samples = _collect_pair_samples(
        n_pages, page_header_choice, page_footer_choice
    )
    selected_pair_keys = _select_pair_keys(
        pair_pages,
        pair_top_samples,
        pair_bottom_samples,
        max_pairs,
    )
    pair_prototypes = _build_pair_prototypes(
        selected_pair_keys,
        pair_top_samples,
        pair_bottom_samples,
    )
    page_assignment = _assign_pages_to_pairs(
        n_pages,
        selected_pair_keys,
        page_header_choice,
        page_footer_choice,
        pair_prototypes,
    )
    top_by_page, bottom_by_page, hf_rects_by_page, top_margin, bottom_margin = _build_margins_and_rects(
        n_pages,
        page_assignment,
        pair_prototypes,
        page_header_choice,
        page_footer_choice,
    )
    info = _build_detection_info(
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
