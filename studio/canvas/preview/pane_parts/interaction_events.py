"""CanvasPreviewPane method implementations."""
from __future__ import annotations

from .deps import *  # noqa: F403

def eventFilter(self, watched, event):
    is_preview_target = watched in (self._view, self._view.viewport())
    if is_preview_target and event.type() == QEvent.Type.ContextMenu:
        self._open_highlight_context_menu(event.globalPos())
        event.accept()
        return True
    if (
        is_preview_target
        and event.type() == QEvent.Type.KeyPress
        and event.matches(QKeySequence.StandardKey.Copy)
    ):
        if self._copy_selection_to_clipboard():
            event.accept()
            return True
    if (
        self._allow_editing
        and not self._structured_view_active
        and is_preview_target
        and event.type() == QEvent.Type.KeyPress
        and self._is_preview_content_edit_keypress(event)
    ):
        self._preview_user_edit_intent = True
    if (
        self._allow_editing
        and not self._structured_view_active
        and is_preview_target
        and event.type() in (QEvent.Type.InputMethod, QEvent.Type.Drop)
    ):
        self._preview_user_edit_intent = True
    if is_preview_target and event.type() == QEvent.Type.Wheel:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            if delta == 0:
                delta = event.pixelDelta().y()
            if delta > 0:
                self.increase_preview_text_size()
            elif delta < 0:
                self.decrease_preview_text_size()
            event.accept()
            return True
        # Keep wheel scrolling responsive on complex HTML layouts
        # (e.g. large tables) and stop delayed restore timers from
        # snapping the view back while the user scrolls.
        self._mark_view_scroll_interaction()
        delta = self._wheel_scroll_delta_px(event)
        if delta:
            self._queue_wheel_scroll(int(delta))
            event.accept()
            return True
    if is_preview_target and event.type() == QEvent.Type.MouseMove:
        self._update_hover_tooltip(event.globalPosition().toPoint())
    if (
        is_preview_target
        and event.type() == QEvent.Type.MouseButtonRelease
        and event.button() == Qt.MouseButton.LeftButton
    ):
        if self._handle_preview_link_click(event.globalPosition().toPoint()):
            event.accept()
            return True
        if self._handle_highlight_click(event.globalPosition().toPoint()):
            event.accept()
            return True
    if is_preview_target and event.type() == QEvent.Type.Leave:
        QToolTip.hideText()
        self._hovered_highlight_id = ""
    if (
        self._allow_editing
        and not self._structured_view_active
        and is_preview_target
        and event.type() == QEvent.Type.KeyPress
    ):
        if event.key() == Qt.Key.Key_Tab:
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self._outdent_list_item()
            else:
                self._indent_list_item()
            event.accept()
            return True
    if (
        self._allow_editing
        and is_preview_target
        and event.type() == QEvent.Type.FocusOut
    ):
        QTimer.singleShot(0, self._finish_preview_edit_session)
    return QWidget.eventFilter(self, watched, event)
def _handle_preview_link_click(self, global_pos: QPoint) -> bool:
    vp_pos = self._view.viewport().mapFromGlobal(global_pos)
    href = str(self._view.anchorAt(vp_pos) or "").strip()
    if not href:
        return False

    if href.startswith("d2c://graph/"):
        return self._handle_graph_action_link(href)

    # External / file links are handled manually because openLinks=False.
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", href):
        return bool(QDesktopServices.openUrl(QUrl(href)))
    if href.startswith("/"):
        return bool(QDesktopServices.openUrl(QUrl.fromLocalFile(href)))
    return False
def _handle_graph_action_link(self, href: str) -> bool:
    spec = self._structured_graph_spec
    if spec is None:
        return False

    parsed = urlparse(href)
    if parsed.scheme != "d2c" or parsed.netloc != "graph":
        return False

    action = str(parsed.path or "").strip("/").lower()
    query = parse_qs(parsed.query)
    node_id = str((query.get("id") or [""])[0] or "").strip()
    changed = False

    if action == "toggle":
        node = spec.nodes.get(node_id)
        if node is None or not node.children:
            return False
        if node_id in self._graph_collapsed_ids:
            self._graph_collapsed_ids.discard(node_id)
        else:
            self._graph_collapsed_ids.add(node_id)
        changed = True
    elif action == "focus":
        if node_id in spec.nodes and self._graph_focus_node_id != node_id:
            self._graph_focus_node_id = node_id
            changed = True
    elif action == "clear_focus":
        if self._graph_focus_node_id:
            self._graph_focus_node_id = ""
            changed = True
    elif action == "expand_all":
        if self._graph_collapsed_ids:
            self._graph_collapsed_ids.clear()
            changed = True
    elif action == "collapse_all":
        target = {
            node.node_id
            for node in spec.nodes.values()
            if node.children
        }
        if target != self._graph_collapsed_ids:
            self._graph_collapsed_ids = target
            changed = True
    else:
        return False

    if not changed:
        return True
    self.request_preserve_view_state()
    self._last_rendered_markdown = None
    self.schedule_update()
    return True

__all__ = [
    "eventFilter",
    "_handle_preview_link_click",
    "_handle_graph_action_link",
]
