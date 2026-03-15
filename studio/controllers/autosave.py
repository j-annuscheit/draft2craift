"""Autosave controller — manages the local autosave-project runtime."""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QObject, QSettings, QStandardPaths, QTimer
from PySide6.QtWidgets import QMessageBox, QWidget

from shared.config.setting_keys import AutosaveSettingsKeys
from shared.services.highlights.store import get_highlight_store

if TYPE_CHECKING:
    from studio.app_context import AppContext
    from studio.canvas.tabs import CanvasTabWidget
    from studio.logger import AppLogger


# Timings are tuned for responsiveness while limiting write/load churn.
AUTOSAVE_FULL_MIN_DELAY_MS = 80
AUTOSAVE_FULL_DEFAULT_DELAY_MS = 900
AUTOSAVE_WATCH_INTERVAL_MS = 1200
AUTOSAVE_DRAFT_DEBOUNCE_MS = 450
AUTOSAVE_STRUCTURE_CHANGE_DELAY_MS = 220
AUTOSAVE_SIGNATURE_CHANGE_DELAY_MS = 250
AUTOSAVE_STATUS_TIMEOUT_MS = 1200
AUTOSAVE_STATUS_HINT_THROTTLE_S = 1.0


class AutosaveController(QObject):
    """Manages the periodic autosave project lifecycle."""

    _AUTOSAVE_SETTING_KEY = AutosaveSettingsKeys.ENABLED

    def __init__(
        self,
        *,
        parent: QObject,
        canvas: CanvasTabWidget,
        app_context: AppContext,
        app_logger: AppLogger,
        app_settings: QSettings,
    ) -> None:
        super().__init__(parent)
        self._canvas = canvas
        self._context = app_context
        self._app_logger = app_logger
        self._app_settings = app_settings

        # Internal state
        self._enabled: bool = self._load_enabled()
        self._suspended: bool = False
        self._runtime_connected: bool = False
        self._editor_hooks: set[int] = set()
        self._pending_editor = None  # MarkdownEditor | None
        self._last_tab_count: int = 0
        self._last_signature: str = ""
        self._last_hint_ts: float = 0.0
        self._autosave_dir: Path = self._resolve_autosave_dir()

        # Timers
        self._draft_timer = QTimer(self)
        self._draft_timer.setSingleShot(True)
        self._draft_timer.timeout.connect(self._flush_draft)

        self._full_timer = QTimer(self)
        self._full_timer.setSingleShot(True)
        self._full_timer.timeout.connect(self.flush_full)

        self._watch_timer = QTimer(self)
        self._watch_timer.setSingleShot(False)
        self._watch_timer.timeout.connect(self._watch_structure)

    # ── Properties ────────────────────────────────────────────────────

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = bool(value)
        self._app_settings.setValue(self._AUTOSAVE_SETTING_KEY, bool(value))
        self._app_settings.sync()

    @property
    def suspended(self) -> bool:
        return self._suspended

    @suspended.setter
    def suspended(self, value: bool) -> None:
        self._suspended = bool(value)

    @property
    def autosave_dir(self) -> Path:
        return self._autosave_dir

    # ── Public interface ───────────────────────────────────────────────

    def schedule_full(self, delay_ms: int = AUTOSAVE_FULL_DEFAULT_DELAY_MS) -> None:
        if (not self._enabled) or self._suspended:
            return
        if not self._runtime_connected:
            return
        # Lower bound prevents immediate back-to-back full snapshots while signals burst.
        self._full_timer.start(max(AUTOSAVE_FULL_MIN_DELAY_MS, int(delay_ms)))

    def toggle_enabled(self, checked: bool) -> None:
        enabled = bool(checked)
        if enabled == self.enabled:
            return
        self.enabled = enabled
        if enabled:
            self.start_runtime()
            self.schedule_full(delay_ms=150)
            self._context.show_status(
                "Autosave aktiviert (lokales Autosave-Projekt).",
                3000,
            )
            return
        self.stop_runtime()
        self._reset_workspace()
        self._context.show_status(
            "Autosave deaktiviert. Lokales Autosave-Projekt wurde entfernt.",
            3500,
        )

    def toggle_enabled_shortcut(self, *, action: object | None = None) -> None:
        self.toggle_enabled(not bool(self.enabled))
        if action is None:
            return
        blocker = getattr(action, "blockSignals", None)
        set_checked = getattr(action, "setChecked", None)
        if not callable(blocker) or not callable(set_checked):
            return
        blocked = blocker(True)
        set_checked(bool(self.enabled))
        blocker(blocked)

    def rewire_editors(self) -> None:
        if not self._enabled:
            return
        from studio.canvas.editor import MarkdownEditor  # local import
        tabs = self._canvas.tabs.tab_widget
        live_ids: set[int] = set()
        for i in range(tabs.count()):
            panel = tabs.widget(i)
            editor = getattr(panel, "editor", None)
            if editor is None:
                continue
            live_ids.add(id(editor))
        self._editor_hooks.intersection_update(live_ids)

        for i in range(tabs.count()):
            panel = tabs.widget(i)
            editor = getattr(panel, "editor", None)
            if editor is None:
                continue
            key = id(editor)
            if key in self._editor_hooks:
                continue
            editor.textChanged.connect(self._on_editor_text_changed)
            self._editor_hooks.add(key)

    def flush_pending_preview_edits(self, panel: QWidget | None = None) -> None:
        panels: list[QWidget] = []
        if panel is not None:
            panels = [panel]
        else:
            tabs = self._canvas.tabs.tab_widget
            panels = [
                tabs.widget(i)
                for i in range(tabs.count())
                if isinstance(tabs.widget(i), QWidget)
            ]

        for current in panels:
            flush = getattr(current, "flush_pending_preview_edits", None)
            if flush is None:
                continue
            try:
                flush()
            except Exception as exc:
                self._app_logger.warning(
                    "SYS",
                    f"[AUTOSAVE] flush_pending_preview_edits failed for panel {current!r}: {exc}",
                )
                continue

    def flush_before_close(self) -> None:
        if (not self._enabled) or self._suspended:
            return
        self._watch_timer.stop()
        if self._draft_timer.isActive():
            self._draft_timer.stop()
            self._flush_draft()
        if self._full_timer.isActive():
            self._full_timer.stop()
        self.flush_full()

    def start_runtime(self) -> None:
        if not self._enabled:
            return
        if not self._runtime_connected:
            tabs = self._canvas.tabs
            tab_widget = tabs.tab_widget
            tab_widget.currentChanged.connect(self._on_canvas_tab_changed)
            tab_widget.tabCloseRequested.connect(self._on_canvas_structure_changed)
            tab_widget.tabBar().tabMoved.connect(self._on_canvas_structure_changed)
            tabs.tab_renamed.connect(self._on_canvas_structure_changed)
            self._runtime_connected = True

        self.rewire_editors()
        self._last_tab_count = self._canvas.tabs.tab_widget.count()
        self._last_signature = self._signature()
        if not self._watch_timer.isActive():
            # Lightweight periodic structure check for tab/order/metadata drift.
            self._watch_timer.start(AUTOSAVE_WATCH_INTERVAL_MS)

    def stop_runtime(self) -> None:
        self._watch_timer.stop()
        self._draft_timer.stop()
        self._full_timer.stop()
        self._pending_editor = None

        self._disconnect_editor_hooks()

        if not self._runtime_connected:
            return

        tabs = self._canvas.tabs
        tab_widget = tabs.tab_widget
        try:
            tab_widget.currentChanged.disconnect(self._on_canvas_tab_changed)
        except Exception as exc:
            self._app_logger.debug(
                "SYS",
                f"[AUTOSAVE] disconnect currentChanged skipped: {exc}",
            )
        try:
            tab_widget.tabCloseRequested.disconnect(self._on_canvas_structure_changed)
        except Exception as exc:
            self._app_logger.debug(
                "SYS",
                f"[AUTOSAVE] disconnect tabCloseRequested skipped: {exc}",
            )
        try:
            tab_widget.tabBar().tabMoved.disconnect(self._on_canvas_structure_changed)
        except Exception as exc:
            self._app_logger.debug(
                "SYS",
                f"[AUTOSAVE] disconnect tabMoved skipped: {exc}",
            )
        try:
            tabs.tab_renamed.disconnect(self._on_canvas_structure_changed)
        except Exception as exc:
            self._app_logger.debug(
                "SYS",
                f"[AUTOSAVE] disconnect tab_renamed skipped: {exc}",
            )
        self._runtime_connected = False

    def maybe_restore_from_tmp(self, parent_widget: QWidget) -> bool:
        if not self._enabled:
            return False
        if not self._project_file().exists():
            return False

        choice = QMessageBox.question(
            parent_widget,
            "Autosave-Projekt gefunden",
            (
                "Im Autosave-Bereich wurde ein automatisch gespeichertes Projekt gefunden.\n\n"
                "Möchtest du daran weiterarbeiten?"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )

        if choice == QMessageBox.StandardButton.Yes:
            self._suspended = True
            try:
                loaded = self._context.load_project(self._autosave_dir)
            finally:
                self._suspended = False
            if loaded:
                self._context.show_status("Autosave-Projekt wiederhergestellt.", 4000)
                return True

            self._reset_workspace()
            return False

        self._reset_workspace()
        return False

    def flush_full(self) -> None:
        if (not self._enabled) or self._suspended:
            return
        is_rag_busy = False
        try:
            is_rag_busy = bool(self._context.is_rag_busy())
        except Exception as exc:
            self._app_logger.warning(
                "SYS",
                f"[AUTOSAVE] is_rag_busy probe failed: {exc}",
            )
        if is_rag_busy:
            if not self._full_timer.isActive():
                self._app_logger.debug(
                    "SYS",
                    "[AUTOSAVE] Full flush delayed (RAG worker busy)",
                )
                self._full_timer.start(AUTOSAVE_FULL_DEFAULT_DELAY_MS)
            return
        self._app_logger.debug("SYS", "[AUTOSAVE] Full flush start")
        self._prepare_workspace()
        self.flush_pending_preview_edits()
        try:
            ok = self._context.save_project(
                self._autosave_dir,
                include_st_embeddings=False,
            )
        except Exception as exc:
            self._app_logger.error("SYS", f"[AUTOSAVE] Full flush failed: {exc}")
            return
        if not ok:
            self._app_logger.error(
                "SYS", "[AUTOSAVE] Full flush failed (save_project returned False)"
            )
            return
        self.rewire_editors()
        self._last_tab_count = self._canvas.tabs.tab_widget.count()
        self._last_signature = self._signature()
        self._show_saved_hint(full_snapshot=True)
        self._app_logger.debug("SYS", "[AUTOSAVE] Full flush done")

    # ── Private helpers ────────────────────────────────────────────────

    @staticmethod
    def _resolve_autosave_dir() -> Path:
        raw_app_dir = str(
            QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
            or ""
        ).strip()
        if raw_app_dir:
            base = Path(raw_app_dir).expanduser()
            if not base.is_absolute():
                base = Path.home() / base
            return (base.resolve(strict=False) / "autosave_project").resolve(strict=False)
        return (Path.home() / ".draft2craift" / "autosave_project").resolve(strict=False)

    def _project_file(self) -> Path:
        return self._autosave_dir / "project.json"

    def _prepare_workspace(self) -> None:
        self._autosave_dir.mkdir(parents=True, exist_ok=True)
        (self._autosave_dir / "canvas").mkdir(parents=True, exist_ok=True)

    def _reset_workspace(self) -> None:
        if self._autosave_dir.exists():
            shutil.rmtree(self._autosave_dir, ignore_errors=True)

    def _load_enabled(self) -> bool:
        raw = self._app_settings.value(self._AUTOSAVE_SETTING_KEY, True)
        return self._as_bool(raw, True)

    @staticmethod
    def _as_bool(raw: object, default: bool) -> bool:
        if isinstance(raw, bool):
            return raw
        if raw is None:
            return bool(default)
        text = str(raw).strip().lower()
        if text in {"1", "true", "yes", "on"}:
            return True
        if text in {"0", "false", "no", "off"}:
            return False
        return bool(default)

    def _signature(self) -> str:
        tabs_data = self._collect_canvas_tabs_data()
        extras = {}
        try:
            extras = self._autosave_state_extras()
        except Exception as exc:
            self._app_logger.warning(
                "SYS",
                f"[AUTOSAVE] state extras lookup failed: {exc}",
            )
        tts_mode = ""
        try:
            tts_mode = self._context.chat_tts_mode()
        except Exception as exc:
            self._app_logger.warning(
                "SYS",
                f"[AUTOSAVE] chat TTS mode lookup failed: {exc}",
            )
        payload = {
            "canvas_tabs": [
                {
                    "title": row.get("title", ""),
                    "file_path": row.get("file_path", ""),
                    "read_only": bool(row.get("read_only", False)),
                }
                for row in tabs_data
            ],
            "imported_docs": extras.get("imported_docs", []),
            "user_mode": extras.get("user_mode", ""),
            "theme": extras.get("theme", ""),
            "chat_tts_mode": tts_mode,
            "preview_page_margin": extras.get("preview_page_margin", {}),
            "preview_theme": extras.get("preview_theme", ""),
            "highlights": self._highlight_store_signature(),
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)

    def _autosave_state_extras(self) -> dict[str, Any]:
        """Gather non-canvas runtime state required for snapshot signatures."""
        theme = ""
        preview_margin: dict[str, object] = {}
        preview_theme = ""
        ctrl = self._context.theme_controller
        if ctrl is not None:
            try:
                theme = str(ctrl.get_theme_id() or "")
            except Exception as exc:
                self._app_logger.warning("SYS", f"[AUTOSAVE] get_theme_id failed: {exc}")
            try:
                preview_margin = dict(ctrl.get_preview_page_margin_settings() or {})
            except Exception as exc:
                self._app_logger.warning(
                    "SYS", f"[AUTOSAVE] get_preview_page_margin_settings failed: {exc}"
                )
            try:
                preview_theme = str(ctrl.get_preview_theme_id() or "")
            except Exception as exc:
                self._app_logger.warning(
                    "SYS", f"[AUTOSAVE] get_preview_theme_id failed: {exc}"
                )
        return {
            "user_mode": self._context.get_user_mode(),
            "theme": theme,
            "imported_docs": sorted(self._context.file_registry.keys()),
            "preview_page_margin": preview_margin,
            "preview_theme": preview_theme,
        }

    def _highlight_store_signature(self) -> dict[str, object]:
        """Return cheap change markers so highlight edits trigger full autosave."""
        try:
            store = get_highlight_store()
            path = store.path.resolve(strict=False)
            stat = path.stat() if path.exists() else None
            return {
                "path": str(path),
                "mtime_ns": int(stat.st_mtime_ns) if stat is not None else 0,
                "size": int(stat.st_size) if stat is not None else 0,
                "glossary_enabled": bool(store.is_glossary_enabled()),
            }
        except Exception as exc:
            self._app_logger.warning(
                "SYS",
                f"[AUTOSAVE] highlight signature probe failed: {exc}",
            )
            return {
                "path": "",
                "mtime_ns": 0,
                "size": 0,
                "glossary_enabled": True,
            }

    def _collect_canvas_tabs_data(self) -> list[dict]:
        tabs = self._canvas.tabs.tab_widget
        out: list[dict] = []
        for i in range(tabs.count()):
            panel = tabs.widget(i)
            editor = getattr(panel, "editor", None)
            if editor is None:
                continue
            out.append(
                {
                    "title": self._canvas.tabs.get_tab_full_title(i),
                    "file_path": str(getattr(panel, "file_path", "") or ""),
                    "canvas_file": f"doc_{i:04d}.md",
                    "read_only": bool(editor.isReadOnly()),
                }
            )
        return out

    def _show_saved_hint(self, *, full_snapshot: bool = False) -> None:
        now = time.monotonic()
        if (not full_snapshot) and (now - self._last_hint_ts) < AUTOSAVE_STATUS_HINT_THROTTLE_S:
            return
        self._last_hint_ts = now
        text = (
            "Autosave: Snapshot gespeichert"
            if full_snapshot
            else "Autosave: gespeichert"
        )
        self._context.show_status(text, AUTOSAVE_STATUS_TIMEOUT_MS)

    def _disconnect_editor_hooks(self) -> None:
        tabs = self._canvas.tabs.tab_widget
        for i in range(tabs.count()):
            panel = tabs.widget(i)
            editor = getattr(panel, "editor", None)
            if editor is None:
                continue
            try:
                editor.textChanged.disconnect(self._on_editor_text_changed)
            except Exception as exc:
                self._app_logger.debug(
                    "SYS",
                    f"[AUTOSAVE] disconnect textChanged skipped for editor {editor!r}: {exc}",
                )
                continue
        self._editor_hooks.clear()

    def _find_panel_for_editor(self, editor) -> tuple[QWidget | None, int]:
        tabs = self._canvas.tabs.tab_widget
        if editor is not None:
            for i in range(tabs.count()):
                panel = tabs.widget(i)
                if getattr(panel, "editor", None) is editor:
                    return panel, i
        panel = self._canvas.tabs.current_panel()
        if panel is None:
            return None, -1
        return panel, tabs.indexOf(panel)

    def _flush_draft(self) -> None:
        if (not self._enabled) or self._suspended:
            return
        self._prepare_workspace()
        if not self._project_file().exists():
            self.flush_full()
            return

        panel, index = self._find_panel_for_editor(self._pending_editor)
        self._pending_editor = None
        if panel is None or index < 0:
            return

        self.flush_pending_preview_edits(panel)
        editor = getattr(panel, "editor", None)
        if editor is None:
            return

        canvas_file = self._autosave_dir / "canvas" / f"doc_{index:04d}.md"
        try:
            self._write_text_atomic(canvas_file, editor.toPlainText())
            self._show_saved_hint(full_snapshot=False)
        except Exception as exc:
            self._app_logger.warning(
                "SYS",
                f"[AUTOSAVE] draft flush failed for {canvas_file}: {exc}; escalating to full flush",
            )
            self.flush_full()

    def _watch_structure(self) -> None:
        if (not self._enabled) or self._suspended:
            return
        self.rewire_editors()
        signature = self._signature()
        if signature == self._last_signature:
            return
        self._last_signature = signature
        self.schedule_full(delay_ms=AUTOSAVE_SIGNATURE_CHANGE_DELAY_MS)

    # ── Signal slots ───────────────────────────────────────────────────

    def _on_editor_text_changed(self) -> None:
        if (not self._enabled) or self._suspended:
            return
        from studio.canvas.editor import MarkdownEditor  # local import
        sender = self.sender()
        if isinstance(sender, MarkdownEditor):
            self._pending_editor = sender
        # Debounce typing bursts; flush once the user pauses briefly.
        self._draft_timer.start(AUTOSAVE_DRAFT_DEBOUNCE_MS)

    def _on_canvas_tab_changed(self, _index: int) -> None:
        if (not self._enabled) or self._suspended:
            return
        self.rewire_editors()
        count = self._canvas.tabs.tab_widget.count()
        if count != self._last_tab_count:
            self._last_tab_count = count
            self.schedule_full(delay_ms=AUTOSAVE_STRUCTURE_CHANGE_DELAY_MS)

    def _on_canvas_structure_changed(self, *_args) -> None:
        if (not self._enabled) or self._suspended:
            return
        self.rewire_editors()
        self.schedule_full(delay_ms=AUTOSAVE_STRUCTURE_CHANGE_DELAY_MS)

    @staticmethod
    def _write_text_atomic(path: Path, content: str) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(str(content or ""), encoding="utf-8")
        tmp.replace(target)
