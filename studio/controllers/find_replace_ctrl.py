"""Find/Replace controller — search and replace across editors and preview panes."""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6.QtGui import QTextCursor, QTextDocument
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

from studio.canvas.editor import MarkdownEditor

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

    # ── Public interface ───────────────────────────────────────────────

    def open_dialog(self):
        target = self._resolve_find_target()
        if target is None:
            self._show_status("Kein aktiver Editor für Suche.", 2000)
            return
        self._find_target = target
        editor = target.get("editor")
        if isinstance(editor, MarkdownEditor):
            self._editor = editor

        if self._dialog is None:
            self._build_dialog()

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
        dlg.setWindowTitle("Suchen / Ersetzen")
        dlg.setModal(False)
        dlg.resize(520, 170)
        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        row_find = QHBoxLayout()
        row_find.setContentsMargins(0, 0, 0, 0)
        row_find.setSpacing(6)
        row_find.addWidget(QLabel("Suchen:"))
        self._find_query_edit = QLineEdit()
        row_find.addWidget(self._find_query_edit, 1)
        layout.addLayout(row_find)

        row_replace = QHBoxLayout()
        row_replace.setContentsMargins(0, 0, 0, 0)
        row_replace.setSpacing(6)
        row_replace.addWidget(QLabel("Ersetzen:"))
        self._replace_query_edit = QLineEdit()
        row_replace.addWidget(self._replace_query_edit, 1)
        layout.addLayout(row_replace)

        flags_row = QHBoxLayout()
        flags_row.setContentsMargins(0, 0, 0, 0)
        flags_row.setSpacing(10)
        self._find_case_cb = QCheckBox("Groß/Kleinschreibung")
        self._find_whole_cb = QCheckBox("Ganzes Wort")
        flags_row.addWidget(self._find_case_cb)
        flags_row.addWidget(self._find_whole_cb)
        flags_row.addStretch(1)
        self._find_count_lbl = QLabel("Treffer: 0")
        self._find_count_lbl.setStyleSheet(
            "color: palette(placeholder-text); font-size: 10px;"
        )
        flags_row.addWidget(self._find_count_lbl)
        layout.addLayout(flags_row)

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.setSpacing(6)
        btn_prev = QPushButton("Vorheriges")
        btn_next = QPushButton("Nächstes")
        self._find_replace_btn = QPushButton("Ersetzen")
        self._find_replace_all_btn = QPushButton("Alle ersetzen")
        btn_close = QPushButton("Schließen")
        btn_prev.clicked.connect(lambda: self._find_in_editor_from_dialog(backward=True))
        btn_next.clicked.connect(lambda: self._find_in_editor_from_dialog(backward=False))
        self._find_replace_btn.clicked.connect(self._replace_from_dialog)
        self._find_replace_all_btn.clicked.connect(self._replace_all_from_dialog)
        btn_close.clicked.connect(dlg.hide)
        btn_row.addWidget(btn_prev)
        btn_row.addWidget(btn_next)
        btn_row.addWidget(self._find_replace_btn)
        btn_row.addWidget(self._find_replace_all_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(btn_close)
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

    def _count_find_matches_editor(self, editor: MarkdownEditor, needle: str) -> int:
        query = str(needle or "")
        if not query:
            return 0
        flags = self._build_find_flags(backward=False)
        doc = editor.document()
        count = 0
        cursor = doc.find(query, 0, flags)
        last_signature: tuple[int, int, int] | None = None
        max_iterations = max(1, int(doc.characterCount()) + 1)
        iterations = 0
        while not cursor.isNull() and iterations < max_iterations:
            start = int(cursor.selectionStart())
            end = int(cursor.selectionEnd())
            pos = int(cursor.position())
            signature = (start, end, pos)
            if signature == last_signature:
                _LOG.warning(
                    "Find/Replace match counting aborted due to non-advancing cursor for %r",
                    query,
                )
                break
            count += 1
            iterations += 1
            last_signature = signature
            cursor = doc.find(query, max(pos, end, start + 1), flags)
        if iterations >= max_iterations and not cursor.isNull():
            _LOG.warning(
                "Find/Replace match counting reached safety limit (%d) for %r",
                max_iterations,
                query,
            )
        return count

    def _count_find_matches(self, target: dict, needle: str) -> int:
        kind = str(target.get("kind", "")).strip().lower()
        if kind == "editor":
            editor = target.get("editor")
            if isinstance(editor, MarkdownEditor):
                return self._count_find_matches_editor(editor, needle)
            return 0
        if kind == "preview":
            panel = target.get("panel")
            if panel is None:
                return 0
            case_sensitive = bool(
                self._find_case_cb is not None and self._find_case_cb.isChecked()
            )
            whole_words = bool(
                self._find_whole_cb is not None and self._find_whole_cb.isChecked()
            )
            try:
                return int(
                    panel.count_preview_matches(
                        str(needle or ""),
                        case_sensitive=case_sensitive,
                        whole_words=whole_words,
                    )
                )
            except Exception:
                _LOG.warning(
                    "Find/Replace preview match count failed for panel %r",
                    panel,
                    exc_info=True,
                )
                return 0
        return 0

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
            label.setText("Treffer: —")
            self._update_find_replace_controls_state(None)
            return
        label.setText(f"Treffer: {self._count_find_matches(target, query)}")
        self._update_find_replace_controls_state(target)

    def _build_find_flags(self, *, backward: bool = False):
        flags = QTextDocument.FindFlag(0)
        if backward:
            flags |= QTextDocument.FindFlag.FindBackward
        if self._find_case_cb is not None and self._find_case_cb.isChecked():
            flags |= QTextDocument.FindFlag.FindCaseSensitively
        if self._find_whole_cb is not None and self._find_whole_cb.isChecked():
            flags |= QTextDocument.FindFlag.FindWholeWords
        return flags

    def _find_in_target(self, target: dict, needle: str, *, backward: bool = False) -> bool:
        kind = str(target.get("kind", "")).strip().lower()
        if kind == "preview":
            panel = target.get("panel")
            if panel is None:
                return False
            case_sensitive = bool(
                self._find_case_cb is not None and self._find_case_cb.isChecked()
            )
            whole_words = bool(
                self._find_whole_cb is not None and self._find_whole_cb.isChecked()
            )
            try:
                return bool(
                    panel.find_preview_text(
                        needle,
                        backward=backward,
                        case_sensitive=case_sensitive,
                        whole_words=whole_words,
                        wrap=True,
                    )
                )
            except Exception:
                _LOG.warning(
                    "Find/Replace preview search failed for panel %r",
                    panel,
                    exc_info=True,
                )
                return False

        editor = target.get("editor")
        if not isinstance(editor, MarkdownEditor):
            return False
        flags = self._build_find_flags(backward=backward)
        doc = editor.document()
        cursor = editor.textCursor()
        current_start = int(cursor.selectionStart())
        current_end = int(cursor.selectionEnd())
        current_has_selection = current_end > current_start
        start = int(cursor.selectionStart()) if backward else int(cursor.selectionEnd())
        probe = QTextCursor(doc)
        if backward:
            probe.setPosition(max(0, start - 1))
        else:
            probe.setPosition(max(0, start))
        found = doc.find(str(needle or ""), probe, flags)
        if found.isNull():
            restart = QTextCursor(doc)
            if backward:
                restart.setPosition(max(0, int(doc.characterCount()) - 1))
            else:
                restart.setPosition(0)
            found = doc.find(str(needle or ""), restart, flags)
        if (
            not found.isNull()
            and current_has_selection
            and int(found.selectionStart()) == current_start
            and int(found.selectionEnd()) == current_end
        ):
            probe2 = QTextCursor(doc)
            if backward:
                probe2.setPosition(max(0, int(found.selectionStart()) - 1))
            else:
                probe2.setPosition(max(0, int(found.selectionEnd())))
            alt = doc.find(str(needle or ""), probe2, flags)
            if alt.isNull():
                restart = QTextCursor(doc)
                if backward:
                    restart.setPosition(max(0, int(doc.characterCount()) - 1))
                else:
                    restart.setPosition(0)
                alt = doc.find(str(needle or ""), restart, flags)
            if (
                not alt.isNull()
                and (
                    int(alt.selectionStart()) != current_start
                    or int(alt.selectionEnd()) != current_end
                )
            ):
                found = alt
        if found.isNull():
            return False
        editor.setTextCursor(found)
        editor.ensureCursorVisible()
        return True

    def _find_in_editor_from_dialog(self, *, backward: bool = False) -> bool:
        target = self._resolve_find_target()
        if target is None:
            self._show_status("Kein aktiver Editor für Suche.", 2000)
            self._update_find_replace_controls_state(None)
            return False
        self._update_find_replace_controls_state(target)

        needle = str(
            self._find_query_edit.text() if self._find_query_edit is not None else ""
        ).strip()
        if not needle:
            self._show_status("Bitte Suchtext eingeben.", 2000)
            return False

        if self._find_in_target(target, needle, backward=backward):
            return True

        self._show_status("Kein Treffer gefunden.", 1800)
        return False

    def _replace_from_dialog(self):
        target = self._resolve_find_target()
        if target is None:
            self._show_status("Kein aktiver Editor für Ersetzen.", 2000)
            return
        if self._find_target_is_read_only(target):
            self._show_status("Ersetzen ist in dieser Ansicht gesperrt.", 2000)
            self._update_find_replace_controls_state(target)
            return
        editor = target.get("editor")
        if not isinstance(editor, MarkdownEditor):
            self._show_status("Ersetzen ist in dieser Ansicht nicht verfügbar.", 2000)
            self._update_find_replace_controls_state(target)
            return

        needle = str(
            self._find_query_edit.text() if self._find_query_edit is not None else ""
        )
        replacement = str(
            self._replace_query_edit.text() if self._replace_query_edit is not None else ""
        )
        if not needle:
            self._show_status("Bitte Suchtext eingeben.", 2000)
            return

        cursor = editor.textCursor()
        selected = str(cursor.selectedText() or "").replace("\u2029", "\n")
        case_sensitive = bool(
            self._find_case_cb is not None and self._find_case_cb.isChecked()
        )
        if case_sensitive:
            match_selected = selected == needle
        else:
            match_selected = selected.casefold() == needle.casefold()

        if match_selected:
            cursor.insertText(replacement)
            editor.setTextCursor(cursor)

        self._find_in_editor_from_dialog(backward=False)
        self._update_find_match_count()

    def _replace_all_from_dialog(self):
        target = self._resolve_find_target()
        if target is None:
            self._show_status("Kein aktiver Editor für Ersetzen.", 2000)
            return
        if self._find_target_is_read_only(target):
            self._show_status("Ersetzen ist in dieser Ansicht gesperrt.", 2000)
            self._update_find_replace_controls_state(target)
            return
        editor = target.get("editor")
        if not isinstance(editor, MarkdownEditor):
            self._show_status("Ersetzen ist in dieser Ansicht nicht verfügbar.", 2000)
            self._update_find_replace_controls_state(target)
            return

        needle = str(
            self._find_query_edit.text() if self._find_query_edit is not None else ""
        )
        replacement = str(
            self._replace_query_edit.text() if self._replace_query_edit is not None else ""
        )
        if not needle:
            self._show_status("Bitte Suchtext eingeben.", 2000)
            return

        flags = self._build_find_flags(backward=False)
        doc = editor.document()
        edit_cursor = editor.textCursor()
        edit_cursor.beginEditBlock()
        count = 0
        max_iterations = max(1, int(doc.characterCount()) + 1)
        hit = doc.find(needle, 0, flags)
        last_signature: tuple[int, int, int] | None = None
        while not hit.isNull() and count < max_iterations:
            start = int(hit.selectionStart())
            end = int(hit.selectionEnd())
            pos = int(hit.position())
            signature = (start, end, pos)
            if signature == last_signature:
                _LOG.warning(
                    "Find/Replace replace-all aborted due to non-advancing cursor for %r",
                    needle,
                )
                break
            last_signature = signature
            hit.insertText(replacement)
            count += 1
            next_pos = max(start + len(replacement), pos, end, start + 1)
            hit = doc.find(needle, next_pos, flags)
        edit_cursor.endEditBlock()
        if count >= max_iterations and not hit.isNull():
            _LOG.warning(
                "Find/Replace replace-all reached safety limit (%d) for %r",
                max_iterations,
                needle,
            )

        self._show_status(
            f"{count} Treffer ersetzt." if count else "Keine Treffer zum Ersetzen.",
            2000,
        )
        self._update_find_match_count()
