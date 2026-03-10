"""Case editor dialog for Testcase Studio."""
from __future__ import annotations

import json
from typing import Any

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from testcase_studio.case_fields import (
    format_field_value,
    is_empty_value,
    parse_field_text,
)
from testcase_studio.models import FieldGuide
from testcase_studio.suite_schema import FIELD_GUIDES, SUITE_BY_ID, SUITE_SPECS
from testcase_studio.text_utils import coerce_labels, safe_str
from testcase_studio.ui_style import MUTED, STYLE, YELLOW


class CaseDraftDialog(QDialog):
    def __init__(
        self,
        *,
        suite_id: str,
        payload: dict[str, Any],
        accepted_default: bool,
        title: str,
        existing_labels: list[str] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(920, 680)
        self.setStyleSheet(STYLE)

        self._sync_lock = False
        self._field_editors: dict[str, QPlainTextEdit] = {}
        self._field_guides: dict[str, FieldGuide] = {}
        self._existing_labels = sorted(coerce_labels(existing_labels or []), key=str.casefold)

        root = QVBoxLayout(self)
        form = QFormLayout()

        self._suite_combo = QComboBox()
        for spec in SUITE_SPECS:
            self._suite_combo.addItem(spec.label, spec.suite_id)
        index = self._suite_combo.findData(suite_id)
        if index >= 0:
            self._suite_combo.setCurrentIndex(index)
        form.addRow("Ziel-Testtyp:", self._suite_combo)

        self._accepted_cb = QCheckBox("Akzeptiert (wird exportiert)")
        self._accepted_cb.setChecked(bool(accepted_default))
        form.addRow("Status:", self._accepted_cb)

        self._hint_lbl = QLabel("")
        self._hint_lbl.setStyleSheet(f"color: {MUTED};")
        self._hint_lbl.setWordWrap(True)
        form.addRow("Hinweis:", self._hint_lbl)

        self._required_lbl = QLabel("")
        self._required_lbl.setStyleSheet(f"color: {YELLOW};")
        self._required_lbl.setWordWrap(True)
        form.addRow("Pflichtfelder:", self._required_lbl)
        root.addLayout(form)

        root.addWidget(self._build_labels_box())

        req_box = QGroupBox("Felder direkt bearbeiten (Text -> JSON)")
        self._required_form = QFormLayout(req_box)
        self._required_form.setSpacing(6)
        root.addWidget(req_box)

        self._json_edit = QPlainTextEdit(json.dumps(payload, ensure_ascii=False, indent=2))
        self._json_edit.setStyleSheet(
            "font-family: monospace; font-size: 11px;"
        )
        root.addWidget(self._json_edit, 1)

        actions = QHBoxLayout()
        ok_btn = QPushButton("Uebernehmen")
        ok_btn.setObjectName("success")
        ok_btn.clicked.connect(self._accept)
        cancel_btn = QPushButton("Abbrechen")
        cancel_btn.clicked.connect(self.reject)
        actions.addWidget(ok_btn)
        actions.addWidget(cancel_btn)
        actions.addStretch()
        root.addLayout(actions)

        self._suite_combo.currentIndexChanged.connect(self._on_suite_changed)
        self._json_edit.textChanged.connect(self._sync_required_from_json)
        self._on_suite_changed()

    def _build_labels_box(self) -> QGroupBox:
        box = QGroupBox("Labels")
        form = QFormLayout(box)

        selector = QWidget()
        row = QHBoxLayout(selector)
        row.setContentsMargins(0, 0, 0, 0)
        self._label_existing_combo = QComboBox()
        self._label_existing_combo.addItem("(bestehendes Label waehlen)", "")
        for label in self._existing_labels:
            self._label_existing_combo.addItem(label, label)
        add_btn = QPushButton("Hinzufuegen")
        add_btn.clicked.connect(self._add_label_from_picker)
        row.addWidget(self._label_existing_combo, 1)
        row.addWidget(add_btn)
        form.addRow("Bisherige Labels:", selector)

        new_selector = QWidget()
        new_row = QHBoxLayout(new_selector)
        new_row.setContentsMargins(0, 0, 0, 0)
        self._label_new_toggle = QCheckBox("Neues Label")
        self._label_new_toggle.toggled.connect(self._on_label_mode_toggled)
        self._label_new_edit = QLineEdit()
        self._label_new_edit.setEnabled(False)
        self._label_new_edit.setPlaceholderText("z.B. regression")
        self._label_new_edit.returnPressed.connect(self._add_new_label)
        self._label_new_add_btn = QPushButton("Neu hinzufuegen")
        self._label_new_add_btn.setEnabled(False)
        self._label_new_add_btn.clicked.connect(self._add_new_label)
        new_row.addWidget(self._label_new_toggle)
        new_row.addWidget(self._label_new_edit, 1)
        new_row.addWidget(self._label_new_add_btn)
        form.addRow("Neues Label:", new_selector)

        selected = QWidget()
        selected_layout = QVBoxLayout(selected)
        selected_layout.setContentsMargins(0, 0, 0, 0)
        self._labels_list = QListWidget()
        self._labels_list.setMaximumHeight(90)
        self._labels_list.itemDoubleClicked.connect(lambda _: self._remove_selected_label())
        remove_btn = QPushButton("Entfernen")
        remove_btn.clicked.connect(self._remove_selected_label)
        selected_layout.addWidget(self._labels_list)
        selected_layout.addWidget(remove_btn)
        form.addRow("Ausgewaehlt:", selected)
        return box

    def _refresh_hints(self) -> None:
        suite_id = self.suite_id()
        spec = SUITE_BY_ID.get(suite_id)
        if spec is None:
            self._hint_lbl.setText("")
            self._required_lbl.setText("")
            return
        self._hint_lbl.setText(spec.description)
        self._required_lbl.setText(", ".join(spec.required_fields) if spec.required_fields else "-")

    def _on_suite_changed(self) -> None:
        self._refresh_hints()
        self._rebuild_required_inputs()
        self._sync_required_from_json()

    def _on_label_mode_toggled(self, enabled: bool) -> None:
        self._label_new_edit.setEnabled(enabled)
        self._label_new_add_btn.setEnabled(enabled)

    def _labels_from_widget(self) -> list[str]:
        labels: list[str] = []
        for idx in range(self._labels_list.count()):
            text = safe_str(self._labels_list.item(idx).text())
            if text:
                labels.append(text)
        return coerce_labels(labels)

    def _set_labels_widget(self, labels: list[str]) -> None:
        self._labels_list.clear()
        for label in coerce_labels(labels):
            self._labels_list.addItem(label)

    def _add_label_token(self, token: str) -> None:
        label = safe_str(token)
        if not label:
            return
        current = self._labels_from_widget()
        if label.casefold() in {item.casefold() for item in current}:
            return
        current.append(label)
        self._set_labels_widget(current)
        self._sync_json_from_required()

    def _add_label_from_picker(self) -> None:
        self._add_label_token(safe_str(self._label_existing_combo.currentData()))

    def _add_new_label(self) -> None:
        if not self._label_new_toggle.isChecked():
            return
        label = safe_str(self._label_new_edit.text())
        if not label:
            return
        self._add_label_token(label)
        if label.casefold() not in {item.casefold() for item in self._existing_labels}:
            self._existing_labels.append(label)
            self._existing_labels.sort(key=str.casefold)
            self._label_existing_combo.blockSignals(True)
            self._label_existing_combo.clear()
            self._label_existing_combo.addItem("(bestehendes Label waehlen)", "")
            for item in self._existing_labels:
                self._label_existing_combo.addItem(item, item)
            self._label_existing_combo.blockSignals(False)
        self._label_new_edit.clear()

    def _remove_selected_label(self) -> None:
        row = self._labels_list.currentRow()
        if row >= 0:
            self._labels_list.takeItem(row)
            self._sync_json_from_required()

    def _read_json_obj(self) -> dict[str, Any]:
        try:
            parsed = json.loads(self._json_edit.toPlainText().strip() or "{}")
        except Exception:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def _write_json_obj(self, payload: dict[str, Any]) -> None:
        if self._sync_lock:
            return
        self._sync_lock = True
        self._json_edit.setPlainText(json.dumps(payload, ensure_ascii=False, indent=2))
        self._sync_lock = False

    def _rebuild_required_inputs(self) -> None:
        while self._required_form.rowCount() > 0:
            self._required_form.removeRow(0)
        self._field_editors.clear()
        self._field_guides.clear()

        suite_id = self.suite_id()
        guides = FIELD_GUIDES.get(suite_id, [])
        spec = SUITE_BY_ID.get(suite_id)
        if not guides and spec:
            guides = [FieldGuide(key, key, True, "Pflichtfeld", "") for key in spec.required_fields]

        for guide in guides:
            if guide.key == "labels":
                continue
            edit = QPlainTextEdit()
            edit.setMaximumHeight(int(max(52, guide.max_height)))
            edit.setPlaceholderText(guide.example)
            tooltip = guide.help_text + (f"\n\nBeispiel:\n{guide.example}" if guide.example else "")
            edit.setToolTip(tooltip)
            edit.textChanged.connect(self._sync_json_from_required)
            marker = " *" if guide.required else ""
            label = QLabel(f"{guide.label}{marker}:")
            label.setToolTip(tooltip)
            self._required_form.addRow(label, edit)
            self._field_editors[guide.key] = edit
            self._field_guides[guide.key] = guide

    def _sync_required_from_json(self) -> None:
        if self._sync_lock:
            return
        payload = self._read_json_obj()
        self._sync_lock = True
        self._set_labels_widget(coerce_labels(payload.get("labels")))
        for key, edit in self._field_editors.items():
            edit.setPlainText(format_field_value(key, payload.get(key)))
        self._sync_lock = False

    def _sync_json_from_required(self) -> None:
        if self._sync_lock:
            return
        payload = self._read_json_obj()
        labels = self._labels_from_widget()
        if labels:
            payload["labels"] = labels
        else:
            payload.pop("labels", None)

        for key, edit in self._field_editors.items():
            value = parse_field_text(key, edit.toPlainText())
            guide = self._field_guides.get(key)
            if is_empty_value(value):
                if guide and not guide.required:
                    payload.pop(key, None)
                else:
                    payload[key] = value
            else:
                payload[key] = value
        self._write_json_obj(payload)

    def _accept(self) -> None:
        try:
            parsed = json.loads(self._json_edit.toPlainText().strip() or "{}")
        except Exception as exc:
            QMessageBox.warning(self, "Ungueltiges JSON", f"JSON konnte nicht geparst werden:\n{exc}")
            return
        if not isinstance(parsed, dict):
            QMessageBox.warning(self, "Ungueltiges JSON", "Testcase muss ein JSON-Objekt sein.")
            return

        spec = SUITE_BY_ID.get(self.suite_id())
        if spec:
            missing: list[str] = []
            for key in spec.required_fields:
                value = parsed.get(key)
                if value is None or (isinstance(value, str) and not value.strip()) or (isinstance(value, list) and not value):
                    missing.append(key)
            if missing:
                answer = QMessageBox.question(
                    self,
                    "Pflichtfelder fehlen",
                    "Folgende Pflichtfelder wirken leer/fehlend:\n"
                    + ", ".join(missing)
                    + "\n\nTrotzdem uebernehmen?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    return
        self.accept()

    def suite_id(self) -> str:
        return str(self._suite_combo.currentData() or "")

    def accepted(self) -> bool:
        return bool(self._accepted_cb.isChecked())

    def payload(self) -> dict[str, Any]:
        try:
            parsed = json.loads(self._json_edit.toPlainText().strip() or "{}")
        except Exception:
            return {}
        return parsed if isinstance(parsed, dict) else {}
