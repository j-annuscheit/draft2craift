from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QDialogButtonBox

from shared.config.app_settings import SpeechSettings
from shared.domain.user_mode import USER_MODE_CONFIG_PATH, reload_user_mode_config
from studio.speech.settings_dialog import SpeechSettingsDialog


def _write_speech_mode_config(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "alpha.toml").write_text(
        """
version = 1
id = "alpha"
label = "Alpha"
order = 0
default_profile = true

[visibility]

[labels]
"speech.settings.window_title" = "Speech Settings"
"speech.settings.intro" = "Configure microphone/headset."
"speech.settings.tab.stt" = "STT"
"speech.settings.tab.tts" = "TTS"
"speech.settings.group.stt" = "Speech-to-Text"
"speech.settings.group.tts" = "Text-to-Speech"
"speech.settings.field.audio_backend" = "Audio backend:"
"speech.settings.field.microphone" = "Microphone:"
"speech.settings.field.level_test" = "Level test:"
"speech.settings.field.whisper_model" = "Whisper model:"
"speech.settings.field.language" = "Language:"
"speech.settings.field.compute_type" = "Compute type:"
"speech.settings.field.cpu_threads" = "CPU threads:"
"speech.settings.field.tts_engine" = "TTS engine:"
"speech.settings.field.chat_read_aloud" = "Read chat aloud:"
"speech.settings.field.tts_language" = "TTS language:"
"speech.settings.field.piper_model" = "Piper model:"
"speech.settings.field.speaker_id" = "Speaker ID:"
"speech.settings.field.output_device" = "Output device:"
"speech.settings.field.voice" = "Voice:"
"speech.settings.field.rate" = "Rate (%):"
"speech.settings.field.volume" = "Volume (%):"
"speech.settings.field.pause_ms" = "Pause (ms):"
"speech.settings.field.trigger_pause_ms" = "Trigger pause (ms):"
"speech.settings.field.lead_in_ms" = "Start lead-in (ms):"
"speech.settings.field.start_trigger" = "Start trigger:"
"speech.settings.field.pause_trigger" = "Pause trigger:"
"speech.settings.button.refresh" = "Refresh"
"speech.settings.button.scan" = "Scan"
"speech.settings.button.browse" = "Browse"
"speech.settings.button.test_input" = "Test Input"
"speech.settings.button.stop_test" = "Stop Test"
"speech.settings.button.ok" = "OK"
"speech.settings.button.cancel" = "Cancel"
""".strip(),
        encoding="utf-8",
    )

    (path / "beta.toml").write_text(
        """
version = 1
id = "beta"
label = "Beta"
order = 1
default_profile = false

[visibility]

[labels]
"speech.settings.window_title" = "Speech Einstellungen"
"speech.settings.intro" = "Mikrofon/Headset konfigurieren."
"speech.settings.tab.stt" = "STT (Whisper)"
"speech.settings.tab.tts" = "TTS"
"speech.settings.group.stt" = "Speech-to-Text"
"speech.settings.group.tts" = "Text-to-Speech"
"speech.settings.field.audio_backend" = "Audio backend:"
"speech.settings.field.microphone" = "Mikrofon:"
"speech.settings.field.level_test" = "Pegeltest:"
"speech.settings.field.whisper_model" = "Whisper model:"
"speech.settings.field.language" = "Sprache:"
"speech.settings.field.compute_type" = "Compute type:"
"speech.settings.field.cpu_threads" = "CPU threads:"
"speech.settings.field.tts_engine" = "TTS engine:"
"speech.settings.field.chat_read_aloud" = "Chat Vorlesen:"
"speech.settings.field.tts_language" = "TTS Sprache:"
"speech.settings.field.piper_model" = "Piper Modell:"
"speech.settings.field.speaker_id" = "Speaker-ID:"
"speech.settings.field.output_device" = "Output device:"
"speech.settings.field.voice" = "Voice:"
"speech.settings.field.rate" = "Rate (%):"
"speech.settings.field.volume" = "Volume (%):"
"speech.settings.field.pause_ms" = "Pause (ms):"
"speech.settings.field.trigger_pause_ms" = "Trigger-Pause (ms):"
"speech.settings.field.lead_in_ms" = "Start-Vorlauf (ms):"
"speech.settings.field.start_trigger" = "Start-Trigger:"
"speech.settings.field.pause_trigger" = "Pause-Trigger:"
"speech.settings.button.refresh" = "Refresh"
"speech.settings.button.scan" = "Scan"
"speech.settings.button.browse" = "Browse"
"speech.settings.button.test_input" = "Test Input"
"speech.settings.button.stop_test" = "Stop Test"
"speech.settings.button.ok" = "OK"
"speech.settings.button.cancel" = "Abbrechen"
""".strip(),
        encoding="utf-8",
    )


def test_speech_settings_dialog_labels_are_profile_driven(tmp_path: Path, qt_app):
    _ = qt_app
    cfg = tmp_path / "user_modes"
    _write_speech_mode_config(cfg)

    try:
        reload_user_mode_config(cfg)
        dialog = SpeechSettingsDialog(SpeechSettings(), user_mode="beta")

        ok_btn = dialog._buttons_box.button(QDialogButtonBox.StandardButton.Ok)
        cancel_btn = dialog._buttons_box.button(QDialogButtonBox.StandardButton.Cancel)

        assert dialog.windowTitle() == "Speech Einstellungen"
        assert dialog._intro_label.text() == "Mikrofon/Headset konfigurieren."
        assert dialog.tabs.tabText(0) == "STT (Whisper)"
        assert dialog.tabs.tabText(1) == "TTS"
        assert dialog._stt_group.title() == "Speech-to-Text"
        assert dialog._tts_group.title() == "Text-to-Speech"
        assert dialog._stt_row_labels["microphone"].text() == "Mikrofon:"
        assert dialog._stt_row_labels["level_test"].text() == "Pegeltest:"
        assert dialog._stt_row_labels["language"].text() == "Sprache:"
        assert dialog._tts_row_labels["chat_read_aloud"].text() == "Chat Vorlesen:"
        assert dialog._tts_row_labels["piper_model"].text() == "Piper Modell:"
        assert dialog._tts_row_labels["speaker_id"].text() == "Speaker-ID:"
        assert dialog._tts_row_labels["pause_trigger"].text() == "Pause-Trigger:"
        assert dialog.refresh_input_btn.text() == "Refresh"
        assert dialog.piper_refresh_btn.text() == "Scan"
        assert dialog.piper_browse_btn.text() == "Browse"
        assert dialog.tts_refresh_btn.text() == "Refresh"
        assert ok_btn is not None and ok_btn.text() == "OK"
        assert cancel_btn is not None and cancel_btn.text() == "Abbrechen"

        dialog.set_user_mode("alpha")
        assert dialog.windowTitle() == "Speech Settings"
        assert dialog._intro_label.text() == "Configure microphone/headset."
        assert dialog._stt_row_labels["microphone"].text() == "Microphone:"
        assert dialog._stt_row_labels["level_test"].text() == "Level test:"
        assert dialog._stt_row_labels["language"].text() == "Language:"
        assert dialog._tts_row_labels["chat_read_aloud"].text() == "Read chat aloud:"
        assert dialog._tts_row_labels["piper_model"].text() == "Piper model:"
        assert dialog._tts_row_labels["speaker_id"].text() == "Speaker ID:"
        assert dialog._tts_row_labels["pause_trigger"].text() == "Pause trigger:"
        assert ok_btn.text() == "OK"
        assert cancel_btn.text() == "Cancel"
    finally:
        reload_user_mode_config(USER_MODE_CONFIG_PATH)
