"""Worker: ``control.fail.v1``.

Purpose:
- Terminate the workflow and append a structured error message to
  ``ctx.errors``.

Expected input:
- ``step.args.code``: short machine-readable error code.
- ``step.args.message``: human-readable error message.

Writes / side effects:
- appends ``"<code>: <message>"`` to ``ctx.errors``.
- returns ``StepOutcome(stop=True)``.

Tool usage:
- None.

Failure behavior:
- Missing args fall back to ``WORKFLOW_FAILED`` / ``Workflow failed``.
"""
from __future__ import annotations

from shared.services.agentic.contracts import StepOutcome

WORKER_ID = "control.fail.v1"


def run(ctx, step, projected):  # noqa: ANN001
    _ = projected
    code = str(step.args.get("code", "WORKFLOW_FAILED") or "WORKFLOW_FAILED")
    message = str(step.args.get("message", "Workflow failed") or "Workflow failed")
    ctx.errors.append(f"{code}: {message}")
    return StepOutcome(stop=True)
