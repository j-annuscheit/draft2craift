"""Worker: ``mindmap.plan_expansion.v1``.

Purpose:
- Decide whether another RAG-driven map expansion round is worthwhile.
"""
from __future__ import annotations

from ._support import plan_expansion as run

WORKER_ID = "mindmap.plan_expansion.v1"
