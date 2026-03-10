"""Per-panel one-shot selection cache and stable span cache."""
from __future__ import annotations


class SelectionStateCache:
    """Stores temporary text selection and revision-bound source spans."""

    def __init__(self):
        self._selected_by_panel: dict[int, str] = {}
        self._span_by_panel: dict[int, tuple[int, int, int]] = {}

    def store_selection(self, panel, text: str) -> None:
        self._selected_by_panel[id(panel)] = str(text or "")

    def pop_selection(self, panel, *, consume: bool) -> str:
        key = id(panel)
        cached = self._selected_by_panel.get(key, "")
        if cached.strip() and consume:
            self._selected_by_panel.pop(key, None)
        return cached

    def clear(self, panel) -> None:
        key = id(panel)
        self._selected_by_panel.pop(key, None)
        self._span_by_panel.pop(key, None)

    def cache_span(self, panel, start: int, end: int) -> None:
        editor = panel.editor
        if end < start:
            start, end = end, start
        self._span_by_panel[id(panel)] = (
            int(start),
            int(end),
            int(editor.document().revision()),
        )

    def get_span(self, panel) -> tuple[int, int] | None:
        cached = self._span_by_panel.get(id(panel))
        if cached is None:
            return None

        start, end, revision = cached
        editor = panel.editor
        if int(editor.document().revision()) != int(revision):
            return None

        text_len = len(editor.get_full_text())
        start = max(0, min(int(start), text_len))
        end = max(0, min(int(end), text_len))
        if end <= start:
            return None
        return (start, end)

    @staticmethod
    def should_preserve_editor_cache(panel) -> bool:
        """
        Keep one-shot selection cache when focus moved away from the editor.

        This covers the common flow where users select text in canvas and then
        click the chat input/send button. In that case selection disappears, but
        rewrite should still use the just-selected span once.
        """
        editor = getattr(panel, "editor", None)
        if editor is None or not hasattr(editor, "hasFocus"):
            return False
        try:
            return not bool(editor.hasFocus())
        except Exception:
            return False

    @staticmethod
    def should_preserve_preview_cache(panel) -> bool:
        """Keep one-shot preview selection cache when preview lost focus."""
        if hasattr(panel, "preview_has_focus"):
            try:
                return not bool(panel.preview_has_focus())
            except Exception:
                return False
        return False
