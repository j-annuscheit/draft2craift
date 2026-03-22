from __future__ import annotations

from shared.services.agentic.contracts import StepDef, WorkflowDefinition
from shared.services.agentic.engine import WorkflowEngine
from shared.services.agentic.registry import StepRegistry


def _simple_definition(runner_id: str) -> WorkflowDefinition:
    return WorkflowDefinition(
        schema_version=1,
        workflow_id="demo",
        workflow_version="1.0.0",
        job_type="demo",
        entry_step="run",
        terminal_steps=("run",),
        state_init={},
        projections={},
        steps=(StepDef(id="run", runner=runner_id),),
        edges=(),
        budgets={},
    )


def test_registry_infers_owner_and_version():
    registry = StepRegistry()
    registry.register("factcheck.plan_query.v2", lambda _ctx, _step, _proj: None)
    meta = registry.metadata("factcheck.plan_query.v2")
    assert meta.owner == "factcheck"
    assert meta.version == "2.0.0"
    assert meta.stability == "stable"
    assert meta.deprecated is False


def test_engine_warns_on_deprecated_runner_by_default():
    registry = StepRegistry()
    registry.register(
        "demo.legacy_step.v1",
        lambda _ctx, _step, _proj: None,
        meta={
            "owner": "demo",
            "stability": "deprecated",
            "version": "1.0.0",
            "deprecated": True,
            "replaced_by": "demo.new_step.v2",
            "deprecation_note": "migrate to v2",
        },
    )
    engine = WorkflowEngine(registry)
    result = engine.run(
        definition=_simple_definition("demo.legacy_step.v1"),
        request={},
        policy={},
        tools={},
        profile_id="",
        wiring={},
    )
    assert result.ok is True
    warnings = list(result.metrics.get("deprecation_warnings", []) or [])
    assert warnings
    assert "demo.legacy_step.v1" in warnings[0]
    assert "demo.new_step.v2" in warnings[0]


def test_engine_blocks_deprecated_runner_when_policy_is_block():
    registry = StepRegistry()
    registry.register(
        "demo.legacy_step.v1",
        lambda _ctx, _step, _proj: None,
        meta={"stability": "deprecated", "deprecated": True},
    )
    engine = WorkflowEngine(registry)
    result = engine.run(
        definition=_simple_definition("demo.legacy_step.v1"),
        request={},
        policy={"deprecation_policy": "block"},
        tools={},
        profile_id="",
        wiring={},
    )
    assert result.ok is False
    assert result.errors
    assert "Deprecated runner" in result.errors[0]
