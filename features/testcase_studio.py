"""Testcase Studio: manage feedback and convert it into accepted evaluator testcases.

Pipeline:
Feedback -> Testcase (draft/edit/accept) -> Suite export -> Test runs -> Run comparison.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

# ---------------------------------------------------------------------------
# Constants / style
# ---------------------------------------------------------------------------

_BG = "#1E1E2E"
_SURFACE = "#181825"
_MANTLE = "#313244"
_OVERLAY = "#45475A"
_TEXT = "#CDD6F4"
_MUTED = "#6C7086"
_BLUE = "#89B4FA"
_GREEN = "#A6E3A1"
_RED = "#F38BA8"
_YELLOW = "#F9E2AF"
_PURPLE = "#CBA6F7"

_STYLE = f"""
QDialog, QWidget {{ background: {_BG}; color: {_TEXT}; }}
QGroupBox {{
  background: {_SURFACE}; border: 1px solid {_OVERLAY}; border-radius: 4px;
  margin-top: 8px; padding: 8px;
}}
QGroupBox::title {{
  subcontrol-origin: margin; subcontrol-position: top left;
  color: {_PURPLE}; padding: 0 4px;
}}
QLineEdit, QComboBox, QPlainTextEdit {{
  background: {_MANTLE}; color: {_TEXT}; border: 1px solid {_OVERLAY};
  border-radius: 3px; padding: 4px 6px;
}}
QPushButton {{
  background: {_MANTLE}; color: {_TEXT}; border: 1px solid {_OVERLAY};
  border-radius: 3px; padding: 5px 10px;
}}
QPushButton:hover {{ background: {_OVERLAY}; }}
QPushButton#primary {{ background: #1A3A5C; color: {_BLUE}; border-color: {_BLUE}; font-weight: bold; }}
QPushButton#success {{ background: #1E3A2F; color: {_GREEN}; border-color: {_GREEN}; }}
QPushButton#danger {{ background: #3A1E2A; color: {_RED}; border-color: {_RED}; }}
QTableWidget {{
  background: {_SURFACE}; border: 1px solid {_OVERLAY}; gridline-color: {_MANTLE};
}}
QHeaderView::section {{
  background: {_MANTLE}; color: {_PURPLE}; border: none; border-right: 1px solid {_OVERLAY};
  padding: 4px 6px;
}}
"""

_EVENTS_FILE = "feedback_events.jsonl"
_TESTCASES_FILE = "test_cases.jsonl"
_COUNTER_FILE = "testcase_counter.json"


@dataclass(frozen=True)
class SuiteSpec:
    suite_id: str
    label: str
    description: str
    required_fields: tuple[str, ...]


@dataclass(frozen=True)
class FieldGuide:
    key: str
    label: str
    required: bool
    help_text: str
    example: str
    max_height: int = 62


SUITE_SPECS: tuple[SuiteSpec, ...] = (
    SuiteSpec(
        "rag",
        "RAG",
        "RAG-Fall mit Query, Markdown-Dokumenten und Include/Exclude-Zitaten (Strings).",
        ("query", "documents"),
    ),
    SuiteSpec(
        "pdf",
        "PDF->Markdown",
        "Konvertierungsfall mit PDF-Pfad und erwarteter Markdown-Datei.",
        ("pdf", "expected"),
    ),
    SuiteSpec(
        "glossary",
        "Glossary",
        "Glossarfall mit Markdown (Pfad ODER direkter Inhalt), Target- und Excluded-Terms.",
        ("target_terms",),
    ),
    SuiteSpec(
        "factcheck",
        "Fact-Check",
        "Fact-Check-Fall mit target_markdown, sources, gt_facts, gt_verdicts.",
        ("target_markdown", "sources", "gt_facts_markdown", "gt_verdicts_markdown"),
    ),
    SuiteSpec(
        "judge",
        "Judge",
        "Pairwise Judge-Fall mit prompt plus Gewinner-/Verlierer-Antwort.",
        ("prompt", "answer_winner", "answer_loser"),
    ),
    SuiteSpec(
        "llmcompare",
        "LLM-Compare",
        "Vergleichsfall mit prompt (A/B werden im Lauf erzeugt).",
        ("prompt",),
    ),
)
SUITE_BY_ID = {s.suite_id: s for s in SUITE_SPECS}
SUITE_LABEL_TO_ID = {s.label: s.suite_id for s in SUITE_SPECS}


FIELD_GUIDES: dict[str, list[FieldGuide]] = {
    "rag": [
        FieldGuide(
            key="labels",
            label="Labels",
            required=False,
            help_text="Mehrere erlaubt. Eine Zeile pro Label (alternativ Komma-getrennt).",
            example="rag\nfeedback",
            max_height=70,
        ),
        FieldGuide(
            key="query",
            label="Query",
            required=True,
            help_text="Einzelne Suchanfrage (String).",
            example="Welche Vorteile hat Solarenergie in Staedten?",
        ),
        FieldGuide(
            key="documents",
            label="Markdown-Dokumente",
            required=True,
            help_text=(
                "Mehrere erlaubt. Eine Zeile pro Dokument.\n"
                "Format pro Zeile: '/pfad/doc.md' oder 'Name|/pfad/doc.md' oder "
                "'Name::Direktinhalt'."
            ),
            example=(
                "energie.md|scripts/examples/fixtures/rag_doc_1.md\n"
                "security.md|scripts/examples/fixtures/rag_doc_2.md"
            ),
            max_height=92,
        ),
        FieldGuide(
            key="include_quotes",
            label="Include-Zitate",
            required=False,
            help_text=(
                "Mehrere erlaubt. Eine Zeile pro erwarteter Phrase/Textstelle, die in den "
                "RAG-Excerpts vorkommen soll."
            ),
            example="Solarmodule auf Daechern\nSenkung lokaler Emissionen",
            max_height=82,
        ),
        FieldGuide(
            key="exclude_quotes",
            label="Exclude-Zitate",
            required=False,
            help_text=(
                "Mehrere erlaubt. Eine Zeile pro verbotener Phrase/Textstelle, die in den "
                "RAG-Excerpts NICHT vorkommen soll."
            ),
            example="Kohle ist emissionsfrei\nEs gibt keine Risiken",
            max_height=82,
        ),
        FieldGuide(
            key="top_k",
            label="Top-K",
            required=False,
            help_text="Optional. Zahl als String oder Zahl im JSON.",
            example="3",
        ),
    ],
    "pdf": [
        FieldGuide(
            key="labels",
            label="Labels",
            required=False,
            help_text="Mehrere erlaubt. Eine Zeile pro Label (alternativ Komma-getrennt).",
            example="smoke\nreflow\nparagraphs",
            max_height=72,
        ),
        FieldGuide(
            key="pdf",
            label="PDF-Pfad",
            required=True,
            help_text="Genau ein PDF-Dateipfad.",
            example="scripts/examples/fixtures/pdf_eval/01_wrapped_paragraph.pdf",
        ),
        FieldGuide(
            key="expected",
            label="GT-Markdown-Pfad",
            required=True,
            help_text="Genau eine erwartete Markdown-Datei.",
            example="scripts/examples/fixtures/pdf_eval/01_wrapped_paragraph.expected.md",
        ),
        FieldGuide(
            key="settings",
            label="Settings (JSON)",
            required=False,
            help_text="Optionales JSON-Objekt mit PDFImportSettings-Overrides.",
            example='{"para_mode":"smart","heading_mode":"pymupdf4llm"}',
            max_height=82,
        ),
        FieldGuide(
            key="thresholds",
            label="Thresholds (JSON)",
            required=False,
            help_text="Optionales JSON-Objekt, z.B. token_f1/paragraph_mean.",
            example='{"token_f1":0.92,"paragraph_mean":0.92}',
            max_height=82,
        ),
    ],
    "glossary": [
        FieldGuide(
            key="labels",
            label="Labels",
            required=False,
            help_text="Mehrere erlaubt. Eine Zeile pro Label (alternativ Komma-getrennt).",
            example="glossary\nfeedback",
            max_height=70,
        ),
        FieldGuide(
            key="markdown",
            label="Markdown-Pfad",
            required=False,
            help_text=(
                "Genau ein Dateipfad. Alternative zu 'markdown_text'. "
                "Wenn gesetzt, wird Dateiinhalt gelesen."
            ),
            example="scripts/examples/fixtures/glossary_eval/01_llm_basics.md",
        ),
        FieldGuide(
            key="markdown_text",
            label="Markdown-Inhalt direkt",
            required=False,
            help_text=(
                "Direkter Markdown-Text statt Dateipfad. Alternative zu 'markdown'. "
                "Nur eines von beiden nutzen."
            ),
            example="# LLM\nEin LLM arbeitet mit Tokens und Kontextfenster.",
            max_height=88,
        ),
        FieldGuide(
            key="target_terms",
            label="Target-Terms",
            required=True,
            help_text="Mehrere erlaubt. Eine Zeile pro Soll-Begriff.",
            example="LLM\nToken\nKontextfenster",
            max_height=82,
        ),
        FieldGuide(
            key="excluded_terms",
            label="Excluded-Terms",
            required=False,
            help_text="Mehrere erlaubt. Eine Zeile pro Begriff, der NICHT extrahiert werden darf.",
            example="Halluzination\nPlacebo-Begriff",
            max_height=82,
        ),
        FieldGuide(
            key="max_terms",
            label="max_terms",
            required=False,
            help_text="Optional. Zahl.",
            example="24",
        ),
        FieldGuide(
            key="context_max_chars",
            label="context_max_chars",
            required=False,
            help_text="Optional. Zahl.",
            example="22000",
        ),
        FieldGuide(
            key="threshold_recall",
            label="threshold_recall",
            required=False,
            help_text="Optional. Float zwischen 0 und 1.",
            example="0.67",
        ),
    ],
    "factcheck": [
        FieldGuide(
            key="labels",
            label="Labels",
            required=False,
            help_text="Mehrere erlaubt. Eine Zeile pro Label (alternativ Komma-getrennt).",
            example="smoke\ncity\ncontradiction",
            max_height=72,
        ),
        FieldGuide(
            key="target_markdown",
            label="Target-Markdown-Pfad",
            required=True,
            help_text="Pfad auf den zu pruefenden Zieltext.",
            example="fixtures/factcheck_eval/01_city_target.md",
        ),
        FieldGuide(
            key="sources",
            label="Sources",
            required=True,
            help_text=(
                "Mehrere erlaubt. Eine Zeile pro Quelle.\n"
                "Format pro Zeile: '/pfad/source.md' oder 'Name|/pfad/source.md'."
            ),
            example=(
                "city_report_a|fixtures/factcheck_eval/01_city_source_a.md\n"
                "city_report_b|fixtures/factcheck_eval/01_city_source_b.md"
            ),
            max_height=92,
        ),
        FieldGuide(
            key="gt_facts_markdown",
            label="GT-Facts-Pfad",
            required=True,
            help_text="Pfad zur Ground-Truth-Facts-Datei.",
            example="fixtures/factcheck_eval/01_city.gt_facts.md",
        ),
        FieldGuide(
            key="gt_verdicts_markdown",
            label="GT-Verdicts-Pfad",
            required=True,
            help_text="Pfad zur Ground-Truth-Verdicts-Datei.",
            example="fixtures/factcheck_eval/01_city.gt_verdicts.md",
        ),
        FieldGuide(
            key="mode",
            label="Mode",
            required=False,
            help_text="Optional: all | extract | verify | full",
            example="full",
        ),
        FieldGuide(
            key="threshold_extract_recall",
            label="threshold_extract_recall",
            required=False,
            help_text="Optional. Float 0..1.",
            example="0.67",
        ),
        FieldGuide(
            key="threshold_verify_status",
            label="threshold_verify_status",
            required=False,
            help_text="Optional. Float 0..1.",
            example="0.67",
        ),
        FieldGuide(
            key="threshold_full_f1",
            label="threshold_full_f1",
            required=False,
            help_text="Optional. Float 0..1.",
            example="0.50",
        ),
        FieldGuide(
            key="source_max_chars",
            label="source_max_chars",
            required=False,
            help_text="Optional. Zahl.",
            example="24000",
        ),
        FieldGuide(
            key="target_max_chars",
            label="target_max_chars",
            required=False,
            help_text="Optional. Zahl.",
            example="20000",
        ),
        FieldGuide(
            key="max_verify_facts",
            label="max_verify_facts",
            required=False,
            help_text="Optional. Zahl (0 = alle).",
            example="0",
        ),
    ],
    "judge": [
        FieldGuide(
            key="labels",
            label="Labels",
            required=False,
            help_text="Mehrere erlaubt. Eine Zeile pro Label (alternativ Komma-getrennt).",
            example="smoke\ninstruction_following",
            max_height=70,
        ),
        FieldGuide(
            key="prompt",
            label="Prompt",
            required=True,
            help_text="Genau ein Prompt/Text.",
            example="Nenne genau drei Vorteile von Code Reviews.",
            max_height=74,
        ),
        FieldGuide(
            key="answer_winner",
            label="Answer Winner",
            required=True,
            help_text=(
                "Die bessere/korrekte Referenzantwort. "
                "Wird intern als answer_a + winner=A gespeichert."
            ),
            example="- Fruehes Finden von Fehlern\n- Einheitlicher Stil\n- Wissenstransfer",
            max_height=88,
        ),
        FieldGuide(
            key="answer_loser",
            label="Answer Looser",
            required=True,
            help_text="Die schlechtere/fehlerhafte Vergleichsantwort.",
            example="Code Reviews helfen bei Qualitaet, Teamarbeit und Wartbarkeit.",
            max_height=88,
        ),
        FieldGuide(
            key="prompt_max_chars",
            label="prompt_max_chars",
            required=False,
            help_text=(
                "Maximale Zeichenanzahl fuer den Prompt im Judge-Run. "
                "Laengere Prompts werden abgeschnitten. "
                "Im Runner gilt mindestens 256 Zeichen."
            ),
            example="6000",
        ),
        FieldGuide(
            key="answer_max_chars",
            label="answer_max_chars",
            required=False,
            help_text=(
                "Maximale Zeichenanzahl pro Antwort (Winner/Looser) im Judge-Run. "
                "Laengere Antworten werden abgeschnitten. "
                "Im Runner gilt mindestens 256 Zeichen."
            ),
            example="8000",
        ),
    ],
    "llmcompare": [
        FieldGuide(
            key="labels",
            label="Labels",
            required=False,
            help_text="Mehrere erlaubt. Eine Zeile pro Label (alternativ Komma-getrennt).",
            example="reasoning\nquality",
            max_height=70,
        ),
        FieldGuide(
            key="prompt",
            label="Prompt",
            required=True,
            help_text="Prompt, der gegen A/B-Settings verglichen wird.",
            example="Erklaere in 4 Saetzen den Unterschied zwischen Durchsatz und Latenz.",
            max_height=74,
        ),
        FieldGuide(
            key="prompt_max_chars",
            label="prompt_max_chars",
            required=False,
            help_text=(
                "Maximale Zeichenanzahl fuer den Prompt im LLM-Compare-Run. "
                "Laengere Prompts werden abgeschnitten. "
                "Im Runner gilt mindestens 256 Zeichen."
            ),
            example="6000",
        ),
    ],
}


# ---------------------------------------------------------------------------
# Storage helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            raw = json.loads(text)
        except Exception:
            continue
        if isinstance(raw, dict):
            rows.append(raw)
    return rows


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _events_path(storage_dir: Path) -> Path:
    return storage_dir / _EVENTS_FILE


def _cases_path(storage_dir: Path) -> Path:
    return storage_dir / _TESTCASES_FILE


def _counter_path(storage_dir: Path) -> Path:
    return storage_dir / _COUNTER_FILE


def _read_events(storage_dir: Path) -> list[dict[str, Any]]:
    return _read_jsonl(_events_path(storage_dir))


def _write_events(storage_dir: Path, events: list[dict[str, Any]]) -> None:
    _write_jsonl(_events_path(storage_dir), events)


def _read_cases(storage_dir: Path) -> list[dict[str, Any]]:
    cases = _read_jsonl(_cases_path(storage_dir))
    cases.sort(key=lambda row: int(row.get("case_no", 0) or 0))
    return cases


def _write_cases(storage_dir: Path, cases: list[dict[str, Any]]) -> None:
    ordered = list(cases)
    ordered.sort(key=lambda row: int(row.get("case_no", 0) or 0))
    _write_jsonl(_cases_path(storage_dir), ordered)


def _read_counter(storage_dir: Path) -> dict[str, Any]:
    path = _counter_path(storage_dir)
    raw = _read_json(path)
    next_no = int(raw.get("next_case_no", 1) or 1)
    if next_no < 1:
        next_no = 1
    return {"next_case_no": next_no}


def _reserve_case_no(storage_dir: Path) -> int:
    data = _read_counter(storage_dir)
    no = int(data.get("next_case_no", 1))
    data["next_case_no"] = no + 1
    _write_json(_counter_path(storage_dir), data)
    return no


def _case_id_from_no(case_no: int) -> str:
    return f"tc_{int(case_no):06d}"


# ---------------------------------------------------------------------------
# Feedback -> testcase draft helpers
# ---------------------------------------------------------------------------


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _event_payload(event: dict[str, Any]) -> dict[str, Any]:
    payload = event.get("payload")
    return payload if isinstance(payload, dict) else {}


def _extract_prompt_from_event(event: dict[str, Any]) -> str:
    use_case = _safe_str(event.get("use_case")).lower()
    payload = _event_payload(event)

    if use_case == "rag_search":
        rag = payload.get("rag_search")
        if isinstance(rag, dict):
            return _safe_str(rag.get("query"))
    if use_case == "canvas_edit":
        canvas = payload.get("canvas")
        if isinstance(canvas, dict):
            selected = _safe_str(canvas.get("selected_text"))
            if selected:
                return selected
    user_msg = _safe_str(payload.get("last_user_message"))
    if user_msg:
        return user_msg
    return _safe_str(payload.get("query"))


def _extract_observed_output(event: dict[str, Any]) -> str:
    payload = _event_payload(event)

    assistant = _safe_str(payload.get("last_assistant_message"))
    if assistant:
        return assistant

    fact = payload.get("fact_check")
    if isinstance(fact, dict):
        md = _safe_str(fact.get("markdown"))
        if md:
            return md

    rag = payload.get("rag_search")
    if isinstance(rag, dict):
        try:
            return json.dumps(rag.get("results", []), ensure_ascii=False, indent=2)
        except Exception:
            pass
    return ""


def _extract_inline_docs_from_event(event: dict[str, Any]) -> list[dict[str, str]]:
    payload = _event_payload(event)
    input_ctx = payload.get("input_context")
    if not isinstance(input_ctx, dict):
        return []
    file_contents = input_ctx.get("file_contents")
    if not isinstance(file_contents, list):
        return []

    docs: list[dict[str, str]] = []
    for item in file_contents:
        name = ""
        content = ""
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            name = _safe_str(item[0])
            content = _safe_str(item[1])
        elif isinstance(item, dict):
            name = _safe_str(item.get("name"))
            content = _safe_str(item.get("content"))
        if name and content:
            docs.append({"name": name, "content": content})
    return docs


def _event_labels(event: dict[str, Any], suite_id: str) -> list[str]:
    use_case = _safe_str(event.get("use_case")) or "unknown"
    sentiment = _safe_str(event.get("sentiment")) or "neutral"
    labels = ["feedback", use_case, sentiment, suite_id]
    out: list[str] = []
    seen: set[str] = set()
    for item in labels:
        token = _safe_str(item)
        if not token:
            continue
        key = token.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(token)
    return out


def _build_case_draft_from_event(event: dict[str, Any], suite_id: str) -> dict[str, Any]:
    prompt = _extract_prompt_from_event(event)
    observed = _extract_observed_output(event)
    labels = _event_labels(event, suite_id)
    payload = _event_payload(event)
    use_case = _safe_str(event.get("use_case")).lower()

    if suite_id == "rag":
        documents: list[Any] = []
        docs = _extract_inline_docs_from_event(event)
        if docs:
            documents.extend(docs)
        else:
            input_ctx = payload.get("input_context")
            if isinstance(input_ctx, dict):
                selected = input_ctx.get("selected_file_names")
                if isinstance(selected, list):
                    for item in selected:
                        text = _safe_str(item)
                        if text:
                            documents.append(text)
        if not documents:
            documents = ["TODO: fixtures/rag_doc_1.md"]

        include_quotes: list[str] = []
        rag = payload.get("rag_search")
        if isinstance(rag, dict):
            results = rag.get("results")
            if isinstance(results, list):
                for item in results[:3]:
                    excerpt = ""
                    if isinstance(item, dict):
                        excerpt = _safe_str(item.get("excerpt"))
                    if excerpt:
                        include_quotes.append(_truncate(excerpt, 140))
        include_quotes = [x for x in include_quotes if x]

        draft: dict[str, Any] = {
            "id": "",
            "labels": labels,
            "query": prompt or "TODO: Suchanfrage",
            "documents": documents,
            "include_quotes": include_quotes,
            "exclude_quotes": [],
            "top_k": 3,
        }
        return draft

    if suite_id == "pdf":
        file_path = _safe_str(payload.get("file_path"))
        if not file_path.lower().endswith(".pdf"):
            file_path = "TODO: fixtures/pdf_eval/input.pdf"
        return {
            "id": "",
            "labels": labels,
            "pdf": file_path,
            "expected": "TODO: fixtures/pdf_eval/expected.md",
        }

    if suite_id == "glossary":
        glossary = payload.get("glossary")
        terms: list[str] = []
        if isinstance(glossary, dict):
            entries = glossary.get("entries")
            if isinstance(entries, list):
                for entry in entries:
                    if isinstance(entry, dict):
                        term = _safe_str(entry.get("term"))
                    else:
                        term = _safe_str(entry)
                    if term:
                        terms.append(term)
        markdown_raw = _safe_str(payload.get("file_path"))
        markdown = markdown_raw if markdown_raw.lower().endswith(".md") else ""
        if not terms:
            terms = ["TODO Begriff"]
        draft = {
            "id": "",
            "labels": labels,
            "target_terms": terms,
            "excluded_terms": [],
        }
        if markdown:
            draft["markdown"] = markdown
        else:
            draft["markdown_text"] = "TODO: Markdown-Inhalt direkt einfuegen"
        return draft

    if suite_id == "factcheck":
        return {
            "id": "",
            "labels": labels,
            "mode": "full",
            "target_markdown": "TODO: fixtures/factcheck_eval/target.md",
            "sources": [
                {
                    "name": "source_1.md",
                    "path": "TODO: fixtures/factcheck_eval/source_1.md",
                }
            ],
            "gt_facts_markdown": "TODO: fixtures/factcheck_eval/gt_facts.md",
            "gt_verdicts_markdown": "TODO: fixtures/factcheck_eval/gt_verdicts.md",
        }

    if suite_id == "judge":
        answer_loser = observed or "TODO: beobachtete (schwaechere) Antwort"
        answer_winner = "TODO: bessere Referenzantwort"
        if use_case == "chat_answer" and not observed:
            answer_loser = "TODO: beobachtete Antwort"
        return {
            "id": "",
            "labels": labels,
            "prompt": prompt or "TODO: Prompt",
            "answer_winner": answer_winner,
            "answer_loser": answer_loser,
        }

    if suite_id == "llmcompare":
        return {
            "id": "",
            "labels": labels,
            "prompt": prompt or "TODO: Prompt",
        }

    return {"id": "", "labels": labels}


def _manual_case_template(suite_id: str) -> dict[str, Any]:
    _ = suite_id
    return {"id": "", "labels": []}


def _truncate(text: str, n: int = 96) -> str:
    clean = str(text or "").replace("\n", " ").strip()
    if len(clean) <= n:
        return clean
    return clean[: n - 1] + "..."


def _case_title(case_payload: dict[str, Any]) -> str:
    for key in ("prompt", "query", "target_markdown", "pdf", "markdown", "markdown_text"):
        value = _safe_str(case_payload.get(key))
        if value:
            return _truncate(value, 120)
    return "(ohne Titel)"


def _coerce_int_list(raw: Any) -> list[int]:
    out: list[int] = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        try:
            value = int(item)
        except Exception:
            continue
        if value > 0:
            out.append(value)
    return out


def _coerce_labels(raw: Any) -> list[str]:
    tokens: list[str] = []
    if isinstance(raw, str):
        for line in raw.splitlines():
            for part in line.split(","):
                text = part.strip()
                if text:
                    tokens.append(text)
    elif isinstance(raw, list):
        for item in raw:
            text = str(item or "").strip()
            if text:
                tokens.append(text)

    out: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        key = token.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(token)
    return out


# ---------------------------------------------------------------------------
# Generic widgets
# ---------------------------------------------------------------------------


def _cell(text: str) -> QTableWidgetItem:
    item = QTableWidgetItem(str(text or ""))
    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
    return item


class CaseDraftDialog(QDialog):
    def __init__(
        self,
        *,
        suite_id: str,
        payload: dict[str, Any],
        accepted_default: bool,
        title: str,
        existing_labels: list[str] | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(920, 680)
        self.setStyleSheet(_STYLE)
        self._sync_lock = False
        self._field_editors: dict[str, QPlainTextEdit] = {}
        self._field_guides: dict[str, FieldGuide] = {}
        self._existing_labels = sorted(_coerce_labels(existing_labels or []), key=str.casefold)

        root = QVBoxLayout(self)

        form = QFormLayout()
        self._suite_combo = QComboBox()
        for spec in SUITE_SPECS:
            self._suite_combo.addItem(spec.label, spec.suite_id)
        suite_idx = self._suite_combo.findData(suite_id)
        if suite_idx >= 0:
            self._suite_combo.setCurrentIndex(suite_idx)
        form.addRow("Ziel-Testtyp:", self._suite_combo)

        self._accepted_cb = QCheckBox("Akzeptiert (wird exportiert)")
        self._accepted_cb.setChecked(bool(accepted_default))
        form.addRow("Status:", self._accepted_cb)

        self._hint_lbl = QLabel("")
        self._hint_lbl.setStyleSheet(f"color: {_MUTED};")
        self._hint_lbl.setWordWrap(True)
        form.addRow("Hinweis:", self._hint_lbl)

        self._required_lbl = QLabel("")
        self._required_lbl.setStyleSheet(f"color: {_YELLOW};")
        self._required_lbl.setWordWrap(True)
        form.addRow("Pflichtfelder:", self._required_lbl)

        root.addLayout(form)

        labels_box = QGroupBox("Labels")
        labels_form = QFormLayout(labels_box)

        selector = QWidget()
        sel_row = QHBoxLayout(selector)
        sel_row.setContentsMargins(0, 0, 0, 0)
        self._label_existing_combo = QComboBox()
        self._label_existing_combo.addItem("(bestehendes Label waehlen)", "")
        for label in self._existing_labels:
            self._label_existing_combo.addItem(label, label)
        self._label_add_btn = QPushButton("Hinzufuegen")
        self._label_add_btn.clicked.connect(self._add_label_from_picker)
        sel_row.addWidget(self._label_existing_combo, 1)
        sel_row.addWidget(self._label_add_btn)
        labels_form.addRow("Bisherige Labels:", selector)

        new_row = QWidget()
        nrow = QHBoxLayout(new_row)
        nrow.setContentsMargins(0, 0, 0, 0)
        self._label_new_toggle = QCheckBox("Neues Label")
        self._label_new_toggle.toggled.connect(self._on_label_mode_toggled)
        self._label_new_edit = QLineEdit()
        self._label_new_edit.setPlaceholderText("z.B. regression")
        self._label_new_edit.setEnabled(False)
        self._label_new_edit.returnPressed.connect(self._add_new_label)
        self._label_new_add_btn = QPushButton("Neu hinzufuegen")
        self._label_new_add_btn.clicked.connect(self._add_new_label)
        self._label_new_add_btn.setEnabled(False)
        nrow.addWidget(self._label_new_toggle)
        nrow.addWidget(self._label_new_edit, 1)
        nrow.addWidget(self._label_new_add_btn)
        labels_form.addRow("Neues Label:", new_row)

        selected_row = QWidget()
        srow = QVBoxLayout(selected_row)
        srow.setContentsMargins(0, 0, 0, 0)
        self._labels_list = QListWidget()
        self._labels_list.setMaximumHeight(90)
        self._labels_list.setToolTip(
            "Ausgewaehlte Labels. Entfernen mit Auswahl + 'Entfernen' oder Doppelklick."
        )
        self._labels_list.itemDoubleClicked.connect(lambda _: self._remove_selected_label())
        self._label_remove_btn = QPushButton("Entfernen")
        self._label_remove_btn.clicked.connect(self._remove_selected_label)
        srow.addWidget(self._labels_list)
        srow.addWidget(self._label_remove_btn)
        labels_form.addRow("Ausgewaehlt:", selected_row)

        root.addWidget(labels_box)

        req_box = QGroupBox("Felder direkt bearbeiten (Text -> JSON)")
        self._required_form = QFormLayout(req_box)
        self._required_form.setSpacing(6)
        root.addWidget(req_box)

        self._json_edit = QPlainTextEdit(json.dumps(payload, ensure_ascii=False, indent=2))
        self._json_edit.setStyleSheet(
            f"background: {_SURFACE}; color: {_TEXT}; border: 1px solid {_OVERLAY};"
            "font-family: monospace; font-size: 11px;"
        )
        root.addWidget(self._json_edit, 1)

        row = QHBoxLayout()
        ok_btn = QPushButton("Uebernehmen")
        ok_btn.setObjectName("success")
        ok_btn.clicked.connect(self._accept)
        cancel_btn = QPushButton("Abbrechen")
        cancel_btn.clicked.connect(self.reject)
        row.addWidget(ok_btn)
        row.addWidget(cancel_btn)
        row.addStretch()
        root.addLayout(row)

        self._suite_combo.currentIndexChanged.connect(self._on_suite_changed)
        self._json_edit.textChanged.connect(self._sync_required_from_json)
        self._on_suite_changed()

    def _refresh_hints(self) -> None:
        suite_id = str(self._suite_combo.currentData() or "")
        spec = SUITE_BY_ID.get(suite_id)
        if spec is None:
            self._hint_lbl.setText("")
            self._required_lbl.setText("")
            return
        extra = ""
        if suite_id == "rag":
            extra = (
                "\nWichtig: include_quotes/exclude_quotes sind Zitate (Strings), "
                "keine Dateinamen."
            )
        elif suite_id == "glossary":
            extra = "\nWichtig: genau eines von 'markdown' oder 'markdown_text' setzen."
        elif suite_id == "judge":
            extra = "\nHinweis: answer_winner wird intern als answer_a + winner=A exportiert."
        self._hint_lbl.setText(spec.description + extra)
        self._required_lbl.setText(", ".join(spec.required_fields) if spec.required_fields else "-")

    def _on_suite_changed(self) -> None:
        self._refresh_hints()
        self._rebuild_required_inputs()
        self._sync_required_from_json()

    def _read_json_obj(self) -> dict[str, Any]:
        try:
            parsed = json.loads(self._json_edit.toPlainText().strip() or "{}")
        except Exception:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def _write_json_obj(self, payload: dict[str, Any]) -> None:
        if self._sync_lock:
            return
        self._sync_lock = True
        self._json_edit.setPlainText(json.dumps(payload, ensure_ascii=False, indent=2))
        self._sync_lock = False

    def _on_label_mode_toggled(self, enabled: bool) -> None:
        self._label_new_edit.setEnabled(bool(enabled))
        self._label_new_add_btn.setEnabled(bool(enabled))

    def _labels_from_widget(self) -> list[str]:
        items: list[str] = []
        for i in range(self._labels_list.count()):
            text = _safe_str(self._labels_list.item(i).text())
            if text:
                items.append(text)
        return _coerce_labels(items)

    def _set_labels_widget(self, labels: list[str]) -> None:
        self._labels_list.clear()
        for label in _coerce_labels(labels):
            self._labels_list.addItem(label)

    def _add_label_token(self, token: str) -> None:
        label = _safe_str(token)
        if not label:
            return
        current = self._labels_from_widget()
        if label.casefold() in {x.casefold() for x in current}:
            return
        current.append(label)
        self._set_labels_widget(current)
        self._sync_json_from_required()

    def _add_label_from_picker(self) -> None:
        token = _safe_str(self._label_existing_combo.currentData())
        self._add_label_token(token)

    def _add_new_label(self) -> None:
        if not self._label_new_toggle.isChecked():
            return
        token = _safe_str(self._label_new_edit.text())
        if not token:
            return
        self._add_label_token(token)
        if token.casefold() not in {x.casefold() for x in self._existing_labels}:
            self._existing_labels.append(token)
            self._existing_labels.sort(key=str.casefold)
            self._label_existing_combo.blockSignals(True)
            self._label_existing_combo.clear()
            self._label_existing_combo.addItem("(bestehendes Label waehlen)", "")
            for label in self._existing_labels:
                self._label_existing_combo.addItem(label, label)
            self._label_existing_combo.blockSignals(False)
        self._label_new_edit.clear()

    def _remove_selected_label(self) -> None:
        row = self._labels_list.currentRow()
        if row < 0:
            return
        self._labels_list.takeItem(row)
        self._sync_json_from_required()

    @staticmethod
    def _is_empty_value(value: Any) -> bool:
        if value is None:
            return True
        if isinstance(value, str):
            return not value.strip()
        if isinstance(value, (list, tuple, dict)):
            return len(value) == 0
        return False

    @staticmethod
    def _split_multi_values(raw: str) -> list[str]:
        out: list[str] = []
        for line in raw.splitlines():
            for item in line.split(","):
                token = item.strip()
                if token:
                    out.append(token)
        return out

    @staticmethod
    def _parse_documents_lines(raw: str) -> list[Any]:
        if not raw:
            return []
        docs: list[Any] = []
        for line in raw.splitlines():
            part = line.strip()
            if not part:
                continue
            if part.startswith("{") and part.endswith("}"):
                try:
                    obj = json.loads(part)
                except Exception:
                    obj = None
                if isinstance(obj, dict):
                    docs.append(obj)
                    continue
            if "::" in part:
                name, content = [p.strip() for p in part.split("::", 1)]
                if content:
                    docs.append({"name": name or "inline_doc.md", "content": content})
                continue
            if "|" in part:
                name, path = [p.strip() for p in part.split("|", 1)]
                if path:
                    row: dict[str, Any] = {"path": path}
                    if name:
                        row["name"] = name
                    docs.append(row)
                continue
            docs.append(part)
        return docs

    @staticmethod
    def _parse_sources_lines(raw: str) -> list[dict[str, str]]:
        if not raw:
            return []
        rows: list[dict[str, str]] = []
        for line in raw.splitlines():
            part = line.strip()
            if not part:
                continue
            if "|" in part:
                name, path = [p.strip() for p in part.split("|", 1)]
                if path:
                    rows.append({"name": name or "source", "path": path})
            else:
                rows.append({"name": Path(part).name or "source", "path": part})
        return rows

    @staticmethod
    def _format_documents_value(value: Any) -> str:
        if not isinstance(value, list):
            return ""
        out: list[str] = []
        for item in value:
            if isinstance(item, str):
                text = item.strip()
                if text:
                    out.append(text)
                continue
            if not isinstance(item, dict):
                continue
            name = _safe_str(item.get("name"))
            path = _safe_str(item.get("path"))
            content = _safe_str(item.get("content"))
            if path:
                out.append(f"{name}|{path}" if name else path)
                continue
            if content and "\n" not in content:
                out.append(f"{name or 'inline_doc.md'}::{content}")
                continue
            if content:
                out.append(json.dumps(item, ensure_ascii=False))
        return "\n".join(out)

    @staticmethod
    def _format_sources_value(value: Any) -> str:
        if not isinstance(value, list):
            return ""
        out: list[str] = []
        for item in value:
            if isinstance(item, dict):
                name = _safe_str(item.get("name"))
                path = _safe_str(item.get("path"))
                if path:
                    out.append(f"{name}|{path}" if name else path)
            elif isinstance(item, str):
                text = item.strip()
                if text:
                    out.append(text)
        return "\n".join(out)

    def _parse_field_text(self, key: str, text: str) -> Any:
        raw = str(text or "").strip()
        if not raw:
            if key in {"documents", "sources", "target_terms", "excluded_terms", "include_quotes", "exclude_quotes", "labels"}:
                return []
            if key in {"settings", "thresholds"}:
                return {}
            return ""

        if key in {
            "labels",
            "target_terms",
            "excluded_terms",
            "include_quotes",
            "exclude_quotes",
            "gt_docs",
            "excluded_docs",
            "gt_contains",
            "expected_contains",
        }:
            return self._split_multi_values(raw)

        if key == "documents":
            return self._parse_documents_lines(raw)

        if key == "winner":
            up = raw.upper()
            return up if up in {"A", "B"} else raw

        if key == "sources":
            return self._parse_sources_lines(raw)

        if key in {
            "top_k",
            "max_terms",
            "context_max_chars",
            "prompt_max_chars",
            "answer_max_chars",
            "source_max_chars",
            "target_max_chars",
            "max_verify_facts",
        }:
            try:
                return int(float(raw))
            except Exception:
                return raw

        if key in {
            "threshold_recall",
            "threshold_extract_recall",
            "threshold_verify_status",
            "threshold_full_f1",
        }:
            try:
                return float(raw)
            except Exception:
                return raw

        if key in {"settings", "thresholds"}:
            try:
                parsed = json.loads(raw)
                return parsed if isinstance(parsed, dict) else {}
            except Exception:
                return raw

        if raw.startswith("[") or raw.startswith("{"):
            try:
                return json.loads(raw)
            except Exception:
                pass
        return raw

    def _format_field_value(self, key: str, value: Any) -> str:
        if key == "documents":
            return self._format_documents_value(value)
        if key == "sources":
            return self._format_sources_value(value)
        if isinstance(value, list):
            return "\n".join(str(x) for x in value if str(x).strip())
        if isinstance(value, dict):
            return json.dumps(value, ensure_ascii=False, indent=2)
        return str(value or "")

    def _rebuild_required_inputs(self) -> None:
        while self._required_form.rowCount() > 0:
            self._required_form.removeRow(0)
        self._field_editors.clear()
        self._field_guides.clear()

        suite_id = self.suite_id()
        spec = SUITE_BY_ID.get(suite_id)
        guides = FIELD_GUIDES.get(suite_id, [])

        if not guides and spec is not None:
            guides = [
                FieldGuide(
                    key=key,
                    label=key,
                    required=True,
                    help_text="Pflichtfeld",
                    example="",
                )
                for key in spec.required_fields
            ]

        for guide in guides:
            if guide.key == "labels":
                continue
            edit = QPlainTextEdit()
            edit.setMaximumHeight(int(max(52, guide.max_height)))
            edit.setPlaceholderText(guide.example)
            tooltip = guide.help_text
            if guide.example:
                tooltip += "\n\nBeispiel:\n" + guide.example
            edit.setToolTip(tooltip)
            edit.textChanged.connect(self._sync_json_from_required)
            required_marker = " *" if guide.required else ""
            field_label = QLabel(f"{guide.label}{required_marker}:")
            field_label.setToolTip(tooltip)
            self._required_form.addRow(field_label, edit)
            self._field_editors[guide.key] = edit
            self._field_guides[guide.key] = guide

    def _sync_required_from_json(self) -> None:
        if self._sync_lock:
            return
        payload = self._read_json_obj()
        self._sync_lock = True
        self._set_labels_widget(_coerce_labels(payload.get("labels")))
        for key, edit in self._field_editors.items():
            edit.setPlainText(self._format_field_value(key, payload.get(key)))
        self._sync_lock = False

    def _sync_json_from_required(self) -> None:
        if self._sync_lock:
            return
        payload = self._read_json_obj()
        labels = self._labels_from_widget()
        if labels:
            payload["labels"] = labels
        else:
            payload.pop("labels", None)
        for key, edit in self._field_editors.items():
            value = self._parse_field_text(key, edit.toPlainText())
            guide = self._field_guides.get(key)
            if self._is_empty_value(value):
                if guide and not guide.required:
                    payload.pop(key, None)
                else:
                    payload[key] = value
            else:
                payload[key] = value
        self._write_json_obj(payload)

    def _suite_specific_warnings(self, suite_id: str, payload: dict[str, Any]) -> list[str]:
        warns: list[str] = []
        if suite_id == "glossary":
            has_path = bool(_safe_str(payload.get("markdown")))
            has_text = bool(_safe_str(payload.get("markdown_text")))
            if has_path and has_text:
                warns.append("Sowohl 'markdown' als auch 'markdown_text' gesetzt (nur eins nutzen).")
            if not has_path and not has_text:
                warns.append("Glossary braucht entweder 'markdown' oder 'markdown_text'.")
        if suite_id == "judge":
            winner = _safe_str(payload.get("answer_winner"))
            loser = _safe_str(payload.get("answer_loser"))
            if winner and loser and winner.strip() == loser.strip():
                warns.append("answer_winner und answer_loser sind identisch.")
        if suite_id == "rag":
            docs = payload.get("documents")
            if not isinstance(docs, list) or not docs:
                warns.append("RAG braucht mindestens ein Dokument in 'documents'.")
        return warns

    def _accept(self) -> None:
        try:
            parsed = json.loads(self._json_edit.toPlainText().strip() or "{}")
        except Exception as exc:
            QMessageBox.warning(self, "Ungueltiges JSON", f"JSON konnte nicht geparst werden:\n{exc}")
            return
        if not isinstance(parsed, dict):
            QMessageBox.warning(self, "Ungueltiges JSON", "Testcase muss ein JSON-Objekt sein.")
            return

        suite_id = self.suite_id()
        spec = SUITE_BY_ID.get(suite_id)
        if spec is not None:
            missing: list[str] = []
            for key in spec.required_fields:
                value = parsed.get(key)
                if value is None:
                    missing.append(key)
                    continue
                if isinstance(value, str) and not value.strip():
                    missing.append(key)
                    continue
                if isinstance(value, list) and not value:
                    missing.append(key)
            if missing:
                ans = QMessageBox.question(
                    self,
                    "Pflichtfelder fehlen",
                    "Folgende Pflichtfelder wirken leer/fehlend:\n"
                    + ", ".join(missing)
                    + "\n\nTrotzdem uebernehmen?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if ans != QMessageBox.StandardButton.Yes:
                    return
            warns = self._suite_specific_warnings(suite_id, parsed)
            if warns:
                ans = QMessageBox.question(
                    self,
                    "Validierungs-Hinweise",
                    "\n".join(f"- {w}" for w in warns)
                    + "\n\nTrotzdem uebernehmen?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if ans != QMessageBox.StandardButton.Yes:
                    return
        self.accept()

    def suite_id(self) -> str:
        return str(self._suite_combo.currentData() or "")

    def accepted(self) -> bool:
        return bool(self._accepted_cb.isChecked())

    def payload(self) -> dict[str, Any]:
        try:
            parsed = json.loads(self._json_edit.toPlainText().strip() or "{}")
        except Exception:
            return {}
        return parsed if isinstance(parsed, dict) else {}


# ---------------------------------------------------------------------------
# Main dialog
# ---------------------------------------------------------------------------


class TestcaseStudio(QDialog):
    """Single source of truth for feedback and cross-suite testcases."""

    def __init__(self, storage_dir: str | Path | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Testcase Studio")
        self.resize(1340, 860)
        self.setStyleSheet(_STYLE)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowMaximizeButtonHint)

        sd = Path(storage_dir).expanduser() if storage_dir else Path("runs/feedback")
        if not sd.is_absolute():
            sd = (Path.cwd() / sd).resolve()
        self._storage_dir = sd

        self._events: list[dict[str, Any]] = []
        self._cases: list[dict[str, Any]] = []

        self._selected_event_id = ""
        self._selected_case_no = 0

        self._build_ui()
        self._reload_all()

    # ---- UI build ---------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QWidget()
        header.setFixedHeight(42)
        header.setStyleSheet(f"background: {_SURFACE}; border-bottom: 1px solid {_OVERLAY};")
        hdr = QHBoxLayout(header)
        hdr.setContentsMargins(12, 4, 12, 4)
        title = QLabel("Testcase Studio")
        title.setStyleSheet(f"color: {_PURPLE}; font-weight: bold; font-size: 14px;")
        path = QLabel(str(self._storage_dir))
        path.setStyleSheet(f"color: {_MUTED}; font-size: 11px;")
        reload_btn = QPushButton("Aktualisieren")
        reload_btn.clicked.connect(self._reload_all)
        close_btn = QPushButton("Schliessen")
        close_btn.clicked.connect(self.reject)
        hdr.addWidget(title)
        hdr.addWidget(path)
        hdr.addStretch()
        hdr.addWidget(reload_btn)
        hdr.addWidget(close_btn)
        root.addWidget(header)

        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_feedback_tab(), "Feedback")
        self._tabs.addTab(self._build_cases_tab(), "Testcases")
        root.addWidget(self._tabs, 1)

        status = QWidget()
        status.setFixedHeight(24)
        status.setStyleSheet(f"background: {_SURFACE}; border-top: 1px solid {_OVERLAY};")
        sb = QHBoxLayout(status)
        sb.setContentsMargins(12, 2, 12, 2)
        self._status_lbl = QLabel("Bereit")
        self._status_lbl.setStyleSheet(f"color: {_MUTED}; font-size: 10px;")
        sb.addWidget(self._status_lbl)
        sb.addStretch()
        root.addWidget(status)

    def _build_feedback_tab(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(8)

        flt = QHBoxLayout()
        self._fb_filter_edit = QLineEdit()
        self._fb_filter_edit.setPlaceholderText("Filter: event_id, use_case, note, prompt...")
        self._fb_filter_edit.textChanged.connect(self._refresh_feedback_table)
        self._fb_sent_combo = QComboBox()
        self._fb_sent_combo.addItem("Alle", "all")
        self._fb_sent_combo.addItem("Negativ", "negative")
        self._fb_sent_combo.addItem("Positiv", "positive")
        self._fb_sent_combo.currentIndexChanged.connect(self._refresh_feedback_table)
        flt.addWidget(self._fb_filter_edit, 1)
        flt.addWidget(self._fb_sent_combo)
        lay.addLayout(flt)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # left table
        self._fb_table = QTableWidget(0, 6)
        self._fb_table.setHorizontalHeaderLabels(
            ["Zeit", "Event-ID", "Use-Case", "Sent", "Linked", "Notiz"]
        )
        self._fb_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._fb_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._fb_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._fb_table.verticalHeader().setVisible(False)
        self._fb_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self._fb_table.itemSelectionChanged.connect(self._on_feedback_selected)
        splitter.addWidget(self._fb_table)

        # right details
        detail = QWidget()
        dl = QVBoxLayout(detail)
        dl.setContentsMargins(8, 8, 8, 8)

        self._fb_meta_lbl = QLabel("Kein Feedback ausgewaehlt")
        self._fb_meta_lbl.setStyleSheet(f"color: {_BLUE}; font-weight: bold;")
        dl.addWidget(self._fb_meta_lbl)

        self._fb_prompt_lbl = QLabel("")
        self._fb_prompt_lbl.setWordWrap(True)
        self._fb_prompt_lbl.setStyleSheet(f"color: {_TEXT};")
        dl.addWidget(self._fb_prompt_lbl)

        self._fb_observed_lbl = QLabel("")
        self._fb_observed_lbl.setWordWrap(True)
        self._fb_observed_lbl.setStyleSheet(f"color: {_MUTED};")
        dl.addWidget(self._fb_observed_lbl)

        fields_box = QGroupBox("Wichtige Felder")
        fl = QVBoxLayout(fields_box)
        self._fb_fields_edit = QPlainTextEdit()
        self._fb_fields_edit.setReadOnly(True)
        self._fb_fields_edit.setMaximumHeight(170)
        self._fb_fields_edit.setStyleSheet(
            f"background: {_SURFACE}; color: {_TEXT}; border: 1px solid {_OVERLAY};"
            "font-size: 10px;"
        )
        fl.addWidget(self._fb_fields_edit)
        dl.addWidget(fields_box)

        convert_box = QGroupBox("In Testcase umwandeln")
        cform = QFormLayout(convert_box)
        self._fb_target_suite_combo = QComboBox()
        for spec in SUITE_SPECS:
            self._fb_target_suite_combo.addItem(spec.label, spec.suite_id)
        cform.addRow("Testtyp:", self._fb_target_suite_combo)
        self._fb_hint_lbl = QLabel("")
        self._fb_hint_lbl.setWordWrap(True)
        self._fb_hint_lbl.setStyleSheet(f"color: {_MUTED};")
        cform.addRow("Hinweis:", self._fb_hint_lbl)
        mk_btn = QPushButton("Entwurf erzeugen")
        mk_btn.setObjectName("primary")
        mk_btn.clicked.connect(self._create_case_from_feedback)
        cform.addRow("", mk_btn)
        dl.addWidget(convert_box)

        self._fb_target_suite_combo.currentIndexChanged.connect(self._refresh_feedback_suite_hint)
        self._refresh_feedback_suite_hint()

        link_box = QGroupBox("Verknuepfte Testcases")
        ll = QVBoxLayout(link_box)
        self._fb_linked_cases_edit = QPlainTextEdit()
        self._fb_linked_cases_edit.setReadOnly(True)
        self._fb_linked_cases_edit.setMaximumHeight(90)
        self._fb_linked_cases_edit.setStyleSheet(
            f"background: {_SURFACE}; color: {_MUTED}; border: 1px solid {_OVERLAY};"
        )
        ll.addWidget(self._fb_linked_cases_edit)
        dl.addWidget(link_box)

        payload_box = QGroupBox("Payload JSON")
        pl = QVBoxLayout(payload_box)
        self._fb_payload_edit = QPlainTextEdit()
        self._fb_payload_edit.setReadOnly(True)
        self._fb_payload_edit.setStyleSheet(
            f"background: {_SURFACE}; color: {_TEXT}; border: 1px solid {_OVERLAY};"
            "font-family: monospace; font-size: 10px;"
        )
        pl.addWidget(self._fb_payload_edit)
        dl.addWidget(payload_box, 1)

        row = QHBoxLayout()
        del_btn = QPushButton("Feedback loeschen")
        del_btn.setObjectName("danger")
        del_btn.clicked.connect(self._delete_selected_feedback)
        row.addWidget(del_btn)
        row.addStretch()
        dl.addLayout(row)

        splitter.addWidget(detail)
        splitter.setSizes([720, 620])
        lay.addWidget(splitter, 1)
        return page

    def _build_cases_tab(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(8)

        top = QHBoxLayout()
        self._case_filter_edit = QLineEdit()
        self._case_filter_edit.setPlaceholderText("Filter: case_id, event_id, title...")
        self._case_filter_edit.textChanged.connect(self._refresh_cases_table)
        self._case_suite_combo = QComboBox()
        self._case_suite_combo.addItem("Alle", "all")
        for spec in SUITE_SPECS:
            self._case_suite_combo.addItem(spec.label, spec.suite_id)
        self._case_suite_combo.currentIndexChanged.connect(self._refresh_cases_table)
        self._case_status_combo = QComboBox()
        self._case_status_combo.addItem("Alle", "all")
        self._case_status_combo.addItem("Akzeptiert", "accepted")
        self._case_status_combo.addItem("Entwurf", "draft")
        self._case_status_combo.currentIndexChanged.connect(self._refresh_cases_table)
        top.addWidget(self._case_filter_edit, 1)
        top.addWidget(self._case_suite_combo)
        top.addWidget(self._case_status_combo)
        lay.addLayout(top)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        self._case_table = QTableWidget(0, 8)
        self._case_table.setHorizontalHeaderLabels(
            ["Nr", "Case-ID", "Suite", "Status", "Event", "Updated", "Title", ""]
        )
        self._case_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._case_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._case_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._case_table.verticalHeader().setVisible(False)
        header = self._case_table.horizontalHeader()
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        self._case_table.itemSelectionChanged.connect(self._on_case_selected)
        splitter.addWidget(self._case_table)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(8, 8, 8, 8)

        self._case_meta_lbl = QLabel("Kein Testcase ausgewaehlt")
        self._case_meta_lbl.setStyleSheet(f"color: {_BLUE}; font-weight: bold;")
        rl.addWidget(self._case_meta_lbl)

        self._case_json_preview = QPlainTextEdit()
        self._case_json_preview.setReadOnly(True)
        self._case_json_preview.setStyleSheet(
            f"background: {_SURFACE}; color: {_TEXT}; border: 1px solid {_OVERLAY};"
            "font-family: monospace; font-size: 10px;"
        )
        rl.addWidget(self._case_json_preview, 1)

        act = QHBoxLayout()
        self._new_suite_combo = QComboBox()
        for spec in SUITE_SPECS:
            self._new_suite_combo.addItem(spec.label, spec.suite_id)
        new_btn = QPushButton("Neuer manueller Testcase")
        new_btn.clicked.connect(self._new_manual_case)
        edit_btn = QPushButton("Bearbeiten")
        edit_btn.setObjectName("success")
        edit_btn.clicked.connect(self._edit_selected_case)
        del_btn = QPushButton("Loeschen")
        del_btn.setObjectName("danger")
        del_btn.clicked.connect(self._delete_selected_case)
        act.addWidget(self._new_suite_combo)
        act.addWidget(new_btn)
        act.addWidget(edit_btn)
        act.addWidget(del_btn)
        rl.addLayout(act)

        export_box = QGroupBox("Suite-Export fuer Test Studio")
        ef = QFormLayout(export_box)
        self._export_output_edit = QLineEdit(str(self._storage_dir / "generated"))
        out_row = QHBoxLayout()
        out_row.addWidget(self._export_output_edit, 1)
        out_pick = QPushButton("...")
        out_pick.setFixedWidth(30)
        out_pick.clicked.connect(self._pick_export_dir)
        out_row.addWidget(out_pick)
        out_wrap = QWidget()
        out_wrap.setLayout(out_row)
        ef.addRow("Output:", out_wrap)
        self._export_run_name_edit = QLineEdit()
        self._export_run_name_edit.setPlaceholderText("leer = testcase_YYYYMMDD_HHMMSS")
        ef.addRow("Run-Name:", self._export_run_name_edit)
        self._export_include_drafts_cb = QCheckBox("Entwuerfe auch exportieren")
        self._export_include_drafts_cb.setChecked(False)
        ef.addRow("Modus:", self._export_include_drafts_cb)
        export_btn = QPushButton("Suites schreiben")
        export_btn.setObjectName("primary")
        export_btn.clicked.connect(self._export_suites)
        ef.addRow("", export_btn)
        rl.addWidget(export_box)

        self._export_log = QPlainTextEdit()
        self._export_log.setReadOnly(True)
        self._export_log.setMaximumHeight(130)
        self._export_log.setStyleSheet(
            f"background: {_SURFACE}; color: {_MUTED}; border: 1px solid {_OVERLAY};"
            "font-family: monospace; font-size: 10px;"
        )
        rl.addWidget(self._export_log)

        splitter.addWidget(right)
        splitter.setSizes([760, 580])
        lay.addWidget(splitter, 1)

        return page

    # ---- loading / refresh ------------------------------------------------

    def _reload_all(self) -> None:
        self._events = _read_events(self._storage_dir)
        self._cases = _read_cases(self._storage_dir)
        self._refresh_feedback_table()
        self._refresh_cases_table()
        self._status(f"Geladen: {len(self._events)} Feedback-Events, {len(self._cases)} Testcases")

    def _status(self, text: str) -> None:
        self._status_lbl.setText(text)

    def _refresh_feedback_suite_hint(self) -> None:
        suite_id = str(self._fb_target_suite_combo.currentData() or "")
        spec = SUITE_BY_ID.get(suite_id)
        self._fb_hint_lbl.setText(spec.description if spec else "")

    def _refresh_feedback_table(self) -> None:
        query = self._fb_filter_edit.text().strip().casefold()
        sent = str(self._fb_sent_combo.currentData() or "all")

        case_index: dict[int, dict[str, Any]] = {
            int(c.get("case_no", 0) or 0): c for c in self._cases
        }

        visible: list[dict[str, Any]] = []
        for event in reversed(self._events):
            event_sent = _safe_str(event.get("sentiment")).lower()
            if sent != "all" and event_sent != sent:
                continue
            if query:
                payload = _event_payload(event)
                hay = " ".join(
                    [
                        _safe_str(event.get("event_id")),
                        _safe_str(event.get("use_case")),
                        _safe_str(event.get("note")),
                        _safe_str(payload.get("last_user_message")),
                        _safe_str((payload.get("rag_search") or {}).get("query")),
                    ]
                ).casefold()
                if query not in hay:
                    continue
            visible.append(event)

        self._fb_table.setRowCount(len(visible))
        for row, event in enumerate(visible):
            event_id = _safe_str(event.get("event_id"))
            linked = event.get("linked_testcases")
            linked_nos = _coerce_int_list(linked)
            linked_nos = [x for x in linked_nos if x > 0]
            linked_titles = []
            for no in linked_nos[:3]:
                ce = case_index.get(no)
                if ce:
                    linked_titles.append(_safe_str(ce.get("case_id")))
            linked_text = str(len(linked_nos))
            if linked_titles:
                linked_text += " (" + ", ".join(linked_titles) + ")"

            note = _truncate(_safe_str(event.get("note")), 80)
            ts = _safe_str(event.get("timestamp"))[:19].replace("T", " ")
            use_case = _safe_str(event.get("use_case"))
            sent_txt = _safe_str(event.get("sentiment"))

            cells = [
                _cell(ts),
                _cell(event_id),
                _cell(use_case),
                _cell(sent_txt),
                _cell(linked_text),
                _cell(note),
            ]
            for col, item in enumerate(cells):
                item.setData(Qt.ItemDataRole.UserRole, event_id)
                if col == 3:
                    if sent_txt == "negative":
                        item.setForeground(QColor(_RED))
                    elif sent_txt == "positive":
                        item.setForeground(QColor(_GREEN))
                self._fb_table.setItem(row, col, item)

        self._fb_table.resizeColumnToContents(0)
        self._fb_table.resizeColumnToContents(1)
        self._fb_table.resizeColumnToContents(2)
        self._fb_table.resizeColumnToContents(3)
        self._fb_table.resizeColumnToContents(4)

        # Keep selection if possible
        if self._selected_event_id:
            for row in range(self._fb_table.rowCount()):
                item = self._fb_table.item(row, 1)
                if item and item.text() == self._selected_event_id:
                    self._fb_table.selectRow(row)
                    break

    def _refresh_cases_table(self) -> None:
        query = self._case_filter_edit.text().strip().casefold()
        suite_filter = str(self._case_suite_combo.currentData() or "all")
        status_filter = str(self._case_status_combo.currentData() or "all")

        visible: list[dict[str, Any]] = []
        for entry in self._cases:
            suite_id = _safe_str(entry.get("suite_type"))
            accepted = bool(entry.get("accepted", False))
            if suite_filter != "all" and suite_id != suite_filter:
                continue
            if status_filter == "accepted" and not accepted:
                continue
            if status_filter == "draft" and accepted:
                continue
            if query:
                hay = " ".join(
                    [
                        _safe_str(entry.get("case_id")),
                        _safe_str(entry.get("source_event_id")),
                        _safe_str(entry.get("title")),
                        _safe_str(entry.get("suite_type")),
                    ]
                ).casefold()
                if query not in hay:
                    continue
            visible.append(entry)

        self._case_table.setRowCount(len(visible))
        for row, entry in enumerate(visible):
            case_no = int(entry.get("case_no", 0) or 0)
            case_id = _safe_str(entry.get("case_id"))
            suite_id = _safe_str(entry.get("suite_type"))
            suite_label = SUITE_BY_ID.get(suite_id).label if suite_id in SUITE_BY_ID else suite_id
            status = "accepted" if bool(entry.get("accepted", False)) else "draft"
            source_event_id = _safe_str(entry.get("source_event_id"))
            updated = _safe_str(entry.get("updated_at"))
            title = _truncate(_safe_str(entry.get("title")), 140)

            cells = [
                _cell(str(case_no)),
                _cell(case_id),
                _cell(suite_label),
                _cell(status),
                _cell(source_event_id),
                _cell(updated),
                _cell(title),
                _cell(""),
            ]
            for col, item in enumerate(cells):
                item.setData(Qt.ItemDataRole.UserRole, case_no)
                if col == 3:
                    item.setForeground(QColor(_GREEN if status == "accepted" else _YELLOW))
                self._case_table.setItem(row, col, item)

        self._case_table.resizeColumnToContents(0)
        self._case_table.resizeColumnToContents(1)
        self._case_table.resizeColumnToContents(2)
        self._case_table.resizeColumnToContents(3)
        self._case_table.resizeColumnToContents(4)
        self._case_table.resizeColumnToContents(5)

        if self._selected_case_no > 0:
            for row in range(self._case_table.rowCount()):
                item = self._case_table.item(row, 0)
                if item and item.text() == str(self._selected_case_no):
                    self._case_table.selectRow(row)
                    break

    # ---- selection handlers ------------------------------------------------

    def _find_event(self, event_id: str) -> dict[str, Any] | None:
        for event in self._events:
            if _safe_str(event.get("event_id")) == event_id:
                return event
        return None

    def _find_case(self, case_no: int) -> dict[str, Any] | None:
        for entry in self._cases:
            if int(entry.get("case_no", 0) or 0) == int(case_no):
                return entry
        return None

    def _known_labels(self) -> list[str]:
        labels: list[str] = []
        for entry in self._cases:
            case = entry.get("case")
            if not isinstance(case, dict):
                continue
            labels.extend(_coerce_labels(case.get("labels")))
        return _coerce_labels(labels)

    def _format_feedback_fields(self, event: dict[str, Any]) -> str:
        payload = _event_payload(event)
        lines: list[str] = []

        def add(label: str, value: Any) -> None:
            text = _safe_str(value)
            if not text:
                return
            lines.append(f"{label}: {text}")

        add("event_id", event.get("event_id"))
        add("use_case", event.get("use_case"))
        add("sentiment", event.get("sentiment"))
        add("source", event.get("source"))
        add("user_id", event.get("user_id"))
        add("note", event.get("note"))
        tags = event.get("error_tags")
        if isinstance(tags, list) and tags:
            add("error_tags", ", ".join(str(x) for x in tags if str(x).strip()))

        add("model", payload.get("model"))
        llm_runtime = payload.get("llm_runtime")
        if isinstance(llm_runtime, dict):
            add("llm.model_path", llm_runtime.get("model_path"))
            add("llm.ctx_size", llm_runtime.get("ctx_size"))
            add("llm.gpu_layers", llm_runtime.get("gpu_layers"))

        rag = payload.get("rag_search")
        if isinstance(rag, dict):
            add("rag.query", rag.get("query"))
            add("rag.result_count", rag.get("result_count"))
            results = rag.get("results")
            if isinstance(results, list):
                names: list[str] = []
                for item in results[:5]:
                    if isinstance(item, dict):
                        name = _safe_str(item.get("name") or item.get("path"))
                        if name:
                            names.append(name)
                if names:
                    add("rag.top_results", " | ".join(names))

        add("file_path", payload.get("file_path"))
        add("file_type", payload.get("file_type"))

        canvas = payload.get("canvas")
        if isinstance(canvas, dict):
            add("canvas.tab_title", canvas.get("tab_title"))
            sel = _safe_str(canvas.get("selected_text"))
            if sel:
                add("canvas.selected_text", _truncate(sel, 140))

        input_ctx = payload.get("input_context")
        if isinstance(input_ctx, dict):
            files = input_ctx.get("selected_file_names")
            if isinstance(files, list) and files:
                add("input.files", ", ".join(str(x) for x in files if str(x).strip()))
            rag_results = input_ctx.get("rag_results")
            if isinstance(rag_results, list):
                add("input.rag_results", len(rag_results))
            file_contents = input_ctx.get("file_contents")
            if isinstance(file_contents, list):
                add("input.file_contents", len(file_contents))

        add("last_user_message", _truncate(_safe_str(payload.get("last_user_message")), 180))
        add("last_assistant_message", _truncate(_safe_str(payload.get("last_assistant_message")), 180))

        return "\n".join(lines) if lines else "(keine strukturierten Felder erkannt)"

    def _on_feedback_selected(self) -> None:
        items = self._fb_table.selectedItems()
        if not items:
            return
        event_id = _safe_str(items[0].data(Qt.ItemDataRole.UserRole))
        event = self._find_event(event_id)
        if event is None:
            return
        self._selected_event_id = event_id

        use_case = _safe_str(event.get("use_case"))
        sentiment = _safe_str(event.get("sentiment"))
        ts = _safe_str(event.get("timestamp"))
        self._fb_meta_lbl.setText(f"{event_id} | {use_case} | {sentiment} | {ts}")

        prompt = _extract_prompt_from_event(event)
        observed = _extract_observed_output(event)
        self._fb_prompt_lbl.setText(f"Prompt: {_truncate(prompt, 220) if prompt else '-'}")
        self._fb_observed_lbl.setText(f"Observed: {_truncate(observed, 220) if observed else '-'}")

        payload = _event_payload(event)
        self._fb_payload_edit.setPlainText(json.dumps(payload, ensure_ascii=False, indent=2))
        self._fb_fields_edit.setPlainText(self._format_feedback_fields(event))

        linked = event.get("linked_testcases")
        linked_nos = _coerce_int_list(linked)
        linked_lines: list[str] = []
        for no in linked_nos:
            entry = self._find_case(no)
            if entry is None:
                linked_lines.append(f"#{no}: (nicht gefunden)")
                continue
            linked_lines.append(
                f"#{no}  {entry.get('case_id', '')}  [{entry.get('suite_type', '')}]  "
                f"{'accepted' if entry.get('accepted') else 'draft'}"
            )
        self._fb_linked_cases_edit.setPlainText("\n".join(linked_lines) if linked_lines else "(keine)")

    def _on_case_selected(self) -> None:
        items = self._case_table.selectedItems()
        if not items:
            return
        case_no = int(items[0].data(Qt.ItemDataRole.UserRole) or 0)
        entry = self._find_case(case_no)
        if entry is None:
            return
        self._selected_case_no = case_no

        self._case_meta_lbl.setText(
            f"#{case_no}  {entry.get('case_id', '')}  [{entry.get('suite_type', '')}]  "
            f"{'accepted' if entry.get('accepted') else 'draft'}"
        )
        self._case_json_preview.setPlainText(json.dumps(entry.get("case", {}), ensure_ascii=False, indent=2))

    # ---- feedback actions --------------------------------------------------

    def _create_case_from_feedback(self) -> None:
        event = self._find_event(self._selected_event_id)
        if event is None:
            QMessageBox.information(self, "Kein Feedback", "Bitte zuerst ein Feedback-Event auswaehlen.")
            return
        suite_id = str(self._fb_target_suite_combo.currentData() or "")
        if suite_id not in SUITE_BY_ID:
            return

        draft = _build_case_draft_from_event(event, suite_id)
        dlg = CaseDraftDialog(
            suite_id=suite_id,
            payload=draft,
            accepted_default=True,
            title=f"Testcase aus Feedback {self._selected_event_id}",
            existing_labels=self._known_labels(),
            parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        final_suite_id = dlg.suite_id()
        payload = dlg.payload()
        accepted = dlg.accepted()

        case_no = _reserve_case_no(self._storage_dir)
        case_id = _case_id_from_no(case_no)
        payload["id"] = case_id

        entry = {
            "case_no": case_no,
            "case_id": case_id,
            "suite_type": final_suite_id,
            "accepted": bool(accepted),
            "source_event_id": self._selected_event_id,
            "source_event_ids": [self._selected_event_id],
            "title": _case_title(payload),
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
            "case": payload,
        }
        self._cases.append(entry)
        _write_cases(self._storage_dir, self._cases)

        # link case number to event
        for row in self._events:
            if _safe_str(row.get("event_id")) != self._selected_event_id:
                continue
            linked = row.get("linked_testcases")
            linked_nos = _coerce_int_list(linked)
            if case_no not in linked_nos:
                linked_nos.append(case_no)
            row["linked_testcases"] = sorted(set(linked_nos))
            break
        _write_events(self._storage_dir, self._events)

        self._refresh_feedback_table()
        self._refresh_cases_table()
        self._selected_case_no = case_no
        self._tabs.setCurrentIndex(1)
        self._status(f"Testcase erstellt: #{case_no} ({case_id})")

    def _delete_selected_feedback(self) -> None:
        event_id = self._selected_event_id
        if not event_id:
            return
        ans = QMessageBox.question(
            self,
            "Feedback loeschen",
            f"Feedback {event_id} wirklich loeschen?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ans != QMessageBox.StandardButton.Yes:
            return

        self._events = [e for e in self._events if _safe_str(e.get("event_id")) != event_id]
        _write_events(self._storage_dir, self._events)
        self._selected_event_id = ""
        self._fb_meta_lbl.setText("Kein Feedback ausgewaehlt")
        self._fb_prompt_lbl.setText("")
        self._fb_observed_lbl.setText("")
        self._fb_payload_edit.clear()
        self._fb_fields_edit.clear()
        self._fb_linked_cases_edit.clear()
        self._refresh_feedback_table()
        self._status(f"Feedback geloescht: {event_id}")

    # ---- testcase actions --------------------------------------------------

    def _open_case_editor(
        self,
        *,
        suite_id: str,
        payload: dict[str, Any],
        accepted: bool,
        title: str,
    ) -> tuple[bool, str, dict[str, Any], bool]:
        dlg = CaseDraftDialog(
            suite_id=suite_id,
            payload=payload,
            accepted_default=accepted,
            title=title,
            existing_labels=self._known_labels(),
            parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return False, suite_id, payload, accepted
        return True, dlg.suite_id(), dlg.payload(), dlg.accepted()

    def _new_manual_case(self) -> None:
        suite_id = str(self._new_suite_combo.currentData() or "rag")
        draft = _manual_case_template(suite_id)

        ok, final_suite_id, payload, accepted = self._open_case_editor(
            suite_id=suite_id,
            payload=draft,
            accepted=False,
            title="Neuer manueller Testcase",
        )
        if not ok:
            return

        case_no = _reserve_case_no(self._storage_dir)
        case_id = _case_id_from_no(case_no)
        payload["id"] = case_id
        entry = {
            "case_no": case_no,
            "case_id": case_id,
            "suite_type": final_suite_id,
            "accepted": bool(accepted),
            "source_event_id": "",
            "source_event_ids": [],
            "title": _case_title(payload),
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
            "case": payload,
        }
        self._cases.append(entry)
        _write_cases(self._storage_dir, self._cases)
        self._selected_case_no = case_no
        self._refresh_cases_table()
        self._status(f"Manueller Testcase erstellt: #{case_no}")

    def _edit_selected_case(self) -> None:
        entry = self._find_case(self._selected_case_no)
        if entry is None:
            QMessageBox.information(self, "Kein Testcase", "Bitte zuerst einen Testcase auswaehlen.")
            return

        ok, final_suite_id, payload, accepted = self._open_case_editor(
            suite_id=_safe_str(entry.get("suite_type")),
            payload=dict(entry.get("case") or {}),
            accepted=bool(entry.get("accepted", False)),
            title=f"Testcase bearbeiten #{entry.get('case_no', 0)}",
        )
        if not ok:
            return

        case_no = int(entry.get("case_no", 0) or 0)
        case_id = _case_id_from_no(case_no)
        payload["id"] = case_id

        entry["suite_type"] = final_suite_id
        entry["accepted"] = bool(accepted)
        entry["title"] = _case_title(payload)
        entry["updated_at"] = _now_iso()
        entry["case"] = payload

        _write_cases(self._storage_dir, self._cases)
        self._refresh_cases_table()
        self._on_case_selected()
        self._status(f"Testcase aktualisiert: #{case_no}")

    def _delete_selected_case(self) -> None:
        case_no = self._selected_case_no
        if case_no <= 0:
            return
        entry = self._find_case(case_no)
        if entry is None:
            return

        ans = QMessageBox.question(
            self,
            "Testcase loeschen",
            f"Testcase #{case_no} ({entry.get('case_id', '')}) wirklich loeschen?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ans != QMessageBox.StandardButton.Yes:
            return

        self._cases = [c for c in self._cases if int(c.get("case_no", 0) or 0) != case_no]
        _write_cases(self._storage_dir, self._cases)

        # remove link references from feedback events
        for event in self._events:
            linked = event.get("linked_testcases")
            if not isinstance(linked, list):
                continue
            cleaned = [x for x in _coerce_int_list(linked) if x != case_no]
            event["linked_testcases"] = cleaned
        _write_events(self._storage_dir, self._events)

        self._selected_case_no = 0
        self._case_meta_lbl.setText("Kein Testcase ausgewaehlt")
        self._case_json_preview.clear()
        self._refresh_feedback_table()
        self._refresh_cases_table()
        self._status(f"Testcase geloescht: #{case_no}")

    # ---- export ------------------------------------------------------------

    def _pick_export_dir(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self,
            "Export-Ordner waehlen",
            self._export_output_edit.text(),
        )
        if folder:
            self._export_output_edit.setText(folder)

    def _export_suites(self) -> None:
        try:
            repo_root = Path(__file__).resolve().parents[1]
            if str(repo_root) not in sys.path:
                sys.path.insert(0, str(repo_root))
            from scripts.feedback_generate_tests import export_from_storage  # type: ignore
        except Exception as exc:
            QMessageBox.warning(self, "Export", f"Exporter konnte nicht geladen werden:\n{exc}")
            return

        run_name = self._export_run_name_edit.text().strip()
        output_dir = Path(self._export_output_edit.text().strip() or str(self._storage_dir / "generated")).expanduser()
        if not output_dir.is_absolute():
            output_dir = (Path.cwd() / output_dir).resolve()

        include_drafts = bool(self._export_include_drafts_cb.isChecked())

        try:
            summary, written = export_from_storage(
                storage_dir=self._storage_dir,
                output_dir=output_dir,
                run_name=run_name,
                include_unaccepted=include_drafts,
            )
        except Exception as exc:
            QMessageBox.warning(self, "Export", f"Export fehlgeschlagen:\n{exc}")
            return

        lines = [
            f"run_name={summary.get('run_name', '')}",
            f"include_unaccepted={summary.get('include_unaccepted', False)}",
            f"exported_cases={summary.get('exported_cases', 0)}",
            "written:",
        ]
        for path in written:
            lines.append(f"  - {path}")
        self._export_log.setPlainText("\n".join(lines))
        self._status("Suite-Export abgeschlossen")


# ---------------------------------------------------------------------------
# Standalone entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Testcase Studio")
    parser.add_argument(
        "--storage-dir",
        default="runs/feedback",
        help="Feedback/Testcase Speicherordner (default: runs/feedback)",
    )
    args = parser.parse_args(argv)

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Testcase Studio")

    dialog = TestcaseStudio(storage_dir=args.storage_dir)
    dialog.setWindowFlags(
        Qt.WindowType.Window
        | Qt.WindowType.WindowMaximizeButtonHint
        | Qt.WindowType.WindowMinimizeButtonHint
        | Qt.WindowType.WindowCloseButtonHint
    )
    dialog.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
