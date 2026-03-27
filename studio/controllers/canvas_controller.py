"""Canvas-focused orchestration extracted from MainWindow."""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6.QtWidgets import QApplication, QDialog, QTabWidget, QWidget

from shared.domain.user_mode import resolve_feature_label
from studio.canvas.exporting.annotation_export import (
    AnnotationExportOptions,
    build_annotation_export_markdown,
    collect_annotation_export_data,
)
from studio.canvas.file_actions import CanvasFileActions
from studio.canvas.editor import MarkdownEditor
from studio.dialogs.annotation_export_dialog import AnnotationExportDialog

_LOG = logging.getLogger(__name__)

if TYPE_CHECKING:
    from studio.canvas.tabs import CanvasTabWidget
    from studio.chat.dock import ChatDock
    from studio.knowledge.dock import KnowledgeDock


class CanvasController:
    """Resolves active canvas/split targets and handles export orchestration."""

    def __init__(
        self,
        *,
        parent: QWidget,
        canvas: CanvasTabWidget,
        knowledge_dock: KnowledgeDock,
        chat_dock: ChatDock,
        show_status: Callable[[str, int], None],
    ):
        self._parent = parent
        self._canvas = canvas
        self._knowledge_dock = knowledge_dock
        self._chat_dock = chat_dock
        self._show_status = show_status

    @staticmethod
    def widget_belongs_to(widget: QWidget | None, root: QWidget | None) -> bool:
        current = widget
        while current is not None:
            if current is root:
                return True
            current = current.parentWidget()
        return False

    @staticmethod
    def editor_from_widget_chain(widget: QWidget | None) -> MarkdownEditor | None:
        current = widget
        while current is not None:
            editor = getattr(current, "editor", None)
            if isinstance(editor, MarkdownEditor):
                return editor
            current = current.parentWidget()
        return None

    @staticmethod
    def split_panel_from_widget_chain(widget: QWidget | None) -> QWidget | None:
        current = widget
        while current is not None:
            if (
                hasattr(current, "set_view_mode")
                and hasattr(current, "view_mode")
                and hasattr(current, "editor")
            ):
                return current
            current = current.parentWidget()
        return None

    def resolve_knowledge_panel_context(self) -> tuple[QWidget | None, object | None, str]:
        current = self._knowledge_dock.tab_widget.currentWidget()
        if current is self._knowledge_dock.doc_viewer:
            return (
                self._knowledge_dock.doc_viewer.tabs.current_panel(),
                self._knowledge_dock.doc_viewer.tabs,
                "viewer",
            )
        if current is self._knowledge_dock.rag_tab:
            return (
                self._knowledge_dock.rag_panel.tabs.current_panel(),
                self._knowledge_dock.rag_panel.tabs,
                "rag",
            )
        return None, None, ""

    def resolve_active_split_panel(self) -> QWidget | None:
        focus = QApplication.focusWidget()
        panel = self.split_panel_from_widget_chain(focus)
        if panel is not None:
            return panel

        if self.widget_belongs_to(focus, self._knowledge_dock):
            panel, _tabs, _scope = self.resolve_knowledge_panel_context()
            if panel is not None:
                return panel
        if self.widget_belongs_to(focus, self._chat_dock):
            return self._chat_dock.history.current_panel()

        return self._canvas.tabs.current_panel()

    def resolve_panel_tab_title(self, panel: QWidget | None) -> str:
        if panel is None:
            return ""
        node = panel
        while node is not None:
            host = node.parentWidget()
            if isinstance(host, QTabWidget):
                idx = host.indexOf(node)
                if idx < 0:
                    for probe in range(host.count()):
                        page = host.widget(probe)
                        if page is not None and self.widget_belongs_to(panel, page):
                            idx = probe
                            break
                if idx >= 0:
                    try:
                        tab_data = host.tabBar().tabData(idx)
                    except Exception:
                        _LOG.warning(
                            "CanvasController failed to read tab metadata (host=%r idx=%r)",
                            host,
                            idx,
                            exc_info=True,
                        )
                        tab_data = None
                    if isinstance(tab_data, str) and tab_data.strip():
                        return tab_data.strip()
                    label = str(host.tabText(idx) or "").strip()
                    if label.startswith("🔒 "):
                        label = label[2:].strip()
                    return label
            node = host
        return ""

    def resolve_active_export_target(self) -> dict[str, object]:
        focus = QApplication.focusWidget()
        panel: QWidget | None = None
        tabs = None
        scope = "draft"

        if self.widget_belongs_to(focus, self._knowledge_dock):
            panel, tabs, scope = self.resolve_knowledge_panel_context()
        elif self.widget_belongs_to(focus, self._chat_dock):
            panel = self._chat_dock.history.current_panel()
            tabs = None
            scope = "chat"

        if panel is None:
            panel = self._canvas.tabs.current_panel()
            tabs = self._canvas.tabs
            scope = "draft"

        tab_name = self.resolve_panel_tab_title(panel)
        if not tab_name:
            if scope == "chat":
                tab_name = self._chat_dock.history.current_tab_title()
            elif tabs is not None:
                try:
                    idx = int(tabs.tab_widget.currentIndex())
                    if idx >= 0:
                        tab_name = str(tabs.get_tab_full_title(idx) or "").strip()
                except Exception:
                    _LOG.warning(
                        "CanvasController failed to resolve active tab name",
                        exc_info=True,
                    )
                    tab_name = ""

        return {
            "panel": panel,
            "tabs": tabs,
            "scope": scope,
            "tab_name": tab_name,
        }

    def export_active_canvas_document(self):
        target = self.resolve_active_export_target()
        panel = target.get("panel")
        if panel is None:
            self._show_status("Kein exportierbares Canvas aktiv.", 2800)
            return
        tabs = target.get("tabs")
        scope = str(target.get("scope", "draft") or "draft")
        tab_name = str(target.get("tab_name", "") or "")
        base_tabs = tabs if tabs is not None else self._canvas.tabs
        exporter = CanvasFileActions(parent=self._parent, tabs=base_tabs)
        exporter.export_specific_panel(
            panel,
            default_format="pdf",
            panel_scope=scope,
            tab_name=tab_name,
        )

    @staticmethod
    def _resolve_annotation_source_text(panel: object) -> str:
        payload_getter = getattr(panel, "annotation_export_text", None)
        if callable(payload_getter):
            try:
                return str(payload_getter() or "")
            except Exception:
                return ""
        editor = getattr(panel, "editor", None)
        if editor is None:
            return ""
        getter = getattr(editor, "get_full_text", None)
        if callable(getter):
            try:
                return str(getter() or "")
            except Exception:
                return ""
        return str(getattr(editor, "toPlainText", lambda: "")() or "")

    @staticmethod
    def _label(mode: str, key: str, default: str) -> str:
        return resolve_feature_label(str(mode or ""), key, default)

    def export_panel_annotations_to_canvas(
        self,
        *,
        panel: object,
        panel_scope: str,
        tab_name: str,
        user_mode: str = "",
    ) -> bool:
        source_text = self._resolve_annotation_source_text(panel)
        if not source_text.strip():
            self._show_status(
                self._label(
                    user_mode,
                    "annotation.extract.status.empty",
                    "Keine Annotationen im aktiven Reiter gefunden.",
                ),
                3200,
            )
            return False

        scope = str(panel_scope or "").strip().lower() or "generic"
        title = str(tab_name or "").strip()
        data = collect_annotation_export_data(
            panel_scope=scope,
            tab_name=title,
            source_text=source_text,
        )
        if not data.has_entries:
            self._show_status(
                self._label(
                    user_mode,
                    "annotation.extract.status.empty",
                    "Keine Annotationen im aktiven Reiter gefunden.",
                ),
                3200,
            )
            return False

        dialog = AnnotationExportDialog(
            color_counts=list(data.color_counts),
            glossary_count=int(data.glossary_count),
            user_mode=user_mode,
            parent=self._parent,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False

        options = AnnotationExportOptions.normalize(dialog.options())
        content = build_annotation_export_markdown(
            panel_scope=scope,
            tab_name=title,
            data=data,
            options=options,
        )
        if title:
            title_template = self._label(
                user_mode,
                "annotation.extract.canvas_tab_title.template",
                "Annotationen: {tab}",
            )
            try:
                tab_title = str(title_template).format(tab=title)
            except Exception:
                tab_title = f"Annotationen: {title}"
        else:
            tab_title = self._label(
                user_mode,
                "annotation.extract.canvas_tab_title.default",
                "Annotationen Extraktion",
            )
        self._canvas.tabs.add_tab(
            title=tab_title,
            content=content,
            read_only=False,
            activate=True,
        )
        self._show_status(
            self._label(
                user_mode,
                "annotation.extract.status.done",
                "Annotationen in neuem Canvas-Tab extrahiert.",
            ),
            4200,
        )
        return True

    def select_next_draft_tab(self) -> None:
        tabs = self._canvas.tabs.tab_widget
        count = int(tabs.count())
        if count > 1:
            tabs.setCurrentIndex((int(tabs.currentIndex()) + 1) % count)

    def select_previous_draft_tab(self) -> None:
        tabs = self._canvas.tabs.tab_widget
        count = int(tabs.count())
        if count > 1:
            tabs.setCurrentIndex((int(tabs.currentIndex()) - 1) % count)

    def open_fact_check_canvas(self, title_hint: str, content: str) -> tuple[bool, str]:
        title = (
            f"Fakten: {str(title_hint or '').strip()}"
            if str(title_hint or "").strip()
            else "Faktencheck"
        )
        try:
            self._canvas.tabs.add_tab(title=title, content=content, read_only=True)
            self._show_status("Faktencheck im Draft-Workspace geöffnet.", 4000)
            return True, title
        except Exception as exc:
            _LOG.error(
                "CanvasController failed to open fact-check tab '%s': %s",
                title,
                exc,
                exc_info=True,
            )
            return False, str(exc)

    def show_welcome_text(self, text: str) -> None:
        panel = self._canvas.tabs.current_panel()
        if panel:
            panel.editor.setPlainText(str(text or ""))
