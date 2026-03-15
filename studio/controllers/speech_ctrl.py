"""Speech controller — Whisper dictation and TTS management."""
from __future__ import annotations

import os
from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QSettings, Signal
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox, QWidget

from shared.config.app_settings import SpeechSettings
from shared.services.speech.tts import TextToSpeechManager
from shared.services.speech.dictation import WhisperDictationWorker
from studio.dialogs.window_manager import find_dialog_manager

if TYPE_CHECKING:
    from studio.canvas.tabs import CanvasTabWidget
    from studio.chat.dock import ChatDock
    from studio.knowledge.dock import KnowledgeDock
    from studio.logger import AppLogger


class SpeechController(QObject):
    """Manages Whisper dictation and TTS lifecycle."""

    dictation_running_changed = Signal(bool)

    def __init__(
        self,
        *,
        parent: QObject,
        canvas: CanvasTabWidget,
        knowledge_dock: KnowledgeDock,
        chat_dock: ChatDock,
        app_logger: AppLogger,
        app_settings: QSettings,
        show_status: Callable[[str, int], None],
        autosave_schedule_fn: Callable[[int], None],
        on_tts_speaking_changed: Callable[[bool], None],
    ):
        super().__init__(parent)
        self._canvas = canvas
        self._knowledge_dock = knowledge_dock
        self._chat_dock = chat_dock
        self._app_logger = app_logger
        self._app_settings = app_settings
        self._show_status = show_status
        self._autosave_schedule_fn = autosave_schedule_fn
        self._on_tts_speaking_changed_cb = on_tts_speaking_changed

        self._speech_settings = SpeechSettings()
        self._tts_manager = TextToSpeechManager(parent)
        self._dictation_worker: WhisperDictationWorker | None = None
        self._dictation_target_panel: QWidget | None = None
        self._dictation_running: bool = False
        self._last_workspace_panel: object | None = None
        self._cached_workspace_selection_text: str = ""

        # Wire TTS signals
        self._tts_manager.status.connect(self._on_tts_status)
        self._tts_manager.error.connect(self._on_tts_error)
        self._tts_manager.speaking_changed.connect(self._on_tts_speaking_changed_internal)
        app = QApplication.instance()
        if app is not None:
            app.focusChanged.connect(self._on_focus_changed)

    # ── Properties ────────────────────────────────────────────────────

    @property
    def dictation_running(self) -> bool:
        return self._dictation_running

    @property
    def speech_settings(self) -> SpeechSettings:
        return self._speech_settings

    @property
    def tts_manager(self) -> TextToSpeechManager:
        return self._tts_manager

    # ── Public interface ───────────────────────────────────────────────

    def get_speech_settings(self) -> dict:
        return self._speech_settings.to_dict()

    def apply_speech_settings(self, raw: object):
        self._speech_settings = SpeechSettings.from_dict(raw)
        self._apply_runtime_settings()

    def open_speech_settings_dialog(self, parent_widget: QWidget):
        from studio.speech.settings_dialog import SpeechSettingsDialog  # local import
        current_mode = str(getattr(parent_widget, "user_mode", "") or "")
        manager = find_dialog_manager(parent_widget)
        if manager is not None:
            manager.show_dialog(
                "speech-settings",
                lambda: SpeechSettingsDialog(
                    self._speech_settings,
                    parent_widget,
                    user_mode=current_mode,
                ),
                on_accept=lambda dialog: self._apply_speech_settings_dialog(dialog),
            )
            return
        dialog = SpeechSettingsDialog(
            self._speech_settings,
            parent_widget,
            user_mode=current_mode,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._apply_speech_settings_dialog(dialog)

    def start_whisper_dictation(self):
        if self._dictation_worker is not None and self._dictation_worker.isRunning():
            self._show_status("Whisper-Diktat läuft bereits.", 2500)
            return

        stt = self._speech_settings
        input_device = str(stt.stt_input_device or "").strip()
        if (
            not input_device
            and os.name != "nt"
            and str(stt.stt_backend or "auto").strip().lower() != "sounddevice"
        ):
            input_device = "pipewire"
        threads = max(1, min(int(stt.stt_cpu_threads), os.cpu_count() or 4))

        self._open_new_dictation_target_tab()
        worker = WhisperDictationWorker(
            parent=self.parent(),
            model_size=stt.stt_model_size or "tiny",
            language=stt.stt_language or "",
            device="cpu",
            audio_device=input_device,
            audio_backend=stt.stt_backend or "auto",
            compute_type=stt.stt_compute_type or "int8",
            cpu_threads=threads,
        )
        worker.started_ok.connect(self._on_dictation_started)
        worker.stopped_ok.connect(self._on_dictation_stopped)
        worker.status.connect(self._on_dictation_status)
        worker.text_chunk.connect(self._on_dictation_text_chunk)
        worker.failed.connect(self._on_dictation_failed)
        worker.finished.connect(self._on_dictation_finished)
        self._dictation_worker = worker
        self._set_dictation_running(True)
        self._app_logger.info(
            "STT",
            "Config | "
            f"backend={stt.stt_backend} "
            f"input={input_device or 'auto'} "
            f"model={stt.stt_model_size} "
            f"lang={stt.stt_language or 'auto'} "
            f"compute={stt.stt_compute_type} "
            f"threads={threads}",
        )
        self._app_logger.info("STT", "Whisper-Diktat gestartet.")
        self._show_status("Starte Whisper-Diktat…", 2500)
        worker.start()

    def stop_whisper_dictation(self):
        worker = self._dictation_worker
        if worker is None or not worker.isRunning():
            self._set_dictation_running(False)
            self._show_status("Whisper-Diktat ist nicht aktiv.", 2000)
            return
        worker.request_stop()
        self._show_status("Stoppe Whisper-Diktat…", 3000)

    def speak_draft_text(self, text: str):
        payload = str(text or "").strip()
        if not payload:
            self._show_status("Draft ist leer.", 2000)
            return
        self._tts_manager.speak(payload, interrupt=True)

    def speak_selection_text(self, text: str) -> None:
        payload = str(text or "").strip()
        if not payload:
            self._show_status("Keine Auswahl zum Vorlesen.", 2000)
            return
        self._tts_manager.speak(payload, interrupt=True)

    def speak_chat_text(self, text: str):
        payload = str(text or "").strip()
        if not payload:
            self._show_status("Keine Chat-Antwort zum Vorlesen.", 2000)
            return
        self._tts_manager.speak(payload, interrupt=True)

    def speak_active_workspace_text(self) -> None:
        """Read selected text or full active draft/viewer/rag pane."""
        payload = self._resolve_active_workspace_tts_payload()
        if not payload:
            self._show_status(
                "Keine Markierung oder Text im aktiven Draft/Viewer/RAG gefunden.",
                2500,
            )
            return
        self._tts_manager.speak(payload, interrupt=True)

    def stop_tts(self):
        if not self._tts_manager.is_speaking():
            self._show_status("TTS ist nicht aktiv.", 1500)
            return
        self._tts_manager.stop()
        self._show_status("TTS gestoppt.", 2500)

    def stop_all(self):
        """Stop dictation worker and TTS on shutdown."""
        if self._dictation_worker is not None:
            self._dictation_worker.request_stop()
            self._dictation_worker.wait(3000)
        self._tts_manager.stop()

    def apply_dictation_running_to_actions(
        self,
        running: bool,
        *,
        start_action: object | None = None,
        stop_action: object | None = None,
    ) -> None:
        if start_action is not None and hasattr(start_action, "setEnabled"):
            start_action.setEnabled(not bool(running))
        if stop_action is not None and hasattr(stop_action, "setEnabled"):
            stop_action.setEnabled(bool(running))

    def apply_tts_speaking_state(self, speaking: bool) -> None:
        active = bool(speaking)
        self._canvas.set_read_aloud_active(active)
        self._chat_dock.set_read_aloud_active(active)

    # ── Private helpers ────────────────────────────────────────────────

    def _apply_runtime_settings(self):
        self._tts_manager.update_settings(self._speech_settings)
        try:
            self._chat_dock.set_chat_tts_mode(self._speech_settings.chat_tts_mode)
        except Exception as exc:
            self._app_logger.warning(
                "STT",
                f"Applying chat TTS mode failed: {exc}",
            )

    def _apply_speech_settings_dialog(self, dialog: QDialog) -> None:
        get_settings = getattr(dialog, "get_settings", None)
        if not callable(get_settings):
            return
        self._speech_settings = get_settings()
        self._apply_runtime_settings()
        self._app_logger.info(
            "STT",
            "Speech settings updated | "
            f"backend={self._speech_settings.stt_backend} "
            f"input={self._speech_settings.stt_input_device or 'auto'} "
            f"model={self._speech_settings.stt_model_size}",
        )
        try:
            self._autosave_schedule_fn(300)
        except Exception as exc:
            self._app_logger.warning(
                "STT",
                f"Autosave scheduling after speech settings update failed: {exc}",
            )
        self._show_status("Speech settings gespeichert.", 2500)

    def _set_dictation_running(self, running: bool):
        self._dictation_running = bool(running)
        self.dictation_running_changed.emit(self._dictation_running)

    def _open_new_dictation_target_tab(self) -> QWidget:
        tabs = self._canvas.tabs.tab_widget
        previous_idx = tabs.currentIndex()
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        title = f"Transkript {datetime.now().strftime('%H:%M')}"
        header = (
            f"# {title}\n\n"
            f"_Whisper-Session gestartet: {stamp}_\n\n"
        )
        panel = self._canvas.tabs.add_tab(
            title=title,
            content=header,
            read_only=False,
        )
        self._dictation_target_panel = panel
        if 0 <= previous_idx < tabs.count():
            tabs.setCurrentIndex(previous_idx)
        return panel

    def _ensure_dictation_target_panel(self) -> QWidget:
        if self._is_canvas_panel_open(self._dictation_target_panel):
            return self._dictation_target_panel  # type: ignore[return-value]
        return self._open_new_dictation_target_tab()

    def _is_canvas_panel_open(self, panel: QWidget | None) -> bool:
        if panel is None:
            return False
        tabs = self._canvas.tabs.tab_widget
        for idx in range(tabs.count()):
            if tabs.widget(idx) is panel:
                return True
        return False

    @staticmethod
    def _widget_belongs_to(widget: QWidget | None, root: QWidget | None) -> bool:
        current = widget
        while current is not None:
            if current is root:
                return True
            current = current.parentWidget()
        return False

    @staticmethod
    def _normalize_qt_selected_text(value: str) -> str:
        return (
            str(value or "")
            .replace("\u2029", "\n")
            .replace("\u2028", "\n")
            .strip()
        )

    def _resolve_knowledge_current_panel(self) -> object | None:
        current = self._knowledge_dock.tab_widget.currentWidget()
        if current is self._knowledge_dock.doc_viewer:
            return self._knowledge_dock.doc_viewer.tabs.current_panel()
        if current is self._knowledge_dock.rag_tab:
            return self._knowledge_dock.rag_panel.tabs.current_panel()
        return None

    def _resolve_workspace_panel_from_widget(
        self,
        widget: QWidget | None,
    ) -> object | None:
        if self._widget_belongs_to(widget, self._canvas):
            return self._canvas.tabs.current_panel()
        if self._widget_belongs_to(widget, self._knowledge_dock):
            return self._resolve_knowledge_current_panel()
        return None

    @staticmethod
    def _panel_available(panel: object | None) -> bool:
        if panel is None:
            return False
        try:
            return getattr(panel, "editor", None) is not None
        except RuntimeError:
            return False

    @classmethod
    def _panel_selected_text(cls, panel: object | None) -> str:
        if panel is None:
            return ""
        try:
            preview_getter = getattr(panel, "get_preview_selected_text", None)
            if callable(preview_getter):
                selected = cls._normalize_qt_selected_text(preview_getter())
                if selected:
                    return selected
            editor = getattr(panel, "editor", None)
            if editor is None:
                return ""
            cursor = editor.textCursor()
            return cls._normalize_qt_selected_text(cursor.selectedText())
        except Exception:
            return ""

    @classmethod
    def _panel_full_text(cls, panel: object | None) -> str:
        if panel is None:
            return ""
        try:
            editor = getattr(panel, "editor", None)
            if editor is None:
                return ""
            getter = getattr(editor, "get_full_text", None)
            if callable(getter):
                return str(getter() or "").strip()
            return str(editor.toPlainText() or "").strip()
        except Exception:
            return ""

    def _resolve_active_workspace_tts_payload(self) -> str:
        focus = QApplication.focusWidget()
        panel = self._resolve_workspace_panel_from_widget(focus)
        focus_in_workspace = self._panel_available(panel)
        knowledge_panel = self._resolve_knowledge_current_panel()
        canvas_panel = self._canvas.tabs.current_panel()

        candidates: list[object] = []
        for candidate in (
            panel,
            knowledge_panel,
            canvas_panel,
            self._last_workspace_panel,
        ):
            if candidate is None:
                continue
            if not self._panel_available(candidate):
                continue
            if any(existing is candidate for existing in candidates):
                continue
            candidates.append(candidate)

        for candidate in candidates:
            selected = self._panel_selected_text(candidate)
            if not selected:
                continue
            self._last_workspace_panel = candidate
            self._cached_workspace_selection_text = selected
            return selected

        if self._panel_available(panel):
            self._last_workspace_panel = panel
        elif self._panel_available(self._last_workspace_panel):
            panel = self._last_workspace_panel
        else:
            panel = canvas_panel

        if not focus_in_workspace and self._cached_workspace_selection_text:
            cached = str(self._cached_workspace_selection_text or "").strip()
            self._cached_workspace_selection_text = ""
            if cached:
                return cached
        return self._panel_full_text(panel)

    # ── Signal slots ───────────────────────────────────────────────────

    def _on_focus_changed(
        self,
        old: QWidget | None,
        now: QWidget | None,
    ) -> None:
        previous_panel = self._resolve_workspace_panel_from_widget(old)
        if self._panel_available(previous_panel):
            self._last_workspace_panel = previous_panel
            selected_before_blur = self._panel_selected_text(previous_panel)
            if selected_before_blur:
                self._cached_workspace_selection_text = selected_before_blur

        panel = self._resolve_workspace_panel_from_widget(now)
        if not self._panel_available(panel):
            return
        self._last_workspace_panel = panel
        selected_now = self._panel_selected_text(panel)
        if selected_now:
            self._cached_workspace_selection_text = selected_now
        else:
            self._cached_workspace_selection_text = ""

    def on_chat_tts_mode_changed(self, mode: str):
        self._speech_settings.chat_tts_mode = str(mode or "off")
        try:
            self._autosave_schedule_fn(350)
        except Exception as exc:
            self._app_logger.warning(
                "STT",
                f"Autosave scheduling after chat TTS mode change failed: {exc}",
            )

    def _on_dictation_started(self):
        self._show_status("Whisper-Diktat läuft.", 2500)

    def _on_dictation_status(self, message: str):
        text = str(message or "").strip()
        if text:
            self._app_logger.debug("STT", text)
            self._show_status(text, 4000)

    def _on_dictation_text_chunk(self, text: str):
        chunk = str(text or "").strip()
        if not chunk:
            return
        self._show_status(
            f"Whisper erkannt: {chunk[:60]}{'…' if len(chunk) > 60 else ''}",
            1800,
        )
        panel = self._ensure_dictation_target_panel()
        editor = getattr(panel, "editor", None)
        if editor is None:
            return

        cursor = editor.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        existing = editor.toPlainText()
        joiner = ""
        if existing and not existing.endswith((" ", "\n", "\t")):
            joiner = " "
        ending = "\n\n" if chunk.endswith((".", "!", "?", "…")) else " "
        cursor.insertText(f"{joiner}{chunk}{ending}")
        editor.setTextCursor(cursor)

    def _on_dictation_failed(self, message: str):
        msg = str(message or "Unbekannter Fehler im Whisper-Diktat.")
        self._app_logger.error("STT", msg)
        self._show_status(f"Whisper-Fehler: {msg}", 6000)
        QMessageBox.warning(
            None,
            "Whisper Dictation",
            msg,
        )
        self._set_dictation_running(False)
        self._dictation_worker = None

    def _on_dictation_stopped(self):
        self._app_logger.info("STT", "Whisper-Diktat gestoppt.")
        self._show_status("Whisper-Diktat gestoppt.", 3000)
        self._set_dictation_running(False)
        self._dictation_worker = None

    def _on_dictation_finished(self):
        worker = self._dictation_worker
        if worker is not None and worker.isRunning():
            return
        self._set_dictation_running(False)
        self._dictation_worker = None

    def _on_tts_speaking_changed_internal(self, speaking: bool):
        try:
            self._on_tts_speaking_changed_cb(bool(speaking))
        except Exception as exc:
            self._app_logger.warning(
                "TTS",
                f"TTS speaking-state callback failed: {exc}",
            )

    def _on_tts_status(self, message: str):
        text = str(message or "").strip()
        if not text:
            return
        self._app_logger.debug("TTS", text)
        self._show_status(text, 2500)

    def _on_tts_error(self, message: str):
        text = str(message or "").strip() or "Unbekannter TTS-Fehler."
        self._app_logger.error("TTS", text)
        self._show_status(f"TTS-Fehler: {text}", 6000)
        QMessageBox.warning(None, "Text to Speech", text)
