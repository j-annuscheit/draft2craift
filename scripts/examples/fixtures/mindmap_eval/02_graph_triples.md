# Demo Graph Triples

```graph
{
  "type": "graph",
  "title": "Wissensgraph KI",
  "nodes": [
    {"id": "llm", "label": "Large Language Model"},
    {"id": "transformer", "label": "Transformer"},
    {"id": "attention", "label": "Aufmerksamkeitsmechanismus"},
    {"id": "application", "label": "Anwendung"}
  ],
  "triples": [
    {"subject": "transformer", "predicate": "nutzt", "object": "attention"},
    {"subject": "llm", "predicate": "basiert_auf", "object": "transformer"},
    {"subject": "llm", "predicate": "ermoeglicht", "object": "application"}
  ]
}
```
