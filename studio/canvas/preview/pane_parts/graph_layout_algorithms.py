"""CanvasPreviewPane method implementations."""
from __future__ import annotations

from .deps import *  # noqa: F403

@classmethod
def _layout_mindmap_nodes(
    cls,
    *,
    spec: GraphSpec,
    node_ids: list[str],
) -> dict[str, QPointF]:
    visible_set = set(node_ids)
    child_map: dict[str, list[str]] = {}
    for node_id in node_ids:
        node = spec.nodes.get(node_id)
        if node is None:
            child_map[node_id] = []
            continue
        child_map[node_id] = [
            child_id
            for child_id in node.children
            if child_id in visible_set
        ]

    roots: list[str] = [
        node_id
        for node_id in spec.roots
        if node_id in visible_set
    ]
    if not roots:
        roots = [node_ids[0]]

    assigned_children: dict[str, list[str]] = {
        node_id: []
        for node_id in node_ids
    }
    parent_of: dict[str, str] = {}

    def attach(node_id: str, ancestry: set[str]):
        if node_id in ancestry:
            return
        chain = set(ancestry)
        chain.add(node_id)
        for child_id in child_map.get(node_id, []):
            if child_id == node_id:
                continue
            if child_id in chain:
                continue
            if child_id in parent_of:
                continue
            parent_of[child_id] = node_id
            assigned_children[node_id].append(child_id)
            attach(child_id, chain)

    for root_id in roots:
        attach(root_id, set())

    root_set = set(roots)
    for node_id in node_ids:
        if node_id in root_set or node_id in parent_of:
            continue
        roots.append(node_id)
        root_set.add(node_id)
        attach(node_id, set())

    span_cache: dict[str, float] = {}

    def subtree_span(node_id: str, chain: set[str]) -> float:
        cached = span_cache.get(node_id)
        if cached is not None:
            return cached
        if node_id in chain:
            return 1.0
        next_chain = set(chain)
        next_chain.add(node_id)
        children = assigned_children.get(node_id, [])
        if not children:
            span_cache[node_id] = 1.0
            return 1.0
        total = 0.0
        for child_id in children:
            total += subtree_span(child_id, next_chain)
        total = max(1.0, total)
        span_cache[node_id] = total
        return total

    raw_positions: dict[str, tuple[float, float]] = {}

    primary_root = roots[0]
    raw_positions[primary_root] = (0.0, 0.0)

    def place_side(node_id: str, depth: int, side: int, start_y: float) -> float:
        span = subtree_span(node_id, set())
        children = assigned_children.get(node_id, [])
        if not children:
            center_y = start_y + (span / 2.0)
            raw_positions[node_id] = (float(side) * float(depth), center_y)
            return center_y

        cursor = start_y
        child_centers: list[float] = []
        for child_id in children:
            child_span = subtree_span(child_id, set())
            child_center = place_side(child_id, depth + 1, side, cursor)
            child_centers.append(child_center)
            cursor += child_span
        center_y = (
            sum(child_centers) / float(len(child_centers))
            if child_centers
            else start_y + (span / 2.0)
        )
        raw_positions[node_id] = (float(side) * float(depth), center_y)
        return center_y

    root_children = assigned_children.get(primary_root, [])
    right_children = root_children[::2]
    left_children = root_children[1::2]
    if not right_children and left_children:
        right_children, left_children = left_children, []

    def place_root_children(children: list[str], side: int):
        if not children:
            return
        total = sum(subtree_span(child_id, set()) for child_id in children)
        cursor = -total / 2.0
        for child_id in children:
            span = subtree_span(child_id, set())
            place_side(child_id, 1, side, cursor)
            cursor += span

    place_root_children(right_children, 1)
    place_root_children(left_children, -1)

    extra_root_y = 1.4
    for extra_root in roots[1:]:
        if extra_root in raw_positions:
            continue
        span = subtree_span(extra_root, set())
        center_y = extra_root_y + (span / 2.0)
        raw_positions[extra_root] = (0.0, center_y)
        place_side(extra_root, 1, 1, extra_root_y)
        extra_root_y += span + 0.9

    if not raw_positions:
        out: dict[str, QPointF] = {}
        for idx, node_id in enumerate(node_ids):
            out[node_id] = QPointF(float(idx), 0.0)
        return out

    xs = [point[0] for point in raw_positions.values()]
    ys = [point[1] for point in raw_positions.values()]
    center_x = (min(xs) + max(xs)) / 2.0
    center_y = (min(ys) + max(ys)) / 2.0
    fallback_y = (max(ys) if ys else 0.0) + 1.0

    out: dict[str, QPointF] = {}
    spill_idx = 0
    for node_id in node_ids:
        pos = raw_positions.get(node_id)
        if pos is None:
            pos = (0.0 + float(spill_idx), fallback_y)
            spill_idx += 1
        out[node_id] = QPointF(
            float((pos[0] - center_x) * 1.45),
            float((pos[1] - center_y) * 1.05),
        )
    return out
@staticmethod
def _layout_knowledge_graph_nodes(
    *,
    spec: GraphSpec,
    node_ids: list[str],
    edges: list[tuple[str, str, str]],
) -> dict[str, QPointF]:
    visible_set = set(node_ids)
    children: dict[str, list[str]] = {node_id: [] for node_id in node_ids}
    parents: dict[str, list[str]] = {node_id: [] for node_id in node_ids}
    neighbors: dict[str, set[str]] = {node_id: set() for node_id in node_ids}
    for source_id, target_id, _label in edges:
        if source_id not in visible_set or target_id not in visible_set:
            continue
        children[source_id].append(target_id)
        parents[target_id].append(source_id)
        neighbors[source_id].add(target_id)
        neighbors[target_id].add(source_id)

    components: list[list[str]] = []
    seen: set[str] = set()
    for node_id in sorted(node_ids):
        if node_id in seen:
            continue
        stack = [node_id]
        comp: list[str] = []
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            comp.append(current)
            stack.extend(sorted(neighbors.get(current, set()) - seen))
        components.append(sorted(comp))
    components.sort(key=lambda rows: (-len(rows), rows[0] if rows else ""))

    raw_positions: dict[str, tuple[float, float]] = {}
    component_cursor_y = 0.0
    component_gap = 1.2

    for comp_nodes in components:
        if not comp_nodes:
            continue
        comp_set = set(comp_nodes)
        roots = [node_id for node_id in spec.roots if node_id in comp_set]
        if not roots:
            roots = [
                node_id
                for node_id in comp_nodes
                if not [p for p in parents.get(node_id, []) if p in comp_set]
            ]
        if not roots:
            roots = [comp_nodes[0]]

        levels: dict[str, int] = {}
        queue: deque[tuple[str, int]] = deque((root_id, 0) for root_id in roots)
        while queue:
            node_id, depth = queue.popleft()
            prev = levels.get(node_id)
            if prev is not None and depth >= prev:
                continue
            levels[node_id] = depth
            for child_id in children.get(node_id, []):
                if child_id in comp_set:
                    queue.append((child_id, depth + 1))

        fallback_level = max(levels.values(), default=-1) + 1
        for node_id in comp_nodes:
            if node_id in levels:
                continue
            known_parent_levels = [
                levels[parent_id]
                for parent_id in parents.get(node_id, [])
                if parent_id in levels
            ]
            if known_parent_levels:
                levels[node_id] = max(known_parent_levels) + 1
            else:
                levels[node_id] = fallback_level

        max_level = max(levels.values(), default=0)
        by_level: dict[int, list[str]] = {
            level: []
            for level in range(max_level + 1)
        }
        for node_id in comp_nodes:
            by_level.setdefault(levels.get(node_id, 0), []).append(node_id)

        level_order: dict[str, float] = {}
        comp_positions: dict[str, tuple[float, float]] = {}
        max_level_height = 1
        for level in range(max_level + 1):
            level_nodes = by_level.get(level, [])
            if not level_nodes:
                continue

            def barycenter(node_id: str) -> float:
                preds = [
                    parent_id
                    for parent_id in parents.get(node_id, [])
                    if parent_id in level_order
                ]
                if preds:
                    return sum(level_order[p] for p in preds) / float(len(preds))
                if node_id in roots:
                    return float(roots.index(node_id))
                return float(comp_nodes.index(node_id))

            level_nodes.sort(key=lambda node_id: (barycenter(node_id), node_id))
            count = len(level_nodes)
            max_level_height = max(max_level_height, count)
            for idx, node_id in enumerate(level_nodes):
                y = float(idx) - (float(count - 1) / 2.0)
                comp_positions[node_id] = (float(level), y)
                level_order[node_id] = y

        for node_id, (x, y) in comp_positions.items():
            raw_positions[node_id] = (x, y + component_cursor_y)
        component_cursor_y += float(max_level_height) + component_gap

    if not raw_positions:
        out: dict[str, QPointF] = {}
        for idx, node_id in enumerate(node_ids):
            out[node_id] = QPointF(float(idx), 0.0)
        return out

    xs = [point[0] for point in raw_positions.values()]
    ys = [point[1] for point in raw_positions.values()]
    center_x = (min(xs) + max(xs)) / 2.0
    center_y = (min(ys) + max(ys)) / 2.0

    out: dict[str, QPointF] = {}
    for node_id in node_ids:
        pos = raw_positions.get(node_id)
        if pos is None:
            pos = (0.0, 0.0)
        out[node_id] = QPointF(
            float((pos[0] - center_x) * 1.35),
            float((pos[1] - center_y) * 1.1),
        )
    return out

__all__ = [
    "_layout_mindmap_nodes",
    "_layout_knowledge_graph_nodes",
]
