"""Runtime settings for LangGraph workflows."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import os
from pathlib import Path
from typing import Any

from shared.services.local_policy import langsmith_tracing_enabled

_TRUTHY = {"1", "true", "yes", "on"}
_DEFAULT_PROFILES = {
    "factcheck": "factcheck_v2_local",
    "chat": "chat_v2_local",
    "canvas": "canvas_v2_local",
    "mindmap": "mindmap_v2_local",
    "graph": "graph_v2_local",
}


def _env_flag(name: str, default: bool = False) -> bool:
    raw = str(os.environ.get(name, "") or "").strip().casefold()
    if not raw:
        return bool(default)
    return raw in _TRUTHY


def _env_text(name: str, default: str = "") -> str:
    value = str(os.environ.get(name, "") or "").strip()
    return value if value else str(default or "")


@dataclass(slots=True)
class AgenticRuntimeSettings:
    factcheck_enabled: bool
    chat_enabled: bool
    canvas_enabled: bool
    mindmap_enabled: bool
    graph_enabled: bool

    factcheck_profile_id: str
    chat_profile_id: str
    canvas_profile_id: str
    mindmap_profile_id: str
    graph_profile_id: str

    strict_policy: bool
    trace_enabled: bool
    cache_enabled: bool
    map_result_detail_level: str
    env_name: str
    overlay_profile_ids_raw: str

    # ── Mindmap / Graph pro settings ──────────────────────────────────────
    # Verify each node/claim against source documents (NLI or regex fallback)
    mindmap_factcheck: bool
    # Maximum number of nodes in the generated map (0 = use per-call default)
    mindmap_max_nodes: int
    # How many fact-check → refinement rounds to run (0 = disable refinement)
    mindmap_max_refinement_rounds: int
    # Retrieval strategy before draft generation:
    #   "agent"  — LLM autonomously picks tools (rag_search/regex_search/heading_search/full_text)
    #   "rag"    — fixed: concept extraction → semantic RAG search
    #   "none"   — no retrieval augmentation (use context_text as-is)
    mindmap_retrieval_strategy: str
    # Budget in Sekunden (bevorzugt). Das System misst echte LLM-Zeiten und
    # reguliert sich selbst. 0 = Fallback auf agent_budget_points * 3 s.
    mindmap_budget_seconds: float
    # Pass full context window to generation instead of focused snippets
    mindmap_use_full_context: bool
    # Hard upper bound for context chars passed into map generation
    mindmap_context_max_chars: int
    # Agent tool capability switches
    mindmap_agent_allow_rag: bool
    mindmap_agent_allow_regex: bool
    mindmap_agent_allow_heading: bool
    mindmap_agent_allow_full_text: bool
    # Agent may rewrite/narrow search terms across iterations
    mindmap_agent_allow_query_narrowing: bool
    # Agent may request heading content summaries
    mindmap_agent_allow_heading_summaries: bool
    # Optional cap for regex tool calls per run (0 = unlimited)
    mindmap_agent_max_regex_calls: int
    # Legacy compatibility field (runtime uses budget_seconds instead)
    mindmap_agent_max_iterations: int
    # Same options for graph mode
    graph_factcheck: bool
    graph_max_nodes: int
    graph_retrieval_strategy: str
    graph_budget_seconds: float
    graph_use_full_context: bool
    graph_context_max_chars: int
    graph_agent_allow_rag: bool
    graph_agent_allow_regex: bool
    graph_agent_allow_heading: bool
    graph_agent_allow_full_text: bool
    graph_agent_allow_query_narrowing: bool
    graph_agent_allow_heading_summaries: bool
    graph_agent_max_regex_calls: int
    # Legacy compatibility field (runtime uses budget_seconds instead)
    graph_agent_max_iterations: int

    @classmethod
    def defaults(cls) -> "AgenticRuntimeSettings":
        return cls(
            factcheck_enabled=_env_flag("D2C_AGENTIC_FACTCHECK", default=True),
            chat_enabled=_env_flag("D2C_AGENTIC_CHAT", default=True),
            canvas_enabled=_env_flag("D2C_AGENTIC_CANVAS", default=True),
            mindmap_enabled=_env_flag("D2C_AGENTIC_MINDMAP", default=True),
            graph_enabled=_env_flag("D2C_AGENTIC_GRAPH", default=True),
            factcheck_profile_id=_env_text("D2C_AGENTIC_FACTCHECK_PROFILE", _DEFAULT_PROFILES["factcheck"]),
            chat_profile_id=_env_text("D2C_AGENTIC_CHAT_PROFILE", _DEFAULT_PROFILES["chat"]),
            canvas_profile_id=_env_text("D2C_AGENTIC_CANVAS_PROFILE", _DEFAULT_PROFILES["canvas"]),
            mindmap_profile_id=_env_text("D2C_AGENTIC_MINDMAP_PROFILE", _DEFAULT_PROFILES["mindmap"]),
            graph_profile_id=_env_text("D2C_AGENTIC_GRAPH_PROFILE", _DEFAULT_PROFILES["graph"]),
            strict_policy=_env_flag("D2C_AGENTIC_STRICT_POLICY", default=False),
            trace_enabled=langsmith_tracing_enabled(),
            cache_enabled=not _env_flag("D2C_AGENTIC_CACHE_DISABLED", default=False),
            map_result_detail_level=_env_text("D2C_AGENTIC_MAP_RESULT_DETAIL", "auto"),
            env_name=_env_text("D2C_AGENTIC_ENV", ""),
            overlay_profile_ids_raw=_env_text("D2C_AGENTIC_OVERLAY_PROFILE_IDS", ""),
            mindmap_factcheck=_env_flag("D2C_MINDMAP_FACTCHECK", default=True),
            mindmap_max_nodes=int(_env_text("D2C_MINDMAP_MAX_NODES", "32") or 32),
            mindmap_max_refinement_rounds=int(_env_text("D2C_MINDMAP_MAX_REFINEMENTS", "1") or 1),
            mindmap_retrieval_strategy=_env_text("D2C_MINDMAP_RETRIEVAL_STRATEGY", "agent"),
            mindmap_budget_seconds=float(_env_text("D2C_MINDMAP_BUDGET_SECONDS", "45") or 45),
            mindmap_use_full_context=_env_flag("D2C_MINDMAP_USE_FULL_CONTEXT", default=False),
            mindmap_context_max_chars=int(_env_text("D2C_MINDMAP_CONTEXT_MAX_CHARS", "50000") or 50000),
            mindmap_agent_allow_rag=_env_flag("D2C_MINDMAP_AGENT_ALLOW_RAG", default=True),
            mindmap_agent_allow_regex=_env_flag("D2C_MINDMAP_AGENT_ALLOW_REGEX", default=True),
            mindmap_agent_allow_heading=_env_flag("D2C_MINDMAP_AGENT_ALLOW_HEADING", default=True),
            mindmap_agent_allow_full_text=_env_flag("D2C_MINDMAP_AGENT_ALLOW_FULL_TEXT", default=True),
            mindmap_agent_allow_query_narrowing=_env_flag("D2C_MINDMAP_AGENT_ALLOW_QUERY_NARROWING", default=True),
            mindmap_agent_allow_heading_summaries=_env_flag("D2C_MINDMAP_AGENT_ALLOW_HEADING_SUMMARIES", default=True),
            mindmap_agent_max_regex_calls=int(_env_text("D2C_MINDMAP_AGENT_MAX_REGEX_CALLS", "0") or 0),
            mindmap_agent_max_iterations=int(_env_text("D2C_MINDMAP_AGENT_MAX_ITERATIONS", "1") or 1),
            graph_factcheck=_env_flag("D2C_GRAPH_FACTCHECK", default=True),
            graph_max_nodes=int(_env_text("D2C_GRAPH_MAX_NODES", "32") or 32),
            graph_retrieval_strategy=_env_text("D2C_GRAPH_RETRIEVAL_STRATEGY", "agent"),
            graph_budget_seconds=float(_env_text("D2C_GRAPH_BUDGET_SECONDS", "40") or 40),
            graph_use_full_context=_env_flag("D2C_GRAPH_USE_FULL_CONTEXT", default=False),
            graph_context_max_chars=int(_env_text("D2C_GRAPH_CONTEXT_MAX_CHARS", "50000") or 50000),
            graph_agent_allow_rag=_env_flag("D2C_GRAPH_AGENT_ALLOW_RAG", default=True),
            graph_agent_allow_regex=_env_flag("D2C_GRAPH_AGENT_ALLOW_REGEX", default=True),
            graph_agent_allow_heading=_env_flag("D2C_GRAPH_AGENT_ALLOW_HEADING", default=True),
            graph_agent_allow_full_text=_env_flag("D2C_GRAPH_AGENT_ALLOW_FULL_TEXT", default=True),
            graph_agent_allow_query_narrowing=_env_flag("D2C_GRAPH_AGENT_ALLOW_QUERY_NARROWING", default=True),
            graph_agent_allow_heading_summaries=_env_flag("D2C_GRAPH_AGENT_ALLOW_HEADING_SUMMARIES", default=True),
            graph_agent_max_regex_calls=int(_env_text("D2C_GRAPH_AGENT_MAX_REGEX_CALLS", "0") or 0),
            graph_agent_max_iterations=int(_env_text("D2C_GRAPH_AGENT_MAX_ITERATIONS", "1") or 1),
        )

    @classmethod
    def from_dict(cls, raw: object) -> "AgenticRuntimeSettings":
        defaults = cls.defaults()
        if not isinstance(raw, dict):
            return defaults
        data = dict(raw)
        merged = dict(asdict(defaults))
        for key in list(merged.keys()):
            if key not in data:
                continue
            merged[key] = data[key]
        # Legacy mapping: if a caller sets old iteration fields but no explicit
        # budget_seconds, interpret them as budget seconds for compatibility.
        if "mindmap_budget_seconds" not in data and "mindmap_agent_max_iterations" in data:
            merged["mindmap_budget_seconds"] = data.get("mindmap_agent_max_iterations", merged["mindmap_budget_seconds"])
        if "graph_budget_seconds" not in data and "graph_agent_max_iterations" in data:
            merged["graph_budget_seconds"] = data.get("graph_agent_max_iterations", merged["graph_budget_seconds"])
        return cls(**merged)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    def clone(self) -> "AgenticRuntimeSettings":
        return self.from_dict(self.to_dict())

    def run_options_for(self, workflow_key: str) -> dict[str, Any]:
        key = str(workflow_key or "").strip().casefold()
        enabled = bool(getattr(self, f"{key}_enabled", False))
        profile_id = str(getattr(self, f"{key}_profile_id", _DEFAULT_PROFILES.get(key, "")) or "")
        return {
            "enabled": enabled,
            "profile_id": profile_id,
            "trace_enabled": bool(self.trace_enabled),
            "cache_enabled": bool(self.cache_enabled),
        }


def discover_profile_ids_by_workflow(
    repo_root: Path | None = None,
) -> dict[str, list[str]]:
    _ = repo_root
    return {
        "factcheck": [_DEFAULT_PROFILES["factcheck"]],
        "chat": [_DEFAULT_PROFILES["chat"]],
        "canvas": [_DEFAULT_PROFILES["canvas"]],
        "mindmap": [_DEFAULT_PROFILES["mindmap"]],
        "graph": [_DEFAULT_PROFILES["graph"]],
    }
