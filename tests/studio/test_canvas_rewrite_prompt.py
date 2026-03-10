from __future__ import annotations

import unittest

from shared.services.llm.manager import LLMManager


class CanvasRewritePromptTests(unittest.TestCase):
    def test_rewrite_block_is_repeated_after_context(self):
        manager = LLMManager()
        prompt = manager._build_prompt(
            user_message="Bitte kürzen.",
            file_contents=[("Draft: Demo", "Voller Draft-Inhalt")],
            rag_results=[("doc.md", 0.9, "Kontextauszug")],
            selected_text="ALT TEXT",
            chat_history=[],
            selection_apply_mode=True,
            grounding_required=False,
            grounding_has_sources=True,
            system_prompt_text=manager.get_prompt_set()["chat_system"],
        )

        self.assertIn("### Ende Kontext ###", prompt)
        self.assertIn("### WICHTIG: REWRITE-AUFTRAG (NACH KONTEXT) ###", prompt)
        self.assertEqual(prompt.count("[[CANVAS_REWRITE]]"), 2)
        self.assertEqual(prompt.count("[[/CANVAS_REWRITE]]"), 2)
        self.assertIn(
            "## DIESER TEXT WIRD ERSETZT (NUR DIESER ABSCHNITT)",
            prompt,
        )

    def test_no_rewrite_block_without_selection_apply_mode(self):
        manager = LLMManager()
        prompt = manager._build_prompt(
            user_message="Normale Frage.",
            file_contents=[("Draft: Demo", "Voller Draft-Inhalt")],
            rag_results=[],
            selected_text="ALT TEXT",
            chat_history=[],
            selection_apply_mode=False,
            grounding_required=False,
            grounding_has_sources=True,
            system_prompt_text=manager.get_prompt_set()["chat_system"],
        )

        self.assertNotIn("### WICHTIG: REWRITE-AUFTRAG (NACH KONTEXT) ###", prompt)
        self.assertEqual(prompt.count("[[CANVAS_REWRITE]]"), 0)
        self.assertEqual(prompt.count("[[/CANVAS_REWRITE]]"), 0)

    def test_rewrite_mode_forces_explicit_replacement_title(self):
        manager = LLMManager()
        manager.set_prompt_set(
            {"chat_section_selected_title": "## Ausgewählter Text (Draft)"}
        )
        prompt = manager._build_prompt(
            user_message="Bitte ändern.",
            file_contents=[],
            rag_results=[],
            selected_text="ALT TEXT",
            chat_history=[],
            selection_apply_mode=True,
            grounding_required=False,
            grounding_has_sources=True,
            system_prompt_text=manager.get_prompt_set()["chat_system"],
        )

        self.assertIn(
            "## DIESER TEXT WIRD ERSETZT (NUR DIESER ABSCHNITT)",
            prompt,
        )
        self.assertNotIn("## Ausgewählter Text (Draft)", prompt)

    def test_rewrite_mode_marks_selection_inside_draft_and_avoids_duplicate_block(self):
        manager = LLMManager()
        prompt = manager._build_prompt(
            user_message="Bitte ändern.",
            file_contents=[("Draft: Demo", "AAAA\nALT TEXT\nBBBB")],
            rag_results=[],
            selected_text="ALT TEXT",
            chat_history=[],
            selection_apply_mode=True,
            grounding_required=False,
            grounding_has_sources=True,
            system_prompt_text=manager.get_prompt_set()["chat_system"],
        )

        self.assertIn("[[CANVAS_TARGET_START]]\nALT TEXT\n[[CANVAS_TARGET_END]]", prompt)
        self.assertIn(
            "Text außerhalb dieser Marker darf nicht in der Antwort erscheinen.",
            prompt,
        )
        self.assertNotIn(
            "## DIESER TEXT WIRD ERSETZT (NUR DIESER ABSCHNITT)\n```\nALT TEXT\n```",
            prompt,
        )

    def test_rewrite_enforcer_contains_small_model_guardrails(self):
        manager = LLMManager()
        prompt = manager._build_prompt(
            user_message="Bitte Text überarbeiten.",
            file_contents=[],
            rag_results=[],
            selected_text="ALT TEXT",
            chat_history=[],
            selection_apply_mode=True,
            grounding_required=False,
            grounding_has_sources=True,
            system_prompt_text=manager.get_prompt_set()["chat_system"],
        )

        self.assertIn("Rewrite-Pflicht (streng, auch für kleine Modelle)", prompt)
        self.assertIn("Löschen/Entfernen/Streichen", prompt)
        self.assertIn("Vermeide allgemeine Floskeln", prompt)
        self.assertIn("halte es exakt ein", prompt)


if __name__ == "__main__":
    unittest.main()
