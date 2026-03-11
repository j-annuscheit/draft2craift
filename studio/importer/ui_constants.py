from __future__ import annotations

_DIALOG_STYLE = """
QDialog { background: palette(window); color: palette(window-text); }
QWidget { color: palette(text); }
QListWidget {
    background: palette(base); color: palette(text);
    border: 1px solid palette(mid); border-radius: 4px; font-size: 11px;
}
QListWidget::item { padding: 4px 6px; }
QListWidget::item:selected { background: palette(highlight); color: palette(highlighted-text); }
QListWidget::item:hover { background: palette(alternate-base); }
QPlainTextEdit {
    background: palette(base); color: palette(text);
    border: 1px solid palette(mid); border-radius: 4px;
    font-size: 11px;
    font-family: "Cascadia Code", "JetBrains Mono", "Fira Code", monospace;
}
QPushButton {
    background: palette(alternate-base); color: palette(text);
    border: 1px solid palette(mid); padding: 4px 12px; border-radius: 4px; font-size: 11px;
}
QPushButton:hover { border-color: palette(highlight); }
QPushButton:disabled { color: palette(placeholder-text); background: palette(window); }
QPushButton[toolbarButton="true"] {
    padding: 0px 4px;
    font-weight: bold;
}
QPushButton#primary { background: palette(highlight); color: palette(highlighted-text); border-color: palette(highlight); font-weight: bold; }
QPushButton#primary:hover { border-color: palette(highlight); }
QPushButton#primary:disabled { background: palette(alternate-base); color: palette(placeholder-text); border-color: palette(mid); }
QPushButton#accent { background: palette(base); color: palette(text); border: 1px solid palette(highlight); font-weight: bold; }
QPushButton#accent:hover { background: palette(alternate-base); border-color: palette(highlight); }
QPushButton#accent:disabled { background: palette(window); color: palette(placeholder-text); border-color: palette(mid); }
QGroupBox {
    color: palette(text); border: 1px solid palette(mid); border-radius: 4px;
    margin-top: 10px; font-size: 10px; font-weight: bold; padding-top: 4px;
}
QGroupBox::title {
    subcontrol-origin: margin; left: 8px; padding: 0 4px; color: palette(highlight);
}
QCheckBox { color: palette(text); font-size: 11px; spacing: 6px; }
QCheckBox::indicator {
    width: 13px; height: 13px;
    border: 1px solid palette(mid); border-radius: 3px; background: palette(base);
}
QCheckBox::indicator:checked { background: palette(highlight); border-color: palette(highlight); }
QCheckBox::indicator:disabled { background: palette(window); border-color: palette(alternate-base); }
QCheckBox:disabled { color: palette(placeholder-text); }
QSpinBox, QDoubleSpinBox {
    background: palette(base); color: palette(text);
    border: 1px solid palette(mid); border-radius: 4px;
    padding: 2px 4px; font-size: 11px;
}
QSpinBox:focus, QDoubleSpinBox:focus { border-color: palette(highlight); }
QSpinBox:disabled, QDoubleSpinBox:disabled { color: palette(placeholder-text); background: palette(window); }
QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {
    background: palette(alternate-base); border: none; width: 14px;
}
QComboBox {
    background: palette(base); color: palette(text);
    border: 1px solid palette(mid); border-radius: 4px;
    padding: 2px 6px; font-size: 11px;
}
QComboBox:focus { border-color: palette(highlight); }
QComboBox:disabled { color: palette(placeholder-text); background: palette(window); }
QComboBox::drop-down { border: none; width: 18px; }
QComboBox QAbstractItemView {
    background: palette(base); color: palette(text);
    selection-background-color: palette(highlight); selection-color: palette(highlighted-text);
    border: 1px solid palette(mid);
}
QLineEdit {
    background: palette(base); color: palette(text);
    border: 1px solid palette(mid); border-radius: 4px;
    padding: 2px 6px; font-size: 11px;
}
QLineEdit:focus { border-color: palette(highlight); }
QScrollArea { background: palette(window); border: none; }
QScrollBar:vertical { background: palette(base); width: 8px; margin: 0; }
QScrollBar::handle:vertical { background: palette(mid); border-radius: 4px; min-height: 20px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QProgressBar {
    background: palette(alternate-base); border: none; border-radius: 3px;
    height: 8px; color: palette(text); font-size: 10px;
}
QProgressBar::chunk { background: palette(highlight); border-radius: 3px; }
QLabel { color: palette(text); font-size: 11px; }
QSplitter::handle { background: palette(mid); width: 2px; }
"""

_STATUS_PENDING = "Pending"
_STATUS_DONE    = "Done"
_STATUS_ERROR   = "Error"

_ICON = {_STATUS_PENDING: "⏳", _STATUS_DONE: "✓", _STATUS_ERROR: "✗"}
