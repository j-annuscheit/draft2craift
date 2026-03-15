from __future__ import annotations

from PySide6.QtWidgets import QMessageBox, QVBoxLayout, QWidget
from PySide6.QtCore import Signal

from shared.domain.user_mode import (
    default_user_mode,
    normalize_user_mode,
    resolve_feature_label,
)
from shared.services.highlights.store import get_highlight_store
from studio.canvas.tabbed_editor_widget import TabbedEditorWidget
from studio.canvas.split_view import MarkdownSplitPanel


class DocumentViewerPanel(QWidget):
    """Multi-tab document viewer with shared markdown split-view panels."""

    file_remove_requested = Signal(str, str)   # (doc_key, visible_title)
    document_rename_requested = Signal(str, str)  # (old_doc_key, new_doc_key)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._user_mode = normalize_user_mode(
            str(getattr(parent, "user_mode", "") or "") or default_user_mode()
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.tabs = TabbedEditorWidget(
            default_read_only=True,
            tab_title_prefix="Doc",
            editable_tab_titles=True,
            compact_inactive_tabs=True,
            active_title_max_chars=10,
            strip_file_extensions=True,
            export_scope="viewer",
            panel_factory=lambda ro: MarkdownSplitPanel(
                read_only=ro,
                show_toolbar=True,
                lock_toggle_enabled=False,
                allow_preview_editing=True,
                show_markdown_by_default=False,
                show_preview_by_default=True,
                highlight_scope="viewer",
            ),
        )
        layout.addWidget(self.tabs)
        self.tabs.tab_renamed.connect(self._on_tab_renamed)
        self.tabs.tab_widget.currentChanged.connect(self._on_current_tab_changed)

        try:
            self.tabs.tab_widget.tabCloseRequested.disconnect(self.tabs._close_tab)
        except Exception:
            pass
        self.tabs.tab_widget.tabCloseRequested.connect(self._on_tab_close_requested)
        self.set_user_mode(self._user_mode)

    def _label(self, key: str, default: str) -> str:
        return resolve_feature_label(self._user_mode, key, default)

    def set_user_mode(self, mode: str) -> None:
        self._user_mode = normalize_user_mode(mode)
        tab_widget = self.tabs.tab_widget
        for idx in range(tab_widget.count()):
            self._apply_panel_user_mode(tab_widget.widget(idx))

    def open_file(self, path: str):
        """Open file in a new tab, or switch to existing tab."""
        for i in range(self.tabs.tab_widget.count()):
            panel = self.tabs.tab_widget.widget(i)
            if str(getattr(panel, "file_path", "")) == str(path):
                self.tabs.tab_widget.setCurrentIndex(i)
                return
        panel = self.tabs.add_file_tab(path)
        self._apply_panel_user_mode(panel)

    def open_content(
        self,
        title: str,
        content: str,
        doc_key: str = "",
        *,
        activate: bool = True,
    ):
        """Open pre-converted markdown content in a new viewer tab."""
        panel = self.tabs.add_tab(title=title, content="", activate=activate)
        self._apply_panel_user_mode(panel)
        setattr(panel, "_doc_key", str(doc_key or "").strip())
        setattr(panel, "_lazy_markdown_content", str(content or ""))
        if activate:
            self._materialize_panel_content(panel)
            self._schedule_panel_preview_update(panel)

    def get_current_text(self) -> str:
        panel = self.tabs.current_panel()
        return panel.editor.get_full_text() if panel else ""

    def remove_tabs_for_doc(self, doc_key: str):
        """Remove all viewer tabs that belong to a specific imported document."""
        key = str(doc_key or "").strip()
        if not key:
            return
        tab_widget = self.tabs.tab_widget
        removed = False
        for i in range(tab_widget.count() - 1, -1, -1):
            panel = tab_widget.widget(i)
            panel_key = str(getattr(panel, "_doc_key", "") or "").strip()
            if panel_key == key:
                tab_widget.removeTab(i)
                removed = True
        if removed:
            if tab_widget.count() == 0:
                self.tabs.add_tab()
            self.tabs._refresh_tab_labels()
            self.tabs._update_close_buttons()

    def apply_document_rename(self, old_doc_key: str, new_doc_key: str) -> bool:
        """
        Apply a global document rename across all viewer tabs of that document.

        This updates:
        - internal ``_doc_key`` bindings
        - visible tab titles for all matching tabs
        """
        old_key = str(old_doc_key or "").strip()
        new_key = str(new_doc_key or "").strip()
        if not old_key or not new_key or old_key == new_key:
            return False

        tab_widget = self.tabs.tab_widget
        changed = False
        for i in range(tab_widget.count()):
            panel = tab_widget.widget(i)
            panel_key = str(getattr(panel, "_doc_key", "") or "").strip()
            if panel_key != old_key:
                continue
            setattr(panel, "_doc_key", new_key)
            bar = self.tabs.tab_widget.tabBar()
            bar.setTabData(i, new_key)
            self.tabs.tab_widget.setTabToolTip(i, new_key)
            changed = True

        if changed:
            self.tabs._refresh_tab_labels()
            self.tabs._update_close_buttons()
        return changed

    def _on_tab_close_requested(self, index: int):
        tab_widget = self.tabs.tab_widget
        if index < 0 or index >= tab_widget.count():
            return

        panel = tab_widget.widget(index)
        full_title = (
            self.tabs.get_tab_full_title(index)
            or tab_widget.tabText(index)
            or self._label("knowledge.viewer.document.fallback_title", "Dokument")
        )
        doc_key = str(getattr(panel, "_doc_key", "") or "").strip()

        if not doc_key:
            self.tabs._close_tab(index)
            return

        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setWindowTitle(
            self._label("knowledge.viewer.delete_dialog.title", "Dokument löschen")
        )
        delete_prompt = self._label(
            "knowledge.viewer.delete_dialog.prompt.template",
            "'{title}' wirklich löschen?",
        )
        try:
            msg.setText(delete_prompt.format(title=full_title))
        except Exception:
            msg.setText(f"'{full_title}' wirklich löschen?")
        msg.setInformativeText(
            self._label(
                "knowledge.viewer.delete_dialog.info",
                "Das Dokument wird vollständig entfernt aus:\n"
                "• Viewer\n"
                "• Imported Documents / Selected Files for RAG\n"
                "• Chat-Kontext (Imported Documents)\n\n"
                "Für erneute Nutzung muss es erneut importiert werden.",
            )
        )
        btn_cancel = msg.addButton(
            self._label("knowledge.viewer.delete_dialog.button.cancel", "Abbrechen"),
            QMessageBox.ButtonRole.RejectRole,
        )
        btn_delete = msg.addButton(
            self._label("knowledge.viewer.delete_dialog.button.delete", "Löschen"),
            QMessageBox.ButtonRole.DestructiveRole,
        )
        msg.setDefaultButton(btn_cancel)
        msg.exec()
        if msg.clickedButton() is not btn_delete:
            return

        self.file_remove_requested.emit(doc_key, full_title)

    def _on_tab_renamed(self, old_title: str, new_title: str):
        get_highlight_store().rename_tab(
            panel_scope="viewer",
            old_name=old_title,
            new_name=new_title,
        )
        old_key = str(old_title or "").strip()
        new_key = str(new_title or "").strip()
        if old_key and new_key and old_key != new_key:
            self.document_rename_requested.emit(old_key, new_key)

    def _on_current_tab_changed(self, index: int):
        panel = self.tabs.tab_widget.widget(index)
        if isinstance(panel, QWidget):
            self._materialize_panel_content(panel)
            self._schedule_panel_preview_update(panel)

    @staticmethod
    def _schedule_panel_preview_update(panel: QWidget):
        refresh = getattr(panel, "refresh_preview_overlays", None)
        if callable(refresh):
            try:
                refresh()
            except Exception:
                pass

    def _apply_panel_user_mode(self, panel: QWidget | None) -> None:
        setter = getattr(panel, "set_user_mode", None)
        if callable(setter):
            setter(self._user_mode)

    @staticmethod
    def _materialize_panel_content(panel: QWidget):
        text = getattr(panel, "_lazy_markdown_content", None)
        if text is None:
            return
        editor = getattr(panel, "editor", None)
        if editor is None:
            return
        old_block = bool(editor.blockSignals(True))
        try:
            editor.setPlainText(str(text or ""))
            try:
                delattr(panel, "_lazy_markdown_content")
            except Exception:
                setattr(panel, "_lazy_markdown_content", None)
        finally:
            editor.blockSignals(old_block)
