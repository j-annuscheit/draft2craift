from __future__ import annotations

from shared.domain.graph_codec import extract_graph_spec


def _find_node_id_by_label(spec, label: str) -> str:
    wanted = str(label or "").strip().casefold()
    for node_id, node in dict(spec.nodes or {}).items():
        if str(getattr(node, "label", "") or "").strip().casefold() == wanted:
            return str(node_id or "")
    return ""


def test_graph_codec_parses_line_continuation_json_and_repairs_tree_markers():
    body = "\n".join(
        [
            "{\\",
            '  "type": "mindmap",\\',
            '  "title": "Transformer",\\',
            '  "nodes": [\\',
            "    {\\",
            '      "id": "transformer",\\',
            '      "label": "Transformer",\\',
            '      "children": [\\',
            '        {"id":"n1","label":"├── Abstract"},\\',
            '        {"id":"n2","label":"│   └── Motivation"},\\',
            '        {"id":"n3","label":"├── 1 Introduction"},\\',
            '        {"id":"n4","label":"│   └── Recurrent neural networks"}\\',
            "      ]\\",
            "    }\\",
            "  ]\\",
            "}\\",
        ]
    )
    markdown = f"```mindmap\n{body}\n```"

    spec = extract_graph_spec(markdown)
    assert spec is not None
    assert str(spec.kind or "").casefold() == "mindmap"

    root_id = _find_node_id_by_label(spec, "Transformer")
    assert root_id
    root = spec.nodes[root_id]

    abstract_id = _find_node_id_by_label(spec, "Abstract")
    intro_id = _find_node_id_by_label(spec, "1 Introduction")
    motivation_id = _find_node_id_by_label(spec, "Motivation")
    rnn_id = _find_node_id_by_label(spec, "Recurrent neural networks")

    assert abstract_id in list(root.children or [])
    assert intro_id in list(root.children or [])
    assert motivation_id in list(spec.nodes[abstract_id].children or [])
    assert rnn_id in list(spec.nodes[intro_id].children or [])

    # Ensure tree marker glyphs were not kept as literal labels.
    assert all("├──" not in str(node.label or "") for node in spec.nodes.values())
    assert all("│" not in str(node.label or "") for node in spec.nodes.values())

