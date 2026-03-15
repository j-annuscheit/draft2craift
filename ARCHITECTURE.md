# draft2craift — Architecture Reference

> This document is the authoritative description of the repository structure,
> layer rules, and design patterns. Any new code must conform to the rules
> stated here. Any deviation is a defect, not a style preference.

---

## 1. What the Application Is

**draft2craift** is a local-first AI writing studio — a PySide6 desktop application.
It runs fully offline (no cloud calls except optional model downloads from
Hugging Face Hub over HTTPS). Core capabilities:

- Multi-tab Markdown editor with live preview
- RAG (Retrieval-Augmented Generation) over imported documents
- Streaming LLM chat with context selection
- Glossary and mind-map generation
- Text-to-speech / speech-to-text
- Atomic project save/load with crash-recovery autosave

Entry point: `draft2craift` CLI → `studio.main:main` → `studio.app:run` →
`studio.window.MainWindow`.

---

## 2. Two-Layer Architecture

The repository is split into exactly two source trees:

```
canvas2/
├── shared/      # Layer 1 — Qt-agnostic business logic
└── studio/      # Layer 2 — Qt UI application
```

### Layer 1 — `shared/`

**Rule:** `shared/` must not import from `studio/`.

`shared/` contains domain models and services that have no knowledge of the
UI. It is importable in isolation (e.g. for unit tests, eval scripts, or a
future headless server mode).

**Allowed Qt usage in `shared/`:** Qt is used in worker/service boundaries where
signal/slot threading is required:
- `shared/services/rag/*` (`RAGSystem`, `RAGWorker`)
- `shared/services/llm/*` (`LLMManager`, `LLMWorker`)
- `shared/services/speech/*` (TTS/STT workers and managers)
- `shared/services/project/project_loader.py` (`QByteArray` for persisted UI state restore)

`shared/` must still avoid UI widgets (`QWidget`, `QDialog`, `QMainWindow`).

### Layer 2 — `studio/`

`studio/` imports freely from `shared/`. It owns all Qt widgets, docks,
controllers, dialogs, and the setup pipeline. It must not reach into
`shared/` module *internals* (e.g. private `_` attributes); use the public
API only.

### Dependency Direction

```
studio/  →  shared/services/  →  shared/domain/
         ↘                    ↗
           shared/config/
```

`shared/domain/` and `shared/config/` never import from `shared/services/`.
`shared/services/` sub-packages do not import from each other unless one is
a declared dependency (e.g. `rag/` uses `llm/manager.py` for query expansion).

---

## 3. Directory Structure

```
canvas2/
├── shared/
│   ├── config/                  # Runtime config models, path helpers, QSettings key registry
│   │   ├── app_settings.py      # Typed settings models (SpeechSettings, AppSettings)
│   │   ├── paths.py             # Platform-aware app data path helpers
│   │   └── setting_keys.py      # All persistent setting keys, grouped by domain
│   ├── domain/                  # Pure data — frozen dataclasses, Enum, TypedDict
│   │   ├── document.py          # DocumentRef, DocumentContent
│   │   ├── export.py            # ExportRequest
│   │   ├── feedback.py          # FeedbackEntry
│   │   ├── graph.py             # GraphNode, GraphEdge
│   │   ├── graph_codec.py       # JSON serialisation for graphs
│   │   ├── graph_spec.py        # Tree graph with collapse state
│   │   ├── highlight.py         # HighlightSpan, HighlightEntry
│   │   ├── prompt.py            # PromptTemplate
│   │   ├── rag.py               # RagChunk, RagQuery, RagResult
│   │   ├── testcase.py          # TestCase (eval harness)
│   │   └── user_mode.py         # Config-driven profiles, visibility + label resolution
│   └── services/
│       ├── feedback/            # Feedback persistence
│       ├── highlights/          # Highlight store (project/autosave scoped)
│       ├── importer/            # PDF / DOCX → Markdown conversion
│       ├── llm/                 # LLM inference (manager, worker, backend adapters, prompt tasks)
│       ├── project/             # Project save / load / path security
│       ├── rag/                 # Indexing, search, chunking, config
│       └── speech/              # TTS (Piper) and STT (Whisper)
│
├── studio/
│   ├── app.py                   # QApplication bootstrap, theme bootstrap
│   ├── main.py                  # CLI entry point (27 lines)
│   ├── window.py                # MainWindow — orchestration hub
│   ├── app_context.py           # AppContext mediator (see §6)
│   ├── logger.py                # AppLogger + LogDock
│   ├── menubar.py               # Menu construction (called once from window.__init__)
│   ├── theme.py                 # Theme helpers
│   ├── user_mode_bindings.py    # Declarative helpers for profile-driven widget wiring
│   ├── setup/                   # Bootstrap pipeline (no business logic)
│   │   ├── services_setup.py    # Creates services + AppContext
│   │   ├── docks_setup.py       # Creates dock widgets, initial signal wiring
│   │   └── controllers_setup.py # Creates all controllers, binds to AppContext
│   ├── controllers/             # One file per controller (see §7)
│   ├── canvas/                  # CanvasTabWidget (editor + preview)
│   ├── chat/                    # ChatDock + fact-check pipeline
│   ├── knowledge/               # KnowledgeDock (viewer + RAG panel)
│   ├── dialogs/                 # Modal dialogs (prompt editor, etc.)
│   ├── feedback/                # Feedback UI components
│   ├── glossary/                # Glossary editor dialog
│   └── importer/                # File import dialog + workers
│
├── tests/                       # pytest tests (mirrors source tree layout)
├── eval/                        # Offline evaluation scripts (currently packaged too)
├── data/                        # Runtime-editable defaults (welcome/about texts, user_modes/*.toml)
├── docs/                        # Human-readable documentation
└── pyproject.toml               # Build config, dependencies, entry points
```

---

## 4. `shared/services/rag/` — RAG Pipeline

### Components

| File | Class | Role |
|------|-------|------|
| `orchestrator.py` | `RAGSystem(QObject)` | Public facade; thread-safe via `RLock` |
| `worker.py` | `RAGWorker(QThread)` | Queue-based background execution |
| `config.py` | `RAGConfig` | Nested dataclass tree |
| `indexer.py` | `RAGIndexer` | Owns index state (TF-IDF + ST embeddings) |
| `searcher.py` | `RAGSearcher` | Full search pipeline (expansion → retrieval → fusion → rerank) |
| `chunking.py` | — | Three strategies: `sliding_window`, `section`, `recursive` |
| `expanders.py` | — | HyDE query expansion (TF-IDF mode, ST mode) |
| `tfidf.py` | — | TF-IDF ranking |
| `search_fusion.py` | — | Reciprocal Rank Fusion (RRF, k=60 per Cormack 2009) |

### `RAGConfig` Structure

```
RAGConfig
├── backend:   BackendConfig   — use_tfidf, use_st, st_model_name, use_regex_search
├── chunking:  ChunkingConfig  — strategy, chunk_size, overlap, include_filename
├── hyde:      HyDEConfig      — use_hyde, min_words, tfidf_mode, st_mode, st_hypotheses
├── context:   ContextConfig   — enabled, before_chars, after_chars
├── selection: SelectionConfig — mode, top_k, score_threshold
├── literal:   LiteralConfig   — max_results, use_llm_terms
└── rerank:    RerankConfig    — enabled, min_score
```

### Internal Key Format

Chunk keys inside `RAGIndexer` are `"{doc_name}\x00{chunk_index}"`.
`_SEP = "\x00"` is used because document names may contain `:`, `/`, and `|`
but never a NUL byte.

### `RAGSystem` Signals

| Signal | Payload | When |
|--------|---------|------|
| `results_ready` | `list` | Search completed |
| `backend_changed` | `str` | Active backend toggled |
| `rag_settings_requested` | — | Settings dialog trigger |

### `RAGWorker` Signals

| Signal | Payload | When |
|--------|---------|------|
| `search_complete` | `(str, list, dict)` | query, results, debug_info |
| `index_complete` | `int` | count of indexed documents |
| `st_loaded` | `bool` | sentence-transformers model ready |
| `status_changed` | `str` | status bar update |

---

## 5. `shared/services/llm/` — LLM Pipeline

### `LLMManager(QObject)` Signals

| Signal | Payload | When |
|--------|---------|------|
| `token_received` | `str` | streaming token |
| `generation_complete` | `str` | full output |
| `error_occurred` | `str` | error message |
| `model_loaded` | `(bool, str)` | success + backend/model status |
| `nli_model_loaded` | `(bool, str)` | NLI model status |
| `is_generating` | `bool` | generation state toggle |

`LLMWorker(QThread)` owns the active `BaseLLMBackend` instance
(`shared/services/llm/backends/`). Token streaming goes via `token_received`
signal to the main thread.

### Backend Abstraction

LLM inference is backend-modular:
- `BaseLLMBackend` defines the stable runtime contract (`load_model`,
  `generate_once`, `generate_stream`, `count_tokens`, `context_window`,
  `prepare_prompt`).
- Built-in backends:
  - `LlamaCppBackend` for local `.gguf/.bin` models.
  - `TransformersBackend` for Hugging Face `transformers` model ids/URLs.
- `factory.py` resolves backend choice from user setting (`auto|llama_cpp|transformers`)
  and model reference.
- `LLMManager` and task modules must call backend-agnostic helper methods;
  no task may access backend-native model objects directly.
- Prompt formatting and tokenization must be backend-owned. Runtime code passes
  prompt text to the backend; each backend decides whether/how to transform it
  (for example chat-template rendering in `transformers`) before token counting
  or generation.
- No new compatibility shims for deprecated internals (for example
  `LLMWorker._model` or manager-level `_nli_*` proxy fields). Tests must target
  public APIs or the active backend object directly.

### Adding a New Backend

To add another provider (e.g. vLLM, ONNX Runtime, REST API wrapper):
1. Implement `BaseLLMBackend` in a new module under `shared/services/llm/backends/`.
2. Register it in `factory.py` (choice normalization + creation).
3. Do **not** change chat/controller business logic; only backend wiring/factory.
4. Add service tests that cover load + generate + stop behavior for the new backend.

---

## 6. AppContext — The Mediator

**File:** `studio/app_context.py`

### Purpose

`AppContext` is a **Mediator**: it gives controllers a stable, named API for
cross-cutting operations without them knowing about each other directly.

### What Belongs in AppContext

- Forwarding calls that cross controller boundaries (e.g. autosave ↔
  knowledge, knowledge ↔ chat, any controller ↔ project/settings).
- Runtime state with no single owner: `user_mode`, `file_registry`,
  `status_feedback_payload`.
- `validate()` — post-setup binding check.

### What Does NOT Belong in AppContext

- Business logic — keep that in the individual controllers.
- New delegation methods that simply wrap a single controller method.
  Add those directly to the calling controller.
- **Direct dock access.** Docks are UI layer. Route through the controller
  that owns the dock.
- New `bind_*` methods for docks or widgets (the only UI bind is
  `bind_glossary_feedback_bar`, which exists because `LLMSideTaskController`
  needs the widget before it is a controller).

### Bindings (set during setup, checked by `validate()`)

```python
ctx.bind_theme_controller(ThemeController)       # _init_early_controllers
ctx.bind_autosave_controller(AutosaveController) # controllers_setup
ctx.bind_knowledge_controller(KnowledgeController)
ctx.bind_chat_controller(ChatController)
ctx.bind_glossary_feedback_bar(FeedbackBar)      # _init_statusbar
```

`validate()` raises `RuntimeError` listing missing bindings. It runs whenever
`__debug__` is True (default CPython) or `APP_DEBUG=1` is set.

### Services Held Directly

`ctx.rag_system`, `ctx.llm_manager`, `ctx.project_manager`,
`ctx.app_settings`, `ctx.app_logger`, `ctx.file_registry`, `ctx.user_mode`.

These are direct attributes, not wrapped. Controllers access them as
`ctx.rag_system`, not through delegation methods.

---

## 7. Controller Pattern

**Directory:** `studio/controllers/`

Each controller owns exactly one concern. Controllers do not call each other
directly — they call `ctx.*` methods (AppContext), or communicate via Qt
signals.

### Controllers and Their Responsibilities

| Controller | File | Owns |
|------------|------|------|
| `ThemeController` | `theme_ctrl.py` | App theme, preview theme, page margins |
| `AutosaveController` | `autosave.py` | Periodic save, crash recovery, workspace cleanup |
| `KnowledgeController` | `knowledge_controller.py` | `file_registry`, import, rename, remove, RAG reindex |
| `ChatController` | `chat_controller.py` | LLM context building, context bar refresh, TTS mode |
| `ProjectController` | `project_controller.py` | File-picker dialogs, delegates to `project_manager` |
| `SpeechController` | `speech_ctrl.py` | TTS playback, Whisper dictation, speech settings |
| `ZoomController` | `zoom_ctrl.py` | Editor zoom, view mode (markdown/preview/both) |
| `CanvasController` | `canvas_controller.py` | Export, focus detection for canvas/dock selection |
| `FindReplaceController` | `find_replace_ctrl.py` | Non-modal find/replace across all panels |
| `LLMSideTaskController` | `llm_tasks.py` | Glossary, mind-map/graph/chunk-map tasks |
| `FeedbackController` | `feedback_ctrl.py` | Feedback UI, freeform dialog, stats |

### Controller Rules

1. A controller is created **once** in the setup pipeline and held for the
   application lifetime.
2. Constructors take explicit dependencies (no global state, no singletons
   except `AppContext`).
3. A controller **must not** hold a reference to another controller. Use
   `ctx.*` methods or signals instead.
4. A controller **must not** call private methods (`_`) of docks or widgets.
   If you need that behaviour, add a public method or property to the target.
5. Return types must be annotated on all public methods.

### KnowledgeController Ports (Protocols)

`KnowledgeController` interacts with docks through typed Protocols defined in
`knowledge_ports.py`:

```
KnowledgeDockPort — suspend/resume reindex, add files, open/rename/remove docs
ChatDockPort      — add/rename/remove documents in context panel
RAGWorkerPort     — isRunning(), enqueue_load_st(), st_loaded signal
```

These Protocols are `@runtime_checkable`. Pass a real dock in production,
pass a `MagicMock(spec=<Port>)` in tests.

---

## 8. Setup Sequence

`MainWindow.__init__` runs exactly these steps in this order. The order is
load-bearing — each step depends on the previous.

```
Step 1  _init_services()          — RAGSystem, LLMManager, ProjectManager, AppContext
Step 2  _init_early_controllers() — ThemeController (needed by Step 3),
                                    FeedbackController
Step 3  _init_window()            — window geometry, chrome theme (needs ThemeCtrl)
Step 4  _init_central()           — CanvasTabWidget (central widget)
Step 5  _init_statusbar()         — QStatusBar, FeedbackBar, status labels
                                    → binds FeedbackBar to ctx
Step 6  _init_docks()             — KnowledgeDock, ChatDock, LogDock
                                    → sets up dock callback wiring
Step 7  _init_controllers()       — all remaining controllers including
                                    LLMSideTaskController (needs FeedbackBar from Step 5)
                                    and FindReplaceController
Step 8  ctx.validate()            — asserts all bindings present (debug mode)
Step 9  build_menubar()           — populates menu (needs knowledge_controller for submenu)
Step 10 _init_global_shortcuts()  — Ctrl+F, Alt+1/2/3, Ctrl+Tab, Ctrl+Alt+S
Step 11 _connect_global_signals() — cross-component signal wiring + 1 s context timer
Step 12 set_user_mode()           — applies user mode UI state
Step 13 _autosave_ctrl.maybe_restore_from_tmp() — crash recovery
Step 14 _autosave_ctrl.start_runtime()          — activates periodic save
Step 15 log startup info
```

**Why Step 5 before Step 6:** `LLMSideTaskController` (created in Step 7)
needs the `FeedbackBar` widget. The `FeedbackBar` is created in Step 5 and
bound to `ctx`. Step 6 creates the docks, which `LLMSideTaskController` also
needs. So the order is: FeedbackBar → Docks → LLMSideTaskController. If you
need a new controller that requires a UI widget created before docks exist,
bind that widget to `ctx` in its creation step, not in `_init_docks`.

### Profile-Driven UI Rules

User profiles are runtime-configured via `data/user_modes/*.toml` (not hard-coded).
`shared/domain/user_mode.py` is the single resolver API used by UI code.

#### A. Source-of-truth contract (MUST)

- A profile is exactly one TOML file: `data/user_modes/<mode_id>.toml`.
- Canonical profile id is the filename stem; `id` in TOML must match it.
- Exactly one profile must declare `default_profile=true`.
- Every profile must define all required sections:
  `visibility`, `labels`, `literal_labels`, `literal_tooltips`.
- Key sets across profiles must stay aligned; add/remove keys consistently in all
  profile files.
- `validate_user_mode_config()` must pass in tests/CI.

#### B. Runtime API contract (MUST)

- Use `is_feature_visible(mode, "feature.key", default=...)` for all visibility
  gates (menus, actions, buttons, dialogs, advanced settings fields).
- Use `resolve_feature_label(mode, "feature.key", default)` for profile-specific
  labels; use `feature.key.tooltip` for hover text overrides.
- For hard-coded UI literals that are not key-bound, use profile literal maps
  (`literal_labels`, `literal_tooltips`) via
  `studio/profile_text_overrides.py`.
- Prefer declarative bindings over repeated imperative
  `setText()/setToolTip()/setVisible()` blocks:
  `studio/user_mode_bindings.py` (`apply_widget_texts`,
  `apply_widget_tooltips`, `apply_widget_visibility`, `apply_form_row_*`,
  `apply_combo_item_labels`).
- Runtime `QMessageBox` text must remain profile-overridable via
  `install_qmessagebox_literal_overrides()`.

#### Example: profile-controlled button

TOML keys in profile files:

```toml
# data/user_modes/simple.toml
[visibility]
"example.actions.generate_summary" = false

[labels]
"example.actions.generate_summary" = "Generate Summary"
"example.actions.generate_summary.tooltip" = "Create a summary from the current context."
```

```toml
# data/user_modes/plus.toml
[visibility]
"example.actions.generate_summary" = true

[labels]
"example.actions.generate_summary" = "Generate Summary"
"example.actions.generate_summary.tooltip" = "Create a summary from the current context."
```

Widget wiring (no `if mode == "simple"` branching):

```python
from PySide6.QtWidgets import QPushButton

from shared.domain.user_mode import normalize_user_mode
from studio.user_mode_bindings import (
    apply_widget_texts,
    apply_widget_tooltips,
    apply_widget_visibility,
)

self.generate_summary_btn = QPushButton("Generate Summary")

def set_user_mode(self, mode: str) -> None:
    self._user_mode = normalize_user_mode(mode)
    apply_widget_visibility(
        self._user_mode,
        (
            (self.generate_summary_btn, "example.actions.generate_summary", True),
        ),
    )
    apply_widget_texts(
        self._user_mode,
        (
            (self.generate_summary_btn, "example.actions.generate_summary", "Generate Summary"),
        ),
    )
    apply_widget_tooltips(
        self._user_mode,
        (
            (
                self.generate_summary_btn,
                "example.actions.generate_summary.tooltip",
                "Create a summary from the current context.",
            ),
        ),
    )
```

#### C. Main-window propagation contract (MUST)

- `MainWindow.set_user_mode()` is the only orchestration point for mode changes.
- It must continue to:
  - normalize the incoming mode,
  - update runtime context state,
  - propagate to canvas/docks/open dialogs,
  - apply key-based bindings and literal overrides,
  - sync mode menu checks and status label.
- Any new modeless dialog must implement `set_user_mode(mode: str)` so the
  propagation path remains complete.

#### D. Persistence contract (MUST)

- User mode must round-trip through project persistence in `project.json`
  (`ui.user_mode`) and be restored by `ProjectLoader`.
- Autosave restore must recover user mode because it loads the autosave project
  through the same project loader path.
- Unknown/legacy mode values must normalize safely to `default_user_mode()`.
- Global `QSettings` is not the source of truth for user mode selection.
  Persistent user mode state is project/autosave scoped.

#### E. Key design and allowed patterns

- Prefer stable key namespaces:
  `canvas.toolbar.*`, `canvas.preview.button.*`, `knowledge.tab.*`,
  `rag.results.*`, `prompt_editor.*`, `importer.dialog.*`,
  `importer.pdf.viewer.*`, `importer.pdf.group.*`,
  `importer.pdf.general.*`, `importer.pdf.tables.*`,
  `importer.pdf.header_footer.*`, `importer.pdf.heading.*`,
  `importer.pdf.paragraph.*`, `glossary.editor.*`, `feedback.*`.
- Prefer key-based checks over rank-based or hard-coded branching.
  `mode_rank()` is legacy and should not be used for new UI gating.
- Avoid direct string branching like `if mode == "simple"` in UI code unless it
  is an explicit, documented compatibility shim.

---

## 9. Signal/Slot Rules

**Rule:** Prefer Qt signals over callback functions.

Correct pattern:
```python
# Sender emits a signal:
class ChatDock(QDockWidget):
    glossary_requested = Signal(str)

# Receiver connects to it:
chat_dock.glossary_requested.connect(llm_tasks_ctrl.request_glossary)
```

Incorrect pattern (do not add more of these):
```python
# Do NOT inject callbacks via set_* methods:
chat_dock.set_glossary_request_handler(window._generate_glossary)
```

The existing `set_context_getter`, `set_canvas_selection_getter` etc. on
`ChatDock` are legacy. Do not add new `set_*_handler` or `set_*_getter`
methods to any dock or widget.

**Thread safety:** Signals crossing thread boundaries (worker → main thread)
are safe because Qt queues them automatically when emitted from a non-GUI
thread. Never update a QWidget directly from a background thread.

---

## 10. Threading Model

```
Main Thread (Qt event loop)
│
├── LLMWorker (QThread)          — owns active BaseLLMBackend; streams tokens via signals
│
├── RAGWorker (QThread)          — queue-based; indexing + search + ST model load
│   └── RAGSystem (RLock)        — all RAGSystem methods are thread-safe
│
├── TTS Worker (QThread)         — Piper audio synthesis
│
└── Dictation Worker (QThread)   — Whisper inference + audio capture (arecord)
```

**Rules:**
1. Never call a `QWidget` method from a background thread.
2. Background threads communicate with the main thread exclusively via signals.
3. `RAGSystem` methods are safe to call from any thread (protected by
   `threading.RLock`), but long blocking calls (sync index) should still go
   through `RAGWorker` to keep the UI responsive.
4. `LLMManager` synchronous methods (`expand_query_tfidf_sync`, etc.) block
   the calling thread. Call them only from a worker thread or from a context
   where blocking is acceptable (e.g. during autosave preparation).
5. `QThread.wait(timeout_ms)` return value **must** be checked. If it returns
   `False`, call `terminate()` then `wait()` and log the event.

---

## 11. Project Persistence

### Folder Layout (on disk)

```
<project_folder>/
├── canvas/
│   ├── doc_0000.md          # Canvas tab 0 content
│   ├── doc_0001.md          # Canvas tab 1 content
│   └── ...
├── knowledge/
│   ├── doc_0000.md          # Imported document 0 (persisted markdown)
│   └── ...
├── rag/
│   ├── index.pkl            # Pickled TF-IDF index + metadata
│   └── embeddings.pt        # Pickled sentence-transformer embeddings (optional)
├── chat/
│   ├── history.json         # Chat message history
│   └── chunk_claim_cache.json  # Fact-check claim cache
├── logs/
│   └── entries.json         # Debug log entries
├── highlights.json          # Highlight/glossary store for this project
└── project.json             # Manifest (`version`, file list, metadata)
```

### Archive Format (`.d2c`)

Project persistence supports both folder-based projects and compressed archives:
- Export creates a standard ZIP archive with `.d2c` extension that contains the
  full project folder contents at archive root.
- Import accepts `.d2c` archives (and ZIP-compatible content), validates ZIP
  integrity and required project structure (`project.json`, `canvas/`,
  `knowledge/`, `rag/`, `chat/`, `logs/`), then extracts to a managed workspace
  before running `ProjectLoader`.
- ZIP path traversal is blocked during validation/extraction (no absolute paths,
  no `..`, no drive-style prefixes).
- `ProjectLoader` expects current manifest fields only (for example
  `llm.nli_model_id`, `settings.prompts`); deprecated aliases are not mapped.

### Manifest UI contract

- `project.json` must preserve UI profile state in `ui.user_mode`.
- Save path: `ProjectSaver` writes `ui.user_mode` from `MainWindow.user_mode`.
- Load path: `ProjectLoader` restores `ui.user_mode` through
  `MainWindow.set_user_mode(..., notify=False)`.
- Because autosave restore uses `ProjectLoader` on the autosave workspace,
  user mode restoration must behave identically for manual project load and
  crash-recovery restore.

### Path Security

All paths within a project are validated via `ProjectPaths._resolve_child()`:
- `Path.resolve(strict=False)` prevents symlink traversal.
- `_is_relative_to(candidate, allowed_root)` rejects escapes like `../../etc`.
- No user-supplied string is ever passed to `Path` without going through
  `ProjectPaths`.

---

## 12. QSettings Key Registry

All persistent setting keys live in `shared/config/setting_keys.py` as
`Final[str]` class attributes. **Never** write a QSettings key as a string
literal anywhere else in the codebase.

Key groups:

| Class | Domain | Example key |
|-------|--------|-------------|
| `AutosaveSettingsKeys` | Autosave | `autosave/enabled` |
| `ThemeSettingsKeys` | UI / preview | `ui/theme`, `preview/markdown_theme` |
| `FeedbackSettingsKeys` | Feedback | `feedback/ui_enabled` |
| `SpeechSettingsKeys` | TTS / STT | `tts_engine`, `stt_model_size` |
| `PromptTemplateKeys` | LLM prompts | 39 keys, includes `ALL` tuple |
| `RAGSettingsKeys` | RAG pipeline | `rag/chunking_strategy`, `rag/top_k` |

QSettings organisation/application strings: `"draft2craift"` / `"draft2craift"`.
Primary runtime settings are created in `services_setup.py` and passed through
`AppContext`. One additional bootstrap instance exists in `studio/app.py` to
apply the UI theme before `MainWindow` is constructed.

---

## 13. Domain Models (`shared/domain/`)

Domain models are pure Python — no Qt, no I/O. They use `@dataclass(frozen=True)`
or plain `@dataclass`. No methods beyond `__post_init__` validation.

Do not add serialisation logic to domain classes. Serialisation belongs in
`shared/services/project/project_saver.py` and `project_loader.py`.

---

## 14. Testing Conventions

Tests mirror the source tree:

```
tests/
├── domain/         # Tests for shared/domain/*
├── services/       # Tests for shared/services/*
└── studio/         # Tests for studio/controllers/* and studio/setup/*
```

**Mocking:**
- Prefer `unittest.mock.create_autospec(SomeClass, instance=True, spec_set=True)`.
- Avoid adding new hand-crafted stub classes (`_FooStub`); migrate legacy stubs opportunistically.
- For dock dependencies, mock against the Port protocol:
  `MagicMock(spec=KnowledgeDockPort)`.

**Qt in tests:**
- Tests that instantiate `QObject` subclasses need a `QApplication`. Use the
  shared `conftest.py` fixture; do not create `QApplication` inline.
- Controller tests should not instantiate `MainWindow`.

**Coverage target:** 75 % (not yet enforced in CI but the goal).

---

## 15. Architectural Rules — Checklist

Use this list to verify that new code is conformant.

### Layer rules
- [ ] `shared/` contains no import from `studio/`
- [ ] `shared/` contains no `QWidget`, `QDialog`, `QMainWindow`, `QLayout`
- [ ] `shared/domain/` contains no import from `shared/services/`
- [ ] `shared/config/` contains no import from `shared/services/`

### AppContext rules
- [ ] `AppContext` holds references only to services and controllers — not to
      dock widgets (exception: `_glossary_feedback_bar`)
- [ ] No new `bind_*dock*` or `bind_*widget*` methods added to `AppContext`
- [ ] No new delegation method added to `AppContext` that is a trivial
      one-liner wrap of a single controller method
- [ ] `AppContext.validate()` is called exactly once, after `_init_controllers()`

### Controller rules
- [ ] No controller holds a reference to another controller
- [ ] No controller calls a `_private` method of a dock or widget
- [ ] Every new controller is created in `controllers_setup.py` and added to
      `ControllerBundle`
- [ ] Every controller method has a return type annotation

### Signal/Slot rules
- [ ] No new `set_*_handler` or `set_*_getter` injected into a dock or widget
- [ ] No UI widget update performed from a non-main thread (no direct `setText`,
      `setEnabled`, etc. in a `QThread.run()`)

### Threading rules
- [ ] `QThread.wait(timeout_ms)` return value is always checked
- [ ] LLM synchronous methods are not called on the main thread during normal
      UI operation

### Settings rules
- [ ] No QSettings key written as a string literal outside `setting_keys.py`
- [ ] Additional `QSettings` instances are avoided in runtime code (bootstrap in `studio/app.py` is allowed)

### User-mode rules
- [ ] New UI behavior is gated via profile keys (`is_feature_visible` /
      `resolve_feature_label`) rather than hard-coded mode branching
- [ ] New profile keys are added consistently to all `data/user_modes/*.toml`
      files and `validate_user_mode_config()` remains clean
- [ ] New modeless dialogs implement `set_user_mode(mode: str)` and are
      compatible with main-window propagation
- [ ] Project save/load keeps `ui.user_mode` round-trip intact

### Project path rules
- [ ] All file I/O within a project folder goes through `ProjectPaths`
- [ ] No `Path(user_string)` without `.resolve()` + `_is_relative_to()` check

### Path resolution rules
- [ ] `Path.cwd()` is not used for persistent data paths; use
      `QStandardPaths.writableLocation()` (in `studio/`) or
      `platformdirs.user_data_dir()` (in `shared/`)

### Testing rules
- [ ] New tests prefer autospec/spec-set mocks; no new long-lived hand-crafted stubs
- [ ] New controller has at least one test in `tests/studio/`

---

## 16. Static Data (`data/`)

```
data/
├── about.md          # "About" page shown in the preview panel
├── shortcuts.md      # Keyboard shortcuts reference page
├── welcome.md        # First-run welcome page
├── user_modes/       # Profile catalog (*.toml) for visibility/labels/literals
└── prompts/
    └── defaults.json # Default LLM prompt templates shipped with the app
```

**Rules:**
- Runtime code may read from `data/` (for example via `_read_data_file()` in
  `window.py` and profile loading in `shared/domain/user_mode.py`), but must not
  write back into repository data files.
- `prompts/defaults.json` is the fallback when no user-customised prompts exist;
  runtime user edits are stored in `QStandardPaths.AppDataLocation`, never in
  `data/`.
- `user_modes/*.toml` is the canonical profile catalog used by
  `shared/domain/user_mode.py`.
- Do not add binary assets, images, or model weights here — only plain text and
  JSON.

---

## 17. Automated Tests (`tests/`)

```
tests/
├── conftest.py            # Session-scoped pytest fixtures
├── domain/                # Pure-Python domain model tests (no Qt)
│   ├── test_feedback_domain.py
│   ├── test_graph_spec.py
│   └── test_user_mode.py
├── services/              # shared/ service layer tests (no Qt or minimal Qt)
│   ├── test_rag_chunking.py
│   ├── test_rag_config.py
│   ├── test_rag_concurrency.py
│   ├── test_rag_orchestrator_public_api.py
│   ├── test_project_path_security.py
│   ├── test_prompt_migration.py
│   └── ...                # ~11 files total
└── studio/                # PySide6 UI layer tests (require Qt offscreen)
    ├── test_app_context_validate.py
    ├── test_autosave_controller.py
    ├── test_chat_history_sessions.py
    ├── test_find_replace_controller.py
    ├── test_knowledge_controller_rag_public_api.py
    ├── test_llm_tasks_controller.py
    ├── test_theme_profiles.py
    └── ...                # ~22 files total
```

### Key fixtures (`conftest.py`)

| Fixture | Scope | What it provides |
|---------|-------|-----------------|
| `_qt_offscreen` | session (autouse) | Sets `QT_QPA_PLATFORM=offscreen` before Qt initialises |
| `qt_app` | session | Single `QApplication` instance reused by all tests |
| `rag_config` | function | `RAGConfig` with both backends disabled (fast, no model) |
| `rag_entries` | function | List of `RAGEntry` objects for seeding |
| `rag_system` | function | Empty `RAGSystem` instance |
| `indexed_rag_system` | function | `RAGSystem` pre-seeded with `rag_entries` |

### Conventions

- **Mirror structure:** every `studio/foo.py` has tests in `tests/studio/test_foo.py`; every `shared/services/bar.py` has tests in `tests/services/test_bar.py`.
- **Prefer autospec mocks:** use `unittest.mock.create_autospec(SomeClass, spec_set=True)` for new tests; migrate legacy stubs over time.
- **Offscreen Qt:** all `tests/studio/` tests rely on the `_qt_offscreen` autouse fixture; never create a real display.
- **No network / model I/O:** tests must not download models or call external APIs; mock `LLMManager` and `RAGSystem` at the boundary.
- **Run:** `pytest tests/` from the repository root. No special flags required.

---

## 18. Evaluation Scripts (`eval/`)

```
eval/
├── rag_eval.py            # RAG pipeline: precision, recall, F1, MRR, MAP, nDCG
├── rag_sweep.py           # Grid-sweep over RAGConfig hyperparameters
├── factcheck_eval.py      # Fact-check claim accuracy vs. reference
├── glossary_eval.py       # Glossary extraction quality
├── judge_eval.py          # LLM-as-judge scoring of generated text
├── llm_compare_eval.py    # Side-by-side comparison of two LLM outputs
├── mindmap_eval.py        # Mind-map structure correctness
├── pdf_eval.py            # PDF text extraction quality
├── stt_diag.py            # Speech-to-text diagnostics (WER, latency)
├── feedback_generate_tests.py  # Generate test cases from feedback events
├── build_fixtures.py      # Build reusable eval fixture files
└── shared/
    ├── logger.py          # Structured JSONL logger used by all eval scripts
    ├── metrics.py         # Shared metric implementations (RR, AP, nDCG, …)
    └── models.py          # Dataclasses: EvalCase, EvalResult, SuiteRun
```

### Invocation pattern

```bash
python -m eval.rag_eval --suite eval/examples/rag_suite.example.json \
       --output-dir runs/rag_eval --run-name exp-01
python -m eval.rag_sweep --suite eval/examples/rag_sweep.example.json
```

All scripts write results as JSONL to `--output-dir` (defaults are tool-specific under `runs/`).

### Rules

- **Packaging status:** `eval/` is currently included in the wheel (see `pyproject.toml` `[tool.hatch.build.targets.wheel]`). It is still intended for repo/tooling workflows.
- **Shared utilities live in `eval/shared/`**, never duplicated across scripts.
- **No Qt imports** in `eval/` — these are pure CLI tools; GUI display is handled by `test_studio/`.
- Metrics from `eval/shared/metrics.py` are the canonical implementations; do not recompute precision/recall/F1 inline.

---

## 19. Evaluation Dashboard (`test_studio/`)

```
test_studio/
├── main.py          # Entry point: `python test_studio/main.py`
├── app.py           # Main PySide6 window (TestStudioApp)
├── models.py        # Qt data models (SuiteRunModel, RunCompareModel)
├── components/      # Data loading, metrics, runner/process helpers
└── view/            # Reusable view widgets
```

**Purpose:** GUI dashboard for loading, running, and comparing `eval/` suite
results. Reads JSONL run files produced by `eval/*.py` scripts and shows
aggregate metrics, per-case diffs, and pass/fail status.

**Rules:**
- Uses PySide6 but is **not** part of the main `studio/` application; it is a
  standalone tool launched separately.
- Does not import from `studio/`; may import from `shared/` and `eval/shared/`.
- Does not modify run files — read-only display only.
- Launch: `python test_studio/main.py` (not `python main.py`).

---

## 20. Test-Case Authoring Studio (`testcase_studio/`)

```
testcase_studio/
├── main.py               # Entry point: `python testcase_studio/main.py`
├── app.py                # Root dialog (TestCaseStudioApp)
├── case_dialog.py        # Per-case edit dialog
├── case_fields.py        # Field widgets (query, ground-truth, tags…)
├── controller.py         # Business logic: load/save/validate suite JSON
├── draft_builder.py      # Builds draft test cases from feedback event JSONL
├── feedback_formatter.py # Formats feedback payloads for human review
├── models.py             # Dataclasses: TestCase, EvalSuite
├── storage.py            # Read/write suite JSON files
├── suite_schema.py       # JSON schema definition for suite files
├── text_utils.py         # Text helpers (truncation, normalisation)
├── ui_style.py           # Shared stylesheet constants
└── views.py              # List / detail views
```

**Purpose:** PySide6 dialog application for authoring and editing evaluation
test-case suites (`.json` files consumed by `eval/` scripts). Can also ingest
feedback event logs and propose draft test cases for human review.

**Rules:**
- Standalone tool — not imported by `studio/` or `test_studio/`.
- May import from `shared/` and `eval/shared/`; must not import from `studio/`.
- Suite files it writes must validate against `suite_schema.py`'s schema.
- Launch: `python testcase_studio/main.py`.

---

## 21. Known Intentional Exceptions

These patterns look like violations but are intentional and must not be
"fixed":

| Pattern | Location | Reason |
|---------|----------|--------|
| `QObject` / `QThread` in `shared/` | `rag/orchestrator.py`, `rag/worker.py`, `llm/manager.py`, `llm/worker.py`, speech workers | Signal/slot threading requires Qt base classes |
| `QByteArray` in `shared/services/project` | `project_loader.py` | Restores persisted window state bytes during project load |
| `set_context_getter` etc. on `ChatDock` | `docks_setup.py` | Legacy callback wiring; acceptable until signal migration |
| `_apply_runtime_settings()` called from `window.py` | `_connect_global_signals` | Private method call across layers; tracked as tech debt |
| `getattr(..., None)` defensive access | `AppContext.autosave_*` methods | Guards against partially-initialised state during startup |
