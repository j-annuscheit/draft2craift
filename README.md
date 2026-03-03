<div align="center">

# draft2craift

**Local-first AI writing studio — no cloud, no subscriptions, no data leaving your machine.**

***D**ocument **R**etrieval **A**ugmented **F**ile **T**ool **2** **C**ollaboratively **R**evised **A**I **F**ormatted **T**ext*

[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL--3.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)](https://python.org)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey)]()
[![No Cloud](https://img.shields.io/badge/Cloud-None-brightgreen)]()
[![GGUF](https://img.shields.io/badge/Inference-llama.cpp%20%2F%20GGUF-orange)]()

<!-- Add screenshot or demo GIF here -->
<!-- ![demo](docs/demo.gif) -->

</div>

---

draft2craift is a **PySide6 desktop application** for LLM-assisted document writing with
Retrieval-Augmented Generation (RAG). Load any GGUF model, import your documents,
and let the AI help — entirely offline.

**Key features at a glance:**
- Three-pane layout: Markdown editor · Knowledge dock · AI chat
- Import PDF, DOCX, HTML, ODT, CSV and code files
- RAG with TF-IDF (built-in) or sentence-transformers (optional)
- Fact-checking pipeline against your own documents
- Fully local inference via [llama-cpp-python](https://github.com/abetlen/llama-cpp-python)
- Portable Windows `.exe` and Linux bundle available

---

## How does draft2craift compare to other tools?

| | draft2craift | LM Studio | OpenWebUI | Jan.ai | Obsidian + plugins |
|---|---|---|---|---|---|
| Local GGUF inference | ✅ | ✅ | ✅ | ✅ | via plugin |
| Markdown editor | ✅ | ❌ | ❌ | ❌ | ✅ |
| Built-in RAG pipeline | ✅ | ❌ | ✅ | limited | via plugin |
| PDF / DOCX import | ✅ | ❌ | ✅ | ❌ | limited |
| Fact-checking | ✅ | ❌ | ❌ | ❌ | ❌ |
| No server required | ✅ | ✅ | ❌ | ✅ | ✅ |
| No API key needed | ✅ | ✅ | ✅ | ✅ | ❌ |
| Open source | ✅ AGPL | ❌ | ✅ | ✅ | ✅ |

draft2craift is the only tool in this list that tightly integrates a **Markdown editor**,
**local LLM chat**, and a **full RAG pipeline** in a single offline desktop application.

---

## FAQ

**What is draft2craift?**
draft2craift is a free, open-source desktop app for AI-assisted writing. It runs entirely
on your computer — no internet connection required. You load a local GGUF language model,
import your documents, and the app helps you write, research, and fact-check.

**Does draft2craift send any data to the cloud?**
No. All inference runs locally via llama-cpp-python (llama.cpp). No telemetry, no API
calls, no accounts. Your documents and drafts never leave your machine.

**Which AI models does draft2craift support?**
Any model in GGUF format: Llama 3, Mistral, Phi-3/4, Gemma 2, Qwen 2.5, DeepSeek,
and many others. Download models from Hugging Face (search for GGUF quantizations).

**What is RAG and how does draft2craift use it?**
RAG (Retrieval-Augmented Generation) means the AI answers based on your own documents
instead of just its training data. draft2craift indexes your imported files and
automatically retrieves relevant passages to include in the LLM context when you chat.

**Can I use draft2craift for commercial work?**
Yes. The application is licensed under AGPL-3.0. You can use it freely for any purpose.
If you distribute a modified version, you must share the source code under AGPL-3.0.

**What are the system requirements?**
Python 3.10+, Windows / Linux / macOS. For GPU acceleration: NVIDIA (CUDA) or
Apple Silicon (Metal). CPU-only mode works on any modern computer — slower but functional.

**Is there a portable version / installer?**
Yes. Pre-built Windows `.exe` bundles (portable ZIP and Inno Setup installer) can be built
with the included PowerShell script. A Linux `.tar.gz` bundle is also available.

**How is draft2craift different from a simple ChatGPT wrapper?**
draft2craift is built around the writing workflow: it has a full Markdown editor with
live preview, a document knowledge base with RAG search, project save/load, and a
fact-checking pipeline. It is not a chat interface bolted onto an editor.

---

## Table of Contents

- [1. Features](#1-features)
- [2. Installation](#2-installation)
- [3. Running the app](#3-running-the-app)
- [4. Usage](#4-usage)
- [5. GGUF / LLM details](#5-gguf--llm-details)
- [6. File import and PDF → Markdown](#6-file-import-and-pdf--markdown)
- [7. RAG (Retrieval)](#7-rag-retrieval)
- [8. Prompt system](#8-prompt-system)
- [9. Fact-checking](#9-fact-checking)
- [10. Save / load projects](#10-save--load-projects)
- [11. RAG test tools (CLI)](#11-rag-test-tools-cli)
- [12. Keyboard shortcuts](#12-keyboard-shortcuts)
- [13. Troubleshooting](#13-troubleshooting)
- [14. Architecture](#14-architecture)
- [15. Windows EXE & installer](#15-windows-exe--installer)
- [16. License](#16-license)

---

## 1. Features

- **Draft (centre panel)**
  - Multi-tab Markdown editor
  - Undo / Redo buttons in the draft header
  - Live HTML preview (`HTML View`) with cursor sync
  - Export current tab as PDF or Word document

- **Knowledge Dock (left)**
  - `Viewer`: imported documents as Markdown tabs
  - `RAG`: file selection + search + result tabs
  - Renameable tabs, compact inactive tabs (numbered)
  - Delete document with confirmation dialog

- **AI Chat Dock (right)**
  - Load any GGUF model (llama.cpp via `llama-cpp-python`)
  - Change generation parameters live without reloading
  - Configurable context sources: draft, RAG results, individual documents
  - Optional: rewrite selected draft text directly with the LLM
  - Optional: Whisper dictation to a dedicated Draft tab (background transcription)

- **RAG**
  - Backends: TF-IDF, optional sentence-transformers, optional literal search
  - Chunking strategies: `sliding_window`, `section`, `recursive`
  - Optional: HyDE, literal term expansion via LLM, LLM reranking
  - Detailed debug view including search history per RAG tab

- **Fact-checking**
  - LLM extracts claims from target text and verifies each one against sources
  - Result is written as a Markdown table into a new draft tab
  - Includes quality check for inconsistent evidence

- **Prompt editor**
  - Fully editable prompts (not hard-coded)
  - Groups: Chat, Fact-check, RAG, Advanced, Legacy
  - Prompt flow preview and reset (single / group / all)

- **Project format**
  - Save and load draft tabs, imported documents, RAG index, prompt set, chat history, logs, UI state

---

## 2. Installation

### 2.1 Requirements

- Python 3.10+ (recommended: 3.11 / 3.12)
- `pip`
- Platform: Windows / Linux / macOS

### 2.2 Clone the repository

```bash
git clone https://github.com/annuscheit-jonas/draft2craift.git
cd draft2craift
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -U pip
pip install -r requirements.txt
```

### 2.3 llama-cpp-python (GGUF inference)

**CPU:**
```bash
pip install llama-cpp-python
```

**CUDA (NVIDIA):**
```bash
CMAKE_ARGS="-DGGML_CUDA=on" pip install llama-cpp-python
```

**Metal (Apple Silicon):**
```bash
CMAKE_ARGS="-DGGML_METAL=on" pip install llama-cpp-python
```

### 2.4 Optional packages

| Package | Feature |
|---|---|
| `pip install sentence-transformers` | Semantic RAG search |
| `pip install faster-whisper sounddevice` | Live Whisper dictation from microphone |
| `pip install piper-tts onnxruntime pathvalidate` | High-quality offline TTS (local models) |
| `pip install pymupdf4llm` | Full PDF import (AGPL-3.0) |
| `pip install python-docx` | DOCX import |
| `pip install markdownify` | HTML import |
| `pip install odfpy` | ODT import |

Install everything at once:
```bash
pip install sentence-transformers faster-whisper sounddevice piper-tts onnxruntime pathvalidate pymupdf4llm python-docx markdownify odfpy
```

Offline TTS with Piper (local models only):
```bash
pip install piper-tts onnxruntime pathvalidate
```
On first TTS use, draft2craift can auto-download one Piper model
(`.onnx` + `.onnx.json`) into `./models/piper`.
After the first successful download, synthesis runs fully local/offline.

Disable auto-download if required:
```bash
export DRAFT2CRAIFT_TTS_AUTO_DOWNLOAD=0
```

The app scans local Piper models from:
- `./models/piper`
- `~/.local/share/piper`
- `~/.local/share/piper/voices`
- `~/.cache/piper`

Optional custom model directory:
```bash
export DRAFT2CRAIFT_PIPER_MODELS_DIR=/path/to/local/piper-models
```

### 2.5 Conda environment

```bash
conda env create -f environment.yml
conda activate draft2craift
# then install llama-cpp-python manually (see 2.3)
```

---

## 3. Running the app

```bash
python main.py
```

A welcome tab opens on first launch.

---

## 4. Usage

### 4.1 Layout

| Panel | Description |
|---|---|
| **Centre** | Draft — Markdown editor, HTML preview |
| **Left** | Knowledge Dock — Viewer, RAG |
| **Right** | AI Chat Dock — model, chat, context |
| **Bottom** | Debug Log — toggle with `Ctrl+3` |

### 4.2 Typical workflow

1. `File → Import Files…` (`Ctrl+I`) — import your documents
2. Enable relevant files in the `RAG` tab
3. Load a GGUF model in the AI panel
4. Ask questions in the chat or rewrite selected draft text
5. Run fact-checking (`AI → Fact Check`) if needed
6. Save your project (`Ctrl+Shift+S`)

---

## 5. GGUF / LLM details

### 5.1 Generation vs. model load parameters

The Chat Dock has two separate parameter areas:

- **Generation** *(takes effect immediately for the next request)*
  - `max_tokens`, `temperature`, `top_p`, `repeat_penalty`, `forbidden_chars`
- **Model Load** *(takes effect only after clicking `Load Model`)*
  - Model path, `n_ctx`, `n_gpu_layers`, `n_threads`

### 5.2 Forbidden characters

`forbidden_chars` is enforced at two levels:
- during sampling via `logit_bias` (llama.cpp token suppression)
- as an additional output filter

Defaults include special whitespace characters, em-dash, and semicolon.

### 5.3 Context and grounding

The chat context can be assembled from:
- current draft
- current RAG result tab
- selected imported documents
- selected draft text

When document-grounded mode is active but no usable sources are present,
the response is intentionally declined.

### 5.4 Draft rewrite mode

Checkbox: `Apply rewrite directly to selected Draft text`

- **Unchecked:** response appears normally in the chat
- **Checked:** LLM must deliver the rewrite inside a `[[CANVAS_REWRITE]]…[[/CANVAS_REWRITE]]` block; the selection is replaced directly
- A safety check prevents incomplete replacements

---

## 6. File import and PDF → Markdown

### 6.1 Supported formats

| Format | Requirement |
|---|---|
| PDF | `pymupdf4llm` (optional, recommended) |
| DOCX | `python-docx` |
| HTML / HTM | `markdownify` |
| ODT | `odfpy` |
| CSV, TXT, RST, MD | — (standard library) |
| Code files | — (wrapped as Markdown code block) |

### 6.2 Parallel import

`Import All` uses a `ProcessPoolExecutor` (spawn) to accelerate conversion —
even for mixed file types.

### 6.3 PDF-specific settings

- **Pages:** page selection (`all` or ranges like `1-5,8,10-`)
- **Table strategy:** `lines_strict`, `lines`, `text`, `none`
- **Header / footer removal:**
  - Auto-detect (per page, repetition- and position-based)
  - Manual scan zones (global for all pages)
- **Heading detection:** `pymupdf4llm`, `custom`, `none`
- **Paragraph reflow:** `none`, `join`, `smart`

### 6.4 PDF viewer in the import dialog

- Page navigation + zoom
- Overlays for H/F zones, detected blocks and heading rectangles
- In manual H/F mode: zones can be adjusted by dragging

---

## 7. RAG (Retrieval)

### 7.1 Backends

| Backend | Requirement |
|---|---|
| `tfidf` | always available |
| `st` (sentence-transformers) | `pip install sentence-transformers` |
| `literal` | regex / substring search |

Multiple backends can be combined (`tfidf+st+literal`).

### 7.2 Pipeline

1. Query expansion (optional: HyDE, literal terms)
2. Retrieval per backend
3. Fusion (RRF)
4. Result selection (`top_k`, `threshold`, `top_k_threshold`)
5. LLM reranking (optional)
6. Merge into document results

### 7.3 RAG debug view

`🧪` in the RAG panel opens the debug history:
- backend hits, used terms, warnings, merge information

---

## 8. Prompt system

All prompts are stored in `prompts/defaults.json` and are fully editable.

`AI → Edit Prompts…` opens the prompt editor with the following groups:

| Group | Content |
|---|---|
| Chat | System prompt, context blocks |
| Fact-check | Extraction, verification, summary |
| RAG | HyDE, term expansion, reranking |
| Advanced | Structural building blocks |
| Legacy | Deprecated prompts (backwards compatibility) |

Prompt values are saved with the project and restored on load.

---

## 9. Fact-checking

### How it works

1. Determine target text (selected text → draft → chat input field)
2. LLM extracts claims (JSON list)
3. Each claim is verified individually against active sources
4. Result is written as a Markdown table into a new draft tab

### Result format

| Column | Content |
|---|---|
| `ID` | Sequential number |
| `Claim` | Extracted claim |
| `Evidence` | Found passage |
| `Source` | Document name |
| `Status` | `confirmed` · `partial` · `unconfirmed` · `contradiction` |

---

## 10. Save / load projects

`File → Save Project…` (`Ctrl+Shift+S`) / `File → Load Project…` (`Ctrl+Shift+O`)

Saved: draft tabs, documents, RAG index, sentence-transformer embeddings,
RAG result tabs, chat history, logs, LLM parameters, prompt set, layout.

```
<project>/
  project.json
  canvas/
  knowledge/
  rag/
    index.pkl
    embeddings.pt   (optional, only with sentence-transformers)
  chat/
  logs/
```

> The model is **not** reloaded automatically when a project is loaded — only the UI fields are restored.

---

## 11. RAG test tools (CLI)

```bash
# Single test suite
python scripts/rag_eval.py \
  --suite scripts/examples/rag_suite.example.json \
  --output-dir runs/rag_eval \
  --run-name demo_eval

# Hard semantic suite (non-literal/paraphrase queries)
python scripts/rag_eval.py \
  --suite scripts/examples/rag_suite.semantic_extreme.json \
  --output-dir runs/rag_eval \
  --run-name semantic_extreme_baseline

# With GGUF model (enables LLM reranking + HyDE evaluation)
python scripts/rag_eval.py ... \
  --llm-model /path/to/model.gguf \
  --llm-n-ctx 4096

# Parameter sweep
python scripts/rag_sweep.py \
  --suite scripts/examples/rag_suite.example.json \
  --grid scripts/examples/rag_sweep.example.json \
  --output-dir runs/rag_sweep

# Open interactive dashboard (run comparison + label analysis)
python scripts/test_studio.py --root runs

# Open Testcase Studio (Feedback -> Testcase management)
python scripts/testcase_studio.py --storage-dir runs/feedback
```

Metrics: Precision, Recall, F1, Hit@K, MRR, MAP, nDCG, Contains-Recall

---

## 12. Keyboard shortcuts

| Shortcut | Action |
|---|---|
| `Ctrl+N` | New draft tab |
| `Ctrl+O` | Open file in draft |
| `Ctrl+S` | Save current tab |
| `Ctrl+I` | Import files |
| `Ctrl+Shift+S` | Save project |
| `Ctrl+Shift+O` | Load project |
| `Ctrl+Q` | Quit |
| `Ctrl+1` | Toggle Knowledge Dock |
| `Ctrl+2` | Toggle AI Chat Dock |
| `Ctrl+3` | Toggle Debug Log |
| `Ctrl+Enter` | Send message |
| `Ctrl+.` | Stop generation |

---

## 13. Troubleshooting

**Model does not load**
- Check that the file path exists
- Run `pip show llama-cpp-python`
- Reinstall the correct build variant (CPU / CUDA / Metal)
- Check the Debug Log (`Ctrl+3`) for the full error message

**No response in document-grounded mode**
- Enable documents in the Context Selector
- Run a RAG search first, then ask again

**Prompt too large / context window exceeded**
- Select fewer context sources
- Reduce `max_tokens`
- Use a model with a larger context window

**RAG reranking not applied**
- Check the RAG debug panel for a fallback warning

---

## 14. Architecture

```
main.py                        App entry point
shell/
  window.py                    Orchestration, menus, signal wiring
  theme.py                     Global Qt palette/theme
  logging.py                   Debug logger + LogDock
core/
  user_modes.py                Shared user mode constants/helpers
services/
  llm/manager.py               Prompt building, LLMWorker (QThread), llama.cpp
  rag/system.py                Indexing, search, fusion, RAGWorker (QThread)
  project/manager.py           Save/load complete project state
features/
  canvas/widget.py             Draft canvas + HTML preview
  chat/dock.py                 Chat UI, rewrite flow, fact-checking
  knowledge/dock.py            Viewer + RAG UI
  importer/*                   Import dialog, PDF pipeline, viewer, workers
widgets/
  markdown/editor.py           Markdown editor + tab management
  markdown/highlighter.py      Markdown syntax highlighting
```

**Key patterns:**
- Qt Signal / Slot — no direct cross-component method calls
- LLM inference in `QThread` (LLMWorker)
- RAG operations in `RAGWorker` with task queue + lock
- Dual RAG backends (strategy pattern, identical API)

---

## 15. Windows EXE & installer

PyInstaller **cannot cross-compile** — the build must run on Windows (x64).

### Requirements

- Python 3.10–3.12
- PowerShell
- Optional for installer: [Inno Setup](https://jrsoftware.org/isinfo.php) (`iscc` on `PATH`)
- Optional for CUDA: NVIDIA CUDA Toolkit + Visual Studio Build Tools (C++ workload)

### Build profiles

| Profile | Contents | When to use |
|---|---|---|
| `full` *(default)* | all features incl. PDF + HTML | normal AGPL release |
| `minimal` | without AGPL / GPL packages | reduced build |

### CPU build (recommended)

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1 -Variant cpu -LicenseProfile full
```

Output:
- `dist_portable\draft2craift-FULL-Portable-CPU.zip`
- `dist_installer\draft2craift-FULL-Setup-CPU.exe` *(if iscc is available)*

### CUDA build

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1 -Variant cuda -LicenseProfile full
```

### Both variants at once

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build_windows_all.ps1 -LicenseProfile full
```

### Linux bundle

```bash
bash packaging/build_linux.sh cpu full
# → dist_portable/draft2craift-FULL-Portable-Linux-CPU.tar.gz
```

> A fresh Windows target system may be missing the
> **Microsoft Visual C++ Redistributable 2015–2022 (x64)**.

---

## 16. License

Copyright (C) 2026 Jonas Annuscheit

This project is licensed under the **GNU Affero General Public License v3.0 (AGPL-3.0)**.
See [LICENSE](LICENSE) for the full license text.

The licenses of all bundled third-party libraries are documented in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
