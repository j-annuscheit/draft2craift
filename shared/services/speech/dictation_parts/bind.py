"""Bind split method implementations to WhisperDictationWorker."""
from __future__ import annotations

from . import (
    audio_backends,
    arecord_io,
    transcription,
    model_config,
    device_selection,
    audio_energy,
)

_METHOD_MODULES = (
    audio_backends,
    arecord_io,
    transcription,
    model_config,
    device_selection,
    audio_energy,
)

def bind_whisper_dictation_worker(cls):
    for module in _METHOD_MODULES:
        for name in getattr(module, "__all__", ()):
            setattr(cls, name, getattr(module, name))
