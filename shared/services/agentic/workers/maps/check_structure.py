"""Worker: ``mindmap.check_structure.v1``.

Purpose:
- Run the lightweight V2 structure check used before semantic validation.
"""
from __future__ import annotations

from ._support import check_structure as run

WORKER_ID = "mindmap.check_structure.v1"
