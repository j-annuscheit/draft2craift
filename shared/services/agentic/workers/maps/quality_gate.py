"""Worker: ``mindmap.quality_gate.v1``.

Purpose:
- Collapse validation state into a tiny routing decision payload.
"""
from __future__ import annotations

from ._support import quality_gate as run

WORKER_ID = "mindmap.quality_gate.v1"
