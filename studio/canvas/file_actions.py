"""File open/save/export actions for canvas tabs."""
from __future__ import annotations

import os
from typing import TYPE_CHECKING

from PySide6.QtWidgets import QDialog, QFileDialog, QMessageBox, QWidget

from .exporting import ExportOptions, ExportOptionsDialog, write_docx, write_pdf

if TYPE_CHECKING:
    from studio.canvas.editor_panel import EditorPanel
    from studio.canvas.tabbed_editor_widget import TabbedEditorWidget


class CanvasFileActions:
    """Encapsulates file dialogs and export logic for canvas tabs."""

    def __init__(self, parent: QWidget, tabs: "TabbedEditorWidget"):
        self._parent = parent
        self._tabs = tabs

    def open_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self._parent,
            "Open File",
            "",
            "Markdown (*.md *.markdown);;Text (*.txt);;All Files (*)",
        )
        if path:
            self._tabs.add_file_tab(path)

    def save_current(self) -> None:
        panel = self._current_panel()
        if panel is None:
            return

        path = panel.file_path or ""
        if not path:
            path, _ = QFileDialog.getSaveFileName(
                self._parent,
                "Save As",
                "untitled.md",
                "Markdown (*.md);;Text (*.txt);;All Files (*)",
            )
        if not path:
            return

        if panel.editor.save_file(path):
            panel.file_path = path
            idx = self._tabs.tab_widget.currentIndex()
            self._tabs.set_tab_full_title(idx, os.path.basename(path))

    def export_document(self, default_format: str = "pdf") -> bool:
        panel = self._current_panel()
        tab_name = self._tab_name_for_panel(panel) if panel is not None else ""
        return self.export_specific_panel(
            panel,
            default_format=default_format,
            panel_scope="draft",
            tab_name=tab_name,
        )

    def export_pdf(self) -> None:
        self.export_document(default_format="pdf")

    def export_word(self) -> None:
        self.export_document(default_format="word")

    def export_specific_panel(
        self,
        panel: QWidget | None,
        *,
        default_format: str = "pdf",
        panel_scope: str = "draft",
        tab_name: str = "",
    ) -> bool:
        if panel is None:
            return False
        editor = getattr(panel, "editor", None)
        if editor is None or not hasattr(editor, "toPlainText"):
            return False

        options = self._ask_export_options(default_format)
        if options is None:
            return False

        is_word = str(options.output_format).strip().lower() == "word"
        suffix = ".docx" if is_word else ".pdf"
        file_filter = "Word Document (*.docx)" if is_word else "PDF (*.pdf)"
        title = "Export as Word" if is_word else "Export as PDF"
        stem_source = str(getattr(panel, "file_path", "") or "").strip()
        if not stem_source:
            stem_source = str(tab_name or self._tab_name_for_panel(panel) or "untitled")
        stem = os.path.splitext(stem_source)[0] or "untitled"

        path, _ = QFileDialog.getSaveFileName(
            self._parent,
            title,
            stem + suffix,
            file_filter,
        )
        if not path:
            return False

        scope = str(panel_scope or "draft").strip().lower() or "draft"
        resolved_tab_name = str(tab_name or self._tab_name_for_panel(panel) or "").strip()
        markdown_text = str(editor.toPlainText() or "")

        try:
            if is_word:
                write_docx(
                    markdown_text,
                    path,
                    options=options,
                    panel_scope=scope,
                    tab_name=resolved_tab_name,
                )
            else:
                write_pdf(
                    markdown_text,
                    path,
                    options=options,
                    panel_scope=scope,
                    tab_name=resolved_tab_name,
                )
            return True
        except ImportError:
            if is_word:
                QMessageBox.warning(
                    self._parent,
                    "Missing Dependency",
                    "python-docx ist nicht installiert. Bitte ausfuehren: pip install python-docx",
                )
            else:
                QMessageBox.warning(
                    self._parent,
                    "Missing Dependency",
                    "Eine benoetigte Export-Abhaengigkeit ist nicht installiert.",
                )
            return False
        except Exception as exc:
            kind = "Word" if is_word else "PDF"
            QMessageBox.warning(self._parent, f"{kind} Export Failed", str(exc))
            return False

    def _current_panel(self) -> "EditorPanel | None":
        return self._tabs.current_panel()

    def _tab_name_for_panel(self, panel: QWidget | None) -> str:
        if panel is None:
            return ""
        tabs = getattr(self._tabs, "tab_widget", None)
        if tabs is None:
            return ""
        for idx in range(tabs.count()):
            if tabs.widget(idx) is not panel:
                continue
            try:
                return str(self._tabs.get_tab_full_title(idx) or "").strip()
            except Exception:
                return str(tabs.tabText(idx) or "").strip()
        return ""

    def _ask_export_options(self, default_format: str) -> ExportOptions | None:
        dialog = ExportOptionsDialog(self._parent, default_format=default_format)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return dialog.options()
