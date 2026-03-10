"""Domain models for structured mindmap/graph specifications."""
from __future__ import annotations

from dataclasses import dataclass, field


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
