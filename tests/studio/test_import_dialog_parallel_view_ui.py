from __future__ import annotations

from studio.importer.dialog import FileImportDialog


def test_parallel_view_shows_both_panes(qt_app) -> None:
    dialog = FileImportDialog()
    dialog.show()
    qt_app.processEvents()

    dialog._toggle_split_view()
    qt_app.processEvents()

    assert dialog._split_view_active is True
    assert dialog._right_stack.currentIndex() == dialog._dual_view_page_index
    assert dialog._dual_view_splitter.count() == 2
    assert dialog._pdf_tab_widget.isVisible() is True
    assert dialog._dual_markdown_tabs.isVisible() is True
    assert dialog._dual_markdown_tabs.indexOf(dialog._markdown_tab_widget) >= 0
    assert dialog._pdf_tab_widget.geometry().width() > 0
    assert dialog._dual_markdown_tabs.geometry().width() > 0

    dialog.close()
    qt_app.processEvents()
