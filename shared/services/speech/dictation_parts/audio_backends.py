"""WhisperDictationWorker method implementations."""
from __future__ import annotations

from .deps import *  # noqa: F403

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

__all__ = [
    "_select_audio_backend",
    "_run_sounddevice_loop",
    "_run_arecord_loop",
    "_run_audio_buffer_loop",
    "_queue_get_block",
]
