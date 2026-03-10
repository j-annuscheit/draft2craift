"""CanvasPreviewPane method implementations."""
from __future__ import annotations

from .deps import *  # noqa: F403
from .models import _RenderedHighlight

def _schedule_highlight_sync(self):
    self._highlight_sync_timer.start(self._HIGHLIGHT_SYNC_DELAY_MS)
def _sync_highlights_from_editor(self):
    editor = self._editor
    if editor is None:
        return
    md = self._markdown_for_render(editor.get_full_text())
    doc = QTextDocument()
    spec = extract_graph_spec(md)
    if spec is None:
        doc.setMarkdown(md)
    else:
        signature = graph_spec_signature(spec)
        if signature == self._structured_graph_signature:
            collapsed = set(self._graph_collapsed_ids)
            focus = self._graph_focus_node_id
        else:
            collapsed = set(spec.default_collapsed_ids)
            focus = ""
        doc.setHtml(
            render_graph_html(
                spec,
                collapsed_ids=collapsed,
                focus_node_id=focus,
            )
        )
    plain_text = (doc.toPlainText() or "").replace("\r\n", "\n")
    get_highlight_store().sync_for_text(
        panel_scope=self._highlight_scope,
        tab_name=self._current_tab_name(),
        full_text=plain_text,
    )
def _apply_highlights(self):
    theme_selections = self._build_preview_theme_extra_selections()
    if self._structured_view_active:
        # Text overlays are bound to QTextBrowser selections.
        # Graph mode uses dedicated scene tooltips and click targets.
        self._rendered_highlights = []
        self._view.setExtraSelections(theme_selections)
        return
    text = self._preview_plain_text()
    store = get_highlight_store()
    store.sync_for_text(
        panel_scope=self._highlight_scope,
        tab_name=self._current_tab_name(),
        full_text=text,
    )
    matches = store.resolve_matches(
        panel_scope=self._highlight_scope,
        tab_name=self._current_tab_name(),
        full_text=text,
    )
    self._rendered_highlights = []
    if not matches:
        self._view.setExtraSelections(theme_selections)
        return
    old_suppress = self._suppress_preview_change
    self._suppress_preview_change = True
    try:
        self._render_highlight_matches(
            matches,
            theme_selections=theme_selections,
        )
    finally:
        self._suppress_preview_change = old_suppress
def _render_highlight_matches(
    self,
    matches: list[HighlightMatch],
    *,
    theme_selections: list[QTextEdit.ExtraSelection] | None = None,
):
    self._ensure_index_maps()
    doc = self._view.document()
    selections: list[QTextEdit.ExtraSelection] = list(theme_selections or [])
    for item in matches:
        start_py = max(0, int(item.start))
        end_py = max(0, int(item.end))
        if end_py <= start_py:
            continue
        start = self._py_to_qt_pos(start_py)
        end = self._py_to_qt_pos(end_py)
        if end <= start:
            continue
        cursor = QTextCursor(doc)
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        fmt = QTextCharFormat()
        bg_color = QColor(item.color or "#F9E2AF")
        if bg_color.isValid():
            bg_color.setAlpha(120)
            fmt.setBackground(bg_color)
        sel = QTextEdit.ExtraSelection()
        sel.cursor = cursor
        sel.format = fmt
        selections.append(sel)
        self._rendered_highlights.append(
            _RenderedHighlight(
                highlight_id=item.highlight_id,
                start=start,
                end=end,
                color=item.color,
                hover_text=item.hover_text,
                jump_to=item.jump_to,
                kind=item.kind,
            )
        )
    self._view.setExtraSelections(selections)

__all__ = [
    "_schedule_highlight_sync",
    "_sync_highlights_from_editor",
    "_apply_highlights",
    "_render_highlight_matches",
]
