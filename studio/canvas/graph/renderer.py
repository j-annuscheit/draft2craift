"""Structured graph HTML rendering helpers for studio preview."""
from __future__ import annotations

import html
from urllib.parse import quote

from shared.domain.graph_codec import (
    contains_structured_graph,
    extract_graph_spec,
    graph_spec_signature,
    spec_to_markdown,
)
from shared.domain.graph_spec import GraphSpec

_MAX_LABEL_CHARS = 180


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


def _clip_text(value: object, *, max_chars: int) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."


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
            f"{html.escape(_clip_text(src.label, max_chars=_MAX_LABEL_CHARS))}</a>"
        )
        dst_html = (
            f"<a class='d2c-node-label' href='d2c://graph/focus?id={dst_id_q}'>"
            f"{html.escape(_clip_text(dst.label, max_chars=_MAX_LABEL_CHARS))}</a>"
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


__all__ = [
    "GraphSpec",
    "contains_structured_graph",
    "extract_graph_spec",
    "graph_spec_signature",
    "spec_to_markdown",
    "render_graph_html",
]
