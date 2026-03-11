"""Speech controller — Whisper dictation and TTS management."""
from __future__ import annotations

import os
from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QSettings, Signal
from PySide6.QtWidgets import QDialog, QMessageBox, QWidget

from shared.config.app_settings import SpeechSettings
from shared.services.speech.tts import TextToSpeechManager
from shared.services.speech.dictation import WhisperDictationWorker
from studio.dialogs.window_manager import find_dialog_manager

if TYPE_CHECKING:
    from studio.canvas.tabs import CanvasTabWidget
    from studio.chat.dock import ChatDock
    from studio.logger import AppLogger


class SpeechController(QObject):
    """Manages Whisper dictation and TTS lifecycle."""

    dictation_running_changed = Signal(bool)

    def __init__(
        self,
        *,
        parent: QObject,
        canvas: CanvasTabWidget,
        chat_dock: ChatDock,
        app_logger: AppLogger,
        app_settings: QSettings,
        show_status: Callable[[str, int], None],
        autosave_schedule_fn: Callable[[int], None],
        on_tts_speaking_changed: Callable[[bool], None],
    ):
        super().__init__(parent)
        self._canvas = canvas
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

        # Wire TTS signals
        self._tts_manager.status.connect(self._on_tts_status)
        self._tts_manager.error.connect(self._on_tts_error)
        self._tts_manager.speaking_changed.connect(self._on_tts_speaking_changed_internal)

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
        manager = find_dialog_manager(parent_widget)
        if manager is not None:
            manager.show_dialog(
                "speech-settings",
                lambda: SpeechSettingsDialog(self._speech_settings, parent_widget),
                on_accept=lambda dialog: self._apply_speech_settings_dialog(dialog),
            )
            return
        dialog = SpeechSettingsDialog(self._speech_settings, parent_widget)
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

    def speak_chat_text(self, text: str):
        payload = str(text or "").strip()
        if not payload:
            self._show_status("Keine Chat-Antwort zum Vorlesen.", 2000)
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

    # ── Signal slots ───────────────────────────────────────────────────

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
