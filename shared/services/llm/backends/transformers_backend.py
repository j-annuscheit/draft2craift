"""Transformers backend wrapper implementing :class:`BaseLLMBackend`."""
from __future__ import annotations

import gc
import os
from pathlib import PurePosixPath
import re
import threading
from typing import Any
from urllib.parse import urlparse

from .base import BaseLLMBackend

_HF_HOSTS = {"huggingface.co", "www.huggingface.co"}
_HUGE_MODEL_MAX_LENGTH = 10**8
_ROLE_TAG_RE = re.compile(r"<\|([a-zA-Z_]+)\|>")
_CHAT_ROLES = {"system", "user", "assistant"}


def normalize_transformers_model_ref(model_ref: str) -> str:
    """Normalize Hugging Face model refs from ids or URLs."""
    text = str(model_ref or "").strip()
    if not text:
        raise ValueError("Model reference is empty.")
    if not re.match(r"^https?://", text, flags=re.IGNORECASE):
        return text

    parsed = urlparse(text)
    if parsed.netloc.casefold() not in _HF_HOSTS:
        return text

    raw_path = str(parsed.path or "").strip("/")
    if not raw_path:
        raise ValueError(f"Could not resolve Hugging Face model id from URL: {text}")

    parts = [part for part in PurePosixPath(raw_path).parts if str(part).strip()]
    if parts and parts[0] == "models":
        parts = parts[1:]
    if len(parts) == 1:
        return parts[0]
    if len(parts) < 2:
        raise ValueError(f"Could not resolve Hugging Face model id from URL: {text}")
    return f"{parts[0]}/{parts[1]}"


class TransformersBackend(BaseLLMBackend):
    """Inference backend for Hugging Face ``transformers`` causal language models."""

    def __init__(self) -> None:
        self._model: Any = None
        self._tokenizer: Any = None
        self._torch: Any = None
        self._transformers: Any = None
        self._model_ref: str = ""
        self._device: str = "cpu"
        self._context_window: int = 4096

    @property
    def backend_id(self) -> str:
        return "transformers"

    @property
    def model_ref(self) -> str:
        return str(self._model_ref or "")

    def load_model(
        self,
        model_ref: str,
        *,
        n_ctx: int = 4096,
        n_gpu_layers: int = 0,
        n_threads: int = 0,
        embedding: bool = False,
        flash_attn: bool = True,
    ) -> tuple[bool, str]:
        _ = n_gpu_layers, embedding, flash_attn
        self.unload_model()

        try:
            import torch  # type: ignore
            from transformers import AutoModelForCausalLM, AutoTokenizer  # type: ignore
        except ImportError:
            return (
                False,
                "transformers/torch not installed.\nRun: pip install transformers torch",
            )

        try:
            resolved_ref = normalize_transformers_model_ref(str(model_ref or ""))
            if not resolved_ref:
                raise ValueError("Model reference is empty.")

            threads = int(n_threads or (os.cpu_count() or 4))
            if threads > 0:
                try:
                    torch.set_num_threads(threads)
                except Exception:
                    pass

            device = "cpu"
            dtype: Any = None
            if bool(getattr(torch.cuda, "is_available", lambda: False)()):
                device = "cuda"
                dtype = getattr(torch, "float16", None)
            elif bool(getattr(getattr(torch.backends, "mps", None), "is_available", lambda: False)()):
                device = "mps"
                dtype = getattr(torch, "float16", None)

            tokenizer = AutoTokenizer.from_pretrained(resolved_ref, use_fast=True)
            if tokenizer.pad_token_id is None and tokenizer.eos_token_id is not None:
                tokenizer.pad_token = tokenizer.eos_token

            model_kwargs: dict[str, Any] = {}
            if dtype is not None:
                model_kwargs["torch_dtype"] = dtype
            model = AutoModelForCausalLM.from_pretrained(resolved_ref, **model_kwargs)
            model.to(device)
            model.eval()

            self._model = model
            self._tokenizer = tokenizer
            self._torch = torch
            self._transformers = __import__("transformers")
            self._model_ref = resolved_ref
            self._device = device
            self._context_window = self._infer_context_window(default_n_ctx=int(n_ctx))

            return True, f"✓ {resolved_ref} [transformers/{device}]"
        except Exception as exc:
            self.unload_model()
            return False, f"Load failed: {exc}"

    def unload_model(self) -> None:
        model = self._model
        self._model = None
        self._tokenizer = None
        torch_mod = self._torch
        self._torch = None
        self._transformers = None
        self._model_ref = ""
        self._device = "cpu"
        self._context_window = 4096

        if model is not None:
            try:
                to_fn = getattr(model, "to", None)
                if callable(to_fn):
                    to_fn("cpu")
            except Exception:
                pass
            del model

        if torch_mod is not None:
            try:
                if bool(getattr(torch_mod.cuda, "is_available", lambda: False)()):
                    torch_mod.cuda.empty_cache()
            except Exception:
                pass
        gc.collect()

    def is_loaded(self) -> bool:
        return self._model is not None and self._tokenizer is not None

    def context_window(self, default_n_ctx: int = 4096) -> int:
        try:
            current = int(self._context_window)
            if current > 0:
                return current
        except Exception:
            pass
        return int(default_n_ctx)

    def count_tokens(self, text: str) -> int:
        prompt_text = self.prepare_prompt(text)
        tokenizer = self._tokenizer
        if tokenizer is None:
            return max(1, len(str(prompt_text or "")) // 4)
        try:
            encoded = tokenizer(
                str(prompt_text or ""),
                add_special_tokens=False,
                return_attention_mask=False,
                return_token_type_ids=False,
            )
            token_ids = encoded.get("input_ids", []) if isinstance(encoded, dict) else []
            return max(1, len(token_ids))
        except Exception:
            return max(1, len(str(prompt_text or "")) // 4)

    def prepare_prompt(self, prompt: str) -> str:
        text = str(prompt or "")
        tokenizer = self._tokenizer
        if tokenizer is None:
            return text

        apply_template = getattr(tokenizer, "apply_chat_template", None)
        if not callable(apply_template):
            return text

        messages = _parse_role_tagged_prompt(text)
        if not messages:
            return text

        try:
            rendered = apply_template(
                messages,
                tokenize=False,
                add_generation_prompt=True,
            )
            return str(rendered or text)
        except TypeError:
            try:
                rendered = apply_template(messages, tokenize=False)
                return str(rendered or text)
            except Exception:
                return text
        except Exception:
            return text

    def generate_once(
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
        _ = forbidden_chars
        self._ensure_loaded()
        torch_mod = self._torch
        tokenizer = self._tokenizer
        model = self._model
        prepared_prompt = self.prepare_prompt(prompt)
        inputs = tokenizer(prepared_prompt, return_tensors="pt")
        inputs = {k: v.to(self._device) for k, v in inputs.items()}
        gen_kwargs = self._build_generation_kwargs(
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            repeat_penalty=repeat_penalty,
        )
        with torch_mod.no_grad():
            output_ids = model.generate(**inputs, **gen_kwargs)
        prompt_len = int(inputs["input_ids"].shape[-1])
        new_ids = output_ids[0][prompt_len:]
        text = str(
            tokenizer.decode(
                new_ids,
                skip_special_tokens=False,
            )
            or ""
        )
        return self._apply_stop_strings(text, stop or ["<|"])

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
        stop_requested=None,
    ):
        _ = stop, forbidden_chars
        self._ensure_loaded()
        torch_mod = self._torch
        transformers_mod = self._transformers
        tokenizer = self._tokenizer
        model = self._model
        should_stop = stop_requested or (lambda: False)

        prepared_prompt = self.prepare_prompt(prompt)
        inputs = tokenizer(prepared_prompt, return_tensors="pt")
        inputs = {k: v.to(self._device) for k, v in inputs.items()}
        streamer = transformers_mod.TextIteratorStreamer(
            tokenizer,
            skip_prompt=True,
            skip_special_tokens=False,
        )
        criteria_cls = _build_stop_requested_criteria(transformers_mod, should_stop)
        stopping = transformers_mod.StoppingCriteriaList([criteria_cls()])
        gen_kwargs = self._build_generation_kwargs(
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            repeat_penalty=repeat_penalty,
        )

        error_holder: dict[str, Exception] = {}

        def _run_generate() -> None:
            try:
                with torch_mod.no_grad():
                    model.generate(
                        **inputs,
                        **gen_kwargs,
                        streamer=streamer,
                        stopping_criteria=stopping,
                    )
            except Exception as exc:
                error_holder["error"] = exc

        thread = threading.Thread(target=_run_generate, daemon=True)
        thread.start()
        for piece in streamer:
            if should_stop():
                break
            token = str(piece or "")
            if token:
                yield token
        thread.join(timeout=2.0)
        if "error" in error_holder:
            raise error_holder["error"]

    def _ensure_loaded(self) -> None:
        if self._model is None or self._tokenizer is None or self._torch is None:
            raise RuntimeError("No model loaded.")

    def _infer_context_window(self, default_n_ctx: int) -> int:
        candidates: list[int] = []
        model = self._model
        tokenizer = self._tokenizer

        config = getattr(model, "config", None)
        for key in (
            "max_position_embeddings",
            "n_positions",
            "max_sequence_length",
            "max_seq_len",
            "seq_length",
        ):
            value = getattr(config, key, None)
            try:
                parsed = int(value)
            except Exception:
                continue
            if parsed > 0:
                candidates.append(parsed)

        try:
            tok_max = int(getattr(tokenizer, "model_max_length", 0) or 0)
            if 0 < tok_max < _HUGE_MODEL_MAX_LENGTH:
                candidates.append(tok_max)
        except Exception:
            pass

        if candidates:
            return max(candidates)
        return max(256, int(default_n_ctx or 4096))

    @staticmethod
    def _apply_stop_strings(text: str, stop: list[str]) -> str:
        output = str(text or "")
        for marker in stop:
            token = str(marker or "")
            if not token:
                continue
            idx = output.find(token)
            if idx >= 0:
                output = output[:idx]
        return output

    @staticmethod
    def _build_generation_kwargs(
        *,
        max_tokens: int,
        temperature: float,
        top_p: float,
        repeat_penalty: float,
    ) -> dict[str, Any]:
        do_sample = float(temperature) > 1e-5
        kwargs: dict[str, Any] = {
            "max_new_tokens": max(1, int(max_tokens)),
            "repetition_penalty": max(1.0, float(repeat_penalty)),
            "do_sample": do_sample,
        }
        if do_sample:
            kwargs["temperature"] = max(1e-5, float(temperature))
            kwargs["top_p"] = max(0.01, min(1.0, float(top_p)))
        return kwargs


def _build_stop_requested_criteria(transformers_mod: Any, stop_requested):
    """Create a ``StoppingCriteria`` class bound to ``stop_requested`` callback."""

    base_cls = getattr(transformers_mod, "StoppingCriteria", object)

    class _StopRequestedCriteria(base_cls):  # type: ignore[misc, valid-type]
        def __call__(self, input_ids, scores, **kwargs):  # noqa: ANN001, ANN201
            _ = input_ids, scores, kwargs
            try:
                return bool(stop_requested())
            except Exception:
                return False

    return _StopRequestedCriteria


def _parse_role_tagged_prompt(prompt: str) -> list[dict[str, str]]:
    text = str(prompt or "")
    matches = list(_ROLE_TAG_RE.finditer(text))
    if not matches:
        return []

    messages: list[dict[str, str]] = []
    last_idx = len(matches) - 1
    for idx, match in enumerate(matches):
        role = str(match.group(1) or "").strip().casefold()
        if role not in _CHAT_ROLES:
            continue
        start = int(match.end())
        end = int(matches[idx + 1].start()) if idx < last_idx else len(text)
        content = str(text[start:end] or "")
        if content.startswith("\n"):
            content = content[1:]
        content = content.rstrip()
        if role == "assistant" and idx == last_idx and not content:
            # Trailing assistant tag already denotes generation prompt.
            continue
        if not content and role != "assistant":
            continue
        messages.append({"role": role, "content": content})
    return messages
