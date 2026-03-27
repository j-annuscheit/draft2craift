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

from shared.domain.user_mode import normalize_user_mode, resolve_feature_label
from studio.feedback.bar import FeedbackBar
from shared.services.highlights.store import get_highlight_store
from studio.canvas.tabbed_editor_widget import TabbedEditorWidget
from studio.canvas.split_view import MarkdownSplitPanel

from ..rag_debug_dialog import show_rag_debug_history
from .formatting import build_results_markdown
from .history import (
    append_debug_entry,
    build_debug_entry,
    sanitize_debug_history,
)
from .styles import (
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
        self._user_mode = ""
        self._debug_history: list[dict] = []
        self._feedback_service = None
        self._last_rag_data: dict = {}
        self._feedback_bar: FeedbackBar | None = None
        self._search_btn: QPushButton | None = None
        self._new_tab_btn: QPushButton | None = None
        self._debug_btn: QPushButton | None = None
        self._settings_btn: QPushButton | None = None
        self._setup_ui()
        self.set_user_mode("")

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

        self._search_btn = QPushButton("🔍 Search")
        self._search_btn.setStyleSheet(RAG_SEARCH_BUTTON_STYLE)
        self._search_btn.clicked.connect(self._do_search)

        self._new_tab_btn = self._create_icon_button(
            text="+",
            tooltip="Neuen leeren Ergebnis-Tab hinzufügen",
        )
        self._new_tab_btn.clicked.connect(self._add_results_tab)

        self._debug_btn = self._create_icon_button(
            text="🧪",
            tooltip="Show debug details for the last search",
        )
        self._debug_btn.clicked.connect(self._show_debug)

        self._settings_btn = self._create_icon_button(
            text="⚙",
            tooltip="RAG Settings",
        )
        self._settings_btn.clicked.connect(self.settings_requested)

        hbox.addWidget(self.search_input)
        hbox.addWidget(self._search_btn)
        hbox.addWidget(self._new_tab_btn)
        hbox.addWidget(self._debug_btn)
        hbox.addWidget(self._settings_btn)
        return bar

    @staticmethod
    def _create_icon_button(text: str, tooltip: str) -> QPushButton:
        button = QPushButton(text)
        button.setToolTip(tooltip)
        button.setFixedWidth(28)
        button.setStyleSheet(RAG_ICON_BUTTON_STYLE)
        return button

    def set_user_mode(self, mode: str) -> None:
        self._user_mode = normalize_user_mode(mode)
        tabs_mode_setter = getattr(self.tabs, "set_user_mode", None)
        if callable(tabs_mode_setter):
            tabs_mode_setter(self._user_mode)
        self.search_input.setPlaceholderText(
            resolve_feature_label(
                self._user_mode,
                "rag.results.search.placeholder",
                "Search knowledge base…",
            )
        )
        if self._search_btn is not None:
            self._search_btn.setText(
                resolve_feature_label(
                    self._user_mode,
                    "rag.results.button.search",
                    "🔍 Search",
                )
            )
            self._search_btn.setToolTip(
                resolve_feature_label(
                    self._user_mode,
                    "rag.results.button.search.tooltip",
                    "Run search against the indexed knowledge base",
                )
            )
        if self._new_tab_btn is not None:
            self._new_tab_btn.setText(
                resolve_feature_label(
                    self._user_mode,
                    "rag.results.button.new_tab",
                    "+",
                )
            )
            self._new_tab_btn.setToolTip(
                resolve_feature_label(
                    self._user_mode,
                    "rag.results.button.new_tab.tooltip",
                    "Add an empty results tab",
                )
            )
        if self._debug_btn is not None:
            self._debug_btn.setText(
                resolve_feature_label(
                    self._user_mode,
                    "rag.results.button.debug",
                    "🧪",
                )
            )
            self._debug_btn.setToolTip(
                resolve_feature_label(
                    self._user_mode,
                    "rag.results.button.debug.tooltip",
                    "Show debug details for the last search",
                )
            )
        if self._settings_btn is not None:
            self._settings_btn.setText(
                resolve_feature_label(
                    self._user_mode,
                    "rag.results.button.settings",
                    "⚙",
                )
            )
            self._settings_btn.setToolTip(
                resolve_feature_label(
                    self._user_mode,
                    "rag.results.button.settings.tooltip",
                    "Open RAG settings",
                )
            )
        if self._feedback_bar is not None:
            self._feedback_bar.set_user_mode(self._user_mode)

    def _add_results_tab(self) -> None:
        """Add a new empty results tab and make it active."""
        self.tabs.add_tab(
            title=resolve_feature_label(
                self._user_mode,
                "rag.results.tab.default.title",
                "🔍 RAG",
            )
        )

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
            self.tabs.add_tab(
                title=resolve_feature_label(
                    self._user_mode,
                    "rag.results.tab.default.title",
                    "🔍 RAG",
                ),
                content=block,
            )
            return

        existing = panel.editor.get_full_text().rstrip()
        panel.editor.setPlainText((existing + "\n\n" if existing else "") + block)
        cursor = panel.editor.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        panel.editor.setTextCursor(cursor)

    def _record_debug(self, query: str, debug_info: object, result_count: int) -> None:
        tab_widget = self.tabs.tab_widget
        tab_idx = tab_widget.currentIndex()
        tab_title = (
            self.tabs.get_tab_full_title(tab_idx)
            if tab_idx >= 0
            else resolve_feature_label(
                self._user_mode,
                "rag.results.tab.default.title",
                "🔍 RAG",
            )
        )
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
