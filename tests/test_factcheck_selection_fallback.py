from __future__ import annotations

import unittest

from features.chat.factcheck_pipeline import FactCheckPipelineMixin


class _LLMStub:
    def is_model_loaded(self) -> bool:
        return True

    def is_nli_model_loaded(self) -> bool:
        return True


class _HistoryStub:
    def __init__(self):
        self.messages: list[tuple[str, str]] = []
        self.feedback_resets = 0

    def add_message(self, role: str, message: str):
        self.messages.append((role, message))

    def reset_feedback(self):
        self.feedback_resets += 1


class _InputStub:
    def __init__(self, text: str = ""):
        self._text = str(text or "")

    def toPlainText(self) -> str:
        return self._text


class _CanvasStub:
    def __init__(self, selected: str):
        self._selected = str(selected or "")

    def get_selected_text(self, *, allow_cached: bool = True) -> str:
        _ = allow_cached
        return self._selected


class _HostStub:
    def __init__(self, selected: str):
        self.canvas = _CanvasStub(selected)


class _DockProxy(FactCheckPipelineMixin):
    def __init__(self):
        self.llm = _LLMStub()
        self.history = _HistoryStub()
        self.input_box = _InputStub("")
        self._aux_generating = False
        self._context_getter = None
        self._canvas_selection_getter = None
        self._pending_apply_to_canvas = False
        self._pending_selected_text = ""
        self._pending_user_message = ""
        self._start_extract_called = False

        self._ctx = {
            "grounding_has_sources": True,
            "file_contents": [("Doc A", "Quelle A")],
            "rag_results": [],
            "selected_text": "",
        }
        self._host = _HostStub("PARENT-AUSWAHL")

    def _collect_shared_context(self) -> dict:
        return dict(self._ctx)

    def _start_fact_extract_call(self):
        self._start_extract_called = True

    def parent(self):
        return self._host


class FactcheckSelectionFallbackTests(unittest.TestCase):
    def test_send_fact_check_uses_explicit_canvas_selection_getter(self):
        dock = _DockProxy()
        dock._canvas_selection_getter = lambda: "GETTER-AUSWAHL"

        dock._send_fact_check()

        self.assertTrue(dock._start_extract_called)
        self.assertEqual(dock._pending_fact_target_text, "GETTER-AUSWAHL")
        self.assertEqual(
            dock._pending_fact_target_label,
            "markierte Draft-Auswahl",
        )

    def test_send_fact_check_uses_parent_canvas_selection_fallback(self):
        dock = _DockProxy()
        dock._canvas_selection_getter = None
        dock._host = _HostStub("PARENT-AUSWAHL")

        dock._send_fact_check()

        self.assertTrue(dock._start_extract_called)
        self.assertEqual(dock._pending_fact_target_text, "PARENT-AUSWAHL")
        self.assertEqual(
            dock._pending_fact_target_label,
            "markierte Draft-Auswahl",
        )


if __name__ == "__main__":
    unittest.main()
