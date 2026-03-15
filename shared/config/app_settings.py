"""Application settings models."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import os

from shared.domain.user_mode import default_user_mode
from shared.config.setting_keys import SpeechSettingsKeys


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
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: object) -> "SpeechSettings":
        if not isinstance(raw, dict):
            return cls()
        data = dict(raw)
        defaults = cls()
        backend = str(
            data.get(SpeechSettingsKeys.STT_BACKEND, defaults.stt_backend)
        ).strip().lower()
        if backend not in _STT_BACKENDS:
            backend = defaults.stt_backend
        model = str(
            data.get(SpeechSettingsKeys.STT_MODEL_SIZE, defaults.stt_model_size)
        ).strip()
        model_low = model.lower()
        if not model:
            model = defaults.stt_model_size
        elif model_low in _WHISPER_MODELS:
            model = model_low
        elif not _looks_like_path(model):
            model = defaults.stt_model_size
        compute = str(
            data.get(SpeechSettingsKeys.STT_COMPUTE_TYPE, defaults.stt_compute_type)
        ).strip().lower()
        if compute not in _COMPUTE_TYPES:
            compute = defaults.stt_compute_type
        tts_engine = str(
            data.get(SpeechSettingsKeys.TTS_ENGINE, defaults.tts_engine)
        ).strip().lower()
        if tts_engine not in _TTS_ENGINES:
            tts_engine = defaults.tts_engine
        chat_tts_mode = str(
            data.get(SpeechSettingsKeys.CHAT_TTS_MODE, defaults.chat_tts_mode)
        ).strip().lower()
        if chat_tts_mode not in _CHAT_TTS_MODES:
            chat_tts_mode = defaults.chat_tts_mode
        return cls(
            stt_backend=backend,
            stt_input_device=str(
                data.get(SpeechSettingsKeys.STT_INPUT_DEVICE, "") or ""
            ).strip(),
            stt_model_size=model,
            stt_language=str(
                data.get(SpeechSettingsKeys.STT_LANGUAGE, "de") or ""
            ).strip(),
            stt_compute_type=compute,
            stt_cpu_threads=_int_in_range(
                data.get(SpeechSettingsKeys.STT_CPU_THREADS, defaults.stt_cpu_threads),
                min_value=1,
                max_value=64,
                default=defaults.stt_cpu_threads,
            ),
            tts_engine=tts_engine,
            tts_language=(
                str(data.get(SpeechSettingsKeys.TTS_LANGUAGE, "de") or "").strip()
                or "de"
            ),
            tts_model_path=str(
                data.get(SpeechSettingsKeys.TTS_MODEL_PATH, "") or ""
            ).strip(),
            tts_speaker_id=_int_in_range(
                data.get(SpeechSettingsKeys.TTS_SPEAKER_ID, defaults.tts_speaker_id),
                min_value=-1,
                max_value=999,
                default=defaults.tts_speaker_id,
            ),
            tts_output_device=str(
                data.get(SpeechSettingsKeys.TTS_OUTPUT_DEVICE, "") or ""
            ).strip(),
            tts_voice=str(data.get(SpeechSettingsKeys.TTS_VOICE, "") or "").strip(),
            tts_rate=_int_in_range(
                data.get(SpeechSettingsKeys.TTS_RATE, defaults.tts_rate),
                min_value=50,
                max_value=300,
                default=defaults.tts_rate,
            ),
            tts_volume=_int_in_range(
                data.get(SpeechSettingsKeys.TTS_VOLUME, defaults.tts_volume),
                min_value=0,
                max_value=100,
                default=defaults.tts_volume,
            ),
            tts_pause_ms=_int_in_range(
                data.get(SpeechSettingsKeys.TTS_PAUSE_MS, defaults.tts_pause_ms),
                min_value=0,
                max_value=2000,
                default=defaults.tts_pause_ms,
            ),
            tts_trigger_pause_ms=_int_in_range(
                data.get(
                    SpeechSettingsKeys.TTS_TRIGGER_PAUSE_MS,
                    defaults.tts_trigger_pause_ms,
                ),
                min_value=0,
                max_value=4000,
                default=defaults.tts_trigger_pause_ms,
            ),
            tts_lead_in_ms=_int_in_range(
                data.get(SpeechSettingsKeys.TTS_LEAD_IN_MS, defaults.tts_lead_in_ms),
                min_value=0,
                max_value=2000,
                default=defaults.tts_lead_in_ms,
            ),
            tts_start_trigger=str(
                data.get(SpeechSettingsKeys.TTS_START_TRIGGER, defaults.tts_start_trigger)
                or ""
            ).strip(),
            tts_pause_triggers=str(
                data.get(
                    SpeechSettingsKeys.TTS_PAUSE_TRIGGERS,
                    defaults.tts_pause_triggers,
                )
                or ""
            ).strip(),
            chat_tts_mode=chat_tts_mode,
        )


@dataclass(slots=True)
class AppSettings:
    """User-facing high-level settings."""

    theme_id: str = "dark"
    autosave_enabled: bool = True
    user_mode: str = default_user_mode()


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
