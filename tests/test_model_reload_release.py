from __future__ import annotations

import sys
import types
import unittest
from unittest import mock

from services.llm.manager import LLMWorker


class _ClosableModel:
    def __init__(self):
        self.close_calls = 0

    def close(self):
        self.close_calls += 1


class _NonClosableModel:
    pass


class _FakeLlama:
    def __init__(self, *, model_path: str, **_kwargs):
        self.model_path = model_path


class ModelReloadReleaseTests(unittest.TestCase):
    def test_release_loaded_model_closes_and_clears_reference(self):
        worker = LLMWorker()
        old_model = _ClosableModel()
        worker._model = old_model
        worker._forbidden_bias_cache_model = ("old.gguf", 1)
        worker._forbidden_bias_cache = {("x",): {1: -100.0}}

        worker._release_loaded_model()

        self.assertEqual(old_model.close_calls, 1)
        self.assertIsNone(worker._model)
        self.assertIsNone(worker._forbidden_bias_cache_model)
        self.assertEqual(worker._forbidden_bias_cache, {})

    def test_release_loaded_model_handles_models_without_close(self):
        worker = LLMWorker()
        worker._model = _NonClosableModel()

        worker._release_loaded_model()

        self.assertIsNone(worker._model)
        self.assertIsNone(worker._forbidden_bias_cache_model)
        self.assertEqual(worker._forbidden_bias_cache, {})

    def test_do_load_releases_previous_model_before_loading_new_one(self):
        worker = LLMWorker()
        old_model = _ClosableModel()
        worker._model = old_model
        worker._model_path = "new.gguf"
        worker._load_params = {"n_ctx": 2048, "n_threads": 2}

        fake_module = types.SimpleNamespace(Llama=_FakeLlama)
        with mock.patch.dict(sys.modules, {"llama_cpp": fake_module}):
            worker._do_load()

        self.assertEqual(old_model.close_calls, 1)
        self.assertIsInstance(worker._model, _FakeLlama)
        self.assertEqual(worker._model.model_path, "new.gguf")


if __name__ == "__main__":
    unittest.main()
