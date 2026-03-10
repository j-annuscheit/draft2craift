from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMenu,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from shared.domain.user_mode import normalize_user_mode
from shared.services.importer.entry import converted_results
from studio.canvas.split_view import MarkdownSplitPanel
from studio.feedback.bar import FeedbackBar

from .pdf_settings import PDFSettingsPanel
from .ui_constants import _ICON, _STATUS_DONE
from .pdf_viewer import PDFViewerPanel


class FileImportDialogUIMixin:
    """UI setup and generic dialog helpers."""

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)
        self._btn_add = QPushButton("Add Files…")
        self._btn_remove = QPushButton("Remove")
        self._btn_add.clicked.connect(self._add_files)
        self._btn_remove.clicked.connect(self._remove_selected)
        toolbar.addWidget(self._btn_add)
        toolbar.addWidget(self._btn_remove)

        self._btn_toggle_settings = QPushButton("◀ Settings")
        self._btn_toggle_settings.setToolTip("Show / hide PDF settings panel")
        self._btn_toggle_settings.clicked.connect(self._toggle_settings)
        if not bool(getattr(self, "_settings_visible", True)):
            self._btn_toggle_settings.setText("▶ Settings")
        toolbar.addWidget(self._btn_toggle_settings)

        toolbar.addStretch()
        root.addLayout(toolbar)

        self._splitter = QSplitter(Qt.Orientation.Horizontal)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(4)
        lbl_files = QLabel("Files")
        lbl_files.setStyleSheet("color: #6C7086; font-size: 10px;")
        left_layout.addWidget(lbl_files)
        self._list = QListWidget()
        self._list.currentItemChanged.connect(self._on_item_selected)
        self._list.itemDoubleClicked.connect(self._rename_list_item)
        left_layout.addWidget(self._list)
        self._splitter.addWidget(left)

        mid_wrap = QWidget()
        mid_layout = QVBoxLayout(mid_wrap)
        mid_layout.setContentsMargins(0, 0, 0, 0)
        mid_layout.setSpacing(4)
        lbl_settings = QLabel("PDF Settings")
        lbl_settings.setStyleSheet("color: #6C7086; font-size: 10px;")
        mid_layout.addWidget(lbl_settings)
        self._pdf_panel = PDFSettingsPanel()
        self._pdf_panel.set_user_mode(self._user_mode)
        self._pdf_panel.preview_requested.connect(self._run_preview)
        self._pdf_panel.detect_requested.connect(self._run_detect)
        self._pdf_panel.analyze_requested.connect(self._run_font_analysis)
        self._pdf_panel.settings_changed.connect(self._on_settings_changed)
        mid_layout.addWidget(self._pdf_panel)
        self._splitter.addWidget(mid_wrap)
        self._splitter.setCollapsible(1, True)

        self._tabs = QTabWidget()
        self._tabs.setStyleSheet(
            "QTabWidget::pane { border: none; }"
            "QTabBar::tab { background: #313244; color: #CDD6F4; padding: 4px 12px; "
            "               border-radius: 3px 3px 0 0; font-size: 11px; }"
            "QTabBar::tab:selected { background: #45475A; }"
        )

        self._pdf_viewer = PDFViewerPanel()
        self._pdf_viewer.zone_changed.connect(self._on_zone_changed)
        self._tabs.addTab(self._pdf_viewer, "PDF View")

        md_widget = QWidget()
        md_layout = QVBoxLayout(md_widget)
        md_layout.setContentsMargins(0, 4, 0, 0)
        md_layout.setSpacing(4)
        hdr_row = QHBoxLayout()
        hdr_row.addStretch()
        self._preview_status = QLabel("")
        self._preview_status.setStyleSheet("color: #F9E2AF; font-size: 10px;")
        self._preview_status.setWordWrap(False)
        self._preview_status.setMaximumWidth(16777215)
        self._preview_status.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        self._preview_status.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self._preview_status.setVisible(False)
        hdr_row.addWidget(self._preview_status)
        md_layout.addLayout(hdr_row)
        self._preview = MarkdownSplitPanel(
            read_only=True,
            show_toolbar=True,
            lock_toggle_enabled=False,
            allow_preview_editing=True,
            highlight_scope="importer",
        )
        self._preview.editor.read_only_changed.connect(
            lambda _ro: self._refresh_markdown_tab_title()
        )
        self._preview.editor.setPlaceholderText(
            "Select a file to see its preview…\n\n"
            "For PDFs: adjust settings, then click  ▶ Preview."
        )
        md_layout.addWidget(self._preview)
        self._markdown_tab_index = self._tabs.addTab(md_widget, "🔒 Markdown")
        self._tabs.tabBar().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tabs.tabBar().customContextMenuRequested.connect(
            self._open_tab_context_menu
        )

        self._splitter.addWidget(self._tabs)
        if bool(getattr(self, "_settings_visible", True)):
            self._splitter.setSizes([220, 320, 560])
        else:
            self._splitter.setSizes([220, 0, 880])
        root.addWidget(self._splitter, stretch=1)

        self._feedback_bar = FeedbackBar()
        self._feedback_bar.feedback_submitted.connect(self._on_import_feedback)
        root.addWidget(self._feedback_bar)

        progress_row = QHBoxLayout()
        self._progress = QProgressBar()
        self._progress.setFixedHeight(8)
        self._progress.setVisible(False)
        self._progress_lbl = QLabel("")
        self._progress_lbl.setStyleSheet("color: #6C7086; font-size: 10px;")
        progress_row.addWidget(self._progress)
        progress_row.addWidget(self._progress_lbl)
        root.addLayout(progress_row)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._btn_llm_fix = QPushButton("Use LLM to optimize")
        self._btn_llm_fix.setToolTip(
            "Korrigiert die Markdown-Struktur fuer alle geladenen Dateien nacheinander per LLM "
            "(Ueberschriften, Tabellen, Zeilenumbrueche, OCR-Formatfehler). "
            "Inhalte sollen unveraendert bleiben."
        )
        self._btn_llm_fix.clicked.connect(self._run_llm_fix_current_markdown)
        self._btn_import = QPushButton("Convert to MarkDown")
        self._btn_import.setObjectName("primary")
        self._btn_import.setEnabled(False)
        self._btn_import.clicked.connect(self._start_import)
        self._btn_open = QPushButton("Import and Close")
        self._btn_open.setEnabled(False)
        self._btn_open.clicked.connect(self._open_in_viewer)
        self._btn_cancel = QPushButton("Abbrechen")
        self._btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(self._btn_import)
        btn_row.addWidget(self._btn_llm_fix)
        btn_row.addWidget(self._btn_open)
        btn_row.addWidget(self._btn_cancel)
        root.addLayout(btn_row)
        refresh = getattr(self, "_refresh_llm_fix_button", None)
        if callable(refresh):
            refresh()

    def set_user_mode(self, mode: str):
        self._user_mode = normalize_user_mode(mode)
        self._pdf_panel.set_user_mode(self._user_mode)

    def _update_list_item(self, path: str, status: str):
        entry = self._entries.get(path)
        if not entry:
            return
        color = QColor("#A6E3A1") if status == _STATUS_DONE else QColor("#F38BA8")
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == path:
                item.setText(f"{_ICON[status]}  {entry.name}")
                item.setForeground(color)
                if path == self._current_path:
                    self._preview.set_markdown_text(entry.markdown)
                break

    def _has_converted(self) -> bool:
        return any(entry.status == _STATUS_DONE for entry in self._entries.values())

    def _open_in_viewer(self):
        parent = self.parent()
        logger = getattr(parent, "app_logger", None)
        if logger is not None:
            try:
                logger.debug(
                    "SYS",
                    (
                        "[IMPORT/DIALOG] Import-and-Close clicked"
                        f"  |  entries={len(getattr(self, '_entries', {}) or {})}"
                    ),
                )
            except Exception:
                pass
        busy_check = getattr(self, "_has_running_background_worker", None)
        if callable(busy_check) and bool(busy_check()):
            self._preview_status.setText("Bitte warten: Import/Analyse laeuft noch…")
            self._preview_status.setToolTip(
                "Import and Close ist erst moeglich, wenn alle Hintergrundjobs fertig sind."
            )
            self._preview_status.setVisible(True)
            if logger is not None:
                try:
                    logger.debug("SYS", "[IMPORT/DIALOG] Import-and-Close blocked (background worker busy)")
                except Exception:
                    pass
            return
        prepare = getattr(self, "_prepare_for_handover_and_close", None)
        if callable(prepare):
            if logger is not None:
                try:
                    logger.debug("SYS", "[IMPORT/DIALOG] Releasing preview resources before handover")
                except Exception:
                    pass
            prepare()
        results = converted_results(self._entries)
        if not results:
            if logger is not None:
                try:
                    logger.debug("SYS", "[IMPORT/DIALOG] No converted results to hand over")
                except Exception:
                    pass
            return
        if logger is not None:
            try:
                logger.debug("SYS", f"[IMPORT/DIALOG] Handover payload prepared  |  files={len(results)}")
            except Exception:
                pass
        direct_handler = getattr(parent, "_on_files_imported", None)
        # Prefer direct in-process handoff for large payloads (markdown blobs)
        # to avoid heavy Qt signal marshalling of giant Python lists.
        if callable(direct_handler):
            payload = [(str(n), str(p), str(m)) for (n, p, m) in results]
            if logger is not None:
                try:
                    logger.debug(
                        "SYS",
                        f"[IMPORT/DIALOG] Direct handover scheduled via QTimer  |  files={len(payload)}",
                    )
                except Exception:
                    pass
            self.accept()
            QTimer.singleShot(
                0,
                lambda cb=direct_handler, data=payload: cb(data),
            )
            return
        if logger is not None:
            try:
                logger.debug("SYS", "[IMPORT/DIALOG] Emitting files_imported signal")
            except Exception:
                pass
        self.files_imported.emit(results)
        self.accept()

    def _open_tab_context_menu(self, pos):
        bar = self._tabs.tabBar()
        index = bar.tabAt(pos)
        if index != getattr(self, "_markdown_tab_index", -1):
            return

        menu = QMenu(self)
        read_only_action = menu.addAction("🔒 Read-Only")
        read_only_action.setCheckable(True)
        read_only_action.setChecked(self._preview.editor.isReadOnly())

        menu.addSeparator()
        preview_action = menu.addAction("Zeige HTML-View")
        preview_action.setCheckable(True)
        markdown_action = menu.addAction("Zeige Markdown")
        markdown_action.setCheckable(True)
        both_action = menu.addAction("Zeige beides")
        both_action.setCheckable(True)

        mode = self._preview.view_mode()
        preview_action.setChecked(mode == "preview")
        markdown_action.setChecked(mode == "markdown")
        both_action.setChecked(mode == "both")

        picked = menu.exec(bar.mapToGlobal(pos))
        if picked is None:
            return

        if picked is read_only_action:
            self._preview.set_editable_mode(not read_only_action.isChecked())
            self._refresh_markdown_tab_title()
            return
        if picked is preview_action:
            self._preview.set_view_mode("preview")
            return
        if picked is markdown_action:
            self._preview.set_view_mode("markdown")
            return
        if picked is both_action:
            self._preview.set_view_mode("both")

    def _refresh_markdown_tab_title(self):
        if getattr(self, "_markdown_tab_index", -1) < 0:
            return
        prefix = "🔒" if self._preview.editor.isReadOnly() else "✏"
        self._tabs.setTabText(self._markdown_tab_index, f"{prefix} Markdown")

    def _on_import_feedback(self, sentiment: str, tags: list[str], note: str):
        service = getattr(self, "_feedback_service", None)
        if service is None:
            return
        path = str(getattr(self, "_current_path", "") or "")
        entry = (getattr(self, "_entries", {}) or {}).get(path)
        markdown_preview = ""
        if entry is not None:
            markdown_preview = str(entry.markdown or "")[:2000]
        import os
        payload = {
            "file_path": path,
            "file_type": os.path.splitext(path)[1].lower() if path else "",
            "markdown_preview": markdown_preview,
        }
        service.submit_feedback(
            use_case="file_import",
            sentiment=sentiment,
            payload=payload,
            error_tags=tags or None,
            note=note,
        )
