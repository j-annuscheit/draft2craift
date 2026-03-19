from __future__ import annotations

import unittest
from unittest.mock import Mock

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

    def test_import_sessions_supports_structured_format(self):
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
        widget.deleteLater()

    def test_activate_tab_by_title_switches_current_tab(self):
        widget = ChatHistoryWidget()
        widget.add_tab("Zweiter Chat")

        switched = widget.activate_tab_by_title("Zweiter Chat")

        self.assertTrue(switched)
        self.assertEqual(widget.current_tab_title(), "Zweiter Chat")
        widget.deleteLater()

    def test_jump_to_highlight_prefers_requested_tab_title(self):
        widget = ChatHistoryWidget()
        widget.add_tab("Zweiter Chat")
        tabs = getattr(widget, "_tabs")
        first_page = tabs.widget(0)
        second_page = tabs.widget(1)
        first_display = widget._sessions[first_page].display
        second_display = widget._sessions[second_page].display
        first_display.jump_to_highlight = Mock(return_value=False)
        second_display.jump_to_highlight = Mock(return_value=True)

        jumped = widget.jump_to_highlight(
            "hl_target",
            preferred_tab_titles=["Zweiter Chat"],
        )

        self.assertTrue(jumped)
        self.assertGreaterEqual(second_display.jump_to_highlight.call_count, 1)
        self.assertEqual(widget.current_tab_title(), "Zweiter Chat")
        widget.deleteLater()

    def test_attach_last_assistant_thinking_exports_metadata(self):
        widget = ChatHistoryWidget()
        widget.begin_streaming("assistant")
        widget.append_token("Antwort")
        widget.finish_streaming()
        widget.attach_last_assistant_thinking("internal chain")

        payload = widget.export_sessions()
        row = payload["tabs"][0]["history"][-1]
        self.assertEqual(row["content"], "Antwort")
        self.assertEqual(row.get("think"), "internal chain")
        widget.deleteLater()

    def test_import_sessions_restores_thinking_hover_metadata(self):
        widget = ChatHistoryWidget()
        payload = {
            "current_tab": 0,
            "tabs": [
                {
                    "title": "A",
                    "view_mode": "preview",
                    "history": [
                        {
                            "role": "assistant",
                            "content": "sichtbar",
                            "think": "intern",
                        }
                    ],
                }
            ],
        }

        widget.import_sessions(payload)
        exported = widget.export_sessions()
        self.assertEqual(exported["tabs"][0]["history"][0].get("think"), "intern")
        panel = widget.current_panel()
        preview = getattr(panel, "_preview", None) if panel is not None else None
        link_tips = dict(getattr(preview, "_link_tooltips", {}) or {})
        self.assertEqual(len(link_tips), 1)
        self.assertEqual(next(iter(link_tips.values())), "intern")
        widget.deleteLater()

    def test_streaming_thinking_marker_is_inserted_before_visible_answer(self):
        widget = ChatHistoryWidget()
        widget.begin_streaming("assistant")
        widget.append_streaming_thinking_token("denken")
        widget.append_token("Antwort")
        widget.finish_streaming()

        panel = widget.current_panel()
        text = panel.editor.toPlainText() if panel is not None else ""
        self.assertIn("Thinking", text)
        self.assertIn("Antwort", text)
        self.assertLess(text.find("Thinking"), text.find("Antwort"))

        payload = widget.export_sessions()
        row = payload["tabs"][0]["history"][-1]
        self.assertEqual(row.get("think"), "denken")
        widget.deleteLater()


if __name__ == "__main__":
    unittest.main()
