"""Shared user-mode constants and helpers."""
from __future__ import annotations

USER_MODE_SIMPLE = "simple"
USER_MODE_PLUS = "plus"
USER_MODE_EXPERT = "expert"

USER_MODE_ORDER = (
    USER_MODE_SIMPLE,
    USER_MODE_PLUS,
    USER_MODE_EXPERT,
)

USER_MODE_LABELS = {
    USER_MODE_SIMPLE: "Einfach",
    USER_MODE_PLUS: "Plus",
    USER_MODE_EXPERT: "Experte",
}


def normalize_user_mode(value: object) -> str:
    text = str(value or "").strip().lower()
    if text in USER_MODE_LABELS:
        return text
    return USER_MODE_PLUS


def mode_rank(value: object) -> int:
    mode = normalize_user_mode(value)
    return USER_MODE_ORDER.index(mode)
