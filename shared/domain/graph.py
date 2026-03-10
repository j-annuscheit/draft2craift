"""Domain graph structures for mindmap and graph rendering."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class GraphNode:
    """A graph node."""

    node_id: str
    label: str


@dataclass(frozen=True, slots=True)
class GraphEdge:
    """A directed graph edge."""

    source_id: str
    target_id: str
    label: str = ""


@dataclass(slots=True)
class GraphSpec:
    """Graph collection with basic consistency checks."""

    nodes: list[GraphNode] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)

    def node_ids(self) -> set[str]:
        return {node.node_id for node in self.nodes}

    def validate(self) -> tuple[bool, str]:
        ids = self.node_ids()
        if len(ids) != len(self.nodes):
            return False, "Duplicate node ids detected."
        for edge in self.edges:
            if edge.source_id not in ids or edge.target_id not in ids:
                return False, "Edge references unknown node id."
        return True, ""
