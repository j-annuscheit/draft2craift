"""Threaded backend worker for model load and token streaming."""
from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

from PySide6.QtCore import QObject, QThread, Signal

from .backends import BACKEND_AUTO, create_backend, normalize_backend_choice
from .backends.base import BaseLLMBackend


class LLMWorker(QThread):
    """
    Runs one active LLM backend inside a dedicated thread.

    Usage
    -----
    1. Call ``load_model(path_or_id, …)`` → start() → waits for ``model_loaded``
    2. Call ``generate(prompt, …)``       → start() → streams ``token_received``
                                            → emits ``generation_complete``
    """

    token_received = Signal(str)
    generation_complete = Signal(str)
    error_occurred = Signal(str)
    model_loaded = Signal(bool, str)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._backend: BaseLLMBackend | None = None
        self._backend_id: str = ""

        self._task: str = ""  # "load" | "generate"
        self._stop: bool = False

        self._model_path: str = ""
        self._requested_backend: str = BACKEND_AUTO
        self._load_params: dict[str, Any] = {}

        self._prompt: str = ""
        self._gen_params: dict[str, Any] = {}
        self._forbidden_chars: tuple[str, ...] = ()

    def load_model(
        self,
        model_path: str,
        n_ctx: int = 4096,
        n_gpu_layers: int = 0,
        n_threads: int = 0,
        embedding: bool = False,
        flash_attn: bool = True,
        trust_remote_code: bool = False,
        backend: str = BACKEND_AUTO,
    ) -> None:
        self._task = "load"
        self._model_path = str(model_path or "")
        self._requested_backend = normalize_backend_choice(backend)
        self._load_params = {
            "n_ctx": int(n_ctx),
            "n_gpu_layers": int(n_gpu_layers),
            "n_threads": int(n_threads),
            "embedding": bool(embedding),
            "flash_attn": bool(flash_attn),
            "trust_remote_code": bool(trust_remote_code),
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
    ) -> None:
        if not self.is_model_loaded():
            self.error_occurred.emit("No model loaded.")
            return
        self._task = "generate"
        self._prompt = str(prompt or "")
        self._gen_params = {
            "max_tokens": int(max_tokens),
            "temperature": float(temperature),
            "top_p": float(top_p),
            "repeat_penalty": float(repeat_penalty),
            "stop": ["<|"],
        }
        self._forbidden_chars = tuple(sorted(set(forbidden_chars or ())))
        self._stop = False
        if not self.isRunning():
            self.start()

    def request_stop(self) -> None:
        self._stop = True

    def backend_name(self) -> str:
        return str(self._backend_id or "")

    def is_model_loaded(self) -> bool:
        return self._backend is not None and bool(self._backend.is_loaded())

    def context_window(self, default_n_ctx: int = 4096) -> int:
        backend = self._backend
        if backend is None:
            return int(default_n_ctx)
        return int(backend.context_window(default_n_ctx))

    def count_tokens(self, text: str) -> int:
        backend = self._backend
        if backend is None:
            return max(1, len(str(text or "")) // 4)
        return max(1, int(backend.count_tokens(text)))

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
        backend = self._backend
        if backend is None:
            raise RuntimeError("No model loaded.")
        return backend.generate_once(
            str(prompt or ""),
            max_tokens=int(max_tokens),
            temperature=float(temperature),
            top_p=float(top_p),
            repeat_penalty=float(repeat_penalty),
            stop=list(stop or ["<|"]),
            forbidden_chars=tuple(forbidden_chars or ()),
        )

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
        backend = self._backend
        if backend is None:
            raise RuntimeError("No model loaded.")
        return backend.generate_stream(
            str(prompt or ""),
            max_tokens=int(max_tokens),
            temperature=float(temperature),
            top_p=float(top_p),
            repeat_penalty=float(repeat_penalty),
            stop=list(stop or ["<|"]),
            forbidden_chars=tuple(forbidden_chars or ()),
            stop_requested=stop_requested,
        )

    def run(self) -> None:
        if self._task == "load":
            self._do_load()
        elif self._task == "generate":
            self._do_generate()

    def _do_load(self) -> None:
        self._release_loaded_model()
        try:
            backend = create_backend(
                self._model_path,
                requested_backend=self._requested_backend,
            )
            success, message = backend.load_model(
                self._model_path,
                **self._resolved_load_kwargs(),
            )
            if not success:
                self._release_loaded_model()
                self.model_loaded.emit(False, str(message or "Load failed."))
                return

            self._backend = backend
            self._backend_id = str(backend.backend_id or "")
            message_text = str(message or "")
            if self._backend_id:
                message_text = f"{message_text} [{self._backend_id}]"
            self.model_loaded.emit(True, message_text.strip())
        except Exception as exc:
            self._release_loaded_model()
            self.model_loaded.emit(False, f"Load failed: {exc}")

    def _resolved_load_kwargs(self) -> dict[str, Any]:
        params = dict(self._load_params or {})
        return {
            "n_ctx": int(params.get("n_ctx", 4096) or 4096),
            "n_gpu_layers": int(params.get("n_gpu_layers", 0) or 0),
            "n_threads": int(params.get("n_threads", 0) or 0),
            "embedding": bool(params.get("embedding", False)),
            "flash_attn": bool(params.get("flash_attn", True)),
            "trust_remote_code": bool(params.get("trust_remote_code", False)),
        }

    def _release_loaded_model(self) -> None:
        backend = self._backend
        self._backend = None
        self._backend_id = ""
        if backend is None:
            return
        try:
            backend.unload_model()
        except Exception:
            return

    def _do_generate(self) -> None:
        backend = self._backend
        if backend is None:
            self.error_occurred.emit("No model loaded.")
            return

        stop_marker = "<|"
        keep_suffix = len(stop_marker) - 1
        params = dict(self._gen_params)
        params["max_tokens"] = max(1, int(params.get("max_tokens", 1)))

        def _stream_once(run_params: dict[str, Any]) -> tuple[str, bool]:
            full = ""
            buf = ""
            emitted = False
            suppress_output = False
            stop_requested_by_worker = False

            def _stop_requested() -> bool:
                return bool(self._stop) or stop_requested_by_worker

            for token in backend.generate_stream(
                self._prompt,
                max_tokens=int(run_params.get("max_tokens", 1)),
                temperature=float(run_params.get("temperature", 0.7)),
                top_p=float(run_params.get("top_p", 0.9)),
                repeat_penalty=float(run_params.get("repeat_penalty", 1.1)),
                stop=list(run_params.get("stop", ["<|"])),
                forbidden_chars=self._forbidden_chars,
                stop_requested=_stop_requested,
            ):
                if self._stop:
                    suppress_output = True
                    continue

                buf += str(token or "")
                if stop_marker in buf:
                    safe = buf[:buf.index(stop_marker)]
                    if safe:
                        full += safe
                        emitted = True
                        self.token_received.emit(safe)
                    buf = ""
                    suppress_output = True
                    stop_requested_by_worker = True
                    continue

                if suppress_output:
                    continue

                if len(buf) > keep_suffix:
                    emit_now = buf[:-keep_suffix]
                    if emit_now:
                        full += emit_now
                        emitted = True
                        self.token_received.emit(emit_now)
                    buf = buf[-keep_suffix:]

            else:
                if buf and (not suppress_output):
                    full += buf
                    emitted = True
                    self.token_received.emit(buf)
                return full, emitted

        emitted = False
        try:
            n_ctx = int(backend.context_window(int(self._load_params.get("n_ctx", 4096) or 4096)))
            prompt_tokens = int(backend.count_tokens(self._prompt))
            reserve = 16
            available = max(0, n_ctx - prompt_tokens - reserve)
            requested = int(params.get("max_tokens", 1))
            if available <= 0:
                self.error_occurred.emit(
                    "Generation error: Prompt exceeds model context window. "
                    "Reduce context or max tokens."
                )
                return
            if requested > available:
                params["max_tokens"] = max(1, available)

            full, emitted = _stream_once(params)
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

            retry_params = dict(params)
            retry_params["max_tokens"] = max(32, int(retry_params.get("max_tokens", 64)) // 2)
            try:
                full, _retry_emitted = _stream_once(retry_params)
                self.generation_complete.emit(full)
            except Exception as retry_exc:
                self.error_occurred.emit(f"Generation error: {retry_exc}")
