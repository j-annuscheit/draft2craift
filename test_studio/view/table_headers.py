"""Column configuration for Test Studio tables."""
from __future__ import annotations

from PySide6.QtWidgets import QHeaderView, QTableWidget


def _mode(mode: str) -> str:
    return mode if mode in {"rag", "pdf", "glossary", "factcheck", "judge", "llmcompare"} else "mixed"


def run_headers(mode: str) -> list[str]:
    mapping = {
        "rag": [
            "Type",
            "Run",
            "Timestamp",
            "Cases",
            "Macro F1",
            "Hit@K",
            "MAP",
            "Zero-F1%",
            "Suite",
            "Summary File",
        ],
        "judge": [
            "Type",
            "Run",
            "Timestamp",
            "Cases",
            "Accuracy",
            "Parsed Rate",
            "Avg Conf",
            "Fail%",
            "Suite",
            "Summary File",
        ],
        "llmcompare": [
            "Type",
            "Run",
            "Timestamp",
            "Cases",
            "Pref A",
            "Pref B",
            "Parsed",
            "Fail%",
            "Suite",
            "Summary File",
        ],
        "factcheck": [
            "Type",
            "Run",
            "Timestamp",
            "Cases",
            "Full F1",
            "Extract F1",
            "Verify Acc",
            "Fail%",
            "Suite",
            "Summary File",
        ],
        "pdf": [
            "Type",
            "Run",
            "Timestamp",
            "Cases",
            "Token F1",
            "Paragraph",
            "Line Ratio",
            "Fail%",
            "Suite",
            "Summary File",
        ],
        "glossary": [
            "Type",
            "Run",
            "Timestamp",
            "Cases",
            "Recall",
            "Precision",
            "F1",
            "Fail%",
            "Suite",
            "Summary File",
        ],
        "mixed": [
            "Type",
            "Run",
            "Timestamp",
            "Cases",
            "Primary",
            "Structure",
            "Secondary",
            "Fail%",
            "Suite",
            "Summary File",
        ],
    }
    return mapping[_mode(mode)]


def comparison_headers(mode: str) -> list[str]:
    mapping = {
        "rag": [
            "Type",
            "Run",
            "Cases",
            "Macro F1",
            "Micro F1",
            "Hit@K",
            "MAP",
            "MRR",
            "nDCG",
            "Zero-F1%",
            "Suite",
        ],
        "judge": [
            "Type",
            "Run",
            "Cases",
            "Accuracy",
            "Parsed Rate",
            "Avg Conf",
            "Threshold",
            "Pass",
            "Micro Acc",
            "Fail%",
            "Suite",
        ],
        "llmcompare": [
            "Type",
            "Run",
            "Cases",
            "Pref A",
            "Pref B",
            "Parsed",
            "Avg Conf",
            "Win Gap",
            "Undecided",
            "Fail%",
            "Suite",
        ],
        "factcheck": [
            "Type",
            "Run",
            "Cases",
            "Full F1",
            "Micro F1",
            "Extract F1",
            "Verify Acc",
            "Pass Rate",
            "Full Recall",
            "Fail%",
            "Suite",
        ],
        "pdf": [
            "Type",
            "Run",
            "Cases",
            "Token F1",
            "Paragraph",
            "Line Ratio",
            "Char Ratio",
            "Pass Rate",
            "Token F1 (Micro)",
            "Fail%",
            "Suite",
        ],
        "glossary": [
            "Type",
            "Run",
            "Cases",
            "Recall",
            "Precision",
            "F1",
            "Pass Rate",
            "Hit-All",
            "Micro F1",
            "Fail%",
            "Suite",
        ],
        "mixed": [
            "Type",
            "Run",
            "Cases",
            "Primary",
            "Structure",
            "Secondary",
            "Metric A",
            "Metric B",
            "Metric C",
            "Fail%",
            "Suite",
        ],
    }
    return mapping[_mode(mode)]


def case_headers(mode: str) -> list[str]:
    mapping = {
        "rag": [
            "Case ID",
            "Labels",
            "F1",
            "Precision",
            "Recall",
            "Hit@K",
            "Expected Docs",
            "Predicted Docs",
            "Query",
        ],
        "pdf": [
            "Case ID",
            "Labels",
            "Token F1",
            "Precision",
            "Recall",
            "Paragraph",
            "Expected MD",
            "Observed",
            "PDF Input",
        ],
        "glossary": [
            "Case ID",
            "Labels",
            "Recall",
            "Precision",
            "F1",
            "Hit-All",
            "Target Terms",
            "Observed",
            "Markdown Input",
        ],
        "factcheck": [
            "Case ID",
            "Labels",
            "Full F1",
            "Full Precision",
            "Full Recall",
            "Verify Acc",
            "GT Facts",
            "Observed",
            "Target",
        ],
        "judge": [
            "Case ID",
            "Labels",
            "Correct",
            "Precision",
            "Recall",
            "Parsed",
            "Expected",
            "Predicted",
            "Judge Output",
        ],
        "llmcompare": [
            "Case ID",
            "Labels",
            "Pref A",
            "Pref B",
            "Decided",
            "Parsed",
            "Settings",
            "Decision",
            "Prompt",
        ],
        "mixed": [
            "Case ID",
            "Labels",
            "Primary",
            "Precision",
            "Recall",
            "Structure",
            "Expected",
            "Observed",
            "Input",
        ],
    }
    return mapping[_mode(mode)]


def label_headers(mode: str) -> list[str]:
    mapping = {
        "rag": ["Run", "Label", "Cases", "Macro F1", "Hit@K", "Precision", "Recall", "Failures", "Fail%"],
        "pdf": ["Run", "Label", "Cases", "Token F1", "Paragraph", "Token Precision", "Token Recall", "Failures", "Fail%"],
        "factcheck": ["Run", "Label", "Cases", "Full F1", "Extract F1", "Full Precision", "Full Recall", "Failures", "Fail%"],
        "judge": ["Run", "Label", "Cases", "Accuracy", "Parsed Rate", "Precision", "Recall", "Failures", "Fail%"],
        "llmcompare": ["Run", "Label", "Cases", "Pref A", "Pref B", "Decided", "Parsed", "Failures", "Fail%"],
        "glossary": ["Run", "Label", "Cases", "Recall", "Precision", "F1", "Hit-All", "Failures", "Fail%"],
        "mixed": ["Run", "Label", "Cases", "Primary", "Structure", "Precision", "Recall", "Failures", "Fail%"],
    }
    return mapping[_mode(mode)]


def configure_run_table(table: QTableWidget, mode: str) -> None:
    headers = run_headers(mode)
    table.setColumnCount(len(headers))
    table.setHorizontalHeaderLabels(headers)
    header = table.horizontalHeader()
    for idx in range(len(headers)):
        if idx in {8, 9}:
            header.setSectionResizeMode(idx, QHeaderView.ResizeMode.Stretch)
        else:
            header.setSectionResizeMode(idx, QHeaderView.ResizeMode.ResizeToContents)


def configure_comparison_table(table: QTableWidget, mode: str) -> None:
    headers = comparison_headers(mode)
    table.setColumnCount(len(headers))
    table.setHorizontalHeaderLabels(headers)
    header = table.horizontalHeader()
    for idx in range(len(headers)):
        if idx == 10:
            header.setSectionResizeMode(idx, QHeaderView.ResizeMode.Stretch)
        else:
            header.setSectionResizeMode(idx, QHeaderView.ResizeMode.ResizeToContents)


def configure_case_table(table: QTableWidget, mode: str) -> None:
    headers = case_headers(mode)
    table.setColumnCount(len(headers))
    table.setHorizontalHeaderLabels(headers)
    header = table.horizontalHeader()
    for idx in range(min(6, len(headers))):
        header.setSectionResizeMode(idx, QHeaderView.ResizeMode.ResizeToContents)
    for idx in range(6, len(headers)):
        header.setSectionResizeMode(idx, QHeaderView.ResizeMode.Stretch)


def configure_label_table(table: QTableWidget, mode: str) -> None:
    headers = label_headers(mode)
    table.setColumnCount(len(headers))
    table.setHorizontalHeaderLabels(headers)
    header = table.horizontalHeader()
    for idx in range(len(headers)):
        header.setSectionResizeMode(idx, QHeaderView.ResizeMode.ResizeToContents)
    header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
