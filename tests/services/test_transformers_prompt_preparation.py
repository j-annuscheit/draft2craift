from __future__ import annotations

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
