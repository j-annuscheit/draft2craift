"""Lightweight runtime worker built on top of LiteLLM and llama.cpp."""
from __future__ import annotations

from collections.abc import Callable, Iterator
import os
from pathlib import Path
from typing import Any

from shared.services.local_policy import is_local_litellm_target


class LLMWorker:
    """Synchronous worker adapter with the legacy API surface."""

    def __init__(self) -> None:
        self._busy = False
        self._stop_requested = False
        self._backend_id = ""
        self._model_ref = ""
        self._n_ctx = 4096
        self._llama = None

    def load_model(
        self,
        model_path: str,
        n_ctx: int = 4096,
        n_gpu_layers: int = 0,
        n_threads: int = 0,
        flash_attn: bool = True,
        trust_remote_code: bool = False,
        backend: str = "auto",
    ) -> tuple[bool, str]:
        _ = flash_attn, trust_remote_code
        self._llama = None
        self._model_ref = str(model_path or "").strip()
        self._n_ctx = max(512, int(n_ctx or 4096))
        self._stop_requested = False
        use_llama_cpp = (
            str(backend or "").strip().casefold() == "llama_cpp"
            or self._model_ref.casefold().endswith(".gguf")
            or Path(self._model_ref).is_file()
        )
        if use_llama_cpp:
            try:
                from llama_cpp import Llama  # type: ignore

                threads = int(n_threads or (os.cpu_count() or 4))
                self._llama = Llama(
                    model_path=self._model_ref,
                    n_ctx=self._n_ctx,
                    n_gpu_layers=int(n_gpu_layers or 0),
                    n_threads=max(1, threads),
                    verbose=False,
                )
                self._backend_id = "llama_cpp"
                return True, f"Model loaded ({self._backend_id})"
            except Exception as exc:
                self._llama = None
                return False, f"llama.cpp load failed: {exc}"

        # LiteLLM model-id mode (provider/model string) - local-first guard.
        self._backend_id = "litellm"
        if not self._model_ref:
            return False, "Model identifier must not be empty."
        if not self._is_local_litellm_allowed(self._model_ref):
            return (
                False,
                "Remote LLM model blocked by local-first policy. "
                "Use a local model (.gguf) or set D2C_ALLOW_REMOTE_LLM=1 explicitly.",
            )
        return True, f"Model loaded ({self._backend_id})"

    def request_stop(self) -> None:
        self._stop_requested = True

    def isRunning(self) -> bool:  # noqa: N802 - Qt compatibility
        return bool(self._busy)

    def backend_name(self) -> str:
        return str(self._backend_id or "")

    def is_model_loaded(self) -> bool:
        if self._llama is not None:
            return True
        return bool(self._model_ref.strip())

    def context_window(self, default_n_ctx: int = 4096) -> int:
        return int(self._n_ctx or default_n_ctx)

    def count_tokens(self, text: str) -> int:
        sample = str(text or "")
        if not sample:
            return 0
        if self._llama is not None:
            try:
                encoded = self._llama.tokenize(sample.encode("utf-8"), add_bos=False)
                return int(len(encoded))
            except Exception:
                pass
        return max(1, len(sample) // 4)

    def run_completion_sync(
        self,
        prompt: str,
        *,
        max_tokens: int,
        temperature: float,
        top_p: float,
        repeat_penalty: float,
        stop: list[str] | None = None,
        forbidden_chars: tuple[str, ...] = (),
    ) -> str:
        text = str(prompt or "")
        self._busy = True
        self._stop_requested = False
        try:
            if self._llama is not None:
                response = self._llama.create_completion(
                    prompt=text,
                    max_tokens=max(1, int(max_tokens or 1)),
                    temperature=float(temperature),
                    top_p=float(top_p),
                    repeat_penalty=float(repeat_penalty),
                    stop=list(stop or ["<|"]),
                    stream=False,
                )
                result = str(
                    (((response or {}).get("choices") or [{}])[0]).get("text", "") or ""
                )
                return self._apply_forbidden_filter(result, forbidden_chars)

            from litellm import completion  # type: ignore

            local_api_base = self._local_api_base()
            if not self._is_local_litellm_allowed(self._model_ref):
                raise RuntimeError(
                    "Remote LLM request blocked by local-first policy. "
                    "Set D2C_ALLOW_REMOTE_LLM=1 for explicit opt-in."
                )
            response = completion(
                model=self._model_ref,
                messages=[{"role": "user", "content": text}],
                max_tokens=max(1, int(max_tokens or 1)),
                temperature=float(temperature),
                top_p=float(top_p),
                stop=list(stop or ["<|"]),
                api_base=local_api_base or None,
            )
            choice = ((response or {}).get("choices") or [{}])[0]
            message = choice.get("message", {}) if isinstance(choice, dict) else {}
            content = ""
            if isinstance(message, dict):
                content = str(message.get("content", "") or "")
            if not content:
                content = str(choice.get("text", "") or "") if isinstance(choice, dict) else ""
            return self._apply_forbidden_filter(content, forbidden_chars)
        finally:
            self._busy = False

    def iter_completion_sync(
        self,
        prompt: str,
        *,
        max_tokens: int,
        temperature: float,
        top_p: float,
        repeat_penalty: float,
        stop: list[str] | None = None,
        forbidden_chars: tuple[str, ...] = (),
        stop_requested: Callable[[], bool] | None = None,
    ) -> Iterator[str]:
        should_stop = stop_requested or (lambda: False)
        self._busy = True
        self._stop_requested = False
        try:
            if self._llama is not None:
                stream = self._llama.create_completion(
                    prompt=str(prompt or ""),
                    max_tokens=max(1, int(max_tokens or 1)),
                    temperature=float(temperature),
                    top_p=float(top_p),
                    repeat_penalty=float(repeat_penalty),
                    stop=list(stop or ["<|"]),
                    stream=True,
                )
                for chunk in stream:
                    if self._stop_requested or should_stop():
                        break
                    raw = str(
                        (((chunk or {}).get("choices") or [{}])[0]).get("text", "") or ""
                    )
                    filtered = self._apply_forbidden_filter(raw, forbidden_chars)
                    if filtered:
                        yield filtered
                return

            from litellm import completion  # type: ignore

            local_api_base = self._local_api_base()
            if not self._is_local_litellm_allowed(self._model_ref):
                raise RuntimeError(
                    "Remote LLM request blocked by local-first policy. "
                    "Set D2C_ALLOW_REMOTE_LLM=1 for explicit opt-in."
                )
            stream = completion(
                model=self._model_ref,
                messages=[{"role": "user", "content": str(prompt or "")}],
                max_tokens=max(1, int(max_tokens or 1)),
                temperature=float(temperature),
                top_p=float(top_p),
                stop=list(stop or ["<|"]),
                stream=True,
                api_base=local_api_base or None,
            )
            for chunk in stream:
                if self._stop_requested or should_stop():
                    break
                delta = (((chunk or {}).get("choices") or [{}])[0]).get("delta", {})
                piece = str((delta or {}).get("content", "") or "")
                filtered = self._apply_forbidden_filter(piece, forbidden_chars)
                if filtered:
                    yield filtered
        finally:
            self._busy = False

    def shutdown(self) -> bool:
        self._llama = None
        self._busy = False
        self._stop_requested = False
        return True

    @staticmethod
    def _apply_forbidden_filter(text: str, forbidden_chars: tuple[str, ...]) -> str:
        out = str(text or "")
        for char in tuple(forbidden_chars or ()):
            if not char:
                continue
            out = out.replace(str(char), "")
        return out

    @staticmethod
    def _is_local_litellm_allowed(model_ref: str) -> bool:
        return is_local_litellm_target(model_ref=model_ref, api_base=LLMWorker._local_api_base())

    @staticmethod
    def _local_api_base() -> str:
        return str(os.environ.get("LITELLM_LOCAL_API_BASE", "") or "").strip()
