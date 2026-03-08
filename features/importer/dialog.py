from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QDialog

from core.user_modes import USER_MODE_PLUS, normalize_user_mode

from .dialog_selection import FileImportSelectionMixin
from .dialog_ui import FileImportDialogUIMixin
from .dialog_workers import FileImportWorkersMixin
from .entry import ImportEntry
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

    def __init__(self, parent=None, user_mode: str = USER_MODE_PLUS, feedback_service=None):
        super().__init__(parent)
        self.setWindowTitle("Import Files")
        self.resize(1180, 660)
        self.setStyleSheet(_DIALOG_STYLE)
        self._user_mode = normalize_user_mode(user_mode)
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

        self._splitter = None
        self._settings_visible = False

        self._setup_ui()
