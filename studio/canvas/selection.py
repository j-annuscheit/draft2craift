"""Selection and text-replacement helpers for canvas tabs."""
from __future__ import annotations

from typing import TYPE_CHECKING

from studio.canvas.selection_cache import SelectionStateCache
from studio.canvas.selection_mapper import SelectionSpanMapper
from studio.canvas.selection_panel import (
    get_preview_selected_text,
    should_use_preview_selection_path,
)
from studio.canvas.selection_text import normalize_selection_text

if TYPE_CHECKING:
    from studio.canvas.tabbed_editor_widget import TabbedEditorWidget


class CanvasSelectionActions:
    """Encapsulates selection-centric operations on the active canvas tab."""

    def __init__(self, tabs: "TabbedEditorWidget"):
        self._tabs = tabs
        self._cache = SelectionStateCache()
        self._mapper = SelectionSpanMapper()
        self._tracked_editor = None
        self._tracked_panel = None
        self._tabs.tab_widget.currentChanged.connect(self._on_tab_changed)
        self._on_tab_changed()

    def _on_tab_changed(self, _index: int = -1):
        old_editor = self._tracked_editor
        old_panel = self._tracked_panel
        if old_editor is not None:
            try:
                old_editor.copyAvailable.disconnect(self._on_editor_copy_available)
            except Exception:
                pass
        if old_panel is not None and hasattr(old_panel, "disconnect_preview_copy_available"):
            try:
                old_panel.disconnect_preview_copy_available(self._on_preview_copy_available)
            except Exception:
                pass

        panel = self._tabs.current_panel()
        editor = panel.editor if panel is not None else None
        self._tracked_panel = panel
        self._tracked_editor = editor

        if editor is not None:
            try:
                editor.copyAvailable.connect(self._on_editor_copy_available)
            except Exception:
                pass
        if panel is not None and hasattr(panel, "connect_preview_copy_available"):
            try:
                panel.connect_preview_copy_available(self._on_preview_copy_available)
            except Exception:
                pass

    def _on_editor_copy_available(self, available: bool):
        panel = self._tabs.current_panel()
        if panel is None:
            return
        if not bool(available):
            if self._cache.should_preserve_editor_cache(panel):
                return
            self._clear_cached_selection(panel)
            return

        cursor = panel.editor.textCursor()
        text = normalize_selection_text(panel.editor.get_selected_text())
        if not text.strip():
            return

        self._cache.store_selection(panel, text)
        if cursor.hasSelection():
            self._cache_span(
                panel,
                int(cursor.selectionStart()),
                int(cursor.selectionEnd()),
            )

    def _on_preview_copy_available(self, available: bool):
        panel = self._tabs.current_panel()
        if panel is None:
            return
        if not bool(available):
            if self._cache.should_preserve_preview_cache(panel):
                return
            self._clear_cached_selection(panel)
            return

        text = normalize_selection_text(get_preview_selected_text(panel))
        if not text.strip():
            return

        self._cache.store_selection(panel, text)
        span = self._find_selection_span(panel.editor.get_full_text(), text)
        if span is not None and span != (-1, -1):
            self._cache_span(panel, span[0], span[1])

    def get_selected_text(
        self,
        *,
        allow_cached: bool = True,
        consume_cached: bool = True,
    ) -> str:
        panel = self._tabs.current_panel()
        if panel is None:
            return ""

        if self._use_preview_selection_path(panel):
            selected = normalize_selection_text(get_preview_selected_text(panel))
            if selected.strip():
                self._cache.store_selection(panel, selected)
                span = self._find_selection_span(panel.editor.get_full_text(), selected)
                if span is not None and span != (-1, -1):
                    self._cache_span(panel, span[0], span[1])
                return selected

        selected_editor = normalize_selection_text(panel.editor.get_selected_text())
        if selected_editor.strip():
            self._cache.store_selection(panel, selected_editor)
            cursor = panel.editor.textCursor()
            if cursor.hasSelection():
                self._cache_span(
                    panel,
                    int(cursor.selectionStart()),
                    int(cursor.selectionEnd()),
                )
            return selected_editor

        if allow_cached:
            cached = self._cache.pop_selection(panel, consume=consume_cached)
            if cached.strip():
                # One-shot fallback for focus handoff (e.g. click on Send).
                return cached
        return ""

    def get_selected_span(
        self,
        *,
        allow_cached: bool = True,
    ) -> tuple[int, int] | None:
        panel = self._tabs.current_panel()
        if panel is None:
            return None

        if self._use_preview_selection_path(panel):
            selected = normalize_selection_text(get_preview_selected_text(panel))
            if selected.strip():
                span = self._find_selection_span(panel.editor.get_full_text(), selected)
                if span is not None and span != (-1, -1):
                    self._cache_span(panel, span[0], span[1])
                    return (int(span[0]), int(span[1]))

        cursor = panel.editor.textCursor()
        if cursor.hasSelection():
            start = int(cursor.selectionStart())
            end = int(cursor.selectionEnd())
            self._cache_span(panel, start, end)
            if end < start:
                start, end = end, start
            return (start, end)

        if allow_cached:
            return self._get_cached_span(panel)
        return None

    def replace_selected_text(
        self,
        replacement: str,
        expected_original: str = "",
        preferred_span: tuple[int, int] | None = None,
    ) -> tuple[bool, str]:
        panel = self._tabs.current_panel()
        if panel is None:
            return False, "No active canvas tab."

        editor = panel.editor
        if preferred_span is not None:
            explicit = self._apply_preferred_span_replace(
                editor,
                replacement,
                expected_original,
                preferred_span,
            )
            if explicit[0]:
                return explicit

        if self._use_preview_selection_path(panel):
            return self._replace_for_preview_path(
                panel,
                editor,
                replacement,
                expected_original,
            )

        cursor = editor.textCursor()
        if not cursor.hasSelection():
            return self._replace_without_editor_selection(
                panel,
                editor,
                replacement,
                expected_original,
            )

        current_selected = normalize_selection_text(cursor.selectedText())
        expected = normalize_selection_text(expected_original)
        if expected and current_selected != expected:
            return False, "Selection changed since the request was sent."

        cursor.beginEditBlock()
        cursor.insertText(replacement)
        cursor.endEditBlock()
        editor.setTextCursor(cursor)
        return True, "Applied."

    def _replace_for_preview_path(
        self,
        panel,
        editor,
        replacement: str,
        expected_original: str,
    ) -> tuple[bool, str]:
        selected_preview = normalize_selection_text(get_preview_selected_text(panel))
        if not selected_preview.strip():
            selected_preview = normalize_selection_text(expected_original)
        if not selected_preview.strip():
            selected_preview = self._cache.pop_selection(panel, consume=False)
        if not selected_preview.strip():
            return False, "No active text selection in HTML view."

        expected = normalize_selection_text(expected_original)
        if expected and selected_preview != expected:
            return False, "Selection changed since the request was sent."

        span = self._find_selection_span(editor.get_full_text(), selected_preview)
        if span is None:
            return self._replace_with_cached_span_or_error(
                panel,
                editor,
                replacement,
                "Could not map HTML selection to markdown source. "
                "Please narrow the selection.",
            )
        if span == (-1, -1):
            return self._replace_with_cached_span_or_error(
                panel,
                editor,
                replacement,
                "Selection is ambiguous in source text. "
                "Please select a more specific passage.",
            )

        start, end = self._mapper.align_span_with_selection_boundaries(
            editor.get_full_text(),
            selected_preview,
            span[0],
            span[1],
        )
        self._replace_range(editor, start, end, replacement)
        return True, "Applied."

    def _replace_without_editor_selection(
        self,
        panel,
        editor,
        replacement: str,
        expected_original: str,
    ) -> tuple[bool, str]:
        expected = normalize_selection_text(expected_original)
        if not expected:
            expected = self._cache.pop_selection(panel, consume=False)
        if not expected.strip():
            return False, "No active text selection in draft workspace."

        span = self._find_selection_span(editor.get_full_text(), expected)
        if span is None:
            return self._replace_with_cached_span_or_error(
                panel,
                editor,
                replacement,
                "Could not map selection to markdown source. "
                "Please select a more specific passage.",
            )
        if span == (-1, -1):
            return self._replace_with_cached_span_or_error(
                panel,
                editor,
                replacement,
                "Selection is ambiguous in source text. "
                "Please select a more specific passage.",
            )

        start, end = self._mapper.align_span_with_selection_boundaries(
            editor.get_full_text(),
            expected,
            span[0],
            span[1],
        )
        self._replace_range(editor, start, end, replacement)
        return True, "Applied."

    def _replace_with_cached_span_or_error(
        self,
        panel,
        editor,
        replacement: str,
        error_message: str,
    ) -> tuple[bool, str]:
        cached = self._get_cached_span(panel)
        if cached is None:
            return False, error_message
        start, end = cached
        self._replace_range(editor, start, end, replacement)
        return True, "Applied (cached span)."

    def _apply_preferred_span_replace(
        self,
        editor,
        replacement: str,
        expected_original: str,
        preferred_span: tuple[int, int],
    ) -> tuple[bool, str]:
        text = editor.get_full_text()
        text_len = len(text)
        try:
            start, end = preferred_span
        except Exception:
            return False, "Invalid selection span."

        start = max(0, min(int(start), text_len))
        end = max(0, min(int(end), text_len))
        if end <= start:
            return False, "Invalid selection span."

        expected = normalize_selection_text(expected_original)
        current = normalize_selection_text(text[start:end])
        if expected and current != expected:
            return False, "Selection changed since the request was sent."

        self._replace_range(editor, start, end, replacement)
        return True, "Applied (selection span)."

    def _cache_span(self, panel, start: int, end: int):
        self._cache.cache_span(panel, start, end)

    def _clear_cached_selection(self, panel):
        self._cache.clear(panel)

    def _get_cached_span(self, panel) -> tuple[int, int] | None:
        return self._cache.get_span(panel)

    def get_current_text(self) -> str:
        panel = self._tabs.current_panel()
        return panel.editor.get_full_text() if panel else ""

    def _use_preview_selection_path(self, panel) -> bool:
        return should_use_preview_selection_path(panel)

    @staticmethod
    def _replace_range(editor, start: int, end: int, replacement: str):
        cursor = editor.textCursor()
        cursor.beginEditBlock()
        cursor.setPosition(max(0, int(start)))
        cursor.setPosition(max(0, int(end)), cursor.MoveMode.KeepAnchor)
        cursor.insertText(replacement)
        cursor.endEditBlock()
        editor.setTextCursor(cursor)

    def _find_selection_span(self, source: str, selected: str) -> tuple[int, int] | None:
        return self._mapper.find_selection_span(source, selected)
