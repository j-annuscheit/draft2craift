from __future__ import annotations

import re
from typing import Optional

from .models import PDFImportSettings

_SENTENCE_END = re.compile(r"[.!?]['\"\u201d\)\]]?\s*$")
_TRAILING_HYPHEN = re.compile(r"-\s*$")

# ── Paragraph reflow ─────────────────────────────────────────────────────────

_MD_HEADING = re.compile(r"^#{1,6}\s")
_MD_CODE_FENCE = re.compile(r"^```")
_MD_TABLE_ROW = re.compile(r"^\|")
_MD_LIST_ITEM = re.compile(r"^\s{0,3}(?:[-*+]|\d+[.)])\s+")
_MD_PAGE_MARK = re.compile(r"^\[Seite \d+\]")
_MD_HR = re.compile(r"^---+\s*$")
_MD_HEADING_LINE_RE = re.compile(r"^(#{1,6}\s+)(.+)$")
_MD_STRONG_HTML_RE = re.compile(r"<\s*strong\s*>(.*?)<\s*/\s*strong\s*>", re.IGNORECASE)
_MD_LOWER_START = re.compile(r"^[\"'(\[\{„“‚‘]*[a-z0-9äöüß]")
_MD_DOT_LEADER = re.compile(r"[.\u2024\u2025\u2026]{5,}")
_MD_DOT_LIMIT_RE = re.compile(r"[.\u2024\u2025\u2026]{4,}")
_MD_TABLE_SEP = re.compile(r"^\|\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$")
_MD_SECTION_NUM_HEADING = re.compile(r"^#{1,6}\s+(\d+)\)")
_MD_HTML_BR_RE = re.compile(r"<\s*br\s*/?\s*>", re.IGNORECASE)
_PDF_SECTION_NUM_HEADING = re.compile(r"^\s*(\d+)\)\s+(.+)$")
_TABLEISH_HEADING_RE = re.compile(r"(table|tabelle|tabellen|longtable|grid|matrix|summenlinie)", re.IGNORECASE)
_GENERIC_COL_RE = re.compile(r"^col\d+$", re.IGNORECASE)
_CURRENCY_ONLY_RE = re.compile(r"^[€$£¥₹]+$")
_TABLE_MENTION_RE = re.compile(r"\b(?:tabelle|tabellen|table|tables)\b", re.IGNORECASE)
_HARD_HEADING_MAX_CHARS = 120


def _strip_bold_from_heading_line(line: str) -> str:
    """
    Remove bold markup from markdown heading lines.

    Example:
      ## **Titel**  ->  ## Titel
    """
    m = _MD_HEADING_LINE_RE.match(line)
    if not m:
        return line

    prefix, title = m.groups()
    prev = None
    while prev != title:
        prev = title
        title = re.sub(r"\*\*(.+?)\*\*", r"\1", title)
        title = re.sub(r"__(.+?)__", r"\1", title)
        title = _MD_STRONG_HTML_RE.sub(r"\1", title)

    title = title.strip()
    if not title:
        return line

    # Hard cap: headings with >=120 characters are treated as running text.
    if len(title) >= _HARD_HEADING_MAX_CHARS:
        return title

    return f"{prefix}{title}"


def _strip_bold_from_markdown_headings(text: str) -> str:
    if not text:
        return text
    return "\n".join(_strip_bold_from_heading_line(ln) for ln in text.splitlines())


def _replace_html_br_with_space(text: str) -> str:
    """Normalize HTML <br> tags to plain spaces in markdown output."""
    if not text:
        return text
    return _MD_HTML_BR_RE.sub(" ", text)


def _limit_dot_leaders(text: str) -> str:
    """Clamp dot leaders to exactly three dots (.... -> ...)."""
    if not text:
        return text
    return _MD_DOT_LIMIT_RE.sub("...", text)


def extract_markdown_headings_by_page(markdown: str) -> dict[int, list[tuple[int, str]]]:
    """Return markdown headings in global mode as {-1: [(level, text), ...]}.

    Rules:
      - A heading must start at the beginning of a line with '#'.
      - Headings inside fenced code blocks are ignored.
      - The leading title line '# <filename>' is ignored.
    """
    if not markdown:
        return {}
    # Keep heading parsing consistent with displayed markdown.
    lines = _strip_bold_from_markdown_headings(markdown).splitlines()
    out: dict[int, list[tuple[int, str]]] = {-1: []}
    in_code_fence = False

    for i, ln in enumerate(lines):
        if _MD_CODE_FENCE.match(ln.strip()):
            in_code_fence = not in_code_fence
            continue
        if in_code_fence:
            continue

        hm = _MD_HEADING.match(ln)
        if not hm:
            continue

        level = len(ln) - len(ln.lstrip("#"))
        level = max(1, min(level, 6))
        title = ln[level:].strip()
        if not title or len(title) < 3:
            continue

        # Usually "# <filename>" at the top should not be treated as content heading.
        if i == 0 and level == 1:
            continue

        out[-1].append((level, title))

    return out if out[-1] else {}


def _is_special_line(line: str) -> bool:
    """True for markdown lines that should never be joined or split."""
    return any(
        (
            _MD_HEADING.match(line),
            _MD_TABLE_ROW.match(line),
            _MD_LIST_ITEM.match(line),
            _looks_like_toc_line(line),
            _MD_PAGE_MARK.match(line),
            _MD_HR.match(line),
            line.startswith("    "),  # indented code
        )
    )


def _looks_like_toc_line(line: str) -> bool:
    """Heuristic for TOC entries with dot leaders and trailing page number."""
    stripped = line.strip()
    if len(stripped) < 10:
        return False
    if not _MD_DOT_LEADER.search(stripped):
        return False

    # Ignore markdown emphasis markers when checking trailing page number.
    plain = re.sub(r"[*_`]", "", stripped)
    return bool(re.search(r"\d+\s*$", plain))


def _is_plain_text_line(line: str) -> bool:
    stripped = line.strip()
    return bool(stripped) and not _is_special_line(line) and not _MD_CODE_FENCE.match(stripped)


def _should_soft_merge_blank(prev_line: str, next_line: str, mode: str) -> bool:
    """
    Decide whether a blank-line gap between two plain lines is likely OCR/layout noise.

    join-mode is intentionally aggressive. smart-mode keeps paragraph boundaries when
    the previous line clearly ends a sentence and the next line looks like a new one.
    """
    if not _is_plain_text_line(prev_line) or not _is_plain_text_line(next_line):
        return False

    if mode == "join":
        return True

    prev = prev_line.rstrip()
    nxt = next_line.lstrip()

    if not prev or not nxt:
        return False

    if not _SENTENCE_END.search(prev):
        return True

    return bool(_MD_LOWER_START.match(nxt))


def _smart_reflow_block(lines: list[str], settings: PDFImportSettings) -> list[str]:
    """
    Apply heuristic paragraph reflow to the lines of a single text block.

    Rules
    -----
    • Line ending with ``-``  (hyphen, word-wrap artefact)
        → strip the hyphen and join with the NEXT token WITHOUT a space
          (dehyphenation: "ge-" + "trennt" → "getrennt")
        → never treated as a paragraph boundary

    • Line ending with ``.``, ``!`` or ``?``  (sentence end)
        → paragraph boundary ONLY when the line is clearly "short"
          relative to its text box fill
          (len < min_fill_ratio × box_fill_width).
          This avoids splitting mid-paragraph on every sentence.

    • Otherwise
        → join with the next line (continuation of same paragraph).
    """
    stripped = [line.rstrip() for line in lines]
    nonempty = [line for line in stripped if line]
    if not nonempty:
        return []

    # Derive a per-box reference width from fuller lines.
    # We use the 85th percentile to avoid short trailing lines and single outliers.
    nonempty_lens = sorted(len(line.strip()) for line in nonempty)
    if not nonempty_lens:
        return []
    box_ref_len = nonempty_lens[max(0, int((len(nonempty_lens) - 1) * 0.85))]
    box_ref_len = max(1, box_ref_len)

    paragraphs: list[str] = []
    # Each element is either a plain str or ("dehyphen", str_without_hyphen)
    # so we know to join the next piece without a space.
    buffer: list = []
    pending_dehyphen = False   # True → next buffer.append joins without space

    def flush():
        nonlocal buffer, pending_dehyphen
        if not buffer:
            return
        parts: list[str] = []
        join_tight = False
        for item in buffer:
            if join_tight and parts:
                parts[-1] = parts[-1] + item
            else:
                parts.append(item)
            join_tight = False
            if isinstance(item, tuple):       # should not happen after cleanup
                join_tight = True
        paragraphs.append(" ".join(parts))
        buffer = []
        pending_dehyphen = False

    for i, line in enumerate(stripped):
        if not line:
            flush()
            continue

        # ── Hyphen continuation (dehyphenation) ──────────────────────────
        if settings.para_join_hyphen and _TRAILING_HYPHEN.search(line):
            stem = line.rstrip("-").rstrip()
            if buffer and pending_dehyphen:
                # Multiple consecutive hyphen-lines: concat immediately
                buffer[-1] = buffer[-1] + stem
            elif buffer:
                # Mark next join as tight (no space)
                buffer.append(stem)
                pending_dehyphen = True
            else:
                buffer.append(stem)
                pending_dehyphen = True
            continue

        # ── Normal line ───────────────────────────────────────────────────
        if pending_dehyphen and buffer:
            buffer[-1] = buffer[-1] + line   # join without space
            pending_dehyphen = False
        else:
            buffer.append(line)
            pending_dehyphen = False

        # ── Paragraph-end decision ────────────────────────────────────────
        is_last = (i == len(stripped) - 1)
        if is_last:
            break

        is_sent_end = bool(_SENTENCE_END.search(line))
        # "short" is measured against the local text-box fill width.
        is_short = len(line.strip()) < box_ref_len * settings.para_min_fill_ratio

        if settings.para_sentence_end and is_sent_end and is_short:
            flush()

    flush()
    return [p for p in paragraphs if p]


def _reflow_markdown(text: str, settings: PDFImportSettings) -> str:
    """
    Post-process pymupdf4llm markdown output to improve paragraph structure.

    Preserves headings, tables, code fences, lists, page markers and
    horizontal rules unchanged.  Applies reflow only to plain-text paragraphs.
    """
    if settings.para_mode == "none":
        return text

    lines = text.splitlines()
    if not lines:
        return text

    out: list[str] = []
    plain_buffer: list[str] = []
    in_code_fence = False

    def flush_plain() -> None:
        nonlocal plain_buffer
        if not plain_buffer:
            return

        if settings.para_mode == "join":
            paras = [" ".join(line.strip() for line in plain_buffer if line.strip())]
        else:
            paras = _smart_reflow_block(plain_buffer, settings)

        for para in paras:
            para = para.strip()
            if not para:
                continue
            if out and out[-1] != "":
                out.append("")
            out.append(para)

        plain_buffer = []

    def append_blank() -> None:
        if out and out[-1] != "":
            out.append("")

    def append_special(line: str) -> None:
        # List items should stay compact even if source had blank lines
        # between them.
        is_list = bool(_MD_LIST_ITEM.match(line))
        is_toc = bool(_looks_like_toc_line(line))
        same_kind_as_prev = False
        if len(out) >= 2:
            same_kind_as_prev = (is_list and bool(_MD_LIST_ITEM.match(out[-2]))) or (
                is_toc and bool(_looks_like_toc_line(out[-2]))
            )
        should_remove_gap = (is_list or is_toc) and len(out) >= 2 and out[-1] == "" and same_kind_as_prev
        if should_remove_gap:
            out.pop()
        out.append(line)

    i = 0
    while i < len(lines):
        raw = lines[i]
        line = raw.rstrip()
        stripped = line.strip()

        if _MD_CODE_FENCE.match(stripped):
            flush_plain()
            out.append(line)
            in_code_fence = not in_code_fence
            i += 1
            continue

        if in_code_fence:
            out.append(line)
            i += 1
            continue

        if not stripped:
            j = i
            while j < len(lines) and not lines[j].strip():
                j += 1

            gap_len = j - i
            prev_line = plain_buffer[-1] if plain_buffer else ""
            next_line = lines[j].rstrip() if j < len(lines) else ""
            allow_gap = gap_len == 1
            if not allow_gap and settings.para_mode == "join" and gap_len == 2 and prev_line and not _SENTENCE_END.search(prev_line.rstrip()):
                allow_gap = True

            should_merge = (
                allow_gap and j < len(lines) and prev_line and _should_soft_merge_blank(
                    prev_line, next_line, settings.para_mode
                )
            )
            if should_merge:
                i = j
                continue

            flush_plain()
            append_blank()
            i = j
            continue

        if _is_special_line(line):
            flush_plain()
            append_special(line)
            i += 1
            continue

        plain_buffer.append(line)
        i += 1

    flush_plain()

    while out and out[0] == "":
        out.pop(0)
    while out and out[-1] == "":
        out.pop()

    return "\n".join(out)


def _split_markdown_blocks(text: str) -> list[str]:
    if not text:
        return []
    return [b.strip() for b in re.split(r"\n{2,}", text.strip()) if b.strip()]


def _first_nonempty_line(text: str) -> str:
    for ln in text.splitlines():
        s = ln.strip()
        if s:
            return ln.rstrip()
    return ""


def _last_nonempty_line(text: str) -> str:
    for ln in reversed(text.splitlines()):
        s = ln.strip()
        if s:
            return ln.rstrip()
    return ""


def _is_plain_block(block: str) -> bool:
    lines = [ln.rstrip() for ln in block.splitlines() if ln.strip()]
    return bool(lines) and all(_is_plain_text_line(ln) for ln in lines)


def _merge_smart_page_boundaries(
    page_entries: list[tuple[int, str]],
    settings: PDFImportSettings,
) -> list[tuple[int, str]]:
    """
    In smart mode, merge page boundaries when page N+1 starts with a continuation
    of the paragraph from page N.
    """
    if settings.para_mode != "smart" or len(page_entries) < 2:
        return page_entries

    merged = list(page_entries)
    for i in range(1, len(merged)):
        prev_pi, prev_text = merged[i - 1]
        cur_pi, cur_text = merged[i]
        if not prev_text.strip() or not cur_text.strip():
            continue

        prev_blocks = _split_markdown_blocks(prev_text)
        cur_blocks = _split_markdown_blocks(cur_text)
        if not prev_blocks or not cur_blocks:
            continue

        prev_block = prev_blocks[-1]
        cur_block = cur_blocks[0]
        if not (_is_plain_block(prev_block) and _is_plain_block(cur_block)):
            continue

        prev_tail = _last_nonempty_line(prev_block)
        cur_head = _first_nonempty_line(cur_block)
        if not prev_tail or not cur_head:
            continue

        if not _should_soft_merge_blank(prev_tail, cur_head, "smart"):
            continue

        left = prev_block.rstrip()
        right = cur_block.lstrip()
        if settings.para_join_hyphen and _TRAILING_HYPHEN.search(left):
            joined = left.rstrip("-").rstrip() + right
        else:
            joined = f"{left} {right}".strip()

        prev_blocks[-1] = joined
        cur_blocks = cur_blocks[1:]

        merged[i - 1] = (prev_pi, "\n\n".join(prev_blocks).strip())
        merged[i] = (cur_pi, "\n\n".join(cur_blocks).strip())

    return merged


def _split_md_row(line: str) -> list[str]:
    s = line.strip()
    if not s.startswith("|"):
        return []
    if not s.endswith("|"):
        s = s + "|"
    core = s[1:-1]
    return [c.strip() for c in core.split("|")]


def _parse_markdown_table_block(block: str) -> Optional[dict]:
    lines = [ln.rstrip() for ln in block.splitlines() if ln.strip()]
    if len(lines) < 2:
        return None
    if not all(ln.lstrip().startswith("|") for ln in lines):
        return None
    if not _MD_TABLE_SEP.match(lines[1].strip()):
        return None
    header_cells = _split_md_row(lines[0])
    sep_cells = _split_md_row(lines[1])
    if not header_cells or len(header_cells) != len(sep_cells):
        return None
    data_lines = lines[2:]
    if not all(ln.lstrip().startswith("|") for ln in data_lines):
        return None
    return {
        "lines": lines,
        "header_line": lines[0],
        "sep_line": lines[1],
        "header_cells": header_cells,
        "data_lines": data_lines,
        "col_count": len(header_cells),
    }


def _cell_is_dataish(cell: str) -> bool:
    s = cell.strip().strip("`").strip()
    if not s:
        return False
    if re.match(r"^[+-]?\d+(?:[.,]\d+)?%?$", s):
        return True
    if re.match(r"^\d+[./-]\d+$", s):
        return True
    if re.match(r"^[a-z0-9_/-]{1,20}$", s, flags=re.IGNORECASE):
        return True
    return False


def _header_looks_like_data_row(cells: list[str]) -> bool:
    if not cells:
        return False
    normalized = [c.strip().strip("`").strip() for c in cells]
    if not normalized or not normalized[0]:
        return False
    if not re.match(r"^\d+$", normalized[0]):
        return False
    dataish = sum(1 for c in cells if _cell_is_dataish(c))
    numeric = sum(1 for c in normalized if re.match(r"^[+-]?\d+(?:[.,]\d+)?%?$", c))
    return dataish >= max(2, len(cells) - 1) and numeric >= 2


def _merge_table_page_boundaries(
    page_entries: list[tuple[int, str]],
    show_page_markers: bool,
) -> list[tuple[int, str]]:
    """
    Fix table continuations where page N+1 starts with a data row incorrectly
    treated as a markdown table header (e.g. "|20|...|" + separator row).
    """
    if len(page_entries) < 2:
        return page_entries

    merged = list(page_entries)
    for i in range(1, len(merged)):
        prev_pi, prev_text = merged[i - 1]
        cur_pi, cur_text = merged[i]
        if not prev_text.strip() or not cur_text.strip():
            continue

        prev_blocks = _split_markdown_blocks(prev_text)
        cur_blocks = _split_markdown_blocks(cur_text)
        if not prev_blocks or not cur_blocks:
            continue

        prev_tbl = _parse_markdown_table_block(prev_blocks[-1])
        cur_tbl = _parse_markdown_table_block(cur_blocks[0])
        if not prev_tbl or not cur_tbl:
            continue
        if prev_tbl["col_count"] != cur_tbl["col_count"]:
            continue
        if _header_looks_like_data_row(prev_tbl["header_cells"]):
            continue
        if not _header_looks_like_data_row(cur_tbl["header_cells"]):
            continue

        # Current "header" is actually first data row of continuation.
        continuation_rows = [cur_tbl["header_line"]] + cur_tbl["data_lines"]

        if show_page_markers:
            # Keep rows on this page, but restore a real header for validity.
            cur_blocks[0] = "\n".join(
                [prev_tbl["header_line"], prev_tbl["sep_line"]] + continuation_rows
            )
            merged[i] = (cur_pi, "\n\n".join(cur_blocks).strip())
            continue

        # No page markers: merge into previous table so it becomes one continuous table.
        prev_blocks[-1] = "\n".join(prev_tbl["lines"] + continuation_rows)
        cur_blocks = cur_blocks[1:]
        merged[i - 1] = (prev_pi, "\n\n".join(prev_blocks).strip())
        merged[i] = (cur_pi, "\n\n".join(cur_blocks).strip())

    return merged
