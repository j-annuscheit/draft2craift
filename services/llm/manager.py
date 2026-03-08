"""
LLM Manager
===========
Two classes:

  LLMWorker  – QThread that owns the llama_cpp.Llama instance.
               Emits streamed tokens via signals.

  LLMManager – High-level QObject that builds context-aware prompts,
               tracks generation timing, and exposes a clean API to
               the rest of the app.  Accepts an optional AppLogger
               for detailed debug output.
"""
from __future__ import annotations

import gc
import json
import os
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any

from PySide6.QtCore import QThread, QObject, Signal
from features.canvas.structured_graph import (
    GraphEdge,
    GraphNode,
    GraphSpec,
    extract_graph_spec,
    spec_to_markdown,
)
from services.rag.system import RAGConfig, RAGSystem

CANVAS_REWRITE_OPEN = "[[CANVAS_REWRITE]]"
CANVAS_REWRITE_CLOSE = "[[/CANVAS_REWRITE]]"
CANVAS_TARGET_SECTION_TITLE = (
    "## DIESER TEXT WIRD ERSETZT (NUR DIESER ABSCHNITT)"
)
CANVAS_TARGET_START = "[[CANVAS_TARGET_START]]"
CANVAS_TARGET_END = "[[CANVAS_TARGET_END]]"
POST_CONTEXT_REWRITE_TITLE = (
    "### WICHTIG: REWRITE-AUFTRAG (NACH KONTEXT) ###"
)
GROUNDING_INSUFFICIENT_MESSAGE = (
    "Nicht genug Informationen in den ausgewählten Dokumenten/RAG-Quellen."
)
REQUIRED_STYLE_RULES = (
    "Verbindliche Stilregel:\n"
    "- Verwende keinen Gedankenstrich als Satzzeichen "
    "(—, –, ‒, ― oder ' - ').\n"
    "- Nutze stattdessen je nach Satz Komma, Punkt, Doppelpunkt "
    "oder Klammern.\n"
    "- Bindestriche innerhalb von Wörtern sind erlaubt "
    "(z. B. 3D-Datensatz)."
)

def _runtime_app_root() -> Path:
    """
    Return the directory that contains bundled data files.

    - Source run: project root (repository root)
    - PyInstaller: sys._MEIPASS (onefile temp dir or onedir _internal)
    """
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    # manager.py -> services/llm/manager.py, project root is parents[2]
    return Path(__file__).resolve().parents[2]


# ── Worker ────────────────────────────────────────────────────────────────────

class LLMWorker(QThread):
    """
    Runs llama_cpp.Llama inside a dedicated thread so the UI never blocks.

    Usage
    -----
    1. Call ``load_model(path, …)`` → start() → waits for ``model_loaded``
    2. Call ``generate(prompt, …)``  → start() → streams ``token_received``
                                                 → emits ``generation_complete``
    """

    token_received      = Signal(str)
    generation_complete = Signal(str)
    error_occurred      = Signal(str)
    model_loaded        = Signal(bool, str)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._model: Any = None
        self._task: str  = ""           # "load" | "generate"
        self._stop: bool = False

        self._model_path: str = ""
        self._load_params: dict = {}

        self._prompt: str = ""
        self._gen_params: dict = {}
        self._forbidden_chars: tuple[str, ...] = ()
        self._forbidden_bias_cache_model: tuple[str, int] | None = None
        self._forbidden_bias_cache: dict[tuple[str, ...], dict[int, float]] = {}
        self._model_thread_ident: int | None = None

    # ── Public API ────────────────────────────────────────────────────────────

    def load_model(
        self,
        model_path: str,
        n_ctx: int = 4096,
        n_gpu_layers: int = 0,
        n_threads: int = 0,
        embedding: bool = False,
    ):
        self._task       = "load"
        self._model_path = model_path
        self._load_params = {
            "n_ctx":        n_ctx,
            "n_gpu_layers": n_gpu_layers,
            "n_threads":    n_threads or (os.cpu_count() or 4),
            "embedding":    bool(embedding),
            "verbose":      False,
        }
        if not self.isRunning():
            self.start()

    def generate(
        self,
        prompt: str,
        max_tokens: int   = 1024,
        temperature: float = 0.7,
        top_p: float       = 0.9,
        repeat_penalty: float = 1.1,
        forbidden_chars: tuple[str, ...] | None = None,
    ):
        if self._model is None:
            self.error_occurred.emit("No model loaded.")
            return
        self._task      = "generate"
        self._prompt    = prompt
        self._gen_params = {
            "max_tokens":     max_tokens,
            "temperature":    temperature,
            "top_p":          top_p,
            "repeat_penalty": repeat_penalty,
            "stream":         True,
            "stop":           ["<|"],
        }
        self._forbidden_chars = tuple(sorted(set(forbidden_chars or ())))
        self._stop = False
        if not self.isRunning():
            self.start()

    def request_stop(self):
        self._stop = True

    # ── Thread entry ──────────────────────────────────────────────────────────

    def run(self):
        if self._task == "load":
            self._do_load()
        elif self._task == "generate":
            self._do_generate()

    def _do_load(self):
        try:
            self._release_loaded_model()
            from llama_cpp import Llama  # type: ignore
            self._model = Llama(model_path=self._model_path, **self._load_params)
            self._model_thread_ident = int(threading.get_ident())
            self._forbidden_bias_cache_model = None
            self._forbidden_bias_cache.clear()
            self.model_loaded.emit(True, f"✓ {os.path.basename(self._model_path)}")
        except ImportError:
            self.model_loaded.emit(
                False,
                "llama-cpp-python not installed.\nRun: pip install llama-cpp-python",
            )
        except Exception as exc:
            self.model_loaded.emit(False, f"Load failed: {exc}")

    def _release_loaded_model(self):
        """Release currently loaded model resources before loading another one."""
        model = self._model
        self._model = None
        self._model_thread_ident = None
        self._forbidden_bias_cache_model = None
        self._forbidden_bias_cache.clear()
        if model is None:
            return
        close_fn = getattr(model, "close", None)
        if callable(close_fn):
            try:
                close_fn()
            except Exception:
                pass
        del model
        gc.collect()

    def _build_forbidden_logit_bias(self) -> dict[int, float]:
        """
        Build a token-bias map that suppresses tokens containing forbidden chars.

        Uses llama.cpp sampling (`logit_bias`) directly and caches results per
        loaded model + forbidden-char set to avoid repeated full-vocab scans.
        """
        if self._model is None or not self._forbidden_chars:
            return {}

        model_key = (self._model_path, int(self._model.n_vocab()))
        if self._forbidden_bias_cache_model != model_key:
            self._forbidden_bias_cache_model = model_key
            self._forbidden_bias_cache.clear()

        key = self._forbidden_chars
        cached = self._forbidden_bias_cache.get(key)
        if cached is not None:
            return cached

        forbidden_bytes = [ch.encode("utf-8") for ch in key if ch]
        logit_bias: dict[int, float] = {}
        n_vocab = int(self._model.n_vocab())

        for tid in range(n_vocab):
            piece: bytes
            try:
                piece = self._model.detokenize([tid], special=True)
            except TypeError:
                try:
                    piece = self._model.detokenize([tid])
                except Exception:
                    continue
            except Exception:
                continue

            if not piece:
                continue

            if any(fb and fb in piece for fb in forbidden_bytes):
                logit_bias[tid] = -100.0
                continue

            text = piece.decode("utf-8", errors="ignore")
            if text and any(ch in text for ch in key):
                logit_bias[tid] = -100.0

        self._forbidden_bias_cache[key] = logit_bias
        return logit_bias

    def _do_generate(self):
        """Stream tokens, cutting off at the first '<|' sentinel.

        llama_cpp's ``stop`` parameter handles the common case, but the
        sentinel can arrive split across two tokens (e.g. '<' then '|').
        The one-character look-behind buffer below catches that edge case
        without delaying any visible output.
        """
        STOP = "<|"
        keep = len(STOP) - 1   # 1 char held back to detect split sentinel
        try:
            full = ""
            buf  = ""
            gen_params = dict(self._gen_params)
            if self._forbidden_chars:
                bias = self._build_forbidden_logit_bias()
                if bias:
                    gen_params["logit_bias"] = bias

            for chunk in self._model(self._prompt, **gen_params):
                if self._stop:
                    break
                token = chunk["choices"][0].get("text", "")
                if not token:
                    continue

                buf += token

                if STOP in buf:
                    safe = buf[: buf.index(STOP)]
                    if safe:
                        full += safe
                        self.token_received.emit(safe)
                    break

                # Flush everything except the last `keep` chars, which might
                # be the start of a split '<|' sequence.
                if len(buf) > keep:
                    emit = buf[:-keep]
                    full += emit
                    self.token_received.emit(emit)
                    buf = buf[-keep:]

            else:
                # Loop completed without hitting a stop — flush the buffer.
                if buf:
                    full += buf
                    self.token_received.emit(buf)

            self.generation_complete.emit(full)
        except Exception as exc:
            self.error_occurred.emit(f"Generation error: {exc}")


# ── Manager ───────────────────────────────────────────────────────────────────

class LLMManager(QObject):
    """
    High-level manager.  Builds context-aware prompts, tracks timing, and
    delegates execution to LLMWorker.

    Parameters
    ----------
    logger:
        Optional AppLogger instance.  When provided, LLM calls, timing,
        errors, and query expansion are written to the debug log.

    Prompt layout
    -------------
    <system>
    [optional context block: attached files, RAG excerpts, selected text]
    [chat history]
    <user>
    <assistant>
    """

    token_received      = Signal(str)
    generation_complete = Signal(str)
    error_occurred      = Signal(str)
    model_loaded        = Signal(bool, str)
    nli_model_loaded    = Signal(bool, str)
    is_generating       = Signal(bool)

    _FORBIDDEN_CHAR_ALIASES = {
        "nbsp": "\u00A0",
        "nnbsp": "\u202F",
        "thinspace": "\u2009",
        "figurespace": "\u2007",
        "wordjoiner": "\u2060",
        "zwnbsp": "\uFEFF",
        "emdash": "—",
        "endash": "–",
        "semicolon": ";",
        "space": " ",
    }
    PROMPT_KEYS: tuple[str, ...] = (
        "chat_system",
        "chat_section_grounding_title",
        "chat_section_rewrite_title",
        "chat_section_context_title",
        "chat_section_context_end",
        "chat_section_files_title",
        "chat_section_rag_title",
        "chat_section_selected_title",
        "chat_citation_rule_answer",
        "chat_citation_rule_rewrite",
        "chat_grounding_note_rewrite",
        "chat_grounding_rules",
        "chat_canvas_rewrite_rules",
        "claim_extract_system",
        "claim_extract_user",
        "fact_verify_system",
        "fact_verify_user",
        "fact_verify_chunk_system",
        "fact_verify_chunk_user",
        "nli_verify_system",
        "nli_verify_user",
        "fact_check_system",
        "hyde_tfidf_system",
        "hyde_tfidf_user",
        "hyde_st_single_system",
        "hyde_st_single_user",
        "hyde_st_multi_system",
        "hyde_st_multi_user",
        "literal_terms_system",
        "literal_terms_user",
        "rag_rerank_system",
        "rag_rerank_user",
        "mindmap_system",
        "mindmap_user",
        "graph_system",
        "graph_user",
        "glossary_system",
        "glossary_user",
    )
    PROMPT_DEFAULTS_FILE = _runtime_app_root() / "prompts" / "defaults.json"

    def __init__(self, logger: Any = None, parent: QObject | None = None):
        super().__init__(parent)
        self._log    = logger
        self.worker  = LLMWorker()
        self._nli_model: Any = None
        self._nli_tokenizer: Any = None
        self._nli_torch: Any = None
        self._nli_model_id: str = ""
        self._nli_device: str = "cpu"
        self._nli_label_lookup: dict[int, str] = {}
        self._nli_loading: bool = False
        self._nli_last_error: str = ""
        self._prompt_defaults: dict[str, str] = self._load_prompt_defaults()
        self._prompts: dict[str, str] = dict(self._prompt_defaults)
        self._system_prompt = self._prompts["chat_system"]
        # Generation timing
        self._gen_start: float = 0.0
        self._token_count: int = 0
        self._forbidden_chars: set[str] = set()

        # Wire worker signals through interceptors for logging
        self.worker.token_received.connect(self._on_token)
        self.worker.generation_complete.connect(self._on_complete)
        self.worker.error_occurred.connect(self._on_error)
        self.worker.model_loaded.connect(self._on_model_loaded)

    # ── Model management ──────────────────────────────────────────────────────

    def load_model(
        self,
        path: str,
        n_ctx: int = 4096,
        n_gpu_layers: int = 0,
        n_threads: int = 0,
    ):
        if self._log:
            basename = os.path.basename(path)
            threads  = n_threads or (os.cpu_count() or 4)
            self._log.info(
                "LLM",
                f"Loading model: {basename}"
                f"  |  n_ctx={n_ctx}  gpu_layers={n_gpu_layers}  threads={threads}",
            )
        self.worker.load_model(path, n_ctx=n_ctx, n_gpu_layers=n_gpu_layers, n_threads=n_threads)

    def is_model_loaded(self) -> bool:
        return self.worker._model is not None

    def load_nli_model(
        self,
        model_id: str,
        n_ctx: int = 2048,
        n_gpu_layers: int = 0,
        n_threads: int = 0,
    ):
        _ = n_ctx, n_gpu_layers
        model_ref = str(model_id or "").strip()
        if not model_ref:
            self._on_nli_model_loaded(False, "NLI model id is empty.")
            return
        if model_ref.casefold().endswith((".gguf", ".bin")):
            self._on_nli_model_loaded(
                False,
                "NLI uses Transformers only. Please provide a HuggingFace model id "
                "(for example: cross-encoder/nli-deberta-v3-xsmall).",
            )
            return
        if self._nli_loading:
            self._on_nli_model_loaded(False, "NLI model is already loading.")
            return

        self._nli_loading = True
        if self._log:
            self._log.info(
                "NLI",
                f"Loading transformers NLI model: {model_ref}"
                f"  |  threads={n_threads or (os.cpu_count() or 4)}",
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

            old_model = self._nli_model
            old_torch = self._nli_torch

            self._nli_model = model
            self._nli_tokenizer = tokenizer
            self._nli_torch = torch
            self._nli_model_id = model_ref
            self._nli_device = device
            self._nli_label_lookup = self._build_nli_label_lookup(
                getattr(model, "config", None)
            )
            self._nli_last_error = ""

            if old_model is not None:
                self._dispose_nli_model(old_model, old_torch)

            self._on_nli_model_loaded(True, f"✓ {model_ref} [{device}]")
        except ImportError:
            self._on_nli_model_loaded(
                False,
                "transformers/torch not installed.\n"
                "Run: pip install transformers torch",
            )
        except Exception as exc:
            self._on_nli_model_loaded(False, f"Load failed: {exc}")
        finally:
            self._nli_loading = False

    def is_nli_model_loaded(self) -> bool:
        return self._nli_model is not None and self._nli_tokenizer is not None

    @staticmethod
    def _dispose_nli_model(model: Any, torch_mod: Any | None = None):
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
    def _build_nli_label_lookup(config: Any) -> dict[int, str]:
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
    def _normalize_nli_label(raw: str) -> str:
        value = str(raw or "").strip().casefold()
        if value in {"entailment", "entailed", "support", "supported", "belegt", "yes", "ja"}:
            return "entailment"
        if value in {"contradiction", "conflict", "widerspruch", "refuted", "no", "nein"}:
            return "contradiction"
        if value in {"neutral", "unknown", "unrelated", "nicht_belegt"}:
            return "neutral"
        return "neutral"

    @staticmethod
    def _nli_token_set(text: str) -> set[str]:
        return {
            tok
            for tok in re.findall(r"[^\W\d_]{3,}", str(text or "").casefold())
            if tok
        }

    @staticmethod
    def _nli_pick_evidence(premise: str, hypothesis: str, *, max_chars: int = 220) -> str:
        text = str(premise or "").strip()
        if not text:
            return ""
        if len(text) <= max_chars:
            return text

        h_tokens = LLMManager._nli_token_set(hypothesis)
        candidates = [
            part.strip()
            for part in re.split(r"(?<=[.!?])\s+|\n+", text)
            if part.strip()
        ]
        best = ""
        best_score = 0.0
        for cand in candidates:
            c_tokens = LLMManager._nli_token_set(cand)
            if not c_tokens or not h_tokens:
                continue
            score = len(c_tokens & h_tokens) / max(1, len(h_tokens))
            if score > best_score:
                best = cand
                best_score = score
        snippet = best if best else text[:max_chars]
        snippet = re.sub(r"\s+", " ", snippet).strip()
        if len(snippet) > max_chars:
            snippet = snippet[:max_chars].rstrip() + " …"
        return snippet

    @staticmethod
    def _fallback_nli_label_from_index(index: int, class_count: int) -> str:
        if class_count == 3:
            # Standard MNLI ordering used by many cross-encoder NLI checkpoints.
            mapping = {0: "contradiction", 1: "entailment", 2: "neutral"}
            return mapping.get(int(index), "neutral")
        if class_count == 2:
            mapping = {0: "contradiction", 1: "entailment"}
            return mapping.get(int(index), "neutral")
        return "neutral"

    def verify_nli_sync(self, premise: str, hypothesis: str) -> dict[str, Any]:
        """Run one NLI decision for premise/hypothesis on the transformers cross-encoder."""
        if self._nli_loading:
            return {
                "label": "neutral",
                "score": 0.0,
                "evidence": "",
                "reason": "nli_model_loading",
                "raw": "",
            }
        if not self.is_nli_model_loaded():
            return {
                "label": "neutral",
                "score": 0.0,
                "evidence": "",
                "reason": "nli_model_not_loaded",
                "raw": "",
            }
        model = self._nli_model
        tokenizer = self._nli_tokenizer
        torch_mod = self._nli_torch
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

        system_block = self._render_prompt_template("nli_verify_system").strip()
        user_block = self._render_prompt_template(
            "nli_verify_user",
            {
                "premise": premise_text,
                "hypothesis": hypothesis_text,
            },
        ).strip()
        if not system_block:
            system_block = (
                "Transformers NLI Workflow:\n"
                "1) tokenize(premise, hypothesis)\n"
                "2) SequenceClassification forward pass\n"
                "3) softmax(logits) -> label entailment|neutral|contradiction"
            )
        if not user_block:
            user_block = (
                f"premise={premise_text}\n"
                f"hypothesis={hypothesis_text}"
            )
        prompt = (
            "[backend=transformers-cross-encoder]\n"
            f"model_id={self._nli_model_id or 'unknown'}\n"
            f"device={self._nli_device or 'cpu'}\n"
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
                    encoded[key] = to_fn(self._nli_device or "cpu")

            with torch_mod.no_grad():
                outputs = model(**encoded)
                logits_tensor = outputs.logits[0]
                probs_tensor = torch_mod.softmax(logits_tensor, dim=-1)
                best_index = int(torch_mod.argmax(probs_tensor).item())

            logits = [float(x) for x in logits_tensor.detach().cpu().tolist()]
            probs = [float(x) for x in probs_tensor.detach().cpu().tolist()]
            class_count = len(probs)
            raw_label = str(
                self._nli_label_lookup.get(best_index, f"LABEL_{best_index}") or ""
            ).strip()
            label = self._normalize_nli_label(raw_label)
            if label == "neutral":
                label = self._fallback_nli_label_from_index(best_index, class_count)
            score = probs[best_index] if 0 <= best_index < class_count else 0.0
            score = max(0.0, min(1.0, float(score)))

            evidence = ""
            if label in {"entailment", "contradiction"}:
                evidence = premise_text

            ranking = sorted(
                range(class_count),
                key=lambda idx: probs[idx],
                reverse=True,
            )
            top_labels = []
            for idx in ranking[:3]:
                name = str(self._nli_label_lookup.get(idx, f"LABEL_{idx}") or f"LABEL_{idx}")
                top_labels.append({"index": idx, "label": name, "prob": round(probs[idx], 6)})

            reason = (
                f"backend=transformers; raw_label={raw_label}; "
                f"best_index={best_index}; model={self._nli_model_id or 'unknown'}"
            )
            raw_full = json.dumps(
                {
                    "backend": "transformers-cross-encoder",
                    "model_id": self._nli_model_id or "",
                    "device": self._nli_device or "cpu",
                    "premise_len": len(premise_text),
                    "hypothesis_len": len(hypothesis_text),
                    "label_lookup": self._nli_label_lookup,
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
            if self._log:
                self._log.error("NLI", f"NLI inference failed: {exc}")
            self._log_llm_io("NLI-Verify", prompt, error=str(exc))
            return {
                "label": "neutral",
                "score": 0.0,
                "evidence": "",
                "reason": f"nli_runtime_error: {exc}",
                "raw": "",
            }

    def _load_prompt_defaults(self) -> dict[str, str]:
        """Load default prompt templates from external JSON file."""
        defaults: dict[str, str] = {}
        src = self.PROMPT_DEFAULTS_FILE
        try:
            with src.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                for key in self.PROMPT_KEYS:
                    value = data.get(key, "")
                    if isinstance(value, str):
                        defaults[key] = value
        except Exception as exc:
            if self._log:
                self._log.error("LLM", f"Prompt-Defaults konnten nicht geladen werden ({src}): {exc}")

        for key in self.PROMPT_KEYS:
            defaults.setdefault(key, "")

        if not defaults.get("chat_system", "").strip():
            defaults["chat_system"] = "Du bist ein hilfreicher Schreibassistent."

        return defaults

    def set_system_prompt(self, text: str):
        value = str(text or "").strip()
        if not value:
            value = self._prompt_defaults["chat_system"]
        self._prompts["chat_system"] = value
        self._system_prompt = value

    def get_prompt_set(self) -> dict[str, str]:
        """Return all configurable prompt templates (system + user blocks)."""
        return dict(self._prompts)

    def get_prompt_defaults(self) -> dict[str, str]:
        """Return default prompt templates (immutable copy)."""
        return dict(self._prompt_defaults)

    def set_prompt_set(self, prompts: dict[str, str]):
        """Apply multiple prompt values (unknown keys are ignored)."""
        if not isinstance(prompts, dict):
            return
        for key in self.PROMPT_KEYS:
            if key not in prompts:
                continue
            value = str(prompts.get(key, "") or "").strip()
            if not value:
                value = self._prompt_defaults[key]
            else:
                value = self._migrate_legacy_prompt_value(key, value)
            self._prompts[key] = value
        self._system_prompt = self._prompts["chat_system"]

    def _migrate_legacy_prompt_value(self, key: str, value: str) -> str:
        """Upgrade known legacy default prompts to current defaults."""
        candidate = str(value or "").strip()
        if self._is_legacy_prompt_value(key, candidate):
            upgraded = str(self._prompt_defaults.get(key, candidate) or "").strip()
            if upgraded and upgraded != candidate:
                if self._log:
                    self._log.info(
                        "LLM",
                        f"Prompt-Migration: '{key}' wurde auf aktuellen Default angehoben.",
                    )
                return upgraded
        return candidate

    @staticmethod
    def _is_legacy_prompt_value(key: str, candidate: str) -> bool:
        """Heuristically detect older built-in prompts from previous releases."""
        text = str(candidate or "").strip()
        if not text:
            return False

        if key == "mindmap_system":
            return (
                text.startswith("Du erstellst eine MindMap aus Kontext.")
                and "Verbindliche Regeln:" not in text
            )
        if key == "mindmap_user":
            return (
                "Erstelle eine MindMap zur Frage: {query}" in text
                and "Nutze nur diesen Kontext:" in text
                and "Ausgabeformat streng:" in text
                and "Arbeite intern in 3 Schritten:" not in text
            )
        if key == "graph_system":
            return (
                text.startswith("Du erstellst einen Wissensgraphen aus Kontext.")
                and "Verbindliche Regeln:" not in text
            )
        if key == "graph_user":
            return (
                "Erstelle einen Wissensgraphen zur Frage: {query}" in text
                and "Nutze nur diesen Kontext:" in text
                and "Ausgabeformat" in text
                and "Arbeite intern in 4 Schritten:" not in text
            )
        return False

    def _render_prompt_template(
        self,
        key: str,
        replacements: dict[str, str] | None = None,
    ) -> str:
        """Lightweight placeholder substitution for configurable prompt templates."""
        text = str(self._prompts.get(key, self._prompt_defaults.get(key, "")) or "")
        out = text
        for name, value in (replacements or {}).items():
            out = out.replace("{" + str(name) + "}", str(value))
        return out

    def render_prompt_template(
        self,
        key: str,
        replacements: dict[str, str] | None = None,
    ) -> str:
        """Public wrapper used by UI elements to render editable prompt templates."""
        return self._render_prompt_template(key, replacements)

    def _log_llm_io(
        self,
        call_name: str,
        prompt: str,
        output: str | None = None,
        error: str | None = None,
    ):
        """Write full input/output for one synchronous LLM call into debug log."""
        if not self._log:
            return
        self._log.debug("LLM", f"[{call_name}] INPUT:\n{prompt}")
        if output is not None:
            self._log.debug("LLM", f"[{call_name}] OUTPUT:\n{output}")
        if error:
            self._log.error("LLM", f"[{call_name}] ERROR: {error}")

    @staticmethod
    def _extract_tagged_payload(raw_text: str, tag: str) -> str:
        payload, _tag_found = LLMManager._extract_tagged_payload_with_flag(raw_text, tag)
        return payload

    @staticmethod
    def _extract_tagged_payload_with_flag(raw_text: str, tag: str) -> tuple[str, bool]:
        raw = str(raw_text or "")
        if not raw.strip():
            return "", False
        tag_name = str(tag or "").strip()
        if not tag_name:
            return raw.strip(), True
        m = re.search(
            rf"<{re.escape(tag_name)}>\s*([\s\S]*?)\s*</{re.escape(tag_name)}>",
            raw,
            flags=re.IGNORECASE,
        )
        if m:
            return str(m.group(1) or "").strip(), True
        return raw.strip(), False

    def fix_markdown_chunk_sync(
        self,
        markdown_chunk: str,
    ) -> tuple[str, dict[str, Any]]:
        """
        Repair Markdown formatting for one chunk while preserving content meaning.

        The call is synchronous and should only be used when the streaming worker
        is idle.
        """
        source = str(markdown_chunk or "")
        if not source.strip():
            return source, {
                "applied": False,
                "reason": "empty_input",
            }
        if not self.is_model_loaded():
            return source, {
                "applied": False,
                "reason": "model_not_loaded",
            }
        if self.worker.isRunning():
            return source, {
                "applied": False,
                "reason": "model_busy",
            }

        model = self.worker._model
        if model is None:
            return source, {
                "applied": False,
                "reason": "model_missing",
            }
        if self._log:
            caller_tid = int(threading.get_ident())
            model_tid = int(getattr(self.worker, "_model_thread_ident", 0) or 0)
            self._log.debug(
                "LLM",
                (
                    "[Import-Markdown-Fix] call context"
                    f"  |  caller_tid={caller_tid}"
                    f"  model_tid={model_tid}"
                    f"  same_thread={int(caller_tid == model_tid and model_tid != 0)}"
                    f"  worker_running={int(bool(self.worker.isRunning()))}"
                ),
            )

        system_prompt = (
            "Du bist ein strenger Markdown-Repair-Assistent.\n"
            "Du darfst NUR Markdown-Strukturfehler korrigieren.\n"
            "Erlaubt: Ueberschriftensyntax, Tabellen-Trennzeilen, Listenmarker, "
            "Codeblock-Zaeune, kaputte Zeilenumbrueche durch OCR "
            "(Worttrennung am Zeilenende, gesplittete Absatze).\n"
            "Fuehre Korrekturen IMMER direkt im Text aus, niemals als Markierung.\n"
            "Verboten sind insbesondere Korrektur-Annotationen wie *Teilwort*, "
            "_Teilwort_, [sic], Kommentare oder Erklaerungen.\n"
            "Wenn ein Wort fehlerhaft getrennt ist, gib das korrekte Wort direkt aus "
            "(z.B. 'In nerhalb' -> 'Innerhalb').\n"
            "Ueberschriften muessen immer auf einer eigenen Zeile stehen.\n"
            "Nie eine Ueberschrift an den vorherigen oder naechsten Absatz haengen.\n"
            "Wenn eine fett markierte, nummerierte Kapitelzeile vorliegt "
            "(z.B. '**5.2.4 Titel** ...'), bevorzuge eine echte "
            "Markdown-Ueberschrift statt Fettdruck.\n"
            "Setze den Absatztext danach in die naechste Zeile.\n"
            "Bewertungsskalen oder Legenden (z.B. '**0 P.** **1 P.** **2 P.**' "
            "oder Prozentlisten) sind KEINE Ueberschriften.\n"
            "Erzeuge neue Markdown-Ueberschriften nur bei klaren Kapitelzeilen "
            "wie '5.2.4 Titel' oder '3 Ergebnisse'.\n"
            "Bei Binnenstern-Schreibungen in Woertern (z.B. Kuenstler*innen) "
            "muss der Stern in Markdown escaped werden (Kuenstler\\*innen).\n"
            "Verboten: inhaltliche Umschreibungen, neue Fakten, Loeschung relevanter "
            "Aussagen, Umstellung von Satzinhalten, Stilverbesserungen.\n"
            "Zahlen, Namen, Zeitangaben, Reihenfolge und Aussagegehalt muessen "
            "erhalten bleiben.\n"
            "Wenn unsicher: Original unveraendert lassen."
        )
        source_tokens = max(1, self._count_tokens(source))
        max_out_tokens = max(280, min(2200, int(source_tokens * 2.1)))
        max_attempts = 3
        last_raw_full = ""
        last_error = ""

        for attempt in range(1, max_attempts + 1):
            retry_hint = ""
            if attempt >= 2:
                retry_hint = (
                    "\nWICHTIG: Deine Antwort MUSS exakt ein <fixed_md>...</fixed_md> "
                    "enthalten. Keine weiteren Tags, kein Fliesstext ausserhalb."
                )
            user_prompt = (
                "Repariere den folgenden Markdown-Block.\n"
                "Gib NUR den korrigierten Markdown-Block zurueck, eingeschlossen in:\n"
                "<fixed_md>\n"
                "...markdown...\n"
                "</fixed_md>\n"
                "Kein weiterer Text."
                f"{retry_hint}\n\n"
                "<markdown_input>\n"
                f"{source}\n"
                "</markdown_input>"
            )
            prompt = (
                "<|system|>\n"
                f"{system_prompt}\n"
                "<|user|>\n"
                f"{user_prompt}\n"
                "<|assistant|>\n"
            )
            window_err = self._check_prompt_window(prompt, max_out_tokens)
            if window_err:
                if self._log:
                    self._log.error("LLM", f"Import markdown-fix context too large: {window_err}")
                self._log_llm_io(
                    f"Import-Markdown-Fix#{attempt}",
                    prompt,
                    error=window_err,
                )
                return source, {
                    "applied": False,
                    "reason": "context_too_large",
                    "error": window_err,
                }
            try:
                result = model(
                    prompt,
                    max_tokens=max_out_tokens,
                    temperature=0.05,
                    top_p=0.9,
                    repeat_penalty=1.0,
                    stop=["<|"],
                    stream=False,
                )
                raw_full = str(result["choices"][0].get("text", "") or "")
                last_raw_full = raw_full
                self._log_llm_io(f"Import-Markdown-Fix#{attempt}", prompt, raw_full)
                payload, tag_found = self._extract_tagged_payload_with_flag(
                    raw_full,
                    "fixed_md",
                )
                if tag_found and payload.strip():
                    return payload, {
                        "applied": True,
                        "reason": "ok",
                        "attempt": attempt,
                        "tag_found": True,
                        "raw_len": len(raw_full),
                        "out_len": len(payload),
                    }
            except Exception as exc:
                last_error = str(exc)
                self._log_llm_io(
                    f"Import-Markdown-Fix#{attempt}",
                    prompt,
                    error=last_error,
                )
                if self._log:
                    self._log.error("LLM", f"Import markdown-fix failed (attempt {attempt}): {exc}")

        # After 3 failed tagged attempts, use full output as a last fallback.
        fallback = str(last_raw_full or "").strip()
        if fallback:
            return fallback, {
                "applied": True,
                "reason": "fallback_raw_output",
                "attempt": max_attempts,
                "tag_found": False,
                "raw_len": len(last_raw_full),
                "out_len": len(fallback),
            }

        if last_error:
            return source, {
                "applied": False,
                "reason": "exception",
                "error": last_error,
            }
        return source, {
            "applied": False,
            "reason": "empty_output",
            "raw_preview": str(last_raw_full or "")[:220],
        }

    def expand_query_tfidf_sync(self, query: str) -> str:
        """HyDE keyword expansion for the TF-IDF backend.

        Generates a comma-separated list of domain keywords / synonyms.
        TF-IDF matches these terms against the indexed vocabulary, dramatically
        improving recall for short or abstract queries.

        Call only while the worker is idle (not generating).
        """
        if not self.is_model_loaded():
            return query
        if self.worker.isRunning():
            if self._log:
                self._log.debug("LLM", f"HyDE (TF-IDF) skipped – model busy: '{query}'")
            return query
        model = self.worker._model
        user_block = self._render_prompt_template(
            "hyde_tfidf_user",
            {"query": query},
        )
        prompt = (
            "<|system|>\n"
            f"{self._prompts['hyde_tfidf_system']}\n"
            "<|user|>\n"
            f"{user_block}\n"
            "<|assistant|>\n"
        )
        try:
            result   = model(prompt, max_tokens=80, temperature=0.2,
                             stop=["<|"], stream=False)
            raw_text = result["choices"][0].get("text", "")
            self._log_llm_io("HyDE-TFIDF", prompt, raw_text)
            keywords = raw_text.strip()
            if self._log:
                if keywords:
                    self._log.info(
                        "LLM",
                        f"HyDE (TF-IDF keywords): '{query}'  ->  '{keywords[:100]}'",
                    )
                else:
                    self._log.debug("LLM", f"HyDE (TF-IDF) no output for: '{query}'")
            return keywords if keywords else query
        except Exception as exc:
            self._log_llm_io("HyDE-TFIDF", prompt, error=str(exc))
            if self._log:
                self._log.error("LLM", f"HyDE TF-IDF expansion failed: {exc}")
            return query

    def expand_query_st_sync(self, query: str, n_hypotheses: int = 1) -> list[str]:
        """HyDE passage expansion for the sentence-transformers backend.

        Generates 1 or *n_hypotheses* short hypothetical passages whose vectors
        closely match real document chunks for cosine-similarity retrieval.

        Returns a ``list[str]`` (always at least ``[query]`` as fallback).
        Call only while the worker is idle (not generating).
        """
        if not self.is_model_loaded():
            return [query]
        if self.worker.isRunning():
            if self._log:
                self._log.debug("LLM", f"HyDE (ST) skipped – model busy: '{query}'")
            return [query]
        model = self.worker._model

        if n_hypotheses <= 1:
            user_block = self._render_prompt_template(
                "hyde_st_single_user",
                {"query": query},
            )
            prompt = (
                "<|system|>\n"
                f"{self._prompts['hyde_st_single_system']}\n"
                "<|user|>\n"
                f"{user_block}\n"
                "<|assistant|>\n"
            )
            try:
                result  = model(prompt, max_tokens=120, temperature=0.3,
                                stop=["<|"], stream=False)
                raw_text = result["choices"][0].get("text", "")
                self._log_llm_io("HyDE-ST-single", prompt, raw_text)
                passage = raw_text.strip()
                if self._log and passage and passage != query:
                    self._log.info(
                        "LLM",
                        f"HyDE (ST passage): '{query}'  ->  '{passage[:80]}…'",
                    )
                return [passage] if passage else [query]
            except Exception as exc:
                self._log_llm_io("HyDE-ST-single", prompt, error=str(exc))
                if self._log:
                    self._log.error("LLM", f"HyDE ST expansion failed: {exc}")
                return [query]
        else:
            user_block = self._render_prompt_template(
                "hyde_st_multi_user",
                {"query": query, "n_hypotheses": str(n_hypotheses)},
            )
            prompt = (
                "<|system|>\n"
                f"{self._prompts['hyde_st_multi_system']}\n"
                "<|user|>\n"
                f"{user_block}\n"
                "<|assistant|>\n"
            )
            try:
                result   = model(
                    prompt,
                    max_tokens=120 * n_hypotheses,
                    temperature=0.5,
                    stop=["<|"],
                    stream=False,
                )
                raw_text = result["choices"][0].get("text", "")
                self._log_llm_io("HyDE-ST-multi", prompt, raw_text)
                text     = raw_text.strip()
                passages = [p.strip() for p in text.split("---") if p.strip()]
                if not passages:
                    passages = [query]
                if self._log:
                    self._log.info(
                        "LLM",
                        f"HyDE (ST multi-passage x{len(passages)}): '{query}'",
                    )
                return passages
            except Exception as exc:
                self._log_llm_io("HyDE-ST-multi", prompt, error=str(exc))
                if self._log:
                    self._log.error("LLM", f"HyDE ST multi-passage expansion failed: {exc}")
                return [query]

    def expand_query_literal_terms_sync(
        self,
        query: str,
        max_terms: int = 8,
    ) -> list[str] | tuple[list[str], dict[str, Any]]:
        """Generate short literal search terms for the literal RAG backend."""
        if not self.is_model_loaded():
            return [], {
                "applied": False,
                "used": False,
                "reason": "model_not_loaded",
            }
        if self.worker.isRunning():
            if self._log:
                self._log.debug("LLM", f"Literal expansion skipped – model busy: '{query}'")
            return [], {
                "applied": False,
                "used": False,
                "reason": "model_busy",
            }

        limit = max(1, int(max_terms))
        model = self.worker._model
        user_block = self._render_prompt_template(
            "literal_terms_user",
            {"query": query, "max_terms": str(limit)},
        )
        prompt = (
            "<|system|>\n"
            f"{self._prompts['literal_terms_system']}\n"
            "<|user|>\n"
            f"{user_block}\n"
            "<|assistant|>\n"
        )
        try:
            result = model(
                prompt,
                max_tokens=max(40, limit * 12),
                temperature=0.2,
                top_p=0.9,
                stop=["<|"],
                stream=False,
            )
            raw_full = result["choices"][0].get("text", "")
            self._log_llm_io("Literal-Terms", prompt, raw_full)
            raw = raw_full.strip()
            if not raw:
                return [], {
                    "applied": True,
                    "used": False,
                    "reason": "empty",
                }

            terms: list[str] = []
            seen: set[str] = set()
            for token in re.split(r"[,\n;]+", raw):
                term = token.strip()
                term = re.sub(r"^\s*(?:[-*]+|\d+[\.\)])\s*", "", term).strip()
                term = term.strip("\"'`")
                term = re.sub(r"\s+", " ", term)
                if len(term) < 2:
                    continue
                key = term.casefold()
                if key in seen:
                    continue
                seen.add(key)
                terms.append(term)
                if len(terms) >= limit:
                    break

            if self._log:
                if terms:
                    self._log.info(
                        "LLM",
                        f"Literal terms: '{query}' -> {', '.join(terms[:8])}",
                    )
                else:
                    self._log.debug("LLM", f"Literal terms empty for: '{query}'")
            return terms, {
                "applied": True,
                "used": bool(terms),
                "reason": "ok" if terms else "empty",
            }
        except Exception as exc:
            self._log_llm_io("Literal-Terms", prompt, error=str(exc))
            if self._log:
                self._log.error("LLM", f"Literal term expansion failed: {exc}")
            return [], {
                "applied": False,
                "used": False,
                "reason": "exception",
                "error": str(exc),
            }

    def rerank_rag_results_sync(
        self,
        query: str,
        candidates: list[dict],
        top_k: int = 5,
        min_score: float = 0.45,
    ) -> tuple[list[dict], dict]:
        """Rerank and filter RAG candidates via LLM class labels."""
        if not candidates:
            return [], {
                "applied": True,
                "reason": "no_candidates",
                "selected": 0,
                "evaluated": 0,
            }
        if not self.is_model_loaded():
            return candidates[:top_k], {
                "applied": False,
                "reason": "model_not_loaded",
                "selected": min(len(candidates), top_k),
                "evaluated": len(candidates),
            }
        if self.worker.isRunning():
            if self._log:
                self._log.debug("LLM", f"RAG rerank skipped – model busy: '{query}'")
            return candidates[:top_k], {
                "applied": False,
                "reason": "model_busy",
                "selected": min(len(candidates), top_k),
                "evaluated": len(candidates),
            }

        model = self.worker._model
        limit = max(1, len(candidates))
        docs = candidates[:limit]
        score_threshold = max(0.0, min(1.0, float(min_score)))

        items: list[str] = []
        for idx, doc in enumerate(docs):
            raw_name = str(doc.get("name", "")).strip()
            if not raw_name:
                raw_name = str(doc.get("doc", "")).strip()
            if not raw_name:
                raw_name = str(doc.get("key", "")).strip()
            name = os.path.basename(raw_name) if raw_name else "unknown"

            methods: list[str] = []
            if isinstance(doc.get("methods"), list):
                methods = [str(m) for m in doc.get("methods", []) if str(m).strip()]
            else:
                meta = doc.get("meta", {})
                if isinstance(meta, dict) and isinstance(meta.get("methods"), list):
                    methods = [str(m) for m in meta.get("methods", []) if str(m).strip()]
            source = ", ".join(methods) if methods else "unknown"

            excerpt = str(doc.get("excerpt", "")).strip()
            excerpt = re.sub(r"\s+", " ", excerpt)
            items.append(f"[{idx}] {name}  | source: {source}\n{excerpt}")

        user_block = self._render_prompt_template(
            "rag_rerank_user",
            {
                "query": query,
                "items": "\n\n".join(items),
            },
        )
        prompt = (
            "<|system|>\n"
            f"{self._prompts['rag_rerank_system']}\n"
            "<|user|>\n"
            f"{user_block}\n"
            "<|assistant|>\n"
        )
        max_out_tokens = max(160, 64 * len(docs))
        window_err = self._check_prompt_window(prompt, max_out_tokens)
        if window_err:
            if self._log:
                self._log.error("LLM", f"RAG rerank context too large: {window_err}")
            return docs[:top_k], {
                "applied": False,
                "reason": "context_too_large",
                "error": window_err,
                "selected": min(len(docs), top_k),
                "evaluated": len(docs),
            }

        try:
            result = model(
                prompt,
                max_tokens=max_out_tokens,
                temperature=0.1,
                top_p=0.9,
                repeat_penalty=1.05,
                stop=["<|"],
                stream=False,
            )
            raw_full = result["choices"][0].get("text", "")
            self._log_llm_io("RAG-Rerank", prompt, raw_full)
            raw = raw_full.strip()

            parsed: Any = None
            try:
                parsed = json.loads(raw)
            except Exception:
                m = re.search(r"\[[\s\S]*\]", raw)
                if m:
                    parsed = json.loads(m.group(0))

            if not isinstance(parsed, list):
                return docs[:top_k], {
                    "applied": False,
                    "reason": "parse_failed",
                    "selected": min(len(docs), top_k),
                    "evaluated": len(docs),
                    "raw_preview": raw[:300],
                }

            decisions_by_idx: dict[int, dict[str, Any]] = {}
            for item in parsed:
                if not isinstance(item, dict):
                    continue
                try:
                    idx = int(item.get("idx", -1))
                except Exception:
                    continue
                if idx < 0 or idx >= len(docs):
                    continue
                score_value: float | None = None
                if "score" in item:
                    try:
                        score_value = max(0.0, min(1.0, float(item.get("score", 0.0))))
                    except Exception:
                        score_value = None
                cls_raw = str(item.get("class", "") or "").strip().lower()
                if cls_raw in {"sinnvoll", "useful", "relevant", "ja", "yes", "keep"}:
                    cls = "sinnvoll"
                elif cls_raw in {"nicht_sinnvoll", "nicht sinnvoll", "irrelevant", "no", "nein", "drop"}:
                    cls = "nicht_sinnvoll"
                else:
                    keep_raw = item.get("keep", None)
                    if isinstance(keep_raw, bool):
                        keep_fallback = keep_raw
                    elif isinstance(keep_raw, (int, float)):
                        keep_fallback = bool(keep_raw)
                    elif isinstance(keep_raw, str):
                        keep_fallback = keep_raw.strip().lower() in {"1", "true", "yes", "ja", "keep"}
                    elif score_value is not None:
                        keep_fallback = score_value >= score_threshold
                    else:
                        keep_fallback = False
                    cls = "sinnvoll" if keep_fallback else "nicht_sinnvoll"
                reason = str(item.get("reason", "") or "")[:240]
                prev = decisions_by_idx.get(idx)
                if prev is None:
                    decisions_by_idx[idx] = {
                        "idx": idx,
                        "class": cls,
                        "keep": (cls == "sinnvoll"),
                        "score": score_value,
                        "reason": reason,
                    }
                elif prev.get("class") != "sinnvoll" and cls == "sinnvoll":
                    # Prefer positive classification for the same idx.
                    decisions_by_idx[idx] = {
                        "idx": idx,
                        "class": cls,
                        "keep": True,
                        "score": score_value,
                        "reason": reason,
                    }

            if not decisions_by_idx:
                return docs[:top_k], {
                    "applied": False,
                    "reason": "no_valid_decisions",
                    "selected": min(len(docs), top_k),
                    "evaluated": len(docs),
                }

            ordered = sorted(
                decisions_by_idx.values(),
                key=lambda d: (1 if d.get("class") == "sinnvoll" else 0),
                reverse=True,
            )

            selected: list[dict] = []
            debug_decisions: list[dict[str, Any]] = []
            for dec in ordered:
                idx = int(dec["idx"])
                cls = str(dec.get("class", "nicht_sinnvoll"))
                keep = bool(dec["keep"]) and cls == "sinnvoll"
                reason = str(dec.get("reason", ""))
                score_value = dec.get("score", None)

                doc = dict(docs[idx])
                meta = dict(doc.get("meta", {})) if isinstance(doc.get("meta"), dict) else {}
                meta["llm_rerank_class"] = cls
                meta["llm_rerank_keep"] = keep
                if isinstance(score_value, (int, float)):
                    meta["llm_rerank_score"] = round(float(score_value), 4)
                if reason:
                    meta["llm_rerank_reason"] = reason
                doc["meta"] = meta

                debug_decisions.append({
                    "idx": idx,
                    "name": str(doc.get("name", "") or doc.get("doc", "") or doc.get("key", "")),
                    "class": cls,
                    "score": round(float(score_value), 4) if isinstance(score_value, (int, float)) else None,
                    "keep": keep,
                    "reason": reason,
                })
                if keep:
                    selected.append(doc)

            selected = selected[:max(1, int(top_k))]
            if self._log:
                self._log.info(
                    "LLM",
                    f"RAG rerank: '{query}'  |  selected {len(selected)}/{len(docs)}",
                )
            return selected, {
                "applied": True,
                "reason": "ok",
                "selected": len(selected),
                "evaluated": len(docs),
                "mode": "class_label",
                "threshold": score_threshold,
                "decisions": debug_decisions,
            }
        except Exception as exc:
            self._log_llm_io("RAG-Rerank", prompt, error=str(exc))
            if self._log:
                self._log.error("LLM", f"RAG rerank failed: {exc}")
            return docs[:top_k], {
                "applied": False,
                "reason": "exception",
                "error": str(exc),
                "selected": min(len(docs), top_k),
                "evaluated": len(docs),
            }

    @staticmethod
    def _normalize_mindmap_mode(mode: str) -> str:
        value = str(mode or "").strip().casefold()
        if ("chunk" in value) or ("abschnitt" in value) or ("section" in value):
            return "chunkmap"
        if "graph" in value or "wissens" in value:
            return "graph"
        return "mindmap"

    @staticmethod
    def _slug_node_id(text: str, fallback: str) -> str:
        raw = re.sub(r"[^a-z0-9]+", "-", str(text or "").strip().casefold()).strip("-")
        return raw or fallback

    @staticmethod
    def _chunk_leaf_label(index: int, chunk_text: str) -> str:
        lead = re.sub(r"\s+", " ", str(chunk_text or "")).strip()
        if not lead:
            return f"Chunk {index:02d}"
        return f"Chunk {index:02d}: {lead}"

    def _generate_chunk_mindmap_sync(
        self,
        *,
        context_text: str,
        query: str,
        max_nodes: int,
        chunking_strategy: str,
        chunk_size: int,
        chunk_overlap: int,
    ) -> tuple[str, dict[str, Any]]:
        strategy = str(chunking_strategy or "").strip().casefold()
        if strategy not in {"sliding_window", "section", "recursive"}:
            strategy = "sliding_window"

        size = max(220, min(4200, int(chunk_size or 900)))
        overlap = max(0, min(size - 20, int(chunk_overlap or 160)))
        # chunkmap: max_nodes <= 0 means "no hard leaf limit".
        try:
            requested_limit = int(max_nodes)
        except Exception:
            requested_limit = 0
        leaf_limit = requested_limit if requested_limit > 0 else 0

        cfg = RAGConfig(
            use_tfidf=False,
            use_st=False,
            use_regex_search=False,
            use_hyde=False,
            chunk_size=size,
            chunk_overlap=overlap,
            chunking_strategy=strategy,
            include_headings=True,
            include_filename=False,
        )

        try:
            chunker = RAGSystem(config=cfg)
            chunk_rows = chunker._build_chunks(context_text, doc_name="Kontext")  # pylint: disable=protected-access
        except Exception as exc:
            if self._log:
                self._log.error("LLM", f"Chunk-MindMap chunking failed: {exc}")
            return "", {
                "applied": False,
                "reason": "chunking_exception",
                "error": str(exc),
            }

        if not chunk_rows:
            return "", {
                "applied": False,
                "reason": "no_chunks",
            }

        question = str(query or "").strip()
        title = "Chunk-MindMap"
        if question:
            title = f"Chunk-MindMap: {question[:96]}"

        root_label = question[:120] if question else "Kontext"
        root_id = "root"
        nodes: dict[str, GraphNode] = {
            root_id: GraphNode(node_id=root_id, label=root_label or "Kontext")
        }
        roots = [root_id]
        edges: list[GraphEdge] = []
        edge_seen: set[tuple[str, str]] = set()
        used_ids: set[str] = {root_id}
        path_to_node: dict[tuple[str, ...], str] = {(): root_id}

        def alloc_node_id(prefix: str, seed: str) -> str:
            base = self._slug_node_id(seed, prefix)
            candidate = f"{prefix}-{base}"
            candidate = candidate.strip("-")
            if not candidate:
                candidate = prefix
            if candidate not in used_ids:
                used_ids.add(candidate)
                return candidate
            idx = 2
            while True:
                probe = f"{candidate}-{idx}"
                if probe not in used_ids:
                    used_ids.add(probe)
                    return probe
                idx += 1

        def connect(parent_id: str, child_id: str):
            parent = nodes.get(parent_id)
            if parent is not None and child_id not in parent.children:
                parent.children.append(child_id)
            key = (parent_id, child_id)
            if key in edge_seen:
                return
            edge_seen.add(key)
            edges.append(GraphEdge(source_id=parent_id, target_id=child_id, label=""))

        chunk_count = 0
        total_chunks = 0
        truncated = False

        for row in chunk_rows:
            chunk_text = str(row.get("raw_text", "") or "").strip()
            if not chunk_text:
                continue
            total_chunks += 1
            if leaf_limit > 0 and chunk_count >= leaf_limit:
                truncated = True
                continue

            breadcrumb_raw = row.get("breadcrumb", [])
            breadcrumb: list[str] = []
            if isinstance(breadcrumb_raw, list):
                for item in breadcrumb_raw:
                    token = re.sub(r"\s+", " ", str(item or "")).strip()
                    if token:
                        breadcrumb.append(token)
            if not breadcrumb:
                breadcrumb = ["Ohne Ueberschrift"]

            parent_id = root_id
            path_parts: list[str] = []
            for heading in breadcrumb:
                path_parts.append(heading)
                path_key = tuple(path_parts)
                heading_node_id = path_to_node.get(path_key, "")
                if not heading_node_id:
                    heading_node_id = alloc_node_id("h", " / ".join(path_parts))
                    nodes[heading_node_id] = GraphNode(
                        node_id=heading_node_id,
                        label=heading,
                    )
                    path_to_node[path_key] = heading_node_id
                    connect(parent_id, heading_node_id)
                parent_id = heading_node_id

            chunk_count += 1
            leaf_id = alloc_node_id("chunk", str(chunk_count))
            nodes[leaf_id] = GraphNode(
                node_id=leaf_id,
                label=self._chunk_leaf_label(chunk_count, chunk_text),
                quote=chunk_text,
            )
            connect(parent_id, leaf_id)

        if chunk_count <= 0:
            return "", {
                "applied": False,
                "reason": "no_nonempty_chunks",
            }

        spec = GraphSpec(
            kind="mindmap",
            title=title,
            nodes=nodes,
            roots=roots,
            edges=edges,
        )
        markdown = spec_to_markdown(spec)
        if self._log:
            self._log.info(
                "LLM",
                "Chunk-MindMap erstellt"
                f"  |  chunks={chunk_count}/{total_chunks}"
                f"  |  strategy={strategy}"
                f"  |  chunk_size={size}"
                f"  |  overlap={overlap}",
            )
        return markdown, {
            "applied": True,
            "reason": "ok",
            "kind": "mindmap",
            "variant": "chunkmap",
            "nodes": len(nodes),
            "edges": len(edges),
            "chunks": chunk_count,
            "chunks_total": total_chunks,
            "chunking_strategy": strategy,
            "chunk_size": size,
            "chunk_overlap": overlap,
            "truncated": truncated,
        }

    def generate_mindmap_sync(
        self,
        *,
        context_text: str,
        query: str = "",
        mode: str = "mindmap",
        max_nodes: int = 28,
        chunking_strategy: str = "sliding_window",
        chunk_size: int = 900,
        chunk_overlap: int = 160,
    ) -> tuple[str, dict[str, Any]]:
        """Generate a structured MindMap/Wissensgraph markdown block."""
        context = str(context_text or "").strip()
        if not context:
            return "", {
                "applied": False,
                "reason": "empty_context",
            }
        mode_clean = self._normalize_mindmap_mode(mode)
        if mode_clean == "chunkmap":
            return self._generate_chunk_mindmap_sync(
                context_text=context,
                query=str(query or ""),
                max_nodes=max_nodes,
                chunking_strategy=chunking_strategy,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
            )
        if not self.is_model_loaded():
            return "", {
                "applied": False,
                "reason": "model_not_loaded",
            }
        if self.worker.isRunning():
            if self._log:
                self._log.debug(
                    "LLM",
                    "MindMap generation skipped – model busy.",
                )
            return "", {
                "applied": False,
                "reason": "model_busy",
            }

        if mode_clean == "graph":
            system_key = "graph_system"
            user_key = "graph_user"
            hard_system_rules = (
                "HARTE REGELN (immer befolgen):\n"
                "- Kein Inhaltsverzeichnis und kein Kapitelgerüst ausgeben.\n"
                "- Nur Tripel im Format Subjekt | Relation | Objekt.\n"
                "- Relation darf nicht leer/generisch sein.\n"
                "- Keine Entitäts-Dubletten, keine Selbstkanten, keine Halluzinationen.\n"
                "- Ziel ist ein möglichst zusammenhängender Graph mit einer dominanten Hauptkomponente.\n"
                "- Neue Tripel sollen bevorzugt an bereits eingeführte Entitäten andocken.\n"
                "- Viele isolierte Mini-Subgraphen vermeiden; wenn nicht belegbar verbindbar, weglassen."
            )
            hard_user_rules = (
                "Zusatzregeln:\n"
                "- Verwerfe TOC-/Layout-Zeilen (z. B. \"Inhaltsverzeichnis\", \"1.2\", Seitenzahlen).\n"
                "- Wenn du nur Strukturüberschriften findest, gib stattdessen die stärksten inhaltlichen Beziehungen aus.\n"
                "- Bevorzuge gemeinsame Entitäten als Brücken zwischen Teilaspekten.\n"
                "- Isolierte Inseln nur wenn der Kontext keine belegbare Verbindung liefert."
            )
        else:
            system_key = "mindmap_system"
            user_key = "mindmap_user"
            hard_system_rules = (
                "HARTE REGELN (immer befolgen):\n"
                "- Kein Inhaltsverzeichnis und kein Kapitelgerüst ausgeben.\n"
                "- Nur konzeptuelle Knoten und Beziehungen (nicht Dokument-Navigation).\n"
                "- Blätter müssen Kurz-Zitate enthalten: Label :: \"Zitat\".\n"
                "- Keine Halluzinationen.\n"
                "- MindMap muss wirklich hierarchisch sein, nicht flache Liste:\n"
                "  * genau 1 Wurzelknoten,\n"
                "  * darunter 3-7 Hauptäste,\n"
                "  * pro Hauptast 2-4 Unterknoten,\n"
                "  * mehrere Blattknoten mit Direktzitaten.\n"
                "- Einrückung: exakt 2 Leerzeichen je Ebene.\n"
                "- Mehrere Einrückungsebenen sind ausdrücklich erlaubt.\n"
                "- Die Hierarchie wird ausschließlich über diese Einrückungen gebildet.\n"
                "- Hierarchierichtung strikt: Oben steht das übergeordnete Ganze, unten nur Teilaspekte/Unterkategorien/Belege.\n"
                "- Ein allgemeinerer Begriff darf niemals unter einem spezielleren Begriff stehen."
            )
            hard_user_rules = (
                "Zusatzregeln:\n"
                "- Verwerfe TOC-/Layout-Zeilen (z. B. \"Inhaltsverzeichnis\", \"1.2\", Seitenzahlen).\n"
                "- Wenn der Kontext viele Überschriften enthält, priorisiere dennoch inhaltliche Aussagen und Befunde.\n"
                "- Forme die Ausgabe als Baum (Konzept->Unterkonzept->Beleg), nicht als Stichwortsammlung.\n"
                "- Nutze bei Bedarf mehrere Einrückungsstufen; jede zusätzliche Einrückung ist eine tiefere Ebene.\n"
                "- Prüfe jede Eltern->Kind-Kante: Kind muss ein Teil/eine Spezifizierung des Elternknotens sein.\n"
                "- Wenn eine Kante umgekehrt ist (Unterpunkt allgemeiner als Parent), Richtung korrigieren."
            )
        limit = max(8, min(96, int(max_nodes)))
        question = str(query or "").strip()
        if not question:
            question = "Erstelle eine strukturierte Übersicht."

        system_prompt = str(self._prompts.get(system_key, "") or "").strip()
        if hard_system_rules not in system_prompt:
            system_prompt = (system_prompt + "\n\n" + hard_system_rules).strip()
        user_block = self._render_prompt_template(
            user_key,
            {
                "context": context,
                "query": question,
                "mode": mode_clean,
                "max_nodes": str(limit),
            },
        )
        user_block = str(user_block or "").strip()
        if hard_user_rules not in user_block:
            if mode_clean == "mindmap":
                # Keep context as final section in the user prompt.
                user_block = (hard_user_rules + "\n\n" + user_block).strip()
            else:
                user_block = (user_block + "\n\n" + hard_user_rules).strip()
        prompt = (
            "<|system|>\n"
            f"{system_prompt}\n"
            "<|user|>\n"
            f"{user_block}\n"
            "<|assistant|>\n"
        )
        max_out_tokens = max(320, min(3600, limit * 140))
        window_err = self._check_prompt_window(prompt, max_out_tokens)
        if window_err:
            if self._log:
                self._log.error("LLM", f"MindMap context too large: {window_err}")
            return "", {
                "applied": False,
                "reason": "context_too_large",
                "error": window_err,
            }

        model = self.worker._model
        try:
            result = model(
                prompt,
                max_tokens=max_out_tokens,
                temperature=0.2,
                top_p=0.9,
                repeat_penalty=1.05,
                stop=["<|"],
                stream=False,
            )
            raw_full = result["choices"][0].get("text", "")
            self._log_llm_io("MindMap", prompt, raw_full)
            raw = str(raw_full or "").strip()
            if not raw:
                return "", {
                    "applied": True,
                    "reason": "empty",
                }

            spec = extract_graph_spec(raw)
            if spec is None:
                spec = extract_graph_spec(f"```{mode_clean}\n{raw}\n```")
            if spec is None:
                json_match = re.search(r"\{[\s\S]*\}", raw)
                if json_match is not None:
                    candidate = f"```{mode_clean}\n{json_match.group(0)}\n```"
                    spec = extract_graph_spec(candidate)
            if spec is None:
                return "", {
                    "applied": False,
                    "reason": "parse_failed",
                    "raw_preview": raw[:320],
                }

            if mode_clean == "graph":
                spec.kind = "graph"
            else:
                spec.kind = "mindmap"

            if spec.title.strip() in {"MindMap", "Wissensgraph"} and question:
                prefix = "Wissensgraph" if spec.kind == "graph" else "MindMap"
                spec.title = f"{prefix}: {question[:96]}"

            if spec.kind == "graph":
                for edge in spec.edges:
                    if not str(edge.label or "").strip():
                        edge.label = "bezogen_auf"
            else:
                for node in spec.nodes.values():
                    if node.children:
                        continue
                    quote = str(getattr(node, "quote", "") or "").strip()
                    if quote:
                        continue
                    desc = str(node.description or "").strip()
                    if not desc:
                        continue
                    node.quote = desc[:220]

            markdown = spec_to_markdown(spec)
            return markdown, {
                "applied": True,
                "reason": "ok",
                "kind": spec.kind,
                "nodes": len(spec.nodes),
                "edges": len(spec.edges),
            }
        except Exception as exc:
            self._log_llm_io("MindMap", prompt, error=str(exc))
            if self._log:
                self._log.error("LLM", f"MindMap generation failed: {exc}")
            return "", {
                "applied": False,
                "reason": "exception",
                "error": str(exc),
            }

    def generate_glossary_sync(
        self,
        context_text: str,
        max_terms: int = 24,
    ) -> tuple[list[dict[str, object]], dict[str, Any]]:
        """Generate glossary entries from context text via local LLM."""
        context = str(context_text or "").strip()
        if not context:
            return [], {
                "applied": False,
                "reason": "empty_context",
            }
        if not self.is_model_loaded():
            return [], {
                "applied": False,
                "reason": "model_not_loaded",
            }
        if self.worker.isRunning():
            if self._log:
                self._log.debug("LLM", "Glossary generation skipped – model busy.")
            return [], {
                "applied": False,
                "reason": "model_busy",
            }

        model = self.worker._model
        limit = max(1, min(64, int(max_terms)))

        def _compact_context(text: str, max_chars: int) -> tuple[str, bool]:
            source = str(text or "")
            cap = max(1200, int(max_chars))
            if len(source) <= cap:
                return source, False
            marker = "\n\n[... Kontext gekürzt ...]\n\n"
            if cap <= (len(marker) + 24):
                return source[:cap], True
            head_len = int(cap * 0.72)
            tail_len = max(0, cap - head_len - len(marker))
            compact = (
                source[:head_len].rstrip()
                + marker
                + source[-tail_len:].lstrip()
            )
            return compact, True

        def _normalize_entries(parsed: Any) -> list[dict[str, object]]:
            if isinstance(parsed, dict):
                for key in ("entries", "glossary", "items", "begriffe"):
                    value = parsed.get(key)
                    if isinstance(value, list):
                        parsed = value
                        break
                else:
                    # Single object fallback.
                    parsed = [parsed]

            if not isinstance(parsed, list):
                return []

            out: list[dict[str, object]] = []
            seen: set[str] = set()
            for item in parsed:
                term = ""
                definition = ""
                aliases: list[str] = []
                if isinstance(item, dict):
                    term = str(
                        item.get("term")
                        or item.get("begriff")
                        or item.get("keyword")
                        or item.get("title")
                        or ""
                    ).strip()
                    definition = str(
                        item.get("definition")
                        or item.get("erklaerung")
                        or item.get("erklärung")
                        or item.get("explanation")
                        or item.get("desc")
                        or ""
                    ).strip()
                    raw_aliases = item.get("aliases", [])
                    if isinstance(raw_aliases, list):
                        aliases = [
                            str(alias or "").strip()
                            for alias in raw_aliases
                            if str(alias or "").strip()
                        ]
                    elif isinstance(raw_aliases, str):
                        aliases = [
                            token.strip()
                            for token in re.split(r"[,\n;]+", raw_aliases)
                            if token.strip()
                        ]
                elif isinstance(item, str):
                    term = str(item or "").strip(" -*\t\"'`")

                if len(term) < 2:
                    continue
                key = term.casefold()
                if key in seen:
                    continue
                seen.add(key)
                out.append(
                    {
                        "term": term,
                        "definition": definition,
                        "aliases": aliases,
                    }
                )
                if len(out) >= limit:
                    break
            return out

        def _parse_glossary_output(raw_text: str) -> tuple[list[dict[str, object]], str]:
            raw = str(raw_text or "").strip()
            if not raw:
                return [], "empty"

            candidates: list[str] = [raw]
            for m in re.finditer(r"```(?:json)?\s*([\s\S]*?)```", raw, flags=re.IGNORECASE):
                candidate = str(m.group(1) or "").strip()
                if candidate:
                    candidates.append(candidate)
            bracket_match = re.search(r"\[[\s\S]*\]", raw)
            if bracket_match:
                candidates.append(str(bracket_match.group(0) or "").strip())
            object_match = re.search(r"\{[\s\S]*\}", raw)
            if object_match:
                candidates.append(str(object_match.group(0) or "").strip())

            seen_candidates: set[str] = set()
            for candidate in candidates:
                token = str(candidate or "").strip()
                if not token or token in seen_candidates:
                    continue
                seen_candidates.add(token)
                try:
                    parsed = json.loads(token)
                except Exception:
                    continue
                normalized = _normalize_entries(parsed)
                if normalized:
                    return normalized, "json"

            # Minimal text fallback: "- TERM: definition" / "TERM: definition".
            fallback_rows: list[dict[str, object]] = []
            seen_terms: set[str] = set()
            for line in raw.splitlines():
                entry = str(line or "").strip()
                entry = re.sub(r"^\s*(?:[-*]+|\d+[\.\)])\s*", "", entry).strip()
                if not entry:
                    continue
                term = ""
                definition = ""
                if ":" in entry:
                    left, right = entry.split(":", 1)
                    term = left.strip(" \"'`")
                    definition = right.strip()
                else:
                    if len(entry.split()) <= 5:
                        term = entry.strip(" \"'`")
                if len(term) < 2:
                    continue
                key = term.casefold()
                if key in seen_terms:
                    continue
                seen_terms.add(key)
                fallback_rows.append(
                    {
                        "term": term,
                        "definition": definition,
                        "aliases": [],
                    }
                )
                if len(fallback_rows) >= limit:
                    break
            if fallback_rows:
                return fallback_rows, "lines"
            return [], "parse_failed"

        def _call_glossary(
            *,
            call_name: str,
            prompt: str,
            stop_tokens: list[str] | None,
            temperature: float,
            top_p: float,
            repeat_penalty: float,
            max_tokens: int,
        ) -> str:
            kwargs: dict[str, Any] = {
                "max_tokens": int(max_tokens),
                "temperature": float(temperature),
                "top_p": float(top_p),
                "repeat_penalty": float(repeat_penalty),
                "stream": False,
            }
            if isinstance(stop_tokens, list):
                kwargs["stop"] = list(stop_tokens)
            result = model(prompt, **kwargs)
            raw_full = result["choices"][0].get("text", "")
            self._log_llm_io(call_name, prompt, raw_full)
            return str(raw_full or "")

        # Compact very long contexts for small models so they still produce output.
        n_ctx = int(self._n_ctx())
        context_char_budget = min(26000, max(7000, int(n_ctx * 2.8)))
        compact_context, was_compacted = _compact_context(context, context_char_budget)

        user_block = self._render_prompt_template(
            "glossary_user",
            {"context": compact_context, "max_terms": str(limit)},
        )
        prompt = (
            "<|system|>\n"
            f"{self._prompts['glossary_system']}\n"
            "<|user|>\n"
            f"{user_block}\n"
            "<|assistant|>\n"
        )
        max_out_tokens = max(220, min(1800, limit * 70))
        window_err = self._check_prompt_window(prompt, max_out_tokens)
        if window_err:
            if self._log:
                self._log.error("LLM", f"Glossary context too large: {window_err}")
            return [], {
                "applied": False,
                "reason": "context_too_large",
                "error": window_err,
            }

        try:
            raw_primary = _call_glossary(
                call_name="Glossary",
                prompt=prompt,
                stop_tokens=["<|"],
                temperature=0.2,
                top_p=0.9,
                repeat_penalty=1.05,
                max_tokens=max_out_tokens,
            )
            primary_entries, primary_parse_reason = _parse_glossary_output(raw_primary)
            if primary_entries:
                return primary_entries, {
                    "applied": True,
                    "reason": "ok",
                    "generated": len(primary_entries),
                    "parse": primary_parse_reason,
                    "retried": False,
                    "context_compacted": was_compacted,
                    "context_chars_used": len(compact_context),
                }

            if self._log:
                self._log.warning(
                    "LLM",
                    "Glossary primary parse empty/failed. Retrying with compact strict prompt.",
                )

            retry_context, retry_compacted = _compact_context(compact_context, 9000)
            retry_prompt = (
                "<|system|>\n"
                "Extrahiere ein Glossar aus dem Kontext.\n"
                "Antworte ausschließlich als gültiges JSON-Array.\n"
                "Jedes Element: {\"term\":\"...\",\"definition\":\"...\",\"aliases\":[\"...\"]}\n"
                "Keine Erklärungen, kein Markdown, kein zusätzlicher Text.\n"
                "<|user|>\n"
                f"Maximal {limit} Einträge.\n"
                "Nur Begriffe aus dem Kontext verwenden.\n"
                "Kontext:\n"
                f"{retry_context}\n"
                "<|assistant|>\n"
            )
            retry_window_err = self._check_prompt_window(retry_prompt, max_out_tokens)
            if retry_window_err:
                return [], {
                    "applied": False,
                    "reason": "context_too_large_retry",
                    "error": retry_window_err,
                    "parse": primary_parse_reason,
                    "retried": True,
                }

            raw_retry = _call_glossary(
                call_name="Glossary-Retry",
                prompt=retry_prompt,
                stop_tokens=None,
                temperature=0.1,
                top_p=0.85,
                repeat_penalty=1.0,
                max_tokens=max_out_tokens,
            )
            retry_entries, retry_parse_reason = _parse_glossary_output(raw_retry)
            if retry_entries:
                return retry_entries, {
                    "applied": True,
                    "reason": "ok_retry",
                    "generated": len(retry_entries),
                    "parse": retry_parse_reason,
                    "retried": True,
                    "context_compacted": bool(was_compacted or retry_compacted),
                    "context_chars_used": len(retry_context),
                }

            final_reason = (
                "empty"
                if (not str(raw_primary or "").strip() and not str(raw_retry or "").strip())
                else "parse_failed"
            )
            return [], {
                "applied": True,
                "reason": final_reason,
                "generated": 0,
                "retried": True,
                "parse": retry_parse_reason or primary_parse_reason,
                "raw_preview": str(raw_retry or raw_primary or "")[:320],
                "context_compacted": bool(was_compacted or retry_compacted),
                "context_chars_used": len(retry_context),
            }
        except Exception as exc:
            self._log_llm_io("Glossary", prompt, error=str(exc))
            if self._log:
                self._log.error("LLM", f"Glossary generation failed: {exc}")
            return [], {
                "applied": False,
                "reason": "exception",
                "error": str(exc),
            }

    def expand_query_sync(self, query: str) -> str:
        """Deprecated: generate a single hypothetical passage.

        Use ``expand_query_tfidf_sync`` or ``expand_query_st_sync`` instead.
        """
        passages = self.expand_query_st_sync(query, 1)
        return passages[0] if passages else query

    # ── Generation ────────────────────────────────────────────────────────────

    def send_message(
        self,
        user_message: str,
        file_contents: list[tuple[str, str]] | None = None,
        rag_results: list[tuple[str, float, str]] | None = None,
        selected_text: str = "",
        chat_history: list[tuple[str, str]] | None = None,
        max_tokens: int     = 1024,
        temperature: float  = 0.7,
        top_p: float        = 0.9,
        repeat_penalty: float = 1.1,
        forbidden_chars: str = "",
        selection_apply_mode: bool = False,
        grounding_required: bool = False,
        grounding_has_sources: bool = True,
        system_prompt_key: str = "chat_system",
    ) -> bool:
        if grounding_required and not grounding_has_sources:
            msg = (
                f"{GROUNDING_INSUFFICIENT_MESSAGE} "
                "Bitte zuerst RAG-Ergebnisse erzeugen und/oder Dokumente auswählen."
            )
            if self._log:
                self._log.warning("LLM", f"Generation abgelehnt: {msg}")
            self.error_occurred.emit(msg)
            return False

        system_prompt_text = str(
            self._prompts.get(system_prompt_key, self._system_prompt) or self._system_prompt
        )
        system_prompt_text = self._append_required_style_rules(system_prompt_text)

        prompt = self._build_prompt(
            user_message, file_contents, rag_results,
            selected_text, chat_history, selection_apply_mode,
            grounding_required, grounding_has_sources,
            system_prompt_text,
        )

        # Context-window check — must happen before handing off to the worker
        if self.is_model_loaded():
            err = self._check_context(
                prompt, user_message, file_contents, rag_results,
                selected_text, chat_history, max_tokens,
                system_prompt_text,
            )
            if err:
                if self._log:
                    self._log.error("LLM", err)
                self.error_occurred.emit(err)
                return False

        if self._log:
            self._log.info(
                "LLM",
                f"Generating  |  prompt: {len(prompt)} chars"
                f"  ({self._count_tokens(prompt)} tokens)"
                f"  max_tokens={max_tokens}  temp={temperature}  top_p={top_p}",
            )
            self._log.debug("LLM", f"Full prompt:\n{prompt}")

        self._gen_start   = time.perf_counter()
        self._token_count = 0
        self._forbidden_chars = self._parse_forbidden_chars(forbidden_chars)
        if self._log and self._forbidden_chars:
            self._log.debug(
                "LLM",
                f"Forbidden-character filter active ({len(self._forbidden_chars)} chars).",
            )
        self.is_generating.emit(True)
        self.worker.generate(
            prompt,
            max_tokens    = max_tokens,
            temperature   = temperature,
            top_p         = top_p,
            repeat_penalty = repeat_penalty,
            forbidden_chars = tuple(self._forbidden_chars),
        )
        return True

    def stop(self):
        if self._log:
            elapsed = time.perf_counter() - self._gen_start
            self._log.warning(
                "LLM",
                f"Generation stopped by user"
                f"  |  {self._token_count} tokens  |  {elapsed:.2f}s elapsed",
            )
        self.worker.request_stop()

    @staticmethod
    def _append_required_style_rules(system_prompt_text: str) -> str:
        base = (system_prompt_text or "").strip()
        if REQUIRED_STYLE_RULES in base:
            return base
        if not base:
            return REQUIRED_STYLE_RULES
        return f"{base}\n\n{REQUIRED_STYLE_RULES}"

    # ── Prompt builder ────────────────────────────────────────────────────────

    def _build_prompt(
        self,
        user_message: str,
        file_contents: list[tuple[str, str]] | None,
        rag_results: list[tuple[str, float, str]] | None,
        selected_text: str,
        chat_history: list[tuple[str, str]] | None,
        selection_apply_mode: bool,
        grounding_required: bool,
        grounding_has_sources: bool,
        system_prompt_text: str,
    ) -> str:
        parts: list[str] = []
        rewrite_instruction_block = ""
        prompt_file_contents = list(file_contents or [])
        selection_marked_in_canvas = False

        if selection_apply_mode and selected_text.strip() and prompt_file_contents:
            adjusted: list[tuple[str, str]] = []
            for name, content in prompt_file_contents:
                entry_name = str(name or "")
                entry_content = str(content or "")
                if (not selection_marked_in_canvas) and entry_name.startswith("Draft:"):
                    entry_content, applied = self._inject_canvas_target_markers(
                        entry_content,
                        selected_text,
                    )
                    selection_marked_in_canvas = (
                        selection_marked_in_canvas or applied
                    )
                adjusted.append((entry_name, entry_content))
            prompt_file_contents = adjusted

        parts.append(f"<|system|>\n{system_prompt_text}\n")

        if grounding_required:
            cite_rule = self._render_prompt_template(
                "chat_citation_rule_rewrite"
                if selection_apply_mode
                else "chat_citation_rule_answer"
            ).strip()
            grounding_block = self._render_prompt_template(
                "chat_grounding_rules",
                {
                    "insufficient_message": GROUNDING_INSUFFICIENT_MESSAGE,
                    "citation_rule": cite_rule,
                },
            ).strip()
            grounding_title = self._render_prompt_template(
                "chat_section_grounding_title"
            ).strip() or "### Verbindliche Dokument-Regeln ###"
            parts.append(
                f"\n{grounding_title}\n"
                + grounding_block
                + "\n"
            )

        if selection_apply_mode and selected_text.strip():
            grounding_note = (
                self._render_prompt_template("chat_grounding_note_rewrite").strip()
                if (grounding_required and grounding_has_sources) else ""
            )
            rewrite_enforcer = (
                "Rewrite-Pflicht (streng, auch für kleine Modelle):\n"
                "1) Die Nutzeranweisung hat höchste Priorität.\n"
                "2) Ersetze ausschließlich den Zielbereich.\n"
                "3) Weitere Draft-/Dokument-Kontexte sind nur Referenz "
                "(Stil, Konsistenz, Fakten).\n"
                "4) Gib NICHT den gesamten Draft zurück, außer der gesamte "
                "Draft ist tatsächlich der Zielbereich.\n"
                "5) Wenn eine Änderung verlangt ist (z. B. entfernen, ergänzen, "
                "umschreiben, kürzen), muss sich der ausgegebene Text inhaltlich "
                "ändern.\n"
                "6) Wenn der Auftrag Löschen/Entfernen/Streichen verlangt, dürfen "
                "diese Inhalte im Ergebnis nicht wieder auftauchen "
                "(auch nicht paraphrasiert).\n"
                "7) Vermeide allgemeine Floskeln; schreibe konkret zur Aufgabe.\n"
                "8) Behalte die Form des Zielbereichs standardmäßig bei "
                "(Liste bleibt Liste, Tabelle bleibt Tabelle, JSON bleibt JSON).\n"
                "9) Wenn der Nutzer ausdrücklich eine Format-Umwandlung verlangt "
                "(z. B. Stichpunkte -> Fließtext), dann führe genau diese "
                "Umwandlung aus.\n"
                "10) Wenn der Nutzer ein Ausgabeformat vorgibt, halte es exakt ein.\n"
            )
            if selection_marked_in_canvas:
                rewrite_enforcer += (
                    f"11) Im Draft-Kontext markiert {CANVAS_TARGET_START} den Anfang "
                    f"und {CANVAS_TARGET_END} das Ende des zu ersetzenden Abschnitts.\n"
                    f"12) Ersetze nur den Text zwischen {CANVAS_TARGET_START} und "
                    f"{CANVAS_TARGET_END}; Text außerhalb dieser Marker darf nicht "
                    "in der Antwort erscheinen.\n"
                )
            else:
                rewrite_enforcer += (
                    "11) Der zu ersetzende Abschnitt steht unter der Überschrift "
                    f"'{CANVAS_TARGET_SECTION_TITLE}'.\n"
                )
            rewrite_block = self._render_prompt_template(
                "chat_canvas_rewrite_rules",
                {
                    "canvas_open": CANVAS_REWRITE_OPEN,
                    "canvas_close": CANVAS_REWRITE_CLOSE,
                    "grounding_note": grounding_note,
                    "insufficient_message": GROUNDING_INSUFFICIENT_MESSAGE,
                },
            ).strip()
            if (
                not rewrite_block
                or CANVAS_REWRITE_OPEN not in rewrite_block
                or CANVAS_REWRITE_CLOSE not in rewrite_block
            ):
                rewrite_block = (
                    "Du bearbeitest den aktuell ausgewählten Draft-Text.\n"
                    "Gib NUR den finalen, vollständig editierten Ersatztext in "
                    "diesem exakten Wrapper zurück:\n"
                    f"{CANVAS_REWRITE_OPEN}\n"
                    "<hier der vollständige finale Text>\n"
                    f"{CANVAS_REWRITE_CLOSE}\n"
                    "Keine Erklärung, keine zusätzlichen Präfixe/Suffixe."
                )
            rewrite_title = self._render_prompt_template(
                "chat_section_rewrite_title"
            ).strip() or "### Ausgabeformat für Draft-Rewrite ###"
            rewrite_instruction_block = (
                f"\n{rewrite_title}\n"
                + rewrite_enforcer
                + rewrite_block
                + "\n"
            )
            parts.append(rewrite_instruction_block)

        has_context = (
            bool(prompt_file_contents)
            or bool(rag_results)
            or bool(selected_text and selected_text.strip())
        )
        if has_context:
            context_title = self._render_prompt_template(
                "chat_section_context_title"
            ).strip() or "### Kontext ###"
            parts.append(f"\n{context_title}\n")

            if prompt_file_contents:
                files_title = self._render_prompt_template(
                    "chat_section_files_title"
                ).strip() or "## Angehängte Dokumente"
                parts.append(f"{files_title}\n")
                for name, content in prompt_file_contents:
                    parts.append(f"### {name}\n```\n{content}\n```\n")

            if rag_results:
                rag_title = self._render_prompt_template(
                    "chat_section_rag_title"
                ).strip() or "## Relevante Auszüge (Wissensbasis)"
                parts.append(f"{rag_title}\n")
                for path, score, excerpt in rag_results:
                    basename = os.path.basename(path)
                    parts.append(
                        f"**{basename}** (score {score:.2f})\n{excerpt}\n"
                    )

            if selected_text and selected_text.strip():
                if selection_apply_mode and selection_marked_in_canvas:
                    selected_title = ""
                elif selection_apply_mode:
                    selected_title = CANVAS_TARGET_SECTION_TITLE
                else:
                    selected_title = self._render_prompt_template(
                        "chat_section_selected_title"
                    ).strip() or CANVAS_TARGET_SECTION_TITLE
                if selected_title:
                    parts.append(
                        f"{selected_title}\n```\n{selected_text}\n```\n"
                    )

            context_end = self._render_prompt_template(
                "chat_section_context_end"
            ).strip() or "### Ende Kontext ###"
            parts.append(f"{context_end}\n")
            if rewrite_instruction_block:
                parts.append(
                    f"\n{POST_CONTEXT_REWRITE_TITLE}\n"
                    + rewrite_instruction_block.lstrip()
                )

        for role, content in (chat_history or []):
            parts.append(f"\n<|{role}|>\n{content}")

        parts.append(f"\n<|user|>\n{user_message}")
        parts.append("\n<|assistant|>\n")

        return "".join(parts)

    @staticmethod
    def _inject_canvas_target_markers(
        draft_text: str,
        selected_text: str,
    ) -> tuple[str, bool]:
        source = str(draft_text or "")
        selected = str(selected_text or "")
        if not source or not selected.strip():
            return source, False
        start = source.find(selected)
        if start < 0:
            return source, False
        end = start + len(selected)
        marked = (
            source[:start]
            + f"{CANVAS_TARGET_START}\n"
            + selected
            + f"\n{CANVAS_TARGET_END}"
            + source[end:]
        )
        return marked, True

    # ── Context-window guard ───────────────────────────────────────────────────

    def _n_ctx(self) -> int:
        """Return the model's configured context window size."""
        return self.worker._load_params.get("n_ctx", 4096)

    def _count_tokens(self, text: str) -> int:
        """Count tokens via the model's tokenizer; falls back to len/4."""
        model = self.worker._model
        if model is None:
            return len(text) // 4
        try:
            return len(model.tokenize(text.encode("utf-8", errors="replace")))
        except Exception:
            return len(text) // 4

    def _check_context(
        self,
        prompt: str,
        user_message: str,
        file_contents: list[tuple[str, str]] | None,
        rag_results: list[tuple[str, float, str]] | None,
        selected_text: str,
        chat_history: list[tuple[str, str]] | None,
        max_tokens: int,
        system_prompt_text: str,
    ) -> str:
        """Return a detailed error string if the context exceeds n_ctx, else ''."""
        n_ctx         = self._n_ctx()
        prompt_tokens = self._count_tokens(prompt)

        if prompt_tokens + max_tokens <= n_ctx:
            return ""

        # Build per-component breakdown
        def tok(text: str) -> int:
            return self._count_tokens(text)

        breakdown: list[tuple[str, int]] = []

        breakdown.append((
            "System-Prompt",
            tok(f"<|system|>\n{system_prompt_text}\n"),
        ))

        if file_contents:
            files_title = self._render_prompt_template(
                "chat_section_files_title"
            ).strip() or "## Angehängte Dokumente"
            fc_text = files_title + "\n" + "".join(
                f"### {name}\n```\n{content}\n```\n"
                for name, content in file_contents
            )
            breakdown.append((f"Dateien ({len(file_contents)})", tok(fc_text)))

        if rag_results:
            rag_title = self._render_prompt_template(
                "chat_section_rag_title"
            ).strip() or "## Relevante Auszüge (Wissensbasis)"
            rag_text = rag_title + "\n" + "".join(
                f"**{os.path.basename(path)}** (score {score:.2f})\n{excerpt}\n"
                for path, score, excerpt in rag_results
            )
            breakdown.append((f"RAG-Ergebnisse ({len(rag_results)})", tok(rag_text)))

        if selected_text and selected_text.strip():
            selected_title = self._render_prompt_template(
                "chat_section_selected_title"
            ).strip() or CANVAS_TARGET_SECTION_TITLE
            breakdown.append((
                "Ausgewählter Text",
                tok(f"{selected_title}\n```\n{selected_text}\n```\n"),
            ))

        if chat_history:
            hist_text = "".join(
                f"\n<|{role}|>\n{content}" for role, content in chat_history
            )
            breakdown.append((
                f"Chat-Verlauf ({len(chat_history)} Nachr.)",
                tok(hist_text),
            ))

        breakdown.append((
            "Nutzeranfrage",
            tok(f"\n<|user|>\n{user_message}\n<|assistant|>\n"),
        ))

        # Format the error message
        pad = max(len(label) for label, _ in breakdown)
        sep = "─" * (pad + 12)

        lines = ["Kontext zu groß – Nachricht nicht gesendet.", ""]
        lines.append("Token-Aufschlüsselung:")
        for label, n in breakdown:
            lines.append(f"  {label:<{pad}}  {n:>7} Tokens")

        overhead = prompt_tokens - sum(n for _, n in breakdown)
        if overhead > 0:
            lines.append(f"  {'Struktur-Overhead':<{pad}}  {overhead:>7} Tokens")

        lines.append(f"  {sep}")
        lines.append(f"  {'Prompt gesamt':<{pad}}  {prompt_tokens:>7} Tokens")
        lines.append(f"  {'Reserviert (Antwort)':<{pad}}  {max_tokens:>7} Tokens")
        lines.append(f"  {sep}")
        lines.append(f"  {'Benötigt':<{pad}}  {prompt_tokens + max_tokens:>7} Tokens")
        lines.append(f"  {'Maximal (n_ctx)':<{pad}}  {n_ctx:>7} Tokens")
        lines.append(f"  {'Überschreitung':<{pad}}  {prompt_tokens + max_tokens - n_ctx:>7} Tokens")

        return "\n".join(lines)

    def _check_prompt_window(self, prompt: str, max_tokens: int) -> str:
        """
        Return an error when prompt+output would exceed the model n_ctx window.

        Used by synchronous helper calls that don't go through send_message().
        """
        n_ctx = self._n_ctx()
        prompt_tokens = self._count_tokens(prompt)
        needed = int(prompt_tokens) + int(max_tokens)
        if needed <= n_ctx:
            return ""
        return (
            "Kontext zu groß für das aktuelle Modellfenster.\n"
            f"Prompt: {prompt_tokens} Tokens\n"
            f"Reserviert (Antwort): {int(max_tokens)} Tokens\n"
            f"Benötigt: {needed} Tokens\n"
            f"Maximal (n_ctx): {n_ctx} Tokens\n"
            f"Überschreitung: {needed - n_ctx} Tokens"
        )

    @classmethod
    def _decode_forbidden_token(cls, raw: str) -> str:
        token = raw.strip()
        if not token:
            return ""

        if len(token) >= 2 and token[0] == token[-1] and token[0] in ("'", '"'):
            token = token[1:-1]

        alias = cls._FORBIDDEN_CHAR_ALIASES.get(token.casefold())
        if alias is not None:
            return alias

        m = re.fullmatch(r"(?:u\+|\\u)([0-9a-fA-F]{4,6})", token)
        if m:
            try:
                return chr(int(m.group(1), 16))
            except ValueError:
                return ""

        m = re.fullmatch(r"(?:0x|\\x)([0-9a-fA-F]{2,6})", token)
        if m:
            try:
                return chr(int(m.group(1), 16))
            except ValueError:
                return ""

        if "\\" in token:
            try:
                token = bytes(token, "utf-8").decode("unicode_escape")
            except Exception:
                pass

        return token

    @classmethod
    def _parse_forbidden_chars(cls, spec: str) -> set[str]:
        chars: set[str] = set()
        for raw in re.split(r"[,\n]+", spec or ""):
            decoded = cls._decode_forbidden_token(raw)
            if not decoded:
                continue
            for ch in decoded:
                chars.add(ch)
        return chars

    def _apply_forbidden_filter(self, text: str) -> str:
        if not text or not self._forbidden_chars:
            return text
        return "".join(ch for ch in text if ch not in self._forbidden_chars)

    # ── Worker signal interceptors ─────────────────────────────────────────────

    def _on_token(self, token: str):
        self._token_count += 1
        filtered = self._apply_forbidden_filter(token)
        if filtered:
            self.token_received.emit(filtered)

    def _on_complete(self, response: str):
        filtered_response = self._apply_forbidden_filter(response)
        elapsed = time.perf_counter() - self._gen_start
        if self._log:
            removed_chars = max(0, len(response) - len(filtered_response))
            tok_s = self._token_count / elapsed if elapsed > 0 else 0.0
            self._log.info(
                "LLM",
                f"Generation complete"
                f"  |  {self._token_count} tokens"
                f"  |  {elapsed:.2f}s"
                f"  |  {tok_s:.1f} tok/s",
            )
            if removed_chars > 0:
                self._log.info("LLM", f"Removed {removed_chars} forbidden characters.")
            self._log.debug("LLM", f"Full response:\n{filtered_response}")
        self.is_generating.emit(False)
        self.generation_complete.emit(filtered_response)

    def _on_error(self, message: str):
        if self._log:
            self._log.error("LLM", f"Error: {message}")
        self.error_occurred.emit(message)

    def _on_model_loaded(self, success: bool, message: str):
        if self._log:
            if success:
                self._log.info("LLM", f"Model ready: {message}")
            else:
                self._log.error("LLM", f"Model load failed: {message}")
        self.model_loaded.emit(success, message)

    def _on_nli_model_loaded(self, success: bool, message: str):
        self._nli_last_error = "" if success else str(message or "")
        if self._log:
            if success:
                self._log.info("NLI", f"Model ready: {message}")
            else:
                self._log.error("NLI", f"Model load failed: {message}")
        self.nli_model_loaded.emit(success, message)
