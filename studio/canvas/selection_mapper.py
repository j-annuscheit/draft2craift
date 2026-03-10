"""Selection span mapping between preview text and markdown source."""
from __future__ import annotations

from studio.canvas.selection_text import (
    normalize_markdown_line,
    normalize_selection_text,
    tokenize_for_match,
)


class SelectionSpanMapper:
    """Maps selected text snippets to source text spans with robust fallbacks."""

    def align_span_with_selection_boundaries(
        self,
        source: str,
        selected: str,
        start: int,
        end: int,
    ) -> tuple[int, int]:
        """
        Trim accidental boundary newlines from mapped spans.

        HTML->Markdown mapping heuristics may return whole-line spans and include
        the trailing newline of the last line. If the user's selected text did
        not include that newline, replacing the span can merge the next line
        into the replacement.
        """
        src = (source or "").replace("\r\n", "\n")
        sel = normalize_selection_text(selected)
        text_len = len(src)
        start = max(0, min(int(start), text_len))
        end = max(0, min(int(end), text_len))
        if end <= start or not sel:
            return (start, end)

        if not sel.endswith("\n"):
            while end > start and src[end - 1] == "\n":
                end -= 1
                if normalize_selection_text(src[start:end]) == sel:
                    break
        if not sel.startswith("\n"):
            while start < end and src[start] == "\n":
                start += 1
                if normalize_selection_text(src[start:end]) == sel:
                    break
        return (start, end)

    def find_selection_span(
        self,
        source: str,
        selected: str,
    ) -> tuple[int, int] | None:
        src = (source or "").replace("\r\n", "\n")
        sel = (selected or "").replace("\r\n", "\n").strip("\n")
        if not src or not sel:
            return None

        direct = self._find_all_direct_spans(src, sel)
        if len(direct) == 1:
            return direct[0]
        if len(direct) > 1:
            return (-1, -1)

        linewise = self._find_linewise_normalized_span(src, sel)
        if linewise is not None:
            return linewise

        tokenwise = self._find_tokenwise_normalized_span(src, sel)
        if tokenwise is not None:
            return tokenwise

        return self._find_boundary_anchor_span(src, sel)

    @staticmethod
    def _find_all_direct_spans(text: str, needle: str) -> list[tuple[int, int]]:
        spans: list[tuple[int, int]] = []
        start = 0
        while True:
            index = text.find(needle, start)
            if index < 0:
                break
            spans.append((index, index + len(needle)))
            start = index + 1
        return spans

    def _find_linewise_normalized_span(
        self,
        source: str,
        selected: str,
    ) -> tuple[int, int] | None:
        lines = source.splitlines(keepends=True)
        if not lines:
            return None

        norm_source = [normalize_markdown_line(line.rstrip("\n")) for line in lines]
        norm_sel = [normalize_markdown_line(line) for line in selected.splitlines()]
        norm_sel = [line for line in norm_sel if line]
        if not norm_sel:
            return None

        offsets: list[int] = []
        position = 0
        for line in lines:
            offsets.append(position)
            position += len(line)

        source_nonempty: list[tuple[int, str]] = [
            (index, value)
            for index, value in enumerate(norm_source)
            if value
        ]
        if not source_nonempty:
            return None

        source_indices = [index for index, _ in source_nonempty]
        source_values = [value for _, value in source_nonempty]
        block_len = len(norm_sel)
        matches: list[tuple[int, int]] = []

        for index in range(0, len(source_values) - block_len + 1):
            if source_values[index:index + block_len] != norm_sel:
                continue
            start_line = source_indices[index]
            end_line = source_indices[index + block_len - 1]
            start = offsets[start_line]
            end = offsets[end_line] + len(lines[end_line])
            matches.append((start, end))

        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            return (-1, -1)
        return None

    def _find_tokenwise_normalized_span(
        self,
        source: str,
        selected: str,
    ) -> tuple[int, int] | None:
        lines = source.splitlines(keepends=True)
        if not lines:
            return None

        offsets: list[int] = []
        position = 0
        for line in lines:
            offsets.append(position)
            position += len(line)

        source_tokens: list[tuple[str, int]] = []
        for line_index, raw_line in enumerate(lines):
            normalized = normalize_markdown_line(raw_line.rstrip("\n"))
            if not normalized:
                continue
            for token in tokenize_for_match(normalized):
                source_tokens.append((token, line_index))

        selected_tokens: list[str] = []
        for raw_line in selected.splitlines():
            normalized = normalize_markdown_line(raw_line)
            if not normalized:
                continue
            selected_tokens.extend(tokenize_for_match(normalized))

        if not source_tokens or not selected_tokens:
            return None
        if len(selected_tokens) > len(source_tokens):
            return None

        source_words = [token for token, _ in source_tokens]
        block_len = len(selected_tokens)
        matches: list[tuple[int, int]] = []

        for index in range(0, len(source_words) - block_len + 1):
            if source_words[index:index + block_len] != selected_tokens:
                continue
            start_line = source_tokens[index][1]
            end_line = source_tokens[index + block_len - 1][1]
            start = offsets[start_line]
            end = offsets[end_line] + len(lines[end_line])
            matches.append((start, end))

        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            return (-1, -1)
        return None

    def _find_boundary_anchor_span(
        self,
        source: str,
        selected: str,
    ) -> tuple[int, int] | None:
        """
        Fallback span mapping using first/last selected line as anchors.

        Useful when HTML selection text drops formatting-only source lines
        (e.g. horizontal rules / markdown markers) between start and end.
        """
        lines = source.splitlines(keepends=True)
        if not lines:
            return None

        offsets: list[int] = []
        position = 0
        for line in lines:
            offsets.append(position)
            position += len(line)

        source_rows: list[tuple[int, str]] = []
        for index, raw_line in enumerate(lines):
            normalized = normalize_markdown_line(raw_line.rstrip("\n"))
            if normalized:
                source_rows.append((index, normalized))
        if not source_rows:
            return None

        selected_rows = [normalize_markdown_line(raw) for raw in selected.splitlines()]
        selected_rows = [row for row in selected_rows if row]
        if not selected_rows:
            return None

        first_anchor = selected_rows[0]
        last_anchor = selected_rows[-1]

        start_hits = self._anchor_line_hits(source_rows, first_anchor)
        end_hits = self._anchor_line_hits(source_rows, last_anchor)
        if not start_hits or not end_hits:
            return None

        best: tuple[int, int] | None = None
        best_score = -1.0
        best_span_len = 10**9
        ambiguous = False

        for start_index, start_score in start_hits:
            for end_index, end_score in end_hits:
                if end_index < start_index:
                    continue
                score = start_score + end_score
                span_len = end_index - start_index
                if score > best_score or (
                    abs(score - best_score) < 1e-9 and span_len < best_span_len
                ):
                    best = (start_index, end_index)
                    best_score = score
                    best_span_len = span_len
                    ambiguous = False
                elif abs(score - best_score) < 1e-9 and span_len == best_span_len:
                    ambiguous = True

        if best is None:
            return None
        if ambiguous:
            return (-1, -1)

        start_line, end_line = best
        start = offsets[start_line]
        end = offsets[end_line] + len(lines[end_line])
        return (start, end)

    def _anchor_line_hits(
        self,
        source_rows: list[tuple[int, str]],
        anchor: str,
    ) -> list[tuple[int, float]]:
        hits: list[tuple[int, float]] = []
        anchor_norm = str(anchor or "").strip()
        if not anchor_norm:
            return hits
        for src_index, src_norm in source_rows:
            score = self._line_similarity(src_norm, anchor_norm)
            if score >= 0.70:
                hits.append((src_index, score))
        return hits

    @staticmethod
    def _line_similarity(source_line: str, anchor_line: str) -> float:
        src_tokens = tokenize_for_match(source_line)
        anc_tokens = tokenize_for_match(anchor_line)
        if not src_tokens or not anc_tokens:
            return 0.0

        src_set = set(src_tokens)
        anc_set = set(anc_tokens)
        overlap = len(src_set & anc_set)
        base = overlap / max(1, len(anc_set))

        src_text = " ".join(src_tokens)
        anc_text = " ".join(anc_tokens)
        if src_text == anc_text:
            return 1.0
        if src_text.startswith(anc_text) or anc_text.startswith(src_text):
            base = max(base, 0.9)
        return base
