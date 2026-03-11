"""WhisperDictationWorker method implementations."""
from __future__ import annotations

from .deps import *  # noqa: F403
from shared.config.paths import app_data_dir

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
        root = (app_data_dir() / "models" / "whisper").resolve(strict=False)
    try:
        root.mkdir(parents=True, exist_ok=True)
    except Exception:
        return ""
    return str(root.resolve())

__all__ = [
    "_env_flag",
    "_looks_like_path",
    "_resolve_model_reference",
    "_stt_auto_download_enabled",
    "_whisper_download_dir",
]
