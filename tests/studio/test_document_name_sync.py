from __future__ import annotations

import unittest

import pytest

from studio.chat.context_panel import ContextSelectorPanel
from studio.knowledge.viewer_panel import DocumentViewerPanel
from studio.knowledge.files_panel import ImportedFilesPanel


pytestmark = pytest.mark.usefixtures("qt_app")


class DocumentNameSyncTests(unittest.TestCase):
    def test_imported_files_panel_rename_updates_checked_entries(self):
        panel = ImportedFilesPanel()
        panel.add_file("Alpha.md", "A")
        panel.add_file("Beta.md", "B")

        renamed = panel.rename_file("Alpha.md", "Alpha Renamed.md")
        self.assertEqual(renamed, "Alpha Renamed.md")

        checked = panel.get_checked_files()
        names = [name for name, _ in checked]
        self.assertIn("Alpha Renamed.md", names)
        self.assertNotIn("Alpha.md", names)
        panel.deleteLater()

    def test_context_panel_rename_preserves_checkbox_state(self):
        panel = ContextSelectorPanel()
        panel.add_document("Alpha.md", "A")
        panel.add_document("Beta.md", "B")
        panel._cbs["Alpha.md"].setChecked(True)

        renamed = panel.rename_document("Alpha.md", "Alpha Renamed.md")
        self.assertEqual(renamed, "Alpha Renamed.md")

        _use_canvas, _use_rag, docs = panel.get_selection()
        selected_names = [name for name, _ in docs]
        self.assertIn("Alpha Renamed.md", selected_names)
        self.assertNotIn("Alpha.md", selected_names)
        panel.deleteLater()

    def test_document_viewer_apply_document_rename_updates_all_doc_tabs(self):
        panel = DocumentViewerPanel()
        panel.open_content("Alpha.md", "First", doc_key="Alpha.md")
        panel.open_content("Alpha.md", "Second", doc_key="Alpha.md")

        changed = panel.apply_document_rename("Alpha.md", "Alpha Renamed.md")
        self.assertTrue(changed)

        tab_widget = panel.tabs.tab_widget
        renamed_count = 0
        for i in range(tab_widget.count()):
            doc_key = str(getattr(tab_widget.widget(i), "_doc_key", "") or "")
            if doc_key != "Alpha Renamed.md":
                continue
            renamed_count += 1
            self.assertEqual(
                panel.tabs.get_tab_full_title(i),
                "Alpha Renamed.md",
            )

        self.assertGreaterEqual(renamed_count, 2)
        panel.deleteLater()

    def test_document_viewer_emits_rename_request_signal(self):
        panel = DocumentViewerPanel()
        panel.open_content("Alpha.md", "Body", doc_key="Alpha.md")
        idx = panel.tabs.tab_widget.count() - 1

        events: list[tuple[str, str]] = []
        panel.document_rename_requested.connect(
            lambda old, new: events.append((str(old), str(new)))
        )

        panel.tabs.set_tab_full_title(idx, "Alpha Renamed.md")
        self.assertIn(("Alpha", "Alpha Renamed"), events)
        panel.deleteLater()


if __name__ == "__main__":
    unittest.main()
