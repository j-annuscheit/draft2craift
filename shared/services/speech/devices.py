"""Helpers for listing audio input/output devices."""
from __future__ import annotations

import os
import shutil
import subprocess


def list_input_devices(backend: str = "auto") -> list[str]:
    """Return device IDs/names suitable for microphone capture."""
    mode = str(backend or "auto").strip().lower()
    if mode == "sounddevice":
        return _list_sounddevice_inputs()
    if mode == "arecord":
        return _list_arecord_inputs()
    if os.name != "nt" and shutil.which("arecord"):
        return _list_arecord_inputs()
    result = _list_sounddevice_inputs()
    if result:
        return result
    return _list_arecord_inputs()


def list_output_devices() -> list[str]:
    """Return device IDs/names suitable for playback."""
    result = _list_aplay_outputs()
    if result:
        return result
    return ["default"]


def _list_arecord_inputs() -> list[str]:
    known = _read_alsa_devices(["arecord", "-L"])
    preferred = ["pipewire", "pulse", "default", "sysdefault"]
    out: list[str] = []
    for item in preferred:
        if item not in out:
            out.append(item)
    for item in known:
        low = item.casefold()
        if low in {"null"}:
            continue
        if any(
            tag in low
            for tag in ("hdmi", "spdif", "iec958", "surround", "rear")
        ):
            continue
        if item not in out:
            out.append(item)
    if "plughw:2,0" not in out:
        out.append("plughw:2,0")
    if "plughw:1,0" not in out:
        out.append("plughw:1,0")
    if "plughw:0,0" not in out:
        out.append("plughw:0,0")
    return out


def _list_aplay_outputs() -> list[str]:
    known = _read_alsa_devices(["aplay", "-L"])
    preferred = ["pipewire", "pulse", "default", "sysdefault"]
    out: list[str] = []
    for item in preferred:
        if item not in out:
            out.append(item)
    for item in known:
        low = item.casefold()
        if low in {"null"}:
            continue
        if item not in out:
            out.append(item)
    return out or ["default"]


def _list_sounddevice_inputs() -> list[str]:
    try:
        import sounddevice as sd  # type: ignore
    except Exception:
        return []

    devices: list[str] = []
    try:
        all_devices = sd.query_devices()
    except Exception:
        return []
    for idx, dev in enumerate(all_devices):
        try:
            max_in = int(dev.get("max_input_channels", 0) or 0)
        except Exception:
            max_in = 0
        if max_in <= 0:
            continue
        name = str(dev.get("name", "") or "").strip()
        if not name:
            name = f"Device {idx}"
        devices.append(f"{idx}:{name}")
    return devices


def _read_alsa_devices(cmd: list[str]) -> list[str]:
    if not shutil.which(cmd[0]):
        return []
    try:
        proc = subprocess.run(
            cmd,
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
        if not line:
            continue
        if line[0].isspace():
            continue
        name = line.strip()
        if name and name not in out:
            out.append(name)
    return out
