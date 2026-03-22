from __future__ import annotations

from shared.services.agentic.contracts import StepDef, WorkflowDefinition
from shared.services.agentic.engine import WorkflowEngine
from shared.services.agentic.registry import StepRegistry
from shared.services.agentic.runtime import summarize_run
from shared.services.agentic.templates.step_runner_template import runner_template


def _definition() -> WorkflowDefinition:
    return WorkflowDefinition(
        schema_version=1,
        workflow_id="template_demo",
        workflow_version="1.0.0",
        job_type="demo",
        entry_step="run",
        terminal_steps=("run",),
        state_init={},
        projections={},
        steps=(StepDef(id="run", runner="template.runner.v1"),),
        edges=(),
        budgets={},
    )


def test_step_runner_template_contract_smoke():
    registry = StepRegistry()
    registry.register("template.runner.v1", runner_template)
    engine = WorkflowEngine(registry)
    result = engine.run(
        definition=_definition(),
        request={"example_input": "hello"},
        policy={},
        tools={},
        profile_id="",
        wiring={},
    )
    assert result.ok is True
    summary = summarize_run(result)
    assert summary["workflow_id"] == "template_demo"
    assert summary["steps"] >= 1


def test_step_runner_template_handles_empty_input():
    registry = StepRegistry()
    registry.register("template.runner.v1", runner_template)
    engine = WorkflowEngine(registry)
    result = engine.run(
        definition=_definition(),
        request={"example_input": ""},
        policy={},
        tools={},
        profile_id="",
        wiring={},
    )
    assert result.ok is True
    assert result.state.get("example_status") == "empty_input"
