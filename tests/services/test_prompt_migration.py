from __future__ import annotations

import unittest

from shared.services.llm.manager import LLMManager


class PromptTemplateSetTests(unittest.TestCase):
    def test_prompt_set_keeps_explicit_values(self):
        manager = LLMManager()
        manager.set_prompt_set(
            {
                "mindmap_system": "Eigene Systemregel",
                "mindmap_user": "Eigener User-Prompt {query}",
            }
        )

        prompts = manager.get_prompt_set()
        self.assertEqual(prompts["mindmap_system"], "Eigene Systemregel")
        self.assertEqual(prompts["mindmap_user"], "Eigener User-Prompt {query}")

    def test_custom_mindmap_user_prompt_is_not_overwritten(self):
        custom_prompt = (
            "Erstelle eine MindMap.\n"
            "Ausgabe:\n"
            "```mindmap\n"
            "Start\n"
            "  Eigener Ast\n"
            "    Blatt :: \"Zitat\"\n"
            "```"
        )
        manager = LLMManager()
        manager.set_prompt_set({"mindmap_user": custom_prompt})
        prompts = manager.get_prompt_set()
        self.assertEqual(prompts["mindmap_user"], custom_prompt)

    def test_empty_prompt_values_fall_back_to_defaults(self):
        manager = LLMManager()
        defaults = manager.get_prompt_defaults()
        manager.set_prompt_set({"mindmap_user": "   "})
        prompts = manager.get_prompt_set()
        self.assertEqual(prompts["mindmap_user"], defaults["mindmap_user"])


if __name__ == "__main__":
    unittest.main()
