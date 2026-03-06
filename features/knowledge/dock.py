"""
Knowledge Dock
==============
Left-side QDockWidget containing:

  Tab 0 – 📄 Viewer   : TabbedEditorWidget (read-only by default, toggleable)
  Tab 1 – 🔍 RAG      : top file selector + RAG search/results
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QDockWidget, QSplitter, QTabWidget, QVBoxLayout, QWidget

from services.rag.system import RAGSystem, RAGWorker

from .document_viewer_panel import DocumentViewerPanel
from .imported_files_panel import ImportedFilesPanel
from .rag_results_panel import RAGResultsPanel

_DOCK_TAB_STYLE = """
QTabWidget::pane { border: none; }
QTabBar::tab {
    background: palette(alternate-base); color: palette(placeholder-text);
    padding: 5px 14px; border: none;
}
QTabBar::tab:selected {
    background: palette(base); color: palette(text);
    border-top: 2px solid palette(highlight);
}
QTabBar::tab:hover { background: palette(mid); color: palette(text); }
"""


class KnowledgeDock(QDockWidget):
    """
    Unified Knowledge Dock.

    Orchestrates:
    • ImportedFilesPanel  → embedded in RAG tab, drives RAG indexing
    • DocumentViewerPanel → read-only markdown view of imported documents
    • RAGResultsPanel     → semantic / TF-IDF search results
    """

    rag_settings_requested = Signal()   # relayed from RAGResultsPanel → MainWindow
    rag_status_changed = Signal(str)  # relayed from RAGWorker → MainWindow
    document_remove_requested = Signal(str)  # doc_key (display name)
    document_rename_requested = Signal(str, str)  # old_name, new_name

    def __init__(self, rag_system: RAGSystem, parent=None):
        super().__init__("Knowledge Base", parent)
        self.rag_system = rag_system
        self.rag_worker = RAGWorker(rag_system, parent=self)
        self._setup_dock()
        self._connect_signals()
        self.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        features = QDockWidget.DockWidgetFeature.DockWidgetMovable
        features |= QDockWidget.DockWidgetFeature.DockWidgetFloatable
        features |= QDockWidget.DockWidgetFeature.DockWidgetClosable
        self.setFeatures(features)

    def _setup_dock(self):
        container = QWidget()
        container.setMinimumWidth(260)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)

        self.tab_widget = QTabWidget()
        self.tab_widget.setStyleSheet(_DOCK_TAB_STYLE)

        self.imported_files = ImportedFilesPanel()
        self.doc_viewer = DocumentViewerPanel()
        self.rag_panel = RAGResultsPanel()
        self.rag_tab = QWidget()

        rag_layout = QVBoxLayout(self.rag_tab)
        rag_layout.setContentsMargins(0, 0, 0, 0)
        rag_layout.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(6)
        splitter.addWidget(self.imported_files)
        splitter.addWidget(self.rag_panel)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        self.imported_files.setMinimumHeight(120)
        self.rag_panel.setMinimumHeight(220)
        splitter.setSizes([170, 420])
        rag_layout.addWidget(splitter)

        self.tab_widget.addTab(self.doc_viewer, "📄 Viewer")
        self.tab_widget.addTab(self.rag_tab, "🔍 RAG")

        layout.addWidget(self.tab_widget)
        self.setWidget(container)

    def _connect_signals(self):
        self.imported_files.selection_changed.connect(self._reindex_rag)
        self.rag_panel.search_requested.connect(self._run_rag_search)
        self.rag_panel.settings_requested.connect(self.rag_settings_requested)
        self.doc_viewer.file_remove_requested.connect(self._on_doc_remove_requested)
        self.doc_viewer.document_rename_requested.connect(self._on_doc_rename_requested)

        self.rag_worker.search_complete.connect(self._on_search_complete)
        self.rag_worker.status_changed.connect(self._on_rag_status)

    def _reindex_rag(self, entries: list[tuple[str, str]]):
        """Enqueue a RAG index rebuild (runs in background thread)."""
        self.rag_worker.enqueue_index(entries)

    def _run_rag_search(self, query: str):
        """Enqueue a RAG search (runs in background thread)."""
        self.rag_worker.enqueue_search(query)
        self.tab_widget.setCurrentWidget(self.rag_tab)

    def _on_search_complete(self, query: str, results: list, debug_info: dict):
        self.rag_panel.display_results(query, results, debug_info)

    def _on_rag_status(self, message: str):
        self.rag_panel.set_status(message)
        self.rag_status_changed.emit(message)

    def _on_doc_remove_requested(self, doc_key: str, _title: str):
        key = str(doc_key or "").strip()
        if key:
            self.document_remove_requested.emit(key)

    def _on_doc_rename_requested(self, old_name: str, new_name: str):
        old_key = str(old_name or "").strip()
        new_key = str(new_name or "").strip()
        if old_key and new_key and old_key != new_key:
            self.document_rename_requested.emit(old_key, new_key)

    def reindex_rag(self):
        """Re-index all currently checked files (enqueues background task)."""
        entries = self.imported_files.get_checked_files()
        self.rag_worker.enqueue_index(entries)

    def add_imported_file(self, name: str, content: str):
        """Register a newly imported file in the Files panel (auto-checked)."""
        self.imported_files.add_file(name, content)

    def open_content(self, title: str, content: str, doc_key: str = ""):
        """Open pre-converted markdown content in the Document Viewer."""
        self.doc_viewer.open_content(title, content, doc_key=doc_key)
        self.tab_widget.setCurrentWidget(self.doc_viewer)

    def remove_imported_file(self, name: str):
        """Remove one imported file from the selector (and trigger reindex)."""
        self.imported_files.remove_file(name)

    def rename_imported_file(self, old_name: str, new_name: str) -> str:
        """Rename one imported file entry in the selector."""
        return self.imported_files.rename_file(old_name, new_name)

    def remove_viewer_document(self, doc_key: str):
        """Remove all viewer tabs for the given imported document key."""
        self.doc_viewer.remove_tabs_for_doc(doc_key)

    def rename_viewer_document(self, old_doc_key: str, new_doc_key: str) -> bool:
        """Rename viewer tabs and bindings for one imported document key."""
        return self.doc_viewer.apply_document_rename(old_doc_key, new_doc_key)

    def set_feedback_service(self, service) -> None:
        self.rag_panel.set_feedback_service(service)

    def get_rag_results_text(self) -> str:
        return self.rag_panel.get_current_text()

    def get_rag_debug_history(self) -> list[dict]:
        return self.rag_panel.get_debug_history()

    def set_rag_debug_history(self, items: list[dict]):
        self.rag_panel.set_debug_history(items)
