"""Bind split method implementations to CanvasPreviewPane."""
from __future__ import annotations

from . import (
    theme_setup,
    binding_controls,
    interaction_events,
    highlight_interactions,
    search_sync,
    view_state,
    highlight_render,
    preview_styling,
    markdown_render,
    markdown_tables,
    markdown_restore,
    editing_commit,
    formatting_actions,
    render_sync,
    graph_state,
    graph_model,
    graph_layout_algorithms,
    graph_layout_helpers,
    graph_scene,
)

_METHOD_MODULES = (
    theme_setup,
    binding_controls,
    interaction_events,
    highlight_interactions,
    search_sync,
    view_state,
    highlight_render,
    preview_styling,
    markdown_render,
    markdown_tables,
    markdown_restore,
    editing_commit,
    formatting_actions,
    render_sync,
    graph_state,
    graph_model,
    graph_layout_algorithms,
    graph_layout_helpers,
    graph_scene,
)

def bind_canvas_preview_pane(cls):
    for module in _METHOD_MODULES:
        for name in getattr(module, "__all__", ()):
            setattr(cls, name, getattr(module, name))
