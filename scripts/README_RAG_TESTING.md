# RAG + Fact-Check Test Tools

## 1) Einzelne Test-Suite ausführen

```bash
python scripts/rag_eval.py \
  --suite scripts/examples/rag_suite.example.json \
  --output-dir runs/rag_eval \
  --run-name demo_eval
```

### 1b) Harte Semantik-Suite (nicht-wörtliche Queries)

Die Suite `scripts/examples/rag_suite.semantic_extreme.json` enthält bewusst
schwierige Fälle mit Paraphrasen, impliziten Formulierungen, Negation und
Cross-Domain-Fragen.

```bash
# Baseline ohne LLM-Callbacks (TF-IDF-only, kein literal matching)
python scripts/rag_eval.py \
  --suite scripts/examples/rag_suite.semantic_extreme.json \
  --output-dir runs/rag_eval \
  --run-name semantic_extreme_baseline
```

```bash
# Optional: gleiche Suite mit LLM-basierten RAG-Schritten
python scripts/rag_eval.py \
  --suite scripts/examples/rag_suite.semantic_extreme.json \
  --output-dir runs/rag_eval \
  --run-name semantic_extreme_llm \
  --llm-model /path/to/model.gguf \
  --llm-n-ctx 4096 \
  --llm-gpu-layers 0 \
  --llm-threads 8 \
  --set use_hyde=true \
  --set use_regex_search=true \
  --set literal_use_llm_terms=true \
  --set llm_rerank_enabled=true
```

Für systematische Vergleiche gibt es auch ein Sweep-Grid:

```bash
python scripts/rag_sweep.py \
  --suite scripts/examples/rag_suite.semantic_extreme.json \
  --grid scripts/examples/rag_sweep.semantic_extreme.json \
  --output-dir runs/rag_sweep \
  --run-prefix semantic_extreme_sweep
```

### 1c) GUI-Dashboard für Run-Vergleiche und Label-Analyse

```bash
python scripts/test_studio.py --root runs
```

Das Dashboard kann:
- mehrere `*.summary.json`-Runs vergleichen
- pro Run einzelne Cases inspizieren
- Label-Metriken über ausgewählte Runs aggregieren
- KPI-Karten + interaktive Plots für Macro F1, Hit@K, MAP und Zero-F1-Druck
- Top-/Weak-Label-Ansicht, um schnell zu sehen was stabil funktioniert und was bricht
- Runner-Tab fuer RAG, PDF, Glossary und Fact-Check (inkl. Run-All Queue)

Feedback/Testcase-Verwaltung:
- `python scripts/testcase_studio.py --storage-dir runs/feedback`

Optional mit LLM (für HyDE/literal terms/reranking):

```bash
python scripts/rag_eval.py \
  --suite scripts/examples/rag_suite.example.json \
  --output-dir runs/rag_eval \
  --run-name demo_eval_llm \
  --llm-model /path/to/model.gguf \
  --llm-n-ctx 4096 \
  --llm-gpu-layers 0 \
  --llm-threads 8
```

Erzeugte Artefakte pro Run:
- `*.summary.json` (Gesamtmetriken + Konfiguration + `summary.by_label`)
- `*.cases.csv` (Metriken pro Testfall)
- `*.debug.jsonl` (vollständige Debug-Daten pro Testfall)
- `*.log` (Ablauf-/Fehlerlog)

## 1d) Faktencheck-Tests (CLI)

```bash
python scripts/factcheck_eval.py \
  --suite scripts/examples/factcheck_suite.3stage.json \
  --output-dir runs/factcheck_eval \
  --run-name demo_factcheck_3stage \
  --llm-model /path/to/model.gguf \
  --llm-n-ctx 4096 \
  --llm-gpu-layers 0 \
  --llm-threads 8
```

Die 3-Stufen-Suite `scripts/examples/factcheck_suite.3stage.json` enthaelt:
- `stage1_extract_from_generated_text` (`mode=extract`)
- `stage2_verify_gt_facts_against_sources` (`mode=verify`)
- `stage3_full_pipeline_generated_facts_to_verification` (`mode=full`)

Damit werden genau diese Schritte separat abgedeckt:
1. Fakten aus generiertem Zieltext extrahieren und gegen GT-Fakten messen
2. GT-Fakten gegen Quellen verifizieren und Status gegen GT-Verdikte messen
3. End-to-End (Extraktion + Verifikation), wobei mit eigenen extrahierten Fakten weitergerechnet wird

Im GUI-Runner (`python scripts/test_studio.py --root runs`) ist diese Suite
im Fact-Check-Tab als Standard hinterlegt. Fuer den 3-Stufen-Lauf `Mode=all`
lassen, damit die case-spezifischen Modi (`extract`/`verify`/`full`) aktiv sind.

## 2) Parameter-Sweep ausführen

```bash
python scripts/rag_sweep.py \
  --suite scripts/examples/rag_suite.example.json \
  --grid scripts/examples/rag_sweep.example.json \
  --output-dir runs/rag_sweep \
  --run-prefix demo_sweep
```

Optional globale LLM-Defaults (pro Kombination via Grid überschreibbar):

```bash
python scripts/rag_sweep.py \
  --suite scripts/examples/rag_suite.example.json \
  --grid scripts/examples/rag_sweep.example.json \
  --output-dir runs/rag_sweep \
  --run-prefix demo_sweep_llm \
  --llm-model /path/to/model.gguf \
  --llm-n-ctx 4096 \
  --llm-gpu-layers 0 \
  --llm-threads 8
```

Erzeugte Sweep-Artefakte:
- `*.sweep.json` (alle Runs + bestes Ergebnis)
- `*.sweep.csv` (tabellarische Übersicht)
- `*.sweep.log` (Ablauf-/Fehlerlog)
- Zusätzlich pro Kombination die normalen `rag_eval`-Run-Dateien

## Suite-Format (JSON)

Pflicht:
- `cases`: Liste von Testfällen mit `query`

Optional:
- `documents`: globale Markdown-Dateien
- `config`: globale `RAGConfig`-Werte

Je Case:
- `id`: optional
- `query`: Pflicht
- `labels`: optional, String oder Liste von Strings
- `documents`: optional (überschreibt globale Dokumentliste)
- `gt_docs` oder `expected_docs`: erwartete Zieldokumente
- `gt_contains` oder `expected_contains`: erwartete Textfragmente
- `top_k`: optionaler Override

## Sweep-Format (JSON)

- `combination_mode`: `"product"` oder `"zip"`
- `base_config`: fixe `RAGConfig`-Werte für alle Runs
- `parameters`: Parameter-Grid
- `max_runs`: optionales Limit

Hinweis:
- Keys in `parameters`, die `RAGConfig` entsprechen, werden als
  Konfigurations-Overrides verwendet.
- Spezial-Keys für LLM:
  - `llm_model`
  - `llm_n_ctx`
  - `llm_gpu_layers`
  - `llm_threads`
