from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QDialogButtonBox, QLabel, QPushButton, QTabWidget

from shared.domain.user_mode import USER_MODE_CONFIG_PATH, reload_user_mode_config
from studio.dialogs.prompt_editor import PromptEditorDialog


class _PromptManagerStub:
    PROMPT_KEYS = ("chat_system", "chat_grounding_rules")

    def __init__(self) -> None:
        self._prompts = {
            "chat_system": "sys-value",
            "chat_grounding_rules": "grounding-value",
        }
        self._defaults = {
            "chat_system": "sys-default",
            "chat_grounding_rules": "grounding-default",
        }

    def get_prompt_set(self) -> dict[str, str]:
        return dict(self._prompts)

    def get_prompt_defaults(self) -> dict[str, str]:
        return dict(self._defaults)

    def set_prompt_set(self, prompts: dict[str, str]) -> None:
        self._prompts = dict(prompts)


def _write_prompt_editor_mode_config(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "alpha.toml").write_text(
        """
version = 1
id = "alpha"
label = "Alpha"
order = 0
default_profile = true

[visibility]

[labels]
"prompt_editor.window_title" = "Prompt Config"
"prompt_editor.intro" = "Custom intro text."
"prompt_editor.group.chat" = "Conversation"
"prompt_editor.group.info.default" = "Custom group info."
"prompt_editor.meta.type" = "Type"
"prompt_editor.meta.usage" = "Usage"
"prompt_editor.meta.placeholders" = "Vars"
"prompt_editor.flow.label" = "Flow Preview"
"prompt_editor.flow.chat" = "Custom flow"
"prompt_editor.button.reset_current" = "Reset current"
"prompt_editor.button.reset_group" = "Reset group"
"prompt_editor.button.reset_all" = "Reset all"
"prompt_editor.button.ok" = "Apply"
"prompt_editor.button.cancel" = "Abort"
"prompt_editor.prompt.chat_system.title" = "System Prompt"
"prompt_editor.prompt.chat_system.kind" = "SystemKind"
"prompt_editor.prompt.chat_system.desc" = "System description"
"prompt_editor.prompt.chat_system.placeholders" = "{var}"
""".strip(),
        encoding="utf-8",
    )


def test_prompt_editor_uses_profile_labels(tmp_path: Path, qt_app):
    _ = qt_app
    cfg = tmp_path / "user_modes"
    _write_prompt_editor_mode_config(cfg)

    try:
        reload_user_mode_config(cfg)
        dialog = PromptEditorDialog(_PromptManagerStub(), user_mode="alpha")

        assert dialog.windowTitle() == "Prompt Config"
        label_texts = [lbl.text() for lbl in dialog.findChildren(QLabel)]
        assert "Custom intro text." in label_texts
        assert "Custom group info." in label_texts
        assert "Flow Preview" in label_texts

        tab_widgets = dialog.findChildren(QTabWidget)
        assert any(
            any(tw.tabText(i) == "Conversation" for i in range(tw.count()))
            for tw in tab_widgets
        )
        assert any(
            any(tw.tabText(i) == "System Prompt" for i in range(tw.count()))
            for tw in tab_widgets
        )

        button_texts = {btn.text() for btn in dialog.findChildren(QPushButton)}
        assert "Reset current" in button_texts
        assert "Reset group" in button_texts
        assert "Reset all" in button_texts

        boxes = dialog.findChildren(QDialogButtonBox)
        assert boxes
        ok_btn = boxes[-1].button(QDialogButtonBox.StandardButton.Ok)
        cancel_btn = boxes[-1].button(QDialogButtonBox.StandardButton.Cancel)
        assert ok_btn is not None and ok_btn.text() == "Apply"
        assert cancel_btn is not None and cancel_btn.text() == "Abort"
    finally:
        reload_user_mode_config(USER_MODE_CONFIG_PATH)
