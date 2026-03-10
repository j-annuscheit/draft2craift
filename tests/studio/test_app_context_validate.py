from __future__ import annotations

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
        with self.assertRaises(RuntimeError) as err:
            ctx.validate()
        self.assertIn("theme_controller", str(err.exception))
        self.assertIn("chat_dock", str(err.exception))

    def test_validate_passes_when_all_bindings_exist(self):
        ctx = _build_context()
        ctx.bind_theme_controller(object())
        ctx.bind_autosave_controller(object())
        ctx.bind_knowledge_controller(object())
        ctx.bind_chat_controller(object())
        ctx.bind_docks(
            knowledge_dock=object(),
            chat_dock=object(),
        )
        ctx.validate()


if __name__ == "__main__":
    unittest.main()
