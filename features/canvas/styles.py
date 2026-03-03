"""Shared visual constants for the canvas feature."""

CANVAS_TOOLBAR_STYLE = """
QWidget#canvasbar {
    background: #181825;
    border-bottom: 1px solid #313244;
}
QPushButton {
    background: #313244; color: #CDD6F4;
    border: none; padding: 3px 12px;
    border-radius: 3px; font-size: 11px;
}
QPushButton:hover { background: #45475A; }
QPushButton:checked { background: #89B4FA; color: #1E1E2E; }
"""

PREVIEW_PANEL_STYLE = "background: #181825; border-left: 1px solid #313244;"

PREVIEW_VIEW_STYLE = (
    "QTextBrowser {"
    "background: #1E1E2E;"
    "color: #CDD6F4;"
    "border: 1px solid #45475A;"
    "border-radius: 6px;"
    "padding: 2px;"
    "}"
)
