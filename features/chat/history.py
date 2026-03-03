"""Chat history widget rendered as shared markdown split-view."""
from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QMenu,
    QTabWidget,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from features.feedback.bar import FeedbackBar
from widgets.markdown.split_view import MarkdownSplitPanel


@dataclass
class _HistorySession:
    page: QWidget
    display: MarkdownSplitPanel
    history: list[tuple[str, str]]
    streaming: bool = False
    feedback_bar: FeedbackBar | None = None


class ChatHistoryWidget(QWidget):
    """Tabbed chat history, each tab with its own markdown split-view."""

    feedback_submitted = Signal(str, str, list, str)  # use_case, sentiment, tags, note

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._sessions: dict[QWidget, _HistorySession] = {}
        self._tab_counter = 0
        self._stream_page: QWidget | None = None
        self._tabs: QTabWidget | None = None
        self._setup_ui()
        self.add_tab("Chat 1")

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        tabs = QTabWidget()
        tabs.setTabsClosable(True)
        tabs.setMovable(True)
        tabs.setStyleSheet(
            "QTabWidget::pane { border: none; }"
            "QTabBar::tab { background: #2A2A3E; color: #A6ADC8; "
            "padding: 4px 10px; border: none; "
            "border-right: 1px solid #181825; }"
            "QTabBar::tab:selected { background: #1E1E2E; color: #CDD6F4; "
            "border-top: 2px solid #89B4FA; }"
            "QTabBar::tab:hover { background: #313244; color: #CDD6F4; }"
        )
        tabs.tabCloseRequested.connect(self._close_tab)
        tabs.tabBar().setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        tabs.tabBar().customContextMenuRequested.connect(
            self._open_tab_context_menu
        )
        self._tabs = tabs
        layout.addWidget(tabs)

    def add_tab(self, title: str | None = None) -> int:
        """Create a new chat tab and make it active."""
        tabs = self._tabs
        if tabs is None:
            return -1

        self._tab_counter += 1
        tab_title = title or f"Chat {self._tab_counter}"

        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(0)

        display = MarkdownSplitPanel(
            read_only=True,
            show_toolbar=True,
            lock_toggle_enabled=False,
            allow_preview_editing=False,
            sync_preview_to_cursor=False,
            highlight_scope="chat",
        )
        display.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        page_layout.addWidget(display)

        feedback_bar = FeedbackBar()
        page_layout.addWidget(feedback_bar)

        session = _HistorySession(
            page=page,
            display=display,
            history=[],
            feedback_bar=feedback_bar,
        )
        self._sessions[page] = session

        feedback_bar.feedback_submitted.connect(
            lambda sentiment, tags, note, sess=session: self._on_bar_feedback(
                sess, sentiment, tags, note
            )
        )

        index = tabs.addTab(page, tab_title)
        tabs.setCurrentIndex(index)
        return index

    def activate_feedback(self, use_case: str):
        """Activate feedback bar on the active tab."""
        session = self._active_session()
        if session is None or session.feedback_bar is None:
            return
        session.feedback_bar.activate(use_case)

    def reset_feedback(self):
        """Reset (hide) feedback bar on the active tab."""
        session = self._active_session()
        if session is None or session.feedback_bar is None:
            return
        session.feedback_bar.reset()

    def _on_bar_feedback(
        self,
        session: _HistorySession,
        sentiment: str,
        tags: list[str],
        note: str,
    ):
        use_case = ""
        if session.feedback_bar is not None:
            use_case = session.feedback_bar._use_case
        self.feedback_submitted.emit(use_case, sentiment, tags, note)

    def add_message(self, role: str, content: str):
        """Append a complete message to the active tab."""
        session = self._active_session()
        if session is None:
            return
        session.history.append((role, content))
        self._append_message_markdown(session, role, content)
        self._scroll_bottom(session)

    def begin_streaming(self, role: str = "assistant"):
        """Start a streaming response on the active tab."""
        session = self._active_session()
        if session is None:
            return
        session.streaming = True
        session.history.append((role, ""))
        self._stream_page = session.page
        self._append_markdown_text(session, f"\n### {role.upper()}\n\n")
        self._scroll_bottom(session)

    def append_token(self, token: str):
        """Append a single streaming token."""
        session = self._stream_session() or self._active_session()
        if session is None or not session.streaming:
            return
        self._append_markdown_text(session, token)
        self._scroll_bottom(session)
        if session.history:
            role, existing = session.history[-1]
            session.history[-1] = (role, existing + token)

    def finish_streaming(self):
        """End streaming and append a trailing newline."""
        session = self._stream_session() or self._active_session()
        if session is None:
            return
        session.streaming = False
        self._append_markdown_text(session, "\n\n")
        self._scroll_bottom(session)
        if self._stream_page is session.page:
            self._stream_page = None

    def get_history(self) -> list[tuple[str, str]]:
        session = self._active_session()
        if session is None:
            return []
        return list(session.history)

    def get_last_message(self, role: str = "") -> str:
        session = self._active_session()
        if session is None:
            return ""
        wanted = str(role or "").strip().lower()
        for msg_role, msg_text in reversed(session.history):
            if wanted and str(msg_role or "").strip().lower() != wanted:
                continue
            clean = str(msg_text or "").strip()
            if clean:
                return clean
        return ""

    def clear_history(self):
        """Clear only the active chat tab."""
        session = self._active_session()
        if session is None:
            return
        session.history.clear()
        session.streaming = False
        session.display.clear_text()
        if self._stream_page is session.page:
            self._stream_page = None

    def _close_tab(self, index: int):
        tabs = self._tabs
        if tabs is None:
            return
        if tabs.count() <= 1:
            self.clear_history()
            return

        page = tabs.widget(index)
        if page is None:
            return
        if page is self._stream_page:
            return

        self._sessions.pop(page, None)
        tabs.removeTab(index)
        page.deleteLater()

    def _open_tab_context_menu(self, pos):
        tabs = self._tabs
        if tabs is None:
            return
        bar = tabs.tabBar()
        index = bar.tabAt(pos)
        if index < 0:
            return
        page = tabs.widget(index)
        session = self._sessions.get(page)
        if session is None:
            return
        panel = session.display

        menu = QMenu(self)
        preview_action = menu.addAction("Zeige HTML-View")
        preview_action.setCheckable(True)
        md_action = menu.addAction("Zeige Markdown")
        md_action.setCheckable(True)
        both_action = menu.addAction("Zeige beides")
        both_action.setCheckable(True)

        mode = panel.view_mode()
        preview_action.setChecked(mode == "preview")
        md_action.setChecked(mode == "markdown")
        both_action.setChecked(mode == "both")

        picked = menu.exec(bar.mapToGlobal(pos))
        if picked is None:
            return
        if picked is preview_action:
            panel.set_view_mode("preview")
            return
        if picked is md_action:
            panel.set_view_mode("markdown")
            return
        if picked is both_action:
            panel.set_view_mode("both")

    def _active_session(self) -> _HistorySession | None:
        tabs = self._tabs
        if tabs is None:
            return None
        page = tabs.currentWidget()
        if page is None:
            return None
        return self._sessions.get(page)

    def _stream_session(self) -> _HistorySession | None:
        if self._stream_page is None:
            return None
        return self._sessions.get(self._stream_page)

    def _append_message_markdown(
        self,
        session: _HistorySession,
        role: str,
        content: str,
    ):
        self._append_markdown_text(
            session,
            f"\n### {role.upper()}\n\n{content.rstrip()}\n",
        )

    def _append_markdown_text(self, session: _HistorySession, text: str):
        editor = session.display.editor
        cursor = editor.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(text)
        editor.setTextCursor(cursor)

    def _scroll_bottom(self, session: _HistorySession):
        panel = session.display
        QTimer.singleShot(
            0,
            panel.scroll_to_bottom,
        )
        # Preview rendering is timer-driven.
        # Enforce bottom again shortly after the first jump.
        QTimer.singleShot(160, panel.scroll_to_bottom)
