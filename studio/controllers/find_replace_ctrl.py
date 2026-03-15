"""Find/Replace controller — search and replace across editors and preview panes."""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QWidget,
    QVBoxLayout,
)

from studio.controllers.find_replace_ops import (
    _build_find_flags as _build_find_flags_fn,
    _count_find_matches as _count_find_matches_fn,
    _count_find_matches_editor as _count_find_matches_editor_fn,
    _find_in_target as _find_in_target_fn,
    _replace_all_from_dialog as _replace_all_from_dialog_fn,
    _replace_from_dialog as _replace_from_dialog_fn,
)
from studio.canvas.editor import MarkdownEditor
from shared.domain.user_mode import normalize_user_mode, resolve_feature_label

_LOG = logging.getLogger(__name__)

if TYPE_CHECKING:
    from studio.canvas.tabs import CanvasTabWidget
    from studio.knowledge.dock import KnowledgeDock


class FindReplaceController:
    """Manages the non-modal Find/Replace dialog and all search/replace logic."""

    def __init__(
        self,
        *,
        parent_window: QWidget,
        canvas: CanvasTabWidget,
        knowledge_dock: KnowledgeDock,
        show_status: Callable[[str, int], None],
    ):
        self._parent_window = parent_window
        self._canvas = canvas
        self._knowledge_dock = knowledge_dock
        self._show_status = show_status

        self._dialog: QDialog | None = None
        self._editor: MarkdownEditor | None = None
        self._find_target: dict | None = None
        self._find_read_only_editor: MarkdownEditor | None = None

        # Dialog widgets (set when dialog is created)
        self._find_query_edit: QLineEdit | None = None
        self._replace_query_edit: QLineEdit | None = None
        self._find_case_cb: QCheckBox | None = None
        self._find_whole_cb: QCheckBox | None = None
        self._find_count_lbl: QLabel | None = None
        self._find_replace_btn: QPushButton | None = None
        self._find_replace_all_btn: QPushButton | None = None
        self._find_label: QLabel | None = None
        self._replace_label: QLabel | None = None
        self._find_prev_btn: QPushButton | None = None
        self._find_next_btn: QPushButton | None = None
        self._find_close_btn: QPushButton | None = None

    # ── Public interface ───────────────────────────────────────────────

    def _user_mode(self) -> str:
        return normalize_user_mode(str(getattr(self._parent_window, "user_mode", "") or ""))

    def _label(self, key: str, default: str) -> str:
        return resolve_feature_label(self._user_mode(), key, default)

    def _format_label(self, key: str, default: str, **kwargs: object) -> str:
        template = self._label(key, default)
        try:
            return template.format(**kwargs)
        except Exception:
            return template

    def open_dialog(self):
        target = self._resolve_find_target()
        if target is None:
            self._show_status(
                self._label(
                    "find_replace.status.no_active_editor_search",
                    "Kein aktiver Editor für Suche.",
                ),
                2000,
            )
            return
        self._find_target = target
        editor = target.get("editor")
        if isinstance(editor, MarkdownEditor):
            self._editor = editor

        if self._dialog is None:
            self._build_dialog()
        else:
            self._apply_dialog_labels()

        find_edit = self._find_query_edit
        if find_edit is not None:
            selected = ""
            if str(target.get("kind", "")).strip().lower() == "preview":
                panel = target.get("panel")
                if panel is not None and hasattr(panel, "get_preview_selected_text"):
                    try:
                        selected = str(panel.get_preview_selected_text() or "")
                    except Exception:
                        _LOG.warning(
                            "Find/Replace could not read preview selection for panel %r",
                            panel,
                            exc_info=True,
                        )
                        selected = ""
            else:
                if isinstance(editor, MarkdownEditor):
                    selected = str(editor.textCursor().selectedText() or "")
            selected = selected.replace("\u2029", "\n")
            if selected.strip():
                find_edit.setText(selected)
            find_edit.setFocus()
            find_edit.selectAll()

        self._update_find_match_count()
        assert self._dialog is not None
        self._dialog.show()
        self._dialog.raise_()
        self._dialog.activateWindow()

    # ── Private helpers ────────────────────────────────────────────────

    def _build_dialog(self):
        dlg = QDialog(self._parent_window)
        dlg.setWindowTitle(self._label("find_replace.window_title", "Suchen / Ersetzen"))
        dlg.setModal(False)
        dlg.resize(520, 170)
        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        row_find = QHBoxLayout()
        row_find.setContentsMargins(0, 0, 0, 0)
        row_find.setSpacing(6)
        self._find_label = QLabel("")
        row_find.addWidget(self._find_label)
        self._find_query_edit = QLineEdit()
        row_find.addWidget(self._find_query_edit, 1)
        layout.addLayout(row_find)

        row_replace = QHBoxLayout()
        row_replace.setContentsMargins(0, 0, 0, 0)
        row_replace.setSpacing(6)
        self._replace_label = QLabel("")
        row_replace.addWidget(self._replace_label)
        self._replace_query_edit = QLineEdit()
        row_replace.addWidget(self._replace_query_edit, 1)
        layout.addLayout(row_replace)

        flags_row = QHBoxLayout()
        flags_row.setContentsMargins(0, 0, 0, 0)
        flags_row.setSpacing(10)
        self._find_case_cb = QCheckBox("")
        self._find_whole_cb = QCheckBox("")
        flags_row.addWidget(self._find_case_cb)
        flags_row.addWidget(self._find_whole_cb)
        flags_row.addStretch(1)
        self._find_count_lbl = QLabel("")
        self._find_count_lbl.setStyleSheet(
            "color: palette(placeholder-text); font-size: 10px;"
        )
        flags_row.addWidget(self._find_count_lbl)
        layout.addLayout(flags_row)

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.setSpacing(6)
        self._find_prev_btn = QPushButton("")
        self._find_next_btn = QPushButton("")
        self._find_replace_btn = QPushButton("")
        self._find_replace_all_btn = QPushButton("")
        self._find_close_btn = QPushButton("")
        self._find_prev_btn.clicked.connect(
            lambda: self._find_in_editor_from_dialog(backward=True)
        )
        self._find_next_btn.clicked.connect(
            lambda: self._find_in_editor_from_dialog(backward=False)
        )
        self._find_replace_btn.clicked.connect(self._replace_from_dialog)
        self._find_replace_all_btn.clicked.connect(self._replace_all_from_dialog)
        self._find_close_btn.clicked.connect(dlg.hide)
        btn_row.addWidget(self._find_prev_btn)
        btn_row.addWidget(self._find_next_btn)
        btn_row.addWidget(self._find_replace_btn)
        btn_row.addWidget(self._find_replace_all_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(self._find_close_btn)
        layout.addLayout(btn_row)

        self._find_query_edit.textChanged.connect(
            lambda _text: self._update_find_match_count()
        )
        self._find_case_cb.toggled.connect(lambda _on: self._update_find_match_count())
        self._find_whole_cb.toggled.connect(lambda _on: self._update_find_match_count())
        self._find_query_edit.returnPressed.connect(
            lambda: self._find_in_editor_from_dialog(backward=False)
        )
        self._replace_query_edit.returnPressed.connect(self._replace_from_dialog)
        self._dialog = dlg
        self._apply_dialog_labels()

    def _apply_dialog_labels(self) -> None:
        if self._dialog is not None:
            self._dialog.setWindowTitle(
                self._label("find_replace.window_title", "Suchen / Ersetzen")
            )
        if self._find_label is not None:
            self._find_label.setText(self._label("find_replace.label.find", "Suchen:"))
        if self._replace_label is not None:
            self._replace_label.setText(
                self._label("find_replace.label.replace", "Ersetzen:")
            )
        if self._find_case_cb is not None:
            self._find_case_cb.setText(
                self._label(
                    "find_replace.checkbox.case_sensitive",
                    "Groß/Kleinschreibung",
                )
            )
        if self._find_whole_cb is not None:
            self._find_whole_cb.setText(
                self._label("find_replace.checkbox.whole_word", "Ganzes Wort")
            )
        if self._find_prev_btn is not None:
            self._find_prev_btn.setText(
                self._label("find_replace.button.previous", "Vorheriges")
            )
        if self._find_next_btn is not None:
            self._find_next_btn.setText(
                self._label("find_replace.button.next", "Nächstes")
            )
        if self._find_replace_btn is not None:
            self._find_replace_btn.setText(
                self._label("find_replace.button.replace", "Ersetzen")
            )
        if self._find_replace_all_btn is not None:
            self._find_replace_all_btn.setText(
                self._label("find_replace.button.replace_all", "Alle ersetzen")
            )
        if self._find_close_btn is not None:
            self._find_close_btn.setText(
                self._label("find_replace.button.close", "Schließen")
            )

    def _is_valid_find_target(self, target: dict | None) -> bool:
        if not isinstance(target, dict):
            return False
        kind = str(target.get("kind", "")).strip().lower()
        if kind == "editor":
            editor = target.get("editor")
            if not isinstance(editor, MarkdownEditor):
                return False
            try:
                _ = editor.document()
                return True
            except Exception:
                _LOG.warning(
                    "Find/Replace target validation failed for editor %r",
                    editor,
                    exc_info=True,
                )
                return False
        if kind == "preview":
            panel = target.get("panel")
            return (
                panel is not None
                and hasattr(panel, "find_preview_text")
                and hasattr(panel, "count_preview_matches")
            )
        return False

    def _resolve_find_target(self) -> dict | None:
        from studio.controllers.canvas_controller import CanvasController  # local import

        focus = QApplication.focusWidget()
        panel = CanvasController.split_panel_from_widget_chain(focus)
        if panel is None:
            if CanvasController.widget_belongs_to(focus, self._knowledge_dock):
                panel, _tabs, _scope = self._parent_window._canvas_controller.resolve_knowledge_panel_context()
            elif CanvasController.widget_belongs_to(focus, self._canvas):
                panel = self._canvas.tabs.current_panel()

        if panel is not None and hasattr(panel, "is_preview_widget"):
            try:
                if panel.is_preview_widget(focus):
                    target = {"kind": "preview", "panel": panel}
                    if self._is_valid_find_target(target):
                        self._find_target = target
                        return target
            except Exception:
                _LOG.warning(
                    "Find/Replace preview focus probe failed for panel %r",
                    panel,
                    exc_info=True,
                )

        if panel is not None:
            editor = getattr(panel, "editor", None)
            if isinstance(editor, MarkdownEditor):
                target = {"kind": "editor", "editor": editor, "panel": panel}
                if self._is_valid_find_target(target):
                    self._find_target = target
                    self._editor = editor
                    return target

        cached_target = self._find_target
        if self._is_valid_find_target(cached_target):
            return cached_target

        panel = self._canvas.tabs.current_panel()
        if panel is not None:
            editor = getattr(panel, "editor", None)
            if isinstance(editor, MarkdownEditor):
                target = {"kind": "editor", "editor": editor, "panel": panel}
                self._find_target = target
                self._editor = editor
                return target
        return None

    _count_find_matches_editor = _count_find_matches_editor_fn
    _count_find_matches = _count_find_matches_fn

    def _disconnect_find_read_only_hook(self):
        hooked = self._find_read_only_editor
        if isinstance(hooked, MarkdownEditor):
            try:
                hooked.read_only_changed.disconnect(self._on_find_target_read_only_changed)
            except Exception:
                _LOG.debug(
                    "Find/Replace read_only_changed disconnect skipped for %r",
                    hooked,
                    exc_info=True,
                )
        self._find_read_only_editor = None

    def _track_find_target_read_only(self, target: dict | None):
        if not self._is_valid_find_target(target):
            self._disconnect_find_read_only_hook()
            return
        if str(target.get("kind", "")).strip().lower() != "editor":
            self._disconnect_find_read_only_hook()
            return
        editor = target.get("editor")
        if not isinstance(editor, MarkdownEditor):
            self._disconnect_find_read_only_hook()
            return
        if editor is self._find_read_only_editor:
            return
        self._disconnect_find_read_only_hook()
        try:
            editor.read_only_changed.connect(self._on_find_target_read_only_changed)
        except Exception:
            _LOG.warning(
                "Find/Replace read_only_changed connect failed for %r",
                editor,
                exc_info=True,
            )
            return
        self._find_read_only_editor = editor

    def _on_find_target_read_only_changed(self, _read_only: bool):
        if self._dialog is None:
            return
        if not self._dialog.isVisible():
            return
        self._update_find_replace_controls_state()

    def _find_target_is_read_only(self, target: dict | None) -> bool:
        if not self._is_valid_find_target(target):
            return True
        kind = str(target.get("kind", "")).strip().lower()
        if kind == "editor":
            editor = target.get("editor")
            if isinstance(editor, MarkdownEditor):
                try:
                    return bool(editor.isReadOnly())
                except Exception:
                    _LOG.warning(
                        "Find/Replace read-only probe failed for %r",
                        editor,
                        exc_info=True,
                    )
                    return True
            return True
        return True

    def _update_find_replace_controls_state(self, target: dict | None = None):
        tgt = target if self._is_valid_find_target(target) else self._resolve_find_target()
        self._track_find_target_read_only(tgt)
        replace_enabled = bool(tgt is not None and not self._find_target_is_read_only(tgt))
        if self._replace_query_edit is not None:
            self._replace_query_edit.setEnabled(replace_enabled)
        if self._find_replace_btn is not None:
            self._find_replace_btn.setEnabled(replace_enabled)
        if self._find_replace_all_btn is not None:
            self._find_replace_all_btn.setEnabled(replace_enabled)

    def _update_find_match_count(self):
        label = self._find_count_lbl
        if label is None:
            return
        query = str(self._find_query_edit.text() if self._find_query_edit is not None else "")
        target = self._resolve_find_target()
        if target is None:
            label.setText(
                self._format_label(
                    "find_replace.label.matches.none",
                    "Treffer: {count}",
                    count="—",
                )
            )
            self._update_find_replace_controls_state(None)
            return
        label.setText(
            self._format_label(
                "find_replace.label.matches.template",
                "Treffer: {count}",
                count=self._count_find_matches(target, query),
            )
        )
        self._update_find_replace_controls_state(target)

    _build_find_flags = _build_find_flags_fn
    _find_in_target = _find_in_target_fn

    def _find_in_editor_from_dialog(self, *, backward: bool = False) -> bool:
        target = self._resolve_find_target()
        if target is None:
            self._show_status(
                self._label(
                    "find_replace.status.no_active_editor_search",
                    "Kein aktiver Editor für Suche.",
                ),
                2000,
            )
            self._update_find_replace_controls_state(None)
            return False
        self._update_find_replace_controls_state(target)

        needle = str(
            self._find_query_edit.text() if self._find_query_edit is not None else ""
        ).strip()
        if not needle:
            self._show_status(
                self._label(
                    "find_replace.status.enter_search_text",
                    "Bitte Suchtext eingeben.",
                ),
                2000,
            )
            return False

        if self._find_in_target(target, needle, backward=backward):
            return True

        self._show_status(
            self._label("find_replace.status.no_match_found", "Kein Treffer gefunden."),
            1800,
        )
        return False

    _replace_from_dialog = _replace_from_dialog_fn
    _replace_all_from_dialog = _replace_all_from_dialog_fn
