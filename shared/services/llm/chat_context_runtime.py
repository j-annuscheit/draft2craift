"""Context guards and signal handling for ``LLMManager`` runtime."""
from __future__ import annotations

import os
import re
import time

_COMMA_NEWLINE_SPLIT_RE = re.compile(r"[,\n]+")
_THINK_OPEN_TAG = "<think>"
_THINK_CLOSE_TAG = "</think>"
_THINK_BLOCK_RE = re.compile(r"<think>[\s\S]*?</think>", flags=re.IGNORECASE)
_THINK_OPEN_TAIL_RE = re.compile(r"<think>[\s\S]*$", flags=re.IGNORECASE)
_IMPLICIT_THINK_MARKERS = (
    "i need to",
    "let me",
    "the user asked",
    "i should",
    "i will",
    "ich sollte",
    "lass mich",
    "der nutzer hat",
)


def _n_ctx(self) -> int:
    """Return the model's configured context window size."""
    worker = getattr(self, "worker", None)
    if worker is None:
        return 4096
    try:
        return int(worker.context_window(4096))
    except Exception:
        return 4096

def _count_tokens(self, text: str) -> int:
    """Count tokens via the model's tokenizer; falls back to len/4."""
    worker = getattr(self, "worker", None)
    if worker is None:
        return max(1, len(str(text or "")) // 4)
    try:
        return max(1, int(worker.count_tokens(str(text or ""))))
    except Exception:
        return max(1, len(str(text or "")) // 4)

def _check_context(
    self,
    prompt: str,
    user_message: str,
    file_contents: list[tuple[str, str]] | None,
    rag_results: list[tuple[str, float, str]] | None,
    selected_text: str,
    chat_history: list[tuple[str, str]] | None,
    max_tokens: int,
    system_prompt_text: str,
) -> str:
    """Return a detailed error string if the context exceeds n_ctx, else ''."""
    n_ctx         = self._n_ctx()
    prompt_tokens = self._count_tokens(prompt)

    if prompt_tokens + max_tokens <= n_ctx:
        return ""

    # Build per-component breakdown
    def tok(text: str) -> int:
        return self._count_tokens(text)

    breakdown: list[tuple[str, int]] = []

    breakdown.append((
        "System-Prompt",
        tok(f"<|system|>\n{system_prompt_text}\n"),
    ))

    if file_contents:
        files_title = self._render_prompt_template(
            "chat_section_files_title"
        ).strip() or "## Angehängte Dokumente"
        fc_text = files_title + "\n" + "".join(
            f"### {name}\n```\n{content}\n```\n"
            for name, content in file_contents
        )
        breakdown.append((f"Dateien ({len(file_contents)})", tok(fc_text)))

    if rag_results:
        rag_title = self._render_prompt_template(
            "chat_section_rag_title"
        ).strip() or "## Relevante Auszüge (Wissensbasis)"
        rag_text = rag_title + "\n" + "".join(
            f"**{os.path.basename(path)}** (score {score:.2f})\n{excerpt}\n"
            for path, score, excerpt in rag_results
        )
        breakdown.append((f"RAG-Ergebnisse ({len(rag_results)})", tok(rag_text)))

    if selected_text and selected_text.strip():
        selected_title = self._render_prompt_template(
            "chat_section_selected_title"
        ).strip() or CANVAS_TARGET_SECTION_TITLE
        breakdown.append((
            "Ausgewählter Text",
            tok(f"{selected_title}\n```\n{selected_text}\n```\n"),
        ))

    if chat_history:
        hist_text = "".join(
            f"\n<|{role}|>\n{content}" for role, content in chat_history
        )
        breakdown.append((
            f"Chat-Verlauf ({len(chat_history)} Nachr.)",
            tok(hist_text),
        ))

    breakdown.append((
        "Nutzeranfrage",
        tok(f"\n<|user|>\n{user_message}\n<|assistant|>\n"),
    ))

    # Format the error message
    pad = max(len(label) for label, _ in breakdown)
    sep = "─" * (pad + 12)

    lines = ["Kontext zu groß – Nachricht nicht gesendet.", ""]
    lines.append("Token-Aufschlüsselung:")
    for label, n in breakdown:
        lines.append(f"  {label:<{pad}}  {n:>7} Tokens")

    overhead = prompt_tokens - sum(n for _, n in breakdown)
    if overhead > 0:
        lines.append(f"  {'Struktur-Overhead':<{pad}}  {overhead:>7} Tokens")

    lines.append(f"  {sep}")
    lines.append(f"  {'Prompt gesamt':<{pad}}  {prompt_tokens:>7} Tokens")
    lines.append(f"  {'Reserviert (Antwort)':<{pad}}  {max_tokens:>7} Tokens")
    lines.append(f"  {sep}")
    lines.append(f"  {'Benötigt':<{pad}}  {prompt_tokens + max_tokens:>7} Tokens")
    lines.append(f"  {'Maximal (n_ctx)':<{pad}}  {n_ctx:>7} Tokens")
    lines.append(f"  {'Überschreitung':<{pad}}  {prompt_tokens + max_tokens - n_ctx:>7} Tokens")

    return "\n".join(lines)

def _check_prompt_window(self, prompt: str, max_tokens: int) -> str:
    """
    Return an error when prompt+output would exceed the model n_ctx window.

    Used by synchronous helper calls that don't go through send_message().
    """
    n_ctx = self._n_ctx()
    prompt_tokens = self._count_tokens(prompt)
    needed = int(prompt_tokens) + int(max_tokens)
    if needed <= n_ctx:
        return ""
    return (
        "Kontext zu groß für das aktuelle Modellfenster.\n"
        f"Prompt: {prompt_tokens} Tokens\n"
        f"Reserviert (Antwort): {int(max_tokens)} Tokens\n"
        f"Benötigt: {needed} Tokens\n"
        f"Maximal (n_ctx): {n_ctx} Tokens\n"
        f"Überschreitung: {needed - n_ctx} Tokens"
    )

def _decode_forbidden_token(cls, raw: str) -> str:
    token = raw.strip()
    if not token:
        return ""

    if len(token) >= 2 and token[0] == token[-1] and token[0] in ("'", '"'):
        token = token[1:-1]

    alias = cls._FORBIDDEN_CHAR_ALIASES.get(token.casefold())
    if alias is not None:
        return alias

    m = re.fullmatch(r"(?:u\+|\\u)([0-9a-fA-F]{4,6})", token)
    if m:
        try:
            return chr(int(m.group(1), 16))
        except ValueError:
            return ""

    m = re.fullmatch(r"(?:0x|\\x)([0-9a-fA-F]{2,6})", token)
    if m:
        try:
            return chr(int(m.group(1), 16))
        except ValueError:
            return ""

    if "\\" in token:
        try:
            token = bytes(token, "utf-8").decode("unicode_escape")
        except Exception:
            pass

    return token

def _parse_forbidden_chars(cls, spec: str) -> set[str]:
    chars: set[str] = set()
    for raw in _COMMA_NEWLINE_SPLIT_RE.split(spec or ""):
        decoded = cls._decode_forbidden_token(raw)
        if not decoded:
            continue
        for ch in decoded:
            chars.add(ch)
    return chars

def _apply_forbidden_filter(self, text: str) -> str:
    if not text or not self._forbidden_chars:
        return text
    return "".join(ch for ch in text if ch not in self._forbidden_chars)


def _hide_think_blocks_enabled(self) -> bool:
    configured = getattr(self, "_hide_think_blocks", None)
    if configured is not None:
        return bool(configured)
    show = str(os.environ.get("D2C_SHOW_THINK_BLOCKS", "")).strip().casefold() in {
        "1",
        "true",
        "yes",
        "on",
    }
    return not show


def _assume_implicit_think_prefix(self) -> bool:
    forced = str(os.environ.get("D2C_ASSUME_IMPLICIT_THINK", "")).strip().casefold()
    if forced in {"1", "true", "yes", "on"}:
        return True
    if forced in {"0", "false", "no", "off"}:
        return False

    worker = getattr(self, "worker", None)
    backend = getattr(worker, "_backend", None) if worker is not None else None
    model_ref = str(getattr(backend, "model_ref", "") or "").casefold()
    backend_id = str(getattr(backend, "backend_id", "") or "").casefold()
    return ("nemotron" in model_ref) and (backend_id == "transformers")


def _strip_think_blocks_full(text: str) -> str:
    value = str(text or "")
    if not value:
        return ""
    lower = value.casefold()
    close_idx = lower.find(_THINK_CLOSE_TAG)
    open_idx = lower.find(_THINK_OPEN_TAG)
    if close_idx >= 0 and (open_idx < 0 or open_idx > close_idx):
        value = value[close_idx + len(_THINK_CLOSE_TAG):]
    value = _THINK_BLOCK_RE.sub("", value)
    value = _THINK_OPEN_TAIL_RE.sub("", value)
    return value


def _extract_think_fallback(text: str) -> str:
    value = str(text or "")
    if not value:
        return ""
    lower = value.casefold()
    close_idx = lower.find(_THINK_CLOSE_TAG)
    open_idx = lower.find(_THINK_OPEN_TAG)
    if close_idx >= 0 and (open_idx < 0 or open_idx > close_idx):
        return value[:close_idx]
    if open_idx >= 0 and close_idx > open_idx:
        return value[open_idx + len(_THINK_OPEN_TAG):close_idx]
    if open_idx >= 0:
        return value[open_idx + len(_THINK_OPEN_TAG):]
    return ""


def _looks_like_implicit_think_payload(text: str) -> bool:
    raw = str(text or "").strip()
    if not raw:
        return False
    lowered = raw.casefold()
    return any(marker in lowered for marker in _IMPLICIT_THINK_MARKERS)


def _split_think_stream(
    self,
    text: str,
    *,
    flush: bool = False,
) -> tuple[str, str]:
    if not _hide_think_blocks_enabled(self):
        return str(text or ""), ""

    incoming = str(text or "")
    pending = str(getattr(self, "_think_stream_pending", "") or "")
    inside = bool(getattr(self, "_think_stream_inside", False))
    implicit_prefix = bool(getattr(self, "_think_stream_implicit_prefix", False))
    data = pending + incoming
    if not data and not flush:
        return "", ""

    visible_parts: list[str] = []
    think_parts: list[str] = []
    i = 0
    lower_data = data.casefold()
    open_tag = _THINK_OPEN_TAG
    close_tag = _THINK_CLOSE_TAG

    while i < len(data):
        if inside:
            end_idx = lower_data.find(close_tag, i)
            if end_idx < 0:
                if flush:
                    if implicit_prefix:
                        tail = data[i:]
                        if _looks_like_implicit_think_payload(tail):
                            think_parts.append(tail)
                        else:
                            visible_parts.append(tail)
                    else:
                        think_parts.append(data[i:])
                    setattr(self, "_think_stream_inside", False)
                    setattr(self, "_think_stream_implicit_prefix", False)
                    setattr(self, "_think_stream_pending", "")
                    return "".join(visible_parts), "".join(think_parts)
                keep_from = max(i, len(data) - len(close_tag) + 1)
                if implicit_prefix:
                    keep_from = i
                think_parts.append(data[i:keep_from])
                setattr(self, "_think_stream_inside", True)
                setattr(self, "_think_stream_implicit_prefix", implicit_prefix)
                setattr(self, "_think_stream_pending", data[keep_from:])
                return "".join(visible_parts), "".join(think_parts)
            think_parts.append(data[i:end_idx])
            inside = False
            implicit_prefix = False
            i = end_idx + len(close_tag)
            continue

        start_idx = lower_data.find(open_tag, i)
        if start_idx < 0:
            if flush:
                visible_parts.append(data[i:])
                setattr(self, "_think_stream_inside", False)
                setattr(self, "_think_stream_implicit_prefix", False)
                setattr(self, "_think_stream_pending", "")
                return "".join(visible_parts), "".join(think_parts)
            keep_from = max(i, len(data) - len(open_tag) + 1)
            visible_parts.append(data[i:keep_from])
            setattr(self, "_think_stream_inside", False)
            setattr(self, "_think_stream_implicit_prefix", False)
            setattr(self, "_think_stream_pending", data[keep_from:])
            return "".join(visible_parts), "".join(think_parts)

        visible_parts.append(data[i:start_idx])
        inside = True
        implicit_prefix = False
        i = start_idx + len(open_tag)

    setattr(self, "_think_stream_inside", inside)
    setattr(self, "_think_stream_implicit_prefix", implicit_prefix)
    setattr(self, "_think_stream_pending", "")
    return "".join(visible_parts), "".join(think_parts)


def _emit_thinking_delta(self, delta: str) -> None:
    text = str(delta or "")
    if not text:
        return
    current = str(getattr(self, "_last_think_text", "") or "")
    setattr(self, "_last_think_text", f"{current}{text}")
    signal = getattr(self, "thinking_received", None)
    if signal is not None and hasattr(signal, "emit"):
        try:
            signal.emit(text)
        except Exception:
            pass


# ── Worker signal interceptors ─────────────────────────────────────────────

def _on_token(self, token: str):
    self._token_count += 1
    visible, think_delta = _split_think_stream(self, str(token or ""), flush=False)
    _emit_thinking_delta(self, think_delta)
    filtered = self._apply_forbidden_filter(visible)
    if filtered:
        self.token_received.emit(filtered)

def _on_complete(self, response: str):
    raw_response = str(response or "")
    tail_visible, tail_think = _split_think_stream(self, "", flush=True)
    _emit_thinking_delta(self, tail_think)

    tail_filtered = self._apply_forbidden_filter(tail_visible)
    if tail_filtered:
        self.token_received.emit(tail_filtered)

    think_payload = str(getattr(self, "_last_think_text", "") or "").strip()
    if not think_payload:
        think_payload = str(_extract_think_fallback(raw_response) or "").strip()
        setattr(self, "_last_think_text", think_payload)

    without_think = (
        _strip_think_blocks_full(raw_response)
        if _hide_think_blocks_enabled(self)
        else raw_response
    )
    filtered_response = self._apply_forbidden_filter(without_think)
    removed_think_chars = max(0, len(raw_response) - len(without_think))
    removed_forbidden_chars = max(0, len(without_think) - len(filtered_response))
    elapsed = time.perf_counter() - self._gen_start
    if self._log:
        tok_s = self._token_count / elapsed if elapsed > 0 else 0.0
        self._log.info(
            "LLM",
            f"Generation complete"
            f"  |  {self._token_count} tokens"
            f"  |  {elapsed:.2f}s"
            f"  |  {tok_s:.1f} tok/s",
        )
        if removed_think_chars > 0 or removed_forbidden_chars > 0:
            self._log.info(
                "LLM",
                "Filtering stats"
                f"  |  removed_think_chars={removed_think_chars}"
                f"  |  removed_forbidden_chars={removed_forbidden_chars}",
            )
        if think_payload:
            self._log.debug("LLM", f"Thinking (hidden from chat):\n{think_payload}")
        self._log.debug("LLM", f"Full response (raw):\n{raw_response}")
        self._log.debug("LLM", f"Visible response:\n{filtered_response}")
    self.is_generating.emit(False)
    self.generation_complete.emit(filtered_response)

def _on_error(self, message: str):
    if self._log:
        self._log.error("LLM", f"Error: {message}")
    self.is_generating.emit(False)
    self.error_occurred.emit(message)

def _on_model_loaded(self, success: bool, message: str):
    if self._log:
        if success:
            self._log.info("LLM", f"Model ready: {message}")
        else:
            self._log.error("LLM", f"Model load failed: {message}")
    self.model_loaded.emit(success, message)

def _on_nli_model_loaded(self, success: bool, message: str):
    backend = getattr(self, "_nli_backend", None)
    if backend is not None:
        backend.last_error = "" if success else str(message or "")
    if self._log:
        if success:
            self._log.info("NLI", f"Model ready: {message}")
        else:
            self._log.error("NLI", f"Model load failed: {message}")
    self.nli_model_loaded.emit(success, message)
