"""CanvasPreviewPane method implementations."""
from __future__ import annotations

from .deps import *  # noqa: F403

@classmethod
def _markdown_for_render(cls, text: str) -> str:
    """
    Prepare markdown for HTML display without structural rewrites.

    Canonical normalization is intended for HTML->Markdown roundtrips and
    can otherwise alter list/paragraph structure in pure preview mode.
    """
    normalized = str(text or "").replace("\r\n", "\n")
    normalized = cls._replace_hr_markers(normalized)
    normalized = cls._inject_render_soft_break_tags(normalized)
    return cls._inject_render_spacers_for_extra_blank_lines(normalized)
@classmethod
def _escape_internal_word_asterisks(cls, text: str) -> str:
    """
    Escape star-in-word forms (e.g. Kuenstler*innen) to avoid accidental
    emphasis parsing while preserving visible '*' in markdown/preview.
    """
    return cls._INTERNAL_WORD_STAR_RE.sub(r"\\*", str(text or ""))
@classmethod
def _hr_marker_line_regex(cls) -> re.Pattern[str]:
    cached = cls._HR_MARKER_LINE_RE
    if cached is None:
        cached = re.compile(
            rf"(?m)^[ \t]*{re.escape(cls._HR_MARKER)}[ \t]*$"
        )
        cls._HR_MARKER_LINE_RE = cached
    return cached
@classmethod
def _replace_hr_markers(cls, text: str) -> str:
    return cls._hr_marker_line_regex().sub("- - -", str(text or ""))
@classmethod
def _inject_render_soft_break_tags(cls, text: str) -> str:
    """
    Preserve user-authored single line breaks in plain paragraphs.

    Qt's Markdown parser collapses single newlines inside a paragraph to
    spaces on roundtrip (`setMarkdown()` -> `toMarkdown()`). For preview
    editing we render such breaks as markdown hard-break markers (`\\`),
    so formatting actions do not unexpectedly join source lines.
    """
    lines = str(text or "").split("\n")
    if len(lines) < 2:
        return str(text or "")

    in_fence = False
    fence_char = ""
    fence_len = 0

    def is_plain_paragraph_line(line: str, *, in_code_fence: bool) -> bool:
        if in_code_fence:
            return False
        raw = str(line or "")
        stripped = raw.strip()
        if not stripped:
            return False
        if cls._line_is_blank_like(raw):
            return False
        if cls._FENCE_MARKER_RE.match(stripped):
            return False
        if cls._HEADING_LINE_RE.match(stripped):
            return False
        if raw.startswith("    ") or raw.startswith("\t"):
            return False
        if cls._BLOCKQUOTE_LINE_RE.match(raw):
            return False
        if cls._BULLET_ITEM_RE.match(raw) is not None:
            return False
        if cls._ORDERED_ITEM_RE.match(raw) is not None:
            return False
        if cls._THEMATIC_BREAK_LINE_RE.match(raw):
            return False
        if cls._TABLE_ROW_PREFIX_RE.match(raw):
            return False
        if cls._HTML_LINE_RE.match(raw):
            return False
        return True

    def has_hard_break_marker(line: str) -> bool:
        stripped_right = str(line or "").rstrip()
        if stripped_right.endswith("\\"):
            return True
        return bool(cls._HARD_BREAK_HTML_RE.search(stripped_right))

    out: list[str] = []
    total = len(lines)
    for idx, line in enumerate(lines):
        raw = str(line or "")
        stripped = raw.lstrip()
        fence_match = cls._FENCE_MARKER_RE.match(stripped)
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

        append_line = raw
        if idx < (total - 1):
            next_raw = str(lines[idx + 1] or "")
            if (
                is_plain_paragraph_line(raw, in_code_fence=in_fence)
                and is_plain_paragraph_line(next_raw, in_code_fence=in_fence)
                and not has_hard_break_marker(raw)
            ):
                append_line = f"{raw}\\"
        out.append(append_line)

    return "\n".join(out)
@classmethod
def _inject_render_spacers_for_extra_blank_lines(cls, text: str) -> str:
    lines = str(text or "").split("\n")
    out: list[str] = []
    blank_run: list[str] = []
    in_fence = False
    fence_char = ""
    fence_len = 0

    def flush_blank_run():
        nonlocal blank_run
        if not blank_run:
            return
        has_existing_spacer = any(
            cls._BLANK_LINE_SENTINEL in str(line or "")
            for line in blank_run
        )
        if has_existing_spacer:
            # Stored preview spacers must be render-idempotent; otherwise
            # format actions in HTML view multiply blank gaps each cycle.
            out.extend(blank_run)
        else:
            out.append("")
            for _ in range(max(0, len(blank_run) - 1)):
                out.append(cls._BLANK_LINE_SENTINEL)
                out.append("")
        blank_run = []

    for line in lines:
        stripped = str(line or "").lstrip()
        fence_match = cls._FENCE_MARKER_RE.match(stripped)
        if fence_match is not None:
            marker = fence_match.group(1)
            marker_char = marker[0]
            marker_len = len(marker)
            flush_blank_run()
            if not in_fence:
                in_fence = True
                fence_char = marker_char
                fence_len = marker_len
            elif marker_char == fence_char and marker_len >= fence_len:
                in_fence = False
                fence_char = ""
                fence_len = 0
            out.append(line)
            continue

        if in_fence:
            flush_blank_run()
            out.append(line)
            continue

        if cls._line_is_blank_like(line):
            blank_run.append(line)
            continue

        flush_blank_run()
        out.append(line)

    flush_blank_run()
    return "\n".join(out)
@staticmethod
def _normalize_inline_code_backslashes(text: str) -> str:
    """
    Stabilize inline-code backslashes across Qt Markdown roundtrips.

    QTextDocument.toMarkdown() currently over-escapes backslashes inside
    inline code spans. Repeated setMarkdown()/toMarkdown() cycles then
    multiply them (`\\` -> `\\\\` -> ...). We collapse even-length runs
    in single-backtick code spans back to their minimal representation.
    """

    def collapse_runs(segment: str) -> str:
        out: list[str] = []
        i = 0
        while i < len(segment):
            if segment[i] != "\\":
                out.append(segment[i])
                i += 1
                continue
            j = i
            while j < len(segment) and segment[j] == "\\":
                j += 1
            run_len = j - i
            if run_len >= 2 and run_len % 2 == 0:
                out.append("\\" * (run_len // 2))
            else:
                out.append("\\" * run_len)
            i = j
        return "".join(out)

    def inline_code_repl(match: re.Match[str]) -> str:
        return f"`{collapse_runs(match.group(1))}`"

    return re.sub(r"`([^`\n]*)`", inline_code_repl, text)
@classmethod
def _normalize_ordered_sublist_indent(cls, text: str) -> str:
    """
    Normalize ordered-list sub bullets to a stable indentation depth.

    Qt returns compact indents (often 2/4 spaces) for nested bullets under
    ordered items. That can flatten levels during roundtrips. We map the
    observed bullet nesting depth to stable Markdown indents:
      level 1 -> ordered_indent + 5
      level 2 -> ordered_indent + 9
      level n -> ordered_indent + 5 + 4*(n-1)
    """
    lines = text.split("\n")
    out: list[str] = []
    ordered_indent: int | None = None
    bullet_indent_stack: list[int] = []

    for line in lines:
        raw = line.rstrip()
        stripped = raw.strip()
        if not stripped:
            out.append("")
            continue

        ordered_match = cls._ORDERED_ITEM_RE.match(raw)
        if ordered_match is not None:
            ordered_indent = len(ordered_match.group(1))
            bullet_indent_stack = []
            out.append(raw)
            continue

        current_indent = len(raw) - len(raw.lstrip(" "))
        if ordered_indent is not None and current_indent <= ordered_indent:
            ordered_indent = None
            bullet_indent_stack = []

        bullet_match = cls._BULLET_ITEM_RE.match(raw)
        if bullet_match is not None and ordered_indent is not None:
            bullet_indent = len(bullet_match.group(1))
            if bullet_indent <= ordered_indent:
                ordered_indent = None
                bullet_indent_stack = []
                out.append(raw)
                continue

            if not bullet_indent_stack:
                level = 1
                bullet_indent_stack = [bullet_indent]
            else:
                prev_indent = bullet_indent_stack[-1]
                if bullet_indent > prev_indent:
                    level = len(bullet_indent_stack) + 1
                    bullet_indent_stack.append(bullet_indent)
                elif bullet_indent == prev_indent:
                    level = len(bullet_indent_stack)
                else:
                    while (
                        len(bullet_indent_stack) > 1
                        and bullet_indent < bullet_indent_stack[-1]
                    ):
                        bullet_indent_stack.pop()
                    if bullet_indent > bullet_indent_stack[-1]:
                        level = len(bullet_indent_stack) + 1
                        bullet_indent_stack.append(bullet_indent)
                    else:
                        level = len(bullet_indent_stack)
                        bullet_indent_stack[-1] = bullet_indent

            target_indent = ordered_indent + 5 + ((level - 1) * 4)
            raw = (" " * target_indent) + raw.lstrip()
            out.append(raw)
            continue

        out.append(raw)

    return "\n".join(out)

__all__ = [
    "_markdown_for_render",
    "_escape_internal_word_asterisks",
    "_hr_marker_line_regex",
    "_replace_hr_markers",
    "_inject_render_soft_break_tags",
    "_inject_render_spacers_for_extra_blank_lines",
    "_normalize_inline_code_backslashes",
    "_normalize_ordered_sublist_indent",
]
