"""Comparison tab view for Test Studio."""
from __future__ import annotations

from PySide6.QtWidgets import QLabel, QTableWidget, QVBoxLayout, QWidget

from test_studio.components.metrics import failure_rate, set_numeric_item, set_text_item
from test_studio.models import RunEntry
from test_studio.view.table_headers import configure_comparison_table


class ComparisonTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)

        hint = QLabel(
            "Wähle links Runs aus. Ohne Auswahl zeigt die Tabelle die ersten sichtbaren Runs."
        )
        hint.setStyleSheet("color: #7F849C;")
        layout.addWidget(hint)

        self.table = QTableWidget(0, 11)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSortingEnabled(True)
        configure_comparison_table(self.table, "mixed")
        layout.addWidget(self.table, 1)

    def refresh(self, runs_scope: list[RunEntry], mode: str) -> None:
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        configure_comparison_table(self.table, mode)

        for row_idx, run in enumerate(runs_scope[:20]):
            self.table.insertRow(row_idx)
            set_text_item(self.table, row_idx, 0, run.run_type.upper())
            set_text_item(self.table, row_idx, 1, run.run_name)
            set_text_item(self.table, row_idx, 2, str(run.cases_count))
            self._render_metrics_row(row_idx, run, mode)

        self.table.setSortingEnabled(True)

    def _render_metrics_row(self, row_idx: int, run: RunEntry, mode: str) -> None:
        if mode == "rag":
            values = [run.macro_f1, run.micro_f1, run.hit_at_k, run.map_value, run.mrr, run.ndcg]
        elif mode == "judge":
            values = [run.macro_f1, run.hit_at_k, run.map_value, run.mrr, run.ndcg, run.micro_f1]
        elif mode == "llmcompare":
            values = [run.macro_f1, run.micro_f1, run.hit_at_k, run.map_value, run.mrr, run.ndcg]
        elif mode == "factcheck":
            values = [run.macro_f1, run.micro_f1, run.hit_at_k, run.map_value, run.mrr, run.ndcg]
        elif mode == "pdf":
            values = [run.macro_f1, run.hit_at_k, run.map_value, run.mrr, run.ndcg, run.micro_f1]
        elif mode == "glossary":
            values = [run.hit_at_k, run.map_value, run.macro_f1, run.mrr, run.ndcg, run.micro_f1]
        else:
            values = [run.macro_f1, run.hit_at_k, run.map_value, run.micro_f1, run.mrr, run.ndcg]

        for index, value in enumerate(values, start=3):
            set_numeric_item(self.table, row_idx, index, value, heatmap=True)
        set_numeric_item(self.table, row_idx, 9, failure_rate(run), heatmap=True)
        set_text_item(self.table, row_idx, 10, run.suite)
