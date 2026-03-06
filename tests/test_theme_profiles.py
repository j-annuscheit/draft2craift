from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from shell.theme import (
    apply_theme,
    available_themes,
    current_theme_id,
    normalize_theme_id,
    theme_tokens,
)


class ThemeProfilesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def test_available_themes_contains_requested_variants(self):
        ids = [theme_id for theme_id, _label in available_themes()]
        self.assertIn("light", ids)
        self.assertIn("dark", ids)
        self.assertIn("darker", ids)
        self.assertIn("colorful-light", ids)
        self.assertIn("colorful-dark", ids)

    def test_normalize_theme_id_accepts_alias(self):
        self.assertEqual(normalize_theme_id("colorful_light"), "colorful-light")
        self.assertEqual(normalize_theme_id("classic-dark"), "dark")
        self.assertEqual(normalize_theme_id("unknown"), "dark")

    def test_apply_theme_sets_current_theme(self):
        previous = current_theme_id()
        try:
            resolved = apply_theme(self._app, "colorful-dark")
            self.assertEqual(resolved, "colorful-dark")
            self.assertEqual(current_theme_id(), "colorful-dark")
            tokens = theme_tokens("colorful-dark")
            self.assertEqual(tokens["theme_id"], "colorful-dark")
            self.assertTrue(tokens["accent"].startswith("#"))
        finally:
            apply_theme(self._app, previous)


if __name__ == "__main__":
    unittest.main()
