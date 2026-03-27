from __future__ import annotations

from studio.importer.dialog_ui import FileImportDialogUIMixin


class _TabsStub:
    def __init__(self, current_index: int = 0):
        self._current_index = int(current_index)
        self._widgets: list[object] = []
        self._labels: list[str] = []

    def addTab(self, widget, label: str) -> int:
        self._widgets.append(widget)
        self._labels.append(str(label))
        return len(self._widgets) - 1

    def removeTab(self, index: int):
        del self._widgets[index]
        del self._labels[index]

    def indexOf(self, widget) -> int:
        try:
            return self._widgets.index(widget)
        except ValueError:
            return -1

    def clear(self):
        self._widgets.clear()
        self._labels.clear()
        self._current_index = 0

    def count(self) -> int:
        return len(self._widgets)

    def currentIndex(self) -> int:
        return self._current_index

    def setCurrentIndex(self, index: int):
        self._current_index = int(index)

    def setTabText(self, index: int, label: str):
        self._labels[index] = str(label)


class _DualTabsStub(_TabsStub):
    def show(self):
        return None


class _SplitterStub:
    def __init__(self):
        self.widgets: list[object] = []
        self.sizes: list[int] = []

    def addWidget(self, widget):
        self.widgets.append(widget)

    def setSizes(self, sizes: list[int]):
        self.sizes = list(sizes)


class _StackStub:
    def __init__(self):
        self.current = 0

    def setCurrentIndex(self, index: int):
        self.current = int(index)


class _ButtonStub:
    def __init__(self):
        self.text = ""
        self.tooltip = ""

    def setText(self, text: str):
        self.text = str(text)

    def setToolTip(self, tooltip: str):
        self.tooltip = str(tooltip)


class _EditorStub:
    def isReadOnly(self) -> bool:
        return True


class _PreviewStub:
    def __init__(self):
        self.editor = _EditorStub()


class _DialogStub(FileImportDialogUIMixin):
    def __init__(self):
        self._user_mode = "simple"
        self._tabs = _TabsStub(current_index=0)
        self._pdf_tab_widget = object()
        self._markdown_tab_widget = object()
        self._pdf_tab_index = self._tabs.addTab(self._pdf_tab_widget, "PDF")
        self._markdown_tab_index = self._tabs.addTab(self._markdown_tab_widget, "MD")
        self._preview = _PreviewStub()
        self._dual_view_splitter = _SplitterStub()
        self._dual_markdown_tabs = _DualTabsStub(current_index=0)
        self._right_stack = _StackStub()
        self._btn_toggle_split_view = _ButtonStub()
        self._tabs_page_index = 0
        self._dual_view_page_index = 1
        self._split_view_active = False
        self._split_view_origin_tab_index = -1


def test_toggle_parallel_view_moves_widgets_and_restores_tab():
    dialog = _DialogStub()

    dialog._toggle_split_view()

    assert dialog._split_view_active is True
    assert dialog._right_stack.current == 1
    assert dialog._tabs.count() == 0
    assert dialog._dual_view_splitter.widgets == [
        dialog._pdf_tab_widget,
        dialog._dual_markdown_tabs,
    ]
    assert dialog._dual_markdown_tabs.count() == 1
    assert dialog._dual_markdown_tabs.indexOf(dialog._markdown_tab_widget) == 0

    dialog._toggle_split_view()

    assert dialog._split_view_active is False
    assert dialog._right_stack.current == 0
    assert dialog._tabs.count() == 2
    assert dialog._tabs.currentIndex() == 0
