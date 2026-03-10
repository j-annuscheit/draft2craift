"""Live microphone level probe used by Speech Settings dialog."""
from __future__ import annotations

import os
import queue
import select
import shutil
import subprocess
import threading
from typing import Any

from PySide6.QtCore import QThread, Signal


class InputLevelProbeWorker(QThread):
    """Continuously emit normalized microphone levels in [0.0, 1.0]."""

    level_changed = Signal(float)
    status = Signal(str)
    failed = Signal(str)
    stopped_ok = Signal()

    def __init__(
        self,
        parent=None,
        backend: str = "auto",
        device: str = "",
        sample_rate: int = 16000,
        block_seconds: float = 0.12,
    ):
        super().__init__(parent)
        self.backend = str(backend or "auto").strip().lower()
        self.device = str(device or "").strip()
        self.sample_rate = max(8000, int(sample_rate))
        self.block_seconds = max(0.05, float(block_seconds))
        self._stop_requested = threading.Event()

    def request_stop(self):
        self._stop_requested.set()

    def run(self):
        self._stop_requested.clear()
        try:
            mode = self._resolve_backend()
            self.status.emit(f"Level probe backend: {mode}")
            if mode == "arecord":
                self._run_arecord_probe()
            else:
                self._run_sounddevice_probe()
            self.stopped_ok.emit()
        except Exception as exc:
            self.failed.emit(str(exc))

    def _resolve_backend(self) -> str:
        if self.backend in {"arecord", "sounddevice"}:
            return self.backend
        if os.name != "nt" and shutil.which("arecord"):
            return "arecord"
        return "sounddevice"

    def _run_arecord_probe(self):
        if not shutil.which("arecord"):
            raise RuntimeError("arecord nicht gefunden.")
        device = self.device or "default"
        cmd = [
            "arecord",
            "-D",
            device,
            "-f",
            "S16_LE",
            "-c",
            "1",
            "-r",
            str(self.sample_rate),
            "-t",
            "raw",
        ]
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            if proc.stdout is None:
                raise RuntimeError("arecord stdout ist nicht verfügbar.")
            read_bytes = max(
                320,
                int(self.sample_rate * self.block_seconds) * 2,
            )
            while not self._stop_requested.is_set():
                ready, _, _ = select.select([proc.stdout], [], [], 0.2)
                if not ready:
                    continue
                data = proc.stdout.read(read_bytes)
                if not data:
                    if proc.poll() is not None:
                        err = _read_stderr(proc)
                        raise RuntimeError(
                            f"arecord beendet: {err or proc.returncode}"
                        )
                    continue
                level = _pcm16_rms_level(data)
                self.level_changed.emit(level)
        finally:
            _stop_process(proc)

    def _run_sounddevice_probe(self):
        try:
            import numpy as np  # type: ignore
            import sounddevice as sd  # type: ignore
        except Exception as exc:
            raise RuntimeError(
                "sounddevice/numpy fehlen für Probe."
            ) from exc

        queue_blocks: queue.Queue[Any] = queue.Queue(maxsize=32)
        warnings: list[str] = []
        selected_device = _parse_sounddevice_device(self.device)
        channel_count = 1
        blocksize = max(256, int(self.sample_rate * self.block_seconds))

        def _callback(indata, _frames, _time_info, status):
            if status:
                warnings.append(str(status))
            try:
                queue_blocks.put_nowait(indata.copy())
            except queue.Full:
                pass

        with sd.InputStream(
            samplerate=self.sample_rate,
            device=selected_device,
            channels=channel_count,
            dtype="float32",
            blocksize=blocksize,
            callback=_callback,
        ):
            while not self._stop_requested.is_set():
                try:
                    block = queue_blocks.get(timeout=0.2)
                except queue.Empty:
                    continue
                if getattr(block, "ndim", 1) == 2:
                    mono = block[:, 0]
                else:
                    mono = block
                mono = mono.astype(np.float32, copy=False)
                rms = (
                    float(np.sqrt(np.mean(np.square(mono))))
                    if mono.size
                    else 0.0
                )
                level = max(0.0, min(1.0, rms * 8.0))
                self.level_changed.emit(level)
        if warnings:
            self.status.emit(f"Audio-Hinweis: {warnings[-1]}")


def _pcm16_rms_level(data: bytes) -> float:
    if not data:
        return 0.0
    if len(data) % 2:
        data = data[:-1]
    if not data:
        return 0.0
    # Inline parsing avoids a hard numpy dependency for the arecord path.
    sample_count = len(data) // 2
    if sample_count <= 0:
        return 0.0
    total = 0.0
    for i in range(0, len(data), 2):
        raw = int.from_bytes(data[i:i + 2], "little", signed=True)
        value = raw / 32768.0
        total += value * value
    rms = (total / sample_count) ** 0.5
    return max(0.0, min(1.0, rms * 8.0))


def _read_stderr(proc: subprocess.Popen) -> str:
    try:
        if proc.stderr is None:
            return ""
        raw = proc.stderr.read()
        if isinstance(raw, bytes):
            return raw.decode("utf-8", errors="ignore").strip()
        return str(raw).strip()
    except Exception:
        return ""


def _stop_process(proc: subprocess.Popen):
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


def _parse_sounddevice_device(value: str):
    raw = str(value or "").strip()
    if not raw:
        return None
    if ":" in raw:
        left, _sep, _right = raw.partition(":")
        if left.strip().isdigit():
            return int(left.strip())
    if raw.isdigit():
        return int(raw)
    return raw
