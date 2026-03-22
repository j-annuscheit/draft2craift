"""Worker: ``mindmap.refine_nodes.v1``.

Purpose:
- Ask for a small structural refinement when the validated map can still be
  improved without changing its overall topic.
"""
from __future__ import annotations

from ._support import refine_nodes as run

WORKER_ID = "mindmap.refine_nodes.v1"
