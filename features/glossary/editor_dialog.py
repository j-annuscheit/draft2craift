"""Dialog for viewing and editing glossary entries in table form."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from services.highlights import get_highlight_store

_DIALOG_STYLE = """
QDialog {
    background: palette(window);
    color: palette(window-text);
}
QLabel { color: palette(text); font-size: 11px; }
QTableWidget {
    background: palette(base);
    color: palette(text);
    border: 1px solid palette(mid);
    gridline-color: palette(alternate-base);
    font-size: 11px;
}
QTableWidget::item { padding: 4px 8px; }
QTableWidget::item:selected { background: palette(highlight); color: palette(highlighted-text); }
QHeaderView::section {
    background: palette(alternate-base);
    color: palette(highlight);
    border: none;
    border-right: 1px solid palette(mid);
    padding: 4px 8px;
    font-size: 11px;
}
QPushButton {
    background: palette(alternate-base);
    color: palette(text);
    border: 1px solid palette(mid);
    border-radius: 4px;
    padding: 4px 12px;
    font-size: 11px;
}
QPushButton:hover { border: 1px solid palette(highlight); }
"""


class GlossaryEditorDialog(QDialog):
    """Table editor for glossary terms and definitions."""

    glossary_saved = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Glossar verwalten")
        self.resize(880, 520)
        self.setStyleSheet(_DIALOG_STYLE)
        self._store = get_highlight_store()
        self._setup_ui()
        self._load_entries()

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        self._summary_lbl = QLabel("")
        self._summary_lbl.setWordWrap(True)
        root.addWidget(self._summary_lbl)

        self._table = QTableWidget(0, 2)
        self._table.setHorizontalHeaderLabels(
            ["Begriff", "Definition (Hover-Text)"]
        )
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self._table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        root.addWidget(self._table, 1)

        row_buttons = QHBoxLayout()
        self._add_btn = QPushButton("Zeile hinzufügen")
        self._add_btn.clicked.connect(self._add_row)
        row_buttons.addWidget(self._add_btn)

        self._delete_btn = QPushButton("Ausgewählte Zeilen löschen")
        self._delete_btn.clicked.connect(self._delete_selected_rows)
        row_buttons.addWidget(self._delete_btn)

        self._reload_btn = QPushButton("Neu laden")
        self._reload_btn.clicked.connect(self._load_entries)
        row_buttons.addWidget(self._reload_btn)
        row_buttons.addStretch(1)
        root.addLayout(row_buttons)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self._save_btn = buttons.addButton(
            "Speichern",
            QDialogButtonBox.ButtonRole.AcceptRole,
        )
        self._save_btn.clicked.connect(self._save_entries)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _new_item(self, text: str = "") -> QTableWidgetItem:
        return QTableWidgetItem(str(text or ""))

    def _set_summary(self, entry_count: int):
        self._summary_lbl.setText(
            "Glossar-Einträge: "
            f"{int(entry_count)}. Änderungen über 'Speichern' übernehmen."
        )

    def _append_row(self, term: str = "", definition: str = ""):
        row = self._table.rowCount()
        self._table.insertRow(row)
        self._table.setItem(row, 0, self._new_item(term))
        self._table.setItem(row, 1, self._new_item(definition))

    def _add_row(self):
        self._append_row("", "")
        row = self._table.rowCount() - 1
        self._table.setCurrentCell(row, 0)
        self._table.editItem(self._table.item(row, 0))

    def _delete_selected_rows(self):
        rows = sorted(
            {
                idx.row()
                for idx in self._table.selectionModel().selectedRows()
            },
            reverse=True,
        )
        for row in rows:
            self._table.removeRow(int(row))
        self._set_summary(self._table.rowCount())

    def _load_entries(self):
        entries = self._store.list_glossary_entries()
        self._table.setRowCount(0)
        for row in entries:
            self._append_row(
                str(row.get("term", "") or ""),
                str(row.get("definition", "") or ""),
            )
        self._set_summary(len(entries))

    def _collect_entries(self) -> tuple[list[dict], list[str]]:
        entries: list[dict] = []
        errors: list[str] = []
        seen_terms: set[str] = set()
        for row in range(self._table.rowCount()):
            term_item = self._table.item(row, 0)
            def_item = self._table.item(row, 1)
            term = str(term_item.text() if term_item else "").strip()
            definition = str(def_item.text() if def_item else "").strip()

            if not term and not definition:
                continue
            if not term:
                errors.append(f"Zeile {row + 1}: Begriff fehlt.")
                continue

            key = term.casefold()
            if key in seen_terms:
                errors.append(f"Zeile {row + 1}: Begriff '{term}' ist doppelt.")
                continue
            seen_terms.add(key)
            entries.append(
                {
                    "term": term,
                    "definition": definition,
                }
            )
        return entries, errors

    def _save_entries(self):
        entries, errors = self._collect_entries()
        if errors:
            QMessageBox.warning(
                self,
                "Glossar",
                "Bitte korrigieren:\n- " + "\n- ".join(errors[:24]),
            )
            return
        count = self._store.replace_glossary_entries(
            entries=entries,
            panel_scope="*",
            apply_all_tabs=True,
        )
        self._set_summary(count)
        self.glossary_saved.emit(int(count))
