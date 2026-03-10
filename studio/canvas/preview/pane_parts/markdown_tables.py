"""CanvasPreviewPane method implementations."""
from __future__ import annotations

from .deps import *  # noqa: F403

@staticmethod
def _is_markdown_table_row(line: str) -> bool:
    stripped = str(line or "").strip()
    if len(stripped) < 3:
        return False
    if not stripped.startswith("|"):
        return False
    return "|" in stripped[1:]
@classmethod
def _normalize_table_row_spacing(cls, text: str) -> str:
    """
    Collapse blank lines between markdown table rows.

    QTextDocument.toMarkdown() can emit empty lines between `|...|` rows
    after rich-text edits. This breaks markdown table parsing. We remove
    only blank separators where both neighboring non-blank lines are table
    rows, and skip fenced code blocks.
    """
    lines = str(text or "").split("\n")
    if len(lines) < 3:
        return str(text or "")

    out: list[str] = []
    in_fence = False
    fence_char = ""
    fence_len = 0
    count = len(lines)
    for idx, line in enumerate(lines):
        raw = str(line or "")
        stripped = raw.lstrip()
        fence_match = re.match(r"^([`~]{3,})", stripped)
        if fence_match is not None:
            marker = fence_match.group(1)
            marker_char = marker[0]
            marker_len = len(marker)
            if not in_fence:
                in_fence = True
                fence_char = marker_char
                fence_len = marker_len
            elif marker_char == fence_char and marker_len >= fence_len:
                in_fence = False
                fence_char = ""
                fence_len = 0
            out.append(raw)
            continue

        if in_fence:
            out.append(raw)
            continue

        if raw.strip():
            out.append(raw)
            continue

        prev_nonblank = ""
        for prev in reversed(out):
            if str(prev or "").strip():
                prev_nonblank = str(prev or "")
                break
        next_nonblank = ""
        j = idx + 1
        while j < count:
            candidate = str(lines[j] or "")
            if candidate.strip():
                next_nonblank = candidate
                break
            j += 1
        if (
            cls._is_markdown_table_row(prev_nonblank)
            and cls._is_markdown_table_row(next_nonblank)
        ):
            continue
        out.append(raw)

    return "\n".join(out)
@staticmethod
def _pure_pipe_row_column_count(line: str) -> int:
    stripped = str(line or "").strip()
    if not stripped:
        return 0
    if re.fullmatch(r"\|+", stripped) is None:
        return 0
    cols = len(stripped) - 1
    if cols <= 0:
        return 0
    return int(cols)
@classmethod
def _normalize_pure_pipe_table_blocks(cls, text: str) -> str:
    """
    Convert Qt's blank-table markdown (`||||`) to valid table syntax.

    After rich-text edits, QTextDocument can export empty table rows as
    pure pipe lines and drop the separator row. Such blocks no longer parse
    as markdown tables in the next render pass. We rebuild them into:
      header row + separator row + remaining body rows.
    """
    lines = str(text or "").split("\n")
    if len(lines) < 2:
        return str(text or "")

    out: list[str] = []
    in_fence = False
    fence_char = ""
    fence_len = 0
    count = len(lines)
    idx = 0
    while idx < count:
        raw = str(lines[idx] or "")
        stripped = raw.lstrip()
        fence_match = re.match(r"^([`~]{3,})", stripped)
        if fence_match is not None:
            marker = fence_match.group(1)
            marker_char = marker[0]
            marker_len = len(marker)
            if not in_fence:
                in_fence = True
                fence_char = marker_char
                fence_len = marker_len
            elif marker_char == fence_char and marker_len >= fence_len:
                in_fence = False
                fence_char = ""
                fence_len = 0
            out.append(raw)
            idx += 1
            continue

        if in_fence:
            out.append(raw)
            idx += 1
            continue

        cols = cls._pure_pipe_row_column_count(raw)
        if cols <= 0:
            out.append(raw)
            idx += 1
            continue

        j = idx
        while (
            j < count
            and cls._pure_pipe_row_column_count(lines[j]) == cols
        ):
            j += 1
        block_rows = j - idx
        if block_rows >= 2:
            header = "| " + " | ".join([" "] * cols) + " |"
            separator = "| " + " | ".join(["---"] * cols) + " |"
            out.append(header)
            out.append(separator)
            body_count = max(0, block_rows - 2)
            if body_count > 0:
                body_row = "| " + " | ".join([" "] * cols) + " |"
                for _ in range(body_count):
                    out.append(body_row)
        else:
            out.append(raw)
        idx = j

    return "\n".join(out)
@staticmethod
def _split_markdown_table_cells(line: str) -> list[str]:
    stripped = str(line or "").strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [part.strip() for part in stripped.split("|")]
@staticmethod
def _format_markdown_table_row(cells: list[str]) -> str:
    safe = [str(cell or "").strip() for cell in list(cells or [])]
    return "| " + " | ".join(safe) + " |"
@classmethod
def _is_markdown_table_separator_row(cls, line: str) -> bool:
    cells = cls._table_separator_cells(line)
    if not cells:
        return False
    return all(str(cell or "").strip() for cell in cells)
@classmethod
def _table_separator_cells(cls, line: str) -> list[str] | None:
    if not cls._is_markdown_table_row(line):
        return None
    cells = cls._split_markdown_table_cells(line)
    if not cells:
        return None
    parsed: list[str] = []
    has_rule = False
    for cell in cells:
        token = str(cell or "").strip()
        if not token:
            parsed.append("")
            continue
        if re.fullmatch(r":?-{1,}:?", token) is None:
            return None
        has_rule = True
        parsed.append(token)
    if not has_rule:
        return None
    return parsed
@classmethod
def _normalize_table_column_mismatch(cls, text: str) -> str:
    """
    Normalize markdown table rows to a stable column count and spacing.

    Enter/newline edits inside a table cell can produce rows with more
    pipe-separated cells than the table header (e.g. `|C| | |D|`). That
    breaks stable roundtrips in Qt. We fold overflow cells into the first
    column text (as `<br>` joins), repair weak separator rows emitted by
    Qt (e.g. `|-----|||||`), and reformat rows to stable markdown syntax.
    """
    lines = str(text or "").split("\n")
    if len(lines) < 3:
        return str(text or "")

    out: list[str] = []
    in_fence = False
    fence_char = ""
    fence_len = 0
    count = len(lines)
    idx = 0
    while idx < count:
        raw = str(lines[idx] or "")
        stripped = raw.lstrip()
        fence_match = re.match(r"^([`~]{3,})", stripped)
        if fence_match is not None:
            marker = fence_match.group(1)
            marker_char = marker[0]
            marker_len = len(marker)
            if not in_fence:
                in_fence = True
                fence_char = marker_char
                fence_len = marker_len
            elif marker_char == fence_char and marker_len >= fence_len:
                in_fence = False
                fence_char = ""
                fence_len = 0
            out.append(raw)
            idx += 1
            continue

        if in_fence:
            out.append(raw)
            idx += 1
            continue

        if idx + 1 < count and cls._is_markdown_table_row(raw):
            sep_cells = cls._table_separator_cells(lines[idx + 1])
            if sep_cells is None:
                out.append(raw)
                idx += 1
                continue

            header_raw_cells = cls._split_markdown_table_cells(raw)
            cols = max(1, len(header_raw_cells), len(sep_cells))
            row_start = idx + 2
            row_end = row_start
            while row_end < count and cls._is_markdown_table_row(lines[row_end]):
                row_end += 1

            def normalize_cells(raw_cells: list[str]) -> list[str]:
                cells = [str(cell or "").strip() for cell in raw_cells]
                if len(cells) < cols:
                    cells.extend([""] * (cols - len(cells)))
                    return cells
                if len(cells) == cols:
                    return cells
                if cols == 1:
                    merged = "<br>".join(
                        part for part in cells if str(part or "").strip()
                    ).strip()
                    return [merged]
                head_len = len(cells) - (cols - 1)
                first_parts = cells[:head_len]
                tail = cells[-(cols - 1):]
                first = "<br>".join(
                    part for part in first_parts if str(part or "").strip()
                ).strip()
                return [first, *tail]

            def normalize_separator(raw_cells: list[str]) -> list[str]:
                cells = [str(cell or "").strip() for cell in raw_cells]
                if len(cells) < cols:
                    cells.extend([""] * (cols - len(cells)))
                elif len(cells) > cols:
                    cells = cells[:cols]
                normalized_sep: list[str] = []
                for token in cells:
                    current = str(token or "").strip()
                    if not current:
                        normalized_sep.append("---")
                        continue
                    if re.fullmatch(r":?-{1,}:?", current) is None:
                        normalized_sep.append("---")
                        continue
                    left_colon = current.startswith(":")
                    right_colon = current.endswith(":")
                    if left_colon and right_colon:
                        normalized_sep.append(":---:")
                        continue
                    if left_colon:
                        normalized_sep.append(":---")
                        continue
                    if right_colon:
                        normalized_sep.append("---:")
                        continue
                    normalized_sep.append("---")
                return normalized_sep

            header_cells = normalize_cells(header_raw_cells)
            out.append(cls._format_markdown_table_row(header_cells))
            out.append(cls._format_markdown_table_row(normalize_separator(sep_cells)))
            idx = row_start
            while idx < row_end:
                row_cells = normalize_cells(
                    cls._split_markdown_table_cells(lines[idx])
                )
                out.append(cls._format_markdown_table_row(row_cells))
                idx += 1
            continue

        out.append(raw)
        idx += 1

    return "\n".join(out)
@classmethod
def _line_is_blank_like(cls, line: str) -> bool:
    # Preserve visually empty spacer paragraphs as blank-like.
    token = str(line or "").replace("\u00A0", " ").replace("\u200B", "")
    return not token.strip()
@classmethod
def _nonempty_normalized_rows(
    cls,
    text: str,
) -> list[tuple[str, int, int]]:
    lines = str(text or "").replace("\r\n", "\n").split("\n")
    rows: list[tuple[str, int, int]] = []
    count = len(lines)
    i = 0
    while i < count:
        token = cls._normalize_markdown_line(lines[i]).casefold()
        if not token:
            i += 1
            continue
        j = i + 1
        gap = 0
        while j < count and cls._line_is_blank_like(lines[j]):
            gap += 1
            j += 1
        rows.append((token, i, gap))
        i = j
    return rows

__all__ = [
    "_is_markdown_table_row",
    "_normalize_table_row_spacing",
    "_pure_pipe_row_column_count",
    "_normalize_pure_pipe_table_blocks",
    "_split_markdown_table_cells",
    "_format_markdown_table_row",
    "_is_markdown_table_separator_row",
    "_table_separator_cells",
    "_normalize_table_column_mismatch",
    "_line_is_blank_like",
    "_nonempty_normalized_rows",
]
