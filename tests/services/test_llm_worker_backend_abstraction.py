from __future__ import annotations

from collections.abc import Callable

from shared.services.llm.backends.base import BaseLLMBackend
import shared.services.llm.worker as worker_module
from shared.services.llm.worker import LLMWorker


class _FakeBackend(BaseLLMBackend):
    def __init__(self, backend_id: str, stream_tokens: list[str] | None = None):
        self._backend_id = backend_id
        self._loaded = False
        self._model_ref = ""
        self._stream_tokens = list(stream_tokens or ["Hello ", "World"])

    @property
    def backend_id(self) -> str:
        return self._backend_id

    @property
    def model_ref(self) -> str:
        return self._model_ref

    def load_model(self, model_ref: str, **kwargs):  # noqa: ANN003
        _ = kwargs
        self._loaded = True
        self._model_ref = str(model_ref or "")
        return True, f"loaded:{self._model_ref}"

    def unload_model(self) -> None:
        self._loaded = False

    def is_loaded(self) -> bool:
        return self._loaded

    def context_window(self, default_n_ctx: int = 4096) -> int:
        return int(default_n_ctx)

    def count_tokens(self, text: str) -> int:
        return max(1, len(str(text or "").split()))

    def prepare_prompt(self, prompt: str) -> str:
        return str(prompt or "")

    def generate_once(self, prompt: str, **kwargs):  # noqa: ANN003
        _ = prompt, kwargs
        return "sync-output"

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
        stop_requested: Callable[[], bool] | None = None,
    ):
        _ = (
            prompt,
            max_tokens,
            temperature,
            top_p,
            repeat_penalty,
            stop,
            forbidden_chars,
        )
        should_stop = stop_requested or (lambda: False)
        for token in self._stream_tokens:
            if should_stop():
                break
            yield token


def test_worker_load_uses_factory_choice(monkeypatch):
    created: list[_FakeBackend] = []

    def _fake_create_backend(model_ref: str, requested_backend: str | None = None):
        _ = requested_backend
        backend_id = "llama_cpp" if str(model_ref).endswith(".gguf") else "transformers"
        backend = _FakeBackend(backend_id)
        created.append(backend)
        return backend

    monkeypatch.setattr(worker_module, "create_backend", _fake_create_backend)
    worker = LLMWorker()
    worker._model_path = "demo.gguf"
    worker._requested_backend = "auto"
    worker._load_params = {"n_ctx": 2048}

    results: list[tuple[bool, str]] = []
    worker.model_loaded.connect(lambda ok, msg: results.append((bool(ok), str(msg))))
    worker._do_load()

    assert worker.is_model_loaded() is True
    assert worker.backend_name() == "llama_cpp"
    assert results and results[-1][0] is True
    assert created and created[-1].model_ref == "demo.gguf"


def test_worker_streams_tokens_through_backend(monkeypatch):
    def _fake_create_backend(model_ref: str, requested_backend: str | None = None):
        _ = model_ref, requested_backend
        return _FakeBackend("transformers", stream_tokens=["A", "B", "C"])

    monkeypatch.setattr(worker_module, "create_backend", _fake_create_backend)
    worker = LLMWorker()
    worker._model_path = "distilgpt2"
    worker._requested_backend = "auto"
    worker._load_params = {"n_ctx": 1024}
    worker._do_load()

    streamed: list[str] = []
    completed: list[str] = []
    worker.token_received.connect(streamed.append)
    worker.generation_complete.connect(completed.append)

    worker._prompt = "frage"
    worker._gen_params = {
        "max_tokens": 32,
        "temperature": 0.2,
        "top_p": 0.9,
        "repeat_penalty": 1.0,
        "stop": ["<|"],
    }
    worker._forbidden_chars = ()
    worker._stop = False
    worker._do_generate()

    assert streamed == ["A", "B", "C"]
    assert completed == ["ABC"]


def test_worker_requests_backend_stop_after_detected_stop_marker(monkeypatch):
    class _StopAwareBackend(_FakeBackend):
        def __init__(self):
            super().__init__("transformers", stream_tokens=["Hi", "<|", "ignored", "tail"])
            self.stop_checks: list[bool] = []

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
            stop_requested: Callable[[], bool] | None = None,
        ):
            _ = (
                prompt,
                max_tokens,
                temperature,
                top_p,
                repeat_penalty,
                stop,
                forbidden_chars,
            )
            should_stop = stop_requested or (lambda: False)
            for token in self._stream_tokens:
                current = bool(should_stop())
                self.stop_checks.append(current)
                if current:
                    break
                yield token
            self.stop_checks.append(bool(should_stop()))

    created: list[_StopAwareBackend] = []

    def _fake_create_backend(model_ref: str, requested_backend: str | None = None):
        _ = model_ref, requested_backend
        backend = _StopAwareBackend()
        created.append(backend)
        return backend

    monkeypatch.setattr(worker_module, "create_backend", _fake_create_backend)
    worker = LLMWorker()
    worker._model_path = "distilgpt2"
    worker._requested_backend = "auto"
    worker._load_params = {"n_ctx": 1024}
    worker._do_load()

    streamed: list[str] = []
    completed: list[str] = []
    worker.token_received.connect(streamed.append)
    worker.generation_complete.connect(completed.append)

    worker._prompt = "frage"
    worker._gen_params = {
        "max_tokens": 32,
        "temperature": 0.2,
        "top_p": 0.9,
        "repeat_penalty": 1.0,
        "stop": ["<|"],
    }
    worker._forbidden_chars = ()
    worker._stop = False
    worker._do_generate()

    backend = created[-1]
    assert completed == ["Hi"]
    assert "".join(streamed) == "Hi"
    assert any(backend.stop_checks)
