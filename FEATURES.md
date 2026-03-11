# draft2craift Workflow für PT-Arbeit

Lokale Arbeitsumgebung für Projektideen, Studienmaterial, Konzepte und belastbare Entscheidungen.

Dieses Dokument beschreibt den praktischen Ablauf für PT-Arbeit:
- Projektideen lesen und strukturieren
- Inhalte bewerten und priorisieren
- Aufgaben, Notizen und Entwürfe managen
- Aussagen prüfen und Ergebnisse freigeben

Jeder Abschnitt hat zwei Ebenen:
- Praxisnutzen: Was bringt es im Alltag.
- Technische Umsetzung: Wie es im System läuft und welche Hebel relevant sind.

## Zielbild

draft2craift ist kein reiner Chat-Client.
Es ist ein lokaler Arbeitsprozess aus Import, Strukturierung, Analyse, Schreiben, Verifikation und Projektpersistenz.

Im Zentrum steht PT-Arbeit:
1. Idee oder Unterlagen aufnehmen
2. Relevantes Wissen herausziehen
3. Ergebnisse bewerten und absichern
4. Entscheidungen dokumentieren und exportieren

## Workflow 0) Unterstützung konfigurieren

## 0.1) LLM

### Praxisnutzen
- Du stellst Arbeitsstil und Leistung passend zur Aufgabe ein: schnell, streng, kreativ oder fokussiert.
- Das Modell arbeitet im selben Projektkontext wie Notizen, Quellen und Drafts.

### Technische Umsetzung
- GGUF-Modelle laufen lokal über `llama-cpp-python`.
- Modellparameter und Prompt-Konfiguration werden im Projekt gespeichert.
- Promptaufbau ist klar getrennt in Systemprompt, Kontextquellen, Historie und User-Input.
- Selection-Rewrite erlaubt gezielte Bearbeitung einzelner Textpassagen.

### Wichtige Einstellhebel
- Laden: `n_ctx`, `n_gpu_layers`, `n_threads`
- Generierung: `max_tokens`, `temperature`, `top_p`, `repeat_penalty`
- Kontextsteuerung: Draft, RAG, Dokumentauswahl

## 0.2) NLI

### Praxisnutzen
- Aussagen werden nicht nur sprachlich, sondern logisch gegen Quellen geprüft.
- Kritische Aussagen können mit Entailment-Logik abgesichert werden.

### Technische Umsetzung
- NLI-Modell wird getrennt vom LLM geladen (Transformers-Backend).
- Fact-Checks können NLI-only, LLM-only oder hybrid laufen.
- Ergebnisse werden als `entailment`, `neutral`, `contradiction` mit Score ausgewertet.

### Wichtige Einstellhebel
- NLI-Modell-ID
- Threads für Laden/Inference
- Methodenmischung pro Fact-Check-Lauf

## Workflow 1) Projektquellen aufnehmen und in Markdown überführen

## 1.1) Smarte PDF-Umwandlung

### Praxisnutzen
- Aus schwer bearbeitbaren PDFs werden editierbare Arbeitsdokumente.
- Auch große Dateimengen bleiben kontrollierbar.

### Technische Umsetzung
- PDF-Konvertierung nutzt `pymupdf4llm`.
- Vorschau vor Batch-Import reduziert Fehlimporte.
- Bei großen PDF-Batches wird isolierte Verarbeitung genutzt, um Stabilität hochzuhalten.

### Wichtige Einstellhebel
- Seitenbereiche (`all`, `1-5,8,10-`)
- Seitenmarker (`[Seite N]`)
- Bildextraktion, DPI, Grafikgrenzen

## 1.2) Tabellenrobustheit

### Praxisnutzen
- Tabellen bleiben als auswertbare Struktur erhalten.

### Technische Umsetzung
- Strategien: `lines_strict`, `lines`, `text`, `none`
- Tabellenbereiche werden in der Import-Pipeline nachbearbeitet.

### Wichtige Einstellhebel
- Table Strategy
- Paragraph-Reflow in Kombination mit Tabellen

## 1.3) Abschnitts- und Heading-Erkennung

### Praxisnutzen
- Bessere Struktur bedeutet bessere Suche, bessere Zusammenfassungen, bessere Mindmaps.

### Technische Umsetzung
- Heading-Modi: `pymupdf4llm`, `custom`, `none`
- Optionaler Font-Analyze-Worker für Ratio-Vorschläge

### Wichtige Einstellhebel
- `heading_mode`
- H1/H2/H3-Ratios
- `heading_max_chars`
- Bold/Color-Promotion

## 1.4) Kopf- und Fußzeilen entfernen

### Praxisnutzen
- Wiederholender Seitenmüll verschwindet aus späteren Such- und Analyseergebnissen.

### Technische Umsetzung
- Auto-Detect für wiederkehrende Bereiche
- Alternative manuelle Top/Bottom-Zonen

### Wichtige Einstellhebel
- `auto_hf_detect`
- `hf_min_pages`, `hf_threshold`, `hf_max_pairs`
- `hf_top_zone`, `hf_bottom_zone`

## 1.5) Optional: LLM-Optimizer nach dem Import

### Praxisnutzen
- Eingelesene Inhalte werden lesbarer und konsistenter, ohne den Kerninhalt zu verlieren.

### Technische Umsetzung
- Chunk-basierte Optimierung in separatem Worker
- Guardrails für Struktur und Marker
- Laufstatistik über geänderte/abgelehnte Chunks

## Workflow 2) Projektideen lesen und strukturieren

## 2.1) Highlights mit Kommentaren und Sprungzielen

### Praxisnutzen
- Relevante Stellen werden direkt im Text verankert.
- Kommentare und Verlinkungen machen aus Lesen ein strukturiertes Review.

### Technische Umsetzung
- Persistenter HighlightStore mit Anchor-Matching (`exact/prefix/suffix`)
- Kontextmenü: Kommentar, Jump-To, Farbe, Löschen
- Anchor-Sync bei Textänderungen

### Wichtige Einstellhebel
- Scope pro Panel (`draft`, `viewer`, `rag`, `chat`, `importer`)
- Tab-gebunden oder tab-übergreifend

## 2.2) In-Dokument-Glossar

### Praxisnutzen
- Begriffe, Definitionen und Abkürzungen bleiben im Lesefluss verfügbar.

### Technische Umsetzung
- Glossar-Einträge liegen im selben HighlightStore (Typ `glossary`)
- Overlay global ein-/ausschaltbar
- Manuelle oder LLM-gestützte Glossarerstellung

## 2.3) Zusammenfassen und Rückfragen

### Praxisnutzen
- Du gehst ohne Bruch von Quelle zu Bewertung und Entscheidungsvorlage.

### Technische Umsetzung
- Kontextquellen sind explizit wählbar
- Grounding-Logik kann unbegründete Antworten bewusst unterbinden
- Zusammenfassung und Q&A laufen über denselben Chat-Flow

## 2.4) Mindmaps und Graphen

### Praxisnutzen
- Mindmaps und Graphen machen komplexe Projektideen auf einen Blick verständlich, indem sie Zusammenhänge, Abhängigkeiten und Risiken visuell und schnell erfassbar darstellen.

### Technische Umsetzung
- Modi: `mindmap`, `graph`, `chunkmap`
- Promptregeln + Parser mit Fallback
- ChunkMap basiert auf echter Chunking-Struktur

## 2.5) Multi-Tab-Notizen

### Praxisnutzen
- Mehrere Denkspuren parallel: Analyse, Beschlussvorlage, offene Fragen.

### Technische Umsetzung
- Markdown-first Tabs mit synchroner Preview
- Umbenennbare Tabs für klare Arbeitsstrukturen

## 2.6) Export für Review, Freigabe und Dokumentation

### Praxisnutzen
- Export ist nicht nur "Datei speichern", sondern ein gestaltbarer Ausgabeprozess.
- Es erlaubt gezielte Textgestaltung, zum Beispiel 2-spaltig, sowie die mögliche Übernahme eines Glossars.

### Technische Umsetzung
- Export pro aktivem Panel nach PDF oder DOCX
- Einheitlicher Exportdialog mit Optionen für:
  - Ausgabeformat (`PDF`, `Word`)
  - Typografie (`Schriftart`, `Schriftgröße`, `Zeilenabstand`)
  - Layout (`2-Spalten-Export`)
  - Wissenselemente (`Highlights übernehmen`, `Kommentare übernehmen`)

### Was im Export intern passiert
- Markdown wird blockbasiert geparst (Heading, Listen, Abschnitte).
- Highlight-Matches werden über `panel_scope` und `tab_name` gegen den HighlightStore aufgelöst.
- PDF:
  - HTML-basierte Ausgabe über `QTextDocument` + `QPrinter`
  - optionale Highlight-Farben und Kommentarverweise
  - optionales 2-Spalten-Layout
- DOCX:
  - Ausgabe über `python-docx`
  - Typografie und Zeilenabstand werden auf Stil- und Run-Ebene gesetzt
  - optionales 2-Spalten-Layout in der Section
  - Highlights werden auf Word-Highlightfarben abgebildet
  - Kommentare werden als echte Kommentarobjekte (falls verfügbar) oder Fallback-Text ausgegeben

### Ergebnis
- Der Export ist jetzt ein vollwertiger Teil des PT-Workflows und kein nachgelagerter Minimal-Schritt.

## Workflow 3) Projektideen bewerten, schreiben und entscheiden

## 3.1) Zielgerichtete Textarbeit an selektierten Passagen

### Praxisnutzen
- Keine globale Neuformulierung, sondern präzise Eingriffe an relevanten Stellen.

### Technische Umsetzung
- Selection-Rewrite mit expliziter Zielmarkierung
- Rückschreiben nur in den markierten Bereich

## 3.2) RAG-gestützte Verdichtung

### Praxisnutzen
- Lange Dokumente werden auf die wirklich relevanten Segmente reduziert.

### Technische Umsetzung
- Chunking: `sliding_window`, `section`, `recursive`
- Backends: TF-IDF, optional ST, Literal
- Fusion über RRF, danach Auswahl und optionales LLM-Reranking

### Wichtige Einstellhebel
- Backend-Wahl und ST-Modell
- Chunk-Size/Overlap/Strategie
- Selection-Mode, Threshold, Rerank
- HyDE und Term-Expansion

## 3.3) Faktcheck-Pipeline für belastbare Aussagen

### Praxisnutzen
- Entscheidungsdokumente werden auf Evidenz statt Eindruck aufgebaut.

### Technische Umsetzung
- Pipeline: Claim-Extraktion -> Quellenabgleich -> Methodenlauf -> Ergebnisreport
- Methoden: `nli`, `llm_chunk`, `llm_global`, `llm_claim_nli`
- Ergebnis als strukturierte Markdown-Tabelle

## 3.4) Diktat und TTS bei Bedarf

### Praxisnutzen
- Schnellere Erfassung und akustische Gegenprüfung von Entwürfen.

### Technische Umsetzung
- STT mit Whisper-Worker
- TTS mit Piper-Präferenz und lokalen Fallbacks

## Workflow 4) Projektmanagement, Qualität und Lernschleife

## 4.1) Feedback in der Arbeit erfassen

### Praxisnutzen
- Probleme und Stärken werden direkt am Prozesspunkt dokumentiert.

### Technische Umsetzung
- Feedback-Bar in Kernflows (Chat, Import, Glossar, Mindmap, Fact-Check)
- Strukturierte Felder für Sentiment, Tags, Notizen, Use-Case

## 4.2) Feedback in Testfälle überführen

### Praxisnutzen
- Aus Einzelbeobachtungen werden reproduzierbare Qualitätschecks.

### Technische Umsetzung
- Feedbackdaten können in Testfälle transformiert werden
- Eval-Stack für wiederholbare Runs ist vorhanden

## 4.3) Iterationen messbar machen

### Praxisnutzen
- Modellwahl, Promptwahl und RAG-Parameter werden datenbasiert entschieden.

### Technische Umsetzung
- Eval-Skripte für RAG, PDF, Glossar, Mindmap, Fact-Check und Modellvergleich
- Vergleichbarkeit über Runs, Logs und Projektzustand

## Workflow 5) Immer aktiv im Hintergrund

## 5.1) Autosave und Projektfortsetzung

### Praxisnutzen
- Arbeit wird fortgesetzt, nicht rekonstruiert.

### Technische Umsetzung
- Autosave nutzt den gleichen Projektmechanismus wie manuelles Speichern
- Restore-Flow beim Neustart
- Projektzustand umfasst u. a. Canvas, Knowledge, RAG, Chat, Highlights, Einstellungen

## 5.2) Individualisierbares UI

### Praxisnutzen
- Das Tool passt sich dem Team- und Arbeitsstil an.

### Technische Umsetzung
- Dock-Layout, Sichtbarkeit, Modusprofile
- Theme-, Preview- und Zoom-Einstellungen

## Unterschied zu einem normalen lokalen Chatbot

1. Prozessfokus statt Promptfokus: komplette PT-Arbeit in einem System.
2. Dokumentstruktur ist zentral, nicht nur Dateianhang.
3. Verifikation ist eingebaut (Fact-Check + NLI), kein externer Zusatz.
4. Persistente Projekte statt nur Chat-Historie.
5. Feedback -> Testfall -> Eval als echte Lernschleife.

## Kurzpositionierung

draft2craift ist eine lokale Arbeitsplattform für PT-Arbeit:
Konfigurieren -> Importieren -> Strukturieren -> Bewerten -> Schreiben -> Prüfen -> Exportieren -> Iterieren.
