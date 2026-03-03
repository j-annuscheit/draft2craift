"""Application theme helpers."""
from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


def apply_dark_theme(app: QApplication):
    p = QPalette()
    colors = {
        QPalette.ColorRole.Window: "#1E1E2E",
        QPalette.ColorRole.WindowText: "#CDD6F4",
        QPalette.ColorRole.Base: "#181825",
        QPalette.ColorRole.AlternateBase: "#1E1E2E",
        QPalette.ColorRole.ToolTipBase: "#313244",
        QPalette.ColorRole.ToolTipText: "#CDD6F4",
        QPalette.ColorRole.Text: "#CDD6F4",
        QPalette.ColorRole.Button: "#313244",
        QPalette.ColorRole.ButtonText: "#CDD6F4",
        QPalette.ColorRole.BrightText: "#F38BA8",
        QPalette.ColorRole.Highlight: "#89B4FA",
        QPalette.ColorRole.HighlightedText: "#1E1E2E",
        QPalette.ColorRole.Link: "#89B4FA",
        QPalette.ColorRole.Mid: "#45475A",
        QPalette.ColorRole.Dark: "#181825",
        QPalette.ColorRole.Shadow: "#11111B",
    }
    for role, hex_color in colors.items():
        p.setColor(role, QColor(hex_color))
    app.setPalette(p)
    tooltip_style = (
        "QToolTip {"
        "color: #CDD6F4;"
        "background-color: #181825;"
        "border: 1px solid #45475A;"
        "padding: 4px 6px;"
        "}"
    )
    current = str(app.styleSheet() or "")
    if tooltip_style not in current:
        app.setStyleSheet((current + "\n" + tooltip_style).strip())
