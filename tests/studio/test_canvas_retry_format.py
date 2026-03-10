from __future__ import annotations

import unittest

from studio.chat.dock import ChatDock
from shared.services.llm.manager import CANVAS_REWRITE_CLOSE, CANVAS_REWRITE_OPEN


class CanvasRetryFormatTests(unittest.TestCase):
    def test_retry_message_enforces_canvas_wrapper(self):
        msg = ChatDock._canvas_rewrite_retry_user_message()
        self.assertIn(CANVAS_REWRITE_OPEN, msg)
        self.assertIn(CANVAS_REWRITE_CLOSE, msg)
        self.assertIn("TEXT_DER_DEN_ZU_ERSETZENDEN_TEXT_ERSETZT", msg)
        self.assertIn("Aufgabe bleibt unverändert", msg)
        self.assertNotIn("<Text", msg)
        self.assertIn("Keine Erklärung", msg)

    def test_scope_retry_message_mentions_selected_area_only(self):
        msg = ChatDock._canvas_scope_retry_user_message()
        self.assertIn(CANVAS_REWRITE_OPEN, msg)
        self.assertIn(CANVAS_REWRITE_CLOSE, msg)
        self.assertIn("NUR den selektierten Bereich", msg)

    def test_detects_non_selected_canvas_repeat(self):
        draft = "Einleitung\nAUSWAHL\nSchlussteil"
        selected = "AUSWAHL"
        self.assertTrue(
            ChatDock._contains_non_selected_canvas_repeat(
                draft,
                selected,
                draft,
            )
        )
        self.assertFalse(
            ChatDock._contains_non_selected_canvas_repeat(
                draft,
                selected,
                "Überarbeitete Auswahl",
            )
        )

    def test_extract_selected_replacement_from_full_draft_exact_match(self):
        draft = "Teil A\nTeil B\nTeil C"
        selected = "Teil B"
        rewritten = "Teil A\nTeil B neu\nTeil C"
        self.assertEqual(
            ChatDock._extract_selected_replacement_from_full_draft(
                draft,
                selected,
                rewritten,
            ),
            "Teil B neu",
        )

    def test_extract_selected_replacement_from_full_draft_returns_empty_when_no_match(self):
        draft = "Teil A\nTeil B\nTeil C"
        selected = "Teil B"
        rewritten = "Komplett anderer Text"
        self.assertEqual(
            ChatDock._extract_selected_replacement_from_full_draft(
                draft,
                selected,
                rewritten,
            ),
            "",
        )

    def test_extract_selected_replacement_from_full_draft_requires_unique_decomposition(self):
        draft = "aaaa"
        selected = "a"
        rewritten = "aaaa"
        self.assertEqual(
            ChatDock._extract_selected_replacement_from_full_draft(
                draft,
                selected,
                rewritten,
            ),
            "",
        )

    def test_extract_selected_replacement_accepts_95_percent_prefix_suffix_match(self):
        prefix = "A" * 120
        suffix = "C" * 120
        draft = f"{prefix}BBB{suffix}"
        selected = "BBB"
        rewritten = f"{prefix[:-1]}ZNEU{suffix[:-1]}Y"
        self.assertEqual(
            ChatDock._extract_selected_replacement_from_full_draft(
                draft,
                selected,
                rewritten,
            ),
            "NEU",
        )

    def test_extract_selected_replacement_rejects_below_95_percent_prefix_match(self):
        prefix = "A" * 20
        suffix = "C" * 40
        draft = f"{prefix}BBB{suffix}"
        selected = "BBB"
        # 10% prefix drift (2/20) should not be accepted.
        rewritten = f"{prefix[:-2]}ZZNEU{suffix}"
        self.assertEqual(
            ChatDock._extract_selected_replacement_from_full_draft(
                draft,
                selected,
                rewritten,
            ),
            "",
        )

    def test_on_complete_uses_local_full_draft_fallback_for_strict_match(self):
        class _History:
            def __init__(self):
                self.messages = []
                self.feedback = []
                self.finished = False

            def finish_streaming(self):
                self.finished = True

            def add_message(self, role: str, message: str):
                self.messages.append((role, message))

            def activate_feedback(self, use_case: str):
                self.feedback.append(use_case)

        class _DockProxy:
            _extract_selected_replacement_from_full_draft = staticmethod(
                ChatDock._extract_selected_replacement_from_full_draft
            )
            _contains_non_selected_canvas_repeat = staticmethod(
                ChatDock._contains_non_selected_canvas_repeat
            )
            _canvas_scope_retry_user_message = staticmethod(
                ChatDock._canvas_scope_retry_user_message
            )
            _retry_canvas_rewrite_format = staticmethod(lambda *_args, **_kwargs: False)

            def __init__(self):
                self._history_stream_open = False
                self._pending_fact_check = False
                self._pending_apply_to_canvas = True
                self._pending_apply_context = {
                    "file_contents": [("Draft: test.md", "Teil A\nTeil B\nTeil C")],
                }
                self._pending_selected_text = "Teil B"
                self._pending_selected_span = None
                self._last_assistant_msg = ""
                self._last_use_case = ""
                self.history = _History()
                self._maybe_auto_read_response = lambda _response: None
                self.reset_called = False
                self.calls = []

                def _apply(
                    replacement: str,
                    expected_original: str,
                    preferred_span,
                ):
                    self.calls.append((replacement, expected_original, preferred_span))
                    if len(self.calls) == 1:
                        return (
                            False,
                            "Selection is ambiguous in source text. "
                            "Please select a more specific passage.",
                        )
                    return True, "Applied."

                self._selection_apply_handler = _apply

            def _reset_pending_canvas_rewrite(self):
                self.reset_called = True
                self._pending_apply_to_canvas = False

        proxy = _DockProxy()
        response = (
            f"{CANVAS_REWRITE_OPEN}\n"
            "Teil A\nTeil B neu\nTeil C\n"
            f"{CANVAS_REWRITE_CLOSE}"
        )

        ChatDock._on_complete(proxy, response)

        self.assertEqual(
            proxy.calls,
            [
                ("Teil B neu", "Teil B", None),
                ("Teil A\nTeil B neu\nTeil C", "Teil A\nTeil B\nTeil C", None),
            ],
        )
        self.assertTrue(proxy.reset_called)
        self.assertTrue(
            any(
                role == "system" and "✅ Selection updated in draft workspace." in msg
                for role, msg in proxy.history.messages
            )
        )
        self.assertNotIn(
            (
                "system",
                "⚠ Could not apply rewrite. Draft selection was not changed.",
            ),
            proxy.history.messages,
        )


if __name__ == "__main__":
    unittest.main()
