"""Shared visual constants for the canvas feature."""

CANVAS_TOOLBAR_STYLE = """
QWidget#canvasbar {
    background: palette(base);
    border-bottom: 1px solid palette(mid);
}
QPushButton {
    background: palette(alternate-base);
    color: palette(text);
    border: none; padding: 3px 12px;
    border-radius: 3px; font-size: 11px;
}
QPushButton:hover { border: 1px solid palette(highlight); }
QPushButton:checked { background: palette(highlight); color: palette(highlighted-text); }
"""

PREVIEW_PANEL_STYLE = "background: palette(base); border-left: 1px solid palette(mid);"

PREVIEW_VIEW_STYLE = (
    "QTextBrowser {"
    "background: palette(base);"
    "color: palette(text);"
    "border: 1px solid palette(mid);"
    "border-radius: 6px;"
    "padding: 2px;"
    "}"
)
