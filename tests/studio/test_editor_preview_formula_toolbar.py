from __future__ import annotations

from PySide6.QtWidgets import QApplication, QDialog, QPushButton

from studio.canvas.editor import MarkdownEditor
from studio.canvas.editor_panel import EditorPanel
from studio.canvas.preview.pane import CanvasPreviewPane


def _process_events() -> None:
    app = QApplication.instance()
    if app is not None:
        app.processEvents()


def test_markdown_editor_toolbar_hides_edit_quote_formula_buttons(qt_app):
    _ = qt_app
    panel = EditorPanel(read_only=False, show_toolbar=True)
    try:
        buttons = panel.findChildren(QPushButton)
        texts = [str(btn.text() or "") for btn in buttons]
        joined = " | ".join(texts)
        assert "Zitat" not in joined
        assert "Formel" not in joined
        assert "Bearbeitung" not in joined
        assert "Editing" not in joined
    finally:
        panel.deleteLater()
        _process_events()


def test_preview_toolbar_formula_button_inserts_latex(monkeypatch, qt_app):
    _ = qt_app
    import studio.canvas.formula_editor as formula_editor

    class _FakeFormulaDialog:
        DialogCode = QDialog.DialogCode

        def __init__(self, parent=None):
            _ = parent

        def exec(self):
            return self.DialogCode.Accepted

        def result_latex(self) -> str:
            return "$E=mc^2$"

    monkeypatch.setattr(formula_editor, "FormulaEditorDialog", _FakeFormulaDialog)

    editor = MarkdownEditor(read_only=False)
    pane = CanvasPreviewPane(
        allow_editing=True,
        show_title=False,
        sync_cursor_with_editor=False,
    )
    try:
        pane.bind_editor(editor)
        editor.setPlainText("Alpha")
        pane._render()
        _process_events()

        assert "formula" in pane._format_buttons
        pane._format_buttons["formula"].click()
        _process_events()

        assert "$E=mc^2$" in editor.toPlainText()
    finally:
        pane.deleteLater()
        editor.deleteLater()
        _process_events()
