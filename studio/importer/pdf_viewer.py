"""Compact PDF viewer panel for importer."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLabel, QTextEdit, QVBoxLayout, QWidget

from shared.services.importer.models import PDFImportSettings


class PDFViewerPanel(QWidget):
    """Simple PDF info and markdown preview panel."""

    zone_changed = Signal(float, float)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._path = ""
        self._settings = PDFImportSettings()
        self._body_size = 0.0
        self._markdown = ""
        self._setup_ui()

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)
        self._title = QLabel("No PDF loaded")
        self._meta = QLabel("")
        self._meta.setWordWrap(True)
        self._preview = QTextEdit()
        self._preview.setReadOnly(True)
        root.addWidget(self._title)
        root.addWidget(self._meta)
        root.addWidget(self._preview, stretch=1)

    def load_pdf(
        self,
        path: str,
        settings: PDFImportSettings,
        body_size: float = 0.0,
        markdown: str = "",
    ) -> None:
        self._path = str(path or "")
        self._settings = settings
        self._body_size = float(body_size or 0.0)
        self._markdown = str(markdown or "")
        page_count = self._safe_page_count(self._path)
        self._title.setText(self._path or "No PDF loaded")
        self._meta.setText(
            f"Pages: {page_count} | Body size: {self._body_size:.2f} | Auto HF: {bool(self._settings.auto_hf_detect)}"
        )
        self._preview.setPlainText(self._markdown)

    def refresh_settings(
        self,
        settings: PDFImportSettings,
        body_size: float = 0.0,
        markdown: str = "",
    ) -> None:
        self.load_pdf(self._path, settings, body_size=body_size, markdown=markdown or self._markdown)

    def update_markdown(self, markdown: str) -> None:
        self._markdown = str(markdown or "")
        self._preview.setPlainText(self._markdown)

    def update_body_size(self, body_size: float, settings: PDFImportSettings) -> None:
        self._body_size = float(body_size or 0.0)
        self._settings = settings
        self.refresh_settings(settings, body_size=self._body_size)

    def clear(self) -> None:
        self._path = ""
        self._settings = PDFImportSettings()
        self._body_size = 0.0
        self._markdown = ""
        self._title.setText("No PDF loaded")
        self._meta.setText("")
        self._preview.clear()

    @staticmethod
    def _safe_page_count(path: str) -> int:
        if not str(path or "").strip():
            return 0
        try:
            import fitz  # type: ignore

            with fitz.open(path) as doc:
                return int(len(doc))
        except Exception:
            return 0
