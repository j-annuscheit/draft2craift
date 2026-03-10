"""Case details tab for Test Studio."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from test_studio.components.metrics import set_numeric_item, set_text_item
from test_studio.models import CaseEntry, RunEntry
from test_studio.view.table_headers import configure_case_table


class CasesTab(QWidget):
    run_changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._runs_by_path: dict[str, RunEntry] = {}

        layout = QVBoxLayout(self)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Run:"))
        self.run_selector = QComboBox()
        controls.addWidget(self.run_selector)

        controls.addWidget(QLabel("Label:"))
        self.label_selector = QComboBox()
        controls.addWidget(self.label_selector)

        self.query_filter = QLineEdit()
        self.query_filter.setPlaceholderText("Filter by case id or query…")
        controls.addWidget(self.query_filter, 1)
        layout.addLayout(controls)

        self.table = QTableWidget(0, 9)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSortingEnabled(True)
        configure_case_table(self.table, "mixed")
        layout.addWidget(self.table, 1)

        self.run_selector.currentIndexChanged.connect(self._on_run_changed)
        self.label_selector.currentIndexChanged.connect(self.refresh_table)
        self.query_filter.textChanged.connect(self.refresh_table)

    def set_runs_scope(self, runs_scope: list[RunEntry], runs_by_path: dict[str, RunEntry]) -> None:
        self._runs_by_path = runs_by_path
        current = self.run_selector.currentData()

        self.run_selector.blockSignals(True)
        self.run_selector.clear()
        for run in runs_scope:
            self.run_selector.addItem(f"[{run.run_type.upper()}] {run.run_name}", str(run.path))

        if current:
            for idx in range(self.run_selector.count()):
                if self.run_selector.itemData(idx) == current:
                    self.run_selector.setCurrentIndex(idx)
                    break
        self.run_selector.blockSignals(False)

        self.refresh_label_selector()
        self.refresh_table()

    def current_run(self) -> RunEntry | None:
        path = str(self.run_selector.currentData() or "")
        return self._runs_by_path.get(path)

    def refresh_label_selector(self) -> None:
        run = self.current_run()
        labels = sorted(
            {label for case in (run.cases if run else []) for label in case.labels},
            key=str.casefold,
        )

        current = self.label_selector.currentData()
        self.label_selector.blockSignals(True)
        self.label_selector.clear()
        self.label_selector.addItem("All labels", "")
        for label in labels:
            self.label_selector.addItem(label, label)

        if current:
            for idx in range(self.label_selector.count()):
                if self.label_selector.itemData(idx) == current:
                    self.label_selector.setCurrentIndex(idx)
                    break
        self.label_selector.blockSignals(False)

    def refresh_table(self) -> None:
        run = self.current_run()
        mode = run.run_type if run else "mixed"

        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        configure_case_table(self.table, mode)

        if run is None:
            self.table.setSortingEnabled(True)
            return

        label_filter = str(self.label_selector.currentData() or "")
        query_filter = self.query_filter.text().strip().casefold()
        cases = [
            case
            for case in run.cases
            if (not label_filter or label_filter in case.labels)
            and (
                not query_filter
                or query_filter in case.case_id.casefold()
                or query_filter in case.query.casefold()
            )
        ]

        for row_idx, case in enumerate(cases):
            self.table.insertRow(row_idx)
            self._render_case_row(row_idx, case)

        self.table.setSortingEnabled(True)

    def _render_case_row(self, row_idx: int, case: CaseEntry) -> None:
        set_text_item(self.table, row_idx, 0, case.case_id)
        set_text_item(self.table, row_idx, 1, ", ".join(case.labels) or "__unlabeled__")
        set_numeric_item(self.table, row_idx, 2, case.f1, heatmap=True)
        set_numeric_item(self.table, row_idx, 3, case.precision, heatmap=True)
        set_numeric_item(self.table, row_idx, 4, case.recall, heatmap=True)
        set_numeric_item(self.table, row_idx, 5, case.hit_at_k, heatmap=True)
        set_text_item(self.table, row_idx, 6, " | ".join(case.expected_docs))
        set_text_item(self.table, row_idx, 7, " | ".join(case.predicted_docs))
        set_text_item(self.table, row_idx, 8, case.query)

    def _on_run_changed(self) -> None:
        self.refresh_label_selector()
        self.refresh_table()
        self.run_changed.emit()
