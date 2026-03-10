"""Piper model and WAV composition helpers for TTS."""
from __future__ import annotations

from pathlib import Path
import tempfile
import wave

from shared.config.app_settings import SpeechSettings
from shared.services.speech.piper_models import best_local_piper_model

from .helpers_text import _TRAILING_PUNCT_RE, _WHITESPACE_RE

def _resolve_piper_model_path(settings: SpeechSettings) -> str:
    explicit = str(settings.tts_model_path or "").strip()
    if explicit:
        if explicit.startswith(("http://", "https://")):
            raise RuntimeError(
                "Nur lokale Piper-Modelle erlaubt. "
                "HTTP/HTTPS ist deaktiviert."
            )
        model = Path(explicit).expanduser()
        if model.exists() and model.is_file():
            return str(model.resolve())
        raise RuntimeError(f"Piper-Modell nicht gefunden: {explicit}")

    language = str(settings.tts_language or "").strip()
    model = best_local_piper_model(language)
    if model:
        return model
    return ""

def _piper_length_scale(rate_percent: int) -> float:
    # piper: lower length_scale => faster speech.
    clean_rate = max(50, min(300, int(rate_percent)))
    if clean_rate == 100:
        return 1.0
    return max(0.55, min(1.8, 100.0 / float(clean_rate)))

def _piper_lead_in_ms(settings: SpeechSettings) -> int:
    # Some output devices clip the first ~100-300ms after playback starts.
    # Add a short silent pre-roll to protect leading words.
    base = int(getattr(settings, "tts_lead_in_ms", 320) or 320)
    return max(0, min(2000, base))

def _apply_start_trigger(text: str, trigger: str) -> str:
    payload = str(text or "").strip()
    if not payload:
        return ""
    starter = _WHITESPACE_RE.sub(" ", str(trigger or "")).strip()
    if not starter:
        return payload
    if not _TRAILING_PUNCT_RE.search(starter):
        starter = f"{starter}."
    return f"{starter} {payload}".strip()

def _new_temp_wav_path() -> str:
    with tempfile.NamedTemporaryFile(
        suffix=".wav",
        delete=False,
    ) as tmp:
        return tmp.name

def _concat_wav_files(
    segment_paths: list[str],
    output_path: str,
    *,
    inter_silence_ms: int,
    guard_ms: int = 0,
):
    paths = [str(p or "").strip() for p in segment_paths if str(p or "").strip()]
    if not paths:
        raise RuntimeError("Keine Audiosegmente fuer TTS-Konkatenation vorhanden.")

    silence_ms = max(0, int(inter_silence_ms))
    with wave.open(paths[0], "rb") as first:
        channels = int(first.getnchannels())
        sample_width = int(first.getsampwidth())
        sample_rate = int(first.getframerate())
        params = first.getparams()

    if channels <= 0 or sample_width <= 0 or sample_rate <= 0:
        raise RuntimeError("Ungueltiges WAV-Format aus Piper.")

    gap_pcm = _build_inter_segment_gap_pcm(
        sample_rate=sample_rate,
        channels=channels,
        sample_width=sample_width,
        total_ms=silence_ms,
        guard_ms=max(0, int(guard_ms)),
    )

    with wave.open(output_path, "wb") as out:
        out.setparams(params)
        for idx, path in enumerate(paths):
            with wave.open(path, "rb") as src:
                if (
                    int(src.getnchannels()) != channels
                    or int(src.getsampwidth()) != sample_width
                    or int(src.getframerate()) != sample_rate
                ):
                    raise RuntimeError(
                        "Inkonsistente WAV-Parameter bei TTS-Segmenten."
                    )
                out.writeframes(src.readframes(src.getnframes()))
            if idx < (len(paths) - 1) and gap_pcm:
                out.writeframes(gap_pcm)

def _build_inter_segment_gap_pcm(
    *,
    sample_rate: int,
    channels: int,
    sample_width: int,
    total_ms: int,
    guard_ms: int,
) -> bytes:
    total = max(0, int(total_ms))
    if total <= 0:
        return b""

    guard = max(0, min(int(guard_ms), total))
    zeros_ms = total - guard

    zero_pcm = _build_silence_pcm(
        sample_rate=sample_rate,
        channels=channels,
        sample_width=sample_width,
        milliseconds=zeros_ms,
    )
    if guard <= 0:
        return zero_pcm

    guard_pcm = _build_guard_pcm(
        sample_rate=sample_rate,
        channels=channels,
        sample_width=sample_width,
        milliseconds=guard,
    )
    return zero_pcm + guard_pcm

def _build_silence_pcm(
    *,
    sample_rate: int,
    channels: int,
    sample_width: int,
    milliseconds: int,
) -> bytes:
    ms = max(0, int(milliseconds))
    if ms <= 0:
        return b""
    frames = int(round(sample_rate * (ms / 1000.0)))
    if frames <= 0:
        return b""
    return b"\x00" * (frames * channels * sample_width)

def _build_guard_pcm(
    *,
    sample_rate: int,
    channels: int,
    sample_width: int,
    milliseconds: int,
) -> bytes:
    """
    Very low-level non-zero PCM to keep audio devices "awake" right before the
    next segment starts. This avoids first-word clipping after long pure silence.
    """
    ms = max(0, int(milliseconds))
    if ms <= 0:
        return b""
    frames = int(round(sample_rate * (ms / 1000.0)))
    if frames <= 0:
        return b""

    if sample_width == 2:
        amp = 18  # ~ -65 dBFS, effectively inaudible but non-zero.
        frame_bytes = bytearray()
        sign = 1
        for i in range(frames):
            if (i % 32) == 0:
                sign *= -1
            value = amp * sign
            sample = int(value).to_bytes(
                2,
                byteorder="little",
                signed=True,
            )
            for _ in range(channels):
                frame_bytes.extend(sample)
        return bytes(frame_bytes)

    # Fallback for uncommon sample widths.
    return _build_silence_pcm(
        sample_rate=sample_rate,
        channels=channels,
        sample_width=sample_width,
        milliseconds=ms,
    )

def _prepend_wav_silence(wav_path: str, milliseconds: int):
    lead_ms = max(0, int(milliseconds))
    if lead_ms <= 0:
        return
    try:
        with wave.open(wav_path, "rb") as src:
            params = src.getparams()
            channels = int(src.getnchannels())
            sample_width = int(src.getsampwidth())
            sample_rate = int(src.getframerate())
            frames = src.readframes(src.getnframes())
    except Exception:
        return

    if channels <= 0 or sample_width <= 0 or sample_rate <= 0:
        return

    silence_frames = int(round(sample_rate * (lead_ms / 1000.0)))
    if silence_frames <= 0:
        return
    silence = b"\x00" * (silence_frames * channels * sample_width)

    try:
        with wave.open(wav_path, "wb") as dst:
            dst.setparams(params)
            dst.writeframes(silence)
            dst.writeframes(frames)
    except Exception:
        return

__all__ = [
    "_resolve_piper_model_path",
    "_piper_length_scale",
    "_piper_lead_in_ms",
    "_apply_start_trigger",
    "_new_temp_wav_path",
    "_concat_wav_files",
    "_build_inter_segment_gap_pcm",
    "_build_silence_pcm",
    "_build_guard_pcm",
    "_prepend_wav_silence",
]
