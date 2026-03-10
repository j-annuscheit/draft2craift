"""WhisperDictationWorker method implementations."""
from __future__ import annotations

from .deps import *  # noqa: F403

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

__all__ = [
    "_open_best_arecord_stream",
    "_arecord_device_candidates",
    "_to_arecord_device_name",
    "_read_arecord_devices",
    "_read_arecord_block",
    "_read_process_stderr",
    "_stop_subprocess",
    "_unique_ints",
]
