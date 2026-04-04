"""LangGraph-first workflow service facade."""
from __future__ import annotations

import json
import hashlib
import os
import re
import time
import unicodedata
from pathlib import Path
from typing import Any

try:
    from langgraph.graph import END, START, StateGraph
    _LANGGRAPH_AVAILABLE = True
except Exception:  # pragma: no cover - dependency optional during bootstrap
    END = "__end__"  # type: ignore[assignment]
    START = "__start__"  # type: ignore[assignment]
    StateGraph = None  # type: ignore[assignment]
    _LANGGRAPH_AVAILABLE = False

try:
    from langchain_core.prompts import PromptTemplate as _LCPromptTemplate
    _LANGCHAIN_PROMPTS_AVAILABLE = True
except Exception:  # pragma: no cover - dependency optional during bootstrap
    _LCPromptTemplate = None  # type: ignore[assignment]
    _LANGCHAIN_PROMPTS_AVAILABLE = False

try:
    from langchain_core.output_parsers import JsonOutputParser as _LCJsonOutputParser
    _LANGCHAIN_JSON_PARSER_AVAILABLE = True
except Exception:  # pragma: no cover - dependency optional during bootstrap
    _LCJsonOutputParser = None  # type: ignore[assignment]
    _LANGCHAIN_JSON_PARSER_AVAILABLE = False

from .contracts import StepTrace, WorkflowRunResult
from ._mindmap_pipeline import run_mindmap_pipeline as _run_mindmap_pipeline_impl
from shared.domain.graph_codec import extract_graph_spec, spec_to_markdown
from shared.domain.graph_spec import GraphEdge, GraphNode, GraphSpec
from shared.domain.graph_validation import GraphValidationLimits, validate_graph_spec
from shared.services.local_policy import langsmith_tracing_enabled
from shared.services.plugins.manager import PluginManager

_WORD_TOKEN_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ0-9][A-Za-zÀ-ÖØ-öø-ÿ0-9_-]{2,}", flags=re.UNICODE)
_MARKDOWN_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(?P<title>.+?)\s*$")
_GROUNDING_STOPWORDS = {
    "the", "and", "oder", "und", "mit", "without", "from", "that", "this", "dies", "diese",
    "sind", "ist", "eine", "einer", "einen", "der", "die", "das", "im", "in", "to", "for",
    "von", "auf", "über", "under", "bei", "as", "an", "a", "of", "is", "are", "was",
    "frage", "kontext", "zentralen", "konzepte", "fragestellung", "overview",
}


def _tool(tools: dict[str, Any], name: str):
    fn = dict(tools or {}).get(str(name or ""))
    if callable(fn):
        return fn
    return None


def _render_prompt(template: str, **kwargs: Any) -> str:
    if _LANGCHAIN_PROMPTS_AVAILABLE and _LCPromptTemplate is not None:
        try:
            return str(_LCPromptTemplate.from_template(str(template or "")).format(**kwargs))
        except Exception:
            pass
    text = str(template or "")
    for key, value in kwargs.items():
        text = text.replace("{" + str(key) + "}", str(value))
    return text


def _clip_text(value: object, *, max_chars: int = 2400) -> str:
    text = str(value or "").strip()
    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - 3)].rstrip() + "..."


def _tokenize_words(text: str) -> set[str]:
    return {
        str(token or "").casefold()
        for token in _WORD_TOKEN_RE.findall(str(text or ""))
        if len(str(token or "")) >= 3
    }


def _normalize_match_text(text: str) -> str:
    raw = str(text or "").strip().casefold()
    if not raw:
        return ""
    folded = unicodedata.normalize("NFKD", raw)
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
    folded = re.sub(r"[\u2018\u2019\u201A\u201B\u2032\u2035]", "'", folded)
    folded = re.sub(r"[\u201C\u201D\u201E\u201F\u2033\u2036]", "\"", folded)
    folded = re.sub(r"[\[\]\(\)\{\},;:!?/\\|]+", " ", folded)
    folded = re.sub(r"\s+", " ", folded).strip()
    return folded


def _snippet_fingerprint(text: str) -> str:
    normalized = _normalize_match_text(str(text or ""))
    if not normalized:
        return ""
    compact = re.sub(r"\s+", " ", normalized).strip()
    if not compact:
        return ""
    # Hash the whole normalized text so long snippets that share the same
    # opening prefix are still distinguishable.
    return hashlib.sha1(compact.encode("utf-8")).hexdigest()


def _dedup_keep_order(items: list[str], *, max_items: int) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in list(items or []):
        text = str(item or "").strip()
        key = text.casefold()
        if not text or key in seen:
            continue
        seen.add(key)
        out.append(text)
        if len(out) >= max(1, int(max_items or 1)):
            break
    return out


def _split_markdown_sections(
    text: str,
    *,
    max_sections: int = 48,
    max_section_chars: int = 2_200,
) -> list[tuple[str, str]]:
    raw = str(text or "").strip()
    if not raw:
        return []
    lines = raw.splitlines()
    sections: list[tuple[str, str]] = []
    cur_title = "Kontext"
    cur_lines: list[str] = []

    def _flush() -> None:
        if len(sections) >= max(1, int(max_sections or 1)):
            return
        body = "\n".join(cur_lines).strip()
        if not body:
            return
        clipped = body[: max(300, int(max_section_chars or 2_200))]
        sections.append((str(cur_title or "Kontext").strip(), clipped))

    for line in lines:
        heading_match = _MARKDOWN_HEADING_RE.match(str(line or ""))
        if heading_match is not None:
            _flush()
            cur_title = str(heading_match.group("title") or "Kontext").strip() or "Kontext"
            cur_lines = [str(line or "").rstrip()]
            continue
        cur_lines.append(str(line or "").rstrip())
    _flush()
    if sections:
        return sections
    return [("Kontext", raw[: max(300, int(max_section_chars or 2_200))])]


def _build_focus_context(
    *,
    context_text: str,
    query: str,
    concepts: list[str],
    rag_snippets: list[str],
    max_chars: int = 12_000,
) -> tuple[str, list[str], list[str]]:
    sections = _split_markdown_sections(str(context_text or ""))
    query_tokens = _tokenize_words(" ".join([str(query or "")] + [str(c or "") for c in list(concepts or [])]))
    scored: list[tuple[float, int, str, str]] = []
    for idx, (title, body) in enumerate(sections):
        heading_tokens = _tokenize_words(title)
        body_preview = str(body or "")[:1200]
        body_tokens = _tokenize_words(body_preview)
        overlap = len(query_tokens & (heading_tokens | body_tokens))
        score = float(overlap * 3)
        if idx == 0:
            score += 1.0
        if overlap > 0 and len(body_preview) >= 200:
            score += 1.0
        scored.append((score, idx, title, body))
    scored.sort(key=lambda row: (row[0], -row[1]), reverse=True)

    selected_rows: list[tuple[int, str, str]] = []
    for score, idx, title, body in scored[:8]:
        _ = score
        selected_rows.append((idx, title, body))
    if not selected_rows and sections:
        selected_rows.append((0, sections[0][0], sections[0][1]))
    selected_rows.sort(key=lambda row: row[0])

    chosen_headings = _dedup_keep_order([title for _, title, _ in selected_rows], max_items=8)
    chosen_bodies = [body for _, _, body in selected_rows]
    chosen_concepts = _dedup_keep_order([str(c or "") for c in list(concepts or [])], max_items=7)
    chosen_snippets = _dedup_keep_order([str(s or "") for s in list(rag_snippets or [])], max_items=14)

    parts: list[str] = []
    if chosen_headings:
        parts.append("## Relevante Abschnitte")
        for heading in chosen_headings:
            parts.append(f"- {heading}")
    if chosen_concepts:
        parts.append("\n## Fokus-Konzepte")
        for concept in chosen_concepts:
            parts.append(f"- {concept}")
    if chosen_bodies:
        parts.append("\n## Kontextauszüge")
        for idx, body in enumerate(chosen_bodies[:6], 1):
            parts.append(f"[Auszug {idx}]\n{_clip_text(body, max_chars=1800)}")
    if chosen_snippets:
        parts.append("\n## Retrieval-Belege")
        for snippet in chosen_snippets[:8]:
            parts.append(f"- {_clip_text(snippet, max_chars=380)}")

    stitched = "\n".join(parts).strip()
    if not stitched:
        stitched = str(context_text or "").strip()
    return stitched[: max(2_000, int(max_chars or 12_000))], chosen_headings, chosen_concepts


def _build_structure_guidance(
    *,
    mode: str,
    query: str,
    headings: list[str],
    concepts: list[str],
    max_nodes: int,
    required_main_nodes: list[str] | None = None,
) -> str:
    is_graph = str(mode or "").strip().casefold() == "graph"
    root_hint = str(query or "").strip() or (headings[0] if headings else "Kernfrage")
    branches = _dedup_keep_order(
        [str(item or "") for item in list(concepts or []) + list(headings or [])],
        max_items=7,
    )
    if is_graph:
        lines = [
            "Leitplanken (Graph):",
            f"- Verwende maximal {max(4, int(max_nodes or 32))} Knoten.",
            "- Fokussiere auf zentrale Entitäten aus Frage/Kontext.",
            "- Relationen sollen präzise, kurz und semantisch sein.",
        ]
        if branches:
            lines.append("- Kandidaten-Entitäten: " + ", ".join(branches[:7]))
        return "\n".join(lines)

    lines = [
        "Leitplanken (MindMap):",
        f"- Wurzelknoten orientiert an: {root_hint}",
        "- 3 bis 7 Hauptäste, jeweils nur belegte Aspekte.",
        f"- Maximal {max(4, int(max_nodes or 32))} Knoten.",
    ]
    required_nodes = [str(x or "").strip() for x in list(required_main_nodes or []) if str(x or "").strip()]
    if required_nodes:
        lines.append("- Pflicht-Hauptäste (wenn im Kontext belegbar): " + ", ".join(required_nodes[:8]))
    if branches:
        lines.append("- Kandidaten für Hauptäste: " + ", ".join(branches[:7]))
    return "\n".join(lines)


def _extract_anchor_terms(
    *,
    query: str,
    headings: list[str],
    concepts: list[str],
    context_text: str,
    max_terms: int = 10,
) -> list[str]:
    seed = " ".join(
        [
            str(query or ""),
            "\n".join(str(x or "") for x in list(headings or [])[:8]),
            "\n".join(str(x or "") for x in list(concepts or [])[:8]),
            str(context_text or "")[:4_000],
        ]
    )
    tokens = [
        str(token or "").strip()
        for token in _WORD_TOKEN_RE.findall(seed)
    ]
    filtered: list[str] = []
    for token in tokens:
        key = token.casefold()
        if len(key) < 4 or key in _GROUNDING_STOPWORDS:
            continue
        filtered.append(token)
    return _dedup_keep_order(filtered, max_items=max_terms)


def _extract_pattern_keywords(texts: list[str], *, max_terms: int = 4, offset: int = 0) -> str:
    """Extract meaningful keywords from texts, returning a regex OR-pattern or single keyword.

    Used by heading_search and regex_search to build useful patterns instead of
    passing the raw full-sentence query (which matches nothing in headings).
    When max_terms=1, returns the keyword at position `offset` (for rotation).
    """
    words: list[str] = []
    seen: set[str] = set()
    for text in list(texts or []):
        for w in re.findall(r"[A-Za-z\u00C0-\u00D6\u00D8-\u00F6\u00F8-\u00FF]{4,}", str(text or "")):
            k = w.casefold()
            if k in _GROUNDING_STOPWORDS or k in seen:
                continue
            seen.add(k)
            words.append(w)
    if not words:
        first = str(texts[0] if texts else "").strip()
        return first[:40] if first else ""
    if max_terms == 1:
        return words[offset % len(words)]
    return "|".join(words[:max_terms])


def _extract_explicit_main_nodes(query: str, *, max_items: int = 8) -> list[str]:
    text = str(query or "").strip()
    if not text:
        return []
    lowered = text.casefold()
    marker = ""
    for candidate in ("hauptknoten:", "hauptknoten ", "main nodes:", "main node:"):
        idx = lowered.find(candidate)
        if idx >= 0:
            marker = text[idx + len(candidate):]
            break
    if not marker:
        return []
    rows = re.split(r"[,\n;|/]+", marker)
    cleaned: list[str] = []
    for row in rows:
        item = str(row or "").strip().strip("\"'").strip()
        item = re.sub(r"^[\-\*\d\.\)\s]+", "", item).strip()
        item = re.sub(r"[.;:!?]+$", "", item).strip()
        item = re.sub(r"\s+(und|and)\s+$", "", item, flags=re.IGNORECASE).strip()
        if len(item) < 2:
            continue
        cleaned.append(item)
    return _dedup_keep_order(cleaned, max_items=max_items)


def _label_matches_query_target(label: str, target: str) -> bool:
    a = _normalize_match_text(label)
    b = _normalize_match_text(target)
    if not a or not b:
        return False
    if a == b or a in b or b in a:
        return True
    a_tokens = _tokenize_words(a)
    b_tokens = _tokenize_words(b)
    if not a_tokens or not b_tokens:
        return False
    overlap = len(a_tokens & b_tokens)
    min_required = max(1, (min(len(a_tokens), len(b_tokens)) + 1) // 2)
    return overlap >= min_required


def _missing_required_main_nodes(markdown: str, required_nodes: list[str]) -> list[str]:
    required = _dedup_keep_order([str(x or "") for x in list(required_nodes or [])], max_items=16)
    if not required:
        return []
    spec = extract_graph_spec(str(markdown or ""))
    if spec is None or str(spec.kind or "").strip().casefold() != "mindmap":
        return required
    root_children_labels: list[str] = []
    all_labels: list[str] = []
    for node in list(dict(spec.nodes or {}).values()):
        label = str(getattr(node, "label", "") or "").strip()
        if label:
            all_labels.append(label)
    if spec.roots:
        root_id = str(spec.roots[0] or "").strip()
        root_node = dict(spec.nodes or {}).get(root_id)
        if root_node is not None:
            for child_id in list(getattr(root_node, "children", []) or []):
                child = dict(spec.nodes or {}).get(str(child_id or "").strip())
                child_label = str(getattr(child, "label", "") or "").strip() if child else ""
                if child_label:
                    root_children_labels.append(child_label)
    missing: list[str] = []
    for req in required:
        if any(_label_matches_query_target(lbl, req) for lbl in root_children_labels):
            continue
        if any(_label_matches_query_target(lbl, req) for lbl in all_labels):
            continue
        missing.append(req)
    return missing


def _node_label_merge_key(label: str) -> str:
    text = str(label or "").split("::", 1)[0].strip()
    text = re.sub(r"^[\-\*\d\.\)\s]+", "", text).strip()
    return _normalize_match_text(text)


def _clone_graph_spec(spec: GraphSpec) -> GraphSpec:
    return GraphSpec(
        kind=str(spec.kind or ""),
        title=str(spec.title or ""),
        nodes={
            str(node_id): GraphNode(
                node_id=str(node.node_id or node_id),
                label=str(node.label or ""),
                description=str(node.description or ""),
                quote=str(node.quote or ""),
                href=str(node.href or ""),
                children=list(node.children or []),
            )
            for node_id, node in dict(spec.nodes or {}).items()
        },
        roots=[str(x or "") for x in list(spec.roots or []) if str(x or "").strip()],
        edges=[
            GraphEdge(
                source_id=str(edge.source_id or ""),
                target_id=str(edge.target_id or ""),
                label=str(edge.label or ""),
            )
            for edge in list(spec.edges or [])
        ],
        default_collapsed_ids=set(str(x or "") for x in list(spec.default_collapsed_ids or set())),
    )


def _unique_node_id(preferred: str, used_ids: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", _normalize_match_text(preferred) or "node").strip("-") or "node"
    candidate = base
    suffix = 2
    while candidate in used_ids:
        candidate = f"{base}-{suffix}"
        suffix += 1
    used_ids.add(candidate)
    return candidate


def _rebuild_tree_edges(spec: GraphSpec) -> None:
    seen: set[tuple[str, str, str]] = set()
    edges: list[GraphEdge] = []
    for node_id, node in dict(spec.nodes or {}).items():
        for child_id in list(node.children or []):
            child = str(child_id or "").strip()
            if not child or child not in spec.nodes:
                continue
            key = (str(node_id), child, "")
            if key in seen:
                continue
            seen.add(key)
            edges.append(GraphEdge(source_id=str(node_id), target_id=child, label=""))
    for edge in list(spec.edges or []):
        src = str(edge.source_id or "").strip()
        dst = str(edge.target_id or "").strip()
        label = str(edge.label or "")
        if not src or not dst or src not in spec.nodes or dst not in spec.nodes:
            continue
        key = (src, dst, label)
        if key in seen:
            continue
        seen.add(key)
        edges.append(GraphEdge(source_id=src, target_id=dst, label=label))
    spec.edges = edges


def _merge_mindmap_specs(base_spec: GraphSpec, incoming_spec: GraphSpec, *, max_nodes: int) -> GraphSpec:
    merged = _clone_graph_spec(base_spec)
    if not merged.roots:
        return _clone_graph_spec(incoming_spec)
    if not incoming_spec.roots:
        _rebuild_tree_edges(merged)
        return merged

    used_ids = set(str(node_id or "") for node_id in dict(merged.nodes or {}).keys())
    base_root_id = str(merged.roots[0] or "").strip()
    incoming_root_ids = [str(x or "").strip() for x in list(incoming_spec.roots or []) if str(x or "").strip()]

    def _safe_fuzzy_merge_match(existing_label: str, incoming_label: str) -> bool:
        if not _label_matches_query_target(existing_label, incoming_label):
            return False
        existing_tokens = {
            tok for tok in _tokenize_words(existing_label)
            if tok and tok not in _GROUNDING_STOPWORDS
        }
        incoming_tokens = {
            tok for tok in _tokenize_words(incoming_label)
            if tok and tok not in _GROUNDING_STOPWORDS
        }
        if existing_tokens and incoming_tokens:
            overlap = existing_tokens & incoming_tokens
            min_size = min(len(existing_tokens), len(incoming_tokens))
            required = 1 if min_size <= 1 else min_size
            if len(overlap) < required:
                return False
        return True

    def _find_matching_child_id(parent_id: str, label: str) -> str:
        parent = dict(merged.nodes or {}).get(str(parent_id or "").strip())
        if parent is None:
            return ""
        wanted = _node_label_merge_key(label)
        if not wanted:
            return ""
        exact_matches: list[str] = []
        fuzzy_matches: list[str] = []
        for child_id in list(parent.children or []):
            child = dict(merged.nodes or {}).get(str(child_id or "").strip())
            if child is None:
                continue
            child_key = _node_label_merge_key(str(child.label or ""))
            if child_key == wanted:
                exact_matches.append(str(child_id))
                continue
            if _safe_fuzzy_merge_match(str(child.label or ""), label):
                fuzzy_matches.append(str(child_id))
        if exact_matches:
            return exact_matches[0]
        if fuzzy_matches:
            return fuzzy_matches[0]
        return ""

    def _clone_subtree(incoming_node_id: str) -> str:
        incoming_node = dict(incoming_spec.nodes or {}).get(str(incoming_node_id or "").strip())
        if incoming_node is None or len(merged.nodes) >= max(2, int(max_nodes or 32)):
            return ""
        preferred = str(incoming_node.node_id or "") or str(incoming_node.label or "") or "node"
        new_id = _unique_node_id(preferred, used_ids)
        merged.nodes[new_id] = GraphNode(
            node_id=new_id,
            label=str(incoming_node.label or ""),
            description=str(incoming_node.description or ""),
            quote=str(incoming_node.quote or ""),
            href=str(incoming_node.href or ""),
            children=[],
        )
        for child_id in list(incoming_node.children or []):
            child_new_id = _clone_subtree(str(child_id or ""))
            if child_new_id:
                merged.nodes[new_id].children.append(child_new_id)
        return new_id

    def _merge_into_parent(parent_id: str, incoming_node_id: str) -> None:
        incoming_node = dict(incoming_spec.nodes or {}).get(str(incoming_node_id or "").strip())
        if incoming_node is None:
            return
        existing_child_id = _find_matching_child_id(parent_id, str(incoming_node.label or ""))
        if existing_child_id:
            existing_node = dict(merged.nodes or {}).get(existing_child_id)
            if existing_node is None:
                return
            if not str(existing_node.quote or "").strip() and str(incoming_node.quote or "").strip():
                existing_node.quote = str(incoming_node.quote or "")
            if not str(existing_node.description or "").strip() and str(incoming_node.description or "").strip():
                existing_node.description = str(incoming_node.description or "")
            if not str(existing_node.href or "").strip() and str(incoming_node.href or "").strip():
                existing_node.href = str(incoming_node.href or "")
            for child_id in list(incoming_node.children or []):
                _merge_into_parent(existing_child_id, str(child_id or ""))
            return
        new_child_id = _clone_subtree(str(incoming_node_id or ""))
        if not new_child_id:
            return
        parent_node = dict(merged.nodes or {}).get(str(parent_id or "").strip())
        if parent_node is None:
            return
        if new_child_id not in list(parent_node.children or []):
            parent_node.children = list(parent_node.children or []) + [new_child_id]

    base_root = dict(merged.nodes or {}).get(base_root_id)
    if base_root is not None:
        incoming_root = dict(incoming_spec.nodes or {}).get(incoming_root_ids[0])
        if incoming_root is not None:
            if not str(base_root.label or "").strip() and str(incoming_root.label or "").strip():
                base_root.label = str(incoming_root.label or "")
            for child_id in list(incoming_root.children or []):
                _merge_into_parent(base_root_id, str(child_id or ""))
        for extra_root_id in incoming_root_ids[1:]:
            _merge_into_parent(base_root_id, extra_root_id)

    _rebuild_tree_edges(merged)
    return merged


def _grounding_issues_for_markdown(
    *,
    markdown: str,
    context_text: str,
    anchor_terms: list[str],
) -> tuple[list[str], dict[str, Any]]:
    issues: list[str] = []
    spec = extract_graph_spec(str(markdown or ""))
    parts: list[str] = []
    if spec is not None:
        parts.append(str(spec.title or ""))
        for node in list(dict(spec.nodes or {}).values()):
            parts.append(str(getattr(node, "label", "") or ""))
            quote = str(getattr(node, "quote", "") or "").strip()
            if quote:
                parts.append(quote)
    else:
        parts.append(str(markdown or ""))
    map_text = "\n".join(parts).strip()
    map_tokens = _tokenize_words(map_text)
    context_tokens = _tokenize_words(str(context_text or ""))
    overlap_ratio = 0.0
    if map_tokens:
        overlap_ratio = float(len(map_tokens & context_tokens)) / max(1.0, float(len(map_tokens)))
    if len(map_tokens) >= 8 and overlap_ratio < 0.08:
        issues.append(
            f"Geringe Kontextüberlappung ({overlap_ratio:.3f}) zwischen MindMap und Quelle."
        )
    anchor_hits: list[str] = []
    low_map = map_text.casefold()
    for token in list(anchor_terms or []):
        text = str(token or "").strip()
        if not text:
            continue
        if text.casefold() in low_map:
            anchor_hits.append(text)
    if anchor_terms and not anchor_hits and overlap_ratio < 0.20:
        issues.append("Kein dokumentnaher Ankerbegriff in der MindMap gefunden.")
    return issues, {
        "overlap_ratio": round(overlap_ratio, 5),
        "anchor_terms": list(anchor_terms or []),
        "anchor_hits": anchor_hits[:12],
        "map_token_count": len(map_tokens),
        "context_token_count": len(context_tokens),
    }


def _map_validation_limits(*, mode: str, max_nodes: int) -> GraphValidationLimits:
    bounded_nodes = max(4, min(1_024, int(max_nodes or 32)))
    is_graph = str(mode or "").strip().casefold() == "graph"
    if is_graph:
        return GraphValidationLimits(
            min_nodes=2,
            max_nodes=bounded_nodes,
            max_edges=max(16, bounded_nodes * 6),
            max_depth=64,
            require_single_root=False,
            allow_cycles=True,
            max_isolated_nodes=bounded_nodes,
            require_connected=False,
            min_word_letters=2,
        )
    return GraphValidationLimits(
        min_nodes=2,
        max_nodes=bounded_nodes,
        max_edges=max(16, bounded_nodes * 4),
        max_depth=32,
        require_single_root=True,
        allow_cycles=False,
        max_isolated_nodes=max(4, bounded_nodes // 2),
        require_connected=True,
        min_word_letters=2,
    )


def _normalize_and_validate_map_markdown(
    *,
    markdown: str,
    mode: str,
    max_nodes: int,
) -> tuple[str, dict[str, Any], list[str]]:
    raw = str(markdown or "").strip()
    expected_kind = "graph" if str(mode or "").strip().casefold() == "graph" else "mindmap"
    structure_payload: dict[str, Any] = {
        "ok": False,
        "expected_kind": expected_kind,
        "structure_check": {
            "node_count": 0,
            "edge_count": 0,
            "component_count": 0,
            "root_count": 0,
            "isolated_count": 0,
            "max_depth": 0,
        },
    }
    if not raw:
        return "", structure_payload, ["Leere Modellausgabe: kein MindMap/Graph-Markdown vorhanden."]

    spec = extract_graph_spec(raw)
    if spec is None:
        return (
            "",
            structure_payload,
            [
                "Ungültige Struktur: Ausgabe enthält keinen parsebaren ```mindmap```/```graph```-Block.",
            ],
        )
    if str(spec.kind or "").strip().casefold() != expected_kind:
        return (
            "",
            structure_payload,
            [
                f"Ungültiger Strukturtyp: erwartet '{expected_kind}', erhalten '{spec.kind}'.",
            ],
        )

    limits = _map_validation_limits(mode=expected_kind, max_nodes=max_nodes)
    report = validate_graph_spec(spec, limits=limits)
    stats = dict(report.stats or {})
    root_label = ""
    primary_children: list[str] = []
    if spec.roots:
        root_id = str(spec.roots[0] or "").strip()
        root_node = dict(spec.nodes or {}).get(root_id)
        if root_node is not None:
            root_label = str(getattr(root_node, "label", "") or "").strip()
            for child_id in list(getattr(root_node, "children", []) or [])[:6]:
                child = dict(spec.nodes or {}).get(str(child_id or "").strip())
                child_label = str(getattr(child, "label", "") or "").strip() if child else ""
                if child_label:
                    primary_children.append(child_label)

    structure_payload = {
        "ok": bool(report.ok),
        "expected_kind": expected_kind,
        "kind": str(spec.kind or expected_kind),
        "title": str(spec.title or ""),
        "root_label": root_label,
        "primary_children": primary_children,
        "stats": stats,
        "issues": [issue.to_dict() for issue in list(report.issues or [])],
        "structure_check": {
            "node_count": int(stats.get("nodes", 0) or 0),
            "edge_count": int(stats.get("edges", 0) or 0),
            "component_count": int(stats.get("components", 0) or 0),
            "root_count": int(stats.get("roots", 0) or 0),
            "isolated_count": int(stats.get("isolated_nodes", 0) or 0),
            "max_depth": int(stats.get("max_depth", 0) or 0),
        },
    }
    if not report.ok:
        errors = [
            f"[{str(issue.code or 'validation')}] {str(issue.message or '').strip()}"
            for issue in list(report.issues or [])[:12]
            if str(issue.message or "").strip()
        ]
        if not errors:
            errors = ["Strukturvalidierung fehlgeschlagen."]
        return "", structure_payload, errors

    return spec_to_markdown(spec), structure_payload, []


class AgenticWorkflowService:
    """Pure LangGraph orchestration for chat/canvas/factcheck/mindmap/graph."""

    def __init__(
        self,
        *,
        repo_root=None,
        registry=None,
        plugin_manager: Any = None,
    ) -> None:
        _ = repo_root, registry
        self._plugin_manager = plugin_manager
        if self._plugin_manager is None:
            root = Path(repo_root or Path(__file__).resolve().parents[3])
            plugins_root = root / "plugins"
            manager = PluginManager(root_dir=plugins_root)
            manager.load_all()
            self._plugin_manager = manager

    @staticmethod
    def _require_langgraph() -> None:
        if _LANGGRAPH_AVAILABLE and StateGraph is not None:
            return
        raise RuntimeError(
            "LangGraph is required for agentic workflows. "
            "Install LangGraph in the local environment to run this workflow."
        )

    def run(
        self,
        *,
        workflow_id: str,
        request: dict[str, Any],
        profile_id: str = "",
        tools: dict[str, Any] | None = None,
    ) -> WorkflowRunResult:
        wid = str(workflow_id or "").strip().casefold()
        if wid == "chat_v2":
            return self.run_chat(request=request, tools=tools, profile_id=profile_id, enabled=True)
        if wid == "canvas_v2":
            return self.run_canvas(request=request, tools=tools, profile_id=profile_id, enabled=True)
        if wid == "factcheck_v2":
            return self.run_factcheck(request=request, tools=tools, profile_id=profile_id, enabled=True)
        if wid == "mindmap_v2":
            return self.run_mindmap(request=request, tools=tools, profile_id=profile_id, enabled=True)
        if wid == "graph_v2":
            return self.run_graph(request=request, tools=tools, profile_id=profile_id, enabled=True)
        return WorkflowRunResult(
            ok=False,
            workflow_id=str(workflow_id or ""),
            profile_id=str(profile_id or ""),
            result={},
            state=dict(request or {}),
            trace=[],
            errors=[f"Unknown workflow_id: {workflow_id}"],
            metrics={},
        )

    def run_factcheck(
        self,
        *,
        request: dict[str, Any],
        tools: dict[str, Any] | None = None,
        profile_id: str = "factcheck_v2_local",
        enabled: bool | None = None,
    ) -> WorkflowRunResult:
        if enabled is False:
            raise RuntimeError("Factcheck workflow disabled.")
        self._require_langgraph()
        return self._run_factcheck_graph(
            request=dict(request or {}),
            tools=dict(tools or {}),
            profile_id=str(profile_id or ""),
        )

    def run_chat(
        self,
        *,
        request: dict[str, Any],
        tools: dict[str, Any] | None = None,
        profile_id: str = "chat_v2_local",
        enabled: bool | None = None,
    ) -> WorkflowRunResult:
        if enabled is False:
            raise RuntimeError("Chat workflow disabled.")
        self._require_langgraph()
        return self._run_chat_graph(
            request=dict(request or {}),
            tools=dict(tools or {}),
            profile_id=str(profile_id or ""),
        )

    def run_canvas(
        self,
        *,
        request: dict[str, Any],
        tools: dict[str, Any] | None = None,
        profile_id: str = "canvas_v2_local",
        enabled: bool | None = None,
    ) -> WorkflowRunResult:
        if enabled is False:
            raise RuntimeError("Canvas workflow disabled.")
        self._require_langgraph()
        return self._run_canvas_graph(
            request=dict(request or {}),
            tools=dict(tools or {}),
            profile_id=str(profile_id or ""),
        )

    def run_mindmap(
        self,
        *,
        request: dict[str, Any],
        tools: dict[str, Any] | None = None,
        profile_id: str = "mindmap_v2_local",
        enabled: bool | None = None,
    ) -> WorkflowRunResult:
        if enabled is False:
            raise RuntimeError("Mindmap workflow disabled.")
        self._require_langgraph()
        return self._run_map_graph(
            request=dict(request or {}),
            tools=dict(tools or {}),
            profile_id=str(profile_id or ""),
            mode="mindmap",
            workflow_id="mindmap_v2",
        )

    def run_graph(
        self,
        *,
        request: dict[str, Any],
        tools: dict[str, Any] | None = None,
        profile_id: str = "graph_v2_local",
        enabled: bool | None = None,
    ) -> WorkflowRunResult:
        if enabled is False:
            raise RuntimeError("Graph workflow disabled.")
        self._require_langgraph()
        return self._run_map_graph(
            request=dict(request or {}),
            tools=dict(tools or {}),
            profile_id=str(profile_id or ""),
            mode="graph",
            workflow_id="graph_v2",
        )

    def _run_chat_graph(
        self,
        *,
        request: dict[str, Any],
        tools: dict[str, Any],
        profile_id: str,
    ) -> WorkflowRunResult:
        traces: list[StepTrace] = []
        t0 = time.perf_counter()
        llm = _tool(tools, "llm.generate")
        rag = _tool(tools, "rag.search")
        plugin = self._plugin_manager

        def retrieve(state: dict[str, Any]) -> dict[str, Any]:
            st = time.perf_counter()
            q = str(state.get("question", "") or "")
            hits: list[str] = []
            if callable(rag):
                try:
                    hits = list(rag(query=q, top_k=6) or [])
                except Exception:
                    hits = []
            output = {"retrieval_hits": hits}
            traces.append(
                StepTrace(
                    step_id="retrieve",
                    status="ok",
                    duration_ms=(time.perf_counter() - st) * 1000.0,
                    output=output,
                )
            )
            return output

        def draft(state: dict[str, Any]) -> dict[str, Any]:
            st = time.perf_counter()
            q = str(state.get("question", "") or "")
            hits = list(state.get("retrieval_hits", []) or [])
            prompt = _render_prompt(
                "Frage:\n{question}\n\nKontext:\n{context}",
                question=q,
                context="\n".join(str(x) for x in hits[:8]),
            )
            answer = ""
            if callable(llm):
                try:
                    answer = str(llm(prompt=prompt) or "")
                except Exception:
                    answer = ""
            if plugin is not None:
                payload = plugin.run_hook("graph.chat.after_draft", {"answer": answer, "hits": hits, "question": q})
                answer = str(payload.get("answer", answer) or answer)
            output = {"draft_answer": answer}
            traces.append(
                StepTrace(
                    step_id="draft",
                    status="ok",
                    duration_ms=(time.perf_counter() - st) * 1000.0,
                    output={"answer_len": len(answer)},
                )
            )
            return output

        graph = StateGraph(dict)
        graph.add_node("retrieve", retrieve)
        graph.add_node("draft", draft)
        graph.add_edge(START, "retrieve")
        graph.add_edge("retrieve", "draft")
        graph.add_edge("draft", END)
        compiled = graph.compile()
        final_state = compiled.invoke({"question": str(request.get("question", "") or "")})
        answer = str(final_state.get("draft_answer", "") or "")
        citations = list(final_state.get("retrieval_hits", []) or [])[:5]
        state = dict(final_state)
        result = {"response": {"text": answer, "citations": citations}}
        metrics = self._metrics("chat_v2", t0, traces)
        return WorkflowRunResult(
            ok=True,
            workflow_id="chat_v2",
            profile_id=profile_id,
            result=result,
            state=state,
            trace=traces,
            errors=[],
            metrics=metrics,
        )

    def _run_canvas_graph(
        self,
        *,
        request: dict[str, Any],
        tools: dict[str, Any],
        profile_id: str,
    ) -> WorkflowRunResult:
        traces: list[StepTrace] = []
        t0 = time.perf_counter()
        llm = _tool(tools, "llm.generate")
        apply_fn = _tool(tools, "canvas.apply")

        def draft(state: dict[str, Any]) -> dict[str, Any]:
            st = time.perf_counter()
            instruction = str(state.get("instruction", "") or "")
            selected = str(state.get("selected_text", "") or "")
            prompt = _render_prompt(
                (
                    "Anweisung:\n{instruction}\n\n"
                    "Zu ersetzender Text:\n{selected_text}\n\n"
                    "Gib nur den finalen Ersatztext zurueck, eingerahmt:\n"
                    "[[CANVAS_REWRITE]]\n...\n[[/CANVAS_REWRITE]]"
                ),
                instruction=instruction,
                selected_text=selected,
            )
            text = ""
            if callable(llm):
                text = str(llm(prompt=prompt) or "")
            traces.append(
                StepTrace(
                    step_id="draft_patch",
                    status="ok",
                    duration_ms=(time.perf_counter() - st) * 1000.0,
                    output={"text_len": len(text)},
                )
            )
            return {"draft_text": text}

        def apply(state: dict[str, Any]) -> dict[str, Any]:
            st = time.perf_counter()
            text = str(state.get("draft_text", "") or "")
            if callable(apply_fn):
                apply_fn(text=text)
            traces.append(
                StepTrace(
                    step_id="apply_patch",
                    status="ok",
                    duration_ms=(time.perf_counter() - st) * 1000.0,
                    output={"applied": True},
                )
            )
            return {"applied_text": text}

        initial_state = {
            "instruction": str(request.get("instruction", "") or ""),
            "selected_text": str(request.get("selected_text", "") or ""),
        }
        graph = StateGraph(dict)
        graph.add_node("draft_patch", draft)
        graph.add_node("apply_patch", apply)
        graph.add_edge(START, "draft_patch")
        graph.add_edge("draft_patch", "apply_patch")
        graph.add_edge("apply_patch", END)
        compiled = graph.compile()
        final_state = compiled.invoke(initial_state)
        result_text = str(final_state.get("applied_text", "") or "")
        metrics = self._metrics("canvas_v2", t0, traces)
        return WorkflowRunResult(
            ok=True,
            workflow_id="canvas_v2",
            profile_id=profile_id,
            result={"markdown": result_text, "response": {"text": result_text}},
            state=dict(final_state),
            trace=traces,
            errors=[],
            metrics=metrics,
        )

    def _run_factcheck_graph(
        self,
        *,
        request: dict[str, Any],
        tools: dict[str, Any],
        profile_id: str,
    ) -> WorkflowRunResult:
        traces: list[StepTrace] = []
        t0 = time.perf_counter()
        rag = _tool(tools, "rag.search")
        nli = _tool(tools, "nli.verify")
        source_text = str(request.get("c", "") or "")
        seed_rows = list(dict(request.get("o", {}) or {}).get("rows", []) or [])

        def extract(state: dict[str, Any]) -> dict[str, Any]:
            st = time.perf_counter()
            claims = [line.strip() for line in source_text.replace("\n", " ").split(".") if line.strip()]
            traces.append(
                StepTrace(
                    step_id="extract_claims",
                    status="ok",
                    duration_ms=(time.perf_counter() - st) * 1000.0,
                    output={"count": len(claims)},
                )
            )
            return {"claims": claims}

        def verify(state: dict[str, Any]) -> dict[str, Any]:
            st = time.perf_counter()
            claims = list(state.get("claims", []) or [])
            out_rows = [dict(row) for row in seed_rows]
            for claim in claims:
                evidences: list[str] = []
                if callable(rag):
                    try:
                        evidences = list(rag(query=claim, top_k=3) or [])
                    except Exception:
                        evidences = []
                label = "unconfirmed"
                if evidences and callable(nli):
                    try:
                        verdict = dict(nli(premise=evidences[0], hypothesis=claim) or {})
                        mapped = str(verdict.get("label", "") or "").strip().casefold()
                        if mapped == "entailment":
                            label = "confirmed"
                        elif mapped == "contradiction":
                            label = "contradiction"
                        else:
                            label = "partial"
                    except Exception:
                        label = "partial" if evidences else "unconfirmed"
                elif evidences:
                    label = "partial"
                out_rows.append(
                    {
                        "fact": claim,
                        "status": label,
                        "evidence": evidences[0] if evidences else "",
                    }
                )
            traces.append(
                StepTrace(
                    step_id="verify_claims",
                    status="ok",
                    duration_ms=(time.perf_counter() - st) * 1000.0,
                    output={"rows": len(out_rows)},
                )
            )
            return {"rows": out_rows}

        graph = StateGraph(dict)
        graph.add_node("extract_claims", extract)
        graph.add_node("verify_claims", verify)
        graph.add_edge(START, "extract_claims")
        graph.add_edge("extract_claims", "verify_claims")
        graph.add_edge("verify_claims", END)
        compiled = graph.compile()
        final_state = compiled.invoke({})
        rows = list(final_state.get("rows", []) or [])
        metrics = self._metrics("factcheck_v2", t0, traces)
        return WorkflowRunResult(
            ok=True,
            workflow_id="factcheck_v2",
            profile_id=profile_id,
            result={"o": rows, "response": {"text": "Factcheck complete.", "rows": rows}},
            state=dict(final_state),
            trace=traces,
            errors=[],
            metrics=metrics,
        )

    def _run_map_graph(
        self,
        *,
        request: dict[str, Any],
        tools: dict[str, Any],
        profile_id: str,
        mode: str,
        workflow_id: str,
    ) -> WorkflowRunResult:
        return self._run_mindmap_pipeline(
            request=request,
            tools=tools,
            profile_id=profile_id,
            mode=mode,
            workflow_id=workflow_id,
        )

    def _run_mindmap_pipeline(
        self,
        *,
        request: dict[str, Any],
        tools: dict[str, Any],
        profile_id: str,
        mode: str,
        workflow_id: str,
    ) -> WorkflowRunResult:
        """Agent-based MindMap/Graph-Pipeline. Delegiert an _mindmap_pipeline.py."""
        return _run_mindmap_pipeline_impl(
            request=request,
            tools=tools,
            mode=mode,
            workflow_id=workflow_id,
            profile_id=profile_id,
        )

    @staticmethod
    def _metrics(workflow_id: str, t0: float, trace: list[StepTrace]) -> dict[str, Any]:
        tracing_enabled = langsmith_tracing_enabled()
        duration_ms = round((time.perf_counter() - t0) * 1000.0, 3)
        return {
            "workflow_id": str(workflow_id or ""),
            "duration_ms": duration_ms,
            "elapsed_ms": duration_ms,
            "steps": len(trace),
            "langgraph_available": bool(_LANGGRAPH_AVAILABLE),
            "langchain_prompt_templates": bool(_LANGCHAIN_PROMPTS_AVAILABLE),
            "langchain_json_parser": bool(_LANGCHAIN_JSON_PARSER_AVAILABLE),
            "langsmith_tracing": bool(tracing_enabled),
            "langsmith_project": str(os.environ.get("LANGSMITH_PROJECT", "") or ""),
        }
