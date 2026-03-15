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

from shared.services.importer.models import PDFImportSettings
from .pdf_settings_groups import (
    build_general_group,
    build_heading_group,
    build_hf_group,
    build_para_group,
    build_tbl_img_group,
)
from .pdf_settings_helpers import set_combo_value, set_form_row_visible
from shared.domain.user_mode import (
    default_user_mode,
    is_feature_visible,
    normalize_user_mode,
    resolve_feature_label,
)


def _set_form_row_label(form: QFormLayout, field: QWidget, label_text: str) -> None:
    label = form.labelForField(field)
    if label is not None:
        label.setText(str(label_text or ""))


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
        self._user_mode = default_user_mode()
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
        show_tbl_img = bool(
            is_feature_visible(
                self._user_mode,
                "importer.pdf.group.tbl_img",
                default=True,
            )
        )
        show_hf = bool(
            is_feature_visible(
                self._user_mode,
                "importer.pdf.group.header_footer",
                default=True,
            )
        )
        show_heading = bool(
            is_feature_visible(
                self._user_mode,
                "importer.pdf.group.heading",
                default=True,
            )
        )
        show_para = bool(
            is_feature_visible(
                self._user_mode,
                "importer.pdf.group.paragraph",
                default=True,
            )
        )

        show_tbl_graphics_limit = bool(
            is_feature_visible(
                self._user_mode,
                "importer.pdf.tbl_img.graphics_limit",
                default=False,
            )
        )
        show_hf_min_pages = bool(
            is_feature_visible(
                self._user_mode,
                "importer.pdf.header_footer.min_pages",
                default=False,
            )
        )
        show_hf_threshold = bool(
            is_feature_visible(
                self._user_mode,
                "importer.pdf.header_footer.threshold",
                default=False,
            )
        )
        show_hf_max_pairs = bool(
            is_feature_visible(
                self._user_mode,
                "importer.pdf.header_footer.max_pairs",
                default=False,
            )
        )
        show_hf_debug = bool(
            is_feature_visible(
                self._user_mode,
                "importer.pdf.header_footer.debug_button",
                default=False,
            )
        )
        show_heading_custom = bool(
            is_feature_visible(
                self._user_mode,
                "importer.pdf.heading.custom_options",
                default=False,
            )
        )
        show_heading_analyze = bool(
            is_feature_visible(
                self._user_mode,
                "importer.pdf.heading.analyze_button",
                default=False,
            )
        )
        show_heading_debug = bool(
            is_feature_visible(
                self._user_mode,
                "importer.pdf.heading.debug_button",
                default=False,
            )
        )
        show_para_smart = bool(
            is_feature_visible(
                self._user_mode,
                "importer.pdf.paragraph.smart_options",
                default=True,
            )
        )
        show_para_fill = bool(
            is_feature_visible(
                self._user_mode,
                "importer.pdf.paragraph.min_fill",
                default=False,
            )
        )

        self._group_tbl_img.setVisible(show_tbl_img)
        self._group_hf.setVisible(show_hf)
        self._group_heading.setVisible(show_heading)
        self._group_para.setVisible(show_para)

        set_form_row_visible(self._tbl_img_form, self._graphics_limit, show_tbl_graphics_limit)
        set_form_row_visible(self._hf_auto_form, self._hf_min_pages, show_hf_min_pages)
        set_form_row_visible(self._hf_auto_form, self._hf_threshold, show_hf_threshold)
        set_form_row_visible(self._hf_auto_form, self._hf_max_pairs, show_hf_max_pairs)

        self._mode_hf_visible = show_hf
        self._mode_hf_advanced = bool(show_hf_min_pages or show_hf_threshold or show_hf_max_pairs)
        self._mode_hf_debug = show_hf_debug

        self._mode_heading_custom = show_heading_custom
        self._btn_analyze.setVisible(show_heading_analyze)
        self._btn_font_debug.setVisible(show_heading_debug)

        self._mode_para_smart_visible = show_para_smart
        self._mode_para_fill_visible = show_para_fill

        self._btn_preview.setText(
            resolve_feature_label(
                self._user_mode,
                "importer.pdf.button.preview",
                "▶   Preview with These Settings",
            )
        )
        self._btn_detect.setText(
            resolve_feature_label(
                self._user_mode,
                "importer.pdf.button.detect",
                "🔍  Run Auto-Detect",
            )
        )
        self._btn_detect_debug.setText(
            resolve_feature_label(
                self._user_mode,
                "importer.pdf.button.detect_debug",
                "Debug Info…",
            )
        )
        self._btn_analyze.setText(
            resolve_feature_label(
                self._user_mode,
                "importer.pdf.button.analyze_fonts",
                "🔬  Analyze Fonts + Apply",
            )
        )
        self._btn_font_debug.setText(
            resolve_feature_label(
                self._user_mode,
                "importer.pdf.button.font_debug",
                "Debug Info…",
            )
        )
        self._btn_preview.setToolTip(
            resolve_feature_label(
                self._user_mode,
                "importer.pdf.button.preview.tooltip",
                "Convert this PDF with current settings and show result",
            )
        )
        self._btn_detect.setToolTip(
            resolve_feature_label(
                self._user_mode,
                "importer.pdf.button.detect.tooltip",
                "Scan the PDF and show which H/F would be removed",
            )
        )
        self._btn_analyze.setToolTip(
            resolve_feature_label(
                self._user_mode,
                "importer.pdf.button.analyze_fonts.tooltip",
                "Inspect all font sizes in the PDF.\nAutomatically applies suggested H1/H2/H3 ratios.",
            )
        )
        self._btn_detect_debug.setToolTip(
            resolve_feature_label(
                self._user_mode,
                "importer.pdf.button.detect_debug.tooltip",
                "Open Header/Footer detection details in a separate window.",
            )
        )
        self._btn_font_debug.setToolTip(
            resolve_feature_label(
                self._user_mode,
                "importer.pdf.button.font_debug.tooltip",
                "Open font-analysis details in a separate window.",
            )
        )

        self._group_general.setTitle(
            resolve_feature_label(
                self._user_mode,
                "importer.pdf.group.general.title",
                "General",
            )
        )
        self._group_tbl_img.setTitle(
            resolve_feature_label(
                self._user_mode,
                "importer.pdf.group.tables_images.title",
                "Tables & Images",
            )
        )
        self._group_hf.setTitle(
            resolve_feature_label(
                self._user_mode,
                "importer.pdf.group.header_footer.title",
                "Header / Footer Removal",
            )
        )
        self._group_heading.setTitle(
            resolve_feature_label(
                self._user_mode,
                "importer.pdf.group.heading.title",
                "Heading Detection",
            )
        )
        self._group_para.setTitle(
            resolve_feature_label(
                self._user_mode,
                "importer.pdf.group.paragraph.title",
                "Paragraph Reflow",
            )
        )

        _set_form_row_label(
            self._general_form,
            self._page_range,
            resolve_feature_label(
                self._user_mode,
                "importer.pdf.general.pages",
                "Pages:",
            ),
        )
        self._page_range.setPlaceholderText(
            resolve_feature_label(
                self._user_mode,
                "importer.pdf.general.pages.placeholder",
                "all   or   1-5,7,10-",
            )
        )
        self._page_range.setToolTip(
            resolve_feature_label(
                self._user_mode,
                "importer.pdf.general.pages.tooltip",
                "Page range (1-indexed, inclusive).\n"
                "  all   → all pages\n"
                "  1-10  → pages 1–10\n"
                "  1-5,8,12-  → pages 1-5, 8, 12 to end",
            )
        )
        self._show_markers.setText(
            resolve_feature_label(
                self._user_mode,
                "importer.pdf.general.show_markers",
                "Insert [Seite N] page markers",
            )
        )
        self._show_markers.setToolTip(
            resolve_feature_label(
                self._user_mode,
                "importer.pdf.general.show_markers.tooltip",
                "Adds page marker lines to the generated Markdown.\n"
                "Heading overlays in the PDF viewer remain global and do not depend on markers.",
            )
        )

        _set_form_row_label(
            self._tbl_img_form,
            self._table_strategy,
            resolve_feature_label(
                self._user_mode,
                "importer.pdf.tables.table_strategy",
                "Table strategy:",
            ),
        )
        self._table_strategy.setToolTip(
            resolve_feature_label(
                self._user_mode,
                "importer.pdf.tables.table_strategy.tooltip",
                "lines_strict  Strict line-based (default)\n"
                "lines          Flexible line-based\n"
                "text           Text-flow based\n"
                "none           Disable table extraction",
            )
        )
        self._write_images.setText(
            resolve_feature_label(
                self._user_mode,
                "importer.pdf.tables.extract_images",
                "Extract images to disk",
            )
        )
        self._write_images.setToolTip(
            resolve_feature_label(
                self._user_mode,
                "importer.pdf.tables.extract_images.tooltip",
                "Extract images and save them to disk during conversion.",
            )
        )
        _set_form_row_label(
            self._tbl_img_form,
            self._image_format,
            resolve_feature_label(
                self._user_mode,
                "importer.pdf.tables.image_format",
                "Image format:",
            ),
        )
        self._image_format.setToolTip(
            resolve_feature_label(
                self._user_mode,
                "importer.pdf.tables.image_format.tooltip",
                "Choose image output format.",
            )
        )
        _set_form_row_label(
            self._tbl_img_form,
            self._dpi,
            resolve_feature_label(
                self._user_mode,
                "importer.pdf.tables.dpi",
                "DPI:",
            ),
        )
        self._dpi.setToolTip(
            resolve_feature_label(
                self._user_mode,
                "importer.pdf.tables.dpi.tooltip",
                "Rendering resolution used for extracted images.",
            )
        )
        _set_form_row_label(
            self._tbl_img_form,
            self._graphics_limit,
            resolve_feature_label(
                self._user_mode,
                "importer.pdf.tables.graphics_limit",
                "Graphics limit:",
            ),
        )
        self._graphics_limit.setToolTip(
            resolve_feature_label(
                self._user_mode,
                "importer.pdf.tables.graphics_limit.tooltip",
                "Max graphics per page  (0 = unlimited)",
            )
        )

        _set_form_row_label(
            self._hf_mode_form,
            self._hf_mode,
            resolve_feature_label(
                self._user_mode,
                "importer.pdf.header_footer.mode",
                "Mode:",
            ),
        )
        self._hf_mode.setToolTip(
            resolve_feature_label(
                self._user_mode,
                "importer.pdf.header_footer.mode.tooltip",
                "Auto-Detect: finds repeating headers/footers per page (supports merged PDFs).\n"
                "Manual: apply one fixed top/bottom scan zone for all pages.",
            )
        )
        self._hf_mode.setItemText(
            0,
            resolve_feature_label(
                self._user_mode,
                "importer.pdf.header_footer.mode.auto_detect",
                "Auto-Detect (per page)",
            ),
        )
        self._hf_mode.setItemText(
            1,
            resolve_feature_label(
                self._user_mode,
                "importer.pdf.header_footer.mode.manual_scan",
                "Manual scan zones (all pages)",
            ),
        )
        _set_form_row_label(
            self._hf_auto_form,
            self._hf_min_pages,
            resolve_feature_label(
                self._user_mode,
                "importer.pdf.header_footer.min_repeats",
                "Min. repeats:",
            ),
        )
        self._hf_min_pages.setToolTip(
            resolve_feature_label(
                self._user_mode,
                "importer.pdf.header_footer.min_repeats.tooltip",
                "Minimum page count where a line must repeat to be classified as running element.",
            )
        )
        _set_form_row_label(
            self._hf_auto_form,
            self._hf_threshold,
            resolve_feature_label(
                self._user_mode,
                "importer.pdf.header_footer.min_fraction",
                "Min. fraction:",
            ),
        )
        self._hf_threshold.setToolTip(
            resolve_feature_label(
                self._user_mode,
                "importer.pdf.header_footer.min_fraction.tooltip",
                "Alternative minimum as fraction of total pages.",
            )
        )
        _set_form_row_label(
            self._hf_auto_form,
            self._hf_max_pairs,
            resolve_feature_label(
                self._user_mode,
                "importer.pdf.header_footer.max_pairs",
                "Max pairs:",
            ),
        )
        self._hf_max_pairs.setToolTip(
            resolve_feature_label(
                self._user_mode,
                "importer.pdf.header_footer.max_pairs.tooltip",
                "Maximum number of header/footer combinations across the document.",
            )
        )
        _set_form_row_label(
            self._hf_manual_form,
            self._hf_top_zone,
            resolve_feature_label(
                self._user_mode,
                "importer.pdf.header_footer.top_scan_zone",
                "Top scan zone:",
            ),
        )
        self._hf_top_zone.setToolTip(
            resolve_feature_label(
                self._user_mode,
                "importer.pdf.header_footer.top_scan_zone.tooltip",
                "Relative top scan zone in percent.",
            )
        )
        _set_form_row_label(
            self._hf_manual_form,
            self._hf_bottom_zone,
            resolve_feature_label(
                self._user_mode,
                "importer.pdf.header_footer.bottom_scan_zone",
                "Bottom scan zone:",
            ),
        )
        self._hf_bottom_zone.setToolTip(
            resolve_feature_label(
                self._user_mode,
                "importer.pdf.header_footer.bottom_scan_zone.tooltip",
                "Relative bottom scan zone in percent.",
            )
        )

        _set_form_row_label(
            self._heading_mode_form,
            self._heading_mode,
            resolve_feature_label(
                self._user_mode,
                "importer.pdf.heading.mode",
                "Mode:",
            ),
        )
        self._heading_mode.setToolTip(
            resolve_feature_label(
                self._user_mode,
                "importer.pdf.heading.mode.tooltip",
                "pymupdf4llm  Use the library's built-in detection\n"
                "custom        Apply the size ratios / bold / color rules below\n"
                "none          Disable heading detection entirely",
            )
        )
        self._heading_mode.setItemText(
            0,
            resolve_feature_label(
                self._user_mode,
                "importer.pdf.heading.mode.pymupdf",
                "pymupdf4llm  (default)",
            ),
        )
        self._heading_mode.setItemText(
            1,
            resolve_feature_label(
                self._user_mode,
                "importer.pdf.heading.mode.custom",
                "custom",
            ),
        )
        self._heading_mode.setItemText(
            2,
            resolve_feature_label(
                self._user_mode,
                "importer.pdf.heading.mode.none",
                "none  (off)",
            ),
        )
        _set_form_row_label(
            self._heading_ratio_form,
            self._hdg_h1_ratio,
            resolve_feature_label(
                self._user_mode,
                "importer.pdf.heading.h1_ratio",
                "H1 size ratio:",
            ),
        )
        self._hdg_h1_ratio.setToolTip(
            resolve_feature_label(
                self._user_mode,
                "importer.pdf.heading.h1_ratio.tooltip",
                "size ≥ body × ratio → H1",
            )
        )
        _set_form_row_label(
            self._heading_ratio_form,
            self._hdg_h2_ratio,
            resolve_feature_label(
                self._user_mode,
                "importer.pdf.heading.h2_ratio",
                "H2 size ratio:",
            ),
        )
        self._hdg_h2_ratio.setToolTip(
            resolve_feature_label(
                self._user_mode,
                "importer.pdf.heading.h2_ratio.tooltip",
                "size ≥ body × ratio → H2",
            )
        )
        _set_form_row_label(
            self._heading_ratio_form,
            self._hdg_h3_ratio,
            resolve_feature_label(
                self._user_mode,
                "importer.pdf.heading.h3_ratio",
                "H3 size ratio:",
            ),
        )
        self._hdg_h3_ratio.setToolTip(
            resolve_feature_label(
                self._user_mode,
                "importer.pdf.heading.h3_ratio.tooltip",
                "size ≥ body × ratio → H3",
            )
        )
        _set_form_row_label(
            self._heading_ratio_form,
            self._hdg_max_chars,
            resolve_feature_label(
                self._user_mode,
                "importer.pdf.heading.max_chars",
                "Max heading chars:",
            ),
        )
        self._hdg_max_chars.setToolTip(
            resolve_feature_label(
                self._user_mode,
                "importer.pdf.heading.max_chars.tooltip",
                "Lines longer than this value are never treated as headings.",
            )
        )
        self._hdg_bold.setText(
            resolve_feature_label(
                self._user_mode,
                "importer.pdf.heading.bold_promotes",
                "Bold at body size → H3",
            )
        )
        self._hdg_bold.setToolTip(
            resolve_feature_label(
                self._user_mode,
                "importer.pdf.heading.bold_promotes.tooltip",
                "Promote bold text near body size to H3.",
            )
        )
        self._hdg_color.setText(
            resolve_feature_label(
                self._user_mode,
                "importer.pdf.heading.color_promotes",
                "Colored text → H3",
            )
        )
        self._hdg_color.setToolTip(
            resolve_feature_label(
                self._user_mode,
                "importer.pdf.heading.color_promotes.tooltip",
                "Promote colored text near body size to H3.",
            )
        )

        _set_form_row_label(
            self._para_mode_form,
            self._para_mode,
            resolve_feature_label(
                self._user_mode,
                "importer.pdf.paragraph.mode",
                "Mode:",
            ),
        )
        self._para_mode.setItemText(
            0,
            resolve_feature_label(
                self._user_mode,
                "importer.pdf.paragraph.mode.smart",
                "smart",
            ),
        )
        self._para_mode.setItemText(
            1,
            resolve_feature_label(
                self._user_mode,
                "importer.pdf.paragraph.mode.join",
                "join",
            ),
        )
        self._para_mode.setItemText(
            2,
            resolve_feature_label(
                self._user_mode,
                "importer.pdf.paragraph.mode.none",
                "none",
            ),
        )
        self._para_sentence_end.setText(
            resolve_feature_label(
                self._user_mode,
                "importer.pdf.paragraph.sentence_end",
                "Line ending with  . ! ?  → paragraph boundary",
            )
        )
        self._para_sentence_end.setToolTip(
            resolve_feature_label(
                self._user_mode,
                "importer.pdf.paragraph.sentence_end.tooltip",
                "When enabled, sentence-ending short lines trigger paragraph breaks.",
            )
        )
        self._para_join_hyphen.setText(
            resolve_feature_label(
                self._user_mode,
                "importer.pdf.paragraph.join_hyphen",
                "Line ending with  -  → join and dehyphenate",
            )
        )
        self._para_join_hyphen.setToolTip(
            resolve_feature_label(
                self._user_mode,
                "importer.pdf.paragraph.join_hyphen.tooltip",
                "Join lines ending with hyphen and remove wrap hyphenation.",
            )
        )
        _set_form_row_label(
            self._para_fill_form,
            self._para_min_fill,
            resolve_feature_label(
                self._user_mode,
                "importer.pdf.paragraph.short_line_threshold",
                "Short-line threshold:",
            ),
        )
        self._para_min_fill.setToolTip(
            resolve_feature_label(
                self._user_mode,
                "importer.pdf.paragraph.short_line_threshold.tooltip",
                "Lower values split paragraphs more aggressively on short lines.",
            )
        )

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
            resolve_feature_label(
                self._user_mode,
                "importer.pdf.debug.detect.window_title",
                "Header/Footer Debug Info",
            ),
            self._detect_debug_info
            or resolve_feature_label(
                self._user_mode,
                "importer.pdf.debug.empty",
                "No debug info available yet.",
            ),
        )

    def _show_font_debug(self):
        self._show_debug_dialog(
            resolve_feature_label(
                self._user_mode,
                "importer.pdf.debug.font.window_title",
                "Font Analysis Debug Info",
            ),
            self._font_debug_info
            or resolve_feature_label(
                self._user_mode,
                "importer.pdf.debug.empty",
                "No debug info available yet.",
            ),
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
        btn_close = QPushButton(
            resolve_feature_label(
                self._user_mode,
                "importer.pdf.debug.button.close",
                "Close",
            )
        )
        btn_close.clicked.connect(dlg.accept)
        row.addWidget(btn_close)
        lay.addLayout(row)
        dlg.exec()
