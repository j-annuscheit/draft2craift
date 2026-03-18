"""Runtime chat flow and context guard methods for ``LLMManager``."""
from __future__ import annotations

import os
import re
import time

CANVAS_REWRITE_OPEN = "[[CANVAS_REWRITE]]"
CANVAS_REWRITE_CLOSE = "[[/CANVAS_REWRITE]]"
CANVAS_TARGET_SECTION_TITLE = "## DIESER TEXT WIRD ERSETZT (NUR DIESER ABSCHNITT)"
CANVAS_TARGET_START = "[[CANVAS_TARGET_START]]"
CANVAS_TARGET_END = "[[CANVAS_TARGET_END]]"
POST_CONTEXT_REWRITE_TITLE = "### WICHTIG: REWRITE-AUFTRAG (NACH KONTEXT) ###"
GROUNDING_INSUFFICIENT_MESSAGE = (
    "Nicht genug Informationen in den ausgewählten Dokumenten/RAG-Quellen."
)
REQUIRED_STYLE_RULES = (
    "Verbindliche Stilregel:\n"
    "- Verwende keinen Gedankenstrich als Satzzeichen "
    "(—, –, ‒, ― oder ' - ').\n"
    "- Nutze stattdessen je nach Satz Komma, Punkt, Doppelpunkt "
    "oder Klammern.\n"
    "- Bindestriche innerhalb von Wörtern sind erlaubt "
    "(z. B. 3D-Datensatz)."
)
_COMMA_NEWLINE_SPLIT_RE = re.compile(r"[,\n]+")


def send_message(
    self,
    user_message: str,
    file_contents: list[tuple[str, str]] | None = None,
    rag_results: list[tuple[str, float, str]] | None = None,
    selected_text: str = "",
    chat_history: list[tuple[str, str]] | None = None,
    max_tokens: int     = 1024,
    temperature: float  = 0.7,
    top_p: float        = 0.9,
    repeat_penalty: float = 1.1,
    forbidden_chars: str = "",
    selection_apply_mode: bool = False,
    grounding_required: bool = False,
    grounding_has_sources: bool = True,
    system_prompt_key: str = "chat_system",
) -> bool:
    if grounding_required and not grounding_has_sources:
        msg = (
            f"{GROUNDING_INSUFFICIENT_MESSAGE} "
            "Bitte zuerst RAG-Ergebnisse erzeugen und/oder Dokumente auswählen."
        )
        if self._log:
            self._log.warning("LLM", f"Generation abgelehnt: {msg}")
        self.error_occurred.emit(msg)
        return False

    system_prompt_text = str(
        self._prompts.get(system_prompt_key, self._system_prompt) or self._system_prompt
    )
    system_prompt_text = self._append_required_style_rules(system_prompt_text)

    prompt = self._build_prompt(
        user_message, file_contents, rag_results,
        selected_text, chat_history, selection_apply_mode,
        grounding_required, grounding_has_sources,
        system_prompt_text,
    )

    # Context-window check — must happen before handing off to the worker
    if self.is_model_loaded():
        err = self._check_context(
            prompt, user_message, file_contents, rag_results,
            selected_text, chat_history, max_tokens,
            system_prompt_text,
        )
        if err:
            if self._log:
                self._log.error("LLM", err)
            self.error_occurred.emit(err)
            return False

    if self._log:
        self._log.info(
            "LLM",
            f"Generating  |  prompt: {len(prompt)} chars"
            f"  ({self._count_tokens(prompt)} tokens)"
            f"  max_tokens={max_tokens}  temp={temperature}  top_p={top_p}",
        )
        self._log.debug("LLM", f"Full prompt:\n{prompt}")

    self._gen_start   = time.perf_counter()
    self._token_count = 0
    self._forbidden_chars = self._parse_forbidden_chars(forbidden_chars)
    if self._log and self._forbidden_chars:
        self._log.debug(
            "LLM",
            f"Forbidden-character filter active ({len(self._forbidden_chars)} chars).",
        )
    self.is_generating.emit(True)
    self.worker.generate(
        prompt,
        max_tokens    = max_tokens,
        temperature   = temperature,
        top_p         = top_p,
        repeat_penalty = repeat_penalty,
        forbidden_chars = tuple(self._forbidden_chars),
    )
    return True

def stop(self):
    if self._log:
        elapsed = time.perf_counter() - self._gen_start
        self._log.warning(
            "LLM",
            f"Generation stopped by user"
            f"  |  {self._token_count} tokens  |  {elapsed:.2f}s elapsed",
        )
    self.worker.request_stop()

def _append_required_style_rules(system_prompt_text: str) -> str:
    base = (system_prompt_text or "").strip()
    if REQUIRED_STYLE_RULES in base:
        return base
    if not base:
        return REQUIRED_STYLE_RULES
    return f"{base}\n\n{REQUIRED_STYLE_RULES}"

# ── Prompt builder ────────────────────────────────────────────────────────

def _build_prompt(
    self,
    user_message: str,
    file_contents: list[tuple[str, str]] | None,
    rag_results: list[tuple[str, float, str]] | None,
    selected_text: str,
    chat_history: list[tuple[str, str]] | None,
    selection_apply_mode: bool,
    grounding_required: bool,
    grounding_has_sources: bool,
    system_prompt_text: str,
) -> str:
    parts: list[str] = []
    rewrite_instruction_block = ""
    prompt_file_contents = list(file_contents or [])
    selection_marked_in_canvas = False

    if selection_apply_mode and selected_text.strip() and prompt_file_contents:
        adjusted: list[tuple[str, str]] = []
        for name, content in prompt_file_contents:
            entry_name = str(name or "")
            entry_content = str(content or "")
            if (not selection_marked_in_canvas) and entry_name.startswith("Draft:"):
                entry_content, applied = self._inject_canvas_target_markers(
                    entry_content,
                    selected_text,
                )
                selection_marked_in_canvas = (
                    selection_marked_in_canvas or applied
                )
            adjusted.append((entry_name, entry_content))
        prompt_file_contents = adjusted

    parts.append(f"<|system|>\n{system_prompt_text}\n")

    if grounding_required:
        cite_rule = self._render_prompt_template(
            "chat_citation_rule_rewrite"
            if selection_apply_mode
            else "chat_citation_rule_answer"
        ).strip()
        grounding_block = self._render_prompt_template(
            "chat_grounding_rules",
            {
                "insufficient_message": GROUNDING_INSUFFICIENT_MESSAGE,
                "citation_rule": cite_rule,
            },
        ).strip()
        grounding_title = self._render_prompt_template(
            "chat_section_grounding_title"
        ).strip() or "### Verbindliche Dokument-Regeln ###"
        parts.append(
            f"\n{grounding_title}\n"
            + grounding_block
            + "\n"
        )

    if selection_apply_mode and selected_text.strip():
        grounding_note = (
            self._render_prompt_template("chat_grounding_note_rewrite").strip()
            if (grounding_required and grounding_has_sources) else ""
        )
        rewrite_enforcer = (
            "Rewrite-Pflicht (streng, auch für kleine Modelle):\n"
            "1) Die Nutzeranweisung hat höchste Priorität.\n"
            "2) Ersetze ausschließlich den Zielbereich.\n"
            "3) Weitere Draft-/Dokument-Kontexte sind nur Referenz "
            "(Stil, Konsistenz, Fakten).\n"
            "4) Gib NICHT den gesamten Draft zurück, außer der gesamte "
            "Draft ist tatsächlich der Zielbereich.\n"
            "5) Wenn eine Änderung verlangt ist (z. B. entfernen, ergänzen, "
            "umschreiben, kürzen), muss sich der ausgegebene Text inhaltlich "
            "ändern.\n"
            "6) Wenn der Auftrag Löschen/Entfernen/Streichen verlangt, dürfen "
            "diese Inhalte im Ergebnis nicht wieder auftauchen "
            "(auch nicht paraphrasiert).\n"
            "7) Vermeide allgemeine Floskeln; schreibe konkret zur Aufgabe.\n"
            "8) Behalte die Form des Zielbereichs standardmäßig bei "
            "(Liste bleibt Liste, Tabelle bleibt Tabelle, JSON bleibt JSON).\n"
            "9) Wenn der Nutzer ausdrücklich eine Format-Umwandlung verlangt "
            "(z. B. Stichpunkte -> Fließtext), dann führe genau diese "
            "Umwandlung aus.\n"
            "10) Wenn der Nutzer ein Ausgabeformat vorgibt, halte es exakt ein.\n"
        )
        if selection_marked_in_canvas:
            rewrite_enforcer += (
                f"11) Im Draft-Kontext markiert {CANVAS_TARGET_START} den Anfang "
                f"und {CANVAS_TARGET_END} das Ende des zu ersetzenden Abschnitts.\n"
                f"12) Ersetze nur den Text zwischen {CANVAS_TARGET_START} und "
                f"{CANVAS_TARGET_END}; Text außerhalb dieser Marker darf nicht "
                "in der Antwort erscheinen.\n"
            )
        else:
            rewrite_enforcer += (
                "11) Der zu ersetzende Abschnitt steht unter der Überschrift "
                f"'{CANVAS_TARGET_SECTION_TITLE}'.\n"
            )
        rewrite_block = self._render_prompt_template(
            "chat_canvas_rewrite_rules",
            {
                "canvas_open": CANVAS_REWRITE_OPEN,
                "canvas_close": CANVAS_REWRITE_CLOSE,
                "grounding_note": grounding_note,
                "insufficient_message": GROUNDING_INSUFFICIENT_MESSAGE,
            },
        ).strip()
        if (
            not rewrite_block
            or CANVAS_REWRITE_OPEN not in rewrite_block
            or CANVAS_REWRITE_CLOSE not in rewrite_block
        ):
            rewrite_block = (
                "Du bearbeitest den aktuell ausgewählten Draft-Text.\n"
                "Gib NUR den finalen, vollständig editierten Ersatztext in "
                "diesem exakten Wrapper zurück:\n"
                f"{CANVAS_REWRITE_OPEN}\n"
                "<hier der vollständige finale Text>\n"
                f"{CANVAS_REWRITE_CLOSE}\n"
                "Keine Erklärung, keine zusätzlichen Präfixe/Suffixe."
            )
        rewrite_title = self._render_prompt_template(
            "chat_section_rewrite_title"
        ).strip() or "### Ausgabeformat für Draft-Rewrite ###"
        rewrite_instruction_block = (
            f"\n{rewrite_title}\n"
            + rewrite_enforcer
            + rewrite_block
            + "\n"
        )
        parts.append(rewrite_instruction_block)

    has_context = (
        bool(prompt_file_contents)
        or bool(rag_results)
        or bool(selected_text and selected_text.strip())
    )
    if has_context:
        context_title = self._render_prompt_template(
            "chat_section_context_title"
        ).strip() or "### Kontext ###"
        parts.append(f"\n{context_title}\n")

        if prompt_file_contents:
            files_title = self._render_prompt_template(
                "chat_section_files_title"
            ).strip() or "## Angehängte Dokumente"
            parts.append(f"{files_title}\n")
            for name, content in prompt_file_contents:
                parts.append(f"### {name}\n```\n{content}\n```\n")

        if rag_results:
            rag_title = self._render_prompt_template(
                "chat_section_rag_title"
            ).strip() or "## Relevante Auszüge (Wissensbasis)"
            parts.append(f"{rag_title}\n")
            for path, score, excerpt in rag_results:
                basename = os.path.basename(path)
                parts.append(
                    f"**{basename}** (score {score:.2f})\n{excerpt}\n"
                )

        if selected_text and selected_text.strip():
            if selection_apply_mode and selection_marked_in_canvas:
                selected_title = ""
            elif selection_apply_mode:
                selected_title = CANVAS_TARGET_SECTION_TITLE
            else:
                selected_title = self._render_prompt_template(
                    "chat_section_selected_title"
                ).strip() or CANVAS_TARGET_SECTION_TITLE
            if selected_title:
                parts.append(
                    f"{selected_title}\n```\n{selected_text}\n```\n"
                )

        context_end = self._render_prompt_template(
            "chat_section_context_end"
        ).strip() or "### Ende Kontext ###"
        parts.append(f"{context_end}\n")
        if rewrite_instruction_block:
            parts.append(
                f"\n{POST_CONTEXT_REWRITE_TITLE}\n"
                + rewrite_instruction_block.lstrip()
            )

    for role, content in (chat_history or []):
        parts.append(f"\n<|{role}|>\n{content}")

    parts.append(f"\n<|user|>\n{user_message}")
    parts.append("\n<|assistant|>\n")
    prompt = "".join(parts)
    resolver = getattr(self, "_resolve_project_variables_text", None)
    if callable(resolver):
        try:
            return str(resolver(prompt) or "")
        except Exception:
            return prompt
    return prompt

def _inject_canvas_target_markers(
    draft_text: str,
    selected_text: str,
) -> tuple[str, bool]:
    source = str(draft_text or "")
    selected = str(selected_text or "")
    if not source or not selected.strip():
        return source, False
    start = source.find(selected)
    if start < 0:
        return source, False
    end = start + len(selected)
    marked = (
        source[:start]
        + f"{CANVAS_TARGET_START}\n"
        + selected
        + f"\n{CANVAS_TARGET_END}"
        + source[end:]
    )
    return marked, True

# ── Context-window guard ───────────────────────────────────────────────────
