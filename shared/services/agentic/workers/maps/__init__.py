"""Mindmap / graph workers.

This package contains the registered workers for map-shaped workflows.

Current structure:
- ``source/``: source normalization and outline extraction
- ``seed/``: deterministic seed-tree creation
- ``frontier/``: incremental node-by-node expansion
- ``validate/``: candidate and final validation
- ``apply/``: candidate staging, commit/discard and final cleanup
- ``render/``: final markdown emission

Legacy graph-oriented helpers still exist in sibling modules and ``_support.py``.
New mindmap work should prefer the smaller v3 worker packages and
``shared.services.agentic.lib.maps``.
"""
