from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

import pytest
from PySide6.QtWidgets import QMainWindow

from shared.config.setting_keys import ThemeSettingsKeys
from studio.canvas.preview.pane import CanvasPreviewPane
from studio.controllers.theme_ctrl import ThemeController
from studio.controllers.zoom_ctrl import ZoomController


pytestmark = pytest.mark.usefixtures("qt_app")


class _SettingsStub:
    def __init__(self, values: dict[str, object] | None = None):
        self.values = dict(values or {})

    def value(self, key: str, default):
        return self.values.get(key, default)

    def setValue(self, key: str, value: object):
        self.values[key] = value

    def sync(self):
        return None


class ThemeControllerIntegrationTests(unittest.TestCase):
    def test_apply_theme_id_persists_setting_and_schedules_autosave(self):
        settings = _SettingsStub({ThemeSettingsKeys.UI_THEME: "dark"})
        window = QMainWindow()
        window._theme_actions = {}
        autosave = Mock()
        controller = ThemeController(
            app_settings=settings,  # type: ignore[arg-type]
            parent_window=window,
            autosave_schedule_fn=autosave,
        )

        with patch("studio.controllers.theme_ctrl.apply_theme", return_value="light"):
            controller.apply_theme_id("light", persist=True)

        self.assertEqual(settings.values[ThemeSettingsKeys.UI_THEME], "light")
        autosave.assert_called_once_with(220)
        window.deleteLater()

    def test_apply_preview_page_margin_settings_persists_normalized_values(self):
        previous_enabled, previous_em = CanvasPreviewPane.global_page_margin_settings()
        settings = _SettingsStub()
        window = QMainWindow()
        window._action_page_margin_enabled = None
        window._page_margin_actions = []
        controller = ThemeController(
            app_settings=settings,  # type: ignore[arg-type]
            parent_window=window,
            autosave_schedule_fn=Mock(),
        )
        try:
            controller.apply_preview_page_margin_settings(
                {"enabled": "false", "em": "not-a-float"}
            )
            enabled, em = CanvasPreviewPane.global_page_margin_settings()
            self.assertFalse(enabled)
            self.assertAlmostEqual(em, CanvasPreviewPane._PAGE_MARGIN_DEFAULT_EM, places=3)
            self.assertFalse(settings.values[ThemeSettingsKeys.PREVIEW_PAGE_MARGIN_ENABLED])
            self.assertAlmostEqual(
                float(settings.values[ThemeSettingsKeys.PREVIEW_PAGE_MARGIN_EM]),
                CanvasPreviewPane._PAGE_MARGIN_DEFAULT_EM,
                places=3,
            )
        finally:
            CanvasPreviewPane.apply_global_page_margin_settings(
                enabled=previous_enabled,
                em=previous_em,
            )
            window.deleteLater()


class ZoomControllerIntegrationTests(unittest.TestCase):
    def test_increase_active_prefers_focused_markdown_editor(self):
        canvas = Mock()
        show_status = Mock()
        controller = ZoomController(canvas=canvas, show_status=show_status)
        editor = Mock()
        editor.increase_zoom.return_value = True
        editor.zoom_percent.return_value = 130

        with (
            patch.object(controller, "_focused_markdown_editor", return_value=editor),
            patch.object(controller, "_is_focus_on_html_preview", return_value=False),
        ):
            controller.increase_active()

        show_status.assert_called_once_with("Markdown-Ansicht: 130%", 1500)

    def test_increase_active_uses_preview_when_preview_is_focused(self):
        canvas = Mock()
        canvas.increase_preview_text_size.return_value = True
        canvas.preview_zoom_percent.return_value = 120
        show_status = Mock()
        controller = ZoomController(canvas=canvas, show_status=show_status)

        with (
            patch.object(controller, "_focused_markdown_editor", return_value=None),
            patch.object(controller, "_is_focus_on_html_preview", return_value=True),
        ):
            controller.increase_active()

        show_status.assert_called_once_with("HTML-Vorschau: 120%", 1500)

    def test_set_canvas_view_mode_updates_panel_and_status(self):
        canvas = Mock()
        show_status = Mock()
        controller = ZoomController(canvas=canvas, show_status=show_status)
        panel = Mock()
        canvas_controller = Mock()
        canvas_controller.resolve_active_split_panel.return_value = panel

        controller.set_canvas_view_mode("preview", canvas_controller=canvas_controller)

        panel.set_view_mode.assert_called_once_with("preview")
        show_status.assert_called_once_with("Ansicht: nur HTML", 1800)


if __name__ == "__main__":
    unittest.main()

