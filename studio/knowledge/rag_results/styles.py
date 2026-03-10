"""Style constants for the RAG results panel and debug dialog."""

RAG_SEARCH_INPUT_STYLE = """
QLineEdit {
    background: palette(base); color: palette(text);
    border: 1px solid palette(mid); border-radius: 4px;
    padding: 3px 8px; font-size: 11px;
}
QLineEdit:focus { border-color: palette(highlight); }
"""

RAG_SEARCH_BUTTON_STYLE = """
QPushButton {
    background: palette(highlight); color: palette(highlighted-text);
    border: none; border-radius: 4px;
    padding: 3px 10px; font-size: 11px; font-weight: bold;
}
QPushButton:hover { border: 1px solid palette(highlight); }
"""

RAG_ICON_BUTTON_STYLE = (
    "QPushButton { background: palette(alternate-base); color: palette(text); border: none;"
    " border-radius: 3px; font-size: 13px; padding: 0; }"
    "QPushButton:hover { border: 1px solid palette(highlight); }"
)

RAG_TOP_BAR_STYLE = "background: palette(alternate-base); border-bottom: 1px solid palette(mid);"

RAG_STATUS_LABEL_STYLE = (
    "color: palette(highlight); font-size: 10px; padding: 2px 8px;"
    "background: palette(base); border-bottom: 1px solid palette(alternate-base);"
)

RAG_DEBUG_DIALOG_STYLE = (
    "QDialog{background:palette(window);color:palette(window-text);}"
    "QTextEdit{background:palette(base);color:palette(text);border:1px solid palette(mid);"
    "border-radius:4px;padding:6px;font-family:'Cascadia Code','Consolas',monospace;"
    "font-size:11px;}"
)

RAG_DEBUG_SELECTOR_STYLE = (
    "QComboBox{background:palette(base);color:palette(text);border:1px solid palette(mid);"
    "border-radius:4px;padding:4px 8px;font-size:11px;}"
    "QComboBox::drop-down{border:none;width:18px;}"
    "QComboBox QAbstractItemView{background:palette(alternate-base);color:palette(text);"
    "selection-background-color:palette(highlight);selection-color:palette(highlighted-text);border:none;}"
)
