"""CanvasPreviewPane method implementations."""
from __future__ import annotations

from .deps import *  # noqa: F403

def __init__(
    self,
    parent: QWidget | None = None,
    allow_editing: bool = True,
    show_title: bool = True,
    sync_cursor_with_editor: bool = True,
):
    QWidget.__init__(self, parent)
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
    self._graph_view: GraphCanvasView | None = None
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

    self._view = PreviewTextBrowser()
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

    self._graph_view = GraphCanvasView()
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

__all__ = [
    "__init__",
    "_palette_hex",
    "_mix_hex_colors",
    "_normalize_preview_theme_id",
    "preview_theme_options",
    "global_preview_theme_id",
    "apply_global_preview_theme",
    "preview_theme_id",
    "set_preview_theme_id",
    "_setup_ui",
    "_build_format_bar",
    "_build_graph_bar",
    "_setup_timers",
]
