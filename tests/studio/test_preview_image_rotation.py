from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import QMimeData

from studio.canvas.editor import MarkdownEditor
from studio.canvas.preview.pane import CanvasPreviewPane
from studio.canvas.preview.pane_parts.interaction_events import (
    _apply_preview_image_raster_rotation,
    _apply_preview_image_rotations,
    _rotate_local_preview_image_source,
)


def test_apply_preview_image_rotations_injects_rotation_style() -> None:
    html = '<p><img src="file:///tmp/image.png" style="width: 20px;"></p>'

    out, changed = _apply_preview_image_rotations(
        html,
        {"file:///tmp/image.png": 90},
    )

    assert changed is True
    assert "--d2c-rot: 90deg" in out
    assert "transform: rotate(var(--d2c-rot))" in out
    assert "transform-origin: center center" in out
    assert "width: 20px" in out


def test_apply_preview_image_rotations_replaces_previous_rotation_style() -> None:
    html = '<p><img src="file:///tmp/image.png" style="width: 20px;"></p>'
    first, _ = _apply_preview_image_rotations(
        html,
        {"file:///tmp/image.png": 90},
    )
    second, _ = _apply_preview_image_rotations(
        first,
        {"file:///tmp/image.png": 180},
    )

    assert second.count("--d2c-rot:") == 1
    assert "--d2c-rot: 180deg" in second


def test_apply_preview_image_rotations_matches_relative_and_absolute_sources() -> None:
    html = '<p><img src="file:///tmp/project/canvas/assets/clipboard/sample.png"></p>'

    out, changed = _apply_preview_image_rotations(
        html,
        {"assets/clipboard/sample.png": 90},
    )

    assert changed is True
    assert "--d2c-rot: 90deg" in out


def test_rotate_local_preview_image_source_rotates_file_dimensions(tmp_path: Path) -> None:
    from PySide6.QtGui import QImage

    image_path = tmp_path / "sample.png"
    src = QImage(4, 2, QImage.Format.Format_ARGB32)
    src.fill(0xFF336699)
    assert src.save(str(image_path))

    assert _rotate_local_preview_image_source(str(image_path), degrees=90) is True

    rotated = QImage(str(image_path))
    assert not rotated.isNull()
    assert rotated.width() == 2
    assert rotated.height() == 4


def test_apply_preview_image_raster_rotation_replaces_src_with_data_uri(
    tmp_path: Path,
    qt_app,
) -> None:
    _ = qt_app
    from PySide6.QtGui import QImage

    canvas_root = tmp_path / "canvas"
    assets_dir = canvas_root / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    image_path = assets_dir / "sample.png"
    src = QImage(8, 3, QImage.Format.Format_ARGB32)
    src.fill(0xFFAA5500)
    assert src.save(str(image_path))

    html = '<p><img src="assets/sample.png" alt="img"></p>'
    out, changed = _apply_preview_image_raster_rotation(
        html,
        target_source="assets/sample.png",
        degrees=90,
        search_paths=[str(canvas_root)],
    )

    assert changed is True
    assert "data:image/png;base64," in out
    assert "assets/sample.png" not in out


def test_rotate_preview_image_rotates_local_asset_file(
    tmp_path: Path,
    qt_app,
) -> None:
    _ = qt_app
    from PySide6.QtGui import QImage

    canvas_root = tmp_path / "canvas"
    assets_dir = canvas_root / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    image_path = assets_dir / "sample.png"
    src = QImage(5, 2, QImage.Format.Format_ARGB32)
    src.fill(0xFF1199CC)
    assert src.save(str(image_path))

    pane = CanvasPreviewPane(allow_editing=True, show_title=False, sync_cursor_with_editor=False)
    try:
        pane._view.setSearchPaths([str(canvas_root)])
        pane.set_html_content('<p><img src="assets/sample.png"></p>')
        assert pane._rotate_preview_image("assets/sample.png", degrees=90) is True

        rotated = QImage(str(image_path))
        assert not rotated.isNull()
        assert rotated.width() == 2
        assert rotated.height() == 5
    finally:
        pane.deleteLater()


def test_preview_syncs_relative_image_search_paths(tmp_path: Path, qt_app):
    _ = qt_app
    project_root = (tmp_path / "project").resolve(strict=False)
    autosave_root = (tmp_path / "autosave").resolve(strict=False)
    pane = CanvasPreviewPane(allow_editing=True, show_title=False, sync_cursor_with_editor=False)
    try:
        pane._project_manager = SimpleNamespace(current_project_folder=project_root)
        pane._autosave_ctrl = SimpleNamespace(autosave_dir=autosave_root)
        pane._sync_local_resource_search_paths()
        paths = [str(item) for item in pane._view.searchPaths()]
        assert str((project_root / "canvas").resolve(strict=False)) in paths
        assert str((autosave_root / "canvas").resolve(strict=False)) in paths
    finally:
        pane.deleteLater()


def test_preview_paste_routes_image_clipboard_through_editor_handler(
    monkeypatch,
    qt_app,
):
    _ = qt_app
    pane = CanvasPreviewPane(allow_editing=True, show_title=False, sync_cursor_with_editor=False)
    editor = MarkdownEditor(read_only=False)
    pane.bind_editor(editor)
    pane.set_allow_editing(True)
    pane._view.setReadOnly(False)
    called = {"count": 0}
    try:
        mime = QMimeData()
        mime.setText("![img](https://example.com/image.png)")

        class _ClipboardStub:
            def mimeData(self_inner):
                return mime

        monkeypatch.setattr(
            "studio.canvas.preview.pane_parts.interaction_events.QApplication.clipboard",
            lambda: _ClipboardStub(),
        )

        def _fake_insert(_mime):
            called["count"] += 1
            return True

        monkeypatch.setattr(editor, "_insert_image_markdown_from_mime_data", _fake_insert)
        assert pane._handle_preview_image_paste() is True
        assert called["count"] == 1
    finally:
        pane.deleteLater()
        editor.deleteLater()
