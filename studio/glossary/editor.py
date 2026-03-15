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

from shared.domain.user_mode import normalize_user_mode, resolve_feature_label
from shared.services.highlights.store import get_highlight_store

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

    def __init__(self, parent=None, user_mode: str | None = None):
        super().__init__(parent)
        self._user_mode = normalize_user_mode("" if user_mode is None else user_mode)
        self._add_btn: QPushButton | None = None
        self._delete_btn: QPushButton | None = None
        self._reload_btn: QPushButton | None = None
        self._save_btn: QPushButton | None = None
        self._close_btn: QPushButton | None = None
        self.setWindowTitle(
            resolve_feature_label(
                self._user_mode,
                "glossary.editor.window_title",
                "Glossary Manager",
            )
        )
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
        self._table.setHorizontalHeaderLabels(["", ""])
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self._table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        root.addWidget(self._table, 1)

        row_buttons = QHBoxLayout()
        self._add_btn = QPushButton("")
        self._add_btn.clicked.connect(self._add_row)
        row_buttons.addWidget(self._add_btn)

        self._delete_btn = QPushButton("")
        self._delete_btn.clicked.connect(self._delete_selected_rows)
        row_buttons.addWidget(self._delete_btn)

        self._reload_btn = QPushButton("")
        self._reload_btn.clicked.connect(self._load_entries)
        row_buttons.addWidget(self._reload_btn)
        row_buttons.addStretch(1)
        root.addLayout(row_buttons)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self._save_btn = buttons.addButton(
            "",
            QDialogButtonBox.ButtonRole.AcceptRole,
        )
        self._save_btn.clicked.connect(self._save_entries)
        self._close_btn = buttons.button(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self.set_user_mode(self._user_mode)

    def _new_item(self, text: str = "") -> QTableWidgetItem:
        return QTableWidgetItem(str(text or ""))

    def _summary_text(self, entry_count: int) -> str:
        template = resolve_feature_label(
            self._user_mode,
            "glossary.editor.summary.template",
            "Glossary entries: {count}. Apply changes with 'Save'.",
        )
        return self._format_profile_text(
            str(template),
            fallback=f"{str(template)} {int(entry_count)}",
            count=int(entry_count),
        )

    @staticmethod
    def _format_profile_text(template: str, fallback: str, **kwargs: object) -> str:
        try:
            return str(template).format(**kwargs)
        except Exception:
            return str(fallback)

    def _set_summary(self, entry_count: int):
        self._summary_lbl.setText(self._summary_text(entry_count))

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
                errors.append(
                    self._format_profile_text(
                        resolve_feature_label(
                            self._user_mode,
                            "glossary.editor.validation.term_missing",
                            "Row {row}: term is missing.",
                        ),
                        fallback=f"Row {row + 1}: term is missing.",
                        row=row + 1,
                    )
                )
                continue

            key = term.casefold()
            if key in seen_terms:
                errors.append(
                    self._format_profile_text(
                        resolve_feature_label(
                            self._user_mode,
                            "glossary.editor.validation.term_duplicate",
                            "Row {row}: term '{term}' is duplicated.",
                        ),
                        fallback=f"Row {row + 1}: term '{term}' is duplicated.",
                        row=row + 1,
                        term=term,
                    )
                )
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
            prefix_raw = resolve_feature_label(
                self._user_mode,
                "glossary.editor.validation.prefix",
                "Please correct:",
            )
            errors_text = "\n- ".join(errors[:24])
            prefix = str(prefix_raw or "").replace("\r\n", "\n").rstrip()
            if "{errors}" in prefix:
                message = self._format_profile_text(
                    prefix,
                    fallback=f"{prefix}\n- {errors_text}",
                    errors=errors_text,
                )
            elif prefix.endswith("\n-") or prefix.endswith("-"):
                message = f"{prefix} {errors_text}"
            elif prefix:
                message = f"{prefix}\n- {errors_text}"
            else:
                message = f"- {errors_text}"
            QMessageBox.warning(
                self,
                resolve_feature_label(
                    self._user_mode,
                    "glossary.editor.validation.title",
                    "Glossary",
                ),
                message,
            )
            return
        count = self._store.replace_glossary_entries(
            entries=entries,
            panel_scope="*",
            apply_all_tabs=True,
        )
        self._set_summary(count)
        self.glossary_saved.emit(int(count))

    def set_user_mode(self, mode: str) -> None:
        self._user_mode = normalize_user_mode(mode)
        self.setWindowTitle(
            resolve_feature_label(
                self._user_mode,
                "glossary.editor.window_title",
                "Glossary Manager",
            )
        )
        if self._add_btn is not None:
            self._add_btn.setText(
                resolve_feature_label(
                    self._user_mode,
                    "glossary.editor.button.add_row",
                    "Add row",
                )
            )
        if self._delete_btn is not None:
            self._delete_btn.setText(
                resolve_feature_label(
                    self._user_mode,
                    "glossary.editor.button.delete_selected",
                    "Delete selected rows",
                )
            )
        if self._reload_btn is not None:
            self._reload_btn.setText(
                resolve_feature_label(
                    self._user_mode,
                    "glossary.editor.button.reload",
                    "Reload",
                )
            )
        if self._save_btn is not None:
            self._save_btn.setText(
                resolve_feature_label(
                    self._user_mode,
                    "glossary.editor.button.save",
                    "Save",
                )
            )
        if self._close_btn is not None:
            self._close_btn.setText(
                resolve_feature_label(
                    self._user_mode,
                    "glossary.editor.button.close",
                    "Close",
                )
            )

        term_text = resolve_feature_label(
            self._user_mode,
            "glossary.editor.column.term",
            "Term",
        )
        definition_text = resolve_feature_label(
            self._user_mode,
            "glossary.editor.column.definition",
            "Definition (hover text)",
        )
        self._table.setHorizontalHeaderLabels([term_text, definition_text])

        term_tooltip = resolve_feature_label(
            self._user_mode,
            "glossary.editor.column.term.tooltip",
            "Glossary term used for highlighting.",
        )
        definition_tooltip = resolve_feature_label(
            self._user_mode,
            "glossary.editor.column.definition.tooltip",
            "Shown as hover text on highlighted term matches.",
        )
        term_item = self._table.horizontalHeaderItem(0)
        if term_item is not None:
            term_item.setToolTip(term_tooltip)
        definition_item = self._table.horizontalHeaderItem(1)
        if definition_item is not None:
            definition_item.setToolTip(definition_tooltip)
        self._set_summary(self._table.rowCount())
