"""Rendering helpers for map results."""
from __future__ import annotations

from shared.domain.graph_codec import spec_to_markdown


def render_markdown(spec) -> str:
    return spec_to_markdown(spec)
