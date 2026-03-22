"""Source-grounding heuristics for graph and mindmap outputs."""
from __future__ import annotations

from typing import Any
import re
import unicodedata

from shared.domain.graph_spec import GraphSpec

from .graph_closure import label_fingerprint

_WORD_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]+")
_MARKUP_RE = re.compile(r"(```|^\s*#+\s|^\s*[-*]\s|\*\*|^\s*[\[\]{}(),:;]+\s*$)", re.MULTILINE)
_META_PHRASES = (
    "ich habe versucht",
    "strukturiertes graph-format",
    "strukturiertes graph-format",
    "graph-ausgabe",
    "mindmap-ausgabe",
    "die art der beziehung zwischen den knoten",
    "keine erklaerungen ausserhalb",
    "antworte nur mit",
)
_META_TOKEN_SETS = (
    {"relation", "beziehung", "knoten"},
    {"source", "target"},
    {"nodes", "edges"},
    {"graph", "format"},
    {"mindmap", "format"},
)


def _bool(raw: Any, default: bool) -> bool:
    if isinstance(raw, bool):
        return raw
    text = str(raw or "").strip().casefold()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return bool(default)


def _int(raw: Any, default: int) -> int:
    try:
        return int(raw)
    except Exception:
        return int(default)


def _float(raw: Any, default: float) -> float:
    try:
        return float(raw)
    except Exception:
        return float(default)


def _ascii_fold(text: str) -> str:
    raw = unicodedata.normalize("NFKD", str(text or "").casefold())
    return "".join(ch for ch in raw if not unicodedata.combining(ch))


def _term_set(text: str) -> set[str]:
    return set(label_fingerprint(text))


def _symbol_set(text: str) -> set[str]:
    return {
        str(token or "").strip().casefold()
        for token in re.findall(r"\b([A-Za-z])\b", str(text or ""))
        if str(token or "").strip()
    }


def _contains_substantial_phrase(label: str, corpus: str) -> bool:
    label_norm = re.sub(r"\s+", " ", _ascii_fold(label)).strip(" -_:;,.'\"")
    corpus_norm = _ascii_fold(corpus)
    if len(label_norm) < 8:
        return False
    return label_norm in corpus_norm


def _label_initial(label: str) -> str:
    for token in _WORD_RE.findall(_ascii_fold(label)):
        if token:
            return token[:1]
    return ""


def _is_meta_label(label: str) -> bool:
    raw = str(label or "").strip()
    if not raw:
        return True
    folded = _ascii_fold(raw)
    if _MARKUP_RE.search(raw):
        return True
    if any(phrase in folded for phrase in _META_PHRASES):
        return True
    tokens = set(label_fingerprint(raw))
    if not tokens:
        return True
    for required in _META_TOKEN_SETS:
        if required <= tokens:
            return True
    if re.search(r'"\s+und\s+"', raw):
        return True
    if len(_WORD_RE.findall(raw)) >= 8 and raw.endswith('"'):
        return True
    return False


def evaluate_graph_grounding(
    *,
    spec: GraphSpec | None,
    mode: str,
    context_text: str,
    query: str,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = dict(policy or {})
    mode_clean = str(mode or "graph").strip().casefold()
    default_enabled = mode_clean == "graph"
    enabled = _bool(
        cfg.get("map_require_context_grounding"),
        default_enabled and bool(str(context_text or "").strip()),
    )
    source_text = str(context_text or "").strip()
    query_text = str(query or "").strip()
    source_terms = _term_set(source_text) | _term_set(query_text)
    source_symbols = _symbol_set(source_text) | _symbol_set(query_text)
    min_grounded_nodes = _int(
        cfg.get("map_min_grounded_nodes"),
        2 if mode_clean == "graph" else 1,
    )
    min_grounded_ratio = _float(
        cfg.get("map_min_grounded_ratio"),
        0.45 if mode_clean == "graph" else 0.25,
    )
    max_meta_ratio = _float(
        cfg.get("map_max_meta_node_ratio"),
        0.34 if mode_clean == "graph" else 0.5,
    )
    max_meta_nodes = _int(
        cfg.get("map_max_meta_nodes"),
        1 if mode_clean == "graph" else 2,
    )
    total_nodes = len(dict(spec.nodes or {})) if spec is not None else 0
    if not enabled:
        return {
            "enabled": False,
            "ok": True,
            "reason": "grounding_disabled",
            "total_nodes": total_nodes,
            "grounded_nodes": 0,
            "grounded_ratio": 0.0,
            "meta_like_nodes": 0,
            "meta_like_ratio": 0.0,
            "context_term_count": len(source_terms),
            "query_term_count": len(_term_set(query_text)),
            "min_grounded_nodes": min_grounded_nodes,
            "min_grounded_ratio": min_grounded_ratio,
            "max_meta_nodes": max_meta_nodes,
            "max_meta_node_ratio": max_meta_ratio,
        }
    if spec is None:
        return {
            "enabled": True,
            "ok": False,
            "reason": "grounding_missing_spec",
            "total_nodes": 0,
            "grounded_nodes": 0,
            "grounded_ratio": 0.0,
            "meta_like_nodes": 0,
            "meta_like_ratio": 0.0,
            "context_term_count": len(source_terms),
            "query_term_count": len(_term_set(query_text)),
            "min_grounded_nodes": min_grounded_nodes,
            "min_grounded_ratio": min_grounded_ratio,
            "max_meta_nodes": max_meta_nodes,
            "max_meta_node_ratio": max_meta_ratio,
        }

    grounded_nodes = 0
    meta_like_nodes = 0
    grounded_labels: list[str] = []
    ungrounded_labels: list[str] = []
    meta_labels: list[str] = []
    for node in dict(spec.nodes or {}).values():
        label = str(getattr(node, "label", "") or "").strip()
        if not label:
            continue
        label_terms = _term_set(label)
        grounded = bool(label_terms & source_terms)
        if (not grounded) and source_symbols:
            initial = _label_initial(label)
            grounded = bool(initial) and initial in source_symbols
        if (not grounded) and source_text:
            grounded = _contains_substantial_phrase(label, source_text)
        if (not grounded) and query_text:
            grounded = _contains_substantial_phrase(label, query_text)
        if grounded:
            grounded_nodes += 1
            if len(grounded_labels) < 6:
                grounded_labels.append(label)
        else:
            if len(ungrounded_labels) < 6:
                ungrounded_labels.append(label)
        if _is_meta_label(label):
            meta_like_nodes += 1
            if len(meta_labels) < 6:
                meta_labels.append(label)

    total = max(1, total_nodes)
    grounded_ratio = grounded_nodes / total
    meta_ratio = meta_like_nodes / total
    ok = True
    reason = "grounded"
    if grounded_nodes < max(1, min_grounded_nodes) or grounded_ratio < float(min_grounded_ratio):
        ok = False
        reason = "grounding_insufficient"
    if meta_like_nodes > int(max_meta_nodes) or meta_ratio > float(max_meta_ratio):
        ok = False
        if grounded_nodes == 0 or meta_ratio >= 0.5:
            reason = "meta_labels_detected"

    return {
        "enabled": True,
        "ok": bool(ok),
        "reason": reason,
        "total_nodes": total_nodes,
        "grounded_nodes": grounded_nodes,
        "grounded_ratio": round(float(grounded_ratio), 4),
        "meta_like_nodes": meta_like_nodes,
        "meta_like_ratio": round(float(meta_ratio), 4),
        "context_term_count": len(source_terms),
        "query_term_count": len(_term_set(query_text)),
        "min_grounded_nodes": min_grounded_nodes,
        "min_grounded_ratio": min_grounded_ratio,
        "max_meta_nodes": max_meta_nodes,
        "max_meta_node_ratio": max_meta_ratio,
        "sample_grounded_labels": grounded_labels,
        "sample_ungrounded_labels": ungrounded_labels,
        "sample_meta_labels": meta_labels,
    }
