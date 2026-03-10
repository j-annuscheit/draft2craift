"""Parser/serializer for structured graph markdown blocks."""
from __future__ import annotations

import json
import re
from typing import Any

from shared.domain.graph_spec import GraphEdge, GraphNode, GraphSpec

_FENCED_BLOCK_RE = re.compile(
    r"```(?P<tag>[A-Za-z0-9_-]+)[ \t]*\n(?P<body>[\s\S]*?)\n```",
    flags=re.MULTILINE,
)
_GRAPH_TAGS = {
    "mindmap",
    "mind-map",
    "graph",
    "knowledge_graph",
    "knowledge-graph",
    "wissensgraph",
}
_EDGE_TEXT_RE = re.compile(
    r"^\s*(?P<src>[^-:>]+?)\s*[-=]+>\s*(?P<dst>[^:]+?)(?::\s*(?P<label>.+))?$"
)
_MAX_LABEL_CHARS = 180
_MAX_DESC_CHARS = 6000
_MAX_LINK_CHARS = 512

def contains_structured_graph(markdown_text: str) -> bool:
    return extract_graph_spec(markdown_text) is not None

def extract_graph_spec(markdown_text: str) -> GraphSpec | None:
    for tag, body in _iter_graph_blocks(markdown_text):
        payload = _parse_payload(body, tag_hint=tag)
        if payload is None:
            continue
        spec = _payload_to_spec(payload, tag_hint=tag)
        if spec is not None:
            return spec
    return None
def graph_spec_signature(spec: GraphSpec) -> str:
    edge_rows = sorted(f"{e.source_id}>{e.target_id}:{e.label}" for e in spec.edges)
    child_rows = sorted(
        f"{n.node_id}:{','.join(n.children)}:{n.quote}"
        for n in spec.nodes.values()
    )
    return "|".join(
        [
            spec.kind,
            spec.title,
            ",".join(sorted(spec.nodes.keys())),
            ",".join(spec.roots),
            ";".join(child_rows),
            ";".join(edge_rows),
        ]
    )
def spec_to_markdown(spec: GraphSpec) -> str:
    visited: set[str] = set()

    def walk(node_id: str) -> dict[str, Any]:
        node = spec.nodes[node_id]
        out: dict[str, Any] = {"id": node.node_id, "label": node.label}
        if node.description:
            out["description"] = node.description
        if node.quote:
            out["quote"] = node.quote
        if node.href:
            out["href"] = node.href
        if node_id in visited:
            out["children"] = list(node.children)
            return out
        visited.add(node_id)
        if node.children:
            out["children"] = [
                walk(child_id) if child_id in spec.nodes else child_id
                for child_id in node.children
            ]
        return out

    nodes_payload: list[dict[str, Any]] = []
    root_ids = [node_id for node_id in spec.roots if node_id in spec.nodes]
    for root_id in root_ids:
        nodes_payload.append(walk(root_id))
    for node_id in sorted(spec.nodes.keys()):
        if node_id in root_ids or node_id in visited:
            continue
        nodes_payload.append(walk(node_id))

    payload: dict[str, Any] = {
        "type": spec.kind,
        "title": spec.title,
        "nodes": nodes_payload,
        "edges": [
            {
                "from": edge.source_id,
                "to": edge.target_id,
                **({"label": edge.label} if edge.label else {}),
            }
            for edge in spec.edges
        ],
    }
    if spec.default_collapsed_ids:
        payload["collapsed"] = sorted(spec.default_collapsed_ids)

    tag = "graph" if spec.kind == "graph" else "mindmap"
    body = json.dumps(payload, ensure_ascii=False, indent=2)
    return f"```{tag}\n{body}\n```"


def _iter_graph_blocks(markdown_text: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for match in _FENCED_BLOCK_RE.finditer(str(markdown_text or "")):
        tag = str(match.group("tag") or "").strip().casefold()
        if tag not in _GRAPH_TAGS:
            continue
        out.append((tag, str(match.group("body") or "").strip()))
    return out


def _parse_payload(text: str, *, tag_hint: str) -> dict[str, Any] | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
    return _parse_simple_text_payload(raw, tag_hint=tag_hint)


def _parse_simple_text_payload(text: str, *, tag_hint: str) -> dict[str, Any] | None:
    if tag_hint in {"graph", "knowledge_graph", "knowledge-graph", "wissensgraph"}:
        return _parse_simple_graph_payload(text)
    mindmap_payload = _parse_simple_mindmap_payload(text)
    if mindmap_payload is not None:
        return mindmap_payload
    return _parse_simple_graph_payload(text)


def _normalize_simple_line(raw: str) -> tuple[int, str]:
    line = str(raw or "").rstrip()
    if not line.strip():
        return 0, ""
    expand = line.replace("\t", "  ")
    stripped = expand.lstrip(" ")
    indent = len(expand) - len(stripped)
    return max(0, indent // 2), stripped.strip()


def _split_mindmap_line(content: str) -> tuple[str, str]:
    raw = str(content or "").strip()
    if " | " not in raw:
        return raw, ""
    left, right = raw.split(" | ", 1)
    quote = right.strip()
    if quote.casefold().startswith("quote:"):
        quote = quote.split(":", 1)[1].strip()
    if len(quote) >= 2 and quote[0] == quote[-1] and quote[0] in {"'", '"'}:
        quote = quote[1:-1].strip()
    return left.strip(), quote


def _parse_simple_mindmap_payload(text: str) -> dict[str, Any] | None:
    lines = [line for line in str(text or "").splitlines() if line.strip()]
    if not lines:
        return None
    roots: list[dict[str, Any]] = []
    stack: list[tuple[int, dict[str, Any]]] = []
    for raw_line in lines:
        indent, content = _normalize_simple_line(raw_line)
        label, quote = _split_mindmap_line(content)
        if not label:
            continue
        node: dict[str, Any] = {"label": _clip_text(label, max_chars=_MAX_LABEL_CHARS)}
        if quote:
            node["quote"] = _clip_text(quote, max_chars=_MAX_DESC_CHARS)
        while stack and stack[-1][0] >= indent:
            stack.pop()
        if stack:
            children = stack[-1][1].setdefault("children", [])
            if isinstance(children, list):
                children.append(node)
        else:
            roots.append(node)
        stack.append((indent, node))
    if not roots:
        return None
    title = _clip_text(roots[0].get("label", "MindMap"), max_chars=160) or "MindMap"
    return {"type": "mindmap", "title": title, "nodes": roots}


def _parse_simple_graph_payload(text: str) -> dict[str, Any] | None:
    lines = [line for line in str(text or "").splitlines() if line.strip()]
    if not lines:
        return None
    title = "Graph"
    edge_rows: list[dict[str, str]] = []
    standalone_nodes: list[dict[str, str]] = []
    for raw_line in lines:
        _indent, content = _normalize_simple_line(raw_line)
        title_match = re.match(r"^title\s*:\s*(.+)$", content, flags=re.IGNORECASE)
        if title_match:
            title = _clip_text(title_match.group(1), max_chars=160) or title
            continue
        match = _EDGE_TEXT_RE.match(content)
        if match is not None:
            src = _clip_text(match.group("src"), max_chars=_MAX_LABEL_CHARS)
            dst = _clip_text(match.group("dst"), max_chars=_MAX_LABEL_CHARS)
            if not src or not dst:
                continue
            row = {"from": src, "to": dst}
            lbl = _clip_text(match.group("label") or "", max_chars=140)
            if lbl:
                row["label"] = lbl
            edge_rows.append(row)
            continue
        standalone_nodes.append({"label": _clip_text(content, max_chars=_MAX_LABEL_CHARS)})
    if not edge_rows and not standalone_nodes:
        return None
    if not standalone_nodes:
        seen: set[str] = set()
        for row in edge_rows:
            for label in (row.get("from", ""), row.get("to", "")):
                key = str(label or "").casefold()
                if not key or key in seen:
                    continue
                seen.add(key)
                standalone_nodes.append({"label": str(label)})
    return {"type": "graph", "title": title, "nodes": standalone_nodes, "edges": edge_rows}


def _payload_to_spec(payload: dict[str, Any], *, tag_hint: str) -> GraphSpec | None:
    kind = str(payload.get("type", "") or "").strip().casefold()
    if kind not in {"mindmap", "graph"}:
        kind = "graph" if "graph" in str(tag_hint or "") else "mindmap"
    title = _clip_text(payload.get("title", "Wissensgraph" if kind == "graph" else "MindMap"), max_chars=160)
    title = title or ("Wissensgraph" if kind == "graph" else "MindMap")

    nodes: dict[str, GraphNode] = {}
    label_to_id: dict[str, str] = {}
    edges: list[GraphEdge] = []
    roots: list[str] = []
    incoming: set[str] = set()
    used_ids: set[str] = set()
    edge_seen: set[tuple[str, str, str]] = set()

    def alloc_node_id(candidate: str) -> str:
        base = _slug(candidate) if candidate else "node"
        out = base
        idx = 2
        while out in used_ids:
            out = f"{base}-{idx}"
            idx += 1
        used_ids.add(out)
        return out

    def resolve_node_ref(token: str) -> str:
        raw = str(token or "").strip()
        if not raw:
            return ""
        if raw in nodes:
            return raw
        return label_to_id.get(raw.casefold(), "")

    def ensure_node(node_data: Any) -> str:
        if isinstance(node_data, str):
            token = _clip_text(node_data, max_chars=_MAX_LABEL_CHARS)
            if not token:
                return ""
            found = resolve_node_ref(token)
            if found:
                return found
            node_id = alloc_node_id(token)
            nodes[node_id] = GraphNode(node_id=node_id, label=token)
            label_to_id.setdefault(token.casefold(), node_id)
            return node_id
        if not isinstance(node_data, dict):
            return ""
        candidate_id = _clip_text(node_data.get("id") or node_data.get("node_id") or "", max_chars=80)
        label = _clip_text(
            node_data.get("label") or node_data.get("title") or node_data.get("name") or candidate_id,
            max_chars=_MAX_LABEL_CHARS,
        )
        node_id = candidate_id if (candidate_id and candidate_id not in used_ids) else alloc_node_id(candidate_id or label)
        if node_id in nodes:
            return node_id
        node = GraphNode(
            node_id=node_id,
            label=label or node_id,
            description=_clip_text(node_data.get("description") or node_data.get("desc") or "", max_chars=_MAX_DESC_CHARS),
            quote=_clip_text(node_data.get("quote") or "", max_chars=_MAX_DESC_CHARS),
            href=_clip_href(node_data.get("href") or node_data.get("link") or node_data.get("url") or ""),
        )
        nodes[node_id] = node
        label_to_id.setdefault(node.label.casefold(), node_id)
        return node_id

    def add_edge(src: str, dst: str, label: str = ""):
        if not src or not dst or src not in nodes or dst not in nodes:
            return
        lbl = _clip_text(label, max_chars=140)
        key = (src, dst, lbl)
        if key in edge_seen:
            return
        edge_seen.add(key)
        incoming.add(dst)
        edges.append(GraphEdge(source_id=src, target_id=dst, label=lbl))
        node = nodes.get(src)
        if node is not None and dst not in node.children:
            node.children.append(dst)

    def walk_node(node_data: Any, parent_id: str = "") -> str:
        node_id = ensure_node(node_data)
        if not node_id:
            return ""
        if parent_id:
            add_edge(parent_id, node_id)
        elif node_id not in roots:
            roots.append(node_id)
        if isinstance(node_data, dict):
            children = node_data.get("children", [])
            if isinstance(children, list):
                for child in children:
                    if isinstance(child, str):
                        child_id = ensure_node(child)
                        if child_id:
                            add_edge(node_id, child_id)
                    else:
                        walk_node(child, node_id)
        return node_id

    raw_nodes = payload.get("nodes", [])
    for row in (raw_nodes if isinstance(raw_nodes, list) else [raw_nodes]):
        walk_node(row)

    raw_edges = payload.get("edges", [])
    for row in (raw_edges if isinstance(raw_edges, list) else [raw_edges]):
        if isinstance(row, str):
            match = _EDGE_TEXT_RE.match(row)
            if match is None:
                continue
            add_edge(ensure_node(match.group("src")), ensure_node(match.group("dst")), match.group("label") or "")
            continue
        if not isinstance(row, dict):
            continue
        add_edge(
            ensure_node(row.get("from") or row.get("source") or row.get("start") or ""),
            ensure_node(row.get("to") or row.get("target") or row.get("end") or ""),
            row.get("label") or "",
        )

    if not nodes:
        return None
    if not roots:
        roots = [node_id for node_id in nodes if node_id not in incoming]
    if not roots:
        roots = [sorted(nodes.keys())[0]]

    collapsed_ids: set[str] = set()
    raw_collapsed = payload.get("collapsed", [])
    for token in (raw_collapsed if isinstance(raw_collapsed, list) else [raw_collapsed]):
        node_id = resolve_node_ref(str(token or ""))
        if node_id:
            collapsed_ids.add(node_id)

    return GraphSpec(
        kind=kind,
        title=title,
        nodes=nodes,
        roots=roots,
        edges=edges,
        default_collapsed_ids=collapsed_ids,
    )


def _clip_text(value: object, *, max_chars: int) -> str:
    text = str(value or "").replace("\r\n", "\n").strip()
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    return text[: max(1, max_chars - 1)].rstrip() + "…"


def _clip_href(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) > _MAX_LINK_CHARS:
        text = text[:_MAX_LINK_CHARS]
    return text


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().casefold()).strip("-")
