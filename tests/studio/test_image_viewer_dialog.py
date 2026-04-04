from __future__ import annotations

import base64
from pathlib import Path

from PySide6.QtCore import QPoint
from PySide6.QtGui import QColor, QImage

from studio.canvas.image_viewer_dialog import ImageViewerDialog, _pixmap_from_source


def test_pixmap_from_source_loads_local_file(tmp_path: Path, qt_app):
    _ = qt_app
    image_path = tmp_path / "sample.png"
    image = QImage(16, 16, QImage.Format.Format_ARGB32)
    image.fill(0xFF00FF00)
    assert image.save(str(image_path), "PNG")

    pixmap = _pixmap_from_source(str(image_path))
    assert not pixmap.isNull()


def test_pixmap_from_source_loads_data_uri(tmp_path: Path, qt_app):
    _ = qt_app
    image_path = tmp_path / "sample.png"
    image = QImage(10, 10, QImage.Format.Format_ARGB32)
    image.fill(0xFFFF0000)
    assert image.save(str(image_path), "PNG")
    payload = base64.b64encode(image_path.read_bytes()).decode("ascii")
    uri = f"data:image/png;base64,{payload}"

    pixmap = _pixmap_from_source(uri)
    assert not pixmap.isNull()


def test_image_viewer_dialog_opens_with_valid_image(tmp_path: Path, qt_app):
    _ = qt_app
    image_path = tmp_path / "dialog.png"
    image = QImage(20, 20, QImage.Format.Format_ARGB32)
    image.fill(0xFF112233)
    assert image.save(str(image_path), "PNG")

    dialog = ImageViewerDialog(str(image_path))
    try:
        assert dialog.windowTitle() == "Bildansicht"
    finally:
        dialog.close()
        dialog.deleteLater()


def test_pixmap_from_source_resolves_relative_path_with_search_paths(
    tmp_path: Path,
    qt_app,
):
    _ = qt_app
    canvas_root = tmp_path / "project" / "canvas"
    image_path = canvas_root / "assets" / "clipboard" / "img.png"
    image_path.parent.mkdir(parents=True, exist_ok=True)

    image = QImage(18, 12, QImage.Format.Format_ARGB32)
    image.fill(0xFF445566)
    assert image.save(str(image_path), "PNG")

    pixmap = _pixmap_from_source(
        "assets/clipboard/img.png",
        search_paths=[str(canvas_root)],
    )
    assert not pixmap.isNull()


def test_image_viewer_dialog_rotate_persists_local_file(tmp_path: Path, qt_app):
    _ = qt_app
    image_path = tmp_path / "rotate.png"
    image = QImage(22, 9, QImage.Format.Format_ARGB32)
    image.fill(0xFF2255AA)
    assert image.save(str(image_path), "PNG")

    dialog = ImageViewerDialog(str(image_path))
    try:
        dialog._rotate_image(90)
    finally:
        dialog.close()
        dialog.deleteLater()

    rotated = QImage(str(image_path))
    assert not rotated.isNull()
    assert rotated.width() == 9
    assert rotated.height() == 22


def test_image_viewer_dialog_eraser_changes_pixel(tmp_path: Path, qt_app):
    _ = qt_app
    image_path = tmp_path / "erase.png"
    image = QImage(16, 16, QImage.Format.Format_ARGB32)
    image.fill(0xFFFF0000)
    assert image.save(str(image_path), "PNG")

    dialog = ImageViewerDialog(str(image_path))
    try:
        dialog._brush_color = QColor("#0000FF")
        assert dialog._paint_segment(QPoint(8, 8), QPoint(8, 8)) is True
        dialog._commit_image_edit()

        painted = QImage(str(image_path))
        assert not painted.isNull()
        painted_pixel = painted.pixelColor(8, 8)
        assert painted_pixel.blue() > 0

        dialog._on_eraser_toggled(True)
        assert dialog._paint_segment(QPoint(8, 8), QPoint(8, 8)) is True
        dialog._commit_image_edit()
    finally:
        dialog.close()
        dialog.deleteLater()

    edited = QImage(str(image_path))
    assert not edited.isNull()
    pixel = edited.pixelColor(8, 8)
    assert pixel.red() == 255
    assert pixel.green() == 0
    assert pixel.blue() == 0
    assert pixel.alpha() == 255


def test_image_viewer_dialog_eraser_pen_width_is_double(tmp_path: Path, qt_app):
    _ = qt_app
    image_path = tmp_path / "size.png"
    image = QImage(8, 8, QImage.Format.Format_ARGB32)
    image.fill(0xFFFFFFFF)
    assert image.save(str(image_path), "PNG")

    dialog = ImageViewerDialog(str(image_path))
    try:
        dialog._on_brush_size_changed(3)
        dialog._on_eraser_toggled(False)
        assert dialog._effective_pen_width() == 3
        dialog._on_eraser_toggled(True)
        assert dialog._effective_pen_width() == 6
    finally:
        dialog.close()
        dialog.deleteLater()
