"""Speech settings dialog (STT today, TTS-ready for next step)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
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

from services.speech.devices import list_input_devices, list_output_devices
from services.speech.level_probe import InputLevelProbeWorker
from services.speech.piper_models import (
    list_local_piper_models,
    refresh_local_piper_models_cache,
)
from services.speech.settings import SpeechSettings


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
    """GUI dialog to configure STT/TTS and probe microphone levels."""

    def __init__(
        self,
        settings: SpeechSettings,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Speech Settings")
        self.resize(700, 460)
        self._probe_worker: InputLevelProbeWorker | None = None
        self._base = SpeechSettings.from_dict(settings.to_dict())

        self._build_ui()
        self._load_values()
        self._refresh_input_devices()
        self._refresh_output_devices()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        intro = QLabel(
            "Mikrofon/Headset fuer Whisper-Diktat konfigurieren.\n"
            "STT/TTS laufen lokal. "
            "Whisper- und Piper-Modelle koennen beim ersten Start "
            "einmalig heruntergeladen werden."
        )
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

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
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

        self.backend_combo = QComboBox()
        for key, label in _BACKENDS:
            self.backend_combo.addItem(label, key)
        self.backend_combo.currentIndexChanged.connect(
            self._refresh_input_devices
        )
        form.addRow("Audio backend:", self.backend_combo)

        self.input_combo = QComboBox()
        self.input_combo.setEditable(True)
        self.input_combo.lineEdit().setPlaceholderText("device name/index")
        self.refresh_input_btn = QPushButton("Refresh")
        self.refresh_input_btn.clicked.connect(self._refresh_input_devices)
        input_row = QWidget()
        input_layout = QHBoxLayout(input_row)
        input_layout.setContentsMargins(0, 0, 0, 0)
        input_layout.setSpacing(6)
        input_layout.addWidget(self.input_combo, 1)
        input_layout.addWidget(self.refresh_input_btn)
        form.addRow("Mikrofon:", input_row)

        self.test_btn = QPushButton("Test Input")
        self.test_btn.clicked.connect(self._toggle_probe)
        self.level_bar = QProgressBar()
        self.level_bar.setRange(0, 100)
        self.level_bar.setValue(0)
        self.level_bar.setFormat("input level: %p%")
        level_row = QWidget()
        level_layout = QGridLayout(level_row)
        level_layout.setContentsMargins(0, 0, 0, 0)
        level_layout.setHorizontalSpacing(6)
        level_layout.setVerticalSpacing(4)
        level_layout.addWidget(self.test_btn, 0, 0)
        level_layout.addWidget(self.level_bar, 0, 1)
        form.addRow("Pegeltest:", level_row)

        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        for item in _WHISPER_MODELS:
            self.model_combo.addItem(item, item)
        self.model_combo.lineEdit().setPlaceholderText(
            "tiny/base/... oder lokaler Modellpfad"
        )
        form.addRow("Whisper model:", self.model_combo)

        self.language_edit = QLineEdit()
        self.language_edit.setPlaceholderText("de / en / auto(empty)")
        form.addRow("Sprache:", self.language_edit)

        self.compute_combo = QComboBox()
        for item in _COMPUTE_TYPES:
            self.compute_combo.addItem(item, item)
        form.addRow("Compute type:", self.compute_combo)

        self.cpu_threads_spin = QSpinBox()
        self.cpu_threads_spin.setRange(1, 64)
        self.cpu_threads_spin.setSingleStep(1)
        form.addRow("CPU threads:", self.cpu_threads_spin)

        layout.addWidget(group)
        layout.addStretch(1)
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

        self.tts_engine_combo = QComboBox()
        for item in _TTS_ENGINES:
            self.tts_engine_combo.addItem(item, item)
        self.tts_engine_combo.currentIndexChanged.connect(
            self._on_tts_engine_changed
        )
        form.addRow("TTS engine:", self.tts_engine_combo)

        self.chat_tts_mode_combo = QComboBox()
        for key, label in _CHAT_TTS_MODES:
            self.chat_tts_mode_combo.addItem(label, key)
        form.addRow("Chat Vorlesen:", self.chat_tts_mode_combo)

        self.tts_language_combo = QComboBox()
        self.tts_language_combo.setEditable(True)
        for code, label in _TTS_LANGUAGES:
            self.tts_language_combo.addItem(f"{label} ({code})", code)
        self.tts_language_combo.currentIndexChanged.connect(
            self._refresh_piper_models
        )
        form.addRow("TTS Sprache:", self.tts_language_combo)

        self.piper_model_combo = QComboBox()
        self.piper_model_combo.setEditable(True)
        self.piper_model_combo.lineEdit().setPlaceholderText(
            "lokales .onnx Modell"
        )
        self.piper_refresh_btn = QPushButton("Scan")
        self.piper_refresh_btn.clicked.connect(self._refresh_piper_models)
        self.piper_browse_btn = QPushButton("Browse")
        self.piper_browse_btn.clicked.connect(self._browse_piper_model)
        piper_row = QWidget()
        piper_layout = QHBoxLayout(piper_row)
        piper_layout.setContentsMargins(0, 0, 0, 0)
        piper_layout.setSpacing(6)
        piper_layout.addWidget(self.piper_model_combo, 1)
        piper_layout.addWidget(self.piper_refresh_btn)
        piper_layout.addWidget(self.piper_browse_btn)
        form.addRow("Piper Modell:", piper_row)

        self.tts_speaker_spin = QSpinBox()
        self.tts_speaker_spin.setRange(-1, 999)
        self.tts_speaker_spin.setToolTip(
            "-1 = default speaker, >=0 = specific speaker id"
        )
        form.addRow("Speaker-ID:", self.tts_speaker_spin)

        self.tts_output_combo = QComboBox()
        self.tts_output_combo.setEditable(True)
        self.tts_output_combo.lineEdit().setPlaceholderText("output device")
        self.tts_refresh_btn = QPushButton("Refresh")
        self.tts_refresh_btn.clicked.connect(self._refresh_output_devices)
        output_row = QWidget()
        output_layout = QHBoxLayout(output_row)
        output_layout.setContentsMargins(0, 0, 0, 0)
        output_layout.setSpacing(6)
        output_layout.addWidget(self.tts_output_combo, 1)
        output_layout.addWidget(self.tts_refresh_btn)
        form.addRow("Output device:", output_row)

        self.tts_voice_edit = QLineEdit()
        self.tts_voice_edit.setPlaceholderText("voice id (optional)")
        form.addRow("Voice:", self.tts_voice_edit)

        self.tts_rate_spin = QSpinBox()
        self.tts_rate_spin.setRange(50, 300)
        self.tts_rate_spin.setSingleStep(5)
        form.addRow("Rate (%):", self.tts_rate_spin)

        self.tts_volume_spin = QSpinBox()
        self.tts_volume_spin.setRange(0, 100)
        self.tts_volume_spin.setSingleStep(5)
        form.addRow("Volume (%):", self.tts_volume_spin)

        self.tts_pause_spin = QSpinBox()
        self.tts_pause_spin.setRange(0, 2000)
        self.tts_pause_spin.setSingleStep(25)
        self.tts_pause_spin.setSuffix(" ms")
        self.tts_pause_spin.setToolTip(
            "Zusaetzliche Pause zwischen Satz-/Abschnittssegmenten"
        )
        form.addRow("Pause (ms):", self.tts_pause_spin)

        self.tts_trigger_pause_spin = QSpinBox()
        self.tts_trigger_pause_spin.setRange(0, 4000)
        self.tts_trigger_pause_spin.setSingleStep(25)
        self.tts_trigger_pause_spin.setSuffix(" ms")
        self.tts_trigger_pause_spin.setToolTip(
            "Extra-Pause nach konfigurierten Pause-Triggern "
            "(z. B. ',' ':' ' - ' '—')."
        )
        form.addRow("Trigger-Pause (ms):", self.tts_trigger_pause_spin)

        self.tts_lead_in_spin = QSpinBox()
        self.tts_lead_in_spin.setRange(0, 2000)
        self.tts_lead_in_spin.setSingleStep(25)
        self.tts_lead_in_spin.setSuffix(" ms")
        self.tts_lead_in_spin.setToolTip(
            "Stiller Vorlauf am Anfang (hilft bei verschlucktem ersten Wort, v. a. Piper)"
        )
        form.addRow("Start-Vorlauf (ms):", self.tts_lead_in_spin)

        self.tts_start_trigger_edit = QLineEdit()
        self.tts_start_trigger_edit.setPlaceholderText(
            "optional, z. B. hm"
        )
        self.tts_start_trigger_edit.setToolTip(
            "Optionales Startwort vor jeder Ausgabe. "
            "Hilft, wenn das erste echte Wort sporadisch fehlt."
        )
        form.addRow("Start-Trigger:", self.tts_start_trigger_edit)

        self.tts_pause_triggers_edit = QLineEdit()
        self.tts_pause_triggers_edit.setPlaceholderText(
            ",|:|;| - |—|–|‒|―"
        )
        self.tts_pause_triggers_edit.setToolTip(
            "Zusatz-Pause ausloesen nach diesen Zeichen/Sequenzen. "
            "Eintraege mit | trennen, z. B.: ,|:| - |—"
        )
        form.addRow("Pause-Trigger:", self.tts_pause_triggers_edit)

        note = QLabel(
            "Hinweis: Piper liefert die beste lokale Qualitaet.\n"
            "Wenn noch kein Modell lokal vorhanden ist, wird beim ersten "
            "Vorlesen automatisch heruntergeladen."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #BAC2DE;")

        layout.addWidget(group)
        layout.addWidget(note)
        layout.addStretch(1)
        return page

    def _load_values(self):
        self._set_combo_data(self.backend_combo, self._base.stt_backend)
        self._set_combo_data(self.model_combo, self._base.stt_model_size)
        self._set_combo_data(self.compute_combo, self._base.stt_compute_type)
        self.language_edit.setText(self._base.stt_language)
        self.cpu_threads_spin.setValue(self._base.stt_cpu_threads)

        self._set_combo_data(self.tts_engine_combo, self._base.tts_engine)
        self._set_combo_data(
            self.chat_tts_mode_combo,
            self._base.chat_tts_mode,
        )
        self._set_combo_data(
            self.tts_language_combo,
            self._base.tts_language or "de",
        )
        self._set_combo_data(
            self.piper_model_combo,
            self._base.tts_model_path,
        )
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

    def _refresh_input_devices(self):
        selected = self._current_combo_data(self.input_combo)
        if not selected:
            selected = self._base.stt_input_device
        backend = self._current_combo_data(self.backend_combo) or "auto"
        devices = list_input_devices(backend=backend)
        self.input_combo.blockSignals(True)
        self.input_combo.clear()
        self.input_combo.addItem("Auto", "")
        for dev in devices:
            self.input_combo.addItem(dev, dev)
        self._set_combo_data(self.input_combo, selected)
        if self.input_combo.currentIndex() < 0:
            self.input_combo.setCurrentIndex(0)
        self.input_combo.blockSignals(False)

    def _refresh_output_devices(self):
        selected = self._current_combo_data(self.tts_output_combo)
        if not selected:
            selected = self._base.tts_output_device
        devices = list_output_devices()
        self.tts_output_combo.blockSignals(True)
        self.tts_output_combo.clear()
        self.tts_output_combo.addItem("default", "default")
        for dev in devices:
            if dev == "default":
                continue
            self.tts_output_combo.addItem(dev, dev)
        self._set_combo_data(self.tts_output_combo, selected or "default")
        self.tts_output_combo.blockSignals(False)

    def _refresh_piper_models(self):
        selected = self._current_combo_data(self.piper_model_combo)
        if not selected:
            selected = self._base.tts_model_path
        language = self._current_combo_data(self.tts_language_combo)
        refresh_local_piper_models_cache()
        models = list_local_piper_models(language=language)
        self.piper_model_combo.blockSignals(True)
        self.piper_model_combo.clear()
        if not models:
            self.piper_model_combo.addItem(
                "(keine lokalen Piper-Modelle gefunden)",
                "",
            )
        else:
            for path in models[:200]:
                self.piper_model_combo.addItem(path, path)
        self._set_combo_data(self.piper_model_combo, selected)
        self.piper_model_combo.blockSignals(False)

    def _browse_piper_model(self):
        path, _flt = QFileDialog.getOpenFileName(
            self,
            "Piper Modell waehlen",
            "",
            "Piper model (*.onnx);;All files (*.*)",
        )
        if not path:
            return
        self._set_combo_data(self.piper_model_combo, path)

    def _on_tts_engine_changed(self):
        engine = self._current_combo_data(self.tts_engine_combo)
        piper_on = engine == "piper"
        self.tts_language_combo.setEnabled(piper_on)
        self.piper_model_combo.setEnabled(piper_on)
        self.piper_refresh_btn.setEnabled(piper_on)
        self.piper_browse_btn.setEnabled(piper_on)
        self.tts_speaker_spin.setEnabled(piper_on)
        self.tts_output_combo.setEnabled(piper_on)
        self.tts_refresh_btn.setEnabled(piper_on)

    def _toggle_probe(self):
        worker = self._probe_worker
        if worker is not None and worker.isRunning():
            self._stop_probe()
            return
        self._start_probe()

    def _start_probe(self):
        backend = self._current_combo_data(self.backend_combo) or "auto"
        device = self._current_combo_data(self.input_combo)
        worker = InputLevelProbeWorker(
            parent=self,
            backend=backend,
            device=device or "",
            sample_rate=16000,
        )
        worker.level_changed.connect(self._on_probe_level)
        worker.status.connect(self._on_probe_status)
        worker.failed.connect(self._on_probe_failed)
        worker.stopped_ok.connect(self._on_probe_stopped)
        worker.finished.connect(self._on_probe_stopped)
        self._probe_worker = worker
        self.test_btn.setText("Stop Test")
        self.level_bar.setValue(0)
        self._set_status("Probe started.")
        worker.start()

    def _stop_probe(self):
        worker = self._probe_worker
        if worker is None:
            return
        worker.request_stop()
        worker.wait(1500)
        self._probe_worker = None
        self.test_btn.setText("Test Input")

    def _on_probe_level(self, value: float):
        pct = int(max(0.0, min(1.0, float(value))) * 100.0)
        self.level_bar.setValue(pct)

    def _on_probe_status(self, text: str):
        self._set_status(text)

    def _on_probe_failed(self, message: str):
        self._stop_probe()
        self._set_status(f"Probe error: {message}")
        QMessageBox.warning(self, "Input Test", str(message))

    def _on_probe_stopped(self):
        self.test_btn.setText("Test Input")
        is_done = (
            self._probe_worker is not None
            and not self._probe_worker.isRunning()
        )
        if is_done:
            self._probe_worker = None

    def _set_status(self, text: str):
        self._status_label.setText(str(text or "").strip())

    def get_settings(self) -> SpeechSettings:
        return SpeechSettings.from_dict(
            {
                "stt_backend": self._current_combo_data(self.backend_combo),
                "stt_input_device": self._current_combo_data(self.input_combo),
                "stt_model_size": self._current_combo_data(self.model_combo),
                "stt_language": self.language_edit.text().strip(),
                "stt_compute_type": self._current_combo_data(
                    self.compute_combo
                ),
                "stt_cpu_threads": self.cpu_threads_spin.value(),
                "tts_engine": self._current_combo_data(self.tts_engine_combo),
                "tts_language": self._current_combo_data(
                    self.tts_language_combo
                ),
                "tts_model_path": self._current_combo_data(
                    self.piper_model_combo
                ),
                "tts_speaker_id": self.tts_speaker_spin.value(),
                "tts_output_device": self._current_combo_data(
                    self.tts_output_combo
                ),
                "tts_voice": self.tts_voice_edit.text().strip(),
                "tts_rate": self.tts_rate_spin.value(),
                "tts_volume": self.tts_volume_spin.value(),
                "tts_pause_ms": self.tts_pause_spin.value(),
                "tts_trigger_pause_ms": self.tts_trigger_pause_spin.value(),
                "tts_lead_in_ms": self.tts_lead_in_spin.value(),
                "tts_start_trigger": self.tts_start_trigger_edit.text().strip(),
                "tts_pause_triggers": self.tts_pause_triggers_edit.text().strip(),
                "chat_tts_mode": self._current_combo_data(
                    self.chat_tts_mode_combo
                ),
            }
        )

    @staticmethod
    def _current_combo_data(combo: QComboBox) -> str:
        data = combo.currentData(Qt.ItemDataRole.UserRole)
        if isinstance(data, str):
            return data.strip()
        text = combo.currentText()
        return str(text or "").strip()

    @staticmethod
    def _set_combo_data(combo: QComboBox, wanted: str):
        target = str(wanted or "").strip()
        if not target:
            return
        for idx in range(combo.count()):
            data = combo.itemData(idx, Qt.ItemDataRole.UserRole)
            if str(data or "").strip() == target:
                combo.setCurrentIndex(idx)
                return
            text = combo.itemText(idx)
            if str(text or "").strip() == target:
                combo.setCurrentIndex(idx)
                return
        if combo.isEditable():
            combo.setEditText(target)

    def accept(self):
        self._stop_probe()
        super().accept()

    def reject(self):
        self._stop_probe()
        super().reject()
