"""Worker: ``mindmap.ensure_connected_graph.v1``.

Purpose:
- Repair disconnected or insufficiently grounded map drafts by creating a
  staged candidate revision.
"""
from __future__ import annotations

from ._support import ensure_connected_graph as run

WORKER_ID = "mindmap.ensure_connected_graph.v1"
