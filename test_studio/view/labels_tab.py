"""Label analysis tab for Test Studio."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from test_studio.components.metrics import aggregate_labels, set_numeric_item, set_text_item
from test_studio.models import RunEntry
from test_studio.view.table_headers import configure_label_table


class LabelsTab(QWidget):
    def __init__(self) -> None:
        super().__init__()

        layout = QVBoxLayout(self)
        controls = QHBoxLayout()

        self.scope_selector = QComboBox()
        self.scope_selector.addItem("Selected runs", "selected")
        self.scope_selector.addItem("All visible runs", "all")

        self.mode_selector = QComboBox()
        self.mode_selector.addItem("Aggregated labels", "aggregate")
        self.mode_selector.addItem("Run x label", "per_run")

        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Filter labels…")

        controls.addWidget(QLabel("Scope:"))
        controls.addWidget(self.scope_selector)
        controls.addWidget(QLabel("Mode:"))
        controls.addWidget(self.mode_selector)
        controls.addWidget(self.filter_edit, 1)
        layout.addLayout(controls)

        self.table = QTableWidget(0, 9)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSortingEnabled(True)
        configure_label_table(self.table, "mixed")
        layout.addWidget(self.table, 1)

    def connect_refresh(self, callback) -> None:
        self.scope_selector.currentIndexChanged.connect(callback)
        self.mode_selector.currentIndexChanged.connect(callback)
        self.filter_edit.textChanged.connect(callback)

    def refresh(
        self,
        *,
        visible_runs: list[RunEntry],
        selected_runs: list[RunEntry],
        mode: str,
    ) -> None:
        scope = str(self.scope_selector.currentData() or "selected")
        label_mode = str(self.mode_selector.currentData() or "aggregate")
        label_filter = self.filter_edit.text().strip().casefold()

        if scope == "selected":
            runs = selected_runs or visible_runs
        else:
            runs = visible_runs

        configure_label_table(self.table, mode)

        rows: list[tuple[str, object]] = []
        if label_mode == "aggregate":
            all_cases = [case for run in runs for case in run.cases]
            rows = [("(aggregate)", stat) for stat in aggregate_labels(all_cases)]
        else:
            for run in runs:
                rows.extend(
                    (f"[{run.run_type.upper()}] {run.run_name}", stat)
                    for stat in aggregate_labels(run.cases)
                )

        if label_filter:
            rows = [row for row in rows if label_filter in row[1].label.casefold()]

        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)

        for row_idx, (run_name, stat) in enumerate(rows):
            self.table.insertRow(row_idx)
            set_text_item(self.table, row_idx, 0, run_name)
            set_text_item(self.table, row_idx, 1, stat.label)
            set_text_item(self.table, row_idx, 2, str(stat.cases))

            if mode == "glossary":
                metric_values = [stat.macro_recall, stat.macro_precision, stat.macro_f1, stat.macro_hit]
            elif mode == "llmcompare":
                metric_values = [stat.macro_f1, stat.macro_precision, stat.macro_recall, stat.macro_hit]
            elif mode == "factcheck":
                metric_values = [stat.macro_f1, stat.macro_hit, stat.macro_precision, stat.macro_recall]
            else:
                metric_values = [stat.macro_f1, stat.macro_hit, stat.macro_precision, stat.macro_recall]

            for offset, value in enumerate(metric_values, start=3):
                set_numeric_item(self.table, row_idx, offset, value, heatmap=True)

            set_text_item(self.table, row_idx, 7, str(stat.failures))
            set_numeric_item(self.table, row_idx, 8, stat.failure_rate, heatmap=True)

        self.table.setSortingEnabled(True)
