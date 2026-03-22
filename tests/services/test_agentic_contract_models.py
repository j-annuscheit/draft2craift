from __future__ import annotations

from shared.services.agentic.contracts import (
    StepDef,
    StepOutcome,
    StepTrace,
    WorkflowDefinition,
    WorkflowProfile,
    WorkflowRunResult,
)


def test_contract_models_defaults() -> None:
    step = StepDef(
        id="run",
        runner="demo.runner.v1",
    )
    assert step.id == "run"
    assert step.max_visits == 0

    outcome = StepOutcome(value={"ok": True}, candidate_writes={"draft": {"value": 1}})
    assert outcome.value == {"ok": True}
    assert "draft" in outcome.candidate_writes

    definition = WorkflowDefinition(
        schema_version=1,
        workflow_id="demo",
        workflow_version="1.0.0",
        job_type="demo",
        entry_step="run",
        terminal_steps=("run",),
        state_init={},
        projections={},
        steps=(step,),
        edges=(),
        budgets={},
    )
    assert definition.step_by_id()["run"].runner == "demo.runner.v1"

    profile = WorkflowProfile(
        schema_version=1,
        profile_id="demo_profile",
        workflow_id="demo",
        profile_version="1.0.0",
        description="Demo",
        policy={},
        model_routing={},
        cache_policy={},
        wiring={},
    )
    assert profile.profile_id == "demo_profile"

    trace = StepTrace(step_id="run", runner="demo.runner.v1", status="ok", duration_ms=1.5)
    assert trace.visit_index == 0

    run_result = WorkflowRunResult(
        ok=True,
        workflow_id="demo",
        profile_id="demo_profile",
        result={},
        state={},
        trace=[trace],
        errors=[],
        metrics={},
    )
    assert run_result.ok is True
