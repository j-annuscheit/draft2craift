from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QDialog

from shared.domain.user_mode import (
    default_user_mode,
    normalize_user_mode,
    resolve_feature_label,
)

from .dialog_selection import FileImportSelectionMixin
from .dialog_ui import FileImportDialogUIMixin
from .dialog_workers import FileImportWorkersMixin
from shared.services.importer.entry import ImportEntry
from .ui_constants import _DIALOG_STYLE
from .workers import (
    ConversionWorker,
    DetectWorker,
    FontAnalysisWorker,
    MarkdownLLMFixWorker,
    SingleConversionWorker,
)


class FileImportDialog(
    FileImportDialogUIMixin,
    FileImportSelectionMixin,
    FileImportWorkersMixin,
    QDialog,
):
    """
    Three-pane dialog for importing and converting files to Markdown.

    Left   – file list
    Middle – PDF settings panel  (greyed out for non-PDF files)
    Right  – Markdown preview
    """

    files_imported = Signal(list)

    def __init__(self, parent=None, user_mode: str | None = None, feedback_service=None):
        super().__init__(parent)
        self.setWindowTitle("Import Files")
        self.resize(1180, 660)
        self.setStyleSheet(_DIALOG_STYLE)
        self._user_mode = normalize_user_mode(default_user_mode() if user_mode is None else user_mode)
        self._feedback_service = feedback_service

        self._entries: dict[str, ImportEntry] = {}
        self._current_path: Optional[str] = None

        self._worker: Optional[ConversionWorker] = None
        self._preview_worker: Optional[SingleConversionWorker] = None
        self._detect_worker: Optional[DetectWorker] = None
        self._font_worker: Optional[FontAnalysisWorker] = None
        self._llm_fix_worker: Optional[MarkdownLLMFixWorker] = None
        self._llm_fix_path: Optional[str] = None
        self._llm_fix_status_by_path: dict[str, dict[str, object]] = {}
        self._llm_fix_queue: list[str] = []
        self._llm_fix_total: int = 0
        self._llm_fix_done_count: int = 0
        self._llm_fix_batch_active: bool = False
        self._pending_select_after_import: Optional[str] = None

        self._splitter = None
        self._settings_visible = False

        self._setup_ui()

    def _prepare_for_handover_and_close(self):
        """
        Deterministically release heavy preview resources before dialog close.

        This avoids late C-level cleanup races (fitz/PyMuPDF in PDF preview)
        during object destruction after Import-and-Close.
        """
        try:
            viewer = getattr(self, "_pdf_viewer", None)
            if viewer is not None and hasattr(viewer, "clear"):
                viewer.clear()
        except Exception:
            pass
        try:
            self._current_path = None
            preview = getattr(self, "_preview", None)
            if preview is not None and hasattr(preview, "clear_text"):
                preview.clear_text()
        except Exception:
            pass

    def reject(self):
        busy_check = getattr(self, "_has_running_background_worker", None)
        if callable(busy_check) and bool(busy_check()):
            status = getattr(self, "_preview_status", None)
            if status is not None:
                status.setText(
                    resolve_feature_label(
                        self._user_mode,
                        "importer.dialog.status.close_blocked",
                        "Bitte warten: Hintergrundjob laeuft noch…",
                    )
                )
                status.setToolTip(
                    resolve_feature_label(
                        self._user_mode,
                        "importer.dialog.status.close_blocked.tooltip",
                        "Schliessen ist blockiert, bis Import/Analyse abgeschlossen ist.",
                    )
                )
                status.setVisible(True)
            return
        super().reject()
