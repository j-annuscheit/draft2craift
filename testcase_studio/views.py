"""Qt view classes for Testcase Studio tabs."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from testcase_studio.suite_schema import SUITE_SPECS
from testcase_studio.ui_style import BLUE, MUTED, OVERLAY, SURFACE, TEXT


class FeedbackTabView(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        filters = QHBoxLayout()
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Filter: event_id, use_case, note, prompt...")
        self.sent_combo = QComboBox()
        self.sent_combo.addItem("Alle", "all")
        self.sent_combo.addItem("Negativ", "negative")
        self.sent_combo.addItem("Positiv", "positive")
        filters.addWidget(self.filter_edit, 1)
        filters.addWidget(self.sent_combo)
        layout.addLayout(filters)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Zeit", "Event-ID", "Use-Case", "Sent", "Linked", "Notiz"])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        splitter.addWidget(self.table)

        detail = QWidget()
        right = QVBoxLayout(detail)
        right.setContentsMargins(8, 8, 8, 8)

        self.meta_lbl = QLabel("Kein Feedback ausgewaehlt")
        self.meta_lbl.setStyleSheet(f"color: {BLUE}; font-weight: bold;")
        right.addWidget(self.meta_lbl)

        self.prompt_lbl = QLabel("")
        self.prompt_lbl.setWordWrap(True)
        right.addWidget(self.prompt_lbl)

        self.observed_lbl = QLabel("")
        self.observed_lbl.setWordWrap(True)
        self.observed_lbl.setStyleSheet(f"color: {MUTED};")
        right.addWidget(self.observed_lbl)

        fields_box = QGroupBox("Wichtige Felder")
        fields_layout = QVBoxLayout(fields_box)
        self.fields_edit = QPlainTextEdit()
        self.fields_edit.setReadOnly(True)
        self.fields_edit.setMaximumHeight(170)
        self.fields_edit.setStyleSheet(
            f"background: {SURFACE}; color: {TEXT}; border: 1px solid {OVERLAY}; font-size: 10px;"
        )
        fields_layout.addWidget(self.fields_edit)
        right.addWidget(fields_box)

        convert_box = QGroupBox("In Testcase umwandeln")
        convert_form = QFormLayout(convert_box)
        self.target_suite_combo = QComboBox()
        for spec in SUITE_SPECS:
            self.target_suite_combo.addItem(spec.label, spec.suite_id)
        self.hint_lbl = QLabel("")
        self.hint_lbl.setWordWrap(True)
        self.hint_lbl.setStyleSheet(f"color: {MUTED};")
        self.create_btn = QPushButton("Entwurf erzeugen")
        self.create_btn.setObjectName("primary")
        convert_form.addRow("Testtyp:", self.target_suite_combo)
        convert_form.addRow("Hinweis:", self.hint_lbl)
        convert_form.addRow("", self.create_btn)
        right.addWidget(convert_box)

        linked_box = QGroupBox("Verknuepfte Testcases")
        linked_layout = QVBoxLayout(linked_box)
        self.linked_cases_edit = QPlainTextEdit()
        self.linked_cases_edit.setReadOnly(True)
        self.linked_cases_edit.setMaximumHeight(90)
        self.linked_cases_edit.setStyleSheet(
            f"background: {SURFACE}; color: {MUTED}; border: 1px solid {OVERLAY};"
        )
        linked_layout.addWidget(self.linked_cases_edit)
        right.addWidget(linked_box)

        payload_box = QGroupBox("Payload JSON")
        payload_layout = QVBoxLayout(payload_box)
        self.payload_edit = QPlainTextEdit()
        self.payload_edit.setReadOnly(True)
        self.payload_edit.setStyleSheet(
            f"background: {SURFACE}; color: {TEXT}; border: 1px solid {OVERLAY}; "
            "font-family: monospace; font-size: 10px;"
        )
        payload_layout.addWidget(self.payload_edit)
        right.addWidget(payload_box, 1)

        self.delete_btn = QPushButton("Feedback loeschen")
        self.delete_btn.setObjectName("danger")
        row = QHBoxLayout()
        row.addWidget(self.delete_btn)
        row.addStretch()
        right.addLayout(row)

        splitter.addWidget(detail)
        splitter.setSizes([720, 620])
        layout.addWidget(splitter, 1)


class CasesTabView(QWidget):
    def __init__(self, storage_dir_text: str) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        filters = QHBoxLayout()
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Filter: case_id, event_id, title...")
        self.suite_combo = QComboBox()
        self.suite_combo.addItem("Alle", "all")
        for spec in SUITE_SPECS:
            self.suite_combo.addItem(spec.label, spec.suite_id)
        self.status_combo = QComboBox()
        self.status_combo.addItem("Alle", "all")
        self.status_combo.addItem("Akzeptiert", "accepted")
        self.status_combo.addItem("Entwurf", "draft")
        filters.addWidget(self.filter_edit, 1)
        filters.addWidget(self.suite_combo)
        filters.addWidget(self.status_combo)
        layout.addLayout(filters)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(["Nr", "Case-ID", "Suite", "Status", "Event", "Updated", "Title", ""])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        splitter.addWidget(self.table)

        detail = QWidget()
        right = QVBoxLayout(detail)
        right.setContentsMargins(8, 8, 8, 8)

        self.meta_lbl = QLabel("Kein Testcase ausgewaehlt")
        self.meta_lbl.setStyleSheet(f"color: {BLUE}; font-weight: bold;")
        right.addWidget(self.meta_lbl)

        self.json_preview = QPlainTextEdit()
        self.json_preview.setReadOnly(True)
        self.json_preview.setStyleSheet(
            f"background: {SURFACE}; color: {TEXT}; border: 1px solid {OVERLAY}; "
            "font-family: monospace; font-size: 10px;"
        )
        right.addWidget(self.json_preview, 1)

        actions = QHBoxLayout()
        self.new_suite_combo = QComboBox()
        for spec in SUITE_SPECS:
            self.new_suite_combo.addItem(spec.label, spec.suite_id)
        self.new_btn = QPushButton("Neuer manueller Testcase")
        self.edit_btn = QPushButton("Bearbeiten")
        self.edit_btn.setObjectName("success")
        self.delete_btn = QPushButton("Loeschen")
        self.delete_btn.setObjectName("danger")
        actions.addWidget(self.new_suite_combo)
        actions.addWidget(self.new_btn)
        actions.addWidget(self.edit_btn)
        actions.addWidget(self.delete_btn)
        right.addLayout(actions)

        export_box = QGroupBox("Suite-Export fuer Test Studio")
        export_form = QFormLayout(export_box)
        self.export_output_edit = QLineEdit(storage_dir_text)
        output_row = QHBoxLayout()
        output_row.addWidget(self.export_output_edit, 1)
        self.export_pick_btn = QPushButton("...")
        self.export_pick_btn.setFixedWidth(30)
        output_row.addWidget(self.export_pick_btn)
        output_wrap = QWidget()
        output_wrap.setLayout(output_row)
        export_form.addRow("Output:", output_wrap)
        self.export_run_name_edit = QLineEdit()
        self.export_run_name_edit.setPlaceholderText("leer = testcase_YYYYMMDD_HHMMSS")
        export_form.addRow("Run-Name:", self.export_run_name_edit)
        self.export_include_drafts_cb = QCheckBox("Entwuerfe auch exportieren")
        export_form.addRow("Modus:", self.export_include_drafts_cb)
        self.export_btn = QPushButton("Suites schreiben")
        self.export_btn.setObjectName("primary")
        export_form.addRow("", self.export_btn)
        right.addWidget(export_box)

        self.export_log = QPlainTextEdit()
        self.export_log.setReadOnly(True)
        self.export_log.setMaximumHeight(130)
        self.export_log.setStyleSheet(
            f"background: {SURFACE}; color: {MUTED}; border: 1px solid {OVERLAY}; "
            "font-family: monospace; font-size: 10px;"
        )
        right.addWidget(self.export_log)

        splitter.addWidget(detail)
        splitter.setSizes([760, 580])
        layout.addWidget(splitter, 1)
