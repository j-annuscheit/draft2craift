"""Canvas feature widget and preview integration."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from shared.domain.user_mode import normalize_user_mode, resolve_feature_label
from shared.services.highlights.store import get_highlight_store
from studio.canvas.tabbed_editor_widget import TabbedEditorWidget
from studio.canvas.split_view import MarkdownSplitPanel

from .file_actions import CanvasFileActions
from .selection import CanvasSelectionActions
from .styles import CANVAS_TOOLBAR_STYLE


class CanvasTabWidget(QWidget):
    """Central draft workspace with tabs, toolbar and HTML preview."""
    read_aloud_requested = Signal(str)
    read_aloud_stop_requested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._user_mode = ""
        self._undo_redo_editor = None
        self._read_aloud_active = False
        self._setup_ui()
        self.set_user_mode("")

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.tabs = TabbedEditorWidget(
            default_read_only=False,
            tab_title_prefix="Draft",
            editable_tab_titles=True,
            stored_title_max_chars=10,
            export_scope="draft",
            panel_factory=lambda ro: MarkdownSplitPanel(
                read_only=ro,
                show_toolbar=True,
                allow_preview_editing=True,
                highlight_scope="draft",
            ),
        )
        self._files = CanvasFileActions(parent=self, tabs=self.tabs)
        self._selection = CanvasSelectionActions(tabs=self.tabs)

        layout.addWidget(self._build_toolbar())
        layout.addWidget(self.tabs)

        self.tabs.tab_widget.currentChanged.connect(
            self._on_canvas_tab_changed
        )
        self.tabs.tab_renamed.connect(self._on_tab_renamed)
        self._on_canvas_tab_changed()

    def _build_toolbar(self) -> QWidget:
        bar = QWidget(objectName="canvasbar")
        bar.setFixedHeight(40)
        bar.setStyleSheet(CANVAS_TOOLBAR_STYLE)

        hbox = QHBoxLayout(bar)
        hbox.setContentsMargins(10, 4, 10, 4)
        hbox.setSpacing(6)

        title = QLabel("✦ draft2craift")
        title.setStyleSheet(
            "color: palette(highlight); font-weight: bold; "
            "font-size: 13px; background: transparent;"
        )
        hbox.addWidget(title)

        self.undo_btn = QPushButton("↶ Zurück")
        self.undo_btn.setToolTip("Rückgängig (Undo)")
        self.undo_btn.clicked.connect(self.undo_current)
        hbox.addWidget(self.undo_btn)

        self.redo_btn = QPushButton("↷ Vor")
        self.redo_btn.setToolTip("Wiederholen (Redo)")
        self.redo_btn.clicked.connect(self.redo_current)
        hbox.addWidget(self.redo_btn)

        hbox.addStretch()

        def _add_btn(label: str, slot):
            btn = QPushButton(label)
            btn.clicked.connect(slot)
            hbox.addWidget(btn)
            return btn

        self.new_btn = _add_btn("+ New", lambda: self.tabs.add_tab())
        self.new_btn.setToolTip("Create a new draft tab")
        self.open_btn = _add_btn("📂 Open", self.open_file)
        self.open_btn.setToolTip("Open a file into the current tab")
        self.save_btn = _add_btn("💾 Save", self.save_current)
        self.save_btn.setToolTip("Save the current draft")
        self.read_aloud_btn = _add_btn("🔊 Play", self._request_read_aloud)
        self.read_aloud_btn.setToolTip("Aktuellen Draft vorlesen")
        self.export_btn = _add_btn("⬇ Export", self.export_document)
        self.export_btn.setToolTip("Export the current draft")

        return bar

    def _on_canvas_tab_changed(self, _index: int = -1):
        old_editor = self._undo_redo_editor
        if old_editor is not None:
            for signal in (
                old_editor.undoAvailable,
                old_editor.redoAvailable,
                old_editor.read_only_changed,
            ):
                try:
                    signal.disconnect(self._refresh_undo_redo_buttons)
                except Exception:
                    pass

        panel = self.tabs.current_panel()
        editor = panel.editor if panel else None
        self._undo_redo_editor = editor

        if editor is not None:
            editor.undoAvailable.connect(self._refresh_undo_redo_buttons)
            editor.redoAvailable.connect(self._refresh_undo_redo_buttons)
            editor.read_only_changed.connect(self._refresh_undo_redo_buttons)

        self._refresh_undo_redo_buttons()

    def _refresh_undo_redo_buttons(self, *_):
        self.undo_btn.setEnabled(self.tabs.can_undo_current())
        self.redo_btn.setEnabled(self.tabs.can_redo_current())

    def undo_current(self):
        self.tabs.undo_current()
        self._refresh_undo_redo_buttons()

    def redo_current(self):
        self.tabs.redo_current()
        self._refresh_undo_redo_buttons()

    def preview_zoom_percent(self) -> int:
        panel = self.tabs.current_panel()
        if panel is None or not hasattr(panel, "preview_zoom_percent"):
            return 100
        return int(panel.preview_zoom_percent())

    def set_preview_zoom_percent(self, percent: int) -> bool:
        panel = self.tabs.current_panel()
        if panel is None or not hasattr(panel, "set_preview_zoom_percent"):
            return False
        return bool(panel.set_preview_zoom_percent(percent))

    def increase_preview_text_size(self) -> bool:
        panel = self.tabs.current_panel()
        if panel is None or not hasattr(panel, "increase_preview_text_size"):
            return False
        return bool(panel.increase_preview_text_size())

    def decrease_preview_text_size(self) -> bool:
        panel = self.tabs.current_panel()
        if panel is None or not hasattr(panel, "decrease_preview_text_size"):
            return False
        return bool(panel.decrease_preview_text_size())

    def reset_preview_text_size(self) -> bool:
        panel = self.tabs.current_panel()
        if panel is None or not hasattr(panel, "reset_preview_text_size"):
            return False
        return bool(panel.reset_preview_text_size())

    def is_preview_widget(self, widget: QWidget | None) -> bool:
        panel = self.tabs.current_panel()
        if panel is None or not hasattr(panel, "is_preview_widget"):
            return False
        return bool(panel.is_preview_widget(widget))

    # ------------------------------------------------------------------
    # File operations API
    # ------------------------------------------------------------------

    def open_file(self):
        self._files.open_file()

    def save_current(self):
        self._files.save_current()

    def export_document(self):
        self._files.export_document()

    def export_pdf(self):
        self._files.export_pdf()

    def export_word(self):
        self._files.export_word()

    # ------------------------------------------------------------------
    # Context helpers API (consumed by chat/llm orchestration)
    # ------------------------------------------------------------------

    def get_selected_text(
        self,
        *,
        allow_cached: bool = True,
        consume_cached: bool = True,
    ) -> str:
        return self._selection.get_selected_text(
            allow_cached=allow_cached,
            consume_cached=consume_cached,
        )

    def get_selected_span(
        self,
        *,
        allow_cached: bool = True,
    ) -> tuple[int, int] | None:
        return self._selection.get_selected_span(allow_cached=allow_cached)

    def replace_selected_text(
        self,
        replacement: str,
        expected_original: str = "",
        preferred_span: tuple[int, int] | None = None,
    ) -> tuple[bool, str]:
        return self._selection.replace_selected_text(
            replacement,
            expected_original,
            preferred_span,
        )

    def get_current_text(self) -> str:
        return self._selection.get_current_text()

    def _request_read_aloud(self):
        if self._read_aloud_active:
            self.read_aloud_stop_requested.emit()
            return
        text = self._resolve_read_aloud_text()
        self.read_aloud_requested.emit(str(text or ""))

    def _resolve_read_aloud_text(self) -> str:
        selected = str(
            self.get_selected_text(
                allow_cached=True,
                consume_cached=True,
            )
            or ""
        ).strip()
        if selected:
            return selected
        return str(self.get_current_text() or "").strip()

    def set_read_aloud_active(self, active: bool):
        self._read_aloud_active = bool(active)
        btn = getattr(self, "read_aloud_btn", None)
        if btn is None:
            return
        if self._read_aloud_active:
            btn.setText(
                resolve_feature_label(
                    self._user_mode,
                    "canvas.toolbar.read_aloud.stop",
                    "⏹ Stop",
                )
            )
            btn.setToolTip(
                resolve_feature_label(
                    self._user_mode,
                    "canvas.toolbar.read_aloud.stop.tooltip",
                    "Vorlesen stoppen",
                )
            )
            return
        btn.setText(
            resolve_feature_label(
                self._user_mode,
                "canvas.toolbar.read_aloud.play",
                "🔊 Play",
            )
        )
        btn.setToolTip(
            resolve_feature_label(
                self._user_mode,
                "canvas.toolbar.read_aloud.play.tooltip",
                "Aktuellen Draft vorlesen",
            )
        )

    def set_user_mode(self, mode: str) -> None:
        self._user_mode = normalize_user_mode(mode)
        self.undo_btn.setText(
            resolve_feature_label(
                self._user_mode,
                "canvas.toolbar.undo",
                "↶ Zurück",
            )
        )
        self.undo_btn.setToolTip(
            resolve_feature_label(
                self._user_mode,
                "canvas.toolbar.undo.tooltip",
                "Rückgängig (Undo)",
            )
        )
        self.redo_btn.setText(
            resolve_feature_label(
                self._user_mode,
                "canvas.toolbar.redo",
                "↷ Vor",
            )
        )
        self.redo_btn.setToolTip(
            resolve_feature_label(
                self._user_mode,
                "canvas.toolbar.redo.tooltip",
                "Wiederholen (Redo)",
            )
        )
        self.new_btn.setText(
            resolve_feature_label(
                self._user_mode,
                "canvas.toolbar.new_tab",
                "+ New",
            )
        )
        self.new_btn.setToolTip(
            resolve_feature_label(
                self._user_mode,
                "canvas.toolbar.new_tab.tooltip",
                "Create a new draft tab",
            )
        )
        self.open_btn.setText(
            resolve_feature_label(
                self._user_mode,
                "canvas.toolbar.open",
                "📂 Open",
            )
        )
        self.open_btn.setToolTip(
            resolve_feature_label(
                self._user_mode,
                "canvas.toolbar.open.tooltip",
                "Open a file into the current tab",
            )
        )
        self.save_btn.setText(
            resolve_feature_label(
                self._user_mode,
                "canvas.toolbar.save",
                "💾 Save",
            )
        )
        self.save_btn.setToolTip(
            resolve_feature_label(
                self._user_mode,
                "canvas.toolbar.save.tooltip",
                "Save the current draft",
            )
        )
        self.export_btn.setText(
            resolve_feature_label(
                self._user_mode,
                "canvas.toolbar.export",
                "⬇ Export",
            )
        )
        self.export_btn.setToolTip(
            resolve_feature_label(
                self._user_mode,
                "canvas.toolbar.export.tooltip",
                "Export the current draft",
            )
        )
        if self._read_aloud_active:
            self.read_aloud_btn.setText(
                resolve_feature_label(
                    self._user_mode,
                    "canvas.toolbar.read_aloud.stop",
                    "⏹ Stop",
                )
            )
            self.read_aloud_btn.setToolTip(
                resolve_feature_label(
                    self._user_mode,
                    "canvas.toolbar.read_aloud.stop.tooltip",
                    "Vorlesen stoppen",
                )
            )
        else:
            self.read_aloud_btn.setText(
                resolve_feature_label(
                    self._user_mode,
                    "canvas.toolbar.read_aloud.play",
                    "🔊 Play",
                )
            )
            self.read_aloud_btn.setToolTip(
                resolve_feature_label(
                    self._user_mode,
                    "canvas.toolbar.read_aloud.play.tooltip",
                    "Aktuellen Draft vorlesen",
                )
            )

        host = self.tabs.tab_widget
        for idx in range(host.count()):
            panel = host.widget(idx)
            setter = getattr(panel, "set_user_mode", None)
            if callable(setter):
                setter(self._user_mode)

    def _on_tab_renamed(self, old_title: str, new_title: str):
        get_highlight_store().rename_tab(
            panel_scope="draft",
            old_name=old_title,
            new_name=new_title,
        )
