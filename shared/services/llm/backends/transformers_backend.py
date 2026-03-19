"""Transformers backend wrapper implementing :class:`BaseLLMBackend`."""
from __future__ import annotations

import ctypes
import gc
import os
from pathlib import PurePosixPath
import queue
import re
import sys
import threading
from typing import Any
from urllib.parse import urlparse

from .base import BaseLLMBackend

_HF_HOSTS = {"huggingface.co", "www.huggingface.co"}
_HUGE_MODEL_MAX_LENGTH = 10**8
_ROLE_TAG_RE = re.compile(r"<\|([a-zA-Z_]+)\|>")
_CHAT_ROLES = {"system", "user", "assistant"}
_DEFAULT_STREAM_TIMEOUT_SEC = 5.0
_ENV_TRUE_VALUES = {"1", "true", "yes", "on"}


def _prefer_system_libstdcpp_for_torch_extensions() -> None:
    """Prefer a newer system libstdc++ for native CUDA extensions on Linux."""
    if not sys.platform.startswith("linux"):
        return
    if _env_flag("D2C_DISABLE_SYSTEM_LIBSTDCXX"):
        return

    candidates = (
        "/usr/lib/x86_64-linux-gnu/libstdc++.so.6",
        "/lib/x86_64-linux-gnu/libstdc++.so.6",
    )
    mode = int(getattr(os, "RTLD_GLOBAL", 0) | getattr(os, "RTLD_NOW", 0))
    for path in candidates:
        if not os.path.exists(path):
            continue
        try:
            lib = ctypes.CDLL(path, mode=mode)
            getattr(lib, "__cxa_call_terminate")
        except Exception:
            continue
        os.environ.setdefault("D2C_PRELOADED_LIBSTDCXX", path)
        return


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


def _stream_timeout_seconds() -> float:
    raw = str(os.environ.get("D2C_STREAM_TIMEOUT_SEC", "")).strip()
    if not raw:
        return _DEFAULT_STREAM_TIMEOUT_SEC
    try:
        parsed = float(raw)
    except Exception:
        return _DEFAULT_STREAM_TIMEOUT_SEC
    if parsed <= 0:
        return _DEFAULT_STREAM_TIMEOUT_SEC
    return min(120.0, parsed)


def _env_flag(name: str) -> bool:
    return str(os.environ.get(name, "")).strip().casefold() in _ENV_TRUE_VALUES


def _build_remote_code_kwargs(trust_remote_code: bool) -> dict[str, Any]:
    return {"trust_remote_code": True} if bool(trust_remote_code) else {}


def _prepare_remote_modules_if_needed(*, model_ref: str, trust_remote_code: bool) -> None:
    if bool(trust_remote_code):
        _evict_dynamic_modules_for_repo(model_ref)


def _select_device_and_dtype(
    torch_mod: Any,
    *,
    prefer_bf16_on_cuda: bool,
) -> tuple[str, Any]:
    device = "cpu"
    dtype: Any = None
    if bool(getattr(torch_mod.cuda, "is_available", lambda: False)()):
        device = "cuda"
        dtype = getattr(torch_mod, "float16", None)
        if prefer_bf16_on_cuda:
            try:
                if bool(getattr(torch_mod.cuda, "is_bf16_supported", lambda: False)()):
                    dtype = getattr(torch_mod, "bfloat16", dtype)
            except Exception:
                pass
        return device, dtype

    if bool(getattr(getattr(torch_mod.backends, "mps", None), "is_available", lambda: False)()):
        return "mps", getattr(torch_mod, "float16", None)
    return device, dtype


def _nemotron_mode_flags(
    *,
    model_ref_low: str,
    trust_remote_code: bool,
) -> tuple[bool, bool, bool]:
    is_nemotron = bool(trust_remote_code) and ("nemotron" in str(model_ref_low or ""))
    is_nemotron_fp8 = is_nemotron and ("fp8" in str(model_ref_low or ""))
    fast_kernels_enabled = _env_flag("D2C_ENABLE_NEMOTRON_FAST_KERNELS")
    safe_mode_forced = _env_flag("D2C_FORCE_NEMOTRON_SAFE_MODE")
    default_safe_mode = is_nemotron and (not is_nemotron_fp8)
    force_safe_nemotron = bool(
        is_nemotron
        and (
            safe_mode_forced
            or (default_safe_mode and (not fast_kernels_enabled))
        )
    )
    return is_nemotron, is_nemotron_fp8, force_safe_nemotron


def _resolve_nemotron_fast_mode(
    *,
    is_nemotron_fp8: bool,
    device: str,
    force_safe_nemotron: bool,
) -> tuple[bool, str]:
    force_fast = False
    error_message = ""
    if is_nemotron_fp8 and (str(device) == "cuda") and (not force_safe_nemotron):
        ready, reason = _nemotron_fast_kernels_importable()
        if ready:
            force_fast = True
        else:
            reason_text = str(reason or "Unavailable in current environment.")
            error_message = (
                "Load failed: FP8 Nemotron requires CUDA Mamba kernels "
                "(mamba-ssm >= 2.0.4 and causal-conv1d).\n"
                f"Kernel check failed: {reason_text}\n"
                "Option: use a non-FP8 Nemotron model or force safe fallback via "
                "D2C_FORCE_NEMOTRON_SAFE_MODE=1 (lower quality)."
            )
    return force_fast, error_message


def _patch_nemotron_import_checks(
    *,
    force_safe_nemotron: bool,
    force_fast_nemotron_fp8: bool,
) -> tuple[Any | None, str]:
    if not (force_safe_nemotron or force_fast_nemotron_fp8):
        return None, ""

    try:
        from transformers.utils import import_utils as tf_import_utils  # type: ignore
    except Exception:
        return None, ""

    orig_mamba_2 = tf_import_utils.is_mamba_2_ssm_available
    orig_causal = tf_import_utils.is_causal_conv1d_available
    if force_safe_nemotron:
        tf_import_utils.is_mamba_2_ssm_available = lambda: False
        tf_import_utils.is_causal_conv1d_available = lambda: False
        mode_note = " (safe mode: mamba CUDA kernels disabled)"
    else:
        tf_import_utils.is_mamba_2_ssm_available = lambda: True
        tf_import_utils.is_causal_conv1d_available = lambda: True
        mode_note = ""

    def _restore() -> None:
        try:
            tf_import_utils.is_mamba_2_ssm_available = orig_mamba_2
            tf_import_utils.is_causal_conv1d_available = orig_causal
        except Exception:
            return

    return _restore, mode_note


def _build_model_kwargs(
    *,
    dtype: Any,
    trust_remote_code: bool,
    force_safe_nemotron: bool,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    if dtype is not None:
        kwargs["torch_dtype"] = dtype
    kwargs.update(_build_remote_code_kwargs(trust_remote_code))
    if force_safe_nemotron:
        # Favor eager attention for stability when running Nemotron remote code.
        kwargs.setdefault("attn_implementation", "eager")
    return kwargs


def _apply_fp8_compat_if_needed(
    *,
    model: Any,
    model_ref: str,
    torch_mod: Any,
    dtype: Any,
    is_nemotron_fp8: bool,
) -> str:
    if (not is_nemotron_fp8) or _env_flag("D2C_DISABLE_NEMOTRON_FP8_COMPAT"):
        return ""

    target_dtype = dtype
    if target_dtype is None:
        target_dtype = getattr(torch_mod, "float32", None)

    converted, scaled = _dequantize_fp8_weights_for_compat(
        model,
        model_ref=model_ref,
        torch_mod=torch_mod,
        target_dtype=target_dtype,
    )
    if converted <= 0:
        return ""
    dtype_name = str(target_dtype).replace("torch.", "") if target_dtype is not None else "auto"
    return f" (fp8 compat: dequantized {scaled} scaled layers to {dtype_name})"


def _nemotron_runtime_fast_path_active(model: Any) -> bool:
    module_name = str(getattr(model.__class__, "__module__", "") or "")
    if not module_name.startswith("transformers_modules."):
        return True
    module_obj = sys.modules.get(module_name)
    return bool(getattr(module_obj, "is_fast_path_available", False))


def _is_float8_dtype(dtype: Any) -> bool:
    return "float8" in str(dtype)


def _sanitize_dynamic_module_segment(name: str) -> str:
    text = str(name or "").replace(".", "_dot_").replace("-", "_hyphen_")
    if text and text[0].isdigit():
        text = f"_{text}"
    return text


def _evict_dynamic_modules_for_repo(model_ref: str) -> int:
    parts = [part for part in str(model_ref or "").split("/") if part]
    if not parts:
        return 0
    sanitized = [_sanitize_dynamic_module_segment(part) for part in parts]
    prefix = "transformers_modules." + ".".join(sanitized)
    removed = 0
    for key in list(sys.modules.keys()):
        if key == prefix or key.startswith(prefix + "."):
            sys.modules.pop(key, None)
            removed += 1
    return removed


def _nemotron_fast_kernels_importable() -> tuple[bool, str]:
    try:
        from mamba_ssm.ops.triton.selective_state_update import selective_state_update  # type: ignore
        from mamba_ssm.ops.triton.ssd_combined import (  # type: ignore
            mamba_chunk_scan_combined,
            mamba_split_conv1d_scan_combined,
        )
        from causal_conv1d import causal_conv1d_fn, causal_conv1d_update  # type: ignore
    except Exception as exc:
        return False, str(exc)

    symbols = (
        selective_state_update,
        mamba_chunk_scan_combined,
        mamba_split_conv1d_scan_combined,
        causal_conv1d_fn,
        causal_conv1d_update,
    )
    if not all(symbols):
        return False, "Required Mamba/CausalConv symbols are missing."
    return True, ""


def _load_weight_scale_map(model_ref: str) -> dict[str, float]:
    try:
        from huggingface_hub import snapshot_download  # type: ignore
        from safetensors import safe_open  # type: ignore
    except Exception:
        return {}

    try:
        snapshot_path = snapshot_download(
            repo_id=str(model_ref or ""),
            local_files_only=True,
        )
    except Exception:
        return {}

    scales: dict[str, float] = {}
    try:
        entries = os.scandir(snapshot_path)
    except Exception:
        return {}

    for entry in entries:
        if (not entry.is_file()) or (not entry.name.endswith(".safetensors")):
            continue
        try:
            with safe_open(entry.path, framework="pt", device="cpu") as handle:
                for key in handle.keys():
                    if not str(key).endswith(".weight_scale"):
                        continue
                    try:
                        tensor = handle.get_tensor(key)
                        value = float(tensor.reshape(-1)[0].item())
                    except Exception:
                        continue
                    scales[str(key)] = value
        except Exception:
            continue
    return scales


def _dequantize_fp8_weights_for_compat(
    model: Any,
    *,
    model_ref: str,
    torch_mod: Any,
    target_dtype: Any,
) -> tuple[int, int]:
    named_parameters = getattr(model, "named_parameters", None)
    if not callable(named_parameters):
        return 0, 0
    scales = _load_weight_scale_map(model_ref)
    converted = 0
    scaled = 0
    with torch_mod.no_grad():
        for name, param in named_parameters():
            if param is None:
                continue
            dtype = getattr(param, "dtype", None)
            is_fp8 = _is_float8_dtype(dtype)
            scale_key = ""
            if str(name).endswith(".weight"):
                scale_key = f"{str(name)[:-len('.weight')]}.weight_scale"
            weight_scale = scales.get(scale_key)

            if (not is_fp8) and (weight_scale is None):
                continue

            data = param.data
            if target_dtype is not None and data.dtype != target_dtype:
                data = data.to(dtype=target_dtype)
                converted += 1
            if weight_scale is not None:
                data = data * float(weight_scale)
                scaled += 1
            param.data = data
    return converted, scaled


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
        trust_remote_code: bool = False,
    ) -> tuple[bool, str]:
        _ = n_gpu_layers, embedding, flash_attn
        self.unload_model()
        _prefer_system_libstdcpp_for_torch_extensions()

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
            model_ref_low = resolved_ref.casefold()
            trust_remote = bool(trust_remote_code)
            (
                is_nemotron,
                is_nemotron_fp8,
                force_safe_nemotron,
            ) = _nemotron_mode_flags(
                model_ref_low=model_ref_low,
                trust_remote_code=trust_remote,
            )

            threads = int(n_threads or (os.cpu_count() or 4))
            if threads > 0:
                try:
                    torch.set_num_threads(threads)
                except Exception:
                    pass

            device, dtype = _select_device_and_dtype(
                torch,
                prefer_bf16_on_cuda=is_nemotron,
            )

            tokenizer_kwargs: dict[str, Any] = {"use_fast": True}
            tokenizer_kwargs.update(_build_remote_code_kwargs(trust_remote))
            _prepare_remote_modules_if_needed(
                model_ref=resolved_ref,
                trust_remote_code=trust_remote,
            )
            tokenizer = AutoTokenizer.from_pretrained(resolved_ref, **tokenizer_kwargs)
            if tokenizer.pad_token_id is None and tokenizer.eos_token_id is not None:
                tokenizer.pad_token = tokenizer.eos_token

            force_fast_nemotron_fp8, fast_mode_error = _resolve_nemotron_fast_mode(
                is_nemotron_fp8=is_nemotron_fp8,
                device=device,
                force_safe_nemotron=force_safe_nemotron,
            )
            if fast_mode_error:
                self.unload_model()
                return False, fast_mode_error

            restore_import_checks, safe_mode_note = _patch_nemotron_import_checks(
                force_safe_nemotron=force_safe_nemotron,
                force_fast_nemotron_fp8=force_fast_nemotron_fp8,
            )
            fast_mode_note = (
                " (fast mode: mamba CUDA kernels enabled)"
                if force_fast_nemotron_fp8
                else ""
            )

            model_kwargs = _build_model_kwargs(
                dtype=dtype,
                trust_remote_code=trust_remote,
                force_safe_nemotron=force_safe_nemotron,
            )
            try:
                _prepare_remote_modules_if_needed(
                    model_ref=resolved_ref,
                    trust_remote_code=trust_remote,
                )
                model = AutoModelForCausalLM.from_pretrained(resolved_ref, **model_kwargs)
            finally:
                if callable(restore_import_checks):
                    try:
                        restore_import_checks()
                    except Exception:
                        pass

            fp8_compat_note = _apply_fp8_compat_if_needed(
                model=model,
                model_ref=resolved_ref,
                torch_mod=torch,
                dtype=dtype,
                is_nemotron_fp8=is_nemotron_fp8,
            )

            model.to(device)
            model.eval()

            if force_fast_nemotron_fp8:
                runtime_fast_path = _nemotron_runtime_fast_path_active(model)
                if not runtime_fast_path:
                    self.unload_model()
                    return (
                        False,
                        "Load failed: Nemotron FP8 fast path is not active at runtime. "
                        "Please restart the app and retry. "
                        "If it persists, force safe mode via D2C_FORCE_NEMOTRON_SAFE_MODE=1.",
                    )

            self._model = model
            self._tokenizer = tokenizer
            self._torch = torch
            self._transformers = __import__("transformers")
            self._model_ref = resolved_ref
            self._device = device
            self._context_window = self._infer_context_window(default_n_ctx=int(n_ctx))

            return True, f"✓ {resolved_ref} [transformers/{device}]{safe_mode_note}{fast_mode_note}{fp8_compat_note}"
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
            if hasattr(token_ids, "shape"):
                shape = getattr(token_ids, "shape", ())
                if len(shape) >= 2:
                    return max(1, int(shape[-1]))
                if len(shape) == 1:
                    return max(1, int(shape[0]))
            if token_ids and isinstance(token_ids, list):
                first = token_ids[0]
                if isinstance(first, list):
                    return max(1, len(first))
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
        external_stop_requested = stop_requested or (lambda: False)
        generation_cancelled = False

        def _should_stop() -> bool:
            if generation_cancelled:
                return True
            try:
                return bool(external_stop_requested())
            except Exception:
                return False

        prepared_prompt = self.prepare_prompt(prompt)
        inputs = tokenizer(prepared_prompt, return_tensors="pt")
        inputs = {k: v.to(self._device) for k, v in inputs.items()}
        streamer = transformers_mod.TextIteratorStreamer(
            tokenizer,
            skip_prompt=True,
            skip_special_tokens=False,
        )
        criteria_cls = _build_stop_requested_criteria(transformers_mod, _should_stop)
        stopping = transformers_mod.StoppingCriteriaList([criteria_cls()])
        gen_kwargs = self._build_generation_kwargs(
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            repeat_penalty=repeat_penalty,
        )

        error_holder: dict[str, Exception] = {}
        queue_timeout = _stream_timeout_seconds()

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

        text_queue = getattr(streamer, "text_queue", None)
        stop_signal = getattr(streamer, "stop_signal", None)
        try:
            if text_queue is not None and callable(getattr(text_queue, "get", None)):
                while True:
                    if _should_stop():
                        break
                    try:
                        piece = text_queue.get(timeout=queue_timeout)
                    except queue.Empty:
                        if "error" in error_holder:
                            raise error_holder["error"]
                        if not thread.is_alive():
                            raise RuntimeError(
                                "Generation ended without output. "
                                "The model thread terminated unexpectedly."
                            )
                        continue

                    if piece == stop_signal:
                        break
                    token = str(piece or "")
                    if token:
                        yield token
            else:
                for piece in streamer:
                    if _should_stop():
                        break
                    token = str(piece or "")
                    if token:
                        yield token
        finally:
            generation_cancelled = True
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
