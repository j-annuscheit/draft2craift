"""Feedback feature settings shared between GUI and service."""
from __future__ import annotations

from dataclasses import asdict, dataclass


FEEDBACK_USE_CASES: tuple[str, ...] = (
    "input",
    "rag_search",
    "chat_answer",
    "canvas_edit",
    "mindmap",
    "glossary",
    "fact_check",
    "tts",
    "stt",
    "other",
)


def normalize_use_case(value: object) -> str:
    text = str(value or "").strip().lower()
    if text in FEEDBACK_USE_CASES:
        return text
    return "other"


def _as_bool(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(int(value))
    text = str(value or "").strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


@dataclass
class FeedbackSettings:
    """Runtime settings for user feedback collection."""

    ui_enabled: bool = True
    capture_payload_enabled: bool = True
    storage_dir: str = "runs/feedback"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: object) -> "FeedbackSettings":
        if not isinstance(raw, dict):
            return cls()
        storage_dir = str(raw.get("storage_dir", cls().storage_dir) or "").strip()
        if not storage_dir:
            storage_dir = cls().storage_dir
        return cls(
            ui_enabled=_as_bool(raw.get("ui_enabled"), cls().ui_enabled),
            capture_payload_enabled=_as_bool(
                raw.get("capture_payload_enabled"),
                cls().capture_payload_enabled,
            ),
            storage_dir=storage_dir,
        )
