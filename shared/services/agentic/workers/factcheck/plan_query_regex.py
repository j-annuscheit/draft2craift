"""Worker: ``factcheck.plan_query.regex.v1``.

Purpose:
- Reuse the normal factcheck query planner but force regex-only retrieval.
"""
from __future__ import annotations

from shared.services.agentic.contracts import StepOutcome
from .plan_query import run as plan_query_run

WORKER_ID = "factcheck.plan_query.regex.v1"


def run(ctx, step, projected):  # noqa: ANN001
    base = plan_query_run(ctx, step, projected)
    plan = dict(base.value or {})
    plan["mode"] = "regex"
    return StepOutcome(value=plan)
