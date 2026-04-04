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
    "mermaid",
    "knowledge_graph",
    "knowledge-graph",
    "wissensgraph",
}
_EDGE_TEXT_RE = re.compile(
    r"^\s*(?P<src>[^-:>]+?)\s*[-=]+>\s*(?P<dst>[^:]+?)(?::\s*(?P<label>.+))?$"
)
_MERMAID_EDGE_RE = re.compile(
    r"^(?P<src>.+?)\s*(?:-->|==>|-.->|---|--)\s*"
    r"(?:\|(?P<label>[^|]+)\|\s*)?(?P<dst>.+?)\s*$"
)
_MERMAID_DECL_RE = re.compile(
    r"^(?P<node>[A-Za-z0-9_.:-]+(?:\s*(?:\[[^\]]*\]|\([^)]*\)|\{[^}]*\}))?)$"
)
_YAML_SCALAR_RE = re.compile(
    r'^\s*(?:-\s*)?(?P<key>type|title|text|label|name|id)\s*:\s*(?P<val>.+?)\s*$',
    flags=re.IGNORECASE,
)
_YAML_REL_RE = re.compile(
    r'^\s*-\s*(?:source|from)\s*:\s*"?(?P<src>[^"]+?)"?\s*->\s*"?(?P<dst>[^"]+?)"?\s*$',
    flags=re.IGNORECASE,
)
_MAX_LABEL_CHARS = 180
_MAX_DESC_CHARS = 6000
_MAX_LINK_CHARS = 512
_STRUCTURED_KEY_RE = re.compile(
    r'^\s*-?\s*"?(type|title|nodes|edges|children|label|id|name|text|from|to|source|target)"?\s*:',
    flags=re.IGNORECASE | re.MULTILINE,
)

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
    for candidate in _json_parse_candidates(raw):
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, str):
                nested = str(parsed or "").strip()
                if nested:
                    try:
                        parsed_nested = json.loads(nested)
                        if isinstance(parsed_nested, dict):
                            return parsed_nested
                    except Exception:
                        pass
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
    yaml_like = _parse_yaml_like_payload(raw, tag_hint=tag_hint)
    if yaml_like is not None:
        return yaml_like
    if _looks_structured_mapping_text(raw, tag_hint=tag_hint):
        return None
    return _parse_simple_text_payload(raw, tag_hint=tag_hint)


def _looks_structured_mapping_text(text: str, *, tag_hint: str) -> bool:
    raw = str(text or "").strip()
    if not raw:
        return False
    hint = str(tag_hint or "").strip().casefold()
    if hint == "mermaid":
        return False
    if raw.startswith("{") or raw.startswith("["):
        return True
    if _STRUCTURED_KEY_RE.search(raw) is not None:
        return True
    lowered = raw.casefold()
    return (
        '"nodes"' in lowered
        or '"children"' in lowered
        or '"edges"' in lowered
        or '"label"' in lowered
        or '"id"' in lowered
    )


def _parse_simple_text_payload(text: str, *, tag_hint: str) -> dict[str, Any] | None:
    if tag_hint == "mermaid":
        payload = _parse_mermaid_payload(text)
        if payload is not None:
            return payload
    if tag_hint in {"graph", "knowledge_graph", "knowledge-graph", "wissensgraph"}:
        return _parse_simple_graph_payload(text)
    mindmap_payload = _parse_simple_mindmap_payload(text)
    if mindmap_payload is not None:
        return mindmap_payload
    return _parse_simple_graph_payload(text)


def _json_parse_candidates(raw: str) -> list[str]:
    text = str(raw or "")
    out: list[str] = [text]
    # Some small models emit JSON with line-continuation backslashes at EOL:
    # {\  "type":"mindmap",\ ... }\
    decontinued = re.sub(r"\\\s*(\r?\n)", r"\1", text)
    # Also handle trailing continuation slash at EOF (after strip()).
    decontinued = re.sub(r"\\\s*$", "", decontinued)
    if decontinued != text:
        out.append(decontinued)
    return out


def _unquote_yaml_scalar(value: str) -> str:
    text = str(value or "").strip().rstrip(",")
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'"}:
        text = text[1:-1]
    return _clip_text(text.strip(), max_chars=_MAX_LABEL_CHARS)


def _parse_yaml_like_payload(text: str, *, tag_hint: str) -> dict[str, Any] | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    lines = [str(line or "").rstrip() for line in raw.splitlines() if str(line or "").strip()]
    if not lines:
        return None

    header = str(lines[0] or "").strip()
    header_match = re.match(r"^(mindmap|graph)\s+(?P<title>.+?)\s*\{\s*$", header, flags=re.IGNORECASE)
    kind = str(tag_hint or "").strip().casefold()
    title = ""
    start_idx = 0
    if header_match is not None:
        kind = str(header_match.group(1) or kind or "mindmap").strip().casefold()
        title = _clip_text(str(header_match.group("title") or "").strip(), max_chars=160)
        start_idx = 1
    if kind not in {"mindmap", "graph"}:
        return None

    section = ""
    roots: list[dict[str, Any]] = []
    stack: list[tuple[int, dict[str, Any]]] = []
    edge_rows: list[dict[str, str]] = []
    node_count = 0

    for raw_line in lines[start_idx:]:
        line = str(raw_line or "").rstrip()
        stripped = line.strip()
        if not stripped or stripped == "}":
            continue
        lowered = stripped.casefold()
        if lowered.startswith("nodes:"):
            section = "nodes"
            continue
        if lowered.startswith("relationships:") or lowered.startswith("edges:"):
            section = "edges"
            continue

        scalar_match = _YAML_SCALAR_RE.match(line)
        if scalar_match is not None and section != "nodes":
            key = str(scalar_match.group("key") or "").strip().casefold()
            val = _unquote_yaml_scalar(str(scalar_match.group("val") or ""))
            if key == "title" and val:
                title = _clip_text(val, max_chars=160)
            elif key == "type" and val:
                kind = "graph" if "graph" in val.casefold() else "mindmap"
            continue

        if section == "nodes":
            if lowered.startswith("children:"):
                continue
            scalar_match = _YAML_SCALAR_RE.match(line)
            if scalar_match is None:
                continue
            key = str(scalar_match.group("key") or "").strip().casefold()
            if key not in {"text", "label", "name"}:
                continue
            label = _unquote_yaml_scalar(str(scalar_match.group("val") or ""))
            if not label:
                continue
            indent = len(line) - len(line.lstrip(" "))
            node = {"label": label}
            while stack and stack[-1][0] >= indent:
                stack.pop()
            if stack:
                children = stack[-1][1].setdefault("children", [])
                if isinstance(children, list):
                    children.append(node)
            else:
                roots.append(node)
            stack.append((indent, node))
            node_count += 1
            continue

        if section == "edges":
            rel_match = _YAML_REL_RE.match(line)
            if rel_match is None:
                continue
            src = _unquote_yaml_scalar(str(rel_match.group("src") or ""))
            dst = _unquote_yaml_scalar(str(rel_match.group("dst") or ""))
            if src and dst:
                edge_rows.append({"from": src, "to": dst})

    if node_count <= 0:
        return None
    return {
        "type": "graph" if kind == "graph" else "mindmap",
        "title": title or ("Graph" if kind == "graph" else "MindMap"),
        "nodes": roots,
        **({"edges": edge_rows} if edge_rows else {}),
    }


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
    raw = re.sub(r"^(?:[-*+]\s+|\d+[.)]\s+)", "", raw)
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


def _parse_mermaid_node_token(text: str) -> tuple[str, str]:
    token = str(text or "").strip().rstrip(";")
    if not token:
        return "", ""
    if ":::" in token:
        token = token.split(":::", 1)[0].strip()
    match = re.match(
        r"^(?P<id>[A-Za-z0-9_.:-]+)\s*(?P<shape>\[[^\]]*\]|\([^)]*\)|\{[^}]*\})?\s*$",
        token,
    )
    if match is not None:
        node_id = _clip_text(match.group("id") or "", max_chars=80)
        shape = str(match.group("shape") or "").strip()
        if shape:
            label = shape[1:-1].strip().strip("\"'")
        else:
            label = node_id
        label = _clip_text(label, max_chars=_MAX_LABEL_CHARS) or node_id
        return node_id, label
    clean = token.strip("\"'")
    label = _clip_text(clean, max_chars=_MAX_LABEL_CHARS)
    node_id = _slug(label or clean)
    node_id = _clip_text(node_id or "node", max_chars=80)
    return node_id, label or node_id


def _parse_mermaid_payload(text: str) -> dict[str, Any] | None:
    lines = [str(line or "").strip() for line in str(text or "").splitlines()]
    nodes: dict[str, str] = {}
    edges: list[dict[str, str]] = []

    def ensure_node(raw: str) -> str:
        node_id, label = _parse_mermaid_node_token(raw)
        if not node_id:
            return ""
        if node_id not in nodes:
            nodes[node_id] = label
        return node_id

    for raw_line in lines:
        line = str(raw_line or "").strip()
        if not line:
            continue
        if line.startswith("%%"):
            continue
        if line.casefold().startswith("graph ") or line.casefold().startswith("flowchart "):
            continue
        for segment in [part.strip() for part in line.split(";") if part.strip()]:
            match = _MERMAID_EDGE_RE.match(segment)
            if match is not None:
                src = ensure_node(str(match.group("src") or ""))
                dst = ensure_node(str(match.group("dst") or ""))
                if not src or not dst:
                    continue
                row = {"from": src, "to": dst}
                lbl = _clip_text(match.group("label") or "", max_chars=140)
                if lbl:
                    row["label"] = lbl
                edges.append(row)
                continue
            decl = _MERMAID_DECL_RE.match(segment)
            if decl is not None:
                ensure_node(str(decl.group("node") or ""))

    if not nodes and not edges:
        return None
    node_rows = [{"id": node_id, "label": label} for node_id, label in sorted(nodes.items())]
    return {"type": "graph", "title": "Graph", "nodes": node_rows, "edges": edges}


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
        slug = _slug(candidate) if candidate else ""
        base = slug or "node"
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
                repaired_children = _repair_flat_tree_children(children)
                for child in repaired_children:
                    if isinstance(child, str):
                        child_id = ensure_node(child)
                        if child_id:
                            add_edge(node_id, child_id)
                    else:
                        walk_node(child, node_id)
        return node_id

    raw_nodes = payload.get("nodes", [])
    if isinstance(raw_nodes, list):
        raw_nodes = _repair_flat_tree_children(raw_nodes)
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
    if roots:
        dedup_roots: list[str] = []
        seen_roots: set[str] = set()
        for node_id in roots:
            key = str(node_id or "")
            if not key or key in seen_roots or key not in nodes:
                continue
            seen_roots.add(key)
            dedup_roots.append(key)
        roots = dedup_roots
        if incoming:
            root_candidates = [node_id for node_id in roots if node_id not in incoming]
            if root_candidates:
                roots = root_candidates
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


def _split_tree_marker_label(raw_label: object) -> tuple[int, str]:
    text = str(raw_label or "").replace("\t", "    ").strip()
    if not text:
        return 0, ""
    work = text
    depth = 0
    while True:
        if work.startswith("│   ") or work.startswith("|   "):
            depth += 1
            work = work[4:]
            continue
        if work.startswith("    "):
            depth += 1
            work = work[4:]
            continue
        break
    branch_tokens = (
        "├──",
        "└──",
        "├─",
        "└─",
        "|--",
        "+--",
        "`--",
        "|-",
        "+-",
    )
    for token in branch_tokens:
        if work.startswith(token):
            cleaned = work[len(token):].strip()
            return depth + 1, cleaned
    return 0, text


def _repair_flat_tree_children(children: list[Any]) -> list[Any]:
    rows: list[tuple[dict[str, Any], int, str]] = []
    marker_count = 0
    max_depth = 0
    for child in list(children or []):
        if isinstance(child, dict):
            node = dict(child)
            label = str(
                node.get("label")
                or node.get("title")
                or node.get("name")
                or node.get("id")
                or ""
            )
        elif isinstance(child, str):
            node = {"label": str(child)}
            label = str(child)
        else:
            return children
        depth, cleaned = _split_tree_marker_label(label)
        if depth > 0:
            marker_count += 1
            max_depth = max(max_depth, depth)
        rows.append((node, depth, cleaned))

    if len(rows) < 2:
        return children
    if marker_count < 2 or marker_count < max(2, len(rows) // 2) or max_depth < 2:
        return children

    rebuilt_roots: list[dict[str, Any]] = []
    stack: list[tuple[int, dict[str, Any]]] = []
    for node, depth, cleaned in rows:
        normalized = dict(node)
        if cleaned:
            normalized["label"] = _clip_text(cleaned, max_chars=_MAX_LABEL_CHARS)
        existing_children = normalized.get("children", [])
        normalized["children"] = list(existing_children) if isinstance(existing_children, list) else []
        level = max(1, int(depth or 1))
        while stack and stack[-1][0] >= level:
            stack.pop()
        if stack:
            parent_children = stack[-1][1].setdefault("children", [])
            if isinstance(parent_children, list):
                parent_children.append(normalized)
        else:
            rebuilt_roots.append(normalized)
        stack.append((level, normalized))
    return rebuilt_roots


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
