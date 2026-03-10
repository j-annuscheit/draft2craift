"""Run table widget and rendering for Test Studio."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTableWidget

from test_studio.components.metrics import failure_rate, set_numeric_item, set_text_item
from test_studio.models import RunEntry
from test_studio.view.table_headers import configure_run_table


class RunTableView:
    def __init__(self, table: QTableWidget) -> None:
        self.table = table
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSortingEnabled(True)
        configure_run_table(self.table, "mixed")

    def render(self, runs: list[RunEntry], mode: str) -> None:
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        configure_run_table(self.table, mode)

        for row_idx, run in enumerate(runs):
            self.table.insertRow(row_idx)
            set_text_item(self.table, row_idx, 0, run.run_type.upper())
            run_item = set_text_item(self.table, row_idx, 1, run.run_name)
            run_item.setData(Qt.ItemDataRole.UserRole, str(run.path))

            set_text_item(self.table, row_idx, 2, run.timestamp)
            set_text_item(self.table, row_idx, 3, str(run.cases_count))
            self._render_metrics_row(row_idx, run, mode)

        self.table.setSortingEnabled(True)

    def selected_paths(self) -> list[str]:
        model = self.table.selectionModel()
        if model is None:
            return []

        paths: list[str] = []
        seen: set[str] = set()
        for idx in model.selectedRows(1):
            item = self.table.item(idx.row(), 1)
            if item is None:
                continue
            path = str(item.data(Qt.ItemDataRole.UserRole) or "")
            if not path or path in seen:
                continue
            seen.add(path)
            paths.append(path)
        return paths

    def _render_metrics_row(self, row_idx: int, run: RunEntry, mode: str) -> None:
        if mode == "llmcompare":
            set_numeric_item(self.table, row_idx, 4, run.macro_f1, heatmap=True)
            set_numeric_item(self.table, row_idx, 5, run.micro_f1, heatmap=True)
            set_numeric_item(self.table, row_idx, 6, run.hit_at_k, heatmap=True)
        elif mode == "judge":
            set_numeric_item(self.table, row_idx, 4, run.macro_f1, heatmap=True)
            set_numeric_item(self.table, row_idx, 5, run.hit_at_k, heatmap=True)
            set_numeric_item(self.table, row_idx, 6, run.map_value, heatmap=True)
        elif mode == "factcheck":
            set_numeric_item(self.table, row_idx, 4, run.macro_f1, heatmap=True)
            set_numeric_item(self.table, row_idx, 5, run.hit_at_k, heatmap=True)
            set_numeric_item(self.table, row_idx, 6, run.map_value, heatmap=True)
        elif mode == "glossary":
            set_numeric_item(self.table, row_idx, 4, run.hit_at_k, heatmap=True)
            set_numeric_item(self.table, row_idx, 5, run.map_value, heatmap=True)
            set_numeric_item(self.table, row_idx, 6, run.macro_f1, heatmap=True)
        else:
            set_numeric_item(self.table, row_idx, 4, run.macro_f1, heatmap=True)
            set_numeric_item(self.table, row_idx, 5, run.hit_at_k, heatmap=True)
            set_numeric_item(self.table, row_idx, 6, run.map_value, heatmap=True)

        set_numeric_item(self.table, row_idx, 7, failure_rate(run), heatmap=True)
        set_text_item(self.table, row_idx, 8, run.suite)
        set_text_item(self.table, row_idx, 9, str(run.path))
