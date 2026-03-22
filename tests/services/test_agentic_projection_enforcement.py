from __future__ import annotations

from pathlib import Path

from shared.services.agentic.registry import StepRegistry
from shared.services.agentic.service import AgenticWorkflowService


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n", encoding="utf-8")


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo_projection"
    definitions = repo / "data" / "workflows" / "definitions"
    _write(
        definitions / "projection_guard.toml",
        """
        schema_version = 1
        workflow_id = "projection_guard"
        workflow_version = "1.0.0"
        job_type = "demo"
        entry_step = "inspect"
        terminal_steps = ["inspect"]

        [state_init]
        allowed_state = "ok"
        state_secret = "top-secret"

        [projections.only_visible]
        include = ["request.visible", "state.allowed_state"]

        [[steps]]
        id = "inspect"
        runner = "test.inspect.v1"
        input_projection = "only_visible"
        write_to = "result.payload"

        [budgets]
        max_engine_steps = 4
        """,
    )
    _write(
        definitions / "projection_open.toml",
        """
        schema_version = 1
        workflow_id = "projection_open"
        workflow_version = "1.0.0"
        job_type = "demo"
        entry_step = "inspect"
        terminal_steps = ["inspect"]

        [state_init]
        allowed_state = "ok"
        state_secret = "top-secret"

        [[steps]]
        id = "inspect"
        runner = "test.inspect.v1"
        write_to = "result.payload"

        [budgets]
        max_engine_steps = 4
        """,
    )
    return repo


def _inspect_runner(ctx, _step, _projected):  # noqa: ANN001
    return {
        "visible": ctx.request.get("visible"),
        "request_secret": ctx.request.get("secret"),
        "allowed_state": ctx.state.get("allowed_state"),
        "state_secret": ctx.state.get("state_secret"),
    }


def test_projection_guard_hides_non_projected_fields(tmp_path: Path):
    repo = _repo(tmp_path)
    registry = StepRegistry()
    registry.register("test.inspect.v1", _inspect_runner)
    service = AgenticWorkflowService(repo_root=repo, registry=registry)

    result = service.run(
        workflow_id="projection_guard",
        request={"visible": "ok", "secret": "hidden"},
        profile_id="",
    )
    assert result.ok is True
    payload = dict(result.result.get("payload", {}) or {})
    assert payload.get("visible") == "ok"
    assert payload.get("allowed_state") == "ok"
    assert payload.get("request_secret") is None
    assert payload.get("state_secret") is None


def test_without_projection_runner_sees_full_context(tmp_path: Path):
    repo = _repo(tmp_path)
    registry = StepRegistry()
    registry.register("test.inspect.v1", _inspect_runner)
    service = AgenticWorkflowService(repo_root=repo, registry=registry)

    result = service.run(
        workflow_id="projection_open",
        request={"visible": "ok", "secret": "hidden"},
        profile_id="",
    )
    assert result.ok is True
    payload = dict(result.result.get("payload", {}) or {})
    assert payload.get("request_secret") == "hidden"
    assert payload.get("state_secret") == "top-secret"
