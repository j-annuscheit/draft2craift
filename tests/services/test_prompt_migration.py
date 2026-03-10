from __future__ import annotations

import unittest

from shared.services.llm.manager import LLMManager


LEGACY_MINDMAP_SYSTEM = (
    "Du erstellst eine MindMap aus Kontext.\n"
    "Antworte NUR mit genau einem Markdown-Codeblock vom Typ ```mindmap.\n"
    "Kein JSON."
)

LEGACY_MINDMAP_USER = (
    "Erstelle eine MindMap zur Frage: {query}\n"
    "Maximal {max_nodes} Knoten.\n"
    "Nutze nur diesen Kontext:\n"
    "{context}\n\n"
    "Ausgabeformat streng:\n"
    "```mindmap\n"
    "[altes_format]\n"
    "```\n"
    "Nur ein einziger Codeblock."
)


class PromptMigrationTests(unittest.TestCase):
    def test_legacy_mindmap_prompts_are_upgraded_to_current_defaults(self):
        manager = LLMManager()
        manager.set_prompt_set(
            {
                "mindmap_system": LEGACY_MINDMAP_SYSTEM,
                "mindmap_user": LEGACY_MINDMAP_USER,
            }
        )

        prompts = manager.get_prompt_set()
        defaults = manager.get_prompt_defaults()
        self.assertEqual(prompts["mindmap_system"], defaults["mindmap_system"])
        self.assertEqual(prompts["mindmap_user"], defaults["mindmap_user"])
        self.assertIn("{Blatttitel}", prompts["mindmap_user"])
        self.assertIn("{Unter_Unterpunkt}", prompts["mindmap_user"])
        self.assertIn(
            "Unterpunkte dürfen niemals Oberbegriffe ihres Elternknotens sein.",
            prompts["mindmap_user"],
        )

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


if __name__ == "__main__":
    unittest.main()
