from __future__ import annotations

from dataclasses import dataclass

import pytest

from shared.services.speech.tts_parts import worker_methods


@dataclass
class _SettingsStub:
    tts_rate: int = 100
    tts_speaker_id: int = -1


class _WorkerStub:
    def __init__(self, run_process):
        self._settings = _SettingsStub()
        self._run_process = run_process


def test_has_speakable_text_filters_punctuation_only_payloads():
    assert worker_methods._has_speakable_text("Hallo.")
    assert worker_methods._has_speakable_text("123")
    assert not worker_methods._has_speakable_text("...")
    assert not worker_methods._has_speakable_text(" , ; : ")


def test_is_piper_no_audio_error_detects_wave_channel_traceback():
    assert worker_methods._is_piper_no_audio_error("wave.Error: # channels not specified")
    assert worker_methods._is_piper_no_audio_error("CHANNELS NOT SPECIFIED")
    assert not worker_methods._is_piper_no_audio_error("model not found")


def test_build_piper_sentence_groups_starts_with_short_first_group():
    text = (
        "Das ist ein erster etwas laengerer Satz, der moeglichst frueh starten soll. "
        "Hier kommt Satz zwei mit weiteren Informationen. "
        "Satz drei folgt ebenfalls."
    )

    groups = worker_methods._build_piper_sentence_groups(text)

    assert len(groups) >= 2
    assert len(groups[0]) <= 240
    assert all(worker_methods._has_speakable_text(group) for group in groups)


def test_build_piper_sentence_groups_ignores_comma_splitting():
    text = (
        "Erster Satz, mit Komma, aber ohne Komma-Chunking. "
        "Zweiter Satz, ebenfalls mit mehreren, Kommas."
    )

    groups = worker_methods._build_piper_sentence_groups(text)

    assert len(groups) >= 1
    joined = " ".join(groups)
    assert "," in joined
    assert "Komma-Chunking" in joined


def test_synthesize_piper_to_wav_returns_false_for_unspeakable_text():
    called = {"count": 0}

    def _run_process(*, cmd, stdin_text):
        _ = (cmd, stdin_text)
        called["count"] += 1

    worker = _WorkerStub(_run_process)
    ok = worker_methods._synthesize_piper_to_wav(
        worker,
        text="...",
        model_path="/tmp/model.onnx",
        wav_path="/tmp/out.wav",
        sentence_pause_s=0.0,
    )

    assert ok is False
    assert called["count"] == 0


def test_synthesize_piper_to_wav_returns_false_for_piper_no_audio_error():
    def _run_process(*, cmd, stdin_text):
        _ = (cmd, stdin_text)
        raise RuntimeError("wave.Error: # channels not specified")

    worker = _WorkerStub(_run_process)
    ok = worker_methods._synthesize_piper_to_wav(
        worker,
        text="Nur : ; !",
        model_path="/tmp/model.onnx",
        wav_path="/tmp/out.wav",
        sentence_pause_s=0.0,
    )

    assert ok is False


def test_synthesize_piper_to_wav_raises_for_unrelated_errors():
    def _run_process(*, cmd, stdin_text):
        _ = (cmd, stdin_text)
        raise RuntimeError("Process failed (1)")

    worker = _WorkerStub(_run_process)
    with pytest.raises(RuntimeError, match="Process failed"):
        worker_methods._synthesize_piper_to_wav(
            worker,
            text="Hallo Welt",
            model_path="/tmp/model.onnx",
            wav_path="/tmp/out.wav",
            sentence_pause_s=0.0,
        )
