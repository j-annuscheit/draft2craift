"""_SpeechWorker method implementations."""
from __future__ import annotations

import os
import queue
import shutil
import subprocess
import threading
import time

from shared.services.speech.piper_models import ensure_local_piper_model

from .helpers_backend import _espeak_cmd, _read_process_stderr, _spd_say_cmd, _stop_process
from .helpers_backend import _resolve_tts_backend
from .helpers_piper_audio import (
    _apply_start_trigger,
    _new_temp_wav_path,
    _piper_lead_in_ms,
    _piper_length_scale,
    _prepend_wav_silence,
    _resolve_piper_model_path,
)
from .helpers_text import _split_long_unit, _split_text_units

_PIPER_FIRST_GROUP_MAX_CHARS = 220
_PIPER_GROUP_MAX_CHARS = 420
_PIPER_GROUP_MAX_SENTENCES = 2
_PIPER_PREFETCH_QUEUE_SIZE = 4


def _has_speakable_text(text: str) -> bool:
    return any(ch.isalnum() for ch in str(text or ""))


def _is_piper_no_audio_error(message: str) -> bool:
    return "channels not specified" in str(message or "").casefold()


def _is_stop_requested(self) -> bool:
    event = getattr(self, "_stop_requested", None)
    if event is None:
        return False
    try:
        return bool(event.is_set())
    except Exception:
        return False


def _build_piper_sentence_groups(text: str) -> list[str]:
    units = [unit for unit in _split_text_units(text) if _has_speakable_text(unit)]
    if not units:
        fallback = str(text or "").strip()
        return [fallback] if _has_speakable_text(fallback) else []

    first = units[0]
    first_parts = _split_long_unit(first, max_chars=_PIPER_FIRST_GROUP_MAX_CHARS)
    if not first_parts:
        first_parts = [first]

    groups: list[str] = [first_parts[0]]
    pending_units: list[str] = first_parts[1:] + units[1:]

    current: list[str] = []
    current_chars = 0
    current_sentences = 0

    for raw_unit in pending_units:
        unit = str(raw_unit or "").strip()
        if not _has_speakable_text(unit):
            continue
        parts = _split_long_unit(unit, max_chars=_PIPER_GROUP_MAX_CHARS)
        if not parts:
            parts = [unit]

        for part in parts:
            clean = str(part or "").strip()
            if not _has_speakable_text(clean):
                continue
            if not current:
                current = [clean]
                current_chars = len(clean)
                current_sentences = 1
                continue

            next_chars = current_chars + 1 + len(clean)
            if (
                current_sentences >= _PIPER_GROUP_MAX_SENTENCES
                or next_chars > _PIPER_GROUP_MAX_CHARS
            ):
                groups.append(" ".join(current).strip())
                current = [clean]
                current_chars = len(clean)
                current_sentences = 1
                continue

            current.append(clean)
            current_chars = next_chars
            current_sentences += 1

    if current:
        groups.append(" ".join(current).strip())

    return [group for group in groups if _has_speakable_text(group)]


def request_stop(self):
    self._stop_requested.set()
    with self._lock:
        proc = self._process
        engine = self._engine
        processes = list(getattr(self, "_processes", set()))
    for active in processes:
        _stop_process(active)
    if proc is not None and not any(active is proc for active in processes):
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
    self._run_process(cmd=cmd + [text])


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

    synth_text = _apply_start_trigger(
        text,
        getattr(self._settings, "tts_start_trigger", ""),
    )
    groups = _build_piper_sentence_groups(synth_text)
    if not groups:
        self.status.emit("TTS: Kein aussprechbarer Text erkannt.")
        return

    sentence_pause_s = max(
        0.0,
        min(2.0, float(self._settings.tts_pause_ms) / 1000.0),
    )
    self._play_prefetched_piper_groups(
        groups=groups,
        model_path=model_path,
        sentence_pause_s=sentence_pause_s,
    )


def _play_prefetched_piper_groups(
    self,
    *,
    groups: list[str],
    model_path: str,
    sentence_pause_s: float,
):
    ready: queue.Queue[object] = queue.Queue(maxsize=_PIPER_PREFETCH_QUEUE_SIZE)
    sentinel = object()
    cleanup_lock = threading.Lock()
    pending_paths: set[str] = set()
    synth_error: list[Exception] = []

    def _track(path: str):
        with cleanup_lock:
            pending_paths.add(path)

    def _drop(path: str):
        with cleanup_lock:
            pending_paths.discard(path)

    def _cleanup(path: str):
        _drop(path)
        try:
            os.remove(path)
        except Exception:
            pass

    def _synth_loop():
        try:
            for group in groups:
                if self._stop_requested.is_set():
                    break
                wav_path = _new_temp_wav_path()
                _track(wav_path)
                try:
                    ok = self._synthesize_piper_to_wav(
                        text=group,
                        model_path=model_path,
                        wav_path=wav_path,
                        sentence_pause_s=sentence_pause_s,
                    )
                except Exception as exc:
                    _cleanup(wav_path)
                    if not self._stop_requested.is_set():
                        synth_error.append(exc)
                    break
                if not ok:
                    _cleanup(wav_path)
                    continue

                while not self._stop_requested.is_set():
                    try:
                        ready.put(wav_path, timeout=0.1)
                        break
                    except queue.Full:
                        continue
                else:
                    _cleanup(wav_path)
                    break
        finally:
            while True:
                try:
                    ready.put(sentinel, timeout=0.1)
                    break
                except queue.Full:
                    if self._stop_requested.is_set():
                        continue

    synth_thread = threading.Thread(
        target=_synth_loop,
        name="tts-piper-prefetch",
        daemon=True,
    )
    synth_thread.start()

    first_played = False
    try:
        while True:
            try:
                item = ready.get(timeout=0.1)
            except queue.Empty:
                if not synth_thread.is_alive():
                    break
                if self._stop_requested.is_set():
                    continue
                continue

            if item is sentinel:
                break
            wav_path = str(item)
            try:
                if not first_played:
                    _prepend_wav_silence(
                        wav_path,
                        milliseconds=_piper_lead_in_ms(self._settings),
                    )
                self._play_wav_file(wav_path)
                first_played = True
            except RuntimeError:
                if self._stop_requested.is_set():
                    break
                raise
            finally:
                _cleanup(wav_path)

        if synth_error and not self._stop_requested.is_set():
            raise synth_error[0]
        if not first_played and not self._stop_requested.is_set():
            self.status.emit("TTS: Kein Audio für den Text erzeugt.")
    finally:
        synth_thread.join(timeout=1.0)
        with cleanup_lock:
            leftovers = list(pending_paths)
        for path in leftovers:
            _cleanup(path)


def _synthesize_piper_to_wav(
    self,
    *,
    text: str,
    model_path: str,
    wav_path: str,
    sentence_pause_s: float,
) -> bool:
    if not _has_speakable_text(text):
        return False
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
        if _is_stop_requested(self):
            return False
        if _is_piper_no_audio_error(err_text):
            return False
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
    return True


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
        processes = getattr(self, "_processes", None)
        if isinstance(processes, set):
            processes.add(proc)

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
            processes = getattr(self, "_processes", None)
            if isinstance(processes, set):
                processes.discard(proc)
            if self._process is proc:
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
    "_has_speakable_text",
    "_is_piper_no_audio_error",
    "_build_piper_sentence_groups",
    "_speak_command",
    "_speak_piper",
    "_play_prefetched_piper_groups",
    "_synthesize_piper_to_wav",
    "_play_wav_file",
    "_run_process",
    "_speak_pyttsx3",
    "_wait_after_chunk",
]
