from __future__ import annotations

from pathlib import Path

from shared.services.agentic.loader import load_workflow_definition


_ROOT = Path("/home/be/test_claude/canvas2")
_DEFINITIONS = _ROOT / "data" / "workflows" / "definitions"


def _definition_path(name: str) -> Path:
    return _DEFINITIONS / f"{name}.toml"


def test_builtin_workflows_define_input_projection_for_all_runtime_steps():
    for workflow_id in (
        "factcheck_agentic",
        "chat_agentic",
        "canvas_agentic",
        "mindmap_agentic",
        "graph_agentic",
    ):
        definition = load_workflow_definition(_definition_path(workflow_id))
        for step in list(definition.steps):
            if step.id == "fail_hard":
                continue
            assert str(step.input_projection or "").strip(), (
                f"{workflow_id}:{step.id} missing input_projection"
            )
