from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QProgressBar, QPushButton, QSpinBox, QTabWidget, QVBoxLayout, QWidget

from shared.services.speech.devices import list_input_devices, list_output_devices
from shared.services.speech.level_probe import InputLevelProbeWorker
from shared.services.speech.piper_models import list_local_piper_models, refresh_local_piper_models_cache
from shared.config.app_settings import SpeechSettings
from shared.config.setting_keys import SpeechSettingsKeys

_BACKENDS = (("auto", "Auto"), ("arecord", "arecord (Linux stable)"), ("sounddevice", "sounddevice (PortAudio)"))
_WHISPER_MODELS = ("tiny", "base", "small", "medium", "large-v3")
_COMPUTE_TYPES = ("int8", "int8_float16", "float16", "float32")
_TTS_ENGINES = ("none", "piper", "pyttsx3", "spd-say", "espeak")
_TTS_LANGUAGES = (("de", "Deutsch"), ("en", "English"), ("fr", "Francais"), ("es", "Espanol"), ("it", "Italiano"), ("nl", "Nederlands"), ("pl", "Polski"), ("cs", "Cesky"), ("uk", "Ukrainska"))
_CHAT_TTS_MODES = (("off", "aus"), ("once", "einmal vorlesen"), ("always", "an (immer vorlesen)"))


class SpeechSettingsDialog(QDialog):
    def __init__(self, settings: SpeechSettings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Speech Settings")
        self.resize(700, 460)
        self._probe_worker: InputLevelProbeWorker | None = None
        self._base = SpeechSettings.from_dict(settings.to_dict())
        self._build_ui()
        self._load_values()
        self._refresh_input_devices()
        self._refresh_output_devices()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)
        intro = QLabel("Mikrofon/Headset fuer Whisper-Diktat konfigurieren.\nSTT/TTS laufen lokal.")
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #CDD6F4;")
        root.addWidget(intro)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_stt_tab(), "STT (Whisper)")
        self.tabs.addTab(self._build_tts_tab(), "TTS")
        root.addWidget(self.tabs, 1)
        self._status_label = QLabel("")
        self._status_label.setStyleSheet("color: #89B4FA;")
        root.addWidget(self._status_label)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _build_stt_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)
        group = QGroupBox("Speech-to-Text")
        form = QFormLayout(group)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(8)

        self.backend_combo = self._new_combo(_BACKENDS)
        self.backend_combo.currentIndexChanged.connect(self._refresh_input_devices)
        form.addRow("Audio backend:", self.backend_combo)

        self.input_combo = QComboBox(); self.input_combo.setEditable(True)
        self.input_combo.lineEdit().setPlaceholderText("device name/index")
        self.refresh_input_btn = QPushButton("Refresh")
        self.refresh_input_btn.clicked.connect(self._refresh_input_devices)
        form.addRow("Mikrofon:", self._row_with_buttons(self.input_combo, self.refresh_input_btn))

        self.test_btn = QPushButton("Test Input")
        self.test_btn.clicked.connect(self._toggle_probe)
        self.level_bar = QProgressBar(); self.level_bar.setRange(0, 100)
        self.level_bar.setValue(0); self.level_bar.setFormat("input level: %p%")
        form.addRow("Pegeltest:", self._row_with_buttons(self.level_bar, self.test_btn))

        self.model_combo = self._new_combo(((m, m) for m in _WHISPER_MODELS), editable=True)
        self.model_combo.lineEdit().setPlaceholderText("tiny/base/... oder lokaler Modellpfad")
        form.addRow("Whisper model:", self.model_combo)

        self.language_edit = QLineEdit(); self.language_edit.setPlaceholderText("de / en / auto(empty)")
        form.addRow("Sprache:", self.language_edit)
        self.compute_combo = self._new_combo(((m, m) for m in _COMPUTE_TYPES))
        form.addRow("Compute type:", self.compute_combo)
        self.cpu_threads_spin = self._new_spin(1, 64, step=1)
        form.addRow("CPU threads:", self.cpu_threads_spin)

        layout.addWidget(group); layout.addStretch(1)
        return page

    def _build_tts_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)
        group = QGroupBox("Text-to-Speech")
        form = QFormLayout(group)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(8)

        self.tts_engine_combo = self._new_combo(((e, e) for e in _TTS_ENGINES))
        self.tts_engine_combo.currentIndexChanged.connect(self._on_tts_engine_changed)
        form.addRow("TTS engine:", self.tts_engine_combo)

        self.chat_tts_mode_combo = self._new_combo(_CHAT_TTS_MODES)
        form.addRow("Chat Vorlesen:", self.chat_tts_mode_combo)

        self.tts_language_combo = self._new_combo(((c, f"{n} ({c})") for c, n in _TTS_LANGUAGES), editable=True)
        self.tts_language_combo.currentIndexChanged.connect(self._refresh_piper_models)
        form.addRow("TTS Sprache:", self.tts_language_combo)

        self.piper_model_combo = QComboBox(); self.piper_model_combo.setEditable(True)
        self.piper_model_combo.lineEdit().setPlaceholderText("lokales .onnx Modell")
        self.piper_refresh_btn = QPushButton("Scan")
        self.piper_refresh_btn.clicked.connect(self._refresh_piper_models)
        self.piper_browse_btn = QPushButton("Browse")
        self.piper_browse_btn.clicked.connect(self._browse_piper_model)
        form.addRow("Piper Modell:", self._row_with_buttons(self.piper_model_combo, self.piper_refresh_btn, self.piper_browse_btn))

        self.tts_speaker_spin = self._new_spin(-1, 999, tooltip="-1=default")
        form.addRow("Speaker-ID:", self.tts_speaker_spin)

        self.tts_output_combo = QComboBox(); self.tts_output_combo.setEditable(True)
        self.tts_output_combo.lineEdit().setPlaceholderText("output device")
        self.tts_refresh_btn = QPushButton("Refresh")
        self.tts_refresh_btn.clicked.connect(self._refresh_output_devices)
        form.addRow("Output device:", self._row_with_buttons(self.tts_output_combo, self.tts_refresh_btn))

        self.tts_voice_edit = QLineEdit(); self.tts_voice_edit.setPlaceholderText("voice id (optional)")
        form.addRow("Voice:", self.tts_voice_edit)

        specs = [
            ("tts_rate_spin", "Rate (%):", 50, 300, 5, "", ""),
            ("tts_volume_spin", "Volume (%):", 0, 100, 5, "", ""),
            ("tts_pause_spin", "Pause (ms):", 0, 2000, 25, " ms", "Pause zwischen Segmenten"),
            ("tts_trigger_pause_spin", "Trigger-Pause (ms):", 0, 4000, 25, " ms", "Extra-Pause bei Triggern"),
            ("tts_lead_in_spin", "Start-Vorlauf (ms):", 0, 2000, 25, " ms", "Leiser Vorlauf"),
        ]
        for attr, label, lo, hi, step, suffix, tip in specs:
            spin = self._new_spin(lo, hi, step=step, suffix=suffix, tooltip=tip)
            setattr(self, attr, spin)
            form.addRow(label, spin)

        self.tts_start_trigger_edit = QLineEdit(); self.tts_start_trigger_edit.setPlaceholderText("optional, z. B. hm")
        form.addRow("Start-Trigger:", self.tts_start_trigger_edit)
        self.tts_pause_triggers_edit = QLineEdit(); self.tts_pause_triggers_edit.setPlaceholderText(",|:|;| - |—|–|‒|―")
        form.addRow("Pause-Trigger:", self.tts_pause_triggers_edit)

        note = QLabel("Hinweis: Piper liefert meist die beste lokale Qualitaet.")
        note.setWordWrap(True)
        note.setStyleSheet("color: #BAC2DE;")
        layout.addWidget(group); layout.addWidget(note); layout.addStretch(1)
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

    def _refresh_input_devices(self) -> None:
        selected = self._current_combo_data(self.input_combo) or self._base.stt_input_device
        devices = list_input_devices(backend=self._current_combo_data(self.backend_combo) or "auto")
        self.input_combo.blockSignals(True)
        self.input_combo.clear(); self.input_combo.addItem("Auto", "")
        for dev in devices:
            self.input_combo.addItem(dev, dev)
        self._set_combo_data(self.input_combo, selected)
        if self.input_combo.currentIndex() < 0:
            self.input_combo.setCurrentIndex(0)
        self.input_combo.blockSignals(False)

    def _refresh_output_devices(self) -> None:
        selected = self._current_combo_data(self.tts_output_combo) or self._base.tts_output_device
        self.tts_output_combo.blockSignals(True)
        self.tts_output_combo.clear(); self.tts_output_combo.addItem("default", "default")
        for dev in list_output_devices():
            if dev != "default":
                self.tts_output_combo.addItem(dev, dev)
        self._set_combo_data(self.tts_output_combo, selected or "default")
        self.tts_output_combo.blockSignals(False)

    def _refresh_piper_models(self) -> None:
        selected = self._current_combo_data(self.piper_model_combo) or self._base.tts_model_path
        refresh_local_piper_models_cache()
        models = list_local_piper_models(language=self._current_combo_data(self.tts_language_combo))
        self.piper_model_combo.blockSignals(True)
        self.piper_model_combo.clear()
        if not models:
            self.piper_model_combo.addItem("(keine lokalen Piper-Modelle gefunden)", "")
        else:
            for path in models[:200]:
                self.piper_model_combo.addItem(path, path)
        self._set_combo_data(self.piper_model_combo, selected)
        self.piper_model_combo.blockSignals(False)

    def _browse_piper_model(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Piper Modell waehlen", "", "Piper model (*.onnx);;All files (*.*)")
        if path:
            self._set_combo_data(self.piper_model_combo, path)

    def _on_tts_engine_changed(self) -> None:
        enabled = self._current_combo_data(self.tts_engine_combo) == "piper"
        for w in (self.tts_language_combo, self.piper_model_combo, self.piper_refresh_btn, self.piper_browse_btn, self.tts_speaker_spin, self.tts_output_combo, self.tts_refresh_btn):
            w.setEnabled(enabled)

    def _toggle_probe(self) -> None:
        if self._probe_worker is not None and self._probe_worker.isRunning():
            self._stop_probe(); return
        self._start_probe()

    def _start_probe(self) -> None:
        worker = InputLevelProbeWorker(parent=self, backend=self._current_combo_data(self.backend_combo) or "auto", device=self._current_combo_data(self.input_combo) or "", sample_rate=16000)
        worker.level_changed.connect(self._on_probe_level)
        worker.status.connect(self._set_status)
        worker.failed.connect(self._on_probe_failed)
        worker.stopped_ok.connect(self._on_probe_stopped)
        worker.finished.connect(self._on_probe_stopped)
        self._probe_worker = worker
        self.test_btn.setText("Stop Test")
        self.level_bar.setValue(0)
        self._set_status("Probe started.")
        worker.start()

    def _stop_probe(self) -> None:
        if self._probe_worker is None:
            return
        self._probe_worker.request_stop()
        self._probe_worker.wait(1500)
        self._probe_worker = None
        self.test_btn.setText("Test Input")

    def _on_probe_level(self, value: float) -> None:
        self.level_bar.setValue(int(max(0.0, min(1.0, float(value))) * 100.0))

    def _on_probe_failed(self, message: str) -> None:
        self._stop_probe()
        self._set_status(f"Probe error: {message}")
        QMessageBox.warning(self, "Input Test", str(message))

    def _on_probe_stopped(self) -> None:
        self.test_btn.setText("Test Input")
        if self._probe_worker is not None and not self._probe_worker.isRunning():
            self._probe_worker = None

    def _set_status(self, text: str) -> None:
        self._status_label.setText(str(text or "").strip())

    def get_settings(self) -> SpeechSettings:
        return SpeechSettings.from_dict({
            SpeechSettingsKeys.STT_BACKEND: self._current_combo_data(self.backend_combo),
            SpeechSettingsKeys.STT_INPUT_DEVICE: self._current_combo_data(self.input_combo),
            SpeechSettingsKeys.STT_MODEL_SIZE: self._current_combo_data(self.model_combo),
            SpeechSettingsKeys.STT_LANGUAGE: self.language_edit.text().strip(),
            SpeechSettingsKeys.STT_COMPUTE_TYPE: self._current_combo_data(self.compute_combo),
            SpeechSettingsKeys.STT_CPU_THREADS: self.cpu_threads_spin.value(),
            SpeechSettingsKeys.TTS_ENGINE: self._current_combo_data(self.tts_engine_combo),
            SpeechSettingsKeys.TTS_LANGUAGE: self._current_combo_data(self.tts_language_combo),
            SpeechSettingsKeys.TTS_MODEL_PATH: self._current_combo_data(self.piper_model_combo),
            SpeechSettingsKeys.TTS_SPEAKER_ID: self.tts_speaker_spin.value(),
            SpeechSettingsKeys.TTS_OUTPUT_DEVICE: self._current_combo_data(self.tts_output_combo),
            SpeechSettingsKeys.TTS_VOICE: self.tts_voice_edit.text().strip(),
            SpeechSettingsKeys.TTS_RATE: self.tts_rate_spin.value(),
            SpeechSettingsKeys.TTS_VOLUME: self.tts_volume_spin.value(),
            SpeechSettingsKeys.TTS_PAUSE_MS: self.tts_pause_spin.value(),
            SpeechSettingsKeys.TTS_TRIGGER_PAUSE_MS: self.tts_trigger_pause_spin.value(),
            SpeechSettingsKeys.TTS_LEAD_IN_MS: self.tts_lead_in_spin.value(),
            SpeechSettingsKeys.TTS_START_TRIGGER: self.tts_start_trigger_edit.text().strip(),
            SpeechSettingsKeys.TTS_PAUSE_TRIGGERS: self.tts_pause_triggers_edit.text().strip(),
            SpeechSettingsKeys.CHAT_TTS_MODE: self._current_combo_data(self.chat_tts_mode_combo),
        })

    @staticmethod
    def _new_combo(items, *, editable: bool = False) -> QComboBox:
        combo = QComboBox(); combo.setEditable(editable)
        for key, label in items:
            combo.addItem(str(label), str(key))
        return combo

    @staticmethod
    def _new_spin(lo: int, hi: int, *, step: int = 1, suffix: str = "", tooltip: str = "") -> QSpinBox:
        spin = QSpinBox(); spin.setRange(lo, hi); spin.setSingleStep(step)
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

    def accept(self) -> None:
        self._stop_probe(); super().accept()

    def reject(self) -> None:
        self._stop_probe(); super().reject()
