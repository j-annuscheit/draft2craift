from __future__ import annotations

from types import SimpleNamespace

from shared.services.agentic.settings import AgenticRuntimeSettings
from studio.controllers.llm_tasks_finalize import _finalize_mindmap


class _TabsStub:
    def __init__(self) -> None:
        self.rows: list[dict[str, object]] = []

    def add_tab(self, **kwargs) -> None:
        self.rows.append(dict(kwargs or {}))


class _FeedbackStub:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def activate(self, key: str) -> None:
        self.calls.append(str(key or ""))


class _ControllerStub:
    def __init__(self, *, detail_level: str, user_mode: str) -> None:
        self._settings = AgenticRuntimeSettings.from_dict(
            {"map_result_detail_level": detail_level}
        )
        self._user_mode_value = str(user_mode or "")
        self._canvas = SimpleNamespace(tabs=_TabsStub())
        self._glossary_feedback_bar = _FeedbackStub()
        self.status_calls: list[tuple[str, int]] = []
        self.autosave_calls: list[int] = []
        self.payloads: list[dict[str, object]] = []

    def _get_agentic_settings(self) -> AgenticRuntimeSettings:
        return self._settings

    def _get_user_mode(self) -> str:
        return self._user_mode_value

    def _show_status(self, text: str, timeout_ms: int) -> None:
        self.status_calls.append((str(text or ""), int(timeout_ms)))

    def _autosave_schedule_fn(self, delay_ms: int) -> None:
        self.autosave_calls.append(int(delay_ms))

    def _set_status_feedback_payload(self, payload: dict[str, object]) -> None:
        self.payloads.append(dict(payload or {}))


def test_finalize_mindmap_recovers_stats_from_markdown_when_meta_is_empty():
    ctrl = _ControllerStub(detail_level="compact", user_mode="simple")
    ok, info = _finalize_mindmap(
        ctrl,
        markdown="```mindmap\n- Root\n  - Child\n```",
        meta={"kind": "mindmap", "reason": "agentic", "nodes": 0, "edges": 0},
        context_text="Kontext",
        query="",
        mode="mindmap",
    )

    assert ok is True
    assert "2 Knoten" in info
    assert "1 Verbindung" in info
    assert "0 Knoten" not in info
    assert ctrl.status_calls
    assert "Tiefe 2" in ctrl.status_calls[-1][0]


def test_finalize_graph_uses_detailed_agentic_summary_when_requested():
    ctrl = _ControllerStub(detail_level="auto", user_mode="expert")
    ok, info = _finalize_mindmap(
        ctrl,
        markdown=(
            "```graph\n"
            '{"type":"graph","title":"G","nodes":[{"id":"a","label":"Alpha"},{"id":"b","label":"Beta"}],'
            '"edges":[{"from":"a","to":"b","label":"rel"}]}'
            "\n```"
        ),
        meta={
            "kind": "graph",
            "variant": "graph",
            "reason": "agentic",
            "components": 1,
            "max_depth": 1,
            "workflow_id": "graph_agentic",
            "profile_id": "graph_connected_component",
            "graph_closure_round": 1,
            "expand_round": 2,
            "cleanup": {"renamed_nodes": 2},
            "candidate_review": {"accepted": False, "reason": "candidate_broke_validation"},
            "metrics": {
                "elapsed_ms": 1234.0,
                "steps": 9,
                "tool_calls": {"llm.generate": 3},
                "trace_path": "runs/agentic/demo_graph.json",
            },
        },
        context_text="Kontext",
        query="Verbinde die Kernbegriffe",
        mode="graph",
    )

    assert ok is True
    assert "2 Knoten, 1 Verbindung" in info
    assert "Fokus: Verbinde die Kernbegriffe" in info
    assert "Schleifen: Closure 1, Expand 2." in info
    assert "Cleanup: 2 normalisiert." in info
    assert "Stabilisierung: letzter Kandidat verworfen" in info
    assert "Agentic: Profil graph_connected_component | Workflow graph_agentic." in info
    assert "Trace: runs/agentic/demo_graph.json" in info
