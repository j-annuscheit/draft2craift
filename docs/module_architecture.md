# Module Architecture

This project follows a feature-first modular structure.

## Goals

- Keep modules self-contained by responsibility.
- Avoid editing the same behavior in many files.
- Eliminate duplicated implementation code.
- Keep imports on canonical module paths only.

## Current structure

- `shell/window.py`
  - Canonical application shell (`MainWindow`).
  - Owns top-level orchestration, dock wiring, and menu actions.

- `shell/theme.py`
  - Canonical app theme helper (`apply_dark_theme`).

- `shell/logging.py`
  - Canonical logger and debug dock (`AppLogger`, `LogDock`).

- `features/canvas/widget.py`
  - Canvas orchestration widget (`CanvasTabWidget`): toolbar + tabs + composition.

- `features/canvas/preview.py`
  - HTML preview pane (`CanvasPreviewPane`): render, cursor-sync, zoom/Ctrl+Wheel.

- `features/canvas/file_actions.py`
  - Canvas file operations (`CanvasFileActions`): open/save/export.

- `features/canvas/selection_ops.py`
  - Canvas selection/text helpers (`CanvasSelectionActions`).

- `features/chat/dock.py`
  - Chat orchestration (`ChatDock`): wiring of panels, send flow, signals.

- `features/chat/model_panel.py`
  - Model/runtime parameter panel (`ModelLoadPanel`).

- `features/chat/context_panel.py`
  - Context source selector panel (`ContextSelectorPanel`).

- `features/chat/history.py`
  - Chat transcript widget with streaming token support (`ChatHistoryWidget`).

- `features/chat/rewrite.py`
  - Rewrite extraction and safety validation helpers for selection-apply mode.

- `features/chat/factcheck_pipeline.py`
  - Faktencheck pipeline orchestration (extract -> verify workflow).

- `features/chat/factcheck_utils.py`
  - Faktencheck parsing/normalization/validation helpers.

- `features/knowledge/dock.py`
  - Canonical knowledge dock implementation.

- `features/knowledge/rag_settings_dialog.py`
  - Canonical RAG settings dialog.

- `features/importer/*`
  - Canonical importer subsystem (dialog orchestration + UI/selection/worker mixins, entry state model, panel group builders/helpers, pdf conversion pipeline + dedicated header/footer/font/reflow/table modules, workers, viewer + overlay logic, facade).

- `services/llm/manager.py`
  - Canonical LLM service and worker.

- `services/rag/system.py`
  - Canonical RAG system and worker.

- `services/project/manager.py`
  - Canonical project save/load service.

- `widgets/markdown/editor.py`
  - Canonical markdown widgets (`MarkdownEditor`, `EditorPanel`, `TabbedEditorWidget`).

- `widgets/markdown/highlighter.py`
  - Canonical markdown syntax highlighter.

- `core/user_modes.py`
  - Canonical shared user mode constants/helpers.

## Migration status

- Legacy wrapper modules were removed.
- Legacy entrypoint wrappers were removed.
- Runtime imports now target canonical module paths directly.

## Change rules (to prevent code duplication)

1. Change behavior only in canonical modules (`core/`, `services/`, `features/`, `widgets/`, `shell/`).
2. Do not reintroduce compatibility wrappers for removed legacy paths.
3. If logic is shared across features, place it in `services/` or `widgets/`.
4. Keep import direction one-way: shell/features -> services/widgets/core (never reverse).

## Remaining optional cleanup

1. Split `shell/window.py` further into `shell/menus.py` and `shell/actions.py`.
2. Introduce per-feature test packages that import canonical paths only.
