from __future__ import annotations

import unittest

from features.canvas.preview import CanvasPreviewPane


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


if __name__ == "__main__":
    unittest.main()
