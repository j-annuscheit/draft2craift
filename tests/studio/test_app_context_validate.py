from __future__ import annotations

from unittest.mock import patch
import unittest

from studio.app_context import AppContext


class _WindowStub:
    def statusBar(self):
        return None


def _build_context() -> AppContext:
    return AppContext(
        window=_WindowStub(),
        app_logger=object(),
        rag_system=object(),
        llm_manager=object(),
        project_manager=object(),
        app_settings=object(),
        file_registry={},
        user_mode="plus",
    )


class AppContextValidationTests(unittest.TestCase):
    def test_validate_raises_when_required_bindings_are_missing(self):
        ctx = _build_context()
        self.addCleanup(patch.stopall)
        patch.dict("os.environ", {}, clear=True).start()
        with self.assertRaises(RuntimeError) as err:
            ctx.validate()
        msg = str(err.exception)
        self.assertIn("theme_controller", msg)
        self.assertIn("chat_controller", msg)
        # Docks are no longer validated here — routed through controllers.
        self.assertNotIn("chat_dock", msg)
        self.assertNotIn("knowledge_dock", msg)

    def test_validate_passes_when_all_bindings_exist(self):
        ctx = _build_context()
        self.addCleanup(patch.stopall)
        patch.dict("os.environ", {}, clear=True).start()
        ctx.bind_theme_controller(object())
        ctx.bind_autosave_controller(object())
        ctx.bind_knowledge_controller(object())
        ctx.bind_chat_controller(object())
        ctx.validate()

    def test_validate_is_skipped_when_app_debug_is_disabled(self):
        ctx = _build_context()
        with patch.dict("os.environ", {"APP_DEBUG": "0"}, clear=True):
            ctx.validate()

    def test_validate_forced_when_app_debug_is_enabled(self):
        ctx = _build_context()
        with patch.dict("os.environ", {"APP_DEBUG": "1"}, clear=True):
            with self.assertRaises(RuntimeError):
                ctx.validate()


if __name__ == "__main__":
    unittest.main()
