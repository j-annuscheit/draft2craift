"""Shared metric helpers for eval commands."""
from __future__ import annotations


def safe_ratio(numerator: float, denominator: float) -> float:
    """Return 0.0 when denominator is zero."""
    if denominator == 0:
        return 0.0
    return float(numerator) / float(denominator)
