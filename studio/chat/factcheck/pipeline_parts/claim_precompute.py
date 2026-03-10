"""FactCheckPipelineMixin method implementations."""
from __future__ import annotations

from .deps import *  # noqa: F403

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

__all__ = [
    "_set_chunk_claim_precompute_busy",
    "_start_chunk_claim_precompute",
    "_start_next_chunk_claim_precompute_call",
    "_handle_chunk_claim_precompute_complete",
    "_finish_chunk_claim_precompute",
    "_reset_chunk_claim_precompute_state",
]
