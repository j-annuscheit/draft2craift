"""ChatDock method implementations."""
from __future__ import annotations

from .deps import *  # noqa: F403

def _collect_shared_context(self) -> dict:
    """
    Return one canonical context payload for chat + all side actions.

    This guarantees that Chat, fact-check, glossary, and MindMap/Graph
    all consume exactly the same selected context sources.
    """
    ctx: dict = {}
    if self._context_getter:
        raw = self._context_getter()
        if isinstance(raw, dict):
            ctx = raw
    user_query = ""
    box = getattr(self, "input_box", None)
    if box is not None:
        getter = getattr(box, "toPlainText", None)
        if callable(getter):
            try:
                user_query = str(getter() or "").strip()
            except Exception:
                user_query = ""
    if not user_query:
        user_query = str(getattr(self, "_last_user_msg", "") or "").strip()

    return {
        "file_contents": list(ctx.get("file_contents", []) or []),
        "rag_results": list(ctx.get("rag_results", []) or []),
        "selected_text": str(ctx.get("selected_text", "") or ""),
        "selected_span": ctx.get("selected_span", None),
        "user_query": user_query,
        "grounding_required": bool(ctx.get("grounding_required", False)),
        "grounding_has_sources": bool(
            ctx.get("grounding_has_sources", False)
        ),
        "grounding_selected_docs": int(
            ctx.get("grounding_selected_docs", 0) or 0
        ),
        "grounding_rag_selected": bool(
            ctx.get("grounding_rag_selected", False)
        ),
        "grounding_rag_has_data": bool(
            ctx.get("grounding_rag_has_data", False)
        ),
    }

@staticmethod
def _has_any_context_content(ctx: dict) -> bool:
    selected_text = str(ctx.get("selected_text", "") or "").strip()
    if selected_text:
        return True
    for _name, content in list(ctx.get("file_contents", []) or []):
        if str(content or "").strip():
            return True
    for _path, _score, excerpt in list(ctx.get("rag_results", []) or []):
        if str(excerpt or "").strip():
            return True
    return False

def _reset_pending_canvas_rewrite(self):
    self._pending_apply_to_canvas = False
    self._pending_selected_text = ""
    self._pending_selected_span = None
    self._pending_apply_retry_count = 0
    self._pending_apply_context = {}

def _require_loaded_model(self) -> bool:
    if self.llm.is_model_loaded():
        return True
    self.history.add_message("system", self._NO_MODEL_LOADED_MESSAGE)
    return False

def _notify_canvas_apply_success(self, info: str):
    self._reset_pending_canvas_rewrite()
    self.history.add_message(
        "system",
        f"✅ Selection updated in draft workspace. {info}".strip(),
    )
    self.history.activate_feedback("canvas_edit")

@staticmethod
def _canvas_rewrite_retry_user_message() -> str:
    return (
        "Es wurde nicht die richtige Markierung für den ersetzten Text verwendet.\n"
        "Die Aufgabe bleibt unverändert dieselbe, inklusive Ausgabeform und Struktur.\n"
        "Behalte die Form standardmäßig bei: Liste bleibt Liste, Tabelle bleibt Tabelle, "
        "JSON bleibt JSON, Markdown bleibt Markdown.\n"
        "Nur wenn die ursprüngliche Nutzeranweisung explizit eine "
        "Format-Umwandlung fordert (z. B. zu Fließtext), darf die Form geändert werden.\n"
        "Bitte gib NUR den finalen Ersatzinhalt in folgendem exakten Format aus:\n"
        f"{CANVAS_REWRITE_OPEN}\n"
        "TEXT_DER_DEN_ZU_ERSETZENDEN_TEXT_ERSETZT\n"
        f"{CANVAS_REWRITE_CLOSE}\n"
        "Keine Erklärung, keine zusätzlichen Präfixe/Suffixe."
    )

@staticmethod
def _canvas_scope_retry_user_message() -> str:
    return (
        "Es wurde offenbar Text außerhalb der Auswahl wiederholt.\n"
        "Bitte korrigiere das und ersetze NUR den selektierten Bereich, "
        "NICHT den gesamten Canvas/Draft.\n"
        "Die Aufgabe bleibt unverändert dieselbe, inklusive Ausgabeform und Struktur.\n"
        "Behalte die Form standardmäßig bei.\n"
        "Nur wenn die ursprüngliche Nutzeranweisung explizit eine "
        "Format-Umwandlung fordert, darf die Form geändert werden.\n"
        "Gib NUR den finalen Ersatzinhalt in folgendem exakten Format aus:\n"
        f"{CANVAS_REWRITE_OPEN}\n"
        "TEXT_DER_DEN_ZU_ERSETZENDEN_TEXT_ERSETZT\n"
        f"{CANVAS_REWRITE_CLOSE}\n"
        "Keine Erklärung, keine zusätzlichen Präfixe/Suffixe."
    )

@classmethod
def _contains_non_selected_canvas_repeat(
    cls,
    draft_text: str,
    selected_text: str,
    replacement: str,
) -> bool:
    draft = cls._normalize_context_text(draft_text)
    selected = cls._normalize_context_text(selected_text)
    rewritten = cls._normalize_context_text(replacement)
    if not draft or not selected or not rewritten:
        return False
    if draft == selected or rewritten == selected:
        return False
    if rewritten in draft and rewritten != selected:
        return True
    if draft in rewritten and draft != selected:
        return True

    start = draft.find(selected)
    if start < 0:
        return False

    before = draft[:start].strip()
    after = draft[start + len(selected):].strip()
    before_hint = before[-200:].strip()
    after_hint = after[:200].strip()
    if before_hint and len(before_hint) >= 24 and before_hint in rewritten:
        return True
    if after_hint and len(after_hint) >= 24 and after_hint in rewritten:
        return True
    return False

@staticmethod
def _extract_selected_replacement_from_full_draft(
    draft_text: str,
    selected_text: str,
    rewritten_text: str,
) -> str:
    """
    Detect exact A+B'+C pattern and extract only B'.

    Returns empty string when no unique 1:1 decomposition is possible.
    """
    draft = (
        str(draft_text or "")
        .replace("\u2029", "\n")
        .replace("\r\n", "\n")
    )
    selected = (
        str(selected_text or "")
        .replace("\u2029", "\n")
        .replace("\r\n", "\n")
    )
    rewritten = (
        str(rewritten_text or "")
        .replace("\u2029", "\n")
        .replace("\r\n", "\n")
    )
    if not draft or not selected or not rewritten:
        return ""
    if draft == selected:
        return ""

    candidates: list[str] = []

    def _similarity(a: str, b: str) -> float:
        if a == b:
            return 1.0
        if not a or not b:
            return 0.0
        max_len = max(len(a), len(b))
        if max_len <= 0:
            return 1.0
        if abs(len(a) - len(b)) / max_len > 0.05:
            return 0.0
        return SequenceMatcher(None, a, b).ratio()

    def _nearby_positions(target: int, total: int, window: int) -> list[int]:
        start = max(0, target - window)
        end = min(total, target + window)
        positions = list(range(start, end + 1))
        positions.sort(key=lambda pos: (abs(pos - target), pos))
        return positions

    similarity_threshold = 0.95
    start = 0
    while True:
        idx = draft.find(selected, start)
        if idx < 0:
            break
        end = idx + len(selected)
        prefix = draft[:idx]
        suffix = draft[end:]
        if rewritten.startswith(prefix) and rewritten.endswith(suffix):
            repl_end = len(rewritten) - len(suffix) if suffix else len(rewritten)
            candidate = rewritten[len(prefix):repl_end]
            candidates.append(candidate)
            start = idx + 1
            continue

        # Fuzzy fallback: accept minimal edits in A/C if both parts are still >=95% similar.
        total_len = len(rewritten)
        prefix_target = len(prefix)
        suffix_target = total_len - len(suffix)
        shift_window = max(4, min(64, int(max(prefix_target, len(suffix)) * 0.02)))

        prefix_hits: list[tuple[int, float]] = []
        for pos in _nearby_positions(prefix_target, total_len, shift_window):
            score = _similarity(prefix, rewritten[:pos])
            if score >= similarity_threshold:
                prefix_hits.append((pos, score))
                if len(prefix_hits) >= 12:
                    break

        suffix_hits: list[tuple[int, float]] = []
        for pos in _nearby_positions(suffix_target, total_len, shift_window):
            score = _similarity(suffix, rewritten[pos:])
            if score >= similarity_threshold:
                suffix_hits.append((pos, score))
                if len(suffix_hits) >= 12:
                    break

        best: tuple[float, int, str] | None = None
        for prefix_pos, prefix_score in prefix_hits:
            for suffix_pos, suffix_score in suffix_hits:
                if prefix_pos > suffix_pos:
                    continue
                edge_score = min(prefix_score, suffix_score)
                edge_shift = abs(prefix_pos - prefix_target) + abs(suffix_pos - suffix_target)
                middle = rewritten[prefix_pos:suffix_pos]
                rank = (edge_score, -edge_shift, middle)
                if best is None or rank > best:
                    best = rank
        if best is not None:
            candidates.append(best[2])
        start = idx + 1

    if len(candidates) != 1:
        return ""
    return candidates[0]

def _retry_canvas_rewrite_format(self, retry_message: str | None = None) -> bool:
    if self._pending_apply_retry_count >= self._pending_apply_retry_limit:
        return False
    if not self.llm.is_model_loaded():
        return False
    context = dict(self._pending_apply_context or {})
    if not context:
        return False

    message = str(retry_message or self._canvas_rewrite_retry_user_message())
    self.history.add_message("user", message)

    send_ok = self.llm.send_message(
        user_message=message,
        file_contents=list(context.get("file_contents", []) or []),
        rag_results=list(context.get("rag_results", []) or []),
        selected_text=str(context.get("selected_text", "") or ""),
        chat_history=self.history.get_history()[:-1],
        selection_apply_mode=True,
        grounding_required=bool(context.get("grounding_required", False)),
        grounding_has_sources=bool(context.get("grounding_has_sources", True)),
        **dict(context.get("gen_params", {}) or {}),
    )
    if not send_ok:
        return False

    self._pending_apply_retry_count += 1
    self._pending_apply_to_canvas = True
    self.history.begin_streaming()
    self._history_stream_open = True
    return True

__all__ = [
    "_collect_shared_context",
    "_has_any_context_content",
    "_reset_pending_canvas_rewrite",
    "_require_loaded_model",
    "_notify_canvas_apply_success",
    "_canvas_rewrite_retry_user_message",
    "_canvas_scope_retry_user_message",
    "_contains_non_selected_canvas_repeat",
    "_extract_selected_replacement_from_full_draft",
    "_retry_canvas_rewrite_format",
]
