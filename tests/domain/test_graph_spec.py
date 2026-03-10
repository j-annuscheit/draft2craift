from shared.domain.graph import GraphEdge, GraphNode, GraphSpec


def test_graph_spec_validation_accepts_valid_graph():
    spec = GraphSpec(
        nodes=[GraphNode("a", "A"), GraphNode("b", "B")],
        edges=[GraphEdge("a", "b", "rel")],
    )
    ok, message = spec.validate()
    assert ok is True
    assert message == ""


def test_graph_spec_validation_rejects_unknown_edge_node():
    spec = GraphSpec(
        nodes=[GraphNode("a", "A")],
        edges=[GraphEdge("a", "missing", "rel")],
    )
    ok, message = spec.validate()
    assert ok is False
    assert "unknown node id" in message.lower()
