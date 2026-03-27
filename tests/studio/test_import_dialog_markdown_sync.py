from __future__ import annotations

from shared.services.importer.entry import ImportEntry
from studio.importer.dialog_selection import FileImportSelectionMixin
from studio.importer.dialog_ui import FileImportDialogUIMixin
from studio.importer.ui_constants import _STATUS_DONE, _STATUS_PENDING


class _EditorStub:
    def __init__(self, text: str):
        self._text = text

    def toPlainText(self) -> str:
        return self._text


class _PreviewStub:
    def __init__(self, text: str):
        self.editor = _EditorStub(text)
        self.flush_calls = 0

    def flush_pending_preview_edits(self):
        self.flush_calls += 1


class _DialogSelectionStub(FileImportSelectionMixin):
    def __init__(self, entry: ImportEntry, preview_text: str):
        self._entries = {entry.path: entry}
        self._current_path = entry.path
        self._preview = _PreviewStub(preview_text)


class _SignalStub:
    def __init__(self):
        self.payload = None

    def emit(self, payload):
        self.payload = payload


class _DialogOpenStub(FileImportDialogUIMixin):
    def __init__(self, entry: ImportEntry):
        self._entries = {entry.path: entry}
        self._current_path = entry.path
        self.files_imported = _SignalStub()
        self.accepted = False
        self.sync_calls = 0

    def parent(self):
        return None

    def _has_running_background_worker(self) -> bool:
        return False

    def _prepare_for_handover_and_close(self):
        return None

    def _sync_current_markdown_from_preview(self):
        self.sync_calls += 1
        entry = self._entries[self._current_path]
        entry.markdown = "## edited markdown"

    def accept(self):
        self.accepted = True


def test_sync_current_markdown_from_preview_updates_done_entry():
    entry = ImportEntry(path="/tmp/a.md", name="a.md", markdown="old", status=_STATUS_DONE)
    dialog = _DialogSelectionStub(entry, "new content")

    dialog._sync_current_markdown_from_preview()

    assert entry.markdown == "new content"
    assert dialog._preview.flush_calls == 1


def test_sync_current_markdown_from_preview_ignores_pending_entry():
    entry = ImportEntry(path="/tmp/a.md", name="a.md", markdown="", status=_STATUS_PENDING)
    dialog = _DialogSelectionStub(entry, "# Placeholder")

    dialog._sync_current_markdown_from_preview()

    assert entry.markdown == ""
    assert dialog._preview.flush_calls == 0


def test_open_in_viewer_syncs_before_handover():
    entry = ImportEntry(path="/tmp/a.md", name="a.md", markdown="stale", status=_STATUS_DONE)
    dialog = _DialogOpenStub(entry)

    dialog._open_in_viewer()

    assert dialog.sync_calls == 1
    assert dialog.accepted is True
    assert dialog.files_imported.payload == [("a.md", "/tmp/a.md", "## edited markdown")]
