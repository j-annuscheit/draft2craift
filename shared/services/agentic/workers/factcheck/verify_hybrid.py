"""Worker: ``factcheck.verify.hybrid.v1``.

Purpose:
- Decide whether the current claim is supported, contradicted or still not
  evidenced.

Expected input:
- ``state.current_claim``
- ``state.evidence_candidates``
- ``policy.allow_nli``

Output value:
- status payload with confidence, short reason and best evidence excerpt.

Tool usage:
- optionally ``nli.verify``
"""
from __future__ import annotations

from shared.services.agentic.contracts import StepOutcome

WORKER_ID = "factcheck.verify.hybrid.v1"


def run(ctx, step, projected):  # noqa: ANN001
    _ = step, projected
    claim = str(ctx.state.get("current_claim", "") or "")
    evidence = list(ctx.state.get("evidence_candidates", []) or [])
    allow_nli = bool(ctx.policy.get("allow_nli", True))
    if not claim:
        return StepOutcome(value={"status": "nicht_belegt", "confidence": 0.0, "reason": "empty_claim", "evidence": ""})
    if not evidence:
        return StepOutcome(value={"status": "nicht_belegt", "confidence": 0.0, "reason": "no_evidence", "evidence": ""})

    best = str(evidence[0] if evidence else "")
    nli_label = ""
    nli_score = 0.0
    if allow_nli:
        try:
            nli = ctx.tools.call("nli.verify", premise=best, hypothesis=claim)
            if isinstance(nli, dict):
                nli_label = str(nli.get("label", "") or "").strip().casefold()
                nli_score = float(nli.get("score", 0.0) or 0.0)
        except Exception:
            nli_label = ""
            nli_score = 0.0

    if nli_label == "entailment" and nli_score >= 0.55:
        status = "belegt"
    elif nli_label == "contradiction" and nli_score >= 0.55:
        status = "widerlegt"
    else:
        overlap = len(set(claim.casefold().split()) & set(best.casefold().split()))
        status = "belegt" if overlap >= 4 else "nicht_belegt"
    return StepOutcome(value={
        "status": status,
        "confidence": max(0.0, min(1.0, nli_score if nli_score > 0 else 0.5)),
        "reason": f"nli={nli_label or ('disabled' if not allow_nli else 'none')}",
        "evidence": best[:300],
    })
