"""CanvasPreviewPane method implementations."""
from __future__ import annotations

from .deps import *  # noqa: F403

def _render_structured_graph_scene(self, spec: GraphSpec):
    scene = self._graph_scene
    view = self._graph_view
    if scene is None or view is None:
        # Fallback for environments without graphics scene: keep HTML rendering.
        html_view = render_graph_html(
            spec,
            collapsed_ids=self._graph_collapsed_ids,
            focus_node_id=self._graph_focus_node_id,
        )
        self._view.setHtml(html_view)
        doc = QTextDocument()
        doc.setHtml(html_view)
        self._graph_plain_text = (doc.toPlainText() or "").replace(
            "\r\n",
            "\n",
        )
        return

    scene.clear()
    palette = self.palette()
    text_color = QColor(palette.color(QPalette.ColorRole.Text))
    muted_color = QColor(palette.color(QPalette.ColorRole.PlaceholderText))
    base_color = QColor(palette.color(QPalette.ColorRole.Base))
    alt_color = QColor(palette.color(QPalette.ColorRole.AlternateBase))
    highlight_color = QColor(palette.color(QPalette.ColorRole.Highlight))
    link_color = QColor(palette.color(QPalette.ColorRole.Link))
    mid_color = QColor(palette.color(QPalette.ColorRole.Mid))
    focus_fill = QColor(highlight_color)
    focus_fill.setAlpha(58)
    leaf_fill = QColor(alt_color)
    leaf_fill = leaf_fill.lighter(108)
    root_fill = QColor(base_color)
    root_fill = root_fill.lighter(112)
    normal_fill = QColor(alt_color)
    current_scale = abs(float(view.transform().m11() or 1.0))
    if current_scale < 0.45 or current_scale > 5.0:
        view.reset_zoom()
    node_ids, edges = self._visible_graph_data(spec)
    if not node_ids:
        text_item = scene.addText("Keine Knoten.")
        text_item.setDefaultTextColor(muted_color)
        self._graph_plain_text = ""
        return

    layout_positions = self._layout_graph_nodes(
        spec=spec,
        node_ids=node_ids,
        edges=edges,
    )

    include_edges = spec.kind == "graph"
    expandable_nodes = self._expandable_graph_nodes(
        spec,
        include_edges=include_edges,
    )
    node_dims: dict[str, tuple[float, float]] = {
        node_id: self._estimate_graph_node_size(
            spec,
            node_id=node_id,
            expandable_nodes=expandable_nodes,
        )
        for node_id in node_ids
    }

    # Normalize coordinates into a readable scene area.
    xs = [layout_positions[node_id].x() for node_id in node_ids]
    ys = [layout_positions[node_id].y() for node_id in node_ids]
    min_x = min(xs)
    max_x = max(xs)
    min_y = min(ys)
    max_y = max(ys)
    span_x = max(0.01, max_x - min_x)
    span_y = max(0.01, max_y - min_y)
    if spec.kind == "mindmap":
        scene_w = max(
            980.0,
            ((span_x + 1.0) * 215.0),
        )
        scene_h = max(
            680.0,
            ((span_y + 1.0) * 155.0),
        )
    else:
        scene_w = max(
            920.0,
            235.0 * math.sqrt(float(len(node_ids))),
            ((span_x + 1.0) * 175.0),
        )
        scene_h = max(
            620.0,
            185.0 * math.sqrt(float(len(node_ids))),
            ((span_y + 1.0) * 145.0),
        )
    pad = 90.0

    centers: dict[str, QPointF] = {}
    for node_id in node_ids:
        raw = layout_positions[node_id]
        x = pad + ((raw.x() - min_x) / span_x) * (scene_w - (2.0 * pad))
        y = pad + ((raw.y() - min_y) / span_y) * (scene_h - (2.0 * pad))
        centers[node_id] = QPointF(x, y)

    for node_id, manual in list(self._graph_manual_positions.items()):
        if node_id not in centers:
            continue
        centers[node_id] = QPointF(
            max(28.0, min(scene_w - 28.0, float(manual.x()))),
            max(28.0, min(scene_h - 28.0, float(manual.y()))),
        )

    self._resolve_graph_node_overlaps(
        centers=centers,
        node_dims=node_dims,
        fixed_nodes=set(self._graph_manual_positions.keys()) & set(node_ids),
        scene_w=scene_w,
        scene_h=scene_h,
    )

    focus = self._graph_focus_node_id
    plain_rows: list[str] = [spec.title]
    node_items: dict[str, GraphNodeItem] = {}
    for node_id in node_ids:
        node = spec.nodes[node_id]
        center = centers[node_id]
        is_root = node_id in spec.roots
        is_leaf = not node.children
        is_focus = node_id == focus

        label = str(node.label or node.node_id)
        raw_quote = str(node.quote or "").strip()
        quote_preview = raw_quote
        if quote_preview and len(quote_preview) > 96:
            quote_preview = quote_preview[:93] + "..."
        display_label = label if len(label) <= 36 else (label[:33] + "...")
        if node_id in expandable_nodes:
            marker = "[+]" if node_id in self._graph_collapsed_ids else "[-]"
            display_label = f"{marker} {display_label}"
        lines = [display_label]
        if quote_preview and is_leaf:
            lines.append(f"\"{quote_preview}\"")
        elif node.description:
            desc = str(node.description).strip()
            if len(desc) > 72:
                desc = desc[:69] + "..."
            lines.append(desc)
        text = "\n".join(lines)

        width, height = node_dims.get(node_id, (190.0, 50.0))

        node_item = GraphNodeItem(
            node_id=node_id,
            width=width,
            height=height,
            display_text=text,
            on_click=self._on_graph_node_clicked,
            on_toggle=self._on_graph_node_toggled,
            on_moved=self._on_graph_node_moved,
        )
        node_item.setPos(center.x() - (width / 2.0), center.y() - (height / 2.0))
        node_item.setBrush(
            QBrush(
                focus_fill
                if is_focus
                else leaf_fill
                if is_leaf
                else root_fill
                if is_root
                else normal_fill
            )
        )
        node_item.setPen(
            QPen(
                highlight_color
                if is_focus
                else link_color
                if is_leaf
                else highlight_color
                if is_root
                else mid_color,
                2.2 if is_focus else 1.4,
            )
        )
        tip_parts = [label]
        if node.description:
            tip_parts.append(str(node.description))
        if raw_quote:
            tip_parts.append(f"Zitat: \"{raw_quote}\"")
        if node.href:
            tip_parts.append(f"Link: {node.href}")
        tip_parts.append("Klick: Fokus | Doppelklick: auf/zu oder Link")
        node_item.setToolTip("\n".join(tip_parts))
        node_item.set_text_color(text_color)
        node_item.setZValue(2.0)
        scene.addItem(node_item)
        node_items[node_id] = node_item

        plain_rows.append(label)
        if raw_quote:
            plain_rows.append(raw_quote)

    for source_id, target_id, label in edges:
        source_item = node_items.get(source_id)
        target_item = node_items.get(target_id)
        if source_item is None or target_item is None:
            continue
        src_w, src_h = node_dims.get(source_id, (190.0, 50.0))
        dst_w, dst_h = node_dims.get(target_id, (190.0, 50.0))
        connected = focus in {source_id, target_id}
        edge_color = highlight_color if connected else mid_color
        line_pen = QPen(edge_color, 2.2 if connected else 1.35)
        line_item = QGraphicsLineItem()
        line_item.setPen(line_pen)
        line_item.setZValue(0.4)
        scene.addItem(line_item)

        arrow = QGraphicsPolygonItem()
        arrow.setBrush(QBrush(edge_color))
        arrow.setPen(QPen(edge_color, 1.0))
        arrow.setZValue(0.5)
        scene.addItem(arrow)

        label_item: QGraphicsTextItem | None = None
        if label:
            label_item = QGraphicsTextItem(label)
            label_item.setDefaultTextColor(
                highlight_color if connected else muted_color
            )
            label_item.setZValue(1.2)
            label_item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            scene.addItem(label_item)

        def update_edge_geometry(
            src_item: GraphNodeItem = source_item,
            dst_item: GraphNodeItem = target_item,
            src_size: tuple[float, float] = (src_w, src_h),
            dst_size: tuple[float, float] = (dst_w, dst_h),
            line_ref: QGraphicsLineItem = line_item,
            arrow_ref: QGraphicsPolygonItem = arrow,
            label_ref: QGraphicsTextItem | None = label_item,
        ):
            p1 = src_item.center_pos()
            p2 = dst_item.center_pos()
            dx = p2.x() - p1.x()
            dy = p2.y() - p1.y()
            dist = math.hypot(dx, dy)
            if dist < 1.0:
                line_ref.setLine(p1.x(), p1.y(), p2.x(), p2.y())
                arrow_ref.setPolygon(QPolygonF())
                if label_ref is not None:
                    label_ref.setPos(p1.x(), p1.y())
                return
            ux = dx / dist
            uy = dy / dist
            src_pad = max(22.0, min(src_size[0], src_size[1]) * 0.22)
            dst_pad = max(22.0, min(dst_size[0], dst_size[1]) * 0.22)
            line_start = QPointF(
                p1.x() + (ux * src_pad),
                p1.y() + (uy * src_pad),
            )
            line_end = QPointF(
                p2.x() - (ux * dst_pad),
                p2.y() - (uy * dst_pad),
            )
            line_ref.setLine(
                line_start.x(),
                line_start.y(),
                line_end.x(),
                line_end.y(),
            )
            arrow_size = 10.0
            arrow_width = 5.0
            left = QPointF(
                line_end.x() - (ux * arrow_size) - (uy * arrow_width),
                line_end.y() - (uy * arrow_size) + (ux * arrow_width),
            )
            right = QPointF(
                line_end.x() - (ux * arrow_size) + (uy * arrow_width),
                line_end.y() - (uy * arrow_size) - (ux * arrow_width),
            )
            arrow_ref.setPolygon(QPolygonF([line_end, left, right]))
            if label_ref is not None:
                mid_x = (line_start.x() + line_end.x()) / 2.0
                mid_y = (line_start.y() + line_end.y()) / 2.0
                label_ref.setPos(mid_x + 4.0, mid_y - 8.0)

        update_edge_geometry()
        source_item.add_move_callback(update_edge_geometry)
        target_item.add_move_callback(update_edge_geometry)

    for source_id, target_id, label in edges:
        src = spec.nodes.get(source_id)
        dst = spec.nodes.get(target_id)
        if src is None or dst is None:
            continue
        if label:
            plain_rows.append(f"{src.label} --{label}--> {dst.label}")
        else:
            plain_rows.append(f"{src.label} --> {dst.label}")

    self._graph_plain_text = "\n".join(plain_rows).replace("\r\n", "\n")
    scene.setSceneRect(0.0, 0.0, scene_w, scene_h)
    if focus:
        # Keep focused node centered after redraw.
        for item in scene.items():
            if isinstance(item, GraphNodeItem) and item._node_id == focus:  # pylint: disable=protected-access
                view.centerOn(item.sceneBoundingRect().center())
                break
    else:
        view.centerOn(scene.sceneRect().center())
def scroll_to_bottom(self):
    if self._structured_view_active and self._graph_view is not None and self._graph_scene is not None:
        self._graph_view.centerOn(self._graph_scene.sceneRect().center())
        return
    scrollbar = self._view.verticalScrollBar()
    scrollbar.setValue(scrollbar.maximum())

__all__ = [
    "_render_structured_graph_scene",
    "scroll_to_bottom",
]
