from __future__ import annotations

_DIALOG_STYLE = """
QDialog { background: #1E1E2E; color: #CDD6F4; }
QWidget { background: #1E1E2E; color: #CDD6F4; }
QListWidget {
    background: #181825; color: #CDD6F4;
    border: 1px solid #45475A; border-radius: 4px; font-size: 11px;
}
QListWidget::item { padding: 4px 6px; }
QListWidget::item:selected { background: #313244; }
QListWidget::item:hover { background: #2A2A3E; }
QPlainTextEdit {
    background: #181825; color: #CDD6F4;
    border: 1px solid #45475A; border-radius: 4px;
    font-size: 11px;
    font-family: "Cascadia Code", "JetBrains Mono", "Fira Code", monospace;
}
QPushButton {
    background: #313244; color: #CDD6F4;
    border: none; padding: 4px 12px; border-radius: 4px; font-size: 11px;
}
QPushButton:hover { background: #45475A; }
QPushButton:disabled { color: #6C7086; background: #23233A; }
QPushButton#primary { background: #89B4FA; color: #1E1E2E; font-weight: bold; }
QPushButton#primary:hover { background: #B4BEFE; }
QPushButton#primary:disabled { background: #313244; color: #6C7086; }
QPushButton#accent { background: #A6E3A1; color: #1E1E2E; font-weight: bold; }
QPushButton#accent:hover { background: #94E2D5; }
QPushButton#accent:disabled { background: #313244; color: #6C7086; }
QGroupBox {
    color: #A6ADC8; border: 1px solid #45475A; border-radius: 4px;
    margin-top: 10px; font-size: 10px; font-weight: bold; padding-top: 4px;
}
QGroupBox::title {
    subcontrol-origin: margin; left: 8px; padding: 0 4px; color: #89B4FA;
}
QCheckBox { color: #CDD6F4; font-size: 11px; spacing: 6px; }
QCheckBox::indicator {
    width: 13px; height: 13px;
    border: 1px solid #45475A; border-radius: 3px; background: #181825;
}
QCheckBox::indicator:checked { background: #89B4FA; border-color: #89B4FA; }
QCheckBox::indicator:disabled { background: #2A2A3E; border-color: #313244; }
QCheckBox:disabled { color: #6C7086; }
QSpinBox, QDoubleSpinBox {
    background: #181825; color: #CDD6F4;
    border: 1px solid #45475A; border-radius: 4px;
    padding: 2px 4px; font-size: 11px;
}
QSpinBox:focus, QDoubleSpinBox:focus { border-color: #89B4FA; }
QSpinBox:disabled, QDoubleSpinBox:disabled { color: #6C7086; background: #23233A; }
QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {
    background: #313244; border: none; width: 14px;
}
QComboBox {
    background: #181825; color: #CDD6F4;
    border: 1px solid #45475A; border-radius: 4px;
    padding: 2px 6px; font-size: 11px;
}
QComboBox:focus { border-color: #89B4FA; }
QComboBox:disabled { color: #6C7086; background: #23233A; }
QComboBox::drop-down { border: none; width: 18px; }
QComboBox QAbstractItemView {
    background: #181825; color: #CDD6F4;
    selection-background-color: #313244; border: 1px solid #45475A;
}
QLineEdit {
    background: #181825; color: #CDD6F4;
    border: 1px solid #45475A; border-radius: 4px;
    padding: 2px 6px; font-size: 11px;
}
QLineEdit:focus { border-color: #89B4FA; }
QScrollArea { background: #1E1E2E; border: none; }
QScrollBar:vertical { background: #181825; width: 8px; margin: 0; }
QScrollBar::handle:vertical { background: #45475A; border-radius: 4px; min-height: 20px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QProgressBar {
    background: #313244; border: none; border-radius: 3px;
    height: 8px; color: #CDD6F4; font-size: 10px;
}
QProgressBar::chunk { background: #89B4FA; border-radius: 3px; }
QLabel { color: #A6ADC8; font-size: 11px; }
QSplitter::handle { background: #45475A; width: 2px; }
"""

_STATUS_PENDING = "Pending"
_STATUS_DONE    = "Done"
_STATUS_ERROR   = "Error"

_ICON = {_STATUS_PENDING: "⏳", _STATUS_DONE: "✓", _STATUS_ERROR: "✗"}
