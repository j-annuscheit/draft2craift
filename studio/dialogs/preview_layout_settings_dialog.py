"""Modeless dialog for global layout and HTML/markdown style settings."""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFontDatabase, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
    QColorDialog,
)

from shared.domain.user_mode import (
    default_user_mode,
    normalize_user_mode,
    resolve_feature_label,
)
from studio.canvas.preview.pane import CanvasPreviewPane
from studio.canvas.preview.style_settings import (
    IMAGE_MODE_OPTIONS,
    default_preview_style_settings,
    normalize_preview_style_settings,
    resolve_preview_style_tokens,
)
from studio.theme import available_themes


class PreviewLayoutSettingsDialog(QDialog):
    """Global style cockpit for markdown and HTML preview rendering."""

    _UI_FONT_PREFERENCES: tuple[str, ...] = (
        "Segoe UI",
        "Inter",
        "Roboto",
        "Noto Sans",
        "Arial",
        "Helvetica",
        "Fira Sans",
        "Source Sans Pro",
        "Ubuntu",
        "Cantarell",
        "DejaVu Sans",
    )
    _CODE_FONT_PREFERENCES: tuple[str, ...] = (
        "Cascadia Code",
        "JetBrains Mono",
        "Fira Code",
        "Consolas",
        "Source Code Pro",
        "Menlo",
        "Monaco",
        "DejaVu Sans Mono",
        "Liberation Mono",
        "Courier New",
    )

    def __init__(
        self,
        *,
        theme_id: str,
        preview_theme_id: str,
        page_margin_settings: object,
        style_settings: object,
        user_mode: str | None = None,
        on_theme_changed: Callable[[str], None] | None = None,
        on_preview_theme_changed: Callable[[str], None] | None = None,
        on_page_margin_changed: Callable[[dict], None] | None = None,
        on_style_changed: Callable[[dict], None] | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self._user_mode = normalize_user_mode(
            default_user_mode() if user_mode is None else user_mode
        )
        self._on_theme_changed = on_theme_changed
        self._on_preview_theme_changed = on_preview_theme_changed
        self._on_page_margin_changed = on_page_margin_changed
        self._on_style_changed = on_style_changed
        self._updating = False
        self._style = normalize_preview_style_settings(style_settings)
        self._theme_id = str(theme_id or "")
        self._preview_theme_id = CanvasPreviewPane.normalize_preview_theme_id(
            preview_theme_id
        )
        margin_enabled = bool(
            isinstance(page_margin_settings, dict)
            and page_margin_settings.get("enabled", True)
        )
        margin_em = float(
            page_margin_settings.get("em", CanvasPreviewPane.page_margin_default_em())
        ) if isinstance(page_margin_settings, dict) else float(
            CanvasPreviewPane.page_margin_default_em()
        )
        self._page_margin_enabled = margin_enabled
        self._page_margin_em = float(CanvasPreviewPane.normalize_page_margin_em(margin_em))
        self._color_buttons: dict[str, QPushButton] = {}
        self._auto_color_keys: set[str] = set()
        self._float_controls: dict[str, QDoubleSpinBox] = {}
        self._int_controls: dict[str, QSpinBox] = {}
        self._font_controls: dict[str, QComboBox] = {}
        self._font_choices = self._collect_font_choices()
        self._build_ui()
        self.sync_from_runtime(
            theme_id=self._theme_id,
            preview_theme_id=self._preview_theme_id,
            page_margin_settings={
                "enabled": self._page_margin_enabled,
                "em": self._page_margin_em,
            },
            style_settings=self._style,
        )
        self.set_user_mode(self._user_mode)

    def set_user_mode(self, mode: str) -> None:
        self._user_mode = normalize_user_mode(mode)
        self.setWindowTitle(
            resolve_feature_label(
                self._user_mode,
                "preview.layout_settings.window_title",
                "Layout + HTML-Ansicht",
            )
        )

    def sync_from_runtime(
        self,
        *,
        theme_id: str,
        preview_theme_id: str,
        page_margin_settings: object,
        style_settings: object,
    ) -> None:
        self._updating = True
        try:
            self._theme_id = str(theme_id or "")
            self._preview_theme_id = CanvasPreviewPane.normalize_preview_theme_id(
                preview_theme_id
            )
            normalized = normalize_preview_style_settings(style_settings)
            self._style = dict(normalized)
            if isinstance(page_margin_settings, dict):
                self._page_margin_enabled = bool(
                    page_margin_settings.get("enabled", True)
                )
                try:
                    margin_em = float(
                        page_margin_settings.get(
                            "em",
                            CanvasPreviewPane.page_margin_default_em(),
                        )
                    )
                except Exception:
                    margin_em = float(CanvasPreviewPane.page_margin_default_em())
                self._page_margin_em = float(
                    CanvasPreviewPane.normalize_page_margin_em(margin_em)
                )
            self._theme_combo.setCurrentIndex(
                max(0, self._theme_combo.findData(self._theme_id))
            )
            self._preview_theme_combo.setCurrentIndex(
                max(
                    0,
                    self._preview_theme_combo.findData(self._preview_theme_id),
                )
            )
            self._margin_enabled_cb.setChecked(bool(self._page_margin_enabled))
            self._set_margin_combo_from_em(self._page_margin_em)
            self._refresh_all_value_widgets_from_state()
        finally:
            self._updating = False

    def _build_ui(self) -> None:
        self.resize(980, 760)
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        hint = QLabel(
            "Alle Änderungen werden sofort übernommen und gelten global "
            "(Canvas, RAG, Dokumente, Import, Chat)."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: palette(placeholder-text); font-size: 10px;")
        root.addWidget(hint)

        self._tabs = QTabWidget()
        self._tabs.addTab(
            self._build_layout_tab(),
            "Layout",
        )
        self._tabs.addTab(
            self._build_html_tab(),
            "HTML / Markdown",
        )
        root.addWidget(self._tabs, stretch=1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        reset_button = buttons.addButton("HTML-Werte zurücksetzen", QDialogButtonBox.ButtonRole.ResetRole)
        reset_button.clicked.connect(self._reset_style_defaults)
        buttons.rejected.connect(self.close)
        root.addWidget(buttons)

    def _build_layout_tab(self) -> QWidget:
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        quick_group = QGroupBox("Schnellzugriff")
        quick_form = QFormLayout(quick_group)
        quick_form.setContentsMargins(8, 8, 8, 8)
        quick_form.setSpacing(8)
        self._quick_preset_combo = QComboBox()
        for theme_id, label in CanvasPreviewPane.preview_theme_options():
            self._quick_preset_combo.addItem(str(label), str(theme_id))
        quick_apply_btn = QPushButton("Preset auf alle HTML-Werte anwenden")
        quick_apply_btn.clicked.connect(self._apply_quick_preset)
        quick_form.addRow("HTML-Preset:", self._quick_preset_combo)
        quick_form.addRow("", quick_apply_btn)
        layout.addWidget(quick_group)

        base_group = QGroupBox("Basis")
        base_form = QFormLayout(base_group)
        base_form.setContentsMargins(8, 8, 8, 8)
        base_form.setSpacing(8)

        self._theme_combo = QComboBox()
        for theme_id, label in available_themes():
            self._theme_combo.addItem(str(label), str(theme_id))
        self._theme_combo.currentIndexChanged.connect(self._on_theme_combo_changed)
        base_form.addRow("App-Theme:", self._theme_combo)

        self._preview_theme_combo = QComboBox()
        for theme_id, label in CanvasPreviewPane.preview_theme_options():
            self._preview_theme_combo.addItem(str(label), str(theme_id))
        self._preview_theme_combo.currentIndexChanged.connect(
            self._on_preview_theme_combo_changed
        )
        base_form.addRow("HTML-Stil:", self._preview_theme_combo)

        margin_row = QWidget()
        margin_layout = QHBoxLayout(margin_row)
        margin_layout.setContentsMargins(0, 0, 0, 0)
        margin_layout.setSpacing(6)
        self._margin_enabled_cb = QCheckBox("Aktiv")
        self._margin_enabled_cb.toggled.connect(self._emit_page_margin_changed)
        self._margin_preset_combo = QComboBox()
        for label, em in CanvasPreviewPane.page_margin_presets():
            self._margin_preset_combo.addItem(str(label), float(em))
        self._margin_preset_combo.currentIndexChanged.connect(
            self._on_margin_preset_changed
        )
        margin_layout.addWidget(self._margin_enabled_cb)
        margin_layout.addWidget(self._margin_preset_combo, stretch=1)
        base_form.addRow("Seitenrand:", margin_row)

        layout.addWidget(base_group)
        layout.addStretch(1)
        return host

    def _build_html_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        host = QWidget()
        scroll.setWidget(host)
        root = QVBoxLayout(host)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(10)

        typography_group = QGroupBox("Typografie")
        typography_form = QFormLayout(typography_group)
        typography_form.setContentsMargins(8, 8, 8, 8)
        typography_form.setSpacing(8)
        self._font_controls["markdown_font_family"] = self._build_font_combo(
            key="markdown_font_family",
            preferred=self._CODE_FONT_PREFERENCES,
        )
        typography_form.addRow(
            "Markdown-Schriftart:",
            self._font_controls["markdown_font_family"],
        )
        self._font_controls["html_font_family"] = self._build_font_combo(
            key="html_font_family",
            preferred=self._UI_FONT_PREFERENCES,
        )
        typography_form.addRow(
            "HTML-Schriftart:",
            self._font_controls["html_font_family"],
        )
        self._font_controls["code_font_family"] = self._build_font_combo(
            key="code_font_family",
            preferred=self._CODE_FONT_PREFERENCES,
        )
        typography_form.addRow(
            "Code-Schriftart:",
            self._font_controls["code_font_family"],
        )
        self._int_controls["base_font_percent"] = QSpinBox()
        self._int_controls["base_font_percent"].setRange(70, 220)
        self._int_controls["base_font_percent"].setSuffix("%")
        self._int_controls["base_font_percent"].valueChanged.connect(
            lambda _v: self._on_int_changed("base_font_percent")
        )
        typography_form.addRow(
            "Textgröße:",
            self._int_controls["base_font_percent"],
        )
        self._add_float_spin(
            typography_form,
            "line_height",
            "Zeilenhöhe:",
            1.0,
            2.6,
            0.05,
        )
        self._add_float_spin(
            typography_form,
            "paragraph_gap_em",
            "Absatz-Abstand:",
            0.0,
            3.0,
            0.05,
        )
        root.addWidget(typography_group)

        list_group = QGroupBox("Listen")
        list_form = QFormLayout(list_group)
        list_form.setContentsMargins(8, 8, 8, 8)
        list_form.setSpacing(8)
        self._add_float_spin(
            list_form,
            "list_indent_em",
            "Einzug:",
            0.5,
            4.0,
            0.05,
        )
        self._add_float_spin(
            list_form,
            "list_marker_gap_em",
            "Marker-Abstand:",
            0.0,
            1.5,
            0.05,
        )
        self._add_float_spin(
            list_form,
            "list_margin_top_em",
            "Abstand oben:",
            0.0,
            3.0,
            0.05,
        )
        self._add_float_spin(
            list_form,
            "list_margin_bottom_em",
            "Abstand unten:",
            0.0,
            3.0,
            0.05,
        )
        self._add_float_spin(
            list_form,
            "list_item_gap_em",
            "Abstand pro Punkt:",
            0.0,
            2.0,
            0.05,
        )
        root.addWidget(list_group)

        heading_group = QGroupBox("Überschriften (Größe + Abstände)")
        heading_layout = QGridLayout(heading_group)
        heading_layout.setContentsMargins(8, 8, 8, 8)
        heading_layout.setHorizontalSpacing(8)
        heading_layout.setVerticalSpacing(6)
        heading_layout.addWidget(QLabel("Ebene"), 0, 0)
        heading_layout.addWidget(QLabel("Größe-Faktor"), 0, 1)
        heading_layout.addWidget(QLabel("Vorher"), 0, 2)
        heading_layout.addWidget(QLabel("Nachher"), 0, 3)
        for idx, level in enumerate((1, 2, 3, 4, 5, 6), start=1):
            heading_layout.addWidget(QLabel(f"H{level}"), idx, 0)
            size_key = f"heading_h{level}_size_em"
            before_key = f"heading_h{level}_margin_before_em"
            after_key = f"heading_h{level}_margin_after_em"
            size = QDoubleSpinBox()
            size.setRange(0.5, 4.0)
            size.setSingleStep(0.05)
            size.setDecimals(2)
            size.setSuffix("x")
            size.valueChanged.connect(
                lambda _v, key=size_key: self._on_float_changed(key)
            )
            self._float_controls[size_key] = size
            before = QDoubleSpinBox()
            before.setRange(0.0, 3.0)
            before.setSingleStep(0.05)
            before.setDecimals(2)
            before.valueChanged.connect(
                lambda _v, key=before_key: self._on_float_changed(key)
            )
            self._float_controls[before_key] = before
            after = QDoubleSpinBox()
            after.setRange(0.0, 3.0)
            after.setSingleStep(0.05)
            after.setDecimals(2)
            after.valueChanged.connect(
                lambda _v, key=after_key: self._on_float_changed(key)
            )
            self._float_controls[after_key] = after
            heading_layout.addWidget(size, idx, 1)
            heading_layout.addWidget(before, idx, 2)
            heading_layout.addWidget(after, idx, 3)
        root.addWidget(heading_group)

        blocks_group = QGroupBox("Blöcke")
        blocks_form = QFormLayout(blocks_group)
        blocks_form.setContentsMargins(8, 8, 8, 8)
        blocks_form.setSpacing(8)
        self._add_float_spin(
            blocks_form,
            "table_margin_top_em",
            "Tabelle Abstand oben:",
            0.0,
            3.0,
            0.05,
        )
        self._add_float_spin(
            blocks_form,
            "table_margin_bottom_em",
            "Tabelle Abstand unten:",
            0.0,
            3.0,
            0.05,
        )
        self._add_float_spin(
            blocks_form,
            "blockquote_margin_top_em",
            "Zitatblock oben:",
            0.0,
            3.0,
            0.05,
        )
        self._add_float_spin(
            blocks_form,
            "blockquote_margin_bottom_em",
            "Zitatblock unten:",
            0.0,
            3.0,
            0.05,
        )
        self._add_float_spin(
            blocks_form,
            "hr_margin_top_em",
            "Horizontale Linie oben:",
            0.0,
            3.0,
            0.05,
        )
        self._add_float_spin(
            blocks_form,
            "hr_margin_bottom_em",
            "Horizontale Linie unten:",
            0.0,
            3.0,
            0.05,
        )
        root.addWidget(blocks_group)

        image_group = QGroupBox("Bilder")
        image_form = QFormLayout(image_group)
        image_form.setContentsMargins(8, 8, 8, 8)
        image_form.setSpacing(8)
        self._image_mode_combo = QComboBox()
        self._image_mode_combo.addItem("Ja", "yes")
        self._image_mode_combo.addItem("Klein", "small")
        self._image_mode_combo.addItem("Nein", "no")
        self._image_mode_combo.currentIndexChanged.connect(
            self._on_image_mode_changed
        )
        image_form.addRow("Anzeigen:", self._image_mode_combo)
        self._int_controls["image_small_max_width_percent"] = QSpinBox()
        self._int_controls["image_small_max_width_percent"].setRange(10, 100)
        self._int_controls["image_small_max_width_percent"].setSuffix("%")
        self._int_controls["image_small_max_width_percent"].valueChanged.connect(
            lambda _v: self._on_int_changed("image_small_max_width_percent")
        )
        image_form.addRow(
            "Breite bei Klein:",
            self._int_controls["image_small_max_width_percent"],
        )
        root.addWidget(image_group)

        color_group = QGroupBox("Farben")
        color_layout = QVBoxLayout(color_group)
        color_layout.setContentsMargins(8, 8, 8, 8)
        color_layout.setSpacing(6)
        colors_form = QFormLayout()
        colors_form.setSpacing(6)
        for level in (1, 2, 3, 4, 5, 6):
            self._add_color_row(
                colors_form,
                f"heading_h{level}_color",
                f"H{level}:",
                allow_auto=True,
            )
        self._add_color_row(colors_form, "bold_color", "Fett:", allow_auto=True)
        self._add_color_row(colors_form, "italic_color", "Kursiv:", allow_auto=True)
        self._add_color_row(
            colors_form,
            "bold_italic_color",
            "Fett+Kursiv:",
            allow_auto=True,
        )
        self._add_color_row(colors_form, "link_color", "Link:", allow_auto=True)
        self._add_color_row(
            colors_form,
            "glossary_highlight_color",
            "Glossar-Markierung:",
            allow_auto=False,
        )
        self._add_color_row(
            colors_form,
            "body_background_color",
            "Hintergrund:",
            allow_auto=True,
        )
        self._add_color_row(
            colors_form,
            "body_text_color",
            "Text:",
            allow_auto=True,
        )
        self._add_color_row(
            colors_form,
            "code_text_color",
            "Code-Text:",
            allow_auto=True,
        )
        self._add_color_row(
            colors_form,
            "table_border_color",
            "Tabellenrahmen:",
            allow_auto=True,
        )
        self._add_color_row(
            colors_form,
            "quote_border_color",
            "Zitat-Linie:",
            allow_auto=True,
        )
        self._add_color_row(
            colors_form,
            "hr_color",
            "Horizontallinie:",
            allow_auto=True,
        )
        color_layout.addLayout(colors_form)
        root.addWidget(color_group)
        root.addStretch(1)
        return scroll

    def _add_float_spin(
        self,
        form: QFormLayout,
        key: str,
        label: str,
        min_value: float,
        max_value: float,
        step: float,
    ) -> None:
        spin = QDoubleSpinBox()
        spin.setRange(min_value, max_value)
        spin.setSingleStep(step)
        spin.setDecimals(2)
        spin.valueChanged.connect(lambda _v, item=key: self._on_float_changed(item))
        self._float_controls[key] = spin
        form.addRow(label, spin)

    @staticmethod
    def _normalize_font_name(value: object) -> str:
        return str(value or "").strip()

    def _collect_font_choices(self) -> tuple[str, ...]:
        try:
            installed = [str(name).strip() for name in QFontDatabase.families()]
        except Exception:
            installed = []
        cleaned = [name for name in installed if name]
        if not cleaned:
            cleaned = [
                "Segoe UI",
                "Inter",
                "Roboto",
                "Arial",
                "Cascadia Code",
                "JetBrains Mono",
                "Consolas",
                "DejaVu Sans",
                "DejaVu Sans Mono",
            ]
        unique: list[str] = []
        seen: set[str] = set()
        for name in cleaned:
            key = name.casefold()
            if key in seen:
                continue
            seen.add(key)
            unique.append(name)
        return tuple(sorted(unique, key=lambda item: item.casefold()))

    def _ordered_fonts(self, preferred: tuple[str, ...]) -> tuple[str, ...]:
        choices = list(self._font_choices)
        by_key = {item.casefold(): item for item in choices}
        ordered: list[str] = []
        seen: set[str] = set()
        for name in preferred:
            match = by_key.get(str(name).casefold())
            if not match:
                continue
            key = match.casefold()
            if key in seen:
                continue
            seen.add(key)
            ordered.append(match)
        for name in choices:
            key = name.casefold()
            if key in seen:
                continue
            seen.add(key)
            ordered.append(name)
        return tuple(ordered)

    def _build_font_combo(self, *, key: str, preferred: tuple[str, ...]) -> QComboBox:
        combo = QComboBox()
        combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        for family in self._ordered_fonts(preferred):
            combo.addItem(family, family)
        combo.currentIndexChanged.connect(
            lambda _idx, item=key: self._on_font_changed(item)
        )
        return combo

    def _set_font_combo_value(self, key: str, value: str) -> None:
        combo = self._font_controls.get(key)
        if combo is None:
            return
        target = self._normalize_font_name(value)
        if not target:
            return
        index = combo.findData(target)
        if index < 0:
            combo.addItem(target, target)
            index = combo.findData(target)
        combo.setCurrentIndex(max(0, index))

    def _add_color_row(
        self,
        form: QFormLayout,
        key: str,
        label: str,
        *,
        allow_auto: bool,
    ) -> None:
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        button = QPushButton()
        button.setMinimumWidth(120)
        button.clicked.connect(lambda _checked=False, item=key: self._pick_color(item))
        button.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        button.customContextMenuRequested.connect(
            lambda pos, item=key, btn=button: self._open_color_context_menu(
                item,
                btn.mapToGlobal(pos),
            )
        )
        self._color_buttons[key] = button
        h.addWidget(button)
        if allow_auto:
            self._auto_color_keys.add(key)
        form.addRow(label, row)

    def _resolved_color_tokens_for_preview(self) -> dict[str, object]:
        app = QApplication.instance()
        palette = app.palette() if app is not None else self.palette()
        return resolve_preview_style_tokens(
            preview_theme_id=self._preview_theme_id,
            style_settings=self._style,
            base_color=palette.color(QPalette.ColorRole.Base).name(QColor.NameFormat.HexRgb),
            alt_base_color=palette.color(QPalette.ColorRole.AlternateBase).name(QColor.NameFormat.HexRgb),
            text_color=palette.color(QPalette.ColorRole.Text).name(QColor.NameFormat.HexRgb),
            placeholder_color=palette.color(QPalette.ColorRole.PlaceholderText).name(
                QColor.NameFormat.HexRgb
            ),
            highlight_color=palette.color(QPalette.ColorRole.Highlight).name(QColor.NameFormat.HexRgb),
            mid_color=palette.color(QPalette.ColorRole.Mid).name(QColor.NameFormat.HexRgb),
        )

    def _auto_color_value_for_key(self, key: str) -> str:
        tokens = self._resolved_color_tokens_for_preview()
        mapping = {
            "heading_h1_color": "heading_h1_color",
            "heading_h2_color": "heading_h2_color",
            "heading_h3_color": "heading_h3_color",
            "heading_h4_color": "heading_h4_color",
            "heading_h5_color": "heading_h5_color",
            "heading_h6_color": "heading_h6_color",
            "bold_color": "bold_color",
            "italic_color": "italic_color",
            "bold_italic_color": "bold_italic_color",
            "link_color": "link_color",
            "body_background_color": "body_background_color",
            "body_text_color": "body_text_color",
            "code_text_color": "code_text_color",
            "table_border_color": "table_border_color",
            "quote_border_color": "quote_border_color",
            "quote_text_color": "quote_text_color",
            "code_bg_color": "code_bg_color",
            "quote_bg_color": "quote_bg_color",
            "table_header_bg_color": "table_header_bg_color",
            "table_header_text_color": "table_header_text_color",
            "hr_color": "hr_color",
            "glossary_highlight_color": "glossary_highlight_color",
        }
        token_key = mapping.get(key, "")
        if not token_key:
            return "#000000"
        return str(tokens.get(token_key, "#000000") or "#000000")

    def _refresh_all_value_widgets_from_state(self) -> None:
        for key in self._font_controls:
            self._set_font_combo_value(key, str(self._style.get(key, "")))
        for key, widget in self._float_controls.items():
            try:
                value = float(self._style.get(key, widget.value()))
            except Exception:
                value = widget.value()
            widget.setValue(value)
        for key, widget in self._int_controls.items():
            try:
                value = int(float(self._style.get(key, widget.value())))
            except Exception:
                value = widget.value()
            widget.setValue(value)
        image_mode = str(self._style.get("image_mode", "yes")).lower()
        if image_mode not in IMAGE_MODE_OPTIONS:
            image_mode = "yes"
        self._image_mode_combo.setCurrentIndex(
            max(0, self._image_mode_combo.findData(image_mode))
        )
        for key in self._color_buttons:
            self._refresh_color_button(key)

    def _refresh_color_button(self, key: str) -> None:
        button = self._color_buttons.get(key)
        if button is None:
            return
        explicit_value = str(self._style.get(key, "") or "").strip()
        using_auto = (not explicit_value) and (key in self._auto_color_keys)
        value = explicit_value or self._auto_color_value_for_key(key)
        if value:
            label = f"{value} (auto)" if using_auto else value
            button.setText(label)
            button.setStyleSheet(
                "QPushButton {"
                f"background:{value};"
                "color:black;"
                "border:1px solid palette(mid);"
                "padding:2px 8px;"
                "}"
            )
            if using_auto:
                button.setToolTip("Aktuelle Auto-Farbe aus Theme/HTML-Stil.")
            else:
                button.setToolTip("Manuell gesetzt.")
        else:
            button.setText("#000000")
            button.setStyleSheet("")

    def _set_margin_combo_from_em(self, em: float) -> None:
        best_index = 0
        best_diff = float("inf")
        for idx in range(self._margin_preset_combo.count()):
            value = float(self._margin_preset_combo.itemData(idx))
            diff = abs(value - float(em))
            if diff < best_diff:
                best_diff = diff
                best_index = idx
        self._margin_preset_combo.setCurrentIndex(best_index)

    def _apply_quick_preset(self) -> None:
        theme_id = str(self._quick_preset_combo.currentData() or "classic")
        self._preview_theme_id = CanvasPreviewPane.normalize_preview_theme_id(theme_id)
        self._style = normalize_preview_style_settings(default_preview_style_settings())
        self._updating = True
        try:
            self._preview_theme_combo.setCurrentIndex(
                max(0, self._preview_theme_combo.findData(self._preview_theme_id))
            )
            self._refresh_all_value_widgets_from_state()
        finally:
            self._updating = False
        if callable(self._on_preview_theme_changed):
            self._on_preview_theme_changed(self._preview_theme_id)
        self._emit_style_changed()

    def _reset_style_defaults(self) -> None:
        self._style = normalize_preview_style_settings(default_preview_style_settings())
        self._updating = True
        try:
            self._refresh_all_value_widgets_from_state()
        finally:
            self._updating = False
        self._emit_style_changed()

    def _on_theme_combo_changed(self) -> None:
        if self._updating:
            return
        theme_id = str(self._theme_combo.currentData() or "")
        self._theme_id = theme_id
        if callable(self._on_theme_changed):
            self._on_theme_changed(theme_id)

    def _on_preview_theme_combo_changed(self) -> None:
        if self._updating:
            return
        preview_theme = CanvasPreviewPane.normalize_preview_theme_id(
            self._preview_theme_combo.currentData()
        )
        self._preview_theme_id = preview_theme
        if callable(self._on_preview_theme_changed):
            self._on_preview_theme_changed(preview_theme)
        self._emit_style_changed()

    def _on_margin_preset_changed(self) -> None:
        if self._updating:
            return
        self._page_margin_em = float(
            self._margin_preset_combo.currentData() or CanvasPreviewPane.page_margin_default_em()
        )
        self._emit_page_margin_changed()

    def _emit_page_margin_changed(self) -> None:
        if self._updating:
            return
        self._page_margin_enabled = bool(self._margin_enabled_cb.isChecked())
        if callable(self._on_page_margin_changed):
            self._on_page_margin_changed(
                {
                    "enabled": bool(self._page_margin_enabled),
                    "em": float(self._page_margin_em),
                }
            )

    def _on_font_changed(self, key: str) -> None:
        if self._updating:
            return
        widget = self._font_controls.get(key)
        if widget is None:
            return
        self._style[key] = str(widget.currentData() or widget.currentText() or "")
        self._emit_style_changed()

    def _on_float_changed(self, key: str) -> None:
        if self._updating:
            return
        widget = self._float_controls.get(key)
        if widget is None:
            return
        self._style[key] = float(widget.value())
        self._emit_style_changed()

    def _on_int_changed(self, key: str) -> None:
        if self._updating:
            return
        widget = self._int_controls.get(key)
        if widget is None:
            return
        self._style[key] = int(widget.value())
        self._emit_style_changed()

    def _on_image_mode_changed(self) -> None:
        if self._updating:
            return
        self._style["image_mode"] = str(self._image_mode_combo.currentData() or "yes")
        self._emit_style_changed()

    def _pick_color(self, key: str) -> None:
        current = str(self._style.get(key, "") or "").strip()
        if not current:
            current = self._auto_color_value_for_key(key)
        initial = QColor(current if current else "#FFFFFF")
        color = QColorDialog.getColor(initial, self, "Farbe wählen")
        if not color.isValid():
            return
        self._set_color_value(
            key,
            color.name(QColor.NameFormat.HexRgb).upper(),
        )

    def _open_color_context_menu(self, key: str, global_pos) -> None:
        if key not in self._auto_color_keys:
            return
        menu = QMenu(self)
        reset_action = menu.addAction("Auto-Farbe verwenden")
        picked = menu.exec(global_pos)
        if picked is reset_action:
            self._set_color_value(key, "")

    def _set_color_value(self, key: str, value: str) -> None:
        if self._updating:
            return
        self._style[key] = str(value or "")
        self._refresh_color_button(key)
        self._emit_style_changed()

    def _emit_style_changed(self) -> None:
        if self._updating:
            return
        normalized = normalize_preview_style_settings(self._style)
        self._style = dict(normalized)
        for key in self._color_buttons:
            self._refresh_color_button(key)
        if callable(self._on_style_changed):
            self._on_style_changed(dict(self._style))
