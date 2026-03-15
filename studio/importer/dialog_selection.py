from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QInputDialog, QLineEdit, QListWidgetItem

from shared.domain.user_mode import resolve_feature_label
from shared.services.importer.entry import (
    ImportEntry,
    can_keep_detection_state,
    copy_runtime_state,
    preview_placeholder_text,
)
from shared.services.importer.models import _SUPPORTED_FILTER
from .ui_constants import _ICON, _STATUS_PENDING


class FileImportSelectionMixin:
    """File list and selection handling."""

    def _unique_entry_name(self, desired: str, current_path: str) -> str:
        target = str(desired or "").strip()
        if not target:
            return ""
        existing = {
            str(entry.name or "").strip()
            for path, entry in self._entries.items()
            if str(path or "") != str(current_path or "")
        }
        if target not in existing:
            return target
        stem, dot, ext = target.rpartition(".")
        root = stem if dot else target
        suffix = f".{ext}" if dot else ""
        idx = 1
        while True:
            candidate = f"{root} ({idx}){suffix}"
            if candidate not in existing:
                return candidate
            idx += 1

    def _rename_list_item(self, item: QListWidgetItem):
        if item is None:
            return
        path = str(item.data(Qt.ItemDataRole.UserRole) or "").strip()
        if not path:
            return
        entry = self._entries.get(path)
        if entry is None:
            return

        current_name = str(entry.name or "").strip() or os.path.basename(path)
        new_name, ok = QInputDialog.getText(
            self,
            resolve_feature_label(
                self._user_mode,
                "importer.dialog.rename.window_title",
                "Datei umbenennen",
            ),
            resolve_feature_label(
                self._user_mode,
                "importer.dialog.rename.prompt",
                "Neuer Name:",
            ),
            QLineEdit.EchoMode.Normal,
            current_name,
        )
        if not ok:
            return

        cleaned = str(new_name or "").strip()
        if not cleaned or cleaned == current_name:
            return

        final_name = self._unique_entry_name(cleaned, path)
        if not final_name:
            return

        entry.name = final_name

        update_item = getattr(self, "_update_list_item", None)
        if callable(update_item):
            update_item(path, entry.status)
        else:
            item.setText(f"{_ICON.get(entry.status, _ICON[_STATUS_PENDING])}  {entry.name}")

        if path == self._current_path and (not str(entry.markdown or "").strip()):
            self._preview.set_markdown_text(
                preview_placeholder_text(entry.name, entry.is_pdf())
            )

    def _add_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            resolve_feature_label(
                self._user_mode,
                "importer.dialog.file_picker.title",
                "Add Files",
            ),
            "",
            _SUPPORTED_FILTER,
        )
        for path in paths:
            if path in self._entries:
                continue
            entry = ImportEntry(path=path, name=os.path.basename(path))
            self._entries[path] = entry
            item = QListWidgetItem(f"{_ICON[_STATUS_PENDING]}  {entry.name}")
            item.setData(Qt.ItemDataRole.UserRole, path)
            self._list.addItem(item)
        self._btn_import.setEnabled(bool(self._entries))
        refresh = getattr(self, "_refresh_llm_fix_button", None)
        if callable(refresh):
            refresh()

    def _remove_selected(self):
        item = self._list.currentItem()
        if not item:
            return
        path = item.data(Qt.ItemDataRole.UserRole)
        self._entries.pop(path, None)
        self._list.takeItem(self._list.row(item))
        if self._current_path == path:
            self._current_path = None
            self._preview.clear_text()
            self._pdf_viewer.clear()
        self._btn_import.setEnabled(bool(self._entries))
        update_open = getattr(self, "_update_open_button_state", None)
        if callable(update_open):
            update_open()
        else:
            self._btn_open.setEnabled(self._has_converted())
        refresh = getattr(self, "_refresh_llm_fix_button", None)
        if callable(refresh):
            refresh()

    def _on_item_selected(self, current: QListWidgetItem, previous: QListWidgetItem):
        if previous is not None and self._current_path:
            self._save_panel_settings(self._current_path)

        if not current:
            self._preview.clear_text()
            self._pdf_viewer.clear()
            self._pdf_panel.set_enabled_for_pdf(False)
            self._current_path = None
            sync_status = getattr(self, "_sync_llm_fix_status_for_current_path", None)
            if callable(sync_status):
                sync_status()
            refresh = getattr(self, "_refresh_llm_fix_button", None)
            if callable(refresh):
                refresh()
            return

        path = current.data(Qt.ItemDataRole.UserRole)
        self._current_path = path
        entry = self._entries.get(path)
        if not entry:
            return

        is_pdf = entry.is_pdf()
        self._pdf_panel.set_enabled_for_pdf(is_pdf)
        if is_pdf:
            self._pdf_panel.set_settings(entry.pdf_settings)
            self._pdf_viewer.load_pdf(path, entry.pdf_settings, entry.body_size, entry.markdown)
            self._tabs.setCurrentIndex(0)
        else:
            self._pdf_viewer.clear()
            self._tabs.setCurrentIndex(1)

        if entry.markdown:
            self._preview.set_markdown_text(entry.markdown)
        else:
            self._preview.set_markdown_text(
                preview_placeholder_text(entry.name, is_pdf)
            )
        refresh = getattr(self, "_refresh_llm_fix_button", None)
        if callable(refresh):
            refresh()
        sync_status = getattr(self, "_sync_llm_fix_status_for_current_path", None)
        if callable(sync_status):
            sync_status()

    def _save_panel_settings(self, path: str):
        entry = self._entries.get(path)
        if entry is None or not entry.is_pdf():
            return
        old_settings = entry.pdf_settings
        new_settings = self._pdf_panel.get_settings()
        keep_detection = can_keep_detection_state(old_settings, new_settings)
        copy_runtime_state(
            old_settings,
            new_settings,
            keep_detection=keep_detection,
        )
        entry.pdf_settings = new_settings

    def _on_settings_changed(self):
        if self._current_path:
            self._save_panel_settings(self._current_path)
        if self._current_path and self._current_path in self._entries:
            entry = self._entries[self._current_path]
            self._pdf_viewer.refresh_settings(
                entry.pdf_settings,
                entry.body_size,
            )

    def _toggle_settings(self):
        """Collapse or expand the middle (PDF Settings) pane."""
        self._settings_visible = not self._settings_visible
        sizes = self._splitter.sizes()
        total = sum(sizes)
        left_w = sizes[0]
        if self._settings_visible:
            mid_w = 320
            right_w = max(10, total - left_w - mid_w)
            self._splitter.setSizes([left_w, mid_w, right_w])
            updater = getattr(self, "_update_toggle_settings_button_text", None)
            if callable(updater):
                updater()
            return
        self._splitter.setSizes([left_w, 0, total - left_w])
        updater = getattr(self, "_update_toggle_settings_button_text", None)
        if callable(updater):
            updater()

    def _on_zone_changed(self, top: float, bottom: float):
        """Called when user drags zone boundary lines in the PDF viewer."""
        if not self._current_path:
            return
        entry = self._entries.get(self._current_path)
        if entry is None:
            return
        settings = entry.pdf_settings
        if settings.auto_hf_detect:
            return
        self._pdf_panel.set_zones(top, bottom)
        settings.hf_top_zone = top
        settings.hf_bottom_zone = bottom
