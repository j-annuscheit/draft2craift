from __future__ import annotations

from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QVBoxLayout,
)


class MetricCard(QFrame):
    def __init__(self, title: str, accent: str):
        super().__init__()
        self.setObjectName("MetricCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(2)

        self._title = QLabel(title)
        self._title.setStyleSheet("font-size: 11px; color: #A6ADC8;")
        self._value = QLabel("—")
        self._value.setStyleSheet(
            f"font-size: 24px; font-weight: 700; color: {accent}; letter-spacing: 0.5px;"
        )
        self._sub = QLabel("")
        self._sub.setStyleSheet("font-size: 10px; color: #6C7086;")

        layout.addWidget(self._title)
        layout.addWidget(self._value)
        layout.addWidget(self._sub)

    def set_value(self, value_text: str, sub_text: str = "") -> None:
        self._value.setText(value_text)
        self._sub.setText(sub_text)
