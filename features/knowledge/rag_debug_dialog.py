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

from .rag_results_styles import RAG_DEBUG_DIALOG_STYLE, RAG_DEBUG_SELECTOR_STYLE


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


def show_rag_debug_history(parent: QWidget, history: list[dict]) -> None:
    """Show a modal dialog with stored RAG debug entries."""
    if not history:
        QMessageBox.information(parent, "RAG Debug", "No search debug data available yet.")
        return

    dialog = QDialog(parent)
    dialog.setWindowTitle("RAG Debug History")
    dialog.resize(980, 720)
    dialog.setStyleSheet(RAG_DEBUG_DIALOG_STYLE)

    layout = QVBoxLayout(dialog)

    selector = QComboBox()
    selector.setStyleSheet(RAG_DEBUG_SELECTOR_STYLE)

    entries = list(reversed(history))
    for index, entry in enumerate(entries):
        selector.addItem(_entry_label(entry), index)
    layout.addWidget(selector)

    text_view = QTextEdit()
    text_view.setReadOnly(True)
    layout.addWidget(text_view)

    def render_selected() -> None:
        selected = selector.currentData()
        if selected is None:
            text_view.setPlainText("No debug entry selected.")
            return

        pos = int(selected)
        if not (0 <= pos < len(entries)):
            text_view.setPlainText("No debug entry selected.")
            return

        text_view.setPlainText(_payload_text(entries[pos]))

    selector.currentIndexChanged.connect(render_selected)
    render_selected()

    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
    buttons.rejected.connect(dialog.reject)
    buttons.accepted.connect(dialog.accept)
    close_button = buttons.button(QDialogButtonBox.StandardButton.Close)
    if close_button is not None:
        close_button.clicked.connect(dialog.accept)
    layout.addWidget(buttons)

    dialog.exec()
