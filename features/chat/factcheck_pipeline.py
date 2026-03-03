"""Fact-check pipeline mixin used by chat dock."""
from __future__ import annotations

import os
import re

from .factcheck_utils import (
    compose_fact_check_markdown,
    parse_fact_candidates,
    parse_single_fact_verification,
    suggest_fact_limit,
    validate_fact_check_response,
)


class FactCheckPipelineMixin:
    """Encapsulates extract-then-verify fact-check workflow."""

    def _reset_fact_pipeline_state(self):
        self._pending_fact_check = False
        self._pending_fact_stage = ""
        self._pending_fact_target_text = ""
        self._pending_fact_target_label = ""
        self._pending_fact_sources = []
        self._pending_fact_facts = []
        self._pending_fact_results = []
        self._pending_fact_index = 0

    def _send_fact_check(self):
        if not self.llm.is_model_loaded():
            self.history.add_message(
                "system",
                "⚠ No model loaded. Load a GGUF model first.",
            )
            return
        if bool(getattr(self, "_aux_generating", False)):
            self.history.add_message(
                "system",
                "⚠ Eine Hintergrundaufgabe läuft bereits. Bitte kurz warten.",
            )
            return

        ctx: dict = {}
        collector = getattr(self, "_collect_shared_context", None)
        if callable(collector):
            ctx = collector()
        elif self._context_getter:
            raw = self._context_getter()
            if isinstance(raw, dict):
                ctx = raw

        grounding_has_sources = bool(ctx.get("grounding_has_sources", False))
        if not grounding_has_sources:
            self.history.add_message(
                "system",
                "⚠ Faktencheck benötigt Quellen. "
                "Bitte mindestens ein Dokument auswählen und/oder RAG-Treffer erzeugen.",
            )
            return

        file_contents = list(ctx.get("file_contents", []) or [])
        rag_results = list(ctx.get("rag_results", []) or [])

        source_files = [
            (name, content)
            for name, content in file_contents
            if not str(name).startswith("Draft:")
        ]

        selected_text = str(ctx.get("selected_text", "") or "").strip()
        target_text = ""
        target_label = ""

        if selected_text:
            target_text = selected_text
            target_label = "markierte Draft-Auswahl"
        else:
            for name, content in file_contents:
                if str(name).startswith("Draft:") and str(content or "").strip():
                    target_text = str(content).strip()
                    target_label = str(name)
                    break

        if not target_text:
            typed_text = self.input_box.toPlainText().strip()
            if typed_text:
                target_text = typed_text
                target_label = "Text aus Eingabefeld"

        if not target_text:
            self.history.add_message(
                "system",
                "⚠ Kein Zieltext für Faktencheck gefunden. "
                "Markiere Text im Draft-Workspace oder aktiviere Draft als Kontextquelle.",
            )
            return

        source_contexts: list[tuple[str, str]] = []
        for name, content in source_files:
            clean_name = str(name or "").strip()
            clean_content = str(content or "").strip()
            if not clean_name or not clean_content:
                continue
            source_contexts.append((clean_name, clean_content))
        for path, _score, excerpt in rag_results:
            label = os.path.basename(str(path or "").strip())
            label = label or str(path or "").strip() or "RAG Results"
            text = str(excerpt or "").strip()
            if not text:
                continue
            source_contexts.append((label, text))

        if not source_contexts:
            self.history.add_message(
                "system",
                "⚠ Für den Faktencheck wurden keine verwertbaren Quelltexte gefunden.",
            )
            return

        self.history.add_message("user", f"🔎 Faktencheck: {target_label or 'Zieltext'}")
        self._pending_apply_to_canvas = False
        self._pending_selected_text = ""
        self._pending_user_message = ""
        self.history.reset_feedback()
        self._reset_fact_pipeline_state()

        self._pending_fact_check = True
        self._pending_fact_stage = "extract"
        self._pending_fact_target_text = target_text
        self._pending_fact_target_label = target_label or "Zieltext"
        self._pending_fact_sources = source_contexts
        self._pending_fact_facts = []
        self._pending_fact_results = []
        self._pending_fact_index = 0

        self.history.add_message(
            "system",
            "⏳ Faktencheck gestartet: Extrahiere überprüfbare Fakten aus dem Zieltext…",
        )
        self._start_fact_extract_call()

    def _start_fact_extract_call(self):
        if not self._pending_fact_check or self._pending_fact_stage != "extract":
            return

        target_text = self._pending_fact_target_text.strip()
        if not target_text:
            self.history.add_message(
                "system", "⚠ Faktencheck abgebrochen: Zieltext fehlt."
            )
            self._reset_fact_pipeline_state()
            return

        fact_limit = suggest_fact_limit(target_text)
        request = self.llm.render_prompt_template(
            "fact_extract_user",
            {"fact_limit": str(fact_limit)},
        ).strip()

        gen_params = dict(self.model_panel.get_generation_params())
        base_max = max(256, int(gen_params.get("max_tokens", 1024)))
        max_tokens = max(384, min(base_max, 2200))
        max_tokens = max(max_tokens, min(2600, 220 + fact_limit * 22))
        gen_params["max_tokens"] = max_tokens
        gen_params["temperature"] = min(
            float(gen_params.get("temperature", 0.7)),
            0.35,
        )

        started = self.llm.send_message(
            user_message=request,
            file_contents=[("Zieltext", target_text)],
            rag_results=[],
            selected_text="",
            chat_history=[],
            selection_apply_mode=False,
            grounding_required=False,
            grounding_has_sources=True,
            system_prompt_key="fact_extract_system",
            **gen_params,
        )
        if not started:
            self.history.add_message(
                "system", "⚠ Faktenextraktion konnte nicht gestartet werden."
            )
            self._reset_fact_pipeline_state()

    def _start_next_fact_verify_call(self):
        if not self._pending_fact_check or self._pending_fact_stage != "verify":
            return

        if self._pending_fact_index >= len(self._pending_fact_facts):
            markdown = compose_fact_check_markdown(
                self._pending_fact_results,
                self._pending_fact_target_label,
            )
            note = validate_fact_check_response(
                markdown,
                self._pending_fact_target_text,
                self._pending_fact_sources,
            )
            if note:
                note_text = re.sub(r"^\s*⚠\s*", "", note).strip()
                markdown = f"{markdown}\n\n---\n\n## Qualitätsprüfung\n{note_text}"

            if self._fact_result_handler is not None:
                ok, info = self._fact_result_handler(
                    self._pending_fact_target_label or "Faktencheck",
                    markdown,
                )
                if ok:
                    self.history.add_message(
                        "system",
                        f"✅ Faktencheck in neuem Draft-Tab erstellt: {info}",
                    )
                else:
                    self.history.add_message(
                        "system",
                        "⚠ Faktencheck konnte nicht im Draft-Workspace geöffnet "
                        f"werden: {info}",
                    )
                    self.history.add_message("assistant", markdown)
            else:
                self.history.add_message("assistant", markdown)
            self._reset_fact_pipeline_state()
            return

        fact = self._pending_fact_facts[self._pending_fact_index]
        allowed_sources = ", ".join(
            dict.fromkeys(
                name for name, _ in self._pending_fact_sources if str(name).strip()
            )
        )
        request = self.llm.render_prompt_template(
            "fact_verify_user",
            {
                "allowed_sources": allowed_sources or "Kontextquellen",
                "fact": fact,
            },
        ).strip()

        gen_params = dict(self.model_panel.get_generation_params())
        gen_params["max_tokens"] = max(
            100,
            min(int(gen_params.get("max_tokens", 220)), 260),
        )
        gen_params["temperature"] = min(
            float(gen_params.get("temperature", 0.7)),
            0.25,
        )

        started = self.llm.send_message(
            user_message=request,
            file_contents=self._pending_fact_sources,
            rag_results=[],
            selected_text="",
            chat_history=[],
            selection_apply_mode=False,
            grounding_required=True,
            grounding_has_sources=bool(self._pending_fact_sources),
            system_prompt_key="fact_verify_system",
            **gen_params,
        )
        if not started:
            self.history.add_message(
                "system",
                "⚠ Faktprüfung konnte nicht fortgesetzt werden.",
            )
            self._reset_fact_pipeline_state()

    def _handle_fact_pipeline_complete(self, response: str):
        if self._pending_fact_stage == "extract":
            facts = parse_fact_candidates(response, self._pending_fact_target_text)
            if not facts:
                self.history.add_message(
                    "system",
                    "⚠ Es konnten keine stabilen Fakten aus dem Zieltext extrahiert werden.",
                )
                self._reset_fact_pipeline_state()
                return
            self._pending_fact_facts = facts
            self._pending_fact_results = []
            self._pending_fact_index = 0
            self._pending_fact_stage = "verify"
            self.history.add_message(
                "system",
                f"⏳ Prüfe {len(facts)} Fakten einzeln gegen die Quellen…",
            )
            self._start_next_fact_verify_call()
            return

        if self._pending_fact_stage == "verify":
            if self._pending_fact_index < len(self._pending_fact_facts):
                fact = self._pending_fact_facts[self._pending_fact_index]
                record = parse_single_fact_verification(
                    response,
                    fact,
                    self._pending_fact_index,
                    self._pending_fact_sources,
                )
                self._pending_fact_results.append(record)
                self._pending_fact_index += 1
            self._start_next_fact_verify_call()
            return

        self._reset_fact_pipeline_state()
