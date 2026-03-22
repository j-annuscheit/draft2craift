"""Worker: ``mindmap.validate_semantics.v1``.

Purpose:
- Combine deterministic grounding checks with an optional LLM semantic review.
"""
from __future__ import annotations

from ._support import validate_semantics as run

WORKER_ID = "mindmap.validate_semantics.v1"
