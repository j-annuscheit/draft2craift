"""Canvas feature package."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .widget import CanvasTabWidget

__all__ = ["CanvasTabWidget"]


def __getattr__(name: str):
    if name == "CanvasTabWidget":
        from .widget import CanvasTabWidget

        return CanvasTabWidget
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
