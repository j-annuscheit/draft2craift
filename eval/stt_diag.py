#!/usr/bin/env python3
"""Minimal STT diagnostics for microphone + faster-whisper."""
from __future__ import annotations

import argparse
import os
import sys
import time


def _resolve_input_device(sd_mod):
    try:
        current = sd_mod.default.device
        if isinstance(current, (tuple, list)):
            dev = current[0] if current else None
        else:
            dev = current
        if isinstance(dev, int) and dev < 0:
            return None
        return dev
    except Exception:
        return None


def _parse_audio_device(value: str | None):
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    if raw.casefold() == "default":
        return None
    try:
        return int(raw)
    except ValueError:
        return raw


def _candidate_devices(sd_mod, forced_device, allow_hw: bool = False):
    if forced_device is not None:
        return [forced_device]

    candidates: list[tuple[int, int]] = []
    default_dev = _resolve_input_device(sd_mod)
    try:
        devices = sd_mod.query_devices()
    except Exception:
        return [default_dev]

    for idx, dev in enumerate(devices):
        in_ch = int(dev.get("max_input_channels", 0) or 0)
        if in_ch <= 0:
            continue
        name = str(dev.get("name", "") or "").casefold()
        score = 0
        if idx == default_dev:
            score += 30
        preferred_tags = ("pipewire", "pulse", "default", "sysdefault")
        if any(tag in name for tag in preferred_tags):
            score += 60
        if any(tag in name for tag in ("monitor", "loopback")):
            score -= 20
        if "hw:" in name and "plughw" not in name:
            if not allow_hw:
                continue
            score -= 5
        candidates.append((score, idx))

    candidates.sort(key=lambda item: item[0], reverse=True)
    ordered = [idx for _score, idx in candidates]
    result = [default_dev] + ordered
    unique = []
    seen = set()
    for dev in result:
        if dev in seen:
            continue
        seen.add(dev)
        unique.append(dev)
    return unique


def _candidate_input_channels(max_input_channels: int):
    max_in = max(0, int(max_input_channels))
    candidates = [1, 2]
    if 0 < max_in <= 8:
        candidates.append(max_in)
    if max_in >= 4:
        candidates.extend([3, 4])

    out = []
    seen = set()
    for ch in candidates:
        if ch <= 0 or ch in seen:
            continue
        if max_in > 0 and ch > max_in:
            continue
        seen.add(ch)
        out.append(ch)
    return out or [1, 2]


def _resolve_input_format(sd_mod, preferred_rate: int, device):
    candidates: list[int] = []
    max_in = 0
    try:
        info = sd_mod.query_devices(device=device, kind="input")
        default_rate = info.get("default_samplerate")
        if default_rate:
            candidates.append(int(round(float(default_rate))))
        max_in = int(info.get("max_input_channels", 0) or 0)
    except Exception:
        pass
    channel_candidates = _candidate_input_channels(max_in)

    for rate in (preferred_rate, 48000, 44100, 32000, 24000, 22050, 16000):
        candidates.append(int(rate))

    seen: set[int] = set()
    errors = []
    for ch in channel_candidates:
        for rate in candidates:
            if rate <= 0:
                continue
            key = (rate, ch)
            if key in seen:
                continue
            seen.add(key)
            try:
                sd_mod.check_input_settings(
                    device=device,
                    channels=ch,
                    dtype="float32",
                    samplerate=rate,
                )
                return rate, ch
            except Exception as exc:
                errors.append(f"{rate} Hz / {ch}ch: {exc}")
                continue
    detail = "\n".join(errors[:6]) if errors else "no details"
    raise RuntimeError(f"No valid input format found.\n{detail}")


def _resample_audio(np_mod, audio, src_rate: int, dst_rate: int):
    arr = audio.astype(np_mod.float32, copy=False)
    if arr.size <= 0 or int(src_rate) == int(dst_rate):
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
    return np_mod.interp(x_new, x_old, arr).astype(np_mod.float32, copy=False)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Microphone + Whisper diagnostics."
    )
    parser.add_argument("--seconds", type=float, default=4.0)
    parser.add_argument(
        "--model",
        default="base",
        help="faster-whisper model size",
    )
    parser.add_argument("--language", default="de")
    parser.add_argument("--target-rate", type=int, default=16000)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--compute-type", default="int8")
    parser.add_argument(
        "--audio-device",
        default="",
        help="Input device index/name (empty = auto)",
    )
    parser.add_argument(
        "--probe-inputs",
        action="store_true",
        help="Probe all candidate input devices and print RMS/peak.",
    )
    parser.add_argument(
        "--allow-hw",
        action="store_true",
        help="Also probe direct ALSA hw:* devices (may be unstable).",
    )
    args = parser.parse_args()

    print("== STT Diagnostics ==")
    print("python:", sys.executable)

    try:
        os.environ.setdefault("PA_ALSA_PLUGHW", "1")
        import numpy as np  # type: ignore
    except Exception as exc:
        print("ERROR: numpy import failed:", repr(exc))
        return 2
    try:
        import sounddevice as sd  # type: ignore
    except Exception as exc:
        print("ERROR: sounddevice import failed:", repr(exc))
        return 2

    print("sounddevice:", getattr(sd, "__version__", "?"))
    try:
        devices = sd.query_devices()
    except Exception as exc:
        print("ERROR: query_devices failed:", repr(exc))
        return 2
    print("audio devices:", len(devices))
    for i, dev in enumerate(devices[:12]):
        print(
            f"[{i}] {dev['name']} | in={dev['max_input_channels']} "
            f"out={dev['max_output_channels']} sr={dev['default_samplerate']}"
        )
    if len(devices) > 12:
        print("...")

    forced_audio_device = _parse_audio_device(args.audio_device)
    print("default input device:", _resolve_input_device(sd))
    if forced_audio_device is not None:
        print("forced input device:", forced_audio_device)

    duration = max(1.0, float(args.seconds))
    probe_devices = _candidate_devices(
        sd,
        forced_audio_device,
        allow_hw=bool(args.allow_hw),
    )
    if args.probe_inputs:
        print("probing input devices...")
        for dev in probe_devices:
            try:
                rate, channels = _resolve_input_format(
                    sd,
                    args.target_rate,
                    dev,
                )
            except Exception as exc:
                print(f"- {dev}: rate error -> {exc}")
                continue

            blocks: list = []

            def _probe_cb(indata, _frames, _time_info, _status):
                blocks.append(indata.copy())

            try:
                with sd.InputStream(
                    samplerate=rate,
                    device=dev,
                    channels=channels,
                    dtype="float32",
                    callback=_probe_cb,
                    blocksize=max(512, int(rate * 0.25)),
                ):
                    time.sleep(duration)
            except Exception as exc:
                print(f"- {dev} @ {rate} Hz: stream error -> {exc}")
                continue

            if not blocks:
                print(f"- {dev} @ {rate} Hz: no blocks")
                continue

            arr = np.concatenate(
                [b[:, 0] if b.ndim == 2 else b for b in blocks]
            )
            rms = float(np.sqrt(np.mean(np.square(arr)))) if arr.size else 0.0
            peak = float(np.max(np.abs(arr))) if arr.size else 0.0
            print(
                f"- {dev} @ {rate} Hz: "
                f"{channels}ch samples={int(arr.size)} "
                f"rms={rms:.6f} peak={peak:.6f}"
            )
        return 0

    chosen_device = None
    chosen_rate = None
    chosen_channels = None
    last_err = None
    for dev in probe_devices:
        try:
            rate, channels = _resolve_input_format(
                sd,
                args.target_rate,
                dev,
            )
            chosen_device = dev
            chosen_rate = rate
            chosen_channels = channels
            break
        except Exception as exc:
            last_err = exc
    if chosen_rate is None:
        print("ERROR: no valid input rate:", repr(last_err))
        return 2

    print("chosen input device:", chosen_device)
    print("chosen input rate:", chosen_rate)
    print("chosen input channels:", chosen_channels)

    blocks: list = []

    def _cb(indata, _frames, _time_info, status):
        if status:
            print("callback status:", status)
        blocks.append(indata.copy())

    print(f"recording {duration:.1f}s... speak now")
    try:
        with sd.InputStream(
            samplerate=chosen_rate,
            device=chosen_device,
            channels=chosen_channels or 1,
            dtype="float32",
            callback=_cb,
            blocksize=max(512, int(chosen_rate * 0.25)),
        ):
            time.sleep(duration)
    except Exception as exc:
        print("ERROR: InputStream failed:", repr(exc))
        return 2

    if not blocks:
        print("ERROR: no audio blocks captured")
        return 2

    audio = np.concatenate([b[:, 0] if b.ndim == 2 else b for b in blocks])
    rms = float(np.sqrt(np.mean(np.square(audio)))) if audio.size else 0.0
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    print("captured samples:", int(audio.size))
    print(f"rms={rms:.6f} peak={peak:.6f}")

    if rms < 0.0002 and peak < 0.002:
        print("WARN: very low signal; mic may be muted/too quiet.")

    try:
        from faster_whisper import WhisperModel  # type: ignore
    except Exception as exc:
        print("ERROR: faster-whisper import failed:", repr(exc))
        return 3

    print(
        "loading whisper model:",
        args.model,
        f"(device={args.device}, compute_type={args.compute_type})",
    )
    try:
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
        model = WhisperModel(
            args.model,
            device=args.device,
            compute_type=args.compute_type,
            local_files_only=True,
        )
    except Exception as exc:
        print("ERROR: model load failed:", repr(exc))
        return 3

    model_audio = _resample_audio(
        np,
        audio,
        int(chosen_rate),
        args.target_rate,
    )
    print("transcribing with VAD...")
    try:
        segs, _ = model.transcribe(
            model_audio,
            language=args.language or None,
            task="transcribe",
            beam_size=1,
            vad_filter=True,
            condition_on_previous_text=False,
            temperature=0.0,
        )
        text_vad = " ".join(
            str(getattr(s, "text", "") or "").strip() for s in segs
        ).strip()
    except Exception as exc:
        print("ERROR: transcribe (vad) failed:", repr(exc))
        return 3
    print("VAD text:", repr(text_vad))

    print("transcribing without VAD...")
    try:
        segs2, _ = model.transcribe(
            model_audio,
            language=args.language or None,
            task="transcribe",
            beam_size=1,
            vad_filter=False,
            condition_on_previous_text=False,
            temperature=0.0,
        )
        text_no_vad = " ".join(
            str(getattr(s, "text", "") or "").strip() for s in segs2
        ).strip()
    except Exception as exc:
        print("ERROR: transcribe (no vad) failed:", repr(exc))
        return 3
    print("NO-VAD text:", repr(text_no_vad))

    print("== DONE ==")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
