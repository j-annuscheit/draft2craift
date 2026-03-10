"""Preview highlight rendering helpers."""
from __future__ import annotations


def apply_highlight_markers(html: str) -> str:
    """Pass-through hook for future preview highlight rendering."""
    return str(html or "")
