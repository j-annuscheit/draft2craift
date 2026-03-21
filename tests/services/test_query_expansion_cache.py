from __future__ import annotations

import unittest
from unittest.mock import Mock

from shared.services.llm.manager import LLMManager


class _DummyModel:
    def __init__(self, outputs: list[str]):
        self._outputs = list(outputs)
        self.calls: list[dict[str, object]] = []

    def complete(self, prompt: str, **kwargs) -> str:
        self.calls.append(
            {
                "prompt": str(prompt or ""),
                "kwargs": dict(kwargs or {}),
            }
        )
        return self._outputs.pop(0) if self._outputs else ""


class QueryExpansionCacheTests(unittest.TestCase):
    def _build_manager(self, *, outputs: list[str]) -> tuple[LLMManager, _DummyModel]:
        manager = LLMManager()
        model = _DummyModel(outputs)
        manager.worker.is_model_loaded = Mock(return_value=True)
        manager.worker.isRunning = Mock(return_value=False)
        manager._generate_backend_text = Mock(
            side_effect=lambda prompt, **kwargs: model.complete(prompt, **kwargs)
        )
        return manager, model

    def test_tfidf_expansion_reuses_cached_value(self):
        manager, model = self._build_manager(outputs=["alpha, beta"])

        out1 = manager.expand_query_tfidf_sync("frage")
        out2 = manager.expand_query_tfidf_sync("frage")

        self.assertEqual(out1, "alpha, beta")
        self.assertEqual(out2, "alpha, beta")
        self.assertEqual(len(model.calls), 1)

    def test_tfidf_cache_is_cleared_after_prompt_update(self):
        manager, model = self._build_manager(outputs=["x", "y"])

        self.assertEqual(manager.expand_query_tfidf_sync("frage"), "x")
        manager.set_prompt_set({})
        self.assertEqual(manager.expand_query_tfidf_sync("frage"), "y")
        self.assertEqual(len(model.calls), 2)

    def test_st_expansion_cache_key_includes_hypothesis_count(self):
        manager, model = self._build_manager(outputs=["eins---zwei", "einzeln"])

        self.assertEqual(
            manager.expand_query_st_sync("frage", n_hypotheses=2),
            ["eins", "zwei"],
        )
        self.assertEqual(
            manager.expand_query_st_sync("frage", n_hypotheses=2),
            ["eins", "zwei"],
        )
        self.assertEqual(
            manager.expand_query_st_sync("frage", n_hypotheses=1),
            ["einzeln"],
        )
        self.assertEqual(len(model.calls), 2)

    def test_literal_expansion_reuses_cache_for_same_limit(self):
        manager, model = self._build_manager(
            outputs=[
                "```regex\nalpha\\s+beta\nbeta(?:-)?gamma\n```",
                "gamma\\d+\ndelta",
            ]
        )

        terms1, meta1 = manager.expand_query_literal_terms_sync("frage", max_terms=2)
        terms2, meta2 = manager.expand_query_literal_terms_sync("frage", max_terms=2)
        terms3, _meta3 = manager.expand_query_literal_terms_sync("frage", max_terms=1)

        self.assertEqual(terms1, [r"alpha\s+beta", r"beta(?:-)?gamma"])
        self.assertEqual(terms2, [r"alpha\s+beta", r"beta(?:-)?gamma"])
        self.assertEqual(terms3, [r"gamma\d+"])
        self.assertEqual(meta1["applied"], True)
        self.assertEqual(meta2["applied"], True)
        self.assertEqual(len(model.calls), 2)


if __name__ == "__main__":
    unittest.main()
