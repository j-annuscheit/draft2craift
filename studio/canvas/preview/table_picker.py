"""Table insertion picker widgets for preview toolbar."""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPalette
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class TableSizeGrid(QWidget):
    """Interactive table-size picker grid."""

    hovered_size_changed = Signal(int, int)
    size_chosen = Signal(int, int)

    def __init__(
        self,
        *,
        max_rows: int = 10,
        max_cols: int = 10,
        cell_px: int = 18,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._max_rows = max(1, int(max_rows))
        self._max_cols = max(1, int(max_cols))
        self._cell_px = max(10, int(cell_px))
        self._hover_rows = 0
        self._hover_cols = 0
        self.setMouseTracking(True)
        self.setFixedSize(
            int(self._max_cols * self._cell_px),
            int(self._max_rows * self._cell_px),
        )
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def _cell_at(self, pos: QPoint) -> tuple[int, int]:
        x = int(pos.x())
        y = int(pos.y())
        if x < 0 or y < 0:
            return 0, 0
        col = (x // self._cell_px) + 1
        row = (y // self._cell_px) + 1
        if row < 1 or col < 1:
            return 0, 0
        if row > self._max_rows or col > self._max_cols:
            return 0, 0
        return int(row), int(col)

    def _set_hover(self, rows: int, cols: int):
        rows = max(0, int(rows))
        cols = max(0, int(cols))
        if rows == self._hover_rows and cols == self._hover_cols:
            return
        self._hover_rows = rows
        self._hover_cols = cols
        self.hovered_size_changed.emit(rows, cols)
        self.update()

    def leaveEvent(self, event):
        self._set_hover(0, 0)
        super().leaveEvent(event)

    def mouseMoveEvent(self, event):
        row, col = self._cell_at(event.position().toPoint())
        self._set_hover(row, col)
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            row, col = self._cell_at(event.position().toPoint())
            if row > 0 and col > 0:
                self.size_chosen.emit(row, col)
                event.accept()
                return
        super().mousePressEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        base = self.palette().color(QPalette.ColorRole.Base)
        border = self.palette().color(QPalette.ColorRole.Mid)
        active = self.palette().color(QPalette.ColorRole.Highlight)
        active_bg = QColor(active)
        active_bg.setAlpha(125)
        painter.fillRect(self.rect(), base)
        for row in range(self._max_rows):
            for col in range(self._max_cols):
                x = int(col * self._cell_px)
                y = int(row * self._cell_px)
                rect = QRect(
                    x,
                    y,
                    int(self._cell_px - 1),
                    int(self._cell_px - 1),
                )
                if (row + 1) <= self._hover_rows and (col + 1) <= self._hover_cols:
                    painter.fillRect(rect, active_bg)
                painter.setPen(border)
                painter.drawRect(rect)


class TableInsertPicker(QWidget):
    """Word-like table picker with hover size preview."""

    size_chosen = Signal(int, int)

    def __init__(
        self,
        *,
        max_rows: int = 10,
        max_cols: int = 10,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        self._label = QLabel("Tabelle einfügen: 0 x 0")
        self._label.setStyleSheet("font-size: 11px; color: palette(text);")
        layout.addWidget(self._label)

        self._grid = TableSizeGrid(
            max_rows=max_rows,
            max_cols=max_cols,
            parent=self,
        )
        self._grid.hovered_size_changed.connect(self._on_hovered_size_changed)
        self._grid.size_chosen.connect(self.size_chosen.emit)
        layout.addWidget(self._grid)

    def _on_hovered_size_changed(self, rows: int, cols: int):
        if rows <= 0 or cols <= 0:
            self._label.setText("Tabelle einfügen: 0 x 0")
            return
        self._label.setText(f"Tabelle einfügen: {rows} x {cols}")
