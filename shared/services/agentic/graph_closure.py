"""Utilities for robust graph closure and cleanup in agentic workflows."""
from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
import re
import unicodedata

from shared.domain.graph_spec import GraphEdge, GraphNode, GraphSpec

_JSON_KV_RE = re.compile(
    r'^"?(?P<key>[A-Za-z_][A-Za-z0-9_\- ]*)"?\s*:\s*"?(?P<val>[^"\n]+)"?\s*,?$'
)
_FIELD_PREFIX_RE = re.compile(
    r'^\s*-?\s*(?P<key>text|label|title|name)\s*:\s*(?P<val>.+?)\s*$',
    flags=re.IGNORECASE,
)
_WORD_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]+")
_STRUCTURAL_ONLY_KEYS = {
    "type",
    "title",
    "nodes",
    "edges",
    "children",
    "id",
    "label",
    "name",
    "text",
    "from",
    "to",
    "source",
    "target",
}


@dataclass(slots=True, frozen=True)
class GraphCleanupInfo:
    removed_nodes: int = 0
    renamed_nodes: int = 0
    merged_nodes: int = 0


def _slug(value: str) -> str:
    out = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().casefold()).strip("-")
    return out or "node"


def _contains_word_like_text(text: str, *, min_letters: int) -> bool:
    required = max(1, int(min_letters))
    for token in _WORD_RE.findall(str(text or "")):
        if len(str(token or "")) >= required:
            return True
    return False


def _ascii_fold(text: str) -> str:
    raw = unicodedata.normalize("NFKD", str(text or "").casefold())
    return "".join(ch for ch in raw if not unicodedata.combining(ch))


def _normalize_token(token: str) -> str:
    out = re.sub(r"[^a-z0-9]+", "", _ascii_fold(token))
    if len(out) <= 3:
        return out
    for suffix in ("ing", "ern", "erns", "ers", "er", "es", "en", "e", "s", "n"):
        if out.endswith(suffix) and len(out) - len(suffix) >= 3:
            return out[: -len(suffix)]
    return out


def _label_fingerprint(text: str) -> tuple[str, ...]:
    tokens = [
        _normalize_token(token)
        for token in _WORD_RE.findall(_ascii_fold(text))
    ]
    filtered = [token for token in tokens if len(token) >= 3]
    return tuple(sorted(dict.fromkeys(filtered)))


def _label_signature(text: str) -> str:
    return " ".join(_label_fingerprint(text))


def label_fingerprint(text: str) -> tuple[str, ...]:
    """Public wrapper used by validators and candidate review."""
    return _label_fingerprint(text)


def _labels_equivalent(left: str, right: str) -> bool:
    left_clean = str(left or "").strip()
    right_clean = str(right or "").strip()
    if not left_clean or not right_clean:
        return False
    if left_clean.casefold() == right_clean.casefold():
        return True
    left_sig = _label_signature(left_clean)
    right_sig = _label_signature(right_clean)
    if left_sig and left_sig == right_sig:
        return True
    left_fp = set(_label_fingerprint(left_clean))
    right_fp = set(_label_fingerprint(right_clean))
    if left_fp and right_fp:
        overlap = len(left_fp & right_fp)
        if overlap == len(left_fp) == len(right_fp):
            return True
        if overlap >= 2 and overlap == min(len(left_fp), len(right_fp)):
            return True
    left_norm = re.sub(r"\s+", " ", _ascii_fold(left_clean)).strip()
    right_norm = re.sub(r"\s+", " ", _ascii_fold(right_clean)).strip()
    if not left_norm or not right_norm:
        return False
    return SequenceMatcher(a=left_norm, b=right_norm).ratio() >= 0.94


def _prefer_label(current: str, candidate: str) -> str:
    current_clean = str(current or "").strip()
    candidate_clean = str(candidate or "").strip()
    if not current_clean:
        return candidate_clean
    if not candidate_clean:
        return current_clean
    current_fp = _label_fingerprint(current_clean)
    candidate_fp = _label_fingerprint(candidate_clean)
    if len(candidate_fp) > len(current_fp):
        return candidate_clean
    if len(candidate_fp) == len(current_fp) and len(candidate_clean) > len(current_clean):
        return candidate_clean
    return current_clean


def _merge_text_field(current: str, candidate: str) -> str:
    current_clean = str(current or "").strip()
    candidate_clean = str(candidate or "").strip()
    if not current_clean:
        return candidate_clean
    if not candidate_clean:
        return current_clean
    if len(candidate_clean) > len(current_clean):
        return candidate_clean
    return current_clean


def _clean_label(raw: str, *, min_word_letters: int = 3) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    text = text.replace('\\"', '"').replace("\\n", " ").replace("\\t", " ").strip()

    # Trim obvious JSON/punctuation wrappers.
    text = text.strip().strip("\"'").strip()
    text = text.rstrip(",;").strip()

    # Common structural artifacts from malformed JSON/markdown output.
    if text in {"{", "}", "[", "]", "(", ")", "-", ",", ":", "::", "```"}:
        return ""
    bare_key = str(text or "").strip().strip("\"'").strip().rstrip(":").strip().casefold()
    if bare_key in _STRUCTURAL_ONLY_KEYS:
        return ""

    field_match = _FIELD_PREFIX_RE.match(text)
    if field_match is not None:
        val = str(field_match.group("val") or "").strip().strip("\"'").strip()
        return val if _contains_word_like_text(val, min_letters=min_word_letters) else ""

    match = _JSON_KV_RE.match(text)
    if match is not None:
        key = str(match.group("key") or "").strip().casefold()
        val = str(match.group("val") or "").strip().strip("\"'").strip().rstrip(",;")
        if key in {"relation", "predicate", "edge", "type"}:
            return ""
        if key in {"source", "target", "node", "id", "label", "name", "entity", "concept", "topic"}:
            return (
                val
                if _contains_word_like_text(val, min_letters=min_word_letters)
                else ""
            )
        return (
            val
            if _contains_word_like_text(val, min_letters=min_word_letters)
            else ""
        )

    if not re.search(r"[A-Za-z0-9]", text):
        return ""
    if not _contains_word_like_text(text, min_letters=min_word_letters):
        return ""

    return text


def _undirected_neighbors(spec: GraphSpec) -> dict[str, set[str]]:
    neighbors: dict[str, set[str]] = {
        str(node_id): set()
        for node_id in dict(spec.nodes or {}).keys()
        if str(node_id or "").strip()
    }
    for node_id, node in dict(spec.nodes or {}).items():
        src = str(node_id or "").strip()
        if not src or src not in neighbors:
            continue
        for child in list(getattr(node, "children", []) or []):
            dst = str(child or "").strip()
            if dst and dst in neighbors:
                neighbors[src].add(dst)
                neighbors[dst].add(src)
    for edge in list(spec.edges or []):
        src = str(getattr(edge, "source_id", "") or "").strip()
        dst = str(getattr(edge, "target_id", "") or "").strip()
        if src and dst and src in neighbors and dst in neighbors:
            neighbors[src].add(dst)
            neighbors[dst].add(src)
    return neighbors


def component_groups(spec: GraphSpec) -> list[list[str]]:
    neighbors = _undirected_neighbors(spec)
    if not neighbors:
        return []
    groups: list[list[str]] = []
    seen: set[str] = set()
    for start in sorted(neighbors.keys()):
        if start in seen:
            continue
        stack = [start]
        seen.add(start)
        group: list[str] = []
        while stack:
            node_id = stack.pop()
            group.append(node_id)
            for nxt in sorted(neighbors.get(node_id, set())):
                if nxt in seen:
                    continue
                seen.add(nxt)
                stack.append(nxt)
        groups.append(sorted(group))
    groups.sort(key=lambda row: (-len(row), row[0] if row else ""))
    return groups


def component_overview_text(spec: GraphSpec) -> str:
    groups = component_groups(spec)
    if not groups:
        return "Keine Komponenten ermittelt."
    lines: list[str] = []
    for idx, group in enumerate(groups[:8], 1):
        labels: list[str] = []
        for node_id in group[:8]:
            node = dict(spec.nodes or {}).get(node_id)
            label = str(getattr(node, "label", "") or node_id).strip() or node_id
            labels.append(f"{node_id} ({label})")
        suffix = " ..." if len(group) > 8 else ""
        lines.append(
            f"- Komponente {idx}: {len(group)} Knoten -> " + ", ".join(labels) + suffix
        )
    if len(groups) > 8:
        lines.append(f"- Weitere Komponenten: {len(groups) - 8}")
    return "\n".join(lines)


def sanitize_graph_spec(
    spec: GraphSpec,
    *,
    min_word_letters: int = 3,
    merge_similar_nodes: bool | None = None,
) -> tuple[GraphSpec, GraphCleanupInfo]:
    used_ids: set[str] = set()
    old_to_new: dict[str, str] = {}
    new_nodes: dict[str, GraphNode] = {}
    removed_nodes = 0
    renamed_nodes = 0
    merged_nodes = 0
    merge_enabled = bool(
        str(spec.kind or "").strip().casefold() in {"mindmap", "chunkmap"}
        if merge_similar_nodes is None
        else merge_similar_nodes
    )

    def alloc(candidate: str) -> str:
        base = _slug(candidate)
        out = base
        idx = 2
        while out in used_ids:
            out = f"{base}-{idx}"
            idx += 1
        used_ids.add(out)
        return out

    for old_id in sorted(dict(spec.nodes or {}).keys()):
        node = dict(spec.nodes or {}).get(old_id)
        if node is None:
            continue
        raw_id = str(getattr(node, "node_id", old_id) or "").strip()
        raw_label = str(getattr(node, "label", "") or "").strip()
        cleaned_label = _clean_label(
            raw_label,
            min_word_letters=max(1, int(min_word_letters)),
        )
        if not cleaned_label:
            removed_nodes += 1
            continue

        if merge_enabled:
            duplicate_id = ""
            for new_id, existing in dict(new_nodes or {}).items():
                if _labels_equivalent(cleaned_label, str(getattr(existing, "label", "") or "")):
                    duplicate_id = str(new_id or "")
                    break
            if duplicate_id:
                old_to_new[str(old_id)] = duplicate_id
                if raw_id and raw_id != str(old_id):
                    old_to_new[raw_id] = duplicate_id
                existing = new_nodes[duplicate_id]
                existing.label = _prefer_label(existing.label, cleaned_label)
                existing.description = _merge_text_field(
                    existing.description,
                    str(getattr(node, "description", "") or "").strip(),
                )
                existing.quote = _merge_text_field(
                    existing.quote,
                    str(getattr(node, "quote", "") or "").strip(),
                )
                existing.href = _merge_text_field(
                    existing.href,
                    str(getattr(node, "href", "") or "").strip(),
                )
                merged_nodes += 1
                continue

        wanted_id = raw_id if re.search(r"[A-Za-z0-9]", raw_id) else ""
        new_id = alloc(wanted_id or cleaned_label)
        if new_id != raw_id:
            renamed_nodes += 1
        old_to_new[str(old_id)] = new_id
        if raw_id and raw_id != str(old_id):
            old_to_new[raw_id] = new_id

        new_nodes[new_id] = GraphNode(
            node_id=new_id,
            label=cleaned_label,
            description=str(getattr(node, "description", "") or "").strip(),
            quote=str(getattr(node, "quote", "") or "").strip(),
            href=str(getattr(node, "href", "") or "").strip(),
            children=[],
        )

    if not new_nodes:
        empty = GraphSpec(
            kind=str(spec.kind or "graph"),
            title=str(spec.title or "Graph"),
            nodes={},
            roots=[],
            edges=[],
            default_collapsed_ids=set(),
        )
        return empty, GraphCleanupInfo(
            removed_nodes=removed_nodes,
            renamed_nodes=renamed_nodes,
        )

    edge_seen: set[tuple[str, str, str]] = set()
    new_edges: list[GraphEdge] = []
    explicit_pairs: set[tuple[str, str]] = set()

    def add_edge(src_raw: str, dst_raw: str, label: str = "") -> None:
        src = old_to_new.get(str(src_raw or ""), "")
        dst = old_to_new.get(str(dst_raw or ""), "")
        if not src or not dst or src not in new_nodes or dst not in new_nodes:
            return
        if src == dst and str(src_raw or "").strip() != str(dst_raw or "").strip():
            return
        clean_label = str(label or "").strip()
        key = (src, dst, clean_label)
        if key in edge_seen:
            return
        edge_seen.add(key)
        new_edges.append(GraphEdge(source_id=src, target_id=dst, label=clean_label))
        if src != dst and dst not in new_nodes[src].children:
            new_nodes[src].children.append(dst)

    for edge in list(spec.edges or []):
        src = old_to_new.get(str(getattr(edge, "source_id", "") or ""), "")
        dst = old_to_new.get(str(getattr(edge, "target_id", "") or ""), "")
        if src and dst:
            explicit_pairs.add((src, dst))

    for node in list(dict(spec.nodes or {}).values()):
        src_old = str(getattr(node, "node_id", "") or "")
        for child in list(getattr(node, "children", []) or []):
            src = old_to_new.get(src_old, "")
            dst = old_to_new.get(str(child or ""), "")
            if src and dst and (src, dst) in explicit_pairs:
                continue
            add_edge(src_old, str(child or ""), "")

    for edge in list(spec.edges or []):
        add_edge(
            str(getattr(edge, "source_id", "") or ""),
            str(getattr(edge, "target_id", "") or ""),
            str(getattr(edge, "label", "") or ""),
        )

    incoming: set[str] = {str(edge.target_id) for edge in new_edges if str(edge.target_id)}
    roots: list[str] = []
    seen_roots: set[str] = set()
    for root in list(spec.roots or []):
        node_id = old_to_new.get(str(root or ""), "")
        if not node_id or node_id in seen_roots:
            continue
        seen_roots.add(node_id)
        roots.append(node_id)
    if not roots:
        roots = [node_id for node_id in sorted(new_nodes.keys()) if node_id not in incoming]
    if not roots:
        roots = [sorted(new_nodes.keys())[0]]

    cleaned = GraphSpec(
        kind=str(spec.kind or "graph"),
        title=str(spec.title or "Graph"),
        nodes=new_nodes,
        roots=roots,
        edges=new_edges,
        default_collapsed_ids=set(),
    )
    return cleaned, GraphCleanupInfo(
        removed_nodes=removed_nodes,
        renamed_nodes=renamed_nodes,
        merged_nodes=merged_nodes,
    )


def connect_components_minimally(
    spec: GraphSpec,
    *,
    edge_label: str = "bridge",
) -> tuple[GraphSpec, int]:
    groups = component_groups(spec)
    if len(groups) <= 1:
        return spec, 0

    nodes = {
        str(node_id): GraphNode(
            node_id=str(node.node_id),
            label=str(node.label),
            description=str(node.description or ""),
            quote=str(node.quote or ""),
            href=str(node.href or ""),
            children=list(node.children or []),
        )
        for node_id, node in dict(spec.nodes or {}).items()
    }
    edges = [
        GraphEdge(
            source_id=str(edge.source_id),
            target_id=str(edge.target_id),
            label=str(edge.label or ""),
        )
        for edge in list(spec.edges or [])
    ]
    seen = {
        (str(edge.source_id), str(edge.target_id), str(edge.label or ""))
        for edge in edges
    }

    added = 0
    reps = [group[0] for group in groups if group]
    for idx in range(1, len(reps)):
        src = str(reps[idx - 1] or "")
        dst = str(reps[idx] or "")
        if not src or not dst or src == dst or src not in nodes or dst not in nodes:
            continue
        key = (src, dst, str(edge_label or "").strip())
        if key in seen:
            continue
        seen.add(key)
        edges.append(GraphEdge(source_id=src, target_id=dst, label=str(edge_label or "").strip()))
        if dst not in nodes[src].children:
            nodes[src].children.append(dst)
        added += 1

    incoming: set[str] = {str(edge.target_id) for edge in edges if str(edge.target_id)}
    roots = [node_id for node_id in sorted(nodes.keys()) if node_id not in incoming]
    if not roots:
        roots = [sorted(nodes.keys())[0]]

    out = GraphSpec(
        kind=str(spec.kind or "graph"),
        title=str(spec.title or "Graph"),
        nodes=nodes,
        roots=roots,
        edges=edges,
        default_collapsed_ids=set(spec.default_collapsed_ids or set()),
    )
    return out, int(added)
