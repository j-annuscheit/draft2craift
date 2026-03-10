"""Tabbed container for editor panels used by canvas and knowledge views."""
from __future__ import annotations

import os
from typing import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QInputDialog,
    QLineEdit,
    QMenu,
    QTabBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from studio.canvas.editor_panel import EditorPanel
from studio.canvas.editor_styles import TAB_STYLE, TAB_STYLE_COMPACT
from studio.canvas.file_actions import CanvasFileActions


class TabbedEditorWidget(QWidget):
    """
    QTabWidget wrapper that manages multiple panel widgets with ``.editor``.

    Each tab is independent (draft tab, viewer tab, RAG tab).
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
        stored_title_max_chars: int = 0,
        strip_file_extensions: bool = False,
        inactive_tab_label: str = "•",
        export_scope: str = "draft",
        panel_factory: Callable[[bool], QWidget] | None = None,
    ):
        super().__init__(parent)
        self.default_read_only = default_read_only
        self.tab_title_prefix = tab_title_prefix
        self.editable_tab_titles = bool(editable_tab_titles)
        self.compact_inactive_tabs = bool(compact_inactive_tabs)
        self.active_title_max_chars = max(1, int(active_title_max_chars))
        self.stored_title_max_chars = max(0, int(stored_title_max_chars))
        self.strip_file_extensions = bool(strip_file_extensions)
        self.inactive_tab_label = str(inactive_tab_label or "•")
        self.export_scope = str(export_scope or "draft").strip().lower() or "draft"
        self._panel_factory = panel_factory
        self._counter = 0
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.tab_widget = QTabWidget()
        self.tab_widget.setTabsClosable(True)
        self.tab_widget.setMovable(True)
        self.tab_widget.setStyleSheet(TAB_STYLE_COMPACT if self.compact_inactive_tabs else TAB_STYLE)
        self.tab_widget.tabCloseRequested.connect(self._close_tab)
        self.tab_widget.currentChanged.connect(self._update_close_buttons)
        if self.compact_inactive_tabs:
            self.tab_widget.currentChanged.connect(self._refresh_tab_labels)
        if self.editable_tab_titles:
            self.tab_widget.tabBarDoubleClicked.connect(self._rename_tab_dialog)
        self.tab_widget.tabBar().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tab_widget.tabBar().customContextMenuRequested.connect(self._open_tab_context_menu)

        layout.addWidget(self.tab_widget)
        self.add_tab()

    def add_tab(
        self,
        title: str = "",
        content: str = "",
        file_path: str = "",
        read_only: bool | None = None,
        activate: bool = True,
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

        index = self.tab_widget.addTab(panel, title)
        self._set_full_tab_title(index, title)
        if activate:
            self.tab_widget.setCurrentIndex(index)
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
        widget = self.tab_widget.currentWidget()
        return widget if isinstance(widget, QWidget) and hasattr(widget, "editor") else None

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

    def _truncate_stored_title(self, title: str) -> str:
        text = (title or "").strip() or self.tab_title_prefix
        max_chars = self.stored_title_max_chars
        if max_chars > 0 and len(text) > max_chars:
            if max_chars <= 3:
                text = "." * max_chars
            else:
                keep_chars = max(1, max_chars - 3)
                text = text[:keep_chars] + "..."
        return text

    def _set_full_tab_title(self, index: int, title: str):
        full = self._clean_title(title)
        stored = self._truncate_stored_title(full)
        bar = self.tab_widget.tabBar()
        bar.setTabData(index, stored)
        self.tab_widget.setTabToolTip(index, full)
        if not self.compact_inactive_tabs:
            self.tab_widget.setTabText(index, stored)

    def _display_title(self, full: str, is_active: bool, index: int) -> str:
        if not self.compact_inactive_tabs:
            return self._truncate_stored_title(full)
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
        count = self.tab_widget.count()
        if count <= 0:
            return
        current = self.tab_widget.currentIndex()
        for index in range(count):
            full = self.get_tab_full_title(index)
            ro_prefix = "🔒 " if self._panel_is_read_only(index) else ""
            display = self._display_title(full, index == current, index)
            self.tab_widget.setTabText(index, f"{ro_prefix}{display}")
            self.tab_widget.setTabToolTip(index, full)

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
        export_action = menu.addAction("Exportieren…")
        menu.addSeparator()
        read_only_action = menu.addAction("🔒 Read-Only")
        read_only_action.setCheckable(True)
        read_only_action.setChecked(bool(editor.isReadOnly()))

        markdown_action = None
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

            markdown_action = menu.addAction("Zeige Markdown")
            markdown_action.setCheckable(True)
            both_action = menu.addAction("Zeige beides")
            both_action.setCheckable(True)

            if hasattr(panel, "view_mode"):
                mode = str(panel.view_mode())
            else:
                markdown_visible = bool(panel.is_markdown_visible())
                html_visible = bool(panel.is_preview_visible())
                mode = "both" if (markdown_visible and html_visible) else (
                    "markdown" if markdown_visible else "preview"
                )

            preview_action.setChecked(mode == "preview")
            markdown_action.setChecked(mode == "markdown")
            both_action.setChecked(mode == "both")

        picked = menu.exec(bar.mapToGlobal(pos))
        if picked is None:
            return

        if picked is export_action:
            tab_name = self.get_tab_full_title(index)
            exporter = CanvasFileActions(parent=self, tabs=self)
            exporter.export_specific_panel(
                panel,
                default_format="pdf",
                panel_scope=self.export_scope,
                tab_name=tab_name,
            )
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

        if markdown_action is not None and picked is markdown_action:
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
        count = self.tab_widget.count()
        current = self.tab_widget.currentIndex()
        bar = self.tab_widget.tabBar()
        show_close = count > 1
        for index in range(count):
            visible = show_close and index == current
            btn_right = bar.tabButton(index, QTabBar.ButtonPosition.RightSide)
            if btn_right is not None:
                btn_right.setVisible(visible)
            btn_left = bar.tabButton(index, QTabBar.ButtonPosition.LeftSide)
            if btn_left is not None:
                btn_left.setVisible(visible)
