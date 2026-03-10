"""Bind split methods to _SpeechWorker."""
from __future__ import annotations

from . import worker_methods

def bind_speech_worker_methods(cls):
    for name in getattr(worker_methods, "__all__", ()):
        setattr(cls, name, getattr(worker_methods, name))

__all__ = ["bind_speech_worker_methods"]
