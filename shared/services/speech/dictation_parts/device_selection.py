"""WhisperDictationWorker method implementations."""
from __future__ import annotations

from .deps import *  # noqa: F403

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

@classmethod
def _resolve_input_device(cls, sd_mod):
    device = None
    try:
        current = sd_mod.default.device
        device = cls._normalize_input_device_id(current)
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

@classmethod
def _device_label(cls, sd_mod, device) -> str:
    dev_norm = cls._normalize_input_device_id(device)
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

__all__ = [
    "_parse_audio_device",
    "_resolve_input_device",
    "_normalize_input_device_id",
    "_input_device_candidates",
    "_open_best_input_stream",
    "_is_hw_device",
    "_device_label",
    "_resolve_input_stream_format",
    "_candidate_input_channels",
]
