"""Debug history dialog for RAG search traces."""
from __future__ import annotations

import json

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QMessageBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from studio.dialogs.window_manager import find_dialog_manager

from .rag_results.styles import RAG_DEBUG_DIALOG_STYLE, RAG_DEBUG_SELECTOR_STYLE


def _entry_label(entry: dict) -> str:
    query = str(entry.get("query", "")).strip() or "(empty query)"
    tab_title = str(entry.get("tab_title", "🔍 RAG"))
    timestamp = str(entry.get("timestamp", ""))
    result_count = int(entry.get("result_count", 0))
    return f"[{timestamp}] {tab_title} · {query}  (results: {result_count})"


def _payload_text(entry: dict) -> str:
    payload = {
        "query": entry.get("query", ""),
        "timestamp": entry.get("timestamp", ""),
        "tab_title": entry.get("tab_title", "🔍 RAG"),
        "tab_index": entry.get("tab_index", -1),
        "result_count": entry.get("result_count", 0),
        "debug": entry.get("debug", {}),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


class RAGDebugHistoryDialog(QDialog):
    """Modeless viewer for stored RAG debug entries."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("RAG Debug History")
        self.resize(980, 720)
        self.setStyleSheet(RAG_DEBUG_DIALOG_STYLE)
        self._entries: list[dict] = []
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        self._selector = QComboBox()
        self._selector.setStyleSheet(RAG_DEBUG_SELECTOR_STYLE)
        self._selector.currentIndexChanged.connect(self._render_selected)
        layout.addWidget(self._selector)

        self._text_view = QTextEdit()
        self._text_view.setReadOnly(True)
        layout.addWidget(self._text_view)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        close_button = buttons.button(QDialogButtonBox.StandardButton.Close)
        if close_button is not None:
            close_button.clicked.connect(self.accept)
        layout.addWidget(buttons)

    def set_history(self, history: list[dict]) -> None:
        self._entries = list(reversed(list(history or [])))
        self._selector.blockSignals(True)
        self._selector.clear()
        for index, entry in enumerate(self._entries):
            self._selector.addItem(_entry_label(entry), index)
        self._selector.blockSignals(False)
        self._render_selected()

    def _render_selected(self) -> None:
        selected = self._selector.currentData()
        if selected is None:
            self._text_view.setPlainText("No debug entry selected.")
            return
        pos = int(selected)
        if not (0 <= pos < len(self._entries)):
            self._text_view.setPlainText("No debug entry selected.")
            return
        self._text_view.setPlainText(_payload_text(self._entries[pos]))


def show_rag_debug_history(parent: QWidget, history: list[dict]) -> None:
    """Show stored RAG debug entries in a singleton, modeless dialog."""
    if not history:
        QMessageBox.information(parent, "RAG Debug", "No search debug data available yet.")
        return

    manager = find_dialog_manager(parent)
    if manager is not None:
        def _create() -> RAGDebugHistoryDialog:
            dialog = RAGDebugHistoryDialog(parent)
            dialog.set_history(history)
            return dialog

        def _refresh(dialog: QDialog) -> None:
            if isinstance(dialog, RAGDebugHistoryDialog):
                dialog.set_history(history)

        manager.show_dialog(
            "rag-debug-history",
            _create,
            on_reopen=_refresh,
        )
        return

    dialog = RAGDebugHistoryDialog(parent)
    dialog.set_history(history)
    dialog.exec()
