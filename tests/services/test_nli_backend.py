from __future__ import annotations

import json
import math
import unittest

from shared.services.llm.manager import LLMManager


class _FakeScalar:
    def __init__(self, value: int):
        self._value = int(value)

    def item(self) -> int:
        return self._value


class _FakeTensor:
    def __init__(self, values: list[float]):
        self.values = list(values)

    def to(self, _device: str):
        return self

    def detach(self):
        return self

    def cpu(self):
        return self

    def tolist(self) -> list[float]:
        return list(self.values)


class _FakeNoGrad:
    def __enter__(self):
        return None

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeTorch:
    def no_grad(self):
        return _FakeNoGrad()

    @staticmethod
    def softmax(tensor: _FakeTensor, dim: int = -1) -> _FakeTensor:
        _ = dim
        raw = list(tensor.values)
        max_val = max(raw) if raw else 0.0
        exps = [math.exp(v - max_val) for v in raw]
        total = sum(exps) or 1.0
        return _FakeTensor([v / total for v in exps])

    @staticmethod
    def argmax(tensor: _FakeTensor) -> _FakeScalar:
        if not tensor.values:
            return _FakeScalar(0)
        best_idx = max(range(len(tensor.values)), key=lambda idx: tensor.values[idx])
        return _FakeScalar(best_idx)


class _FakeTokenizer:
    def __call__(self, premise: str, hypothesis: str, **kwargs):
        _ = premise, hypothesis, kwargs
        return {
            "input_ids": _FakeTensor([101.0, 102.0]),
            "attention_mask": _FakeTensor([1.0, 1.0]),
        }


class _FakeModelOutput:
    def __init__(self, logits: list[float]):
        self.logits = [_FakeTensor(logits)]


class _FakeModel:
    def __init__(self, logits: list[float]):
        self._logits = logits

    def __call__(self, **kwargs):
        _ = kwargs
        return _FakeModelOutput(self._logits)


class NliTransformersBackendTests(unittest.TestCase):
    def test_verify_nli_sync_uses_softmax_confidence_and_mapped_label(self):
        manager = LLMManager()
        manager._nli_backend.model = _FakeModel([0.2, 2.0, -0.1])
        manager._nli_backend.tokenizer = _FakeTokenizer()
        manager._nli_backend.torch_mod = _FakeTorch()
        manager._nli_backend.model_id = "cross-encoder/nli-deberta-v3-xsmall"
        manager._nli_backend.device = "cpu"
        manager._nli_backend.label_lookup = {}

        result = manager.verify_nli_sync(
            "Der Vertrag gilt ab 2025.",
            "Der Vertrag gilt ab 2025.",
        )

        self.assertEqual(result["label"], "entailment")
        self.assertGreater(float(result["score"]), 0.0)
        self.assertLessEqual(float(result["score"]), 1.0)
        self.assertIn("backend=transformers", str(result["reason"]))
        raw = json.loads(str(result["raw"]))
        self.assertEqual(raw.get("mapped_label"), "entailment")
        self.assertIn("probs", raw)
        self.assertEqual(len(raw.get("probs", [])), 3)

    def test_load_nli_model_rejects_gguf_path(self):
        manager = LLMManager()
        manager.load_nli_model("/tmp/nli-model.gguf")
        self.assertFalse(manager.is_nli_model_loaded())
        self.assertIn("Transformers only", manager._nli_backend.last_error)


if __name__ == "__main__":
    unittest.main()
