"""CanvasPreviewPane method implementations."""
from __future__ import annotations

from .deps import *  # noqa: F403

@staticmethod
def _graph_child_map(
    spec: GraphSpec,
    *,
    include_edges: bool,
) -> dict[str, list[str]]:
    nodes = spec.nodes
    out: dict[str, list[str]] = {}
    for node_id, node in nodes.items():
        out[node_id] = [child for child in node.children if child in nodes]
    if include_edges:
        for edge in spec.edges:
            src = edge.source_id
            dst = edge.target_id
            if src not in nodes or dst not in nodes:
                continue
            bucket = out.setdefault(src, [])
            if dst not in bucket:
                bucket.append(dst)
    return out
@classmethod
def _expandable_graph_nodes(
    cls,
    spec: GraphSpec,
    *,
    include_edges: bool,
) -> set[str]:
    child_map = cls._graph_child_map(spec, include_edges=include_edges)
    return {
        node_id
        for node_id, children in child_map.items()
        if children
    }
@classmethod
def _collapsed_hidden_nodes(
    cls,
    spec: GraphSpec,
    *,
    collapsed_ids: set[str],
    include_edges: bool,
) -> set[str]:
    if not collapsed_ids:
        return set()
    child_map = cls._graph_child_map(spec, include_edges=include_edges)
    hidden: set[str] = set()
    for start in collapsed_ids:
        stack = list(child_map.get(start, []))
        while stack:
            node_id = stack.pop()
            if node_id in hidden:
                continue
            hidden.add(node_id)
            stack.extend(child_map.get(node_id, []))
    return hidden
@classmethod
def _collect_descendants(
    cls,
    spec: GraphSpec,
    *,
    start_id: str,
    include_edges: bool,
) -> set[str]:
    nodes = spec.nodes
    if start_id not in nodes:
        return set()
    child_map = cls._graph_child_map(spec, include_edges=include_edges)
    out: set[str] = set()
    stack = list(child_map.get(start_id, []))
    while stack:
        node_id = stack.pop()
        if node_id in out or node_id not in nodes:
            continue
        out.add(node_id)
        stack.extend(child_map.get(node_id, []))
    return out
@classmethod
def _initial_collapsed_graph_nodes(
    cls,
    spec: GraphSpec,
) -> set[str]:
    nodes = spec.nodes
    if not nodes:
        return set()
    include_edges = spec.kind == "graph"
    child_map = cls._graph_child_map(spec, include_edges=include_edges)
    expandable = {
        node_id
        for node_id, children in child_map.items()
        if children
    }
    if not expandable:
        return set()

    roots = [node_id for node_id in spec.roots if node_id in nodes]
    if not roots:
        roots = [sorted(nodes.keys())[0]]

    depths: dict[str, int] = {}
    queue: deque[tuple[str, int]] = deque((node_id, 0) for node_id in roots)
    while queue:
        node_id, depth = queue.popleft()
        prev = depths.get(node_id)
        if prev is not None and depth >= prev:
            continue
        depths[node_id] = depth
        for child_id in child_map.get(node_id, []):
            if child_id not in nodes:
                continue
            queue.append((child_id, depth + 1))

    for node_id in sorted(nodes.keys()):
        if node_id not in depths:
            depths[node_id] = 0

    return {
        node_id
        for node_id in expandable
        if depths.get(node_id, 0) >= 1
    }
@staticmethod
def _open_href(href: str):
    target = str(href or "").strip()
    if not target:
        return
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target):
        QDesktopServices.openUrl(QUrl(target))
        return
    if target.startswith("/"):
        QDesktopServices.openUrl(QUrl.fromLocalFile(target))
def _visible_graph_data(
    self,
    spec: GraphSpec,
) -> tuple[list[str], list[tuple[str, str, str]]]:
    nodes = spec.nodes
    if not nodes:
        return [], []

    roots = [node_id for node_id in spec.roots if node_id in nodes]
    if not roots:
        roots = [sorted(nodes.keys())[0]]

    visible: list[str] = []
    seen: set[str] = set()

    def walk(start_id: str):
        stack = [start_id]
        while stack:
            node_id = stack.pop()
            if node_id in seen or node_id not in nodes:
                continue
            seen.add(node_id)
            visible.append(node_id)
            node = nodes[node_id]
            if node_id in self._graph_collapsed_ids:
                continue
            for child_id in reversed(node.children):
                if child_id in nodes:
                    stack.append(child_id)

    if spec.kind == "graph":
        hidden = self._collapsed_hidden_nodes(
            spec,
            collapsed_ids=self._graph_collapsed_ids,
            include_edges=True,
        )
        visible = [
            node_id
            for node_id in sorted(nodes.keys())
            if node_id not in hidden
        ]
        seen = set(visible)
    else:
        hidden = self._collapsed_hidden_nodes(
            spec,
            collapsed_ids=self._graph_collapsed_ids,
            include_edges=False,
        )
        for root_id in roots:
            walk(root_id)
        for node_id in sorted(nodes.keys()):
            if node_id not in seen:
                if node_id in hidden:
                    continue
                walk(node_id)

    visible_set = set(visible)
    edges: list[tuple[str, str, str]] = []
    for edge in spec.edges:
        if edge.source_id not in visible_set or edge.target_id not in visible_set:
            continue
        edges.append((edge.source_id, edge.target_id, edge.label))
    return visible, edges
def _layout_graph_nodes(
    self,
    *,
    spec: GraphSpec,
    node_ids: list[str],
    edges: list[tuple[str, str, str]],
) -> dict[str, QPointF]:
    if not node_ids:
        return {}
    if len(node_ids) == 1:
        return {node_ids[0]: QPointF(0.0, 0.0)}
    if spec.kind == "mindmap":
        return self._layout_mindmap_nodes(spec=spec, node_ids=node_ids)
    return self._layout_knowledge_graph_nodes(
        spec=spec,
        node_ids=node_ids,
        edges=edges,
    )

__all__ = [
    "_graph_child_map",
    "_expandable_graph_nodes",
    "_collapsed_hidden_nodes",
    "_collect_descendants",
    "_initial_collapsed_graph_nodes",
    "_open_href",
    "_visible_graph_data",
    "_layout_graph_nodes",
]
