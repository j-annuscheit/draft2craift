"""CanvasPreviewPane method implementations."""
from __future__ import annotations

from .deps import *  # noqa: F403

def _expand_all_graph_nodes(self):
    spec = self._structured_graph_spec
    if spec is None:
        return
    if not self._graph_collapsed_ids:
        return
    self._graph_collapsed_ids.clear()
    self._render_structured_graph_scene(spec)
def _collapse_all_graph_nodes(self):
    spec = self._structured_graph_spec
    if spec is None:
        return
    include_edges = spec.kind == "graph"
    collapsed = self._expandable_graph_nodes(
        spec,
        include_edges=include_edges,
    )
    if collapsed == self._graph_collapsed_ids:
        return
    self._graph_collapsed_ids = collapsed
    self._render_structured_graph_scene(spec)
def _clear_graph_focus(self):
    spec = self._structured_graph_spec
    if spec is None:
        return
    if not self._graph_focus_node_id:
        return
    self._graph_focus_node_id = ""
    self._render_structured_graph_scene(spec)
def _visible_node_items(self) -> dict[str, GraphNodeItem]:
    scene = self._graph_scene
    if scene is None:
        return {}
    out: dict[str, GraphNodeItem] = {}
    for item in scene.items():
        if isinstance(item, GraphNodeItem):
            out[item._node_id] = item  # pylint: disable=protected-access
    return out
def _optimize_visible_graph_layout(self):
    spec = self._structured_graph_spec
    scene = self._graph_scene
    view = self._graph_view
    if spec is None or scene is None or view is None:
        return
    if nx is None:
        return
    node_items = self._visible_node_items()
    if len(node_items) < 2:
        return

    visible_nodes, visible_edges = self._visible_graph_data(spec)
    visible_set = {
        node_id
        for node_id in visible_nodes
        if node_id in node_items
    }
    if len(visible_set) < 2:
        return

    graph = nx.Graph()
    graph.add_nodes_from(sorted(visible_set))
    for source_id, target_id, _label in visible_edges:
        if source_id in visible_set and target_id in visible_set:
            graph.add_edge(source_id, target_id)

    current_pos = {
        node_id: (
            float(node_items[node_id].center_pos().x()),
            float(node_items[node_id].center_pos().y()),
        )
        for node_id in graph.nodes
    }
    scene_rect = scene.sceneRect()
    if scene_rect.width() <= 1.0 or scene_rect.height() <= 1.0:
        scene_rect = scene.itemsBoundingRect().adjusted(-80, -80, 80, 80)
        if scene_rect.width() <= 1.0 or scene_rect.height() <= 1.0:
            scene_rect = scene.itemsBoundingRect().adjusted(-180, -140, 180, 140)

    node_count = max(2, graph.number_of_nodes())
    area = max(1.0, float(scene_rect.width()) * float(scene_rect.height()))
    k_value = max(58.0, min(230.0, math.sqrt(area / float(node_count)) * 0.42))

    try:
        target_pos = nx.spring_layout(
            graph,
            pos=current_pos,
            seed=17,
            k=k_value,
            iterations=180,
            scale=None,
        )
    except Exception:
        return

    blend = 0.42
    margin = 18.0
    for node_id, item in node_items.items():
        if node_id not in target_pos:
            continue
        current_center = item.center_pos()
        target = target_pos[node_id]
        target_x = float(target[0])
        target_y = float(target[1])
        center_x = ((1.0 - blend) * float(current_center.x())) + (blend * target_x)
        center_y = ((1.0 - blend) * float(current_center.y())) + (blend * target_y)

        width = float(item.rect().width())
        height = float(item.rect().height())
        half_w = width / 2.0
        half_h = height / 2.0
        center_x = max(
            float(scene_rect.left()) + half_w + margin,
            min(float(scene_rect.right()) - half_w - margin, center_x),
        )
        center_y = max(
            float(scene_rect.top()) + half_h + margin,
            min(float(scene_rect.bottom()) - half_h - margin, center_y),
        )
        item.setPos(center_x - half_w, center_y - half_h)
        self._graph_manual_positions[node_id] = QPointF(center_x, center_y)

    bounds = scene.itemsBoundingRect().adjusted(-36.0, -36.0, 36.0, 36.0)
    if bounds.width() > 1.0 and bounds.height() > 1.0:
        scene.setSceneRect(bounds)
    focus_item = node_items.get(self._graph_focus_node_id)
    if focus_item is not None:
        view.centerOn(focus_item.center_pos())
def _reflow_visible_graph_layout(self):
    spec = self._structured_graph_spec
    if spec is None:
        return
    visible_nodes, _visible_edges = self._visible_graph_data(spec)
    if not visible_nodes:
        return
    for node_id in visible_nodes:
        self._graph_manual_positions.pop(node_id, None)
    self._graph_layout_nonce += 1
    self._render_structured_graph_scene(spec)
def _on_graph_node_clicked(self, node_id: str, open_link: bool):
    spec = self._structured_graph_spec
    if spec is None:
        return
    node = spec.nodes.get(str(node_id or ""))
    if node is None:
        return
    self._graph_focus_node_id = node.node_id
    self._render_structured_graph_scene(spec)
    if open_link and node.href:
        self._open_href(node.href)
def _on_graph_node_toggled(self, node_id: str):
    spec = self._structured_graph_spec
    if spec is None:
        return
    node = spec.nodes.get(str(node_id or ""))
    if node is None:
        return
    include_edges = spec.kind == "graph"
    expandable = self._expandable_graph_nodes(spec, include_edges=include_edges)
    if node.node_id in expandable:
        if node.node_id in self._graph_collapsed_ids:
            self._graph_collapsed_ids.discard(node.node_id)
            # MindMap UX: when opening a node, start one level deep and keep
            # descendant branches collapsed until explicitly opened.
            if spec.kind == "mindmap":
                descendants = self._collect_descendants(
                    spec,
                    start_id=node.node_id,
                    include_edges=False,
                )
                collapsed_descendants = {
                    child_id
                    for child_id in descendants
                    if child_id in expandable
                }
                self._graph_collapsed_ids.update(collapsed_descendants)
        else:
            self._graph_collapsed_ids.add(node.node_id)
        self._render_structured_graph_scene(spec)
        return
    if node.href:
        self._open_href(node.href)
def _on_graph_node_moved(self, node_id: str, center: QPointF):
    node_key = str(node_id or "").strip()
    if not node_key:
        return
    self._graph_manual_positions[node_key] = QPointF(center)

__all__ = [
    "_expand_all_graph_nodes",
    "_collapse_all_graph_nodes",
    "_clear_graph_focus",
    "_visible_node_items",
    "_optimize_visible_graph_layout",
    "_reflow_visible_graph_layout",
    "_on_graph_node_clicked",
    "_on_graph_node_toggled",
    "_on_graph_node_moved",
]
