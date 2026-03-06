from __future__ import annotations

import unittest

from features.canvas.selection_ops import CanvasSelectionActions


class _Signal:
    def connect(self, _slot):
        return None

    def disconnect(self, _slot):
        return None


class _Cursor:
    def __init__(self, *, has_selection: bool, start: int = 0, end: int = 0):
        self._has_selection = bool(has_selection)
        self._start = int(start)
        self._end = int(end)

    def hasSelection(self) -> bool:
        return self._has_selection

    def selectionStart(self) -> int:
        return self._start

    def selectionEnd(self) -> int:
        return self._end


class _Document:
    def __init__(self, revision: int = 1):
        self._revision = int(revision)

    def revision(self) -> int:
        return self._revision


class _EditorStub:
    def __init__(
        self,
        *,
        full_text: str,
        selected_text: str = "",
        cursor_has_selection: bool = False,
        cursor_start: int = 0,
        cursor_end: int = 0,
        has_focus: bool = True,
    ):
        self._full_text = str(full_text or "")
        self._selected_text = str(selected_text or "")
        self._cursor = _Cursor(
            has_selection=cursor_has_selection,
            start=cursor_start,
            end=cursor_end,
        )
        self._has_focus = bool(has_focus)
        self._document = _Document()
        self.copyAvailable = _Signal()

    def get_selected_text(self) -> str:
        return self._selected_text

    def get_full_text(self) -> str:
        return self._full_text

    def textCursor(self) -> _Cursor:
        return self._cursor

    def document(self) -> _Document:
        return self._document

    def hasFocus(self) -> bool:
        return self._has_focus


class _PanelStub:
    def __init__(
        self,
        *,
        editor: _EditorStub,
        preview_selected_text: str = "",
        should_use_preview: bool = False,
        markdown_visible: bool = True,
        preview_visible: bool = True,
        preview_has_focus: bool = True,
    ):
        self.editor = editor
        self._preview_selected_text = str(preview_selected_text or "")
        self._should_use_preview = bool(should_use_preview)
        self._markdown_visible = bool(markdown_visible)
        self._preview_visible = bool(preview_visible)
        self._preview_has_focus = bool(preview_has_focus)
        self._preview_copy_slot = None

    def should_use_preview_selection(self) -> bool:
        return self._should_use_preview

    def get_preview_selected_text(self) -> str:
        return self._preview_selected_text

    def is_markdown_visible(self) -> bool:
        return self._markdown_visible

    def is_preview_visible(self) -> bool:
        return self._preview_visible

    def preview_has_focus(self) -> bool:
        return self._preview_has_focus

    def connect_preview_copy_available(self, slot) -> bool:
        self._preview_copy_slot = slot
        return True

    def disconnect_preview_copy_available(self, _slot) -> bool:
        self._preview_copy_slot = None
        return True


class _TabWidgetStub:
    def __init__(self):
        self.currentChanged = _Signal()


class _TabsStub:
    def __init__(self, panel: _PanelStub):
        self._panel = panel
        self.tab_widget = _TabWidgetStub()

    def current_panel(self) -> _PanelStub:
        return self._panel


class CanvasSelectionOpsTests(unittest.TestCase):
    def test_get_selected_text_uses_preview_selection_in_both_mode(self):
        editor = _EditorStub(full_text="Alpha beta gamma", selected_text="")
        panel = _PanelStub(
            editor=editor,
            preview_selected_text="Alpha",
            should_use_preview=False,  # both-mode path
            markdown_visible=True,
            preview_visible=True,
        )
        actions = CanvasSelectionActions(_TabsStub(panel))

        selected = actions.get_selected_text(allow_cached=False)
        self.assertEqual(selected, "Alpha")

    def test_get_selected_text_prefers_editor_when_both_have_selection(self):
        editor = _EditorStub(
            full_text="Alpha beta gamma",
            selected_text="beta",
            cursor_has_selection=True,
            cursor_start=6,
            cursor_end=10,
        )
        panel = _PanelStub(
            editor=editor,
            preview_selected_text="Alpha",
            should_use_preview=False,
            markdown_visible=True,
            preview_visible=True,
        )
        actions = CanvasSelectionActions(_TabsStub(panel))

        selected = actions.get_selected_text(allow_cached=False)
        self.assertEqual(selected, "beta")

    def test_get_selected_span_prefers_editor_selection(self):
        editor = _EditorStub(
            full_text="Alpha beta gamma",
            selected_text="beta",
            cursor_has_selection=True,
            cursor_start=6,
            cursor_end=10,
        )
        panel = _PanelStub(
            editor=editor,
            preview_selected_text="Alpha",
            should_use_preview=False,
            markdown_visible=True,
            preview_visible=True,
        )
        actions = CanvasSelectionActions(_TabsStub(panel))

        self.assertEqual(actions.get_selected_span(allow_cached=False), (6, 10))

    def test_replace_selected_text_uses_preview_path_in_both_mode(self):
        editor = _EditorStub(full_text="Alpha beta gamma", selected_text="")
        panel = _PanelStub(
            editor=editor,
            preview_selected_text="Alpha",
            should_use_preview=False,
            markdown_visible=True,
            preview_visible=True,
        )
        actions = CanvasSelectionActions(_TabsStub(panel))
        captured: dict[str, object] = {}

        def _capture_replace(_editor, start: int, end: int, replacement: str):
            captured["start"] = int(start)
            captured["end"] = int(end)
            captured["replacement"] = replacement

        actions._replace_range = _capture_replace  # type: ignore[method-assign]

        ok, info = actions.replace_selected_text("Z", "Alpha")
        self.assertTrue(ok)
        self.assertIn("Applied", info)
        self.assertEqual(captured, {"start": 0, "end": 5, "replacement": "Z"})

    def test_preview_copy_available_caches_selection_for_later_use(self):
        editor = _EditorStub(full_text="Alpha beta gamma", selected_text="")
        panel = _PanelStub(
            editor=editor,
            preview_selected_text="Alpha",
            should_use_preview=True,
            markdown_visible=False,
            preview_visible=True,
        )
        actions = CanvasSelectionActions(_TabsStub(panel))

        actions._on_preview_copy_available(True)
        panel._preview_selected_text = ""

        self.assertEqual(actions.get_selected_text(allow_cached=False), "")
        self.assertEqual(actions.get_selected_text(allow_cached=True), "Alpha")
        self.assertEqual(actions.get_selected_text(allow_cached=True), "")

    def test_get_selected_text_can_peek_cached_without_consuming(self):
        editor = _EditorStub(full_text="Alpha beta gamma", selected_text="")
        panel = _PanelStub(
            editor=editor,
            preview_selected_text="Alpha",
            should_use_preview=True,
            markdown_visible=False,
            preview_visible=True,
        )
        actions = CanvasSelectionActions(_TabsStub(panel))

        actions._on_preview_copy_available(True)
        panel._preview_selected_text = ""

        self.assertEqual(
            actions.get_selected_text(
                allow_cached=True,
                consume_cached=False,
            ),
            "Alpha",
        )
        self.assertEqual(
            actions.get_selected_text(
                allow_cached=True,
                consume_cached=False,
            ),
            "Alpha",
        )
        self.assertEqual(actions.get_selected_text(allow_cached=True), "Alpha")
        self.assertEqual(actions.get_selected_text(allow_cached=True), "")

    def test_preview_copy_unavailable_clears_cached_selection(self):
        editor = _EditorStub(full_text="Alpha beta gamma", selected_text="")
        panel = _PanelStub(
            editor=editor,
            preview_selected_text="Alpha",
            should_use_preview=True,
            markdown_visible=False,
            preview_visible=True,
        )
        actions = CanvasSelectionActions(_TabsStub(panel))

        actions._on_preview_copy_available(True)
        actions._on_preview_copy_available(False)
        panel._preview_selected_text = ""

        self.assertEqual(actions.get_selected_text(allow_cached=True), "")

    def test_editor_copy_unavailable_preserves_cached_selection_on_focus_handoff(self):
        editor = _EditorStub(
            full_text="Alpha beta gamma",
            selected_text="Alpha",
            cursor_has_selection=True,
            cursor_start=0,
            cursor_end=5,
            has_focus=True,
        )
        panel = _PanelStub(editor=editor)
        actions = CanvasSelectionActions(_TabsStub(panel))

        actions._on_editor_copy_available(True)
        editor._selected_text = ""
        editor._cursor._has_selection = False
        editor._has_focus = False  # user moved focus to chat controls
        actions._on_editor_copy_available(False)

        self.assertEqual(actions.get_selected_text(allow_cached=True), "Alpha")
        self.assertEqual(actions.get_selected_text(allow_cached=True), "")

    def test_preview_copy_unavailable_preserves_cached_selection_on_focus_handoff(self):
        editor = _EditorStub(full_text="Alpha beta gamma", selected_text="")
        panel = _PanelStub(
            editor=editor,
            preview_selected_text="Alpha",
            should_use_preview=True,
            markdown_visible=False,
            preview_visible=True,
            preview_has_focus=True,
        )
        actions = CanvasSelectionActions(_TabsStub(panel))

        actions._on_preview_copy_available(True)
        panel._preview_selected_text = ""
        panel._preview_has_focus = False  # user moved focus to chat controls
        actions._on_preview_copy_available(False)

        self.assertEqual(actions.get_selected_text(allow_cached=True), "Alpha")
        self.assertEqual(actions.get_selected_text(allow_cached=True), "")

    def test_replace_selected_text_uses_cached_span_when_preview_selection_is_ambiguous(self):
        editor = _EditorStub(full_text="foo bar foo", selected_text="")
        panel = _PanelStub(
            editor=editor,
            preview_selected_text="foo",
            should_use_preview=False,
            markdown_visible=True,
            preview_visible=True,
        )
        actions = CanvasSelectionActions(_TabsStub(panel))
        actions._cache_span(panel, 8, 11)  # second "foo"
        captured: dict[str, object] = {}

        def _capture_replace(_editor, start: int, end: int, replacement: str):
            captured["start"] = int(start)
            captured["end"] = int(end)
            captured["replacement"] = replacement

        actions._replace_range = _capture_replace  # type: ignore[method-assign]
        ok, info = actions.replace_selected_text("XYZ", "foo")

        self.assertTrue(ok)
        self.assertIn("cached span", info)
        self.assertEqual(captured, {"start": 8, "end": 11, "replacement": "XYZ"})

    def test_replace_selected_text_uses_cached_span_when_text_search_is_ambiguous(self):
        editor = _EditorStub(full_text="foo bar foo", selected_text="")
        panel = _PanelStub(
            editor=editor,
            preview_selected_text="",
            should_use_preview=False,
            markdown_visible=True,
            preview_visible=True,
        )
        actions = CanvasSelectionActions(_TabsStub(panel))
        actions._cache_span(panel, 8, 11)  # second "foo"
        captured: dict[str, object] = {}

        def _capture_replace(_editor, start: int, end: int, replacement: str):
            captured["start"] = int(start)
            captured["end"] = int(end)
            captured["replacement"] = replacement

        actions._replace_range = _capture_replace  # type: ignore[method-assign]
        ok, info = actions.replace_selected_text("XYZ", "foo")

        self.assertTrue(ok)
        self.assertIn("cached span", info)
        self.assertEqual(captured, {"start": 8, "end": 11, "replacement": "XYZ"})

    def test_replace_selected_text_uses_preferred_span_when_provided(self):
        editor = _EditorStub(full_text="foo bar foo", selected_text="")
        panel = _PanelStub(
            editor=editor,
            preview_selected_text="",
            should_use_preview=False,
            markdown_visible=True,
            preview_visible=True,
        )
        actions = CanvasSelectionActions(_TabsStub(panel))
        captured: dict[str, object] = {}

        def _capture_replace(_editor, start: int, end: int, replacement: str):
            captured["start"] = int(start)
            captured["end"] = int(end)
            captured["replacement"] = replacement

        actions._replace_range = _capture_replace  # type: ignore[method-assign]
        ok, info = actions.replace_selected_text("XYZ", "foo", (8, 11))

        self.assertTrue(ok)
        self.assertIn("selection span", info)
        self.assertEqual(captured, {"start": 8, "end": 11, "replacement": "XYZ"})

    def test_replace_selected_text_trims_trailing_newline_from_mapped_preview_span(self):
        editor = _EditorStub(full_text="A\nB\nC\nD\nE", selected_text="")
        panel = _PanelStub(
            editor=editor,
            preview_selected_text="C\nD",
            should_use_preview=True,
            markdown_visible=False,
            preview_visible=True,
        )
        actions = CanvasSelectionActions(_TabsStub(panel))
        captured: dict[str, object] = {}

        def _capture_replace(_editor, start: int, end: int, replacement: str):
            captured["start"] = int(start)
            captured["end"] = int(end)
            captured["replacement"] = replacement

        actions._replace_range = _capture_replace  # type: ignore[method-assign]
        actions._find_selection_span = lambda _src, _sel: (4, 8)  # type: ignore[method-assign]

        ok, info = actions.replace_selected_text("C'\nD'", "C\nD")

        self.assertTrue(ok)
        self.assertIn("Applied", info)
        # 4..8 maps to "C\nD\n"; expected selection is "C\nD", so end is trimmed.
        self.assertEqual(captured, {"start": 4, "end": 7, "replacement": "C'\nD'"})

    def test_replace_selected_text_keeps_trailing_newline_when_selection_has_it(self):
        editor = _EditorStub(full_text="A\nB\nC\nD\nE", selected_text="")
        panel = _PanelStub(
            editor=editor,
            preview_selected_text="C\nD\n",
            should_use_preview=True,
            markdown_visible=False,
            preview_visible=True,
        )
        actions = CanvasSelectionActions(_TabsStub(panel))
        captured: dict[str, object] = {}

        def _capture_replace(_editor, start: int, end: int, replacement: str):
            captured["start"] = int(start)
            captured["end"] = int(end)
            captured["replacement"] = replacement

        actions._replace_range = _capture_replace  # type: ignore[method-assign]
        actions._find_selection_span = lambda _src, _sel: (4, 8)  # type: ignore[method-assign]

        ok, info = actions.replace_selected_text("C'\nD'", "C\nD\n")

        self.assertTrue(ok)
        self.assertIn("Applied", info)
        self.assertEqual(captured, {"start": 4, "end": 8, "replacement": "C'\nD'"})


if __name__ == "__main__":
    unittest.main()
