# draft2craift — Architecture Reference

> **Dieses Dokument ist normativ.**
> Wenn Code und Regelwerk widersprechen, gilt das Regelwerk — nicht der Code.
> Abweichungen sind Defekte, keine Stilfragen. Ausnahmen erfordern das Verfahren aus §22.

---

## 1. Was die Anwendung ist

**draft2craift** ist ein local-first AI Writing Studio — eine PySide6-Desktop-Applikation.
Sie läuft vollständig offline (keine Cloud-Aufrufe außer optionalen Modell-Downloads von
Hugging Face Hub über HTTPS). Kern-Features:

- Multi-Tab Markdown-Editor mit Live-Vorschau
- RAG (Retrieval-Augmented Generation) über importierte Dokumente
- Streaming-LLM-Chat mit Kontextauswahl
- Glossar- und Mindmap-Generierung
- Text-to-Speech / Speech-to-Text
- Atomares Projekt-Save/Load mit Crash-Recovery-Autosave

Entry point: `draft2craift` CLI → `studio.main:main` → `studio.app:run` → `studio.window.MainWindow`.

---

## 1.1 Änderungsstand (2026-03-15)

Diese Punkte sind seit v7 **verbindlich umgesetzt** und ab jetzt Teil des Regelwerks:

1. **Kein Legacy-/Kompatibilitäts-Fallback im Projekt-Load/Save-Pfad**
   - `ProjectLoader` lädt strikt gegen das aktuelle Format.
   - Alte/abweichende Formate werden nicht mehr still toleriert.
2. **User-Mode-Verantwortung in `UserModeController` zentralisiert**
   - Moduswechsel + Dialog-Propagation laufen über `studio/controllers/user_mode_controller.py`.
3. **Setup-Extraktionen umgesetzt**
   - Global Shortcuts: `studio/setup/shortcuts_setup.py`
   - Global Signals: `studio/setup/signals_setup.py`
4. **Menubar über explizite Inputs statt Gott-Objekt**
   - `build_menubar(MenuBuildInputs(...))` statt implizitem Zugriff auf `MainWindow`-Interna.
5. **QSettings konsolidiert**
   - Genau eine Runtime-Instanz in `services_setup.py`; Bootstrap-Instanz in `studio/app.py` bleibt die einzige erlaubte zweite Instanz.

**Architekturentscheidung:** Es gibt **keine Rückwärtskompatibilitätspflicht** zu alten Projektformaten.
Fehlerhafte/alte Strukturen sind Ladefehler, keine Anlassfälle für neue Fallback-Branches.

---

## 2. Schichtenmodell (verbindlich)

```
studio/  →  shared/services/  →  shared/domain/
         ↘                    ↗
           shared/config/
```

Das Repository ist in genau zwei Source-Trees aufgeteilt:

```
canvas2/
├── shared/      # Layer 1 — Qt-agnostische Business-Logik
└── studio/      # Layer 2 — Qt UI-Anwendung
```

### Layer 1 — `shared/`

**Regel:** `shared/` darf niemals aus `studio/` importieren.

`shared/` enthält Domain-Modelle und Services ohne jede Kenntnis der UI. Es ist isoliert importierbar (z.B. für Unit-Tests, Eval-Skripte oder einen künftigen Headless-Modus).

**Erlaubte Qt-Nutzung in `shared/`:** Qt wird an Worker-/Service-Grenzen verwendet, wo Signal/Slot-Threading erforderlich ist:
- `shared/services/rag/*` (`RAGSystem`, `RAGWorker`)
- `shared/services/llm/*` (`LLMManager`, `LLMWorker`)
- `shared/services/speech/*` (TTS/STT-Worker und Manager)
- `shared/services/project/project_loader.py` (`QByteArray` für persistierten UI-State-Restore)

`shared/` muss UI-Widgets (`QWidget`, `QDialog`, `QMainWindow`, `QLayout`) vollständig vermeiden.

### Layer 2 — `studio/`

`studio/` importiert frei aus `shared/`. Es besitzt alle Qt-Widgets, Docks, Controller, Dialoge und die Setup-Pipeline. Es darf nicht in `shared/`-Modul-*Interna* greifen (z.B. private `_`-Attribute); nur die öffentliche API nutzen.

### Abhängigkeitsrichtung

`shared/domain/` und `shared/config/` importieren nie aus `shared/services/`.
`shared/services/`-Sub-Packages importieren nicht voneinander, außer wenn eines ein deklarierter
Dependency ist (z.B. nutzt `rag/` `llm/manager.py` für Query-Expansion).

---

## 3. Verzeichnisstruktur

```
canvas2/
├── shared/
│   ├── config/                  # QSettings-Key-Konstanten (keine Logik)
│   │   └── setting_keys.py      # Alle persistenten Setting-Keys, gruppiert nach Domäne
│   ├── domain/                  # Reine Daten — frozen dataclasses, Enum, TypedDict
│   │   ├── document.py          # DocumentRef, DocumentContent
│   │   ├── export.py            # ExportRequest
│   │   ├── feedback.py          # FeedbackEntry
│   │   ├── graph.py             # GraphNode, GraphEdge
│   │   ├── graph_codec.py       # JSON-Serialisierung für Graphen
│   │   ├── graph_spec.py        # Tree-Graph mit Collapse-State
│   │   ├── highlight.py         # HighlightSpan, HighlightEntry
│   │   ├── prompt.py            # PromptTemplate
│   │   ├── rag.py               # RagChunk, RagQuery, RagResult
│   │   ├── testcase.py          # TestCase (Eval-Harness)
│   │   └── user_mode.py         # Config-getriebene Profile, Sichtbarkeits- und Label-Auflösung
│   └── services/
│       ├── feedback/            # Feedback-Persistenz
│       ├── highlights/          # Highlight-Store (projekt-/autosave-gebunden)
│       ├── importer/            # PDF/DOCX → Markdown-Konvertierung
│       ├── llm/                 # LLM-Inferenz (Manager, Worker, Backend-Adapter, Prompt-Tasks)
│       ├── project/             # Projekt-Save/Load, Pfadsicherheit, Schema
│       ├── rag/                 # Indexierung, Suche, Chunking, Config
│       └── speech/              # TTS (Piper) und STT (Whisper)
│
├── studio/
│   ├── app.py                   # QApplication-Bootstrap, Theme-Bootstrap
│   ├── main.py                  # CLI-Entry-Point (< 30 Zeilen)
│   ├── window.py                # MainWindow — Dependency-Injector, ≤ 300 Zeilen (§10)
│   ├── app_context.py           # AppContext-Mediator (§8)
│   ├── logger.py                # AppLogger + LogDock
│   ├── menubar.py               # Menü-Konstruktion — empfängt ctx, nicht window (§10)
│   ├── theme.py                 # Theme-Hilfsfunktionen
│   ├── user_mode_bindings.py    # Deklarative Helfer für profil-getriebenes Widget-Wiring
│   ├── profile_text_overrides.py # Literal-Text/Tooltip-Overrides für Widget-Bäume
│   ├── setup/                   # Bootstrap-Pipeline (keine Business-Logik)
│   │   ├── services_setup.py    # Erzeugt Services + AppContext
│   │   ├── docks_setup.py       # Erzeugt Dock-Widgets, initiales Signal-Wiring
│   │   └── controllers_setup.py # Erzeugt alle Controller, bindet an AppContext
│   ├── controllers/             # Eine Datei pro Controller (§9)
│   ├── canvas/                  # CanvasTabWidget (Editor + Vorschau)
│   ├── chat/                    # ChatDock + Fact-Check-Pipeline
│   ├── knowledge/               # KnowledgeDock (Viewer + RAG-Panel)
│   ├── dialogs/                 # Modale Dialoge (Prompt-Editor, etc.)
│   ├── feedback/                # Feedback-UI-Komponenten
│   ├── glossary/                # Glossar-Editor-Dialog
│   └── importer/                # Datei-Import-Dialog + Worker
│
├── tests/                       # pytest-Tests (spiegelt Source-Tree-Layout)
├── eval/                        # Offline-Evaluation-Skripte
├── data/                        # Laufzeit-editierbare Defaults (welcome/about, user_modes/*.toml)
├── docs/                        # Menschenlesbare Dokumentation
└── pyproject.toml               # Build-Config, Abhängigkeiten, Entry-Points
```

---

## 4. Invarianten (MUSS — ohne Ausnahme im Normalfall)

1. **`shared/` importiert niemals `studio/`.**
2. **`shared/domain/` enthält keine I/O-, UI- oder Service-Logik.**
3. **Kein Controller kennt einen anderen Controller direkt** — Koordination via `ctx.*` oder Signals.
4. **Keine `_private`-Zugriffe über Modulgrenzen** (kein `other_object._attr`).
5. **Projekt-I/O nur über `ProjectPaths`** — kein `Path(user_string)` ohne `.resolve()` + `_is_relative_to()`-Check.
6. **Keine persistenten Pfade über `Path.cwd()`** — `QStandardPaths` (in `studio/`) oder `platformdirs` (in `shared/`). `allowed_root` in `ProjectPaths` ist immer explizit — kein `Path.cwd()`-Fallback.
7. **UI-Updates nur im Main Thread** — keine direkten Widget-Aufrufe aus Background-Threads.
8. **Worker kommunizieren mit UI ausschließlich via Signals/Slots.**
9. **`QThread.wait(timeout_ms)` Rückgabewert wird geprüft** — bei `False`: `terminate()`, dann `wait()`, dann loggen.
10. **Settings-Keys nur in `shared/config/setting_keys.py`** — keine String-Literale anderswo.
11. **`AppContext.validate()` läuft nach vollständigem Setup** — einmal, nach `_init_controllers()`.
12. **Highlights sind projekt-/autosave-gebunden** — nicht global pro Arbeitsverzeichnis.
13. **`window.py` ist ein Dependency-Injector, kein Mediator** — Methoden-Body-Regel: §10.
14. **Jedes modale und modeless Dialog implementiert `set_user_mode(mode: str) -> None`.**
15. **Projekt-Persistenz ist strikt und formatgebunden** — keine stillen Legacy-/Kompatibilitäts-Fallbacks.

---

## 5. Anti-Drift-Gates

Jede Änderung muss diese 5 Gates bestehen. Verletzung eines Gates → Change wird nicht gemerged.

### Gate 1 — Schicht-Gate
Keine neuen verbotenen Importkanten. `shared/` importiert nicht aus `studio/`. `shared/domain/` importiert nicht aus `shared/services/`.

### Gate 2 — API-Gate
Keine neuen privaten Cross-Modul-Zugriffe (`._*` auf fremde Klassen/Objekte). Keine neuen `set_*_handler`- oder `set_*_getter`-Methoden in Docks oder Widgets.

### Gate 3 — Persistenz-Gate
Kein neuer unsicherer Pfadzugriff. Projektdateien nur innerhalb des Projekt-Roots. Kein `Path.cwd()` für persistente Pfade.
Keine neuen Legacy-/Kompatibilitäts-Fallbacks im Save/Load-Pfad.

### Gate 4 — Threading-Gate
Keine UI-Operation aus Worker-Threads. Shutdown-Pfade prüfen `wait()` mit Timeout robust. LLM-synchrone Methoden nicht im Main Thread aufgerufen.

### Gate 5 — Test-Gate
Für betroffene Schicht existiert mindestens ein Test, der das Verhalten absichert. Neue Controller haben mindestens einen Test in `tests/studio/`.

---

## 6. `shared/services/rag/` — RAG-Pipeline

### Komponenten

| Datei | Klasse | Rolle |
|-------|-------|------|
| `orchestrator.py` | `RAGSystem(QObject)` | Öffentliche Fassade; Thread-sicher via `RLock` |
| `worker.py` | `RAGWorker(QThread)` | Queue-basierte Background-Ausführung |
| `config.py` | `RAGConfig` | Verschachtelte Dataclass-Struktur |
| `indexer.py` | `RAGIndexer` | Besitzt Index-State (lexical: TF-IDF/BM25 + ST-Embeddings) |
| `searcher.py` | `RAGSearcher` | Vollständige Such-Pipeline (Expansion → Retrieval → Fusion → Rerank) |
| `chunking.py` | — | Drei Strategien: `sliding_window`, `section`, `recursive` |
| `expanders.py` | — | HyDE Query-Expansion (TF-IDF-Modus, ST-Modus) |
| `tfidf.py` | — | Lexical Ranking (`TFIDFIndex`, `BM25Index`) |
| `search_fusion.py` | — | Reciprocal Rank Fusion (RRF, k=60 nach Cormack 2009) |

### `RAGConfig`-Struktur

```
RAGConfig
├── backend:   BackendConfig   — use_tfidf, lexical_mode(tfidf|bm25), bm25_k1, bm25_b, use_st, st_model_name, use_regex_search
├── chunking:  ChunkingConfig  — strategy, chunk_size, overlap, include_filename
├── hyde:      HyDEConfig      — use_hyde, min_words, tfidf_mode, st_mode, st_hypotheses
├── context:   ContextConfig   — enabled, before_chars, after_chars
├── selection: SelectionConfig — mode, top_k, score_threshold
├── literal:   LiteralConfig   — max_results, use_llm_terms
└── rerank:    RerankConfig    — enabled, min_score, max_candidates
```

### RAG-Override-Vertrag (strict)

- `RAGConfig.with_overrides(..., strict=True)` akzeptiert ausschließlich:
  - section-Objekte (`{"backend": {...}, "selection": {...}}`)
  - oder dotted keys (`"backend.lexical_mode"`, `"selection.top_k"`).
- Flache Legacy-Keys wie `"chunk_size"`, `"top_k"`, `"use_tfidf"` sind **invalid** und erzeugen `KeyError`.
- Eval-Suites und Sweep-Grids unter `eval/examples/rag_*.json` folgen genau diesem Vertrag.

### Internes Key-Format

Chunk-Keys in `RAGIndexer` sind `"{doc_name}\x00{chunk_index}"`.
`_SEP = "\x00"` — Dokumentnamen können `:`, `/` und `|` enthalten, aber niemals ein NUL-Byte.

### `RAGSystem`-Signals

| Signal | Payload | Wann |
|--------|---------|------|
| `results_ready` | `list` | Suche abgeschlossen |
| `backend_changed` | `str` | Aktives Backend gewechselt |
| `rag_settings_requested` | — | Einstellungs-Dialog-Trigger |

### `RAGWorker`-Signals

| Signal | Payload | Wann |
|--------|---------|------|
| `search_complete` | `(str, list, dict)` | query, results, debug_info |
| `index_complete` | `int` | Anzahl indexierter Dokumente |
| `st_loaded` | `bool` | Sentence-Transformers-Modell bereit |
| `status_changed` | `str` | Status-Bar-Update |

---

## 7. `shared/services/llm/` — LLM-Pipeline

### `LLMManager(QObject)`-Signals

| Signal | Payload | Wann |
|--------|---------|------|
| `token_received` | `str` | Streaming-Token |
| `generation_complete` | `str` | Vollständige Ausgabe |
| `error_occurred` | `str` | Fehlermeldung |
| `model_loaded` | `(bool, str)` | Erfolg + Backend/Modell-Status |
| `nli_model_loaded` | `(bool, str)` | NLI-Modell-Status |
| `is_generating` | `bool` | Generierungs-State-Toggle |

`LLMWorker(QThread)` besitzt die aktive `BaseLLMBackend`-Instanz (`shared/services/llm/backends/`).

### Backend-Abstraktion

- `BaseLLMBackend` definiert den stabilen Runtime-Contract (`load_model`, `generate_once`, `generate_stream`, `count_tokens`, `context_window`, `prepare_prompt`).
- Built-in Backends: `LlamaCppBackend` (`.gguf/.bin`), `TransformersBackend` (HF-IDs/URLs).
- `factory.py` löst die Backend-Wahl aus dem User-Setting auf (`auto|llama_cpp|transformers`).
- Task-Module rufen ausschließlich backend-agnostische Methoden auf — kein direkter Zugriff auf native Modell-Objekte.
- Prompt-Formatierung und Tokenisierung sind Backend-owned.

### Neues Backend hinzufügen

1. `BaseLLMBackend` in einem neuen Modul unter `shared/services/llm/backends/` implementieren.
2. In `factory.py` registrieren.
3. Keine Änderung an Chat-/Controller-Business-Logik — nur Backend-Wiring/Factory.
4. Service-Tests für Load + Generate + Stop des neuen Backends schreiben.

---

## 8. AppContext — Der Mediator

**Datei:** `studio/app_context.py`

### Zweck

`AppContext` ist ein **Mediator**: er gibt Controllern eine stabile, benannte API für cross-cutting Operations, ohne dass sie sich gegenseitig kennen.

### Was in AppContext gehört

- Weiterleitungs-Aufrufe, die Controller-Grenzen kreuzen.
- Runtime-State ohne einzelnen Besitzer: `user_mode`, `file_registry`, `status_feedback_payload`.
- `validate()` — Post-Setup-Binding-Check.

### Was NICHT in AppContext gehört

- Business-Logik — gehört in die einzelnen Controller.
- Neue Delegations-Methoden, die trivial eine einzelne Controller-Methode wrappen.
- **Direkter Dock-Zugriff** — Docks sind UI-Layer; über den besitzenden Controller routen.
- Neue `bind_*`-Methoden für Docks oder Widgets (die einzige UI-Bind-Ausnahme: `bind_glossary_feedback_bar`).

### Bindings (gesetzt während Setup, geprüft von `validate()`)

```python
ctx.bind_theme_controller(ThemeController)
ctx.bind_autosave_controller(AutosaveController)
ctx.bind_knowledge_controller(KnowledgeController)
ctx.bind_chat_controller(ChatController)
ctx.bind_glossary_feedback_bar(FeedbackBar)
```

`validate()` wirft `RuntimeError` bei fehlenden Bindings. Läuft wenn `__debug__` True (Standard-CPython) oder `APP_DEBUG=1`.

### Services direkt gehalten

`ctx.rag_system`, `ctx.llm_manager`, `ctx.project_manager`, `ctx.app_settings`, `ctx.app_logger`, `ctx.file_registry`, `ctx.user_mode`.

Das sind direkte Attribute, keine Delegations-Methoden. Controller greifen als `ctx.rag_system` zu, nicht über Delegations-Methoden.

---

## 9. Controller-Pattern

**Verzeichnis:** `studio/controllers/`

Jeder Controller besitzt genau ein Thema. Controller rufen sich nicht gegenseitig direkt auf — sie nutzen `ctx.*`-Methoden oder Qt-Signals.

### Controller und ihre Verantwortlichkeiten

| Controller | Datei | Besitzt |
|------------|------|------|
| `ThemeController` | `theme_ctrl.py` | App-Theme, Vorschau-Theme, Seitenränder |
| `AutosaveController` | `autosave.py` | Periodisches Save, Crash-Recovery, Workspace-Cleanup |
| `KnowledgeController` | `knowledge_controller.py` | `file_registry`, Import, Umbenennen, Entfernen, RAG-Reindex |
| `ChatController` | `chat_controller.py` | LLM-Kontext-Bau, Context-Bar-Refresh, TTS-Modus |
| `ProjectController` | `project_controller.py` | File-Picker-Dialoge, delegiert an `project_manager` |
| `SpeechController` | `speech_ctrl.py` | TTS-Playback, Whisper-Diktierung, Speech-Einstellungen |
| `ZoomController` | `zoom_ctrl.py` | Editor-Zoom, View-Modus (markdown/preview/both) |
| `CanvasController` | `canvas_controller.py` | Export, Fokus-Erkennung für Canvas/Dock-Auswahl |
| `FindReplaceController` | `find_replace_ctrl.py` | Nicht-modales Find/Replace über alle Panels |
| `LLMSideTaskController` | `llm_tasks.py` | Glossar, Mindmap/Graph/Chunk-Map-Tasks |
| `FeedbackController` | `feedback_ctrl.py` | Feedback-UI, Freeform-Dialog, Statistiken |
| `UserModeController` | `user_mode_controller.py` | Kanonischer User-Mode-State, Moduswechsel, Dialog-Propagation, Feature-Visibility/Label-Anwendung |

**Geplante Controller (noch nicht implementiert — Zielzustand):**

| Controller | Aufgabe |
|------------|--------|
| `DialogController` | Dialog-Lebenszyklen (Factory, Show, Track offener Dialoge) |

### Controller-Regeln

1. Ein Controller wird **einmalig** in der Setup-Pipeline erzeugt und für die App-Lifetime gehalten.
2. Konstruktoren nehmen explizite Abhängigkeiten (kein Global-State, keine Singletons außer `AppContext`).
3. Ein Controller **darf keine Referenz auf einen anderen Controller** halten — `ctx.*` oder Signals nutzen.
4. Ein Controller **darf keine privaten Methoden** (`_`) von Docks oder Widgets aufrufen.
5. Rückgabetypen müssen auf allen öffentlichen Methoden annotiert sein.
6. **Controller mit Background-Threads implementieren `shutdown(self, timeout_ms: int = ...) -> bool`** — wird sequenziell aus `closeEvent` aufgerufen.

### KnowledgeController-Ports (Protokolle)

`KnowledgeController` interagiert mit Docks über typisierte Protokolle in `knowledge_ports.py`:

```
KnowledgeDockPort — suspend/resume Reindex, Dateien hinzufügen, Dokumente öffnen/umbenennen/entfernen
ChatDockPort      — Dokumente im Kontext-Panel hinzufügen/umbenennen/entfernen
RAGWorkerPort     — isRunning(), enqueue_load_st(), st_loaded Signal
```

Diese Protokolle sind `@runtime_checkable`. In Tests: `MagicMock(spec=KnowledgeDockPort)`.

---

## 10. `window.py` — Dependency-Injector-Regel (verbindlich)

**Datei:** `studio/window.py` — **Zielgröße: ≤ 300 Zeilen**

### Die Kernregel

> `window.py` ist ein **Dependency-Injector**. Es erzeugt Abhängigkeiten und verdrahtet sie.
> Es implementiert keine Business-Logik selbst.

**Konkretes Kriterium:** Jede Methode in `window.py` darf entweder:
- (a) ein **Setup-Schritt** sein — ruft genau ein Setup-Modul auf (`_init_*`-Methoden), oder
- (b) eine **einzeilige Delegation** sein — ruft genau eine Controller-/ctx-Methode auf, oder
- (c) `closeEvent` sein — kontrollierte Ausnahme (§23).

**Verboten in `window.py`:**
- Inline-Dialog-Factories mit Signal-Wiring (→ `DialogController`)
- `if hasattr(self, "_widget"): self._widget.setXxx(...)` in Nicht-Setup-Methoden (→ `UserModeController`)
- `resolve_feature_label(...)` Aufrufe in Methoden-Bodies (→ Dialog-Klasse oder Controller)
- Business-Logik-Bodies (z.B. Autosave-Toggle-Logik → `AutosaveController`)

### menubar.py-Regel

`build_menubar(...)` empfängt einen **expliziten Input-Port** (`MenuBuildInputs`) mit exakt benannten Abhängigkeiten.
Kein Menücode darf direkt auf beliebige `MainWindow`-Interna zugreifen.

```python
# Korrekt:
build_menubar(
    MenuBuildInputs(
        host=self,  # nur Qt-Parent + menuBar()-Host
        canvas=...,
        knowledge_dock=...,
        chat_dock=...,
        log_dock=...,
        action_handlers={...},
        ...
    )
)

# Verboten:
build_menubar(self)   # MainWindow als Gott-Objekt
```

### Erlaubte Struktur von `__init__`

```python
def __init__(self):
    super().__init__()
    self._init_services()
    self._init_early_controllers()
    self._init_window()
    self._init_central()
    self._init_statusbar()
    self._init_docks()
    self._init_controllers()
    self._context.validate()
    build_menubar(MenuBuildInputs(...))
    self._init_global_shortcuts()
    self._connect_global_signals()
    self.set_user_mode(self._user_mode, notify=False)
    self._autosave_ctrl.maybe_restore_from_tmp(self)
    self._autosave_ctrl.start_runtime()
```

### `closeEvent`-Pattern

`closeEvent` koordiniert Shutdown sequenziell. Jeder Controller mit Background-Threads implementiert `shutdown() -> bool`:

```python
def closeEvent(self, event):
    if not self._confirm_save_on_close():
        return event.ignore()
    if not self._llm_ctrl.shutdown(timeout_ms=3000):
        return event.ignore()
    if not self._rag_ctrl.shutdown(timeout_ms=5000):
        return event.ignore()
    self._autosave_ctrl.flush_before_close()
    self._speech_ctrl.stop_all()
    self._dialog_manager.close_all()
    event.accept()
```

---

## 11. Profil-System (User Modes)

### Überblick

User-Profile sind runtime-konfiguriert via `data/user_modes/*.toml` — nicht hard-coded in Python.
`shared/domain/user_mode.py` ist die einzige Resolver-API, die UI-Code verwendet.

### TOML-Datei-Konvention

- Eine `.toml`-Datei pro Profil: Dateiname ist die kanonische Profil-ID (`plus.toml` → `plus`).
- Das Feld `id` im TOML muss mit dem Dateinamen übereinstimmen.
- Genau eine Datei setzt `default_profile = true`.
- Struktur-Konsistenz wird von `validate_user_mode_config()` in Tests/CI erzwungen.

### Profil-Datei-Struktur

```toml
version = 1
id = "plus"
label = "Plus"
order = 1
default_profile = true

[visibility]
"feature.key" = true        # steuert setVisible()

[labels]
"button.run" = "Starten"    # steuert setText() via resolve_feature_label()
"button.run.tooltip" = "…"  # steuert setToolTip()

[literal_labels]
"Model Load" = "Modell laden"   # direkte Quelltext-Ersetzung

[literal_tooltips]
"Fact Check" = "Fakten prüfen"
```

### API-Nutzungsregeln

```python
# Sichtbarkeit — für alle Menüs, Buttons, Dialoge, erweiterte Felder:
is_feature_visible(mode, "feature.key", default=True)

# Feature-Labels — für profil-spezifische Button/Label-Texte:
resolve_feature_label(mode, "feature.key", default="Standard")

# Literal-Overrides — für hard-codierte Strings, die überschrieben werden sollen:
apply_profile_text_overrides(widget, mode)   # traversiert Widget-Baum einmalig

# Deklarative Bindungen (bevorzugt gegenüber imperativem setText/setVisible):
apply_widget_texts(mode, bindings)
apply_widget_visibility(mode, bindings)
apply_form_row_labels(mode, form, bindings)
apply_combo_item_labels(mode, combo, bindings)
```

### Verboten

- `mode_rank()` für neue Feature-Gates — **deprecated**, verwende `is_feature_visible()` mit expliziten Keys.
- Inline-`resolve_feature_label()`-Aufrufe in `window.py`- oder Controller-Bodies — diese gehören in Dialog-Klassen oder Binding-Tabellen.
- Globaler `_CATALOG`-State ohne Test-Teardown — in `conftest.py` via Fixture absichern.

### `set_user_mode`-Konvention

- **Jedes** modeless Dialog implementiert `set_user_mode(mode: str) -> None`.
- Neue modale Dialoge mit profil-sensitivem Content ebenfalls.
- `UserModeController` (§9) ist die zentrale Stelle für Normalisierung, Propagation und Feature-Bindings.
- `MainWindow.set_user_mode(...)` bleibt eine **einzige Delegation** auf `UserModeController.apply_mode_to_window(...)`.
- Kein direktes `hasattr`-Scanning oder Widget-Tree-Manipulation in `window.py`-Methoden außerhalb von `_init_*`/`closeEvent`.

### Key-Namensräume (stabile Konvention)

```
canvas.toolbar.*         canvas.preview.button.*    knowledge.tab.*
rag.results.*            prompt_editor.*             importer.dialog.*
importer.pdf.*           glossary.editor.*           feedback.*
menu.ai.*                menu.view.*                 window.status.*
mindmap.generate.*
```

---

## 12. Setup-Sequenz

`MainWindow.__init__` läuft genau diese Schritte in dieser Reihenfolge. Die Reihenfolge ist load-bearing.

```
Step 1  _init_services()           — RAGSystem, LLMManager, ProjectManager, AppContext
Step 2  _init_early_controllers()  — ThemeController (benötigt von Step 3), FeedbackController
Step 3  _init_window()             — Window-Geometrie, Chrome-Theme (braucht ThemeCtrl)
Step 4  _init_central()            — CanvasTabWidget (Central Widget)
Step 5  _init_statusbar()          — QStatusBar, FeedbackBar, Status-Labels
                                     → bindet FeedbackBar an ctx
Step 6  _init_docks()              — KnowledgeDock, ChatDock, LogDock
Step 7  _init_controllers()        — alle verbleibenden Controller inkl.
                                     LLMSideTaskController (braucht FeedbackBar aus Step 5)
                                     und FindReplaceController
Step 8  ctx.validate()             — assertiert alle Bindings vorhanden (Debug-Modus)
Step 9  build_menubar(MenuBuildInputs) — füllt Menü über explizite Ports
Step 10 _init_global_shortcuts()   — delegiert an `setup/shortcuts_setup.py`
Step 11 _connect_global_signals()  — delegiert an `setup/signals_setup.py`, inkl. 1s Context-Timer
Step 12 set_user_mode(..., notify=False) — delegiert an `UserModeController`
Step 13 autosave_ctrl.maybe_restore_from_tmp() — Crash-Recovery
Step 14 autosave_ctrl.start_runtime()          — aktiviert periodisches Save
Step 15 Startup-Info loggen
```

**Warum Step 5 vor Step 6:** `LLMSideTaskController` (erzeugt in Step 7) braucht `FeedbackBar`. `FeedbackBar` wird in Step 5 erzeugt und an `ctx` gebunden. Reihenfolge: FeedbackBar → Docks → LLMSideTaskController. Neue Controller, die ein UI-Widget vor Dock-Erzeugung brauchen: Widget in seinem Erzeugungsschritt an `ctx` binden.

---

## 13. Signal/Slot-Regeln

**Regel:** Signals gegenüber Callbacks bevorzugen.

```python
# Korrekt — Sender emittiert Signal:
class ChatDock(QDockWidget):
    glossary_requested = Signal(str)

# Empfänger verbindet:
chat_dock.glossary_requested.connect(llm_tasks_ctrl.request_glossary)
```

```python
# Verboten — Callback-Injection:
chat_dock.set_glossary_request_handler(window._generate_glossary)
```

Keine `set_*_handler`- oder `set_*_getter`-Methoden zu Docks oder Widgets hinzufügen.
Wiring läuft über Signals/Slots oder klar typisierte Controller-Ports.

**Thread-Sicherheit:** Signals, die Thread-Grenzen kreuzen (Worker → Main Thread), sind sicher, weil Qt sie automatisch queued. Niemals `QWidget` direkt aus einem Background-Thread aktualisieren.

---

## 14. Threading-Modell

```
Main Thread (Qt Event Loop)
│
├── LLMWorker (QThread)        — besitzt aktive BaseLLMBackend; streamt Tokens via Signals
│
├── RAGWorker (QThread)        — Queue-basiert; Indexierung + Suche + ST-Modell-Load
│   └── RAGSystem (RLock)      — alle RAGSystem-Methoden sind thread-sicher
│
├── TTS Worker (QThread)       — Piper Audio-Synthese
│
└── Dictation Worker (QThread) — Whisper-Inferenz + Audio-Capture
```

**Regeln:**

1. Niemals eine `QWidget`-Methode aus einem Background-Thread aufrufen.
2. Background-Threads kommunizieren mit Main Thread ausschließlich via Signals.
3. `RAGSystem`-Methoden sind von jedem Thread aufrufbar (`threading.RLock`), aber lange blockierende Aufrufe gehen über `RAGWorker` für UI-Responsivität.
4. `LLMManager`-synchrone Methoden (`expand_query_tfidf_sync` etc.) blockieren den aufrufenden Thread — nur aus Worker-Threads aufrufen.
5. `QThread.wait(timeout_ms)` Rückgabewert **muss** geprüft werden. Bei `False`: `terminate()`, dann `wait()`, dann loggen.
6. Jeder Controller mit Background-Threads implementiert `shutdown(timeout_ms: int) -> bool`.

---

## 15. Projekt-Persistenz

### Ordner-Layout (auf Disk)

```
<project_folder>/
├── canvas/
│   ├── doc_0000.md          # Canvas-Tab 0 Inhalt
│   └── ...
├── knowledge/
│   └── ...                  # Importierte Dokumente
├── rag/
│   ├── index.pkl            # Lexical-Index (TF-IDF/BM25) + Metadaten
│   └── embeddings.pt        # ST-Embeddings (optional)
├── chat/
│   ├── history.json
│   └── chunk_claim_cache.json
├── logs/
│   └── entries.json
├── highlights.json
└── project.json             # Manifest (`version`, Dateiliste, Metadaten)
```

### Archiv-Format (`.d2c`)

- Export erzeugt Standard-ZIP-Archiv mit `.d2c`-Extension.
- Import validiert ZIP-Integrität und erforderliche Projektstruktur, extrahiert dann in managed Workspace.
- ZIP-Pfad-Traversal wird bei Validierung/Extraktion geblockt (keine absoluten Pfade, kein `..`).
- `ProjectLoader` erwartet aktuelle Manifest-Felder — keine deprecated Aliase.

### Strikter Ladevertrag (kein Legacy-Fallback)

- **Keine Altformat-Kompatibilität:** alte Projektstände sind nicht supported.
- `project.json` muss dem aktuellen Schema entsprechen (`version == 2`, inkl. `rag_config`, `canvas`, `knowledge`, `settings`, `llm`, `ui`).
- `chat/history.json` muss im Session-Objektformat vorliegen (`{"current_tab": ..., "tabs": [...]}`), nicht als alte Message-Liste.
- `knowledge.files[*]` lädt Inhalt ausschließlich aus `knowledge_file`; kein Inline-`markdown`-Fallback.
- Canvas lädt ausschließlich in `project.json` referenzierte Dateien; keine automatische Orphan-Recovery (`doc_*.md`) beim Load.
- Traversal-/Schema-/Pfadfehler sind harte Ladefehler (`ProjectSchemaError`/`ValueError`), keine stillen Defaults.

### Pflicht- vs. optionale Artefakte beim Load

- **Pflicht:** `project.json`, `chat/history.json`, `logs/entries.json`
- **Optional:** `rag/index.pkl`, `rag/embeddings.pt`, `chat/chunk_claim_cache.json`

### Pfad-Sicherheit

Alle Pfade innerhalb eines Projekts werden via `ProjectPaths._resolve_child()` validiert:
- `Path.resolve(strict=False)` verhindert Symlink-Traversal.
- `_is_relative_to(candidate, allowed_root)` lehnt Escapes wie `../../etc` ab.
- Kein user-supplied String wird ohne `ProjectPaths`-Verarbeitung an `Path` übergeben.
- `allowed_root` ist immer explizit — kein stiller `Path.cwd()`-Fallback.

---

## 16. QSettings-Key-Registry

Alle persistenten Setting-Keys leben in `shared/config/setting_keys.py` als `Final[str]`-Klassenattribute. **Niemals** einen QSettings-Key als String-Literal anderswo schreiben.

| Klasse | Domäne | Beispiel-Key |
|-------|--------|-------------|
| `AutosaveSettingsKeys` | Autosave | `autosave/enabled` |
| `ThemeSettingsKeys` | UI/Vorschau | `ui/theme`, `preview/markdown_theme` |
| `FeedbackSettingsKeys` | Feedback | `feedback/ui_enabled` |
| `SpeechSettingsKeys` | TTS/STT | `tts_engine`, `stt_model_size` |
| `PromptTemplateKeys` | LLM-Prompts | 39 Keys, inkl. `ALL`-Tuple |
| `RAGSettingsKeys` | RAG-Pipeline | `rag/chunking_strategy`, `rag/top_k` |

QSettings Organisation/Applikation: `"draft2craift"` / `"draft2craift"`.
**Eine** `QSettings`-Instanz wird in `services_setup.py` erzeugt und über `AppContext` weitergegeben. Die Bootstrap-Instanz in `studio/app.py` für Theme-Init vor `MainWindow` ist die einzige erlaubte zweite Instanz.

---

## 17. Domain-Modelle (`shared/domain/`)

Domain-Modelle sind reines Python — kein Qt, kein I/O. Sie nutzen `@dataclass(frozen=True)` oder einfaches `@dataclass`. Keine Methoden außer `__post_init__`-Validierung.

Serialisierungs-Logik gehört nicht in Domain-Klassen — sie gehört in `shared/services/project/project_saver.py` und `project_loader.py`.

**Typisierte Schnittstellen:** Strukturen, die Schichtgrenzen kreuzen (z.B. LLM-Kontext-Dict, RAG-Ergebnisse), sollen als `TypedDict` in `shared/domain/` definiert werden — keine ungetypten `dict`- oder `tuple`-Strukturen an Schnittstellen.

---

## 18. Test-Konventionen

Tests spiegeln die Source-Tree-Struktur:

```
tests/
├── domain/         # Tests für shared/domain/*
├── services/       # Tests für shared/services/*
└── studio/         # Tests für studio/controllers/* und studio/setup/*
```

### Key-Fixtures (`conftest.py`)

| Fixture | Scope | Was sie bietet |
|---------|-------|-----------------|
| `_qt_offscreen` | session (autouse) | Setzt `QT_QPA_PLATFORM=offscreen` vor Qt-Init |
| `qt_app` | session | Einzelne `QApplication`-Instanz, von allen Tests wiederverwendet |
| `rag_config` | function | `RAGConfig` mit beiden Backends deaktiviert (schnell, kein Modell) |
| `rag_entries` | function | Liste von `RAGEntry`-Objekten zum Seeden |
| `rag_system` | function | Leere `RAGSystem`-Instanz |
| `indexed_rag_system` | function | `RAGSystem` vorgeseeded mit `rag_entries` |

### Regeln

- **Mirror-Struktur:** jedes `studio/foo.py` hat Tests in `tests/studio/test_foo.py`.
- **Autospec-Mocks bevorzugen:** `create_autospec(SomeClass, instance=True, spec_set=True)`.
- **Keine neuen Hand-Crafted-Stubs** (`_FooStub`) — Legacy-Stubs opportunistisch migrieren.
- **Offscreen-Qt:** alle `tests/studio/`-Tests verlassen sich auf `_qt_offscreen`-Autouse-Fixture.
- **Kein Netz/Modell-I/O:** Tests dürfen keine Modelle herunterladen oder externe APIs aufrufen.
- **Globaler State:** Tests, die `reload_user_mode_config()` oder anderen globalen State mutieren, brauchen ein `autouse`-Teardown in `conftest.py`.
- **Run:** `pytest tests/` vom Repo-Root. Keine speziellen Flags erforderlich.

**Coverage-Ziel:** 75% (noch nicht in CI erzwungen, aber das Ziel).

---

## 19. Statische Daten (`data/`)

```
data/
├── about.md          # "About"-Seite in der Vorschau
├── shortcuts.md      # Keyboard-Shortcuts-Referenz
├── welcome.md        # Erstes-Start-Willkommen
├── prompts/
│   └── defaults.json # Default-LLM-Prompt-Templates
└── user_modes/       # Profil-TOMLs (je eine Datei pro Profil)
```

**Regeln:**
- Dateien sind zur Laufzeit read-only via `_read_data_file(name)` in `window.py`.
- `prompts/defaults.json` ist der Fallback; User-Edits werden in `QStandardPaths.AppDataLocation` gespeichert, nie zurück in `data/`.
- Keine Binär-Assets, Bilder oder Modell-Gewichte in `data/` — nur Plain-Text und JSON.

---

## 20. Eval-Skripte (`eval/`)

**Regeln:**
- `eval/` wird **nicht** in das Produktions-Wheel gebaut — in `pyproject.toml` ausschließen.
- Shared Utilities leben in `eval/shared/` — keine Duplikate über Skripte.
- Keine Qt-Imports in `eval/` — reine CLI-Tools.
- Keine `sys.path.insert(0, ...)`-Hacks — `pip install -e .` nutzen.
- Metriken aus `eval/shared/metrics.py` sind die kanonischen Implementierungen.

---

## 21. Definition of Done (Architektur)

Ein Change ist architektonisch fertig, wenn:

1. Schichtgrenzen eingehalten sind,
2. Verantwortlichkeit eindeutig zugeordnet ist,
3. keine neue versteckte Kopplung entstanden ist,
4. Persistenz- und Threading-Regeln erfüllt sind,
5. `window.py`-Methoden-Body-Regel (§10) eingehalten ist,
6. Tests und Dokumentation die Entscheidung abbilden.

---

## 22. Ausnahmen (nur kontrolliert)

Eine Ausnahme ist nur zulässig mit:

1. Begründung (warum nötig),
2. Risikoanalyse,
3. Ablaufdatum (bis wann zurückgebaut),
4. Verantwortliche Person,
5. Test, der die Ausnahme sichtbar macht.

Ohne diese 5 Punkte gilt die Änderung als Architekturverstoß.

---

## 23. Bekannte intentionale Ausnahmen

| Muster | Ort | Begründung |
|--------|-----|-----------|
| `QObject`/`QThread` in `shared/` | `rag/orchestrator.py`, `rag/worker.py`, `llm/manager.py`, `llm/worker.py`, Speech-Worker | Signal/Slot-Threading erfordert Qt-Basisklassen |
| `QByteArray` in `shared/services/project` | `project_loader.py` | Stellt persistierte Window-State-Bytes beim Projekt-Load wieder her |
| `_apply_runtime_settings()` privater Aufruf | `studio/setup/signals_setup.py` | Übergangs-Call in Setup-Schritt; bis öffentliche Runtime-API auf `SpeechController` vorhanden ist |
| `getattr(..., None)` defensiver Zugriff | `AppContext.autosave_*`-Methoden | Guard gegen teilweise initialisierten State beim Startup |
| Bootstrap-`QSettings` in `studio/app.py` | `app.py:40` | Theme-Anwendung vor `MainWindow`-Konstruktion — einzige erlaubte zweite Instanz |

---

## 24. Kurz-Checkliste für Reviews

### Schicht-Regeln
- [ ] `shared/` enthält keinen Import aus `studio/`
- [ ] `shared/` enthält kein `QWidget`, `QDialog`, `QMainWindow`, `QLayout`
- [ ] `shared/domain/` enthält keinen Import aus `shared/services/`
- [ ] `shared/config/` enthält keinen Import aus `shared/services/`

### `window.py`-Regeln
- [ ] Jede neue `window.py`-Methode ist eine `_init_*`-Setup-Methode, `closeEvent`, oder einzeilige Delegation
- [ ] `window.py` wächst nicht (Zeilen-Count vor und nach dem Change vergleichen)
- [ ] Kein `resolve_feature_label()`-Aufruf in `window.py`-Methoden-Bodies
- [ ] Keine neue Inline-Dialog-Factory in `window.py`
- [ ] `set_user_mode(...)` bleibt eine einzige Delegation auf `UserModeController`

### AppContext-Regeln
- [ ] `AppContext` hält Referenzen nur auf Services und Controller — nicht auf Dock-Widgets (Ausnahme: `_glossary_feedback_bar`)
- [ ] Keine neuen `bind_*dock*`- oder `bind_*widget*`-Methoden in `AppContext`
- [ ] Keine neue triviale Delegations-Methode in `AppContext`
- [ ] `AppContext.validate()` wird genau einmal aufgerufen, nach `_init_controllers()`

### Controller-Regeln
- [ ] Kein Controller hält Referenz auf einen anderen Controller
- [ ] Kein Controller ruft `_private`-Methode eines Docks oder Widgets auf
- [ ] Jeder neue Controller ist in `controllers_setup.py` erzeugt und in `ControllerBundle`
- [ ] Jede Controller-Methode hat eine Rückgabetyp-Annotation
- [ ] Controller mit Background-Threads hat `shutdown(timeout_ms) -> bool`

### Profil-/User-Mode-Regeln
- [ ] Kein neuer `mode_rank()`-Aufruf — `is_feature_visible()` nutzen
- [ ] Neues Dialog implementiert `set_user_mode(mode: str) -> None`
- [ ] TOML-Schlüssel-Namensräume-Konvention eingehalten (§11)
- [ ] Tests, die `reload_user_mode_config()` aufrufen, haben Teardown-Fixture

### Signal/Slot-Regeln
- [ ] Keine neuen `set_*_handler`- oder `set_*_getter`-Injektionen in Docks/Widgets
- [ ] Kein Widget-Update aus einem Non-Main-Thread

### Threading-Regeln
- [ ] `QThread.wait(timeout_ms)` Rückgabewert immer geprüft
- [ ] LLM-synchrone Methoden nicht im Main Thread aufgerufen

### Settings-Regeln
- [ ] Kein QSettings-Key als String-Literal außerhalb `setting_keys.py`
- [ ] Keine zusätzlichen `QSettings`-Instanzen in Runtime-Code

### Pfad-Regeln
- [ ] Kein `Path.cwd()` für persistente Pfade
- [ ] Kein `Path(user_string)` ohne `.resolve()` + `_is_relative_to()`-Check
- [ ] `allowed_root` in `ProjectPaths` ist immer explizit
- [ ] Keine Legacy-/Fallback-Branches im Projekt-Load/Save (altformate werden nicht still toleriert)

### Test-Regeln
- [ ] Neue Tests bevorzugen `create_autospec(spec_set=True)` — keine neuen Hand-Crafted-Stubs
- [ ] Neuer Controller hat mindestens einen Test in `tests/studio/`
- [ ] Kein Netz-/Modell-I/O in Tests
