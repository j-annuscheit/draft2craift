"""CanvasPreviewPane method implementations."""
from __future__ import annotations

from .deps import *  # noqa: F403

def _on_preview_text_changed(self):
    if (
        not self._allow_editing
        or self._structured_view_active
        or self._suppress_preview_change
        or self._suppress_preview_change_async > 0
        or self._editor is None
    ):
        return
    if not self._focus_is_inside_preview():
        return
    if not self._preview_user_edit_intent:
        return
    self._preview_user_edit_intent = False
    self._preview_user_edit_dirty = True
    self._preview_edit_active = True
    self._preview_to_markdown_timer.start(
        self._PREVIEW_TO_MARKDOWN_DELAY_MS
    )
def _commit_preview_edit_to_markdown(
    self,
    *,
    force: bool = False,
    preserve_reference_linebreaks: bool = False,
):
    if (
        self._editor is None
        or (not self._allow_editing)
        or self._structured_view_active
    ):
        self._preview_edit_active = False
        self._preview_user_edit_dirty = False
        self._preview_user_edit_intent = False
        return
    if (not force) and self._focus_is_inside_preview():
        return
    if not self._preview_user_edit_dirty and not preserve_reference_linebreaks:
        self._preview_edit_active = False
        self._preview_user_edit_intent = False
        return
    current_markdown = self._editor.get_full_text().replace(
        "\r\n",
        "\n",
    ).rstrip()
    plain_text = (self._view.toPlainText() or "").replace("\r\n", "\n")
    new_markdown = self._canonical_markdown(self._view.toMarkdown())
    new_markdown = self._escape_internal_word_asterisks(new_markdown)
    new_markdown = self._unwrap_soft_wrapped_plain_paragraphs(new_markdown)
    new_markdown = self._restore_extra_blank_lines_from_plaintext(
        new_markdown,
        plain_text,
    )
    new_markdown = self._restore_soft_wrapped_plain_lines_from_reference(
        new_markdown,
        current_markdown,
    )
    if preserve_reference_linebreaks:
        new_markdown = self._restore_blank_like_runs_from_reference(
            new_markdown,
            current_markdown,
        )
    if (
        self._view_has_terminal_hr()
        and not self._markdown_has_terminal_hr(new_markdown)
    ):
        if new_markdown.strip():
            new_markdown = f"{new_markdown}\n\n- - -"
        else:
            new_markdown = "- - -"
    if new_markdown == current_markdown:
        self._preview_edit_active = False
        self._preview_user_edit_dirty = False
        self._preview_user_edit_intent = False
        return
    editor = self._editor
    old_cursor_pos = int(editor.textCursor().position())
    old_scroll = editor.verticalScrollBar().value()
    cursor = editor.textCursor()
    cursor.beginEditBlock()
    cursor.select(QTextCursor.SelectionType.Document)
    cursor.insertText(new_markdown)
    cursor.endEditBlock()
    cursor = editor.textCursor()
    cursor.setPosition(min(old_cursor_pos, len(new_markdown)))
    editor.setTextCursor(cursor)
    editor.verticalScrollBar().setValue(old_scroll)
    self._preview_edit_active = False
    self._preview_user_edit_dirty = False
    self._preview_user_edit_intent = False
def _view_has_terminal_hr(self) -> bool:
    html = self._view.toHtml()
    return bool(
        re.search(r"<hr\s*/?>\s*</body>", html, flags=re.IGNORECASE)
    )
@staticmethod
def _markdown_has_terminal_hr(text: str) -> bool:
    lines = text.split("\n")
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines:
        return False
    return lines[-1].strip() in {
        "- - -",
        "---",
        "* * *",
        "***",
        "_ _ _",
        "___",
    }
def _finish_preview_edit_session(self):
    if not self._preview_edit_active:
        return
    if self._focus_is_inside_preview():
        return
    self._preview_to_markdown_timer.stop()
    self._commit_preview_edit_to_markdown(force=True)
    self._preview_edit_active = False
    self.schedule_update()
    self.schedule_cursor_sync()
def flush_pending_preview_edits(self):
    """Force-commit pending preview edits into the bound markdown editor."""
    if self._editor is None:
        return
    self._preview_to_markdown_timer.stop()
    if not self._preview_edit_active:
        return
    self._commit_preview_edit_to_markdown(force=True)
    self._preview_edit_active = False
    self.schedule_update()
    self.schedule_cursor_sync()
def _focus_is_inside_preview(self) -> bool:
    focus = QApplication.focusWidget()
    w = focus
    while w is not None:
        if w is self._view or w is self._format_bar:
            return True
        w = w.parentWidget()
    return False
def _apply_preview_format_change(self, action: Callable[[], None]):
    if not self._allow_editing or self._structured_view_active:
        return
    self._preview_edit_active = True
    self._preview_user_edit_dirty = True
    self._preview_user_edit_intent = False
    self._preview_to_markdown_timer.stop()
    action()
    self._commit_preview_edit_to_markdown(
        force=True,
        preserve_reference_linebreaks=True,
    )
    self._refresh_preview_from_markdown_preserve_cursor()
    self._view.setFocus(Qt.FocusReason.OtherFocusReason)
def _refresh_preview_from_markdown_preserve_cursor(self):
    if self._editor is None:
        return

    state = self._capture_view_state()
    had_focus = self._view.hasFocus()

    self._apply_view_document_style()
    md = self._markdown_for_render(self._editor.get_full_text())
    self._arm_async_preview_change_suppress()
    self._suppress_preview_change = True
    try:
        if md.strip():
            self._set_markdown_or_graph_content(md)
            self._last_rendered_markdown = md
        else:
            self._set_structured_graph_state(None)
            self._view.setHtml("<p><em>Leer.</em></p>")
            self._last_rendered_markdown = None
    finally:
        self._suppress_preview_change = False
    self._apply_highlights()
    self._restore_view_state(state, restore_cursor=True)
    if had_focus:
        self._view.setFocus(Qt.FocusReason.OtherFocusReason)

__all__ = [
    "_on_preview_text_changed",
    "_commit_preview_edit_to_markdown",
    "_view_has_terminal_hr",
    "_markdown_has_terminal_hr",
    "_finish_preview_edit_session",
    "flush_pending_preview_edits",
    "_focus_is_inside_preview",
    "_apply_preview_format_change",
    "_refresh_preview_from_markdown_preserve_cursor",
]
