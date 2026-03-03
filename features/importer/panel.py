from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .models import PDFImportSettings
from .panel_groups import (
    build_general_group,
    build_heading_group,
    build_hf_group,
    build_para_group,
    build_tbl_img_group,
)
from .panel_helpers import set_combo_value, set_form_row_visible
from core.user_modes import (
    USER_MODE_EXPERT,
    USER_MODE_PLUS,
    mode_rank,
    normalize_user_mode,
)


class PDFSettingsPanel(QScrollArea):
    """
    Scrollable settings panel covering all PDF import configuration.

    Signals
    -------
    preview_requested   "▶ Preview" clicked
    detect_requested    "🔍 Run Auto-Detect" (H/F) clicked
    analyze_requested   "🔬 Analyze Fonts" clicked
    settings_changed    Any control changed
    """

    preview_requested = Signal()
    detect_requested = Signal()
    analyze_requested = Signal()
    settings_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._block = False
        self._user_mode = USER_MODE_PLUS
        self._mode_hf_visible = True
        self._mode_hf_advanced = False
        self._mode_hf_debug = False
        self._mode_heading_custom = False
        self._mode_para_smart_visible = True
        self._mode_para_fill_visible = False
        self._last_font_result: Optional[dict] = None
        self._detect_debug_info: str = ""
        self._font_debug_info: str = ""
        self._setup_ui()

    # ──────────────────────────────────────────────────────────────────────
    # UI construction
    # ──────────────────────────────────────────────────────────────────────

    def _setup_ui(self):
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)

        content = QWidget()
        root = QVBoxLayout(content)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        self._group_general = build_general_group(self)
        self._group_tbl_img = build_tbl_img_group(self)
        self._group_hf = build_hf_group(self)
        self._group_heading = build_heading_group(self)
        self._group_para = build_para_group(self)
        root.addWidget(self._group_general)
        root.addWidget(self._group_tbl_img)
        root.addWidget(self._group_hf)
        root.addWidget(self._group_heading)
        root.addWidget(self._group_para)

        self._btn_preview = QPushButton("▶   Preview with These Settings")
        self._btn_preview.setObjectName("primary")
        self._btn_preview.setToolTip("Convert this PDF with current settings and show result")
        self._btn_preview.clicked.connect(self.preview_requested)
        root.addWidget(self._btn_preview)

        root.addStretch()
        self.setWidget(content)
        self._connect_all()
        self.set_user_mode(self._user_mode)

    # ── Internal state sync ───────────────────────────────────────────────

    def _sync_heading_mode(self):
        mode = self._heading_mode.currentText().split()[0]
        self._hdg_custom_widget.setVisible(self._mode_heading_custom)
        self._hdg_custom_widget.setEnabled(self._mode_heading_custom and mode == "custom")

    def _sync_para_mode(self):
        mode = self._para_mode.currentText()
        self._para_smart_widget.setVisible(self._mode_para_smart_visible)
        self._para_smart_widget.setEnabled(self._mode_para_smart_visible and mode == "smart")
        set_form_row_visible(
            self._para_fill_form,
            self._para_min_fill,
            self._mode_para_fill_visible,
        )

    def _is_auto_hf_mode(self) -> bool:
        return self._hf_mode.currentIndex() == 0

    def _sync_hf_widgets(self):
        auto = self._is_auto_hf_mode()
        show_auto = self._mode_hf_visible and auto and self._mode_hf_advanced
        show_detect = self._mode_hf_visible and auto
        show_manual = self._mode_hf_visible and (not auto)
        show_debug = show_detect and self._mode_hf_debug
        self._hf_auto_widget.setVisible(show_auto)
        self._btn_detect.setVisible(show_detect)
        self._btn_detect_debug.setVisible(show_debug)
        self._manual_widget.setVisible(show_manual)

        self._hf_auto_widget.setEnabled(show_auto)
        self._btn_detect.setEnabled(show_detect)
        self._btn_detect_debug.setEnabled(show_debug and bool(self._detect_debug_info.strip()))
        self._manual_widget.setEnabled(show_manual)

    # ── Slot connections ──────────────────────────────────────────────────

    def _connect_all(self):
        pairs = [
            (self._page_range.textChanged, self._emit),
            (self._show_markers.toggled, self._emit),
            (self._table_strategy.currentTextChanged, self._emit),
            (self._write_images.toggled, self._emit),
            (self._image_format.currentTextChanged, self._emit),
            (self._dpi.valueChanged, self._emit),
            (self._graphics_limit.valueChanged, self._emit),
            (self._hf_mode.currentIndexChanged, self._on_hf_mode_changed),
            (self._hf_top_zone.valueChanged, self._emit),
            (self._hf_bottom_zone.valueChanged, self._emit),
            (self._hf_min_pages.valueChanged, self._emit),
            (self._hf_threshold.valueChanged, self._emit),
            (self._hf_max_pairs.valueChanged, self._emit),
            (self._heading_mode.currentIndexChanged, self._emit),
            (self._hdg_h1_ratio.valueChanged, self._emit),
            (self._hdg_h2_ratio.valueChanged, self._emit),
            (self._hdg_h3_ratio.valueChanged, self._emit),
            (self._hdg_max_chars.valueChanged, self._emit),
            (self._hdg_bold.toggled, self._emit),
            (self._hdg_color.toggled, self._emit),
            (self._para_mode.currentTextChanged, self._emit),
            (self._para_sentence_end.toggled, self._emit),
            (self._para_join_hyphen.toggled, self._emit),
            (self._para_min_fill.valueChanged, self._emit),
        ]
        for sig, slot in pairs:
            sig.connect(slot)

    def _emit(self, *_):
        if not self._block:
            self.settings_changed.emit()

    def _on_hf_mode_changed(self, _):
        self._sync_hf_widgets()
        self._emit()

    def _on_heading_mode_changed(self, _):
        self._sync_heading_mode()
        self._emit()

    def _on_para_mode_changed(self, _):
        self._sync_para_mode()
        self._emit()

    # ── Public API ────────────────────────────────────────────────────────

    def get_settings(self) -> PDFImportSettings:
        s = PDFImportSettings()
        s.page_range = self._page_range.text().strip() or "all"
        s.show_page_markers = self._show_markers.isChecked()
        s.table_strategy = self._table_strategy.currentText()
        s.write_images = self._write_images.isChecked()
        s.image_format = self._image_format.currentText()
        s.dpi = self._dpi.value()
        s.graphics_limit = self._graphics_limit.value()
        s.auto_hf_detect = self._is_auto_hf_mode()
        s.hf_top_zone = self._hf_top_zone.value() / 100.0
        s.hf_bottom_zone = self._hf_bottom_zone.value() / 100.0
        s.hf_min_pages = self._hf_min_pages.value()
        s.hf_threshold = self._hf_threshold.value() / 100.0
        s.hf_max_pairs = self._hf_max_pairs.value()
        s.use_manual_margins = False
        s.margin_top = 0.0
        s.margin_bottom = 0.0
        s.margin_left = 0.0
        s.margin_right = 0.0

        mode_text = self._heading_mode.currentText().split()[0]
        s.heading_mode = mode_text
        s.heading_h1_ratio = self._hdg_h1_ratio.value()
        s.heading_h2_ratio = self._hdg_h2_ratio.value()
        s.heading_h3_ratio = self._hdg_h3_ratio.value()
        s.heading_max_chars = self._hdg_max_chars.value()
        s.heading_bold_promotes = self._hdg_bold.isChecked()
        s.heading_color_promotes = self._hdg_color.isChecked()

        s.para_mode = self._para_mode.currentText()
        s.para_sentence_end = self._para_sentence_end.isChecked()
        s.para_join_hyphen = self._para_join_hyphen.isChecked()
        s.para_min_fill_ratio = self._para_min_fill.value()
        return s

    def set_settings(self, s: PDFImportSettings):
        self._block = True
        self._page_range.setText(s.page_range)
        self._show_markers.setChecked(s.show_page_markers)
        set_combo_value(self._table_strategy, s.table_strategy)
        self._write_images.setChecked(s.write_images)
        set_combo_value(self._image_format, s.image_format)
        self._dpi.setValue(s.dpi)
        self._graphics_limit.setValue(s.graphics_limit)
        self._hf_mode.setCurrentIndex(0 if s.auto_hf_detect else 1)
        self._hf_top_zone.setValue((s.hf_top_zone * 100.0) if s.hf_top_zone > 0 else 10.0)
        self._hf_bottom_zone.setValue((s.hf_bottom_zone * 100.0) if s.hf_bottom_zone > 0 else 10.0)
        self._hf_min_pages.setValue(s.hf_min_pages)
        self._hf_threshold.setValue(s.hf_threshold * 100.0)
        self._hf_max_pairs.setValue(max(1, getattr(s, "hf_max_pairs", 3)))
        self._detect_debug_info = s.detected_info or ""

        # Heading mode: find matching item by prefix
        mode = s.heading_mode
        for i in range(self._heading_mode.count()):
            if self._heading_mode.itemText(i).startswith(mode):
                self._heading_mode.setCurrentIndex(i)
                break
        self._hdg_h1_ratio.setValue(s.heading_h1_ratio)
        self._hdg_h2_ratio.setValue(s.heading_h2_ratio)
        self._hdg_h3_ratio.setValue(s.heading_h3_ratio)
        self._hdg_max_chars.setValue(s.heading_max_chars)
        self._hdg_bold.setChecked(s.heading_bold_promotes)
        self._hdg_color.setChecked(s.heading_color_promotes)

        set_combo_value(self._para_mode, s.para_mode)
        self._para_sentence_end.setChecked(s.para_sentence_end)
        self._para_join_hyphen.setChecked(s.para_join_hyphen)
        self._para_min_fill.setValue(s.para_min_fill_ratio)

        self._font_debug_info = s.font_info or ""
        self._last_font_result = None

        self._block = False
        self._sync_heading_mode()
        self._sync_para_mode()
        self._sync_hf_widgets()
        self._refresh_debug_buttons()

    def set_detect_info(self, info: str):
        self._detect_debug_info = info or ""
        self._refresh_debug_buttons()

    def set_font_info(self, result: dict):
        self._last_font_result = result
        self._font_debug_info = result.get("info", "") or ""
        self._refresh_debug_buttons()
        if all(k in result for k in ("suggested_h1", "suggested_h2", "suggested_h3")):
            self._apply_font_suggestions(result)

    def set_zones(self, top_frac: float, bottom_frac: float):
        """Update zone spinboxes from an external source (e.g. viewer drag) without emitting."""
        self._block = True
        self._hf_top_zone.setValue(top_frac * 100.0)
        self._hf_bottom_zone.setValue(bottom_frac * 100.0)
        self._block = False

    def _apply_font_suggestions(self, result: Optional[dict] = None):
        src = result or self._last_font_result
        if not src:
            return
        self._block = True
        self._hdg_h1_ratio.setValue(src.get("suggested_h1", 1.40))
        self._hdg_h2_ratio.setValue(src.get("suggested_h2", 1.20))
        self._hdg_h3_ratio.setValue(src.get("suggested_h3", 1.05))
        # Switch mode to "custom" so the new ratios are actually used
        for i in range(self._heading_mode.count()):
            if self._heading_mode.itemText(i).startswith("custom"):
                self._heading_mode.setCurrentIndex(i)
                break
        self._block = False
        self._sync_heading_mode()
        self._emit()

    def set_enabled_for_pdf(self, is_pdf: bool):
        self._btn_preview.setEnabled(is_pdf)
        self._btn_detect.setEnabled(is_pdf and self._is_auto_hf_mode())
        self._btn_analyze.setEnabled(is_pdf)
        self._btn_detect_debug.setEnabled(
            is_pdf and self._is_auto_hf_mode() and bool(self._detect_debug_info.strip())
        )
        self._btn_font_debug.setEnabled(is_pdf and bool(self._font_debug_info.strip()))
        self.widget().setEnabled(is_pdf)

    def set_user_mode(self, mode: str):
        self._user_mode = normalize_user_mode(mode)
        rank = mode_rank(self._user_mode)
        plus_or_higher = rank >= mode_rank(USER_MODE_PLUS)
        expert_only = rank >= mode_rank(USER_MODE_EXPERT)

        self._group_tbl_img.setVisible(plus_or_higher)
        self._group_hf.setVisible(plus_or_higher)
        self._group_heading.setVisible(plus_or_higher)
        self._group_para.setVisible(True)

        set_form_row_visible(self._tbl_img_form, self._graphics_limit, expert_only)
        set_form_row_visible(self._hf_auto_form, self._hf_min_pages, expert_only)
        set_form_row_visible(self._hf_auto_form, self._hf_threshold, expert_only)
        set_form_row_visible(self._hf_auto_form, self._hf_max_pairs, expert_only)

        self._mode_hf_visible = plus_or_higher
        self._mode_hf_advanced = expert_only
        self._mode_hf_debug = expert_only

        self._mode_heading_custom = expert_only
        self._btn_analyze.setVisible(expert_only)
        self._btn_font_debug.setVisible(expert_only)

        self._mode_para_smart_visible = plus_or_higher
        self._mode_para_fill_visible = expert_only

        self._sync_hf_widgets()
        self._sync_heading_mode()
        self._sync_para_mode()
        self._refresh_debug_buttons()

    def _refresh_debug_buttons(self):
        self._btn_detect_debug.setEnabled(
            self._mode_hf_debug and self._is_auto_hf_mode() and bool(self._detect_debug_info.strip())
        )
        self._btn_font_debug.setEnabled(self._mode_heading_custom and bool(self._font_debug_info.strip()))

    def _show_detect_debug(self):
        self._show_debug_dialog(
            "Header/Footer Debug Info",
            self._detect_debug_info or "No debug info available yet.",
        )

    def _show_font_debug(self):
        self._show_debug_dialog(
            "Font Analysis Debug Info",
            self._font_debug_info or "No debug info available yet.",
        )

    def _show_debug_dialog(self, title: str, text: str):
        dlg = QDialog(self)
        dlg.setWindowTitle(title)
        dlg.resize(860, 560)
        lay = QVBoxLayout(dlg)
        edit = QPlainTextEdit()
        edit.setReadOnly(True)
        edit.setPlainText(text)
        lay.addWidget(edit)
        row = QHBoxLayout()
        row.addStretch()
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(dlg.accept)
        row.addWidget(btn_close)
        lay.addLayout(row)
        dlg.exec()
