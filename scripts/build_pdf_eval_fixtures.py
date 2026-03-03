#!/usr/bin/env python3
"""
Build fixed PDF fixtures + expected markdown files for pdf_eval.

This script generates deterministic test PDFs used by:
  scripts/examples/pdf_suite.example.json
"""
from __future__ import annotations

import argparse
import json
import pathlib
from typing import Any

import fitz  # type: ignore


_THIS_FILE = pathlib.Path(__file__).resolve()
_PROJECT_ROOT = _THIS_FILE.parents[1]
_FIXTURE_DIR = _PROJECT_ROOT / "scripts" / "examples" / "fixtures" / "pdf_eval"
_SUITE_PATH = _PROJECT_ROOT / "scripts" / "examples" / "pdf_suite.example.json"


def _case_definitions() -> list[dict[str, Any]]:
    return [
        {
            "id": "wrapped_paragraph",
            "labels": ["smoke", "reflow", "paragraphs"],
            "pdf_file": "01_wrapped_paragraph.pdf",
            "expected_file": "01_wrapped_paragraph.expected.md",
            "pages": [
                [
                    {"x": 72, "y": 72, "size": 20, "text": "Projektstart"},
                    {
                        "x": 72,
                        "y": 110,
                        "size": 12,
                        "text": "Dies ist eine Zeile mit Umbruch",
                    },
                    {
                        "x": 72,
                        "y": 126,
                        "size": 12,
                        "text": "die im Ergebnis zu einem Absatz",
                    },
                    {
                        "x": 72,
                        "y": 142,
                        "size": 12,
                        "text": "zusammengeführt werden sollte.",
                    },
                    {
                        "x": 72,
                        "y": 180,
                        "size": 12,
                        "text": "Nächster Absatz bleibt getrennt.",
                    },
                ],
            ],
            "expected_markdown": (
                "# 01_wrapped_paragraph.pdf\n\n"
                "---\n\n"
                "[Seite 1]\n\n"
                "# Projektstart\n\n"
                "Dies ist eine Zeile mit Umbruch die im Ergebnis zu einem Absatz "
                "zusammengeführt werden sollte.\n\n"
                "Nächster Absatz bleibt getrennt.\n"
            ),
        },
        {
            "id": "headings_and_lists",
            "labels": ["smoke", "headings", "lists"],
            "pdf_file": "02_headings_and_lists.pdf",
            "expected_file": "02_headings_and_lists.expected.md",
            "pages": [
                [
                    {"x": 72, "y": 72, "size": 18, "text": "Checkliste"},
                    {"x": 72, "y": 110, "size": 14, "text": "Vorbereitung"},
                    {"x": 72, "y": 136, "size": 12, "text": "- Datei laden"},
                    {
                        "x": 72,
                        "y": 152,
                        "size": 12,
                        "text": "- Einstellungen prüfen",
                    },
                    {"x": 72, "y": 178, "size": 14, "text": "Durchführung"},
                    {"x": 72, "y": 204, "size": 12, "text": "1. Lauf starten"},
                    {
                        "x": 72,
                        "y": 220,
                        "size": 12,
                        "text": "2. Ergebnis sichern",
                    },
                ],
            ],
            "expected_markdown": (
                "# 02_headings_and_lists.pdf\n\n"
                "---\n\n"
                "[Seite 1]\n\n"
                "# Checkliste\n\n"
                "## Vorbereitung\n\n"
                "- Datei laden\n"
                "- Einstellungen prüfen\n"
                "## Durchführung\n\n"
                "1. Lauf starten\n"
                "2. Ergebnis sichern\n"
            ),
        },
        {
            "id": "multi_page_flow",
            "labels": ["smoke", "pages", "reflow"],
            "pdf_file": "03_multi_page_flow.pdf",
            "expected_file": "03_multi_page_flow.expected.md",
            "pages": [
                [
                    {"x": 72, "y": 72, "size": 18, "text": "Mehrseitiger Test"},
                    {"x": 72, "y": 110, "size": 12, "text": "Absatz auf Seite eins."},
                    {
                        "x": 72,
                        "y": 126,
                        "size": 12,
                        "text": "Weitere Zeile für den selben Block.",
                    },
                ],
                [
                    {"x": 72, "y": 72, "size": 14, "text": "Fortsetzung"},
                    {"x": 72, "y": 110, "size": 12, "text": "Absatz auf Seite zwei."},
                    {"x": 72, "y": 140, "size": 12, "text": "- Punkt A"},
                    {"x": 72, "y": 156, "size": 12, "text": "- Punkt B"},
                ],
            ],
            "expected_markdown": (
                "# 03_multi_page_flow.pdf\n\n"
                "---\n\n"
                "[Seite 1]\n\n"
                "# Mehrseitiger Test\n\n"
                "Absatz auf Seite eins. Weitere Zeile für den selben Block.\n\n"
                "[Seite 2]\n\n"
                "## Fortsetzung\n\n"
                "Absatz auf Seite zwei.\n\n"
                "- Punkt A\n"
                "- Punkt B\n"
            ),
        },
    ]


def _write_text(path: pathlib.Path, text: str, *, overwrite: bool):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not overwrite:
        return
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def _write_pdf(path: pathlib.Path, pages: list[list[dict[str, Any]]], *, overwrite: bool):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not overwrite:
        return
    doc = fitz.open()
    for lines in pages:
        page = doc.new_page(width=595, height=842)
        for row in lines:
            page.insert_text(
                (float(row.get("x", 72)), float(row.get("y", 72))),
                str(row.get("text", "")),
                fontsize=float(row.get("size", 12)),
            )
    doc.save(str(path))
    doc.close()


def _build_suite(cases: list[dict[str, Any]]) -> dict[str, Any]:
    out_cases: list[dict[str, Any]] = []
    for case in cases:
        out_cases.append(
            {
                "id": case["id"],
                "labels": case.get("labels", []),
                "pdf": f"fixtures/pdf_eval/{case['pdf_file']}",
                "expected": f"fixtures/pdf_eval/{case['expected_file']}",
            }
        )
    return {
        "defaults": {
            "settings": {
                "show_page_markers": True,
                "para_mode": "smart",
                "heading_mode": "pymupdf4llm",
            },
            "thresholds": {
                "char_ratio": 0.93,
                "line_ratio": 0.92,
                "token_f1": 0.92,
                "paragraph_mean": 0.92,
            },
        },
        "cases": out_cases,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create fixed PDF eval fixtures and suite JSON"
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing fixture files",
    )
    args = parser.parse_args()

    cases = _case_definitions()
    for case in cases:
        pdf_path = _FIXTURE_DIR / case["pdf_file"]
        expected_path = _FIXTURE_DIR / case["expected_file"]
        _write_pdf(pdf_path, case["pages"], overwrite=args.overwrite)
        _write_text(
            expected_path,
            str(case["expected_markdown"]),
            overwrite=args.overwrite,
        )
        print(f"fixture: {pdf_path}")
        print(f"expected: {expected_path}")

    suite = _build_suite(cases)
    _write_text(
        _SUITE_PATH,
        json.dumps(suite, ensure_ascii=False, indent=2) + "\n",
        overwrite=True,
    )
    print(f"suite: {_SUITE_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
