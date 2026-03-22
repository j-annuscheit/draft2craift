"""Worker: ``factcheck.verify.v1``.

Purpose:
- Provide the default factcheck verification entry point.
- The implementation intentionally reuses the hybrid verifier so the workflow
  can swap policies without duplicating logic.
"""
from __future__ import annotations

from .verify_hybrid import run as verify_hybrid_run

WORKER_ID = "factcheck.verify.v1"


def run(ctx, step, projected):  # noqa: ANN001
    return verify_hybrid_run(ctx, step, projected)
