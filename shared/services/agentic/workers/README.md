# Agentic Workers

Dieses Verzeichnis enthaelt die produktiven Step-Worker des Agentic-Runtimes.

## Ziel der Struktur

- genau ein registrierbarer Worker pro Datei
- kleine, klar umrissene Verantwortlichkeiten
- direkte Dokumentation im Code jeder Worker-Datei
- keine versteckte Verdrahtung ueber grosse `runners_*.py`-Sammeldateien

## Namensschema

- `control/`: generische Kontroll-Worker
- `factcheck/`: Factcheck-spezifische Worker
- `chat/`: Chat-spezifische Worker
- `canvas/`: Canvas-/Rewrite-Worker
- `maps/`: Mindmap-/Graph-Worker
  - `source/`: Quellaufbereitung
  - `seed/`: deterministischer Startbaum
  - `frontier/`: inkrementeller Ausbau
  - `validate/`: Validierung
  - `apply/`: Candidate/Commit/Finalisierung
  - `render/`: finale Ausgabe

## Was in jeder Worker-Datei dokumentiert wird

Jede Worker-Datei beschreibt mindestens:

- Worker-ID
- Zweck
- erwartete Eingaben
- Output / State-Schreibverhalten
- Tool-Nutzung
- Fehlverhalten / Fallbacks

## Maps-Besonderheit

Der produktive Mindmap-v3-Workflow arbeitet nicht mehr mit einem grossen
Draft-Worker, sondern mit einer kleinen, einheitlichen Kette:

1. Quelle vorbereiten
2. Seed-Baum deterministisch erzeugen
3. einen Frontier-Knoten waehlen
4. lokale Evidenz sammeln
5. wenige Kinder vorschlagen lassen
6. Kandidaten validieren
7. Candidate committen oder verwerfen
8. final bereinigen und emitten

Die neuen registrierten Worker-IDs fuer den Mindmap-v3-Pfad nutzen das praefix
`map.*.v1`, zum Beispiel:

- `map.resolve_request.v1`
- `map.seed_from_outline.v1`
- `map.select_frontier_node.v1`
- `map.propose_child_nodes.v1`
- `map.validate_candidate_tree.v1`
- `map.emit_result.v1`

## Interne Support-Module

- Die neue gemeinsame Map-Logik liegt unter `shared/services/agentic/lib/maps/`.
- Registriert werden ausschliesslich die Worker-Dateien selbst.
- Optimierungen sollen zuerst im passenden Worker oder in `lib/maps/` landen.
- `maps/_support.py` existiert derzeit noch fuer den aelteren Graph-/Legacy-Pfad,
  ist aber nicht mehr die Zielstruktur fuer neue Mindmap-Arbeit.
