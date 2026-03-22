"""Worker: ``control.emit_result.v1``.

Purpose:
- Copy selected values from ``state`` / ``request`` into ``result``.
- Finish the workflow immediately after the projection was emitted.

Expected input:
- ``step.args.map``: mapping ``result_key -> source_path``.
- Source paths may start with ``state.`` or ``request.``.

Writes via ``StepOutcome.updates``:
- one ``result.<key>`` entry per configured mapping.

Tool usage:
- None.

Failure behavior:
- Unknown or unsupported source paths resolve to ``None``.
- The worker always sets ``stop=True`` because emission is terminal.
"""
from __future__ import annotations

from typing import Any

from shared.services.agentic.contracts import StepOutcome
from shared.services.agentic.paths import get_path

WORKER_ID = "control.emit_result.v1"


def run(ctx, step, projected):  # noqa: ANN001
    _ = projected
    mapping = dict(step.args.get("map", {}) or {})
    updates: dict[str, Any] = {}
    for key, src_path in mapping.items():
        if not isinstance(src_path, str):
            continue
        if src_path.startswith("state."):
            value = get_path(ctx.state, src_path[len("state."):], None)
        elif src_path.startswith("request."):
            value = get_path(ctx.request, src_path[len("request."):], None)
        else:
            value = None
        updates[f"result.{str(key)}"] = value
    return StepOutcome(updates=updates, stop=True)
