"""WhisperDictationWorker method implementations."""
from __future__ import annotations

from .deps import *  # noqa: F403

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

__all__ = [
    "_prepare_audio_for_model",
    "_effective_speech_threshold",
    "_update_noise_floor",
    "_rms",
    "_has_speech_energy",
    "_has_strong_speech_energy",
    "_looks_hallucinated_repetition",
]
