"""Zoom and canvas view-mode helpers extracted from MainWindow."""
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6.QtWidgets import QApplication

if TYPE_CHECKING:
    from studio.canvas.tabs import CanvasTabWidget
    from studio.controllers.canvas_controller import CanvasController


class ZoomController:
    """Manages text-size zoom for the markdown editor and HTML preview panes."""

    def __init__(
        self,
        *,
        canvas: CanvasTabWidget,
        show_status: Callable[[str, int], None],
    ):
        self._canvas = canvas
        self._show_status = show_status

    # ── focused editor ────────────────────────────────────────────────

    def _focused_markdown_editor(self):
        from studio.canvas.editor import MarkdownEditor
        w = QApplication.focusWidget()
        while w is not None:
            if isinstance(w, MarkdownEditor):
                return w
            w = w.parentWidget()
        return None

    def _is_focus_on_html_preview(self) -> bool:
        return self._canvas.is_preview_widget(QApplication.focusWidget())

    def _zoom_status(self, label: str, percent: int):
        self._show_status(f"{label}: {percent}%", 1500)

    # ── active-pane zoom ──────────────────────────────────────────────

    def increase_active(self):
        editor = self._focused_markdown_editor()
        if editor is not None:
            if editor.increase_zoom():
                self._zoom_status("Markdown-Ansicht", editor.zoom_percent())
            return
        if self._is_focus_on_html_preview():
            if self._canvas.increase_preview_text_size():
                self._zoom_status("HTML-Vorschau", self._canvas.preview_zoom_percent())
            return
        panel = self._canvas.tabs.current_panel()
        if panel and panel.editor.increase_zoom():
            self._zoom_status("Markdown-Ansicht", panel.editor.zoom_percent())

    def decrease_active(self):
        editor = self._focused_markdown_editor()
        if editor is not None:
            if editor.decrease_zoom():
                self._zoom_status("Markdown-Ansicht", editor.zoom_percent())
            return
        if self._is_focus_on_html_preview():
            if self._canvas.decrease_preview_text_size():
                self._zoom_status("HTML-Vorschau", self._canvas.preview_zoom_percent())
            return
        panel = self._canvas.tabs.current_panel()
        if panel and panel.editor.decrease_zoom():
            self._zoom_status("Markdown-Ansicht", panel.editor.zoom_percent())

    def reset_active(self):
        editor = self._focused_markdown_editor()
        if editor is not None:
            if editor.reset_zoom():
                self._zoom_status("Markdown-Ansicht", editor.zoom_percent())
            return
        if self._is_focus_on_html_preview():
            if self._canvas.reset_preview_text_size():
                self._zoom_status("HTML-Vorschau", self._canvas.preview_zoom_percent())
            return
        panel = self._canvas.tabs.current_panel()
        if panel and panel.editor.reset_zoom():
            self._zoom_status("Markdown-Ansicht", panel.editor.zoom_percent())

    # ── preview-only zoom ─────────────────────────────────────────────

    def increase_preview(self):
        if self._canvas.increase_preview_text_size():
            self._zoom_status("HTML-Vorschau", self._canvas.preview_zoom_percent())

    def decrease_preview(self):
        if self._canvas.decrease_preview_text_size():
            self._zoom_status("HTML-Vorschau", self._canvas.preview_zoom_percent())

    def reset_preview(self):
        if self._canvas.reset_preview_text_size():
            self._zoom_status("HTML-Vorschau", self._canvas.preview_zoom_percent())

    # ── view-mode shortcut ────────────────────────────────────────────

    def set_canvas_view_mode(self, mode: str, *, canvas_controller: CanvasController):
        panel = canvas_controller.resolve_active_split_panel()
        if panel is None or not hasattr(panel, "set_view_mode"):
            return
        normalized = str(mode or "").strip().lower()
        if normalized not in {"markdown", "preview", "both"}:
            return
        panel.set_view_mode(normalized)
        label_map = {"markdown": "nur Markdown", "preview": "nur HTML", "both": "Split (Markdown + HTML)"}
        self._show_status(f"Ansicht: {label_map.get(normalized, normalized)}", 1800)
