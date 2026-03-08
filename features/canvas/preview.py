"""HTML preview widget for the canvas feature."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import html
import math
import re
import weakref
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QTimer, Qt, QUrl, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QDesktopServices,
    QFont,
    QKeySequence,
    QPalette,
    QPainter,
    QPen,
    QPolygonF,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextFormat,
    QTextListFormat,
)
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsLineItem,
    QGraphicsPolygonItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsTextItem,
    QGraphicsView,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMenu,
    QPushButton,
    QStackedLayout,
    QTextBrowser,
    QTextEdit,
    QToolTip,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from services.highlights import HighlightMatch, get_highlight_store

from .structured_graph import (
    GraphSpec,
    extract_graph_spec,
    graph_spec_signature,
    render_graph_html,
)
from .styles import PREVIEW_PANEL_STYLE, PREVIEW_VIEW_STYLE

try:
    import networkx as nx
except Exception:
    nx = None


@dataclass(slots=True)
class _RenderedHighlight:
    """One applied highlight span in preview plain-text coordinates."""

    highlight_id: str
    start: int
    end: int
    color: str
    hover_text: str
    jump_to: str
    kind: str


class _GraphCanvasView(QGraphicsView):
    """Pan/zoom-capable graph canvas."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(
            QGraphicsView.ViewportAnchor.AnchorUnderMouse
        )
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


class _GraphNodeItem(QGraphicsRectItem):
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
        ctrl_pressed = bool(
            event.modifiers() & Qt.KeyboardModifier.ControlModifier
        )
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
        if (
            change
            == QGraphicsRectItem.GraphicsItemChange.ItemPositionHasChanged
        ):
            for callback in list(self._move_callbacks):
                try:
                    callback()
                except Exception:
                    continue
        return super().itemChange(change, value)


class _PreviewTextBrowser(QTextBrowser):
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
            level = int(
                block_format.property(QTextFormat.Property.BlockQuoteLevel) or 0
            )
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


class _TableSizeGrid(QWidget):
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


class _TableInsertPicker(QWidget):
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

        self._grid = _TableSizeGrid(
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


class CanvasPreviewPane(QWidget):
    """Encapsulates preview editing/rendering, zooming, and cursor sync."""

    _HR_MARKER = "{{__D2C_HR__}}"
    _BLANK_LINE_SENTINEL = "\u200B"
    _ORDERED_ITEM_RE = re.compile(r"^(\s*)\d+[.)]\s+")
    _BULLET_ITEM_RE = re.compile(r"^(\s*)[-+*]\s+")
    _TOKEN_RE = re.compile(r"\w+(?:[+./-]\w+)*", flags=re.UNICODE)
    _INTERNAL_WORD_STAR_RE = re.compile(r"(?<=[^\W\d_])\*(?=[^\W\d_])", flags=re.UNICODE)
    _ZOOM_MIN = 60
    _ZOOM_MAX = 260
    _ZOOM_STEP = 10
    _BASE_PT = 11.0
    _TITLE_BASE_PT = 11.0
    _PAGE_MARGIN_DEFAULT_EM = 2.2
    _PAGE_MARGIN_PRESETS: tuple[tuple[str, float], ...] = (
        ("Schmal", 1.4),
        ("Normal", 2.2),
        ("Breit", 3.0),
        ("Sehr breit", 4.0),
    )
    _PREVIEW_THEME_DEFAULT = "classic"
    _PREVIEW_THEME_OPTIONS: tuple[tuple[str, str], ...] = (
        ("classic", "Klassisch"),
        ("accent", "Akzent"),
        ("vivid", "Lebhaft"),
    )
    _GLOBAL_PAGE_MARGIN_ENABLED = True
    _GLOBAL_PAGE_MARGIN_EM = _PAGE_MARGIN_DEFAULT_EM
    _GLOBAL_PREVIEW_THEME = _PREVIEW_THEME_DEFAULT
    _INSTANCES: "weakref.WeakSet[CanvasPreviewPane]" = weakref.WeakSet()
    _PREVIEW_TO_MARKDOWN_DELAY_MS = 140
    _HIGHLIGHT_SYNC_DELAY_MS = 240
    _DEFAULT_HOVER_TEXT = "Info"
    _HIGHLIGHT_COLORS = (
        ("Gelb", "#F9E2AF"),
        ("Grün", "#A6E3A1"),
        ("Blau", "#89B4FA"),
        ("Rot", "#F38BA8"),
        ("Lila", "#CBA6F7"),
        ("Orange", "#FAB387"),
    )

    def __init__(
        self,
        parent: QWidget | None = None,
        allow_editing: bool = True,
        show_title: bool = True,
        sync_cursor_with_editor: bool = True,
    ):
        super().__init__(parent)
        self._editor: Any | None = None
        self._zoom_percent = 100
        self._allow_editing = bool(allow_editing)
        self._show_title = bool(show_title)
        self._sync_cursor_with_editor = bool(sync_cursor_with_editor)
        self._page_margin_enabled = bool(self._GLOBAL_PAGE_MARGIN_ENABLED)
        self._page_margin_em = self._normalize_page_margin_em(
            float(self._GLOBAL_PAGE_MARGIN_EM)
        )
        self._preview_theme_id = self._normalize_preview_theme_id(
            self._GLOBAL_PREVIEW_THEME
        )
        self._format_bar: QWidget | None = None
        self._title: QLabel | None = None
        self._preview_edit_active = False
        self._suppress_preview_change = False
        self._suppress_preview_change_async = 0
        self._preview_user_edit_dirty = False
        self._preview_user_edit_intent = False
        self._highlight_scope = "generic"
        self._tab_name_getter: Callable[[], str] | None = None
        self._tab_switcher: Callable[[str], bool] | None = None
        self._rendered_highlights: list[_RenderedHighlight] = []
        self._hovered_highlight_id = ""
        self._last_rendered_markdown: str | None = None
        self._structured_graph_spec: GraphSpec | None = None
        self._structured_graph_signature = ""
        self._graph_collapsed_ids: set[str] = set()
        self._graph_focus_node_id = ""
        self._graph_manual_positions: dict[str, QPointF] = {}
        self._graph_layout_nonce = 0
        self._structured_view_active = False
        self._graph_view: _GraphCanvasView | None = None
        self._graph_scene: QGraphicsScene | None = None
        self._graph_plain_text = ""
        self._index_map_text = ""
        self._py_to_qt_map: list[int] = [0]
        self._qt_to_py_map: list[int] = [0]
        self._preserve_view_state_once = False
        self._view_scroll_guard_epoch = 0
        self._restoring_view_scroll = False
        self._pending_wheel_scroll_delta_px = 0
        self._render_cycle_id = 0
        self._table_insert_btn: QPushButton | None = None
        self._table_insert_menu: QMenu | None = None
        self._INSTANCES.add(self)
        self._setup_ui()
        self._setup_timers()

    def _palette_hex(
        self,
        role: QPalette.ColorRole,
        fallback: str = "#000000",
    ) -> str:
        color = self.palette().color(role)
        if isinstance(color, QColor) and color.isValid():
            return color.name(QColor.NameFormat.HexRgb)
        fallback_color = QColor(str(fallback or ""))
        if fallback_color.isValid():
            return fallback_color.name(QColor.NameFormat.HexRgb)
        return "#000000"

    @staticmethod
    def _mix_hex_colors(
        primary: str,
        secondary: str,
        secondary_weight: float,
    ) -> str:
        a = QColor(str(primary or ""))
        b = QColor(str(secondary or ""))
        if not a.isValid() and not b.isValid():
            return "#000000"
        if not a.isValid():
            return b.name(QColor.NameFormat.HexRgb)
        if not b.isValid():
            return a.name(QColor.NameFormat.HexRgb)
        w = min(1.0, max(0.0, float(secondary_weight)))
        inv = 1.0 - w
        mixed = QColor(
            int(round((a.red() * inv) + (b.red() * w))),
            int(round((a.green() * inv) + (b.green() * w))),
            int(round((a.blue() * inv) + (b.blue() * w))),
        )
        return mixed.name(QColor.NameFormat.HexRgb)

    @classmethod
    def _normalize_preview_theme_id(cls, value: object) -> str:
        token = str(value or "").strip().lower()
        valid = {name for name, _label in cls._PREVIEW_THEME_OPTIONS}
        if token in valid:
            return token
        return str(cls._PREVIEW_THEME_DEFAULT)

    @classmethod
    def preview_theme_options(cls) -> tuple[tuple[str, str], ...]:
        return tuple(cls._PREVIEW_THEME_OPTIONS)

    @classmethod
    def global_preview_theme_id(cls) -> str:
        return cls._normalize_preview_theme_id(cls._GLOBAL_PREVIEW_THEME)

    @classmethod
    def apply_global_preview_theme(cls, theme_id: object):
        normalized = cls._normalize_preview_theme_id(theme_id)
        cls._GLOBAL_PREVIEW_THEME = normalized
        for pane in list(cls._INSTANCES):
            try:
                pane.set_preview_theme_id(normalized)
            except Exception:
                continue

    def preview_theme_id(self) -> str:
        return str(self._preview_theme_id)

    def set_preview_theme_id(self, theme_id: object) -> bool:
        normalized = self._normalize_preview_theme_id(theme_id)
        if normalized == str(self._preview_theme_id):
            return False
        self._preview_theme_id = normalized
        self._apply_view_document_style()
        try:
            self._apply_highlights()
        except Exception:
            pass
        self._view.viewport().update()
        return True

    def _setup_ui(self):
        self.setStyleSheet(PREVIEW_PANEL_STYLE)

        layout = QVBoxLayout(self)
        if self._show_title or self._allow_editing:
            layout.setContentsMargins(6, 6, 6, 6)
            layout.setSpacing(4)
        else:
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)

        if self._show_title:
            self._title = QLabel("HTML-Vorschau")
            layout.addWidget(self._title)
        layout.addWidget(self._build_format_bar())

        self._view = _PreviewTextBrowser()
        self._view.setOpenLinks(False)
        self._view.setReadOnly(not self._allow_editing)
        self._view.setMouseTracking(True)
        self._view.viewport().setMouseTracking(True)
        self._view.setStyleSheet(PREVIEW_VIEW_STYLE)
        self._view.textChanged.connect(self._on_preview_text_changed)
        self._view.verticalScrollBar().valueChanged.connect(
            self._on_view_scrollbar_value_changed
        )
        self._view.installEventFilter(self)
        self._view.viewport().installEventFilter(self)

        self._graph_view = _GraphCanvasView()
        self._graph_view.setStyleSheet(PREVIEW_VIEW_STYLE)
        self._graph_scene = QGraphicsScene(self)
        self._graph_view.setScene(self._graph_scene)
        self._graph_view.setVisible(False)

        self._graph_bar = self._build_graph_bar()
        layout.addWidget(self._graph_bar)

        stack_host = QWidget()
        self._content_stack = QStackedLayout(stack_host)
        self._content_stack.setContentsMargins(0, 0, 0, 0)
        self._content_stack.setSpacing(0)
        self._content_stack.addWidget(self._view)
        self._content_stack.addWidget(self._graph_view)
        self._content_stack.setCurrentWidget(self._view)
        self._apply_title_style()
        layout.addWidget(stack_host)

    def _build_format_bar(self) -> QWidget:
        bar = QWidget()
        self._format_bar = bar
        row = QHBoxLayout(bar)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        button_specs = (
            ("H1", "Überschrift 1", lambda: self._set_heading_level(1)),
            ("H2", "Überschrift 2", lambda: self._set_heading_level(2)),
            ("H3", "Überschrift 3", lambda: self._set_heading_level(3)),
            ("Absatz", "Absatz (entfernt Überschrift)", self._clear_heading),
            ("B", "Fett", self._toggle_bold),
            ("I", "Kursiv", self._toggle_italic),
            ('"', "Zitat", self._toggle_block_quote),
            ("•", "Aufzählung", self._toggle_bullet_list),
            ("1.", "Nummerierte Liste", self._toggle_numbered_list),
            ("Tab", "Tabelle einfügen", self._show_table_insert_menu),
            ("HR", "Waagerechter Strich", self._insert_horizontal_rule),
            ("→", "Einrücken (Tab)", self._indent_list_item),
            ("←", "Ausrücken (Shift+Tab)", self._outdent_list_item),
        )
        button_style = (
            "QPushButton {"
            "background: palette(alternate-base);"
            "color: palette(text);"
            "border: 1px solid palette(mid);"
            "padding: 2px 8px;"
            "border-radius: 3px;"
            "font-size: 11px;"
            "min-height: 20px;"
            "}"
            "QPushButton:hover { border: 1px solid palette(highlight); }"
            "QPushButton:pressed { background: palette(mid); }"
            "QPushButton:checked {"
            "background: palette(highlight);"
            "color: palette(highlighted-text);"
            "border: 1px solid palette(highlight);"
            "}"
        )
        for label, tooltip, slot in button_specs:
            btn = QPushButton(label)
            btn.setToolTip(tooltip)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(button_style)
            btn.clicked.connect(slot)
            if label == "Tab":
                self._table_insert_btn = btn
            row.addWidget(btn)
        row.addStretch()

        bar.setVisible(self._allow_editing)
        return bar

    def _build_graph_bar(self) -> QWidget:
        bar = QWidget()
        row = QHBoxLayout(bar)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        button_style = (
            "QPushButton {"
            "background: palette(alternate-base);"
            "color: palette(text);"
            "border: 1px solid palette(mid);"
            "padding: 2px 8px;"
            "border-radius: 3px;"
            "font-size: 11px;"
            "min-height: 20px;"
            "}"
            "QPushButton:hover { border: 1px solid palette(highlight); }"
            "QPushButton:pressed { background: palette(mid); }"
        )

        self._graph_expand_btn = QPushButton("Alle +")
        self._graph_expand_btn.setToolTip("Alle MindMap-Knoten ausklappen")
        self._graph_expand_btn.setStyleSheet(button_style)
        self._graph_expand_btn.clicked.connect(self._expand_all_graph_nodes)
        row.addWidget(self._graph_expand_btn)

        self._graph_collapse_btn = QPushButton("Alle -")
        self._graph_collapse_btn.setToolTip("Alle MindMap-Knoten einklappen")
        self._graph_collapse_btn.setStyleSheet(button_style)
        self._graph_collapse_btn.clicked.connect(self._collapse_all_graph_nodes)
        row.addWidget(self._graph_collapse_btn)

        self._graph_focus_clear_btn = QPushButton("Fokus x")
        self._graph_focus_clear_btn.setToolTip("Knotenfokus aufheben")
        self._graph_focus_clear_btn.setStyleSheet(button_style)
        self._graph_focus_clear_btn.clicked.connect(self._clear_graph_focus)
        row.addWidget(self._graph_focus_clear_btn)

        self._graph_layout_opt_btn = QPushButton("Layout +")
        self._graph_layout_opt_btn.setToolTip(
            "Sichtbare Knoten ueberlappungsarm optimieren "
            "(moeglichst kleine Verschiebungen)"
        )
        self._graph_layout_opt_btn.setStyleSheet(button_style)
        self._graph_layout_opt_btn.clicked.connect(
            self._optimize_visible_graph_layout
        )
        row.addWidget(self._graph_layout_opt_btn)

        self._graph_layout_fresh_btn = QPushButton("Layout neu")
        self._graph_layout_fresh_btn.setToolTip(
            "Sichtbare Knoten komplett neu anordnen"
        )
        self._graph_layout_fresh_btn.setStyleSheet(button_style)
        self._graph_layout_fresh_btn.clicked.connect(
            self._reflow_visible_graph_layout
        )
        row.addWidget(self._graph_layout_fresh_btn)

        hint = QLabel("Klick: Fokus | Doppelklick: auf/zu oder Link")
        hint.setStyleSheet("color: palette(placeholder-text); font-size: 10px;")
        row.addWidget(hint)
        row.addStretch()
        bar.setVisible(False)
        return bar

    def _setup_timers(self):
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.timeout.connect(self._render)

        self._cursor_timer = QTimer(self)
        self._cursor_timer.setSingleShot(True)
        self._cursor_timer.timeout.connect(self._sync_to_cursor)

        self._preview_to_markdown_timer = QTimer(self)
        self._preview_to_markdown_timer.setSingleShot(True)
        self._preview_to_markdown_timer.timeout.connect(
            self._commit_preview_edit_to_markdown
        )

        self._highlight_sync_timer = QTimer(self)
        self._highlight_sync_timer.setSingleShot(True)
        self._highlight_sync_timer.timeout.connect(
            self._sync_highlights_from_editor
        )

        self._wheel_scroll_flush_timer = QTimer(self)
        self._wheel_scroll_flush_timer.setSingleShot(True)
        self._wheel_scroll_flush_timer.timeout.connect(
            self._flush_pending_wheel_scroll
        )

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
        super().showEvent(event)
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
        return super().eventFilter(watched, event)

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

    def _open_highlight_context_menu(self, global_pos: QPoint):
        menu = self._view.createStandardContextMenu()

        vp_pos = self._view.viewport().mapFromGlobal(global_pos)
        cursor_at_pos = self._view.cursorForPosition(vp_pos)
        selected_text = self.get_selected_text().strip()
        active_span = self._span_at_position(cursor_at_pos.position())

        if menu.actions():
            menu.addSeparator()

        create_actions: dict = {}
        if selected_text:
            current_menu = menu.addMenu("Markieren (aktueller Tab)")
            all_tabs_menu = menu.addMenu("Markieren (alle Tabs)")
            for label, color in self._HIGHLIGHT_COLORS:
                current_action = current_menu.addAction(label)
                all_action = all_tabs_menu.addAction(label)
                create_actions[current_action] = (color, False)
                create_actions[all_action] = (color, True)

        edit_actions: dict = {}
        if active_span is not None:
            menu.addSeparator()

            is_glossary = str(active_span.kind or "") == "glossary"
            if is_glossary:
                hover_action = menu.addAction("Glossar-Text setzen…")
                delete_action = menu.addAction("Glossar-Markierung löschen")
                edit_actions[hover_action] = ("hover", active_span.highlight_id)
                edit_actions[delete_action] = ("delete", active_span.highlight_id)
            else:
                hover_action = menu.addAction("Hover-Text setzen…")
                jump_action = menu.addAction("Jump-Ziel (Markierung) setzen…")
                clear_jump_action = menu.addAction("Jump-Ziel entfernen")
                delete_action = menu.addAction("Markierung löschen")
                color_menu = menu.addMenu("Farbe ändern")
                for label, color in self._HIGHLIGHT_COLORS:
                    action = color_menu.addAction(label)
                    edit_actions[action] = ("color", color)

                edit_actions[hover_action] = ("hover", active_span.highlight_id)
                edit_actions[jump_action] = ("jump", active_span.highlight_id)
                edit_actions[clear_jump_action] = (
                    "jump_clear",
                    active_span.highlight_id,
                )
                edit_actions[delete_action] = ("delete", active_span.highlight_id)

        picked = menu.exec(global_pos)
        if picked is None:
            return
        if self._is_copy_action(picked):
            # Normalize clipboard text so HTML copy never injects hidden chars
            # or paragraph separators into Markdown targets.
            self._copy_selection_to_clipboard()
            return

        create_payload = create_actions.get(picked)
        if create_payload is not None:
            color, apply_all = create_payload
            self._create_highlight_from_selection(
                color=color,
                apply_all_tabs=apply_all,
            )
            return

        edit_payload = edit_actions.get(picked)
        if edit_payload is None:
            return
        self._apply_highlight_edit_action(edit_payload, active_span)

    @staticmethod
    def _is_copy_action(action) -> bool:
        if action is None:
            return False
        try:
            match = action.shortcut().matches(QKeySequence.StandardKey.Copy)
            if match == QKeySequence.SequenceMatch.ExactMatch:
                return True
        except Exception:
            pass
        label = str(action.text() or "").replace("&", "").strip().lower()
        return label in {"copy", "kopieren"}

    def _create_highlight_from_selection(
        self,
        *,
        color: str,
        apply_all_tabs: bool,
    ):
        cursor = self._view.textCursor()
        if not cursor.hasSelection():
            return
        start_qt = int(cursor.selectionStart())
        end_qt = int(cursor.selectionEnd())
        start = self._qt_to_py_pos(start_qt)
        end = self._qt_to_py_pos(end_qt)
        if end <= start:
            return
        text = self._preview_plain_text()
        store = get_highlight_store()
        highlight_id = store.add_from_selection(
            panel_scope=self._highlight_scope,
            tab_name=self._current_tab_name(),
            full_text=text,
            start=start,
            end=end,
            color=color,
            apply_all_tabs=apply_all_tabs,
        )
        if highlight_id:
            self.request_preserve_view_state()
            self.schedule_update()

    def _apply_highlight_edit_action(
        self,
        payload: tuple,
        span: _RenderedHighlight | None,
    ):
        if span is None:
            return
        mode = str(payload[0] or "")
        store = get_highlight_store()
        if mode == "delete":
            if store.delete(span.highlight_id):
                self.request_preserve_view_state()
                self.schedule_update()
            return
        if mode == "hover":
            current = span.hover_text or ""
            text, ok = QInputDialog.getMultiLineText(
                self,
                "Hover-Text",
                "Text beim Überfahren:",
                current,
            )
            if ok and store.set_hover_text(span.highlight_id, text):
                self.request_preserve_view_state()
                self.schedule_update()
            return
        if mode == "jump":
            target_id = self._pick_jump_target(span.highlight_id)
            if target_id is None:
                return
            if store.set_jump_target(span.highlight_id, target_id):
                self.request_preserve_view_state()
                self.schedule_update()
            return
        if mode == "jump_clear":
            if store.set_jump_target(span.highlight_id, ""):
                self.request_preserve_view_state()
                self.schedule_update()
            return
        if mode == "color":
            color = str(payload[1] or "")
            if store.set_color(span.highlight_id, color):
                self.request_preserve_view_state()
                self.schedule_update()

    def _update_hover_tooltip(self, global_pos: QPoint):
        vp_pos = self._view.viewport().mapFromGlobal(global_pos)
        cursor = self._view.cursorForPosition(vp_pos)
        span = self._span_at_position(cursor.position())
        if span is None or not span.hover_text:
            if self._hovered_highlight_id:
                QToolTip.hideText()
                self._hovered_highlight_id = ""
            return
        if self._hovered_highlight_id == span.highlight_id:
            return
        self._hovered_highlight_id = span.highlight_id
        QToolTip.showText(
            global_pos,
            self._tooltip_text(span.hover_text),
            self._view.viewport(),
        )

    @staticmethod
    def _tooltip_text(text: str) -> str:
        safe = html.escape(str(text or ""))
        return safe.replace("\n", "<br/>")

    def _pick_jump_target(self, source_highlight_id: str) -> str | None:
        store = get_highlight_store()
        options = store.list_jump_targets()
        labels: list[str] = ["(kein Jump-Ziel)"]
        label_to_id: dict[str, str] = {"(kein Jump-Ziel)": ""}
        current_target = ""

        current = store.get_highlight(source_highlight_id)
        if isinstance(current, dict):
            current_target = str(current.get("jump_to", "") or "").strip()

        for row in options:
            target_id = str(row.get("id", "") or "").strip()
            if not target_id or target_id == source_highlight_id:
                continue
            scope = str(row.get("panel_scope", "") or "")
            tab_scope = str(row.get("tab_scope", "") or "tabs")
            tabs = list(row.get("tabs", []) or [])
            tabs_label = "all" if tab_scope == "all" else ",".join(tabs[:2])
            preview = str(row.get("exact_preview", "") or "")
            label = f"{target_id} | {scope}:{tabs_label} | {preview}"
            labels.append(label)
            label_to_id[label] = target_id

        if len(labels) == 1:
            return ""

        current_label = "(kein Jump-Ziel)"
        for label, target_id in label_to_id.items():
            if target_id == current_target:
                current_label = label
                break

        picked, ok = QInputDialog.getItem(
            self,
            "Jump-Ziel auswählen",
            "Ziel-Markierung:",
            labels,
            labels.index(current_label) if current_label in labels else 0,
            False,
        )
        if not ok:
            return None
        return label_to_id.get(str(picked), "")

    def _handle_highlight_click(self, global_pos: QPoint) -> bool:
        vp_pos = self._view.viewport().mapFromGlobal(global_pos)
        cursor = self._view.cursorForPosition(vp_pos)
        span = self._span_at_position(cursor.position())
        if span is None:
            return False
        target_ref = str(span.jump_to or "").strip()
        if not target_ref:
            return False

        store = get_highlight_store()
        target = store.get_highlight(target_ref)
        if isinstance(target, dict):
            target_scope = str(target.get("panel_scope", "") or "").strip().lower()
            if target_scope and target_scope != self._highlight_scope:
                QToolTip.showText(
                    global_pos,
                    (
                        "Jump-Ziel liegt in anderem Panel "
                        f"('{target_scope}')."
                    ),
                    self._view.viewport(),
                )
                return True

            target_tab_scope = str(target.get("tab_scope", "") or "tabs")
            current_tab = self._current_tab_name()
            if target_tab_scope == "tabs":
                tabs = [
                    str(item or "").strip()
                    for item in list(target.get("tabs", []) or [])
                    if str(item or "").strip()
                ]
                if tabs and current_tab not in tabs:
                    switcher = self._tab_switcher
                    if switcher is not None and switcher(tabs[0]):
                        return True
                    QToolTip.showText(
                        global_pos,
                        f"Jump-Ziel ist im Tab '{tabs[0]}'.",
                        self._view.viewport(),
                    )
                    return True
            if self._jump_to_highlight_id(target_ref):
                return True
            return True

        # Backward compatibility for older free-text jump targets.
        return self._jump_to_text(target_ref)

    def _jump_to_highlight_id(self, target_id: str) -> bool:
        match = get_highlight_store().resolve_highlight_by_id(
            highlight_id=target_id,
            panel_scope=self._highlight_scope,
            tab_name=self._current_tab_name(),
            full_text=self._preview_plain_text(),
        )
        if match is None:
            return False
        qt_start = self._py_to_qt_pos(int(match.start))
        qt_end = self._py_to_qt_pos(int(match.end))
        if qt_end <= qt_start:
            return False
        cursor = self._view.textCursor()
        cursor.setPosition(qt_start)
        cursor.setPosition(qt_end, QTextCursor.MoveMode.KeepAnchor)
        self._view.setTextCursor(cursor)
        self._view.ensureCursorVisible()
        return True

    def _jump_to_text(self, needle: str) -> bool:
        query = str(needle or "").strip()
        if not query:
            return False
        cursor = self._view.textCursor()
        start_pos = int(cursor.selectionEnd())
        doc = self._view.document()

        probe = QTextCursor(doc)
        probe.setPosition(max(0, start_pos))
        found = doc.find(query, probe)
        if found.isNull():
            found = doc.find(query)
        if found.isNull():
            return False
        self._view.setTextCursor(found)
        self._view.ensureCursorVisible()
        return True

    def find_text(
        self,
        query: str,
        *,
        backward: bool = False,
        case_sensitive: bool = False,
        whole_words: bool = False,
        wrap: bool = True,
    ) -> bool:
        if self._structured_view_active:
            return False
        needle = str(query or "")
        if not needle:
            return False

        flags = QTextDocument.FindFlag(0)
        if backward:
            flags |= QTextDocument.FindFlag.FindBackward
        if case_sensitive:
            flags |= QTextDocument.FindFlag.FindCaseSensitively
        if whole_words:
            flags |= QTextDocument.FindFlag.FindWholeWords

        doc = self._view.document()
        cursor = self._view.textCursor()
        current_start = int(cursor.selectionStart())
        current_end = int(cursor.selectionEnd())
        current_has_selection = current_end > current_start
        start = int(cursor.selectionStart()) if backward else int(cursor.selectionEnd())
        probe = QTextCursor(doc)
        if backward:
            probe.setPosition(max(0, start - 1))
        else:
            probe.setPosition(max(0, start))

        found = doc.find(needle, probe, flags)
        if found.isNull() and wrap:
            restart = QTextCursor(doc)
            if backward:
                restart.setPosition(max(0, int(doc.characterCount()) - 1))
            else:
                restart.setPosition(0)
            found = doc.find(needle, restart, flags)

        if (
            not found.isNull()
            and current_has_selection
            and int(found.selectionStart()) == current_start
            and int(found.selectionEnd()) == current_end
        ):
            probe2 = QTextCursor(doc)
            if backward:
                probe2.setPosition(max(0, int(found.selectionStart()) - 1))
            else:
                probe2.setPosition(max(0, int(found.selectionEnd())))
            alt = doc.find(needle, probe2, flags)
            if alt.isNull() and wrap:
                restart = QTextCursor(doc)
                if backward:
                    restart.setPosition(max(0, int(doc.characterCount()) - 1))
                else:
                    restart.setPosition(0)
                alt = doc.find(needle, restart, flags)
            if (
                not alt.isNull()
                and (
                    int(alt.selectionStart()) != current_start
                    or int(alt.selectionEnd()) != current_end
                )
            ):
                found = alt
        if found.isNull():
            return False

        self._view.setTextCursor(found)
        self._view.ensureCursorVisible()
        return True

    def count_text_matches(
        self,
        query: str,
        *,
        case_sensitive: bool = False,
        whole_words: bool = False,
    ) -> int:
        if self._structured_view_active:
            return 0
        needle = str(query or "")
        if not needle:
            return 0

        flags = QTextDocument.FindFlag(0)
        if case_sensitive:
            flags |= QTextDocument.FindFlag.FindCaseSensitively
        if whole_words:
            flags |= QTextDocument.FindFlag.FindWholeWords

        doc = self._view.document()
        count = 0
        found = doc.find(needle, 0, flags)
        while not found.isNull():
            count += 1
            found = doc.find(needle, found.position(), flags)
        return count

    def is_read_only(self) -> bool:
        return bool(self._view.isReadOnly())

    def _span_at_position(self, position: int) -> _RenderedHighlight | None:
        for item in self._rendered_highlights:
            if item.start <= position < item.end:
                return item
        return None

    def schedule_update(self, *_):
        if not self.isVisible():
            return
        if self._preview_edit_active:
            return
        if self._preview_timer.isActive():
            return
        self._preview_timer.start(120)

    def schedule_cursor_sync(self, *_):
        if not self._sync_cursor_with_editor:
            return
        if not self.isVisible():
            return
        if self._editor is not None and not self._editor.isVisible():
            return
        if self._preview_edit_active:
            return
        self._cursor_timer.start(45)

    def _current_tab_name(self) -> str:
        getter = self._tab_name_getter
        if getter is None:
            return ""
        try:
            return str(getter() or "").strip()
        except Exception:
            return ""

    def _preview_plain_text(self) -> str:
        if self._structured_view_active:
            return str(self._graph_plain_text or "")
        return (self._view.toPlainText() or "").replace("\r\n", "\n")

    @classmethod
    def _tail_probe_from_markdown(cls, markdown: str) -> str:
        lines = str(markdown or "").splitlines()
        for raw in reversed(lines):
            normalized = cls._normalize_markdown_line(raw)
            if not normalized:
                continue
            tokens = [
                token.casefold()
                for token in cls._TOKEN_RE.findall(normalized)
                if token
            ]
            if not tokens:
                continue
            # Use the last words so end-of-document truncation is detectable.
            return " ".join(tokens[-12:])
        return ""

    @classmethod
    def _contains_tail_probe(cls, haystack: str, probe: str) -> bool:
        needle = str(probe or "").strip()
        if not needle:
            return True
        words = [
            token.casefold()
            for token in cls._TOKEN_RE.findall(str(haystack or ""))
            if token
        ]
        if not words:
            return False
        return needle in " ".join(words)

    def _copy_selection_to_clipboard(self) -> bool:
        cursor = self._view.textCursor()
        if not cursor.hasSelection():
            return False
        text = str(cursor.selectedText() or "")
        text = (
            text.replace("\u2029", "\n")
            .replace("\u2028", "\n")
            .replace("\r\n", "\n")
            .replace("\r", "\n")
            .replace("\uFFFC", "")
            .replace("\u200b", "")
            .replace("\u200c", "")
            .replace("\u200d", "")
            .replace("\ufeff", "")
        )
        QApplication.clipboard().setText(text)
        return True

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

    def _schedule_highlight_sync(self):
        self._highlight_sync_timer.start(self._HIGHLIGHT_SYNC_DELAY_MS)

    def _sync_highlights_from_editor(self):
        editor = self._editor
        if editor is None:
            return
        md = self._markdown_for_render(editor.get_full_text())
        doc = QTextDocument()
        spec = extract_graph_spec(md)
        if spec is None:
            doc.setMarkdown(md)
        else:
            signature = graph_spec_signature(spec)
            if signature == self._structured_graph_signature:
                collapsed = set(self._graph_collapsed_ids)
                focus = self._graph_focus_node_id
            else:
                collapsed = set(spec.default_collapsed_ids)
                focus = ""
            doc.setHtml(
                render_graph_html(
                    spec,
                    collapsed_ids=collapsed,
                    focus_node_id=focus,
                )
            )
        plain_text = (doc.toPlainText() or "").replace("\r\n", "\n")
        get_highlight_store().sync_for_text(
            panel_scope=self._highlight_scope,
            tab_name=self._current_tab_name(),
            full_text=plain_text,
        )

    def _apply_highlights(self):
        theme_selections = self._build_preview_theme_extra_selections()
        if self._structured_view_active:
            # Text overlays are bound to QTextBrowser selections.
            # Graph mode uses dedicated scene tooltips and click targets.
            self._rendered_highlights = []
            self._view.setExtraSelections(theme_selections)
            return
        text = self._preview_plain_text()
        store = get_highlight_store()
        store.sync_for_text(
            panel_scope=self._highlight_scope,
            tab_name=self._current_tab_name(),
            full_text=text,
        )
        matches = store.resolve_matches(
            panel_scope=self._highlight_scope,
            tab_name=self._current_tab_name(),
            full_text=text,
        )
        self._rendered_highlights = []
        if not matches:
            self._view.setExtraSelections(theme_selections)
            return
        old_suppress = self._suppress_preview_change
        self._suppress_preview_change = True
        try:
            self._render_highlight_matches(
                matches,
                theme_selections=theme_selections,
            )
        finally:
            self._suppress_preview_change = old_suppress

    def _preview_theme_text_colors(self) -> dict[str, str]:
        theme = self._normalize_preview_theme_id(self._preview_theme_id)
        text_color = self._palette_hex(QPalette.ColorRole.Text, "#CDD6F4")
        link_color = self._palette_hex(QPalette.ColorRole.Highlight, "#89B4FA")
        if theme == "vivid":
            heading_h1 = self._mix_hex_colors(text_color, "#2563EB", 0.86)
            heading_h2 = self._mix_hex_colors(text_color, "#7C3AED", 0.82)
            heading_h3 = self._mix_hex_colors(text_color, "#DB2777", 0.76)
            strong_color = self._mix_hex_colors(text_color, "#F97316", 0.78)
            em_color = self._mix_hex_colors(text_color, "#22C55E", 0.72)
        else:
            heading_h1 = self._mix_hex_colors(text_color, "#60A5FA", 0.64)
            heading_h2 = self._mix_hex_colors(text_color, "#A78BFA", 0.54)
            heading_h3 = self._mix_hex_colors(text_color, "#34D399", 0.50)
            strong_color = self._mix_hex_colors(text_color, "#FB923C", 0.50)
            em_color = self._mix_hex_colors(text_color, link_color, 0.24)
        strong_em_color = self._mix_hex_colors(strong_color, em_color, 0.45)
        return {
            "heading_h1": heading_h1,
            "heading_h2": heading_h2,
            "heading_h3": heading_h3,
            "heading_default": heading_h3,
            "strong": strong_color,
            "em": em_color,
            "strong_em": strong_em_color,
        }

    def _build_preview_theme_extra_selections(self) -> list[QTextEdit.ExtraSelection]:
        if self._normalize_preview_theme_id(self._preview_theme_id) == "classic":
            return []

        doc = self._view.document()
        colors = self._preview_theme_text_colors()
        heading_h1_q = QColor(colors["heading_h1"])
        heading_h2_q = QColor(colors["heading_h2"])
        heading_h3_q = QColor(colors["heading_h3"])
        heading_default_q = QColor(colors["heading_default"])
        strong_q = QColor(colors["strong"])
        em_q = QColor(colors["em"])
        strong_em_q = QColor(colors["strong_em"])

        selections: list[QTextEdit.ExtraSelection] = []
        block = doc.begin()
        while block.isValid():
            heading_level = int(block.blockFormat().headingLevel())
            block_start = int(block.position())
            block_end = block_start + max(0, int(block.length()) - 1)
            if heading_level > 0 and block_end > block_start:
                cursor = QTextCursor(doc)
                cursor.setPosition(block_start)
                cursor.setPosition(block_end, QTextCursor.MoveMode.KeepAnchor)
                fmt = QTextCharFormat()
                if heading_level == 1:
                    fmt.setForeground(heading_h1_q)
                elif heading_level == 2:
                    fmt.setForeground(heading_h2_q)
                elif heading_level == 3:
                    fmt.setForeground(heading_h3_q)
                else:
                    fmt.setForeground(heading_default_q)
                sel = QTextEdit.ExtraSelection()
                sel.cursor = cursor
                sel.format = fmt
                selections.append(sel)
                block = block.next()
                continue

            iterator = block.begin()
            while not iterator.atEnd():
                frag = iterator.fragment()
                if frag.isValid():
                    frag_fmt = frag.charFormat()
                    if not frag_fmt.fontFixedPitch():
                        is_bold = int(frag_fmt.fontWeight()) >= int(QFont.Weight.DemiBold)
                        is_italic = bool(frag_fmt.fontItalic())
                        if is_bold or is_italic:
                            color = strong_q if is_bold else em_q
                            if is_bold and is_italic:
                                color = strong_em_q
                            start = int(frag.position())
                            end = start + len(frag.text())
                            if end > start:
                                cursor = QTextCursor(doc)
                                cursor.setPosition(start)
                                cursor.setPosition(
                                    end,
                                    QTextCursor.MoveMode.KeepAnchor,
                                )
                                fmt = QTextCharFormat()
                                fmt.setForeground(color)
                                sel = QTextEdit.ExtraSelection()
                                sel.cursor = cursor
                                sel.format = fmt
                                selections.append(sel)
                iterator += 1

            block = block.next()

        return selections

    def _render_highlight_matches(
        self,
        matches: list[HighlightMatch],
        *,
        theme_selections: list[QTextEdit.ExtraSelection] | None = None,
    ):
        self._ensure_index_maps()
        doc = self._view.document()
        selections: list[QTextEdit.ExtraSelection] = list(theme_selections or [])
        for item in matches:
            start_py = max(0, int(item.start))
            end_py = max(0, int(item.end))
            if end_py <= start_py:
                continue
            start = self._py_to_qt_pos(start_py)
            end = self._py_to_qt_pos(end_py)
            if end <= start:
                continue
            cursor = QTextCursor(doc)
            cursor.setPosition(start)
            cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
            fmt = QTextCharFormat()
            bg_color = QColor(item.color or "#F9E2AF")
            if bg_color.isValid():
                bg_color.setAlpha(120)
                fmt.setBackground(bg_color)
            sel = QTextEdit.ExtraSelection()
            sel.cursor = cursor
            sel.format = fmt
            selections.append(sel)
            self._rendered_highlights.append(
                _RenderedHighlight(
                    highlight_id=item.highlight_id,
                    start=start,
                    end=end,
                    color=item.color,
                    hover_text=item.hover_text,
                    jump_to=item.jump_to,
                    kind=item.kind,
                )
            )
        self._view.setExtraSelections(selections)

    def _apply_title_style(self):
        if self._title is None:
            return
        title_pt = self._TITLE_BASE_PT * (self._zoom_percent / 100.0)
        title_color = self._palette_hex(
            QPalette.ColorRole.PlaceholderText,
            "#6C7086",
        )
        if self._preview_theme_id == "accent":
            accent = self._palette_hex(QPalette.ColorRole.Highlight, "#89B4FA")
            title_color = self._mix_hex_colors(title_color, accent, 0.32)
        elif self._preview_theme_id == "vivid":
            title_color = self._mix_hex_colors(title_color, "#3B82F6", 0.62)
        self._title.setStyleSheet(
            f"color: {title_color}; "
            f"font-size: {title_pt:.1f}pt; font-weight: bold;"
        )

    def _markdown_stylesheet(self) -> str:
        zoom = self._zoom_percent / 100.0
        body_pt = self._BASE_PT * zoom
        code_pt = max(8.0, body_pt * 0.95)
        paragraph_gap_em = 0.95
        preview_theme = self._normalize_preview_theme_id(self._preview_theme_id)
        base_color = self._palette_hex(QPalette.ColorRole.Base, "#11111B")
        alt_base_color = self._palette_hex(
            QPalette.ColorRole.AlternateBase,
            "#1E1E2E",
        )
        text_color = self._palette_hex(QPalette.ColorRole.Text, "#CDD6F4")
        code_color = self._palette_hex(
            QPalette.ColorRole.PlaceholderText,
            "#BAC2DE",
        )
        link_color = self._palette_hex(QPalette.ColorRole.Highlight, "#89B4FA")
        table_border = self._palette_hex(QPalette.ColorRole.Mid, "#D0D0D0")
        quote_border = self._palette_hex(QPalette.ColorRole.Mid, "#7A7A7A")
        quote_color = self._palette_hex(
            QPalette.ColorRole.PlaceholderText,
            "#BAC2DE",
        )
        heading_h1_color = text_color
        heading_h2_color = text_color
        heading_h3_color = text_color
        heading_default_color = text_color
        strong_color = text_color
        em_color = text_color
        code_bg = "transparent"
        quote_bg = "transparent"
        table_header_bg = "transparent"
        table_header_text = text_color
        hr_color = table_border
        if preview_theme == "accent":
            heading_h1_color = self._mix_hex_colors(text_color, "#60A5FA", 0.64)
            heading_h2_color = self._mix_hex_colors(text_color, "#A78BFA", 0.54)
            heading_h3_color = self._mix_hex_colors(text_color, "#34D399", 0.50)
            heading_default_color = heading_h3_color
            strong_color = self._mix_hex_colors(text_color, "#FB923C", 0.50)
            em_color = self._mix_hex_colors(text_color, link_color, 0.14)
            code_bg = self._mix_hex_colors(base_color, link_color, 0.12)
            quote_bg = self._mix_hex_colors(base_color, link_color, 0.08)
            table_header_bg = self._mix_hex_colors(
                alt_base_color,
                link_color,
                0.10,
            )
            table_header_text = self._mix_hex_colors(text_color, link_color, 0.30)
            hr_color = self._mix_hex_colors(table_border, link_color, 0.28)
            quote_color = self._mix_hex_colors(quote_color, link_color, 0.20)
        elif preview_theme == "vivid":
            heading_h1_color = self._mix_hex_colors(text_color, "#2563EB", 0.86)
            heading_h2_color = self._mix_hex_colors(text_color, "#7C3AED", 0.82)
            heading_h3_color = self._mix_hex_colors(text_color, "#DB2777", 0.76)
            heading_default_color = heading_h3_color
            strong_color = self._mix_hex_colors(text_color, "#F97316", 0.78)
            em_color = self._mix_hex_colors(text_color, "#22C55E", 0.72)
            code_bg = self._mix_hex_colors(base_color, "#A855F7", 0.24)
            quote_bg = self._mix_hex_colors(base_color, "#F97316", 0.18)
            table_header_bg = self._mix_hex_colors(alt_base_color, "#2563EB", 0.35)
            table_header_text = self._mix_hex_colors(text_color, "#F8FAFC", 0.32)
            hr_color = self._mix_hex_colors(table_border, "#F97316", 0.42)
            quote_color = self._mix_hex_colors(quote_color, "#F97316", 0.40)
            quote_border = self._mix_hex_colors(quote_border, "#F97316", 0.56)
            table_border = self._mix_hex_colors(table_border, "#2563EB", 0.34)
        body_rule = (
            "body { "
            "font-family: 'Segoe UI', sans-serif; "
            "font-size: 1em; "
            "line-height: 1.45; "
            f"color: {text_color}; "
            "background: transparent; "
            "}"
        )
        code_rule = (
            "pre, code { "
            "font-family: 'Cascadia Code', 'Consolas', monospace; "
            f"font-size: {code_pt:.1f}pt; "
            f"color: {code_color}; "
            "}"
        )
        return "".join(
            [
                body_rule,
                f"h1 {{ font-size: 2.00em; color: {heading_h1_color}; font-weight: 680; }} ",
                f"h2 {{ font-size: 1.60em; color: {heading_h2_color}; font-weight: 670; }} ",
                f"h3 {{ font-size: 1.30em; color: {heading_h3_color}; font-weight: 660; }} ",
                f"h4, h5, h6 {{ color: {heading_default_color}; font-weight: 650; }} ",
                f"strong, b {{ color: {strong_color}; font-weight: 700; }} ",
                f"em, i {{ color: {em_color}; }} ",
                f"p {{ margin: 0 0 {paragraph_gap_em:.2f}em 0; }} ",
                f"ul, ol {{ margin: 0.35em 0 {paragraph_gap_em:.2f}em 1.35em; }} ",
                "li { margin: 0.20em 0; } ",
                f"a {{ color: {link_color}; }} ",
                (
                    "blockquote { "
                    f"margin: 0.30em 0 {paragraph_gap_em:.2f}em 0; "
                    "padding: 0.10em 0 0.10em 0.80em; "
                    f"border-left: 4px solid {quote_border}; "
                    f"color: {quote_color}; "
                    f"background: {quote_bg}; "
                    "}"
                ),
                code_rule,
                f"pre, code {{ background: {code_bg}; border-radius: 3px; }} ",
                "table { border-collapse: collapse; } ",
                (
                    f"th, td {{ border: 1px solid {table_border}; "
                    "padding: 4px 8px; }}"
                ),
                (
                    f"th {{ background: {table_header_bg}; color: {table_header_text}; "
                    "font-weight: 650; }}"
                ),
                f"hr {{ border: 0; border-top: 1px solid {hr_color}; }} ",
            ]
        )

    def _apply_view_document_style(self):
        body_pt = self._BASE_PT * (self._zoom_percent / 100.0)
        doc = self._view.document()
        font = QFont(doc.defaultFont())
        font.setPointSizeF(body_pt)
        doc.setDefaultFont(font)
        self._apply_title_style()
        margin_px = 0.0
        if self._page_margin_enabled:
            margin_px = max(8.0, body_pt * float(self._page_margin_em))
        doc.setDocumentMargin(float(margin_px))
        doc.setDefaultStyleSheet(self._markdown_stylesheet())

    @classmethod
    def _normalize_page_margin_em(cls, value: float) -> float:
        try:
            numeric = float(value)
        except Exception:
            numeric = float(cls._PAGE_MARGIN_DEFAULT_EM)
        choices = [float(v) for _label, v in cls._PAGE_MARGIN_PRESETS]
        if not choices:
            return float(cls._PAGE_MARGIN_DEFAULT_EM)
        nearest = min(choices, key=lambda current: abs(current - numeric))
        return float(nearest)

    @classmethod
    def global_page_margin_settings(cls) -> tuple[bool, float]:
        return (
            bool(cls._GLOBAL_PAGE_MARGIN_ENABLED),
            float(cls._normalize_page_margin_em(cls._GLOBAL_PAGE_MARGIN_EM)),
        )

    @classmethod
    def apply_global_page_margin_settings(
        cls,
        *,
        enabled: bool,
        em: float,
    ):
        normalized_em = cls._normalize_page_margin_em(em)
        cls._GLOBAL_PAGE_MARGIN_ENABLED = bool(enabled)
        cls._GLOBAL_PAGE_MARGIN_EM = float(normalized_em)
        for pane in list(cls._INSTANCES):
            try:
                pane.set_page_margin_settings(
                    enabled=bool(enabled),
                    em=float(normalized_em),
                )
            except Exception:
                continue

    def page_margin_settings(self) -> tuple[bool, float]:
        return bool(self._page_margin_enabled), float(self._page_margin_em)

    def _sync_page_margin_controls(self):
        # Page-margin controls are global and live in the main View menu.
        return

    def set_page_margin_settings(
        self,
        *,
        enabled: bool | None = None,
        em: float | None = None,
    ) -> bool:
        changed = False
        if enabled is not None:
            next_enabled = bool(enabled)
            if next_enabled != bool(self._page_margin_enabled):
                self._page_margin_enabled = next_enabled
                changed = True
        if em is not None:
            next_em = self._normalize_page_margin_em(em)
            if abs(next_em - float(self._page_margin_em)) >= 0.001:
                self._page_margin_em = float(next_em)
                changed = True
        if not changed:
            self._sync_page_margin_controls()
            return False
        self._sync_page_margin_controls()
        self._apply_view_document_style()
        return True

    @staticmethod
    def _canonical_markdown(text: str) -> str:
        normalized = text.replace("\r\n", "\n").rstrip()
        normalized = CanvasPreviewPane._replace_hr_markers(normalized)
        normalized = CanvasPreviewPane._normalize_inline_code_backslashes(
            normalized
        )
        normalized = CanvasPreviewPane._normalize_ordered_sublist_indent(
            normalized
        )
        normalized = CanvasPreviewPane._normalize_table_row_spacing(normalized)
        normalized = CanvasPreviewPane._normalize_pure_pipe_table_blocks(normalized)
        return CanvasPreviewPane._normalize_table_column_mismatch(normalized)

    @classmethod
    def _markdown_for_render(cls, text: str) -> str:
        """
        Prepare markdown for HTML display without structural rewrites.

        Canonical normalization is intended for HTML->Markdown roundtrips and
        can otherwise alter list/paragraph structure in pure preview mode.
        """
        normalized = str(text or "").replace("\r\n", "\n")
        normalized = cls._replace_hr_markers(normalized)
        normalized = cls._inject_render_soft_break_tags(normalized)
        return cls._inject_render_spacers_for_extra_blank_lines(normalized)

    @classmethod
    def _escape_internal_word_asterisks(cls, text: str) -> str:
        """
        Escape star-in-word forms (e.g. Kuenstler*innen) to avoid accidental
        emphasis parsing while preserving visible '*' in markdown/preview.
        """
        return cls._INTERNAL_WORD_STAR_RE.sub(r"\\*", str(text or ""))

    @classmethod
    def _replace_hr_markers(cls, text: str) -> str:
        pattern = rf"(?m)^[ \t]*{re.escape(cls._HR_MARKER)}[ \t]*$"
        return re.sub(pattern, "- - -", text)

    @classmethod
    def _inject_render_soft_break_tags(cls, text: str) -> str:
        """
        Preserve user-authored single line breaks in plain paragraphs.

        Qt's Markdown parser collapses single newlines inside a paragraph to
        spaces on roundtrip (`setMarkdown()` -> `toMarkdown()`). For preview
        editing we render such breaks as markdown hard-break markers (`\\`),
        so formatting actions do not unexpectedly join source lines.
        """
        lines = str(text or "").split("\n")
        if len(lines) < 2:
            return str(text or "")

        in_fence = False
        fence_char = ""
        fence_len = 0

        def is_plain_paragraph_line(line: str, *, in_code_fence: bool) -> bool:
            if in_code_fence:
                return False
            raw = str(line or "")
            stripped = raw.strip()
            if not stripped:
                return False
            if cls._line_is_blank_like(raw):
                return False
            if re.match(r"^([`~]{3,})", stripped):
                return False
            if re.match(r"^#{1,6}\s+", stripped):
                return False
            if raw.startswith("    ") or raw.startswith("\t"):
                return False
            if re.match(r"^\s*>", raw):
                return False
            if cls._BULLET_ITEM_RE.match(raw) is not None:
                return False
            if cls._ORDERED_ITEM_RE.match(raw) is not None:
                return False
            if re.match(r"^\s*[-*_]{3,}\s*$", raw):
                return False
            if re.match(r"^\s*\|", raw):
                return False
            if re.match(r"^\s*<[^>]+>\s*$", raw):
                return False
            return True

        def has_hard_break_marker(line: str) -> bool:
            stripped_right = str(line or "").rstrip()
            if stripped_right.endswith("\\"):
                return True
            return bool(re.search(r"<br\s*/?>\s*$", stripped_right, flags=re.I))

        out: list[str] = []
        total = len(lines)
        for idx, line in enumerate(lines):
            raw = str(line or "")
            stripped = raw.lstrip()
            fence_match = re.match(r"^([`~]{3,})", stripped)
            if fence_match is not None:
                marker = fence_match.group(1)
                marker_char = marker[0]
                marker_len = len(marker)
                if not in_fence:
                    in_fence = True
                    fence_char = marker_char
                    fence_len = marker_len
                elif marker_char == fence_char and marker_len >= fence_len:
                    in_fence = False
                    fence_char = ""
                    fence_len = 0
                out.append(raw)
                continue

            append_line = raw
            if idx < (total - 1):
                next_raw = str(lines[idx + 1] or "")
                if (
                    is_plain_paragraph_line(raw, in_code_fence=in_fence)
                    and is_plain_paragraph_line(next_raw, in_code_fence=in_fence)
                    and not has_hard_break_marker(raw)
                ):
                    append_line = f"{raw}\\"
            out.append(append_line)

        return "\n".join(out)

    @classmethod
    def _inject_render_spacers_for_extra_blank_lines(cls, text: str) -> str:
        lines = str(text or "").split("\n")
        out: list[str] = []
        blank_run: list[str] = []
        in_fence = False
        fence_char = ""
        fence_len = 0

        def flush_blank_run():
            nonlocal blank_run
            if not blank_run:
                return
            has_existing_spacer = any(
                cls._BLANK_LINE_SENTINEL in str(line or "")
                for line in blank_run
            )
            if has_existing_spacer:
                # Stored preview spacers must be render-idempotent; otherwise
                # format actions in HTML view multiply blank gaps each cycle.
                out.extend(blank_run)
            else:
                out.append("")
                for _ in range(max(0, len(blank_run) - 1)):
                    out.append(cls._BLANK_LINE_SENTINEL)
                    out.append("")
            blank_run = []

        for line in lines:
            stripped = str(line or "").lstrip()
            fence_match = re.match(r"^([`~]{3,})", stripped)
            if fence_match is not None:
                marker = fence_match.group(1)
                marker_char = marker[0]
                marker_len = len(marker)
                flush_blank_run()
                if not in_fence:
                    in_fence = True
                    fence_char = marker_char
                    fence_len = marker_len
                elif marker_char == fence_char and marker_len >= fence_len:
                    in_fence = False
                    fence_char = ""
                    fence_len = 0
                out.append(line)
                continue

            if in_fence:
                flush_blank_run()
                out.append(line)
                continue

            if cls._line_is_blank_like(line):
                blank_run.append(line)
                continue

            flush_blank_run()
            out.append(line)

        flush_blank_run()
        return "\n".join(out)

    @staticmethod
    def _normalize_inline_code_backslashes(text: str) -> str:
        """
        Stabilize inline-code backslashes across Qt Markdown roundtrips.

        QTextDocument.toMarkdown() currently over-escapes backslashes inside
        inline code spans. Repeated setMarkdown()/toMarkdown() cycles then
        multiply them (`\\` -> `\\\\` -> ...). We collapse even-length runs
        in single-backtick code spans back to their minimal representation.
        """

        def collapse_runs(segment: str) -> str:
            out: list[str] = []
            i = 0
            while i < len(segment):
                if segment[i] != "\\":
                    out.append(segment[i])
                    i += 1
                    continue
                j = i
                while j < len(segment) and segment[j] == "\\":
                    j += 1
                run_len = j - i
                if run_len >= 2 and run_len % 2 == 0:
                    out.append("\\" * (run_len // 2))
                else:
                    out.append("\\" * run_len)
                i = j
            return "".join(out)

        def inline_code_repl(match: re.Match[str]) -> str:
            return f"`{collapse_runs(match.group(1))}`"

        return re.sub(r"`([^`\n]*)`", inline_code_repl, text)

    @classmethod
    def _normalize_ordered_sublist_indent(cls, text: str) -> str:
        """
        Normalize ordered-list sub bullets to a stable indentation depth.

        Qt returns compact indents (often 2/4 spaces) for nested bullets under
        ordered items. That can flatten levels during roundtrips. We map the
        observed bullet nesting depth to stable Markdown indents:
          level 1 -> ordered_indent + 5
          level 2 -> ordered_indent + 9
          level n -> ordered_indent + 5 + 4*(n-1)
        """
        lines = text.split("\n")
        out: list[str] = []
        ordered_indent: int | None = None
        bullet_indent_stack: list[int] = []

        for line in lines:
            raw = line.rstrip()
            stripped = raw.strip()
            if not stripped:
                out.append("")
                continue

            ordered_match = cls._ORDERED_ITEM_RE.match(raw)
            if ordered_match is not None:
                ordered_indent = len(ordered_match.group(1))
                bullet_indent_stack = []
                out.append(raw)
                continue

            current_indent = len(raw) - len(raw.lstrip(" "))
            if ordered_indent is not None and current_indent <= ordered_indent:
                ordered_indent = None
                bullet_indent_stack = []

            bullet_match = cls._BULLET_ITEM_RE.match(raw)
            if bullet_match is not None and ordered_indent is not None:
                bullet_indent = len(bullet_match.group(1))
                if bullet_indent <= ordered_indent:
                    ordered_indent = None
                    bullet_indent_stack = []
                    out.append(raw)
                    continue

                if not bullet_indent_stack:
                    level = 1
                    bullet_indent_stack = [bullet_indent]
                else:
                    prev_indent = bullet_indent_stack[-1]
                    if bullet_indent > prev_indent:
                        level = len(bullet_indent_stack) + 1
                        bullet_indent_stack.append(bullet_indent)
                    elif bullet_indent == prev_indent:
                        level = len(bullet_indent_stack)
                    else:
                        while (
                            len(bullet_indent_stack) > 1
                            and bullet_indent < bullet_indent_stack[-1]
                        ):
                            bullet_indent_stack.pop()
                        if bullet_indent > bullet_indent_stack[-1]:
                            level = len(bullet_indent_stack) + 1
                            bullet_indent_stack.append(bullet_indent)
                        else:
                            level = len(bullet_indent_stack)
                            bullet_indent_stack[-1] = bullet_indent

                target_indent = ordered_indent + 5 + ((level - 1) * 4)
                raw = (" " * target_indent) + raw.lstrip()
                out.append(raw)
                continue

            out.append(raw)

        return "\n".join(out)

    @staticmethod
    def _is_markdown_table_row(line: str) -> bool:
        stripped = str(line or "").strip()
        if len(stripped) < 3:
            return False
        if not stripped.startswith("|"):
            return False
        return "|" in stripped[1:]

    @classmethod
    def _normalize_table_row_spacing(cls, text: str) -> str:
        """
        Collapse blank lines between markdown table rows.

        QTextDocument.toMarkdown() can emit empty lines between `|...|` rows
        after rich-text edits. This breaks markdown table parsing. We remove
        only blank separators where both neighboring non-blank lines are table
        rows, and skip fenced code blocks.
        """
        lines = str(text or "").split("\n")
        if len(lines) < 3:
            return str(text or "")

        out: list[str] = []
        in_fence = False
        fence_char = ""
        fence_len = 0
        count = len(lines)
        for idx, line in enumerate(lines):
            raw = str(line or "")
            stripped = raw.lstrip()
            fence_match = re.match(r"^([`~]{3,})", stripped)
            if fence_match is not None:
                marker = fence_match.group(1)
                marker_char = marker[0]
                marker_len = len(marker)
                if not in_fence:
                    in_fence = True
                    fence_char = marker_char
                    fence_len = marker_len
                elif marker_char == fence_char and marker_len >= fence_len:
                    in_fence = False
                    fence_char = ""
                    fence_len = 0
                out.append(raw)
                continue

            if in_fence:
                out.append(raw)
                continue

            if raw.strip():
                out.append(raw)
                continue

            prev_nonblank = ""
            for prev in reversed(out):
                if str(prev or "").strip():
                    prev_nonblank = str(prev or "")
                    break
            next_nonblank = ""
            j = idx + 1
            while j < count:
                candidate = str(lines[j] or "")
                if candidate.strip():
                    next_nonblank = candidate
                    break
                j += 1
            if (
                cls._is_markdown_table_row(prev_nonblank)
                and cls._is_markdown_table_row(next_nonblank)
            ):
                continue
            out.append(raw)

        return "\n".join(out)

    @staticmethod
    def _pure_pipe_row_column_count(line: str) -> int:
        stripped = str(line or "").strip()
        if not stripped:
            return 0
        if re.fullmatch(r"\|+", stripped) is None:
            return 0
        cols = len(stripped) - 1
        if cols <= 0:
            return 0
        return int(cols)

    @classmethod
    def _normalize_pure_pipe_table_blocks(cls, text: str) -> str:
        """
        Convert Qt's blank-table markdown (`||||`) to valid table syntax.

        After rich-text edits, QTextDocument can export empty table rows as
        pure pipe lines and drop the separator row. Such blocks no longer parse
        as markdown tables in the next render pass. We rebuild them into:
          header row + separator row + remaining body rows.
        """
        lines = str(text or "").split("\n")
        if len(lines) < 2:
            return str(text or "")

        out: list[str] = []
        in_fence = False
        fence_char = ""
        fence_len = 0
        count = len(lines)
        idx = 0
        while idx < count:
            raw = str(lines[idx] or "")
            stripped = raw.lstrip()
            fence_match = re.match(r"^([`~]{3,})", stripped)
            if fence_match is not None:
                marker = fence_match.group(1)
                marker_char = marker[0]
                marker_len = len(marker)
                if not in_fence:
                    in_fence = True
                    fence_char = marker_char
                    fence_len = marker_len
                elif marker_char == fence_char and marker_len >= fence_len:
                    in_fence = False
                    fence_char = ""
                    fence_len = 0
                out.append(raw)
                idx += 1
                continue

            if in_fence:
                out.append(raw)
                idx += 1
                continue

            cols = cls._pure_pipe_row_column_count(raw)
            if cols <= 0:
                out.append(raw)
                idx += 1
                continue

            j = idx
            while (
                j < count
                and cls._pure_pipe_row_column_count(lines[j]) == cols
            ):
                j += 1
            block_rows = j - idx
            if block_rows >= 2:
                header = "| " + " | ".join([" "] * cols) + " |"
                separator = "| " + " | ".join(["---"] * cols) + " |"
                out.append(header)
                out.append(separator)
                body_count = max(0, block_rows - 2)
                if body_count > 0:
                    body_row = "| " + " | ".join([" "] * cols) + " |"
                    for _ in range(body_count):
                        out.append(body_row)
            else:
                out.append(raw)
            idx = j

        return "\n".join(out)

    @staticmethod
    def _split_markdown_table_cells(line: str) -> list[str]:
        stripped = str(line or "").strip()
        if stripped.startswith("|"):
            stripped = stripped[1:]
        if stripped.endswith("|"):
            stripped = stripped[:-1]
        return [part.strip() for part in stripped.split("|")]

    @staticmethod
    def _format_markdown_table_row(cells: list[str]) -> str:
        safe = [str(cell or "").strip() for cell in list(cells or [])]
        return "| " + " | ".join(safe) + " |"

    @classmethod
    def _is_markdown_table_separator_row(cls, line: str) -> bool:
        cells = cls._table_separator_cells(line)
        if not cells:
            return False
        return all(str(cell or "").strip() for cell in cells)

    @classmethod
    def _table_separator_cells(cls, line: str) -> list[str] | None:
        if not cls._is_markdown_table_row(line):
            return None
        cells = cls._split_markdown_table_cells(line)
        if not cells:
            return None
        parsed: list[str] = []
        has_rule = False
        for cell in cells:
            token = str(cell or "").strip()
            if not token:
                parsed.append("")
                continue
            if re.fullmatch(r":?-{1,}:?", token) is None:
                return None
            has_rule = True
            parsed.append(token)
        if not has_rule:
            return None
        return parsed

    @classmethod
    def _normalize_table_column_mismatch(cls, text: str) -> str:
        """
        Normalize markdown table rows to a stable column count and spacing.

        Enter/newline edits inside a table cell can produce rows with more
        pipe-separated cells than the table header (e.g. `|C| | |D|`). That
        breaks stable roundtrips in Qt. We fold overflow cells into the first
        column text (as `<br>` joins), repair weak separator rows emitted by
        Qt (e.g. `|-----|||||`), and reformat rows to stable markdown syntax.
        """
        lines = str(text or "").split("\n")
        if len(lines) < 3:
            return str(text or "")

        out: list[str] = []
        in_fence = False
        fence_char = ""
        fence_len = 0
        count = len(lines)
        idx = 0
        while idx < count:
            raw = str(lines[idx] or "")
            stripped = raw.lstrip()
            fence_match = re.match(r"^([`~]{3,})", stripped)
            if fence_match is not None:
                marker = fence_match.group(1)
                marker_char = marker[0]
                marker_len = len(marker)
                if not in_fence:
                    in_fence = True
                    fence_char = marker_char
                    fence_len = marker_len
                elif marker_char == fence_char and marker_len >= fence_len:
                    in_fence = False
                    fence_char = ""
                    fence_len = 0
                out.append(raw)
                idx += 1
                continue

            if in_fence:
                out.append(raw)
                idx += 1
                continue

            if idx + 1 < count and cls._is_markdown_table_row(raw):
                sep_cells = cls._table_separator_cells(lines[idx + 1])
                if sep_cells is None:
                    out.append(raw)
                    idx += 1
                    continue

                header_raw_cells = cls._split_markdown_table_cells(raw)
                cols = max(1, len(header_raw_cells), len(sep_cells))
                row_start = idx + 2
                row_end = row_start
                while row_end < count and cls._is_markdown_table_row(lines[row_end]):
                    row_end += 1

                def normalize_cells(raw_cells: list[str]) -> list[str]:
                    cells = [str(cell or "").strip() for cell in raw_cells]
                    if len(cells) < cols:
                        cells.extend([""] * (cols - len(cells)))
                        return cells
                    if len(cells) == cols:
                        return cells
                    if cols == 1:
                        merged = "<br>".join(
                            part for part in cells if str(part or "").strip()
                        ).strip()
                        return [merged]
                    head_len = len(cells) - (cols - 1)
                    first_parts = cells[:head_len]
                    tail = cells[-(cols - 1):]
                    first = "<br>".join(
                        part for part in first_parts if str(part or "").strip()
                    ).strip()
                    return [first, *tail]

                def normalize_separator(raw_cells: list[str]) -> list[str]:
                    cells = [str(cell or "").strip() for cell in raw_cells]
                    if len(cells) < cols:
                        cells.extend([""] * (cols - len(cells)))
                    elif len(cells) > cols:
                        cells = cells[:cols]
                    normalized_sep: list[str] = []
                    for token in cells:
                        current = str(token or "").strip()
                        if not current:
                            normalized_sep.append("---")
                            continue
                        if re.fullmatch(r":?-{1,}:?", current) is None:
                            normalized_sep.append("---")
                            continue
                        left_colon = current.startswith(":")
                        right_colon = current.endswith(":")
                        if left_colon and right_colon:
                            normalized_sep.append(":---:")
                            continue
                        if left_colon:
                            normalized_sep.append(":---")
                            continue
                        if right_colon:
                            normalized_sep.append("---:")
                            continue
                        normalized_sep.append("---")
                    return normalized_sep

                header_cells = normalize_cells(header_raw_cells)
                out.append(cls._format_markdown_table_row(header_cells))
                out.append(cls._format_markdown_table_row(normalize_separator(sep_cells)))
                idx = row_start
                while idx < row_end:
                    row_cells = normalize_cells(
                        cls._split_markdown_table_cells(lines[idx])
                    )
                    out.append(cls._format_markdown_table_row(row_cells))
                    idx += 1
                continue

            out.append(raw)
            idx += 1

        return "\n".join(out)

    @classmethod
    def _line_is_blank_like(cls, line: str) -> bool:
        # Preserve visually empty spacer paragraphs as blank-like.
        token = str(line or "").replace("\u00A0", " ").replace("\u200B", "")
        return not token.strip()

    @classmethod
    def _nonempty_normalized_rows(
        cls,
        text: str,
    ) -> list[tuple[str, int, int]]:
        lines = str(text or "").replace("\r\n", "\n").split("\n")
        rows: list[tuple[str, int, int]] = []
        count = len(lines)
        i = 0
        while i < count:
            token = cls._normalize_markdown_line(lines[i]).casefold()
            if not token:
                i += 1
                continue
            j = i + 1
            gap = 0
            while j < count and cls._line_is_blank_like(lines[j]):
                gap += 1
                j += 1
            rows.append((token, i, gap))
            i = j
        return rows

    @classmethod
    def _restore_extra_blank_lines_from_plaintext(
        cls,
        markdown_text: str,
        plain_text: str,
    ) -> str:
        """
        Restore user-added extra blank paragraphs from HTML editor input.

        Qt's toMarkdown() collapses repeated empty paragraphs. We preserve
        additional blank lines by inserting invisible spacer paragraphs between
        blocks where plain-text block gaps are larger than the markdown gap.
        """
        md = str(markdown_text or "").replace("\r\n", "\n")
        plain = str(plain_text or "").replace("\r\n", "\n")
        if not md or not plain:
            return md

        md_rows = cls._nonempty_normalized_rows(md)
        plain_rows = cls._nonempty_normalized_rows(plain)
        if len(md_rows) < 2 or len(md_rows) != len(plain_rows):
            return md
        if any(md_rows[idx][0] != plain_rows[idx][0] for idx in range(len(md_rows))):
            return md

        lines = md.split("\n")
        offset = 0
        changed = False
        for idx in range(len(md_rows) - 1):
            start = int(md_rows[idx][1]) + offset
            end = int(md_rows[idx + 1][1]) + offset
            if end <= start:
                continue
            region = lines[start + 1:end]
            if not region:
                continue
            if not all(cls._line_is_blank_like(line) for line in region):
                continue

            desired_extra = max(0, int(plain_rows[idx][2]))
            target_region = [""]
            for _ in range(desired_extra):
                target_region.append(cls._BLANK_LINE_SENTINEL)
                target_region.append("")

            if region == target_region:
                continue
            lines[start + 1:end] = target_region
            offset += len(target_region) - len(region)
            changed = True

        if not changed:
            return md
        return "\n".join(lines)

    @classmethod
    def _restore_blank_like_runs_from_reference(
        cls,
        markdown_text: str,
        reference_markdown: str,
    ) -> str:
        """
        Restore blank-like separator runs from a markdown reference text.

        Used for preview toolbar formatting actions: Qt may rewrite soft line
        breaks into blank-line-separated blocks during toMarkdown() export.
        When token order is unchanged, we transplant only the inter-row blank
        runs from the reference so original line wrapping is preserved.
        """
        md = str(markdown_text or "").replace("\r\n", "\n")
        ref = str(reference_markdown or "").replace("\r\n", "\n")
        if not md or not ref:
            return md

        md_rows = cls._nonempty_normalized_rows(md)
        ref_rows = cls._nonempty_normalized_rows(ref)
        if len(md_rows) < 2 or len(md_rows) != len(ref_rows):
            return md
        if any(md_rows[idx][0] != ref_rows[idx][0] for idx in range(len(md_rows))):
            return md

        md_lines = md.split("\n")
        ref_lines = ref.split("\n")
        offset = 0
        changed = False
        for idx in range(len(md_rows) - 1):
            md_start = int(md_rows[idx][1]) + offset
            md_end = int(md_rows[idx + 1][1]) + offset
            ref_start = int(ref_rows[idx][1])
            ref_end = int(ref_rows[idx + 1][1])
            if md_end <= md_start:
                continue

            md_region = md_lines[md_start + 1:md_end]
            ref_region = ref_lines[ref_start + 1:ref_end]
            if not all(cls._line_is_blank_like(line) for line in md_region):
                continue
            if not all(cls._line_is_blank_like(line) for line in ref_region):
                continue
            if md_region == ref_region:
                continue

            md_lines[md_start + 1:md_end] = ref_region
            offset += len(ref_region) - len(md_region)
            changed = True

        if not changed:
            return md
        return "\n".join(md_lines)

    @classmethod
    def _is_plain_paragraph_line_for_wrap_restore(cls, line: str) -> bool:
        raw = str(line or "")
        stripped = raw.strip()
        if not stripped:
            return False
        if cls._line_is_blank_like(raw):
            return False
        if re.match(r"^([`~]{3,})", stripped):
            return False
        if re.match(r"^#{1,6}\s+", stripped):
            return False
        if raw.startswith("    ") or raw.startswith("\t"):
            return False
        if re.match(r"^\s*>", raw):
            return False
        if cls._BULLET_ITEM_RE.match(raw) is not None:
            return False
        if cls._ORDERED_ITEM_RE.match(raw) is not None:
            return False
        if re.match(r"^\s*[-*_]{3,}\s*$", raw):
            return False
        if re.match(r"^\s*\|", raw):
            return False
        if re.match(r"^\s*<[^>]+>\s*$", raw):
            return False
        return True

    @classmethod
    def _restore_soft_wrapped_plain_lines_from_reference(
        cls,
        markdown_text: str,
        reference_markdown: str,
    ) -> str:
        """
        Undo Qt soft-wrap artifacts for plain paragraphs.

        QTextDocument.toMarkdown() may rewrite a single long paragraph line
        into multiple hard line breaks. If a non-blank block is plain text in
        both versions and collapses to the same content, restore the original
        block line layout from the markdown reference.
        """
        md = str(markdown_text or "").replace("\r\n", "\n")
        ref = str(reference_markdown or "").replace("\r\n", "\n")
        if not md or not ref:
            return md

        md_lines = md.split("\n")
        ref_lines = ref.split("\n")

        def nonblank_blocks(lines: list[str]) -> list[tuple[int, int]]:
            blocks: list[tuple[int, int]] = []
            idx = 0
            count = len(lines)
            while idx < count:
                while idx < count and cls._line_is_blank_like(lines[idx]):
                    idx += 1
                if idx >= count:
                    break
                start = idx
                while idx < count and not cls._line_is_blank_like(lines[idx]):
                    idx += 1
                blocks.append((start, idx))
            return blocks

        md_blocks = nonblank_blocks(md_lines)
        ref_blocks = nonblank_blocks(ref_lines)
        if not md_blocks or len(md_blocks) != len(ref_blocks):
            return md

        def collapse_block(lines: list[str]) -> str:
            return re.sub(r"\s+", " ", " ".join(lines)).strip()

        changed = False
        offset = 0
        for block_index, (md_start_raw, md_end_raw) in enumerate(md_blocks):
            ref_start, ref_end = ref_blocks[block_index]
            md_start = md_start_raw + offset
            md_end = md_end_raw + offset
            if md_end <= md_start or ref_end <= ref_start:
                continue

            md_block = md_lines[md_start:md_end]
            ref_block = ref_lines[ref_start:ref_end]
            if len(md_block) <= 1 or len(ref_block) != 1:
                continue
            if not all(
                cls._is_plain_paragraph_line_for_wrap_restore(line)
                for line in md_block
            ):
                continue
            if not all(
                cls._is_plain_paragraph_line_for_wrap_restore(line)
                for line in ref_block
            ):
                continue
            if collapse_block(md_block).casefold() != collapse_block(ref_block).casefold():
                continue
            if md_block == ref_block:
                continue

            md_lines[md_start:md_end] = ref_block
            offset += len(ref_block) - len(md_block)
            changed = True

        if not changed:
            return md
        return "\n".join(md_lines)

    @staticmethod
    def _line_has_explicit_hard_break_marker(line: str) -> bool:
        stripped_right = str(line or "").rstrip()
        if stripped_right.endswith("\\"):
            return True
        if re.search(r"<br\s*/?>\s*$", stripped_right, flags=re.IGNORECASE):
            return True
        # Markdown hard break via two trailing spaces.
        return bool(re.search(r"[ ]{2,}$", str(line or "")))

    @classmethod
    def _unwrap_soft_wrapped_plain_paragraphs(cls, markdown_text: str) -> str:
        """
        Collapse Qt-introduced soft-wrap line breaks in plain paragraphs.

        QTextDocument.toMarkdown() may hard-wrap long paragraph lines at a
        visual width. Those breaks are not semantic paragraph boundaries and
        should not be persisted back into source markdown.
        """
        md = str(markdown_text or "").replace("\r\n", "\n")
        if not md:
            return md
        lines = md.split("\n")
        out: list[str] = []
        idx = 0
        total = len(lines)
        while idx < total:
            line = lines[idx]
            if cls._line_is_blank_like(line):
                out.append(line)
                idx += 1
                continue

            start = idx
            while idx < total and not cls._line_is_blank_like(lines[idx]):
                idx += 1
            block = lines[start:idx]
            if len(block) <= 1:
                out.extend(block)
                continue
            if not all(
                cls._is_plain_paragraph_line_for_wrap_restore(part)
                for part in block
            ):
                out.extend(block)
                continue
            if any(
                cls._line_has_explicit_hard_break_marker(part)
                for part in block[:-1]
            ):
                out.extend(block)
                continue

            merged = re.sub(r"\s+", " ", " ".join(part.strip() for part in block)).strip()
            out.append(merged)
        return "\n".join(out)

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

    def _set_heading_level(self, level: int):
        def apply():
            cursor = self._view.textCursor()
            cursor.beginEditBlock()
            block_format = cursor.blockFormat()
            block_format.setHeadingLevel(level)
            cursor.setBlockFormat(block_format)
            cursor.endEditBlock()
            self._view.setTextCursor(cursor)

        self._apply_preview_format_change(apply)

    def _clear_heading(self):
        def apply():
            cursor = self._view.textCursor()
            cursor.beginEditBlock()
            block_format = cursor.blockFormat()
            block_format.setHeadingLevel(0)
            cursor.setBlockFormat(block_format)

            # Qt may keep heading bold formatting on the block text when
            # heading level is removed; normalize back to paragraph weight.
            block_cursor = QTextCursor(cursor)
            block_cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
            char_format = QTextCharFormat(block_cursor.charFormat())
            char_format.setFontWeight(int(QFont.Weight.Normal))
            block_cursor.mergeCharFormat(char_format)

            cursor.endEditBlock()
            self._view.setTextCursor(cursor)

        self._apply_preview_format_change(apply)

    def _trimmed_selection_bounds(self) -> tuple[int, int] | None:
        cursor = self._view.textCursor()
        if not cursor.hasSelection():
            return None
        start = int(cursor.selectionStart())
        end = int(cursor.selectionEnd())
        if end <= start:
            return None
        doc = self._view.document()
        while start < end:
            ch = str(doc.characterAt(start) or "")
            if ch and (not ch.isspace()):
                break
            start += 1
        while end > start:
            ch = str(doc.characterAt(end - 1) or "")
            if ch and (not ch.isspace()):
                break
            end -= 1
        if end <= start:
            return None
        return start, end

    def _selection_all_nonspace_chars_match(
        self,
        start: int,
        end: int,
        matcher: Callable[[QTextCharFormat], bool],
    ) -> tuple[bool, bool]:
        doc = self._view.document()
        probe = QTextCursor(doc)
        all_match = True
        has_nonspace = False
        for pos in range(int(start), int(end)):
            ch = str(doc.characterAt(pos) or "")
            if (not ch) or ch.isspace():
                continue
            has_nonspace = True
            probe.setPosition(min(pos + 1, doc.characterCount() - 1))
            if not matcher(probe.charFormat()):
                all_match = False
                break
        return all_match, has_nonspace

    def _expand_selection_to_formatted_adjacent_whitespace(
        self,
        start: int,
        end: int,
        matcher: Callable[[QTextCharFormat], bool],
    ) -> tuple[int, int]:
        doc = self._view.document()
        probe = QTextCursor(doc)
        left = int(start)
        right = int(end)
        while left > 0:
            ch = str(doc.characterAt(left - 1) or "")
            if (not ch) or (not ch.isspace()):
                break
            probe.setPosition(min(left, doc.characterCount() - 1))
            if not matcher(probe.charFormat()):
                break
            left -= 1
        max_index = max(0, doc.characterCount() - 1)
        while right < max_index:
            ch = str(doc.characterAt(right) or "")
            if (not ch) or (not ch.isspace()):
                break
            probe.setPosition(min(right + 1, max_index))
            if not matcher(probe.charFormat()):
                break
            right += 1
        return left, right

    def _expand_selection_to_bridge_formatted_neighbors(
        self,
        start: int,
        end: int,
        matcher: Callable[[QTextCharFormat], bool],
    ) -> tuple[int, int]:
        doc = self._view.document()
        probe = QTextCursor(doc)
        left = int(start)
        right = int(end)
        max_index = max(0, doc.characterCount() - 1)

        left_ws_start = left
        while left_ws_start > 0:
            ch = str(doc.characterAt(left_ws_start - 1) or "")
            if (not ch) or (not ch.isspace()):
                break
            left_ws_start -= 1
        if left_ws_start < left and left_ws_start > 0:
            probe.setPosition(min(left_ws_start, max_index))
            if matcher(probe.charFormat()):
                left = left_ws_start

        right_ws_end = right
        while right_ws_end < max_index:
            ch = str(doc.characterAt(right_ws_end) or "")
            if (not ch) or (not ch.isspace()):
                break
            right_ws_end += 1
        if right_ws_end > right and right_ws_end < max_index:
            probe.setPosition(min(right_ws_end + 1, max_index))
            if matcher(probe.charFormat()):
                right = right_ws_end

        return left, right

    def _toggle_inline_char_format(
        self,
        *,
        matcher: Callable[[QTextCharFormat], bool],
        apply_state: Callable[[QTextCharFormat, bool], None],
    ):
        cursor = self._view.textCursor()
        if not cursor.hasSelection():
            fmt = self._view.currentCharFormat()
            apply_state(fmt, not matcher(fmt))
            self._view.mergeCurrentCharFormat(fmt)
            return

        bounds = self._trimmed_selection_bounds()
        if bounds is None:
            return
        start, end = bounds
        all_match, has_nonspace = self._selection_all_nonspace_chars_match(
            start,
            end,
            matcher,
        )
        if not has_nonspace:
            return
        target_enabled = not all_match
        if target_enabled:
            start, end = self._expand_selection_to_bridge_formatted_neighbors(
                start,
                end,
                matcher,
            )
        else:
            start, end = self._expand_selection_to_formatted_adjacent_whitespace(
                start,
                end,
                matcher,
            )

        selection = QTextCursor(self._view.document())
        selection.setPosition(int(start))
        selection.setPosition(int(end), QTextCursor.MoveMode.KeepAnchor)
        self._view.setTextCursor(selection)
        fmt = QTextCharFormat()
        apply_state(fmt, target_enabled)
        selection.mergeCharFormat(fmt)
        self._view.setTextCursor(selection)

    def _toggle_bold(self):
        def apply():
            self._toggle_inline_char_format(
                matcher=lambda fmt: fmt.fontWeight() >= int(QFont.Weight.Bold),
                apply_state=lambda fmt, enabled: fmt.setFontWeight(
                    int(QFont.Weight.Bold)
                    if enabled
                    else int(QFont.Weight.Normal)
                ),
            )

        self._apply_preview_format_change(apply)

    def _toggle_italic(self):
        def apply():
            self._toggle_inline_char_format(
                matcher=lambda fmt: bool(fmt.fontItalic()),
                apply_state=lambda fmt, enabled: fmt.setFontItalic(bool(enabled)),
            )

        self._apply_preview_format_change(apply)

    def _toggle_block_quote(self):
        def apply():
            cursor = self._view.textCursor()
            block_format = cursor.blockFormat()
            current_level = int(
                block_format.property(QTextFormat.Property.BlockQuoteLevel) or 0
            )
            block_format.setProperty(
                QTextFormat.Property.BlockQuoteLevel,
                0 if current_level > 0 else 1,
            )
            cursor.setBlockFormat(block_format)
            self._view.setTextCursor(cursor)

        self._apply_preview_format_change(apply)

    def _toggle_bullet_list(self):
        self._toggle_list_style(QTextListFormat.Style.ListDisc)

    def _toggle_numbered_list(self):
        self._toggle_list_style(QTextListFormat.Style.ListDecimal)

    @staticmethod
    def _build_markdown_table(rows: int, cols: int) -> str:
        r = max(1, int(rows))
        c = max(1, int(cols))
        header = "| " + " | ".join([" "] * c) + " |"
        separator = "| " + " | ".join(["---"] * c) + " |"
        body_row = "| " + " | ".join([" "] * c) + " |"
        body = [body_row for _ in range(max(0, r - 1))]
        lines = [header, separator, *body]
        return "\n".join(lines)

    def _insert_markdown_table(self, rows: int, cols: int):
        def apply():
            cursor = self._view.textCursor()
            cursor.beginEditBlock()
            if cursor.hasSelection():
                cursor.removeSelectedText()

            table_markdown = self._build_markdown_table(rows, cols)
            if cursor.positionInBlock() != 0:
                cursor.insertBlock()
            cursor.insertText(table_markdown)
            cursor.insertBlock()
            cursor.endEditBlock()
            self._view.setTextCursor(cursor)

        self._apply_preview_format_change(apply)

    def _show_table_insert_menu(self):
        if not self._allow_editing or self._structured_view_active:
            return
        button = self._table_insert_btn
        if button is None:
            return
        if self._table_insert_menu is not None:
            try:
                self._table_insert_menu.close()
            except Exception:
                pass

        menu = QMenu(self)
        menu.setToolTipsVisible(False)
        picker = _TableInsertPicker(max_rows=12, max_cols=12, parent=menu)

        def _insert_selected(rows: int, cols: int):
            try:
                menu.close()
            except Exception:
                pass
            self._insert_markdown_table(rows, cols)

        picker.size_chosen.connect(_insert_selected)
        action = QWidgetAction(menu)
        action.setDefaultWidget(picker)
        menu.addAction(action)

        def _clear_menu_ref():
            self._table_insert_menu = None

        menu.aboutToHide.connect(_clear_menu_ref)
        self._table_insert_menu = menu
        pos = button.mapToGlobal(QPoint(0, button.height()))
        menu.popup(pos)

    def _insert_horizontal_rule(self):
        def apply():
            cursor = self._view.textCursor()
            cursor.beginEditBlock()
            cursor.insertBlock()
            cursor.insertText(self._HR_MARKER)
            cursor.insertBlock()
            cursor.endEditBlock()
            self._view.setTextCursor(cursor)

        self._apply_preview_format_change(apply)

    def _indent_list_item(self):
        self._adjust_list_indent(+1)

    def _outdent_list_item(self):
        self._adjust_list_indent(-1)

    def _adjust_list_indent(self, delta: int):
        def apply():
            cursor = self._view.textCursor()
            current_list = cursor.currentList()
            if current_list is None:
                if delta <= 0:
                    return
                list_format = QTextListFormat()
                list_format.setStyle(QTextListFormat.Style.ListDisc)
                list_format.setIndent(2)
                cursor.createList(list_format)
                self._view.setTextCursor(cursor)
                return

            list_format = QTextListFormat(current_list.format())
            old_indent = max(1, list_format.indent())
            new_indent = max(1, old_indent + delta)
            if new_indent == old_indent:
                return
            list_format.setIndent(new_indent)
            cursor.createList(list_format)
            self._view.setTextCursor(cursor)

        self._apply_preview_format_change(apply)

    def _toggle_list_style(self, style: QTextListFormat.Style):
        def apply():
            cursor = self._view.textCursor()
            current_list = cursor.currentList()
            cursor.beginEditBlock()
            if (
                current_list is not None
                and current_list.format().style() == style
            ):
                block_format = cursor.blockFormat()
                block_format.setObjectIndex(-1)
                cursor.setBlockFormat(block_format)
            else:
                list_format = QTextListFormat()
                list_format.setStyle(style)
                cursor.createList(list_format)
            cursor.endEditBlock()
            self._view.setTextCursor(cursor)

        self._apply_preview_format_change(apply)

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

    @staticmethod
    def _normalize_markdown_line(line: str) -> str:
        """Map a markdown source line to plain text for preview matching."""
        text = str(line or "").replace("\u200B", "").replace("\u00A0", " ").strip()
        if not text:
            return ""
        text = re.sub(r"^#{1,6}\s*", "", text)
        text = re.sub(r"^\s{0,3}(?:>\s?)+", "", text)
        text = re.sub(r"^\s{0,3}(?:[-*+]|\d+[.)])\s+", "", text)
        text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", text)
        text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
        text = re.sub(r"`([^`]*)`", r"\1", text)
        text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
        text = re.sub(r"__([^_]+)__", r"\1", text)
        text = re.sub(r"\*([^*]+)\*", r"\1", text)
        text = re.sub(r"_([^_]+)_", r"\1", text)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

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

    def _expand_all_graph_nodes(self):
        spec = self._structured_graph_spec
        if spec is None:
            return
        if not self._graph_collapsed_ids:
            return
        self._graph_collapsed_ids.clear()
        self._render_structured_graph_scene(spec)

    def _collapse_all_graph_nodes(self):
        spec = self._structured_graph_spec
        if spec is None:
            return
        include_edges = spec.kind == "graph"
        collapsed = self._expandable_graph_nodes(
            spec,
            include_edges=include_edges,
        )
        if collapsed == self._graph_collapsed_ids:
            return
        self._graph_collapsed_ids = collapsed
        self._render_structured_graph_scene(spec)

    def _clear_graph_focus(self):
        spec = self._structured_graph_spec
        if spec is None:
            return
        if not self._graph_focus_node_id:
            return
        self._graph_focus_node_id = ""
        self._render_structured_graph_scene(spec)

    def _visible_node_items(self) -> dict[str, _GraphNodeItem]:
        scene = self._graph_scene
        if scene is None:
            return {}
        out: dict[str, _GraphNodeItem] = {}
        for item in scene.items():
            if isinstance(item, _GraphNodeItem):
                out[item._node_id] = item  # pylint: disable=protected-access
        return out

    def _optimize_visible_graph_layout(self):
        spec = self._structured_graph_spec
        scene = self._graph_scene
        view = self._graph_view
        if spec is None or scene is None or view is None:
            return
        if nx is None:
            return
        node_items = self._visible_node_items()
        if len(node_items) < 2:
            return

        visible_nodes, visible_edges = self._visible_graph_data(spec)
        visible_set = {
            node_id
            for node_id in visible_nodes
            if node_id in node_items
        }
        if len(visible_set) < 2:
            return

        graph = nx.Graph()
        graph.add_nodes_from(sorted(visible_set))
        for source_id, target_id, _label in visible_edges:
            if source_id in visible_set and target_id in visible_set:
                graph.add_edge(source_id, target_id)

        current_pos = {
            node_id: (
                float(node_items[node_id].center_pos().x()),
                float(node_items[node_id].center_pos().y()),
            )
            for node_id in graph.nodes
        }
        scene_rect = scene.sceneRect()
        if scene_rect.width() <= 1.0 or scene_rect.height() <= 1.0:
            scene_rect = scene.itemsBoundingRect().adjusted(-80, -80, 80, 80)
            if scene_rect.width() <= 1.0 or scene_rect.height() <= 1.0:
                scene_rect = scene.itemsBoundingRect().adjusted(-180, -140, 180, 140)

        node_count = max(2, graph.number_of_nodes())
        area = max(1.0, float(scene_rect.width()) * float(scene_rect.height()))
        k_value = max(58.0, min(230.0, math.sqrt(area / float(node_count)) * 0.42))

        try:
            target_pos = nx.spring_layout(
                graph,
                pos=current_pos,
                seed=17,
                k=k_value,
                iterations=180,
                scale=None,
            )
        except Exception:
            return

        blend = 0.42
        margin = 18.0
        for node_id, item in node_items.items():
            if node_id not in target_pos:
                continue
            current_center = item.center_pos()
            target = target_pos[node_id]
            target_x = float(target[0])
            target_y = float(target[1])
            center_x = ((1.0 - blend) * float(current_center.x())) + (blend * target_x)
            center_y = ((1.0 - blend) * float(current_center.y())) + (blend * target_y)

            width = float(item.rect().width())
            height = float(item.rect().height())
            half_w = width / 2.0
            half_h = height / 2.0
            center_x = max(
                float(scene_rect.left()) + half_w + margin,
                min(float(scene_rect.right()) - half_w - margin, center_x),
            )
            center_y = max(
                float(scene_rect.top()) + half_h + margin,
                min(float(scene_rect.bottom()) - half_h - margin, center_y),
            )
            item.setPos(center_x - half_w, center_y - half_h)
            self._graph_manual_positions[node_id] = QPointF(center_x, center_y)

        bounds = scene.itemsBoundingRect().adjusted(-36.0, -36.0, 36.0, 36.0)
        if bounds.width() > 1.0 and bounds.height() > 1.0:
            scene.setSceneRect(bounds)
        focus_item = node_items.get(self._graph_focus_node_id)
        if focus_item is not None:
            view.centerOn(focus_item.center_pos())

    def _reflow_visible_graph_layout(self):
        spec = self._structured_graph_spec
        if spec is None:
            return
        visible_nodes, _visible_edges = self._visible_graph_data(spec)
        if not visible_nodes:
            return
        for node_id in visible_nodes:
            self._graph_manual_positions.pop(node_id, None)
        self._graph_layout_nonce += 1
        self._render_structured_graph_scene(spec)

    def _on_graph_node_clicked(self, node_id: str, open_link: bool):
        spec = self._structured_graph_spec
        if spec is None:
            return
        node = spec.nodes.get(str(node_id or ""))
        if node is None:
            return
        self._graph_focus_node_id = node.node_id
        self._render_structured_graph_scene(spec)
        if open_link and node.href:
            self._open_href(node.href)

    def _on_graph_node_toggled(self, node_id: str):
        spec = self._structured_graph_spec
        if spec is None:
            return
        node = spec.nodes.get(str(node_id or ""))
        if node is None:
            return
        include_edges = spec.kind == "graph"
        expandable = self._expandable_graph_nodes(spec, include_edges=include_edges)
        if node.node_id in expandable:
            if node.node_id in self._graph_collapsed_ids:
                self._graph_collapsed_ids.discard(node.node_id)
                # MindMap UX: when opening a node, start one level deep and keep
                # descendant branches collapsed until explicitly opened.
                if spec.kind == "mindmap":
                    descendants = self._collect_descendants(
                        spec,
                        start_id=node.node_id,
                        include_edges=False,
                    )
                    collapsed_descendants = {
                        child_id
                        for child_id in descendants
                        if child_id in expandable
                    }
                    self._graph_collapsed_ids.update(collapsed_descendants)
            else:
                self._graph_collapsed_ids.add(node.node_id)
            self._render_structured_graph_scene(spec)
            return
        if node.href:
            self._open_href(node.href)

    def _on_graph_node_moved(self, node_id: str, center: QPointF):
        node_key = str(node_id or "").strip()
        if not node_key:
            return
        self._graph_manual_positions[node_key] = QPointF(center)

    @staticmethod
    def _graph_child_map(
        spec: GraphSpec,
        *,
        include_edges: bool,
    ) -> dict[str, list[str]]:
        nodes = spec.nodes
        out: dict[str, list[str]] = {}
        for node_id, node in nodes.items():
            out[node_id] = [child for child in node.children if child in nodes]
        if include_edges:
            for edge in spec.edges:
                src = edge.source_id
                dst = edge.target_id
                if src not in nodes or dst not in nodes:
                    continue
                bucket = out.setdefault(src, [])
                if dst not in bucket:
                    bucket.append(dst)
        return out

    @classmethod
    def _expandable_graph_nodes(
        cls,
        spec: GraphSpec,
        *,
        include_edges: bool,
    ) -> set[str]:
        child_map = cls._graph_child_map(spec, include_edges=include_edges)
        return {
            node_id
            for node_id, children in child_map.items()
            if children
        }

    @classmethod
    def _collapsed_hidden_nodes(
        cls,
        spec: GraphSpec,
        *,
        collapsed_ids: set[str],
        include_edges: bool,
    ) -> set[str]:
        if not collapsed_ids:
            return set()
        child_map = cls._graph_child_map(spec, include_edges=include_edges)
        hidden: set[str] = set()
        for start in collapsed_ids:
            stack = list(child_map.get(start, []))
            while stack:
                node_id = stack.pop()
                if node_id in hidden:
                    continue
                hidden.add(node_id)
                stack.extend(child_map.get(node_id, []))
        return hidden

    @classmethod
    def _collect_descendants(
        cls,
        spec: GraphSpec,
        *,
        start_id: str,
        include_edges: bool,
    ) -> set[str]:
        nodes = spec.nodes
        if start_id not in nodes:
            return set()
        child_map = cls._graph_child_map(spec, include_edges=include_edges)
        out: set[str] = set()
        stack = list(child_map.get(start_id, []))
        while stack:
            node_id = stack.pop()
            if node_id in out or node_id not in nodes:
                continue
            out.add(node_id)
            stack.extend(child_map.get(node_id, []))
        return out

    @classmethod
    def _initial_collapsed_graph_nodes(
        cls,
        spec: GraphSpec,
    ) -> set[str]:
        nodes = spec.nodes
        if not nodes:
            return set()
        include_edges = spec.kind == "graph"
        child_map = cls._graph_child_map(spec, include_edges=include_edges)
        expandable = {
            node_id
            for node_id, children in child_map.items()
            if children
        }
        if not expandable:
            return set()

        roots = [node_id for node_id in spec.roots if node_id in nodes]
        if not roots:
            roots = [sorted(nodes.keys())[0]]

        depths: dict[str, int] = {}
        queue: deque[tuple[str, int]] = deque((node_id, 0) for node_id in roots)
        while queue:
            node_id, depth = queue.popleft()
            prev = depths.get(node_id)
            if prev is not None and depth >= prev:
                continue
            depths[node_id] = depth
            for child_id in child_map.get(node_id, []):
                if child_id not in nodes:
                    continue
                queue.append((child_id, depth + 1))

        for node_id in sorted(nodes.keys()):
            if node_id not in depths:
                depths[node_id] = 0

        return {
            node_id
            for node_id in expandable
            if depths.get(node_id, 0) >= 1
        }

    @staticmethod
    def _open_href(href: str):
        target = str(href or "").strip()
        if not target:
            return
        if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target):
            QDesktopServices.openUrl(QUrl(target))
            return
        if target.startswith("/"):
            QDesktopServices.openUrl(QUrl.fromLocalFile(target))

    def _visible_graph_data(
        self,
        spec: GraphSpec,
    ) -> tuple[list[str], list[tuple[str, str, str]]]:
        nodes = spec.nodes
        if not nodes:
            return [], []

        roots = [node_id for node_id in spec.roots if node_id in nodes]
        if not roots:
            roots = [sorted(nodes.keys())[0]]

        visible: list[str] = []
        seen: set[str] = set()

        def walk(start_id: str):
            stack = [start_id]
            while stack:
                node_id = stack.pop()
                if node_id in seen or node_id not in nodes:
                    continue
                seen.add(node_id)
                visible.append(node_id)
                node = nodes[node_id]
                if node_id in self._graph_collapsed_ids:
                    continue
                for child_id in reversed(node.children):
                    if child_id in nodes:
                        stack.append(child_id)

        if spec.kind == "graph":
            hidden = self._collapsed_hidden_nodes(
                spec,
                collapsed_ids=self._graph_collapsed_ids,
                include_edges=True,
            )
            visible = [
                node_id
                for node_id in sorted(nodes.keys())
                if node_id not in hidden
            ]
            seen = set(visible)
        else:
            hidden = self._collapsed_hidden_nodes(
                spec,
                collapsed_ids=self._graph_collapsed_ids,
                include_edges=False,
            )
            for root_id in roots:
                walk(root_id)
            for node_id in sorted(nodes.keys()):
                if node_id not in seen:
                    if node_id in hidden:
                        continue
                    walk(node_id)

        visible_set = set(visible)
        edges: list[tuple[str, str, str]] = []
        for edge in spec.edges:
            if edge.source_id not in visible_set or edge.target_id not in visible_set:
                continue
            edges.append((edge.source_id, edge.target_id, edge.label))
        return visible, edges

    def _layout_graph_nodes(
        self,
        *,
        spec: GraphSpec,
        node_ids: list[str],
        edges: list[tuple[str, str, str]],
    ) -> dict[str, QPointF]:
        if not node_ids:
            return {}
        if len(node_ids) == 1:
            return {node_ids[0]: QPointF(0.0, 0.0)}
        if spec.kind == "mindmap":
            return self._layout_mindmap_nodes(spec=spec, node_ids=node_ids)
        return self._layout_knowledge_graph_nodes(
            spec=spec,
            node_ids=node_ids,
            edges=edges,
        )

    @classmethod
    def _layout_mindmap_nodes(
        cls,
        *,
        spec: GraphSpec,
        node_ids: list[str],
    ) -> dict[str, QPointF]:
        visible_set = set(node_ids)
        child_map: dict[str, list[str]] = {}
        for node_id in node_ids:
            node = spec.nodes.get(node_id)
            if node is None:
                child_map[node_id] = []
                continue
            child_map[node_id] = [
                child_id
                for child_id in node.children
                if child_id in visible_set
            ]

        roots: list[str] = [
            node_id
            for node_id in spec.roots
            if node_id in visible_set
        ]
        if not roots:
            roots = [node_ids[0]]

        assigned_children: dict[str, list[str]] = {
            node_id: []
            for node_id in node_ids
        }
        parent_of: dict[str, str] = {}

        def attach(node_id: str, ancestry: set[str]):
            if node_id in ancestry:
                return
            chain = set(ancestry)
            chain.add(node_id)
            for child_id in child_map.get(node_id, []):
                if child_id == node_id:
                    continue
                if child_id in chain:
                    continue
                if child_id in parent_of:
                    continue
                parent_of[child_id] = node_id
                assigned_children[node_id].append(child_id)
                attach(child_id, chain)

        for root_id in roots:
            attach(root_id, set())

        root_set = set(roots)
        for node_id in node_ids:
            if node_id in root_set or node_id in parent_of:
                continue
            roots.append(node_id)
            root_set.add(node_id)
            attach(node_id, set())

        span_cache: dict[str, float] = {}

        def subtree_span(node_id: str, chain: set[str]) -> float:
            cached = span_cache.get(node_id)
            if cached is not None:
                return cached
            if node_id in chain:
                return 1.0
            next_chain = set(chain)
            next_chain.add(node_id)
            children = assigned_children.get(node_id, [])
            if not children:
                span_cache[node_id] = 1.0
                return 1.0
            total = 0.0
            for child_id in children:
                total += subtree_span(child_id, next_chain)
            total = max(1.0, total)
            span_cache[node_id] = total
            return total

        raw_positions: dict[str, tuple[float, float]] = {}

        primary_root = roots[0]
        raw_positions[primary_root] = (0.0, 0.0)

        def place_side(node_id: str, depth: int, side: int, start_y: float) -> float:
            span = subtree_span(node_id, set())
            children = assigned_children.get(node_id, [])
            if not children:
                center_y = start_y + (span / 2.0)
                raw_positions[node_id] = (float(side) * float(depth), center_y)
                return center_y

            cursor = start_y
            child_centers: list[float] = []
            for child_id in children:
                child_span = subtree_span(child_id, set())
                child_center = place_side(child_id, depth + 1, side, cursor)
                child_centers.append(child_center)
                cursor += child_span
            center_y = (
                sum(child_centers) / float(len(child_centers))
                if child_centers
                else start_y + (span / 2.0)
            )
            raw_positions[node_id] = (float(side) * float(depth), center_y)
            return center_y

        root_children = assigned_children.get(primary_root, [])
        right_children = root_children[::2]
        left_children = root_children[1::2]
        if not right_children and left_children:
            right_children, left_children = left_children, []

        def place_root_children(children: list[str], side: int):
            if not children:
                return
            total = sum(subtree_span(child_id, set()) for child_id in children)
            cursor = -total / 2.0
            for child_id in children:
                span = subtree_span(child_id, set())
                place_side(child_id, 1, side, cursor)
                cursor += span

        place_root_children(right_children, 1)
        place_root_children(left_children, -1)

        extra_root_y = 1.4
        for extra_root in roots[1:]:
            if extra_root in raw_positions:
                continue
            span = subtree_span(extra_root, set())
            center_y = extra_root_y + (span / 2.0)
            raw_positions[extra_root] = (0.0, center_y)
            place_side(extra_root, 1, 1, extra_root_y)
            extra_root_y += span + 0.9

        if not raw_positions:
            out: dict[str, QPointF] = {}
            for idx, node_id in enumerate(node_ids):
                out[node_id] = QPointF(float(idx), 0.0)
            return out

        xs = [point[0] for point in raw_positions.values()]
        ys = [point[1] for point in raw_positions.values()]
        center_x = (min(xs) + max(xs)) / 2.0
        center_y = (min(ys) + max(ys)) / 2.0
        fallback_y = (max(ys) if ys else 0.0) + 1.0

        out: dict[str, QPointF] = {}
        spill_idx = 0
        for node_id in node_ids:
            pos = raw_positions.get(node_id)
            if pos is None:
                pos = (0.0 + float(spill_idx), fallback_y)
                spill_idx += 1
            out[node_id] = QPointF(
                float((pos[0] - center_x) * 1.45),
                float((pos[1] - center_y) * 1.05),
            )
        return out

    @staticmethod
    def _layout_knowledge_graph_nodes(
        *,
        spec: GraphSpec,
        node_ids: list[str],
        edges: list[tuple[str, str, str]],
    ) -> dict[str, QPointF]:
        visible_set = set(node_ids)
        children: dict[str, list[str]] = {node_id: [] for node_id in node_ids}
        parents: dict[str, list[str]] = {node_id: [] for node_id in node_ids}
        neighbors: dict[str, set[str]] = {node_id: set() for node_id in node_ids}
        for source_id, target_id, _label in edges:
            if source_id not in visible_set or target_id not in visible_set:
                continue
            children[source_id].append(target_id)
            parents[target_id].append(source_id)
            neighbors[source_id].add(target_id)
            neighbors[target_id].add(source_id)

        components: list[list[str]] = []
        seen: set[str] = set()
        for node_id in sorted(node_ids):
            if node_id in seen:
                continue
            stack = [node_id]
            comp: list[str] = []
            while stack:
                current = stack.pop()
                if current in seen:
                    continue
                seen.add(current)
                comp.append(current)
                stack.extend(sorted(neighbors.get(current, set()) - seen))
            components.append(sorted(comp))
        components.sort(key=lambda rows: (-len(rows), rows[0] if rows else ""))

        raw_positions: dict[str, tuple[float, float]] = {}
        component_cursor_y = 0.0
        component_gap = 1.2

        for comp_nodes in components:
            if not comp_nodes:
                continue
            comp_set = set(comp_nodes)
            roots = [node_id for node_id in spec.roots if node_id in comp_set]
            if not roots:
                roots = [
                    node_id
                    for node_id in comp_nodes
                    if not [p for p in parents.get(node_id, []) if p in comp_set]
                ]
            if not roots:
                roots = [comp_nodes[0]]

            levels: dict[str, int] = {}
            queue: deque[tuple[str, int]] = deque((root_id, 0) for root_id in roots)
            while queue:
                node_id, depth = queue.popleft()
                prev = levels.get(node_id)
                if prev is not None and depth >= prev:
                    continue
                levels[node_id] = depth
                for child_id in children.get(node_id, []):
                    if child_id in comp_set:
                        queue.append((child_id, depth + 1))

            fallback_level = max(levels.values(), default=-1) + 1
            for node_id in comp_nodes:
                if node_id in levels:
                    continue
                known_parent_levels = [
                    levels[parent_id]
                    for parent_id in parents.get(node_id, [])
                    if parent_id in levels
                ]
                if known_parent_levels:
                    levels[node_id] = max(known_parent_levels) + 1
                else:
                    levels[node_id] = fallback_level

            max_level = max(levels.values(), default=0)
            by_level: dict[int, list[str]] = {
                level: []
                for level in range(max_level + 1)
            }
            for node_id in comp_nodes:
                by_level.setdefault(levels.get(node_id, 0), []).append(node_id)

            level_order: dict[str, float] = {}
            comp_positions: dict[str, tuple[float, float]] = {}
            max_level_height = 1
            for level in range(max_level + 1):
                level_nodes = by_level.get(level, [])
                if not level_nodes:
                    continue

                def barycenter(node_id: str) -> float:
                    preds = [
                        parent_id
                        for parent_id in parents.get(node_id, [])
                        if parent_id in level_order
                    ]
                    if preds:
                        return sum(level_order[p] for p in preds) / float(len(preds))
                    if node_id in roots:
                        return float(roots.index(node_id))
                    return float(comp_nodes.index(node_id))

                level_nodes.sort(key=lambda node_id: (barycenter(node_id), node_id))
                count = len(level_nodes)
                max_level_height = max(max_level_height, count)
                for idx, node_id in enumerate(level_nodes):
                    y = float(idx) - (float(count - 1) / 2.0)
                    comp_positions[node_id] = (float(level), y)
                    level_order[node_id] = y

            for node_id, (x, y) in comp_positions.items():
                raw_positions[node_id] = (x, y + component_cursor_y)
            component_cursor_y += float(max_level_height) + component_gap

        if not raw_positions:
            out: dict[str, QPointF] = {}
            for idx, node_id in enumerate(node_ids):
                out[node_id] = QPointF(float(idx), 0.0)
            return out

        xs = [point[0] for point in raw_positions.values()]
        ys = [point[1] for point in raw_positions.values()]
        center_x = (min(xs) + max(xs)) / 2.0
        center_y = (min(ys) + max(ys)) / 2.0

        out: dict[str, QPointF] = {}
        for node_id in node_ids:
            pos = raw_positions.get(node_id)
            if pos is None:
                pos = (0.0, 0.0)
            out[node_id] = QPointF(
                float((pos[0] - center_x) * 1.35),
                float((pos[1] - center_y) * 1.1),
            )
        return out

    @staticmethod
    def _estimate_graph_node_size(
        spec: GraphSpec,
        *,
        node_id: str,
        expandable_nodes: set[str],
    ) -> tuple[float, float]:
        node = spec.nodes.get(node_id)
        if node is None:
            return 190.0, 50.0
        label = str(node.label or node.node_id)
        display_label = label if len(label) <= 36 else (label[:33] + "...")
        if node_id in expandable_nodes:
            display_label = f"[-] {display_label}"

        quote = ""
        if node.quote:
            quote = str(node.quote).strip()
        if quote and len(quote) > 96:
            quote = quote[:93] + "..."

        width = 190.0
        if len(display_label) > 22:
            width = 220.0
        if quote:
            width = max(width, 250.0)

        lines = 1
        if quote and not node.children:
            lines = 2
        elif node.description:
            lines = 2
        height = 50.0 + (22.0 if lines > 1 else 0.0)
        return float(width), float(height)

    @staticmethod
    def _resolve_graph_node_overlaps(
        *,
        centers: dict[str, QPointF],
        node_dims: dict[str, tuple[float, float]],
        fixed_nodes: set[str],
        scene_w: float,
        scene_h: float,
    ) -> None:
        if len(centers) < 2:
            return
        node_ids = list(centers.keys())
        margin = 8.0
        max_iterations = 80

        for _ in range(max_iterations):
            changed = False
            for idx, left_id in enumerate(node_ids):
                left_center = centers.get(left_id)
                if left_center is None:
                    continue
                left_w, left_h = node_dims.get(left_id, (190.0, 50.0))
                for right_id in node_ids[idx + 1:]:
                    right_center = centers.get(right_id)
                    if right_center is None:
                        continue
                    right_w, right_h = node_dims.get(right_id, (190.0, 50.0))

                    dx = float(right_center.x() - left_center.x())
                    dy = float(right_center.y() - left_center.y())
                    min_dx = (left_w * 0.5) + (right_w * 0.5) + margin
                    min_dy = (left_h * 0.5) + (right_h * 0.5) + margin
                    overlap_x = min_dx - abs(dx)
                    overlap_y = min_dy - abs(dy)
                    if overlap_x <= 0.0 or overlap_y <= 0.0:
                        continue

                    move_x = overlap_x if overlap_x < overlap_y else 0.0
                    move_y = overlap_y if overlap_y <= overlap_x else 0.0
                    if move_x <= 0.0 and move_y <= 0.0:
                        move_x = overlap_x * 0.5
                        move_y = overlap_y * 0.5

                    sign_x = 1.0 if dx >= 0.0 else -1.0
                    sign_y = 1.0 if dy >= 0.0 else -1.0
                    if abs(dx) < 1e-6:
                        sign_x = 1.0 if left_id < right_id else -1.0
                    if abs(dy) < 1e-6:
                        sign_y = 1.0 if left_id < right_id else -1.0

                    left_fixed = left_id in fixed_nodes
                    right_fixed = right_id in fixed_nodes
                    if left_fixed and right_fixed:
                        continue

                    if left_fixed:
                        left_shift = 0.0
                        right_shift = 1.0
                    elif right_fixed:
                        left_shift = 1.0
                        right_shift = 0.0
                    else:
                        left_shift = 0.5
                        right_shift = 0.5

                    if move_x > 0.0:
                        left_center.setX(left_center.x() - (sign_x * move_x * left_shift))
                        right_center.setX(right_center.x() + (sign_x * move_x * right_shift))
                    if move_y > 0.0:
                        left_center.setY(left_center.y() - (sign_y * move_y * left_shift))
                        right_center.setY(right_center.y() + (sign_y * move_y * right_shift))
                    changed = True

            if not changed:
                break

        for node_id, center in centers.items():
            width, height = node_dims.get(node_id, (190.0, 50.0))
            half_w = width * 0.5
            half_h = height * 0.5
            min_x = 26.0 + half_w
            max_x = max(min_x, scene_w - 26.0 - half_w)
            min_y = 26.0 + half_h
            max_y = max(min_y, scene_h - 26.0 - half_h)
            center.setX(max(min_x, min(max_x, float(center.x()))))
            center.setY(max(min_y, min(max_y, float(center.y()))))

    def _render_structured_graph_scene(self, spec: GraphSpec):
        scene = self._graph_scene
        view = self._graph_view
        if scene is None or view is None:
            # Fallback for environments without graphics scene: keep HTML rendering.
            html_view = render_graph_html(
                spec,
                collapsed_ids=self._graph_collapsed_ids,
                focus_node_id=self._graph_focus_node_id,
            )
            self._view.setHtml(html_view)
            doc = QTextDocument()
            doc.setHtml(html_view)
            self._graph_plain_text = (doc.toPlainText() or "").replace(
                "\r\n",
                "\n",
            )
            return

        scene.clear()
        palette = self.palette()
        text_color = QColor(palette.color(QPalette.ColorRole.Text))
        muted_color = QColor(palette.color(QPalette.ColorRole.PlaceholderText))
        base_color = QColor(palette.color(QPalette.ColorRole.Base))
        alt_color = QColor(palette.color(QPalette.ColorRole.AlternateBase))
        highlight_color = QColor(palette.color(QPalette.ColorRole.Highlight))
        link_color = QColor(palette.color(QPalette.ColorRole.Link))
        mid_color = QColor(palette.color(QPalette.ColorRole.Mid))
        focus_fill = QColor(highlight_color)
        focus_fill.setAlpha(58)
        leaf_fill = QColor(alt_color)
        leaf_fill = leaf_fill.lighter(108)
        root_fill = QColor(base_color)
        root_fill = root_fill.lighter(112)
        normal_fill = QColor(alt_color)
        current_scale = abs(float(view.transform().m11() or 1.0))
        if current_scale < 0.45 or current_scale > 5.0:
            view.reset_zoom()
        node_ids, edges = self._visible_graph_data(spec)
        if not node_ids:
            text_item = scene.addText("Keine Knoten.")
            text_item.setDefaultTextColor(muted_color)
            self._graph_plain_text = ""
            return

        layout_positions = self._layout_graph_nodes(
            spec=spec,
            node_ids=node_ids,
            edges=edges,
        )

        include_edges = spec.kind == "graph"
        expandable_nodes = self._expandable_graph_nodes(
            spec,
            include_edges=include_edges,
        )
        node_dims: dict[str, tuple[float, float]] = {
            node_id: self._estimate_graph_node_size(
                spec,
                node_id=node_id,
                expandable_nodes=expandable_nodes,
            )
            for node_id in node_ids
        }

        # Normalize coordinates into a readable scene area.
        xs = [layout_positions[node_id].x() for node_id in node_ids]
        ys = [layout_positions[node_id].y() for node_id in node_ids]
        min_x = min(xs)
        max_x = max(xs)
        min_y = min(ys)
        max_y = max(ys)
        span_x = max(0.01, max_x - min_x)
        span_y = max(0.01, max_y - min_y)
        if spec.kind == "mindmap":
            scene_w = max(
                980.0,
                ((span_x + 1.0) * 215.0),
            )
            scene_h = max(
                680.0,
                ((span_y + 1.0) * 155.0),
            )
        else:
            scene_w = max(
                920.0,
                235.0 * math.sqrt(float(len(node_ids))),
                ((span_x + 1.0) * 175.0),
            )
            scene_h = max(
                620.0,
                185.0 * math.sqrt(float(len(node_ids))),
                ((span_y + 1.0) * 145.0),
            )
        pad = 90.0

        centers: dict[str, QPointF] = {}
        for node_id in node_ids:
            raw = layout_positions[node_id]
            x = pad + ((raw.x() - min_x) / span_x) * (scene_w - (2.0 * pad))
            y = pad + ((raw.y() - min_y) / span_y) * (scene_h - (2.0 * pad))
            centers[node_id] = QPointF(x, y)

        for node_id, manual in list(self._graph_manual_positions.items()):
            if node_id not in centers:
                continue
            centers[node_id] = QPointF(
                max(28.0, min(scene_w - 28.0, float(manual.x()))),
                max(28.0, min(scene_h - 28.0, float(manual.y()))),
            )

        self._resolve_graph_node_overlaps(
            centers=centers,
            node_dims=node_dims,
            fixed_nodes=set(self._graph_manual_positions.keys()) & set(node_ids),
            scene_w=scene_w,
            scene_h=scene_h,
        )

        focus = self._graph_focus_node_id
        plain_rows: list[str] = [spec.title]
        node_items: dict[str, _GraphNodeItem] = {}
        for node_id in node_ids:
            node = spec.nodes[node_id]
            center = centers[node_id]
            is_root = node_id in spec.roots
            is_leaf = not node.children
            is_focus = node_id == focus

            label = str(node.label or node.node_id)
            raw_quote = str(node.quote or "").strip()
            quote_preview = raw_quote
            if quote_preview and len(quote_preview) > 96:
                quote_preview = quote_preview[:93] + "..."
            display_label = label if len(label) <= 36 else (label[:33] + "...")
            if node_id in expandable_nodes:
                marker = "[+]" if node_id in self._graph_collapsed_ids else "[-]"
                display_label = f"{marker} {display_label}"
            lines = [display_label]
            if quote_preview and is_leaf:
                lines.append(f"\"{quote_preview}\"")
            elif node.description:
                desc = str(node.description).strip()
                if len(desc) > 72:
                    desc = desc[:69] + "..."
                lines.append(desc)
            text = "\n".join(lines)

            width, height = node_dims.get(node_id, (190.0, 50.0))

            node_item = _GraphNodeItem(
                node_id=node_id,
                width=width,
                height=height,
                display_text=text,
                on_click=self._on_graph_node_clicked,
                on_toggle=self._on_graph_node_toggled,
                on_moved=self._on_graph_node_moved,
            )
            node_item.setPos(center.x() - (width / 2.0), center.y() - (height / 2.0))
            node_item.setBrush(
                QBrush(
                    focus_fill
                    if is_focus
                    else leaf_fill
                    if is_leaf
                    else root_fill
                    if is_root
                    else normal_fill
                )
            )
            node_item.setPen(
                QPen(
                    highlight_color
                    if is_focus
                    else link_color
                    if is_leaf
                    else highlight_color
                    if is_root
                    else mid_color,
                    2.2 if is_focus else 1.4,
                )
            )
            tip_parts = [label]
            if node.description:
                tip_parts.append(str(node.description))
            if raw_quote:
                tip_parts.append(f"Zitat: \"{raw_quote}\"")
            if node.href:
                tip_parts.append(f"Link: {node.href}")
            tip_parts.append("Klick: Fokus | Doppelklick: auf/zu oder Link")
            node_item.setToolTip("\n".join(tip_parts))
            node_item.set_text_color(text_color)
            node_item.setZValue(2.0)
            scene.addItem(node_item)
            node_items[node_id] = node_item

            plain_rows.append(label)
            if raw_quote:
                plain_rows.append(raw_quote)

        for source_id, target_id, label in edges:
            source_item = node_items.get(source_id)
            target_item = node_items.get(target_id)
            if source_item is None or target_item is None:
                continue
            src_w, src_h = node_dims.get(source_id, (190.0, 50.0))
            dst_w, dst_h = node_dims.get(target_id, (190.0, 50.0))
            connected = focus in {source_id, target_id}
            edge_color = highlight_color if connected else mid_color
            line_pen = QPen(edge_color, 2.2 if connected else 1.35)
            line_item = QGraphicsLineItem()
            line_item.setPen(line_pen)
            line_item.setZValue(0.4)
            scene.addItem(line_item)

            arrow = QGraphicsPolygonItem()
            arrow.setBrush(QBrush(edge_color))
            arrow.setPen(QPen(edge_color, 1.0))
            arrow.setZValue(0.5)
            scene.addItem(arrow)

            label_item: QGraphicsTextItem | None = None
            if label:
                label_item = QGraphicsTextItem(label)
                label_item.setDefaultTextColor(
                    highlight_color if connected else muted_color
                )
                label_item.setZValue(1.2)
                label_item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
                scene.addItem(label_item)

            def update_edge_geometry(
                src_item: _GraphNodeItem = source_item,
                dst_item: _GraphNodeItem = target_item,
                src_size: tuple[float, float] = (src_w, src_h),
                dst_size: tuple[float, float] = (dst_w, dst_h),
                line_ref: QGraphicsLineItem = line_item,
                arrow_ref: QGraphicsPolygonItem = arrow,
                label_ref: QGraphicsTextItem | None = label_item,
            ):
                p1 = src_item.center_pos()
                p2 = dst_item.center_pos()
                dx = p2.x() - p1.x()
                dy = p2.y() - p1.y()
                dist = math.hypot(dx, dy)
                if dist < 1.0:
                    line_ref.setLine(p1.x(), p1.y(), p2.x(), p2.y())
                    arrow_ref.setPolygon(QPolygonF())
                    if label_ref is not None:
                        label_ref.setPos(p1.x(), p1.y())
                    return
                ux = dx / dist
                uy = dy / dist
                src_pad = max(22.0, min(src_size[0], src_size[1]) * 0.22)
                dst_pad = max(22.0, min(dst_size[0], dst_size[1]) * 0.22)
                line_start = QPointF(
                    p1.x() + (ux * src_pad),
                    p1.y() + (uy * src_pad),
                )
                line_end = QPointF(
                    p2.x() - (ux * dst_pad),
                    p2.y() - (uy * dst_pad),
                )
                line_ref.setLine(
                    line_start.x(),
                    line_start.y(),
                    line_end.x(),
                    line_end.y(),
                )
                arrow_size = 10.0
                arrow_width = 5.0
                left = QPointF(
                    line_end.x() - (ux * arrow_size) - (uy * arrow_width),
                    line_end.y() - (uy * arrow_size) + (ux * arrow_width),
                )
                right = QPointF(
                    line_end.x() - (ux * arrow_size) + (uy * arrow_width),
                    line_end.y() - (uy * arrow_size) - (ux * arrow_width),
                )
                arrow_ref.setPolygon(QPolygonF([line_end, left, right]))
                if label_ref is not None:
                    mid_x = (line_start.x() + line_end.x()) / 2.0
                    mid_y = (line_start.y() + line_end.y()) / 2.0
                    label_ref.setPos(mid_x + 4.0, mid_y - 8.0)

            update_edge_geometry()
            source_item.add_move_callback(update_edge_geometry)
            target_item.add_move_callback(update_edge_geometry)

        for source_id, target_id, label in edges:
            src = spec.nodes.get(source_id)
            dst = spec.nodes.get(target_id)
            if src is None or dst is None:
                continue
            if label:
                plain_rows.append(f"{src.label} --{label}--> {dst.label}")
            else:
                plain_rows.append(f"{src.label} --> {dst.label}")

        self._graph_plain_text = "\n".join(plain_rows).replace("\r\n", "\n")
        scene.setSceneRect(0.0, 0.0, scene_w, scene_h)
        if focus:
            # Keep focused node centered after redraw.
            for item in scene.items():
                if isinstance(item, _GraphNodeItem) and item._node_id == focus:  # pylint: disable=protected-access
                    view.centerOn(item.sceneBoundingRect().center())
                    break
        else:
            view.centerOn(scene.sceneRect().center())

    def scroll_to_bottom(self):
        if self._structured_view_active and self._graph_view is not None and self._graph_scene is not None:
            self._graph_view.centerOn(self._graph_scene.sceneRect().center())
            return
        scrollbar = self._view.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
