"""Styles used by the RAG settings dialog."""

RAG_SETTINGS_STYLE = """
QDialog          { background: #1E1E2E; color: #CDD6F4; }
QGroupBox {
    color: #89B4FA; font-weight: bold; font-size: 11px;
    border: 1px solid #45475A; border-radius: 4px;
    margin-top: 8px; padding-top: 10px;
}
QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }
QLabel           { color: #CDD6F4; font-size: 11px; }
QSpinBox, QDoubleSpinBox, QLineEdit {
    background: #181825; color: #CDD6F4;
    border: 1px solid #45475A; border-radius: 3px;
    padding: 2px 6px; font-size: 11px;
}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
    background: #313244; border: none; width: 16px;
}
QComboBox {
    background: #181825; color: #CDD6F4;
    border: 1px solid #45475A; border-radius: 3px;
    padding: 2px 6px; font-size: 11px;
}
QComboBox::drop-down { border: none; width: 18px; }
QComboBox QAbstractItemView {
    background: #313244; color: #CDD6F4;
    selection-background-color: #45475A; border: none;
}
QCheckBox              { color: #CDD6F4; font-size: 11px; }
QCheckBox::indicator   { width: 14px; height: 14px; border: 1px solid #45475A; border-radius: 2px; }
QCheckBox::indicator:checked { background: #89B4FA; border-color: #89B4FA; }
QPushButton {
    background: #313244; color: #CDD6F4;
    border: none; border-radius: 3px;
    padding: 4px 12px; font-size: 11px;
}
QPushButton:hover { background: #45475A; }
QPushButton:disabled { color: #585b70; }
"""
