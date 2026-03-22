from __future__ import annotations

from pathlib import Path

from shared.services.agentic.settings import (
    AgenticRuntimeSettings,
    discover_profile_ids_by_workflow,
)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n", encoding="utf-8")


def test_agentic_settings_defaults_follow_environment(monkeypatch):
    monkeypatch.setenv("D2C_AGENTIC_FACTCHECK", "1")
    monkeypatch.setenv("D2C_AGENTIC_CHAT", "0")
    monkeypatch.setenv("D2C_AGENTIC_CANVAS", "1")
    monkeypatch.setenv("D2C_AGENTIC_MINDMAP", "0")
    monkeypatch.setenv("D2C_AGENTIC_STRICT_POLICY", "1")
    monkeypatch.setenv("D2C_AGENTIC_TRACE", "1")
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


def test_agentic_settings_run_options_include_policy_and_overlays():
    settings = AgenticRuntimeSettings.from_dict(
        {
            "chat_enabled": True,
            "chat_profile_id": "chat_alt",
            "strict_policy": True,
            "trace_enabled": False,
            "cache_enabled": True,
            "map_result_detail_level": "detailed",
            "env_name": "stage",
            "overlay_profile_ids_raw": "a,b,a\nc",
        }
    )
    options = settings.run_options_for("chat")
    assert options["enabled"] is True
    assert options["profile_id"] == "chat_alt"
    assert options["overlay_profile_ids"] == ["a", "b", "c"]
    assert options["env_name"] == "stage"
    assert options["policy_overrides"] == {
        "strict_policy": True,
        "trace_enabled": False,
        "cache_policy": {"enabled": True},
    }
    assert settings.map_result_detail_level == "detailed"


def test_agentic_settings_graph_defaults_to_mindmap_toggle_when_env_unset(monkeypatch):
    monkeypatch.delenv("D2C_AGENTIC_GRAPH", raising=False)
    monkeypatch.setenv("D2C_AGENTIC_MINDMAP", "1")
    settings = AgenticRuntimeSettings.defaults()
    assert settings.mindmap_enabled is True
    assert settings.graph_enabled is True


def test_discover_profile_ids_by_workflow(tmp_path: Path):
    repo = tmp_path / "repo"
    profiles = repo / "data" / "workflows" / "profiles"
    _write(
        profiles / "fc.toml",
        """
        schema_version = 1
        profile_id = "fc_profile"
        workflow_id = "factcheck_agentic"
        profile_version = "1.0.0"
        """,
    )
    _write(
        profiles / "chat.toml",
        """
        schema_version = 1
        profile_id = "chat_profile"
        workflow_id = "chat_agentic"
        profile_version = "1.0.0"
        """,
    )
    _write(
        profiles / "graph.toml",
        """
        schema_version = 1
        profile_id = "graph_profile"
        workflow_id = "graph_agentic"
        profile_version = "1.0.0"
        """,
    )
    _write(
        profiles / "other.toml",
        """
        schema_version = 1
        profile_id = "unknown"
        workflow_id = "unknown_workflow"
        profile_version = "1.0.0"
        """,
    )

    found = discover_profile_ids_by_workflow(repo)
    assert "fc_profile" in found["factcheck"]
    assert "chat_profile" in found["chat"]
    assert "canvas_grounded_rewrite" in found["canvas"]
    assert "mindmap_grounded_graph" in found["mindmap"]
    assert "graph_profile" in found["graph"]
    assert "graph_connected_component" in found["graph"]
