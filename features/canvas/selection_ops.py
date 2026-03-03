"""Selection and text-replacement helpers for canvas tabs."""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from widgets.markdown.editor import TabbedEditorWidget


class CanvasSelectionActions:
    """Encapsulates selection-centric operations on the active canvas tab."""

    def __init__(self, tabs: "TabbedEditorWidget"):
        self._tabs = tabs
        self._cached_selection_by_panel: dict[int, str] = {}
        self._cached_span_by_panel: dict[int, tuple[int, int, int]] = {}
        self._tracked_editor = None
        self._tabs.tab_widget.currentChanged.connect(self._on_tab_changed)
        self._on_tab_changed()

    def _on_tab_changed(self, _index: int = -1):
        old_editor = self._tracked_editor
        if old_editor is not None:
            try:
                old_editor.copyAvailable.disconnect(
                    self._on_editor_copy_available
                )
            except Exception:
                pass
        panel = self._tabs.current_panel()
        editor = panel.editor if panel is not None else None
        self._tracked_editor = editor
        if editor is not None:
            try:
                editor.copyAvailable.connect(self._on_editor_copy_available)
            except Exception:
                pass

    def _on_editor_copy_available(self, available: bool):
        if not bool(available):
            return
        panel = self._tabs.current_panel()
        if panel is None:
            return
        cursor = panel.editor.textCursor()
        text = self._normalize_selection_text(panel.editor.get_selected_text())
        if text.strip():
            self._cached_selection_by_panel[id(panel)] = text
            if cursor.hasSelection():
                self._cache_span(
                    panel,
                    int(cursor.selectionStart()),
                    int(cursor.selectionEnd()),
                )

    def get_selected_text(self, *, allow_cached: bool = True) -> str:
        panel = self._tabs.current_panel()
        if panel is None:
            return ""
        if self._should_use_preview_selection(panel):
            selected = self._normalize_selection_text(
                self._get_preview_selected_text(panel)
            )
            if selected.strip():
                self._cached_selection_by_panel[id(panel)] = selected
                span = self._find_selection_span(
                    panel.editor.get_full_text(),
                    selected,
                )
                if span is not None and span != (-1, -1):
                    self._cache_span(panel, span[0], span[1])
                return selected
        selected_editor = self._normalize_selection_text(
            panel.editor.get_selected_text()
        )
        if selected_editor.strip():
            self._cached_selection_by_panel[id(panel)] = selected_editor
            cursor = panel.editor.textCursor()
            if cursor.hasSelection():
                self._cache_span(
                    panel,
                    int(cursor.selectionStart()),
                    int(cursor.selectionEnd()),
                )
            return selected_editor
        if allow_cached:
            return self._cached_selection_by_panel.get(id(panel), "")
        return ""

    def replace_selected_text(
        self,
        replacement: str,
        expected_original: str = "",
    ) -> tuple[bool, str]:
        panel = self._tabs.current_panel()
        if panel is None:
            return False, "No active canvas tab."

        editor = panel.editor
        if self._should_use_preview_selection(panel):
            selected_preview = self._normalize_selection_text(
                self._get_preview_selected_text(panel)
            )
            if not selected_preview.strip():
                selected_preview = self._normalize_selection_text(
                    expected_original
                )
            if not selected_preview.strip():
                selected_preview = self._cached_selection_by_panel.get(
                    id(panel),
                    "",
                )
            if not selected_preview.strip():
                return False, "No active text selection in HTML view."

            expected = self._normalize_selection_text(expected_original)
            if expected and selected_preview != expected:
                return False, "Selection changed since the request was sent."

            span = self._find_selection_span(
                editor.get_full_text(),
                selected_preview,
            )
            if span is None:
                cached = self._get_cached_span(panel)
                if cached is None:
                    return False, (
                        "Could not map HTML selection to markdown source. "
                        "Please narrow the selection."
                    )
                start, end = cached
                self._replace_range(editor, start, end, replacement)
                return True, "Applied (cached span)."
            if span == (-1, -1):
                return False, (
                    "Selection is ambiguous in source text. "
                    "Please select a more specific passage."
                )

            start, end = span
            self._replace_range(editor, start, end, replacement)
            return True, "Applied."

        cursor = editor.textCursor()
        if not cursor.hasSelection():
            expected = self._normalize_selection_text(expected_original)
            if not expected:
                expected = self._cached_selection_by_panel.get(id(panel), "")
            if not expected.strip():
                return False, "No active text selection in draft workspace."
            span = self._find_selection_span(
                editor.get_full_text(),
                expected,
            )
            if span is None:
                cached = self._get_cached_span(panel)
                if cached is None:
                    return False, (
                        "Could not map selection to markdown source. "
                        "Please select a more specific passage."
                    )
                start, end = cached
                self._replace_range(editor, start, end, replacement)
                return True, "Applied (cached span)."
            if span == (-1, -1):
                return False, (
                    "Selection is ambiguous in source text. "
                    "Please select a more specific passage."
                )
            start, end = span
            self._replace_range(editor, start, end, replacement)
            return True, "Applied."

        current_selected = self._normalize_selection_text(
            cursor.selectedText()
        )
        expected = self._normalize_selection_text(expected_original)
        if expected and current_selected != expected:
            return False, "Selection changed since the request was sent."

        cursor.beginEditBlock()
        cursor.insertText(replacement)
        cursor.endEditBlock()
        editor.setTextCursor(cursor)
        return True, "Applied."

    def _cache_span(self, panel, start: int, end: int):
        editor = panel.editor
        if end < start:
            start, end = end, start
        self._cached_span_by_panel[id(panel)] = (
            int(start),
            int(end),
            int(editor.document().revision()),
        )

    def _get_cached_span(self, panel) -> tuple[int, int] | None:
        cached = self._cached_span_by_panel.get(id(panel))
        if cached is None:
            return None
        start, end, revision = cached
        editor = panel.editor
        if int(editor.document().revision()) != int(revision):
            return None
        text_len = len(editor.get_full_text())
        s = max(0, min(int(start), text_len))
        e = max(0, min(int(end), text_len))
        if e <= s:
            return None
        return (s, e)

    def get_current_text(self) -> str:
        panel = self._tabs.current_panel()
        return panel.editor.get_full_text() if panel else ""

    @staticmethod
    def _should_use_preview_selection(panel) -> bool:
        if hasattr(panel, "should_use_preview_selection"):
            try:
                return bool(panel.should_use_preview_selection())
            except Exception:
                return False

        has_visibility_api = (
            hasattr(panel, "is_markdown_visible")
            and hasattr(panel, "is_preview_visible")
        )
        if not has_visibility_api:
            return False
        try:
            return bool(
                panel.is_preview_visible() and not panel.is_markdown_visible()
            )
        except Exception:
            return False

    @staticmethod
    def _get_preview_selected_text(panel) -> str:
        if hasattr(panel, "get_preview_selected_text"):
            try:
                return str(panel.get_preview_selected_text() or "")
            except Exception:
                return ""
        return ""

    @staticmethod
    def _replace_range(editor, start: int, end: int, replacement: str):
        cursor = editor.textCursor()
        cursor.beginEditBlock()
        cursor.setPosition(max(0, int(start)))
        cursor.setPosition(
            max(0, int(end)),
            cursor.MoveMode.KeepAnchor,
        )
        cursor.insertText(replacement)
        cursor.endEditBlock()
        editor.setTextCursor(cursor)

    def _find_selection_span(
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
    def _find_all_direct_spans(
        text: str,
        needle: str,
    ) -> list[tuple[int, int]]:
        spans: list[tuple[int, int]] = []
        start = 0
        while True:
            idx = text.find(needle, start)
            if idx < 0:
                break
            spans.append((idx, idx + len(needle)))
            start = idx + 1
        return spans

    def _find_linewise_normalized_span(
        self,
        source: str,
        selected: str,
    ) -> tuple[int, int] | None:
        lines = source.splitlines(keepends=True)
        if not lines:
            return None

        norm_source = [
            self._normalize_markdown_line(line.rstrip("\n")) for line in lines
        ]
        norm_sel = [
            self._normalize_markdown_line(line)
            for line in selected.splitlines()
        ]

        norm_sel = [line for line in norm_sel if line]
        if not norm_sel:
            return None

        offsets: list[int] = []
        pos = 0
        for line in lines:
            offsets.append(pos)
            pos += len(line)

        source_nonempty: list[tuple[int, str]] = [
            (idx, value)
            for idx, value in enumerate(norm_source)
            if value
        ]
        if not source_nonempty:
            return None

        src_idx = [idx for idx, _ in source_nonempty]
        src_vals = [value for _, value in source_nonempty]
        n = len(norm_sel)
        matches: list[tuple[int, int]] = []
        for i in range(0, len(src_vals) - n + 1):
            if src_vals[i:i + n] != norm_sel:
                continue
            start_line = src_idx[i]
            end_line = src_idx[i + n - 1]
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
        pos = 0
        for line in lines:
            offsets.append(pos)
            pos += len(line)

        source_tokens: list[tuple[str, int]] = []
        for line_idx, raw_line in enumerate(lines):
            normalized = self._normalize_markdown_line(raw_line.rstrip("\n"))
            if not normalized:
                continue
            for token in self._tokenize_for_match(normalized):
                source_tokens.append((token, line_idx))

        selected_tokens: list[str] = []
        for raw_line in selected.splitlines():
            normalized = self._normalize_markdown_line(raw_line)
            if not normalized:
                continue
            selected_tokens.extend(self._tokenize_for_match(normalized))

        if not source_tokens or not selected_tokens:
            return None

        n = len(selected_tokens)
        if n > len(source_tokens):
            return None

        source_words = [token for token, _ in source_tokens]
        matches: list[tuple[int, int]] = []
        for i in range(0, len(source_words) - n + 1):
            if source_words[i:i + n] != selected_tokens:
                continue
            start_line = source_tokens[i][1]
            end_line = source_tokens[i + n - 1][1]
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
        pos = 0
        for line in lines:
            offsets.append(pos)
            pos += len(line)

        source_rows: list[tuple[int, str]] = []
        for idx, raw in enumerate(lines):
            norm = self._normalize_markdown_line(raw.rstrip("\n"))
            if norm:
                source_rows.append((idx, norm))
        if not source_rows:
            return None

        selected_rows = [
            self._normalize_markdown_line(raw)
            for raw in selected.splitlines()
        ]
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
        best_span = 10**9
        ambiguous = False
        for s_idx, s_score in start_hits:
            for e_idx, e_score in end_hits:
                if e_idx < s_idx:
                    continue
                score = s_score + e_score
                span_len = e_idx - s_idx
                if (
                    score > best_score
                    or (abs(score - best_score) < 1e-9 and span_len < best_span)
                ):
                    best = (s_idx, e_idx)
                    best_score = score
                    best_span = span_len
                    ambiguous = False
                elif (
                    abs(score - best_score) < 1e-9
                    and span_len == best_span
                ):
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
        for src_idx, src_norm in source_rows:
            score = self._line_similarity(src_norm, anchor_norm)
            if score >= 0.70:
                hits.append((src_idx, score))
        return hits

    def _line_similarity(self, source_line: str, anchor_line: str) -> float:
        src_tokens = self._tokenize_for_match(source_line)
        anc_tokens = self._tokenize_for_match(anchor_line)
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

    @staticmethod
    def _tokenize_for_match(text: str) -> list[str]:
        """
        Tokenize normalized text for robust HTML->Markdown span mapping.

        This intentionally ignores trailing punctuation differences
        (e.g. "Markdown" vs. "Markdown.").
        """
        src = str(text or "").strip()
        if not src:
            return []
        pattern = r"\w+(?:[+./-]\w+)*"
        return [
            token.casefold()
            for token in re.findall(pattern, src, flags=re.UNICODE)
            if token
        ]

    @staticmethod
    def _normalize_markdown_line(line: str) -> str:
        text = (line or "").replace("\xa0", " ").strip()
        if not text:
            return ""
        if re.match(r"^`{3,}.*$", text):
            return ""
        if re.match(r"^[-*_]{3,}\s*$", text):
            return ""
        text = re.sub(r"^#{1,6}\s*", "", text)
        text = re.sub(r"^\s*(?:[-*+]|[•◦▪●]|\d+[.)])\s+", "", text)
        text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", text)
        text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
        text = re.sub(r"`([^`]*)`", r"\1", text)
        text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
        text = re.sub(r"__([^_]+)__", r"\1", text)
        text = re.sub(r"\*([^*]+)\*", r"\1", text)
        text = re.sub(r"_([^_]+)_", r"\1", text)
        text = re.sub(r"\\([^\s])", r"\1", text)
        text = re.sub(r"<[^>]+>", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _normalize_selection_text(text: str) -> str:
        # Qt's selectedText() uses U+2029 paragraph separators.
        return (text or "").replace("\u2029", "\n").replace("\r\n", "\n")
