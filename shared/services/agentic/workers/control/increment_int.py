"""Worker: ``control.increment_int.v1``.

Purpose:
- Increment an integer value stored in workflow state.

Expected input:
- ``step.args.path``: target state path, typically ``state.round``.
- ``step.args.by``: increment amount, defaults to ``1``.

Writes via ``StepOutcome.updates``:
- the configured integer state path.

Tool usage:
- None.

Failure behavior:
- If ``path`` is missing, the worker returns an empty ``StepOutcome``.
- Missing target values are treated as ``0``.
"""
from __future__ import annotations

from shared.services.agentic.contracts import StepOutcome
from shared.services.agentic.paths import get_path

WORKER_ID = "control.increment_int.v1"


def run(ctx, step, projected):  # noqa: ANN001
    _ = projected
    path = str(step.args.get("path", "") or "")
    by = int(step.args.get("by", 1) or 1)
    cur = int(get_path(ctx.state, path.replace("state.", ""), 0) or 0)
    if not path:
        return StepOutcome()
    return StepOutcome(updates={path: cur + by})
