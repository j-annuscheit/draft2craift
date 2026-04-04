from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import QMimeData, Qt, QUrl
from PySide6.QtGui import QImage

from studio.canvas.editor import MarkdownEditor
from studio.canvas.editor_panel import EditorPanel


def test_markdown_editor_paste_image_saves_file_and_inserts_markdown_link(
    monkeypatch,
    tmp_path: Path,
    qt_app,
):
    _ = qt_app
    editor = MarkdownEditor(read_only=False)
    try:
        monkeypatch.setattr(
            editor,
            "_resolve_image_storage_target",
            lambda: (tmp_path, "assets/clipboard"),
        )
        image = QImage(12, 8, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.red)

        mime = QMimeData()
        mime.setImageData(image)

        editor.insertFromMimeData(mime)
        text = str(editor.toPlainText() or "")
        match = re.search(
            r"!\[clipboard-image\]\(<assets/clipboard/([^>]+)>\)",
            text,
        )
        assert match is not None

        saved_path = tmp_path / str(match.group(1))
        assert saved_path.exists()
        assert saved_path.suffix.lower() == ".png"
        loaded = QImage(str(saved_path))
        assert not loaded.isNull()
    finally:
        editor.deleteLater()


def test_markdown_editor_text_paste_still_uses_normalization(qt_app):
    _ = qt_app
    editor = MarkdownEditor(read_only=False)
    try:
        mime = QMimeData()
        mime.setText("Kuenstler*innen")
        editor.insertFromMimeData(mime)
        assert "Kuenstler\\*innen" in str(editor.toPlainText() or "")
    finally:
        editor.deleteLater()


def test_markdown_editor_drop_local_image_url_saves_and_inserts_markdown(
    monkeypatch,
    tmp_path: Path,
    qt_app,
):
    _ = qt_app
    source_file = tmp_path / "source.png"
    image = QImage(14, 9, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.blue)
    assert image.save(str(source_file), "PNG")

    editor = MarkdownEditor(read_only=False)
    try:
        target_dir = tmp_path / "stored"
        monkeypatch.setattr(
            editor,
            "_resolve_image_storage_target",
            lambda: (target_dir, "assets/clipboard"),
        )

        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(source_file))])

        assert editor.canInsertFromMimeData(mime) is True
        editor.insertFromMimeData(mime)

        text = str(editor.toPlainText() or "")
        match = re.search(
            r"!\[clipboard-image\]\(<assets/clipboard/([^>]+)>\)",
            text,
        )
        assert match is not None
        saved_path = target_dir / str(match.group(1))
        assert saved_path.exists()
        assert saved_path.read_bytes() == source_file.read_bytes()
    finally:
        editor.deleteLater()


def test_editor_panel_toolbar_button_calls_paste_image_handler(qt_app, monkeypatch):
    _ = qt_app
    panel = EditorPanel(read_only=False, show_toolbar=True)
    try:
        called = {"value": 0}

        def _fake_paste():
            called["value"] += 1
            return True

        monkeypatch.setattr(panel.editor, "paste_image_from_clipboard", _fake_paste)
        assert panel.paste_image_btn is not None
        panel.paste_image_btn.click()
        assert called["value"] == 1
    finally:
        panel.deleteLater()


def test_markdown_editor_text_path_paste_saves_and_inserts_markdown(
    monkeypatch,
    tmp_path: Path,
    qt_app,
):
    _ = qt_app
    source_file = tmp_path / "disk_image.png"
    image = QImage(10, 10, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.green)
    assert image.save(str(source_file), "PNG")

    editor = MarkdownEditor(read_only=False)
    try:
        target_dir = tmp_path / "stored_text_path"
        monkeypatch.setattr(
            editor,
            "_resolve_image_storage_target",
            lambda: (target_dir, "assets/clipboard"),
        )
        mime = QMimeData()
        mime.setText(str(source_file))

        assert editor.canInsertFromMimeData(mime) is True
        editor.insertFromMimeData(mime)

        text = str(editor.toPlainText() or "")
        match = re.search(
            r"!\[clipboard-image\]\(<assets/clipboard/([^>]+)>\)",
            text,
        )
        assert match is not None
        saved = target_dir / str(match.group(1))
        assert saved.exists()
        assert saved.read_bytes() == source_file.read_bytes()
    finally:
        editor.deleteLater()


def test_markdown_editor_markdown_image_url_paste_downloads_to_local_asset(
    monkeypatch,
    tmp_path: Path,
    qt_app,
):
    _ = qt_app
    payload_file = tmp_path / "remote_payload.png"
    image = QImage(11, 7, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.yellow)
    assert image.save(str(payload_file), "PNG")
    payload = payload_file.read_bytes()

    editor = MarkdownEditor(read_only=False)
    try:
        target_dir = tmp_path / "stored_remote"
        monkeypatch.setattr(
            editor,
            "_resolve_image_storage_target",
            lambda: (target_dir, "assets/clipboard"),
        )
        monkeypatch.setattr(
            editor,
            "_fetch_remote_image_bytes",
            lambda _url: (payload, ".png"),
        )

        mime = QMimeData()
        mime.setText("![Attention Is All You Need](https://example.com/image.png)")
        editor.insertFromMimeData(mime)

        text = str(editor.toPlainText() or "")
        assert "https://example.com/image.png" not in text
        match = re.search(
            r"!\[Attention Is All You Need\]\(<assets/clipboard/([^>]+)>\)",
            text,
        )
        assert match is not None
        saved = target_dir / str(match.group(1))
        assert saved.exists()
        assert saved.read_bytes() == payload
    finally:
        editor.deleteLater()


def test_markdown_editor_markdown_image_url_paste_inserts_failure_marker_when_download_fails(
    monkeypatch,
    tmp_path: Path,
    qt_app,
):
    _ = qt_app
    editor = MarkdownEditor(read_only=False)
    try:
        monkeypatch.setattr(
            editor,
            "_resolve_image_storage_target",
            lambda: (tmp_path, "assets/clipboard"),
        )
        monkeypatch.setattr(editor, "_fetch_remote_image_bytes", lambda _url: None)
        mime = QMimeData()
        mime.setText("![img](https://example.com/blocked.png)")
        editor.insertFromMimeData(mime)

        text = str(editor.toPlainText() or "")
        assert "https://example.com/blocked.png" not in text
        assert "<!-- image-copy-failed -->" in text
    finally:
        editor.deleteLater()


def test_markdown_editor_browser_clipboard_uses_single_source_no_duplicates(
    monkeypatch,
    tmp_path: Path,
    qt_app,
):
    _ = qt_app
    editor = MarkdownEditor(read_only=False)
    try:
        monkeypatch.setattr(
            editor,
            "_resolve_image_storage_target",
            lambda: (tmp_path, "assets/clipboard"),
        )
        monkeypatch.setattr(
            editor,
            "_fetch_remote_image_bytes",
            lambda _url: (_ for _ in ()).throw(AssertionError("remote download should not run")),
        )

        image = QImage(13, 9, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.cyan)
        mime = QMimeData()
        mime.setImageData(image)
        mime.setText("![alt](https://example.com/image.jpg)")

        editor.insertFromMimeData(mime)
        text = str(editor.toPlainText() or "")
        matches = re.findall(
            r"!\[[^\]]+\]\(<assets/clipboard/([^>]+)>\)",
            text,
        )
        assert len(matches) == 1
    finally:
        editor.deleteLater()


def test_markdown_editor_deduplicates_duplicate_local_urls(
    monkeypatch,
    tmp_path: Path,
    qt_app,
):
    _ = qt_app
    source_file = tmp_path / "dup_source.png"
    image = QImage(12, 12, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.magenta)
    assert image.save(str(source_file), "PNG")

    editor = MarkdownEditor(read_only=False)
    try:
        monkeypatch.setattr(
            editor,
            "_resolve_image_storage_target",
            lambda: (tmp_path / "store_dup", "assets/clipboard"),
        )
        mime = QMimeData()
        local_url = QUrl.fromLocalFile(str(source_file))
        mime.setUrls([local_url, local_url])

        editor.insertFromMimeData(mime)
        text = str(editor.toPlainText() or "")
        matches = re.findall(
            r"!\[[^\]]+\]\(<assets/clipboard/([^>]+)>\)",
            text,
        )
        assert len(matches) == 1
    finally:
        editor.deleteLater()
