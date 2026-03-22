"""Worker: ``mindmap.draft_subgraph.v1``.

Purpose:
- Draft a new connected subgraph from the expansion question and retrieved
  evidence.
"""
from __future__ import annotations

from ._support import draft_subgraph as run

WORKER_ID = "mindmap.draft_subgraph.v1"
