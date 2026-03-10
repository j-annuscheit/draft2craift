"""Domain models for user feedback."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class FeedbackType(str, Enum):
    """Feedback sentiment types."""

    UP = "up"
    DOWN = "down"
    FREEFORM = "freeform"


@dataclass(slots=True)
class FeedbackEntry:
    """One feedback record."""

    session_id: str
    feedback_type: FeedbackType
    text: str = ""
    category: str = ""
