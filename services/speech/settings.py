"""Speech settings shared by STT and future TTS features."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import os


_STT_BACKENDS = {"auto", "arecord", "sounddevice"}
_WHISPER_MODELS = {"tiny", "base", "small", "medium", "large-v3"}
_COMPUTE_TYPES = {"int8", "int8_float16", "float16", "float32"}
_TTS_ENGINES = {"none", "piper", "pyttsx3", "spd-say", "espeak"}
_CHAT_TTS_MODES = {"off", "once", "always"}


def _default_stt_backend() -> str:
    if os.name == "nt":
        return "sounddevice"
    return "auto"


def _default_input_device() -> str:
    if os.name == "nt":
        return ""
    return "pipewire"


def _default_tts_pause_triggers() -> str:
    # Pipe-separated so entries like "," and " - " remain unambiguous.
    return ",|:|;| - |—|–|‒|―"


@dataclass
class SpeechSettings:
    """Runtime speech settings editable via GUI."""

    stt_backend: str = _default_stt_backend()
    stt_input_device: str = _default_input_device()
    stt_model_size: str = "tiny"
    stt_language: str = "de"
    stt_compute_type: str = "int8"
    stt_cpu_threads: int = 4
    tts_engine: str = "piper"
    tts_language: str = "de"
    tts_model_path: str = ""
    tts_speaker_id: int = -1
    tts_output_device: str = "default"
    tts_voice: str = ""
    tts_rate: int = 100
    tts_volume: int = 100
    tts_pause_ms: int = 220
    tts_trigger_pause_ms: int = 320
    tts_lead_in_ms: int = 320
    tts_start_trigger: str = ""
    tts_pause_triggers: str = _default_tts_pause_triggers()
    chat_tts_mode: str = "off"

    def to_dict(self) -> dict:
        """Return settings as plain JSON-serializable dict."""
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: object) -> "SpeechSettings":
        """Build settings object with validation and sane fallbacks."""
        if not isinstance(raw, dict):
            return cls()

        data = dict(raw)
        backend = str(
            data.get("stt_backend", cls().stt_backend)
        ).strip().lower()
        if backend not in _STT_BACKENDS:
            backend = cls().stt_backend

        model = str(
            data.get("stt_model_size", cls().stt_model_size)
        ).strip()
        model_low = model.lower()
        if not model:
            model = cls().stt_model_size
        elif model_low in _WHISPER_MODELS:
            model = model_low
        elif _looks_like_path(model):
            # Keep explicit local paths untouched.
            model = model
        else:
            model = cls().stt_model_size

        compute = str(
            data.get("stt_compute_type", cls().stt_compute_type)
        ).strip().lower()
        if compute not in _COMPUTE_TYPES:
            compute = cls().stt_compute_type

        tts_engine = str(
            data.get("tts_engine", cls().tts_engine)
        ).strip().lower()
        if tts_engine not in _TTS_ENGINES:
            tts_engine = cls().tts_engine
        chat_tts_mode = str(
            data.get("chat_tts_mode", cls().chat_tts_mode)
        ).strip().lower()
        if chat_tts_mode not in _CHAT_TTS_MODES:
            chat_tts_mode = cls().chat_tts_mode

        cpu_threads = _int_in_range(
            data.get("stt_cpu_threads", cls().stt_cpu_threads),
            min_value=1,
            max_value=64,
            default=cls().stt_cpu_threads,
        )
        tts_rate = _int_in_range(
            data.get("tts_rate", cls().tts_rate),
            min_value=50,
            max_value=300,
            default=cls().tts_rate,
        )
        tts_volume = _int_in_range(
            data.get("tts_volume", cls().tts_volume),
            min_value=0,
            max_value=100,
            default=cls().tts_volume,
        )
        tts_pause_ms = _int_in_range(
            data.get("tts_pause_ms", cls().tts_pause_ms),
            min_value=0,
            max_value=2000,
            default=cls().tts_pause_ms,
        )
        tts_trigger_pause_ms = _int_in_range(
            data.get(
                "tts_trigger_pause_ms",
                cls().tts_trigger_pause_ms,
            ),
            min_value=0,
            max_value=4000,
            default=cls().tts_trigger_pause_ms,
        )
        tts_lead_in_ms = _int_in_range(
            data.get("tts_lead_in_ms", cls().tts_lead_in_ms),
            min_value=0,
            max_value=2000,
            default=cls().tts_lead_in_ms,
        )
        tts_start_trigger = str(
            data.get("tts_start_trigger", cls().tts_start_trigger) or ""
        ).strip()
        tts_pause_triggers = str(
            data.get("tts_pause_triggers", cls().tts_pause_triggers) or ""
        ).strip()
        tts_speaker_id = _int_in_range(
            data.get("tts_speaker_id", cls().tts_speaker_id),
            min_value=-1,
            max_value=999,
            default=cls().tts_speaker_id,
        )
        tts_language = (
            str(data.get("tts_language", "de") or "").strip() or "de"
        )

        return cls(
            stt_backend=backend,
            stt_input_device=str(
                data.get("stt_input_device", "") or ""
            ).strip(),
            stt_model_size=model,
            stt_language=str(data.get("stt_language", "de") or "").strip(),
            stt_compute_type=compute,
            stt_cpu_threads=cpu_threads,
            tts_engine=tts_engine,
            tts_language=tts_language,
            tts_model_path=str(data.get("tts_model_path", "") or "").strip(),
            tts_speaker_id=tts_speaker_id,
            tts_output_device=str(
                data.get("tts_output_device", "") or ""
            ).strip(),
            tts_voice=str(data.get("tts_voice", "") or "").strip(),
            tts_rate=tts_rate,
            tts_volume=tts_volume,
            tts_pause_ms=tts_pause_ms,
            tts_trigger_pause_ms=tts_trigger_pause_ms,
            tts_lead_in_ms=tts_lead_in_ms,
            tts_start_trigger=tts_start_trigger,
            tts_pause_triggers=tts_pause_triggers,
            chat_tts_mode=chat_tts_mode,
        )


def _int_in_range(
    value: object,
    *,
    min_value: int,
    max_value: int,
    default: int,
) -> int:
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except Exception:
        return default
    return max(min_value, min(max_value, parsed))


def _looks_like_path(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    if text.startswith(("~", ".", "/")):
        return True
    return ("/" in text) or ("\\" in text)
