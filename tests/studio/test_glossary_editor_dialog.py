from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QMessageBox

from shared.domain.user_mode import USER_MODE_CONFIG_PATH, reload_user_mode_config
from studio.glossary.editor import GlossaryEditorDialog


class _GlossaryStoreStub:
    def __init__(self, entries: list[dict] | None = None) -> None:
        self._entries = list(entries or [])

    def list_glossary_entries(self) -> list[dict]:
        return list(self._entries)

    def replace_glossary_entries(
        self,
        entries: list[dict],
        panel_scope: str,
        apply_all_tabs: bool,
    ) -> int:
        _ = panel_scope, apply_all_tabs
        self._entries = list(entries)
        return len(entries)


def _write_glossary_mode_config(path: Path) -> None:
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
"glossary.editor.window_title" = "Glossary Admin"
"glossary.editor.summary.template" = "Entries: {count}. Save to apply."
"glossary.editor.column.term" = "Term"
"glossary.editor.column.term.tooltip" = "Term help"
"glossary.editor.column.definition" = "Definition (hover)"
"glossary.editor.column.definition.tooltip" = "Definition help"
"glossary.editor.button.add_row" = "Add row"
"glossary.editor.button.delete_selected" = "Delete rows"
"glossary.editor.button.reload" = "Reload now"
"glossary.editor.button.save" = "Save now"
"glossary.editor.button.close" = "Close now"
"glossary.editor.validation.title" = "Glossary Check"
"glossary.editor.validation.prefix" = "Please fix:\\n- "
"glossary.editor.validation.term_missing" = "Line {row}: missing term."
""".strip(),
        encoding="utf-8",
    )

    (path / "beta.toml").write_text(
        """
version = 1
id = "beta"
label = "Beta"
order = 1
default_profile = false

[visibility]

[labels]
"glossary.editor.window_title" = "Glossar Verwaltung"
"glossary.editor.summary.template" = "Einträge: {count}. Über Speichern anwenden."
"glossary.editor.column.term.tooltip" = "Term help"
"glossary.editor.column.term" = "Begriff"
"glossary.editor.column.definition.tooltip" = "Definition help"
"glossary.editor.column.definition" = "Definition (Hover)"
"glossary.editor.button.add_row" = "Add row"
"glossary.editor.button.delete_selected" = "Delete rows"
"glossary.editor.button.reload" = "Reload now"
"glossary.editor.button.save" = "Speichern"
"glossary.editor.button.close" = "Schließen"
"glossary.editor.validation.title" = "Glossary Check"
"glossary.editor.validation.prefix" = "Please fix:\\n- "
"glossary.editor.validation.term_missing" = "Line {row}: missing term."
""".strip(),
        encoding="utf-8",
    )


def test_glossary_editor_initializes_labels_from_profile(tmp_path: Path, qt_app, monkeypatch):
    _ = qt_app
    cfg = tmp_path / "user_modes"
    _write_glossary_mode_config(cfg)

    try:
        reload_user_mode_config(cfg)
        monkeypatch.setattr(
            "studio.glossary.editor.get_highlight_store",
            lambda: _GlossaryStoreStub(entries=[{"term": "A", "definition": "B"}]),
        )
        dialog = GlossaryEditorDialog(user_mode="alpha")

        assert dialog.windowTitle() == "Glossary Admin"
        assert dialog._summary_lbl.text() == "Entries: 1. Save to apply."
        assert dialog._add_btn.text() == "Add row"
        assert dialog._delete_btn.text() == "Delete rows"
        assert dialog._reload_btn.text() == "Reload now"
        assert dialog._save_btn.text() == "Save now"
        assert dialog._close_btn.text() == "Close now"
        assert dialog._table.horizontalHeaderItem(0).text() == "Term"
        assert dialog._table.horizontalHeaderItem(1).text() == "Definition (hover)"
        assert dialog._table.horizontalHeaderItem(0).toolTip() == "Term help"
        assert dialog._table.horizontalHeaderItem(1).toolTip() == "Definition help"
    finally:
        reload_user_mode_config(USER_MODE_CONFIG_PATH)


def test_glossary_editor_set_user_mode_updates_texts(tmp_path: Path, qt_app, monkeypatch):
    _ = qt_app
    cfg = tmp_path / "user_modes"
    _write_glossary_mode_config(cfg)

    try:
        reload_user_mode_config(cfg)
        monkeypatch.setattr(
            "studio.glossary.editor.get_highlight_store",
            lambda: _GlossaryStoreStub(entries=[{"term": "A", "definition": "B"}]),
        )
        dialog = GlossaryEditorDialog(user_mode="alpha")
        dialog.set_user_mode("beta")

        assert dialog.windowTitle() == "Glossar Verwaltung"
        assert dialog._summary_lbl.text() == "Einträge: 1. Über Speichern anwenden."
        assert dialog._table.horizontalHeaderItem(0).text() == "Begriff"
        assert dialog._table.horizontalHeaderItem(1).text() == "Definition (Hover)"
        assert dialog._save_btn.text() == "Speichern"
        assert dialog._close_btn.text() == "Schließen"
    finally:
        reload_user_mode_config(USER_MODE_CONFIG_PATH)


def test_glossary_editor_validation_message_uses_profile_keys(
    tmp_path: Path,
    qt_app,
    monkeypatch,
):
    _ = qt_app
    cfg = tmp_path / "user_modes"
    _write_glossary_mode_config(cfg)
    warned: dict[str, str] = {}

    def _capture_warning(parent, title: str, text: str):  # noqa: ANN001
        _ = parent
        warned["title"] = title
        warned["text"] = text
        return QMessageBox.StandardButton.Ok

    try:
        reload_user_mode_config(cfg)
        monkeypatch.setattr(
            "studio.glossary.editor.get_highlight_store",
            lambda: _GlossaryStoreStub(entries=[]),
        )
        monkeypatch.setattr("studio.glossary.editor.QMessageBox.warning", _capture_warning)
        dialog = GlossaryEditorDialog(user_mode="alpha")
        dialog._append_row("", "definition without term")
        dialog._save_entries()

        assert warned["title"] == "Glossary Check"
        assert warned["text"] == "Please fix:\n- Line 1: missing term."
    finally:
        reload_user_mode_config(USER_MODE_CONFIG_PATH)
