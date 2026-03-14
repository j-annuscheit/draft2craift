"""
LLM Manager
===========
Two classes:

  LLMWorker  – QThread that owns the active backend instance.
               Emits streamed tokens via signals.

  LLMManager – High-level QObject that builds context-aware prompts,
               tracks generation timing, and exposes a clean API to
               the rest of the app.  Accepts an optional AppLogger
               for detailed debug output.
"""
from __future__ import annotations

from collections import OrderedDict
import functools
import os
import re
import time
from typing import Any

from PySide6.QtCore import QObject, Signal
from shared.services.llm.backends import BACKEND_AUTO
from shared.services.llm.nli import NLIBackend
from shared.services.llm.prompts import (
    DEFAULT_PROMPTS_FILE,
    PROMPT_KEYS as LLM_PROMPT_KEYS,
    PromptTemplateRegistry,
)
from shared.services.llm.markdown_fix_tasks import (
    fix_markdown_chunk_sync as _fix_markdown_chunk_sync,
)
from shared.services.llm.query_tasks import (
    expand_query_literal_terms_sync as _expand_query_literal_terms_sync,
    expand_query_st_sync as _expand_query_st_sync,
    expand_query_tfidf_sync as _expand_query_tfidf_sync,
)
from shared.services.llm.rerank_tasks import (
    rerank_rag_results_sync as _rerank_rag_results_sync,
)
from shared.services.llm.mindmap_chunk_tasks import (
    _chunk_leaf_label as _chunk_leaf_label_fn,
    _generate_chunk_mindmap_sync as _generate_chunk_mindmap_sync_fn,
    _normalize_mindmap_mode as _normalize_mindmap_mode_fn,
    _slug_node_id as _slug_node_id_fn,
)
from shared.services.llm.mindmap_generate_tasks import (
    generate_mindmap_sync as _generate_mindmap_sync_fn,
)
from shared.services.llm.glossary_tasks import (
    expand_query_sync as _expand_query_sync_fn,
    generate_glossary_sync as _generate_glossary_sync_fn,
)
from shared.services.llm.chat_prompt_flow import (
    _append_required_style_rules as _append_required_style_rules_fn,
    _build_prompt as _build_prompt_fn,
    _inject_canvas_target_markers as _inject_canvas_target_markers_fn,
    send_message as _send_message_fn,
    stop as _stop_fn,
)
from shared.services.llm.chat_context_runtime import (
    _apply_forbidden_filter as _apply_forbidden_filter_fn,
    _check_context as _check_context_fn,
    _check_prompt_window as _check_prompt_window_fn,
    _count_tokens as _count_tokens_fn,
    _decode_forbidden_token as _decode_forbidden_token_fn,
    _n_ctx as _n_ctx_fn,
    _on_complete as _on_complete_fn,
    _on_error as _on_error_fn,
    _on_model_loaded as _on_model_loaded_fn,
    _on_nli_model_loaded as _on_nli_model_loaded_fn,
    _on_token as _on_token_fn,
    _parse_forbidden_chars as _parse_forbidden_chars_fn,
)
from shared.services.llm.worker import LLMWorker

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
_TAGGED_PAYLOAD_TEMPLATE = r"<{tag}>\s*([\s\S]*?)\s*</{tag}>"


@functools.lru_cache(maxsize=64)
def _tagged_payload_regex(tag_name: str) -> re.Pattern[str]:
    escaped = re.escape(tag_name)
    return re.compile(
        _TAGGED_PAYLOAD_TEMPLATE.format(tag=escaped),
        flags=re.IGNORECASE,
    )


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
    PROMPT_KEYS: tuple[str, ...] = LLM_PROMPT_KEYS
    PROMPT_DEFAULTS_FILE = DEFAULT_PROMPTS_FILE
    _QUERY_CACHE_MISS = object()
    _QUERY_CACHE_MAX = 128

    def __init__(self, logger: Any = None, parent: QObject | None = None):
        super().__init__(parent)
        self._log    = logger
        self.worker  = LLMWorker()
        self._nli_backend = NLIBackend(
            logger=self._log,
            prompt_renderer=self._render_prompt_template,
            io_logger=self._log_llm_io,
        )
        self._prompt_registry = PromptTemplateRegistry(
            logger=self._log,
            defaults_file=self.PROMPT_DEFAULTS_FILE,
        )
        self._prompt_defaults: dict[str, str] = self._prompt_registry.defaults
        self._prompts: dict[str, str] = self._prompt_registry.prompts
        self._system_prompt = self._prompts["chat_system"]
        self._query_expansion_cache: dict[str, OrderedDict[Any, Any]] = {
            "tfidf": OrderedDict(),
            "st": OrderedDict(),
            "literal": OrderedDict(),
        }
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
        flash_attn: bool = True,
        backend: str = BACKEND_AUTO,
    ):
        self._clear_query_expansion_cache()
        if self._log:
            basename = os.path.basename(path)
            threads  = n_threads or (os.cpu_count() or 4)
            self._log.info(
                "LLM",
                f"Loading model: {basename}"
                f"  |  n_ctx={n_ctx}  gpu_layers={n_gpu_layers}"
                f"  threads={threads}  flash_attn={bool(flash_attn)}"
                f"  backend={str(backend or BACKEND_AUTO)}",
            )
        self.worker.load_model(
            path,
            n_ctx=n_ctx,
            n_gpu_layers=n_gpu_layers,
            n_threads=n_threads,
            flash_attn=flash_attn,
            backend=str(backend or BACKEND_AUTO),
        )

    def is_model_loaded(self) -> bool:
        return bool(self.worker.is_model_loaded())

    def current_backend(self) -> str:
        return str(self.worker.backend_name() or "")

    def context_window(self) -> int:
        return int(self.worker.context_window(4096))

    def load_nli_model(
        self,
        model_id: str,
        n_ctx: int = 2048,
        n_gpu_layers: int = 0,
        n_threads: int = 0,
    ):
        _ = n_ctx, n_gpu_layers
        success, message = self._nli_backend.load_model(model_id, n_threads=n_threads)
        self._on_nli_model_loaded(success, message)

    def is_nli_model_loaded(self) -> bool:
        return self._nli_backend.is_loaded()

    def verify_nli_sync(self, premise: str, hypothesis: str) -> dict[str, Any]:
        return self._nli_backend.verify_sync(premise, hypothesis)

    def set_system_prompt(self, text: str):
        self._system_prompt = self._prompt_registry.set_system_prompt(text)

    def get_prompt_set(self) -> dict[str, str]:
        """Return all configurable prompt templates (system + user blocks)."""
        return self._prompt_registry.get_prompt_set()

    def get_prompt_defaults(self) -> dict[str, str]:
        """Return default prompt templates (immutable copy)."""
        return self._prompt_registry.get_prompt_defaults()

    def set_prompt_set(self, prompts: dict[str, str]):
        """Apply multiple prompt values (unknown keys are ignored)."""
        self._prompt_registry.set_prompt_set(prompts)
        self._system_prompt = self._prompts["chat_system"]
        self._clear_query_expansion_cache()

    def _query_cache_get(self, cache_name: str, key: Any) -> Any:
        bucket = self._query_expansion_cache.get(str(cache_name or ""))
        if bucket is None:
            return self._QUERY_CACHE_MISS
        if key not in bucket:
            return self._QUERY_CACHE_MISS
        value = bucket.pop(key)
        bucket[key] = value
        return value

    def _query_cache_set(self, cache_name: str, key: Any, value: Any) -> None:
        name = str(cache_name or "")
        bucket = self._query_expansion_cache.get(name)
        if bucket is None:
            bucket = OrderedDict()
            self._query_expansion_cache[name] = bucket
        if key in bucket:
            bucket.pop(key, None)
        bucket[key] = value
        while len(bucket) > int(self._QUERY_CACHE_MAX):
            bucket.popitem(last=False)

    def _clear_query_expansion_cache(self) -> None:
        for bucket in self._query_expansion_cache.values():
            bucket.clear()

    def _render_prompt_template(
        self,
        key: str,
        replacements: dict[str, str] | None = None,
    ) -> str:
        """Render editable prompt templates with {placeholder} substitution."""
        return self._prompt_registry.render(key, replacements)

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

    def _generate_backend_text(
        self,
        prompt: str,
        *,
        max_tokens: int,
        temperature: float,
        top_p: float,
        repeat_penalty: float,
        stop_tokens: list[str] | None = None,
    ) -> str:
        return self.worker.run_completion_sync(
            prompt,
            max_tokens=int(max_tokens),
            temperature=float(temperature),
            top_p=float(top_p),
            repeat_penalty=float(repeat_penalty),
            stop=list(stop_tokens or ["<|"]),
            forbidden_chars=tuple(self._forbidden_chars),
        )

    def _stream_backend_text(
        self,
        prompt: str,
        *,
        max_tokens: int,
        temperature: float,
        top_p: float,
        repeat_penalty: float,
        stop_tokens: list[str] | None = None,
        stop_requested=None,
    ):
        return self.worker.iter_completion_sync(
            prompt,
            max_tokens=int(max_tokens),
            temperature=float(temperature),
            top_p=float(top_p),
            repeat_penalty=float(repeat_penalty),
            stop=list(stop_tokens or ["<|"]),
            forbidden_chars=tuple(self._forbidden_chars),
            stop_requested=stop_requested,
        )

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
        m = _tagged_payload_regex(tag_name).search(raw)
        if m:
            return str(m.group(1) or "").strip(), True
        return raw.strip(), False

    # Delegated sync task methods (split out of manager.py).
    fix_markdown_chunk_sync = _fix_markdown_chunk_sync
    expand_query_tfidf_sync = _expand_query_tfidf_sync
    expand_query_st_sync = _expand_query_st_sync
    expand_query_literal_terms_sync = _expand_query_literal_terms_sync
    rerank_rag_results_sync = _rerank_rag_results_sync
    _normalize_mindmap_mode = staticmethod(_normalize_mindmap_mode_fn)
    _slug_node_id = staticmethod(_slug_node_id_fn)
    _chunk_leaf_label = staticmethod(_chunk_leaf_label_fn)
    _generate_chunk_mindmap_sync = _generate_chunk_mindmap_sync_fn
    generate_mindmap_sync = _generate_mindmap_sync_fn
    generate_glossary_sync = _generate_glossary_sync_fn
    expand_query_sync = _expand_query_sync_fn
    send_message = _send_message_fn
    stop = _stop_fn
    _append_required_style_rules = staticmethod(_append_required_style_rules_fn)
    _build_prompt = _build_prompt_fn
    _inject_canvas_target_markers = staticmethod(_inject_canvas_target_markers_fn)
    _n_ctx = _n_ctx_fn
    _count_tokens = _count_tokens_fn
    _check_context = _check_context_fn
    _check_prompt_window = _check_prompt_window_fn
    _decode_forbidden_token = classmethod(_decode_forbidden_token_fn)
    _parse_forbidden_chars = classmethod(_parse_forbidden_chars_fn)
    _apply_forbidden_filter = _apply_forbidden_filter_fn
    _on_token = _on_token_fn
    _on_complete = _on_complete_fn
    _on_error = _on_error_fn
    _on_model_loaded = _on_model_loaded_fn
    _on_nli_model_loaded = _on_nli_model_loaded_fn
