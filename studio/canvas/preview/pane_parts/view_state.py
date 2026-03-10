"""CanvasPreviewPane method implementations."""
from __future__ import annotations

from .deps import *  # noqa: F403

def _mark_view_scroll_interaction(self):
    self._view_scroll_guard_epoch = int(self._view_scroll_guard_epoch) + 1
def _on_view_scrollbar_value_changed(self, _value: int):
    if self._restoring_view_scroll:
        return
    self._mark_view_scroll_interaction()
def _wheel_scroll_delta_px(self, event) -> int:
    scrollbar = self._view.verticalScrollBar()
    angle = int(event.angleDelta().y() or 0)
    pixel = int(event.pixelDelta().y() or 0)

    # Mouse wheels usually report robust angle deltas; trackpads often
    # provide pixel deltas. Prefer the stronger signal when both exist.
    step_px = max(20, int(scrollbar.singleStep() or 20))
    lines = max(1, int(QApplication.wheelScrollLines() or 1))
    angle_px = int(round((float(angle) / 120.0) * float(step_px * lines)))
    if angle_px and pixel:
        return angle_px if abs(angle_px) >= abs(pixel) else pixel
    return angle_px or pixel
def _queue_wheel_scroll(self, delta_px: int):
    if int(delta_px) == 0:
        return
    self._pending_wheel_scroll_delta_px += int(delta_px)
    timer = self._wheel_scroll_flush_timer
    if not timer.isActive():
        timer.start(12)
def _flush_pending_wheel_scroll(self):
    pending = int(self._pending_wheel_scroll_delta_px)
    self._pending_wheel_scroll_delta_px = 0
    if pending == 0:
        return
    scrollbar = self._view.verticalScrollBar()
    target = int(scrollbar.value()) - pending
    new_value = max(
        int(scrollbar.minimum()),
        min(target, int(scrollbar.maximum())),
    )
    self._restoring_view_scroll = True
    try:
        scrollbar.setValue(new_value)
    finally:
        self._restoring_view_scroll = False
def _capture_view_state(self) -> tuple[int, int, int, int]:
    cursor = self._view.textCursor()
    scrollbar = self._view.verticalScrollBar()
    return (
        int(cursor.position()),
        int(cursor.anchor()),
        int(scrollbar.value()),
        int(scrollbar.maximum()),
    )
def _restore_view_state(
    self,
    state: tuple[int, int, int, int],
    *,
    restore_cursor: bool = False,
):
    old_pos, old_anchor, old_scroll, old_max = state

    doc = self._view.document()
    max_pos = max(0, int(doc.characterCount()) - 1)
    if restore_cursor:
        new_anchor = max(0, min(int(old_anchor), max_pos))
        new_pos = max(0, min(int(old_pos), max_pos))
        cursor = self._view.textCursor()
        cursor.setPosition(new_anchor)
        if new_pos != new_anchor:
            cursor.setPosition(new_pos, QTextCursor.MoveMode.KeepAnchor)
        self._view.setTextCursor(cursor)
    else:
        # Avoid anchor-driven auto-scroll after rerender: collapse selection
        # to the active caret position when only scroll state is preserved.
        cursor = self._view.textCursor()
        if cursor.hasSelection():
            collapsed = max(0, min(int(cursor.position()), max_pos))
            cursor.setPosition(collapsed)
            self._view.setTextCursor(cursor)

    was_at_end = bool(old_max > 0 and int(old_scroll) >= int(old_max) - 2)
    token = int(self._render_cycle_id)
    scroll_guard = int(self._view_scroll_guard_epoch)

    def apply_scroll():
        if token != self._render_cycle_id:
            return
        if scroll_guard != self._view_scroll_guard_epoch:
            return
        scrollbar = self._view.verticalScrollBar()
        new_max = int(scrollbar.maximum())
        self._restoring_view_scroll = True
        if was_at_end:
            try:
                scrollbar.setValue(new_max)
            finally:
                self._restoring_view_scroll = False
            return
        try:
            # Preserve exact pixel position by default. Ratio-based restore can
            # cause visible drift on small relayouts (e.g. tables, inline wraps).
            scrollbar.setValue(max(0, min(int(old_scroll), new_max)))
        finally:
            self._restoring_view_scroll = False

    # Apply now and repeatedly after layout settles.
    apply_scroll()
    QTimer.singleShot(0, apply_scroll)
    QTimer.singleShot(120, apply_scroll)
    QTimer.singleShot(260, apply_scroll)
def _ensure_index_maps(self):
    text = self._preview_plain_text()
    if text == self._index_map_text:
        return
    self._index_map_text = text
    py_to_qt: list[int] = [0] * (len(text) + 1)
    # Maps QTextCursor UTF-16 boundary positions -> Python string boundaries.
    # Example (BMP only): "abc" => [0, 1, 2, 3]
    # For surrogate pairs, intermediate UTF-16 boundary maps to same py index.
    qt_to_py: list[int] = [0]
    qt_pos = 0
    for py_pos, ch in enumerate(text):
        py_to_qt[py_pos] = qt_pos
        units = 2 if ord(ch) > 0xFFFF else 1
        if units == 1:
            qt_to_py.append(py_pos + 1)
        else:
            # Mid-surrogate boundary should still point to current py char.
            qt_to_py.append(py_pos)
            qt_to_py.append(py_pos + 1)
        qt_pos += units
    py_to_qt[len(text)] = qt_pos
    # Keep boundary map length aligned to qt_pos + 1.
    if len(qt_to_py) < (qt_pos + 1):
        qt_to_py.extend([len(text)] * ((qt_pos + 1) - len(qt_to_py)))
    else:
        qt_to_py[qt_pos] = len(text)
    self._py_to_qt_map = py_to_qt
    self._qt_to_py_map = qt_to_py
def _py_to_qt_pos(self, py_pos: int) -> int:
    self._ensure_index_maps()
    idx = max(0, min(int(py_pos), len(self._py_to_qt_map) - 1))
    return int(self._py_to_qt_map[idx])
def _qt_to_py_pos(self, qt_pos: int) -> int:
    self._ensure_index_maps()
    idx = max(0, min(int(qt_pos), len(self._qt_to_py_map) - 1))
    return int(self._qt_to_py_map[idx])

__all__ = [
    "_mark_view_scroll_interaction",
    "_on_view_scrollbar_value_changed",
    "_wheel_scroll_delta_px",
    "_queue_wheel_scroll",
    "_flush_pending_wheel_scroll",
    "_capture_view_state",
    "_restore_view_state",
    "_ensure_index_maps",
    "_py_to_qt_pos",
    "_qt_to_py_pos",
]
