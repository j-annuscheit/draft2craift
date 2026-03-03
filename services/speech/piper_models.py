"""Local Piper model discovery + optional first-run download helpers."""
from __future__ import annotations

from functools import lru_cache
import json
import os
from pathlib import Path
import re
import shutil
from typing import Callable
from urllib.error import URLError
from urllib.request import urlopen


StatusFn = Callable[[str], None] | None


_QUALITY_WEIGHTS: tuple[tuple[str, int], ...] = (
    ("high", 50),
    ("medium", 30),
    ("low", 15),
    ("x_low", 5),
)

_DEFAULT_VOICE_BY_LANGUAGE: dict[str, tuple[str, ...]] = {
    "de": ("de_DE-thorsten-high", "de_DE-thorsten-medium"),
    "en": ("en_US-lessac-high", "en_US-lessac-medium"),
    "fr": ("fr_FR-siwis-medium",),
    "es": ("es_ES-davefx-medium",),
    "it": ("it_IT-riccardo-x_low",),
    "nl": ("nl_NL-mls_5809-low",),
    "pl": ("pl_PL-darkman-medium",),
    "cs": ("cs_CZ-jirka-medium", "cs_CZ-jirka-low"),
    "uk": ("uk_UA-lada-x_low",),
}
_URL_FORMAT = (
    "https://huggingface.co/rhasspy/piper-voices/resolve/main/"
    "{lang_family}/{lang_code}/{voice_name}/{voice_quality}/"
    "{lang_code}-{voice_name}-{voice_quality}{extension}?download=true"
)
_VOICE_PATTERN = re.compile(
    r"^(?P<lang_family>[^-]+)_(?P<lang_region>[^-]+)-"
    r"(?P<voice_name>[^-]+)-(?P<voice_quality>.+)$"
)
_VOICES_JSON_URL = (
    "https://huggingface.co/rhasspy/piper-voices/resolve/main/"
    "voices.json?download=true"
)


def list_local_piper_models(language: str = "") -> list[str]:
    """List local .onnx Piper models, optionally filtered by language."""
    lang = _normalize_language(language)
    candidates = _discover_models()
    scored: list[tuple[int, str]] = []
    for path in candidates:
        score = _model_score(path, lang)
        if lang and score < 0:
            continue
        scored.append((score, str(path)))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [value for _score, value in scored]


def best_local_piper_model(language: str = "") -> str:
    """Return best matching local Piper model path, or empty string."""
    models = list_local_piper_models(language=language)
    if not models:
        return ""
    return models[0]


def ensure_local_piper_model(
    language: str = "",
    *,
    status: StatusFn = None,
) -> str:
    """
    Ensure at least one local Piper model exists for the language.

    Behavior:
    - Uses existing local model if found.
    - If none exists and auto-download is enabled, downloads a default voice
      once into the local models directory.
    """
    existing = best_local_piper_model(language=language)
    if existing:
        return existing

    if not is_auto_download_enabled():
        return ""

    download_dir = default_download_dir()
    download_dir.mkdir(parents=True, exist_ok=True)

    last_error = ""
    tried: set[str] = set()
    for voice in _default_voice_candidates(language):
        tried.add(voice)
        _emit_status(status, f"Piper: lade Modell ({voice})...")
        try:
            _download_voice(voice=voice, download_dir=download_dir)
        except Exception as exc:
            last_error = str(exc)
            continue

        refresh_local_piper_models_cache()
        exact = download_dir / f"{voice}.onnx"
        if exact.exists():
            return str(exact.resolve())
        discovered = best_local_piper_model(language=language)
        if discovered:
            return discovered

    for voice in _online_voice_candidates(language):
        if voice in tried:
            continue
        _emit_status(status, f"Piper: lade Modell ({voice})...")
        try:
            _download_voice(voice=voice, download_dir=download_dir)
        except Exception as exc:
            last_error = str(exc)
            continue

        refresh_local_piper_models_cache()
        exact = download_dir / f"{voice}.onnx"
        if exact.exists():
            return str(exact.resolve())
        discovered = best_local_piper_model(language=language)
        if discovered:
            return discovered

    if last_error:
        raise RuntimeError(
            "Automatischer Piper-Download fehlgeschlagen: "
            f"{last_error}"
        )
    return ""


def is_auto_download_enabled() -> bool:
    """Return whether first-run Piper auto-download is enabled."""
    raw = str(os.getenv("DRAFT2CRAIFT_TTS_AUTO_DOWNLOAD", "1")).strip().lower()
    return raw not in {"0", "false", "no", "off"}


def default_download_dir() -> Path:
    """Return preferred local directory for downloaded Piper models."""
    env_raw = str(os.getenv("DRAFT2CRAIFT_PIPER_MODELS_DIR", "")).strip()
    if env_raw:
        first = env_raw.split(os.pathsep)[0].strip()
        if first:
            return Path(first).expanduser()
    return (Path.cwd() / "models" / "piper").resolve()


def refresh_local_piper_models_cache():
    """Force rescan on next lookup."""
    _discover_models.cache_clear()


def guess_language_from_model_path(path: str) -> str:
    """Infer language code from model filename/path when possible."""
    pth = Path(str(path or "")).name.casefold()
    if not pth:
        return ""
    match = re.match(r"^([a-z]{2})(?:[_-][a-z]{2})?[_-]", pth)
    if match:
        return match.group(1)
    fallback = re.match(r"^([a-z]{2})[_-]?", pth)
    if fallback:
        return fallback.group(1)
    return ""


@lru_cache(maxsize=1)
def _discover_models() -> tuple[Path, ...]:
    paths: list[Path] = []
    for root in _candidate_roots():
        if not root.exists() or not root.is_dir():
            continue
        try:
            for model in root.rglob("*.onnx"):
                if model.is_file():
                    paths.append(model.resolve())
        except Exception:
            continue
    unique: dict[str, Path] = {}
    for path in paths:
        unique[str(path)] = path
    return tuple(unique.values())


def _candidate_roots() -> list[Path]:
    roots: list[Path] = []
    env_raw = str(os.getenv("DRAFT2CRAIFT_PIPER_MODELS_DIR", "")).strip()
    if env_raw:
        for part in env_raw.split(os.pathsep):
            item = part.strip()
            if item:
                roots.append(Path(item).expanduser())

    roots.extend(
        [
            default_download_dir(),
            Path.home() / ".local" / "share" / "piper",
            Path.home() / ".local" / "share" / "piper" / "voices",
            Path.home() / ".cache" / "piper",
        ]
    )
    out: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(root)
        if key in seen:
            continue
        seen.add(key)
        out.append(root)
    return out


def _normalize_language(language: str) -> str:
    clean = str(language or "").strip().casefold()
    if not clean:
        return ""
    if clean in {"auto", "*"}:
        return ""
    return clean[:2]


def _model_score(path: Path, lang: str) -> int:
    name = path.name.casefold()
    inferred = guess_language_from_model_path(name)
    if lang and inferred and inferred != lang:
        return -1
    score = 0
    if lang and inferred == lang:
        score += 100
    elif lang and not inferred:
        score += 10
    for marker, weight in _QUALITY_WEIGHTS:
        if marker in name:
            score += weight
            break
    if "onnx" in name:
        score += 2
    return score


def _default_voice_candidates(language: str) -> tuple[str, ...]:
    env_voice = str(os.getenv("DRAFT2CRAIFT_PIPER_DEFAULT_VOICE", "")).strip()
    if env_voice:
        return (env_voice,)
    lang = _normalize_language(language)
    if not lang:
        lang = "de"
    picks = _DEFAULT_VOICE_BY_LANGUAGE.get(lang)
    if picks:
        return picks
    return _DEFAULT_VOICE_BY_LANGUAGE.get("de", ("de_DE-thorsten-high",))


def _online_voice_candidates(language: str) -> tuple[str, ...]:
    lang = _normalize_language(language) or "de"
    voices = _fetch_online_voices_index()
    if not voices:
        return ()

    scored: list[tuple[int, str]] = []
    for voice in voices:
        voice_low = voice.casefold()
        if not voice_low.startswith(f"{lang}_"):
            continue
        quality_score = 0
        if voice_low.endswith("-high"):
            quality_score = 100
        elif voice_low.endswith("-medium"):
            quality_score = 70
        elif voice_low.endswith("-low"):
            quality_score = 40
        elif voice_low.endswith("-x_low"):
            quality_score = 20
        scored.append((quality_score, voice))

    if not scored:
        return ()
    scored.sort(key=lambda item: item[0], reverse=True)
    return tuple(voice for _score, voice in scored[:8])


def _fetch_online_voices_index() -> tuple[str, ...]:
    try:
        try:
            from piper import download_voices  # type: ignore

            url = str(
                getattr(download_voices, "VOICES_JSON", _VOICES_JSON_URL)
            ).strip() or _VOICES_JSON_URL
        except Exception:
            url = _VOICES_JSON_URL

        with urlopen(url, timeout=20) as response:
            payload = json.load(response)
        if not isinstance(payload, dict):
            return ()
        keys = [
            str(key).strip()
            for key in payload.keys()
            if str(key or "").strip()
        ]
        return tuple(sorted(keys))
    except Exception:
        return ()


def _download_voice(voice: str, download_dir: Path):
    # Prefer Piper's own downloader when available.
    try:
        from piper import download_voices  # type: ignore

        if hasattr(download_voices, "download_voice"):
            download_voices.download_voice(
                voice,
                download_dir,
                force_redownload=False,
            )
            return
    except Exception:
        pass
    _download_voice_via_http(voice=voice, download_dir=download_dir)


def _download_voice_via_http(voice: str, download_dir: Path):
    voice_match = _VOICE_PATTERN.match(str(voice or "").strip())
    if not voice_match:
        raise RuntimeError(
            f"Ungueltige Voice-ID '{voice}' "
            "(erwartet: xx_YY-name-quality)."
        )

    lang_family = voice_match.group("lang_family")
    lang_code = f"{lang_family}_{voice_match.group('lang_region')}"
    voice_name = voice_match.group("voice_name")
    voice_quality = voice_match.group("voice_quality")
    format_args = {
        "lang_family": lang_family,
        "lang_code": lang_code,
        "voice_name": voice_name,
        "voice_quality": voice_quality,
    }

    download_dir.mkdir(parents=True, exist_ok=True)
    for extension in (".onnx", ".onnx.json"):
        target = download_dir / f"{voice}{extension}"
        if target.exists() and target.stat().st_size > 0:
            continue
        url = _URL_FORMAT.format(extension=extension, **format_args)
        try:
            with urlopen(url, timeout=120) as response:
                with open(target, "wb") as handle:
                    shutil.copyfileobj(response, handle)
        except URLError as exc:
            raise RuntimeError(
                f"Download fehlgeschlagen ({url}): {exc}"
            ) from exc


def _emit_status(status: StatusFn, message: str):
    if status is None:
        return
    try:
        status(str(message or "").strip())
    except Exception:
        pass
