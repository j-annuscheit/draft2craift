"""CanvasPreviewPane method implementations."""
from __future__ import annotations

from .deps import *  # noqa: F403

def _render(self):
    if not self.isVisible():
        return
    if self._preview_edit_active:
        return
    self._render_cycle_id += 1
    # Drop stale delayed cursor-sync tasks; render decides the final position.
    self._cursor_timer.stop()

    self._apply_view_document_style()
    prior_view_state = self._capture_view_state()
    freeze_updates = True
    if freeze_updates:
        self._view.setUpdatesEnabled(False)

    try:
        self._arm_async_preview_change_suppress()
        self._suppress_preview_change = True
        did_replace_document = False
        try:
            if self._editor is None:
                self._set_structured_graph_state(None)
                self._view.setHtml("<p><em>Keine aktive Draft-Seite.</em></p>")
                self._last_rendered_markdown = None
                did_replace_document = True
                self._rendered_highlights = []
                self._view.setExtraSelections([])
                return

            md = self._editor.get_full_text()
            if not md.strip():
                self._set_structured_graph_state(None)
                self._view.clear()
                self._last_rendered_markdown = None
                did_replace_document = True
                self._rendered_highlights = []
                self._view.setExtraSelections([])
                return

            render_md = self._markdown_for_render(md)
            render_md = self._apply_render_unordered_marker_gap(render_md)
            if render_md != self._last_rendered_markdown:
                self._set_markdown_or_graph_content(render_md)
                self._last_rendered_markdown = render_md
                did_replace_document = True
            else:
                if not self._structured_view_active:
                    # Defensive integrity check for sporadic end-of-document
                    # truncation in HTML-only mode: if the tail is missing in
                    # the currently visible preview, force a full rerender.
                    tail_probe = self._tail_probe_from_markdown(render_md)
                    if tail_probe and not self._contains_tail_probe(
                        self._preview_plain_text(),
                        tail_probe,
                    ):
                        self._set_markdown_or_graph_content(render_md)
                        self._last_rendered_markdown = render_md
                        did_replace_document = True
        finally:
            self._suppress_preview_change = False

        self._apply_block_spacing_overrides()
        self._apply_code_typography_overrides()
        self._apply_highlights()
        if not did_replace_document:
            self._preserve_view_state_once = False
            return
        if self._sync_cursor_with_editor:
            # Keep preview caret stable while the user is interacting in
            # HTML view. Otherwise QTextBrowser resets the caret to start
            # when setMarkdown()/setHtml() replaces the document.
            preserve_cursor = self._focus_is_inside_preview()
            editor_visible = (
                self._editor is not None and self._editor.isVisible()
            )
            if not editor_visible:
                self._restore_view_state(
                    prior_view_state,
                    restore_cursor=preserve_cursor,
                )
                self._preserve_view_state_once = False
                return
            had_prior_scroll_range = int(prior_view_state[3]) > 0
            if (
                self._preserve_view_state_once
                or preserve_cursor
                or had_prior_scroll_range
            ):
                self._restore_view_state(
                    prior_view_state,
                    restore_cursor=preserve_cursor,
                )
                self._preserve_view_state_once = False
            else:
                self._sync_to_cursor()
            return
        # Chat-style rendering (no cursor-sync): keep the viewport pinned
        # to the newest content so there is no visible jump to top.
        self.scroll_to_bottom()
        self._preserve_view_state_once = False
    finally:
        if freeze_updates:
            self._view.setUpdatesEnabled(True)
            self._view.viewport().update()
def _sync_to_cursor(self):
    if (
        not self._sync_cursor_with_editor
        or not self.isVisible()
        or self._editor is None
        or self._preview_edit_active
    ):
        return
    if self._structured_view_active:
        return
    if not self._editor.isVisible():
        return
    if self._focus_is_inside_preview():
        return

    target_ratio = 0.0

    editor_scroll = self._editor.verticalScrollBar()
    if editor_scroll.maximum() > 0:
        target_ratio = max(
            0.0,
            min(
                1.0,
                float(editor_scroll.value()) / float(editor_scroll.maximum()),
            ),
        )
    else:
        return

    scrollbar = self._view.verticalScrollBar()
    if scrollbar.maximum() <= 0:
        return
    scrollbar.setValue(int(round(float(scrollbar.maximum()) * target_ratio)))
def _sync_preview_interaction_mode(self):
    allow_preview_editing = (
        self._allow_editing and not self._structured_view_active
    )
    self._view.setReadOnly(not allow_preview_editing)
    if self._format_bar is not None:
        self._format_bar.setVisible(allow_preview_editing)
    if hasattr(self, "_graph_bar") and self._graph_bar is not None:
        self._graph_bar.setVisible(self._structured_view_active)
    if self._graph_view is not None:
        self._graph_view.setInteractive(self._structured_view_active)
def _set_structured_graph_state(self, spec: GraphSpec | None):
    self._structured_graph_spec = spec
    if spec is None:
        self._structured_graph_signature = ""
        self._graph_collapsed_ids = set()
        self._graph_focus_node_id = ""
        self._graph_manual_positions = {}
        self._graph_layout_nonce = 0
        self._graph_plain_text = ""
        self._structured_view_active = False
        if hasattr(self, "_content_stack"):
            self._content_stack.setCurrentWidget(self._view)
        self._sync_preview_interaction_mode()
        return

    # Structured graph mode is read-only from the graph canvas. Any pending
    # preview->markdown sync would write stale QTextBrowser content back.
    self._preview_to_markdown_timer.stop()
    self._preview_edit_active = False
    self._preview_user_edit_dirty = False
    self._preview_user_edit_intent = False

    signature = graph_spec_signature(spec)
    if signature != self._structured_graph_signature:
        self._structured_graph_signature = signature
        self._graph_collapsed_ids = (
            self._initial_collapsed_graph_nodes(spec)
            | set(spec.default_collapsed_ids)
        )
        self._graph_focus_node_id = ""
        self._graph_manual_positions = {}
        self._graph_layout_nonce = 0

    valid = set(spec.nodes.keys())
    include_edges = spec.kind == "graph"
    expandable = self._expandable_graph_nodes(
        spec,
        include_edges=include_edges,
    )
    self._graph_collapsed_ids = {
        node_id
        for node_id in self._graph_collapsed_ids
        if node_id in valid and node_id in expandable
    }
    if self._graph_focus_node_id not in valid:
        self._graph_focus_node_id = ""

    self._structured_view_active = True
    if hasattr(self, "_content_stack") and self._graph_view is not None:
        self._content_stack.setCurrentWidget(self._graph_view)
    self._sync_preview_interaction_mode()
def _set_markdown_or_graph_content(self, markdown_text: str):
    self._arm_async_preview_change_suppress()
    spec = extract_graph_spec(markdown_text)
    if spec is None:
        self._set_structured_graph_state(None)
        self._view.setMarkdown(markdown_text)
        return

    self._set_structured_graph_state(spec)
    self._render_structured_graph_scene(spec)
def _arm_async_preview_change_suppress(self):
    """Suppress delayed textChanged signals from programmatic preview updates."""
    self._suppress_preview_change_async += 1

    def release():
        self._suppress_preview_change_async = max(
            0,
            int(self._suppress_preview_change_async) - 1,
        )

    QTimer.singleShot(0, release)
@staticmethod
def _is_preview_content_edit_keypress(event) -> bool:
    if event is None:
        return False
    if event.matches(QKeySequence.StandardKey.Paste):
        return True
    if event.matches(QKeySequence.StandardKey.Cut):
        return True
    if event.matches(QKeySequence.StandardKey.Undo):
        return True
    if event.matches(QKeySequence.StandardKey.Redo):
        return True
    key = int(event.key())
    if key in (
        int(Qt.Key.Key_Backspace),
        int(Qt.Key.Key_Delete),
        int(Qt.Key.Key_Return),
        int(Qt.Key.Key_Enter),
    ):
        return True
    if event.modifiers() & (
        Qt.KeyboardModifier.ControlModifier
        | Qt.KeyboardModifier.AltModifier
        | Qt.KeyboardModifier.MetaModifier
    ):
        return False
    return bool(str(event.text() or ""))

__all__ = [
    "_render",
    "_sync_to_cursor",
    "_sync_preview_interaction_mode",
    "_set_structured_graph_state",
    "_set_markdown_or_graph_content",
    "_arm_async_preview_change_suppress",
    "_is_preview_content_edit_keypress",
]
