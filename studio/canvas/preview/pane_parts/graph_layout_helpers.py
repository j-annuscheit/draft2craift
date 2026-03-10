"""CanvasPreviewPane method implementations."""
from __future__ import annotations

from .deps import *  # noqa: F403

@staticmethod
def _estimate_graph_node_size(
    spec: GraphSpec,
    *,
    node_id: str,
    expandable_nodes: set[str],
) -> tuple[float, float]:
    node = spec.nodes.get(node_id)
    if node is None:
        return 190.0, 50.0
    label = str(node.label or node.node_id)
    display_label = label if len(label) <= 36 else (label[:33] + "...")
    if node_id in expandable_nodes:
        display_label = f"[-] {display_label}"

    quote = ""
    if node.quote:
        quote = str(node.quote).strip()
    if quote and len(quote) > 96:
        quote = quote[:93] + "..."

    width = 190.0
    if len(display_label) > 22:
        width = 220.0
    if quote:
        width = max(width, 250.0)

    lines = 1
    if quote and not node.children:
        lines = 2
    elif node.description:
        lines = 2
    height = 50.0 + (22.0 if lines > 1 else 0.0)
    return float(width), float(height)
@staticmethod
def _resolve_graph_node_overlaps(
    *,
    centers: dict[str, QPointF],
    node_dims: dict[str, tuple[float, float]],
    fixed_nodes: set[str],
    scene_w: float,
    scene_h: float,
) -> None:
    if len(centers) < 2:
        return
    node_ids = list(centers.keys())
    margin = 8.0
    max_iterations = 80

    for _ in range(max_iterations):
        changed = False
        for idx, left_id in enumerate(node_ids):
            left_center = centers.get(left_id)
            if left_center is None:
                continue
            left_w, left_h = node_dims.get(left_id, (190.0, 50.0))
            for right_id in node_ids[idx + 1:]:
                right_center = centers.get(right_id)
                if right_center is None:
                    continue
                right_w, right_h = node_dims.get(right_id, (190.0, 50.0))

                dx = float(right_center.x() - left_center.x())
                dy = float(right_center.y() - left_center.y())
                min_dx = (left_w * 0.5) + (right_w * 0.5) + margin
                min_dy = (left_h * 0.5) + (right_h * 0.5) + margin
                overlap_x = min_dx - abs(dx)
                overlap_y = min_dy - abs(dy)
                if overlap_x <= 0.0 or overlap_y <= 0.0:
                    continue

                move_x = overlap_x if overlap_x < overlap_y else 0.0
                move_y = overlap_y if overlap_y <= overlap_x else 0.0
                if move_x <= 0.0 and move_y <= 0.0:
                    move_x = overlap_x * 0.5
                    move_y = overlap_y * 0.5

                sign_x = 1.0 if dx >= 0.0 else -1.0
                sign_y = 1.0 if dy >= 0.0 else -1.0
                if abs(dx) < 1e-6:
                    sign_x = 1.0 if left_id < right_id else -1.0
                if abs(dy) < 1e-6:
                    sign_y = 1.0 if left_id < right_id else -1.0

                left_fixed = left_id in fixed_nodes
                right_fixed = right_id in fixed_nodes
                if left_fixed and right_fixed:
                    continue

                if left_fixed:
                    left_shift = 0.0
                    right_shift = 1.0
                elif right_fixed:
                    left_shift = 1.0
                    right_shift = 0.0
                else:
                    left_shift = 0.5
                    right_shift = 0.5

                if move_x > 0.0:
                    left_center.setX(left_center.x() - (sign_x * move_x * left_shift))
                    right_center.setX(right_center.x() + (sign_x * move_x * right_shift))
                if move_y > 0.0:
                    left_center.setY(left_center.y() - (sign_y * move_y * left_shift))
                    right_center.setY(right_center.y() + (sign_y * move_y * right_shift))
                changed = True

        if not changed:
            break

    for node_id, center in centers.items():
        width, height = node_dims.get(node_id, (190.0, 50.0))
        half_w = width * 0.5
        half_h = height * 0.5
        min_x = 26.0 + half_w
        max_x = max(min_x, scene_w - 26.0 - half_w)
        min_y = 26.0 + half_h
        max_y = max(min_y, scene_h - 26.0 - half_h)
        center.setX(max(min_x, min(max_x, float(center.x()))))
        center.setY(max(min_y, min(max_y, float(center.y()))))

__all__ = [
    "_estimate_graph_node_size",
    "_resolve_graph_node_overlaps",
]
