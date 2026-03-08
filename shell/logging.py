"""
App Logger + Log Dock
=====================
Thread-safe Qt-signal-based application logger for debugging LLM, RAG, and
sentence-transformers operations.

Usage
-----
    # In shell/window.py:
    self.app_logger = AppLogger()
    self.log_dock   = LogDock(self.app_logger, parent=self)

    # In any module (duck-typed, logger may be None):
    if self._log:
        self._log.info("RAG", "Indexed 3 chunks in 12 ms")

Categories: LLM | RAG | ST | SYS
Levels:     DEBUG | INFO | WARNING | ERROR
"""
from __future__ import annotations

import datetime
import html as _html
from pathlib import Path
import threading

from PySide6.QtCore import QObject, Signal, Qt
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import (
    QApplication, QComboBox, QCheckBox, QDockWidget,
    QHBoxLayout, QLabel, QPushButton, QTextEdit,
    QVBoxLayout, QWidget,
)

from core.user_modes import (
    USER_MODE_EXPERT,
    USER_MODE_PLUS,
    normalize_user_mode,
    mode_rank,
)


# ── Colour palette (Catppuccin Mocha) ─────────────────────────────────────────

_CAT_COLOR: dict[str, str] = {
    "LLM": "#89B4FA",   # blue
    "RAG": "#CBA6F7",   # mauve
    "ST":  "#A6E3A1",   # green
    "SYS": "#FAB387",   # peach
}

_LEVEL_COLOR: dict[str, str] = {
    "DEBUG":   "#6C7086",   # muted
    "INFO":    "#CDD6F4",   # normal text
    "WARNING": "#F9E2AF",   # yellow
    "ERROR":   "#F38BA8",   # red
}

_ALL_CATEGORIES = ["All", "LLM", "RAG", "ST", "SYS"]
_ALL_LEVELS     = ["All", "DEBUG", "INFO", "WARNING", "ERROR"]

# Type alias for a log entry tuple
LogEntry = tuple[str, str, str, str]   # (timestamp, level, category, message)


# ── Logger ────────────────────────────────────────────────────────────────────

class AppLogger(QObject):
    """
    Lightweight thread-safe logger that emits a Qt signal on every entry.

    Because Qt cross-thread signal connections are automatically queued,
    calling ``info/debug/warning/error`` from any thread is safe – the
    ``message_logged`` signal will be delivered in the main thread.

    Parameters
    ----------
    enabled:
        When *False* all log calls are no-ops (zero overhead).
    """

    message_logged = Signal(str, str, str, str)   # ts, level, category, message

    def __init__(
        self,
        enabled: bool = True,
        parent: QObject | None = None,
        *,
        persist_to_file: bool = True,
        log_file_path: str | None = None,
    ):
        super().__init__(parent)
        self._enabled = enabled
        self._entries: list[LogEntry] = []
        self._persist_to_file = bool(persist_to_file)
        self._io_lock = threading.Lock()
        self._log_file_path = self._resolve_log_file_path(log_file_path)
        self._log_file_handle = None
        if self._persist_to_file:
            self._open_log_file()

    @staticmethod
    def _resolve_log_file_path(path: str | None) -> Path | None:
        custom = str(path or "").strip()
        if custom:
            return Path(custom).expanduser()
        candidates = [
            Path.home() / ".draft2craift" / "logs" / "debug.log",
            Path("/tmp") / "draft2craift" / "logs" / "debug.log",
        ]
        for candidate in candidates:
            try:
                candidate.parent.mkdir(parents=True, exist_ok=True)
                return candidate
            except Exception:
                continue
        return None

    def _open_log_file(self):
        if not self._persist_to_file:
            return
        path = self._log_file_path
        if path is None:
            self._persist_to_file = False
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._log_file_handle = path.open(
                "a",
                encoding="utf-8",
                errors="replace",
                buffering=1,  # line-buffered
            )
        except Exception:
            self._log_file_handle = None
            self._persist_to_file = False

    def _append_to_file(self, entry: LogEntry):
        if not self._persist_to_file or self._log_file_handle is None:
            return
        ts, level, category, message = entry
        line = f"{ts} [{category}] [{level:<7}] {message}\n"
        with self._io_lock:
            try:
                self._log_file_handle.write(line)
                self._log_file_handle.flush()
            except Exception:
                self._persist_to_file = False

    def log_file_path(self) -> str:
        path = self._log_file_path
        return str(path) if path is not None else ""

    # ── Control ───────────────────────────────────────────────────────────────

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool):
        self._enabled = value

    def clear(self):
        self._entries.clear()

    def get_entries(
        self,
        level_filter: str = "All",
        cat_filter: str   = "All",
    ) -> list[LogEntry]:
        result: list[LogEntry] = self._entries
        if level_filter != "All":
            result = [e for e in result if e[1] == level_filter]
        if cat_filter != "All":
            result = [e for e in result if e[2] == cat_filter]
        return result

    # ── Logging API ───────────────────────────────────────────────────────────

    def log(self, level: str, category: str, message: str):
        if not self._enabled:
            return
        ts    = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        entry = (ts, level, category, message)
        self._entries.append(entry)
        self._append_to_file(entry)
        self.message_logged.emit(*entry)

    def debug(self, category: str, message: str):
        self.log("DEBUG", category, message)

    def info(self, category: str, message: str):
        self.log("INFO", category, message)

    def warning(self, category: str, message: str):
        self.log("WARNING", category, message)

    def error(self, category: str, message: str):
        self.log("ERROR", category, message)


# ── Log Dock ──────────────────────────────────────────────────────────────────

_TOOLBAR_STYLE = """
QWidget#logtoolbar {
    background: #181825;
    border-bottom: 1px solid #313244;
}
QPushButton {
    background: #313244; color: #CDD6F4;
    border: none; border-radius: 3px;
    padding: 2px 8px; font-size: 10px;
}
QPushButton:hover { background: #45475A; }
QCheckBox { color: #CDD6F4; font-size: 10px; }
QCheckBox::indicator {
    width: 12px; height: 12px;
    border: 1px solid #45475A; border-radius: 2px;
}
QCheckBox::indicator:checked { background: #A6E3A1; border-color: #A6E3A1; }
QComboBox {
    background: #313244; color: #CDD6F4;
    border: none; border-radius: 3px;
    padding: 1px 6px; font-size: 10px; min-width: 70px;
}
QComboBox::drop-down { border: none; width: 14px; }
QComboBox QAbstractItemView {
    background: #313244; color: #CDD6F4;
    selection-background-color: #45475A; border: none;
}
QLabel { color: #6C7086; font-size: 10px; background: transparent; }
"""

_STATUS_STYLE = """
QWidget { background: #181825; border-top: 1px solid #313244; }
QLabel  { color: #6C7086; font-size: 10px; padding: 2px 8px; }
"""


class LogDock(QDockWidget):
    """
    Dockable debug log panel.

    - Displays all entries from an ``AppLogger`` with live level/category filtering.
    - "Logging" checkbox enables/disables the logger itself (stops collection).
    - The dock can be shown/hidden independently via the View menu toggle.
    """

    def __init__(self, app_logger: AppLogger, parent=None):
        super().__init__("Debug Log", parent)
        self._logger       = app_logger
        self._user_mode    = USER_MODE_PLUS
        self._level_filter = "All"
        self._cat_filter   = "All"
        self._setup_ui()
        self.set_user_mode(self._user_mode)
        self._connect_signals()
        self.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )

    # ── UI Setup ──────────────────────────────────────────────────────────────

    def _setup_ui(self):
        container = QWidget()
        vbox = QVBoxLayout(container)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(0)

        vbox.addWidget(self._build_toolbar())

        self._text = QTextEdit()
        self._text.setReadOnly(True)
        self._text.setFont(QFont("Monospace", 10))
        self._text.setStyleSheet("""
            QTextEdit {
                background: #11111B;
                color: #CDD6F4;
                border: none;
                padding: 4px;
                selection-background-color: #45475A;
            }
        """)
        vbox.addWidget(self._text, stretch=1)

        # Status bar
        status_bar = QWidget()
        status_bar.setFixedHeight(22)
        status_bar.setStyleSheet(_STATUS_STYLE)
        hbox_s = QHBoxLayout(status_bar)
        hbox_s.setContentsMargins(0, 0, 0, 0)
        self._status_lbl = QLabel("0 entries")
        hbox_s.addWidget(self._status_lbl)
        hbox_s.addStretch()
        vbox.addWidget(status_bar)

        self.setWidget(container)
        self.setMinimumHeight(140)

    def _build_toolbar(self) -> QWidget:
        bar = QWidget(objectName="logtoolbar")
        bar.setFixedHeight(32)
        bar.setStyleSheet(_TOOLBAR_STYLE)

        hbox = QHBoxLayout(bar)
        hbox.setContentsMargins(6, 2, 6, 2)
        hbox.setSpacing(6)

        btn_clear = QPushButton("Clear")
        btn_copy  = QPushButton("Copy all")
        btn_clear.clicked.connect(self._on_clear)
        btn_copy.clicked.connect(self._on_copy)
        hbox.addWidget(btn_clear)
        hbox.addWidget(btn_copy)

        hbox.addStretch()

        # Enable/disable toggle
        self._enabled_cb = QCheckBox("Logging on")
        self._enabled_cb.setChecked(self._logger.enabled)
        self._enabled_cb.toggled.connect(self._on_toggle_logging)
        hbox.addWidget(self._enabled_cb)

        # ── Level filter
        self._level_lbl = QLabel("  Level:")
        hbox.addWidget(self._level_lbl)
        self._level_combo = QComboBox()
        self._level_combo.addItems(_ALL_LEVELS)
        self._level_combo.currentTextChanged.connect(self._on_filter_changed)
        hbox.addWidget(self._level_combo)

        # ── Category filter
        self._cat_lbl = QLabel("Cat:")
        hbox.addWidget(self._cat_lbl)
        self._cat_combo = QComboBox()
        self._cat_combo.addItems(_ALL_CATEGORIES)
        self._cat_combo.currentTextChanged.connect(self._on_filter_changed)
        hbox.addWidget(self._cat_combo)

        return bar

    def _connect_signals(self):
        self._logger.message_logged.connect(self._on_new_entry)

    # ── Slots ─────────────────────────────────────────────────────────────────

    def _on_new_entry(self, ts: str, level: str, category: str, message: str):
        """Receives new log entries (always in main thread via Qt queued connection)."""
        if self._level_filter != "All" and level != self._level_filter:
            return
        if self._cat_filter != "All" and category != self._cat_filter:
            return
        self._append_html(ts, level, category, message)
        self._update_status()

    def _on_filter_changed(self):
        self._level_filter = self._level_combo.currentText()
        self._cat_filter   = self._cat_combo.currentText()
        self._rebuild_from_history()

    def _on_clear(self):
        self._logger.clear()
        self._text.clear()
        self._update_status()

    def _on_copy(self):
        QApplication.clipboard().setText(self._text.toPlainText())

    def _on_toggle_logging(self, checked: bool):
        self._logger.enabled = checked
        label = "enabled" if checked else "disabled"
        # Always show this system event regardless of filter
        ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self._append_html(ts, "INFO", "SYS", f"Logging {label}")
        self._update_status()

    def set_user_mode(self, mode: str):
        self._user_mode = normalize_user_mode(mode)
        show_filters = mode_rank(self._user_mode) >= mode_rank(USER_MODE_EXPERT)
        for widget in (self._level_lbl, self._level_combo, self._cat_lbl, self._cat_combo):
            widget.setVisible(show_filters)
            widget.setEnabled(show_filters)
        if not show_filters:
            self._level_combo.setCurrentText("All")
            self._cat_combo.setCurrentText("All")

    # ── Internal ──────────────────────────────────────────────────────────────

    def _rebuild_from_history(self):
        self._text.clear()
        for entry in self._logger.get_entries(self._level_filter, self._cat_filter):
            self._append_html(*entry)
        self._update_status()

    def _append_html(self, ts: str, level: str, category: str, message: str):
        cat_color   = _CAT_COLOR.get(category, "#CDD6F4")
        level_color = _LEVEL_COLOR.get(level, "#CDD6F4")
        msg_safe    = _html.escape(message)

        html = (
            f'<p style="margin:0;padding:1px 0;'
            f'font-family:monospace;font-size:10pt;line-height:1.3;">'
            f'<span style="color:#383856">{ts}</span>'
            f'&nbsp;<span style="color:{cat_color};font-weight:bold">'
            f'[{category:3}]</span>'
            f'&nbsp;<span style="color:#4A4A6A">[{level:7}]</span>'
            f'&nbsp;<span style="color:{level_color};white-space:pre-wrap;">{msg_safe}</span>'
            f'</p>'
        )

        cursor = self._text.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self._text.setTextCursor(cursor)
        self._text.insertHtml(html)

        # Always scroll to the newest entry
        sb = self._text.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _update_status(self):
        total    = len(self._logger._entries)
        filtered = len(self._logger.get_entries(self._level_filter, self._cat_filter))
        if self._level_filter == "All" and self._cat_filter == "All":
            self._status_lbl.setText(f"{total} entries")
        else:
            self._status_lbl.setText(f"{filtered} shown / {total} total")
