"""Field parsing/formatting helpers used by CaseDraftDialog."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def is_empty_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, dict)):
        return len(value) == 0
    return False


def split_multi_values(raw: str) -> list[str]:
    out: list[str] = []
    for line in raw.splitlines():
        for item in line.split(","):
            token = item.strip()
            if token:
                out.append(token)
    return out


def parse_documents_lines(raw: str) -> list[Any]:
    if not raw:
        return []
    docs: list[Any] = []
    for line in raw.splitlines():
        part = line.strip()
        if not part:
            continue
        if part.startswith("{") and part.endswith("}"):
            try:
                parsed = json.loads(part)
            except Exception:
                parsed = None
            if isinstance(parsed, dict):
                docs.append(parsed)
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


def parse_sources_lines(raw: str) -> list[dict[str, str]]:
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


def format_documents_value(value: Any) -> str:
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
        name = str(item.get("name", "") or "").strip()
        path = str(item.get("path", "") or "").strip()
        content = str(item.get("content", "") or "").strip()
        if path:
            out.append(f"{name}|{path}" if name else path)
            continue
        if content and "\n" not in content:
            out.append(f"{name or 'inline_doc.md'}::{content}")
            continue
        if content:
            out.append(json.dumps(item, ensure_ascii=False))
    return "\n".join(out)


def format_sources_value(value: Any) -> str:
    if not isinstance(value, list):
        return ""
    out: list[str] = []
    for item in value:
        if isinstance(item, dict):
            name = str(item.get("name", "") or "").strip()
            path = str(item.get("path", "") or "").strip()
            if path:
                out.append(f"{name}|{path}" if name else path)
        elif isinstance(item, str):
            text = item.strip()
            if text:
                out.append(text)
    return "\n".join(out)


def parse_field_text(key: str, text: str) -> Any:
    raw = str(text or "").strip()
    if not raw:
        if key in {
            "documents",
            "sources",
            "target_terms",
            "excluded_terms",
            "include_quotes",
            "exclude_quotes",
            "labels",
        }:
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
        return split_multi_values(raw)

    if key == "documents":
        return parse_documents_lines(raw)
    if key == "sources":
        return parse_sources_lines(raw)
    if key == "winner":
        winner = raw.upper()
        return winner if winner in {"A", "B"} else raw

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


def format_field_value(key: str, value: Any) -> str:
    if key == "documents":
        return format_documents_value(value)
    if key == "sources":
        return format_sources_value(value)
    if isinstance(value, list):
        return "\n".join(str(item) for item in value if str(item).strip())
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, indent=2)
    return str(value or "")
