"""Background microphone dictation with faster-whisper."""
from __future__ import annotations

import os
import threading
from typing import Any

from PySide6.QtCore import QThread, Signal

from .dictation_parts import bind_whisper_dictation_worker

class WhisperDictationWorker(QThread):
    """
    Continuously transcribe microphone audio and emit text chunks.

    The worker is optional by design: missing runtime dependencies are
    surfaced via ``failed`` without crashing the app.
    """

    text_chunk = Signal(str)
    started_ok = Signal()
    stopped_ok = Signal()
    status = Signal(str)
    failed = Signal(str)

    def __init__(
        self,
        parent=None,
        model_size: str = "base",
        language: str = "",
        device: str = "cpu",
        audio_device: int | str | None = None,
        audio_backend: str = "auto",
        compute_type: str = "int8",
        sample_rate: int = 16000,
        block_seconds: float = 0.40,
        segment_seconds: float = 3.0,
        min_segment_seconds: float = 1.2,
        max_idle_seconds: float = 2.0,
        beam_size: int = 1,
        cpu_threads: int = 0,
        speech_rms_threshold: float = 0.0002,
    ):
        super().__init__(parent)
        self.model_size = str(model_size or "base")
        self.language = str(language or "").strip()
        self.device = str(device or "cpu")
        self.audio_device = self._parse_audio_device(audio_device)
        self.audio_backend = str(audio_backend or "auto").strip().casefold()
        self._allow_hw_audio = self._env_flag("DRAFT2CRAIFT_STT_ALLOW_HW")
        self.compute_type = str(compute_type or "int8")
        self.sample_rate = max(8000, int(sample_rate))
        self.block_seconds = max(0.05, float(block_seconds))
        self.segment_seconds = max(1.0, float(segment_seconds))
        self.min_segment_seconds = max(0.4, float(min_segment_seconds))
        self.max_idle_seconds = max(0.2, float(max_idle_seconds))
        self.beam_size = max(1, int(beam_size))
        self.cpu_threads = max(0, int(cpu_threads))
        self.speech_rms_threshold = max(1e-5, float(speech_rms_threshold))
        self._stop_requested = threading.Event()
        self._noise_rms_ema = 0.0
        self._noise_ready = False
        self._last_emitted_norm = ""
        self._same_emit_count = 0
        self._dropped_repetition_count = 0
        self._chunk_counter = 0

    def request_stop(self):
        """Ask the worker loop to stop at the next safe point."""
        self._stop_requested.set()

    def run(self):
        self._stop_requested.clear()
        self._noise_rms_ema = 0.0
        self._noise_ready = False
        self._last_emitted_norm = ""
        self._same_emit_count = 0
        self._dropped_repetition_count = 0
        self._chunk_counter = 0
        try:
            try:
                import numpy as np  # type: ignore
            except Exception as exc:
                raise RuntimeError(
                    "NumPy nicht verfügbar. Installiere mit:\n"
                    "  pip install numpy"
                ) from exc

            try:
                from faster_whisper import WhisperModel  # type: ignore
            except Exception as exc:
                raise RuntimeError(
                    "Whisper nicht verfügbar. Installiere mit:\n"
                    "  pip install faster-whisper"
                ) from exc

            model_kwargs: dict[str, Any] = {
                "device": self.device,
                "compute_type": self.compute_type,
                "local_files_only": True,
            }
            download_root = self._whisper_download_dir()
            if download_root:
                model_kwargs["download_root"] = download_root
            if self.cpu_threads > 0:
                model_kwargs["cpu_threads"] = self.cpu_threads

            model_ref = self._resolve_model_reference(self.model_size)
            self.status.emit(f"Lade Whisper-Modell: {self.model_size}…")
            os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
            try:
                model = WhisperModel(model_ref, **model_kwargs)
            except Exception as local_exc:
                if self._looks_like_path(self.model_size):
                    details = str(local_exc).strip() or repr(local_exc)
                    raise RuntimeError(
                        "Whisper-Modellpfad nicht gefunden oder ungueltig.\n"
                        "Bitte einen gueltigen lokalen Modellpfad waehlen.\n"
                        f"Modell: {self.model_size}\n"
                        f"Originalfehler: {details}"
                    ) from local_exc

                if not self._stt_auto_download_enabled():
                    details = str(local_exc).strip() or repr(local_exc)
                    raise RuntimeError(
                        "Whisper-Modell nicht lokal gefunden.\n"
                        "Auto-Download ist deaktiviert "
                        "(DRAFT2CRAIFT_STT_AUTO_DOWNLOAD=0).\n"
                        "Bitte lokales Modell waehlen oder Auto-Download aktivieren.\n"
                        f"Modell: {self.model_size} ({model_ref})\n"
                        f"Originalfehler: {details}"
                    ) from local_exc

                self.status.emit(
                    "Whisper-Modell lokal nicht gefunden. "
                    "Starte einmaligen Download…"
                )
                online_kwargs = dict(model_kwargs)
                online_kwargs["local_files_only"] = False
                # Temporarily relax offline flags for first-run download.
                prev_hf_offline = os.environ.get("HF_HUB_OFFLINE")
                prev_tf_offline = os.environ.get("TRANSFORMERS_OFFLINE")
                os.environ.pop("HF_HUB_OFFLINE", None)
                os.environ.pop("TRANSFORMERS_OFFLINE", None)
                try:
                    model = WhisperModel(model_ref, **online_kwargs)
                except Exception as dl_exc:
                    details = str(dl_exc).strip() or repr(dl_exc)
                    raise RuntimeError(
                        "Whisper-Modell konnte nicht automatisch geladen werden.\n"
                        "Bitte Internetzugang pruefen oder lokales Modell nutzen.\n"
                        f"Modell: {self.model_size} ({model_ref})\n"
                        f"Originalfehler: {details}"
                    ) from dl_exc
                finally:
                    if prev_hf_offline is None:
                        os.environ.pop("HF_HUB_OFFLINE", None)
                    else:
                        os.environ["HF_HUB_OFFLINE"] = prev_hf_offline
                    if prev_tf_offline is None:
                        os.environ.pop("TRANSFORMERS_OFFLINE", None)
                    else:
                        os.environ["TRANSFORMERS_OFFLINE"] = prev_tf_offline
                self.status.emit("Whisper-Modell heruntergeladen und lokal bereit.")

            backend = self._select_audio_backend()
            self.status.emit(f"Whisper-Audio backend: {backend}")
            if backend == "arecord":
                self._run_arecord_loop(model, np)
            else:
                self._run_sounddevice_loop(model, np)

            if self._dropped_repetition_count > 0:
                self.status.emit(
                    "Whisper-Hinweis: "
                    f"{self._dropped_repetition_count} "
                    "Wiederholungen verworfen."
                )
            self.status.emit("Whisper-Diktat gestoppt.")
            self.stopped_ok.emit()
        except Exception as exc:
            self.failed.emit(str(exc))

bind_whisper_dictation_worker(WhisperDictationWorker)

__all__ = ["WhisperDictationWorker"]
