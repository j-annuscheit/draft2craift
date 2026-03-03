"""Background microphone dictation with faster-whisper."""
from __future__ import annotations

import os
from pathlib import Path
import queue
import re
import select
import shutil
import subprocess
import threading
import time
from typing import Any

from PySide6.QtCore import QThread, Signal


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

    def _select_audio_backend(self) -> str:
        forced = str(
            os.getenv("DRAFT2CRAIFT_STT_BACKEND", self.audio_backend) or "auto"
        ).strip().casefold()
        if forced in {"sounddevice", "arecord"}:
            return forced
        if os.name != "nt" and shutil.which("arecord"):
            return "arecord"
        return "sounddevice"

    def _run_sounddevice_loop(self, model, np_mod):
        try:
            os.environ.setdefault("PA_ALSA_PLUGHW", "1")
            import sounddevice as sd  # type: ignore
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "Mikrofonaufnahme benötigt sounddevice. Installiere mit:\n"
                "  pip install sounddevice"
            ) from exc
        except OSError as exc:
            details = str(exc).strip() or repr(exc)
            if "PortAudio library not found" in details:
                raise RuntimeError(
                    "sounddevice ist installiert, aber PortAudio fehlt.\n"
                    "Installiere die Systembibliothek, z. B.:\n"
                    "  sudo apt install libportaudio2\n"
                    "oder per Conda:\n"
                    "  conda install -c conda-forge portaudio\n"
                    f"Originalfehler: {details}"
                ) from exc
            raise RuntimeError(
                "sounddevice konnte nicht initialisiert werden.\n"
                f"Originalfehler: {details}"
            ) from exc
        except Exception as exc:
            details = str(exc).strip() or repr(exc)
            raise RuntimeError(
                "Mikrofonaufnahme konnte nicht gestartet werden.\n"
                f"Originalfehler: {details}"
            ) from exc

        audio_queue: queue.Queue[Any] = queue.Queue(maxsize=256)
        stream_warnings: list[str] = []

        def _on_audio(indata, _frames, _time_info, status):
            if status:
                stream_warnings.append(str(status))
            try:
                audio_queue.put_nowait(indata.copy())
            except queue.Full:
                pass

        stream_ctx, input_rate, device = self._open_best_input_stream(
            sd,
            _on_audio,
        )
        self.status.emit(
            "Whisper bereit. Aufnahme läuft… "
            f"(Device: {self._device_label(sd, device)} | "
            f"Input: {input_rate} Hz -> Modell: {self.sample_rate} Hz)"
        )
        self.started_ok.emit()

        with stream_ctx:
            self._run_audio_buffer_loop(
                model=model,
                np_mod=np_mod,
                input_sample_rate=input_rate,
                read_block=lambda: self._queue_get_block(audio_queue, 0.2),
            )

        if stream_warnings:
            self.status.emit(f"Audio-Hinweis: {stream_warnings[-1]}")

    def _run_arecord_loop(self, model, np_mod):
        proc, input_rate, device = self._open_best_arecord_stream()
        self.status.emit(
            "Whisper bereit. Aufnahme läuft… "
            f"(Device: {device} | Input: {input_rate} Hz"
            f" -> Modell: {self.sample_rate} Hz)"
        )
        self.started_ok.emit()
        try:
            block_samples = max(256, int(input_rate * self.block_seconds))
            read_bytes = block_samples * 2  # int16 mono
            self._run_audio_buffer_loop(
                model=model,
                np_mod=np_mod,
                input_sample_rate=input_rate,
                read_block=lambda: self._read_arecord_block(
                    proc,
                    np_mod,
                    read_bytes,
                    timeout=0.2,
                ),
            )
        finally:
            self._stop_subprocess(proc)

    def _run_audio_buffer_loop(
        self,
        model,
        np_mod,
        input_sample_rate: int,
        read_block,
    ):
        flush_samples = int(input_sample_rate * self.segment_seconds)
        min_flush_samples = int(input_sample_rate * self.min_segment_seconds)
        buffer = np_mod.empty((0,), dtype=np_mod.float32)
        last_audio_ts = time.monotonic()

        while not self._stop_requested.is_set():
            block = read_block()
            if block is None:
                idle = time.monotonic() - last_audio_ts
                if (
                    buffer.size >= min_flush_samples
                    and idle >= self.max_idle_seconds
                ):
                    self._chunk_counter += 1
                    text = self._transcribe_buffer(
                        model,
                        buffer,
                        input_sample_rate,
                        np_mod,
                        chunk_id=self._chunk_counter,
                    )
                    buffer = np_mod.empty((0,), dtype=np_mod.float32)
                    if text:
                        self._emit_text_chunk(text)
                continue

            if getattr(block, "ndim", 1) == 2:
                mono = block[:, 0]
            else:
                mono = block
            mono = mono.astype(np_mod.float32, copy=False)
            self._update_noise_floor(np_mod, mono)
            buffer = np_mod.concatenate((buffer, mono))
            last_audio_ts = time.monotonic()

            while buffer.size >= flush_samples:
                chunk = buffer[:flush_samples].copy()
                buffer = buffer[flush_samples:]
                self._chunk_counter += 1
                text = self._transcribe_buffer(
                    model,
                    chunk,
                    input_sample_rate,
                    np_mod,
                    chunk_id=self._chunk_counter,
                )
                if text:
                    self._emit_text_chunk(text)

        if buffer.size >= min_flush_samples:
            self._chunk_counter += 1
            text = self._transcribe_buffer(
                model,
                buffer,
                input_sample_rate,
                np_mod,
                chunk_id=self._chunk_counter,
            )
            if text:
                self._emit_text_chunk(text)

    @staticmethod
    def _queue_get_block(audio_queue: queue.Queue[Any], timeout: float):
        try:
            return audio_queue.get(timeout=max(0.01, float(timeout)))
        except queue.Empty:
            return None

    def _open_best_arecord_stream(self):
        if not shutil.which("arecord"):
            raise RuntimeError(
                "Linux-Fallback benötigt arecord (alsa-utils).\n"
                "Installiere mit: sudo apt install alsa-utils"
            )

        rate_candidates = self._unique_ints(
            (
                self.sample_rate,
                16000,
                48000,
                44100,
                32000,
                24000,
                22050,
            )
        )
        device_candidates = self._arecord_device_candidates()
        self.status.emit(
            "Whisper-Diag arecord devices: "
            + ", ".join(device_candidates[:8])
        )
        errors: list[str] = []
        for dev in device_candidates:
            for rate in rate_candidates:
                cmd = [
                    "arecord",
                    "-D",
                    dev,
                    "-f",
                    "S16_LE",
                    "-c",
                    "1",
                    "-r",
                    str(rate),
                    "-t",
                    "raw",
                ]
                try:
                    proc = subprocess.Popen(
                        cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                    )
                except Exception as exc:
                    errors.append(f"{dev}@{rate}: {exc}")
                    continue

                time.sleep(0.15)
                if proc.poll() is None:
                    if proc.stdout is not None:
                        return proc, int(rate), dev
                    self._stop_subprocess(proc)
                    errors.append(f"{dev}@{rate}: stdout nicht verfügbar")
                    continue

                err_text = self._read_process_stderr(proc)
                errors.append(
                    f"{dev}@{rate}: {err_text or f'Exit {proc.returncode}'}"
                )

        detail = "\n".join(errors[:8]) if errors else "keine Details"
        raise RuntimeError(
            "Kein nutzbares Mikrofon gefunden.\n"
            "Bitte Eingabegerät im Betriebssystem prüfen.\n"
            f"Versuche:\n{detail}"
        )

    def _arecord_device_candidates(self) -> list[str]:
        forced = self.audio_device
        if forced is None:
            forced = self._parse_audio_device(
                os.getenv("DRAFT2CRAIFT_STT_AUDIO_DEVICE", "")
            )
        if forced is not None:
            return [self._to_arecord_device_name(forced)]

        discovered = self._read_arecord_devices()
        preferred = [
            "pulse",
            "pipewire",
            "default",
            "sysdefault",
        ]
        candidates: list[str] = []
        for name in preferred:
            if name not in candidates:
                candidates.append(name)
        for name in discovered:
            low = name.casefold()
            if low in {"null"}:
                continue
            if any(
                tag in low
                for tag in ("front", "rear", "surround", "hdmi", "spdif")
            ):
                continue
            if name not in candidates:
                candidates.append(name)
        for name in ("plughw:2,0", "plughw:1,0", "plughw:0,0"):
            if name not in candidates:
                candidates.append(name)
        return candidates

    @staticmethod
    def _to_arecord_device_name(device: int | str) -> str:
        if isinstance(device, int):
            return f"plughw:{device},0"
        raw = str(device).strip()
        return raw or "default"

    @staticmethod
    def _read_arecord_devices() -> list[str]:
        try:
            proc = subprocess.run(
                ["arecord", "-L"],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except Exception:
            return []
        if proc.returncode != 0 or not proc.stdout:
            return []
        out: list[str] = []
        for line in proc.stdout.splitlines():
            if not line or line[0].isspace():
                continue
            name = line.strip()
            if name and name not in out:
                out.append(name)
        return out

    @staticmethod
    def _read_arecord_block(
        proc: subprocess.Popen,
        np_mod,
        read_bytes: int,
        timeout: float = 0.2,
    ):
        if proc.stdout is None:
            return None
        try:
            ready, _, _ = select.select([proc.stdout], [], [], timeout)
        except Exception:
            ready = []
        if not ready:
            return None
        data = proc.stdout.read(max(2, int(read_bytes)))
        if not data:
            return None
        if len(data) % 2:
            data = data[:-1]
        if not data:
            return None
        audio_i16 = np_mod.frombuffer(data, dtype=np_mod.int16)
        return (audio_i16.astype(np_mod.float32) / 32768.0).reshape(-1)

    @staticmethod
    def _read_process_stderr(proc: subprocess.Popen) -> str:
        try:
            if proc.stderr is None:
                return ""
            raw = proc.stderr.read()
            if isinstance(raw, bytes):
                text = raw.decode("utf-8", errors="ignore")
            else:
                text = str(raw)
            return text.strip()
        except Exception:
            return ""

    @staticmethod
    def _stop_subprocess(proc: subprocess.Popen):
        try:
            if proc.poll() is None:
                proc.terminate()
                proc.wait(timeout=1.0)
        except Exception:
            try:
                if proc.poll() is None:
                    proc.kill()
            except Exception:
                pass

    @staticmethod
    def _unique_ints(values) -> list[int]:
        out: list[int] = []
        seen: set[int] = set()
        for value in values:
            try:
                num = int(value)
            except Exception:
                continue
            if num <= 0 or num in seen:
                continue
            seen.add(num)
            out.append(num)
        return out

    def _transcribe_buffer(
        self,
        model,
        audio,
        input_sample_rate: int,
        np_mod,
        chunk_id: int = 0,
    ) -> str:
        prepared = self._prepare_audio_for_model(
            np_mod,
            audio,
            input_sample_rate,
            self.sample_rate,
        )
        if prepared.size <= 0:
            return ""

        rms = self._rms(np_mod, prepared)
        peak = (
            float(np_mod.max(np_mod.abs(prepared)))
            if prepared.size
            else 0.0
        )
        threshold = self._effective_speech_threshold()
        has_strong_energy = self._has_strong_speech_energy(prepared, np_mod)
        if chunk_id > 0 and (chunk_id <= 3 or chunk_id % 5 == 0):
            self.status.emit(
                "Whisper-Diag "
                f"chunk={chunk_id} "
                f"rms={rms:.6f} peak={peak:.6f} thr={threshold:.6f}"
            )

        primary = self._transcribe_once(
            model,
            prepared,
            vad_filter=True,
        )
        if primary:
            return primary

        # Retry without VAD only when there is at least some plausible speech
        # energy. This must stay permissive; overly strict gating caused
        # false negatives on quiet microphones.
        allow_no_vad = (
            rms >= (threshold * 0.15)
            or peak >= (threshold * 0.80)
            or has_strong_energy
        )
        if not allow_no_vad:
            if chunk_id > 0 and (chunk_id <= 3 or chunk_id % 5 == 0):
                self.status.emit(
                    "Whisper-Diag "
                    f"chunk={chunk_id} fallback=no-vad skipped (low energy)"
                )
            return ""
        return self._transcribe_once(
            model,
            prepared,
            vad_filter=False,
        )

    def _transcribe_once(self, model, audio, vad_filter: bool) -> str:
        language = self.language or None
        segments, _info = model.transcribe(
            audio,
            language=language,
            task="transcribe",
            beam_size=self.beam_size,
            vad_filter=bool(vad_filter),
            vad_parameters={
                "threshold": 0.5,
                "min_silence_duration_ms": 450,
                "speech_pad_ms": 250,
            },
            condition_on_previous_text=False,
            temperature=0.0,
            no_speech_threshold=0.60,
            log_prob_threshold=-1.0,
            compression_ratio_threshold=2.4,
            hallucination_silence_threshold=1.0,
        )
        out: list[str] = []
        for seg in segments:
            text = str(getattr(seg, "text", "") or "").strip()
            if text:
                out.append(text)
        joined = " ".join(out).strip()
        if self._looks_hallucinated_repetition(joined):
            return ""
        return joined

    def _emit_text_chunk(self, text: str):
        clean = str(text or "").strip()
        if not clean:
            return
        norm = self._normalize_for_repeat_detection(clean)
        if norm and norm == self._last_emitted_norm:
            self._same_emit_count += 1
        else:
            self._last_emitted_norm = norm
            self._same_emit_count = 1

        # Drop repeated identical chunks after the 2nd repetition.
        if self._same_emit_count > 2:
            self._dropped_repetition_count += 1
            if self._dropped_repetition_count <= 2:
                self.status.emit(
                    "Whisper-Diag: wiederholten Chunk verworfen."
                )
            return
        self.text_chunk.emit(clean)

    @staticmethod
    def _normalize_for_repeat_detection(text: str) -> str:
        low = str(text or "").casefold()
        low = re.sub(r"\s+", " ", low).strip()
        return re.sub(r"[^\w\säöüß]", "", low)

    @staticmethod
    def _env_flag(name: str) -> bool:
        value = str(os.getenv(name, "") or "").strip().casefold()
        return value in {"1", "true", "yes", "on"}

    @staticmethod
    def _looks_like_path(value: str) -> bool:
        text = str(value or "").strip()
        if not text:
            return False
        if text.startswith(("~", ".", "/")):
            return True
        return ("/" in text) or ("\\" in text)

    @classmethod
    def _resolve_model_reference(cls, model_size: str) -> str:
        """
        Resolve user-facing model names to robust faster-whisper repo IDs.

        Some faster-whisper versions do not map names like `large-v3`
        reliably. Using explicit Systran repo IDs avoids that ambiguity.
        """
        raw = str(model_size or "").strip()
        if not raw:
            return "Systran/faster-whisper-tiny"
        if cls._looks_like_path(raw):
            return raw
        if "/" in raw:
            # Explicit repo id
            return raw
        key = raw.casefold()
        if key == "large":
            key = "large-v3"
        known = {
            "tiny",
            "tiny.en",
            "base",
            "base.en",
            "small",
            "small.en",
            "medium",
            "medium.en",
            "large-v1",
            "large-v2",
            "large-v3",
            "distil-small.en",
            "distil-medium.en",
            "distil-large-v2",
            "distil-large-v3",
        }
        if key in known:
            return f"Systran/faster-whisper-{key}"
        # Unknown custom names stay untouched.
        return raw

    @staticmethod
    def _stt_auto_download_enabled() -> bool:
        raw = str(os.getenv("DRAFT2CRAIFT_STT_AUTO_DOWNLOAD", "1"))
        clean = raw.strip().casefold()
        return clean not in {"0", "false", "no", "off"}

    def _whisper_download_dir(self) -> str:
        if self._looks_like_path(self.model_size):
            return ""
        env_raw = str(os.getenv("DRAFT2CRAIFT_WHISPER_MODELS_DIR", "")).strip()
        if env_raw:
            root = Path(env_raw).expanduser()
        else:
            root = (Path.cwd() / "models" / "whisper").resolve()
        try:
            root.mkdir(parents=True, exist_ok=True)
        except Exception:
            return ""
        return str(root.resolve())

    @staticmethod
    def _parse_audio_device(value):
        if value is None:
            return None
        raw = str(value).strip()
        if not raw:
            return None
        if raw.casefold() in {"default", "auto"}:
            return None
        try:
            idx = int(raw)
            return idx if idx >= 0 else None
        except Exception:
            return raw

    @staticmethod
    def _resolve_input_device(sd_mod):
        device = None
        try:
            current = sd_mod.default.device
            device = WhisperDictationWorker._normalize_input_device_id(current)
            if isinstance(device, int) and device < 0:
                device = None
        except Exception:
            device = None
        return device

    @staticmethod
    def _normalize_input_device_id(device):
        value = device
        if value is None:
            return None
        try:
            if hasattr(value, "__len__") and hasattr(value, "__getitem__"):
                if not isinstance(value, (str, bytes)):
                    if len(value) > 0:
                        value = value[0]
        except Exception:
            pass

        try:
            if isinstance(value, float):
                value = int(value)
            if isinstance(value, str) and value.strip().isdigit():
                value = int(value.strip())
        except Exception:
            pass
        return value

    def _input_device_candidates(self, sd_mod) -> list[int | str | None]:
        forced_device = self.audio_device
        if forced_device is None:
            forced_device = self._parse_audio_device(
                os.getenv("DRAFT2CRAIFT_STT_AUDIO_DEVICE", "")
            )
        if forced_device is not None:
            return [forced_device]

        default_device = self._normalize_input_device_id(
            self._resolve_input_device(sd_mod)
        )
        safe_candidates: list[tuple[int, int]] = []
        hw_fallback_candidates: list[tuple[int, int]] = []

        try:
            devices = sd_mod.query_devices()
        except Exception:
            return [default_device]

        for idx, dev in enumerate(devices):
            try:
                in_ch = int(dev.get("max_input_channels", 0))
            except Exception:
                in_ch = 0
            if in_ch <= 0:
                continue

            name = str(dev.get("name", "") or "").casefold()
            score = 0
            if idx == default_device:
                score += 20
            preferred_tags = ("pipewire", "pulse", "default", "sysdefault")
            if any(tag in name for tag in preferred_tags):
                score += 80
            if any(
                tag in name
                for tag in (
                    "front",
                    "rear",
                    "surround",
                    "hdmi",
                    "iec958",
                    "spdif",
                )
            ):
                score -= 40
            if any(tag in name for tag in ("monitor", "loopback")):
                score -= 20
            is_hw = "hw:" in name
            if is_hw:
                score -= 40
                if self._allow_hw_audio:
                    hw_fallback_candidates.append((score, idx))
            else:
                safe_candidates.append((score, idx))

        safe_candidates.sort(key=lambda item: item[0], reverse=True)
        hw_fallback_candidates.sort(
            key=lambda item: item[0],
            reverse=True,
        )
        result: list[int | None] = [
            idx for _score, idx in safe_candidates
        ]
        if not result:
            # Only if no safer virtual/default device is available.
            result.extend(idx for _score, idx in hw_fallback_candidates)

        # De-duplicate while preserving order.
        unique: list[int | str | None] = []
        seen: set[int | str | None] = set()
        for dev in result:
            dev_norm = self._normalize_input_device_id(dev)
            if isinstance(dev_norm, int) and dev_norm < 0:
                continue
            if dev_norm in seen:
                continue
            seen.add(dev_norm)
            unique.append(dev_norm)

        if (
            default_device is not None
            and default_device not in seen
            and (
                self._allow_hw_audio
                or not self._is_hw_device(sd_mod, default_device)
            )
        ):
            unique.append(default_device)

        # Virtual input aliases often route correctly via PipeWire/Pulse
        # even when raw ALSA endpoints fail.
        for alias in ("default", "sysdefault", "pipewire", "pulse"):
            if alias in seen:
                continue
            unique.append(alias)
            seen.add(alias)

        if None not in seen:
            unique.append(None)
        return unique or [default_device, "default", None]

    def _open_best_input_stream(self, sd_mod, callback):
        candidates = self._input_device_candidates(sd_mod)
        errors: list[str] = []
        try:
            labels = [self._device_label(sd_mod, d) for d in candidates]
            self.status.emit(
                "Whisper-Diag devices: " + ", ".join(labels[:8])
            )
        except Exception:
            pass
        for device in candidates:
            if not self._allow_hw_audio and self._is_hw_device(sd_mod, device):
                errors.append(
                    f"{self._device_label(sd_mod, device)}: "
                    "übersprungen (direktes ALSA hw: Gerät)"
                )
                continue
            try:
                input_rate, input_channels = self._resolve_input_stream_format(
                    sd_mod,
                    device,
                )
            except Exception as exc:
                errors.append(
                    f"{self._device_label(sd_mod, device)}: {exc}"
                )
                continue

            try:
                blocksize = max(256, int(input_rate * self.block_seconds))
                stream_ctx = sd_mod.InputStream(
                    samplerate=input_rate,
                    device=device,
                    channels=input_channels,
                    dtype="float32",
                    blocksize=blocksize,
                    callback=callback,
                )
                return stream_ctx, input_rate, device
            except Exception as exc:
                errors.append(
                    f"{self._device_label(sd_mod, device)} "
                    f"@ {input_rate} Hz: {exc}"
                )

        detail = "\n".join(errors[:8]) if errors else "keine Details"
        if not self._allow_hw_audio:
            detail += (
                "\nHinweis: Direkte ALSA hw:-Geräte sind "
                "standardmäßig deaktiviert (Stabilität). "
                "Override: DRAFT2CRAIFT_STT_ALLOW_HW=1"
            )
        raise RuntimeError(
            "Kein nutzbares Mikrofon gefunden.\n"
            "Bitte Eingabegerät im Betriebssystem prüfen.\n"
            f"Versuche:\n{detail}"
        )

    def _is_hw_device(self, sd_mod, device) -> bool:
        dev_norm = self._normalize_input_device_id(device)
        if isinstance(device, str):
            name = device
        elif dev_norm is None:
            return False
        else:
            try:
                info = sd_mod.query_devices(device=dev_norm)
            except Exception:
                # Unknown numeric ALSA endpoints are treated as unsafe.
                return isinstance(dev_norm, int)
            name = str(info.get("name", "") or "")
        low = name.casefold()
        return ("hw:" in low) and ("plughw" not in low)

    @staticmethod
    def _device_label(sd_mod, device) -> str:
        dev_norm = WhisperDictationWorker._normalize_input_device_id(device)
        if dev_norm is None:
            return "default"
        try:
            info = sd_mod.query_devices(device=dev_norm)
            return f"{dev_norm}:{info.get('name', '?')}"
        except Exception:
            return str(dev_norm)

    def _resolve_input_stream_format(
        self,
        sd_mod,
        device,
    ) -> tuple[int, int]:
        candidates: list[int] = []
        try:
            info = sd_mod.query_devices(device=device, kind="input")
            default_rate = info.get("default_samplerate")
            if default_rate:
                candidates.append(int(round(float(default_rate))))
            max_in = int(info.get("max_input_channels", 0) or 0)
        except Exception:
            max_in = 0
        channel_candidates = self._candidate_input_channels(max_in)

        fallback_rates = (
            self.sample_rate,
            48000,
            44100,
            32000,
            24000,
            22050,
            16000,
        )
        for rate in fallback_rates:
            candidates.append(int(rate))

        unique_rates: list[int] = []
        seen: set[int] = set()
        for rate in candidates:
            if rate <= 0 or rate in seen:
                continue
            unique_rates.append(rate)
            seen.add(rate)

        errors: list[str] = []
        for channels in channel_candidates:
            for rate in unique_rates:
                try:
                    sd_mod.check_input_settings(
                        device=device,
                        channels=channels,
                        dtype="float32",
                        samplerate=rate,
                    )
                    return rate, channels
                except Exception as exc:
                    errors.append(
                        f"{rate} Hz / {channels}ch: {exc}"
                    )

        details = "\n".join(errors[:6]) if errors else "keine Details"
        raise RuntimeError(
            "Kein gültiges Mikrofon-Format gefunden.\n"
            "Bitte Standard-Eingabegerät im Betriebssystem prüfen.\n"
            f"Getestete Kombinationen:\n{details}"
        )

    @staticmethod
    def _candidate_input_channels(max_input_channels: int) -> list[int]:
        max_in = max(0, int(max_input_channels))
        # Prefer mono first (best for STT), then stereo.
        candidates: list[int] = [1, 2]
        if 0 < max_in <= 8:
            candidates.append(max_in)
        if max_in >= 4:
            candidates.extend([3, 4])

        out: list[int] = []
        seen: set[int] = set()
        for ch in candidates:
            if ch <= 0 or ch in seen:
                continue
            if max_in > 0 and ch > max_in:
                continue
            seen.add(ch)
            out.append(ch)
        return out or [1, 2]

    @staticmethod
    def _prepare_audio_for_model(np_mod, audio, src_rate: int, dst_rate: int):
        arr = audio.astype(np_mod.float32, copy=False)
        if arr.size <= 0:
            return arr
        if int(src_rate) == int(dst_rate):
            return arr

        src = max(1, int(src_rate))
        dst = max(1, int(dst_rate))
        out_len = max(1, int(round(arr.size * (dst / src))))
        x_old = np_mod.arange(arr.size, dtype=np_mod.float64)
        x_new = np_mod.linspace(
            0.0,
            float(max(0, arr.size - 1)),
            num=out_len,
            dtype=np_mod.float64,
        )
        resampled = np_mod.interp(
            x_new,
            x_old,
            arr,
        ).astype(np_mod.float32, copy=False)
        return resampled

    def _effective_speech_threshold(self) -> float:
        base = self.speech_rms_threshold
        if not self._noise_ready:
            return base
        adaptive = self._noise_rms_ema * 2.0
        adaptive = max(base * 0.35, adaptive)
        adaptive = min(base * 6.0, adaptive)
        adaptive = min(0.0025, adaptive)
        return adaptive

    def _update_noise_floor(self, np_mod, audio):
        rms = self._rms(np_mod, audio)
        peak = float(np_mod.max(np_mod.abs(audio))) if audio.size else 0.0
        if rms <= 0.0:
            return
        if not self._noise_ready:
            self._noise_rms_ema = rms
            self._noise_ready = True
            return

        # Ignore likely speech bursts while learning background noise.
        if self._noise_rms_ema > 0.0:
            if (
                rms >= (self._noise_rms_ema * 4.0)
                and peak >= (self._noise_rms_ema * 12.0)
            ):
                return

        # Update aggressively near current noise, conservatively otherwise.
        if rms <= (self._noise_rms_ema * 1.7):
            alpha = 0.05
        else:
            alpha = 0.004
        self._noise_rms_ema = (
            (1.0 - alpha) * self._noise_rms_ema
        ) + (alpha * rms)

    @staticmethod
    def _rms(np_mod, audio) -> float:
        if audio.size <= 0:
            return 0.0
        return float(np_mod.sqrt(np_mod.mean(np_mod.square(audio))))

    def _has_speech_energy(self, audio, np_mod) -> bool:
        if audio.size <= 0:
            return False
        rms = self._rms(np_mod, audio)
        peak = float(np_mod.max(np_mod.abs(audio)))
        threshold = self._effective_speech_threshold()
        if rms >= threshold:
            return True
        return peak >= (threshold * 6.0)

    def _has_strong_speech_energy(self, audio, np_mod) -> bool:
        if audio.size <= 0:
            return False
        rms = self._rms(np_mod, audio)
        peak = float(np_mod.max(np_mod.abs(audio)))
        threshold = self._effective_speech_threshold()
        if rms >= (threshold * 1.10):
            return True
        return peak >= (threshold * 4.5)

    @staticmethod
    def _looks_hallucinated_repetition(text: str) -> bool:
        clean = str(text or "").strip()
        if not clean:
            return False

        sentences = [
            s.strip() for s in re.split(r"[.!?]+", clean) if s.strip()
        ]
        if len(sentences) < 4:
            return False

        counts: dict[str, int] = {}
        for sentence in sentences:
            key = re.sub(r"\s+", " ", sentence.casefold()).strip()
            if not key:
                continue
            counts[key] = counts.get(key, 0) + 1

        if not counts:
            return False
        dominant = max(counts.values())
        ratio = dominant / max(1, len(sentences))
        is_short_loop = max((len(k) for k in counts), default=0) <= 24
        return is_short_loop and dominant >= 6 and ratio >= 0.80
