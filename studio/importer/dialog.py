"""File import dialog with conversion and preview."""
from __future__ import annotations

import os
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from shared.domain.user_mode import USER_MODE_PLUS, normalize_user_mode
from shared.services.importer.entry import ImportEntry, converted_results, preview_placeholder_text
from shared.services.importer.models import PDFImportSettings, _SUPPORTED_FILTER
from studio.canvas.split_view import MarkdownSplitPanel
from studio.feedback.bar import FeedbackBar

from .pdf_settings import PDFSettingsPanel
from .pdf_viewer import PDFViewerPanel
from .workers import ConversionWorker


_STATUS_PENDING = "Pending"
_STATUS_DONE = "Done"
_STATUS_ERROR = "Error"
_ICON = {_STATUS_PENDING: "⏳", _STATUS_DONE: "✓", _STATUS_ERROR: "✗"}


class FileImportDialog(QDialog):
    """Compact importer dialog without mixins."""

    files_imported = Signal(list)

    def __init__(self, parent=None, user_mode: str = USER_MODE_PLUS, feedback_service=None):
        super().__init__(parent)
        self.setWindowTitle("Import Files")
        self.resize(1180, 660)
        self._user_mode = normalize_user_mode(user_mode)
        self._feedback_service = feedback_service
        self._entries: dict[str, ImportEntry] = {}
        self._current_path: Optional[str] = None
        self._worker: ConversionWorker | None = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        toolbar = QHBoxLayout()
        self._btn_add = QPushButton("Add Files…")
        self._btn_remove = QPushButton("Remove")
        self._btn_add.clicked.connect(self._add_files)
        self._btn_remove.clicked.connect(self._remove_selected)
        toolbar.addWidget(self._btn_add)
        toolbar.addWidget(self._btn_remove)
        toolbar.addStretch()
        root.addLayout(toolbar)

        self._splitter = QSplitter(Qt.Orientation.Horizontal)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(4)
        left_layout.addWidget(QLabel("Files"))
        self._list = QListWidget()
        self._list.currentItemChanged.connect(self._on_item_selected)
        left_layout.addWidget(self._list)
        self._splitter.addWidget(left)

        mid = QWidget()
        mid_layout = QVBoxLayout(mid)
        mid_layout.setContentsMargins(0, 0, 0, 0)
        mid_layout.setSpacing(4)
        mid_layout.addWidget(QLabel("PDF Settings"))
        self._pdf_panel = PDFSettingsPanel()
        self._pdf_panel.set_user_mode(self._user_mode)
        self._pdf_panel.preview_requested.connect(self._run_preview)
        mid_layout.addWidget(self._pdf_panel)
        self._splitter.addWidget(mid)

        self._tabs = QTabWidget()
        self._pdf_viewer = PDFViewerPanel()
        self._tabs.addTab(self._pdf_viewer, "PDF View")
        self._preview = MarkdownSplitPanel(
            read_only=True,
            show_toolbar=True,
            lock_toggle_enabled=False,
            allow_preview_editing=True,
            highlight_scope="importer",
        )
        self._tabs.addTab(self._preview, "Markdown")
        self._splitter.addWidget(self._tabs)
        self._splitter.setSizes([220, 260, 700])
        root.addWidget(self._splitter, stretch=1)

        self._feedback_bar = FeedbackBar()
        self._feedback_bar.feedback_submitted.connect(self._on_import_feedback)
        root.addWidget(self._feedback_bar)

        progress_row = QHBoxLayout()
        self._progress = QProgressBar()
        self._progress.setVisible(False)
        self._progress_lbl = QLabel("")
        progress_row.addWidget(self._progress)
        progress_row.addWidget(self._progress_lbl)
        root.addLayout(progress_row)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._btn_import = QPushButton("Convert to MarkDown")
        self._btn_import.setEnabled(False)
        self._btn_import.clicked.connect(self._start_import)
        self._btn_open = QPushButton("Import and Close")
        self._btn_open.setEnabled(False)
        self._btn_open.clicked.connect(self._open_in_viewer)
        self._btn_cancel = QPushButton("Abbrechen")
        self._btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(self._btn_import)
        btn_row.addWidget(self._btn_open)
        btn_row.addWidget(self._btn_cancel)
        root.addLayout(btn_row)

    def _add_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Add Files", "", _SUPPORTED_FILTER)
        for path in paths:
            if path in self._entries:
                continue
            entry = ImportEntry(path=path, name=os.path.basename(path))
            self._entries[path] = entry
            item = QListWidgetItem(f"{_ICON[_STATUS_PENDING]}  {entry.name}")
            item.setData(Qt.ItemDataRole.UserRole, path)
            self._list.addItem(item)
        self._btn_import.setEnabled(bool(self._entries))

    def _remove_selected(self) -> None:
        item = self._list.currentItem()
        if item is None:
            return
        path = str(item.data(Qt.ItemDataRole.UserRole) or "")
        self._entries.pop(path, None)
        self._list.takeItem(self._list.row(item))
        if self._current_path == path:
            self._current_path = None
            self._preview.clear_text()
            self._pdf_viewer.clear()
        self._btn_import.setEnabled(bool(self._entries))
        self._btn_open.setEnabled(self._has_converted())

    def _on_item_selected(self, current: QListWidgetItem, previous: QListWidgetItem) -> None:
        del previous
        if current is None:
            self._current_path = None
            self._preview.clear_text()
            self._pdf_viewer.clear()
            self._pdf_panel.set_enabled_for_pdf(False)
            return
        path = str(current.data(Qt.ItemDataRole.UserRole) or "")
        self._current_path = path
        entry = self._entries.get(path)
        if entry is None:
            return
        is_pdf = entry.is_pdf()
        self._pdf_panel.set_enabled_for_pdf(is_pdf)
        self._pdf_panel.set_settings(entry.pdf_settings)
        if is_pdf:
            self._pdf_viewer.load_pdf(path, entry.pdf_settings, entry.body_size, entry.markdown)
            self._tabs.setCurrentIndex(0)
        else:
            self._pdf_viewer.clear()
            self._tabs.setCurrentIndex(1)
        if entry.markdown:
            self._preview.set_markdown_text(entry.markdown)
        else:
            self._preview.set_markdown_text(preview_placeholder_text(entry.name, is_pdf))

    def _run_preview(self) -> None:
        path = str(self._current_path or "")
        if not path:
            return
        entry = self._entries.get(path)
        if entry is None or not entry.is_pdf():
            return
        if entry.markdown:
            self._preview.set_markdown_text(entry.markdown)
            self._tabs.setCurrentIndex(1)

    def _start_import(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        paths = list(self._entries.keys())
        if not paths:
            return
        settings_map = {path: self._entries[path].pdf_settings for path in paths}
        self._progress.setVisible(True)
        self._progress.setMaximum(len(paths))
        self._progress.setValue(0)
        self._progress_lbl.setText(f"0 / {len(paths)} converted")
        self._btn_import.setEnabled(False)
        self._btn_add.setEnabled(False)
        self._btn_remove.setEnabled(False)
        self._list.setEnabled(False)
        self._worker = ConversionWorker(paths, settings_map, self)
        self._worker.file_done.connect(self._on_file_done)
        self._worker.all_done.connect(self._on_all_done)
        self._worker.start()

    def _on_file_done(
        self,
        index: int,
        name: str,
        path: str,
        markdown: str,
        error: str,
        used_settings: object,
    ) -> None:
        del index, name
        entry = self._entries.get(path)
        if entry is None:
            return
        if isinstance(used_settings, PDFImportSettings):
            entry.pdf_settings = used_settings
        if error:
            entry.markdown = f"# Conversion Error\n\n```\n{error}\n```"
            entry.error = str(error)
            entry.status = _STATUS_ERROR
        else:
            entry.markdown = str(markdown or "")
            entry.status = _STATUS_DONE
        self._update_list_item(path, entry.status)
        done = sum(1 for item in self._entries.values() if item.status != _STATUS_PENDING)
        total = len(self._entries)
        self._progress.setValue(done)
        self._progress_lbl.setText(f"{done} / {total} converted")
        self._btn_open.setEnabled(self._has_converted())

    def _on_all_done(self) -> None:
        self._worker = None
        self._btn_import.setEnabled(bool(self._entries))
        self._btn_add.setEnabled(True)
        self._btn_remove.setEnabled(True)
        self._list.setEnabled(True)
        self._btn_open.setEnabled(self._has_converted())

    def _update_list_item(self, path: str, status: str) -> None:
        entry = self._entries.get(path)
        if entry is None:
            return
        for i in range(self._list.count()):
            item = self._list.item(i)
            if str(item.data(Qt.ItemDataRole.UserRole) or "") != path:
                continue
            item.setText(f"{_ICON.get(status, _ICON[_STATUS_PENDING])}  {entry.name}")
            if self._current_path == path:
                self._preview.set_markdown_text(entry.markdown)
            return

    def _has_converted(self) -> bool:
        return any(entry.status == _STATUS_DONE for entry in self._entries.values())

    def _open_in_viewer(self) -> None:
        results = converted_results(self._entries)
        if not results:
            return
        self.files_imported.emit(results)
        self.accept()

    def _on_import_feedback(self, sentiment: str, tags: list[str], note: str) -> None:
        service = self._feedback_service
        if service is None:
            return
        path = str(self._current_path or "")
        entry = self._entries.get(path)
        payload = {
            "file_path": path,
            "file_type": os.path.splitext(path)[1].lower() if path else "",
            "markdown_preview": str(entry.markdown if entry else "")[:2000],
        }
        service.submit_feedback(
            use_case="file_import",
            sentiment=sentiment,
            payload=payload,
            error_tags=tags or None,
            note=note,
        )
