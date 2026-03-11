from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, QRect, QSize, Signal
from PySide6.QtGui import QColor, QCursor, QImage, QPainter, QPalette, QPen, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from shared.services.importer.models import PDFImportSettings
from .pdf_viewer_overlay import (
    _HeadingAnchor,
    _collect_page_lines,
    _extract_global_heading_anchors,
    _extract_page_overlay_rects,
    _find_heading_rects_on_page,
)

class PDFPageView(QWidget):
    """
    Renders a single PDF page (via fitz) with interactive overlays.

    Overlays (each toggleable)
    --------------------------
    • Blue semi-transparent bands  – header / footer scan zones
    • Orange outlines              – text blocks inside the H/F zones
    • Coloured outlines            – heading spans (H1 green, H2 blue, H3 mauve)

    The two zone boundary lines are draggable: drag them to adjust
    hf_top_zone / hf_bottom_zone.  Emits ``zone_changed(top, bottom)``
    (both as fractions 0–1) on mouse release.
    """

    zone_changed = Signal(float, float)   # (top_zone_fraction, bottom_zone_fraction)

    _SNAP       = 8      # px – drag activation distance
    _ZONE_FILL  = QColor(100, 149, 237,  45)
    _ZONE_LINE  = QColor(100, 149, 237, 220)
    _HF_PEN_COL = QColor(255, 165,   0, 200)
    _HDG_COLORS = [
        QColor(166, 227, 161, 200),   # H1 – green
        QColor(137, 180, 250, 200),   # H2 – blue
        QColor(203, 166, 247, 200),   # H3 – mauve
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._doc        = None   # fitz.Document
        self._path       = ""
        self._page_idx   = 0
        self._zoom       = 1.0
        self._pixmap: Optional[QPixmap] = None
        self._page_w_pts = 595.0
        self._page_h_pts = 842.0

        # Zone fractions (0–1)
        self._hf_top    = 0.10
        self._hf_bottom = 0.10

        # Overlay data stored as PDF-point coordinates
        self._hf_top_rects:    list = []
        self._hf_bottom_rects: list = []
        self._heading_rects:   list = []   # (x0,y0,x1,y1,level)

        # Overlay visibility flags
        self.show_zones    = True
        self.show_hf       = True
        self.show_headings = True

        # Drag state
        self._drag_which: Optional[str] = None   # "top" | "bottom" | None
        self._allow_zone_drag = True

        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    # ── Public API ─────────────────────────────────────────────────────────

    def load_page(self, path: str, page_idx: int,
                  settings: PDFImportSettings, body_size: float = 0.0,
                  md_headings: Optional[list[_HeadingAnchor]] = None):
        """Render a PDF page and extract overlay data."""
        try:
            import fitz  # type: ignore
        except ImportError:
            self._pixmap = None
            self.update()
            return

        # Re-open document if path changed
        if path != self._path or self._doc is None:
            if self._doc is not None:
                try:
                    self._doc.close()
                except Exception:
                    pass
                self._doc = None
            try:
                self._doc = fitz.open(path)
            except Exception:
                self._doc = None
                self._pixmap = None
                self.update()
                return
            self._path = path

        if self._doc is None or page_idx >= len(self._doc):
            return
        self._page_idx = page_idx

        page = self._doc[page_idx]
        self._page_w_pts = page.rect.width
        self._page_h_pts = page.rect.height

        # Render page to QPixmap
        mat = fitz.Matrix(self._zoom, self._zoom)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        img = QImage(pix.samples, pix.width, pix.height,
                     pix.stride, QImage.Format.Format_RGB888)
        self._pixmap = QPixmap.fromImage(img)

        # Zone fractions from current mode/settings.
        self._allow_zone_drag = not settings.auto_hf_detect
        if settings.auto_hf_detect:
            has_detect_data = (
                bool(settings.detected_top_by_page)
                or bool(settings.detected_bottom_by_page)
                or bool(settings.detected_hf_rects_by_page)
            )
            top_pt = float(settings.detected_top_by_page.get(page_idx, 0.0))
            bottom_pt = float(settings.detected_bottom_by_page.get(page_idx, 0.0))
            if has_detect_data and self._page_h_pts > 0:
                self._hf_top = max(0.0, min(0.49, top_pt / self._page_h_pts))
                self._hf_bottom = max(0.0, min(0.49, bottom_pt / self._page_h_pts))
            else:
                self._hf_top = settings.hf_top_zone
                self._hf_bottom = settings.hf_bottom_zone
        else:
            self._hf_top = settings.hf_top_zone
            self._hf_bottom = settings.hf_bottom_zone

        # Extract overlay block data
        (self._hf_top_rects,
         self._hf_bottom_rects,
         self._heading_rects) = _extract_page_overlay_rects(
            page,
            settings,
            page_idx=page_idx,
            top_zone=self._hf_top,
            bottom_zone=self._hf_bottom,
            body_size=body_size,
        )

        # If we have markdown-derived headings for this page, prefer them.
        # This keeps the viewer overlay in sync with what actually became "#/##/###" in the Markdown output.
        if md_headings:
            try:
                h = page.rect.height or 1.0
                top_limit = h * self._hf_top
                bottom_limit = h * (1.0 - self._hf_bottom)
                page_lines = _collect_page_lines(page, top_limit, bottom_limit)

                heading_rects: list = []
                seen_rects: set[tuple[float, float, float, float, int]] = set()
                for anchor in md_headings:
                    level = min(anchor.level, 3)
                    rects = _find_heading_rects_on_page(anchor, page_lines)
                    for x0, y0, x1, y1 in rects[:6]:
                        key = (round(x0, 1), round(y0, 1), round(x1, 1), round(y1, 1), level)
                        if key in seen_rects:
                            continue
                        seen_rects.add(key)
                        heading_rects.append((x0, y0, x1, y1, level))
                if heading_rects:
                    self._heading_rects = heading_rects
            except Exception:
                # Fallback silently to detector-based overlays
                pass

        self.setFixedSize(self._pixmap.size())
        self.update()

    def set_zones(self, top: float, bottom: float):
        """Update zone fractions without full re-render (called from spinboxes)."""
        if not self._allow_zone_drag:
            return
        self._hf_top    = top
        self._hf_bottom = bottom
        self.update()

    def set_body_size(self, body_size: float, settings: PDFImportSettings):
        """Re-extract heading overlays after font analysis result arrives."""
        if self._doc is None or self._page_idx >= len(self._doc):
            return
        self.load_page(
            self._path,
            self._page_idx,
            settings,
            body_size,
            None,
        )

    def set_zoom(self, zoom: float, path: str, page_idx: int,
                 settings: PDFImportSettings, body_size: float = 0.0,
                 md_headings: Optional[list[_HeadingAnchor]] = None):
        self._zoom = max(0.25, min(4.0, zoom))
        self.load_page(path, page_idx, settings, body_size, md_headings)

    def page_count(self) -> int:
        return len(self._doc) if self._doc else 0

    def close_doc(self):
        if self._doc is not None:
            try:
                self._doc.close()
            except Exception:
                pass
            self._doc = None
        self._pixmap = None

    # ── Drawing ────────────────────────────────────────────────────────────

    def paintEvent(self, event):
        p = QPainter(self)
        if self._pixmap is None:
            palette = self.palette()
            p.fillRect(self.rect(), palette.color(QPalette.ColorRole.Base))
            p.setPen(palette.color(QPalette.ColorRole.PlaceholderText))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No PDF loaded")
            return

        p.drawPixmap(0, 0, self._pixmap)

        W = self._pixmap.width()
        H = self._pixmap.height()

        def px(x, y):
            return int(x * self._zoom), int(y * self._zoom)

        has_visible_zone = (self._hf_top > 0.0005) or (self._hf_bottom > 0.0005)
        if self.show_zones and has_visible_zone:
            top_y    = int(H * self._hf_top)
            bottom_y = int(H * (1.0 - self._hf_bottom))
            # Tinted bands
            p.fillRect(QRect(0, 0, W, top_y),               self._ZONE_FILL)
            p.fillRect(QRect(0, bottom_y, W, H - bottom_y), self._ZONE_FILL)
            # Boundary lines
            pen = QPen(self._ZONE_LINE, 2, Qt.PenStyle.DashLine)
            p.setPen(pen)
            p.drawLine(0, top_y,    W, top_y)
            p.drawLine(0, bottom_y, W, bottom_y)

        if self.show_hf:
            pen = QPen(self._HF_PEN_COL, 2)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            for (x0, y0, x1, y1) in self._hf_top_rects + self._hf_bottom_rects:
                rx, ry = px(x0, y0); rw, rh = px(x1 - x0, y1 - y0)
                p.drawRect(QRect(rx, ry, rw, rh))

        if self.show_headings:
            p.setBrush(Qt.BrushStyle.NoBrush)
            for item in self._heading_rects:
                x0, y0, x1, y1, level = item
                color = self._HDG_COLORS[min(level - 1, 2)]
                p.setPen(QPen(color, 2))
                rx, ry = px(x0, y0); rw, rh = px(x1 - x0, y1 - y0)
                p.drawRect(QRect(rx, ry, rw, rh))

    # ── Mouse interaction (drag zone lines) ────────────────────────────────

    def _zone_y(self, which: str) -> int:
        H = self._pixmap.height() if self._pixmap else 0
        return int(H * self._hf_top) if which == "top" else int(H * (1.0 - self._hf_bottom))

    def mousePressEvent(self, event):
        if (not self._allow_zone_drag
                or event.button() != Qt.MouseButton.LeftButton
                or self._pixmap is None):
            return
        y = event.position().y()
        for which in ("top", "bottom"):
            if abs(y - self._zone_y(which)) <= self._SNAP:
                self._drag_which = which
                return

    def mouseMoveEvent(self, event):
        if self._pixmap is None:
            return
        if not self._allow_zone_drag:
            self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
            return
        H   = self._pixmap.height()
        y   = event.position().y()
        near = any(abs(y - self._zone_y(w)) <= self._SNAP for w in ("top", "bottom"))
        self.setCursor(QCursor(
            Qt.CursorShape.SizeVerCursor if (near or self._drag_which)
            else Qt.CursorShape.ArrowCursor
        ))
        if self._drag_which is None:
            return
        frac = max(0.01, min(0.49, y / H))
        if self._drag_which == "top":
            self._hf_top = frac
        else:
            self._hf_bottom = max(0.01, min(0.49, 1.0 - frac))
        self.update()

    def mouseReleaseEvent(self, event):
        if (self._allow_zone_drag
                and event.button() == Qt.MouseButton.LeftButton
                and self._drag_which is not None):
            self.zone_changed.emit(self._hf_top, self._hf_bottom)
            self._drag_which = None


class PDFViewerPanel(QWidget):
    """
    Wraps PDFPageView in a scroll area with page navigation, zoom controls,
    and overlay-toggle checkboxes.
    """

    zone_changed = Signal(float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._path       = ""
        self._page_idx   = 0
        self._body_size  = 0.0
        self._settings: Optional[PDFImportSettings] = None
        self._heading_anchors: list[_HeadingAnchor] = []
        self._setup_ui()

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)

        # ── Navigation / zoom toolbar ─────────────────────────────────────
        bar = QHBoxLayout()
        bar.setSpacing(4)

        self._btn_prev = QPushButton("◄")
        self._btn_prev.setProperty("toolbarButton", True)
        self._btn_prev.setFixedSize(34, 28)
        self._btn_prev.setToolTip("Previous page")
        self._btn_prev.clicked.connect(self._prev_page)
        bar.addWidget(self._btn_prev)

        self._page_lbl = QLabel("–")
        self._page_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._page_lbl.setMinimumWidth(60)
        bar.addWidget(self._page_lbl)

        self._btn_next = QPushButton("►")
        self._btn_next.setProperty("toolbarButton", True)
        self._btn_next.setFixedSize(34, 28)
        self._btn_next.setToolTip("Next page")
        self._btn_next.clicked.connect(self._next_page)
        bar.addWidget(self._btn_next)

        bar.addSpacing(8)

        self._btn_zoom_in = QPushButton("+")
        self._btn_zoom_in.setProperty("toolbarButton", True)
        self._btn_zoom_in.setFixedSize(32, 28)
        self._btn_zoom_in.setToolTip("Zoom in")
        self._btn_zoom_in.clicked.connect(self._zoom_in)
        bar.addWidget(self._btn_zoom_in)

        self._btn_zoom_out = QPushButton("-")
        self._btn_zoom_out.setProperty("toolbarButton", True)
        self._btn_zoom_out.setFixedSize(32, 28)
        self._btn_zoom_out.setToolTip("Zoom out")
        self._btn_zoom_out.clicked.connect(self._zoom_out)
        bar.addWidget(self._btn_zoom_out)

        self._btn_fit = QPushButton("Fit")
        self._btn_fit.setProperty("toolbarButton", True)
        self._btn_fit.setFixedSize(42, 28)
        self._btn_fit.setToolTip("Fit page to view")
        self._btn_fit.clicked.connect(self._zoom_fit)
        bar.addWidget(self._btn_fit)

        bar.addSpacing(12)

        self._chk_zones    = QCheckBox("Zones")
        self._chk_hf       = QCheckBox("H/F")
        self._chk_headings = QCheckBox("Headings")
        for chk in (self._chk_zones, self._chk_hf, self._chk_headings):
            chk.setChecked(True)
            chk.toggled.connect(self._update_overlays)
            bar.addWidget(chk)

        bar.addStretch()
        root.addLayout(bar)

        # ── Scroll area with page view ────────────────────────────────────
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(False)
        self._scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._scroll.setStyleSheet("QScrollArea { border: none; background: palette(base); }")

        self._page_view = PDFPageView()
        self._page_view.zone_changed.connect(self.zone_changed)
        self._scroll.setWidget(self._page_view)
        root.addWidget(self._scroll, stretch=1)

    # ── Public API ─────────────────────────────────────────────────────────

    def _headings_for_page(self, page_idx: int) -> Optional[list[_HeadingAnchor]]:
        return self._heading_anchors or None

    def load_pdf(
        self,
        path: str,
        settings: PDFImportSettings,
        body_size: float = 0.0,
        markdown: Optional[str] = None,
    ):
        self._path      = path
        self._settings  = settings
        self._body_size = body_size
        self._page_idx  = 0
        if markdown is not None:
            self._heading_anchors = _extract_global_heading_anchors(markdown)
        self._page_view.load_page(path, 0, settings, body_size,
                                  self._headings_for_page(0))
        self._update_nav()

    def refresh_settings(
        self,
        settings: PDFImportSettings,
        body_size: float = 0.0,
        markdown: Optional[str] = None,
    ):
        """Refresh current page using updated settings without resetting page index."""
        self._settings = settings
        self._body_size = body_size
        if markdown is not None:
            self._heading_anchors = _extract_global_heading_anchors(markdown)
        if self._path:
            n = self._page_view.page_count()
            if n > 0:
                self._page_idx = max(0, min(self._page_idx, n - 1))
            else:
                self._page_idx = 0
            self._page_view.load_page(
                self._path,
                self._page_idx,
                settings,
                body_size,
                self._headings_for_page(self._page_idx),
            )
            self._update_nav()

    def update_markdown(self, markdown: str):
        """Refresh markdown-derived heading overlays without resetting the current page."""
        self._heading_anchors = _extract_global_heading_anchors(markdown)
        if self._settings and self._path:
            self._page_view.load_page(
                self._path,
                self._page_idx,
                self._settings,
                self._body_size,
                self._headings_for_page(self._page_idx),
            )
            self._update_nav()

    def update_zones(self, top: float, bottom: float):
        """Called when settings spinboxes change; avoids full re-render."""
        if self._settings is not None:
            if self._settings.auto_hf_detect:
                return
            self._settings.hf_top_zone    = top
            self._settings.hf_bottom_zone = bottom
        self._page_view.set_zones(top, bottom)

    def update_body_size(self, body_size: float, settings: PDFImportSettings):
        """Called after font analysis; re-extracts heading overlays."""
        self._body_size = body_size
        self._settings  = settings
        if self._path:
            self._page_view.load_page(
                self._path,
                self._page_idx,
                settings,
                body_size,
                self._headings_for_page(self._page_idx),
            )
            self._update_nav()

    def clear(self):
        self._page_view.close_doc()
        self._path = ""
        self._settings = None
        self._heading_anchors = []
        self._page_lbl.setText("–")
        self._page_view.setFixedSize(QSize(1, 1))
        self._page_view.update()

    # ── Navigation ─────────────────────────────────────────────────────────

    def _prev_page(self):
        if self._page_idx > 0 and self._settings and self._path:
            self._page_idx -= 1
            self._page_view.load_page(self._path, self._page_idx,
                                      self._settings, self._body_size,
                                      self._headings_for_page(self._page_idx))
            self._update_nav()

    def _next_page(self):
        n = self._page_view.page_count()
        if self._settings and self._path and self._page_idx < n - 1:
            self._page_idx += 1
            self._page_view.load_page(self._path, self._page_idx,
                                      self._settings, self._body_size,
                                      self._headings_for_page(self._page_idx))
            self._update_nav()

    def _update_nav(self):
        n = self._page_view.page_count()
        self._page_lbl.setText(f"{self._page_idx + 1} / {n}" if n else "–")
        self._btn_prev.setEnabled(self._page_idx > 0)
        self._btn_next.setEnabled(self._page_idx < n - 1)

    # ── Zoom ───────────────────────────────────────────────────────────────

    def _zoom_in(self):
        if self._settings and self._path:
            self._page_view.set_zoom(
                self._page_view._zoom * 1.25,
                self._path, self._page_idx, self._settings, self._body_size,
                self._headings_for_page(self._page_idx),
            )

    def _zoom_out(self):
        if self._settings and self._path:
            self._page_view.set_zoom(
                self._page_view._zoom / 1.25,
                self._path, self._page_idx, self._settings, self._body_size,
                self._headings_for_page(self._page_idx),
            )

    def _zoom_fit(self):
        if not (self._settings and self._path):
            return
        vp_w = self._scroll.viewport().width()  - 4
        vp_h = self._scroll.viewport().height() - 4
        pw   = self._page_view._page_w_pts
        ph   = self._page_view._page_h_pts
        if pw > 0 and ph > 0:
            zoom = min(vp_w / pw, vp_h / ph)
            self._page_view.set_zoom(zoom, self._path, self._page_idx,
                                     self._settings, self._body_size,
                                     self._headings_for_page(self._page_idx))

    # ── Overlay toggles ────────────────────────────────────────────────────

    def _update_overlays(self):
        self._page_view.show_zones    = self._chk_zones.isChecked()
        self._page_view.show_hf       = self._chk_hf.isChecked()
        self._page_view.show_headings = self._chk_headings.isChecked()
        self._page_view.update()
