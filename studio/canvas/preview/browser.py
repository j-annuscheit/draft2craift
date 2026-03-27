"""Preview browser widgets."""
from __future__ import annotations

from PySide6.QtCore import Qt, QRectF
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

        code_runs: list[tuple[QRectF, QColor]] = []
        block = doc.firstBlock()
        run_rect: QRectF | None = None
        run_fill = QColor()
        while block.isValid():
            block_format = block.blockFormat()
            has_code_fence = bool(
                str(
                    block_format.stringProperty(int(QTextFormat.Property.BlockCodeFence))
                    or ""
                ).strip()
            )
            if has_code_fence:
                rect = layout.blockBoundingRect(block)
                if run_rect is None:
                    run_rect = QRectF(rect)
                    run_fill = block_format.background().color()
                else:
                    run_rect = run_rect.united(rect)
            elif run_rect is not None:
                code_runs.append((QRectF(run_rect), QColor(run_fill)))
                run_rect = None
                run_fill = QColor()
            block = block.next()
        if run_rect is not None:
            code_runs.append((QRectF(run_rect), QColor(run_fill)))

        painter = QPainter(viewport)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        code_border = self.palette().color(QPalette.ColorRole.Mid)
        if not code_border.isValid():
            code_border = QColor("#7A7A7A")
        code_border.setAlpha(220)

        code_view_rects: list[tuple[QRectF, QColor]] = []
        for raw_rect, raw_fill in code_runs:
            top = float(raw_rect.top()) - float(v_scroll)
            left = float(raw_rect.left()) - float(h_scroll)
            draw_rect = QRectF(
                left - 2.0,
                top,
                max(1.0, float(raw_rect.width()) + 4.0),
                max(1.0, float(raw_rect.height())),
            )
            if (
                draw_rect.bottom() < float(vp_rect.top()) - 2.0
                or draw_rect.top() > float(vp_rect.bottom()) + 2.0
            ):
                continue
            fill = QColor(raw_fill)
            if (not fill.isValid()) or fill.alpha() <= 0:
                fill = self.palette().color(QPalette.ColorRole.AlternateBase)
            if (not fill.isValid()) or fill.alpha() <= 0:
                fill = QColor("#1E1E2E")
            code_view_rects.append((draw_rect, fill))

        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationOver)
        painter.setPen(Qt.PenStyle.NoPen)
        for rect, fill in code_view_rects:
            painter.setBrush(fill)
            painter.drawRoundedRect(rect, 4.0, 4.0)

        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        box_pen = QPen(code_border)
        box_pen.setWidth(1)
        painter.setPen(box_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for rect, _fill in code_view_rects:
            painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), 4.0, 4.0)

        hr_color = QColor(str(self.property("_hr_color") or "").strip())
        if not hr_color.isValid():
            hr_color = self.palette().color(QPalette.ColorRole.Mid)
        if not hr_color.isValid():
            hr_color = QColor("#7A7A7A")
        hr_color.setAlpha(230)
        hr_pen = QPen(hr_color)
        hr_pen.setWidth(1)
        painter.setPen(hr_pen)
        block = doc.firstBlock()
        while block.isValid():
            block_format = block.blockFormat()
            has_hr = bool(
                block_format.hasProperty(
                    int(QTextFormat.Property.BlockTrailingHorizontalRulerWidth)
                )
            )
            if has_hr:
                rect = layout.blockBoundingRect(block)
                top = float(rect.top()) - float(v_scroll)
                bottom = top + float(rect.height())
                if (
                    bottom >= float(vp_rect.top()) - 2.0
                    and top <= float(vp_rect.bottom()) + 2.0
                    and (bottom - top) >= 1.0
                ):
                    y = int(round(top + (float(rect.height()) * 0.5)))
                    x1 = int(round(float(rect.left()) - float(h_scroll) + 2.0))
                    x2 = int(round(float(rect.right()) - float(h_scroll) - 2.0))
                    if x2 > x1:
                        painter.drawLine(x1, y, x2, y)
            block = block.next()

        quote_color = QColor(str(self.property("_quote_border_color") or "").strip())
        if not quote_color.isValid():
            quote_color = self.palette().color(QPalette.ColorRole.Mid)
        if not quote_color.isValid():
            quote_color = QColor("#7A7A7A")
        quote_color.setAlpha(210)
        pen = QPen(quote_color)
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
