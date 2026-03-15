from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from shared.config.app_settings import SpeechSettings
from shared.config.setting_keys import SpeechSettingsKeys
from shared.domain.user_mode import (
    default_user_mode,
    normalize_user_mode,
    resolve_feature_label,
)
from shared.services.speech.devices import list_input_devices, list_output_devices
from shared.services.speech.level_probe import InputLevelProbeWorker
from shared.services.speech.piper_models import (
    list_local_piper_models,
    refresh_local_piper_models_cache,
)

_BACKENDS = (
    ("auto", "Auto"),
    ("arecord", "arecord (Linux stable)"),
    ("sounddevice", "sounddevice (PortAudio)"),
)
_WHISPER_MODELS = ("tiny", "base", "small", "medium", "large-v3")
_COMPUTE_TYPES = ("int8", "int8_float16", "float16", "float32")
_TTS_ENGINES = ("none", "piper", "pyttsx3", "spd-say", "espeak")
_TTS_LANGUAGES = (
    ("de", "Deutsch"),
    ("en", "English"),
    ("fr", "Francais"),
    ("es", "Espanol"),
    ("it", "Italiano"),
    ("nl", "Nederlands"),
    ("pl", "Polski"),
    ("cs", "Cesky"),
    ("uk", "Ukrainska"),
)
_CHAT_TTS_MODES = (
    ("off", "aus"),
    ("once", "einmal vorlesen"),
    ("always", "an (immer vorlesen)"),
)


class SpeechSettingsDialog(QDialog):
    def __init__(
        self,
        settings: SpeechSettings,
        parent=None,
        user_mode: str | None = None,
    ):
        super().__init__(parent)
        self.resize(700, 460)
        self._probe_worker: InputLevelProbeWorker | None = None
        self._base = SpeechSettings.from_dict(settings.to_dict())
        self._user_mode = normalize_user_mode(
            default_user_mode() if user_mode is None else user_mode
        )
        self._stt_row_labels: dict[str, QLabel] = {}
        self._tts_row_labels: dict[str, QLabel] = {}

        self._build_ui()
        self.set_user_mode(self._user_mode)
        self._load_values()
        self._refresh_input_devices()
        self._refresh_output_devices()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        self._intro_label = QLabel(
            "Mikrofon/Headset fuer Whisper-Diktat konfigurieren.\n"
            "STT/TTS laufen lokal."
        )
        self._intro_label.setWordWrap(True)
        self._intro_label.setStyleSheet("color: #CDD6F4;")
        root.addWidget(self._intro_label)

        self.tabs = QTabWidget()
        self._stt_tab = self._build_stt_tab()
        self._tts_tab = self._build_tts_tab()
        self.tabs.addTab(self._stt_tab, "STT (Whisper)")
        self.tabs.addTab(self._tts_tab, "TTS")
        root.addWidget(self.tabs, 1)

        self._status_label = QLabel("")
        self._status_label.setStyleSheet("color: #89B4FA;")
        root.addWidget(self._status_label)

        self._buttons_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        self._buttons_box.accepted.connect(self.accept)
        self._buttons_box.rejected.connect(self.reject)
        root.addWidget(self._buttons_box)

    def _build_stt_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        self._stt_group = QGroupBox("Speech-to-Text")
        self._stt_form = QFormLayout(self._stt_group)
        self._stt_form.setHorizontalSpacing(14)
        self._stt_form.setVerticalSpacing(8)

        self.backend_combo = self._new_combo(_BACKENDS)
        self.backend_combo.currentIndexChanged.connect(self._refresh_input_devices)
        self._add_form_row(
            self._stt_form,
            self._stt_row_labels,
            "audio_backend",
            "Audio backend:",
            self.backend_combo,
        )

        self.input_combo = QComboBox()
        self.input_combo.setEditable(True)
        line_edit = self.input_combo.lineEdit()
        if line_edit is not None:
            line_edit.setPlaceholderText("device name/index")
        self.refresh_input_btn = QPushButton("Refresh")
        self.refresh_input_btn.clicked.connect(self._refresh_input_devices)
        self._input_row = self._row_with_buttons(self.input_combo, self.refresh_input_btn)
        self._add_form_row(
            self._stt_form,
            self._stt_row_labels,
            "microphone",
            "Mikrofon:",
            self._input_row,
        )

        self.test_btn = QPushButton("Test Input")
        self.test_btn.clicked.connect(self._toggle_probe)
        self.level_bar = QProgressBar()
        self.level_bar.setRange(0, 100)
        self.level_bar.setValue(0)
        self.level_bar.setFormat("input level: %p%")
        self._level_row = self._row_with_buttons(self.level_bar, self.test_btn)
        self._add_form_row(
            self._stt_form,
            self._stt_row_labels,
            "level_test",
            "Pegeltest:",
            self._level_row,
        )

        self.model_combo = self._new_combo(
            ((model, model) for model in _WHISPER_MODELS),
            editable=True,
        )
        model_edit = self.model_combo.lineEdit()
        if model_edit is not None:
            model_edit.setPlaceholderText("tiny/base/... oder lokaler Modellpfad")
        self._add_form_row(
            self._stt_form,
            self._stt_row_labels,
            "whisper_model",
            "Whisper model:",
            self.model_combo,
        )

        self.language_edit = QLineEdit()
        self.language_edit.setPlaceholderText("de / en / auto(empty)")
        self._add_form_row(
            self._stt_form,
            self._stt_row_labels,
            "language",
            "Sprache:",
            self.language_edit,
        )

        self.compute_combo = self._new_combo(
            ((compute_type, compute_type) for compute_type in _COMPUTE_TYPES)
        )
        self._add_form_row(
            self._stt_form,
            self._stt_row_labels,
            "compute_type",
            "Compute type:",
            self.compute_combo,
        )

        self.cpu_threads_spin = self._new_spin(1, 64, step=1)
        self._add_form_row(
            self._stt_form,
            self._stt_row_labels,
            "cpu_threads",
            "CPU threads:",
            self.cpu_threads_spin,
        )

        layout.addWidget(self._stt_group)
        layout.addStretch(1)
        return page

    def _build_tts_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        self._tts_group = QGroupBox("Text-to-Speech")
        self._tts_form = QFormLayout(self._tts_group)
        self._tts_form.setHorizontalSpacing(14)
        self._tts_form.setVerticalSpacing(8)

        self.tts_engine_combo = self._new_combo(
            ((engine, engine) for engine in _TTS_ENGINES)
        )
        self.tts_engine_combo.currentIndexChanged.connect(self._on_tts_engine_changed)
        self._add_form_row(
            self._tts_form,
            self._tts_row_labels,
            "tts_engine",
            "TTS engine:",
            self.tts_engine_combo,
        )

        self.chat_tts_mode_combo = self._new_combo(_CHAT_TTS_MODES)
        self._add_form_row(
            self._tts_form,
            self._tts_row_labels,
            "chat_read_aloud",
            "Chat Vorlesen:",
            self.chat_tts_mode_combo,
        )

        self.tts_language_combo = self._new_combo(
            ((code, f"{name} ({code})") for code, name in _TTS_LANGUAGES),
            editable=True,
        )
        self.tts_language_combo.currentIndexChanged.connect(self._refresh_piper_models)
        self._add_form_row(
            self._tts_form,
            self._tts_row_labels,
            "tts_language",
            "TTS Sprache:",
            self.tts_language_combo,
        )

        self.piper_model_combo = QComboBox()
        self.piper_model_combo.setEditable(True)
        piper_edit = self.piper_model_combo.lineEdit()
        if piper_edit is not None:
            piper_edit.setPlaceholderText("lokales .onnx Modell")
        self.piper_refresh_btn = QPushButton("Scan")
        self.piper_refresh_btn.clicked.connect(self._refresh_piper_models)
        self.piper_browse_btn = QPushButton("Browse")
        self.piper_browse_btn.clicked.connect(self._browse_piper_model)
        self._piper_row = self._row_with_buttons(
            self.piper_model_combo,
            self.piper_refresh_btn,
            self.piper_browse_btn,
        )
        self._add_form_row(
            self._tts_form,
            self._tts_row_labels,
            "piper_model",
            "Piper Modell:",
            self._piper_row,
        )

        self.tts_speaker_spin = self._new_spin(-1, 999, tooltip="-1=default")
        self._add_form_row(
            self._tts_form,
            self._tts_row_labels,
            "speaker_id",
            "Speaker-ID:",
            self.tts_speaker_spin,
        )

        self.tts_output_combo = QComboBox()
        self.tts_output_combo.setEditable(True)
        output_edit = self.tts_output_combo.lineEdit()
        if output_edit is not None:
            output_edit.setPlaceholderText("output device")
        self.tts_refresh_btn = QPushButton("Refresh")
        self.tts_refresh_btn.clicked.connect(self._refresh_output_devices)
        self._output_row = self._row_with_buttons(
            self.tts_output_combo,
            self.tts_refresh_btn,
        )
        self._add_form_row(
            self._tts_form,
            self._tts_row_labels,
            "output_device",
            "Output device:",
            self._output_row,
        )

        self.tts_voice_edit = QLineEdit()
        self.tts_voice_edit.setPlaceholderText("voice id (optional)")
        self._add_form_row(
            self._tts_form,
            self._tts_row_labels,
            "voice",
            "Voice:",
            self.tts_voice_edit,
        )

        specs = [
            ("tts_rate_spin", "rate", "Rate (%):", 50, 300, 5, "", ""),
            ("tts_volume_spin", "volume", "Volume (%):", 0, 100, 5, "", ""),
            (
                "tts_pause_spin",
                "pause_ms",
                "Pause (ms):",
                0,
                2000,
                25,
                " ms",
                "Pause zwischen Segmenten",
            ),
            (
                "tts_trigger_pause_spin",
                "trigger_pause_ms",
                "Trigger-Pause (ms):",
                0,
                4000,
                25,
                " ms",
                "Extra-Pause bei Triggern",
            ),
            (
                "tts_lead_in_spin",
                "lead_in_ms",
                "Start-Vorlauf (ms):",
                0,
                2000,
                25,
                " ms",
                "Leiser Vorlauf",
            ),
        ]
        for attr, key, label, lo, hi, step, suffix, tip in specs:
            spin = self._new_spin(lo, hi, step=step, suffix=suffix, tooltip=tip)
            setattr(self, attr, spin)
            self._add_form_row(
                self._tts_form,
                self._tts_row_labels,
                key,
                label,
                spin,
            )

        self.tts_start_trigger_edit = QLineEdit()
        self.tts_start_trigger_edit.setPlaceholderText("optional, z. B. hm")
        self._add_form_row(
            self._tts_form,
            self._tts_row_labels,
            "start_trigger",
            "Start-Trigger:",
            self.tts_start_trigger_edit,
        )

        self.tts_pause_triggers_edit = QLineEdit()
        self.tts_pause_triggers_edit.setPlaceholderText(",|:|;| - |-|")
        self._add_form_row(
            self._tts_form,
            self._tts_row_labels,
            "pause_trigger",
            "Pause-Trigger:",
            self.tts_pause_triggers_edit,
        )

        self._tts_note_label = QLabel(
            "Hinweis: Piper liefert meist die beste lokale Qualitaet."
        )
        self._tts_note_label.setWordWrap(True)
        self._tts_note_label.setStyleSheet("color: #BAC2DE;")
        layout.addWidget(self._tts_group)
        layout.addWidget(self._tts_note_label)
        layout.addStretch(1)
        return page

    def _load_values(self) -> None:
        self._set_combo_data(self.backend_combo, self._base.stt_backend)
        self._set_combo_data(self.model_combo, self._base.stt_model_size)
        self._set_combo_data(self.compute_combo, self._base.stt_compute_type)
        self.language_edit.setText(self._base.stt_language)
        self.cpu_threads_spin.setValue(self._base.stt_cpu_threads)

        self._set_combo_data(self.tts_engine_combo, self._base.tts_engine)
        self._set_combo_data(self.chat_tts_mode_combo, self._base.chat_tts_mode)
        self._set_combo_data(self.tts_language_combo, self._base.tts_language or "de")
        self._set_combo_data(self.piper_model_combo, self._base.tts_model_path)
        self.tts_speaker_spin.setValue(self._base.tts_speaker_id)
        self.tts_voice_edit.setText(self._base.tts_voice)
        self.tts_rate_spin.setValue(self._base.tts_rate)
        self.tts_volume_spin.setValue(self._base.tts_volume)
        self.tts_pause_spin.setValue(self._base.tts_pause_ms)
        self.tts_trigger_pause_spin.setValue(self._base.tts_trigger_pause_ms)
        self.tts_lead_in_spin.setValue(self._base.tts_lead_in_ms)
        self.tts_start_trigger_edit.setText(self._base.tts_start_trigger)
        self.tts_pause_triggers_edit.setText(self._base.tts_pause_triggers)
        self._refresh_piper_models()
        self._on_tts_engine_changed()

    def set_user_mode(self, mode: str) -> None:
        self._user_mode = normalize_user_mode(mode)

        self.setWindowTitle(
            self._feature_label("speech.settings.window_title", "Speech Settings")
        )
        self._intro_label.setText(
            self._feature_label(
                "speech.settings.intro",
                "Mikrofon/Headset fuer Whisper-Diktat konfigurieren.\n"
                "STT/TTS laufen lokal.",
            )
        )
        stt_tab_index = self.tabs.indexOf(self._stt_tab)
        if stt_tab_index >= 0:
            self.tabs.setTabText(
                stt_tab_index,
                self._feature_label("speech.settings.tab.stt", "STT (Whisper)"),
            )
        tts_tab_index = self.tabs.indexOf(self._tts_tab)
        if tts_tab_index >= 0:
            self.tabs.setTabText(
                tts_tab_index,
                self._feature_label("speech.settings.tab.tts", "TTS"),
            )

        self._stt_group.setTitle(
            self._feature_label("speech.settings.group.stt", "Speech-to-Text")
        )
        self._tts_group.setTitle(
            self._feature_label("speech.settings.group.tts", "Text-to-Speech")
        )

        self._set_form_row_label(
            self._stt_row_labels,
            "audio_backend",
            "speech.settings.field.audio_backend",
            "Audio backend:",
        )
        self._set_form_row_label(
            self._stt_row_labels,
            "microphone",
            "speech.settings.field.microphone",
            "Mikrofon:",
        )
        self._set_form_row_label(
            self._stt_row_labels,
            "level_test",
            "speech.settings.field.level_test",
            "Pegeltest:",
        )
        self._set_form_row_label(
            self._stt_row_labels,
            "whisper_model",
            "speech.settings.field.whisper_model",
            "Whisper model:",
        )
        self._set_form_row_label(
            self._stt_row_labels,
            "language",
            "speech.settings.field.language",
            "Sprache:",
        )
        self._set_form_row_label(
            self._stt_row_labels,
            "compute_type",
            "speech.settings.field.compute_type",
            "Compute type:",
        )
        self._set_form_row_label(
            self._stt_row_labels,
            "cpu_threads",
            "speech.settings.field.cpu_threads",
            "CPU threads:",
        )

        self._set_form_row_label(
            self._tts_row_labels,
            "tts_engine",
            "speech.settings.field.tts_engine",
            "TTS engine:",
        )
        self._set_form_row_label(
            self._tts_row_labels,
            "chat_read_aloud",
            "speech.settings.field.chat_read_aloud",
            "Chat Vorlesen:",
        )
        self._set_form_row_label(
            self._tts_row_labels,
            "tts_language",
            "speech.settings.field.tts_language",
            "TTS Sprache:",
        )
        self._set_form_row_label(
            self._tts_row_labels,
            "piper_model",
            "speech.settings.field.piper_model",
            "Piper Modell:",
        )
        self._set_form_row_label(
            self._tts_row_labels,
            "speaker_id",
            "speech.settings.field.speaker_id",
            "Speaker-ID:",
        )
        self._set_form_row_label(
            self._tts_row_labels,
            "output_device",
            "speech.settings.field.output_device",
            "Output device:",
        )
        self._set_form_row_label(
            self._tts_row_labels,
            "voice",
            "speech.settings.field.voice",
            "Voice:",
        )
        self._set_form_row_label(
            self._tts_row_labels,
            "rate",
            "speech.settings.field.rate",
            "Rate (%):",
        )
        self._set_form_row_label(
            self._tts_row_labels,
            "volume",
            "speech.settings.field.volume",
            "Volume (%):",
        )
        self._set_form_row_label(
            self._tts_row_labels,
            "pause_ms",
            "speech.settings.field.pause_ms",
            "Pause (ms):",
        )
        self._set_form_row_label(
            self._tts_row_labels,
            "trigger_pause_ms",
            "speech.settings.field.trigger_pause_ms",
            "Trigger-Pause (ms):",
        )
        self._set_form_row_label(
            self._tts_row_labels,
            "lead_in_ms",
            "speech.settings.field.lead_in_ms",
            "Start-Vorlauf (ms):",
        )
        self._set_form_row_label(
            self._tts_row_labels,
            "start_trigger",
            "speech.settings.field.start_trigger",
            "Start-Trigger:",
        )
        self._set_form_row_label(
            self._tts_row_labels,
            "pause_trigger",
            "speech.settings.field.pause_trigger",
            "Pause-Trigger:",
        )

        self.refresh_input_btn.setText(
            self._feature_label("speech.settings.button.refresh", "Refresh")
        )
        self.piper_refresh_btn.setText(
            self._feature_label("speech.settings.button.scan", "Scan")
        )
        self.piper_browse_btn.setText(
            self._feature_label("speech.settings.button.browse", "Browse")
        )
        self.tts_refresh_btn.setText(
            self._feature_label("speech.settings.button.refresh", "Refresh")
        )
        self._update_probe_button_text(
            bool(self._probe_worker is not None and self._probe_worker.isRunning())
        )

        self._tts_note_label.setText(
            self._feature_label(
                "speech.settings.note",
                "Hinweis: Piper liefert meist die beste lokale Qualitaet.",
            )
        )
        self.level_bar.setFormat(
            self._feature_label(
                "speech.settings.level_bar.format",
                "input level: %p%",
            )
        )

        input_line = self.input_combo.lineEdit()
        if input_line is not None:
            input_line.setPlaceholderText(
                self._feature_label(
                    "speech.settings.placeholder.input_device",
                    "device name/index",
                )
            )
        model_line = self.model_combo.lineEdit()
        if model_line is not None:
            model_line.setPlaceholderText(
                self._feature_label(
                    "speech.settings.placeholder.whisper_model",
                    "tiny/base/... oder lokaler Modellpfad",
                )
            )
        self.language_edit.setPlaceholderText(
            self._feature_label(
                "speech.settings.placeholder.language",
                "de / en / auto(empty)",
            )
        )
        piper_line = self.piper_model_combo.lineEdit()
        if piper_line is not None:
            piper_line.setPlaceholderText(
                self._feature_label(
                    "speech.settings.placeholder.piper_model",
                    "lokales .onnx Modell",
                )
            )
        output_line = self.tts_output_combo.lineEdit()
        if output_line is not None:
            output_line.setPlaceholderText(
                self._feature_label(
                    "speech.settings.placeholder.output_device",
                    "output device",
                )
            )
        self.tts_voice_edit.setPlaceholderText(
            self._feature_label(
                "speech.settings.placeholder.voice",
                "voice id (optional)",
            )
        )
        self.tts_start_trigger_edit.setPlaceholderText(
            self._feature_label(
                "speech.settings.placeholder.start_trigger",
                "optional, z. B. hm",
            )
        )
        self.tts_pause_triggers_edit.setPlaceholderText(
            self._feature_label(
                "speech.settings.placeholder.pause_trigger",
                ",|:|;| - |-|",
            )
        )

        self._set_combo_item_text(
            self.backend_combo,
            "auto",
            self._feature_label("speech.settings.option.backend.auto", "Auto"),
        )
        self._set_combo_item_text(
            self.backend_combo,
            "arecord",
            self._feature_label(
                "speech.settings.option.backend.arecord",
                "arecord (Linux stable)",
            ),
        )
        self._set_combo_item_text(
            self.backend_combo,
            "sounddevice",
            self._feature_label(
                "speech.settings.option.backend.sounddevice",
                "sounddevice (PortAudio)",
            ),
        )

        self._set_combo_item_text(
            self.chat_tts_mode_combo,
            "off",
            self._feature_label("speech.settings.option.chat_tts_mode.off", "aus"),
        )
        self._set_combo_item_text(
            self.chat_tts_mode_combo,
            "once",
            self._feature_label(
                "speech.settings.option.chat_tts_mode.once",
                "einmal vorlesen",
            ),
        )
        self._set_combo_item_text(
            self.chat_tts_mode_combo,
            "always",
            self._feature_label(
                "speech.settings.option.chat_tts_mode.always",
                "an (immer vorlesen)",
            ),
        )

        ok_button = self._buttons_box.button(QDialogButtonBox.StandardButton.Ok)
        if ok_button is not None:
            ok_button.setText(self._feature_label("speech.settings.button.ok", "OK"))
        cancel_button = self._buttons_box.button(QDialogButtonBox.StandardButton.Cancel)
        if cancel_button is not None:
            cancel_button.setText(
                self._feature_label("speech.settings.button.cancel", "Cancel")
            )

    def _refresh_input_devices(self) -> None:
        selected = self._current_combo_data(self.input_combo) or self._base.stt_input_device
        devices = list_input_devices(
            backend=self._current_combo_data(self.backend_combo) or "auto"
        )
        self.input_combo.blockSignals(True)
        self.input_combo.clear()
        self.input_combo.addItem(
            self._feature_label("speech.settings.option.input.auto", "Auto"),
            "",
        )
        for dev in devices:
            self.input_combo.addItem(dev, dev)
        self._set_combo_data(self.input_combo, selected)
        if self.input_combo.currentIndex() < 0:
            self.input_combo.setCurrentIndex(0)
        self.input_combo.blockSignals(False)

    def _refresh_output_devices(self) -> None:
        selected = self._current_combo_data(self.tts_output_combo) or self._base.tts_output_device
        self.tts_output_combo.blockSignals(True)
        self.tts_output_combo.clear()
        self.tts_output_combo.addItem(
            self._feature_label("speech.settings.option.output.default", "default"),
            "default",
        )
        for dev in list_output_devices():
            if dev != "default":
                self.tts_output_combo.addItem(dev, dev)
        self._set_combo_data(self.tts_output_combo, selected or "default")
        self.tts_output_combo.blockSignals(False)

    def _refresh_piper_models(self) -> None:
        selected = self._current_combo_data(self.piper_model_combo) or self._base.tts_model_path
        refresh_local_piper_models_cache()
        models = list_local_piper_models(
            language=self._current_combo_data(self.tts_language_combo)
        )
        self.piper_model_combo.blockSignals(True)
        self.piper_model_combo.clear()
        if not models:
            self.piper_model_combo.addItem(
                self._feature_label(
                    "speech.settings.option.piper.none_found",
                    "(keine lokalen Piper-Modelle gefunden)",
                ),
                "",
            )
        else:
            for path in models[:200]:
                self.piper_model_combo.addItem(path, path)
        self._set_combo_data(self.piper_model_combo, selected)
        self.piper_model_combo.blockSignals(False)

    def _browse_piper_model(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            self._feature_label(
                "speech.settings.file_dialog.piper_model.title",
                "Piper Modell waehlen",
            ),
            "",
            self._feature_label(
                "speech.settings.file_dialog.piper_model.filter",
                "Piper model (*.onnx);;All files (*.*)",
            ),
        )
        if path:
            self._set_combo_data(self.piper_model_combo, path)

    def _on_tts_engine_changed(self) -> None:
        enabled = self._current_combo_data(self.tts_engine_combo) == "piper"
        for widget in (
            self.tts_language_combo,
            self.piper_model_combo,
            self.piper_refresh_btn,
            self.piper_browse_btn,
            self.tts_speaker_spin,
            self.tts_output_combo,
            self.tts_refresh_btn,
        ):
            widget.setEnabled(enabled)

    def _toggle_probe(self) -> None:
        if self._probe_worker is not None and self._probe_worker.isRunning():
            self._stop_probe()
            return
        self._start_probe()

    def _start_probe(self) -> None:
        worker = InputLevelProbeWorker(
            parent=self,
            backend=self._current_combo_data(self.backend_combo) or "auto",
            device=self._current_combo_data(self.input_combo) or "",
            sample_rate=16000,
        )
        worker.level_changed.connect(self._on_probe_level)
        worker.status.connect(self._set_status)
        worker.failed.connect(self._on_probe_failed)
        worker.stopped_ok.connect(self._on_probe_stopped)
        worker.finished.connect(self._on_probe_stopped)
        self._probe_worker = worker
        self._update_probe_button_text(True)
        self.level_bar.setValue(0)
        self._set_status(
            self._feature_label("speech.settings.status.probe_started", "Probe started.")
        )
        worker.start()

    def _stop_probe(self) -> None:
        if self._probe_worker is None:
            return
        self._probe_worker.request_stop()
        self._probe_worker.wait(1500)
        self._probe_worker = None
        self._update_probe_button_text(False)

    def _on_probe_level(self, value: float) -> None:
        self.level_bar.setValue(int(max(0.0, min(1.0, float(value))) * 100.0))

    def _on_probe_failed(self, message: str) -> None:
        self._stop_probe()
        self._set_status(
            self._format_text(
                self._feature_label(
                    "speech.settings.status.probe_error",
                    "Probe error: {message}",
                ),
                message=str(message),
            )
        )
        QMessageBox.warning(
            self,
            self._feature_label("speech.settings.message.input_test.title", "Input Test"),
            str(message),
        )

    def _on_probe_stopped(self) -> None:
        self._update_probe_button_text(False)
        if self._probe_worker is not None and not self._probe_worker.isRunning():
            self._probe_worker = None

    def _set_status(self, text: str) -> None:
        self._status_label.setText(str(text or "").strip())

    def closeEvent(self, event: QCloseEvent) -> None:
        self._stop_probe()
        super().closeEvent(event)

    def get_settings(self) -> SpeechSettings:
        return SpeechSettings.from_dict(
            {
                SpeechSettingsKeys.STT_BACKEND: self._current_combo_data(
                    self.backend_combo
                ),
                SpeechSettingsKeys.STT_INPUT_DEVICE: self._current_combo_data(
                    self.input_combo
                ),
                SpeechSettingsKeys.STT_MODEL_SIZE: self._current_combo_data(
                    self.model_combo
                ),
                SpeechSettingsKeys.STT_LANGUAGE: self.language_edit.text().strip(),
                SpeechSettingsKeys.STT_COMPUTE_TYPE: self._current_combo_data(
                    self.compute_combo
                ),
                SpeechSettingsKeys.STT_CPU_THREADS: self.cpu_threads_spin.value(),
                SpeechSettingsKeys.TTS_ENGINE: self._current_combo_data(
                    self.tts_engine_combo
                ),
                SpeechSettingsKeys.TTS_LANGUAGE: self._current_combo_data(
                    self.tts_language_combo
                ),
                SpeechSettingsKeys.TTS_MODEL_PATH: self._current_combo_data(
                    self.piper_model_combo
                ),
                SpeechSettingsKeys.TTS_SPEAKER_ID: self.tts_speaker_spin.value(),
                SpeechSettingsKeys.TTS_OUTPUT_DEVICE: self._current_combo_data(
                    self.tts_output_combo
                ),
                SpeechSettingsKeys.TTS_VOICE: self.tts_voice_edit.text().strip(),
                SpeechSettingsKeys.TTS_RATE: self.tts_rate_spin.value(),
                SpeechSettingsKeys.TTS_VOLUME: self.tts_volume_spin.value(),
                SpeechSettingsKeys.TTS_PAUSE_MS: self.tts_pause_spin.value(),
                SpeechSettingsKeys.TTS_TRIGGER_PAUSE_MS: self.tts_trigger_pause_spin.value(),
                SpeechSettingsKeys.TTS_LEAD_IN_MS: self.tts_lead_in_spin.value(),
                SpeechSettingsKeys.TTS_START_TRIGGER: self.tts_start_trigger_edit.text().strip(),
                SpeechSettingsKeys.TTS_PAUSE_TRIGGERS: self.tts_pause_triggers_edit.text().strip(),
                SpeechSettingsKeys.CHAT_TTS_MODE: self._current_combo_data(
                    self.chat_tts_mode_combo
                ),
            }
        )

    def accept(self) -> None:
        self._stop_probe()
        super().accept()

    def reject(self) -> None:
        self._stop_probe()
        super().reject()

    def _feature_label(self, key: str, default: str) -> str:
        return resolve_feature_label(self._user_mode, key, default)

    @staticmethod
    def _add_form_row(
        form: QFormLayout,
        labels: dict[str, QLabel],
        row_key: str,
        label_text: str,
        field: QWidget,
    ) -> None:
        form.addRow(label_text, field)
        label = form.labelForField(field)
        if isinstance(label, QLabel):
            labels[row_key] = label

    def _set_form_row_label(
        self,
        labels: dict[str, QLabel],
        row_key: str,
        feature_key: str,
        default: str,
    ) -> None:
        label = labels.get(row_key)
        if label is None:
            return
        label.setText(self._feature_label(feature_key, default))

    def _update_probe_button_text(self, running: bool) -> None:
        if running:
            self.test_btn.setText(
                self._feature_label("speech.settings.button.stop_test", "Stop Test")
            )
            return
        self.test_btn.setText(
            self._feature_label("speech.settings.button.test_input", "Test Input")
        )

    @staticmethod
    def _set_combo_item_text(combo: QComboBox, value: str, label: str) -> None:
        wanted = str(value or "").strip()
        if not wanted:
            return
        text = str(label or "").strip()
        if not text:
            return
        for idx in range(combo.count()):
            item_data = str(combo.itemData(idx, Qt.ItemDataRole.UserRole) or "").strip()
            if item_data != wanted:
                continue
            combo.setItemText(idx, text)
            return

    @staticmethod
    def _new_combo(items, *, editable: bool = False) -> QComboBox:
        combo = QComboBox()
        combo.setEditable(editable)
        for key, label in items:
            combo.addItem(str(label), str(key))
        return combo

    @staticmethod
    def _new_spin(
        lo: int,
        hi: int,
        *,
        step: int = 1,
        suffix: str = "",
        tooltip: str = "",
    ) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(lo, hi)
        spin.setSingleStep(step)
        if suffix:
            spin.setSuffix(suffix)
        if tooltip:
            spin.setToolTip(tooltip)
        return spin

    @staticmethod
    def _row_with_buttons(main: QWidget, *buttons: QWidget) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(main, 1)
        for btn in buttons:
            layout.addWidget(btn)
        return row

    @staticmethod
    def _current_combo_data(combo: QComboBox) -> str:
        data = combo.currentData(Qt.ItemDataRole.UserRole)
        if isinstance(data, str):
            return data.strip()
        return str(combo.currentText() or "").strip()

    @staticmethod
    def _set_combo_data(combo: QComboBox, wanted: str) -> None:
        target = str(wanted or "").strip()
        if not target:
            return
        for idx in range(combo.count()):
            data = str(combo.itemData(idx, Qt.ItemDataRole.UserRole) or "").strip()
            text = str(combo.itemText(idx) or "").strip()
            if data == target or text == target:
                combo.setCurrentIndex(idx)
                return
        if combo.isEditable():
            combo.setEditText(target)

    @staticmethod
    def _format_text(template: str, **kwargs: object) -> str:
        raw = str(template or "")
        if not raw:
            return ""
        try:
            return raw.format(**kwargs)
        except Exception:
            return raw
