"""Tabbed chat history widget."""
from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QMenu, QSizePolicy, QTabWidget, QVBoxLayout, QWidget

from shared.domain.user_mode import (
    default_user_mode,
    is_feature_visible,
    normalize_user_mode,
    resolve_feature_label,
)
from studio.canvas.file_actions import CanvasFileActions
from studio.canvas.split_view import MarkdownSplitPanel
from studio.feedback.bar import FeedbackBar

_THINKING_LABEL = "Thinking"
_THINK_LINK_PREFIX = "d2c://think/"


@dataclass(slots=True)
class HistorySession:
    page: QWidget
    display: MarkdownSplitPanel
    history: list[tuple[str, str]]
    feedback_bar: FeedbackBar | None = None
    streaming: bool = False
    think_by_message: dict[int, str] = field(default_factory=dict)
    think_link_by_message: dict[int, str] = field(default_factory=dict)
    think_link_tooltips: dict[str, str] = field(default_factory=dict)
    think_marker_counter: int = 0


def _append_text(session: HistorySession, text: str) -> None:
    editor = session.display.editor
    cursor = editor.textCursor()
    cursor.movePosition(QTextCursor.MoveOperation.End)
    cursor.insertText(text)
    editor.setTextCursor(cursor)


def _append_message(session: HistorySession, role: str, content: str) -> None:
    _append_text(session, f"\n### {role.upper()}\n\n{content.rstrip()}\n")


def _scroll_bottom(session: HistorySession) -> None:
    panel = session.display
    QTimer.singleShot(0, panel.scroll_to_bottom)
    QTimer.singleShot(160, panel.scroll_to_bottom)


def _sync_think_tooltips(session: HistorySession) -> None:
    setter = getattr(session.display, "set_preview_link_tooltips", None)
    if callable(setter):
        setter(dict(session.think_link_tooltips))


class ChatHistoryWidget(QWidget):
    feedback_submitted = Signal(str, str, list, str)
    content_changed = Signal()
    annotation_export_requested = Signal(object, str, str)  # panel, scope, tab_name
    _ANNOTATION_EXTRACT_KEY = "editor.tab.context.annotation_extract"

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._user_mode = default_user_mode()
        self._sessions: dict[QWidget, HistorySession] = {}
        self._tab_counter = 0
        self._stream_page: QWidget | None = None
        self._tabs: QTabWidget | None = None
        self._setup_ui()
        self.add_tab("Chat 1")

    def set_user_mode(self, mode: str) -> None:
        self._user_mode = normalize_user_mode(mode)

    def _label(self, key: str, default: str) -> str:
        return resolve_feature_label(self._user_mode, key, default)

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        tabs = QTabWidget()
        tabs.setTabsClosable(True)
        tabs.setMovable(True)
        tabs.setStyleSheet(
            "QTabWidget::pane { border: none; }"
            "QTabBar::tab { background: palette(alternate-base); color: palette(placeholder-text); "
            "padding: 4px 10px; border: none; border-right: 1px solid palette(base); }"
            "QTabBar::tab:selected { background: palette(base); color: palette(text); border-top: 2px solid palette(highlight); }"
            "QTabBar::tab:hover { background: palette(mid); color: palette(text); }"
        )
        tabs.tabCloseRequested.connect(self._close_tab)
        tabs.tabBar().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        tabs.tabBar().customContextMenuRequested.connect(self._open_tab_context_menu)
        self._tabs = tabs
        layout.addWidget(tabs)

    def add_tab(self, title: str | None = None) -> int:
        tabs = self._tabs
        if tabs is None:
            return -1
        self._tab_counter += 1
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
        display.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        page_layout.addWidget(display)
        feedback_bar = FeedbackBar()
        page_layout.addWidget(feedback_bar)
        session = HistorySession(page=page, display=display, history=[], feedback_bar=feedback_bar)
        self._sessions[page] = session
        _sync_think_tooltips(session)
        feedback_bar.feedback_submitted.connect(
            lambda sentiment, tags, note, sess=session: self._on_bar_feedback(sess, sentiment, tags, note)
        )
        index = tabs.addTab(page, title or f"Chat {self._tab_counter}")
        tabs.setCurrentIndex(index)
        self.content_changed.emit()
        return index

    def activate_feedback(self, use_case: str) -> None:
        session = self._active_session()
        if session is None or session.feedback_bar is None:
            return
        session.feedback_bar.activate(use_case)

    def reset_feedback(self) -> None:
        session = self._active_session()
        if session is None or session.feedback_bar is None:
            return
        session.feedback_bar.reset()

    def _on_bar_feedback(self, session: HistorySession, sentiment: str, tags: list[str], note: str) -> None:
        use_case = session.feedback_bar._use_case if session.feedback_bar is not None else ""
        self.feedback_submitted.emit(use_case, sentiment, tags, note)

    def add_message(self, role: str, content: str) -> None:
        session = self._active_session()
        if session is None:
            return
        session.history.append((role, content))
        _append_message(session, role, content)
        _scroll_bottom(session)
        self.content_changed.emit()

    def begin_streaming(self, role: str = "assistant") -> None:
        session = self._active_session()
        if session is None:
            return
        session.streaming = True
        session.history.append((role, ""))
        self._stream_page = session.page
        _append_text(session, f"\n### {role.upper()}\n\n")
        _scroll_bottom(session)

    def append_token(self, token: str) -> None:
        session = self._stream_session() or self._active_session()
        if session is None or not session.streaming:
            return
        _append_text(session, token)
        _scroll_bottom(session)
        if session.history:
            role, existing = session.history[-1]
            session.history[-1] = (role, existing + token)

    def append_streaming_thinking_token(self, token: str) -> None:
        session = self._stream_session() or self._active_session()
        if session is None or not session.streaming or not session.history:
            return
        chunk = str(token or "")
        if not chunk:
            return
        idx = len(session.history) - 1
        role, _content = session.history[idx]
        if str(role or "").strip().lower() != "assistant":
            return

        existing = str(session.think_by_message.get(idx, "") or "")
        updated = f"{existing}{chunk}"
        if not self._set_message_thinking(
            session,
            message_index=idx,
            payload=updated,
            append_marker=True,
        ):
            return
        _scroll_bottom(session)

    def finish_streaming(self) -> None:
        session = self._stream_session() or self._active_session()
        if session is None:
            return
        session.streaming = False
        _append_text(session, "\n\n")
        _scroll_bottom(session)
        if self._stream_page is session.page:
            self._stream_page = None
        self.content_changed.emit()

    def _next_think_link(self, session: HistorySession) -> str:
        session.think_marker_counter += 1
        return f"{_THINK_LINK_PREFIX}{session.think_marker_counter}"

    def _is_assistant_message(self, session: HistorySession, message_index: int) -> bool:
        if message_index < 0 or message_index >= len(session.history):
            return False
        role, _content = session.history[message_index]
        return str(role or "").strip().lower() == "assistant"

    def _ensure_think_link(
        self,
        session: HistorySession,
        *,
        message_index: int,
        append_marker: bool,
    ) -> str:
        link = str(session.think_link_by_message.get(message_index, "") or "").strip()
        if link:
            return link
        link = self._next_think_link(session)
        session.think_link_by_message[message_index] = link
        if append_marker:
            _append_text(session, f"[{_THINKING_LABEL}]({link})\n\n")
        return link

    def _set_message_thinking(
        self,
        session: HistorySession,
        *,
        message_index: int,
        payload: str,
        append_marker: bool,
    ) -> bool:
        raw = str(payload or "")
        if not raw.strip():
            return False
        if not self._is_assistant_message(session, message_index):
            return False
        link = self._ensure_think_link(
            session,
            message_index=message_index,
            append_marker=append_marker,
        )
        if not link:
            return False
        session.think_by_message[message_index] = raw
        session.think_link_tooltips[link] = raw
        _sync_think_tooltips(session)
        return True

    def attach_last_assistant_thinking(self, thinking: str) -> None:
        session = self._stream_session() or self._active_session()
        if session is None or not session.history:
            return
        idx = len(session.history) - 1
        if not self._set_message_thinking(
            session,
            message_index=idx,
            payload=thinking,
            append_marker=True,
        ):
            return
        _scroll_bottom(session)
        self.content_changed.emit()

    def get_history(self) -> list[tuple[str, str]]:
        session = self._active_session()
        return [] if session is None else list(session.history)

    def current_panel(self) -> MarkdownSplitPanel | None:
        session = self._active_session()
        return None if session is None else session.display

    def current_tab_title(self) -> str:
        tabs = self._tabs
        if tabs is None:
            return ""
        idx = int(tabs.currentIndex())
        return "" if idx < 0 else str(tabs.tabText(idx) or "").strip()

    def activate_tab_by_title(self, title: str) -> bool:
        tabs = self._tabs
        target = str(title or "").strip()
        if tabs is None or not target:
            return False
        for idx in range(tabs.count()):
            if str(tabs.tabText(idx) or "").strip() != target:
                continue
            tabs.setCurrentIndex(idx)
            return True
        return False

    def jump_to_highlight(
        self,
        highlight_id: str,
        *,
        preferred_tab_titles: list[str] | None = None,
    ) -> bool:
        tabs = self._tabs
        target_id = str(highlight_id or "").strip()
        if tabs is None or not target_id:
            return False

        preferred = [str(item or "").strip() for item in list(preferred_tab_titles or []) if str(item or "").strip()]
        indices: list[int] = []
        for title in preferred:
            if not self.activate_tab_by_title(title):
                continue
            idx = int(tabs.currentIndex())
            if idx >= 0 and idx not in indices:
                indices.append(idx)
        for idx in range(tabs.count()):
            if idx not in indices:
                indices.append(idx)

        for idx in indices:
            tabs.setCurrentIndex(idx)
            page = tabs.widget(idx)
            session = None if page is None else self._sessions.get(page)
            if session is None:
                continue
            jump = getattr(session.display, "jump_to_highlight", None)
            if not callable(jump):
                continue
            if bool(jump(target_id)):
                return True
        return False

    def export_sessions(self) -> dict:
        tabs = self._tabs
        if tabs is None:
            return {"current_tab": 0, "tabs": []}
        out_tabs: list[dict] = []
        for i in range(tabs.count()):
            page = tabs.widget(i)
            session = self._sessions.get(page)
            if session is None:
                continue
            message_rows: list[dict[str, str]] = []
            for msg_index, (role, content) in enumerate(session.history):
                row = {"role": str(role or ""), "content": str(content or "")}
                think = str(session.think_by_message.get(msg_index, "") or "").strip()
                if think and str(role or "").strip().lower() == "assistant":
                    row["think"] = think
                message_rows.append(row)
            out_tabs.append(
                {
                    "title": str(tabs.tabText(i) or f"Chat {i + 1}"),
                    "view_mode": str(session.display.view_mode() or "both"),
                    "history": message_rows,
                }
            )
        return {"current_tab": int(tabs.currentIndex()), "tabs": out_tabs}

    def import_sessions(self, payload: dict) -> None:
        tabs = self._tabs
        if tabs is None:
            return
        current_idx = 0
        tabs_payload: list[dict] = []
        if isinstance(payload, dict):
            current_idx = int(payload.get("current_tab", 0) or 0)
            raw_tabs = payload.get("tabs", [])
            if isinstance(raw_tabs, list):
                tabs_payload = [row for row in raw_tabs if isinstance(row, dict)]
        self._stream_page = None
        self._sessions.clear()
        while tabs.count() > 0:
            page = tabs.widget(0)
            tabs.removeTab(0)
            if page is not None:
                page.deleteLater()
        if not tabs_payload:
            self.add_tab("Chat 1")
            return
        for idx, row in enumerate(tabs_payload):
            tab_idx = self.add_tab(str(row.get("title", "") or "").strip() or f"Chat {idx + 1}")
            page = tabs.widget(tab_idx)
            session = self._sessions.get(page)
            if session is None:
                continue
            view_mode = str(row.get("view_mode", "") or "").strip().lower()
            if view_mode in {"preview", "markdown", "both"}:
                session.display.set_view_mode(view_mode)
            messages = row.get("history", [])
            if not isinstance(messages, list):
                continue
            for entry in messages:
                if not isinstance(entry, dict):
                    continue
                role = str(entry.get("role", "") or "").strip()
                content = str(entry.get("content", "") or "")
                if not role:
                    continue
                session.history.append((role, content))
                _append_message(session, role, content)
                think = str(entry.get("think", "") or "").strip()
                msg_idx = len(session.history) - 1
                if think and str(role).strip().lower() == "assistant":
                    self._set_message_thinking(
                        session,
                        message_index=msg_idx,
                        payload=think,
                        append_marker=True,
                    )
            _scroll_bottom(session)
        if tabs.count() <= 0:
            self.add_tab("Chat 1")
            self.content_changed.emit()
            return
        if current_idx < 0 or current_idx >= tabs.count():
            current_idx = tabs.count() - 1
        tabs.setCurrentIndex(current_idx)
        self.content_changed.emit()

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

    def clear_history(self) -> None:
        session = self._active_session()
        if session is None:
            return
        session.history.clear()
        session.streaming = False
        session.think_by_message.clear()
        session.think_link_by_message.clear()
        session.think_link_tooltips.clear()
        _sync_think_tooltips(session)
        session.display.clear_text()
        if self._stream_page is session.page:
            self._stream_page = None
        self.content_changed.emit()

    def _close_tab(self, index: int) -> None:
        tabs = self._tabs
        if tabs is None:
            return
        if tabs.count() <= 1:
            self.clear_history()
            return
        page = tabs.widget(index)
        if page is None or page is self._stream_page:
            return
        self._sessions.pop(page, None)
        tabs.removeTab(index)
        page.deleteLater()
        self.content_changed.emit()

    def _open_tab_context_menu(self, pos) -> None:
        tabs = self._tabs
        if tabs is None:
            return
        index = tabs.tabBar().tabAt(pos)
        if index < 0:
            return
        page = tabs.widget(index)
        session = self._sessions.get(page)
        if session is None:
            return
        panel = session.display
        menu = QMenu(self)
        export_action = menu.addAction("Exportieren…")
        annotation_extract_action = None
        if is_feature_visible(
            self._user_mode,
            self._ANNOTATION_EXTRACT_KEY,
            default=True,
        ):
            annotation_extract_action = menu.addAction(
                self._label(
                    self._ANNOTATION_EXTRACT_KEY,
                    "Annotationen extrahieren…",
                )
            )
        menu.addSeparator()
        preview_action = menu.addAction("Zeige HTML-View")
        markdown_action = menu.addAction("Zeige Markdown")
        both_action = menu.addAction("Zeige beides")
        for action in (preview_action, markdown_action, both_action):
            action.setCheckable(True)
        mode = panel.view_mode()
        preview_action.setChecked(mode == "preview")
        markdown_action.setChecked(mode == "markdown")
        both_action.setChecked(mode == "both")
        picked = menu.exec(tabs.tabBar().mapToGlobal(pos))
        if picked is export_action:
            CanvasFileActions(parent=self, tabs=self).export_specific_panel(
                panel,
                default_format="pdf",
                panel_scope="chat",
                tab_name=str(tabs.tabText(index) or "").strip(),
            )
            return
        if annotation_extract_action is not None and picked is annotation_extract_action:
            self.annotation_export_requested.emit(
                panel,
                "chat",
                str(tabs.tabText(index) or "").strip(),
            )
            return
        if picked is preview_action:
            panel.set_view_mode("preview")
        elif picked is markdown_action:
            panel.set_view_mode("markdown")
        elif picked is both_action:
            panel.set_view_mode("both")

    def _active_session(self) -> HistorySession | None:
        tabs = self._tabs
        if tabs is None:
            return None
        page = tabs.currentWidget()
        return None if page is None else self._sessions.get(page)

    def _stream_session(self) -> HistorySession | None:
        return None if self._stream_page is None else self._sessions.get(self._stream_page)
