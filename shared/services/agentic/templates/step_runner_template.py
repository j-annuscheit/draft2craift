"""Template for new agentic step runners.

Copy this file as a starting point for new runners.
"""
from __future__ import annotations

from shared.services.agentic.contracts import StepOutcome


def runner_template(ctx, step, projected):  # noqa: ANN001
    """Minimal contract-compliant runner template.

    Rules:
    - read only from ``ctx.request``, ``ctx.state``, ``ctx.policy``, ``projected``
    - return ``StepOutcome`` only
    - no UI dependencies
    """
    _ = step, projected
    input_value = str(ctx.request.get("example_input", "") or "").strip()
    if not input_value:
        return StepOutcome(
            value={"ok": False, "reason": "empty_input"},
            updates={"state.example_status": "empty_input"},
        )
    transformed = input_value.upper()
    return StepOutcome(
        value={"ok": True, "text": transformed},
        updates={"state.example_status": "ok"},
    )


def candidate_runner_template(ctx, step, projected):  # noqa: ANN001
    """Template for steps that propose a candidate and let a later validator decide."""
    _ = step, projected
    current = str((ctx.state.get("map_draft", {}) or {}).get("markdown", "") or "").strip()
    if not current:
        return StepOutcome(value={"retry": False, "reason": "empty_current"})
    candidate = current + "\n# Candidate change"
    return StepOutcome(
        value={"retry": True, "reason": "candidate_proposed"},
        candidate_writes={
            "map_draft_candidate": {
                "write_to": "state.map_draft",
                "value": {"markdown": candidate, "mode": "mindmap"},
                "meta": {
                    "intent": "refine",
                    "allow_invalid_improvement": False,
                    "min_overlap_ratio": 0.5,
                },
            }
        },
    )
