"""Dialog for editing project-level custom variables."""
from __future__ import annotations

from collections.abc import Mapping

from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from shared.domain.user_mode import (
    default_user_mode,
    is_feature_visible,
    normalize_user_mode,
    resolve_feature_label,
)
from shared.services.project.project_variables import (
    canonical_project_variable_key,
    normalize_project_variables,
)


class ProjectVariablesDialog(QDialog):
    """Manage project variable key/value pairs used across prompts and exports."""

    def __init__(
        self,
        *,
        variables: Mapping[str, object] | None = None,
        user_mode: str | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._user_mode = normalize_user_mode(
            default_user_mode() if user_mode is None else user_mode
        )
        self._accepted_variables = normalize_project_variables(variables or {})

        self._intro: QLabel | None = None
        self._syntax: QLabel | None = None
        self._table: QTableWidget | None = None
        self._add_btn: QPushButton | None = None
        self._remove_btn: QPushButton | None = None
        self._buttons: QDialogButtonBox | None = None

        self.resize(760, 420)
        self._build_ui()
        self._load_variables(self._accepted_variables)
        self._apply_user_mode_labels()

    def set_user_mode(self, mode: str) -> None:
        self._user_mode = normalize_user_mode(mode)
        self._apply_user_mode_labels()

    def variables(self) -> dict[str, str]:
        if self.result() == QDialog.DialogCode.Accepted:
            return dict(self._accepted_variables)
        return dict(self._collect_variables(strict=False))

    def accept(self) -> None:
        values = self._collect_variables(strict=True)
        if values is None:
            return
        self._accepted_variables = values
        super().accept()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        intro = QLabel("")
        intro.setWordWrap(True)
        self._intro = intro
        root.addWidget(intro)

        syntax = QLabel("")
        syntax.setWordWrap(True)
        syntax.setStyleSheet("color: palette(placeholder-text); font-size: 11px;")
        self._syntax = syntax
        root.addWidget(syntax)

        table = QTableWidget(0, 2, self)
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        table.verticalHeader().setVisible(False)
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._table = table
        root.addWidget(table, 1)

        row_buttons = QWidget(self)
        row_layout = QHBoxLayout(row_buttons)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(6)
        add_btn = QPushButton("", row_buttons)
        add_btn.clicked.connect(self._add_empty_row)
        self._add_btn = add_btn
        row_layout.addWidget(add_btn)
        remove_btn = QPushButton("", row_buttons)
        remove_btn.clicked.connect(self._remove_selected_rows)
        self._remove_btn = remove_btn
        row_layout.addWidget(remove_btn)
        row_layout.addStretch(1)
        root.addWidget(row_buttons)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self._buttons = buttons
        root.addWidget(buttons)

    def _load_variables(self, variables: Mapping[str, str]) -> None:
        table = self._table
        if table is None:
            return
        table.setRowCount(0)
        for key, value in variables.items():
            self._append_row(str(key or ""), str(value or ""))
        if table.rowCount() == 0:
            self._add_empty_row()

    def _append_row(self, key: str, value: str) -> None:
        table = self._table
        if table is None:
            return
        row = table.rowCount()
        table.insertRow(row)
        table.setItem(row, 0, QTableWidgetItem(str(key or "")))
        table.setItem(row, 1, QTableWidgetItem(str(value or "")))

    def _add_empty_row(self) -> None:
        table = self._table
        if table is None:
            return
        base = self._label("project.variables.default_key", "variable_name")
        taken = {
            str(
                table.item(row, 0).text()
                if table.item(row, 0) is not None
                else ""
            ).strip()
            for row in range(table.rowCount())
        }
        key = str(base or "variable_name").strip() or "variable_name"
        if key in taken:
            idx = 2
            while f"{key}_{idx}" in taken:
                idx += 1
            key = f"{key}_{idx}"
        self._append_row(key, "")
        last_row = table.rowCount() - 1
        table.setCurrentCell(last_row, 0)
        table.editItem(table.item(last_row, 0))

    def _remove_selected_rows(self) -> None:
        table = self._table
        if table is None:
            return
        rows = sorted({index.row() for index in table.selectedIndexes()}, reverse=True)
        for row in rows:
            table.removeRow(row)
        if table.rowCount() == 0:
            self._add_empty_row()

    def _collect_variables(self, *, strict: bool) -> dict[str, str] | None:
        table = self._table
        if table is None:
            return {}
        out: dict[str, str] = {}
        seen_canonical: dict[str, str] = {}

        for row in range(table.rowCount()):
            key_item = table.item(row, 0)
            value_item = table.item(row, 1)
            key = str(key_item.text() if key_item is not None else "").strip()
            value = str(value_item.text() if value_item is not None else "")

            if not key and not value.strip():
                continue
            if not key:
                if strict:
                    self._warn(
                        self._label(
                            "project.variables.validation.empty_key.title",
                            "Invalid Project Variable",
                        ),
                        self._label(
                            "project.variables.validation.empty_key.message",
                            "Each variable row needs a non-empty key.",
                        ),
                    )
                    return None
                continue

            canonical = canonical_project_variable_key(key)
            if strict and not canonical:
                self._warn(
                    self._label(
                        "project.variables.validation.invalid_key.title",
                        "Invalid Project Variable",
                    ),
                    self._label(
                        "project.variables.validation.invalid_key.message",
                        "A variable key must contain at least one letter or digit.",
                    ),
                )
                return None

            existing = seen_canonical.get(canonical)
            if strict and existing is not None and existing != key:
                self._warn(
                    self._label(
                        "project.variables.validation.duplicate_key.title",
                        "Duplicate Project Variable",
                    ),
                    self._label(
                        "project.variables.validation.duplicate_key.message",
                        "Variable keys must be unique (case-insensitive).",
                    ),
                )
                return None
            if canonical:
                seen_canonical[canonical] = key
            out[key] = value

        return out

    def _warn(self, title: str, text: str) -> None:
        QMessageBox.warning(self, str(title or ""), str(text or ""))

    def _label(self, key: str, default: str) -> str:
        return resolve_feature_label(self._user_mode, key, default)

    def _apply_user_mode_labels(self) -> None:
        self.setWindowTitle(
            self._label(
                "project.variables.window_title",
                "Project Variables",
            )
        )
        if self._intro is not None:
            self._intro.setText(
                self._label(
                    "project.variables.intro",
                    "Define reusable key-value pairs for this project. "
                    "You can reference them in prompts, drafts, and exports.",
                )
            )
        if self._syntax is not None:
            self._syntax.setText(
                self._label(
                    "project.variables.syntax",
                    "Placeholder syntax: ${variable_key} "
                    "(also supported: {{ variable_key }}).",
                )
            )
        if self._table is not None:
            self._table.setHorizontalHeaderLabels(
                (
                    self._label("project.variables.table.key", "Variable Key"),
                    self._label("project.variables.table.value", "Value"),
                )
            )
        if self._add_btn is not None:
            self._add_btn.setText(
                self._label("project.variables.button.add", "Add Variable")
            )
            self._add_btn.setVisible(
                bool(
                    is_feature_visible(
                        self._user_mode,
                        "project.variables.button.add",
                        default=True,
                    )
                )
            )
        if self._remove_btn is not None:
            self._remove_btn.setText(
                self._label("project.variables.button.remove", "Remove Selected")
            )
            self._remove_btn.setVisible(
                bool(
                    is_feature_visible(
                        self._user_mode,
                        "project.variables.button.remove",
                        default=True,
                    )
                )
            )
        if self._buttons is not None:
            ok_btn = self._buttons.button(QDialogButtonBox.StandardButton.Ok)
            if ok_btn is not None:
                ok_btn.setText(self._label("project.variables.button.ok", "OK"))
            cancel_btn = self._buttons.button(QDialogButtonBox.StandardButton.Cancel)
            if cancel_btn is not None:
                cancel_btn.setText(
                    self._label("project.variables.button.cancel", "Cancel")
                )


__all__ = ["ProjectVariablesDialog"]
