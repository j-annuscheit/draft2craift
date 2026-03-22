# Workflows

Diese Ordner enthalten deklarative Agenten-Workflow-Konfigurationen.

- `definitions/`: Ablaufdefinitionen (Steps, Edges, Loops, Budgets)
- `profiles/`: Policy- und Wiring-Profile (z. B. `regex-only`)

Aktuelle Kern-Workflows:

- `factcheck_agentic`
- `chat_agentic`
- `canvas_agentic`
- `mindmap_agentic`
- `graph_agentic` (connected graph closure loop)

Hinweis:

- Diese Dateien sind die Konfigurationsbasis der aktuellen Agentic-Engine.
- Sie bleiben bewusst datengetrieben, damit neue Workflows und Step-Verdrahtungen
  ohne Kerncode-Aenderung hinzugefuegt werden koennen.
- Es wird nur `*.toml` unterstuetzt. Das spart optionale Parser-Abhaengigkeiten
  und haelt die Ladepfade klein und eindeutig.
