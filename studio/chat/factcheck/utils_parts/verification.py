"""Verification parsing, table formatting, and response validation helpers."""
from __future__ import annotations

import html
import json
import re

from .source_chunks import source_text_for_label
from .text_ops import (
    clean_factcheck_cell,
    contains_text,
    evidence_in_source_texts,
    is_fact_from_target_text,
    token_overlap,
)

def parse_single_fact_verification(
    response: str,
    fact: str,
    fact_index: int,
    sources: list[tuple[str, str]],
) -> dict[str, str]:
    raw = (response or "").strip()
    data: dict[str, object] = {}
    try:
        value = json.loads(raw)
        if isinstance(value, dict):
            data = value
    except Exception:
        match = re.search(r"\{[\s\S]*\}", raw)
        if match:
            try:
                value = json.loads(match.group(0))
                if isinstance(value, dict):
                    data = value
            except Exception:
                data = {}

    cls_raw = clean_factcheck_cell(
        str(
            data.get("status", "")
            or data.get("decision", "")
            or data.get("label", "")
            or data.get("class", "")
            or ""
        )
    ).casefold()
    if cls_raw in {"belegt", "sinnvoll", "ja", "yes", "supported", "entailment"}:
        status = "belegt"
    elif cls_raw in {"teilweise", "partially", "partial"}:
        status = "teilweise"
    elif cls_raw in {"widerspruch", "contradiction", "conflict", "refuted"}:
        status = "widerspruch"
    else:
        status = "nicht_belegt"

    to_check_raw = clean_factcheck_cell(
        str(data.get("to_check", "") or data.get("fact", "") or "")
    )
    normalized_to_check = clean_factcheck_cell(to_check_raw) if to_check_raw else ""
    if normalized_to_check and token_overlap(normalized_to_check, fact) < 0.35:
        normalized_to_check = ""
    checked_fact = normalized_to_check or fact

    source_raw = data.get("source", data.get("source_name", ""))
    source_labels: list[str] = []
    if isinstance(source_raw, str):
        source_labels = [item.strip() for item in re.split(r"[;,]", source_raw) if item.strip()]
    elif isinstance(source_raw, list):
        source_labels = [str(item).strip() for item in source_raw if str(item).strip()]

    if not source_labels:
        sources_raw = data.get("sources", [])
        if isinstance(sources_raw, list):
            source_labels = [str(item).strip() for item in sources_raw if str(item).strip()]
        elif isinstance(sources_raw, str):
            source_labels = [
                item.strip()
                for item in re.split(r"[;,]", sources_raw)
                if item.strip()
            ]

    matched_labels: list[str] = []
    for label in source_labels:
        text = source_text_for_label(label, sources)
        if text:
            matched_labels.append(label)
    evidence_full = clean_factcheck_cell(
        str(
            data.get("evidence", "")
            or data.get("quote", "")
            or data.get("excerpt", "")
            or ""
        )
    )
    evidence = evidence_full
    reason = clean_factcheck_cell(str(data.get("reason", "") or ""))
    if evidence_full and not matched_labels:
        inferred = [
            name
            for name, text in sources
            if contains_text(text, evidence_full)
        ]
        if inferred:
            matched_labels = [inferred[0]]
    if len(evidence_full) > 260:
        evidence = evidence_full[:260].rstrip() + " …"

    source_texts = [source_text_for_label(label, sources) for label in matched_labels]
    source_texts = [text for text in source_texts if text]
    support = (
        token_overlap(checked_fact, evidence_full)
        if (checked_fact and evidence_full)
        else 0.0
    )

    evidence_found, evidence_source_score = evidence_in_source_texts(
        evidence_full,
        source_texts,
    )
    if evidence_full and not evidence_found:
        status = "nicht_belegt"
        reason = (
            (reason + "; " if reason else "")
            + f"Evidenz nicht direkt in Quelle gefunden (match={evidence_source_score:.2f})"
        )
    elif evidence_full and source_texts:
        if support < 0.16:
            status = "nicht_belegt"
            reason = (reason + "; " if reason else "") + "Evidenz passt inhaltlich nicht zum Fakt"
        elif status == "belegt" and support < 0.28:
            status = "teilweise"
            reason = (reason + "; " if reason else "") + "Evidenz deckt den Fakt nur teilweise"

    if not evidence_full:
        status = "nicht_belegt" if status == "belegt" else status
        evidence = ""

    return {
        "id": f"C{fact_index + 1}",
        "status": status,
        "fact": checked_fact,
        "sources": ", ".join(dict.fromkeys(matched_labels)) if matched_labels else "",
        "evidence": evidence,
        "reason": reason,
    }

def fact_status_icon(status: str) -> str:
    mapping = {
        "belegt": "🟢",
        "teilweise": "🟡",
        "nicht_belegt": "🔴",
        "widerspruch": "🔵",
    }
    key = str(status or "").strip().casefold()
    return mapping.get(key, "⚪")

def md_escape_cell(text: str) -> str:
    # Keep table cells as plain text to avoid markdown constructs
    # (fences, emphasis, links) from breaking table rendering.
    value = clean_factcheck_cell(str(text or ""))
    # Never keep literal table separators inside a cell.
    value = value.replace("|", " / ")
    value = html.escape(value, quote=False)
    value = value.replace("`", "&#96;")
    value = value.replace("*", "&#42;")
    value = value.replace("[", "&#91;")
    value = value.replace("]", "&#93;")
    value = re.sub(r"\s+", " ", value)
    return value.strip()

def compose_fact_check_markdown(
    rows: list[dict[str, str]],
    target_label: str,
    *,
    evidence_header: str = "Evidenz",
    reason_header: str = "",
) -> str:
    if not rows:
        return "## Faktencheck\n\n*Keine überprüfbaren Fakten gefunden.*"

    counts = {
        "belegt": 0,
        "teilweise": 0,
        "nicht_belegt": 0,
        "widerspruch": 0,
    }
    for row in rows:
        status = str(row.get("status", "")).strip().casefold()
        if status in counts:
            counts[status] += 1

    reason_header_clean = md_escape_cell(reason_header) if reason_header else ""
    has_reason_column = bool(reason_header_clean)
    if has_reason_column:
        header_row = (
            f"| ID | Fakt | {md_escape_cell(evidence_header) or 'Evidenz'} | "
            f"Quelle | {reason_header_clean} | Status |"
        )
        sep_row = "|---|---|---|---|---|---|"
    else:
        header_row = (
            f"| ID | Fakt | {md_escape_cell(evidence_header) or 'Evidenz'} | Quelle | Status |"
        )
        sep_row = "|---|---|---|---|---|"

    lines: list[str] = [
        f"## Faktencheck ({target_label or 'Zieltext'})",
        "",
        header_row,
        sep_row,
    ]

    for row in rows:
        status = str(row.get("status", "nicht_belegt")).strip().casefold() or "nicht_belegt"
        icon = fact_status_icon(status)
        row_id = md_escape_cell(row.get("id", ""))
        fact = md_escape_cell(row.get("fact", ""))
        evidence = md_escape_cell(row.get("evidence", ""))
        sources = md_escape_cell(row.get("sources", ""))
        reason = md_escape_cell(row.get("reason", ""))
        status_text = status
        confidence_raw = row.get("confidence", "")
        confidence_text = ""
        if confidence_raw not in ("", None):
            try:
                conf = float(confidence_raw)
                conf = max(0.0, min(1.0, conf))
                confidence_text = f" ({conf:.2f})"
            except Exception:
                conf_txt = str(confidence_raw).strip()
                if conf_txt:
                    confidence_text = f" ({conf_txt})"
        status_cell = md_escape_cell(status_text + confidence_text)
        if has_reason_column:
            lines.append(
                f"| {row_id} | {fact} | {evidence} | {sources} | {reason} | {icon} {status_cell} |"
            )
        else:
            lines.append(
                f"| {row_id} | {fact} | {evidence} | {sources} | {icon} {status_cell} |"
            )

    lines.extend(
        [
            "",
            "## Zusammenfassung",
            f"- 🟢 belegt: {counts['belegt']}",
            f"- 🟡 teilweise: {counts['teilweise']}",
            f"- 🔴 nicht_belegt: {counts['nicht_belegt']}",
            f"- 🔵 widerspruch: {counts['widerspruch']}",
        ]
    )
    return "\n".join(lines)

def parse_factcheck_rows(response: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    col_map = {
        "id": 0,
        "status": 1,
        "fact": 2,
        "sources": 3,
        "evidence": 4,
    }
    for line in (response or "").splitlines():
        stripped = line.strip()
        if not (stripped.startswith("|") and stripped.endswith("|")):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) < 5:
            continue
        if all(re.fullmatch(r":?-{2,}:?", cell.replace(" ", "")) for cell in cells[:5]):
            continue

        lower = [cell.casefold() for cell in cells]
        is_header = ("id" in lower[0]) and any(
            any(token in cell for token in ("status", "fakt", "evidenz", "quelle"))
            for cell in lower
        )
        if is_header:
            dynamic: dict[str, int] = {}
            for idx, cell in enumerate(lower):
                token = re.sub(r"[^a-zäöüß]", "", cell)
                if not token:
                    continue
                if token.startswith("id"):
                    dynamic["id"] = idx
                elif token.startswith("status"):
                    dynamic["status"] = idx
                elif token.startswith("fakt") or token.startswith("claim"):
                    dynamic["fact"] = idx
                elif token.startswith("evidenz") or token.startswith("zitat"):
                    dynamic["evidence"] = idx
                elif token.startswith(("quelle", "quellen", "source")):
                    dynamic["sources"] = idx
            if len(dynamic) >= 4:
                col_map.update(dynamic)
            continue

        if max(col_map.values()) >= len(cells):
            continue

        rows.append(
            {
                "id": cells[col_map["id"]].strip(),
                "status": cells[col_map["status"]].strip(),
                "fact": cells[col_map["fact"]].strip(),
                "sources": cells[col_map["sources"]].strip(),
                "evidence": cells[col_map["evidence"]].strip(),
            }
        )
    return rows

def validate_fact_check_response(
    response: str,
    target_text: str,
    sources: list[tuple[str, str]],
) -> str:
    rows = parse_factcheck_rows(response)
    if not rows:
        return (
            "⚠ Faktencheck-Qualitätsprüfung: Keine gültige Faktentabelle erkannt. "
            "Bitte mit strengeren Einstellungen erneut ausführen."
        )

    issues: list[str] = []
    for row in rows:
        row_id = row.get("id", "").strip() or "?"
        fact = clean_factcheck_cell(row.get("fact", ""))
        evidence = clean_factcheck_cell(row.get("evidence", ""))
        source_cell = clean_factcheck_cell(row.get("sources", ""))
        source_labels = [item.strip() for item in re.split(r"[;,]", source_cell) if item.strip()]

        fact_in_target = is_fact_from_target_text(fact, target_text) if fact else False
        source_texts = [source_text_for_label(label, sources) for label in source_labels]
        source_texts = [text for text in source_texts if text]
        if not source_texts:
            source_texts = [text for _name, text in sources]

        evidence_in_source = (
            any(contains_text(src, evidence) for src in source_texts) if evidence else False
        )
        support = token_overlap(fact, evidence) if (fact and evidence) else 0.0

        reasons: list[str] = []
        if not fact_in_target:
            reasons.append("Fakt nicht im Zieltext")
        if not evidence_in_source:
            reasons.append("Evidenz nicht in Quellen")
        if evidence_in_source and fact_in_target and support < 0.22:
            reasons.append("Evidenz passt schwach zum Fakt")
        if reasons:
            issues.append(f"{row_id}: {', '.join(reasons)}")

    if not issues:
        return ""

    bad = len(issues)
    total = len(rows)
    preview = "\n".join(f"- {line}" for line in issues[:8])
    more = f"\n- … {bad - 8} weitere" if bad > 8 else ""
    return (
        f"⚠ Faktencheck-Qualitätsprüfung: {bad}/{total} Zeilen wirken nicht belastbar.\n"
        "Auffälligkeiten:\n"
        f"{preview}{more}\n"
        "Empfehlung: Größeres Modell nutzen oder Faktencheck erneut ausführen."
    )

__all__ = [
    "parse_single_fact_verification",
    "fact_status_icon",
    "md_escape_cell",
    "compose_fact_check_markdown",
    "parse_factcheck_rows",
    "validate_fact_check_response",
]
