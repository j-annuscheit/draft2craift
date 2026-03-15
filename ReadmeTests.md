# Test-Dokumentation

Diese Datei beschreibt, wie die Test-Pipelines im Projekt aufgebaut sind und wie neue Test-Cases korrekt erstellt werden.

Stand der Doku: Codebasis vom 2026-03-15.

Fuer den manuellen End-to-End Testworkflow mit Checklisten siehe:
`README_MANUAL_TESTING.md`

## 1.1) Architektur-Guard-Tests (wichtig)

Neben den Eval-Runnern gibt es Tests, die zentrale Architekturregeln absichern:

- `tests/services/test_project_manifest_validation.py`  
  Erzwingt strikte Manifest-Schema-Validierung beim Projekt-Load.
- `tests/services/test_project_path_security.py`  
  Erzwingt Pfad-Sicherheit (kein Traversal, keine Escape-Pfade).
- `tests/studio/test_window_delegation_rule.py`  
  Erzwingt die `window.py`-Delegationsregel (ausser `_init_*` und `closeEvent`).

Schnelllauf fuer diese Guard-Tests:

```bash
PYTHONPATH=. pytest -q \
  tests/services/test_project_manifest_validation.py \
  tests/services/test_project_path_security.py \
  tests/studio/test_window_delegation_rule.py
```

## 1) Testarten im Projekt

Es gibt sieben zentrale Eval-Typen in `eval/`:

| Typ | Script | Ziel | GT (Ground Truth) |
|---|---|---|---|
| RAG Retrieval | `eval/rag_eval.py` | Richtige Dokumente fuer Queries finden | Erwartete Dokumente + optionale erwartete Textfragmente |
| PDF -> Markdown | `eval/pdf_eval.py` | PDF-Konvertierung gegen erwartetes Markdown pruefen | Erwartete Markdown-Datei |
| Glossary | `eval/glossary_eval.py` | Zielbegriffe aus Markdown extrahieren | `target_terms` pro Case |
| MindMap/Graph | `eval/mindmap_eval.py` | Gerenderten MindMap/Graph-View auf Pflicht-/Ausschluss-Strings pruefen | `must_contain` / `must_not_contain` pro Case |
| Fact-Check | `eval/factcheck_eval.py` | Fakten extrahieren und/oder gegen Quellen verifizieren | GT-Fakten + GT-Verdikte |
| LLM-as-a-Judge | `eval/judge_eval.py` | Zwischen zwei Kandidaten die bessere Antwort waehlen | Pro Case korrekter Gewinner (`A` oder `B`) |
| LLM-Compare (Judge) | `eval/llm_compare_eval.py` | Zwei LLM-Settings gegeneinander vergleichen, bewertet durch Judge-LLM | Kein GT pro Case; Ergebnis ist Judge-Praeferenz |

Zusatz:

- `eval/rag_sweep.py` macht Parameter-Sweeps fuer RAG.
- `test_studio/main.py` ist die Test-GUI fuer die bisherigen Kern-Typen.
- `testcase_studio/main.py` verwaltet Feedback -> Testcases (inkl. Accept/Reject).

## 2) Standard-Outputs pro Run

Fast alle Runner schreiben in ihr `--output-dir` diese Dateien:

- `<run_name>.summary.json`: Gesamtmetriken + Konfiguration
- `<run_name>.cases.csv`: Metriken pro Case
- `<run_name>.debug.jsonl`: Debug-Detailzeilen pro Case
- `<run_name>.log`: Ablauf-/Fehlerlog

Optional (je nach Runner):

- `<run_name>.artifacts/`: Pro-Case Rohartefakte (`--write-artifacts`)

## 3) Allgemeine Regeln fuer Suite-Dateien

- Suite-Dateien sind JSON.
- Relative Pfade werden relativ zur Suite-Datei aufgeloest.
- `labels` koennen String oder Liste sein (je nach Runner normalisiert).
- Mit CLI-Filtern koennen Cases ueber Labels und `max-cases` reduziert werden.

## 4) RAG-Tests (`eval/rag_eval.py`)

### 4.1 Input und GT

Input:

- Markdown-Dokumente (`documents` global oder pro Case)
- Query pro Case

GT:

- `gt_docs` (oder Alias `expected_docs`): erwartete Dokumentnamen
- `gt_contains` (oder Alias `expected_contains`): erwartete Textfragmente in Treffern

### 4.2 Suite-Struktur

Beispiel:

```json
{
  "documents": [
    {"name": "rag_doc_1.md", "path": "fixtures/rag_doc_1.md"}
  ],
  "config": {
    "use_tfidf": true,
    "use_st": false,
    "top_k": 3
  },
  "cases": [
    {
      "id": "renewable_001",
      "query": "Welche Vorteile hat Solarenergie in Staedten?",
      "labels": ["energy", "baseline"],
      "gt_docs": ["rag_doc_1.md"],
      "gt_contains": ["Solarmodule auf Daechern"],
      "top_k": 3
    }
  ]
}
```

Wichtige Felder:

- `documents`: global; pro Eintrag String-Pfad oder Objekt `{name,path}`
- `config`: RAGConfig-Overrides
- `cases[].documents`: optional, ueberschreibt globale Dokumente
- `cases[].query`: Pflicht
- `cases[].gt_docs`: fuer Dokument-Ranking-Metriken
- `cases[].gt_contains`: fuer Contains-Recall

### 4.3 Metriken

Pro Case:

- `precision`, `recall`, `f1`
- `hit_at_k`
- `mrr`, `ap`, `ndcg`
- `contains_recall`

Run-Summary:

- `summary.micro.*`
- `summary.macro.*`
- `summary.by_label.*`

### 4.4 CLI-Parameter

| Parameter | Bedeutung |
|---|---|
| `--suite` | Pfad zur RAG-Suite JSON |
| `--output-dir` | Zielordner fuer Run-Dateien |
| `--run-name` | Dateipraefix, sonst Timestamp |
| `--config-json` | JSON-Datei mit RAGConfig-Overrides |
| `--set key=value` | Einzelne RAGConfig-Overrides (repeatable) |
| `--top-k` | Globaler `top_k`-Override |
| `--llm-model` | Optionales GGUF fuer HyDE/literal/reranking |
| `--llm-n-ctx` | LLM Kontextfenster |
| `--llm-gpu-layers` | GPU-Layer fuer llama.cpp |
| `--llm-threads` | CPU Threads (0 = auto) |
| `--log-level` | `DEBUG|INFO|WARNING|ERROR` |

### 4.5 Zulaessige `--set`/`config`-Keys (RAGConfig)

- `use_tfidf`, `use_st`
- `chunk_size`, `chunk_overlap`, `chunking_strategy`
- `include_headings`, `include_filename`
- `use_hyde`, `hyde_min_words`, `hyde_tfidf_mode`, `hyde_st_mode`, `hyde_st_hypotheses`, `hyde_use_doc_context`
- `extended_context`, `extended_context_before`, `extended_context_after`
- `selection_mode`, `top_k`, `score_threshold`
- `use_regex_search`, `regex_max_results`, `literal_use_llm_terms`, `literal_llm_max_terms`
- `llm_rerank_enabled`, `llm_rerank_min_score`, `llm_rerank_max_candidates`
- `st_model_name`, `st_n_threads`

## 5) PDF-Tests (`eval/pdf_eval.py`)

### 5.1 Input und GT

Input:

- PDF-Datei pro Case (`pdf`)

GT:

- Erwartete Markdown-Datei (`expected`)

### 5.2 Suite-Struktur

```json
{
  "defaults": {
    "settings": {
      "show_page_markers": true,
      "para_mode": "smart",
      "heading_mode": "pymupdf4llm"
    },
    "thresholds": {
      "char_ratio": 0.93,
      "line_ratio": 0.92,
      "token_f1": 0.92,
      "paragraph_mean": 0.92
    }
  },
  "cases": [
    {
      "id": "wrapped_paragraph",
      "labels": ["smoke", "reflow"],
      "pdf": "fixtures/pdf_eval/01_wrapped_paragraph.pdf",
      "expected": "fixtures/pdf_eval/01_wrapped_paragraph.expected.md"
    }
  ]
}
```

Felder:

- `defaults.settings`: Default-`PDFImportSettings`
- `defaults.thresholds`: Mindestwerte fuer Pass/Fail
- `cases[].thresholds`: optional pro Case ueberschreiben

### 5.3 Pass/Fail-Logik

Ein Case ist nur `passed=true`, wenn alle 4 Checks den Schwellwert erreichen:

- `char_ratio`
- `line_ratio`
- `token_f1`
- `paragraph_mean`

### 5.4 CLI-Parameter

| Parameter | Bedeutung |
|---|---|
| `--suite` | Pfad zur PDF-Suite |
| `--output-dir` | Zielordner |
| `--run-name` | Dateipraefix |
| `--labels` | Label-Filter (CSV) |
| `--max-cases` | Case-Limit nach Filter |
| `--set key=value` | Override eines `PDFImportSettings`-Felds |
| `--write-artifacts / --no-write-artifacts` | `.artifacts` mit expected/actual/diff |
| `--log-level` | Log-Level |

### 5.5 Moegliche `--set`-Keys (PDFImportSettings)

Wichtige Felder:

- Allgemein: `page_range`, `show_page_markers`
- Bilder/Tabellen: `dpi`, `write_images`, `image_format`, `graphics_limit`, `table_strategy`
- Header/Footer: `auto_hf_detect`, `hf_top_zone`, `hf_bottom_zone`, `hf_min_pages`, `hf_threshold`, `hf_max_pairs`
- Headings: `heading_mode`, `heading_h1_ratio`, `heading_h2_ratio`, `heading_h3_ratio`, `heading_bold_promotes`, `heading_color_promotes`, `heading_max_chars`
- Reflow: `para_mode`, `para_sentence_end`, `para_join_hyphen`, `para_min_fill_ratio`

## 6) Glossary-Tests (`eval/glossary_eval.py`)

### 6.1 Input und GT

Input:

- Markdown pro Case (`markdown`)

GT:

- Zielbegriffe (`target_terms`)

### 6.2 Suite-Struktur

```json
{
  "defaults": {
    "max_terms": 24,
    "context_max_chars": 22000,
    "threshold_recall": 0.67
  },
  "cases": [
    {
      "id": "llm_basics",
      "labels": ["smoke", "llm"],
      "markdown": "fixtures/glossary_eval/01_llm_basics.md",
      "target_terms": ["LLM", "Token", "Kontextfenster"]
    }
  ]
}
```

### 6.3 Matching-Logik

- Begriffe werden normalisiert (casefold, Sonderzeichen reduziert).
- Erwarteter Begriff gilt als gefunden bei exaktem/enthaelt-Match oder hoher Aehnlichkeit.
- Der Schwellwert fuer "gefunden" liegt bei ca. `0.9`.

### 6.4 Pass/Fail-Logik

`passed=true`, wenn:

- `recall >= threshold_recall`
- Glossar-LLM-Aufruf wirklich angewendet wurde (`meta.applied == true`)

### 6.5 CLI-Parameter

| Parameter | Bedeutung |
|---|---|
| `--suite` | Glossary-Suite |
| `--output-dir` | Zielordner |
| `--run-name` | Dateipraefix |
| `--labels` | Label-Filter |
| `--max-cases` | Case-Limit |
| `--llm-model` | GGUF-Modell (Pflicht) |
| `--llm-n-ctx` | LLM Kontext |
| `--llm-gpu-layers` | GPU-Layer |
| `--llm-threads` | Threads |
| `--prompts-json` | Prompt-Overrides |
| `--max-terms` | Override max Begriffe |
| `--context-max-chars` | Override Kontextlaenge |
| `--threshold-recall` | Override Mindest-Recall |
| `--set key=value` | Generischer Override (`max_terms`, `context_max_chars`, `threshold_recall`) |
| `--write-artifacts / --no-write-artifacts` | Pro-Case JSON + Kontextdump |
| `--log-level` | Log-Level |

## 7) Fact-Check-Tests (`eval/factcheck_eval.py`)

### 7.1 Ziel und Modi

`mode` steuert den Testablauf:

- `extract`: Nur Fakt-Extraktion aus Zieltext, Vergleich gegen GT-Fakten
- `verify`: Nur Fakt-Verifikation mit GT-Fakten als Input
- `full`: Extraktion + Verifikation (Pipeline), Verifikation arbeitet auf den extrahierten Fakten
- `all`: Fuehrt alle Metrik-Bloecke aus (je Case kann `mode` ueberschrieben sein)

### 7.2 Input und GT

Input:

- `target_markdown`: Zieltext (oft LLM-generierter Text)
- `sources[]`: Quelltexte zur Verifikation

GT:

- `gt_facts_markdown`: Gold-Faktenliste
- `gt_verdicts_markdown`: Gold-Verdikte pro Fakt (Status + Quelle)

### 7.3 Suite-Struktur

```json
{
  "defaults": {
    "threshold_extract_recall": 0.6,
    "threshold_verify_status": 0.6,
    "threshold_full_f1": 0.45,
    "source_max_chars": 24000,
    "target_max_chars": 20000,
    "max_verify_facts": 0,
    "mode": "all"
  },
  "cases": [
    {
      "id": "stage1_extract_from_generated_text",
      "labels": ["stage1", "extract"],
      "mode": "extract",
      "target_markdown": "fixtures/factcheck_eval/01_city_target.md",
      "sources": [
        {"name": "city_report_a.md", "path": "fixtures/factcheck_eval/01_city_source_a.md"}
      ],
      "gt_facts_markdown": "fixtures/factcheck_eval/01_city.gt_facts.md",
      "gt_verdicts_markdown": "fixtures/factcheck_eval/01_city.gt_verdicts.md"
    }
  ]
}
```

Im Projekt existiert bereits die 3-Stufen-Suite:

- `eval/examples/factcheck_suite.3stage.json`

### 7.4 GT-Formate

`gt_facts_markdown` akzeptiert:

- Markdown-Tabelle mit Fact-Spalte (aus `parse_factcheck_rows`)
- Bullet-/Nummernlisten
- Fallback: Satzsplit aus Fliesstext

`gt_verdicts_markdown` akzeptiert:

- Markdown-Tabelle mit Spalten wie `Status`, `Fakt`, `Quelle`, `Evidenz`
- Alternativ Listenformat wie:
  - `- [belegt] Fakttext | source: quelle.md`

Status-Normalisierung:

- `belegt`, `supported`, `yes`, `ja` -> `belegt`
- `teilweise`, `partial`, `partially` -> `teilweise`
- `widerspruch`, `contradiction`, `conflict` -> `widerspruch`
- sonst -> `nicht_belegt`

### 7.5 Metriken

Extraktion (`extract_*`):

- Vergleich extrahierter Fakten gegen GT-Fakten (aehnlichkeitsbasiertes Matching)
- `extract_precision`, `extract_recall`, `extract_f1`

Verifikation (`verify_*`):

- Statusgenauigkeit gegen GT-Verdikte
- `verify_status_accuracy`, `verify_source_accuracy`

Pipeline (`full_*`):

- Korrekte Status auf vorhergesagten Fakten
- `full_precision`, `full_recall`, `full_f1`

### 7.6 Pass/Fail

Schwellenwerte:

- `threshold_extract_recall`
- `threshold_verify_status`
- `threshold_full_f1`

Finales `passed` haengt vom aktiven Modus ab (`extract`, `verify`, `full`, `all`).

### 7.7 CLI-Parameter

| Parameter | Bedeutung |
|---|---|
| `--suite` | Factcheck-Suite |
| `--output-dir` | Zielordner |
| `--run-name` | Dateipraefix |
| `--labels` | Label-Filter |
| `--max-cases` | Case-Limit |
| `--mode` | `all|extract|verify|full` |
| `--llm-model` | GGUF-Modell (Pflicht) |
| `--llm-n-ctx` | LLM Kontext |
| `--llm-gpu-layers` | GPU-Layer |
| `--llm-threads` | Threads |
| `--prompts-json` | Prompt-Overrides |
| `--extract-max-tokens` | Tokenbudget Fakt-Extraktion |
| `--verify-max-tokens` | Tokenbudget Fakt-Verifikation |
| `--temperature` | Basis-Temperatur |
| `--threshold-extract-recall` | Override Schwellwert Extraktion |
| `--threshold-verify-status` | Override Schwellwert Verifikation |
| `--threshold-full-f1` | Override Schwellwert Pipeline |
| `--source-max-chars` | Quelltext-Kuerzung pro Quelle |
| `--target-max-chars` | Zieltext-Kuerzung |
| `--max-verify-facts` | Limit verifizierter Fakten |
| `--set key=value` | Generischer Override |
| `--write-artifacts / --no-write-artifacts` | Pro-Case Dumps |
| `--log-level` | Log-Level |

## 7a) Judge-Tests (`eval/judge_eval.py`)

### 7a.1 Ziel

- Der Judge bekommt pro Case eine Nutzeraufgabe (`prompt`) und zwei Kandidatenantworten (`answer_a`, `answer_b`).
- Ground Truth ist der korrekte Gewinner (`winner`: `A` oder `B`).
- Das Script misst, ob der Judge den richtigen Gewinner waehlt.

### 7a.2 Suite-Struktur

```json
{
  "defaults": {
    "threshold_accuracy": 0.8,
    "prompt_max_chars": 6000,
    "answer_max_chars": 8000
  },
  "cases": [
    {
      "id": "yes_no_instruction_following",
      "labels": ["smoke"],
      "prompt": "Antworte nur mit 'Ja' oder 'Nein': ...",
      "answer_a": "Ja.",
      "answer_b": "Ausfuehrliche Erklaerung ...",
      "winner": "A"
    }
  ]
}
```

Hinweise:

- `prompt`, `answer_a`, `answer_b` koennen alternativ auch ueber `*_path` aus Dateien geladen werden.
- `winner` akzeptiert `A`/`B` (oder `1`/`2`).

### 7a.3 Metriken

- Pro Case:
  - `correct` (bool)
  - `parsed` (ob Gewinner aus Judge-Output extrahierbar war)
  - `parse_mode` (`json`, `regex`, `unparsed`)
  - `duration_ms`
- Run-weit:
  - `accuracy`
  - `parsed_rate`
  - `avg_confidence` (falls vom Judge geliefert)
  - `passed` anhand `threshold_accuracy`

### 7a.4 CLI-Parameter

| Parameter | Bedeutung |
|---|---|
| `--suite` | Judge-Suite JSON |
| `--output-dir` | Zielordner |
| `--run-name` | Dateipraefix |
| `--labels` | Label-Filter |
| `--max-cases` | Case-Limit |
| `--llm-model` | GGUF-Modell (Pflicht) |
| `--llm-n-ctx` | LLM Kontext |
| `--llm-gpu-layers` | GPU-Layer |
| `--llm-threads` | Threads |
| `--prompts-json` | Optionales Prompt-JSON (fuer `--judge-prompt-key`) |
| `--judge-prompt-key` | Prompt-Key (Default: `judge_pairwise_system`) |
| `--judge-prompt-file` | Optionaler Prompt als Textdatei (ueberschreibt Key-Lookup) |
| `--judge-max-tokens` | Tokenbudget fuer Judge-Ausgabe |
| `--temperature`, `--top-p`, `--repeat-penalty`, `--seed` | Judge-LLM-Einstellungen |
| `--threshold-accuracy` | Mindest-Accuracy fuer `passed=true` |
| `--prompt-max-chars`, `--answer-max-chars` | Textkuerzung |
| `--set key=value` | Generische Overrides |
| `--write-artifacts / --no-write-artifacts` | Pro-Case Prompt/Raw-Output |
| `--log-level` | Log-Level |

## 7b) LLM-Compare-Tests (`eval/llm_compare_eval.py`)

### 7b.1 Ziel

- Pro Case wird dieselbe Aufgabe mit zwei Generator-LLM-Settings beantwortet:
  - Setting A
  - Setting B
- Ein drittes LLM (Judge) vergleicht beide Antworten und waehlt den Gewinner.
- Das Ergebnis ist eine Praeferenzverteilung (A vs B), kein Ground-Truth-Score.

### 7b.2 Suite-Struktur

```json
{
  "defaults": {
    "prompt_max_chars": 6000,
    "threshold_win_gap": 0.05
  },
  "cases": [
    {
      "id": "format_case",
      "labels": ["format"],
      "prompt": "Antworte nur mit Ja oder Nein: ..."
    }
  ]
}
```

Hinweise:

- `prompt` kann alternativ ueber `prompt_path` geladen werden.
- `threshold_win_gap` steuert `passed` auf Run-Ebene.

### 7b.3 Metriken

- Pro Case:
  - `preferred_setting` (`a`, `b` oder leer bei unentschieden/unparsed)
  - `parsed`, `parse_mode`
  - `gen_a_ms`, `gen_b_ms`, `judge_ms`, `total_ms`
- Run-weit:
  - `preference_a_rate`, `preference_b_rate`
  - `parsed_rate`, `undecided_rate`
  - `win_gap` (A-Rate minus B-Rate)
  - `winner` (`A`, `B`, `tie`)

### 7b.4 CLI-Parameter

| Parameter | Bedeutung |
|---|---|
| `--suite` | Compare-Suite JSON |
| `--output-dir` | Zielordner |
| `--run-name` | Dateipraefix |
| `--labels` | Label-Filter |
| `--max-cases` | Case-Limit |
| `--a-llm-model` | GGUF fuer Setting A (Pflicht) |
| `--b-llm-model` | GGUF fuer Setting B (Pflicht) |
| `--judge-llm-model` | GGUF fuer Judge (Pflicht) |
| `--a-llm-*`, `--b-llm-*`, `--judge-llm-*` | n_ctx, gpu_layers, threads |
| `--a-*`, `--b-*` | Generationsparameter je Kandidat (`max_tokens`, `temperature`, `top_p`, `repeat_penalty`, `seed`) |
| `--judge-*` | Judge-Generationsparameter (`max_tokens`, `temperature`, `top_p`, `repeat_penalty`, `seed`) |
| `--prompts-json` | Optionales Prompt-JSON |
| `--candidate-prompt-key` | Key fuer Kandidaten-Systemprompt (Default: `llm_compare_candidate_system`) |
| `--candidate-prompt-file` | Optionaler Kandidatenprompt als Textdatei |
| `--judge-prompt-key` | Key fuer Judge-Systemprompt (Default: `judge_pairwise_system`) |
| `--judge-prompt-file` | Optionaler Judge-Prompt als Textdatei |
| `--swap-order / --no-swap-order` | Antwortreihenfolge fuer Judge alternieren |
| `--threshold-win-gap` | Mindestabstand fuer `passed=true` |
| `--prompt-max-chars` | Prompt-Kuerzung |
| `--set key=value` | Generische Overrides |
| `--write-artifacts / --no-write-artifacts` | Pro-Case Rohartefakte |
| `--log-level` | Log-Level |

## 8) RAG Sweep (`eval/rag_sweep.py`)

Ziel:

- Viele RAG-Konfigurationen automatisch durchlaufen
- Beste Konfiguration ueber Metrikpfad auswaehlen

Input:

- `--suite`: normale RAG-Suite
- `--grid`: Sweep-JSON

Grid-Beispiel:

```json
{
  "combination_mode": "product",
  "max_runs": 24,
  "base_config": {"chunk_size": 450},
  "parameters": {
    "chunking_strategy": ["sliding_window", "section"],
    "top_k": [3, 5],
    "llm_model": ["", "/path/model.gguf"]
  }
}
```

Regeln:

- `combination_mode=product`: kartesisches Produkt
- `combination_mode=zip`: positionsweise kombinieren (Listenlaengen muessen gleich sein)
- LLM-Keys im Grid: `llm_model`, `llm_n_ctx`, `llm_gpu_layers`, `llm_threads`

Outputs:

- `<run_prefix>.sweep.json`
- `<run_prefix>.sweep.csv`
- `<run_prefix>.sweep.log`
- plus einzelne RAG-Runs pro Kombination

## 9) Test-GUI (`test_studio/main.py`)

Start:

```bash
python test_studio/main.py --root runs
```

Funktionen:

- Runs vergleichen (RAG, PDF, Glossary, Fact-Check)
- Einzelne Cases ansehen
- Label-Auswertungen
- Tests im Runner-Tab starten

Runner-Tab:

- Eigene Tabs fuer RAG, PDF, Glossary, Fact-Check, Judge, LLM-Compare
- "Run All-Tests" queued: RAG + PDF + Glossary + Fact-Check + Judge + LLM-Compare
- Glossary, Fact-Check, Judge und LLM-Compare werden in Run-All uebersprungen, wenn noetige LLM-Modelle fehlen

Fact-Check GUI-Default:

- Suite-Default ist `eval/examples/factcheck_suite.3stage.json`

## 10) Neue Test-Cases anlegen (Checkliste)

### 10.1 RAG

1. Neue Markdown-Quellen unter `eval/examples/fixtures/...` ablegen.
2. In der Suite unter `documents` oder case-lokal unter `cases[].documents` referenzieren.
3. Pro Case `query`, `gt_docs` und optional `gt_contains` setzen.
4. Lauf mit kleinem Umfang testen (z.B. ein Label oder ein Case).

### 10.2 PDF

1. PDF-Input und erwartetes Markdown anlegen.
2. Case mit `pdf` und `expected` in Suite eintragen.
3. Falls noetig `thresholds` pro Case anpassen.
4. Diff-Artefakte pruefen (`.artifacts/*.diff.txt`).

### 10.3 Glossary

1. Markdown-Kontextdatei anlegen.
2. `target_terms` sauber und eindeutig definieren.
3. `threshold_recall` passend setzen.
4. Mit starkem Modell gegenpruefen, falls Recall schwankt.

### 10.4 Fact-Check

1. Zieltext (`target_markdown`) anlegen.
2. Quellen (`sources`) anlegen.
3. GT-Fakten (`gt_facts_markdown`) erstellen.
4. GT-Verdikte (`gt_verdicts_markdown`) erstellen.
5. Pro Case `mode` passend setzen (`extract`, `verify`, `full`).

## 11) Typische Fehlerquellen

- Pfade in Suite sind relativ, aber zur falschen Basis gerechnet.
- Labels-Filter passt nicht zu `labels` in Cases.
- LLM-Runner ohne `--llm-model` gestartet (Glossary/Fact-Check).
- Zu aggressive Schwellenwerte fuer kleine/rauschige Datensaetze.
- Bei Fact-Check: GT-Status passt nicht zu normalisiertem Statusschema.

## 12) Quickstart-Befehle

RAG:

```bash
python eval/rag_eval.py \
  --suite eval/examples/rag_suite.example.json \
  --output-dir runs/rag_eval \
  --run-name demo_rag
```

PDF:

```bash
python eval/pdf_eval.py \
  --suite eval/examples/pdf_suite.example.json \
  --output-dir runs/pdf_eval \
  --run-name demo_pdf
```

Glossary:

```bash
python eval/glossary_eval.py \
  --suite eval/examples/glossary_suite.example.json \
  --output-dir runs/glossary_eval \
  --run-name demo_glossary \
  --llm-model /path/to/model.gguf
```

MindMap/Graph:

```bash
python eval/mindmap_eval.py \
  --suite eval/examples/mindmap_suite.example.json \
  --output-dir runs/mindmap_eval \
  --run-name demo_mindmap
```

Fact-Check 3-Stufen:

```bash
python eval/factcheck_eval.py \
  --suite eval/examples/factcheck_suite.3stage.json \
  --output-dir runs/factcheck_eval \
  --run-name demo_factcheck \
  --llm-model /path/to/model.gguf
```

LLM-as-a-Judge:

```bash
python eval/judge_eval.py \
  --suite eval/examples/judge_suite.example.json \
  --output-dir runs/judge_eval \
  --run-name demo_judge \
  --llm-model /path/to/model.gguf
```

LLM-Compare (2 Kandidaten + Judge):

```bash
python eval/llm_compare_eval.py \
  --suite eval/examples/llm_compare_suite.example.json \
  --output-dir runs/llm_compare_eval \
  --run-name demo_compare \
  --a-llm-model /path/to/model_a.gguf \
  --b-llm-model /path/to/model_b.gguf \
  --judge-llm-model /path/to/judge_model.gguf
```
