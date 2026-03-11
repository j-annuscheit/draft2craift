from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

_FILES_STYLE = """
QListWidget {
    background: palette(base);
    color: palette(text);
    border: none;
    font-size: 11px;
}
QListWidget::item {
    padding: 4px 6px;
    border-bottom: 1px solid palette(mid);
}
QListWidget::item:selected {
    background: palette(highlight);
    color: palette(highlighted-text);
}
QListWidget::item:hover {
    background: palette(alternate-base);
}
"""

_FILES_BAR_STYLE = """
QWidget {
    background: palette(alternate-base);
    border-bottom: 1px solid palette(mid);
}
QPushButton {
    background: palette(base);
    color: palette(text);
    border: 1px solid palette(mid);
    padding: 2px 8px;
    border-radius: 3px; font-size: 10px;
}
QPushButton:hover { border: 1px solid palette(highlight); }
"""


class ImportedFilesPanel(QWidget):
    """
    Checkbox list of imported (converted) documents.
    Checked items are sent to RAG; unchecking removes them.
    """

    selection_changed = Signal(list)   # list of (name: str, content: str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._entries: dict[str, str] = {}   # name → markdown content
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        bar = QWidget()
        bar.setFixedHeight(34)
        bar.setStyleSheet(_FILES_BAR_STYLE)
        hbox = QHBoxLayout(bar)
        hbox.setContentsMargins(6, 4, 6, 4)
        hbox.setSpacing(4)

        lbl = QLabel("Select files for RAG")
        lbl.setStyleSheet(
            "color: palette(placeholder-text); font-size: 10px; background: transparent;"
        )
        hbox.addWidget(lbl)
        hbox.addStretch()

        btn_all = QPushButton("All")
        btn_none = QPushButton("None")
        btn_all.clicked.connect(self._select_all)
        btn_none.clicked.connect(self._select_none)
        hbox.addWidget(btn_all)
        hbox.addWidget(btn_none)
        layout.addWidget(bar)

        self._list = QListWidget()
        self._list.setStyleSheet(_FILES_STYLE)
        self._list.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self._list, stretch=1)

        self._status_lbl = QLabel("No files imported yet")
        self._status_lbl.setStyleSheet(
            "color: palette(placeholder-text); font-size: 10px; padding: 4px 8px;"
            "background: palette(base); border-top: 1px solid palette(mid);"
        )
        layout.addWidget(self._status_lbl)

    def add_file(self, name: str, content: str):
        """Register a new imported file (checked by default)."""
        if name in self._entries:
            return
        self._entries[name] = content

        item = QListWidgetItem(name)
        item.setData(Qt.ItemDataRole.UserRole, name)
        item.setCheckState(Qt.CheckState.Checked)
        self._list.addItem(item)
        self._update_status()
        self._emit_selection()

    def add_files(self, entries: list[tuple[str, str]]):
        """
        Register multiple imported files in one batch (checked by default).

        Emits selection/state update only once to avoid repeated expensive
        downstream work (e.g. RAG reindex storms during bulk import).
        """
        rows = list(entries or [])
        if not rows:
            self._update_status()
            return

        added = False
        self._list.blockSignals(True)
        try:
            for name_raw, content_raw in rows:
                name = str(name_raw or "").strip()
                if not name or name in self._entries:
                    continue
                self._entries[name] = str(content_raw or "")
                item = QListWidgetItem(name)
                item.setData(Qt.ItemDataRole.UserRole, name)
                item.setCheckState(Qt.CheckState.Checked)
                self._list.addItem(item)
                added = True
        finally:
            self._list.blockSignals(False)

        if added:
            self._emit_selection()
        else:
            self._update_status()

    def clear_all(self):
        """Remove all imported files and reset the panel to its initial state."""
        self._list.blockSignals(True)
        self._list.clear()
        self._list.blockSignals(False)
        self._entries.clear()
        self._update_status()

    def remove_file(self, name: str):
        """Remove one imported file from the panel and emit updated selection."""
        key = str(name or "").strip()
        if not key:
            return
        existed = key in self._entries
        self._entries.pop(key, None)

        self._list.blockSignals(True)
        for i in range(self._list.count() - 1, -1, -1):
            item = self._list.item(i)
            item_key = str(item.data(Qt.ItemDataRole.UserRole) or "").strip()
            if item_key == key:
                self._list.takeItem(i)
        self._list.blockSignals(False)

        if existed:
            self._emit_selection()
        else:
            self._update_status()

    @staticmethod
    def _unique_name(target: str, existing: set[str], current: str) -> str:
        desired = str(target or "").strip() or str(current or "").strip() or "Document"
        if desired == current or desired not in existing:
            return desired

        stem, dot, ext = desired.rpartition(".")
        root = stem if dot else desired
        suffix = f".{ext}" if dot else ""

        idx = 1
        while True:
            candidate = f"{root} ({idx}){suffix}"
            if candidate not in existing or candidate == current:
                return candidate
            idx += 1

    def rename_file(self, old_name: str, new_name: str) -> str:
        """Rename one imported file entry and keep selection/check-state."""
        old_key = str(old_name or "").strip()
        if not old_key or old_key not in self._entries:
            return ""

        final = self._unique_name(new_name, set(self._entries.keys()), old_key)
        if final == old_key:
            return old_key

        content = self._entries.pop(old_key)
        self._entries[final] = content

        self._list.blockSignals(True)
        for i in range(self._list.count()):
            item = self._list.item(i)
            item_key = str(item.data(Qt.ItemDataRole.UserRole) or "").strip()
            if item_key != old_key:
                continue
            item.setData(Qt.ItemDataRole.UserRole, final)
            item.setText(final)
            break
        self._list.blockSignals(False)

        self._emit_selection()
        return final

    def _select_all(self):
        self._list.blockSignals(True)
        for i in range(self._list.count()):
            self._list.item(i).setCheckState(Qt.CheckState.Checked)
        self._list.blockSignals(False)
        self._emit_selection()

    def _select_none(self):
        self._list.blockSignals(True)
        for i in range(self._list.count()):
            self._list.item(i).setCheckState(Qt.CheckState.Unchecked)
        self._list.blockSignals(False)
        self._emit_selection()

    def _on_item_changed(self, _item: QListWidgetItem):
        self._emit_selection()

    def get_checked_files(self) -> list[tuple[str, str]]:
        """Return [(name, content), …] for all currently checked files."""
        checked = []
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                name = item.data(Qt.ItemDataRole.UserRole)
                if name in self._entries:
                    checked.append((name, self._entries[name]))
        return checked

    def get_document_content(self, name: str) -> str:
        """Return markdown content for one imported document name."""
        key = str(name or "").strip()
        if not key:
            return ""
        return str(self._entries.get(key, "") or "")

    def get_all_documents(self) -> dict[str, str]:
        """Return a copy of all imported documents mapped by display name."""
        return {str(name): str(content or "") for name, content in self._entries.items()}

    def _emit_selection(self):
        self.selection_changed.emit(self.get_checked_files())
        self._update_status()

    def _update_status(self):
        total = self._list.count()
        if total == 0:
            self._status_lbl.setText("No files imported yet")
            return
        checked = sum(
            1 for i in range(total)
            if self._list.item(i).checkState() == Qt.CheckState.Checked
        )
        self._status_lbl.setText(f"{checked} / {total} selected for RAG")
