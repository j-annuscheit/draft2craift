"""Worker: ``factcheck.extract_missing_claims.v1``.

Purpose:
- Extract sentences from ``request.c`` that are not already present in the
  existing fact table.

Expected projected input:
- ``request.c``
- ``request.o.rows[*].fact``

Output value:
- ordered list of new claims.

Tool usage:
- None.
"""
from __future__ import annotations

from shared.services.agentic.contracts import StepOutcome
from shared.services.agentic.projection import projection_get
from ._shared import split_claims

WORKER_ID = "factcheck.extract_missing_claims.v1"


def run(ctx, step, projected):  # noqa: ANN001
    _ = ctx, step
    text = str(projection_get(projected, "request.c", "") or "")
    existing = projection_get(projected, "request.o.rows[*].fact", []) or []
    existing_set = {str(x or "").strip().casefold() for x in list(existing or []) if str(x or "").strip()}
    claims = [c for c in split_claims(text) if c.casefold() not in existing_set]
    return StepOutcome(value=claims)
