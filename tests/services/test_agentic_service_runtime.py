from __future__ import annotations

import json
from pathlib import Path
import time

from shared.services.agentic.contracts import StepOutcome
from shared.services.agentic.default_registry import register_default_runners
from shared.services.agentic.registry import StepRegistry
from shared.services.agentic.service import AgenticWorkflowService


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n", encoding="utf-8")


def _repo_with_layered_workflow(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    definitions = repo / "data" / "workflows" / "definitions"
    profiles = repo / "data" / "workflows" / "profiles"

    _write(
        definitions / "demo.toml",
        """
        schema_version = 1
        workflow_id = "demo"
        workflow_version = "1.0.0"
        job_type = "demo"
        entry_step = "echo_policy"
        terminal_steps = ["echo_policy"]

        [state_init]

        [[steps]]
        id = "echo_policy"
        runner = "test.echo_policy.v1"
        write_to = "result.value"

        [budgets]
        max_engine_steps = 4
        """,
    )
    _write(
        profiles / "_base.toml",
        """
        schema_version = 1
        profile_id = "_base"
        workflow_id = "*"
        profile_version = "1.0.0"
        description = "base"

        [policy]
        x = 1
        """,
    )
    _write(
        profiles / "demo__default.toml",
        """
        schema_version = 1
        profile_id = "demo__default"
        workflow_id = "demo"
        profile_version = "1.0.0"
        description = "workflow default"

        [policy]
        x = 2
        """,
    )
    _write(
        profiles / "_env_dev.toml",
        """
        schema_version = 1
        profile_id = "_env_dev"
        workflow_id = "*"
        profile_version = "1.0.0"
        description = "env"

        [policy]
        x = 3
        """,
    )
    _write(
        profiles / "_env_stage.toml",
        """
        schema_version = 1
        profile_id = "_env_stage"
        workflow_id = "*"
        profile_version = "1.0.0"
        description = "env stage"

        [policy]
        x = 7
        """,
    )
    _write(
        profiles / "exp_overlay.toml",
        """
        schema_version = 1
        profile_id = "exp_overlay"
        workflow_id = "demo"
        profile_version = "1.0.0"
        description = "overlay"

        [policy]
        x = 9
        """,
    )
    _write(
        profiles / "user_profile.toml",
        """
        schema_version = 1
        profile_id = "user_profile"
        workflow_id = "demo"
        profile_version = "1.0.0"
        description = "user"

        [policy]
        x = 4
        """,
    )
    return repo


def _repo_with_strict_workflow(tmp_path: Path) -> Path:
    repo = tmp_path / "repo_strict"
    definitions = repo / "data" / "workflows" / "definitions"

    _write(
        definitions / "strict_demo.toml",
        """
        schema_version = 1
        workflow_id = "strict_demo"
        workflow_version = "1.0.0"
        job_type = "strict_demo"
        entry_step = "call_tool"
        terminal_steps = ["emit_result", "fail_hard"]

        [state_init]
        payload = ""

        [[steps]]
        id = "call_tool"
        runner = "test.call_tool.v1"
        write_to = "state.payload"
        on_error = "fail_hard"

        [[steps]]
        id = "emit_result"
        runner = "control.emit_result.v1"
        [steps.args]
        map = { value = "state.payload" }

        [[steps]]
        id = "fail_hard"
        runner = "control.fail.v1"
        [steps.args]
        code = "STRICT_POLICY_BLOCK"
        message = "tool call blocked"

        [[edges]]
        from = "call_tool"
        to = "emit_result"

        [budgets]
        max_engine_steps = 8
        """,
    )
    return repo


def _repo_with_visit_guard_workflow(tmp_path: Path) -> Path:
    repo = tmp_path / "repo_visit_guard"
    definitions = repo / "data" / "workflows" / "definitions"

    _write(
        definitions / "visit_guard.toml",
        """
        schema_version = 1
        workflow_id = "visit_guard"
        workflow_version = "1.0.0"
        job_type = "demo"
        entry_step = "bounce"
        terminal_steps = ["emit_result", "fail_hard"]

        [state_init]
        counter = 0
        decision = {}

        [projections.bounce_input_v1]
        include = ["state.counter", "state._runtime.step_visits.bounce"]

        [[steps]]
        id = "bounce"
        runner = "test.bounce.v1"
        input_projection = "bounce_input_v1"
        write_to = "decision"
        max_visits = 5
        on_max_visits = "emit_result"

        [[steps]]
        id = "emit_result"
        runner = "control.emit_result.v1"
        [steps.args]
        map = { counter = "state.counter", visits = "state._runtime.step_visits.bounce" }

        [[steps]]
        id = "fail_hard"
        runner = "control.fail.v1"

        [[edges]]
        from = "bounce"
        to = "bounce"

        [budgets]
        max_engine_steps = 12
        """,
    )
    return repo


def _repo_with_candidate_workflow(tmp_path: Path) -> Path:
    repo = tmp_path / "repo_candidate"
    definitions = repo / "data" / "workflows" / "definitions"

    _write(
        definitions / "candidate_demo.toml",
        """
        schema_version = 1
        workflow_id = "candidate_demo"
        workflow_version = "1.0.0"
        job_type = "demo"
        entry_step = "propose"
        terminal_steps = ["emit_result", "fail_hard"]

        [state_init.base]
        text = "baseline"

        [state_init.review]

        [projections.propose_input_v1]
        include = ["state.base"]

        [projections.review_input_v1]
        include = ["request.accept", "state.base", "state._candidates.base_candidate"]

        [[steps]]
        id = "propose"
        runner = "test.propose_candidate.v1"
        input_projection = "propose_input_v1"
        write_to = "state.review"

        [[steps]]
        id = "review_candidate"
        runner = "test.review_candidate.v1"
        input_projection = "review_input_v1"
        write_to = "state.review"

        [[steps]]
        id = "emit_result"
        runner = "control.emit_result.v1"
        [steps.args]
        map = { base = "state.base", review = "state.review", pending = "state._candidates.base_candidate" }

        [[steps]]
        id = "fail_hard"
        runner = "control.fail.v1"

        [[edges]]
        from = "propose"
        to = "review_candidate"

        [[edges]]
        from = "review_candidate"
        to = "emit_result"

        [budgets]
        max_engine_steps = 8
        """,
    )
    return repo


def _repo_with_budget_workflow(tmp_path: Path) -> Path:
    repo = tmp_path / "repo_budget"
    definitions = repo / "data" / "workflows" / "definitions"

    _write(
        definitions / "budget_demo.toml",
        """
        schema_version = 1
        workflow_id = "budget_demo"
        workflow_version = "1.0.0"
        job_type = "demo"
        entry_step = "call_a"
        terminal_steps = ["emit_result", "fail_hard"]

        [state_init]
        last = ""

        [[steps]]
        id = "call_a"
        runner = "test.call_llm.v1"
        write_to = "state.last"

        [[steps]]
        id = "call_b"
        runner = "test.call_llm.v1"
        write_to = "state.last"

        [[steps]]
        id = "sleep_step"
        runner = "test.sleep.v1"
        write_to = "state.last"

        [[steps]]
        id = "emit_result"
        runner = "control.emit_result.v1"
        [steps.args]
        map = { last = "state.last" }

        [[steps]]
        id = "fail_hard"
        runner = "control.fail.v1"

        [[edges]]
        from = "call_a"
        to = "call_b"

        [[edges]]
        from = "call_b"
        to = "emit_result"

        [[edges]]
        from = "sleep_step"
        to = "emit_result"

        [budgets]
        max_engine_steps = 8
        """,
    )
    return repo


def test_service_profile_layering_order(monkeypatch, tmp_path: Path):
    repo = _repo_with_layered_workflow(tmp_path)
    monkeypatch.setenv("D2C_AGENTIC_ENV", "dev")

    registry = StepRegistry()
    registry.register("test.echo_policy.v1", lambda ctx, _step, _proj: ctx.policy.get("x", -1))
    service = AgenticWorkflowService(repo_root=repo, registry=registry)

    result = service.run(
        workflow_id="demo",
        request={},
        profile_id="user_profile",
        overlay_profile_ids=["exp_overlay"],
        policy_overrides={"x": 5},
    )
    assert result.ok is True
    assert result.result.get("value") == 5
    assert result.metrics.get("profile_chain") == [
        "_base",
        "demo__default",
        "_env_dev",
        "exp_overlay",
        "user_profile",
    ]


def test_service_trace_writes_file(monkeypatch, tmp_path: Path):
    repo = _repo_with_layered_workflow(tmp_path)
    monkeypatch.setenv("D2C_AGENTIC_TRACE", "1")
    monkeypatch.setenv("D2C_AGENTIC_ENV", "dev")

    registry = StepRegistry()
    registry.register("test.echo_policy.v1", lambda ctx, _step, _proj: ctx.policy.get("x", -1))
    service = AgenticWorkflowService(repo_root=repo, registry=registry)

    result = service.run(
        workflow_id="demo",
        request={"question": "trace me"},
        profile_id="user_profile",
    )
    assert result.ok is True
    trace_path = str(result.metrics.get("trace_path", "") or "")
    assert trace_path
    trace_file = Path(trace_path)
    assert trace_file.is_file()
    payload = json.loads(trace_file.read_text(encoding="utf-8"))
    assert payload.get("workflow", {}).get("id") == "demo"
    assert payload.get("ok") is True
    trace_rows = list(payload.get("trace", []) or [])
    assert trace_rows
    first = dict(trace_rows[0] or {})
    assert dict(first.get("input", {}) or {}) == {}
    assert dict(first.get("output", {}) or {}).get("value") == 4
    assert dict(first.get("output", {}) or {}).get("write_to") == "result.value"
    assert dict(first.get("state_after", {}) or {}).get("result.value") == 4


def test_service_env_name_override_beats_env_var(monkeypatch, tmp_path: Path):
    repo = _repo_with_layered_workflow(tmp_path)
    monkeypatch.setenv("D2C_AGENTIC_ENV", "dev")

    registry = StepRegistry()
    registry.register("test.echo_policy.v1", lambda ctx, _step, _proj: ctx.policy.get("x", -1))
    service = AgenticWorkflowService(repo_root=repo, registry=registry)

    result = service.run(
        workflow_id="demo",
        request={},
        profile_id="",
        env_name="stage",
    )
    assert result.ok is True
    assert result.result.get("value") == 7
    assert result.metrics.get("profile_chain") == [
        "_base",
        "demo__default",
        "_env_stage",
    ]


def test_strict_policy_blocks_unlisted_tool(tmp_path: Path):
    repo = _repo_with_strict_workflow(tmp_path)
    registry = register_default_runners(StepRegistry())
    registry.register("test.call_tool.v1", lambda ctx, _step, _proj: ctx.tools.call("demo.tool"))
    service = AgenticWorkflowService(repo_root=repo, registry=registry)

    result = service.run(
        workflow_id="strict_demo",
        request={},
        profile_id="",
        policy_overrides={"strict_policy": True},
        tools={"demo.tool": lambda: "ok"},
    )
    assert result.ok is False
    assert result.errors
    assert any("STRICT_POLICY_BLOCK" in err for err in result.errors)


def test_step_max_visits_routes_to_overflow_target(tmp_path: Path):
    repo = _repo_with_visit_guard_workflow(tmp_path)
    registry = register_default_runners(StepRegistry())

    def _bounce(ctx, _step, _proj):
        counter = int(ctx.state.get("counter", 0) or 0) + 1
        return StepOutcome(
            value={"status": "looping", "counter": counter},
            updates={"state.counter": counter},
        )

    registry.register("test.bounce.v1", _bounce)
    service = AgenticWorkflowService(repo_root=repo, registry=registry)

    result = service.run(
        workflow_id="visit_guard",
        request={},
        profile_id="",
    )

    assert result.ok is True
    assert result.result.get("counter") == 5
    assert result.result.get("visits") == 6
    assert result.state.get("_runtime", {}).get("step_visits", {}).get("bounce") == 6
    assert result.trace[-2].step_id == "bounce"
    assert result.trace[-2].status == "skipped"
    assert result.trace[-2].visit_index == 6


def test_candidate_commit_updates_state(tmp_path: Path):
    repo = _repo_with_candidate_workflow(tmp_path)
    registry = register_default_runners(StepRegistry())

    def _propose(_ctx, _step, _proj):
        return StepOutcome(
            value={"stage": "proposed"},
            candidate_writes={
                "base_candidate": {
                    "write_to": "state.base",
                    "value": {"text": "candidate"},
                    "meta": {"strategy": "replace"},
                }
            },
        )

    def _review(ctx, _step, _proj):
        pending = dict(ctx.state.get("_candidates", {}).get("base_candidate", {}) or {})
        accepted = bool(ctx.request.get("accept")) and bool(pending)
        return StepOutcome(
            value={"accepted": accepted, "pending_seen": bool(pending)},
            commit_candidates=("base_candidate",) if accepted else (),
            discard_candidates=() if accepted else ("base_candidate",),
        )

    registry.register("test.propose_candidate.v1", _propose)
    registry.register("test.review_candidate.v1", _review)
    service = AgenticWorkflowService(repo_root=repo, registry=registry)

    result = service.run(
        workflow_id="candidate_demo",
        request={"accept": True},
        profile_id="",
    )

    assert result.ok is True
    assert result.result.get("base") == {"text": "candidate"}
    assert result.result.get("review") == {"accepted": True, "pending_seen": True}
    assert result.result.get("pending") is None
    assert result.state.get("base") == {"text": "candidate"}
    assert result.state.get("_candidates", {}) == {}
    assert list(result.trace[0].output.get("candidate_writes", {}).keys()) == ["base_candidate"]
    assert result.trace[1].output.get("commit_candidates") == ["base_candidate"]


def test_candidate_discard_keeps_previous_state(tmp_path: Path):
    repo = _repo_with_candidate_workflow(tmp_path)
    registry = register_default_runners(StepRegistry())

    def _propose(_ctx, _step, _proj):
        return StepOutcome(
            value={"stage": "proposed"},
            candidate_writes={
                "base_candidate": {
                    "write_to": "state.base",
                    "value": {"text": "candidate"},
                }
            },
        )

    def _review(ctx, _step, _proj):
        pending = dict(ctx.state.get("_candidates", {}).get("base_candidate", {}) or {})
        return StepOutcome(
            value={"accepted": False, "pending_seen": bool(pending)},
            discard_candidates=("base_candidate",),
        )

    registry.register("test.propose_candidate.v1", _propose)
    registry.register("test.review_candidate.v1", _review)
    service = AgenticWorkflowService(repo_root=repo, registry=registry)

    result = service.run(
        workflow_id="candidate_demo",
        request={"accept": False},
        profile_id="",
    )

    assert result.ok is True
    assert result.result.get("base") == {"text": "baseline"}
    assert result.result.get("review") == {"accepted": False, "pending_seen": True}
    assert result.result.get("pending") is None
    assert result.state.get("base") == {"text": "baseline"}
    assert result.state.get("_candidates", {}) == {}
    assert result.trace[1].output.get("discard_candidates") == ["base_candidate"]


def test_service_enforces_max_llm_calls_budget(tmp_path: Path):
    repo = _repo_with_budget_workflow(tmp_path)
    registry = register_default_runners(StepRegistry())

    def _call_llm(ctx, _step, _proj):
        return str(ctx.tools.call("llm.generate", prompt="x") or "")

    registry.register("test.call_llm.v1", _call_llm)
    registry.register("test.sleep.v1", lambda _ctx, _step, _proj: "slept")
    service = AgenticWorkflowService(repo_root=repo, registry=registry)

    result = service.run(
        workflow_id="budget_demo",
        request={},
        profile_id="",
        policy_overrides={"max_llm_calls": 1},
        tools={"llm.generate": lambda **_kwargs: "ok"},
    )

    assert result.ok is False
    assert any("max_llm_calls_exceeded" in err for err in result.errors)


def test_service_enforces_max_runtime_seconds_budget(tmp_path: Path):
    repo = _repo_with_budget_workflow(tmp_path)
    registry = register_default_runners(StepRegistry())

    registry.register("test.call_llm.v1", lambda _ctx, _step, _proj: "ok")

    def _sleep(_ctx, _step, _proj):
        time.sleep(0.02)
        return "slept"

    registry.register("test.sleep.v1", _sleep)
    service = AgenticWorkflowService(repo_root=repo, registry=registry)

    result = service.run(
        workflow_id="budget_demo",
        request={},
        profile_id="",
        wiring_overrides={"demo.call_a": "test.sleep.v1"},
        policy_overrides={"max_runtime_seconds": 0.001},
    )

    assert result.ok is False
    assert any("max_runtime_seconds_exceeded" in err for err in result.errors)
