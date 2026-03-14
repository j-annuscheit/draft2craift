from __future__ import annotations

import unittest
from unittest import mock

import shared.services.llm.worker as worker_module
from shared.services.llm.worker import LLMWorker


class _FakeBackend:
    def __init__(
        self,
        *,
        backend_id: str = "llama_cpp",
        load_success: bool = True,
        unload_raises: bool = False,
    ):
        self.backend_id = backend_id
        self.load_success = bool(load_success)
        self.unload_raises = bool(unload_raises)
        self.load_calls = 0
        self.unload_calls = 0
        self.loaded = False

    def load_model(self, model_ref: str, **kwargs):  # noqa: ANN003
        _ = model_ref, kwargs
        self.load_calls += 1
        self.loaded = self.load_success
        if self.load_success:
            return True, "ok"
        return False, "load failed"

    def unload_model(self) -> None:
        self.unload_calls += 1
        self.loaded = False
        if self.unload_raises:
            raise RuntimeError("close failed")

    def is_loaded(self) -> bool:
        return bool(self.loaded)

    def context_window(self, default_n_ctx: int = 4096) -> int:
        return int(default_n_ctx)

    def count_tokens(self, text: str) -> int:
        return max(1, len(str(text or "").split()))

    def generate_once(self, prompt: str, **kwargs):  # noqa: ANN003
        _ = prompt, kwargs
        return ""

    def generate_stream(self, prompt: str, **kwargs):  # noqa: ANN003
        _ = prompt, kwargs
        if False:  # pragma: no cover
            yield ""


class ModelReloadReleaseTests(unittest.TestCase):
    def test_release_loaded_model_unloads_backend_and_clears_reference(self):
        worker = LLMWorker()
        backend = _FakeBackend(backend_id="transformers")
        worker._backend = backend
        worker._backend_id = "transformers"

        worker._release_loaded_model()

        self.assertEqual(backend.unload_calls, 1)
        self.assertIsNone(worker._backend)
        self.assertEqual(worker._backend_id, "")

    def test_release_loaded_model_ignores_unload_errors(self):
        worker = LLMWorker()
        backend = _FakeBackend(unload_raises=True)
        worker._backend = backend
        worker._backend_id = "llama_cpp"

        worker._release_loaded_model()

        self.assertEqual(backend.unload_calls, 1)
        self.assertIsNone(worker._backend)
        self.assertEqual(worker._backend_id, "")

    def test_do_load_releases_previous_backend_before_loading_new_one(self):
        worker = LLMWorker()
        old_backend = _FakeBackend(backend_id="transformers")
        old_backend.loaded = True
        worker._backend = old_backend
        worker._backend_id = "transformers"
        worker._model_path = "new.gguf"
        worker._requested_backend = "auto"
        worker._load_params = {"n_ctx": 2048, "n_threads": 2}
        new_backend = _FakeBackend(backend_id="llama_cpp")

        with mock.patch.object(worker_module, "create_backend", return_value=new_backend):
            worker._do_load()

        self.assertEqual(old_backend.unload_calls, 1)
        self.assertIs(worker._backend, new_backend)
        self.assertEqual(worker.backend_name(), "llama_cpp")
        self.assertEqual(new_backend.load_calls, 1)


if __name__ == "__main__":
    unittest.main()
