"""Fact-check pipeline mixin used by chat dock."""
from __future__ import annotations

import json
import hashlib
import os
import re
import time

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
)

from .factcheck_utils import (
    chunk_source_text,
    contains_text,
    compose_fact_check_markdown,
    fact_status_icon,
    md_escape_cell,
    parse_fact_candidates,
    parse_single_fact_verification,
    select_evidence_snippet,
    split_sentences_for_facts,
    suggest_fact_limit,
    token_overlap,
    validate_fact_check_response,
)


class FactCheckPipelineMixin:
    """Encapsulates extract-then-verify fact-check workflow."""

    _NLI_ENTAILMENT_GREEN_THRESHOLD = 0.55
    _NLI_STRONG_ENTAILMENT_THRESHOLD = 0.90
    _NLI_ASYNC_MAX_CHECKS_PER_SLICE = 1
    _NLI_ASYNC_SLICE_BUDGET_SEC = 0.03
    _NLI_ASYNC_PROGRESS_STEP = 10
    _FACTCHECK_METHOD_ORDER = ("nli", "llm_chunk", "llm_global", "llm_claim_nli")
    _FACTCHECK_MODE_LABELS = {
        "nli": "NLI (Chunk->Satz)",
        "llm": "LLM (Chunk-weise)",
        "llm_chunk": "LLM (Chunk-weise)",
        "llm_global": "LLM (Alle Quellen pro Fakt)",
        "llm_claim_nli": "LLM-Claims + NLI",
    }
    _LLM_GLOBAL_EVIDENCE_HEADER = "Evidenz (LLM-Output, kein Direktzitat)"
    _CLAIM_CACHE_VERSION = 1
    _CLAIM_CHUNK_SIZE = 900
    _CLAIM_CHUNK_OVERLAP = 160

    def _fact_log_debug(self, message: str):
        logger = getattr(self.llm, "_log", None)
        if logger is not None and hasattr(logger, "debug"):
            try:
                logger.debug("LLM", f"[FACTCHECK] {message}")
            except Exception:
                pass

    def _fact_log_info(self, message: str):
        logger = getattr(self.llm, "_log", None)
        if logger is not None and hasattr(logger, "info"):
            try:
                logger.info("LLM", f"[FACTCHECK] {message}")
            except Exception:
                pass

    def _nli_prompt_workflow_preview(self) -> str:
        render = getattr(self.llm, "render_prompt_template", None)
        system_block = ""
        user_block = ""
        if callable(render):
            try:
                system_block = str(render("nli_verify_system") or "").strip()
            except Exception:
                system_block = ""
            try:
                user_block = str(
                    render(
                        "nli_verify_user",
                        {
                            "premise": "<Chunk-Text>",
                            "hypothesis": "<Fakt/Claim>",
                        },
                    )
                    or ""
                ).strip()
            except Exception:
                user_block = ""
        if not system_block:
            system_block = (
                "Transformers NLI Workflow: tokenize(premise,hypothesis) -> "
                "logits -> softmax -> label entailment|neutral|contradiction."
            )
        if not user_block:
            user_block = "premise=<Chunk-Text>\nhypothesis=<Fakt/Claim>"
        return (
            "ℹ NLI-Workflow (Debug-Template):\n"
            "[backend=transformers-cross-encoder]\n"
            "<|workflow|>\n"
            f"{system_block}\n"
            "<|input|>\n"
            f"{user_block}\n"
        )

    @classmethod
    def _normalize_factcheck_mode(cls, mode: str) -> str:
        value = str(mode or "").strip().casefold()
        if value == "nli":
            return "nli"
        if value in {"llm", "llm_chunk", "chunk", "chunkwise"}:
            return "llm_chunk"
        if value in {"llm_global", "global", "all", "all_sources"}:
            return "llm_global"
        if value in {
            "llm_claim_nli",
            "claim_nli",
            "claims",
            "claims_nli",
            "llm_claims_nli",
            "two_phase",
        }:
            return "llm_claim_nli"
        if value == "both":
            return "both"
        return ""

    @classmethod
    def _normalize_factcheck_selection(
        cls,
        raw_selection: object,
    ) -> list[str]:
        seen: set[str] = set()

        def add_mode(raw_mode: object):
            normalized = cls._normalize_factcheck_mode(str(raw_mode or ""))
            if not normalized:
                return
            if normalized == "both":
                for expanded in ("nli", "llm_chunk"):
                    seen.add(expanded)
                return
            seen.add(normalized)

        if isinstance(raw_selection, (list, tuple, set)):
            for item in raw_selection:
                add_mode(item)
        else:
            add_mode(raw_selection)

        if not seen:
            seen = {"nli"}
        return [mode for mode in cls._FACTCHECK_METHOD_ORDER if mode in seen]

    @classmethod
    def _empty_chunk_claim_cache(cls) -> dict[str, object]:
        return {
            "version": int(cls._CLAIM_CACHE_VERSION),
            "chunk_size": int(cls._CLAIM_CHUNK_SIZE),
            "chunk_overlap": int(cls._CLAIM_CHUNK_OVERLAP),
            "docs": {},
        }

    @classmethod
    def _sanitize_chunk_claim_cache_payload(
        cls,
        raw_payload: object,
    ) -> dict[str, object]:
        payload = raw_payload if isinstance(raw_payload, dict) else {}
        docs_in = payload.get("docs", {})
        docs_out: dict[str, object] = {}
        if isinstance(docs_in, dict):
            for source_hash, raw_doc in docs_in.items():
                key = str(source_hash or "").strip()
                if not key or not isinstance(raw_doc, dict):
                    continue
                chunks_in = raw_doc.get("chunks", {})
                chunks_out: dict[str, object] = {}
                if isinstance(chunks_in, dict):
                    for chunk_hash, raw_chunk in chunks_in.items():
                        ckey = str(chunk_hash or "").strip()
                        if not ckey or not isinstance(raw_chunk, dict):
                            continue
                        claims = raw_chunk.get("claims", [])
                        claim_list: list[str] = []
                        if isinstance(claims, list):
                            for item in claims:
                                claim = re.sub(r"\s+", " ", str(item or "")).strip()
                                if claim:
                                    claim_list.append(claim)
                        chunks_out[ckey] = {
                            "chunk_index": int(raw_chunk.get("chunk_index", 0) or 0),
                            "chunk_text": str(raw_chunk.get("chunk_text", "") or ""),
                            "claims": claim_list,
                            "updated_at": str(raw_chunk.get("updated_at", "") or ""),
                        }
                docs_out[key] = {
                    "source_name": str(raw_doc.get("source_name", "") or ""),
                    "source_hash": key,
                    "chunk_size": int(raw_doc.get("chunk_size", cls._CLAIM_CHUNK_SIZE) or cls._CLAIM_CHUNK_SIZE),
                    "chunk_overlap": int(raw_doc.get("chunk_overlap", cls._CLAIM_CHUNK_OVERLAP) or cls._CLAIM_CHUNK_OVERLAP),
                    "chunks": chunks_out,
                }
        return {
            "version": int(payload.get("version", cls._CLAIM_CACHE_VERSION) or cls._CLAIM_CACHE_VERSION),
            "chunk_size": int(payload.get("chunk_size", cls._CLAIM_CHUNK_SIZE) or cls._CLAIM_CHUNK_SIZE),
            "chunk_overlap": int(payload.get("chunk_overlap", cls._CLAIM_CHUNK_OVERLAP) or cls._CLAIM_CHUNK_OVERLAP),
            "docs": docs_out,
        }

    def _ensure_chunk_claim_cache(self) -> dict[str, object]:
        cache = getattr(self, "_chunk_claim_cache", None)
        if not isinstance(cache, dict):
            cache = self._empty_chunk_claim_cache()
            setattr(self, "_chunk_claim_cache", cache)
            return cache

        normalized = self._sanitize_chunk_claim_cache_payload(cache)
        setattr(self, "_chunk_claim_cache", normalized)
        return normalized

    def export_chunk_claim_cache(self) -> dict[str, object]:
        cache = self._ensure_chunk_claim_cache()
        try:
            return json.loads(json.dumps(cache, ensure_ascii=False))
        except Exception:
            return self._empty_chunk_claim_cache()

    def import_chunk_claim_cache(self, payload: object):
        normalized = self._sanitize_chunk_claim_cache_payload(payload)
        setattr(self, "_chunk_claim_cache", normalized)

    @staticmethod
    def _hash_text(text: str) -> str:
        return hashlib.sha1(str(text or "").encode("utf-8", errors="ignore")).hexdigest()

    def _build_source_chunk_entries(
        self,
        sources: list[tuple[str, str]],
    ) -> list[dict[str, object]]:
        out: list[dict[str, object]] = []
        chunk_size = int(self._CLAIM_CHUNK_SIZE)
        chunk_overlap = int(self._CLAIM_CHUNK_OVERLAP)
        for source_name, source_text in list(sources or []):
            clean_source = str(source_name or "").strip()
            clean_text = str(source_text or "")
            if not clean_source or not clean_text.strip():
                continue
            source_hash = self._hash_text(clean_text)
            chunk_list = chunk_source_text(
                clean_text,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
            )
            for chunk_index, chunk in enumerate(chunk_list):
                chunk_text = str(chunk or "").strip()
                if not chunk_text:
                    continue
                out.append(
                    {
                        "source": clean_source,
                        "source_hash": source_hash,
                        "chunk_index": int(chunk_index),
                        "chunk_text": chunk_text,
                        "chunk_hash": self._hash_text(chunk_text),
                    }
                )
        return out

    def _get_cached_chunk_claims(self, entry: dict[str, object]) -> list[str]:
        cache = self._ensure_chunk_claim_cache()
        docs = cache.get("docs", {})
        if not isinstance(docs, dict):
            return []
        source_hash = str(entry.get("source_hash", "") or "").strip()
        chunk_hash = str(entry.get("chunk_hash", "") or "").strip()
        if not source_hash or not chunk_hash:
            return []
        doc = docs.get(source_hash, {})
        if not isinstance(doc, dict):
            return []
        chunks = doc.get("chunks", {})
        if not isinstance(chunks, dict):
            return []
        item = chunks.get(chunk_hash, {})
        if not isinstance(item, dict):
            return []
        claims = item.get("claims", [])
        if not isinstance(claims, list):
            return []
        out: list[str] = []
        for claim in claims:
            text = re.sub(r"\s+", " ", str(claim or "")).strip()
            if text:
                out.append(text)
        return out

    def _store_cached_chunk_claims(
        self,
        entry: dict[str, object],
        claims: list[str],
    ):
        cache = self._ensure_chunk_claim_cache()
        docs = cache.setdefault("docs", {})
        if not isinstance(docs, dict):
            docs = {}
            cache["docs"] = docs

        source_hash = str(entry.get("source_hash", "") or "").strip()
        chunk_hash = str(entry.get("chunk_hash", "") or "").strip()
        if not source_hash or not chunk_hash:
            return

        doc = docs.get(source_hash)
        if not isinstance(doc, dict):
            doc = {
                "source_name": str(entry.get("source", "") or ""),
                "source_hash": source_hash,
                "chunk_size": int(self._CLAIM_CHUNK_SIZE),
                "chunk_overlap": int(self._CLAIM_CHUNK_OVERLAP),
                "chunks": {},
            }
            docs[source_hash] = doc

        chunks = doc.get("chunks", {})
        if not isinstance(chunks, dict):
            chunks = {}
            doc["chunks"] = chunks

        claim_list: list[str] = []
        seen: set[str] = set()
        for claim in list(claims or []):
            text = re.sub(r"\s+", " ", str(claim or "")).strip()
            if not text:
                continue
            key = text.casefold()
            if key in seen:
                continue
            seen.add(key)
            claim_list.append(text)

        chunks[chunk_hash] = {
            "chunk_index": int(entry.get("chunk_index", 0) or 0),
            "chunk_text": str(entry.get("chunk_text", "") or ""),
            "claims": claim_list,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        setattr(self, "_chunk_claim_cache", cache)

    def _build_claim_nli_units(
        self,
        chunk_entries: list[dict[str, object]],
    ) -> list[dict[str, str]]:
        units: list[dict[str, str]] = []
        for entry in list(chunk_entries or []):
            source_name = str(entry.get("source", "") or "").strip()
            chunk_text = str(entry.get("chunk_text", "") or "").strip()
            if not source_name or not chunk_text:
                continue
            claims = self._get_cached_chunk_claims(entry)
            for claim in claims:
                units.append(
                    {
                        "source": source_name,
                        "premise": claim,
                        "evidence": chunk_text,
                        "mode": "chunk_claim",
                    }
                )
        return units

    @staticmethod
    def _build_source_contexts_from_context(ctx: dict) -> list[tuple[str, str]]:
        file_contents = list(ctx.get("file_contents", []) or [])
        rag_results = list(ctx.get("rag_results", []) or [])

        out: list[tuple[str, str]] = []
        for name, content in file_contents:
            clean_name = str(name or "").strip()
            clean_content = str(content or "").strip()
            if not clean_name or not clean_content:
                continue
            if clean_name.startswith("Draft:"):
                continue
            out.append((clean_name, clean_content))

        for path, _score, excerpt in rag_results:
            label = os.path.basename(str(path or "").strip())
            label = label or str(path or "").strip() or "RAG Results"
            text = str(excerpt or "").strip()
            if not text:
                continue
            out.append((label, text))
        return out

    @staticmethod
    def _normalize_atomic_claims(claims: list[str]) -> list[str]:
        """
        Enforce atomic claims post-processing.

        The LLM is prompted to emit atomic claims, but we still split obvious
        multi-claim bundles conservatively to keep one statement per row.
        """
        out: list[str] = []
        seen: set[str] = set()
        for raw_claim in list(claims or []):
            base = re.sub(r"\s+", " ", str(raw_claim or "")).strip()
            if not base:
                continue

            candidates = [base]
            split_parts = re.split(
                r"\s*;\s+|\s+(?:und|sowie|wobei|außerdem|zudem|hingegen)\s+",
                base,
                flags=re.IGNORECASE,
            )
            valid_parts = [
                re.sub(r"\s+", " ", part).strip(" ,;:-")
                for part in split_parts
                if len(re.findall(r"\w+", part, flags=re.UNICODE)) >= 5
            ]
            if len(valid_parts) >= 2:
                candidates = valid_parts

            for cand in candidates:
                text = re.sub(r"\s+", " ", str(cand or "")).strip()
                if len(text) < 6:
                    continue
                key = text.casefold()
                if key in seen:
                    continue
                seen.add(key)
                out.append(text)
        return out

    def _parse_atomic_claims_from_response(
        self,
        response: str,
        source_text: str,
    ) -> list[str]:
        parsed = parse_fact_candidates(response, source_text)
        atomized = self._normalize_atomic_claims(parsed)
        return atomized

    def _set_chunk_claim_precompute_busy(self, running: bool):
        setattr(self, "_chunk_claim_precompute_running", bool(running))
        apply_busy_state = getattr(self, "_apply_busy_state", None)
        if callable(apply_busy_state):
            try:
                apply_busy_state()
            except Exception:
                pass

    def _start_chunk_claim_precompute(
        self,
        source_contexts: list[tuple[str, str]],
    ) -> tuple[bool, str]:
        if bool(getattr(self, "_pending_fact_check", False)):
            return False, "Faktencheck läuft bereits."
        if bool(getattr(self, "_pending_chunk_claim_precompute", False)):
            return False, "Chunk-Claim-Vorkalkulation läuft bereits."

        chunk_entries = self._build_source_chunk_entries(source_contexts)
        if not chunk_entries:
            return False, "Keine verwertbaren Chunks gefunden."

        missing: list[dict[str, object]] = []
        for entry in chunk_entries:
            if self._get_cached_chunk_claims(entry):
                continue
            missing.append(dict(entry))

        if not missing:
            return True, f"Cache vollständig ({len(chunk_entries)} Chunks)."

        setattr(self, "_pending_chunk_claim_precompute", True)
        setattr(self, "_pending_chunk_claim_entries", chunk_entries)
        setattr(self, "_pending_chunk_claim_tasks", missing)
        setattr(self, "_pending_chunk_claim_index", 0)
        setattr(self, "_pending_chunk_claim_total", len(chunk_entries))
        setattr(self, "_pending_chunk_claim_missing", len(missing))
        self._set_chunk_claim_precompute_busy(True)
        self._fact_log_info(
            "Chunk-Claim precompute start | "
            f"total_chunks={len(chunk_entries)} uncached_chunks={len(missing)}"
        )
        self._start_next_chunk_claim_precompute_call()
        return True, f"Vorkalkulation gestartet ({len(missing)} neue Chunks)."

    def _start_next_chunk_claim_precompute_call(self):
        if not bool(getattr(self, "_pending_chunk_claim_precompute", False)):
            return

        tasks = list(getattr(self, "_pending_chunk_claim_tasks", []) or [])
        idx = int(getattr(self, "_pending_chunk_claim_index", 0) or 0)
        if idx >= len(tasks):
            self._finish_chunk_claim_precompute()
            return

        entry = dict(tasks[idx] or {})
        source_name = str(entry.get("source", "") or "").strip() or "Quelle"
        chunk_text = str(entry.get("chunk_text", "") or "").strip()
        if not chunk_text:
            self._store_cached_chunk_claims(entry, [])
            setattr(self, "_pending_chunk_claim_index", idx + 1)
            self._start_next_chunk_claim_precompute_call()
            return

        fact_limit = suggest_fact_limit(chunk_text)
        request = self.llm.render_prompt_template(
            "claim_extract_user",
            {
                "input_label": "Chunk",
                "fact_limit": str(fact_limit),
            },
        ).strip()
        if not request:
            request = (
                "Extrahiere atomare Claims aus genau diesem Chunk.\n"
                "Ausgabe NUR als JSON-Array von Strings.\n"
                f"Maximal {fact_limit} Claims."
            )
        self._fact_log_debug(
            "Chunk-Claim precompute request\n"
            f"chunk_task_index={idx}\n"
            f"source={source_name}\n"
            f"chunk_hash={entry.get('chunk_hash', '')}\n"
            f"user_prompt={request}\n"
            f"chunk={chunk_text}"
        )

        gen_params = dict(self.model_panel.get_generation_params())
        gen_params["max_tokens"] = max(
            180,
            min(int(gen_params.get("max_tokens", 220)), 800),
        )
        gen_params["temperature"] = min(float(gen_params.get("temperature", 0.7)), 0.25)

        started = self.llm.send_message(
            user_message=request,
            file_contents=[(source_name, chunk_text)],
            rag_results=[],
            selected_text="",
            chat_history=[],
            selection_apply_mode=False,
            grounding_required=False,
            grounding_has_sources=True,
            system_prompt_key="claim_extract_system",
            **gen_params,
        )
        if started:
            return

        self._fact_log_info(
            "Chunk-Claim precompute start failed; cache empty claims.\n"
            f"source={source_name}"
        )
        self._store_cached_chunk_claims(entry, [])
        setattr(self, "_pending_chunk_claim_index", idx + 1)
        self._start_next_chunk_claim_precompute_call()

    def _handle_chunk_claim_precompute_complete(self, response: str):
        if not bool(getattr(self, "_pending_chunk_claim_precompute", False)):
            return
        tasks = list(getattr(self, "_pending_chunk_claim_tasks", []) or [])
        idx = int(getattr(self, "_pending_chunk_claim_index", 0) or 0)
        if idx < len(tasks):
            entry = dict(tasks[idx] or {})
            chunk_text = str(entry.get("chunk_text", "") or "")
            claims = self._parse_atomic_claims_from_response(response, chunk_text)
            self._store_cached_chunk_claims(entry, claims)
            self._fact_log_info(
                "Chunk-Claim precompute parsed | "
                f"chunk_task_index={idx} claims={len(claims)} "
                f"source={entry.get('source', '')}"
            )
            setattr(self, "_pending_chunk_claim_index", idx + 1)
        self._start_next_chunk_claim_precompute_call()

    def _finish_chunk_claim_precompute(self):
        total = int(getattr(self, "_pending_chunk_claim_total", 0) or 0)
        missing = int(getattr(self, "_pending_chunk_claim_missing", 0) or 0)
        self._fact_log_info(
            "Chunk-Claim precompute complete | "
            f"total_chunks={total} processed_chunks={missing}"
        )
        history = getattr(self, "history", None)
        if history is not None and hasattr(history, "add_message"):
            history.add_message(
                "system",
                f"✅ Chunk-Claims vorkalkuliert: {missing}/{total} Chunks neu verarbeitet.",
            )
            if hasattr(history, "activate_feedback"):
                try:
                    history.activate_feedback("fact_check")
                except Exception:
                    pass
        self._reset_chunk_claim_precompute_state()

    def _reset_chunk_claim_precompute_state(self):
        setattr(self, "_pending_chunk_claim_precompute", False)
        setattr(self, "_pending_chunk_claim_entries", [])
        setattr(self, "_pending_chunk_claim_tasks", [])
        setattr(self, "_pending_chunk_claim_index", 0)
        setattr(self, "_pending_chunk_claim_total", 0)
        setattr(self, "_pending_chunk_claim_missing", 0)
        self._set_chunk_claim_precompute_busy(False)

    def _select_factcheck_modes(self) -> list[str] | None:
        default_pref = getattr(
            self,
            "_factcheck_modes_pref",
            getattr(self, "_factcheck_mode_pref", "nli"),
        )
        default_modes = self._normalize_factcheck_selection(default_pref)
        if not isinstance(self, QObject):
            return default_modes

        checkboxes: dict[str, QCheckBox] = {}
        try:
            dialog = QDialog(self)
            dialog.setWindowTitle("Faktencheck-Methoden")

            layout = QVBoxLayout(dialog)
            header = QLabel("Wähle eine oder mehrere Faktencheck-Methoden:")
            header.setWordWrap(True)
            layout.addWidget(header)

            warning = QLabel(
                "⚠ Hinweis: LLM (Chunk-weise) ist sehr langsam, weil jeder Fakt "
                "gegen jeden Chunk geprüft wird."
            )
            warning.setWordWrap(True)
            layout.addWidget(warning)

            for mode in self._FACTCHECK_METHOD_ORDER:
                label = self._FACTCHECK_MODE_LABELS.get(mode, mode)
                cb = QCheckBox(label)
                cb.setChecked(mode in default_modes)
                if mode == "llm_chunk":
                    cb.setToolTip(
                        "Sehr langsam: pro Fakt werden alle Chunks einzeln vom LLM geprüft."
                    )
                elif mode == "llm_claim_nli":
                    cb.setToolTip(
                        "Zweistufig: zuerst Claim-Extraktion pro Chunk (mit Cache), danach NLI-Abgleich."
                    )
                checkboxes[mode] = cb
                layout.addWidget(cb)

            buttons = QDialogButtonBox(
                QDialogButtonBox.StandardButton.Ok
                | QDialogButtonBox.StandardButton.Cancel
            )
            buttons.accepted.connect(dialog.accept)
            buttons.rejected.connect(dialog.reject)
            layout.addWidget(buttons)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return None
        except Exception:
            return default_modes

        selected = [
            mode
            for mode in self._FACTCHECK_METHOD_ORDER
            if checkboxes.get(mode) is not None and checkboxes[mode].isChecked()
        ]
        normalized = self._normalize_factcheck_selection(selected) if selected else []
        if normalized:
            setattr(self, "_factcheck_modes_pref", normalized)
            setattr(self, "_factcheck_mode_pref", normalized[0])
        return normalized

    def _select_factcheck_mode(self) -> str:
        selected = self._select_factcheck_modes()
        if not selected:
            return ""
        return selected[0]

    @staticmethod
    def _extract_json_object(raw: str) -> dict[str, object]:
        text = str(raw or "").strip()
        if not text:
            return {}
        fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, flags=re.IGNORECASE)
        candidate = fenced.group(1).strip() if fenced else text
        try:
            data = json.loads(candidate)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
        match = re.search(r"\{[\s\S]*\}", candidate)
        if not match:
            return {}
        try:
            data = json.loads(match.group(0))
            if isinstance(data, dict):
                return data
        except Exception:
            return {}
        return {}

    def _parse_llm_chunk_verdict(
        self,
        response: str,
    ) -> tuple[str, float, str, str, str]:
        data = self._extract_json_object(response)
        decision_raw = str(
            data.get("decision", "")
            or data.get("label", "")
            or data.get("status", "")
            or data.get("class", "")
        ).strip().casefold()
        label = "neutral"
        if decision_raw in {"entailment", "belegt", "supported", "support", "ja", "yes"}:
            label = "entailment"
        elif decision_raw in {"teilweise", "partial", "partially"}:
            label = "entailment"
        elif decision_raw in {
            "contradiction", "widerspruch", "conflict", "refuted", "nein", "no"
        }:
            label = "contradiction"

        score_raw = data.get("confidence", data.get("score", data.get("probability", None)))
        score = 0.0
        try:
            score = float(score_raw) if score_raw is not None else 0.0
        except Exception:
            score = 0.0
        if not (0.0 <= score <= 1.0):
            score = 0.0
        if score <= 0.0:
            if label == "entailment":
                score = 0.45 if decision_raw in {"teilweise", "partial", "partially"} else 0.62
            elif label == "contradiction":
                score = 0.62
            else:
                score = 0.50

        numeric_check = str(
            data.get("numeric_check", "")
            or data.get("number_check", "")
            or data.get("numeric_relation", "")
        ).strip()
        evidence = str(
            data.get("evidence", "")
            or data.get("quote", "")
            or data.get("excerpt", "")
            or ""
        ).strip()
        reason = str(data.get("reason", "") or "").strip()
        if numeric_check:
            reason = (
                f"{reason}; numeric_check={numeric_check}"
                if reason else f"numeric_check={numeric_check}"
            )
        return label, max(0.0, min(1.0, float(score))), reason, evidence, numeric_check.casefold()

    def _calibrate_llm_chunk_result(
        self,
        *,
        fact: str,
        chunk_text: str,
        label: str,
        score: float,
        reason: str,
        evidence_hint: str,
        numeric_check: str,
    ) -> tuple[str, float, str, str]:
        label_out = str(label or "neutral").strip().casefold() or "neutral"
        score_out = max(0.0, min(1.0, float(score)))
        evidence = str(evidence_hint or "").strip()
        reason_out = reason
        evidence_replaced = False

        # Hallucinated evidence must never be trusted for chunk-level verification.
        if evidence and not contains_text(chunk_text, evidence):
            reason_out = (
                f"{reason_out}; evidence_not_in_chunk_replaced"
                if reason_out else "evidence_not_in_chunk_replaced"
            )
            evidence = ""
            evidence_replaced = True
        if not evidence:
            evidence = select_evidence_snippet(fact, chunk_text, max_chars=260)

        overlap = token_overlap(fact, evidence or chunk_text)
        chunk_overlap = token_overlap(fact, chunk_text)

        if label_out == "entailment":
            # Prevent overconfident entailment on weak lexical grounding.
            score_out = min(score_out, 0.20 + 0.75 * overlap)
            if numeric_check == "conflict":
                label_out = "contradiction"
                score_out = max(score_out, 0.60)
                reason_out = (
                    f"{reason_out}; numeric_conflict_overrides_entailment"
                    if reason_out else "numeric_conflict_overrides_entailment"
                )
            elif overlap < 0.30:
                label_out = "neutral"
                score_out = min(score_out, 0.49)
                reason_out = (
                    f"{reason_out}; low_overlap_downgraded_to_neutral"
                    if reason_out else "low_overlap_downgraded_to_neutral"
                )
            elif overlap < 0.45:
                score_out = min(score_out, 0.72)
                reason_out = (
                    f"{reason_out}; weak_overlap_confidence_capped"
                    if reason_out else "weak_overlap_confidence_capped"
                )
            if evidence_replaced:
                if overlap < 0.55:
                    label_out = "neutral"
                    score_out = min(score_out, 0.49)
                    reason_out = (
                        f"{reason_out}; hallucinated_evidence_downgraded"
                        if reason_out else "hallucinated_evidence_downgraded"
                    )
                else:
                    score_out = min(score_out, 0.58)
                    reason_out = (
                        f"{reason_out}; hallucinated_evidence_confidence_capped"
                        if reason_out else "hallucinated_evidence_confidence_capped"
                    )
        elif label_out == "contradiction":
            if numeric_check == "conflict":
                score_out = max(score_out, 0.65)
            else:
                score_out = min(score_out, 0.30 + 0.65 * max(overlap, chunk_overlap))
            if max(overlap, chunk_overlap) < 0.22 and numeric_check != "conflict":
                label_out = "neutral"
                score_out = min(score_out, 0.49)
                reason_out = (
                    f"{reason_out}; low_overlap_contradiction_downgraded_to_neutral"
                    if reason_out else "low_overlap_contradiction_downgraded_to_neutral"
                )
        else:
            score_out = min(score_out, 0.75)

        return (
            label_out,
            max(0.0, min(1.0, score_out)),
            reason_out,
            evidence,
        )

    def _compose_factcheck_markdown_for_methods(self) -> str:
        method_results = dict(getattr(self, "_pending_fact_method_results", {}) or {})
        run_order = list(getattr(self, "_pending_fact_run_order", []) or [])

        def evidence_header_for_mode(mode: str) -> str:
            mode_norm = self._normalize_factcheck_mode(mode)
            if mode_norm == "llm_global":
                return self._LLM_GLOBAL_EVIDENCE_HEADER
            if mode_norm == "llm_claim_nli":
                return "Evidenz (extrahierter Chunk-Claim)"
            return "Evidenz"

        def reason_header_for_mode(mode: str) -> str:
            mode_norm = self._normalize_factcheck_mode(mode)
            if mode_norm in {"llm_chunk", "llm_global", "llm"}:
                return "Begründung"
            return ""

        if not method_results:
            return compose_fact_check_markdown(
                self._pending_fact_results,
                self._pending_fact_target_label,
            )
        if len(method_results) == 1:
            mode = run_order[0] if run_order else next(iter(method_results.keys()))
            label = self._FACTCHECK_MODE_LABELS.get(str(mode), str(mode))
            return compose_fact_check_markdown(
                method_results.get(mode, []),
                f"{self._pending_fact_target_label} | {label}",
                evidence_header=evidence_header_for_mode(str(mode)),
                reason_header=reason_header_for_mode(str(mode)),
            )

        def status_cell(row: dict[str, str] | None) -> str:
            if not isinstance(row, dict):
                return "—"
            status = str(row.get("status", "nicht_belegt") or "nicht_belegt").strip().casefold()
            icon = fact_status_icon(status)
            confidence_raw = row.get("confidence", "")
            confidence_text = ""
            if confidence_raw not in ("", None):
                try:
                    conf = float(confidence_raw)
                    conf = max(0.0, min(1.0, conf))
                    confidence_text = f" ({conf:.2f})"
                except Exception:
                    conf_txt = str(confidence_raw).strip()
                    if conf_txt:
                        confidence_text = f" ({conf_txt})"
            return f"{icon} {status}{confidence_text}".strip()

        present_modes = [mode for mode in run_order if mode in method_results]
        if not present_modes:
            present_modes = list(method_results.keys())

        row_maps: dict[str, dict[str, dict[str, str]]] = {}
        ordered_keys: list[str] = []
        seen_keys: set[str] = set()
        for mode in present_modes:
            rows = list(method_results.get(mode, []) or [])
            local_map: dict[str, dict[str, str]] = {}
            for idx, row in enumerate(rows):
                row_dict = dict(row or {})
                key = str(row_dict.get("id", "") or "").strip() or f"C{idx + 1}"
                local_map[key] = row_dict
                if key not in seen_keys:
                    seen_keys.add(key)
                    ordered_keys.append(key)
            row_maps[mode] = local_map

        overview_lines: list[str] = []
        if ordered_keys and present_modes:
            header_cols = ["ID", "Fakt"]
            for idx, mode in enumerate(present_modes, 1):
                label = self._FACTCHECK_MODE_LABELS.get(str(mode), str(mode))
                header_cols.append(f"Status{idx}: {label}")
            overview_lines.append("### Übersicht")
            overview_lines.append("")
            overview_lines.append("| " + " | ".join(header_cols) + " |")
            overview_lines.append("|" + "|".join(["---"] * len(header_cols)) + "|")

            for key in ordered_keys:
                fact_text = ""
                for mode in present_modes:
                    row = row_maps.get(mode, {}).get(key)
                    if row:
                        fact_text = str(row.get("fact", "") or "").strip()
                        if fact_text:
                            break
                row_cells = [md_escape_cell(key), md_escape_cell(fact_text)]
                for mode in present_modes:
                    cell = status_cell(row_maps.get(mode, {}).get(key))
                    row_cells.append(md_escape_cell(cell))
                overview_lines.append("| " + " | ".join(row_cells) + " |")

            overview_lines.append("")

        sections: list[str] = [f"## Faktencheck ({self._pending_fact_target_label or 'Zieltext'})", ""]
        sections.extend(overview_lines)
        for mode in run_order:
            rows = list(method_results.get(mode, []) or [])
            label = self._FACTCHECK_MODE_LABELS.get(str(mode), str(mode))
            section = compose_fact_check_markdown(
                rows,
                f"{self._pending_fact_target_label} | {label}",
                evidence_header=evidence_header_for_mode(str(mode)),
                reason_header=reason_header_for_mode(str(mode)),
            )
            section_lines = section.splitlines()
            if section_lines and section_lines[0].startswith("## Faktencheck"):
                section_lines = section_lines[2:] if len(section_lines) >= 2 else []
            sections.append(f"### {label}")
            sections.extend(section_lines)
            sections.append("")
        return "\n".join(sections).strip()

    def _complete_fact_backend(self, mode: str, rows: list[dict[str, str]]):
        run_order = list(getattr(self, "_pending_fact_run_order", []) or [])
        method_results = dict(getattr(self, "_pending_fact_method_results", {}) or {})
        method_results[str(mode)] = list(rows or [])
        setattr(self, "_pending_fact_method_results", method_results)
        next_index = int(getattr(self, "_pending_fact_backend_index", 0) or 0) + 1
        setattr(self, "_pending_fact_backend_index", next_index)
        if next_index < len(run_order):
            self._start_next_fact_backend()
            return
        if run_order:
            first_mode = run_order[0]
            self._pending_fact_results = list(method_results.get(first_mode, []) or [])
        self._finalize_fact_check()

    def _finalize_fact_check(self):
        markdown = self._compose_factcheck_markdown_for_methods()
        self._fact_log_debug(
            "Final markdown table\n"
            f"{markdown}"
        )
        note = validate_fact_check_response(
            markdown,
            self._pending_fact_target_text,
            self._pending_fact_sources,
        )
        if note:
            note_text = re.sub(r"^\s*⚠\s*", "", note).strip()
            markdown = f"{markdown}\n\n---\n\n## Qualitätsprüfung\n{note_text}"

        if self._fact_result_handler is not None:
            ok, info = self._fact_result_handler(
                self._pending_fact_target_label or "Faktencheck",
                markdown,
            )
            if not ok:
                self.history.add_message(
                    "system",
                    "⚠ Faktencheck konnte nicht im Draft-Workspace geöffnet "
                    f"werden: {info}",
                )
                self.history.add_message("assistant", markdown)
        else:
            self.history.add_message("assistant", markdown)
        self._reset_fact_pipeline_state()

    def _set_factcheck_async_busy(self, running: bool):
        setattr(self, "_factcheck_async_running", bool(running))
        apply_busy_state = getattr(self, "_apply_busy_state", None)
        if callable(apply_busy_state):
            try:
                apply_busy_state()
            except Exception:
                pass

    def _supports_async_nli_verify(self) -> bool:
        return isinstance(self, QObject)

    @staticmethod
    def _new_nli_tracker() -> dict[str, object]:
        return {
            "best_label": "neutral",
            "best_score": 0.0,
            "best_source": "",
            "best_chunk": "",
            "best_reason": "",
            "best_entail_score": -1.0,
            "best_entail_source": "",
            "best_entail_chunk": "",
            "best_entail_reason": "",
            "best_contra_score": -1.0,
            "best_contra_source": "",
            "best_contra_chunk": "",
            "best_contra_reason": "",
        }

    @staticmethod
    def _normalize_nli_result_payload(nli: dict[str, object]) -> tuple[str, float, str, str]:
        label = str(nli.get("label", "neutral") or "neutral").strip().casefold()
        score = float(nli.get("score", 0.0) or 0.0)
        score = max(0.0, min(1.0, score))
        reason = str(nli.get("reason", "") or "").strip()
        evidence_raw = str(nli.get("evidence", "") or "").strip()
        return label, score, reason, evidence_raw

    @staticmethod
    def _build_chunk_nli_units(
        source_chunks: list[tuple[str, str]],
    ) -> list[dict[str, str]]:
        units: list[dict[str, str]] = []
        for source_name, chunk_text in source_chunks:
            clean_source = str(source_name or "").strip()
            clean_chunk = str(chunk_text or "").strip()
            if not clean_source or not clean_chunk:
                continue
            units.append(
                {
                    "source": clean_source,
                    "premise": clean_chunk,
                    "evidence": clean_chunk,
                    "mode": "chunk",
                }
            )
        return units

    @staticmethod
    def _build_sentence_nli_units(
        source_chunks: list[tuple[str, str]],
    ) -> list[dict[str, str]]:
        units: list[dict[str, str]] = []
        seen: set[str] = set()
        for source_name, chunk_text in source_chunks:
            clean_source = str(source_name or "").strip()
            clean_chunk = str(chunk_text or "").strip()
            if not clean_source or not clean_chunk:
                continue
            for sentence in split_sentences_for_facts(clean_chunk):
                sent = re.sub(r"\s+", " ", str(sentence or "")).strip()
                if len(sent) < 12:
                    continue
                key = f"{clean_source}\n{sent.casefold()}"
                if key in seen:
                    continue
                seen.add(key)
                units.append(
                    {
                        "source": clean_source,
                        "premise": sent,
                        "evidence": clean_chunk,
                        "mode": "sentence",
                    }
                )
        return units

    @staticmethod
    def _tracker_has_entailment(tracker: dict[str, object]) -> bool:
        best_entail_score = float(tracker.get("best_entail_score", -1.0) or -1.0)
        best_entail_source = str(tracker.get("best_entail_source", "") or "")
        return best_entail_score >= 0.0 and bool(best_entail_source)

    def _tracker_has_strong_entailment(self, tracker: dict[str, object]) -> bool:
        best_entail_score = float(tracker.get("best_entail_score", -1.0) or -1.0)
        best_entail_source = str(tracker.get("best_entail_source", "") or "")
        return (
            best_entail_score >= float(self._NLI_STRONG_ENTAILMENT_THRESHOLD)
            and bool(best_entail_source)
        )

    def _update_nli_tracker(
        self,
        tracker: dict[str, object],
        *,
        label: str,
        score: float,
        source_name: str,
        evidence_text: str,
        reason: str,
    ):
        best_score = float(tracker.get("best_score", 0.0) or 0.0)
        if score > best_score:
            tracker["best_label"] = label
            tracker["best_score"] = score
            tracker["best_source"] = source_name
            tracker["best_chunk"] = evidence_text
            tracker["best_reason"] = reason

        best_entail_score = float(tracker.get("best_entail_score", -1.0) or -1.0)
        if label == "entailment" and score > best_entail_score:
            tracker["best_entail_score"] = score
            tracker["best_entail_source"] = source_name
            tracker["best_entail_chunk"] = evidence_text
            tracker["best_entail_reason"] = reason

        best_contra_score = float(tracker.get("best_contra_score", -1.0) or -1.0)
        if label == "contradiction" and score > best_contra_score:
            tracker["best_contra_score"] = score
            tracker["best_contra_source"] = source_name
            tracker["best_contra_chunk"] = evidence_text
            tracker["best_contra_reason"] = reason

    def _verify_fact_against_nli_units(
        self,
        *,
        fact: str,
        units: list[dict[str, str]],
        tracker: dict[str, object],
        pass_mode: str,
    ) -> str:
        for unit in units:
            source_name = str(unit.get("source", "") or "").strip()
            premise_text = str(unit.get("premise", "") or "").strip()
            evidence_text = str(unit.get("evidence", "") or "").strip()
            if not source_name or not premise_text:
                continue
            nli = self.llm.verify_nli_sync(premise_text, fact)
            label, score, reason, evidence_raw = self._normalize_nli_result_payload(nli)
            reason_low = reason.casefold()
            if (
                reason_low.startswith("nli_runtime_error")
                or reason_low.startswith("nli_backend_unavailable")
                or reason_low.startswith("nli_model_missing")
            ):
                self._fact_log_info(
                    "NLI runtime error; "
                    f"source={source_name} reason={reason}"
                )
                return (
                    "Das geladene NLI-Transformers-Modell konnte nicht inferieren. "
                    f"Quelle: {source_name}. Detail: {reason or 'n/a'}"
                )
            self._fact_log_debug(
                "NLI check\n"
                f"pass={pass_mode}\n"
                f"fact={fact}\n"
                f"source={source_name}\n"
                f"premise={premise_text}\n"
                f"evidence={evidence_text}\n"
                f"result_label={label}\n"
                f"result_score={score:.4f}\n"
                f"result_reason={reason}\n"
                f"result_evidence={evidence_raw}"
            )
            self._update_nli_tracker(
                tracker,
                label=label,
                score=score,
                source_name=source_name,
                evidence_text=(evidence_text or premise_text),
                reason=reason,
            )
            if self._tracker_has_strong_entailment(tracker):
                self._fact_log_info(
                    "NLI early-stop strong entailment | "
                    f"pass={pass_mode} fact={fact} score>="
                    f"{self._NLI_STRONG_ENTAILMENT_THRESHOLD:.2f}"
                )
                break
        return ""

    def _build_nli_result_row(
        self,
        fact_index: int,
        fact: str,
        tracker: dict[str, object],
        *,
        method: str = "nli",
    ) -> dict[str, str]:
        method_norm = self._normalize_factcheck_mode(method) or "nli"
        is_llm_chunk = method_norm in {"llm_chunk", "llm"}
        is_claim_nli = method_norm == "llm_claim_nli"
        if is_llm_chunk:
            entail_prefix = "LLM-chunk entailment score="
            entail_low_prefix = "LLM-chunk entailment score niedrig="
            contradiction_prefix = "LLM-chunk contradiction score="
            pass_desc = "Chunk-Pass"
        elif is_claim_nli:
            entail_prefix = "Claim-NLI entailment score="
            entail_low_prefix = "Claim-NLI entailment score niedrig="
            contradiction_prefix = "Claim-NLI contradiction score="
            pass_desc = "Claim-Pass über extrahierte Chunk-Claims"
        else:
            entail_prefix = "NLI entailment score="
            entail_low_prefix = "NLI entailment score niedrig="
            contradiction_prefix = "NLI contradiction score="
            pass_desc = "Chunk- und Satz-Pass"
        best_label = str(tracker.get("best_label", "neutral") or "neutral")
        best_score = float(tracker.get("best_score", 0.0) or 0.0)
        best_source = str(tracker.get("best_source", "") or "")
        best_chunk = str(tracker.get("best_chunk", "") or "")
        best_reason = str(tracker.get("best_reason", "") or "")
        best_entail_score = float(tracker.get("best_entail_score", -1.0) or -1.0)
        best_entail_source = str(tracker.get("best_entail_source", "") or "")
        best_entail_chunk = str(tracker.get("best_entail_chunk", "") or "")
        best_entail_reason = str(tracker.get("best_entail_reason", "") or "")
        best_contra_score = float(tracker.get("best_contra_score", -1.0) or -1.0)
        best_contra_source = str(tracker.get("best_contra_source", "") or "")
        best_contra_chunk = str(tracker.get("best_contra_chunk", "") or "")
        best_contra_reason = str(tracker.get("best_contra_reason", "") or "")

        # Rule: always prefer the strongest entailment over all chunks.
        if best_entail_score >= 0.0 and best_entail_source:
            status = (
                "belegt"
                if best_entail_score >= self._NLI_ENTAILMENT_GREEN_THRESHOLD
                else "teilweise"
            )
            reason_prefix = (
                entail_prefix
                if status == "belegt"
                else entail_low_prefix
            )
            return {
                "id": f"C{fact_index + 1}",
                "status": status,
                "fact": fact,
                "sources": best_entail_source,
                "evidence": best_entail_chunk,
                "confidence": f"{best_entail_score:.4f}",
                "reason": (
                    f"{reason_prefix}{best_entail_score:.2f}"
                    + (
                        f" ({best_entail_reason})"
                        if best_entail_reason
                        else ""
                    )
                ),
            }

        # Only when no entailment exists, return the strongest contradiction.
        if best_contra_score >= 0.0 and best_contra_source:
            return {
                "id": f"C{fact_index + 1}",
                "status": "widerspruch",
                "fact": fact,
                "sources": best_contra_source,
                "evidence": best_contra_chunk,
                "confidence": f"{best_contra_score:.4f}",
                "reason": (
                    f"{contradiction_prefix}{best_contra_score:.2f}"
                    + (
                        f" ({best_contra_reason})"
                        if best_contra_reason
                        else ""
                    )
                ),
            }

        if best_score > 0.0 and best_source:
            return {
                "id": f"C{fact_index + 1}",
                "status": "nicht_belegt",
                "fact": fact,
                "sources": best_source,
                "evidence": "",
                "confidence": f"{best_score:.4f}",
                "reason": (
                    f"Kein Entailment in {pass_desc}; bester Treffer="
                    f"{best_label} ({best_score:.2f})"
                    + (f" ({best_reason})" if best_reason else "")
                ),
            }

        return {
            "id": f"C{fact_index + 1}",
            "status": "nicht_belegt",
            "fact": fact,
            "sources": "",
            "evidence": "",
            "confidence": "0.0000",
            "reason": "Kein passender Chunk gefunden",
        }

    def _start_next_fact_backend(self):
        if not self._pending_fact_check:
            return
        run_order = list(getattr(self, "_pending_fact_run_order", []) or [])
        backend_index = int(getattr(self, "_pending_fact_backend_index", 0) or 0)
        if backend_index >= len(run_order):
            self._finalize_fact_check()
            return
        mode = self._normalize_factcheck_mode(run_order[backend_index])
        if mode not in {"nli", "llm_chunk", "llm_global", "llm_claim_nli"}:
            setattr(self, "_pending_fact_backend_index", backend_index + 1)
            self._start_next_fact_backend()
            return

        facts = list(getattr(self, "_pending_fact_facts", []) or [])
        source_chunks = list(getattr(self, "_pending_fact_source_chunks", []) or [])
        source_chunk_entries = list(getattr(self, "_pending_fact_source_chunk_entries", []) or [])
        if mode == "llm_global":
            if not facts or not list(getattr(self, "_pending_fact_sources", []) or []):
                self._complete_fact_backend(mode, [])
                return
        elif mode == "llm_claim_nli":
            if not facts or not source_chunk_entries:
                self._complete_fact_backend(mode, [])
                return
        elif not facts or not source_chunks:
            self._complete_fact_backend(mode, [])
            return

        setattr(self, "_pending_fact_active_method", mode)
        self._pending_fact_results = []
        method_label = self._FACTCHECK_MODE_LABELS.get(mode, mode)
        if mode == "nli":
            self._fact_log_info(
                f"NLI mode enabled | facts={len(facts)} chunks={len(source_chunks)}"
            )
            if self._supports_async_nli_verify():
                self._start_nli_verify_async(facts, source_chunks)
                return
            rows = self._verify_facts_with_nli(facts, source_chunks)
            runtime_error = str(getattr(self, "_pending_nli_runtime_error", "") or "").strip()
            if runtime_error:
                self.history.add_message(
                    "system",
                    f"⚠ NLI-Model-Fehler: {runtime_error}",
                )
                self._complete_fact_backend("nli", [])
                return
            self._complete_fact_backend("nli", rows)
            return

        _ = method_label
        if mode == "llm_global":
            self._pending_fact_stage = "verify"
            self._pending_fact_index = 0
            self._start_next_fact_verify_call()
            return
        if mode == "llm_claim_nli":
            self._start_llm_claim_nli_verify()
            return
        self._start_llm_chunk_verify(source_chunks)

    def _start_llm_chunk_verify(self, source_chunks: list[tuple[str, str]]):
        self._pending_fact_stage = "verify_llm_chunk"
        setattr(self, "_pending_llm_chunk_units", self._build_chunk_nli_units(source_chunks))
        setattr(self, "_pending_llm_fact_index", 0)
        setattr(self, "_pending_llm_chunk_index", 0)
        setattr(self, "_pending_llm_tracker", self._new_nli_tracker())
        fact_count = len(self._pending_fact_facts)
        setattr(
            self,
            "_pending_llm_trackers",
            [self._new_nli_tracker() for _ in range(max(0, fact_count))],
        )
        setattr(self, "_pending_llm_fact_done", [False for _ in range(max(0, fact_count))])
        llm_units = list(getattr(self, "_pending_llm_chunk_units", []) or [])
        self._fact_log_info(
            "LLM chunk mode enabled | "
            f"facts={len(self._pending_fact_facts)} chunks={len(llm_units)} "
            "sentence_fallback=disabled iteration=chunk_first"
        )
        total_checks = len(self._pending_fact_facts) * len(llm_units)
        setattr(self, "_pending_llm_total_checks", int(max(0, total_checks)))
        setattr(self, "_pending_llm_done_checks", 0)
        setattr(self, "_pending_llm_next_progress", self._NLI_ASYNC_PROGRESS_STEP)
        self._start_next_llm_chunk_verify_call()

    def _start_llm_claim_nli_verify(self):
        chunk_entries = list(getattr(self, "_pending_fact_source_chunk_entries", []) or [])
        if not chunk_entries:
            self._complete_fact_backend("llm_claim_nli", [])
            return

        missing: list[dict[str, object]] = []
        for entry in chunk_entries:
            cached_claims = self._get_cached_chunk_claims(entry)
            if cached_claims:
                continue
            missing.append(dict(entry))

        setattr(self, "_pending_claim_chunk_entries", chunk_entries)
        setattr(self, "_pending_claim_extract_tasks", missing)
        setattr(self, "_pending_claim_extract_index", 0)

        if not missing:
            self._fact_log_info(
                "Chunk-Claims cache hit | "
                f"chunks={len(chunk_entries)}"
            )
            self._start_claim_nli_verify_from_cache()
            return

        self._pending_fact_stage = "extract_chunk_claims"
        self._fact_log_info(
            "Chunk-Claims preprocessing | "
            f"total_chunks={len(chunk_entries)} uncached_chunks={len(missing)}"
        )
        self._start_next_chunk_claim_extract_call()

    def _start_next_chunk_claim_extract_call(self):
        if not self._pending_fact_check or self._pending_fact_stage != "extract_chunk_claims":
            return

        tasks = list(getattr(self, "_pending_claim_extract_tasks", []) or [])
        idx = int(getattr(self, "_pending_claim_extract_index", 0) or 0)
        if idx >= len(tasks):
            self._start_claim_nli_verify_from_cache()
            return

        entry = dict(tasks[idx] or {})
        source_name = str(entry.get("source", "") or "").strip() or "Quelle"
        chunk_text = str(entry.get("chunk_text", "") or "").strip()
        if not chunk_text:
            self._store_cached_chunk_claims(entry, [])
            setattr(self, "_pending_claim_extract_index", idx + 1)
            self._start_next_chunk_claim_extract_call()
            return

        fact_limit = suggest_fact_limit(chunk_text)
        request = self.llm.render_prompt_template(
            "claim_extract_user",
            {
                "input_label": "Chunk",
                "fact_limit": str(fact_limit),
            },
        ).strip()
        if not request:
            request = (
                "Extrahiere atomare Claims aus genau diesem Chunk.\n"
                "Ausgabe NUR als JSON-Array von Strings.\n"
                f"Maximal {fact_limit} Claims."
            )
        self._fact_log_debug(
            "Chunk-Claim extract request\n"
            f"chunk_task_index={idx}\n"
            f"source={source_name}\n"
            f"chunk_hash={entry.get('chunk_hash', '')}\n"
            f"user_prompt={request}\n"
            f"chunk={chunk_text}"
        )

        gen_params = dict(self.model_panel.get_generation_params())
        gen_params["max_tokens"] = max(
            180,
            min(int(gen_params.get("max_tokens", 220)), 800),
        )
        gen_params["temperature"] = min(float(gen_params.get("temperature", 0.7)), 0.25)

        started = self.llm.send_message(
            user_message=request,
            file_contents=[(source_name, chunk_text)],
            rag_results=[],
            selected_text="",
            chat_history=[],
            selection_apply_mode=False,
            grounding_required=False,
            grounding_has_sources=True,
            system_prompt_key="claim_extract_system",
            **gen_params,
        )
        if started:
            return

        self._fact_log_info(
            "Chunk-Claim extraction start failed; cache empty claims.\n"
            f"source={source_name}"
        )
        self._store_cached_chunk_claims(entry, [])
        setattr(self, "_pending_claim_extract_index", idx + 1)
        self._start_next_chunk_claim_extract_call()

    def _start_claim_nli_verify_from_cache(self):
        chunk_entries = list(getattr(self, "_pending_claim_chunk_entries", []) or [])
        facts = list(getattr(self, "_pending_fact_facts", []) or [])
        claim_units = self._build_claim_nli_units(chunk_entries)
        self._fact_log_info(
            "Chunk-Claim NLI verify start | "
            f"facts={len(facts)} claim_units={len(claim_units)} chunks={len(chunk_entries)}"
        )
        if not facts or not claim_units:
            rows: list[dict[str, str]] = []
            for fact_index, fact in enumerate(facts):
                rows.append(
                    {
                        "id": f"C{fact_index + 1}",
                        "status": "nicht_belegt",
                        "fact": fact,
                        "sources": "",
                        "evidence": "",
                        "confidence": "0.0000",
                        "reason": "Keine extrahierten Chunk-Claims für NLI-Abgleich gefunden",
                    }
                )
            self._pending_fact_results = list(rows)
            self._complete_fact_backend("llm_claim_nli", rows)
            return

        if self._supports_async_nli_verify():
            self._start_nli_verify_async(
                facts=facts,
                source_chunks=[],
                mode="llm_claim_nli",
                chunk_units=claim_units,
                sentence_units=[],
            )
            return

        rows = self._verify_facts_with_nli_units(
            facts=facts,
            chunk_units=claim_units,
            sentence_units=[],
            method="llm_claim_nli",
        )
        runtime_error = str(getattr(self, "_pending_nli_runtime_error", "") or "").strip()
        if runtime_error:
            self.history.add_message(
                "system",
                f"⚠ NLI-Model-Fehler: {runtime_error}",
            )
            self._complete_fact_backend("llm_claim_nli", [])
            return
        self._complete_fact_backend("llm_claim_nli", rows)

    def _build_llm_chunk_rows(
        self,
        facts: list[str],
        trackers: list[dict[str, object]],
        method: str,
    ) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        for fact_index, fact in enumerate(facts):
            tracker = (
                dict(trackers[fact_index])
                if fact_index < len(trackers)
                else self._new_nli_tracker()
            )
            rows.append(
                self._build_nli_result_row(
                    fact_index,
                    fact,
                    tracker,
                    method=method,
                )
            )
        return rows

    def _start_next_llm_chunk_verify_call(self):
        if not self._pending_fact_check or self._pending_fact_stage != "verify_llm_chunk":
            return
        facts = list(self._pending_fact_facts or [])
        units = list(getattr(self, "_pending_llm_chunk_units", []) or [])
        active_method = self._normalize_factcheck_mode(
            getattr(self, "_pending_fact_active_method", "llm_chunk")
        )
        if active_method not in {"llm_chunk", "llm"}:
            active_method = "llm_chunk"
        if not facts or not units:
            self._complete_fact_backend(active_method, list(self._pending_fact_results))
            return

        fact_index = int(getattr(self, "_pending_llm_fact_index", 0) or 0)
        chunk_index = int(getattr(self, "_pending_llm_chunk_index", 0) or 0)
        trackers = list(getattr(self, "_pending_llm_trackers", []) or [])
        if len(trackers) < len(facts):
            trackers.extend(
                self._new_nli_tracker()
                for _ in range(len(facts) - len(trackers))
            )
        fact_done = list(getattr(self, "_pending_llm_fact_done", []) or [])
        if len(fact_done) < len(facts):
            fact_done.extend(False for _ in range(len(facts) - len(fact_done)))

        while chunk_index < len(units):
            if fact_index >= len(facts):
                chunk_index += 1
                fact_index = 0
                continue
            if fact_done[fact_index]:
                fact_index += 1
                continue
            break

        setattr(self, "_pending_llm_fact_index", fact_index)
        setattr(self, "_pending_llm_chunk_index", chunk_index)
        setattr(self, "_pending_llm_trackers", trackers)
        setattr(self, "_pending_llm_fact_done", fact_done)
        current_tracker = (
            dict(trackers[fact_index])
            if 0 <= fact_index < len(trackers)
            else self._new_nli_tracker()
        )
        setattr(self, "_pending_llm_tracker", current_tracker)

        if chunk_index >= len(units) or all(bool(v) for v in fact_done):
            rows = self._build_llm_chunk_rows(facts, trackers, active_method)
            self._pending_fact_results = list(rows)
            self._complete_fact_backend(active_method, rows)
            return

        fact = facts[fact_index]
        unit = units[chunk_index]
        source_name = str(unit.get("source", "") or "").strip() or "Quelle"
        premise_text = str(unit.get("premise", "") or "").strip()
        request = self.llm.render_prompt_template(
            "fact_verify_chunk_user",
            {
                "fact": fact,
                "source": source_name,
                "chunk": premise_text,
            },
        ).strip()
        if not request:
            request = (
                "Prüfe den Fakt gegen genau diesen einzelnen Chunk.\n"
                "Der Chunk ist die einzige Quelle. Kein externes Wissen.\n"
                "Antwort NUR als JSON: "
                "{\"decision\":\"entailment|neutral|contradiction\","
                "\"confidence\":0.0,\"reason\":\"...\",\"numeric_check\":\"...\","
                "\"evidence\":\"...\"}\n"
                f"Fakt:\n{fact}\nQuelle:\n{source_name}"
            )
        self._fact_log_debug(
            "LLM chunk verify request\n"
            f"fact_index={fact_index}\n"
            f"chunk_index={chunk_index}\n"
            f"source={source_name}\n"
            f"fact={fact}\n"
            f"chunk={premise_text}\n"
            f"user_prompt={request}"
        )

        gen_params = dict(self.model_panel.get_generation_params())
        gen_params["max_tokens"] = max(
            120,
            min(int(gen_params.get("max_tokens", 220)), 300),
        )
        gen_params["temperature"] = min(
            float(gen_params.get("temperature", 0.7)),
            0.20,
        )
        started = self.llm.send_message(
            user_message=request,
            file_contents=[(source_name, premise_text)],
            rag_results=[],
            selected_text="",
            chat_history=[],
            selection_apply_mode=False,
            grounding_required=True,
            grounding_has_sources=True,
            system_prompt_key="fact_verify_chunk_system",
            **gen_params,
        )
        if started:
            return
        self.history.add_message(
            "system",
            "⚠ LLM-Chunkprüfung konnte nicht fortgesetzt werden.",
        )
        self._reset_fact_pipeline_state()

    def _verify_facts_with_nli(
        self,
        facts: list[str],
        source_chunks: list[tuple[str, str]],
    ) -> list[dict[str, str]]:
        chunk_units = self._build_chunk_nli_units(source_chunks)
        sentence_units = self._build_sentence_nli_units(source_chunks)
        return self._verify_facts_with_nli_units(
            facts=facts,
            chunk_units=chunk_units,
            sentence_units=sentence_units,
            method="nli",
        )

    def _verify_facts_with_nli_units(
        self,
        *,
        facts: list[str],
        chunk_units: list[dict[str, str]],
        sentence_units: list[dict[str, str]] | None = None,
        method: str = "nli",
    ) -> list[dict[str, str]]:
        results: list[dict[str, str]] = []
        runtime_error = ""
        sentence_units = list(sentence_units or [])

        for fact_index, fact in enumerate(facts):
            tracker = self._new_nli_tracker()
            runtime_error = self._verify_fact_against_nli_units(
                fact=fact,
                units=chunk_units,
                tracker=tracker,
                pass_mode="chunk",
            )
            if runtime_error:
                break
            if (not self._tracker_has_entailment(tracker)) and sentence_units:
                self._fact_log_info(
                    f"NLI sentence-pass fallback | fact_index={fact_index + 1}"
                )
                runtime_error = self._verify_fact_against_nli_units(
                    fact=fact,
                    units=sentence_units,
                    tracker=tracker,
                    pass_mode="sentence",
                )
                if runtime_error:
                    break

            results.append(
                self._build_nli_result_row(fact_index, fact, tracker, method=method)
            )

        setattr(self, "_pending_nli_runtime_error", runtime_error)
        return results

    def _start_nli_verify_async(
        self,
        facts: list[str],
        source_chunks: list[tuple[str, str]],
        *,
        mode: str = "nli",
        chunk_units: list[dict[str, str]] | None = None,
        sentence_units: list[dict[str, str]] | None = None,
    ):
        if chunk_units is None:
            chunk_units = self._build_chunk_nli_units(source_chunks)
        if sentence_units is None:
            sentence_units = self._build_sentence_nli_units(source_chunks)
        mode_norm = self._normalize_factcheck_mode(mode) or "nli"
        if not facts or not chunk_units:
            self._pending_fact_results = []
            self._complete_fact_backend(mode_norm, [])
            return
        self._pending_fact_stage = "verify_nli"
        setattr(self, "_pending_nli_runtime_error", "")
        setattr(self, "_pending_nli_async_active", True)
        setattr(self, "_pending_nli_result_mode", mode_norm)
        setattr(self, "_pending_nli_chunk_units", chunk_units)
        setattr(self, "_pending_nli_sentence_units", sentence_units)
        setattr(self, "_pending_nli_fact_index", 0)
        setattr(self, "_pending_nli_pass_mode", "chunk")
        setattr(self, "_pending_nli_unit_index", 0)
        setattr(self, "_pending_nli_tracker", self._new_nli_tracker())
        total_checks = len(facts) * len(chunk_units)
        setattr(self, "_pending_nli_total_checks", max(0, int(total_checks)))
        setattr(self, "_pending_nli_done_checks", 0)
        setattr(self, "_pending_nli_next_progress", self._NLI_ASYNC_PROGRESS_STEP)
        self._set_factcheck_async_busy(True)
        self._schedule_nli_verify_tick()

    def _schedule_nli_verify_tick(self):
        if not bool(getattr(self, "_pending_nli_async_active", False)):
            return
        QTimer.singleShot(0, self._run_nli_verify_tick)

    def _run_nli_verify_tick(self):
        if (
            not self._pending_fact_check
            or self._pending_fact_stage != "verify_nli"
            or not bool(getattr(self, "_pending_nli_async_active", False))
        ):
            return

        facts = list(getattr(self, "_pending_fact_facts", []) or [])
        chunk_units = list(getattr(self, "_pending_nli_chunk_units", []) or [])
        sentence_units = list(getattr(self, "_pending_nli_sentence_units", []) or [])
        result_mode = self._normalize_factcheck_mode(
            str(getattr(self, "_pending_nli_result_mode", "nli") or "nli")
        ) or "nli"
        if not facts or not chunk_units:
            self._set_factcheck_async_busy(False)
            self._complete_fact_backend(result_mode, [])
            return

        fact_index = int(getattr(self, "_pending_nli_fact_index", 0) or 0)
        pass_mode = str(getattr(self, "_pending_nli_pass_mode", "chunk") or "chunk")
        unit_index = int(getattr(self, "_pending_nli_unit_index", 0) or 0)
        done_checks = int(getattr(self, "_pending_nli_done_checks", 0) or 0)
        tracker = dict(getattr(self, "_pending_nli_tracker", {}) or self._new_nli_tracker())
        total_checks = int(getattr(self, "_pending_nli_total_checks", 0) or 0)
        runtime_error = ""

        checks_done_in_slice = 0
        deadline = time.monotonic() + float(self._NLI_ASYNC_SLICE_BUDGET_SEC)
        max_checks = max(1, int(self._NLI_ASYNC_MAX_CHECKS_PER_SLICE))

        while (
            checks_done_in_slice < max_checks
            and time.monotonic() <= deadline
            and fact_index < len(facts)
        ):
            fact = facts[fact_index]
            units = chunk_units if pass_mode == "chunk" else sentence_units
            if not units:
                if pass_mode == "chunk":
                    break
                self._pending_fact_results.append(
                    self._build_nli_result_row(
                        fact_index,
                        fact,
                        tracker,
                        method=result_mode,
                    )
                )
                fact_index += 1
                pass_mode = "chunk"
                unit_index = 0
                tracker = self._new_nli_tracker()
                continue

            unit = units[unit_index]
            source_name = str(unit.get("source", "") or "").strip()
            premise_text = str(unit.get("premise", "") or "").strip()
            evidence_text = str(unit.get("evidence", "") or "").strip()
            if not source_name or not premise_text:
                unit_index += 1
                if unit_index >= len(units):
                    if pass_mode == "chunk" and (not self._tracker_has_entailment(tracker)) and sentence_units:
                        pass_mode = "sentence"
                        unit_index = 0
                        setattr(self, "_pending_nli_total_checks", total_checks + len(sentence_units))
                        total_checks += len(sentence_units)
                    else:
                        self._pending_fact_results.append(
                            self._build_nli_result_row(
                                fact_index,
                                fact,
                                tracker,
                                method=result_mode,
                            )
                        )
                        fact_index += 1
                        pass_mode = "chunk"
                        unit_index = 0
                        tracker = self._new_nli_tracker()
                continue

            nli = self.llm.verify_nli_sync(premise_text, fact)
            label, score, reason, evidence_raw = self._normalize_nli_result_payload(nli)
            reason_low = reason.casefold()
            if (
                reason_low.startswith("nli_runtime_error")
                or reason_low.startswith("nli_backend_unavailable")
                or reason_low.startswith("nli_model_missing")
            ):
                runtime_error = (
                    "Das geladene NLI-Transformers-Modell konnte nicht inferieren. "
                    f"Quelle: {source_name}. Detail: {reason or 'n/a'}"
                )
                self._fact_log_info(
                    "NLI runtime error; "
                    f"source={source_name} reason={reason}"
                )
                break

            self._fact_log_debug(
                "NLI check\n"
                f"pass={pass_mode}\n"
                f"fact={fact}\n"
                f"source={source_name}\n"
                f"premise={premise_text}\n"
                f"evidence={evidence_text}\n"
                f"result_label={label}\n"
                f"result_score={score:.4f}\n"
                f"result_reason={reason}\n"
                f"result_evidence={evidence_raw}"
            )
            self._update_nli_tracker(
                tracker,
                label=label,
                score=score,
                source_name=source_name,
                evidence_text=(evidence_text or premise_text),
                reason=reason,
            )

            done_checks += 1
            checks_done_in_slice += 1
            unit_index += 1

            next_progress = int(
                getattr(
                    self,
                    "_pending_nli_next_progress",
                    self._NLI_ASYNC_PROGRESS_STEP,
                )
                or self._NLI_ASYNC_PROGRESS_STEP
            )
            if total_checks > 0:
                progress = int((done_checks * 100) / total_checks)
                if progress >= next_progress:
                    setattr(
                        self,
                        "_pending_nli_next_progress",
                        next_progress + self._NLI_ASYNC_PROGRESS_STEP,
                    )

            if self._tracker_has_strong_entailment(tracker):
                self._fact_log_info(
                    "NLI async early-stop strong entailment | "
                    f"pass={pass_mode} fact_index={fact_index + 1} score>="
                    f"{self._NLI_STRONG_ENTAILMENT_THRESHOLD:.2f}"
                )
                unit_index = len(units)

            if unit_index >= len(units):
                if pass_mode == "chunk" and (not self._tracker_has_entailment(tracker)) and sentence_units:
                    self._fact_log_info(
                        f"NLI sentence-pass fallback | fact_index={fact_index + 1}"
                    )
                    pass_mode = "sentence"
                    unit_index = 0
                    setattr(self, "_pending_nli_total_checks", total_checks + len(sentence_units))
                    total_checks += len(sentence_units)
                else:
                    self._pending_fact_results.append(
                        self._build_nli_result_row(
                            fact_index,
                            fact,
                            tracker,
                            method=result_mode,
                        )
                    )
                    fact_index += 1
                    pass_mode = "chunk"
                    unit_index = 0
                    tracker = self._new_nli_tracker()

        setattr(self, "_pending_nli_fact_index", fact_index)
        setattr(self, "_pending_nli_pass_mode", pass_mode)
        setattr(self, "_pending_nli_unit_index", unit_index)
        setattr(self, "_pending_nli_done_checks", done_checks)
        setattr(self, "_pending_nli_tracker", tracker)

        if runtime_error:
            setattr(self, "_pending_nli_runtime_error", runtime_error)
            setattr(self, "_pending_nli_async_active", False)
            self._set_factcheck_async_busy(False)
            self.history.add_message(
                "system",
                f"⚠ NLI-Model-Fehler: {runtime_error}",
            )
            self._complete_fact_backend(result_mode, [])
            return

        if fact_index >= len(facts):
            setattr(self, "_pending_nli_async_active", False)
            self._set_factcheck_async_busy(False)
            self._complete_fact_backend(result_mode, list(self._pending_fact_results))
            return

        self._schedule_nli_verify_tick()

    def _reset_fact_pipeline_state(self):
        self._pending_fact_check = False
        self._pending_fact_stage = ""
        self._pending_fact_target_text = ""
        self._pending_fact_target_label = ""
        self._pending_fact_sources = []
        self._pending_fact_facts = []
        self._pending_fact_results = []
        self._pending_fact_index = 0
        setattr(self, "_pending_nli_runtime_error", "")
        setattr(self, "_pending_nli_async_active", False)
        setattr(self, "_pending_nli_result_mode", "nli")
        setattr(self, "_pending_nli_chunk_units", [])
        setattr(self, "_pending_nli_sentence_units", [])
        setattr(self, "_pending_nli_fact_index", 0)
        setattr(self, "_pending_nli_pass_mode", "chunk")
        setattr(self, "_pending_nli_unit_index", 0)
        setattr(self, "_pending_nli_tracker", self._new_nli_tracker())
        setattr(self, "_pending_nli_total_checks", 0)
        setattr(self, "_pending_nli_done_checks", 0)
        setattr(self, "_pending_nli_next_progress", self._NLI_ASYNC_PROGRESS_STEP)
        setattr(self, "_pending_fact_mode", "nli")
        setattr(self, "_pending_fact_requested_methods", [])
        setattr(self, "_pending_fact_run_order", [])
        setattr(self, "_pending_fact_backend_index", 0)
        setattr(self, "_pending_fact_active_method", "")
        setattr(self, "_pending_fact_method_results", {})
        setattr(self, "_pending_fact_source_chunks", [])
        setattr(self, "_pending_fact_source_chunk_entries", [])
        setattr(self, "_pending_llm_chunk_units", [])
        setattr(self, "_pending_llm_fact_index", 0)
        setattr(self, "_pending_llm_chunk_index", 0)
        setattr(self, "_pending_llm_tracker", self._new_nli_tracker())
        setattr(self, "_pending_llm_trackers", [])
        setattr(self, "_pending_llm_fact_done", [])
        setattr(self, "_pending_llm_total_checks", 0)
        setattr(self, "_pending_llm_done_checks", 0)
        setattr(self, "_pending_llm_next_progress", self._NLI_ASYNC_PROGRESS_STEP)
        setattr(self, "_pending_claim_chunk_entries", [])
        setattr(self, "_pending_claim_extract_tasks", [])
        setattr(self, "_pending_claim_extract_index", 0)
        self._set_factcheck_async_busy(False)
        self._fact_log_info(
            "Reset pipeline state."
        )

    def _resolve_canvas_selected_text(self) -> str:
        """
        Resolve current canvas selection for fact-check target fallback.

        Uses explicit getter when available and falls back to host window's
        canvas widget, including cached one-shot selection after focus handoff.
        """
        getter = getattr(self, "_canvas_selection_getter", None)
        if callable(getter):
            try:
                return str(getter() or "").strip()
            except Exception:
                pass

        parent_fn = getattr(self, "parent", None)
        host = None
        if callable(parent_fn):
            try:
                host = parent_fn()
            except Exception:
                host = None
        if host is None:
            return ""

        canvas = getattr(host, "canvas", None)
        if canvas is None:
            return ""
        get_selected = getattr(canvas, "get_selected_text", None)
        if not callable(get_selected):
            return ""
        try:
            return str(get_selected(allow_cached=True) or "").strip()
        except TypeError:
            try:
                return str(get_selected() or "").strip()
            except Exception:
                return ""
        except Exception:
            return ""

    def _send_fact_check(self):
        if not self.llm.is_model_loaded():
            self.history.add_message(
                "system",
                "⚠ No model loaded. Load a GGUF model first.",
            )
            return
        if bool(getattr(self, "_aux_generating", False)) or bool(
            getattr(self, "_factcheck_async_running", False)
        ):
            self.history.add_message(
                "system",
                "⚠ Eine Hintergrundaufgabe läuft bereits. Bitte kurz warten.",
            )
            return

        ctx: dict = {}
        collector = getattr(self, "_collect_shared_context", None)
        if callable(collector):
            ctx = collector()
        elif self._context_getter:
            raw = self._context_getter()
            if isinstance(raw, dict):
                ctx = raw

        grounding_has_sources = bool(ctx.get("grounding_has_sources", False))
        if not grounding_has_sources:
            self.history.add_message(
                "system",
                "⚠ Faktencheck benötigt Quellen. "
                "Bitte mindestens ein Dokument auswählen und/oder RAG-Treffer erzeugen.",
            )
            return

        file_contents = list(ctx.get("file_contents", []) or [])

        selected_text = str(ctx.get("selected_text", "") or "").strip()
        target_text = ""
        target_label = ""
        if not selected_text:
            selected_text = self._resolve_canvas_selected_text()

        if selected_text:
            target_text = selected_text
            target_label = "markierte Draft-Auswahl"
        else:
            for name, content in file_contents:
                if str(name).startswith("Draft:") and str(content or "").strip():
                    target_text = str(content).strip()
                    target_label = str(name)
                    break

        if not target_text:
            typed_text = self.input_box.toPlainText().strip()
            if typed_text:
                target_text = typed_text
                target_label = "Text aus Eingabefeld"

        if not target_text:
            self.history.add_message(
                "system",
                "⚠ Kein Zieltext für Faktencheck gefunden. "
                "Markiere Text im Draft-Workspace oder aktiviere Draft als Kontextquelle.",
            )
            return

        source_contexts = self._build_source_contexts_from_context(ctx)

        if not source_contexts:
            self.history.add_message(
                "system",
                "⚠ Für den Faktencheck wurden keine verwertbaren Quelltexte gefunden.",
            )
            return

        selected_methods = self._select_factcheck_modes()
        if selected_methods is None:
            return
        if not selected_methods:
            self.history.add_message(
                "system",
                "⚠ Bitte mindestens eine Faktencheck-Methode auswählen.",
            )
            return
        mode_labels = [
            self._FACTCHECK_MODE_LABELS.get(mode, mode)
            for mode in selected_methods
        ]
        mode_label = ", ".join(mode_labels)
        nli_loaded = bool(getattr(self.llm, "is_nli_model_loaded", lambda: False)())
        nli_requested = any(mode in {"nli", "llm_claim_nli"} for mode in selected_methods)
        nli_required_modes = {"nli", "llm_claim_nli"}
        all_selected_need_nli = all(mode in nli_required_modes for mode in selected_methods)
        if nli_requested and not nli_loaded and all_selected_need_nli:
            self.history.add_message(
                "system",
                "⚠ NLI-Modell ist nicht geladen. "
                "Bitte zuerst ein NLI-Transformers-Modell laden oder LLM-Modus wählen.",
            )
            return

        self._fact_log_info(
            "Start fact-check\n"
            f"modes={mode_label}\n"
            f"target_label={target_label or 'Zieltext'}\n"
            f"target_text={target_text}\n"
            f"sources={len(source_contexts)}"
        )
        for idx, (name, content) in enumerate(source_contexts, 1):
            self._fact_log_debug(
                f"Source[{idx}] name={name}\ncontent={content}"
            )

        self._pending_apply_to_canvas = False
        self._pending_selected_text = ""
        self._pending_user_message = ""
        self.history.reset_feedback()
        self._reset_fact_pipeline_state()

        self._pending_fact_check = True
        self._pending_fact_stage = "extract"
        self._pending_fact_target_text = target_text
        self._pending_fact_target_label = target_label or "Zieltext"
        self._pending_fact_sources = source_contexts
        self._pending_fact_facts = []
        self._pending_fact_results = []
        self._pending_fact_index = 0
        setattr(self, "_pending_fact_mode", selected_methods[0])
        setattr(self, "_pending_fact_requested_methods", selected_methods)
        setattr(self, "_pending_fact_run_order", [])
        setattr(self, "_pending_fact_backend_index", 0)
        setattr(self, "_pending_fact_active_method", "")
        setattr(self, "_pending_fact_method_results", {})
        setattr(self, "_pending_fact_source_chunks", [])
        self._start_fact_extract_call()

    def _start_fact_extract_call(self):
        if not self._pending_fact_check or self._pending_fact_stage != "extract":
            return

        target_text = self._pending_fact_target_text.strip()
        if not target_text:
            self.history.add_message(
                "system", "⚠ Faktencheck abgebrochen: Zieltext fehlt."
            )
            self._reset_fact_pipeline_state()
            return

        fact_limit = suggest_fact_limit(target_text)
        request = self.llm.render_prompt_template(
            "claim_extract_user",
            {
                "input_label": "Zieltext",
                "fact_limit": str(fact_limit),
            },
        ).strip()
        self._fact_log_debug(
            "Extract request\n"
            f"fact_limit={fact_limit}\n"
            f"target={target_text}\n"
            f"user_prompt={request}"
        )

        gen_params = dict(self.model_panel.get_generation_params())
        base_max = max(256, int(gen_params.get("max_tokens", 1024)))
        max_tokens = max(384, min(base_max, 2200))
        max_tokens = max(max_tokens, min(2600, 220 + fact_limit * 22))
        gen_params["max_tokens"] = max_tokens
        gen_params["temperature"] = min(
            float(gen_params.get("temperature", 0.7)),
            0.35,
        )

        started = self.llm.send_message(
            user_message=request,
            file_contents=[("Zieltext", target_text)],
            rag_results=[],
            selected_text="",
            chat_history=[],
            selection_apply_mode=False,
            grounding_required=False,
            grounding_has_sources=True,
            system_prompt_key="claim_extract_system",
            **gen_params,
        )
        if not started:
            self.history.add_message(
                "system", "⚠ Faktenextraktion konnte nicht gestartet werden."
            )
            self._fact_log_info("Extract start failed.")
            self._reset_fact_pipeline_state()

    def _start_next_fact_verify_call(self):
        if not self._pending_fact_check or self._pending_fact_stage != "verify":
            return

        if self._pending_fact_index >= len(self._pending_fact_facts):
            active_method = self._normalize_factcheck_mode(
                getattr(self, "_pending_fact_active_method", "")
            )
            if active_method == "llm_global":
                self._complete_fact_backend("llm_global", list(self._pending_fact_results))
                return
            self._finalize_fact_check()
            return

        fact = self._pending_fact_facts[self._pending_fact_index]
        allowed_sources = ", ".join(
            dict.fromkeys(
                name for name, _ in self._pending_fact_sources if str(name).strip()
            )
        )
        request = self.llm.render_prompt_template(
            "fact_verify_user",
            {
                "allowed_sources": allowed_sources or "Kontextquellen",
                "fact": fact,
            },
        ).strip()
        self._fact_log_debug(
            "Verify request\n"
            f"fact_index={self._pending_fact_index}\n"
            f"fact={fact}\n"
            f"allowed_sources={allowed_sources}\n"
            f"user_prompt={request}"
        )

        gen_params = dict(self.model_panel.get_generation_params())
        gen_params["max_tokens"] = max(
            100,
            min(int(gen_params.get("max_tokens", 220)), 260),
        )
        gen_params["temperature"] = min(
            float(gen_params.get("temperature", 0.7)),
            0.25,
        )

        started = self.llm.send_message(
            user_message=request,
            file_contents=self._pending_fact_sources,
            rag_results=[],
            selected_text="",
            chat_history=[],
            selection_apply_mode=False,
            grounding_required=True,
            grounding_has_sources=bool(self._pending_fact_sources),
            system_prompt_key="fact_verify_system",
            **gen_params,
        )
        if not started:
            self.history.add_message(
                "system",
                "⚠ Faktprüfung konnte nicht fortgesetzt werden.",
            )
            self._fact_log_info("Verify start failed.")
            self._reset_fact_pipeline_state()

    def _handle_fact_pipeline_complete(self, response: str):
        self._fact_log_debug(
            "Stage response\n"
            f"stage={self._pending_fact_stage}\n"
            f"response={response}"
        )
        if self._pending_fact_stage == "extract":
            facts = self._parse_atomic_claims_from_response(
                response,
                self._pending_fact_target_text,
            )
            self._fact_log_info(
                f"Extract parsed facts={len(facts)}"
            )
            for idx, fact in enumerate(facts, 1):
                self._fact_log_debug(f"Fact[{idx}] {fact}")
            if not facts:
                self.history.add_message(
                    "system",
                    "⚠ Es konnten keine stabilen Fakten aus dem Zieltext extrahiert werden.",
                )
                self._reset_fact_pipeline_state()
                return
            self.history.add_message("system", f"ℹ Fakten gefunden: {len(facts)}")
            self._pending_fact_facts = facts
            self._pending_fact_results = []
            self._pending_fact_index = 0
            chunk_entries = self._build_source_chunk_entries(self._pending_fact_sources)
            source_chunks = [
                (
                    str(entry.get("source", "") or ""),
                    str(entry.get("chunk_text", "") or ""),
                )
                for entry in chunk_entries
                if str(entry.get("source", "") or "").strip()
                and str(entry.get("chunk_text", "") or "").strip()
            ]
            if not source_chunks:
                self.history.add_message(
                    "system",
                    "⚠ Für den Faktencheck wurden keine verwertbaren Quell-Chunks gefunden.",
                )
                self._reset_fact_pipeline_state()
                return
            setattr(self, "_pending_fact_source_chunks", source_chunks)
            setattr(self, "_pending_fact_source_chunk_entries", chunk_entries)

            requested_methods = self._normalize_factcheck_selection(
                getattr(self, "_pending_fact_requested_methods", [])
            )
            if not requested_methods:
                requested_methods = self._normalize_factcheck_selection(
                    getattr(self, "_pending_fact_mode", "nli")
                )
            nli_loaded = bool(getattr(self.llm, "is_nli_model_loaded", lambda: False)())
            run_order: list[str] = []
            for requested_mode in requested_methods:
                mode = self._normalize_factcheck_mode(requested_mode)
                if mode == "nli":
                    if nli_loaded:
                        run_order.append("nli")
                    else:
                        self.history.add_message(
                            "system",
                            "⚠ NLI-Modell nicht geladen. NLI-Lauf wird übersprungen.",
                        )
                    continue
                if mode in {"llm_chunk", "llm_global"}:
                    run_order.append(mode)
                    continue
                if mode == "llm_claim_nli":
                    if nli_loaded:
                        run_order.append(mode)
                    else:
                        self.history.add_message(
                            "system",
                            "⚠ NLI-Modell nicht geladen. LLM-Claims+NLI wird übersprungen.",
                        )
            if not run_order:
                self.history.add_message(
                    "system",
                    "⚠ Keine verfügbare Faktencheck-Methode ausgewählt.",
                )
                self._reset_fact_pipeline_state()
                return

            setattr(self, "_pending_fact_run_order", run_order)
            setattr(self, "_pending_fact_backend_index", 0)
            setattr(self, "_pending_fact_method_results", {})
            self._start_next_fact_backend()
            return

        if self._pending_fact_stage == "extract_chunk_claims":
            tasks = list(getattr(self, "_pending_claim_extract_tasks", []) or [])
            idx = int(getattr(self, "_pending_claim_extract_index", 0) or 0)
            if idx < len(tasks):
                entry = dict(tasks[idx] or {})
                chunk_text = str(entry.get("chunk_text", "") or "")
                claims = self._parse_atomic_claims_from_response(response, chunk_text)
                self._store_cached_chunk_claims(entry, claims)
                self._fact_log_info(
                    "Chunk-Claim extract parsed | "
                    f"chunk_task_index={idx} claims={len(claims)} "
                    f"source={entry.get('source', '')}"
                )
                setattr(self, "_pending_claim_extract_index", idx + 1)
            self._start_next_chunk_claim_extract_call()
            return

        if self._pending_fact_stage == "verify_llm_chunk":
            facts = list(self._pending_fact_facts or [])
            units = list(getattr(self, "_pending_llm_chunk_units", []) or [])
            fact_index = int(getattr(self, "_pending_llm_fact_index", 0) or 0)
            chunk_index = int(getattr(self, "_pending_llm_chunk_index", 0) or 0)
            if fact_index < len(facts) and chunk_index < len(units):
                unit = units[chunk_index]
                source_name = str(unit.get("source", "") or "").strip()
                chunk_text = str(unit.get("evidence", "") or "").strip()
                fact = facts[fact_index]
                label, score, reason, evidence_hint, numeric_check = self._parse_llm_chunk_verdict(response)
                label, score, reason, evidence_text = self._calibrate_llm_chunk_result(
                    fact=fact,
                    chunk_text=chunk_text,
                    label=label,
                    score=score,
                    reason=reason,
                    evidence_hint=evidence_hint,
                    numeric_check=numeric_check,
                )
                self._fact_log_debug(
                    "LLM chunk verify parsed\n"
                    f"fact_index={fact_index}\n"
                    f"chunk_index={chunk_index}\n"
                    f"fact={fact}\n"
                    f"source={source_name}\n"
                    f"label={label}\n"
                    f"score={score:.4f}\n"
                    f"reason={reason}\n"
                    f"evidence={evidence_text}"
                )
                trackers = list(getattr(self, "_pending_llm_trackers", []) or [])
                if len(trackers) < len(facts):
                    trackers.extend(
                        self._new_nli_tracker()
                        for _ in range(len(facts) - len(trackers))
                    )
                fact_done = list(getattr(self, "_pending_llm_fact_done", []) or [])
                if len(fact_done) < len(facts):
                    fact_done.extend(False for _ in range(len(facts) - len(fact_done)))
                tracker = dict(trackers[fact_index] or self._new_nli_tracker())
                self._update_nli_tracker(
                    tracker,
                    label=label,
                    score=score,
                    source_name=source_name,
                    evidence_text=evidence_text,
                    reason=reason,
                )
                trackers[fact_index] = tracker
                setattr(self, "_pending_llm_trackers", trackers)
                setattr(self, "_pending_llm_fact_done", fact_done)
                setattr(self, "_pending_llm_tracker", tracker)
                done_checks = int(getattr(self, "_pending_llm_done_checks", 0) or 0) + 1
                total_checks = int(getattr(self, "_pending_llm_total_checks", 0) or 0)
                setattr(self, "_pending_llm_done_checks", done_checks)
                next_progress = int(
                    getattr(self, "_pending_llm_next_progress", self._NLI_ASYNC_PROGRESS_STEP)
                    or self._NLI_ASYNC_PROGRESS_STEP
                )
                if total_checks > 0:
                    progress = int((done_checks * 100) / total_checks)
                    if progress >= next_progress:
                        setattr(
                            self,
                            "_pending_llm_next_progress",
                            next_progress + self._NLI_ASYNC_PROGRESS_STEP,
                        )
                if self._tracker_has_strong_entailment(tracker):
                    self._fact_log_info(
                        "LLM chunk early-stop strong entailment | "
                        f"fact_index={fact_index + 1} score>="
                        f"{self._NLI_STRONG_ENTAILMENT_THRESHOLD:.2f}"
                    )
                    fact_done[fact_index] = True
                    setattr(self, "_pending_llm_fact_done", fact_done)
                    remaining_chunks = max(0, len(units) - (chunk_index + 1))
                    if remaining_chunks > 0:
                        adjusted_total = max(done_checks, total_checks - remaining_chunks)
                        setattr(self, "_pending_llm_total_checks", adjusted_total)
                setattr(self, "_pending_llm_fact_index", fact_index + 1)
                setattr(self, "_pending_llm_chunk_index", chunk_index)
            self._start_next_llm_chunk_verify_call()
            return

        if self._pending_fact_stage == "verify":
            if self._pending_fact_index < len(self._pending_fact_facts):
                fact = self._pending_fact_facts[self._pending_fact_index]
                record = parse_single_fact_verification(
                    response,
                    fact,
                    self._pending_fact_index,
                    self._pending_fact_sources,
                )
                self._fact_log_debug(
                    "Verify parsed record\n"
                    f"fact={fact}\n"
                    f"record={record}"
                )
                self._pending_fact_results.append(record)
                self._pending_fact_index += 1
            self._start_next_fact_verify_call()
            return

        self._reset_fact_pipeline_state()
