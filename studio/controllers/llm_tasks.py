"""LLM side-task controller — glossary and mindmap generation."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import json
from pathlib import Path
import tempfile
from uuid import uuid4

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtWidgets import QMessageBox
from shared.services.agentic.settings import AgenticRuntimeSettings
from shared.services.highlights.store import get_highlight_store
from shared.services.llm.manager import LLMManager
from studio.glossary.editor import GlossaryEditorDialog
from studio.controllers.llm_task_context import LLMTaskContext
from studio.controllers.llm_tasks_context import (
    _build_context_text_from_llm_context as _build_context_text_from_llm_context_fn,
    _empty_context_error as _empty_context_error_fn,
    _fallback_context_text_from_ctx as _fallback_context_text_from_ctx_fn,
    _resolve_mindmap_mode_and_query as _resolve_mindmap_mode_and_query_fn,
)
from studio.controllers.llm_tasks_finalize import (
    _finalize_glossary as _finalize_glossary_fn,
    _finalize_mindmap as _finalize_mindmap_fn,
)


# ── Typed side-task contracts ──────────────────────────────────────────────────


@dataclass(frozen=True)
class GlossaryTaskRequest:
    context_text: str
    max_terms: int = 32
    query: str = ""


@dataclass(frozen=True)
class MindmapTaskRequest:
    context_text: str
    query: str
    mode: str = "mindmap"
    max_nodes: int = 32
    chunking_strategy: str = "sliding_window"
    chunk_size: int = 900
    chunk_overlap: int = 160
    map_depth: int = 0
    override_retrieval_strategy: str = ""
    override_agent_max_iterations: int = 0
    override_factcheck: bool | None = None
    override_max_nodes: int = 0
    override_max_refinement_rounds: int = -1
    override_use_full_context: bool | None = None
    override_context_max_chars: int = 0
    override_allow_rag_search: bool | None = None
    override_allow_regex_search: bool | None = None
    override_allow_heading_search: bool | None = None
    override_allow_full_text_search: bool | None = None
    override_allow_query_narrowing: bool | None = None
    override_allow_heading_summaries: bool | None = None
    override_agent_max_regex_calls: int = -1
    override_agent_budget_points: float = 0.0
    override_budget_seconds: float = 0.0
    override_log_draft_markdown: bool | None = None


@dataclass(frozen=True)
class GlossaryTaskResult:
    context_text: str
    entries: list[dict[str, object]]
    meta: dict[str, object]


@dataclass(frozen=True)
class MindmapTaskResult:
    context_text: str
    query: str
    mode: str
    markdown: str
    meta: dict[str, object]


TaskRequest = GlossaryTaskRequest | MindmapTaskRequest
TaskResult = GlossaryTaskResult | MindmapTaskResult

_RAW_DRAFT_ARTIFACT_MAX_CHARS = 200_000
_RAW_DRAFT_META_MAX_CHARS = 60_000
_ARTIFACT_DEBUG_ROW_MAX_CHARS = 2_000


def _clip_text(value: object, *, max_chars: int = 280) -> str:
    text = str(value or "").strip()
    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - 3)].rstrip() + "..."


def _clip_raw_draft_text(value: object, *, max_chars: int) -> str:
    text = str(value or "")
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    if max_chars <= 16:
        return text[:max_chars]
    return text[: max_chars - 16] + "\n...[truncated]"


def _sanitize_for_json(value: object, *, max_chars: int = 280, _depth: int = 0) -> object:
    if _depth >= 4:
        return _clip_text(value, max_chars=max_chars)
    if isinstance(value, dict):
        out: dict[str, object] = {}
        for idx, (k, v) in enumerate(dict(value).items()):
            if idx >= 64:
                out["..."] = "truncated"
                break
            out[str(k)] = _sanitize_for_json(v, max_chars=max_chars, _depth=_depth + 1)
        return out
    if isinstance(value, list):
        out_list: list[object] = []
        for idx, row in enumerate(list(value)):
            if idx >= 64:
                out_list.append("truncated")
                break
            out_list.append(_sanitize_for_json(row, max_chars=max_chars, _depth=_depth + 1))
        return out_list
    if isinstance(value, tuple):
        return _sanitize_for_json(list(value), max_chars=max_chars, _depth=_depth)
    if isinstance(value, (str, int, float, bool)) or value is None:
        if isinstance(value, str):
            return _clip_text(value, max_chars=max_chars)
        return value
    return _clip_text(repr(value), max_chars=max_chars)


def _collect_trace_rows(run_result) -> list[dict[str, object]]:  # noqa: ANN001
    out: list[dict[str, object]] = []
    for row in list(getattr(run_result, "trace", []) or []):
        try:
            payload = asdict(row)
        except Exception:
            payload = {
                "step_id": str(getattr(row, "step_id", "") or ""),
                "status": str(getattr(row, "status", "") or ""),
                "duration_ms": float(getattr(row, "duration_ms", 0.0) or 0.0),
                "reason": str(getattr(row, "reason", "") or ""),
                "input": dict(getattr(row, "input", {}) or {}),
                "output": dict(getattr(row, "output", {}) or {}),
            }
        out.append(
            {
                "step_id": str(payload.get("step_id", "") or ""),
                "status": str(payload.get("status", "") or ""),
                "duration_ms": float(payload.get("duration_ms", 0.0) or 0.0),
                "reason": str(payload.get("reason", "") or ""),
                "input": _sanitize_for_json(payload.get("input", {}), max_chars=220),
                "output": _sanitize_for_json(payload.get("output", {}), max_chars=280),
            }
        )
    return out


def _write_agentic_run_artifact(
    *,
    mode: str,
    query: str,
    context_text: str,
    request_payload: dict[str, object],
    run_result,  # noqa: ANN001
) -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    token = uuid4().hex[:8]
    mode_slug = str(mode or "mindmap").strip().casefold() or "mindmap"
    root = Path.cwd() / "runs" / "agentic"
    try:
        root.mkdir(parents=True, exist_ok=True)
    except Exception:
        root = Path(tempfile.gettempdir()) / "d2c_runs" / "agentic"
        root.mkdir(parents=True, exist_ok=True)
    path = root / f"{mode_slug}_{stamp}_{token}.json"

    state = dict(getattr(run_result, "state", {}) or {})
    markdown = str(dict(getattr(run_result, "result", {}) or {}).get("markdown", "") or "")
    raw_draft_logged = bool(state.get("draft_markdown_logged", False))
    raw_draft = str(state.get("draft_markdown_raw", "") or "") if raw_draft_logged else ""
    state_payload = {
        "concepts": [str(x or "") for x in list(state.get("concepts", []) or [])[:128]],
        "search_queries": [str(x or "") for x in list(state.get("search_queries", []) or [])[:128]],
        "retrieval_agent_steps": [
            _sanitize_for_json(row, max_chars=_ARTIFACT_DEBUG_ROW_MAX_CHARS)
            for row in list(state.get("retrieval_agent_steps", []) or [])[:512]
        ],
        "retrieval_observations": [
            _clip_text(row, max_chars=_ARTIFACT_DEBUG_ROW_MAX_CHARS)
            for row in list(state.get("retrieval_observations", []) or [])[:512]
        ],
        "retrieval_policy": _sanitize_for_json(dict(state.get("retrieval_policy", {}) or {}), max_chars=1_200),
        "rag_snippets": [
            _clip_text(row, max_chars=_ARTIFACT_DEBUG_ROW_MAX_CHARS)
            for row in list(state.get("rag_snippets", []) or [])[:128]
        ],
        "fact_issues": [
            str(x or "")
            for x in list(state.get("fact_issues_list", state.get("fact_issues", [])) or [])[:128]
        ],
        "fact_verified": bool(state.get("fact_verified", False)),
        "structure_check": _sanitize_for_json(dict(state.get("structure_check", {}) or {}), max_chars=1_200),
        "structure_validation": _sanitize_for_json(dict(state.get("structure_validation", {}) or {}), max_chars=1_200),
        "grounding_validation": _sanitize_for_json(dict(state.get("grounding_validation", {}) or {}), max_chars=1_200),
        "grounding_issues": [str(x or "") for x in list(state.get("grounding_issues", []) or [])[:128]],
        "required_main_nodes": [str(x or "") for x in list(state.get("required_main_nodes", []) or [])[:64]],
        "missing_required_main_nodes": [
            str(x or "") for x in list(state.get("missing_required_main_nodes", []) or [])[:64]
        ],
        "draft_progress": [
            _sanitize_for_json(row, max_chars=_ARTIFACT_DEBUG_ROW_MAX_CHARS)
            for row in list(state.get("draft_progress", []) or [])[:128]
        ],
        "draft_markdown_logged": raw_draft_logged,
    }
    if raw_draft_logged and raw_draft:
        state_payload["draft_markdown_raw"] = _clip_raw_draft_text(
            raw_draft,
            max_chars=_RAW_DRAFT_ARTIFACT_MAX_CHARS,
        )
    payload = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "mode": str(mode or ""),
        "query": str(query or ""),
        "request": _sanitize_for_json(request_payload, max_chars=260),
        "workflow_id": str(getattr(run_result, "workflow_id", "") or ""),
        "profile_id": str(getattr(run_result, "profile_id", "") or ""),
        "ok": bool(getattr(run_result, "ok", False)),
        "errors": [str(x or "") for x in list(getattr(run_result, "errors", []) or [])],
        "metrics": _sanitize_for_json(dict(getattr(run_result, "metrics", {}) or {}), max_chars=280),
        "trace": _collect_trace_rows(run_result),
        "state": state_payload,
        "context_preview": _clip_text(context_text, max_chars=8000),
        "markdown_preview": _clip_text(markdown, max_chars=8000),
    }
    try:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(path)
    except Exception:
        return ""


def _agentic_map_meta(run_result, *, mode: str, run_artifact_path: str = "") -> dict[str, object]:  # noqa: ANN001
    state = dict(getattr(run_result, "state", {}) or {})
    metrics = dict(getattr(run_result, "metrics", {}) or {})
    structure_check = dict(state.get("structure_check", {}) or {})
    structure_validation = dict(state.get("structure_validation", {}) or {})
    nodes = int(structure_check.get("node_count", 0) or 0)
    edges = int(structure_check.get("edge_count", 0) or 0)
    components = int(structure_check.get("component_count", 0) or 0)
    trace_rows = _collect_trace_rows(run_result)
    retrieval_steps = list(state.get("retrieval_agent_steps", []) or [])
    retrieval_observations = list(state.get("retrieval_observations", []) or [])
    retrieval_policy = dict(state.get("retrieval_policy", {}) or {})
    rag_snippets = [str(x or "") for x in list(state.get("rag_snippets", []) or [])]
    fact_issues = [str(x or "") for x in list(state.get("fact_issues_list", state.get("fact_issues", [])) or [])]
    grounding_validation = dict(state.get("grounding_validation", {}) or {})
    grounding_issues = [str(x or "") for x in list(state.get("grounding_issues", []) or [])]
    required_main_nodes = list(
        state.get("required_main_nodes", metrics.get("required_main_nodes", [])) or []
    )
    missing_required_main_nodes = list(
        state.get(
            "missing_required_main_nodes",
            grounding_validation.get("missing_required_main_nodes", metrics.get("missing_required_main_nodes", [])),
        )
        or []
    )
    tool_calls = dict(metrics.get("tool_calls", {}) or {})
    retrieval_strategy = str(metrics.get("retrieval_strategy", state.get("retrieval_strategy", "")) or "")
    raw_draft_logged = bool(state.get("draft_markdown_logged", metrics.get("log_draft_markdown", False)))
    raw_draft = str(state.get("draft_markdown_raw", "") or "") if raw_draft_logged else ""

    meta = {
        "kind": str(mode or "mindmap"),
        "variant": str(mode or ""),
        "reason": "agentic",
        "nodes": nodes,
        "edges": edges,
        "roots": 0,
        "isolated_nodes": 0,
        "components": components,
        "max_depth": int(state.get("depth", 0) or 0),
        "root_label": str(state.get("root_label", "") or ""),
        "cleanup": {},
        "candidate_review": {},
        "workflow_id": str(getattr(run_result, "workflow_id", "") or ""),
        "profile_id": str(getattr(run_result, "profile_id", "") or ""),
        "errors": list(getattr(run_result, "errors", []) or []),
        "metrics": metrics,
        "trace_path": str(metrics.get("trace_path", "") or ""),
        "run_artifact_path": str(run_artifact_path or ""),
        "retrieval_strategy": retrieval_strategy,
        "agent_budget_controlled": bool(metrics.get("agent_budget_controlled", False)),
        "log_draft_markdown": raw_draft_logged,
        "tool_calls": tool_calls,
        "retrieval_agent_steps": _sanitize_for_json(retrieval_steps[:40], max_chars=240),
        "retrieval_observations": _sanitize_for_json(retrieval_observations[:40], max_chars=240),
        "retrieval_policy": _sanitize_for_json(retrieval_policy, max_chars=240),
        "rag_snippets_preview": [_clip_text(x, max_chars=260) for x in rag_snippets[:12]],
        "fact_issues_list": fact_issues[:20],
        "structure_validation": _sanitize_for_json(structure_validation, max_chars=240),
        "grounding_validation": _sanitize_for_json(grounding_validation, max_chars=240),
        "grounding_issues": grounding_issues[:20],
        "required_main_nodes": [str(x or "") for x in required_main_nodes[:12]],
        "missing_required_main_nodes": [str(x or "") for x in missing_required_main_nodes[:12]],
        "draft_progress": _sanitize_for_json(list(state.get("draft_progress", []) or [])[:64], max_chars=480),
        "trace_steps": trace_rows[:48],
        "trace_step_count": len(trace_rows),
        "trace_has_errors": any(str(row.get("status", "") or "").casefold() in {"error", "failed", "empty"} for row in trace_rows),
        "graph_closure_round": 0,
        "refine_round": 0,
        "expand_round": 0,
        "expansion_round": 0,
        "gap_round": 0,
        "coverage_ratio": 0.0,
    }
    if raw_draft_logged and raw_draft:
        meta["draft_markdown_raw"] = _clip_raw_draft_text(raw_draft, max_chars=_RAW_DRAFT_META_MAX_CHARS)
    return meta


# ── Worker ─────────────────────────────────────────────────────────────────────


class _LLMSideTaskWorker(QObject):
    """Runs non-streaming LLM side tasks in a background thread."""

    finished = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        llm_manager: LLMManager,
        *,
        request: TaskRequest,
        agentic_settings: AgenticRuntimeSettings | None = None,
        rag_system: object | None = None,
    ):
        super().__init__()
        self._llm_manager = llm_manager
        self._request = request
        self._agentic_settings = (
            agentic_settings.clone()
            if isinstance(agentic_settings, AgenticRuntimeSettings)
            else None
        )
        self._rag_system = rag_system

    def run(self):
        try:
            if isinstance(self._request, GlossaryTaskRequest):
                context_text = str(self._request.context_text or "")
                max_terms = int(self._request.max_terms or 32)
                query = str(self._request.query or "")
                entries, meta = self._llm_manager.generate_glossary_sync(
                    context_text=context_text,
                    max_terms=max_terms,
                    focus_query=query,
                )
                safe_entries = [
                    dict(row)
                    for row in list(entries or [])
                    if isinstance(row, dict)
                ]
                safe_meta = dict(meta or {}) if isinstance(meta, dict) else {}
                self.finished.emit(
                    GlossaryTaskResult(
                        context_text=context_text,
                        entries=safe_entries,
                        meta=safe_meta,
                    )
                )
                return

            if isinstance(self._request, MindmapTaskRequest):
                context_text = str(self._request.context_text or "")
                query = str(self._request.query or "")
                mode = str(self._request.mode or "mindmap")
                map_depth = max(0, min(12, int(self._request.map_depth or 0)))
                mode_clean = str(mode or "").strip().casefold()
                workflow_key = "graph" if mode_clean == "graph" else "mindmap"
                agentic_opts = (
                    self._agentic_settings.run_options_for(workflow_key)
                    if self._agentic_settings is not None
                    else {}
                )
                agentic_enabled = bool(agentic_opts.get("enabled", False))
                if not agentic_enabled:
                    self.failed.emit(
                        "Mindmap/Graph läuft ausschließlich über LangGraph v2. "
                        "Bitte den Workflow in den Agentic-Einstellungen aktivieren."
                    )
                    return
                try:
                    from shared.services.agentic import AgenticWorkflowService, build_tools

                    default_profile_id = (
                        "graph_v2_local"
                        if mode_clean == "graph"
                        else "mindmap_v2_local"
                    )
                    profile_id = str(
                        agentic_opts.get(
                            "profile_id",
                            default_profile_id,
                        )
                        or default_profile_id
                    ).strip()
                    # Read pro settings from agentic_settings
                    _s = self._agentic_settings
                    if mode_clean == "graph" and _s is not None:
                        _retrieval_strategy = str(
                            getattr(_s, "graph_retrieval_strategy", "agent") or "agent"
                        ).strip().casefold()
                        if _retrieval_strategy not in {"agent", "rag", "none"}:
                            _retrieval_strategy = "agent"
                        _budget_seconds = float(getattr(_s, "graph_budget_seconds", 40.0) or 40.0)
                        _factcheck = bool(getattr(_s, "graph_factcheck", True))
                        _max_nodes = int(getattr(_s, "graph_max_nodes", 32) or 32)
                        _use_full_context = bool(getattr(_s, "graph_use_full_context", False))
                        _context_max_chars = int(getattr(_s, "graph_context_max_chars", 50_000) or 50_000)
                        _allow_rag = bool(getattr(_s, "graph_agent_allow_rag", True))
                        _allow_regex = bool(getattr(_s, "graph_agent_allow_regex", True))
                        _allow_heading = bool(getattr(_s, "graph_agent_allow_heading", True))
                        _allow_full_text = bool(getattr(_s, "graph_agent_allow_full_text", True))
                        _allow_query_narrowing = bool(
                            getattr(_s, "graph_agent_allow_query_narrowing", True)
                        )
                        _allow_heading_summaries = bool(
                            getattr(_s, "graph_agent_allow_heading_summaries", True)
                        )
                        try:
                            _agent_max_iter = int(getattr(_s, "graph_agent_max_iterations", 0))
                        except (TypeError, ValueError):
                            _agent_max_iter = 0
                        try:
                            _agent_max_regex_calls = int(getattr(_s, "graph_agent_max_regex_calls", 0))
                        except (TypeError, ValueError):
                            _agent_max_regex_calls = 0
                    elif _s is not None:
                        _retrieval_strategy = str(
                            getattr(_s, "mindmap_retrieval_strategy", "agent") or "agent"
                        ).strip().casefold()
                        if _retrieval_strategy not in {"agent", "rag", "none"}:
                            _retrieval_strategy = "agent"
                        _budget_seconds = float(getattr(_s, "mindmap_budget_seconds", 45.0) or 45.0)
                        _factcheck = bool(getattr(_s, "mindmap_factcheck", True))
                        _max_nodes = int(getattr(_s, "mindmap_max_nodes", 32) or 32)
                        _use_full_context = bool(getattr(_s, "mindmap_use_full_context", False))
                        _context_max_chars = int(getattr(_s, "mindmap_context_max_chars", 50_000) or 50_000)
                        _allow_rag = bool(getattr(_s, "mindmap_agent_allow_rag", True))
                        _allow_regex = bool(getattr(_s, "mindmap_agent_allow_regex", True))
                        _allow_heading = bool(getattr(_s, "mindmap_agent_allow_heading", True))
                        _allow_full_text = bool(getattr(_s, "mindmap_agent_allow_full_text", True))
                        _allow_query_narrowing = bool(
                            getattr(_s, "mindmap_agent_allow_query_narrowing", True)
                        )
                        _allow_heading_summaries = bool(
                            getattr(_s, "mindmap_agent_allow_heading_summaries", True)
                        )
                        try:
                            _agent_max_iter = int(getattr(_s, "mindmap_agent_max_iterations", 0))
                        except (TypeError, ValueError):
                            _agent_max_iter = 0
                        try:
                            _agent_max_regex_calls = int(getattr(_s, "mindmap_agent_max_regex_calls", 0))
                        except (TypeError, ValueError):
                            _agent_max_regex_calls = 0
                    else:
                        _retrieval_strategy = "agent"
                        _budget_seconds = 45.0 if mode_clean != "graph" else 40.0
                        _factcheck, _max_nodes = True, 32
                        _use_full_context, _context_max_chars = False, 50_000
                        _allow_rag, _allow_regex, _allow_heading = True, True, True
                        _allow_full_text = True
                        _allow_query_narrowing = True
                        _allow_heading_summaries = True
                        _agent_max_iter = 0
                        _agent_max_regex_calls = 0
                    raw_max_ref = getattr(_s, "mindmap_max_refinement_rounds", 1) if _s else 1
                    try:
                        _max_ref = int(raw_max_ref if raw_max_ref is not None else 1)
                    except (TypeError, ValueError):
                        _max_ref = 1

                    override_retrieval = str(
                        getattr(self._request, "override_retrieval_strategy", "") or ""
                    ).strip().casefold()
                    if override_retrieval in {"agent", "rag", "none"}:
                        _retrieval_strategy = override_retrieval
                    # Produktanforderung: MindMap/Graph laufen standardmäßig
                    # agentenbasiert (Toolwahl und Suchstrategie durch LLM).
                    _retrieval_strategy = "agent"

                    try:
                        override_agent_iter = int(
                            getattr(self._request, "override_agent_max_iterations", 0) or 0
                        )
                    except (TypeError, ValueError):
                        override_agent_iter = 0
                    if override_agent_iter > 0:
                        _agent_max_iter = override_agent_iter

                    override_factcheck = getattr(self._request, "override_factcheck", None)
                    if override_factcheck is not None:
                        _factcheck = bool(override_factcheck)

                    try:
                        override_max_nodes = int(
                            getattr(self._request, "override_max_nodes", 0) or 0
                        )
                    except (TypeError, ValueError):
                        override_max_nodes = 0
                    if override_max_nodes > 0:
                        _max_nodes = override_max_nodes

                    try:
                        override_max_ref = int(
                            getattr(self._request, "override_max_refinement_rounds", -1) or -1
                        )
                    except (TypeError, ValueError):
                        override_max_ref = -1
                    if override_max_ref >= 0:
                        _max_ref = override_max_ref

                    override_use_full_context = getattr(self._request, "override_use_full_context", None)
                    if override_use_full_context is not None:
                        _use_full_context = bool(override_use_full_context)

                    try:
                        override_context_max_chars = int(
                            getattr(self._request, "override_context_max_chars", 0) or 0
                        )
                    except (TypeError, ValueError):
                        override_context_max_chars = 0
                    if override_context_max_chars > 0:
                        _context_max_chars = override_context_max_chars

                    def _apply_bool_override(name: str, current: bool) -> bool:
                        override_value = getattr(self._request, name, None)
                        if override_value is None:
                            return current
                        return bool(override_value)

                    _allow_rag = _apply_bool_override("override_allow_rag_search", _allow_rag)
                    _allow_regex = _apply_bool_override("override_allow_regex_search", _allow_regex)
                    _allow_heading = _apply_bool_override("override_allow_heading_search", _allow_heading)
                    _allow_full_text = _apply_bool_override("override_allow_full_text_search", _allow_full_text)
                    _allow_query_narrowing = _apply_bool_override(
                        "override_allow_query_narrowing",
                        _allow_query_narrowing,
                    )
                    _allow_heading_summaries = _apply_bool_override(
                        "override_allow_heading_summaries",
                        _allow_heading_summaries,
                    )

                    try:
                        override_regex_calls = int(
                            getattr(self._request, "override_agent_max_regex_calls", -1) or -1
                        )
                    except (TypeError, ValueError):
                        override_regex_calls = -1
                    if override_regex_calls >= 0:
                        _agent_max_regex_calls = override_regex_calls
                    # Budget-Override: override_agent_budget_points bleibt für
                    # Abwärtskompatibilität (1 Punkt ≈ 3 Sekunden).
                    try:
                        override_budget_points = float(
                            getattr(self._request, "override_agent_budget_points", 0.0) or 0.0
                        )
                    except (TypeError, ValueError):
                        override_budget_points = 0.0
                    if override_budget_points > 0.0:
                        _budget_seconds = max(5.0, override_budget_points * 3.0)
                    override_budget_seconds = float(
                        getattr(self._request, "override_budget_seconds", 0.0) or 0.0
                    )
                    if override_budget_seconds > 0.0:
                        _budget_seconds = override_budget_seconds
                    override_log_draft_markdown = getattr(self._request, "override_log_draft_markdown", None)
                    _log_draft_markdown = bool(override_log_draft_markdown) if override_log_draft_markdown is not None else False

                    _max_ref = max(0, min(6, int(_max_ref or 0)))
                    _max_nodes = max(4, min(512, int(_max_nodes or 32)))
                    _context_max_chars = max(4_000, min(1_000_000, int(_context_max_chars or 50_000)))
                    _agent_max_iter = max(0, min(50_000, int(_agent_max_iter or 0)))
                    _agent_max_regex_calls = max(0, min(500, int(_agent_max_regex_calls or 0)))
                    _budget_seconds = max(5.0, min(3600.0, float(_budget_seconds or 45.0)))
                    run_kwargs = {
                        "request": {
                            "mode": mode,
                            "scope": "selection",
                            "query": query,
                            "depth": map_depth,
                            "context_text": context_text,
                            "max_nodes": _max_nodes,
                            # Pipeline-Settings
                            "retrieval_strategy": _retrieval_strategy,
                            "factcheck": _factcheck,
                            "max_refinement_rounds": _max_ref,
                            "use_full_context": _use_full_context,
                            "context_max_chars": _context_max_chars,
                            "allow_rag_search": _allow_rag,
                            "allow_regex_search": _allow_regex,
                            "allow_heading_search": _allow_heading,
                            "allow_full_text_search": _allow_full_text,
                            "allow_query_narrowing": _allow_query_narrowing,
                            "allow_heading_summaries": _allow_heading_summaries,
                            "agent_max_iterations": _agent_max_iter,
                            "agent_max_regex_calls": _agent_max_regex_calls,
                            "force_agent_retrieval": True,
                            "budget_seconds": float(_budget_seconds),
                            "log_draft_markdown": _log_draft_markdown,
                        },
                        "profile_id": profile_id or default_profile_id,
                        "enabled": agentic_enabled,
                        "tools": build_tools(
                            llm_manager=self._llm_manager,
                            rag_system=self._rag_system,
                            source_texts=[("Kontext", context_text)],
                        ),
                    }
                    svc = AgenticWorkflowService()
                    run_result = (
                        svc.run_graph(**run_kwargs)
                        if mode_clean == "graph"
                        else svc.run_mindmap(**run_kwargs)
                    )
                    run_artifact_path = _write_agentic_run_artifact(
                        mode=mode_clean,
                        query=query,
                        context_text=context_text,
                        request_payload=dict(run_kwargs.get("request", {}) or {}),
                        run_result=run_result,
                    )
                    if bool(run_result.ok):
                        markdown = str(run_result.result.get("markdown", "") or "")
                        self.finished.emit(
                            MindmapTaskResult(
                                context_text=context_text,
                                query=query,
                                mode=mode,
                                markdown=markdown,
                                meta=_agentic_map_meta(
                                    run_result,
                                    mode=mode,
                                    run_artifact_path=run_artifact_path,
                                ),
                            )
                        )
                        return
                    errors = list(run_result.errors or [])
                    state_payload = dict(getattr(run_result, "state", {}) or {})
                    raw_draft_logged = bool(
                        state_payload.get(
                            "draft_markdown_logged",
                            dict(run_result.metrics or {}).get("log_draft_markdown", False),
                        )
                    )
                    raw_draft = str(state_payload.get("draft_markdown_raw", "") or "") if raw_draft_logged else ""
                    failure_meta = {
                        "kind": "graph" if mode_clean == "graph" else "mindmap",
                        "variant": "graph" if mode_clean == "graph" else "mindmap",
                        "reason": "agentic_failed",
                        "error": "; ".join(
                            str(item or "").strip()
                            for item in errors[:4]
                            if str(item or "").strip()
                        ) or "LangGraph-Lauf fehlgeschlagen.",
                        "workflow_id": str(run_result.workflow_id or ""),
                        "profile_id": str(run_result.profile_id or ""),
                        "errors": errors,
                        "metrics": dict(run_result.metrics or {}),
                        "run_artifact_path": str(run_artifact_path or ""),
                        "log_draft_markdown": raw_draft_logged,
                        "trace_steps": _collect_trace_rows(run_result)[:48],
                        "trace_step_count": len(list(getattr(run_result, "trace", []) or [])),
                        "retrieval_agent_steps": _sanitize_for_json(
                            list(state_payload.get("retrieval_agent_steps", []) or [])[:40],
                            max_chars=240,
                        ),
                        "rag_snippets_preview": [
                            _clip_text(row, max_chars=260)
                            for row in list(state_payload.get("rag_snippets", []) or [])[:12]
                        ],
                        "fact_issues_list": [
                            str(x or "")
                            for x in list(
                                state_payload.get(
                                    "fact_issues_list",
                                    state_payload.get("fact_issues", []),
                                )
                                or []
                            )[:20]
                        ],
                        "structure_validation": _sanitize_for_json(
                            dict(state_payload.get("structure_validation", {}) or {}),
                            max_chars=240,
                        ),
                        "retrieval_policy": _sanitize_for_json(
                            dict(state_payload.get("retrieval_policy", {}) or {}),
                            max_chars=240,
                        ),
                        "grounding_validation": _sanitize_for_json(
                            dict(state_payload.get("grounding_validation", {}) or {}),
                            max_chars=240,
                        ),
                        "grounding_issues": [
                            str(x or "")
                            for x in list(state_payload.get("grounding_issues", []) or [])[:20]
                        ],
                        "required_main_nodes": [
                            str(x or "")
                            for x in list(
                                state_payload.get(
                                    "required_main_nodes",
                                    dict(run_result.metrics or {}).get("required_main_nodes", []),
                                )
                                or []
                            )[:12]
                        ],
                        "missing_required_main_nodes": [
                            str(x or "")
                            for x in list(
                                state_payload.get(
                                    "missing_required_main_nodes",
                                    dict(run_result.metrics or {}).get("missing_required_main_nodes", []),
                                )
                                or []
                            )[:12]
                        ],
                        "draft_progress": _sanitize_for_json(
                            list(state_payload.get("draft_progress", []) or [])[:64],
                            max_chars=480,
                        ),
                    }
                    if raw_draft_logged and raw_draft:
                        failure_meta["draft_markdown_raw"] = _clip_raw_draft_text(
                            raw_draft,
                            max_chars=_RAW_DRAFT_META_MAX_CHARS,
                        )
                    self.finished.emit(
                        MindmapTaskResult(
                            context_text=context_text,
                            query=query,
                            mode=mode,
                            markdown="",
                            meta=failure_meta,
                        )
                    )
                    return
                except Exception as exc:
                    self.failed.emit(f"Mindmap/Graph-Agent fehlgeschlagen: {exc}")
                    return

            self.failed.emit(
                "Unbekannter Hintergrundaufgabe-Typ: "
                f"{type(self._request).__name__}"
            )
        except Exception as exc:
            self.failed.emit(str(exc))


# ── Controller ─────────────────────────────────────────────────────────────────


class LLMSideTaskController(QObject):
    """Manages non-streaming glossary/mindmap LLM background tasks."""

    def __init__(
        self,
        *,
        parent: QObject,
        ctx: LLMTaskContext,
    ):
        super().__init__(parent)
        self._llm_manager = ctx.llm_manager
        self._rag_system = ctx.rag_system
        self._canvas = ctx.canvas
        self._chat_dock = ctx.chat_dock
        self._app_logger = ctx.app_logger
        self._glossary_feedback_bar = ctx.glossary_feedback_bar
        self._show_status = ctx.show_status
        self._resolve_imported_doc_content = ctx.resolve_imported_doc_content
        self._set_status_feedback_payload = ctx.set_status_feedback_payload
        self._refresh_preview_overlays = ctx.refresh_preview_overlays
        self._autosave_schedule_fn = ctx.autosave_schedule_fn
        self._build_llm_context_cb = ctx.build_llm_context
        self._get_user_mode = ctx.get_user_mode
        self._get_agentic_settings = ctx.get_agentic_settings
        self._is_prompt_editor_allowed = ctx.is_prompt_editor_allowed
        self._dialog_manager = ctx.dialog_manager

        self._thread: QThread | None = None
        self._worker: _LLMSideTaskWorker | None = None
        self._kind: str = ""
        self._done_cb = None

    # ── Public interface ───────────────────────────────────────────────

    def is_task_active(self) -> bool:
        return self._thread is not None

    def generate_glossary_from_llm_context(
        self,
        ctx: dict,
        query_raw: str = "",
        options: dict | None = None,
        done_cb=None,
    ) -> tuple[bool, str]:
        if not self._llm_manager.is_model_loaded():
            return False, "Kein Modell geladen. Bitte zuerst ein GGUF-Modell laden."
        if self._llm_manager.worker.isRunning() or self.is_task_active():
            return (
                False,
                "Das Modell ist gerade beschäftigt. Bitte erneut versuchen, "
                "wenn die aktuelle Generation fertig ist.",
            )

        context_text = self._build_context_text_from_llm_context(ctx, max_chars=0)
        if not context_text:
            context_text = self._fallback_context_text_from_ctx(ctx, max_chars=0)
        if not context_text:
            return self._empty_context_error(ctx)
        query = str(query_raw or "").strip()
        raw_opts = dict(options or {}) if isinstance(options, dict) else {}
        try:
            max_terms = int(raw_opts.get("max_terms", 32) or 32)
        except (TypeError, ValueError):
            max_terms = 32
        max_terms = max(8, min(256, max_terms))

        return self._start_task(
            task_kind="glossary",
            request=GlossaryTaskRequest(
                context_text=context_text,
                max_terms=max_terms,
                query=query,
            ),
            status_message="Generiere Glossar aus Kontext…",
            done_cb=done_cb,
        )

    def generate_mindmap_from_llm_context(
        self,
        ctx: dict,
        query_raw: str = "",
        mode_hint: str = "auto",
        map_depth: int = 0,
        map_options: dict | None = None,
        done_cb=None,
    ) -> tuple[bool, str]:
        resolved_query_raw = str(query_raw or "").strip()
        mode, query = self._resolve_mindmap_mode_and_query(
            resolved_query_raw,
            mode_hint=mode_hint,
        )

        if not self._llm_manager.is_model_loaded():
            return False, "Kein Modell geladen. Bitte zuerst ein GGUF-Modell laden."
        if self.is_task_active():
            return (False, "Es läuft bereits eine Hintergrundaufgabe.")
        if self._llm_manager.worker.isRunning():
            return (
                False,
                "Das Modell ist gerade beschäftigt. Bitte erneut versuchen, "
                "wenn die aktuelle Generation fertig ist.",
            )

        context_text = self._build_context_text_from_llm_context(ctx, max_chars=0)
        if not context_text:
            context_text = self._fallback_context_text_from_ctx(ctx, max_chars=0)
        if not context_text:
            return self._empty_context_error(ctx)

        rag_cfg = self._rag_system.config
        popup_opts = dict(map_options or {}) if isinstance(map_options, dict) else {}

        raw_retrieval = str(popup_opts.get("retrieval_strategy", "") or "").strip().casefold()
        retrieval_override = raw_retrieval if raw_retrieval in {"agent", "rag", "none"} else ""

        try:
            agent_iter_override = int(popup_opts.get("agent_max_iterations", 0) or 0)
        except (TypeError, ValueError):
            agent_iter_override = 0
        agent_iter_override = max(0, min(300, agent_iter_override))

        factcheck_override = None
        if "factcheck" in popup_opts:
            factcheck_override = bool(popup_opts.get("factcheck"))

        try:
            max_nodes_override = int(popup_opts.get("max_nodes", 0) or 0)
        except (TypeError, ValueError):
            max_nodes_override = 0
        max_nodes_override = max(0, min(512, max_nodes_override))

        try:
            max_ref_override = int(popup_opts.get("max_refinement_rounds", -1) or -1)
        except (TypeError, ValueError):
            max_ref_override = -1
        if max_ref_override > 6:
            max_ref_override = 6

        use_full_context_override = None
        if "use_full_context" in popup_opts:
            use_full_context_override = bool(popup_opts.get("use_full_context"))

        try:
            context_max_chars_override = int(popup_opts.get("context_max_chars", 0) or 0)
        except (TypeError, ValueError):
            context_max_chars_override = 0
        context_max_chars_override = max(0, min(1_000_000, context_max_chars_override))

        def _opt_bool(key: str) -> bool | None:
            if key not in popup_opts:
                return None
            return bool(popup_opts.get(key))

        allow_rag_override = _opt_bool("allow_rag_search")
        allow_regex_override = _opt_bool("allow_regex_search")
        allow_heading_override = _opt_bool("allow_heading_search")
        allow_full_text_override = _opt_bool("allow_full_text_search")
        allow_narrowing_override = _opt_bool("allow_query_narrowing")
        allow_heading_summary_override = _opt_bool("allow_heading_summaries")
        log_draft_markdown_override = _opt_bool("log_draft_markdown")
        try:
            max_regex_calls_override = int(popup_opts.get("agent_max_regex_calls", -1) or -1)
        except (TypeError, ValueError):
            max_regex_calls_override = -1
        max_regex_calls_override = max(-1, min(12, max_regex_calls_override))
        try:
            budget_points_override = float(popup_opts.get("agent_budget_points", 0.0) or 0.0)
        except (TypeError, ValueError):
            budget_points_override = 0.0
        budget_points_override = max(0.0, min(500.0, budget_points_override))
        try:
            budget_seconds_override = float(popup_opts.get("budget_seconds", 0.0) or 0.0)
        except (TypeError, ValueError):
            budget_seconds_override = 0.0
        budget_seconds_override = max(0.0, min(7200.0, budget_seconds_override))
        if budget_points_override > 0.0 and agent_iter_override <= 0:
            # Popup no longer exposes explicit max iterations; derive a safe
            # upper bound from budget so the budget is the primary limiter.
            # Cheapest tool (heading_search) costs ~0.1 points.
            auto_iter = int((budget_points_override / 0.1) + 2)
            agent_iter_override = max(8, min(300, auto_iter))

        return self._start_task(
            task_kind="mindmap",
            request=MindmapTaskRequest(
                context_text=context_text,
                query=query,
                mode=mode,
                max_nodes=(0 if mode == "chunkmap" else 32),
                chunking_strategy=str(rag_cfg.chunking.strategy or "sliding_window"),
                chunk_size=int(rag_cfg.chunking.chunk_size or 900),
                chunk_overlap=int(rag_cfg.chunking.chunk_overlap or 160),
                map_depth=max(0, min(12, int(map_depth or 0))),
                override_retrieval_strategy=retrieval_override,
                override_agent_max_iterations=agent_iter_override,
                override_factcheck=factcheck_override,
                override_max_nodes=max_nodes_override,
                override_max_refinement_rounds=max_ref_override,
                override_use_full_context=use_full_context_override,
                override_context_max_chars=context_max_chars_override,
                override_allow_rag_search=allow_rag_override,
                override_allow_regex_search=allow_regex_override,
                override_allow_heading_search=allow_heading_override,
                override_allow_full_text_search=allow_full_text_override,
                override_allow_query_narrowing=allow_narrowing_override,
                override_allow_heading_summaries=allow_heading_summary_override,
                override_agent_max_regex_calls=max_regex_calls_override,
                override_agent_budget_points=budget_points_override,
                override_budget_seconds=budget_seconds_override,
                override_log_draft_markdown=log_draft_markdown_override,
            ),
            status_message="Generiere MindMap/Graph/Chunk-MindMap aus Kontext…",
            done_cb=done_cb,
        )

    def toggle_glossary_overlays(self, checked: bool) -> None:
        get_highlight_store().set_glossary_enabled(bool(checked))
        self._refresh_preview_overlays()
        self._show_status("Glossar-Overlay: AN" if checked else "Glossar-Overlay: AUS", 2500)

    def open_glossary_editor(self) -> None:
        parent = self.parent()
        if parent is None:
            return

        def _create() -> GlossaryEditorDialog:
            dialog = GlossaryEditorDialog(
                parent,
                user_mode=self._get_user_mode(),
            )
            dialog.glossary_saved.connect(self.on_glossary_saved_from_editor)
            return dialog

        self._dialog_manager.show_dialog("glossary-editor", _create)

    def on_glossary_saved_from_editor(self, count: int) -> None:
        self._refresh_preview_overlays()
        overlays_on = get_highlight_store().is_glossary_enabled()
        suffix = "" if overlays_on else " (Overlay aktuell AUS)."
        self._show_status(f"Glossar gespeichert: {int(count)} Begriffe{suffix}", 4500)

    def edit_system_prompt(self) -> None:
        parent = self.parent()
        if parent is None:
            return
        user_mode = self._get_user_mode()
        if not self._is_prompt_editor_allowed(user_mode):
            QMessageBox.information(
                parent,
                "Prompt Editor",
                "Im Einfach-Modus ist der Prompt-Editor ausgeblendet.\nWechsle zu Plus oder Experte.",
            )
            return
        from studio.dialogs.prompt_editor import PromptEditorDialog

        self._dialog_manager.show_dialog(
            "prompt-editor",
            lambda: PromptEditorDialog(self._llm_manager, user_mode, parent=parent),
            on_accept=lambda _dlg: self._autosave_schedule_fn(300),
        )

    # ── Private helpers ────────────────────────────────────────────────

    def _start_task(
        self,
        *,
        task_kind: str,
        request: TaskRequest,
        status_message: str,
        done_cb=None,
    ) -> tuple[bool, str]:
        if self.is_task_active():
            return False, "Es läuft bereits eine Hintergrundaufgabe."

        agentic_settings = None
        try:
            settings = self._get_agentic_settings()
            if isinstance(settings, AgenticRuntimeSettings):
                agentic_settings = settings.clone()
        except Exception:
            agentic_settings = None

        thread = QThread(self)
        worker = _LLMSideTaskWorker(
            self._llm_manager,
            request=request,
            agentic_settings=agentic_settings,
            rag_system=self._rag_system,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_finished)
        worker.failed.connect(self._on_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)

        self._thread = thread
        self._worker = worker
        self._kind = str(task_kind or "")
        self._done_cb = done_cb
        self._chat_dock.set_aux_task_running(True)
        self._show_status(status_message, 2500)
        thread.start()
        return True, ""

    def _finish_task(self, ok: bool, info: str):
        callback = self._done_cb
        self._done_cb = None
        self._kind = ""
        self._worker = None
        self._thread = None
        self._chat_dock.set_aux_task_running(False)
        if callable(callback):
            try:
                callback(bool(ok), str(info or ""))
            except Exception as exc:
                self._app_logger.error("LLM", f"Side-task callback failed: {exc}")

    def _on_finished(self, payload: TaskResult):
        if isinstance(payload, GlossaryTaskResult):
            ok, info = self._finalize_glossary(
                entries=list(payload.entries or []),
                meta=dict(payload.meta or {}),
                context_text=str(payload.context_text or ""),
            )
            self._finish_task(ok, info)
            return
        if isinstance(payload, MindmapTaskResult):
            ok, info = self._finalize_mindmap(
                markdown=str(payload.markdown or ""),
                meta=dict(payload.meta or {}),
                context_text=str(payload.context_text or ""),
                query=str(payload.query or ""),
                mode=str(payload.mode or "mindmap"),
            )
            self._finish_task(ok, info)
            return
        self._finish_task(
            False,
            f"Unbekanntes Aufgaben-Ergebnis: {type(payload).__name__}",
        )

    def _on_failed(self, message: str):
        detail = str(message or "").strip() or "Unbekannter Fehler"
        self._app_logger.error("LLM", f"Hintergrundaufgabe fehlgeschlagen: {detail}")
        self._finish_task(False, detail)

    _finalize_glossary = _finalize_glossary_fn
    _finalize_mindmap = _finalize_mindmap_fn
    _build_context_text_from_llm_context = _build_context_text_from_llm_context_fn
    _fallback_context_text_from_ctx = _fallback_context_text_from_ctx_fn
    _empty_context_error = _empty_context_error_fn
    _resolve_mindmap_mode_and_query = staticmethod(
        _resolve_mindmap_mode_and_query_fn
    )
