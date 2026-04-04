from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import shared.services.agentic as agentic_pkg
from shared.services.agentic.contracts import WorkflowRunResult
from shared.services.agentic.settings import AgenticRuntimeSettings
from studio.controllers.llm_tasks import MindmapTaskRequest, _LLMSideTaskWorker


@dataclass
class _LLMWorkerStub:
    def count_tokens(self, _text: str) -> int:
        return 16

    def context_window(self, _default_n_ctx: int = 4096) -> int:
        return 4096

    def run_completion_sync(self, _prompt: str, **_kwargs) -> str:
        return ""


@dataclass
class _LLMManagerStub:
    worker: _LLMWorkerStub


class _RagStub:
    def search(self, _query: str, top_k: int = 8):
        _ = top_k
        return []


def _cleanup_artifact_from_done(done: list[object]) -> None:
    if not done:
        return
    meta = dict(getattr(done[0], "meta", {}) or {})
    artifact_path = str(meta.get("run_artifact_path", "") or "").strip()
    if not artifact_path:
        return
    try:
        Path(artifact_path).unlink(missing_ok=True)
    except Exception:
        pass


def test_worker_forwards_mindmap_agentic_retrieval_settings(monkeypatch):
    captured: dict[str, object] = {}

    class _SvcStub:
        def run_mindmap(self, **kwargs):
            captured.update(kwargs)
            return WorkflowRunResult(
                ok=True,
                workflow_id="mindmap_v2",
                profile_id=str(kwargs.get("profile_id", "") or ""),
                result={"markdown": "```mindmap\nRoot\n```"},
                state={},
                trace=[],
                errors=[],
                metrics={},
            )

    monkeypatch.setattr(agentic_pkg, "AgenticWorkflowService", _SvcStub, raising=True)

    settings = AgenticRuntimeSettings.from_dict(
        {
            "mindmap_enabled": True,
            "mindmap_profile_id": "mindmap_v2_local",
            "mindmap_retrieval_strategy": "agent",
            "mindmap_agent_max_iterations": 9,
            "mindmap_factcheck": True,
            "mindmap_max_nodes": 42,
            "mindmap_max_refinement_rounds": 2,
        }
    )
    worker = _LLMSideTaskWorker(
        _LLMManagerStub(worker=_LLMWorkerStub()),
        request=MindmapTaskRequest(
            context_text="Kontext",
            query="Attention",
            mode="mindmap",
            max_nodes=32,
        ),
        agentic_settings=settings,
        rag_system=_RagStub(),
    )

    done: list[object] = []
    failed: list[str] = []
    worker.finished.connect(lambda payload: done.append(payload))
    worker.failed.connect(lambda msg: failed.append(str(msg)))

    worker.run()

    assert failed == []
    assert done
    request_payload = dict(captured.get("request", {}) or {})
    assert str(request_payload.get("retrieval_strategy", "")) == "agent"
    assert int(request_payload.get("agent_max_iterations", 0)) == 9
    assert bool(request_payload.get("factcheck", False)) is True
    assert int(request_payload.get("max_nodes", 0)) == 42
    assert int(request_payload.get("max_refinement_rounds", 0)) == 2
    assert bool(request_payload.get("log_draft_markdown", True)) is False
    payload_meta = dict(getattr(done[0], "meta", {}) or {})
    artifact_path = str(payload_meta.get("run_artifact_path", "") or "").strip()
    assert artifact_path
    artifact_file = Path(artifact_path)
    assert artifact_file.exists()
    assert "trace_steps" in payload_meta
    try:
        artifact_file.unlink(missing_ok=True)
    except Exception:
        pass


def test_worker_prefers_request_overrides_for_mindmap_agentic_settings(monkeypatch):
    captured: dict[str, object] = {}

    class _SvcStub:
        def run_mindmap(self, **kwargs):
            captured.update(kwargs)
            return WorkflowRunResult(
                ok=True,
                workflow_id="mindmap_v2",
                profile_id=str(kwargs.get("profile_id", "") or ""),
                result={"markdown": "```mindmap\nRoot\n```"},
                state={},
                trace=[],
                errors=[],
                metrics={},
            )

    monkeypatch.setattr(agentic_pkg, "AgenticWorkflowService", _SvcStub, raising=True)

    settings = AgenticRuntimeSettings.from_dict(
        {
            "mindmap_enabled": True,
            "mindmap_profile_id": "mindmap_v2_local",
            "mindmap_retrieval_strategy": "rag",
            "mindmap_agent_max_iterations": 5,
            "mindmap_factcheck": True,
            "mindmap_max_nodes": 32,
            "mindmap_max_refinement_rounds": 1,
        }
    )
    worker = _LLMSideTaskWorker(
        _LLMManagerStub(worker=_LLMWorkerStub()),
        request=MindmapTaskRequest(
            context_text="Kontext",
            query="Attention",
            mode="mindmap",
            override_retrieval_strategy="agent",
            override_agent_max_iterations=11,
            override_factcheck=False,
            override_max_nodes=77,
            override_max_refinement_rounds=3,
            override_log_draft_markdown=True,
        ),
        agentic_settings=settings,
        rag_system=_RagStub(),
    )

    done: list[object] = []
    failed: list[str] = []
    worker.finished.connect(lambda payload: done.append(payload))
    worker.failed.connect(lambda msg: failed.append(str(msg)))

    worker.run()

    assert failed == []
    assert done
    request_payload = dict(captured.get("request", {}) or {})
    assert str(request_payload.get("retrieval_strategy", "")) == "agent"
    assert int(request_payload.get("agent_max_iterations", 0)) == 11
    assert bool(request_payload.get("factcheck", True)) is False
    assert int(request_payload.get("max_nodes", 0)) == 77
    assert int(request_payload.get("max_refinement_rounds", 0)) == 3
    assert bool(request_payload.get("log_draft_markdown", False)) is True
    _cleanup_artifact_from_done(done)


def test_worker_handles_none_refinement_setting_without_crash(monkeypatch):
    captured: dict[str, object] = {}

    class _SvcStub:
        def run_mindmap(self, **kwargs):
            captured.update(kwargs)
            return WorkflowRunResult(
                ok=True,
                workflow_id="mindmap_v2",
                profile_id=str(kwargs.get("profile_id", "") or ""),
                result={"markdown": "```mindmap\nRoot\n```"},
                state={},
                trace=[],
                errors=[],
                metrics={},
            )

    monkeypatch.setattr(agentic_pkg, "AgenticWorkflowService", _SvcStub, raising=True)

    settings = AgenticRuntimeSettings.from_dict(
        {
            "mindmap_enabled": True,
            "mindmap_profile_id": "mindmap_v2_local",
            "mindmap_retrieval_strategy": "rag",
            "mindmap_agent_max_iterations": 7,
            "mindmap_factcheck": True,
            "mindmap_max_nodes": 40,
            "mindmap_max_refinement_rounds": None,
        }
    )
    worker = _LLMSideTaskWorker(
        _LLMManagerStub(worker=_LLMWorkerStub()),
        request=MindmapTaskRequest(
            context_text="Kontext",
            query="Attention",
            mode="mindmap",
        ),
        agentic_settings=settings,
        rag_system=_RagStub(),
    )

    done: list[object] = []
    failed: list[str] = []
    worker.finished.connect(lambda payload: done.append(payload))
    worker.failed.connect(lambda msg: failed.append(str(msg)))

    worker.run()

    assert failed == []
    assert done
    request_payload = dict(captured.get("request", {}) or {})
    assert int(request_payload.get("max_refinement_rounds", -1)) == 1
    _cleanup_artifact_from_done(done)


def test_worker_request_payload_has_no_expand_fields(monkeypatch):
    captured: dict[str, object] = {}

    class _SvcStub:
        def run_mindmap(self, **kwargs):
            captured.update(kwargs)
            return WorkflowRunResult(
                ok=True,
                workflow_id="mindmap_v2",
                profile_id=str(kwargs.get("profile_id", "") or ""),
                result={"markdown": "```mindmap\nRoot\n```"},
                state={},
                trace=[],
                errors=[],
                metrics={},
            )

    monkeypatch.setattr(agentic_pkg, "AgenticWorkflowService", _SvcStub, raising=True)

    settings = AgenticRuntimeSettings.from_dict(
        {
            "mindmap_enabled": True,
            "mindmap_profile_id": "mindmap_v2_local",
            "mindmap_retrieval_strategy": "agent",
            "mindmap_agent_max_iterations": 7,
            "mindmap_factcheck": True,
            "mindmap_max_nodes": 40,
            "mindmap_max_refinement_rounds": 1,
        }
    )
    worker = _LLMSideTaskWorker(
        _LLMManagerStub(worker=_LLMWorkerStub()),
        request=MindmapTaskRequest(
            context_text="Kontext",
            query="Vertiefe Attention",
            mode="mindmap",
        ),
        agentic_settings=settings,
        rag_system=_RagStub(),
    )

    done: list[object] = []
    failed: list[str] = []
    worker.finished.connect(lambda payload: done.append(payload))
    worker.failed.connect(lambda msg: failed.append(str(msg)))

    worker.run()

    assert failed == []
    assert done
    request_payload = dict(captured.get("request", {}) or {})
    assert "expand_existing_map" not in request_payload
    assert "expand_target_node" not in request_payload
    assert "existing_map_markdown" not in request_payload
    assert "existing_map_source" not in request_payload
    _cleanup_artifact_from_done(done)
