"""Worker: ``mindmap.validate_schema.v1``.

Purpose:
- Perform structural validation and candidate acceptance for graph / mindmap
  drafts.

Implementation note:
- The heavy graph-validation logic is centralized in ``_support.py`` so this
  worker file can stay focused on the contract and registration surface.
"""
from __future__ import annotations

from ._support import validate_schema as run

WORKER_ID = "mindmap.validate_schema.v1"
