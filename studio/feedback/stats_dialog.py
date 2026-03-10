"""Feedback statistics dialog."""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

_DIALOG_STYLE = """
QDialog {
    background: #1E1E2E;
    color: #CDD6F4;
}
QLabel { color: #CDD6F4; font-size: 11px; }
QTableWidget {
    background: #181825;
    color: #CDD6F4;
    border: 1px solid #45475A;
    gridline-color: #313244;
    font-size: 11px;
}
QTableWidget::item { padding: 4px 8px; }
QTableWidget::item:selected { background: #313244; }
QHeaderView::section {
    background: #313244;
    color: #CBA6F7;
    border: none;
    border-right: 1px solid #45475A;
    padding: 4px 8px;
    font-size: 11px;
}
QPushButton {
    background: #313244;
    color: #CDD6F4;
    border: 1px solid #45475A;
    border-radius: 4px;
    padding: 4px 12px;
    font-size: 11px;
}
QPushButton:hover { background: #45475A; }
"""


class FeedbackStatsDialog(QDialog):
    """Simple statistics window showing feedback event counts."""

    def __init__(self, feedback_service: Any, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Feedback Statistik")
        self.resize(560, 400)
        self.setStyleSheet(_DIALOG_STYLE)
        self._service = feedback_service
        self._setup_ui()
        self._load_data()

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        self._summary_lbl = QLabel("")
        self._summary_lbl.setWordWrap(True)
        root.addWidget(self._summary_lbl)

        self._table = QTableWidget()
        self._table.setColumnCount(4)
        self._table.setHorizontalHeaderLabels(
            ["Funktion", "Events", "Positiv", "Negativ"]
        )
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.setAlternatingRowColors(False)
        self._table.verticalHeader().setVisible(False)
        root.addWidget(self._table, 1)

        btn_row = QHBoxLayout()
        refresh_btn = QPushButton("Aktualisieren")
        refresh_btn.clicked.connect(self._load_data)
        btn_row.addWidget(refresh_btn)
        btn_row.addStretch()

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        btn_row.addWidget(buttons)
        root.addLayout(btn_row)

    def _load_data(self):
        try:
            counters = self._service.get_counters()
        except Exception:
            counters = {}

        total = counters.get("total", {}) or {}
        total_events = int(total.get("events", 0) or 0)
        total_pos = int(total.get("positive", 0) or 0)
        total_neg = int(total.get("negative", 0) or 0)

        if total_events > 0:
            pct_pos = round(100 * total_pos / total_events)
            pct_neg = round(100 * total_neg / total_events)
            summary = (
                f"Gesamt: {total_events} Events  |  "
                f"Positiv: {total_pos} ({pct_pos}%)  |  "
                f"Negativ: {total_neg} ({pct_neg}%)"
            )
        else:
            summary = "Noch kein Feedback erfasst."
        self._summary_lbl.setText(summary)

        by_use_case = counters.get("by_use_case", {}) or {}
        rows = sorted(by_use_case.items(), key=lambda kv: -int((kv[1] or {}).get("events", 0)))

        self._table.setRowCount(len(rows))
        for row_idx, (use_case, row_data) in enumerate(rows):
            row_data = row_data or {}
            events = int(row_data.get("events", 0) or 0)
            pos = int(row_data.get("positive", 0) or 0)
            neg = int(row_data.get("negative", 0) or 0)

            self._table.setItem(row_idx, 0, self._cell(str(use_case)))
            self._table.setItem(row_idx, 1, self._cell(str(events), align_right=True))
            pos_item = self._cell(str(pos), align_right=True)
            pos_item.setForeground(Qt.GlobalColor.green)
            self._table.setItem(row_idx, 2, pos_item)
            neg_item = self._cell(str(neg), align_right=True)
            neg_item.setForeground(Qt.GlobalColor.red)
            self._table.setItem(row_idx, 3, neg_item)

        self._table.resizeColumnsToContents()

    @staticmethod
    def _cell(text: str, align_right: bool = False) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        if align_right:
            item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        return item
