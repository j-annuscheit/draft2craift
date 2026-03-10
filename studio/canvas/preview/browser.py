"""Preview browser widgets."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPalette, QPen, QTextFormat
from PySide6.QtWidgets import QTextBrowser


class PreviewTextBrowser(QTextBrowser):
    """Preview browser with visible quote rails for Markdown blockquotes."""

    _QUOTE_BAR_WIDTH_PX = 3
    _QUOTE_BAR_GAP_PX = 10
    _QUOTE_BAR_OFFSET_PX = 12

    def paintEvent(self, event):
        super().paintEvent(event)
        doc = self.document()
        layout = doc.documentLayout() if doc is not None else None
        if layout is None:
            return

        viewport = self.viewport()
        vp_rect = viewport.rect()
        v_scroll = int(self.verticalScrollBar().value())
        h_scroll = int(self.horizontalScrollBar().value())

        color = self.palette().color(QPalette.ColorRole.Mid)
        if not color.isValid():
            color = QColor("#7A7A7A")
        color.setAlpha(210)

        painter = QPainter(viewport)
        pen = QPen(color)
        pen.setWidth(self._QUOTE_BAR_WIDTH_PX)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)

        block = doc.firstBlock()
        while block.isValid():
            block_format = block.blockFormat()
            level = int(block_format.property(QTextFormat.Property.BlockQuoteLevel) or 0)
            if level > 0:
                rect = layout.blockBoundingRect(block)
                top = float(rect.top()) - float(v_scroll)
                bottom = top + float(rect.height())
                if (
                    bottom >= float(vp_rect.top()) - 2.0
                    and top <= float(vp_rect.bottom()) + 2.0
                    and (bottom - top) >= 2.0
                ):
                    y1 = int(round(top + 1.0))
                    y2 = int(round(bottom - 1.0))
                    for idx in range(level):
                        x = (
                            float(rect.left())
                            - float(h_scroll)
                            + float(self._QUOTE_BAR_OFFSET_PX)
                            + float(idx * self._QUOTE_BAR_GAP_PX)
                        )
                        xi = int(round(x))
                        painter.drawLine(xi, y1, xi, y2)
            block = block.next()
