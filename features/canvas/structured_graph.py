"""Structured MindMap/Graph parsing and HTML rendering helpers."""
from __future__ import annotations

from dataclasses import dataclass, field
import html
import json
import re
from typing import Any, Callable
from urllib.parse import quote


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
_MAX_DESC_CHARS = 480
_MAX_LINK_CHARS = 512
_MAX_NODES = 700
_MAX_EDGES = 1400


@dataclass(slots=True)
class GraphNode:
    node_id: str
    label: str
    description: str = ""
    quote: str = ""
    href: str = ""
    children: list[str] = field(default_factory=list)


@dataclass(slots=True)
class GraphEdge:
    source_id: str
    target_id: str
    label: str = ""


@dataclass(slots=True)
class GraphSpec:
    kind: str
    title: str
    nodes: dict[str, GraphNode]
    roots: list[str]
    edges: list[GraphEdge]
    default_collapsed_ids: set[str] = field(default_factory=set)


def contains_structured_graph(markdown_text: str) -> bool:
    """Return True when markdown contains a supported graph block."""
    return extract_graph_spec(markdown_text) is not None


def extract_graph_spec(markdown_text: str) -> GraphSpec | None:
    """Parse first supported fenced graph block from markdown."""
    for block in _iter_graph_blocks(markdown_text):
        tag, body = block
        payload = _parse_payload(body, tag_hint=tag)
        if payload is None:
            continue
        spec = _payload_to_spec(payload, tag_hint=tag)
        if spec is not None:
            return spec
    return None


def graph_spec_signature(spec: GraphSpec) -> str:
    """Stable signature used to reset UI state when structure changes."""
    edge_rows = sorted(
        f"{row.source_id}>{row.target_id}:{row.label}"
        for row in spec.edges
    )
    child_rows = sorted(
        f"{node.node_id}:{','.join(node.children)}:{node.quote}"
        for node in spec.nodes.values()
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
    """Serialize a graph spec to canonical fenced markdown block."""
    visited: set[str] = set()

    def walk(node_id: str) -> dict[str, Any]:
        node = spec.nodes[node_id]
        out: dict[str, Any] = {
            "id": node.node_id,
            "label": node.label,
        }
        if node.description:
            out["description"] = node.description
        if node.quote:
            out["quote"] = node.quote
        if node.href:
            out["href"] = node.href
        if node_id in visited:
            # Prevent recursive expansion in cycles.
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
    root_ids = [root_id for root_id in spec.roots if root_id in spec.nodes]
    for root_id in root_ids:
        nodes_payload.append(walk(root_id))
    for node_id in sorted(spec.nodes.keys()):
        if node_id in root_ids:
            continue
        if node_id in visited:
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


def render_graph_html(
    spec: GraphSpec,
    *,
    collapsed_ids: set[str] | None = None,
    focus_node_id: str = "",
) -> str:
    """Render structured graph into interactive HTML fragment."""
    collapsed = set(collapsed_ids or set())
    focus = str(focus_node_id or "").strip()

    roots = [node_id for node_id in spec.roots if node_id in spec.nodes]
    if not roots:
        roots = sorted(spec.nodes.keys())[:1]

    visited: set[str] = set()
    tree_html = _render_tree_nodes(
        spec=spec,
        roots=roots,
        collapsed_ids=collapsed,
        focus_node_id=focus,
        visited=visited,
    )

    orphan_nodes = [
        node_id
        for node_id in sorted(spec.nodes.keys())
        if node_id not in visited
    ]
    orphan_html = ""
    if orphan_nodes:
        orphan_html = (
            "<h3>Weitere Knoten</h3>"
            + _render_tree_nodes(
                spec=spec,
                roots=orphan_nodes,
                collapsed_ids=collapsed,
                focus_node_id=focus,
                visited=visited,
            )
        )

    edges_html = _render_edges(spec=spec, focus_node_id=focus)
    title = html.escape(spec.title)
    mode_label = "Wissensgraph" if spec.kind == "graph" else "MindMap"
    subtitle = (
        "Knoten lassen sich auf- und zuklappen. Kanten zeigen Verbindungen."
        if spec.kind == "graph"
        else "Knoten lassen sich auf- und zuklappen. Zusaetzliche Kanten sind rechts gelistet."
    )
    return f"""
<html>
  <head>
    <style>
      body {{
        background: #1E1E2E;
        color: #CDD6F4;
        font-family: 'Segoe UI', sans-serif;
        margin: 0;
        padding: 10px;
      }}
      .d2c-shell {{ border: 1px solid #45475A; border-radius: 8px; padding: 10px; background: #181825; }}
      .d2c-head h2 {{ margin: 0 0 2px 0; color: #89B4FA; font-size: 1.28em; }}
      .d2c-head .type {{ color: #A6E3A1; font-size: 0.93em; margin-right: 8px; }}
      .d2c-head .hint {{ color: #6C7086; font-size: 0.9em; }}
      .d2c-controls {{ margin: 8px 0 10px 0; }}
      .d2c-controls a {{ color: #89B4FA; text-decoration: none; margin-right: 10px; }}
      .d2c-grid {{ display: table; width: 100%; border-spacing: 8px 0; }}
      .d2c-col {{ display: table-cell; vertical-align: top; width: 50%; }}
      .d2c-col h3 {{ margin: 0 0 6px 0; color: #CBA6F7; font-size: 1.0em; }}
      ul.d2c-tree {{ margin: 0; padding-left: 18px; }}
      ul.d2c-tree li {{ margin: 2px 0; }}
      .d2c-toggle {{ color: #F9E2AF; text-decoration: none; font-weight: bold; margin-right: 4px; }}
      .d2c-node-label {{ color: #CDD6F4; text-decoration: none; }}
      .d2c-node-label:hover {{ color: #89B4FA; text-decoration: underline; }}
      .d2c-node-focus {{ background: #2B314C; border-radius: 4px; padding: 0 3px; }}
      .d2c-node-desc {{ color: #A6ADC8; font-size: 0.9em; margin-left: 4px; }}
      .d2c-node-link {{ color: #A6E3A1; text-decoration: none; margin-left: 4px; }}
      .d2c-edge-list {{ margin: 0; padding-left: 18px; }}
      .d2c-edge-list li {{ margin: 2px 0; }}
      .d2c-edge-focus {{ color: #F9E2AF; }}
      .d2c-muted {{ color: #6C7086; font-style: italic; }}
    </style>
  </head>
  <body>
    <div class="d2c-shell">
      <div class="d2c-head">
        <h2>{title}</h2>
        <span class="type">{mode_label}</span>
        <span class="hint">{html.escape(subtitle)}</span>
      </div>
      <div class="d2c-controls">
        <a href="d2c://graph/expand_all">Alle ausklappen</a>
        <a href="d2c://graph/collapse_all">Alle einklappen</a>
        <a href="d2c://graph/clear_focus">Fokus loeschen</a>
      </div>
      <div class="d2c-grid">
        <div class="d2c-col">
          <h3>Knoten</h3>
          {tree_html}
          {orphan_html}
        </div>
        <div class="d2c-col">
          <h3>Verbindungen</h3>
          {edges_html}
        </div>
      </div>
    </div>
  </body>
</html>
""".strip()


def _iter_graph_blocks(markdown_text: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for match in _FENCED_BLOCK_RE.finditer(str(markdown_text or "")):
        tag = str(match.group("tag") or "").strip().lower()
        if tag not in _GRAPH_TAGS:
            continue
        body = str(match.group("body") or "")
        out.append((tag, body))
    return out


def _parse_payload(
    body: str,
    *,
    tag_hint: str,
) -> dict[str, Any] | list[Any] | None:
    text = str(body or "").strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
        if isinstance(parsed, (dict, list)):
            return parsed
    except Exception:
        pass

    for pattern in (r"\{[\s\S]*\}", r"\[[\s\S]*\]"):
        match = re.search(pattern, text)
        if match is None:
            continue
        try:
            parsed = json.loads(match.group(0))
        except Exception:
            continue
        if isinstance(parsed, (dict, list)):
            return parsed
    simple = _parse_simple_text_payload(text, tag_hint=tag_hint)
    if simple is not None:
        return simple
    return None


def _parse_simple_text_payload(
    text: str,
    *,
    tag_hint: str,
) -> dict[str, Any] | None:
    tag = str(tag_hint or "").strip().casefold()
    is_graph = ("graph" in tag) or ("wissens" in tag)
    if is_graph:
        # In graph mode we stay strict: no fallback to mindmap parsing.
        # This avoids inferred/guessed relations from indentation-only text.
        return _parse_simple_graph_payload(text)
    mindmap_payload = _parse_simple_mindmap_payload(text)
    if mindmap_payload is not None:
        return mindmap_payload
    return _parse_simple_graph_payload(text)


def _normalize_simple_line(raw: str) -> tuple[int, str]:
    line = str(raw or "").expandtabs(2).rstrip()
    if not line.strip():
        return 0, ""
    indent = len(line) - len(line.lstrip(" "))
    content = line.strip()
    content = re.sub(r"^(?:[-*+]|[•◦▪●])\s+", "", content)
    content = re.sub(r"^\d+[.)]\s+", "", content)
    content = re.sub(r"\s+", " ", content).strip()
    return indent, content


def _strip_quote_wrapper(value: str) -> str:
    text = str(value or "").strip()
    if (
        len(text) >= 2
        and text[0] == text[-1]
        and text[0] in {'"', "'"}
    ):
        text = text[1:-1].strip()
    return text


def _split_mindmap_line(content: str) -> tuple[str, str]:
    text = str(content or "").strip()
    if not text:
        return "", ""
    for sep in ("::", "|"):
        if sep not in text:
            continue
        left, right = text.split(sep, 1)
        label = left.strip()
        quote = right.strip()
        quote = re.sub(r"^quote\s*=\s*", "", quote, flags=re.IGNORECASE)
        quote = _strip_quote_wrapper(quote)
        if label:
            return label, quote
    return text, ""


def _parse_simple_mindmap_payload(text: str) -> dict[str, Any] | None:
    rows: list[tuple[int, str, str]] = []
    for raw_line in str(text or "").splitlines():
        indent, content = _normalize_simple_line(raw_line)
        if not content:
            continue
        label, quote = _split_mindmap_line(content)
        if not label:
            continue
        rows.append((indent, label, quote))
    if not rows:
        return None

    roots: list[dict[str, Any]] = []
    stack: list[tuple[int, dict[str, Any]]] = []
    for indent, label, quote in rows[:_MAX_NODES]:
        node: dict[str, Any] = {"label": label}
        if quote:
            node["quote"] = quote
        while stack and indent <= stack[-1][0]:
            stack.pop()
        if stack:
            parent = stack[-1][1]
            parent.setdefault("children", []).append(node)
        else:
            roots.append(node)
        stack.append((indent, node))

    if not roots:
        return None
    title = str(roots[0].get("label") or "MindMap").strip()
    return {
        "type": "mindmap",
        "title": title or "MindMap",
        "nodes": roots,
    }


def _parse_simple_graph_payload(text: str) -> dict[str, Any] | None:
    triples: list[dict[str, str]] = []
    node_labels: list[str] = []
    seen_nodes: set[str] = set()
    title = "Wissensgraph"

    def add_node(label: str):
        token = str(label or "").strip()
        if not token:
            return
        norm = re.sub(r"\s+", " ", token).strip().casefold()
        if not norm or norm in seen_nodes:
            return
        seen_nodes.add(norm)
        node_labels.append(token)

    for raw_line in str(text or "").splitlines():
        _, content = _normalize_simple_line(raw_line)
        if not content:
            continue
        title_match = re.match(r"^(?:title|titel)\s*:\s*(.+)$", content, flags=re.IGNORECASE)
        if title_match is not None:
            title = _clip_text(title_match.group(1), max_chars=160) or title
            continue

        subj = ""
        pred = ""
        obj = ""

        if "|" in content:
            parts = [part.strip() for part in content.split("|")]
            if len(parts) >= 3:
                subj = parts[0]
                obj = parts[-1]
                pred = " | ".join(parts[1:-1]).strip()
        if not subj or not obj:
            match = _EDGE_TEXT_RE.match(content)
            if match is not None:
                subj = str(match.group("src") or "").strip()
                obj = str(match.group("dst") or "").strip()
                pred = str(match.group("label") or "").strip()
        if not subj or not obj:
            continue
        if not pred:
            continue

        subj = re.sub(r"\s+", " ", subj).strip()
        obj = re.sub(r"\s+", " ", obj).strip()
        pred = re.sub(r"\s+", " ", pred).strip()
        if not subj or not obj or not pred:
            continue

        add_node(subj)
        add_node(obj)
        triples.append(
            {
                "subject": subj,
                "predicate": pred,
                "object": obj,
            }
        )
        if len(triples) >= _MAX_EDGES:
            break

    if not triples:
        return None

    nodes = [{"label": label} for label in node_labels[:_MAX_NODES]]
    return {
        "type": "graph",
        "title": title,
        "nodes": nodes,
        "triples": triples,
    }


def _payload_to_spec(
    payload_raw: dict[str, Any] | list[Any],
    *,
    tag_hint: str,
) -> GraphSpec | None:
    payload: Any = payload_raw
    if isinstance(payload, dict):
        for key in (
            "mindmap",
            "graph",
            "knowledge_graph",
            "knowledge-graph",
            "wissensgraph",
        ):
            value = payload.get(key)
            if isinstance(value, (dict, list)):
                payload = value
                break

    if isinstance(payload, list):
        payload = {"nodes": payload}
    if not isinstance(payload, dict):
        return None

    kind_raw = _clip_text(
        payload.get("type") or payload.get("kind") or tag_hint or "mindmap",
        max_chars=40,
    ).casefold()
    kind = "graph" if ("graph" in kind_raw or "wissens" in kind_raw) else "mindmap"
    title = _clip_text(
        payload.get("title")
        or payload.get("name")
        or ("Wissensgraph" if kind == "graph" else "MindMap"),
        max_chars=160,
    )

    raw_nodes = payload.get("nodes")
    if raw_nodes is None:
        raw_nodes = payload.get("items")
    if raw_nodes is None:
        raw_nodes = payload.get("concepts")
    if raw_nodes is None and any(
        key in payload for key in ("id", "label", "name", "children")
    ):
        raw_nodes = [payload]
    if isinstance(raw_nodes, dict):
        raw_nodes = [raw_nodes]
    if not isinstance(raw_nodes, list):
        raw_relations = (
            payload.get("triples")
            or payload.get("edges")
            or payload.get("links")
            or payload.get("relations")
        )
        if isinstance(raw_relations, list):
            inferred_nodes: list[dict[str, str]] = []
            seen_labels: set[str] = set()
            for item in raw_relations:
                if not isinstance(item, dict):
                    continue
                for key in ("subject", "from", "source", "start"):
                    token = str(item.get(key) or "").strip()
                    if not token:
                        continue
                    norm = token.casefold()
                    if norm in seen_labels:
                        continue
                    seen_labels.add(norm)
                    inferred_nodes.append({"label": token})
                for key in ("object", "to", "target", "end"):
                    token = str(item.get(key) or "").strip()
                    if not token:
                        continue
                    norm = token.casefold()
                    if norm in seen_labels:
                        continue
                    seen_labels.add(norm)
                    inferred_nodes.append({"label": token})
            if inferred_nodes:
                raw_nodes = inferred_nodes
    if not isinstance(raw_nodes, list):
        return None

    nodes: dict[str, GraphNode] = {}
    roots: list[str] = []
    used_ids: set[str] = set()
    pending_children: list[tuple[str, str]] = []
    auto_edges: list[GraphEdge] = []
    label_index: dict[str, str] = {}
    ref_aliases: dict[str, str] = {}
    merge_graph_entities = kind == "graph"
    counter = 0

    def resolve_ref(ref: str) -> str:
        token = str(ref or "").strip()
        if not token:
            return ""
        aliased = ref_aliases.get(token.casefold(), "")
        if aliased and aliased in nodes:
            return aliased
        return _resolve_node_ref(token, nodes)

    def ensure_node(raw: Any, parent_id: str = "") -> str:
        nonlocal counter
        if len(nodes) >= _MAX_NODES:
            return ""
        if isinstance(raw, str):
            raw = {"label": raw}
        if not isinstance(raw, dict):
            return ""

        counter += 1
        candidate_id = _clip_text(
            raw.get("id") or raw.get("node_id") or raw.get("key"),
            max_chars=120,
        )
        label = _clip_text(
            raw.get("label")
            or raw.get("name")
            or raw.get("title")
            or candidate_id
            or f"Knoten {counter}",
            max_chars=_MAX_LABEL_CHARS,
        )
        label_norm = re.sub(r"\s+", " ", label).strip().casefold()
        existing_by_label = ""
        if merge_graph_entities and label_norm:
            existing_by_label = label_index.get(label_norm, "")
        if existing_by_label and existing_by_label in nodes:
            node_id = existing_by_label
        else:
            node_id = _alloc_node_id(candidate_id or label, used_ids, counter)
        if label_norm:
            label_index.setdefault(label_norm, node_id)
        if candidate_id:
            ref_aliases[candidate_id.casefold()] = node_id
        ref_aliases[node_id.casefold()] = node_id
        description = _clip_text(
            raw.get("description")
            or raw.get("desc")
            or raw.get("tooltip")
            or raw.get("note"),
            max_chars=_MAX_DESC_CHARS,
        )
        quote_text = _clip_text(
            raw.get("quote")
            or raw.get("citation")
            or raw.get("evidence")
            or "",
            max_chars=_MAX_DESC_CHARS,
        )
        href = _clip_href(
            raw.get("href")
            or raw.get("url")
            or raw.get("link")
            or "",
        )

        node = nodes.get(node_id)
        if node is None:
            node = GraphNode(
                node_id=node_id,
                label=label,
                description=description,
                quote=quote_text,
                href=href,
                children=[],
            )
            nodes[node_id] = node
        else:
            if label and (not node.label or len(label) > len(node.label)):
                node.label = label
                label_norm_new = re.sub(
                    r"\s+",
                    " ",
                    node.label,
                ).strip().casefold()
                if label_norm_new:
                    label_index[label_norm_new] = node_id
            if description and not node.description:
                node.description = description
            if quote_text and not node.quote:
                node.quote = quote_text
            if href and not node.href:
                node.href = href

        if parent_id and parent_id in nodes:
            parent = nodes[parent_id]
            if node_id not in parent.children:
                parent.children.append(node_id)
                auto_edges.append(GraphEdge(parent_id, node_id, ""))

        raw_children = raw.get("children")
        if raw_children is None:
            raw_children = raw.get("subnodes")
        if isinstance(raw_children, list):
            for child in raw_children:
                if isinstance(child, dict):
                    ensure_node(child, node_id)
                    continue
                if isinstance(child, str):
                    child_ref = child.strip()
                    if child_ref:
                        pending_children.append((node_id, child_ref))
        return node_id

    for item in raw_nodes:
        root_id = ensure_node(item, "")
        if root_id and root_id not in roots:
            roots.append(root_id)

    if not nodes:
        return None

    for parent_id, ref in pending_children:
        if parent_id not in nodes:
            continue
        child_id = resolve_ref(ref)
        if child_id == "":
            child_id = ensure_node({"id": ref, "label": ref}, "")
        if child_id == "" or child_id == parent_id:
            continue
        parent = nodes[parent_id]
        if child_id not in parent.children:
            parent.children.append(child_id)
            auto_edges.append(GraphEdge(parent_id, child_id, ""))

    explicit_edges: list[GraphEdge] = []
    raw_edges = payload.get("edges")
    if raw_edges is None:
        raw_edges = payload.get("links")
    if raw_edges is None:
        raw_edges = payload.get("relations")
    if raw_edges is None:
        raw_edges = payload.get("triples")
    if isinstance(raw_edges, list):
        for item in raw_edges:
            edge = _parse_edge(item, nodes, resolve_ref=resolve_ref)
            if edge is not None:
                explicit_edges.append(edge)

    if kind == "graph":
        # For knowledge graphs, explicit relations are authoritative.
        # Only fall back to hierarchy-derived links when no explicit relation exists.
        edge_source = explicit_edges if explicit_edges else auto_edges
        edges = _dedupe_edges(edge_source)
    else:
        edges = _dedupe_edges(auto_edges + explicit_edges)
    if len(edges) > _MAX_EDGES:
        edges = edges[:_MAX_EDGES]
    if kind == "graph":
        if not any(node.children for node in nodes.values()):
            for edge in edges:
                parent = nodes.get(edge.source_id)
                if parent is None:
                    continue
                child_id = edge.target_id
                if child_id and child_id not in parent.children:
                    parent.children.append(child_id)

    incoming: dict[str, int] = {node_id: 0 for node_id in nodes}
    for edge in edges:
        incoming[edge.target_id] = incoming.get(edge.target_id, 0) + 1

    explicit_roots: list[str] = []
    roots_raw = payload.get("roots")
    if isinstance(roots_raw, list):
        for item in roots_raw:
            ref = str(item or "").strip()
            if not ref:
                continue
            resolved = resolve_ref(ref)
            if resolved and resolved not in explicit_roots:
                explicit_roots.append(resolved)
    if explicit_roots:
        roots = explicit_roots
    else:
        ranked = [node_id for node_id in roots if incoming.get(node_id, 0) == 0]
        if ranked:
            roots = ranked
        else:
            roots = [
                node_id
                for node_id in sorted(nodes.keys())
                if incoming.get(node_id, 0) == 0
            ] or roots

    collapsed = _parse_collapsed_nodes(payload, nodes, roots)
    return GraphSpec(
        kind=kind,
        title=title,
        nodes=nodes,
        roots=roots,
        edges=edges,
        default_collapsed_ids=collapsed,
    )


def _clip_text(value: object, *, max_chars: int) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."


def _clip_href(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) > _MAX_LINK_CHARS:
        text = text[:_MAX_LINK_CHARS]
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", text):
        return text
    if text.startswith("/"):
        return text
    return ""


def _slug(value: str) -> str:
    raw = str(value or "").strip().casefold()
    if not raw:
        return "node"
    slug = re.sub(r"[^a-z0-9_.-]+", "-", raw).strip("-.")
    return slug or "node"


def _alloc_node_id(candidate: str, used_ids: set[str], fallback_index: int) -> str:
    base = _slug(candidate) if candidate else f"node-{fallback_index}"
    current = base
    idx = 2
    while current in used_ids:
        current = f"{base}-{idx}"
        idx += 1
    used_ids.add(current)
    return current


def _resolve_node_ref(ref: str, nodes: dict[str, GraphNode]) -> str:
    token = str(ref or "").strip()
    if not token:
        return ""
    if token in nodes:
        return token
    token_low = token.casefold()
    for node_id in nodes:
        if node_id.casefold() == token_low:
            return node_id
    for node_id, node in nodes.items():
        if node.label.casefold() == token_low:
            return node_id
    return ""


def _parse_edge(
    item: Any,
    nodes: dict[str, GraphNode],
    *,
    resolve_ref: Callable[[str], str] | None = None,
) -> GraphEdge | None:
    source = ""
    target = ""
    label = ""

    if isinstance(item, str):
        match = _EDGE_TEXT_RE.match(item.strip())
        if match is not None:
            source = match.group("src") or ""
            target = match.group("dst") or ""
            label = match.group("label") or ""
    elif isinstance(item, dict):
        source = str(
            item.get("from")
            or item.get("source")
            or item.get("start")
            or item.get("subject")
            or ""
        )
        target = str(
            item.get("to")
            or item.get("target")
            or item.get("end")
            or item.get("object")
            or ""
        )
        label = str(
            item.get("label")
            or item.get("relation")
            or item.get("predicate")
            or item.get("type")
            or ""
        )
    else:
        return None

    resolver = resolve_ref
    if resolver is None:
        resolver = lambda token: _resolve_node_ref(token, nodes)
    src_id = resolver(source)
    dst_id = resolver(target)
    if not src_id or not dst_id or src_id == dst_id:
        return None
    return GraphEdge(
        source_id=src_id,
        target_id=dst_id,
        label=_clip_text(label, max_chars=140),
    )


def _dedupe_edges(edges: list[GraphEdge]) -> list[GraphEdge]:
    labeled_pairs = {
        (edge.source_id, edge.target_id)
        for edge in edges
        if str(edge.label or "").strip()
    }
    out: list[GraphEdge] = []
    seen: set[tuple[str, str, str]] = set()
    for edge in edges:
        label = str(edge.label or "").strip()
        if (
            not label
            and (edge.source_id, edge.target_id) in labeled_pairs
        ):
            continue
        key = (edge.source_id, edge.target_id, label)
        if key in seen:
            continue
        seen.add(key)
        out.append(
            GraphEdge(
                source_id=edge.source_id,
                target_id=edge.target_id,
                label=label,
            )
        )
    return out


def _parse_collapsed_nodes(
    payload: dict[str, Any],
    nodes: dict[str, GraphNode],
    roots: list[str],
) -> set[str]:
    out: set[str] = set()
    raw = payload.get("collapsed")
    if raw is None:
        raw = payload.get("collapsed_nodes")

    if isinstance(raw, bool):
        if raw:
            out = {
                node_id
                for node_id, node in nodes.items()
                if node.children
            }
    elif isinstance(raw, list):
        for item in raw:
            ref = str(item or "").strip()
            if not ref:
                continue
            node_id = _resolve_node_ref(ref, nodes)
            if node_id and nodes[node_id].children:
                out.add(node_id)

    depth = 0
    try:
        depth = int(payload.get("collapse_depth", 0) or 0)
    except Exception:
        depth = 0
    if depth > 0:
        stack: list[tuple[str, int]] = [(node_id, 1) for node_id in roots]
        seen: set[str] = set()
        while stack:
            node_id, level = stack.pop()
            if node_id in seen or node_id not in nodes:
                continue
            seen.add(node_id)
            node = nodes[node_id]
            if level >= depth and node.children:
                out.add(node_id)
                continue
            for child_id in reversed(node.children):
                stack.append((child_id, level + 1))

    return out


def _render_tree_nodes(
    *,
    spec: GraphSpec,
    roots: list[str],
    collapsed_ids: set[str],
    focus_node_id: str,
    visited: set[str],
) -> str:
    lines: list[str] = ["<ul class='d2c-tree'>"]
    for node_id in roots:
        if node_id not in spec.nodes:
            continue
        lines.append(
            _render_one_node(
                spec=spec,
                node_id=node_id,
                collapsed_ids=collapsed_ids,
                focus_node_id=focus_node_id,
                visited=visited,
            )
        )
    lines.append("</ul>")
    return "".join(lines)


def _render_one_node(
    *,
    spec: GraphSpec,
    node_id: str,
    collapsed_ids: set[str],
    focus_node_id: str,
    visited: set[str],
) -> str:
    node = spec.nodes[node_id]
    visited.add(node_id)

    node_id_q = quote(node.node_id, safe="")
    is_collapsed = bool(node.children and node_id in collapsed_ids)
    toggle = "."
    if node.children:
        toggle_symbol = "+" if is_collapsed else "-"
        toggle = (
            f"<a class='d2c-toggle' href='d2c://graph/toggle?id={node_id_q}'"
            f" title='Knoten ein/ausklappen'>{toggle_symbol}</a>"
        )

    label_class = "d2c-node-label"
    if node.node_id == focus_node_id:
        label_class += " d2c-node-focus"

    tooltip = html.escape(node.description or node.label, quote=True)
    if node.quote:
        tooltip = html.escape(node.quote, quote=True)
    label_html = (
        f"<a class='{label_class}' href='d2c://graph/focus?id={node_id_q}'"
        f" title='{tooltip}'>{html.escape(node.label)}</a>"
    )

    link_html = ""
    if node.href:
        href = html.escape(node.href, quote=True)
        link_html = (
            f"<a class='d2c-node-link' href='{href}'"
            " title='Externer Link'>[link]</a>"
        )

    desc_html = ""
    if node.description:
        desc_html = (
            f"<span class='d2c-node-desc'>"
            f"{html.escape(_clip_text(node.description, max_chars=120))}"
            "</span>"
        )
    elif node.quote:
        desc_html = (
            f"<span class='d2c-node-desc'>"
            f"\"{html.escape(_clip_text(node.quote, max_chars=96))}\""
            "</span>"
        )

    lines = [f"<li>{toggle}{label_html}{link_html}{desc_html}"]
    if node.children and not is_collapsed:
        lines.append("<ul class='d2c-tree'>")
        for child_id in node.children:
            if child_id not in spec.nodes:
                continue
            lines.append(
                _render_one_node(
                    spec=spec,
                    node_id=child_id,
                    collapsed_ids=collapsed_ids,
                    focus_node_id=focus_node_id,
                    visited=visited,
                )
            )
        lines.append("</ul>")
    lines.append("</li>")
    return "".join(lines)


def _render_edges(*, spec: GraphSpec, focus_node_id: str) -> str:
    if not spec.edges:
        return "<p class='d2c-muted'>Keine zusaetzlichen Kanten definiert.</p>"

    lines = ["<ul class='d2c-edge-list'>"]
    for edge in spec.edges:
        src = spec.nodes.get(edge.source_id)
        dst = spec.nodes.get(edge.target_id)
        if src is None or dst is None:
            continue
        src_id_q = quote(src.node_id, safe="")
        dst_id_q = quote(dst.node_id, safe="")
        src_html = (
            f"<a class='d2c-node-label' href='d2c://graph/focus?id={src_id_q}'>"
            f"{html.escape(src.label)}</a>"
        )
        dst_html = (
            f"<a class='d2c-node-label' href='d2c://graph/focus?id={dst_id_q}'>"
            f"{html.escape(dst.label)}</a>"
        )
        mid = " -> "
        if edge.label:
            mid = f" <span class='d2c-edge-focus'>-- {html.escape(edge.label)} --</span> "
        row_class = ""
        if focus_node_id in {src.node_id, dst.node_id}:
            row_class = " class='d2c-edge-focus'"
        lines.append(f"<li{row_class}>{src_html}{mid}{dst_html}</li>")
    lines.append("</ul>")
    return "".join(lines)
