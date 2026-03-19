from __future__ import annotations

import queue
import types
import sys

import pytest
import torch

import shared.services.llm.backends.transformers_backend as transformers_backend_module
from shared.services.llm.backends.transformers_backend import TransformersBackend


class _FakeTokenizer:
    def __init__(self) -> None:
        self.apply_calls: list[dict[str, object]] = []
        self.last_tokenize_prompt: str = ""
        self.last_decode_ids: list[int] = []

    def apply_chat_template(
        self,
        messages,
        *,
        tokenize: bool,
        add_generation_prompt: bool = False,
    ):
        self.apply_calls.append(
            {
                "messages": list(messages),
                "tokenize": bool(tokenize),
                "add_generation_prompt": bool(add_generation_prompt),
            }
        )
        return "<templated>"

    def __call__(self, text: str, **kwargs):
        _ = kwargs
        self.last_tokenize_prompt = str(text or "")
        return {"input_ids": [1, 2, 3, 4]}

    def decode(self, token_ids, **kwargs):  # noqa: ANN001, ANN003
        _ = kwargs
        self.last_decode_ids = list(token_ids or [])
        return "decoded-output"


class _FakeTensor:
    def __init__(self, token_ids: list[int]):
        self._token_ids = list(token_ids)
        self.shape = (1, len(self._token_ids))

    def to(self, _device: str):
        return self


class _FakeGenTokenizer(_FakeTokenizer):
    def __call__(self, text: str, **kwargs):
        _ = kwargs
        self.last_tokenize_prompt = str(text or "")
        return {"input_ids": _FakeTensor([11, 22])}


class _FakeNoGrad:
    def __enter__(self):
        return None

    def __exit__(self, exc_type, exc, tb):
        _ = exc_type, exc, tb
        return False


class _FakeTorch:
    def no_grad(self):
        return _FakeNoGrad()


class _FakeModel:
    def generate(self, **kwargs):  # noqa: ANN003
        _ = kwargs
        return [[11, 22, 99]]


def test_prepare_prompt_uses_chat_template_for_role_tagged_prompt():
    backend = TransformersBackend()
    tok = _FakeTokenizer()
    backend._tokenizer = tok

    prompt = (
        "<|system|>\nSystemregel\n"
        "<|user|>\nFrage 1\n"
        "<|assistant|>\nAntwort 1\n"
        "<|user|>\nFrage 2\n"
        "<|assistant|>\n"
    )
    prepared = backend.prepare_prompt(prompt)

    assert prepared == "<templated>"
    assert len(tok.apply_calls) == 1
    call = tok.apply_calls[0]
    assert call["tokenize"] is False
    assert call["add_generation_prompt"] is True
    messages = call["messages"]
    assert [entry["role"] for entry in messages] == [
        "system",
        "user",
        "assistant",
        "user",
    ]


def test_count_tokens_uses_prepared_prompt():
    backend = TransformersBackend()
    tok = _FakeTokenizer()
    backend._tokenizer = tok

    count = backend.count_tokens("<|system|>\nS\n<|user|>\nU\n<|assistant|>\n")

    assert count == 4
    assert tok.last_tokenize_prompt == "<templated>"


def test_count_tokens_handles_nested_input_ids():
    backend = TransformersBackend()

    class _NestedTokenizer(_FakeTokenizer):
        def __call__(self, text: str, **kwargs):
            _ = text, kwargs
            return {"input_ids": [[11, 22, 33, 44, 55]]}

    backend._tokenizer = _NestedTokenizer()
    count = backend.count_tokens("<|system|>\nS\n<|user|>\nU\n<|assistant|>\n")
    assert count == 5


def test_generate_once_uses_prepared_prompt_before_tokenization():
    backend = TransformersBackend()
    tok = _FakeGenTokenizer()
    backend._tokenizer = tok
    backend._model = _FakeModel()
    backend._torch = _FakeTorch()
    backend._device = "cpu"

    text = backend.generate_once(
        "<|system|>\nS\n<|user|>\nU\n<|assistant|>\n",
        max_tokens=16,
        temperature=0.0,
        top_p=1.0,
        repeat_penalty=1.0,
        stop=["<|"],
    )

    assert tok.last_tokenize_prompt == "<templated>"
    assert tok.last_decode_ids == [99]
    assert text == "decoded-output"


def test_load_model_forwards_trust_remote_code(monkeypatch):
    backend = TransformersBackend()
    calls: dict[str, object] = {}

    class _FakeTorchCuda:
        @staticmethod
        def is_available() -> bool:
            return False

    class _FakeTorchMps:
        @staticmethod
        def is_available() -> bool:
            return False

    class _FakeTorchBackends:
        mps = _FakeTorchMps()

    fake_torch = types.ModuleType("torch")
    fake_torch.cuda = _FakeTorchCuda()
    fake_torch.backends = _FakeTorchBackends()

    def _set_num_threads(value: int) -> None:
        calls["threads"] = int(value)

    fake_torch.set_num_threads = _set_num_threads

    class _LoadedTokenizer:
        pad_token_id = None
        eos_token_id = 2
        eos_token = "</s>"
        pad_token = None
        model_max_length = 2048

    class _LoadedConfig:
        max_position_embeddings = 2048

    class _LoadedModel:
        config = _LoadedConfig()

        def to(self, _device: str):
            return self

        def eval(self) -> None:
            return None

    class _FakeAutoTokenizer:
        @staticmethod
        def from_pretrained(model_ref: str, **kwargs):
            calls["tokenizer"] = (str(model_ref), dict(kwargs))
            return _LoadedTokenizer()

    class _FakeAutoModelForCausalLM:
        @staticmethod
        def from_pretrained(model_ref: str, **kwargs):
            calls["model"] = (str(model_ref), dict(kwargs))
            return _LoadedModel()

    fake_transformers = types.ModuleType("transformers")
    fake_transformers.AutoTokenizer = _FakeAutoTokenizer
    fake_transformers.AutoModelForCausalLM = _FakeAutoModelForCausalLM
    fake_import_utils = types.ModuleType("transformers.utils.import_utils")
    fake_import_utils.is_mamba_2_ssm_available = lambda: True  # noqa: E731
    fake_import_utils.is_causal_conv1d_available = lambda: True  # noqa: E731
    fake_utils = types.ModuleType("transformers.utils")
    fake_utils.import_utils = fake_import_utils

    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(sys.modules, "transformers", fake_transformers)
    monkeypatch.setitem(sys.modules, "transformers.utils", fake_utils)
    monkeypatch.setitem(sys.modules, "transformers.utils.import_utils", fake_import_utils)

    success, _message = backend.load_model(
        "some-org/some-model",
        trust_remote_code=True,
    )

    assert success is True
    tokenizer_call = calls.get("tokenizer")
    model_call = calls.get("model")
    assert isinstance(tokenizer_call, tuple)
    assert isinstance(model_call, tuple)
    assert tokenizer_call[1].get("trust_remote_code") is True
    assert model_call[1].get("trust_remote_code") is True


def test_load_model_enables_nemotron_safe_mode(monkeypatch):
    backend = TransformersBackend()
    calls: dict[str, object] = {}

    class _FakeTorchCuda:
        @staticmethod
        def is_available() -> bool:
            return False

    class _FakeTorchMps:
        @staticmethod
        def is_available() -> bool:
            return False

    class _FakeTorchBackends:
        mps = _FakeTorchMps()

    fake_torch = types.ModuleType("torch")
    fake_torch.cuda = _FakeTorchCuda()
    fake_torch.backends = _FakeTorchBackends()
    fake_torch.set_num_threads = lambda _value: None  # noqa: E731

    class _LoadedTokenizer:
        pad_token_id = 0
        eos_token_id = 2
        eos_token = "</s>"
        pad_token = "</s>"
        model_max_length = 2048

    class _LoadedConfig:
        max_position_embeddings = 2048

    class _LoadedModel:
        config = _LoadedConfig()

        def to(self, _device: str):
            return self

        def eval(self) -> None:
            return None

    class _FakeAutoTokenizer:
        @staticmethod
        def from_pretrained(model_ref: str, **kwargs):
            calls["tokenizer"] = (str(model_ref), dict(kwargs))
            return _LoadedTokenizer()

    class _FakeAutoModelForCausalLM:
        @staticmethod
        def from_pretrained(model_ref: str, **kwargs):
            calls["model"] = (str(model_ref), dict(kwargs))
            return _LoadedModel()

    fake_transformers = types.ModuleType("transformers")
    fake_transformers.AutoTokenizer = _FakeAutoTokenizer
    fake_transformers.AutoModelForCausalLM = _FakeAutoModelForCausalLM
    fake_import_utils = types.ModuleType("transformers.utils.import_utils")
    fake_import_utils.is_mamba_2_ssm_available = lambda: True  # noqa: E731
    fake_import_utils.is_causal_conv1d_available = lambda: True  # noqa: E731
    fake_utils = types.ModuleType("transformers.utils")
    fake_utils.import_utils = fake_import_utils

    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(sys.modules, "transformers", fake_transformers)
    monkeypatch.setitem(sys.modules, "transformers.utils", fake_utils)
    monkeypatch.setitem(sys.modules, "transformers.utils.import_utils", fake_import_utils)

    success, message = backend.load_model(
        "nvidia/NVIDIA-Nemotron-3-Nano-4B",
        trust_remote_code=True,
    )

    assert success is True
    model_call = calls.get("model")
    assert isinstance(model_call, tuple)
    assert model_call[1].get("trust_remote_code") is True
    assert model_call[1].get("attn_implementation") == "eager"
    assert "safe mode" in message


def test_load_model_keeps_fp8_nemotron_on_fast_path_by_default(monkeypatch):
    backend = TransformersBackend()
    calls: dict[str, object] = {}

    class _FakeTorchCuda:
        @staticmethod
        def is_available() -> bool:
            return False

    class _FakeTorchMps:
        @staticmethod
        def is_available() -> bool:
            return False

    class _FakeTorchBackends:
        mps = _FakeTorchMps()

    fake_torch = types.ModuleType("torch")
    fake_torch.cuda = _FakeTorchCuda()
    fake_torch.backends = _FakeTorchBackends()
    fake_torch.set_num_threads = lambda _value: None  # noqa: E731

    class _LoadedTokenizer:
        pad_token_id = 0
        eos_token_id = 2
        eos_token = "</s>"
        pad_token = "</s>"
        model_max_length = 2048

    class _LoadedConfig:
        max_position_embeddings = 2048

    class _LoadedModel:
        config = _LoadedConfig()

        def to(self, _device: str):
            return self

        def eval(self) -> None:
            return None

    class _FakeAutoTokenizer:
        @staticmethod
        def from_pretrained(model_ref: str, **kwargs):
            calls["tokenizer"] = (str(model_ref), dict(kwargs))
            return _LoadedTokenizer()

    class _FakeAutoModelForCausalLM:
        @staticmethod
        def from_pretrained(model_ref: str, **kwargs):
            calls["model"] = (str(model_ref), dict(kwargs))
            return _LoadedModel()

    fake_transformers = types.ModuleType("transformers")
    fake_transformers.AutoTokenizer = _FakeAutoTokenizer
    fake_transformers.AutoModelForCausalLM = _FakeAutoModelForCausalLM
    fake_import_utils = types.ModuleType("transformers.utils.import_utils")
    fake_import_utils.is_mamba_2_ssm_available = lambda: True  # noqa: E731
    fake_import_utils.is_causal_conv1d_available = lambda: True  # noqa: E731
    fake_utils = types.ModuleType("transformers.utils")
    fake_utils.import_utils = fake_import_utils

    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(sys.modules, "transformers", fake_transformers)
    monkeypatch.setitem(sys.modules, "transformers.utils", fake_utils)
    monkeypatch.setitem(sys.modules, "transformers.utils.import_utils", fake_import_utils)

    success, message = backend.load_model(
        "nvidia/NVIDIA-Nemotron-3-Nano-4B-FP8",
        trust_remote_code=True,
    )

    assert success is True
    model_call = calls.get("model")
    assert isinstance(model_call, tuple)
    assert model_call[1].get("trust_remote_code") is True
    assert "attn_implementation" not in model_call[1]
    assert "safe mode" not in message


def test_load_model_fp8_cuda_requires_fast_kernels(monkeypatch):
    backend = TransformersBackend()
    calls: dict[str, object] = {}

    class _FakeTorchCuda:
        @staticmethod
        def is_available() -> bool:
            return True

        @staticmethod
        def is_bf16_supported() -> bool:
            return True

    class _FakeTorchMps:
        @staticmethod
        def is_available() -> bool:
            return False

    class _FakeTorchBackends:
        mps = _FakeTorchMps()

    fake_torch = types.ModuleType("torch")
    fake_torch.cuda = _FakeTorchCuda()
    fake_torch.backends = _FakeTorchBackends()
    fake_torch.float16 = "float16"
    fake_torch.bfloat16 = "bfloat16"
    fake_torch.set_num_threads = lambda _value: None  # noqa: E731

    class _LoadedTokenizer:
        pad_token_id = 0
        eos_token_id = 2
        eos_token = "</s>"
        pad_token = "</s>"
        model_max_length = 2048

    class _FakeAutoTokenizer:
        @staticmethod
        def from_pretrained(model_ref: str, **kwargs):
            calls["tokenizer"] = (str(model_ref), dict(kwargs))
            return _LoadedTokenizer()

    class _FakeAutoModelForCausalLM:
        @staticmethod
        def from_pretrained(model_ref: str, **kwargs):
            calls["model"] = (str(model_ref), dict(kwargs))
            return object()

    fake_transformers = types.ModuleType("transformers")
    fake_transformers.AutoTokenizer = _FakeAutoTokenizer
    fake_transformers.AutoModelForCausalLM = _FakeAutoModelForCausalLM

    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(sys.modules, "transformers", fake_transformers)
    monkeypatch.setattr(
        transformers_backend_module,
        "_nemotron_fast_kernels_importable",
        lambda: (False, "missing symbols"),
    )

    success, message = backend.load_model(
        "nvidia/NVIDIA-Nemotron-3-Nano-4B-FP8",
        trust_remote_code=True,
    )

    assert success is False
    assert "requires CUDA Mamba kernels" in message
    assert "Kernel check failed" in message
    assert "model" not in calls


def test_load_model_fp8_cuda_enables_fast_mode_when_kernels_ready(monkeypatch):
    backend = TransformersBackend()
    calls: dict[str, object] = {}

    class _FakeTorchCuda:
        @staticmethod
        def is_available() -> bool:
            return True

        @staticmethod
        def is_bf16_supported() -> bool:
            return True

    class _FakeTorchMps:
        @staticmethod
        def is_available() -> bool:
            return False

    class _FakeTorchBackends:
        mps = _FakeTorchMps()

    fake_torch = types.ModuleType("torch")
    fake_torch.cuda = _FakeTorchCuda()
    fake_torch.backends = _FakeTorchBackends()
    fake_torch.float16 = "float16"
    fake_torch.bfloat16 = "bfloat16"
    fake_torch.set_num_threads = lambda _value: None  # noqa: E731

    class _LoadedTokenizer:
        pad_token_id = 0
        eos_token_id = 2
        eos_token = "</s>"
        pad_token = "</s>"
        model_max_length = 2048

    class _LoadedConfig:
        max_position_embeddings = 2048

    class _LoadedModel:
        config = _LoadedConfig()

        def to(self, _device: str):
            return self

        def eval(self) -> None:
            return None

    class _FakeAutoTokenizer:
        @staticmethod
        def from_pretrained(model_ref: str, **kwargs):
            calls["tokenizer"] = (str(model_ref), dict(kwargs))
            return _LoadedTokenizer()

    class _FakeAutoModelForCausalLM:
        @staticmethod
        def from_pretrained(model_ref: str, **kwargs):
            calls["model"] = (str(model_ref), dict(kwargs))
            return _LoadedModel()

    fake_transformers = types.ModuleType("transformers")
    fake_transformers.AutoTokenizer = _FakeAutoTokenizer
    fake_transformers.AutoModelForCausalLM = _FakeAutoModelForCausalLM
    fake_import_utils = types.ModuleType("transformers.utils.import_utils")
    fake_import_utils.is_mamba_2_ssm_available = lambda: False  # noqa: E731
    fake_import_utils.is_causal_conv1d_available = lambda: False  # noqa: E731
    fake_utils = types.ModuleType("transformers.utils")
    fake_utils.import_utils = fake_import_utils

    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(sys.modules, "transformers", fake_transformers)
    monkeypatch.setitem(sys.modules, "transformers.utils", fake_utils)
    monkeypatch.setitem(sys.modules, "transformers.utils.import_utils", fake_import_utils)
    monkeypatch.setattr(
        transformers_backend_module,
        "_nemotron_fast_kernels_importable",
        lambda: (True, ""),
    )

    success, message = backend.load_model(
        "nvidia/NVIDIA-Nemotron-3-Nano-4B-FP8",
        trust_remote_code=True,
    )

    assert success is True
    model_call = calls.get("model")
    assert isinstance(model_call, tuple)
    assert model_call[1].get("trust_remote_code") is True
    assert "attn_implementation" not in model_call[1]
    assert model_call[1].get("torch_dtype") == "bfloat16"
    assert "fast mode" in message


class _FakeQueueStreamer:
    def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
        _ = args, kwargs
        self.text_queue: queue.Queue[object] = queue.Queue()
        self.stop_signal = object()


class _FakeStoppingCriteria:
    pass


class _FakeStoppingCriteriaList(list):
    pass


def _make_stream_backend(model_obj: object) -> TransformersBackend:
    backend = TransformersBackend()
    backend._tokenizer = _FakeGenTokenizer()
    backend._model = model_obj
    backend._torch = _FakeTorch()
    backend._device = "cpu"
    backend._transformers = types.SimpleNamespace(
        TextIteratorStreamer=_FakeQueueStreamer,
        StoppingCriteria=_FakeStoppingCriteria,
        StoppingCriteriaList=_FakeStoppingCriteriaList,
    )
    return backend


def test_generate_stream_surfaces_background_error(monkeypatch):
    class _ErrorModel:
        def generate(self, **kwargs):  # noqa: ANN003
            _ = kwargs
            raise RuntimeError("boom")

    monkeypatch.setenv("D2C_STREAM_TIMEOUT_SEC", "0.01")
    backend = _make_stream_backend(_ErrorModel())

    with pytest.raises(RuntimeError, match="boom"):
        list(
            backend.generate_stream(
                "<|system|>\nS\n<|user|>\nU\n<|assistant|>\n",
                max_tokens=8,
                temperature=0.0,
                top_p=1.0,
                repeat_penalty=1.0,
                stop=["<|"],
            )
        )


def test_generate_stream_raises_if_thread_exits_without_stream_signal(monkeypatch):
    class _SilentModel:
        def generate(self, **kwargs):  # noqa: ANN003
            _ = kwargs
            return None

    monkeypatch.setenv("D2C_STREAM_TIMEOUT_SEC", "0.01")
    backend = _make_stream_backend(_SilentModel())

    with pytest.raises(RuntimeError, match="terminated unexpectedly"):
        list(
            backend.generate_stream(
                "<|system|>\nS\n<|user|>\nU\n<|assistant|>\n",
                max_tokens=8,
                temperature=0.0,
                top_p=1.0,
                repeat_penalty=1.0,
                stop=["<|"],
            )
        )


def test_fp8_compat_dequantizes_weights_with_weight_scale(monkeypatch):
    class _MiniModel(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.linear = torch.nn.Linear(4, 1, bias=False)
            self.linear.weight = torch.nn.Parameter(
                torch.tensor(
                    [[1.0, 2.0, 3.0, 4.0]],
                    dtype=torch.float8_e4m3fn,
                ),
                requires_grad=False,
            )

    model = _MiniModel()
    monkeypatch.setattr(
        transformers_backend_module,
        "_load_weight_scale_map",
        lambda _model_ref: {"linear.weight_scale": 0.5},
    )

    converted, scaled = transformers_backend_module._dequantize_fp8_weights_for_compat(
        model,
        model_ref="nvidia/NVIDIA-Nemotron-3-Nano-4B-FP8",
        torch_mod=torch,
        target_dtype=torch.float16,
    )

    assert converted == 1
    assert scaled == 1
    assert model.linear.weight.dtype == torch.float16
    assert torch.allclose(
        model.linear.weight.data.float().reshape(-1),
        torch.tensor([0.5, 1.0, 1.5, 2.0], dtype=torch.float32),
        atol=1e-4,
        rtol=0.0,
    )


def test_evict_dynamic_modules_for_repo_removes_matching_prefix(monkeypatch):
    modules = {
        "transformers_modules.nvidia.NVIDIA_hyphen_Nemotron_hyphen_3_hyphen_Nano_hyphen_4B_hyphen_FP8": object(),
        "transformers_modules.nvidia.NVIDIA_hyphen_Nemotron_hyphen_3_hyphen_Nano_hyphen_4B_hyphen_FP8.a1.modeling_nemotron_h": object(),
        "transformers_modules.other.repo": object(),
    }
    for key, value in modules.items():
        monkeypatch.setitem(sys.modules, key, value)

    removed = transformers_backend_module._evict_dynamic_modules_for_repo(
        "nvidia/NVIDIA-Nemotron-3-Nano-4B-FP8"
    )

    assert removed == 2
    assert "transformers_modules.other.repo" in sys.modules
