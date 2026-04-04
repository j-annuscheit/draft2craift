"""Modern LLM manager using LiteLLM + llama.cpp with Jinja2 prompts."""
from __future__ import annotations

from collections.abc import Callable, Mapping
import json
import re
import threading
from typing import Any

from PySide6.QtCore import QObject, Signal

from shared.services.llm.prompts import (
    DEFAULT_PROMPTS_FILE,
    PROMPT_KEYS as LLM_PROMPT_KEYS,
    PromptTemplateStore,
)
from shared.services.project.project_variables import resolve_project_variables_text
from shared.services.llm.worker import LLMWorker

CANVAS_REWRITE_OPEN = "[[CANVAS_REWRITE]]"
CANVAS_REWRITE_CLOSE = "[[/CANVAS_REWRITE]]"
GROUNDING_INSUFFICIENT_MESSAGE = (
    "Nicht genug Informationen in den ausgewaehlten Dokumenten/RAG-Quellen."
)
REQUIRED_STYLE_RULES = (
    "Verbindliche Stilregel:\n"
    "- Verwende keinen Gedankenstrich als Satzzeichen.\n"
    "- Nutze stattdessen Komma, Punkt oder Doppelpunkt.\n"
    "- Bindestriche in Woertern sind erlaubt."
)
_WORD_RE = re.compile(r"\w+", flags=re.UNICODE)
_FENCED_JSON_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", flags=re.IGNORECASE)
_JSON_OBJECT_RE = re.compile(r"\{[\s\S]*\}")
_JSON_ARRAY_RE = re.compile(r"\[[\s\S]*\]")


class LLMManager(QObject):
    """UI-facing LLM facade. Public API is kept stable, internals are clean-slate."""

    token_received = Signal(str)
    thinking_received = Signal(str)
    generation_complete = Signal(str)
    error_occurred = Signal(str)
    model_loaded = Signal(bool, str)
    nli_model_loaded = Signal(bool, str)
    is_generating = Signal(bool)

    PROMPT_KEYS: tuple[str, ...] = LLM_PROMPT_KEYS
    PROMPT_DEFAULTS_FILE = DEFAULT_PROMPTS_FILE

    def __init__(
        self,
        logger: Any = None,
        parent: QObject | None = None,
        project_variables_getter: Callable[[], Mapping[str, object]] | None = None,
        plugin_manager: Any = None,
    ) -> None:
        super().__init__(parent)
        self._log = logger
        self.worker = LLMWorker()
        self._plugin_manager = plugin_manager
        self._project_variables_getter = project_variables_getter
        self._prompt_store = PromptTemplateStore(
            logger=self._log,
            defaults_file=self.PROMPT_DEFAULTS_FILE,
        )
        self._prompt_defaults: dict[str, str] = self._prompt_store.defaults
        self._prompts: dict[str, str] = self._prompt_store.prompts
        self._system_prompt = self._prompts.get("chat_system", "")
        self._forbidden_chars: set[str] = set()
        self._nli_loaded = False
        self._nli_model_id = ""
        self._last_think_text = ""

    def load_model(
        self,
        path: str,
        n_ctx: int = 4096,
        n_gpu_layers: int = 0,
        n_threads: int = 0,
        flash_attn: bool = True,
        trust_remote_code: bool = False,
        backend: str = "auto",
    ) -> None:
        ok, message = self.worker.load_model(
            str(path or ""),
            n_ctx=n_ctx,
            n_gpu_layers=n_gpu_layers,
            n_threads=n_threads,
            flash_attn=flash_attn,
            trust_remote_code=trust_remote_code,
            backend=backend,
        )
        self.model_loaded.emit(bool(ok), str(message or ""))

    def is_model_loaded(self) -> bool:
        return bool(self.worker.is_model_loaded())

    def current_backend(self) -> str:
        return str(self.worker.backend_name() or "")

    def context_window(self) -> int:
        return int(self.worker.context_window(4096))

    def last_think_text(self) -> str:
        return str(self._last_think_text or "")

    def load_nli_model(
        self,
        model_id: str,
        n_ctx: int = 2048,
        n_gpu_layers: int = 0,
        n_threads: int = 0,
    ) -> None:
        _ = n_ctx, n_gpu_layers, n_threads
        text = str(model_id or "").strip()
        self._nli_loaded = bool(text)
        self._nli_model_id = text
        self.nli_model_loaded.emit(self._nli_loaded, f"NLI model: {text or 'none'}")

    def is_nli_model_loaded(self) -> bool:
        return bool(self._nli_loaded)

    def verify_nli_sync(self, premise: str, hypothesis: str) -> dict[str, Any]:
        p_tokens = self._token_set(str(premise or ""))
        h_tokens = self._token_set(str(hypothesis or ""))
        if not h_tokens:
            return {"label": "neutral", "score": 0.0}
        overlap = len(p_tokens & h_tokens) / max(1, len(h_tokens))
        if overlap >= 0.82:
            return {"label": "entailment", "score": round(overlap, 4)}
        if overlap <= 0.15:
            return {"label": "contradiction", "score": round(1.0 - overlap, 4)}
        return {"label": "neutral", "score": round(overlap, 4)}

    def set_system_prompt(self, text: str) -> None:
        self._system_prompt = self._prompt_store.set_system_prompt(text)

    def get_prompt_set(self) -> dict[str, str]:
        return self._prompt_store.get_prompt_set()

    def get_prompt_defaults(self) -> dict[str, str]:
        return self._prompt_store.get_prompt_defaults()

    def set_prompt_set(self, prompts: dict[str, str]) -> None:
        self._prompt_store.set_prompt_set(prompts)
        self._prompts = self._prompt_store.prompts
        self._system_prompt = self._prompts.get("chat_system", self._system_prompt)

    def render_prompt_template(
        self,
        key: str,
        replacements: dict[str, str] | None = None,
    ) -> str:
        rendered = self._prompt_store.render(key, replacements)
        variables = self._resolve_project_variables()
        if not variables:
            return rendered
        return resolve_project_variables_text(rendered, variables).text

    def set_project_variables_getter(
        self,
        getter: Callable[[], Mapping[str, object]] | None,
    ) -> None:
        self._project_variables_getter = getter

    def send_message(
        self,
        user_message: str,
        file_contents: list[tuple[str, str]] | None = None,
        rag_results: list[tuple[str, float, str]] | None = None,
        selected_text: str = "",
        chat_history: list[tuple[str, str]] | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        top_p: float = 0.9,
        repeat_penalty: float = 1.1,
        forbidden_chars: str = "",
        selection_apply_mode: bool = False,
        grounding_required: bool = False,
        grounding_has_sources: bool = True,
        system_prompt_key: str = "chat_system",
    ) -> bool:
        if not self.is_model_loaded():
            self.error_occurred.emit("No model loaded.")
            return False
        if self.worker.isRunning():
            self.error_occurred.emit("Model is busy.")
            return False
        if grounding_required and not grounding_has_sources:
            self.error_occurred.emit(
                f"{GROUNDING_INSUFFICIENT_MESSAGE} Bitte zuerst Quellen aktivieren."
            )
            return False

        self._forbidden_chars = self._parse_forbidden_chars(forbidden_chars)
        prompt = self._build_prompt(
            user_message=str(user_message or ""),
            file_contents=list(file_contents or []),
            rag_results=list(rag_results or []),
            selected_text=str(selected_text or ""),
            chat_history=list(chat_history or []),
            selection_apply_mode=bool(selection_apply_mode),
            grounding_required=bool(grounding_required),
            grounding_has_sources=bool(grounding_has_sources),
            system_prompt_key=str(system_prompt_key or "chat_system"),
        )
        self.is_generating.emit(True)

        def _run() -> None:
            full = ""
            try:
                for token in self.worker.iter_completion_sync(
                    prompt,
                    max_tokens=max(1, int(max_tokens or 1)),
                    temperature=float(temperature),
                    top_p=float(top_p),
                    repeat_penalty=float(repeat_penalty),
                    stop=["<|"],
                    forbidden_chars=tuple(self._forbidden_chars),
                    stop_requested=lambda: False,
                ):
                    full += str(token or "")
                    self.token_received.emit(str(token or ""))
                if self._plugin_manager is not None:
                    payload = self._plugin_manager.run_hook(
                        "llm.after_generate",
                        {"text": full, "mode": "chat"},
                    )
                    full = str(payload.get("text", full) or full)
                self.generation_complete.emit(full)
            except Exception as exc:
                self.error_occurred.emit(f"Generation error: {exc}")
            finally:
                self.is_generating.emit(False)

        threading.Thread(target=_run, daemon=True).start()
        return True

    def stop(self) -> None:
        self.worker.request_stop()

    def generate_glossary_sync(
        self,
        *,
        context_text: str,
        max_terms: int = 32,
        focus_query: str = "",
    ) -> tuple[list[dict[str, object]], dict[str, object]]:
        prompt = self.render_prompt_template(
            "glossary_user",
            {
                "query": str(focus_query or ""),
                "max_terms": str(max(1, int(max_terms or 32))),
                "context_text": str(context_text or ""),
            },
        )
        raw = self._generate_backend_text(
            f"{self._prompts.get('glossary_system', '')}\n\n{prompt}",
            max_tokens=900,
            temperature=0.2,
        )
        rows = self._parse_glossary_rows(raw)
        return rows, {"reason": "litellm", "count": len(rows)}

    def generate_mindmap_sync(
        self,
        *,
        context_text: str,
        query: str,
        mode: str = "mindmap",
        max_nodes: int = 32,
        chunking_strategy: str = "sliding_window",
        chunk_size: int = 900,
        chunk_overlap: int = 160,
        max_output_tokens: int = 1600,
        temperature: float = 0.3,
    ) -> tuple[str, dict[str, object]]:
        _ = chunking_strategy, chunk_size, chunk_overlap
        prompt_key = "graph_user" if str(mode or "").strip().casefold() == "graph" else "mindmap_user"
        system_key = "graph_system" if str(mode or "").strip().casefold() == "graph" else "mindmap_system"
        user_prompt = self.render_prompt_template(
            prompt_key,
            {
                "query": str(query or ""),
                "max_nodes": str(max(4, int(max_nodes or 32))),
                "context_text": str(context_text or ""),
            },
        )
        markdown = self._generate_backend_text(
            f"{self._prompts.get(system_key, '')}\n\n{user_prompt}",
            max_tokens=max(128, min(4096, int(max_output_tokens or 1600))),
            temperature=max(0.0, min(1.2, float(temperature))),
        )
        return str(markdown or "").strip(), {
            "reason": "litellm",
            "mode": str(mode or "mindmap"),
        }

    def shutdown(self, stop_timeout_ms: int = 3000, terminate_timeout_ms: int = 2000) -> bool:
        _ = stop_timeout_ms, terminate_timeout_ms
        return bool(self.worker.shutdown())

    def _build_prompt(
        self,
        *,
        user_message: str,
        file_contents: list[tuple[str, str]],
        rag_results: list[tuple[str, float, str]],
        selected_text: str,
        chat_history: list[tuple[str, str]],
        selection_apply_mode: bool,
        grounding_required: bool,
        grounding_has_sources: bool,
        system_prompt_key: str,
        system_prompt_text: str = "",
    ) -> str:
        system_prompt = str(system_prompt_text or "").strip()
        if not system_prompt:
            system_prompt = str(
                self._prompts.get(system_prompt_key, self._system_prompt)
                or self._system_prompt
            ).strip()
        if REQUIRED_STYLE_RULES not in system_prompt:
            system_prompt = f"{system_prompt}\n\n{REQUIRED_STYLE_RULES}".strip()

        parts: list[str] = [f"<|system|>\n{system_prompt}\n"]
        if grounding_required:
            parts.append(
                "\n### Grounding ###\n"
                f"Required: yes\nSources available: {'yes' if grounding_has_sources else 'no'}\n"
                f"Fallback message: {GROUNDING_INSUFFICIENT_MESSAGE}\n"
            )
        if file_contents:
            parts.append("\n### Files ###\n")
            for name, content in file_contents:
                parts.append(f"[{name}]\n{content}\n")
        if rag_results:
            parts.append("\n### RAG ###\n")
            for path, score, excerpt in rag_results:
                parts.append(f"[{path}] score={score}\n{excerpt}\n")
        if selected_text.strip():
            parts.append("\n### Selected Text ###\n")
            parts.append(f"{selected_text}\n")
        if chat_history:
            parts.append("\n### History ###\n")
            for role, text in chat_history[-10:]:
                parts.append(f"{role}: {text}\n")
        if selection_apply_mode:
            parts.append(
                "\n### Rewrite Mode ###\n"
                f"Return only rewritten content inside:\n{CANVAS_REWRITE_OPEN}\n...\n{CANVAS_REWRITE_CLOSE}\n"
            )
        parts.append(f"\n<|user|>\n{user_message}\n<|assistant|>\n")
        prompt = "".join(parts)
        if self._plugin_manager is not None:
            payload = self._plugin_manager.run_hook(
                "llm.before_generate",
                {"prompt": prompt, "mode": "chat"},
            )
            prompt = str(payload.get("prompt", prompt) or prompt)
        variables = self._resolve_project_variables()
        if variables:
            prompt = resolve_project_variables_text(prompt, variables).text
        return prompt

    def _resolve_project_variables(self) -> dict[str, str]:
        getter = self._project_variables_getter
        if not callable(getter):
            return {}
        try:
            resolved = getter()
        except Exception:
            return {}
        if not isinstance(resolved, Mapping):
            return {}
        out: dict[str, str] = {}
        for key, value in resolved.items():
            name = str(key or "").strip()
            if not name:
                continue
            out[name] = str(value or "")
        return out

    def _generate_backend_text(
        self,
        prompt: str,
        *,
        max_tokens: int = 512,
        temperature: float = 0.2,
        top_p: float = 0.9,
        repeat_penalty: float = 1.05,
    ) -> str:
        if not self.is_model_loaded():
            return ""
        return str(
            self.worker.run_completion_sync(
                str(prompt or ""),
                max_tokens=max(1, int(max_tokens or 1)),
                temperature=float(temperature),
                top_p=float(top_p),
                repeat_penalty=float(repeat_penalty),
                stop=["<|"],
                forbidden_chars=tuple(self._forbidden_chars),
            )
            or ""
        )

    @staticmethod
    def _parse_forbidden_chars(raw: str) -> set[str]:
        text = str(raw or "").strip()
        if not text:
            return set()
        out: set[str] = set()
        for token in re.split(r"[\s,;]+", text):
            item = str(token or "").strip()
            if not item:
                continue
            out.add(item)
        return out

    @staticmethod
    def _token_set(text: str) -> set[str]:
        return {tok for tok in _WORD_RE.findall(str(text or "").casefold()) if len(tok) >= 3}

    @staticmethod
    def _parse_glossary_rows(raw: str) -> list[dict[str, object]]:
        text = str(raw or "").strip()
        if not text:
            return []
        fenced = _FENCED_JSON_RE.search(text)
        if fenced:
            text = str(fenced.group(1) or "").strip()
        if not text:
            return []
        array_match = _JSON_ARRAY_RE.search(text)
        payload: Any = None
        if array_match:
            try:
                payload = json.loads(array_match.group(0))
            except Exception:
                payload = None
        if payload is None:
            object_match = _JSON_OBJECT_RE.search(text)
            if object_match:
                try:
                    payload = [json.loads(object_match.group(0))]
                except Exception:
                    payload = None
        if not isinstance(payload, list):
            rows: list[dict[str, object]] = []
            for line in text.splitlines():
                item = str(line or "").strip().lstrip("-").strip()
                if not item:
                    continue
                rows.append({"term": item, "definition": ""})
            return rows[:32]
        out: list[dict[str, object]] = []
        for row in payload:
            if not isinstance(row, dict):
                continue
            term = str(row.get("term", "") or "").strip()
            definition = str(row.get("definition", "") or "").strip()
            if not term:
                continue
            out.append({"term": term, "definition": definition})
        return out
