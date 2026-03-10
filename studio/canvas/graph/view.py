"""Canvas graph view items."""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QGraphicsRectItem, QGraphicsView, QWidget


class GraphCanvasView(QGraphicsView):
    """Pan/zoom-capable graph canvas."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._zoom_factor = 1.0

    def reset_zoom(self):
        self.resetTransform()
        self._zoom_factor = 1.0

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            if delta == 0:
                delta = event.pixelDelta().y()
            if delta > 0:
                factor = 1.12
            elif delta < 0:
                factor = 1.0 / 1.12
            else:
                factor = 1.0
            new_zoom = self._zoom_factor * factor
            new_zoom = max(0.25, min(4.5, new_zoom))
            if abs(new_zoom - self._zoom_factor) < 0.0001:
                event.accept()
                return
            factor = new_zoom / self._zoom_factor
            self.scale(factor, factor)
            self._zoom_factor = new_zoom
            event.accept()
            return
        super().wheelEvent(event)


class GraphNodeItem(QGraphicsRectItem):
    """Clickable graph node with single/double-click callbacks."""

    def __init__(
        self,
        *,
        node_id: str,
        width: float,
        height: float,
        display_text: str,
        on_click: Callable[[str, bool], None],
        on_toggle: Callable[[str], None],
        on_moved: Callable[[str, QPointF], None],
    ):
        super().__init__(0.0, 0.0, width, height)
        self._node_id = str(node_id or "")
        self._display_text = str(display_text or "")
        self._on_click = on_click
        self._on_toggle = on_toggle
        self._on_moved = on_moved
        self._move_callbacks: list[Callable[[], None]] = []
        self._press_scene_pos = QPointF()
        self._dragged = False
        self._text_color = QColor("#CDD6F4")
        self._text_font = QFont("Segoe UI", 10)
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(
            QGraphicsRectItem.GraphicsItemFlag.ItemSendsGeometryChanges,
            True,
        )
        self.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemIsSelectable, True)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_scene_pos = event.scenePos()
            self._dragged = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            delta = event.scenePos() - self._press_scene_pos
            if delta.manhattanLength() >= 3.0:
                self._dragged = True
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        was_drag = self._dragged
        super().mouseReleaseEvent(event)
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if was_drag:
            self._on_moved(self._node_id, self.center_pos())
            return
        ctrl_pressed = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        self._on_click(self._node_id, ctrl_pressed)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._on_toggle(self._node_id)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def center_pos(self) -> QPointF:
        rect = self.rect()
        return self.mapToScene(rect.center())

    def set_display_text(self, text: str):
        self._display_text = str(text or "")
        self.update()

    def set_text_color(self, color: QColor):
        if isinstance(color, QColor) and color.isValid():
            self._text_color = QColor(color)
        self.update()

    def paint(self, painter, option, widget=None):
        super().paint(painter, option, widget)
        painter.setPen(self._text_color)
        painter.setFont(self._text_font)
        text_rect = self.rect().adjusted(8.0, 6.0, -8.0, -6.0)
        painter.drawText(
            text_rect,
            int(
                Qt.AlignmentFlag.AlignLeft
                | Qt.AlignmentFlag.AlignTop
                | Qt.TextFlag.TextWordWrap
            ),
            self._display_text,
        )

    def add_move_callback(self, callback: Callable[[], None]):
        if callback is None:
            return
        self._move_callbacks.append(callback)

    def itemChange(self, change, value):
        if change == QGraphicsRectItem.GraphicsItemChange.ItemPositionHasChanged:
            for callback in list(self._move_callbacks):
                try:
                    callback()
                except Exception:
                    continue
        return super().itemChange(change, value)
