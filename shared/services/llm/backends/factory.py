"""Backend identifiers and normalization helpers.

Legacy backend instantiation is intentionally removed in favor of
``shared.services.llm.worker.LLMWorker``.
"""
from __future__ import annotations

from pathlib import Path

BACKEND_AUTO = "auto"
BACKEND_LLAMA_CPP = "llama_cpp"
BACKEND_LITELLM = "litellm"


def normalize_backend_choice(value: str | None) -> str:
    text = str(value or "").strip().casefold()
    if text in {BACKEND_AUTO, BACKEND_LLAMA_CPP, BACKEND_LITELLM}:
        return text
    return BACKEND_AUTO


def infer_backend_choice(model_ref: str, requested_backend: str | None = None) -> str:
    selected = normalize_backend_choice(requested_backend)
    if selected != BACKEND_AUTO:
        return selected
    ref = str(model_ref or "").strip()
    if ref.casefold().endswith(".gguf") or Path(ref).is_file():
        return BACKEND_LLAMA_CPP
    return BACKEND_LITELLM
