from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Optional

from shared.services.importer.models import PDFImportSettings
from shared.services.importer.pdf.header_detector import CustomHeaderDetector as _CustomHeaderDetector

_MD_INLINE_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_MD_INLINE_CODE_RE = re.compile(r"`([^`]+)`")
_WS_RE = re.compile(r"\s+")
_STRIP_PUNCT_RE = re.compile(r"[^\w\s\-]", flags=re.UNICODE)
_NUM_PREFIX_ALLOWED_RE = re.compile(r"^[0-9\s().,\-–—:]+$")
_LEADING_HEADING_NUM_RE = re.compile(
    r"^\s*\(?\d+(?:[.\-]\d+)*\)?[.)]?\s+",
    flags=re.IGNORECASE,
)
_MD_HEADING_RE = re.compile(r"^#{1,6}\s")
_MD_CODE_FENCE_RE = re.compile(r"^```")
_MD_PAGE_MARK_RE = re.compile(r"^\[Seite\s+\d+\]\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class _HeadingAnchor:
    level: int
    title: str
    prev_text: str = ""
    next_text: str = ""


@dataclass(frozen=True)
class _PageLine:
    order: int
    x0: float
    y0: float
    x1: float
    y1: float
    text: str
    norm_cf: str
    plain_cf: str


def _normalize_heading_text(text: str) -> str:
    """Normalize markdown heading text for robust PDF text lookup."""
    if not text:
        return ""
    text = _MD_INLINE_LINK_RE.sub(r"\1", text)
    text = _MD_INLINE_CODE_RE.sub(r"\1", text)
    text = text.replace("*", "").replace("_", "").replace("~", "")
    text = _WS_RE.sub(" ", text).strip()
    return text


def _normalize_for_compare(text: str) -> str:
    return _WS_RE.sub(" ", text).strip().casefold()


def _plain_for_compare(text: str) -> str:
    return _normalize_for_compare(_STRIP_PUNCT_RE.sub(" ", text))


def _heading_query_variants(title: str) -> list[str]:
    """Generate robust search queries from a markdown heading title."""
    clean = _normalize_heading_text(title)
    if not clean:
        return []

    variants: list[str] = [clean]
    without_num = _strip_leading_heading_number(clean)
    if without_num and without_num != clean:
        variants.append(without_num)
    words = clean.split()
    for n in (12, 8, 6, 4):
        if len(words) >= n:
            variants.append(" ".join(words[:n]))
    if without_num:
        wwords = without_num.split()
        for n in (10, 8, 6, 4):
            if len(wwords) >= n:
                variants.append(" ".join(wwords[:n]))

    plain = _STRIP_PUNCT_RE.sub("", clean)
    plain = _WS_RE.sub(" ", plain).strip()
    if plain and plain != clean:
        variants.append(plain)
        pwords = plain.split()
        for n in (8, 6, 4):
            if len(pwords) >= n:
                variants.append(" ".join(pwords[:n]))

    out: list[str] = []
    seen: set[str] = set()
    for q in variants:
        q = q.strip()
        if len(q) < 3:
            continue
        key = q.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(q)
    return out


def _strip_leading_heading_number(text: str) -> str:
    """
    Remove a common section-number prefix from heading text.
    Example: "2.1 Der Titel" -> "Der Titel".
    """
    if not text:
        return ""
    s = text.strip()
    # Some PDFs split "2.1" and title into separate text boxes.
    # We therefore search both with and without numeric prefix.
    for _ in range(3):
        m = _LEADING_HEADING_NUM_RE.match(s)
        if not m:
            break
        s = s[m.end():].lstrip()
    return s


def _collect_page_lines(page, top_limit: float, bottom_limit: float) -> list[_PageLine]:
    """Collect PDF text lines (word-based) with geometry and normalized text."""
    try:
        words = page.get_text("words") or []
    except Exception:
        return []
    if not words:
        return []

    lines: dict[tuple[int, int], list[tuple[float, float, float, float, str, int]]] = {}
    for item in words:
        if len(item) < 8:
            continue
        x0, y0, x1, y1, txt, block_no, line_no, word_no = item[:8]
        if y1 <= top_limit or y0 >= bottom_limit:
            continue
        key = (int(block_no), int(line_no))
        lines.setdefault(key, []).append((
            float(x0), float(y0), float(x1), float(y1), str(txt), int(word_no),
        ))

    if not lines:
        return []

    out: list[_PageLine] = []
    for idx, words_in_line in enumerate(
        sorted(lines.values(), key=lambda ws: (min(w[1] for w in ws), min(w[0] for w in ws)))
    ):
        words_in_line.sort(key=lambda w: w[5])
        line_text = " ".join(w[4] for w in words_in_line if w[4]).strip()
        if not line_text:
            continue
        norm_cf = _normalize_for_compare(line_text)
        plain_cf = _plain_for_compare(line_text)
        if not norm_cf:
            continue
        x0 = min(w[0] for w in words_in_line)
        y0 = min(w[1] for w in words_in_line)
        x1 = max(w[2] for w in words_in_line)
        y1 = max(w[3] for w in words_in_line)
        out.append(_PageLine(idx, x0, y0, x1, y1, line_text, norm_cf, plain_cf))
    return out


def _line_starts_with_query(line: _PageLine, query_norm: str, query_plain: str) -> bool:
    if not query_norm:
        return False

    if line.norm_cf.startswith(query_norm) or line.plain_cf.startswith(query_plain):
        return True

    # Allow only decorative leading chars before heading text, never normal prose.
    l1 = line.norm_cf.lstrip(" \t\"'“”‘’([{<•*-–—")
    l2 = line.plain_cf.lstrip(" \t\"'“”‘’([{<•*-–—")
    if l1.startswith(query_norm) or l2.startswith(query_plain):
        return True

    # Fallback: accept numeric section prefixes like "1.2   Heading Title".
    # This covers layouts with a large visual gap between section number and title.
    if _starts_after_numeric_prefix(line.norm_cf, query_norm):
        return True
    if query_plain and _starts_after_numeric_prefix(line.plain_cf, query_plain):
        return True
    return False


def _starts_after_numeric_prefix(line_text: str, query: str) -> bool:
    """
    Return True if *query* starts shortly after a numeric-only prefix.
    Example prefixes: "1", "1.2", "3.4.5)", often followed by large spacing.
    """
    if not line_text or not query:
        return False

    start = 0
    while True:
        pos = line_text.find(query, start)
        if pos < 0:
            return False
        if pos == 0:
            return True

        prefix = line_text[:pos]
        if len(prefix) <= 48:
            compact = _WS_RE.sub(" ", prefix).strip()
            if compact and any(ch.isdigit() for ch in compact):
                if _NUM_PREFIX_ALLOWED_RE.fullmatch(compact):
                    return True
        start = pos + 1


def _line_contains_any(line: _PageLine, query_pairs: list[tuple[str, str]]) -> bool:
    for qn, qp in query_pairs:
        if not qn:
            continue
        if qn in line.norm_cf or qp in line.plain_cf:
            return True
    return False


def _context_query_pairs(text: str) -> list[tuple[str, str]]:
    clean = _normalize_heading_text(text)
    if not clean:
        return []
    variants = [clean]
    words = clean.split()
    if len(words) >= 8:
        variants.append(" ".join(words[:8]))
    if len(words) >= 5:
        variants.append(" ".join(words[:5]))
    out: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for v in variants:
        qn = _normalize_for_compare(v)
        qp = _plain_for_compare(v)
        if not qn:
            continue
        key = (qn, qp)
        if key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def _context_bonus(
    page_lines: list[_PageLine],
    idx: int,
    prev_pairs: list[tuple[str, str]],
    next_pairs: list[tuple[str, str]],
) -> int:
    bonus = 0
    for dist in range(1, 7):
        j = idx - dist
        if j < 0:
            break
        if _line_contains_any(page_lines[j], prev_pairs):
            bonus += max(4, 20 - dist * 3)
            break
    for dist in range(1, 7):
        j = idx + dist
        if j >= len(page_lines):
            break
        if _line_contains_any(page_lines[j], next_pairs):
            bonus += max(4, 20 - dist * 3)
            break
    return bonus


def _find_heading_rects_on_page(
    anchor: _HeadingAnchor,
    page_lines: list[_PageLine],
) -> list[tuple[float, float, float, float]]:
    """Find heading rectangles for one markdown heading anchor on a page."""
    queries = _heading_query_variants(anchor.title)
    if not queries or not page_lines:
        return []

    heading_pairs = [(_normalize_for_compare(q), _plain_for_compare(q)) for q in queries]
    heading_pairs = [(qn, qp) for qn, qp in heading_pairs if qn]
    if not heading_pairs:
        return []
    prev_pairs = _context_query_pairs(anchor.prev_text)
    next_pairs = _context_query_pairs(anchor.next_text)

    best: Optional[tuple[int, _PageLine]] = None
    for i, line in enumerate(page_lines):
        best_match_len = 0
        for qn, qp in heading_pairs:
            if _line_starts_with_query(line, qn, qp):
                best_match_len = max(best_match_len, len(qn))
        if best_match_len == 0:
            continue

        score = best_match_len
        score += _context_bonus(page_lines, i, prev_pairs, next_pairs)
        # Slight preference for short standalone lines (typical heading shape).
        score += max(0, 35 - len(line.norm_cf)) // 4

        if best is None or score > best[0]:
            best = (score, line)

    if best is None:
        return []
    line = best[1]
    return [(line.x0, line.y0, line.x1, line.y1)]


def _extract_global_heading_anchors(markdown: str) -> list[_HeadingAnchor]:
    """Extract global markdown headings with nearby context lines as anchors."""
    if not markdown:
        return []
    lines = markdown.splitlines()
    first_nonempty = next((i for i, ln in enumerate(lines) if ln.strip()), 0)
    anchors: list[_HeadingAnchor] = []
    in_code_fence = False

    def _find_context(start: int, step: int) -> str:
        j = start + step
        while 0 <= j < len(lines):
            raw = lines[j].strip()
            if not raw:
                j += step
                continue
            if _MD_PAGE_MARK_RE.match(raw):
                j += step
                continue
            if _MD_HEADING_RE.match(raw):
                return ""
            if _MD_CODE_FENCE_RE.match(raw):
                return ""
            return raw
        return ""

    for i, ln in enumerate(lines):
        s = ln.strip()
        if _MD_CODE_FENCE_RE.match(s):
            in_code_fence = not in_code_fence
            continue
        if in_code_fence:
            continue

        hm = _MD_HEADING_RE.match(ln)
        if not hm:
            continue

        level = len(ln) - len(ln.lstrip("#"))
        level = max(1, min(level, 6))
        title = ln[level:].strip()
        if not title or len(title) < 3:
            continue

        # Skip leading file title heading.
        if i == first_nonempty and level == 1:
            continue

        anchors.append(_HeadingAnchor(
            level=level,
            title=title,
            prev_text=_find_context(i, -1),
            next_text=_find_context(i, +1),
        ))

    return anchors


def _extract_page_overlay_rects(
    page,
    settings: PDFImportSettings,
    page_idx: int,
    top_zone: float,
    bottom_zone: float,
    body_size: float = 0.0,
) -> tuple:
    """
    Extract overlay rectangles from a fitz Page for the PDF viewer.

    Returns
    -------
    hf_top_rects    list of (x0, y0, x1, y1) — text blocks in the top zone
    hf_bottom_rects list of (x0, y0, x1, y1) — text blocks in the bottom zone
    heading_rects   list of (x0, y0, x1, y1, level) — heading spans (level 1/2/3)
    """
    h = page.rect.height or 1.0
    top_limit = h * top_zone
    bottom_limit = h * (1.0 - bottom_zone)

    hf_top_rects:    list = []
    hf_bottom_rects: list = []
    heading_rects:   list = []
    has_detect_result = (
        bool(settings.detected_hf_rects_by_page)
        or bool(settings.detected_top_by_page)
        or bool(settings.detected_bottom_by_page)
    )

    if settings.auto_hf_detect:
        per_page_rects = settings.detected_hf_rects_by_page.get(page_idx, {})
        hf_top_rects = list(per_page_rects.get("header", []))
        hf_bottom_rects = list(per_page_rects.get("footer", []))

    detector = (
        _CustomHeaderDetector(body_size, settings)
        if body_size > 0 and settings.heading_mode == "custom"
        else None
    )

    for block in page.get_text("dict")["blocks"]:
        if block.get("type") != 0:
            continue
        bx0, by0, bx1, by1 = block["bbox"]
        if not settings.auto_hf_detect:
            if by1 <= top_limit:
                hf_top_rects.append((bx0, by0, bx1, by1))
            elif by0 >= bottom_limit:
                hf_bottom_rects.append((bx0, by0, bx1, by1))
        elif (not has_detect_result) and (not hf_top_rects and not hf_bottom_rects):
            # Auto mode fallback before explicit detection has been run:
            # show candidate blocks in top/bottom zones.
            if by1 <= top_limit:
                hf_top_rects.append((bx0, by0, bx1, by1))
            elif by0 >= bottom_limit:
                hf_bottom_rects.append((bx0, by0, bx1, by1))

        if detector is not None and by1 > top_limit and by0 < bottom_limit:
            for line in block["lines"]:
                for span in line["spans"]:
                    hid = detector.get_header_id(span)
                    if hid:
                        level = len(hid)   # 1, 2, or 3
                        sx0, sy0, sx1, sy1 = span["bbox"]
                        heading_rects.append((sx0, sy0, sx1, sy1, level))

    return hf_top_rects, hf_bottom_rects, heading_rects
