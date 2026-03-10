from __future__ import annotations

import unittest

from studio.canvas.preview.pane import CanvasPreviewPane


class PreviewPageMarginGlobalTests(unittest.TestCase):
    def test_apply_global_page_margin_settings_updates_global_defaults(self):
        previous_enabled, previous_em = CanvasPreviewPane.global_page_margin_settings()
        try:
            CanvasPreviewPane.apply_global_page_margin_settings(
                enabled=False,
                em=2.7,  # nearest preset should be 3.0 ("Breit")
            )
            enabled, em = CanvasPreviewPane.global_page_margin_settings()
            self.assertFalse(enabled)
            self.assertAlmostEqual(em, 3.0, places=3)
        finally:
            CanvasPreviewPane.apply_global_page_margin_settings(
                enabled=previous_enabled,
                em=previous_em,
            )

    def test_apply_global_preview_theme_updates_global_default(self):
        previous = CanvasPreviewPane.global_preview_theme_id()
        try:
            CanvasPreviewPane.apply_global_preview_theme("vivid")
            self.assertEqual(CanvasPreviewPane.global_preview_theme_id(), "vivid")
            CanvasPreviewPane.apply_global_preview_theme("unknown-theme")
            self.assertEqual(CanvasPreviewPane.global_preview_theme_id(), "classic")
        finally:
            CanvasPreviewPane.apply_global_preview_theme(previous)

    def test_preview_theme_options_expose_accent_theme(self):
        options = dict(CanvasPreviewPane.preview_theme_options())
        self.assertIn("classic", options)
        self.assertIn("accent", options)
        self.assertIn("vivid", options)


if __name__ == "__main__":
    unittest.main()
