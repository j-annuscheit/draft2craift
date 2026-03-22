"""Worker: ``canvas.validate_patch_constraints.v1``.

Purpose:
- Perform a minimal local validation for generated canvas patches.

Expected input:
- ``state.canvas_patch.patched_text``

Output value:
- ``{"ok": bool, "reason": str}``

Tool usage:
- None.
"""
from __future__ import annotations

from shared.services.agentic.contracts import StepOutcome

WORKER_ID = "canvas.validate_patch_constraints.v1"


def run(ctx, step, projected):  # noqa: ANN001
    _ = step, projected
    patch = dict(ctx.state.get("canvas_patch", {}) or {})
    text = str(patch.get("patched_text", "") or "").strip()
    ok = bool(text)
    return StepOutcome(value={"ok": ok, "reason": "non_empty" if ok else "empty"})
