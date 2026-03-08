from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from features.feedback.bar import FeedbackBar
from services.highlights import get_highlight_store
from widgets.markdown.editor import TabbedEditorWidget
from widgets.markdown.split_view import MarkdownSplitPanel

from .rag_debug_dialog import show_rag_debug_history
from .rag_results_formatting import build_results_markdown
from .rag_results_history import (
    append_debug_entry,
    build_debug_entry,
    sanitize_debug_history,
)
from .rag_results_styles import (
    RAG_ICON_BUTTON_STYLE,
    RAG_SEARCH_BUTTON_STYLE,
    RAG_SEARCH_INPUT_STYLE,
    RAG_STATUS_LABEL_STYLE,
    RAG_TOP_BAR_STYLE,
)


class RAGResultsPanel(QWidget):
    """
    Query bar + multi-tab display of RAG search results.

    The `+` button adds a new empty results tab; each search appends to
    whichever tab is currently active.
    """

    search_requested = Signal(str)
    settings_requested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._debug_history: list[dict] = []
        self._feedback_service = None
        self._last_rag_data: dict = {}
        self._feedback_bar: FeedbackBar | None = None
        self._setup_ui()

    def set_feedback_service(self, service) -> None:
        self._feedback_service = service

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(self._build_top_bar())

        self._status_lbl = QLabel()
        self._status_lbl.setStyleSheet(RAG_STATUS_LABEL_STYLE)
        self._status_lbl.setVisible(False)
        layout.addWidget(self._status_lbl)

        self._feedback_bar = FeedbackBar()
        self._feedback_bar.feedback_submitted.connect(self._on_rag_feedback)
        layout.addWidget(self._feedback_bar)

        self.tabs = TabbedEditorWidget(
            default_read_only=True,
            tab_title_prefix="Results",
            editable_tab_titles=True,
            compact_inactive_tabs=True,
            active_title_max_chars=10,
            export_scope="rag",
            panel_factory=lambda ro: MarkdownSplitPanel(
                read_only=ro,
                show_toolbar=True,
                lock_toggle_enabled=False,
                allow_preview_editing=True,
                highlight_scope="rag",
            ),
        )
        self.tabs.tab_renamed.connect(self._on_tab_renamed)
        layout.addWidget(self.tabs)

    def _build_top_bar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(40)
        bar.setStyleSheet(RAG_TOP_BAR_STYLE)

        hbox = QHBoxLayout(bar)
        hbox.setContentsMargins(6, 4, 6, 4)
        hbox.setSpacing(4)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search knowledge base…")
        self.search_input.setStyleSheet(RAG_SEARCH_INPUT_STYLE)
        self.search_input.returnPressed.connect(self._do_search)

        search_btn = QPushButton("🔍 Search")
        search_btn.setStyleSheet(RAG_SEARCH_BUTTON_STYLE)
        search_btn.clicked.connect(self._do_search)

        new_tab_btn = self._create_icon_button(
            text="+",
            tooltip="Neuen leeren Ergebnis-Tab hinzufügen",
        )
        new_tab_btn.clicked.connect(self._add_results_tab)

        debug_btn = self._create_icon_button(
            text="🧪",
            tooltip="Show debug details for the last search",
        )
        debug_btn.clicked.connect(self._show_debug)

        settings_btn = self._create_icon_button(
            text="⚙",
            tooltip="RAG Settings",
        )
        settings_btn.clicked.connect(self.settings_requested)

        hbox.addWidget(self.search_input)
        hbox.addWidget(search_btn)
        hbox.addWidget(new_tab_btn)
        hbox.addWidget(debug_btn)
        hbox.addWidget(settings_btn)
        return bar

    @staticmethod
    def _create_icon_button(text: str, tooltip: str) -> QPushButton:
        button = QPushButton(text)
        button.setToolTip(tooltip)
        button.setFixedWidth(28)
        button.setStyleSheet(RAG_ICON_BUTTON_STYLE)
        return button

    def _add_results_tab(self) -> None:
        """Add a new empty results tab and make it active."""
        self.tabs.add_tab(title="🔍 RAG")

    def set_status(self, message: str) -> None:
        if message:
            self._status_lbl.setText(message)
            self._status_lbl.setVisible(True)
            return
        self._status_lbl.setVisible(False)

    def _do_search(self) -> None:
        query = self.search_input.text().strip()
        if query:
            self.search_requested.emit(query)

    def _append_result_block(self, block: str) -> None:
        panel = self.tabs.current_panel()
        if panel is None:
            self.tabs.add_tab(title="🔍 RAG", content=block)
            return

        existing = panel.editor.get_full_text().rstrip()
        panel.editor.setPlainText((existing + "\n\n" if existing else "") + block)
        cursor = panel.editor.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        panel.editor.setTextCursor(cursor)

    def _record_debug(self, query: str, debug_info: object, result_count: int) -> None:
        tab_widget = self.tabs.tab_widget
        tab_idx = tab_widget.currentIndex()
        tab_title = self.tabs.get_tab_full_title(tab_idx) if tab_idx >= 0 else "🔍 RAG"
        entry = build_debug_entry(
            query=query,
            debug_payload=debug_info,
            tab_index=tab_idx,
            tab_title=tab_title,
            result_count=result_count,
        )
        self._debug_history = append_debug_entry(self._debug_history, entry)

    def display_results(self, query: str, results: list, debug_info: dict | None = None) -> None:
        block = build_results_markdown(query, results, debug_info)
        self._append_result_block(block)

        if debug_info:
            self._record_debug(query, debug_info, len(results))

        self._last_rag_data = {"query": query, "results": results}
        if self._feedback_bar is not None:
            self._feedback_bar.activate("rag_search")

    def _on_rag_feedback(self, sentiment: str, tags: list[str], note: str) -> None:
        if self._feedback_service is None:
            return
        payload = {
            "rag_search": {
                "query": self._last_rag_data.get("query", ""),
                "results": [
                    str(r) for r in (self._last_rag_data.get("results") or [])[:10]
                ],
                "result_count": len(self._last_rag_data.get("results") or []),
            }
        }
        self._feedback_service.submit_feedback(
            use_case="rag_search",
            sentiment=sentiment,
            payload=payload,
            error_tags=tags or None,
            note=note,
        )

    def _show_debug(self) -> None:
        show_rag_debug_history(self, self._debug_history)

    def get_current_text(self) -> str:
        panel = self.tabs.current_panel()
        return panel.editor.get_full_text() if panel else ""

    def get_debug_history(self) -> list[dict]:
        return list(self._debug_history)

    def set_debug_history(self, items: list[dict]) -> None:
        self._debug_history = sanitize_debug_history(items)

    def _on_tab_renamed(self, old_title: str, new_title: str):
        get_highlight_store().rename_tab(
            panel_scope="rag",
            old_name=old_title,
            new_name=new_title,
        )
