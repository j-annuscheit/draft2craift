"""Factory helpers for selecting and creating LLM backends."""
from __future__ import annotations

from .base import BaseLLMBackend
from .llama_cpp_backend import LlamaCppBackend
from .transformers_backend import TransformersBackend

BACKEND_AUTO = "auto"
BACKEND_LLAMA_CPP = "llama_cpp"
BACKEND_TRANSFORMERS = "transformers"

_GGUF_SUFFIXES = (".gguf", ".bin")


def normalize_backend_choice(value: str | None) -> str:
    token = str(value or BACKEND_AUTO).strip().casefold()
    if token in {BACKEND_AUTO, BACKEND_LLAMA_CPP, BACKEND_TRANSFORMERS}:
        return token
    return BACKEND_AUTO


def infer_backend_choice(model_ref: str, requested_backend: str | None = None) -> str:
    requested = normalize_backend_choice(requested_backend)
    if requested != BACKEND_AUTO:
        return requested

    ref = str(model_ref or "").strip().casefold()
    if ref.endswith(_GGUF_SUFFIXES):
        return BACKEND_LLAMA_CPP
    return BACKEND_TRANSFORMERS


def create_backend(model_ref: str, requested_backend: str | None = None) -> BaseLLMBackend:
    backend_id = infer_backend_choice(model_ref, requested_backend=requested_backend)
    if backend_id == BACKEND_LLAMA_CPP:
        return LlamaCppBackend()
    if backend_id == BACKEND_TRANSFORMERS:
        return TransformersBackend()
    # Defensive fallback for future choices.
    return TransformersBackend()
