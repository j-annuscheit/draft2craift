from __future__ import annotations

import unittest

import pytest

from studio.chat.history import ChatHistoryWidget


pytestmark = pytest.mark.usefixtures("qt_app")


class ChatHistorySessionsTests(unittest.TestCase):
    def test_export_sessions_contains_all_tabs(self):
        widget = ChatHistoryWidget()
        widget.add_message("user", "Hallo")
        widget.add_tab("Zweiter Chat")
        widget.add_message("assistant", "Antwort 2")

        payload = widget.export_sessions()
        tabs = payload.get("tabs", [])

        self.assertEqual(len(tabs), 2)
        self.assertEqual(tabs[0]["history"][0]["content"], "Hallo")
        self.assertEqual(tabs[1]["title"], "Zweiter Chat")
        self.assertEqual(tabs[1]["history"][0]["content"], "Antwort 2")
        widget.deleteLater()

    def test_import_sessions_supports_new_and_legacy_format(self):
        widget = ChatHistoryWidget()
        payload = {
            "current_tab": 1,
            "tabs": [
                {
                    "title": "A",
                    "view_mode": "markdown",
                    "history": [{"role": "user", "content": "eins"}],
                },
                {
                    "title": "B",
                    "view_mode": "preview",
                    "history": [{"role": "assistant", "content": "zwei"}],
                },
            ],
        }

        widget.import_sessions(payload)
        exported = widget.export_sessions()
        self.assertEqual(len(exported.get("tabs", [])), 2)
        self.assertEqual(exported.get("current_tab"), 1)
        self.assertEqual(exported["tabs"][0]["title"], "A")
        self.assertEqual(exported["tabs"][1]["history"][0]["content"], "zwei")

        legacy = [{"role": "user", "content": "legacy"}]
        widget.import_sessions(legacy)
        exported_legacy = widget.export_sessions()
        self.assertEqual(len(exported_legacy.get("tabs", [])), 1)
        self.assertEqual(
            exported_legacy["tabs"][0]["history"][0]["content"],
            "legacy",
        )
        widget.deleteLater()


if __name__ == "__main__":
    unittest.main()
