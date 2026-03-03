"""Fact-check parsing, normalization, and validation helpers."""
from __future__ import annotations

import json
import os
import re


def normalize_match_text(text: str) -> str:
    value = (text or "").casefold()
    value = value.replace("\u00ad", "")
    value = re.sub(r"\s+", " ", value).strip()
    return value


def normalize_match_text_plain(text: str) -> str:
    value = normalize_match_text(text)
    value = re.sub(r"[^\w\s]", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def clean_factcheck_cell(text: str) -> str:
    value = (text or "").strip()
    value = re.sub(r"^`+|`+$", "", value)
    value = value.strip(" \"'„“‚‘’”«»")
    value = re.sub(r"\s+", " ", value).strip()
    return value


def contains_text(haystack: str, needle: str) -> bool:
    hay = normalize_match_text(haystack)
    nee = normalize_match_text(needle)
    if len(nee) >= 6 and nee in hay:
        return True
    hay_plain = normalize_match_text_plain(haystack)
    nee_plain = normalize_match_text_plain(needle)
    return len(nee_plain) >= 6 and nee_plain in hay_plain


def token_overlap(a: str, b: str) -> float:
    left = {word for word in normalize_match_text_plain(a).split() if len(word) >= 4}
    right = {word for word in normalize_match_text_plain(b).split() if len(word) >= 4}
    if not left or not right:
        return 0.0
    return len(left & right) / max(1, min(len(left), len(right)))


def split_sentences_for_facts(text: str) -> list[str]:
    if not text:
        return []

    lines = (text or "").replace("\r", "\n").splitlines()
    blocks: list[str] = []
    current: list[str] = []

    def flush_current():
        if current:
            block = re.sub(r"\s+", " ", " ".join(current)).strip()
            if block:
                blocks.append(block)
            current.clear()

    for raw_line in lines:
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line:
            flush_current()
            continue
        if line.startswith("#") or line.startswith("|"):
            flush_current()
            continue
        if re.match(r"^(?:[-*•]+|\d+[\.\)])\s+\S", line):
            flush_current()
            bullet = re.sub(r"^(?:[-*•]+|\d+[\.\)])\s*", "", line).strip()
            if bullet:
                blocks.append(bullet)
            continue
        current.append(line)
    flush_current()

    out: list[str] = []
    sentence_split = re.compile(r"(?<=[.!?])\s+")
    for block in blocks:
        for part in sentence_split.split(block):
            sentence = part.strip(" \t-")
            if sentence:
                out.append(sentence)
    return out


def suggest_fact_limit(target_text: str) -> int:
    sentences = [
        sentence
        for sentence in split_sentences_for_facts(target_text)
        if len(sentence) >= 12
    ]
    bullet_count = len(
        re.findall(r"(?m)^\s*(?:[-*•]+|\d+[\.\)])\s+\S+", target_text or "")
    )
    base = len(sentences) + bullet_count
    if base <= 0:
        words = len(re.findall(r"\w+", target_text or "", flags=re.UNICODE))
        if words <= 0:
            return 24
        base = max(24, words // 6)
    limit = int(base * 1.15) + 4
    return max(24, min(180, limit))


def is_fact_from_target_text(fact: str, target_text: str) -> bool:
    if not fact or not target_text:
        return False
    if contains_text(target_text, fact):
        return True

    fact_tokens = [
        word for word in normalize_match_text_plain(fact).split()
        if len(word) >= 4
    ]
    if len(fact_tokens) < 2:
        return False

    target_tokens = {
        word for word in normalize_match_text_plain(target_text).split()
        if len(word) >= 4
    }
    if not target_tokens:
        return False

    matched = sum(1 for token in fact_tokens if token in target_tokens)
    ratio = matched / max(1, len(fact_tokens))

    if len(fact_tokens) <= 4:
        return matched >= 2 and ratio >= 0.60
    if matched >= 3 and ratio >= 0.52:
        return True
    if matched >= 5 and ratio >= 0.42:
        return True
    return False


def heuristic_fact_candidates_from_text(text: str) -> list[str]:
    out: list[str] = []
    if not text:
        return out

    seen: set[str] = set()

    def add_candidate(candidate: str):
        clean = clean_factcheck_cell(candidate)
        if len(clean) < 6:
            return
        key = normalize_match_text_plain(clean)
        if len(key) < 5 or key in seen:
            return
        seen.add(key)
        out.append(clean)

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if re.match(r"^(?:[-*•]+|\d+[\.\)])\s+\S", stripped):
            bullet = re.sub(r"^(?:[-*•]+|\d+[\.\)])\s*", "", stripped).strip()
            if bullet:
                add_candidate(bullet)

    for sentence in split_sentences_for_facts(text):
        sent = re.sub(r"\s+", " ", sentence).strip()
        if not sent:
            continue
        if len(sent) <= 220:
            add_candidate(sent)
            continue

        parts = re.split(r"\s*;\s+|\s+(?:und|oder|sowie|wobei)\s+", sent)
        added = False
        for part in parts:
            clean = part.strip(" ,-\t")
            if len(clean) >= 20:
                add_candidate(clean)
                added = True
        if not added:
            add_candidate(sent)

    return out


def parse_fact_candidates(response: str, target_text: str) -> list[str]:
    out: list[str] = []
    raw = (response or "").strip()
    max_facts = suggest_fact_limit(target_text)

    parsed: object = None
    try:
        parsed = json.loads(raw)
    except Exception:
        match = re.search(r"\[[\s\S]*\]", raw)
        if match:
            try:
                parsed = json.loads(match.group(0))
            except Exception:
                parsed = None

    candidates: list[tuple[str, str]] = []
    if isinstance(parsed, list):
        for item in parsed:
            if isinstance(item, str):
                candidates.append(("llm", item))
            elif isinstance(item, dict):
                for key in ("fact", "claim", "text"):
                    value = item.get(key)
                    if isinstance(value, str) and value.strip():
                        candidates.append(("llm", value))
                        break
    elif isinstance(parsed, dict):
        for key in ("facts", "claims", "items", "data"):
            value = parsed.get(key)
            if not isinstance(value, list):
                continue
            for item in value:
                if isinstance(item, str):
                    candidates.append(("llm", item))
                elif isinstance(item, dict):
                    for inner_key in ("fact", "claim", "text"):
                        inner_val = item.get(inner_key)
                        if isinstance(inner_val, str) and inner_val.strip():
                            candidates.append(("llm", inner_val))
                            break
            if candidates:
                break

    if not candidates:
        for line in raw.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            stripped = re.sub(r"^\s*(?:[-*•]+|\d+[\.\)])\s*", "", stripped)
            if stripped:
                candidates.append(("llm_fallback", stripped))

    ordered_candidates: list[tuple[str, str]] = [
        ("heuristic", candidate)
        for candidate in heuristic_fact_candidates_from_text(target_text)
    ] + candidates

    seen: set[str] = set()
    for _origin, candidate in ordered_candidates:
        clean = clean_factcheck_cell(candidate)
        if len(clean) < 6:
            continue
        key = normalize_match_text_plain(clean)
        if len(key) < 5 or key in seen:
            continue
        if not is_fact_from_target_text(clean, target_text):
            continue
        seen.add(key)
        out.append(clean)
        if len(out) >= max_facts:
            break

    return out


def norm_source_name(name: str) -> str:
    value = os.path.basename(str(name or "").strip())
    value = re.sub(r"\s+", " ", value).strip().casefold()
    return value


def source_text_for_label(label: str, sources: list[tuple[str, str]]) -> str:
    want = norm_source_name(label)
    if not want:
        return ""
    for name, text in sources:
        got = norm_source_name(name)
        if not got:
            continue
        if got == want or got in want or want in got:
            return str(text or "")
    return ""


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

    cls_raw = str(data.get("status", "") or "").strip().casefold()
    if cls_raw in {"belegt", "sinnvoll", "ja", "yes", "supported"}:
        status = "belegt"
    elif cls_raw in {"teilweise", "partially", "partial"}:
        status = "teilweise"
    elif cls_raw in {"widerspruch", "contradiction", "conflict"}:
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

    source_raw = data.get("source", "")
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
    if not matched_labels and sources:
        matched_labels = [sources[0][0]]

    evidence = clean_factcheck_cell(str(data.get("evidence", "") or ""))
    reason = clean_factcheck_cell(str(data.get("reason", "") or ""))
    if len(evidence) > 260:
        evidence = evidence[:260].rstrip() + " …"

    source_texts = [source_text_for_label(label, sources) for label in matched_labels]
    source_texts = [text for text in source_texts if text]
    support = token_overlap(checked_fact, evidence) if (checked_fact and evidence) else 0.0

    if evidence and not any(contains_text(src, evidence) for src in source_texts):
        status = "nicht_belegt"
        reason = (reason + "; " if reason else "") + "Evidenz nicht direkt in Quelle gefunden"
    elif evidence and source_texts:
        if support < 0.16:
            status = "nicht_belegt"
            reason = (reason + "; " if reason else "") + "Evidenz passt inhaltlich nicht zum Fakt"
        elif status == "belegt" and support < 0.28:
            status = "teilweise"
            reason = (reason + "; " if reason else "") + "Evidenz deckt den Fakt nur teilweise"

    if not evidence:
        status = "nicht_belegt" if status == "belegt" else status
        evidence = "—"

    return {
        "id": f"C{fact_index + 1}",
        "status": status,
        "fact": checked_fact,
        "sources": ", ".join(dict.fromkeys(matched_labels)) if matched_labels else "—",
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
    value = str(text or "")
    value = value.replace("|", "\\|")
    value = value.replace("\n", " ")
    return value.strip()


def compose_fact_check_markdown(rows: list[dict[str, str]], target_label: str) -> str:
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

    lines: list[str] = [
        f"## Faktencheck ({target_label or 'Zieltext'})",
        "",
        "| ID | Fakt | Evidenz | Quelle | Status |",
        "|---|---|---|---|---|",
    ]

    for row in rows:
        status = str(row.get("status", "nicht_belegt")).strip().casefold() or "nicht_belegt"
        icon = fact_status_icon(status)
        row_id = md_escape_cell(row.get("id", ""))
        fact = md_escape_cell(row.get("fact", ""))
        evidence = md_escape_cell(row.get("evidence", "—"))
        sources = md_escape_cell(row.get("sources", "—"))
        status_cell = md_escape_cell(status)
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
