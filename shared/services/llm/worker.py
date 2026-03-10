"""Threaded llama.cpp worker for model load and token streaming."""
from __future__ import annotations

import gc
import os
import threading
from typing import Any

from PySide6.QtCore import QObject, QThread, Signal


class LLMWorker(QThread):
    """
    Runs llama_cpp.Llama inside a dedicated thread so the UI never blocks.

    Usage
    -----
    1. Call ``load_model(path, …)`` → start() → waits for ``model_loaded``
    2. Call ``generate(prompt, …)``  → start() → streams ``token_received``
                                                 → emits ``generation_complete``
    """

    token_received = Signal(str)
    generation_complete = Signal(str)
    error_occurred = Signal(str)
    model_loaded = Signal(bool, str)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._model: Any = None
        self._task: str = ""  # "load" | "generate"
        self._stop: bool = False

        self._model_path: str = ""
        self._load_params: dict[str, Any] = {}

        self._prompt: str = ""
        self._gen_params: dict[str, Any] = {}
        self._forbidden_chars: tuple[str, ...] = ()
        self._forbidden_bias_cache_model: tuple[str, int] | None = None
        self._forbidden_bias_cache: dict[tuple[str, ...], dict[int, float]] = {}
        self._model_thread_ident: int | None = None

    def load_model(
        self,
        model_path: str,
        n_ctx: int = 4096,
        n_gpu_layers: int = 0,
        n_threads: int = 0,
        embedding: bool = False,
        flash_attn: bool = True,
    ):
        self._task = "load"
        self._model_path = model_path
        self._load_params = {
            "n_ctx": n_ctx,
            "n_gpu_layers": n_gpu_layers,
            "n_threads": n_threads or (os.cpu_count() or 4),
            "embedding": bool(embedding),
            "flash_attn": bool(flash_attn),
            "verbose": False,
        }
        if not self.isRunning():
            self.start()

    def generate(
        self,
        prompt: str,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        top_p: float = 0.9,
        repeat_penalty: float = 1.1,
        forbidden_chars: tuple[str, ...] | None = None,
    ):
        if self._model is None:
            self.error_occurred.emit("No model loaded.")
            return
        self._task = "generate"
        self._prompt = prompt
        self._gen_params = {
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": top_p,
            "repeat_penalty": repeat_penalty,
            "stream": True,
            "stop": ["<|"],
        }
        self._forbidden_chars = tuple(sorted(set(forbidden_chars or ())))
        self._stop = False
        if not self.isRunning():
            self.start()

    def request_stop(self):
        self._stop = True

    def run(self):
        if self._task == "load":
            self._do_load()
        elif self._task == "generate":
            self._do_generate()

    def _do_load(self):
        try:
            self._release_loaded_model()
            from llama_cpp import Llama  # type: ignore

            load_params = dict(self._load_params)
            load_note = ""
            try:
                self._model = Llama(model_path=self._model_path, **load_params)
            except TypeError as exc:
                msg = str(exc).casefold()
                if "flash_attn" not in msg or "unexpected keyword" not in msg:
                    raise
                load_params.pop("flash_attn", None)
                self._model = Llama(model_path=self._model_path, **load_params)
                self._load_params = load_params
                load_note = " (flash_attn unsupported in this llama-cpp build)"

            self._model_thread_ident = int(threading.get_ident())
            self._forbidden_bias_cache_model = None
            self._forbidden_bias_cache.clear()
            self.model_loaded.emit(
                True,
                f"✓ {os.path.basename(self._model_path)}{load_note}",
            )
        except ImportError:
            self.model_loaded.emit(
                False,
                "llama-cpp-python not installed.\nRun: pip install llama-cpp-python",
            )
        except Exception as exc:
            self.model_loaded.emit(False, f"Load failed: {exc}")

    def _release_loaded_model(self):
        model = self._model
        self._model = None
        self._model_thread_ident = None
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

    def _count_prompt_tokens(self, text: str) -> int:
        model = self._model
        if model is None:
            return max(1, len(text) // 4)

        payload = text.encode("utf-8", errors="replace")
        tokenize_fn = getattr(model, "tokenize", None)
        if not callable(tokenize_fn):
            return max(1, len(text) // 4)

        try:
            tokens = tokenize_fn(payload)
            return max(1, len(tokens))
        except Exception:
            return max(1, len(text) // 4)

    def _build_forbidden_logit_bias(self) -> dict[int, float]:
        if self._model is None or not self._forbidden_chars:
            return {}

        model_key = (self._model_path, int(self._model.n_vocab()))
        if self._forbidden_bias_cache_model != model_key:
            self._forbidden_bias_cache_model = model_key
            self._forbidden_bias_cache.clear()

        key = self._forbidden_chars
        cached = self._forbidden_bias_cache.get(key)
        if cached is not None:
            return cached

        forbidden_bytes = [ch.encode("utf-8") for ch in key if ch]
        logit_bias: dict[int, float] = {}
        n_vocab = int(self._model.n_vocab())

        for tid in range(n_vocab):
            piece: bytes
            try:
                piece = self._model.detokenize([tid], special=True)
            except TypeError:
                try:
                    piece = self._model.detokenize([tid])
                except Exception:
                    continue
            except Exception:
                continue

            if not piece:
                continue

            if any(fb and fb in piece for fb in forbidden_bytes):
                logit_bias[tid] = -100.0
                continue

            text = piece.decode("utf-8", errors="ignore")
            if text and any(ch in text for ch in key):
                logit_bias[tid] = -100.0

        self._forbidden_bias_cache[key] = logit_bias
        return logit_bias

    def _do_generate(self):
        STOP = "<|"
        keep = len(STOP) - 1
        emitted = False
        gen_params: dict[str, Any] = dict(self._gen_params)

        def _stream_once(params: dict[str, Any]) -> tuple[str, bool]:
            full = ""
            buf = ""
            emitted_local = False

            for chunk in self._model(self._prompt, **params):
                if self._stop:
                    break
                token = chunk["choices"][0].get("text", "")
                if not token:
                    continue

                buf += token

                if STOP in buf:
                    safe = buf[: buf.index(STOP)]
                    if safe:
                        full += safe
                        emitted_local = True
                        self.token_received.emit(safe)
                    break

                if len(buf) > keep:
                    emit = buf[:-keep]
                    if emit:
                        full += emit
                        emitted_local = True
                        self.token_received.emit(emit)
                    buf = buf[-keep:]

            else:
                if buf:
                    full += buf
                    emitted_local = True
                    self.token_received.emit(buf)

            return full, emitted_local

        try:
            if self._forbidden_chars:
                bias = self._build_forbidden_logit_bias()
                if bias:
                    gen_params["logit_bias"] = bias

            n_ctx = int(self._load_params.get("n_ctx", 4096) or 4096)
            prompt_tokens = self._count_prompt_tokens(self._prompt)
            reserve = 16
            available = max(0, n_ctx - prompt_tokens - reserve)
            requested_max = max(1, int(gen_params.get("max_tokens", 1)))
            if available <= 0:
                self.error_occurred.emit(
                    "Generation error: Prompt exceeds model context window. "
                    "Reduce context or max tokens."
                )
                return
            if requested_max > available:
                gen_params["max_tokens"] = max(1, available)

            full, emitted = _stream_once(gen_params)
            self.generation_complete.emit(full)
        except Exception as exc:
            msg = str(exc).casefold()
            is_decode_error = "llama_decode returned -1" in msg
            if not is_decode_error:
                self.error_occurred.emit(f"Generation error: {exc}")
                return

            if emitted:
                self.error_occurred.emit(f"Generation error: {exc}")
                return

            reset_fn = getattr(self._model, "reset", None)
            if callable(reset_fn):
                try:
                    reset_fn()
                except Exception:
                    pass

            retry_params = dict(gen_params)
            retry_tokens = max(32, int(retry_params.get("max_tokens", 64)) // 2)
            retry_params["max_tokens"] = retry_tokens
            try:
                full, _ = _stream_once(retry_params)
                self.generation_complete.emit(full)
                return
            except Exception as retry_exc:
                self.error_occurred.emit(f"Generation error: {retry_exc}")
