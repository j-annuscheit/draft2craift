from __future__ import annotations

from shared.services.agentic.settings import (
    AgenticRuntimeSettings,
    discover_profile_ids_by_workflow,
)


def test_agentic_settings_defaults_follow_environment(monkeypatch):
    monkeypatch.setenv("D2C_AGENTIC_FACTCHECK", "1")
    monkeypatch.setenv("D2C_AGENTIC_CHAT", "0")
    monkeypatch.setenv("D2C_AGENTIC_CANVAS", "1")
    monkeypatch.setenv("D2C_AGENTIC_MINDMAP", "0")
    monkeypatch.setenv("D2C_AGENTIC_GRAPH", "0")
    monkeypatch.setenv("D2C_AGENTIC_STRICT_POLICY", "1")
    monkeypatch.setenv("LANGSMITH_TRACING", "1")
    monkeypatch.setenv("LANGSMITH_ENDPOINT", "http://127.0.0.1:1984")
    monkeypatch.setenv("D2C_AGENTIC_CACHE_DISABLED", "1")
    monkeypatch.setenv("D2C_AGENTIC_ENV", "dev")

    settings = AgenticRuntimeSettings.defaults()
    assert settings.factcheck_enabled is True
    assert settings.chat_enabled is False
    assert settings.canvas_enabled is True
    assert settings.mindmap_enabled is False
    assert settings.graph_enabled is False
    assert settings.strict_policy is True
    assert settings.trace_enabled is True
    assert settings.cache_enabled is False
    assert settings.map_result_detail_level == "auto"
    assert settings.env_name == "dev"
    assert settings.mindmap_retrieval_strategy in {"agent", "rag", "none"}
    assert int(settings.mindmap_agent_max_iterations) >= 1


def test_agentic_settings_run_options_include_policy_and_overlays():
    settings = AgenticRuntimeSettings.from_dict(
        {
            "chat_enabled": True,
            "chat_profile_id": "chat_alt",
            "trace_enabled": True,
            "cache_enabled": True,
        }
    )
    options = settings.run_options_for("chat")
    assert options["enabled"] is True
    assert options["profile_id"] == "chat_alt"
    assert options["trace_enabled"] is True
    assert options["cache_enabled"] is True


def test_agentic_settings_accepts_map_retrieval_fields_from_dict():
    settings = AgenticRuntimeSettings.from_dict(
        {
            "mindmap_retrieval_strategy": "agent",
            "mindmap_agent_max_iterations": 9,
            "graph_retrieval_strategy": "none",
            "graph_agent_max_iterations": 4,
        }
    )
    assert settings.mindmap_retrieval_strategy == "agent"
    assert int(settings.mindmap_agent_max_iterations) == 9
    assert settings.graph_retrieval_strategy == "none"
    assert int(settings.graph_agent_max_iterations) == 4


def test_agentic_settings_graph_defaults_to_mindmap_toggle_when_env_unset(monkeypatch):
    monkeypatch.delenv("D2C_AGENTIC_GRAPH", raising=False)
    monkeypatch.setenv("D2C_AGENTIC_MINDMAP", "1")
    settings = AgenticRuntimeSettings.defaults()
    assert settings.mindmap_enabled is True
    assert settings.graph_enabled is True


def test_discover_profile_ids_by_workflow_returns_v2_defaults():
    found = discover_profile_ids_by_workflow()
    assert found["factcheck"] == ["factcheck_v2_local"]
    assert found["chat"] == ["chat_v2_local"]
    assert found["canvas"] == ["canvas_v2_local"]
    assert found["mindmap"] == ["mindmap_v2_local"]
    assert found["graph"] == ["graph_v2_local"]
