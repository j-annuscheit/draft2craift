"""WhisperDictationWorker method implementations."""
from __future__ import annotations

from .deps import *  # noqa: F403

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

__all__ = [
    "_transcribe_buffer",
    "_transcribe_once",
    "_emit_text_chunk",
    "_normalize_for_repeat_detection",
]
