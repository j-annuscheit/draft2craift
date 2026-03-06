"""
MarkdownEditor — Master Editor Class
=====================================
Reusable for the Draft, Document Viewer, and RAG Results panels.
Behaviour is controlled exclusively via:
  - self.setReadOnly(True/False)
  - mode-specific stylesheets
  - the EditorPanel wrapper (optional toolbar)
"""
from __future__ import annotations

import os
from typing import Callable
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QPlainTextEdit, QPushButton, QLabel, QTabWidget, QInputDialog, QLineEdit, QTabBar, QMenu,
)
from PySide6.QtCore import Qt, Signal, QMimeData
from PySide6.QtGui import QFont

from widgets.markdown.highlighter import MarkdownHighlighter

# ── Stylesheets ────────────────────────────────────────────────────────────────
_FONT_STACK = "'Cascadia Code', 'JetBrains Mono', 'Fira Code', 'Consolas', monospace"


def _editor_style(read_only: bool, font_size_pt: float) -> str:
    if read_only:
        bg, fg, border = "palette(base)", "palette(text)", "palette(mid)"
    else:
        bg, fg, border = "palette(base)", "palette(text)", "palette(highlight)"
    return f"""
QPlainTextEdit {{
    background-color: {bg};
    color: {fg};
    border: 1px solid {border};
    padding: 8px;
    selection-background-color: palette(highlight);
    selection-color: palette(highlighted-text);
    font-family: {_FONT_STACK};
    font-size: {font_size_pt:.1f}pt;
}}
"""


_TOOLBAR_STYLE = """
QWidget#toolbar {
    background: palette(alternate-base);
    border-bottom: 1px solid palette(mid);
}
QPushButton {
    background: transparent;
    color: palette(text);
    border: none;
    padding: 2px 10px;
    font-size: 11px;
    border-radius: 3px;
}
QPushButton:hover  { background: palette(mid); }
QPushButton:checked { background: palette(highlight); color: palette(highlighted-text); }
QLabel { color: palette(placeholder-text); font-size: 10px; padding: 0 6px; }
"""


# ── Master Editor ──────────────────────────────────────────────────────────────

class MarkdownEditor(QPlainTextEdit):
    """
    Core text-editing widget with Markdown highlighting.

    Use ``setReadOnly(True)`` for viewer / RAG mode (dark, muted colours).
    Use ``setReadOnly(False)`` for editable canvas mode (highlighted border).
    """

    read_only_changed = Signal(bool)
    _BASE_FONT_PT = 12.0
    _ZOOM_MIN = 60
    _ZOOM_MAX = 260
    _ZOOM_STEP = 10

    def __init__(self, parent: QWidget | None = None, read_only: bool = False):
        super().__init__(parent)
        self._font_size_pt = self._BASE_FONT_PT
        self._setup_font()
        self.highlighter = MarkdownHighlighter(self.document())
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.setTabStopDistance(32)          # ≈4 spaces
        self.setReadOnly(read_only)          # also applies stylesheet

    # ------------------------------------------------------------------

    def _setup_font(self):
        for family in ("Cascadia Code", "JetBrains Mono", "Fira Code",
                       "Consolas", "DejaVu Sans Mono", "Monospace"):
            f = QFont(family)
            f.setStyleHint(QFont.StyleHint.Monospace)
            f.setFixedPitch(True)
            f.setPointSizeF(self._font_size_pt)
            self.setFont(f)
            break

    def _apply_style(self):
        self.setStyleSheet(_editor_style(self.isReadOnly(), self._font_size_pt))

    def setReadOnly(self, read_only: bool):          # override to swap stylesheet
        super().setReadOnly(read_only)
        self._apply_style()
        self.read_only_changed.emit(read_only)

    def toggle_read_only(self) -> bool:
        """Toggle mode. Returns the new read-only state."""
        self.setReadOnly(not self.isReadOnly())
        return self.isReadOnly()

    def set_font_size_pt(self, size_pt: float):
        clamped = max(6.0, min(72.0, float(size_pt)))
        if abs(clamped - self._font_size_pt) < 0.05:
            return
        self._font_size_pt = clamped
        f = self.font()
        f.setPointSizeF(clamped)
        self.setFont(f)
        self._apply_style()

    def font_size_pt(self) -> float:
        return self._font_size_pt

    def zoom_percent(self) -> int:
        return int(round((self._font_size_pt / self._BASE_FONT_PT) * 100))

    def set_zoom_percent(self, percent: int) -> bool:
        clamped = max(self._ZOOM_MIN, min(self._ZOOM_MAX, int(percent)))
        target_pt = self._BASE_FONT_PT * (clamped / 100.0)
        old = self._font_size_pt
        self.set_font_size_pt(target_pt)
        return abs(self._font_size_pt - old) >= 0.05

    def increase_zoom(self) -> bool:
        return self.set_zoom_percent(self.zoom_percent() + self._ZOOM_STEP)

    def decrease_zoom(self) -> bool:
        return self.set_zoom_percent(self.zoom_percent() - self._ZOOM_STEP)

    def reset_zoom(self) -> bool:
        return self.set_zoom_percent(100)

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            if delta == 0:
                delta = event.pixelDelta().y()
            if delta > 0:
                self.increase_zoom()
            elif delta < 0:
                self.decrease_zoom()
            event.accept()
            return
        super().wheelEvent(event)

    @staticmethod
    def _normalize_paste_text(text: str) -> str:
        return (
            str(text or "")
            .replace("\r\n", "\n")
            .replace("\r", "\n")
            .replace("\u2028", "\n")
            .replace("\u2029", "\n")
            .replace("\uFFFC", "")
            .replace("\u200b", "")
            .replace("\u200c", "")
            .replace("\u200d", "")
            .replace("\ufeff", "")
        )

    def insertFromMimeData(self, source):
        if source is None or not source.hasText():
            super().insertFromMimeData(source)
            return
        normalized = self._normalize_paste_text(source.text())
        mime = QMimeData()
        mime.setText(normalized)
        super().insertFromMimeData(mime)

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    def get_selected_text(self) -> str:
        return self.textCursor().selectedText()

    def get_full_text(self) -> str:
        return self.toPlainText()

    def load_file(self, path: str) -> bool:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                self.setPlainText(fh.read())
            return True
        except Exception as exc:
            self.setPlainText(f"⚠ Could not open file:\n{exc}")
            return False

    def save_file(self, path: str) -> bool:
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(self.toPlainText())
            return True
        except Exception:
            return False


# ── Editor Panel (Editor + optional toolbar) ───────────────────────────────────

class EditorPanel(QWidget):
    """
    A complete editor panel consisting of an optional toolbar and a
    ``MarkdownEditor``.  Instantiate with ``read_only=True`` for viewer/RAG
    tabs and ``read_only=False`` for canvas tabs.
    """

    file_path: str = ""

    def __init__(
        self,
        parent: QWidget | None = None,
        read_only: bool = False,
        show_toolbar: bool = True,
    ):
        super().__init__(parent)
        self.editor = MarkdownEditor(read_only=read_only)
        self.lock_btn: QPushButton | None = None
        self.status_label: QLabel | None = None
        self._setup_ui(show_toolbar)

    # ------------------------------------------------------------------

    def _setup_ui(self, show_toolbar: bool):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        if show_toolbar:
            layout.addWidget(self._build_toolbar())
        layout.addWidget(self.editor)

    def _build_toolbar(self) -> QWidget:
        bar = QWidget(objectName="toolbar")
        bar.setFixedHeight(30)
        bar.setStyleSheet(_TOOLBAR_STYLE)

        hbox = QHBoxLayout(bar)
        hbox.setContentsMargins(4, 0, 4, 0)
        hbox.setSpacing(2)

        self.lock_btn = QPushButton()
        self.lock_btn.setCheckable(True)
        self._sync_lock_btn()
        self.lock_btn.clicked.connect(self._toggle_lock)
        hbox.addWidget(self.lock_btn)

        hbox.addStretch()

        self.status_label = QLabel("")
        hbox.addWidget(self.status_label)
        self.editor.textChanged.connect(self._update_status)

        return bar

    def _sync_lock_btn(self):
        if self.lock_btn is None:
            return
        ro = self.editor.isReadOnly()
        self.lock_btn.setText("🔒 Read-Only" if ro else "✏ Editing")
        self.lock_btn.setChecked(ro)

    def _toggle_lock(self):
        self.editor.toggle_read_only()
        self._sync_lock_btn()

    def _update_status(self):
        text = self.editor.toPlainText()
        words = len(text.split()) if text.strip() else 0
        lines = text.count("\n") + 1
        if self.status_label:
            self.status_label.setText(f"{words} w  {lines} L")


# ── Tabbed Editor Container ────────────────────────────────────────────────────

_TAB_STYLE = """
QTabWidget::pane  { border: none; }
QTabBar::tab {
    background: palette(alternate-base);
    color: palette(placeholder-text);
    padding: 4px 14px;
    border: none;
    border-right: 1px solid palette(base);
    min-width: 80px;
}
QTabBar::tab:selected {
    background: palette(base);
    color: palette(text);
    border-top: 2px solid palette(highlight);
}
QTabBar::tab:hover { background: palette(mid); color: palette(text); }
"""

_TAB_STYLE_COMPACT = """
QTabWidget::pane  { border: none; }
QTabBar::tab {
    background: palette(alternate-base);
    color: palette(placeholder-text);
    padding: 4px 6px;
    border: none;
    border-right: 1px solid palette(base);
    min-width: 18px;
}
QTabBar::tab:selected {
    background: palette(base);
    color: palette(text);
    border-top: 2px solid palette(highlight);
    min-width: 90px;
    padding: 4px 10px;
}
QTabBar::tab:hover { background: palette(mid); color: palette(text); }
"""


class TabbedEditorWidget(QWidget):
    """
    QTabWidget wrapper that manages multiple ``EditorPanel`` instances.
    Each sub-tab is an independent editor (canvas tab, viewer tab, RAG tab).
    """

    tab_renamed = Signal(str, str)   # old_title, new_title

    def __init__(
        self,
        parent: QWidget | None = None,
        default_read_only: bool = False,
        tab_title_prefix: str = "Document",
        editable_tab_titles: bool = False,
        compact_inactive_tabs: bool = False,
        active_title_max_chars: int = 10,
        strip_file_extensions: bool = False,
        inactive_tab_label: str = "•",
        panel_factory: Callable[[bool], QWidget] | None = None,
    ):
        super().__init__(parent)
        self.default_read_only = default_read_only
        self.tab_title_prefix = tab_title_prefix
        self.editable_tab_titles = bool(editable_tab_titles)
        self.compact_inactive_tabs = bool(compact_inactive_tabs)
        self.active_title_max_chars = max(1, int(active_title_max_chars))
        self.strip_file_extensions = bool(strip_file_extensions)
        self.inactive_tab_label = str(inactive_tab_label or "•")
        self._panel_factory = panel_factory
        self._counter = 0
        self._setup_ui()

    # ------------------------------------------------------------------

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.tab_widget = QTabWidget()
        self.tab_widget.setTabsClosable(True)
        self.tab_widget.setMovable(True)
        self.tab_widget.setStyleSheet(
            _TAB_STYLE_COMPACT if self.compact_inactive_tabs else _TAB_STYLE
        )
        self.tab_widget.tabCloseRequested.connect(self._close_tab)
        self.tab_widget.currentChanged.connect(self._update_close_buttons)
        if self.compact_inactive_tabs:
            self.tab_widget.currentChanged.connect(self._refresh_tab_labels)
        if self.editable_tab_titles:
            self.tab_widget.tabBarDoubleClicked.connect(self._rename_tab_dialog)
        self.tab_widget.tabBar().setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self.tab_widget.tabBar().customContextMenuRequested.connect(
            self._open_tab_context_menu
        )

        layout.addWidget(self.tab_widget)
        self.add_tab()          # start with one empty tab

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_tab(
        self,
        title: str = "",
        content: str = "",
        file_path: str = "",
        read_only: bool | None = None,
    ) -> QWidget:
        self._counter += 1
        if not title:
            title = f"{self.tab_title_prefix} {self._counter}"
        title = self._clean_title(title)

        target_read_only = self.default_read_only if read_only is None else read_only
        if self._panel_factory is None:
            panel: QWidget = EditorPanel(read_only=target_read_only)
        else:
            panel = self._panel_factory(bool(target_read_only))
        setattr(panel, "file_path", file_path)
        editor = getattr(panel, "editor", None)
        if editor is None:
            raise TypeError("Panel factory must return an object with '.editor'.")
        if hasattr(editor, "read_only_changed"):
            editor.read_only_changed.connect(self._refresh_tab_labels)
        if content:
            editor.setPlainText(content)

        idx = self.tab_widget.addTab(panel, title)
        self._set_full_tab_title(idx, title)
        self.tab_widget.setCurrentIndex(idx)
        self._refresh_tab_labels()
        self._update_close_buttons()
        return panel

    def add_file_tab(self, path: str) -> QWidget:
        title = self._clean_title(os.path.basename(path))
        panel = self.add_tab(title=title, file_path=path)
        editor = getattr(panel, "editor", None)
        if editor is not None:
            editor.load_file(path)
        setattr(panel, "file_path", path)
        return panel

    def get_tab_full_title(self, index: int) -> str:
        if index < 0 or index >= self.tab_widget.count():
            return ""
        bar = self.tab_widget.tabBar()
        data = bar.tabData(index)
        if isinstance(data, str) and data:
            return data
        return self.tab_widget.tabText(index)

    def set_tab_full_title(self, index: int, title: str):
        if index < 0 or index >= self.tab_widget.count():
            return
        old_title = self.get_tab_full_title(index)
        new_title = self._clean_title(title)
        self._set_full_tab_title(index, new_title)
        self._refresh_tab_labels()
        if old_title != new_title:
            self.tab_renamed.emit(old_title, new_title)

    def current_panel(self) -> QWidget | None:
        w = self.tab_widget.currentWidget()
        return w if isinstance(w, QWidget) and hasattr(w, "editor") else None

    def can_undo_current(self) -> bool:
        panel = self.current_panel()
        if panel is None or panel.editor.isReadOnly():
            return False
        return panel.editor.document().isUndoAvailable()

    def can_redo_current(self) -> bool:
        panel = self.current_panel()
        if panel is None or panel.editor.isReadOnly():
            return False
        return panel.editor.document().isRedoAvailable()

    def undo_current(self) -> bool:
        panel = self.current_panel()
        if panel is None or panel.editor.isReadOnly():
            return False
        panel.editor.undo()
        return True

    def redo_current(self) -> bool:
        panel = self.current_panel()
        if panel is None or panel.editor.isReadOnly():
            return False
        panel.editor.redo()
        return True

    # ------------------------------------------------------------------

    def _close_tab(self, index: int):
        if self.tab_widget.count() > 1:
            self.tab_widget.removeTab(index)
            self._refresh_tab_labels()
            self._update_close_buttons()

    def _clean_title(self, title: str) -> str:
        text = (title or "").strip()
        if self.strip_file_extensions and text:
            text = os.path.splitext(text)[0]
        return text or self.tab_title_prefix

    def _set_full_tab_title(self, index: int, title: str):
        full = (title or "").strip() or self.tab_title_prefix
        bar = self.tab_widget.tabBar()
        bar.setTabData(index, full)
        self.tab_widget.setTabToolTip(index, full)
        if not self.compact_inactive_tabs:
            self.tab_widget.setTabText(index, full)

    def _display_title(self, full: str, is_active: bool, index: int) -> str:
        if not self.compact_inactive_tabs:
            return full
        if not is_active:
            return str(index + 1)
        text = full
        max_chars = max(1, self.active_title_max_chars)
        if len(text) <= max_chars:
            return text
        if max_chars == 1:
            return "…"
        return text[: max_chars - 1] + "…"

    def _refresh_tab_labels(self, *_):
        n = self.tab_widget.count()
        if n <= 0:
            return
        cur = self.tab_widget.currentIndex()
        for i in range(n):
            full = self.get_tab_full_title(i)
            ro_prefix = "🔒 " if self._panel_is_read_only(i) else ""
            display = self._display_title(full, i == cur, i)
            self.tab_widget.setTabText(i, f"{ro_prefix}{display}")
            self.tab_widget.setTabToolTip(i, f"{ro_prefix}{full}")

    def _panel_is_read_only(self, index: int) -> bool:
        panel = self.tab_widget.widget(index)
        editor = getattr(panel, "editor", None)
        if editor is None:
            return False
        try:
            return bool(editor.isReadOnly())
        except Exception:
            return False

    def _open_tab_context_menu(self, pos):
        bar = self.tab_widget.tabBar()
        index = bar.tabAt(pos)
        if index < 0:
            return

        panel = self.tab_widget.widget(index)
        editor = getattr(panel, "editor", None)
        if editor is None:
            return

        menu = QMenu(self)
        read_only_action = menu.addAction("🔒 Read-Only")
        read_only_action.setCheckable(True)
        read_only_action.setChecked(bool(editor.isReadOnly()))

        md_action = None
        preview_action = None
        both_action = None
        if (
            hasattr(panel, "is_markdown_visible")
            and hasattr(panel, "is_preview_visible")
            and hasattr(panel, "set_markdown_visible")
            and hasattr(panel, "set_preview_visible")
        ):
            menu.addSeparator()
            preview_action = menu.addAction("Zeige HTML-View")
            preview_action.setCheckable(True)

            md_action = menu.addAction("Zeige Markdown")
            md_action.setCheckable(True)
            both_action = menu.addAction("Zeige beides")
            both_action.setCheckable(True)

            if hasattr(panel, "view_mode"):
                mode = str(panel.view_mode())
            else:
                md_visible = bool(panel.is_markdown_visible())
                html_visible = bool(panel.is_preview_visible())
                mode = "both" if (md_visible and html_visible) else (
                    "markdown" if md_visible else "preview"
                )

            preview_action.setChecked(mode == "preview")
            md_action.setChecked(mode == "markdown")
            both_action.setChecked(mode == "both")

        picked = menu.exec(bar.mapToGlobal(pos))
        if picked is None:
            return

        if picked is read_only_action:
            editable = not read_only_action.isChecked()
            if hasattr(panel, "set_editable_mode"):
                panel.set_editable_mode(editable)
            else:
                editor.setReadOnly(not editable)
            self._refresh_tab_labels()
            return

        if preview_action is not None and picked is preview_action:
            if hasattr(panel, "set_view_mode"):
                panel.set_view_mode("preview")
            else:
                panel.set_markdown_visible(False)
                panel.set_preview_visible(True)
            return

        if md_action is not None and picked is md_action:
            if hasattr(panel, "set_view_mode"):
                panel.set_view_mode("markdown")
            else:
                panel.set_markdown_visible(True)
                panel.set_preview_visible(False)
            return

        if both_action is not None and picked is both_action:
            if hasattr(panel, "set_view_mode"):
                panel.set_view_mode("both")
            else:
                panel.set_markdown_visible(True)
                panel.set_preview_visible(True)
            return

    def _rename_tab_dialog(self, index: int):
        if not self.editable_tab_titles or index < 0 or index >= self.tab_widget.count():
            return
        current = self.get_tab_full_title(index)
        text, ok = QInputDialog.getText(
            self,
            "Tab umbenennen",
            "Neuer Tab-Name:",
            QLineEdit.EchoMode.Normal,
            current,
        )
        if not ok:
            return
        new_title = self._clean_title(text)
        if not new_title:
            return
        self._set_full_tab_title(index, new_title)
        self._refresh_tab_labels()
        if current != new_title:
            self.tab_renamed.emit(current, new_title)

    def _update_close_buttons(self, *_):
        n = self.tab_widget.count()
        cur = self.tab_widget.currentIndex()
        bar = self.tab_widget.tabBar()
        show_close = n > 1
        for i in range(n):
            visible = show_close and i == cur
            btn_right = bar.tabButton(i, QTabBar.ButtonPosition.RightSide)
            if btn_right is not None:
                btn_right.setVisible(visible)
            btn_left = bar.tabButton(i, QTabBar.ButtonPosition.LeftSide)
            if btn_left is not None:
                btn_left.setVisible(visible)
