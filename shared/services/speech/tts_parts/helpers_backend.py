"""Backend selection and process helpers for TTS."""
from __future__ import annotations

import shutil
import subprocess

from shared.config.app_settings import SpeechSettings

def _resolve_tts_backend(settings: SpeechSettings) -> str:
    wanted = str(settings.tts_engine or "none").strip().lower()
    if wanted == "none":
        if shutil.which("piper"):
            return "piper"
        if _has_pyttsx3():
            return "pyttsx3"
        if shutil.which("spd-say"):
            return "spd-say"
        if shutil.which("espeak"):
            return "espeak"
        return "none"
    if wanted == "piper":
        return "piper" if shutil.which("piper") else "none"
    if wanted == "pyttsx3":
        return "pyttsx3" if _has_pyttsx3() else "none"
    if wanted == "spd-say":
        return "spd-say" if shutil.which("spd-say") else "none"
    if wanted == "espeak":
        return "espeak" if shutil.which("espeak") else "none"
    return "none"

def _has_pyttsx3() -> bool:
    try:
        import pyttsx3  # type: ignore # noqa: F401
    except Exception:
        return False
    return True

def _spd_say_cmd(settings: SpeechSettings) -> list[str]:
    rate_percent = int(max(50, min(300, settings.tts_rate)))
    # speech-dispatcher expects roughly [-100..100]
    rate = max(-100, min(100, rate_percent - 100))
    return ["spd-say", "-r", str(rate)]

def _espeak_cmd(settings: SpeechSettings) -> list[str]:
    rate_percent = int(max(50, min(300, settings.tts_rate)))
    volume_percent = int(max(0, min(100, settings.tts_volume)))
    # espeak rate default ~175 wpm.
    rate = int(175 * (rate_percent / 100.0))
    cmd = [
        "espeak",
        "-s",
        str(max(80, min(380, rate))),
        "-a",
        str(max(0, min(200, int(volume_percent * 2)))),
    ]
    voice = str(settings.tts_voice or "").strip()
    if voice:
        cmd.extend(["-v", voice])
    return cmd

def _read_process_stderr(proc: subprocess.Popen) -> str:
    try:
        if proc.stderr is None:
            return ""
        raw = proc.stderr.read()
        if isinstance(raw, bytes):
            return raw.decode("utf-8", errors="ignore").strip()
        return str(raw or "").strip()
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

__all__ = [
    "_resolve_tts_backend",
    "_has_pyttsx3",
    "_spd_say_cmd",
    "_espeak_cmd",
    "_read_process_stderr",
    "_stop_process",
]
