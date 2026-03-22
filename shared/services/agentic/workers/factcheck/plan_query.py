"""Worker: ``factcheck.plan_query.v1``.

Purpose:
- Build a retrieval query and a conservative regex pattern from the current
  claim.

Expected projected input:
- ``state.current_claim``
- ``policy.allowed_retrieval_modes``

Output value:
- ``{"query": ..., "mode": ..., "regex_patterns": [...]}``
"""
from __future__ import annotations

import re

from shared.services.agentic.contracts import StepOutcome
from shared.services.agentic.projection import projection_get

WORKER_ID = "factcheck.plan_query.v1"


def run(ctx, step, projected):  # noqa: ANN001
    claim = str(projection_get(projected, "state.current_claim", "") or "")
    allow = projection_get(projected, "policy.allowed_retrieval_modes", []) or []
    allow_set = {str(x or "").strip().casefold() for x in list(allow or [])}
    regex_only = bool(allow_set) and allow_set <= {"regex"}
    pattern = re.sub(r"\s+", r"\\s+", re.escape(claim[:220])).strip()
    if not pattern:
        pattern = re.escape(claim[:64] or "fact")
    mode = "regex" if regex_only else "hybrid"
    return StepOutcome(value={"query": claim, "mode": mode, "regex_patterns": [pattern]})
