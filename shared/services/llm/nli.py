"""Transformers NLI backend used by the LLM manager."""
from __future__ import annotations

import gc
import json
import re
from typing import Any, Callable

_NLI_TOKEN_RE = re.compile(r"[^\W\d_]{3,}", flags=re.UNICODE)
_NLI_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")


class NLIBackend:
    """Owns the optional transformers cross-encoder for entailment checks."""

    def __init__(
        self,
        *,
        logger: Any = None,
        prompt_renderer: Callable[[str, dict[str, str] | None], str] | None = None,
        io_logger: Callable[[str, str, str | None, str | None], None] | None = None,
    ):
        self.log = logger
        self._render_prompt = prompt_renderer
        self._log_io = io_logger

        self.model: Any = None
        self.tokenizer: Any = None
        self.torch_mod: Any = None
        self.model_id: str = ""
        self.device: str = "cpu"
        self.label_lookup: dict[int, str] = {}
        self.loading: bool = False
        self.last_error: str = ""

    def is_loaded(self) -> bool:
        return self.model is not None and self.tokenizer is not None

    def load_model(self, model_id: str, n_threads: int = 0) -> tuple[bool, str]:
        model_ref = str(model_id or "").strip()
        if not model_ref:
            self.last_error = "NLI model id is empty."
            return False, self.last_error
        if model_ref.casefold().endswith((".gguf", ".bin")):
            self.last_error = (
                "NLI uses Transformers only. Please provide a HuggingFace model id "
                "(for example: cross-encoder/nli-deberta-v3-xsmall)."
            )
            return False, self.last_error
        if self.loading:
            self.last_error = "NLI model is already loading."
            return False, self.last_error

        self.loading = True
        if self.log:
            self.log.info(
                "NLI",
                f"Loading transformers NLI model: {model_ref}"
                f"  |  threads={n_threads or 4}",
            )
        try:
            import torch  # type: ignore
            from transformers import (  # type: ignore
                AutoModelForSequenceClassification,
                AutoTokenizer,
            )

            if n_threads > 0:
                try:
                    torch.set_num_threads(int(n_threads))
                except Exception:
                    pass

            device = "cpu"
            if bool(getattr(torch.cuda, "is_available", lambda: False)()):
                device = "cuda"
            elif bool(
                getattr(getattr(torch.backends, "mps", None), "is_available", lambda: False)()
            ):
                device = "mps"

            tokenizer = AutoTokenizer.from_pretrained(model_ref, use_fast=True)
            model = AutoModelForSequenceClassification.from_pretrained(model_ref)
            model.eval()
            try:
                model.to(device)
            except Exception:
                device = "cpu"
                model.to(device)

            old_model = self.model
            old_torch = self.torch_mod

            self.model = model
            self.tokenizer = tokenizer
            self.torch_mod = torch
            self.model_id = model_ref
            self.device = device
            self.label_lookup = self._build_label_lookup(getattr(model, "config", None))
            self.last_error = ""

            if old_model is not None:
                self._dispose_model(old_model, old_torch)

            return True, f"✓ {model_ref} [{device}]"
        except ImportError:
            self.last_error = (
                "transformers/torch not installed.\n"
                "Run: pip install transformers torch"
            )
            return False, self.last_error
        except Exception as exc:
            self.last_error = f"Load failed: {exc}"
            return False, self.last_error
        finally:
            self.loading = False

    @staticmethod
    def _dispose_model(model: Any, torch_mod: Any | None = None):
        if model is None:
            return
        close_fn = getattr(model, "close", None)
        if callable(close_fn):
            try:
                close_fn()
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

    @staticmethod
    def _build_label_lookup(config: Any) -> dict[int, str]:
        out: dict[int, str] = {}
        if config is None:
            return out
        id2label = getattr(config, "id2label", None)
        if isinstance(id2label, dict):
            for raw_idx, raw_label in id2label.items():
                try:
                    idx = int(raw_idx)
                except Exception:
                    continue
                label = str(raw_label or "").strip()
                if label:
                    out[idx] = label
        if out:
            return out
        label2id = getattr(config, "label2id", None)
        if isinstance(label2id, dict):
            for raw_label, raw_idx in label2id.items():
                try:
                    idx = int(raw_idx)
                except Exception:
                    continue
                label = str(raw_label or "").strip()
                if label:
                    out[idx] = label
        return out

    @staticmethod
    def _normalize_label(raw: str) -> str:
        value = str(raw or "").strip().casefold()
        if value in {"entailment", "entailed", "support", "supported", "belegt", "yes", "ja"}:
            return "entailment"
        if value in {"contradiction", "conflict", "widerspruch", "refuted", "no", "nein"}:
            return "contradiction"
        if value in {"neutral", "unknown", "unrelated", "nicht_belegt"}:
            return "neutral"
        return "neutral"

    @staticmethod
    def _token_set(text: str) -> set[str]:
        return {tok for tok in _NLI_TOKEN_RE.findall(str(text or "").casefold()) if tok}

    @staticmethod
    def pick_evidence(premise: str, hypothesis: str, *, max_chars: int = 220) -> str:
        text = str(premise or "").strip()
        if not text:
            return ""
        if len(text) <= max_chars:
            return text

        h_tokens = NLIBackend._token_set(hypothesis)
        candidates = [part.strip() for part in _NLI_SENTENCE_SPLIT_RE.split(text) if part.strip()]
        best = ""
        best_score = 0.0
        for cand in candidates:
            c_tokens = NLIBackend._token_set(cand)
            if not c_tokens or not h_tokens:
                continue
            score = len(c_tokens & h_tokens) / max(1, len(h_tokens))
            if score > best_score:
                best = cand
                best_score = score
        snippet = best if best else text[:max_chars]
        if len(snippet) > max_chars:
            snippet = snippet[:max_chars].rstrip() + " …"
        return snippet

    @staticmethod
    def _fallback_label_from_index(index: int, class_count: int) -> str:
        if class_count == 3:
            return {0: "contradiction", 1: "entailment", 2: "neutral"}.get(int(index), "neutral")
        if class_count == 2:
            return {0: "contradiction", 1: "entailment"}.get(int(index), "neutral")
        return "neutral"

    def verify_sync(self, premise: str, hypothesis: str) -> dict[str, Any]:
        if self.loading:
            return {
                "label": "neutral",
                "score": 0.0,
                "evidence": "",
                "reason": "nli_model_loading",
                "raw": "",
            }
        if not self.is_loaded():
            return {
                "label": "neutral",
                "score": 0.0,
                "evidence": "",
                "reason": "nli_model_not_loaded",
                "raw": "",
            }
        model = self.model
        tokenizer = self.tokenizer
        torch_mod = self.torch_mod
        if model is None or tokenizer is None or torch_mod is None:
            return {
                "label": "neutral",
                "score": 0.0,
                "evidence": "",
                "reason": "nli_model_missing",
                "raw": "",
            }

        premise_text = str(premise or "").strip()
        hypothesis_text = str(hypothesis or "").strip()
        if not premise_text or not hypothesis_text:
            return {
                "label": "neutral",
                "score": 0.0,
                "evidence": "",
                "reason": "empty_input",
                "raw": "",
            }

        system_block = ""
        user_block = ""
        if callable(self._render_prompt):
            system_block = self._render_prompt("nli_verify_system", None).strip()
            user_block = self._render_prompt(
                "nli_verify_user",
                {"premise": premise_text, "hypothesis": hypothesis_text},
            ).strip()

        if not system_block:
            system_block = (
                "Transformers NLI Workflow:\n"
                "1) tokenize(premise, hypothesis)\n"
                "2) SequenceClassification forward pass\n"
                "3) softmax(logits) -> label entailment|neutral|contradiction"
            )
        if not user_block:
            user_block = f"premise={premise_text}\nhypothesis={hypothesis_text}"

        prompt = (
            "[backend=transformers-cross-encoder]\n"
            f"model_id={self.model_id or 'unknown'}\n"
            f"device={self.device or 'cpu'}\n"
            "<|workflow|>\n"
            f"{system_block}\n"
            "<|input|>\n"
            f"{user_block}\n"
        )
        self._log_llm_io("NLI-Verify", prompt)

        try:
            encoded = tokenizer(
                premise_text,
                hypothesis_text,
                return_tensors="pt",
                truncation=True,
                max_length=512,
            )
        except Exception as exc:
            self._log_llm_io("NLI-Verify", prompt, error=str(exc))
            return {
                "label": "neutral",
                "score": 0.0,
                "evidence": "",
                "reason": f"nli_runtime_error: tokenize_failed: {exc}",
                "raw": "",
            }

        try:
            for key, value in list(encoded.items()):
                to_fn = getattr(value, "to", None)
                if callable(to_fn):
                    encoded[key] = to_fn(self.device or "cpu")

            with torch_mod.no_grad():
                outputs = model(**encoded)
                logits_tensor = outputs.logits[0]
                probs_tensor = torch_mod.softmax(logits_tensor, dim=-1)
                best_index = int(torch_mod.argmax(probs_tensor).item())

            logits = [float(x) for x in logits_tensor.detach().cpu().tolist()]
            probs = [float(x) for x in probs_tensor.detach().cpu().tolist()]
            class_count = len(probs)
            raw_label = str(self.label_lookup.get(best_index, f"LABEL_{best_index}") or "").strip()
            label = self._normalize_label(raw_label)
            if label == "neutral":
                label = self._fallback_label_from_index(best_index, class_count)
            score = probs[best_index] if 0 <= best_index < class_count else 0.0
            score = max(0.0, min(1.0, float(score)))

            evidence = premise_text if label in {"entailment", "contradiction"} else ""
            ranking = sorted(range(class_count), key=lambda idx: probs[idx], reverse=True)
            top_labels = []
            for idx in ranking[:3]:
                name = str(self.label_lookup.get(idx, f"LABEL_{idx}") or f"LABEL_{idx}")
                top_labels.append({"index": idx, "label": name, "prob": round(probs[idx], 6)})

            reason = (
                f"backend=transformers; raw_label={raw_label}; "
                f"best_index={best_index}; model={self.model_id or 'unknown'}"
            )
            raw_full = json.dumps(
                {
                    "backend": "transformers-cross-encoder",
                    "model_id": self.model_id or "",
                    "device": self.device or "cpu",
                    "premise_len": len(premise_text),
                    "hypothesis_len": len(hypothesis_text),
                    "label_lookup": self.label_lookup,
                    "best_index": best_index,
                    "raw_label": raw_label,
                    "mapped_label": label,
                    "score": score,
                    "logits": logits,
                    "probs": probs,
                    "top_labels": top_labels,
                    "reason": reason,
                    "evidence": evidence,
                },
                ensure_ascii=False,
            )
            self._log_llm_io("NLI-Verify", prompt, raw_full)
            return {
                "label": label,
                "score": score,
                "evidence": evidence,
                "reason": reason,
                "raw": raw_full,
            }
        except Exception as exc:
            if self.log:
                self.log.error("NLI", f"NLI inference failed: {exc}")
            self._log_llm_io("NLI-Verify", prompt, error=str(exc))
            return {
                "label": "neutral",
                "score": 0.0,
                "evidence": "",
                "reason": f"nli_runtime_error: {exc}",
                "raw": "",
            }

    def _log_llm_io(
        self,
        call_name: str,
        prompt: str,
        output: str | None = None,
        error: str | None = None,
    ):
        if callable(self._log_io):
            self._log_io(call_name, prompt, output, error)
