"""Feedback event storage and counter aggregation."""
from __future__ import annotations

from datetime import datetime, timezone
import getpass
import json
import os
from pathlib import Path
import socket
import uuid
from typing import Any

from shared.config.paths import app_data_dir

from .settings import FeedbackSettings, normalize_use_case


_EVENTS_FILE = "feedback_events.jsonl"
_COUNTERS_FILE = "feedback_counters.json"
_SENTIMENTS = {"positive", "negative"}


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_user_id() -> str:
    env_value = str(os.getenv("DRAFT2CRAIFT_FEEDBACK_USER", "") or "").strip()
    if env_value:
        return env_value
    user = str(getpass.getuser() or "user").strip() or "user"
    host = str(socket.gethostname() or "host").strip() or "host"
    return f"{user}@{host}"


def _safe_int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _default_counters() -> dict[str, Any]:
    return {
        "version": 1,
        "updated_at": "",
        "total": {"events": 0, "positive": 0, "negative": 0},
        "by_use_case": {},
        "by_day": {},
    }


def _to_json_safe(value: Any, depth: int = 0) -> Any:
    if depth >= 8:
        return str(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in list(value.items())[:200]:
            out[str(key)] = _to_json_safe(item, depth + 1)
        return out
    if isinstance(value, (list, tuple, set)):
        return [
            _to_json_safe(item, depth + 1)
            for item in list(value)[:400]
        ]
    return str(value)


class FeedbackService:
    """Collect feedback events and keep aggregated counters on disk."""

    def __init__(self, settings: FeedbackSettings | None = None, logger: Any = None):
        self._settings = FeedbackSettings.from_dict(
            settings.to_dict() if isinstance(settings, FeedbackSettings) else {}
        )
        self._log = logger

    @property
    def settings(self) -> FeedbackSettings:
        return FeedbackSettings.from_dict(self._settings.to_dict())

    def update_settings(self, settings: FeedbackSettings):
        self._settings = FeedbackSettings.from_dict(settings.to_dict())

    def storage_dir(self) -> Path:
        raw = str(self._settings.storage_dir or "").strip()
        if not raw:
            raw = FeedbackSettings().storage_dir
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = app_data_dir() / path
        return path.resolve(strict=False)

    def events_path(self) -> Path:
        return self.storage_dir() / _EVENTS_FILE

    def counters_path(self) -> Path:
        return self.storage_dir() / _COUNTERS_FILE

    def submit_feedback(
        self,
        *,
        use_case: str,
        sentiment: str,
        payload: dict[str, Any] | None = None,
        source: str = "gui",
        note: str = "",
        error_tags: list[str] | None = None,
    ) -> tuple[bool, str]:
        """Persist one feedback event and update counters."""
        if not self._settings.ui_enabled:
            return False, "feedback_ui_disabled"

        clean_sentiment = str(sentiment or "").strip().lower()
        if clean_sentiment not in _SENTIMENTS:
            return False, f"invalid_sentiment:{clean_sentiment}"

        clean_use_case = normalize_use_case(use_case)
        event_id = f"fb_{uuid.uuid4().hex[:12]}"
        event: dict[str, Any] = {
            "event_id": event_id,
            "timestamp": _utc_iso(),
            "user_id": _default_user_id(),
            "use_case": clean_use_case,
            "sentiment": clean_sentiment,
            "source": str(source or "").strip() or "gui",
            "note": str(note or "").strip(),
        }
        clean_tags = [str(t) for t in (error_tags or []) if str(t).strip()]
        if clean_tags:
            event["error_tags"] = clean_tags
        if self._settings.capture_payload_enabled and payload:
            event["payload"] = _to_json_safe(payload)

        try:
            path = self.events_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(event, ensure_ascii=False) + "\n")

            counters = self._load_counters()
            self._apply_event_to_counters(counters, event)
            self._save_counters(counters)
            return True, event_id
        except Exception as exc:
            if self._log:
                self._log.error("FDBK", f"Feedback save failed: {exc}")
            return False, str(exc)

    def get_counters(self) -> dict[str, Any]:
        return self._load_counters()

    def _load_counters(self) -> dict[str, Any]:
        path = self.counters_path()
        if not path.exists():
            return _default_counters()
        try:
            with open(path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
            return self._validate_counters_payload(raw)
        except Exception as exc:
            if self._log:
                self._log.warning(
                    "FDBK",
                    f"Invalid feedback counters JSON, using defaults: {exc}",
                )
            return _default_counters()

    def _save_counters(self, counters: dict[str, Any]):
        path = self.counters_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(counters, fh, ensure_ascii=False, indent=2)

    def _validate_counters_payload(self, raw: object) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise ValueError("feedback_counters.json top-level JSON must be an object.")

        required_fields = ("version", "total", "by_use_case", "by_day")
        for field in required_fields:
            if field not in raw:
                raise ValueError(f"feedback_counters.json missing required field '{field}'.")

        version = raw.get("version")
        if not isinstance(version, int):
            raise ValueError(
                f"feedback_counters.json field 'version' must be int, got {type(version).__name__}."
            )

        total = raw.get("total")
        if not isinstance(total, dict):
            raise ValueError(
                f"feedback_counters.json field 'total' must be object, got {type(total).__name__}."
            )

        by_use_case_raw = raw.get("by_use_case")
        if not isinstance(by_use_case_raw, dict):
            raise ValueError(
                f"feedback_counters.json field 'by_use_case' must be object, got {type(by_use_case_raw).__name__}."
            )
        by_day_raw = raw.get("by_day")
        if not isinstance(by_day_raw, dict):
            raise ValueError(
                f"feedback_counters.json field 'by_day' must be object, got {type(by_day_raw).__name__}."
            )

        normalized = _default_counters()
        normalized["version"] = int(version)
        normalized["updated_at"] = str(raw.get("updated_at", "") or "")
        normalized["total"] = self._normalize_counter_row(total)

        by_use_case: dict[str, dict[str, int | str]] = {}
        for key, value in by_use_case_raw.items():
            if not isinstance(value, dict):
                continue
            row = self._normalize_counter_row(value)
            last_ts = str(value.get("last_timestamp", "") or "")
            if last_ts:
                row["last_timestamp"] = last_ts
            by_use_case[str(key)] = row
        normalized["by_use_case"] = by_use_case

        by_day: dict[str, dict[str, int]] = {}
        for key, value in by_day_raw.items():
            if not isinstance(value, dict):
                continue
            by_day[str(key)] = self._normalize_counter_row(value)
        normalized["by_day"] = by_day
        return normalized

    @staticmethod
    def _normalize_counter_row(raw: Any) -> dict[str, int]:
        row = raw if isinstance(raw, dict) else {}
        return {
            "events": max(0, _safe_int(row.get("events"), 0)),
            "positive": max(0, _safe_int(row.get("positive"), 0)),
            "negative": max(0, _safe_int(row.get("negative"), 0)),
        }

    def _apply_event_to_counters(
        self,
        counters: dict[str, Any],
        event: dict[str, Any],
    ):
        sentiment = str(event.get("sentiment", "")).strip().lower()
        use_case = normalize_use_case(event.get("use_case", ""))
        ts = str(event.get("timestamp", "")).strip()
        day_key = ts[:10] if len(ts) >= 10 else "unknown"

        total = self._normalize_counter_row(counters.get("total"))
        total["events"] += 1
        if sentiment in _SENTIMENTS:
            total[sentiment] += 1
        counters["total"] = total

        by_use_case = counters.get("by_use_case")
        if not isinstance(by_use_case, dict):
            by_use_case = {}
            counters["by_use_case"] = by_use_case
        uc_row = self._normalize_counter_row(by_use_case.get(use_case))
        uc_row["events"] += 1
        if sentiment in _SENTIMENTS:
            uc_row[sentiment] += 1
        uc_row["last_timestamp"] = ts
        by_use_case[use_case] = uc_row

        by_day = counters.get("by_day")
        if not isinstance(by_day, dict):
            by_day = {}
            counters["by_day"] = by_day
        day_row = self._normalize_counter_row(by_day.get(day_key))
        day_row["events"] += 1
        if sentiment in _SENTIMENTS:
            day_row[sentiment] += 1
        by_day[day_key] = day_row

        counters["updated_at"] = _utc_iso()
