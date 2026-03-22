from __future__ import annotations

from pathlib import Path

from shared.services.agentic.engine import ToolGateway
from shared.services.agentic.registry import StepRegistry
from shared.services.agentic.workers.control.emit_result import run as control_emit_result
from shared.services.agentic.service import AgenticWorkflowService


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n", encoding="utf-8")


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo_tool_runtime"
    definitions = repo / "data" / "workflows" / "definitions"
    profiles = repo / "data" / "workflows" / "profiles"

    _write(
        definitions / "tool_runtime_demo.toml",
        """
        schema_version = 1
        workflow_id = "tool_runtime_demo"
        workflow_version = "1.0.0"
        job_type = "demo"
        entry_step = "step_a"
        terminal_steps = ["emit"]

        [state_init]
        a = ""
        b = ""
        route = ""

        [[steps]]
        id = "step_a"
        runner = "test.call_demo_tool.v1"
        write_to = "state.a"
        [steps.args]
        value = "x"

        [[steps]]
        id = "step_b"
        runner = "test.call_demo_tool.v1"
        write_to = "state.b"
        [steps.args]
        value = "x"

        [[steps]]
        id = "step_route"
        runner = "test.capture_route.v1"
        write_to = "state.route"

        [[steps]]
        id = "emit"
        runner = "control.emit_result.v1"
        [steps.args]
        map = { a = "state.a", b = "state.b", route = "state.route" }

        [[edges]]
        from = "step_a"
        to = "step_b"

        [[edges]]
        from = "step_b"
        to = "step_route"

        [[edges]]
        from = "step_route"
        to = "emit"

        [budgets]
        max_engine_steps = 16
        """,
    )
    _write(
        profiles / "tool_runtime_profile.toml",
        """
        schema_version = 1
        profile_id = "tool_runtime_profile"
        workflow_id = "tool_runtime_demo"
        profile_version = "1.0.0"
        description = "runtime policy test profile"

        [policy]
        strict_policy = false

        [model_routing]
        "demo.step_route" = "llm.fast.route"

        [cache_policy]
        enabled = true
        default_ttl_seconds = 30
        [cache_policy.per_tool_ttl_seconds]
        "demo.tool" = 30
        """,
    )
    return repo


def test_tool_cache_and_model_route_are_enforced(tmp_path: Path):
    repo = _repo(tmp_path)
    counter = {"calls": 0}

    def _demo_tool(*, value: str, _model_route: str = "", **_kwargs):
        _ = _kwargs
        counter["calls"] += 1
        return f"demo:{value}:{counter['calls']}:{_model_route}"

    def _runner_call_tool(ctx, step, _projected):  # noqa: ANN001
        value = str(step.args.get("value", "") or "")
        return ctx.tools.call("demo.tool", value=value)

    def _runner_capture_route(ctx, step, _projected):  # noqa: ANN001
        _ = step
        return ctx.tools.call("demo.tool", value="route")

    registry = StepRegistry()
    registry.register("test.call_demo_tool.v1", _runner_call_tool)
    registry.register("test.capture_route.v1", _runner_capture_route)
    registry.register("control.emit_result.v1", control_emit_result)

    service = AgenticWorkflowService(repo_root=repo, registry=registry)
    result = service.run(
        workflow_id="tool_runtime_demo",
        request={},
        profile_id="tool_runtime_profile",
        policy_overrides={
            "allowed_tools_per_step": {
                "step_a": ["demo.tool"],
                "step_b": ["demo.tool"],
                "step_route": ["demo.tool"],
            }
        },
        tools={"demo.tool": _demo_tool},
    )

    assert result.ok is True
    assert result.result.get("a") == result.result.get("b")
    assert counter["calls"] == 2
    assert "llm.fast.route" in str(result.result.get("route", ""))
    assert int(result.metrics.get("tool_calls", {}).get("demo.tool#cache_hit", 0)) >= 1


def test_tool_gateway_does_not_cache_empty_llm_generate_results():
    calls = {"count": 0}

    def _llm_generate(*, prompt: str, **kwargs):
        _ = prompt, kwargs
        calls["count"] += 1
        return ""

    gateway = ToolGateway(
        tools={"llm.generate": _llm_generate},
        policy={"cache_policy": {"enabled": True, "default_ttl_seconds": 30}},
        step_allowlist={},
    )
    gateway.current_step_id = "draft_map_raw"
    gateway.current_step_logical_key = "mindmap.draft_map_raw"

    assert gateway.call("llm.generate", prompt="P") == ""
    assert gateway.call("llm.generate", prompt="P") == ""
    assert calls["count"] == 2
    assert int(gateway.metrics.get("llm.generate#cache_hit", 0) or 0) == 0
