"""Fact-check pipeline mixin used by chat dock."""
from __future__ import annotations

import re

from .pipeline_parts import bind_factcheck_pipeline_mixin

class FactCheckPipelineMixin:
    """Encapsulates extract-then-verify fact-check workflow."""

    _NLI_ENTAILMENT_GREEN_THRESHOLD = 0.55
    _NLI_STRONG_ENTAILMENT_THRESHOLD = 0.90
    _NLI_ASYNC_MAX_CHECKS_PER_SLICE = 1
    _NLI_ASYNC_SLICE_BUDGET_SEC = 0.03
    _NLI_ASYNC_PROGRESS_STEP = 10
    _FACTCHECK_METHOD_ORDER = ("nli", "llm_chunk", "llm_global", "llm_claim_nli")
    _FACTCHECK_MODE_LABELS = {
        "nli": "NLI (Chunk->Satz)",
        "llm": "LLM (Chunk-weise)",
        "llm_chunk": "LLM (Chunk-weise)",
        "llm_global": "LLM (Alle Quellen pro Fakt)",
        "llm_claim_nli": "LLM-Claims + NLI",
    }
    _LLM_GLOBAL_EVIDENCE_HEADER = "Evidenz (LLM-Output, kein Direktzitat)"
    _CLAIM_CACHE_VERSION = 1
    _CLAIM_CHUNK_SIZE = 900
    _CLAIM_CHUNK_OVERLAP = 160
    _WS_RE = re.compile(r"\s+")
    _LIST_PREFIX_RE = re.compile(r"^\s*(?:[-*]+|\d+[\.\)])\s*")
    _WARNING_PREFIX_RE = re.compile(r"^\s*⚠\s*")
    _FENCED_JSON_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", flags=re.IGNORECASE)
    _JSON_OBJECT_RE = re.compile(r"\{[\s\S]*\}")

bind_factcheck_pipeline_mixin(FactCheckPipelineMixin)

__all__ = ["FactCheckPipelineMixin"]
