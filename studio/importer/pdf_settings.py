"""Compact PDF settings panel for importer dialog."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from shared.services.importer.models import PDFImportSettings


class PDFSettingsPanel(QWidget):
    """Minimal settings panel with preview/detect/analyze actions."""

    preview_requested = Signal()
    detect_requested = Signal()
    analyze_requested = Signal()
    settings_changed = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._settings = PDFImportSettings()
        self._user_mode = "plus"
        self._info_label = QLabel("")
        self._font_info_label = QLabel("")
        self._setup_ui()

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        btn_row = QHBoxLayout()
        self._btn_preview = QPushButton("▶ Preview")
        self._btn_detect = QPushButton("Auto Detect")
        self._btn_analyze = QPushButton("Analyze Fonts")
        self._btn_preview.clicked.connect(self.preview_requested.emit)
        self._btn_detect.clicked.connect(self.detect_requested.emit)
        self._btn_analyze.clicked.connect(self.analyze_requested.emit)
        btn_row.addWidget(self._btn_preview)
        btn_row.addWidget(self._btn_detect)
        btn_row.addWidget(self._btn_analyze)
        btn_row.addStretch()
        root.addLayout(btn_row)

        self._info_label.setWordWrap(True)
        self._font_info_label.setWordWrap(True)
        root.addWidget(self._info_label)
        root.addWidget(self._font_info_label)
        root.addStretch()

    def set_user_mode(self, mode: str) -> None:
        self._user_mode = str(mode or "plus").strip().lower() or "plus"

    def set_enabled_for_pdf(self, enabled: bool) -> None:
        self.setEnabled(bool(enabled))

    def widget(self) -> QWidget:
        return self

    def set_settings(self, settings: PDFImportSettings) -> None:
        self._settings = settings
        self.settings_changed.emit()

    def get_settings(self) -> PDFImportSettings:
        return self._settings

    def set_zones(self, top: float, bottom: float) -> None:
        self._settings.hf_top_zone = float(top)
        self._settings.hf_bottom_zone = float(bottom)
        self.settings_changed.emit()

    def set_detect_info(self, text: str) -> None:
        self._info_label.setText(str(text or ""))

    def set_font_info(self, info: dict) -> None:
        if not isinstance(info, dict):
            self._font_info_label.setText("")
            return
        self._font_info_label.setText(str(info.get("info", "") or ""))
