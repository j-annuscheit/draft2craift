from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from studio.chat.dock_parts import send_actions


class _ChatDockStub:
    def __init__(self) -> None:
        self._aux_generating = False
        self._user_mode = "expert"
        self._last_use_case = ""
        self.history = SimpleNamespace(
            add_message=Mock(),
            reset_feedback=Mock(),
            activate_feedback=Mock(),
        )
        self.input_box = SimpleNamespace(toPlainText=lambda: "Konzentriere dich auf Risiken")
        self.llm = SimpleNamespace(
            worker=SimpleNamespace(isRunning=lambda: False),
        )
        self._mindmap_calls: list[dict[str, object]] = []

        def _handler(
            ctx,
            query_raw="",
            mode_hint="auto",
            map_depth=0,
            done_cb=None,
        ):
            self._mindmap_calls.append(
                {
                    "ctx": dict(ctx or {}),
                    "query_raw": str(query_raw or ""),
                    "mode_hint": str(mode_hint or ""),
                    "map_depth": int(map_depth or 0),
                    "done_cb": done_cb,
                }
            )
            return True, ""

        self._mindmap_request_handler = _handler

    def _collect_shared_context(self) -> dict:
        return {"selected_text": "Kontext", "user_query": ""}

    def _has_any_context_content(self, ctx: dict) -> bool:
        return bool(ctx)

    def _require_loaded_model(self) -> bool:
        return True


class ChatMindmapSendActionsTests(unittest.TestCase):
    def test_graph_generation_passes_map_depth_to_handler(self):
        dock = _ChatDockStub()
        with patch.object(
            send_actions.QInputDialog,
            "getItem",
            return_value=("Graph", True),
        ), patch.object(
            send_actions,
            "_prompt_map_depth_for_mode",
            return_value=4,
        ):
            send_actions._send_mindmap_generation(dock)

        self.assertEqual(len(dock._mindmap_calls), 1)
        call = dock._mindmap_calls[0]
        self.assertEqual(call["mode_hint"], "graph")
        self.assertEqual(call["map_depth"], 4)
        self.assertEqual(call["query_raw"], "Konzentriere dich auf Risiken")

    def test_slider_cancel_stops_request_before_handler(self):
        dock = _ChatDockStub()
        with patch.object(
            send_actions.QInputDialog,
            "getItem",
            return_value=("MindMap", True),
        ), patch.object(
            send_actions,
            "_prompt_map_depth_for_mode",
            return_value=None,
        ):
            send_actions._send_mindmap_generation(dock)

        self.assertEqual(dock._mindmap_calls, [])


if __name__ == "__main__":
    unittest.main()
