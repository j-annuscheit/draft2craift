"""Style constants for the RAG results panel and debug dialog."""

RAG_SEARCH_INPUT_STYLE = """
QLineEdit {
    background: #1E1E2E; color: #CDD6F4;
    border: 1px solid #45475A; border-radius: 4px;
    padding: 3px 8px; font-size: 11px;
}
QLineEdit:focus { border-color: #89B4FA; }
"""

RAG_SEARCH_BUTTON_STYLE = """
QPushButton {
    background: #89B4FA; color: #1E1E2E;
    border: none; border-radius: 4px;
    padding: 3px 10px; font-size: 11px; font-weight: bold;
}
QPushButton:hover { background: #B4BEFE; }
"""

RAG_ICON_BUTTON_STYLE = (
    "QPushButton { background: #313244; color: #CDD6F4; border: none;"
    " border-radius: 3px; font-size: 13px; padding: 0; }"
    "QPushButton:hover { background: #45475A; }"
)

RAG_TOP_BAR_STYLE = "background: #2A2A3E; border-bottom: 1px solid #45475A;"

RAG_STATUS_LABEL_STYLE = (
    "color: #F9E2AF; font-size: 10px; padding: 2px 8px;"
    "background: #181825; border-bottom: 1px solid #2A2A3E;"
)

RAG_DEBUG_DIALOG_STYLE = (
    "QDialog{background:#1E1E2E;color:#CDD6F4;}"
    "QTextEdit{background:#181825;color:#CDD6F4;border:1px solid #45475A;"
    "border-radius:4px;padding:6px;font-family:'Cascadia Code','Consolas',monospace;"
    "font-size:11px;}"
)

RAG_DEBUG_SELECTOR_STYLE = (
    "QComboBox{background:#181825;color:#CDD6F4;border:1px solid #45475A;"
    "border-radius:4px;padding:4px 8px;font-size:11px;}"
    "QComboBox::drop-down{border:none;width:18px;}"
    "QComboBox QAbstractItemView{background:#313244;color:#CDD6F4;"
    "selection-background-color:#45475A;border:none;}"
)
