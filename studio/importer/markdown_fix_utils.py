"""Markdown post-processing helpers for :class:`MarkdownLLMFixWorker`."""
from __future__ import annotations

from difflib import SequenceMatcher
import re
from typing import Any


def _split_markdown_chunks(
    text: str,
    *,
    target_chars: int = 1400,
    max_chars: int = 2200,
) -> list[str]:
    source = str(text or "")
    if not source:
        return []
    chunks: list[str] = []
    buf: list[str] = []
    buf_len = 0
    lines = source.splitlines(keepends=True)
    for line in lines:
        buf.append(line)
        buf_len += len(line)
        at_soft_boundary = (not line.strip()) and (buf_len >= target_chars)
        at_hard_boundary = buf_len >= max_chars
        if at_soft_boundary or at_hard_boundary:
            chunks.append("".join(buf))
            buf = []
            buf_len = 0
    if buf:
        chunks.append("".join(buf))
    return chunks


def _numbers_signature(text: str) -> tuple[str, ...]:
    return tuple(re.findall(r"\d+(?:[.,]\d+)?", str(text or "")))


def _page_marker_signature(text: str) -> tuple[str, ...]:
    matches = re.findall(
        r"\[\s*Seite\s+(\d+)\s*\]",
        str(text or ""),
        flags=re.IGNORECASE,
    )
    return tuple(str(int(num)) for num in matches)


def _accept_candidate(original: str, candidate: str) -> bool:
    orig = str(original or "")
    cand = str(candidate or "")
    if not cand.strip():
        return False
    if _page_marker_signature(orig) != _page_marker_signature(cand):
        return False
    if _numbers_signature(orig) != _numbers_signature(cand):
        return False
    ratio = SequenceMatcher(None, orig, cand).ratio()
    if ratio < 0.86:
        return False
    max_delta = max(120, int(len(orig) * 0.45))
    if abs(len(cand) - len(orig)) > max_delta:
        return False
    return True


def _extract_markdown_payload(raw: str) -> str:
    text = str(raw or "")
    if not text.strip():
        return ""
    fence = re.search(
        r"```(?:markdown|md)?\s*([\s\S]*?)```",
        text,
        flags=re.IGNORECASE,
    )
    if fence:
        return str(fence.group(1) or "")
    return text


def _source_has_xml_tag(text: str, tag_name: str) -> bool:
    return bool(
        re.search(
            rf"</?\s*{re.escape(str(tag_name or '').strip())}\s*>",
            str(text or ""),
            flags=re.IGNORECASE,
        )
    )


def _remove_leaked_prompt_tags(original: str, candidate: str) -> str:
    src = str(original or "")
    out = str(candidate or "")
    if not out:
        return out

    if not _source_has_xml_tag(src, "fixed_md"):
        out = re.sub(r"</?\s*fixed_md\s*>", "", out, flags=re.IGNORECASE)
    if not _source_has_xml_tag(src, "markdown_input"):
        out = re.sub(r"</?\s*markdown_input\s*>", "", out, flags=re.IGNORECASE)
    if "<|" not in src:
        out = re.sub(r"<\|[^|>\n]{1,120}\|>", "", out)
    return out


def _restore_percent_signs(original: str, candidate: str) -> str:
    src = str(original or "")
    out = str(candidate or "")
    if "%" not in src:
        return out
    return re.sub(
        r"(\d+(?:[.,]\d+)?)\s*(?:Prozent|prozent)\b",
        r"\1 %",
        out,
    )


def _restore_page_markers(original: str, candidate: str) -> str:
    """
    Preserve generated page markers in canonical form: ``[Seite N]``.
    """
    src = str(original or "")
    out = str(candidate or "")
    src_signature = _page_marker_signature(src)
    if not src_signature:
        return out

    # Normalize already bracketed variants to canonical spelling/spacing.
    out = re.sub(
        r"\[\s*Seite\s+(\d+)\s*\]",
        lambda m: f"[Seite {int(m.group(1))}]",
        out,
        flags=re.IGNORECASE,
    )

    allowed = {str(int(num)) for num in src_signature}

    # Repair line-only degradations like "Seite 12" -> "[Seite 12]".
    def _line_marker_repl(m: re.Match[str]) -> str:
        num = str(int(m.group(1)))
        if num in allowed:
            return f"[Seite {num}]"
        return str(m.group(0) or "")

    out = re.sub(
        r"(?im)^\s*Seite\s+(\d+)\s*$",
        _line_marker_repl,
        out,
    )
    return out


def _escape_internal_word_asterisks(text: str) -> str:
    return re.sub(
        r"(?<=[^\W\d_])\*(?=[^\W\d_])",
        r"\\*",
        str(text or ""),
        flags=re.UNICODE,
    )


def _strip_new_single_emphasis_markup(original: str, candidate: str) -> str:
    """
    Remove newly introduced single-emphasis spans (*...* / _..._) that
    often appear as correction annotations rather than source formatting.
    """
    orig = str(original or "")
    out = str(candidate or "")
    if not out:
        return out

    def unwrap_if_new(match: re.Match[str]) -> str:
        token = str(match.group(0) or "")
        inner = str(match.group(1) or "")
        if not inner.strip():
            return token
        # Keep emphasis only if this exact span already existed in source.
        return token if token in orig else inner

    out = re.sub(
        r"(?<!\*)\*(?!\*)([^*\n]+?)\*(?!\*)",
        unwrap_if_new,
        out,
    )
    out = re.sub(
        r"(?<!_)_(?!_)([^_\n]+?)_(?!_)",
        unwrap_if_new,
        out,
    )
    return out


def _count_leading_newlines(text: str) -> int:
    m = re.match(r"^\n*", str(text or ""))
    return len(str(m.group(0) if m else ""))


def _count_trailing_newlines(text: str) -> int:
    m = re.search(r"\n*$", str(text or ""))
    return len(str(m.group(0) if m else ""))


def _preserve_chunk_edge_newlines(original: str, candidate: str) -> str:
    orig = str(original or "")
    cand = str(candidate or "")
    need_head = _count_leading_newlines(orig)
    need_tail = _count_trailing_newlines(orig)
    have_head = _count_leading_newlines(cand)
    have_tail = _count_trailing_newlines(cand)
    if have_head < need_head:
        cand = ("\n" * (need_head - have_head)) + cand
    if have_tail < need_tail:
        cand = cand + ("\n" * (need_tail - have_tail))
    return cand


def _extract_heading_specs(text: str) -> list[tuple[str, str]]:
    specs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for raw_line in str(text or "").splitlines():
        line = str(raw_line or "").rstrip()
        m = re.match(r"^\s{0,3}(#{1,6})\s+(.+?)\s*$", line)
        if not m:
            continue
        level = str(m.group(1) or "")
        title = re.sub(r"\s+", " ", str(m.group(2) or "").strip())
        if not level or not title:
            continue
        key = (level, title)
        if key in seen:
            continue
        seen.add(key)
        specs.append(key)
    return specs


def _title_regex(title: str) -> str:
    tokens = [t for t in re.split(r"\s+", str(title or "").strip()) if t]
    if not tokens:
        return ""
    return r"\s+".join(re.escape(token) for token in tokens)


def _restore_heading_boundaries(original: str, candidate: str) -> str:
    out = str(candidate or "")
    specs = _extract_heading_specs(original)
    if not specs:
        return out
    for level, title in specs:
        title_pat = _title_regex(title)
        if not title_pat:
            continue
        heading_pat = rf"\s{{0,3}}{re.escape(level)}\s+{title_pat}"
        # Prevent heading from being glued to previous paragraph text.
        out = re.sub(
            rf"([^\n])({heading_pat})(?=\s|$)",
            r"\1\n\2",
            out,
        )
        # Prevent heading from sharing a line with following paragraph text.
        out = re.sub(
            rf"({heading_pat})([ \t]+)(?=[^\n])",
            r"\1\n",
            out,
        )
    return out


def _parse_numbered_heading_depth(text: str) -> int | None:
    title = str(text or "").strip()
    if not title:
        return None
    m = re.match(r"^(\d+(?:\.\d+){0,7})(?:[.)])?(?:\s+|$)", title)
    if not m:
        return None
    raw = str(m.group(1) or "").strip().strip(".")
    if not raw:
        return None
    parts = [p for p in raw.split(".") if p]
    if not parts:
        return None
    return int(len(parts))


def _is_score_like_title(text: str) -> bool:
    title = re.sub(r"\s+", " ", str(text or "").strip())
    if not title:
        return False
    compact = title.replace(" ", "")
    if re.fullmatch(
        r"\d+(?:[.,]\d+)?(?:%|[Pp](?:unkte|unkt|kt)?\.?)",
        compact,
    ):
        return True
    token_pat = r"\d+(?:[.,]\d+)?\s*(?:%|[Pp](?:unkte|unkt|kt)?\.?)"
    tokens = re.findall(token_pat, title)
    if len(tokens) < 2:
        return False
    rest = re.sub(token_pat, " ", title)
    rest = re.sub(r"[\s,;:|/\\-]+", "", rest)
    return not bool(rest)


def _infer_numbered_heading_offset(text: str, default: int = 1) -> int:
    counts: dict[int, int] = {}
    for raw_line in str(text or "").splitlines():
        m = re.match(r"^\s{0,3}(#{1,6})\s+(.+?)\s*$", str(raw_line or ""))
        if not m:
            continue
        level = int(len(str(m.group(1) or "")))
        title = str(m.group(2) or "")
        if _is_score_like_title(title):
            continue
        depth = _parse_numbered_heading_depth(title)
        if depth is None:
            continue
        offset = int(level - depth)
        if -2 <= offset <= 3:
            counts[offset] = counts.get(offset, 0) + 1
    if not counts:
        return int(default)
    best_offset = sorted(
        counts.items(),
        key=lambda item: (-int(item[1]), abs(int(item[0]) - int(default))),
    )[0][0]
    return int(best_offset)


def _heading_level_from_depth(depth: int, offset: int) -> int:
    value = int(depth) + int(offset)
    return max(1, min(6, value))


def _promote_bold_numbered_headings(text: str, offset: int) -> str:
    lines = str(text or "").splitlines()
    out_lines: list[str] = []
    for raw in lines:
        line = str(raw or "")
        bold_spans = re.findall(r"\*\*[^*\n]+?\*\*", line)
        if len(bold_spans) != 1:
            out_lines.append(line)
            continue
        m = re.match(r"^\s{0,3}\*\*(.+?)\*\*(.*)$", line)
        if not m:
            out_lines.append(line)
            continue
        title = re.sub(r"\s+", " ", str(m.group(1) or "").strip())
        if _is_score_like_title(title):
            out_lines.append(line)
            continue
        depth = _parse_numbered_heading_depth(title)
        if depth is None:
            out_lines.append(line)
            continue
        level = _heading_level_from_depth(depth, offset)
        heading = f"{'#' * level} {title}"
        tail = str(m.group(2) or "").strip()
        if re.search(r"\*\*[^*\n]+?\*\*", tail):
            out_lines.append(line)
            continue
        if tail.startswith(":"):
            tail = tail[1:].lstrip()
        out_lines.append(heading)
        if tail:
            out_lines.append("")
            out_lines.append(tail)
        continue
    return "\n".join(out_lines)


def _normalize_numbered_heading_levels(text: str, offset: int) -> str:
    lines = str(text or "").splitlines()
    out_lines: list[str] = []
    for raw in lines:
        line = str(raw or "")
        m = re.match(r"^(\s{0,3})(#{1,6})(\s+)(.+?)\s*$", line)
        if not m:
            out_lines.append(line)
            continue
        prefix = str(m.group(1) or "")
        title = str(m.group(4) or "").strip()
        if _is_score_like_title(title):
            out_lines.append(line)
            continue
        depth = _parse_numbered_heading_depth(title)
        if depth is None:
            out_lines.append(line)
            continue
        level = _heading_level_from_depth(depth, offset)
        out_lines.append(f"{prefix}{'#' * level} {title}")
    return "\n".join(out_lines)


def _harmonize_numbered_headings(text: str, offset: int) -> str:
    source = str(text or "")
    out = source
    out = _promote_bold_numbered_headings(out, offset)
    out = _normalize_numbered_heading_levels(out, offset)
    return _preserve_chunk_edge_newlines(source, out)


__all__ = [
    "_accept_candidate",
    "_escape_internal_word_asterisks",
    "_extract_markdown_payload",
    "_harmonize_numbered_headings",
    "_infer_numbered_heading_offset",
    "_normalize_numbered_heading_levels",
    "_page_marker_signature",
    "_preserve_chunk_edge_newlines",
    "_promote_bold_numbered_headings",
    "_remove_leaked_prompt_tags",
    "_restore_heading_boundaries",
    "_restore_page_markers",
    "_restore_percent_signs",
    "_split_markdown_chunks",
    "_strip_new_single_emphasis_markup",
]

