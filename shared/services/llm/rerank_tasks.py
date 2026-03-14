"""RAG reranking task methods for ``LLMManager``."""
from __future__ import annotations

import json
import os
import re
from typing import Any

_COLLAPSE_WS_RE = re.compile(r"\s+")
_JSON_ARRAY_RE = re.compile(r"\[[\s\S]*\]")


def _collapse_ws(value: object) -> str:
    return _COLLAPSE_WS_RE.sub(" ", str(value or "")).strip()


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
        excerpt = _collapse_ws(excerpt)
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
        raw_full = self._generate_backend_text(
            prompt,
            max_tokens=max_out_tokens,
            temperature=0.1,
            top_p=0.9,
            repeat_penalty=1.05,
            stop_tokens=["<|"],
        )
        self._log_llm_io("RAG-Rerank", prompt, raw_full)
        raw = raw_full.strip()

        parsed: Any = None
        try:
            parsed = json.loads(raw)
        except Exception:
            m = _JSON_ARRAY_RE.search(raw)
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
