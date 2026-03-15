"""Feedback statistics dialog."""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
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

from shared.domain.user_mode import normalize_user_mode, resolve_feature_label
from studio.theme import theme_tokens

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
QPushButton:hover { border-color: palette(highlight); }
"""


class FeedbackStatsDialog(QDialog):
    """Simple statistics window showing feedback event counts."""

    def __init__(self, feedback_service: Any, user_mode: str | None = None, parent=None):
        super().__init__(parent)
        self._user_mode = normalize_user_mode("" if user_mode is None else user_mode)
        self._refresh_btn: QPushButton | None = None
        self._close_btn: QPushButton | None = None
        self._buttons_box: QDialogButtonBox | None = None
        self.setWindowTitle(
            resolve_feature_label(
                self._user_mode,
                "feedback.stats.window_title",
                "Feedback Statistik",
            )
        )
        self.resize(560, 400)
        self.setStyleSheet(_DIALOG_STYLE)
        self._service = feedback_service
        self._setup_ui()
        self._load_data()

    def set_user_mode(self, mode: str) -> None:
        self._user_mode = normalize_user_mode(mode)
        self._apply_user_mode_labels()
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
            [
                resolve_feature_label(self._user_mode, "feedback.stats.header.feature", "Funktion"),
                resolve_feature_label(self._user_mode, "feedback.stats.header.events", "Events"),
                resolve_feature_label(self._user_mode, "feedback.stats.header.positive", "Positiv"),
                resolve_feature_label(self._user_mode, "feedback.stats.header.negative", "Negativ"),
            ]
        )
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.setAlternatingRowColors(False)
        self._table.verticalHeader().setVisible(False)
        root.addWidget(self._table, 1)

        btn_row = QHBoxLayout()
        refresh_btn = QPushButton(
            resolve_feature_label(
                self._user_mode,
                "feedback.stats.button.refresh",
                "Aktualisieren",
            )
        )
        self._refresh_btn = refresh_btn
        refresh_btn.clicked.connect(self._load_data)
        btn_row.addWidget(refresh_btn)
        btn_row.addStretch()

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self._buttons_box = buttons
        close_btn = buttons.button(QDialogButtonBox.StandardButton.Close)
        self._close_btn = close_btn
        if close_btn is not None:
            close_btn.setText(
                resolve_feature_label(
                    self._user_mode,
                    "feedback.stats.button.close",
                    "Schließen",
                )
            )
        buttons.rejected.connect(self.reject)
        btn_row.addWidget(buttons)
        root.addLayout(btn_row)
        self._apply_user_mode_labels()

    def _load_data(self):
        tokens = theme_tokens()
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
            summary_template = resolve_feature_label(
                self._user_mode,
                "feedback.stats.summary.template",
                "Gesamt: {events} Events  |  Positiv: {positive} ({positive_pct}%)  |  Negativ: {negative} ({negative_pct}%)",
            )
            summary = summary_template.format(
                events=total_events,
                positive=total_pos,
                positive_pct=pct_pos,
                negative=total_neg,
                negative_pct=pct_neg,
            )
        else:
            summary = resolve_feature_label(
                self._user_mode,
                "feedback.stats.summary.empty",
                "Noch kein Feedback erfasst.",
            )
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
            pos_item.setForeground(QColor(tokens["success"]))
            self._table.setItem(row_idx, 2, pos_item)
            neg_item = self._cell(str(neg), align_right=True)
            neg_item.setForeground(QColor(tokens["danger"]))
            self._table.setItem(row_idx, 3, neg_item)

        self._table.resizeColumnsToContents()

    @staticmethod
    def _cell(text: str, align_right: bool = False) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        if align_right:
            item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        return item

    def _apply_user_mode_labels(self) -> None:
        self.setWindowTitle(
            resolve_feature_label(
                self._user_mode,
                "feedback.stats.window_title",
                "Feedback Statistik",
            )
        )
        self._table.setHorizontalHeaderLabels(
            [
                resolve_feature_label(self._user_mode, "feedback.stats.header.feature", "Funktion"),
                resolve_feature_label(self._user_mode, "feedback.stats.header.events", "Events"),
                resolve_feature_label(self._user_mode, "feedback.stats.header.positive", "Positiv"),
                resolve_feature_label(self._user_mode, "feedback.stats.header.negative", "Negativ"),
            ]
        )
        if self._refresh_btn is not None:
            self._refresh_btn.setText(
                resolve_feature_label(
                    self._user_mode,
                    "feedback.stats.button.refresh",
                    "Aktualisieren",
                )
            )
        if self._close_btn is not None:
            self._close_btn.setText(
                resolve_feature_label(
                    self._user_mode,
                    "feedback.stats.button.close",
                    "Schließen",
                )
            )
