"""Fact-check parsing, normalization, and validation helpers."""
from __future__ import annotations

import html
import json
import os
import re


def normalize_match_text(text: str) -> str:
    value = html.unescape(str(text or ""))
    value = re.sub(r"(?is)<\s*/?\s*br\s*/?\s*>", " ", value)
    value = value.casefold()
    value = value.replace("\u00ad", "")
    value = re.sub(r"\s+", " ", value).strip()
    return value


def normalize_match_text_plain(text: str) -> str:
    value = normalize_match_text(text)
    value = re.sub(r"[^\w\s]", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def clean_factcheck_cell(text: str) -> str:
    value = html.unescape(str(text or ""))
    value = re.sub(r"(?is)<\s*/?\s*br\s*/?\s*>", " ", value)
    value = re.sub(r"(?is)<[^>]+>", " ", value)
    value = value.strip()
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


def evidence_in_source_texts(
    evidence: str,
    source_texts: list[str],
) -> tuple[bool, float]:
    snippet = clean_factcheck_cell(evidence)
    if not snippet or not source_texts:
        return False, 0.0

    best_score = 0.0
    for src in source_texts:
        source_text = str(src or "")
        if not source_text:
            continue
        if contains_text(source_text, snippet):
            return True, 1.0
        score = token_overlap(source_text, snippet)
        if score > best_score:
            best_score = score

    fuzzy_threshold = 0.62 if len(snippet) >= 80 else 0.70
    return best_score >= fuzzy_threshold, best_score


def split_sentences_for_facts(text: str) -> list[str]:
    if not text:
        return []

    prepared = html.unescape(str(text or ""))
    prepared = re.sub(r"(?is)<\s*/?\s*br\s*/?\s*>", "\n", prepared)
    lines = prepared.replace("\r", "\n").splitlines()
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


def _line_facts_for_target_text(text: str) -> list[str]:
    """Build robust, order-preserving line-based fact candidates."""
    out: list[str] = []
    if not text:
        return out

    prepared = html.unescape(str(text or ""))
    prepared = re.sub(r"(?is)<\s*/?\s*br\s*/?\s*>", "\n", prepared)
    for raw_line in prepared.replace("\r", "\n").splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line:
            continue
        if line.startswith("#"):
            continue

        # Ignore markdown table rows entirely to avoid layout artifacts as "facts".
        if line.startswith("|") and line.endswith("|"):
            continue

        is_bullet = bool(re.match(r"^(?:[-*•]+|\d+[\.\)])\s+\S", line))
        line = re.sub(r"^(?:[-*•]+|\d+[\.\)])\s*", "", line).strip()
        if not line:
            continue

        if len(line) < 2:
            continue
        if not is_bullet and not re.search(r"[.!?…]\s*$", line):
            # Normal line fallback only if it already looks like a complete sentence.
            continue
        out.append(line)

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


def _extract_json_payload(raw: str) -> object | None:
    text = html.unescape(str(raw or "")).strip()
    if not text:
        return None

    # Prefer fenced JSON block if present.
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, flags=re.IGNORECASE)
    candidate = fenced.group(1).strip() if fenced else text

    try:
        return json.loads(candidate)
    except Exception:
        pass

    # Try to recover the first JSON array/object from mixed text.
    for pattern in (r"\[[\s\S]*\]", r"\{[\s\S]*\}"):
        match = re.search(pattern, candidate)
        if not match:
            continue
        chunk = match.group(0)
        try:
            return json.loads(chunk)
        except Exception:
            continue
    return None


def _collect_llm_fact_strings(data: object) -> list[str]:
    out: list[str] = []
    if isinstance(data, list):
        for item in data:
            if isinstance(item, str):
                out.append(item)
            elif isinstance(item, dict):
                for key in ("fact", "claim", "text", "sentence"):
                    value = item.get(key)
                    if isinstance(value, str) and value.strip():
                        out.append(value)
                        break
        return out

    if isinstance(data, dict):
        for key in ("facts", "claims", "items", "data", "sentences"):
            value = data.get(key)
            if isinstance(value, list):
                out.extend(_collect_llm_fact_strings(value))
                if out:
                    return out
    return out


def _looks_like_fact_fragment(text: str) -> bool:
    value = clean_factcheck_cell(text)
    if not value:
        return True
    low = value.casefold()
    if re.fullmatch(r"[-–—_=~*#.`:;/\\|+\s]+", value):
        return True
    if re.fullmatch(r"(?:col|column)\s*\d+", low):
        return True
    if re.fullmatch(r"item\s*\d+", low):
        return True
    if low in {"beispiele:", "example:", "happy writing.", "view.", "context."}:
        return True

    alpha_words = re.findall(r"[^\W\d_]{2,}", value, flags=re.UNICODE)
    if len(alpha_words) <= 1 and len(value) <= 24:
        return True
    if len(value) < 10 and len(alpha_words) < 2:
        return True
    if value.endswith(":"):
        return True
    return False


def _normalize_fact_list(candidates: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        clean = clean_factcheck_cell(candidate)
        if _looks_like_fact_fragment(clean):
            continue
        key = normalize_match_text_plain(clean)
        if len(key) < 4 or key in seen:
            continue
        seen.add(key)
        out.append(clean)
    return out


def parse_fact_candidates(response: str, target_text: str) -> list[str]:
    parsed = _extract_json_payload(response)
    llm_candidates = _normalize_fact_list(_collect_llm_fact_strings(parsed))
    if llm_candidates:
        return llm_candidates

    sentence_facts = [
        clean_factcheck_cell(sentence)
        for sentence in split_sentences_for_facts(target_text)
        if len(clean_factcheck_cell(sentence)) >= 2
    ]
    line_facts = [
        clean_factcheck_cell(line)
        for line in _line_facts_for_target_text(target_text)
        if len(clean_factcheck_cell(line)) >= 2
    ]

    # Fakt = Satz. Satz-Splitting ist primär.
    # Line-Fallback ergänzt nur zusätzliche bullet-/vollständige Zeilen,
    # die im Satz-Splitting nicht bereits enthalten sind.
    if sentence_facts:
        merged = list(sentence_facts)
        for candidate in line_facts:
            is_duplicate = False
            for existing in merged:
                if contains_text(existing, candidate) or contains_text(candidate, existing):
                    is_duplicate = True
                    break
            if not is_duplicate:
                merged.append(candidate)
        return _normalize_fact_list(merged)
    if line_facts:
        return _normalize_fact_list(line_facts)

    # Fallback für sehr unstrukturierte Texte.
    out: list[str] = []
    max_facts = suggest_fact_limit(target_text)
    for candidate in heuristic_fact_candidates_from_text(target_text):
        clean = clean_factcheck_cell(candidate)
        if len(clean) < 2:
            continue
        out.append(clean)
        if len(out) >= max_facts:
            break

    return _normalize_fact_list(out)


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


def _fact_token_set(text: str) -> set[str]:
    return {
        tok
        for tok in normalize_match_text_plain(text).split()
        if len(tok) >= 4
    }


def chunk_source_text(
    text: str,
    *,
    chunk_size: int = 900,
    chunk_overlap: int = 160,
) -> list[str]:
    src = str(text or "").replace("\r\n", "\n").strip()
    if not src:
        return []

    blocks = [b.strip() for b in re.split(r"\n{2,}", src) if b.strip()]
    if not blocks:
        blocks = [src]

    chunks: list[str] = []
    i = 0
    while i < len(blocks):
        window: list[str] = []
        total = 0
        j = i
        while j < len(blocks):
            block = blocks[j]
            block_len = len(block)
            if window and total + block_len + 2 > chunk_size:
                break
            if block_len > chunk_size and not window:
                start = 0
                while start < block_len:
                    end = min(block_len, start + chunk_size)
                    piece = block[start:end].strip()
                    if piece:
                        chunks.append(piece)
                    if end >= block_len:
                        break
                    start = max(start + 1, end - max(0, chunk_overlap))
                j += 1
                total = 0
                window = []
                break
            window.append(block)
            total += block_len + 2
            j += 1

        if window:
            chunks.append("\n\n".join(window))
            if chunk_overlap > 0 and len(window) > 1:
                overlap_chars = 0
                keep = 0
                for block in reversed(window):
                    overlap_chars += len(block) + 2
                    keep += 1
                    if overlap_chars >= chunk_overlap:
                        break
                i += max(1, len(window) - keep)
            else:
                i = j
        elif j <= i:
            i += 1
        else:
            i = j

    return chunks


def build_source_chunks(
    sources: list[tuple[str, str]],
    *,
    chunk_size: int = 900,
    chunk_overlap: int = 160,
) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for name, text in sources:
        clean_name = str(name or "").strip() or "Quelle"
        for chunk in chunk_source_text(
            str(text or ""),
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        ):
            clean_chunk = str(chunk or "").strip()
            if clean_chunk:
                out.append((clean_name, clean_chunk))
    return out


def select_evidence_snippet(fact: str, chunk: str, *, max_chars: int = 220) -> str:
    text = str(chunk or "").strip()
    if not text:
        return ""
    if len(text) <= max_chars:
        return text

    fact_tokens = _fact_token_set(fact)
    best = ""
    best_score = 0.0
    candidates = [
        part.strip()
        for part in re.split(r"(?<=[.!?])\s+|\n+", text)
        if part.strip()
    ]
    for cand in candidates:
        cand_tokens = _fact_token_set(cand)
        if not cand_tokens or not fact_tokens:
            continue
        score = len(cand_tokens & fact_tokens) / max(1, len(fact_tokens))
        if score > best_score:
            best = cand
            best_score = score

    if best and best_score >= 0.20:
        snippet = best
    else:
        low_text = text.casefold()
        pos = -1
        for tok in sorted(fact_tokens, key=len, reverse=True):
            pos = low_text.find(tok)
            if pos >= 0:
                break
        if pos < 0:
            snippet = text[:max_chars]
        else:
            half = max_chars // 2
            start = max(0, pos - half)
            end = min(len(text), pos + half)
            if start == 0:
                end = min(len(text), max_chars)
            if end >= len(text):
                start = max(0, len(text) - max_chars)
            snippet = text[start:end]
            if start > 0:
                snippet = "…" + snippet
            if end < len(text):
                snippet = snippet + "…"

    snippet = re.sub(r"\s+", " ", snippet).strip()
    if len(snippet) > max_chars:
        snippet = snippet[:max_chars].rstrip() + " …"
    return snippet or ""


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
