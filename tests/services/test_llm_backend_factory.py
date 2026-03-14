from __future__ import annotations

from unittest.mock import Mock

from shared.services.llm.backends.factory import (
    BACKEND_AUTO,
    BACKEND_LLAMA_CPP,
    BACKEND_TRANSFORMERS,
    infer_backend_choice,
)
from shared.services.llm.backends.transformers_backend import (
    normalize_transformers_model_ref,
)
from shared.services.llm.manager import LLMManager


def test_infer_backend_choice_auto_prefers_llama_for_gguf():
    assert infer_backend_choice("/models/demo.gguf", BACKEND_AUTO) == BACKEND_LLAMA_CPP
    assert infer_backend_choice("/models/demo.bin", BACKEND_AUTO) == BACKEND_LLAMA_CPP


def test_infer_backend_choice_auto_prefers_transformers_for_hf_id():
    assert infer_backend_choice("distilgpt2", BACKEND_AUTO) == BACKEND_TRANSFORMERS
    assert (
        infer_backend_choice("https://huggingface.co/gpt2", BACKEND_AUTO)
        == BACKEND_TRANSFORMERS
    )


def test_infer_backend_choice_honors_explicit_selection():
    assert (
        infer_backend_choice("/models/demo.gguf", BACKEND_TRANSFORMERS)
        == BACKEND_TRANSFORMERS
    )
    assert infer_backend_choice("gpt2", BACKEND_LLAMA_CPP) == BACKEND_LLAMA_CPP


def test_normalize_transformers_model_ref_accepts_hf_urls():
    assert normalize_transformers_model_ref("https://huggingface.co/gpt2") == "gpt2"
    assert (
        normalize_transformers_model_ref("https://huggingface.co/openai-community/gpt2")
        == "openai-community/gpt2"
    )
    assert (
        normalize_transformers_model_ref(
            "https://huggingface.co/openai-community/gpt2/tree/main"
        )
        == "openai-community/gpt2"
    )


def test_llm_manager_forwards_backend_choice_to_worker():
    manager = LLMManager()
    manager.worker.load_model = Mock()

    manager.load_model("distilgpt2", backend=BACKEND_TRANSFORMERS, n_threads=2)

    manager.worker.load_model.assert_called_once()
    kwargs = manager.worker.load_model.call_args.kwargs
    assert kwargs["backend"] == BACKEND_TRANSFORMERS
    assert kwargs["n_threads"] == 2
