# Demo Graph Without Inferred Edges

```graph
{
  "type": "graph",
  "title": "Explizite Relationen",
  "nodes": [
    {
      "id": "q",
      "label": "Quelle",
      "children": ["a", "b"]
    },
    {
      "id": "a",
      "label": "Detail A"
    },
    {
      "id": "b",
      "label": "Detail B"
    },
    {
      "id": "r",
      "label": "Ergebnis"
    }
  ],
  "edges": [
    {
      "from": "q",
      "to": "r",
      "label": "belegt"
    }
  ]
}
```
