# Demo Graph

```graph
{
  "type": "graph",
  "title": "RAG System",
  "nodes": [
    {
      "id": "query",
      "label": "User Query",
      "description": "Nutzerfrage als Startpunkt",
      "children": ["retrieval", "ranking"]
    },
    {
      "id": "retrieval",
      "label": "Retrieval",
      "description": "Dokumente werden gesucht"
    },
    {
      "id": "ranking",
      "label": "Reranking",
      "description": "Treffer werden sortiert"
    },
    {
      "id": "answer",
      "label": "Antwort",
      "description": "Finale Antwort",
      "href": "https://example.com/docs"
    }
  ],
  "edges": [
    {"from": "retrieval", "to": "answer", "label": "Kontext"},
    {"from": "ranking", "to": "answer", "label": "Top Treffer"}
  ],
  "collapsed": ["query"]
}
```
