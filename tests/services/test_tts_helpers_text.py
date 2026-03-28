from __future__ import annotations

from shared.services.speech.tts_parts.helpers_text import _build_speech_jobs


def test_build_speech_jobs_keeps_single_job_for_non_piper_backends():
    text = ("Erster Satz. Zweiter Satz. Dritter Satz. " * 60).strip()

    jobs = _build_speech_jobs(
        text,
        pause_ms=220,
        backend="espeak",
        pause_triggers=",|:|;",
    )

    assert len(jobs) == 1
    payload, pause = jobs[0]
    assert payload
    assert pause == 0


def test_build_speech_jobs_keeps_single_job_for_piper_prefetch_worker():
    text = (
        "Die Welt war ruhig, die Lichter glitzerten, "
        "und der Himmel wirkte unendlich weit. "
    ) * 120

    jobs = _build_speech_jobs(
        text,
        pause_ms=220,
        backend="piper",
        pause_triggers=",|:|;",
    )

    assert len(jobs) == 1
    first_payload, first_pause = jobs[0]
    assert len(first_payload) > 0
    assert first_pause == 0
