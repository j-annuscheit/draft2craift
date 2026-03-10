"""Text span matching helpers for highlight anchors and terms."""
from __future__ import annotations

import functools
import re

from .store_common import normalize_text


ANCHOR_CONTEXT_CHARS = 48


@functools.lru_cache(maxsize=512)
def _compiled_term_pattern(
    term: str,
    case_sensitive: bool,
    whole_word: bool,
) -> re.Pattern[str]:
    escaped = re.escape(term)
    if whole_word:
        pattern = rf"(?<!\w){escaped}(?!\w)"
    else:
        pattern = escaped
    flags = 0 if case_sensitive else re.IGNORECASE
    return re.compile(pattern, flags)


def find_term_spans(
    text: str,
    *,
    term: str,
    case_sensitive: bool,
    whole_word: bool,
) -> list[tuple[int, int]]:
    src = normalize_text(text)
    needle = str(term or "")
    if not src or not needle.strip():
        return []
    matcher = _compiled_term_pattern(needle, bool(case_sensitive), bool(whole_word))
    spans: list[tuple[int, int]] = []
    for match in matcher.finditer(src):
        spans.append((int(match.start()), int(match.end())))
    return spans


def build_anchor(text: str, start: int, end: int) -> tuple[str, str, str]:
    src = normalize_text(text)
    s = max(0, min(int(start), len(src)))
    e = max(0, min(int(end), len(src)))
    if e < s:
        s, e = e, s
    prefix_start = max(0, s - ANCHOR_CONTEXT_CHARS)
    suffix_end = min(len(src), e + ANCHOR_CONTEXT_CHARS)
    return (
        src[s:e],
        src[prefix_start:s],
        src[e:suffix_end],
    )


def find_anchor_span(
    text: str,
    exact: str,
    prefix: str,
    suffix: str,
) -> tuple[int, int, str | None] | None:
    src = normalize_text(text)
    needle = normalize_text(exact)
    pre = normalize_text(prefix)
    suf = normalize_text(suffix)
    if not src:
        return None

    direct = _find_exact_spans(src, needle)
    if direct:
        best = _pick_best_span(src, direct, pre, suf)
        return (best[0], best[1], None)

    inferred = _infer_span_from_context(src, pre, suf)
    if inferred is None:
        return None
    start, end = inferred
    return (start, end, src[start:end])


def _find_exact_spans(text: str, needle: str) -> list[tuple[int, int]]:
    if not needle:
        return []
    spans: list[tuple[int, int]] = []
    pos = 0
    while True:
        idx = text.find(needle, pos)
        if idx < 0:
            break
        spans.append((idx, idx + len(needle)))
        pos = idx + 1
    return spans


def _pick_best_span(
    text: str,
    spans: list[tuple[int, int]],
    prefix: str,
    suffix: str,
) -> tuple[int, int]:
    if len(spans) == 1:
        return spans[0]

    best_span = spans[0]
    best_score = -1
    for start, end in spans:
        left = text[max(0, start - len(prefix)):start] if prefix else ""
        right = text[end:min(len(text), end + len(suffix))] if suffix else ""
        score = 0
        if prefix:
            score += _common_suffix_len(left, prefix)
        if suffix:
            score += _common_prefix_len(right, suffix)
        if score > best_score:
            best_score = score
            best_span = (start, end)
    return best_span


def _infer_span_from_context(
    text: str,
    prefix: str,
    suffix: str,
) -> tuple[int, int] | None:
    if not prefix and not suffix:
        return None

    pre_hits = _find_context_hits(text, prefix, tail=True)
    suf_hits = _find_context_hits(text, suffix, tail=False)
    if not pre_hits and not suf_hits:
        return None

    if pre_hits and not suf_hits:
        return None
    if suf_hits and not pre_hits:
        return None

    best: tuple[int, int] | None = None
    best_gap = 10**9
    for start in pre_hits:
        for end in suf_hits:
            if end < start:
                continue
            gap = end - start
            if gap < best_gap:
                best_gap = gap
                best = (start, end)
            break
    return best


def _find_context_hits(text: str, context: str, *, tail: bool) -> list[int]:
    src = str(text or "")
    raw = str(context or "")
    if not raw:
        return []

    sizes: list[int] = []
    full_len = len(raw)
    for size in (full_len, 32, 24, 16, 12, 8):
        if size <= 0:
            continue
        if size > full_len:
            continue
        if size not in sizes:
            sizes.append(size)

    hits: list[int] = []
    for size in sizes:
        piece = raw[-size:] if tail else raw[:size]
        if not piece:
            continue
        pos = 0
        local_hits: list[int] = []
        while True:
            idx = src.find(piece, pos)
            if idx < 0:
                break
            if tail:
                local_hits.append(idx + len(piece))
            else:
                local_hits.append(idx)
            pos = idx + 1
        if local_hits:
            hits = local_hits
            break
    return hits


def _common_suffix_len(left: str, right: str) -> int:
    a = str(left or "")
    b = str(right or "")
    n = min(len(a), len(b))
    count = 0
    for i in range(1, n + 1):
        if a[-i] != b[-i]:
            break
        count += 1
    return count


def _common_prefix_len(left: str, right: str) -> int:
    a = str(left or "")
    b = str(right or "")
    n = min(len(a), len(b))
    count = 0
    for i in range(n):
        if a[i] != b[i]:
            break
        count += 1
    return count


__all__ = [
    "build_anchor",
    "find_anchor_span",
    "find_term_spans",
]
