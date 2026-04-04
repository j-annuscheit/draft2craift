from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication

from studio.canvas.editor import MarkdownEditor
from studio.canvas.preview.pane import CanvasPreviewPane
from studio.canvas.preview.style_settings import normalize_preview_style_settings


pytestmark = pytest.mark.usefixtures("qt_app")


def _process_events() -> None:
    app = QApplication.instance()
    if app is not None:
        app.processEvents()


def _build_pane() -> tuple[CanvasPreviewPane, MarkdownEditor]:
    editor = MarkdownEditor(read_only=False)
    pane = CanvasPreviewPane(
        allow_editing=True,
        show_title=False,
        sync_cursor_with_editor=False,
    )
    pane.bind_editor(editor)
    pane.show()
    _process_events()
    return pane, editor


def test_normalize_preview_style_settings_accepts_formula_text_color():
    style = normalize_preview_style_settings({"formula_text_color": "#12AB34"})
    assert str(style["formula_text_color"]) == "#12AB34"

    invalid = normalize_preview_style_settings({"formula_text_color": "nope"})
    assert str(invalid["formula_text_color"]) == ""


def test_formula_cache_key_depends_on_formula_color():
    from studio.canvas.preview.pane_parts.render_sync import _formula_cache_key

    plain = _formula_cache_key("x+y", False)
    red = _formula_cache_key("x+y", False, formula_color="#FF0000")
    green = _formula_cache_key("x+y", False, formula_color="#00FF00")
    assert plain != red
    assert red != green


def test_latex_renderer_uses_configured_formula_text_color(monkeypatch):
    import studio.canvas.preview.pane_parts.render_sync as render_sync

    calls: list[tuple[str, bool, str]] = []

    def _fake_render(latex: str, display: bool, formula_color: str = "") -> str | None:
        calls.append((str(latex or ""), bool(display), str(formula_color or "")))
        return "FAKEPNG"

    monkeypatch.setattr(render_sync, "_render_formula_png_b64", _fake_render)

    pane, editor = _build_pane()
    try:
        style = pane.preview_style_settings()
        style["formula_text_color"] = "#12AB34"
        pane.set_preview_style_settings(style, force=True)
        editor.setPlainText("Formel: $x+y$")
        pane._render()
        _process_events()

        assert calls, "Expected formula renderer call."
        assert calls[0][2] == "#12AB34"
        assert "FAKEPNG" in str(pane._view.toHtml() or "")
    finally:
        pane.deleteLater()
        editor.deleteLater()
        _process_events()
