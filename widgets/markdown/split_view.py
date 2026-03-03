"""Reusable Markdown + HTML split-view panel."""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QSplitter, QTabWidget, QVBoxLayout, QWidget

from features.canvas.preview import CanvasPreviewPane

from .editor import EditorPanel


class MarkdownSplitPanel(QWidget):
    """
    Shared split-view for markdown display/edit + HTML preview.

    This panel intentionally exposes ``editor`` and ``file_path`` like
    ``EditorPanel`` so existing tab containers can use it without custom logic.
    """

    file_path: str = ""

    def __init__(
        self,
        parent: QWidget | None = None,
        read_only: bool = False,
        show_toolbar: bool = True,
        lock_toggle_enabled: bool = True,
        allow_preview_editing: bool = True,
        preview_show_title: bool = True,
        show_markdown_by_default: bool = False,
        show_preview_by_default: bool = True,
        sync_preview_to_cursor: bool = True,
        highlight_scope: str = "generic",
    ):
        super().__init__(parent)
        self._editor_panel = EditorPanel(
            read_only=read_only,
            show_toolbar=show_toolbar,
        )
        self.editor = self._editor_panel.editor
        self._highlight_scope = str(highlight_scope or "generic").strip().lower()
        self._preview_editing_capable = bool(allow_preview_editing)
        self._markdown_visible = bool(show_markdown_by_default)
        self._preview_visible = bool(show_preview_by_default)
        if not self._markdown_visible and not self._preview_visible:
            self._preview_visible = True
        self._splitter: QSplitter | None = None
        self._preview = CanvasPreviewPane(
            allow_editing=False,
            show_title=preview_show_title,
            sync_cursor_with_editor=sync_preview_to_cursor,
        )
        self._preview.configure_highlights(
            scope=self._highlight_scope,
            tab_name_getter=self._resolve_host_tab_name,
            tab_switcher=self._switch_host_tab,
        )
        self._preview.bind_editor(self.editor)
        self._setup_ui(lock_toggle_enabled=lock_toggle_enabled)
        self.editor.read_only_changed.connect(
            self._on_editor_read_only_changed
        )
        self._apply_pane_visibility()
        self.set_editable_mode(not bool(read_only))

    def _setup_ui(self, lock_toggle_enabled: bool):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        self._editor_panel.setMinimumWidth(0)
        self._preview.setMinimumWidth(0)
        splitter.addWidget(self._editor_panel)
        splitter.addWidget(self._preview)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([600, 400])
        layout.addWidget(splitter)
        self._splitter = splitter

        if not lock_toggle_enabled and self._editor_panel.lock_btn is not None:
            self._editor_panel.lock_btn.setVisible(False)

    def set_markdown_text(self, text: str):
        if hasattr(self._preview, "invalidate_render_cache"):
            self._preview.invalidate_render_cache()
        self.editor.setPlainText(text or "")
        self._preview.schedule_update()
        self._preview.schedule_cursor_sync()

    def set_highlight_tab_name_getter(
        self,
        getter: Callable[[], str] | None,
    ):
        self._preview.configure_highlights(
            scope=self._highlight_scope,
            tab_name_getter=getter or self._resolve_host_tab_name,
            tab_switcher=self._switch_host_tab,
        )

    def clear_text(self):
        self.set_markdown_text("")

    def set_editable_mode(self, editable: bool):
        self.editor.setReadOnly(not bool(editable))

    def preview_zoom_percent(self) -> int:
        return self._preview.preview_zoom_percent()

    def set_preview_zoom_percent(self, percent: int) -> bool:
        return self._preview.set_preview_zoom_percent(percent)

    def increase_preview_text_size(self) -> bool:
        return self._preview.increase_preview_text_size()

    def decrease_preview_text_size(self) -> bool:
        return self._preview.decrease_preview_text_size()

    def reset_preview_text_size(self) -> bool:
        return self._preview.reset_preview_text_size()

    def is_preview_widget(self, widget: QWidget | None) -> bool:
        return self._preview.is_preview_widget(widget)

    def refresh_preview_overlays(self):
        if hasattr(self._preview, "request_preserve_view_state"):
            self._preview.request_preserve_view_state()
        self._preview.schedule_update()

    def flush_pending_preview_edits(self):
        if hasattr(self._preview, "flush_pending_preview_edits"):
            self._preview.flush_pending_preview_edits()

    def scroll_to_bottom(self):
        editor_scroll = self.editor.verticalScrollBar()
        editor_scroll.setValue(editor_scroll.maximum())
        self._preview.scroll_to_bottom()

    def get_preview_selected_text(self) -> str:
        return self._preview.get_selected_text()

    def should_use_preview_selection(self) -> bool:
        return self._preview_visible and not self._markdown_visible

    def is_markdown_visible(self) -> bool:
        return self._markdown_visible

    def is_preview_visible(self) -> bool:
        return self._preview_visible

    def view_mode(self) -> str:
        if self._markdown_visible and self._preview_visible:
            return "both"
        if self._markdown_visible:
            return "markdown"
        return "preview"

    def set_view_mode(self, mode: str):
        normalized = str(mode or "").strip().lower()
        if normalized == "markdown":
            self._markdown_visible = True
            self._preview_visible = False
        elif normalized == "both":
            self._markdown_visible = True
            self._preview_visible = True
        else:
            self._markdown_visible = False
            self._preview_visible = True
        self._apply_pane_visibility()
        if hasattr(self._preview, "invalidate_render_cache"):
            self._preview.invalidate_render_cache()
        self._preview.schedule_update()
        self._preview.schedule_cursor_sync()

    def set_markdown_visible(self, visible: bool):
        target = bool(visible)
        if (not target) and (not self._preview_visible):
            return
        self._markdown_visible = target
        self._apply_pane_visibility()

    def set_preview_visible(self, visible: bool):
        target = bool(visible)
        if (not target) and (not self._markdown_visible):
            return
        self._preview_visible = target
        self._apply_pane_visibility()

    def _on_editor_read_only_changed(self, _read_only: bool):
        self._sync_preview_editing_mode()

    def _sync_preview_editing_mode(self):
        allow_preview_editing = (
            self._preview_editing_capable
            and not self.editor.isReadOnly()
            and self._preview_visible
        )
        self._preview.set_allow_editing(allow_preview_editing)

    def _apply_pane_visibility(self):
        self._editor_panel.setVisible(self._markdown_visible)
        self._preview.setVisible(self._preview_visible)

        splitter = self._splitter
        if splitter is not None:
            if self._markdown_visible and self._preview_visible:
                splitter.setSizes([600, 400])
            elif self._markdown_visible:
                splitter.setSizes([1, 0])
            else:
                splitter.setSizes([0, 1])

        self._sync_preview_editing_mode()

    def _resolve_host_tab_name(self) -> str:
        parent = self.parentWidget()
        while parent is not None:
            if isinstance(parent, QTabWidget):
                idx = parent.indexOf(self)
                if idx >= 0:
                    try:
                        bar = parent.tabBar()
                        data = bar.tabData(idx)
                    except Exception:
                        data = None
                    if isinstance(data, str) and data.strip():
                        return data.strip()
                    label = str(parent.tabText(idx) or "").strip()
                    if label.startswith("🔒 "):
                        label = label[2:].strip()
                    return label
            parent = parent.parentWidget()
        return ""

    def _switch_host_tab(self, title: str) -> bool:
        target = str(title or "").strip()
        if not target:
            return False
        parent = self.parentWidget()
        while parent is not None:
            if isinstance(parent, QTabWidget):
                bar = parent.tabBar()
                for idx in range(parent.count()):
                    data = bar.tabData(idx)
                    full = str(data or "").strip()
                    if full == target:
                        parent.setCurrentIndex(idx)
                        return True
                    label = str(parent.tabText(idx) or "").strip()
                    if label.startswith("🔒 "):
                        label = label[2:].strip()
                    if label == target:
                        parent.setCurrentIndex(idx)
                        return True
                return False
            parent = parent.parentWidget()
        return False
