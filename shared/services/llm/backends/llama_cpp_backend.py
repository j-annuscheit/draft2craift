"""llama.cpp backend wrapper implementing :class:`BaseLLMBackend`."""
from __future__ import annotations

import gc
import os
from typing import Any

from .base import BaseLLMBackend


class LlamaCppBackend(BaseLLMBackend):
    """Inference backend for local GGUF models via ``llama-cpp-python``."""

    def __init__(self) -> None:
        self._model: Any = None
        self._model_ref: str = ""
        self._load_params: dict[str, Any] = {}
        self._forbidden_bias_cache_model: tuple[str, int] | None = None
        self._forbidden_bias_cache: dict[tuple[str, ...], dict[int, float]] = {}

    @property
    def backend_id(self) -> str:
        return "llama_cpp"

    @property
    def model_ref(self) -> str:
        return str(self._model_ref or "")

    def load_model(
        self,
        model_ref: str,
        *,
        n_ctx: int = 4096,
        n_gpu_layers: int = 0,
        n_threads: int = 0,
        embedding: bool = False,
        flash_attn: bool = True,
    ) -> tuple[bool, str]:
        self.unload_model()
        self._model_ref = str(model_ref or "")
        self._load_params = {
            "n_ctx": int(n_ctx),
            "n_gpu_layers": int(n_gpu_layers),
            "n_threads": int(n_threads or (os.cpu_count() or 4)),
            "embedding": bool(embedding),
            "flash_attn": bool(flash_attn),
            "verbose": False,
        }

        try:
            from llama_cpp import Llama  # type: ignore
        except ImportError:
            return (
                False,
                "llama-cpp-python not installed.\nRun: pip install llama-cpp-python",
            )

        try:
            load_params = dict(self._load_params)
            load_note = ""
            try:
                self._model = Llama(model_path=self._model_ref, **load_params)
            except TypeError as exc:
                msg = str(exc).casefold()
                if "flash_attn" not in msg or "unexpected keyword" not in msg:
                    raise
                load_params.pop("flash_attn", None)
                self._model = Llama(model_path=self._model_ref, **load_params)
                self._load_params = load_params
                load_note = " (flash_attn unsupported in this llama-cpp build)"

            self._forbidden_bias_cache_model = None
            self._forbidden_bias_cache.clear()
            return True, f"✓ {os.path.basename(self._model_ref)}{load_note}"
        except Exception as exc:
            self.unload_model()
            return False, f"Load failed: {exc}"

    def unload_model(self) -> None:
        model = self._model
        self._model = None
        self._forbidden_bias_cache_model = None
        self._forbidden_bias_cache.clear()
        if model is None:
            return
        close_fn = getattr(model, "close", None)
        if callable(close_fn):
            try:
                close_fn()
            except Exception:
                pass
        del model
        gc.collect()

    def is_loaded(self) -> bool:
        return self._model is not None

    def context_window(self, default_n_ctx: int = 4096) -> int:
        try:
            return int(self._load_params.get("n_ctx", default_n_ctx) or default_n_ctx)
        except Exception:
            return int(default_n_ctx)

    def count_tokens(self, text: str) -> int:
        prompt_text = self.prepare_prompt(text)
        model = self._model
        if model is None:
            return max(1, len(str(prompt_text or "")) // 4)

        payload = str(prompt_text or "").encode("utf-8", errors="replace")
        tokenize_fn = getattr(model, "tokenize", None)
        if not callable(tokenize_fn):
            return max(1, len(str(prompt_text or "")) // 4)

        try:
            tokens = tokenize_fn(payload)
            return max(1, len(tokens))
        except Exception:
            return max(1, len(str(prompt_text or "")) // 4)

    def prepare_prompt(self, prompt: str) -> str:
        return str(prompt or "")

    def generate_once(
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
        model = self._model
        if model is None:
            raise RuntimeError("No model loaded.")

        params = self._build_generation_params(
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            repeat_penalty=repeat_penalty,
            stop=stop,
            stream=False,
            forbidden_chars=forbidden_chars,
        )
        prepared_prompt = self.prepare_prompt(prompt)
        result = model(prepared_prompt, **params)
        return str(result["choices"][0].get("text", "") or "")

    def generate_stream(
        self,
        prompt: str,
        *,
        max_tokens: int,
        temperature: float,
        top_p: float,
        repeat_penalty: float,
        stop: list[str] | None = None,
        forbidden_chars: tuple[str, ...] = (),
        stop_requested=None,
    ):
        model = self._model
        if model is None:
            raise RuntimeError("No model loaded.")

        params = self._build_generation_params(
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            repeat_penalty=repeat_penalty,
            stop=stop,
            stream=True,
            forbidden_chars=forbidden_chars,
        )
        should_stop = stop_requested or (lambda: False)
        prepared_prompt = self.prepare_prompt(prompt)
        for chunk in model(prepared_prompt, **params):
            if should_stop():
                break
            token = str(chunk["choices"][0].get("text", "") or "")
            if token:
                yield token

    def _build_generation_params(
        self,
        *,
        max_tokens: int,
        temperature: float,
        top_p: float,
        repeat_penalty: float,
        stop: list[str] | None,
        stream: bool,
        forbidden_chars: tuple[str, ...],
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "max_tokens": max(1, int(max_tokens)),
            "temperature": float(temperature),
            "top_p": float(top_p),
            "repeat_penalty": float(repeat_penalty),
            "stream": bool(stream),
            "stop": list(stop or ["<|"]),
        }
        if forbidden_chars:
            bias = self._build_forbidden_logit_bias(tuple(sorted(set(forbidden_chars))))
            if bias:
                params["logit_bias"] = bias
        return params

    def _build_forbidden_logit_bias(self, forbidden_chars: tuple[str, ...]) -> dict[int, float]:
        if self._model is None or not forbidden_chars:
            return {}

        model_key = (self._model_ref, int(self._model.n_vocab()))
        if self._forbidden_bias_cache_model != model_key:
            self._forbidden_bias_cache_model = model_key
            self._forbidden_bias_cache.clear()

        cached = self._forbidden_bias_cache.get(forbidden_chars)
        if cached is not None:
            return cached

        forbidden_bytes = [ch.encode("utf-8") for ch in forbidden_chars if ch]
        logit_bias: dict[int, float] = {}
        n_vocab = int(self._model.n_vocab())

        for token_id in range(n_vocab):
            piece: bytes
            try:
                piece = self._model.detokenize([token_id], special=True)
            except TypeError:
                try:
                    piece = self._model.detokenize([token_id])
                except Exception:
                    continue
            except Exception:
                continue
            if not piece:
                continue

            if any(fb and fb in piece for fb in forbidden_bytes):
                logit_bias[token_id] = -100.0
                continue

            text = piece.decode("utf-8", errors="ignore")
            if text and any(ch in text for ch in forbidden_chars):
                logit_bias[token_id] = -100.0

        self._forbidden_bias_cache[forbidden_chars] = logit_bias
        return logit_bias
