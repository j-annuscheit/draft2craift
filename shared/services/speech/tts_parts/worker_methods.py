"""_SpeechWorker method implementations."""
from __future__ import annotations

import os
import shutil
import subprocess
import time

from shared.services.speech.piper_models import ensure_local_piper_model

from .helpers_backend import _espeak_cmd, _read_process_stderr, _spd_say_cmd, _stop_process
from .helpers_piper_audio import (
    _apply_start_trigger,
    _concat_wav_files,
    _new_temp_wav_path,
    _piper_lead_in_ms,
    _piper_length_scale,
    _prepend_wav_silence,
    _resolve_piper_model_path,
)
from .helpers_text import (
    _parse_pause_triggers,
    _split_for_trigger_pauses,
)
from .helpers_backend import _resolve_tts_backend

def request_stop(self):
    self._stop_requested.set()
    with self._lock:
        proc = self._process
        engine = self._engine
    if proc is not None:
        _stop_process(proc)
    if engine is not None:
        try:
            engine.stop()
        except Exception:
            pass

def run(self):
    if not self._text:
        self.finished_ok.emit()
        return
    try:
        backend = _resolve_tts_backend(self._settings)
        if backend == "piper":
            self._speak_piper(self._text)
        elif backend == "pyttsx3":
            self._speak_pyttsx3(self._text)
        elif backend == "spd-say":
            self._speak_command(self._text, _spd_say_cmd(self._settings))
        elif backend == "espeak":
            self._speak_command(self._text, _espeak_cmd(self._settings))
        else:
            raise RuntimeError(
                "Kein TTS-Backend verfuegbar. "
                "Installiere piper-tts oder lokale System-TTS "
                "(pyttsx3/spd-say/espeak)."
            )
        if not self._stop_requested.is_set():
            self._wait_after_chunk()
        self.finished_ok.emit()
    except Exception as exc:
        self.failed.emit(str(exc))

def _speak_command(self, text: str, cmd: list[str]):
    proc = subprocess.Popen(
        cmd + [text],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    with self._lock:
        self._process = proc
    try:
        while proc.poll() is None:
            if self._stop_requested.is_set():
                _stop_process(proc)
                break
            time.sleep(0.05)
        if proc.returncode not in (0, None):
            err = ""
            try:
                if proc.stderr is not None:
                    err = (proc.stderr.read() or "").strip()
            except Exception:
                err = ""
            raise RuntimeError(
                err or f"TTS command failed ({proc.returncode})"
            )
    finally:
        with self._lock:
            self._process = None

def _speak_piper(self, text: str):
    if not shutil.which("piper"):
        raise RuntimeError(
            "Piper CLI nicht gefunden.\n"
            "Installiere lokal mit:\n"
            "  pip install piper-tts onnxruntime"
        )
    model_path = _resolve_piper_model_path(self._settings)
    if not model_path:
        lang = str(self._settings.tts_language or "de").strip() or "de"
        self.status.emit(
            f"Piper: kein lokales Modell fuer '{lang}' gefunden. "
            "Starte Erst-Download..."
        )
        model_path = ensure_local_piper_model(
            language=lang,
            status=self.status.emit,
        )
    if not model_path:
        lang = str(self._settings.tts_language or "de").strip() or "de"
        raise RuntimeError(
            "Kein lokales Piper-Modell gefunden.\n"
            "Auto-Download war nicht erfolgreich.\n"
            "Bitte in Speech Settings ein .onnx Modell waehlen."
            f"\nSprache: {lang}"
        )

    # If a local model is present, enforce offline subprocess behavior.
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

    wav_path = _new_temp_wav_path()
    segment_paths: list[str] = []

    synth_text = _apply_start_trigger(
        text,
        getattr(self._settings, "tts_start_trigger", ""),
    )
    sentence_pause_s = max(
        0.0,
        min(2.0, float(self._settings.tts_pause_ms) / 1000.0),
    )
    trigger_pause_ms = max(
        0,
        min(4000, int(getattr(self._settings, "tts_trigger_pause_ms", 320))),
    )
    trigger_list = _parse_pause_triggers(
        getattr(self._settings, "tts_pause_triggers", ""),
    )
    if trigger_list and trigger_pause_ms > 0:
        segments = _split_for_trigger_pauses(
            synth_text,
            trigger_list,
        )
    else:
        segments = [synth_text]
    segments = [part for part in segments if str(part or "").strip()]
    if not segments:
        return

    try:
        if len(segments) == 1:
            self._synthesize_piper_to_wav(
                text=segments[0],
                model_path=model_path,
                wav_path=wav_path,
                sentence_pause_s=sentence_pause_s,
            )
        else:
            for segment in segments:
                if self._stop_requested.is_set():
                    return
                seg_path = _new_temp_wav_path()
                segment_paths.append(seg_path)
                self._synthesize_piper_to_wav(
                    text=segment,
                    model_path=model_path,
                    wav_path=seg_path,
                    sentence_pause_s=sentence_pause_s,
                )
            _concat_wav_files(
                segment_paths,
                wav_path,
                inter_silence_ms=trigger_pause_ms,
                guard_ms=min(
                    trigger_pause_ms,
                    max(80, min(450, _piper_lead_in_ms(self._settings))),
                ),
            )
        if self._stop_requested.is_set():
            return
        _prepend_wav_silence(
            wav_path,
            milliseconds=_piper_lead_in_ms(self._settings),
        )
        self._play_wav_file(wav_path)
    finally:
        try:
            os.remove(wav_path)
        except Exception:
            pass
        for seg_path in segment_paths:
            try:
                os.remove(seg_path)
            except Exception:
                continue

def _synthesize_piper_to_wav(
    self,
    *,
    text: str,
    model_path: str,
    wav_path: str,
    sentence_pause_s: float,
):
    cmd = [
        "piper",
        "--model",
        model_path,
        "--output_file",
        wav_path,
        "--length_scale",
        f"{_piper_length_scale(self._settings.tts_rate):.3f}",
    ]
    if sentence_pause_s > 0.0:
        cmd.extend(
            [
                "--sentence_silence",
                f"{sentence_pause_s:.3f}",
            ]
        )
    if self._settings.tts_speaker_id >= 0:
        cmd.extend(["--speaker", str(self._settings.tts_speaker_id)])

    try:
        self._run_process(
            cmd=cmd,
            stdin_text=f"{text}\n",
        )
    except RuntimeError as exc:
        err_text = str(exc)
        if (
            "No module named 'pathvalidate'" in err_text
            or 'No module named "pathvalidate"' in err_text
        ):
            raise RuntimeError(
                "Piper-Installation unvollstaendig: "
                "Python-Modul 'pathvalidate' fehlt.\n"
                "Installiere lokal mit:\n"
                "  pip install pathvalidate"
            ) from exc
        raise

def _play_wav_file(self, wav_path: str):
    device = str(self._settings.tts_output_device or "").strip()
    if shutil.which("aplay"):
        cmd = ["aplay", "-q"]
        if device and device != "default":
            cmd.extend(["-D", device])
        cmd.append(wav_path)
        self._run_process(cmd=cmd)
        return
    if shutil.which("paplay"):
        cmd = ["paplay"]
        if device and device != "default":
            cmd.extend(["--device", device])
        cmd.append(wav_path)
        self._run_process(cmd=cmd)
        return
    if shutil.which("ffplay"):
        cmd = [
            "ffplay",
            "-autoexit",
            "-nodisp",
            "-loglevel",
            "error",
            wav_path,
        ]
        self._run_process(cmd=cmd)
        return
    raise RuntimeError(
        "Kein lokaler Audio-Player gefunden (aplay/paplay/ffplay)."
    )

def _run_process(
    self,
    *,
    cmd: list[str],
    stdin_text: str = "",
):
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE if stdin_text else None,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    with self._lock:
        self._process = proc

    try:
        if stdin_text and proc.stdin is not None:
            try:
                proc.stdin.write(stdin_text)
                proc.stdin.flush()
            finally:
                try:
                    proc.stdin.close()
                except Exception:
                    pass

        while proc.poll() is None:
            if self._stop_requested.is_set():
                _stop_process(proc)
                break
            time.sleep(0.05)

        if proc.returncode not in (0, None):
            raise RuntimeError(
                _read_process_stderr(proc)
                or f"Prozess fehlgeschlagen ({proc.returncode})"
            )
    finally:
        with self._lock:
            self._process = None

def _speak_pyttsx3(self, text: str):
    try:
        import pyttsx3  # type: ignore
    except Exception as exc:
        raise RuntimeError(
            "TTS engine 'pyttsx3' ist nicht installiert."
        ) from exc

    engine = pyttsx3.init()
    with self._lock:
        self._engine = engine
    try:
        rate = int(175 * (float(self._settings.tts_rate) / 100.0))
        volume = max(
            0.0,
            min(1.0, float(self._settings.tts_volume) / 100.0),
        )
        engine.setProperty("rate", max(80, min(380, rate)))
        engine.setProperty("volume", volume)
        wanted_voice = str(self._settings.tts_voice or "").strip()
        if wanted_voice:
            try:
                engine.setProperty("voice", wanted_voice)
            except Exception:
                pass
        engine.say(text)
        if not self._stop_requested.is_set():
            engine.runAndWait()
    finally:
        with self._lock:
            self._engine = None

def _wait_after_chunk(self):
    if self._pause_after_ms <= 0:
        return
    remaining = self._pause_after_ms / 1000.0
    while remaining > 0.0:
        if self._stop_requested.is_set():
            return
        step = min(0.05, remaining)
        time.sleep(step)
        remaining -= step

__all__ = [
    "request_stop",
    "run",
    "_speak_command",
    "_speak_piper",
    "_synthesize_piper_to_wav",
    "_play_wav_file",
    "_run_process",
    "_speak_pyttsx3",
    "_wait_after_chunk",
]
