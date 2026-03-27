"""CanvasPreviewPane method implementations."""
from __future__ import annotations

from .deps import *  # noqa: F403

def bind_editor(self, editor: Any | None):
    """Attach to the active Markdown editor and rewire preview signals."""
    if self._editor is editor:
        self.schedule_update()
        self.schedule_cursor_sync()
        return

    old = self._editor
    if old is not None:
        try:
            old.textChanged.disconnect(self.schedule_update)
        except Exception:
            pass
        try:
            old.textChanged.disconnect(self._schedule_highlight_sync)
        except Exception:
            pass
        try:
            old.cursorPositionChanged.disconnect(self.schedule_cursor_sync)
        except Exception:
            pass

    self._editor = editor
    self._last_rendered_markdown = None
    self._preview_edit_active = False
    self._preview_user_edit_dirty = False
    self._preview_user_edit_intent = False
    self._preview_to_markdown_timer.stop()

    if editor is not None:
        editor.textChanged.connect(self.schedule_update)
        editor.textChanged.connect(self._schedule_highlight_sync)
        if self._sync_cursor_with_editor:
            editor.cursorPositionChanged.connect(self.schedule_cursor_sync)

    self.schedule_update()
    self.schedule_cursor_sync()
def configure_highlights(
    self,
    *,
    scope: str,
    tab_name_getter: Callable[[], str] | None = None,
    tab_switcher: Callable[[str], bool] | None = None,
):
    """Set highlight scope + dynamic tab-title provider for this pane."""
    self._highlight_scope = str(scope or "").strip().lower() or "generic"
    self._tab_name_getter = tab_name_getter
    self._tab_switcher = tab_switcher
    self.schedule_update()


def set_link_tooltips(self, mapping: dict[str, str] | None):
    clean: dict[str, str] = {}
    for raw_href, raw_tip in dict(mapping or {}).items():
        href = str(raw_href or "").strip()
        if not href:
            continue
        tip = str(raw_tip or "").strip()
        if not tip:
            continue
        clean[href] = tip
    self._link_tooltips = clean


def clear_link_tooltips(self):
    self._link_tooltips = {}
def set_enabled(self, enabled: bool):
    self.setVisible(bool(enabled))
    if not enabled:
        self._preview_to_markdown_timer.stop()
        self._preview_edit_active = False
        self._preview_user_edit_dirty = False
        self._preview_user_edit_intent = False
    if enabled:
        self.schedule_update()
        self.schedule_cursor_sync()
def showEvent(self, event):
    QWidget.showEvent(self, event)
    # Initial preview update can be skipped while the widget is hidden.
    # Ensure content is rendered once the pane becomes visible.
    self.schedule_update()
    self.schedule_cursor_sync()
def set_allow_editing(self, allow_editing: bool):
    allow = bool(allow_editing)
    if allow == self._allow_editing:
        return
    if not allow:
        self._preview_to_markdown_timer.stop()
        self._preview_edit_active = False
        self._preview_user_edit_dirty = False
        self._preview_user_edit_intent = False
    self._allow_editing = allow
    self._sync_preview_interaction_mode()
def request_preserve_view_state(self):
    self._preserve_view_state_once = True
    self._cursor_timer.stop()
def invalidate_render_cache(self):
    self._last_rendered_markdown = None
def preview_zoom_percent(self) -> int:
    return self._zoom_percent
def set_preview_zoom_percent(self, percent: int) -> bool:
    clamped = max(self._ZOOM_MIN, min(self._ZOOM_MAX, int(percent)))
    if clamped == self._zoom_percent:
        return False
    self._zoom_percent = clamped
    self._apply_title_style()
    self._apply_view_document_style()
    # Keep visible spacing/code metrics in sync immediately on zoom change.
    self._apply_block_spacing_overrides()
    self._apply_code_typography_overrides()
    self.schedule_update()
    return True
def increase_preview_text_size(self) -> bool:
    target = self._zoom_percent + self._ZOOM_STEP
    return self.set_preview_zoom_percent(target)
def decrease_preview_text_size(self) -> bool:
    target = self._zoom_percent - self._ZOOM_STEP
    return self.set_preview_zoom_percent(target)
def reset_preview_text_size(self) -> bool:
    return self.set_preview_zoom_percent(100)
def is_preview_widget(self, widget: QWidget | None) -> bool:
    w = widget
    while w is not None:
        if w is self._view or w is self._graph_view:
            return True
        w = w.parentWidget()
    return False
def get_selected_text(self) -> str:
    if self._structured_view_active:
        return ""
    cursor = self._view.textCursor()
    if not cursor.hasSelection():
        return ""
    return (cursor.selectedText() or "").replace("\u2029", "\n").replace(
        "\r\n",
        "\n",
    )
def connect_copy_available(self, slot) -> bool:
    """Connect slot(bool) to preview selection availability changes."""
    try:
        self._view.copyAvailable.connect(slot)
        return True
    except Exception:
        return False
def disconnect_copy_available(self, slot) -> bool:
    """Disconnect slot(bool) from preview selection availability."""
    try:
        self._view.copyAvailable.disconnect(slot)
        return True
    except Exception:
        return False

__all__ = [
    "bind_editor",
    "configure_highlights",
    "set_link_tooltips",
    "clear_link_tooltips",
    "set_enabled",
    "showEvent",
    "set_allow_editing",
    "request_preserve_view_state",
    "invalidate_render_cache",
    "preview_zoom_percent",
    "set_preview_zoom_percent",
    "increase_preview_text_size",
    "decrease_preview_text_size",
    "reset_preview_text_size",
    "is_preview_widget",
    "get_selected_text",
    "connect_copy_available",
    "disconnect_copy_available",
]
