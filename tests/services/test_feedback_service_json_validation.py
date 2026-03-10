from __future__ import annotations

import json
from pathlib import Path

from shared.services.feedback.service import FeedbackService
from shared.services.feedback.settings import FeedbackSettings


def _new_service(tmp_path: Path) -> FeedbackService:
    settings = FeedbackSettings(storage_dir=str(tmp_path))
    return FeedbackService(settings=settings)


def test_get_counters_falls_back_to_defaults_on_non_object_json(tmp_path: Path):
    service = _new_service(tmp_path)
    service.counters_path().parent.mkdir(parents=True, exist_ok=True)
    service.counters_path().write_text("[]", encoding="utf-8")

    counters = service.get_counters()

    assert counters["version"] == 1
    assert counters["total"] == {"events": 0, "positive": 0, "negative": 0}
    assert counters["by_use_case"] == {}
    assert counters["by_day"] == {}


def test_get_counters_falls_back_to_defaults_on_missing_required_field(tmp_path: Path):
    service = _new_service(tmp_path)
    service.counters_path().parent.mkdir(parents=True, exist_ok=True)
    service.counters_path().write_text(
        json.dumps(
            {
                "version": 1,
                # "total" intentionally missing
                "by_use_case": {},
                "by_day": {},
            }
        ),
        encoding="utf-8",
    )

    counters = service.get_counters()

    assert counters["version"] == 1
    assert counters["total"]["events"] == 0


def test_submit_feedback_recovers_from_invalid_counter_schema(tmp_path: Path):
    service = _new_service(tmp_path)
    service.counters_path().parent.mkdir(parents=True, exist_ok=True)
    service.counters_path().write_text(
        json.dumps({"version": "x", "total": [], "by_use_case": {}, "by_day": {}}),
        encoding="utf-8",
    )

    ok, event_id = service.submit_feedback(
        use_case="chat_answer",
        sentiment="positive",
        payload={"k": "v"},
    )

    assert ok is True
    assert str(event_id).startswith("fb_")

    counters = service.get_counters()
    assert counters["total"]["events"] == 1
    assert counters["total"]["positive"] == 1
    assert counters["total"]["negative"] == 0
