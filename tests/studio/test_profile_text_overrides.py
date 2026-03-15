from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGroupBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from shared.domain.user_mode import (
    USER_MODE_CONFIG_PATH,
    reload_user_mode_config,
)
from studio.profile_text_overrides import apply_profile_text_overrides


def test_apply_profile_text_overrides_across_widget_types(tmp_path: Path, qt_app):
    cfg = tmp_path / "user_modes"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "alpha.toml").write_text(
        """
version = 1
id = "alpha"
label = "Alpha"
order = 0
default_profile = true

[visibility]

[labels]

[literal_labels]
"Button A" = "Button B"
"Check A" = "Check B"
"Group A" = "Group B"
"Tab A" = "Tab B"
"Tab C" = "Tab D"
"Auto" = "Automatic"
"Prompt…" = "Prompt (localized)…"
"Window A" = "Window B"

[literal_tooltips]
"Button tip A" = "Button tip B"
"Action tip A" = "Action tip B"
"Static Label" = "Static tip"
""".strip(),
        encoding="utf-8",
    )

    try:
        reload_user_mode_config(cfg)

        root = QWidget()
        root.setWindowTitle("Window A")
        layout = QVBoxLayout(root)

        button = QPushButton("Button A")
        button.setToolTip("Button tip A")
        layout.addWidget(button)

        check = QCheckBox("Check A")
        layout.addWidget(check)

        group = QGroupBox("Group A")
        layout.addWidget(group)

        label = QLabel("Static Label")
        layout.addWidget(label)

        combo = QComboBox()
        combo.addItems(["Auto"])
        layout.addWidget(combo)

        line = QLineEdit()
        line.setPlaceholderText("Prompt…")
        layout.addWidget(line)

        tabs = QTabWidget()
        tabs.addTab(QWidget(), "Tab A")
        tabs.addTab(QWidget(), "Tab C")
        layout.addWidget(tabs)

        action = QAction("Action A", root)
        action.setToolTip("Action tip A")

        apply_profile_text_overrides(root, "alpha")

        assert root.windowTitle() == "Window B"
        assert button.text() == "Button B"
        assert button.toolTip() == "Button tip B"
        assert check.text() == "Check B"
        assert group.title() == "Group B"
        assert label.toolTip() == "Static tip"
        assert combo.itemText(0) == "Automatic"
        assert line.placeholderText() == "Prompt (localized)…"
        assert tabs.tabText(0) == "Tab B"
        assert tabs.tabText(1) == "Tab D"
        assert action.toolTip() == "Action tip B"
    finally:
        reload_user_mode_config(USER_MODE_CONFIG_PATH)
