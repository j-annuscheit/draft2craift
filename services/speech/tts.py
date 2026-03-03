"""Non-blocking text-to-speech manager with simple backend fallbacks."""
from __future__ import annotations

from collections import deque
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
import time
import wave

from PySide6.QtCore import QObject, QThread, Signal

from .piper_models import best_local_piper_model, ensure_local_piper_model
from .settings import SpeechSettings

_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_MARKDOWN_PREFIX_RE = re.compile(
    r"^\s{0,3}(?:#{1,6}\s+|>\s*|[-*+]\s+|\d+[.)]\s+)"
)
_TRAILING_PUNCT_RE = re.compile(r"[.!?;:]\Z")
_WHITESPACE_RE = re.compile(r"\s+")
_SPEECH_SPLIT_RE = re.compile(r"\n{2,}|(?<=[.!?;:])\s+")


class _SpeechWorker(QThread):
    """Speak one text chunk in a background thread."""

    status = Signal(str)
    finished_ok = Signal()
    failed = Signal(str)

    def __init__(
        self,
        text: str,
        settings: SpeechSettings,
        pause_after_ms: int = 0,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self._text = str(text or "").strip()
        self._settings = SpeechSettings.from_dict(settings.to_dict())
        self._pause_after_ms = max(0, int(pause_after_ms))
        self._stop_requested = threading.Event()
        self._process: subprocess.Popen | None = None
        self._engine = None
        self._lock = threading.Lock()

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
                "--sentence_silence" in err_text
                and "unrecognized arguments" in err_text
            ):
                # Compatibility fallback for older piper CLI versions.
                cmd_compat = list(cmd)
                if "--sentence_silence" in cmd_compat:
                    idx = cmd_compat.index("--sentence_silence")
                    del cmd_compat[idx : idx + 2]
                self._run_process(
                    cmd=cmd_compat,
                    stdin_text=f"{text}\n",
                )
                return
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


class TextToSpeechManager(QObject):
    """Queue-based TTS manager used by GUI interactions."""

    status = Signal(str)
    error = Signal(str)
    speaking_changed = Signal(bool)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._settings = SpeechSettings()
        self._queue: deque[tuple[str, int]] = deque()
        self._worker: _SpeechWorker | None = None
        self._speaking = False

    def is_speaking(self) -> bool:
        return bool(self._speaking)

    def update_settings(self, settings: SpeechSettings):
        self._settings = SpeechSettings.from_dict(settings.to_dict())

    def speak(self, text: str, interrupt: bool = False):
        payload = str(text or "").strip()
        if not payload:
            return
        backend = _resolve_tts_backend(self._settings)
        jobs = _build_speech_jobs(
            payload,
            pause_ms=self._settings.tts_pause_ms,
            backend=backend,
            pause_triggers=self._settings.tts_pause_triggers,
        )
        if not jobs:
            return
        if interrupt:
            self.stop()
        self._queue.extend(jobs)
        self._pump()

    def stop(self):
        self._queue.clear()
        worker = self._worker
        if worker is not None and worker.isRunning():
            worker.request_stop()
            worker.wait(1500)
        self._worker = None
        self._set_speaking(False)

    def _pump(self):
        if self._worker is not None and self._worker.isRunning():
            return
        if not self._queue:
            return
        text, pause_after_ms = self._queue.popleft()
        worker = _SpeechWorker(
            text=text,
            settings=self._settings,
            pause_after_ms=pause_after_ms,
            parent=self,
        )
        worker.status.connect(self.status.emit)
        worker.failed.connect(self._on_worker_failed)
        worker.finished.connect(self._on_worker_finished)
        self._worker = worker
        if not self._speaking:
            self._set_speaking(True)
            self.status.emit("TTS startet…")
        worker.start()

    def _on_worker_failed(self, message: str):
        self._queue.clear()
        msg = str(message or "").strip() or "Unbekannter TTS-Fehler."
        self.error.emit(msg)

    def _on_worker_finished(self):
        self._worker = None
        if self._queue:
            self._pump()
            return
        if self._speaking:
            self.status.emit("TTS fertig.")
        self._set_speaking(False)

    def _set_speaking(self, speaking: bool):
        next_state = bool(speaking)
        if self._speaking == next_state:
            return
        self._speaking = next_state
        self.speaking_changed.emit(self._speaking)


def _build_speech_jobs(
    text: str,
    *,
    pause_ms: int,
    backend: str,
    pause_triggers: str = "",
) -> list[tuple[str, int]]:
    # Keep exactly one queue job to avoid playback restarts that can clip
    # leading words on some audio setups.
    _ = (pause_ms, backend, pause_triggers)
    normalized = _normalize_text_for_tts(text)
    if not normalized:
        return []
    merged = " ".join(_split_text_units(normalized)).strip()
    if not merged:
        return []
    return [(merged, 0)]


def _parse_pause_triggers(raw: str) -> list[str]:
    text = str(raw or "").replace("\r", "")
    if not text.strip():
        return []

    pieces = text.split("|") if "|" in text else text.splitlines()
    parsed: list[str] = []
    seen: set[str] = set()
    for piece in pieces:
        token = str(piece or "")
        if not token:
            continue
        if token.strip() == "":
            continue

        # Preserve spaced hyphen trigger intentionally as " - ".
        if token.strip() == "-" and (" " in token):
            token = " - "
        else:
            token = token.strip()
        if not token:
            continue
        if token in seen:
            continue
        seen.add(token)
        parsed.append(token)

    parsed.sort(key=len, reverse=True)
    return parsed


def _split_for_trigger_pauses(text: str, triggers: list[str]) -> list[str]:
    return _split_unit_on_pause_triggers(text, triggers)


def _split_unit_on_pause_triggers(
    unit: str,
    triggers: list[str],
) -> list[str]:
    text = str(unit or "").strip()
    if not text:
        return []
    if not triggers:
        return [text]

    chunks: list[str] = []
    cursor = 0
    limit = len(text)
    while cursor < limit:
        hit_index = -1
        hit_token = ""
        for token in triggers:
            idx = text.find(token, cursor)
            if idx < 0:
                continue
            if (
                hit_index < 0
                or idx < hit_index
                or (idx == hit_index and len(token) > len(hit_token))
            ):
                hit_index = idx
                hit_token = token

        if hit_index < 0:
            tail = text[cursor:].strip()
            if tail:
                chunks.append(tail)
            break

        end = hit_index + len(hit_token)
        part = text[cursor:end].strip()
        if part:
            chunks.append(part)
        cursor = end

    return chunks or [text]


def _normalize_text_for_tts(text: str) -> str:
    raw = (
        str(text or "")
        .replace("\u2029", "\n")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
    )
    if not raw.strip():
        return ""

    lines: list[str] = []
    in_code_block = False
    for line in raw.split("\n"):
        clean = line.strip()
        if clean.startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue
        if not clean:
            lines.append("")
            continue

        clean = _MARKDOWN_LINK_RE.sub(r"\1", clean)
        clean = _MARKDOWN_PREFIX_RE.sub("", clean).strip()
        clean = clean.replace("`", "")
        clean = clean.replace("*", " ")
        clean = clean.replace("_", " ")
        clean = clean.strip("|")
        clean = clean.replace("|", ", ")
        clean = _WHITESPACE_RE.sub(" ", clean).strip()
        if not clean:
            continue
        if not _TRAILING_PUNCT_RE.search(clean):
            clean = f"{clean}."
        lines.append(clean)

    text_out = "\n".join(lines).strip()
    if not text_out:
        return ""
    return re.sub(r"\n{3,}", "\n\n", text_out)


def _split_text_units(text: str) -> list[str]:
    units: list[str] = []
    for part in _SPEECH_SPLIT_RE.split(text):
        clean = _WHITESPACE_RE.sub(" ", str(part or "")).strip(" ,")
        if not clean:
            continue
        if not _TRAILING_PUNCT_RE.search(clean):
            clean = f"{clean}."
        units.append(clean)
    return units


def _merge_units(
    units: list[str],
    *,
    target_chars: int,
    hard_max_chars: int,
) -> list[str]:
    chunks: list[str] = []
    current = ""
    for unit in units:
        for piece in _split_long_unit(unit, max_chars=hard_max_chars):
            if not current:
                current = piece
                continue
            proposed = f"{current} {piece}"
            if len(proposed) <= target_chars:
                current = proposed
            else:
                chunks.append(current)
                current = piece
    if current:
        chunks.append(current)
    return chunks


def _split_long_unit(unit: str, *, max_chars: int) -> list[str]:
    clean = str(unit or "").strip()
    if not clean:
        return []
    if len(clean) <= max_chars:
        return [clean]

    chunks: list[str] = []
    current = ""
    for fragment in re.split(r"(?<=,)\s+", clean):
        frag = str(fragment or "").strip()
        if not frag:
            continue
        if len(frag) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(_split_words(frag, max_chars=max_chars))
            continue
        if not current:
            current = frag
            continue
        proposed = f"{current} {frag}"
        if len(proposed) <= max_chars:
            current = proposed
        else:
            chunks.append(current)
            current = frag

    if current:
        chunks.append(current)
    return chunks or _split_words(clean, max_chars=max_chars)


def _split_words(text: str, *, max_chars: int) -> list[str]:
    words = str(text or "").split()
    if not words:
        return []

    chunks: list[str] = []
    current = ""
    for word in words:
        if not current:
            current = word
            continue
        proposed = f"{current} {word}"
        if len(proposed) <= max_chars:
            current = proposed
        else:
            chunks.append(current)
            current = word
    if current:
        chunks.append(current)
    return chunks


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


def _resolve_piper_model_path(settings: SpeechSettings) -> str:
    explicit = str(settings.tts_model_path or "").strip()
    if explicit:
        if explicit.startswith(("http://", "https://")):
            raise RuntimeError(
                "Nur lokale Piper-Modelle erlaubt. "
                "HTTP/HTTPS ist deaktiviert."
            )
        model = Path(explicit).expanduser()
        if model.exists() and model.is_file():
            return str(model.resolve())
        raise RuntimeError(f"Piper-Modell nicht gefunden: {explicit}")

    language = str(settings.tts_language or "").strip()
    model = best_local_piper_model(language)
    if model:
        return model
    return ""


def _piper_length_scale(rate_percent: int) -> float:
    # piper: lower length_scale => faster speech.
    clean_rate = max(50, min(300, int(rate_percent)))
    if clean_rate == 100:
        return 1.0
    return max(0.55, min(1.8, 100.0 / float(clean_rate)))


def _piper_lead_in_ms(settings: SpeechSettings) -> int:
    # Some output devices clip the first ~100-300ms after playback starts.
    # Add a short silent pre-roll to protect leading words.
    base = int(getattr(settings, "tts_lead_in_ms", 320) or 320)
    return max(0, min(2000, base))


def _apply_start_trigger(text: str, trigger: str) -> str:
    payload = str(text or "").strip()
    if not payload:
        return ""
    starter = _WHITESPACE_RE.sub(" ", str(trigger or "")).strip()
    if not starter:
        return payload
    if not _TRAILING_PUNCT_RE.search(starter):
        starter = f"{starter}."
    return f"{starter} {payload}".strip()


def _new_temp_wav_path() -> str:
    with tempfile.NamedTemporaryFile(
        suffix=".wav",
        delete=False,
    ) as tmp:
        return tmp.name


def _concat_wav_files(
    segment_paths: list[str],
    output_path: str,
    *,
    inter_silence_ms: int,
    guard_ms: int = 0,
):
    paths = [str(p or "").strip() for p in segment_paths if str(p or "").strip()]
    if not paths:
        raise RuntimeError("Keine Audiosegmente fuer TTS-Konkatenation vorhanden.")

    silence_ms = max(0, int(inter_silence_ms))
    with wave.open(paths[0], "rb") as first:
        channels = int(first.getnchannels())
        sample_width = int(first.getsampwidth())
        sample_rate = int(first.getframerate())
        params = first.getparams()

    if channels <= 0 or sample_width <= 0 or sample_rate <= 0:
        raise RuntimeError("Ungueltiges WAV-Format aus Piper.")

    gap_pcm = _build_inter_segment_gap_pcm(
        sample_rate=sample_rate,
        channels=channels,
        sample_width=sample_width,
        total_ms=silence_ms,
        guard_ms=max(0, int(guard_ms)),
    )

    with wave.open(output_path, "wb") as out:
        out.setparams(params)
        for idx, path in enumerate(paths):
            with wave.open(path, "rb") as src:
                if (
                    int(src.getnchannels()) != channels
                    or int(src.getsampwidth()) != sample_width
                    or int(src.getframerate()) != sample_rate
                ):
                    raise RuntimeError(
                        "Inkonsistente WAV-Parameter bei TTS-Segmenten."
                    )
                out.writeframes(src.readframes(src.getnframes()))
            if idx < (len(paths) - 1) and gap_pcm:
                out.writeframes(gap_pcm)


def _build_inter_segment_gap_pcm(
    *,
    sample_rate: int,
    channels: int,
    sample_width: int,
    total_ms: int,
    guard_ms: int,
) -> bytes:
    total = max(0, int(total_ms))
    if total <= 0:
        return b""

    guard = max(0, min(int(guard_ms), total))
    zeros_ms = total - guard

    zero_pcm = _build_silence_pcm(
        sample_rate=sample_rate,
        channels=channels,
        sample_width=sample_width,
        milliseconds=zeros_ms,
    )
    if guard <= 0:
        return zero_pcm

    guard_pcm = _build_guard_pcm(
        sample_rate=sample_rate,
        channels=channels,
        sample_width=sample_width,
        milliseconds=guard,
    )
    return zero_pcm + guard_pcm


def _build_silence_pcm(
    *,
    sample_rate: int,
    channels: int,
    sample_width: int,
    milliseconds: int,
) -> bytes:
    ms = max(0, int(milliseconds))
    if ms <= 0:
        return b""
    frames = int(round(sample_rate * (ms / 1000.0)))
    if frames <= 0:
        return b""
    return b"\x00" * (frames * channels * sample_width)


def _build_guard_pcm(
    *,
    sample_rate: int,
    channels: int,
    sample_width: int,
    milliseconds: int,
) -> bytes:
    """
    Very low-level non-zero PCM to keep audio devices "awake" right before the
    next segment starts. This avoids first-word clipping after long pure silence.
    """
    ms = max(0, int(milliseconds))
    if ms <= 0:
        return b""
    frames = int(round(sample_rate * (ms / 1000.0)))
    if frames <= 0:
        return b""

    if sample_width == 2:
        amp = 18  # ~ -65 dBFS, effectively inaudible but non-zero.
        frame_bytes = bytearray()
        sign = 1
        for i in range(frames):
            if (i % 32) == 0:
                sign *= -1
            value = amp * sign
            sample = int(value).to_bytes(
                2,
                byteorder="little",
                signed=True,
            )
            for _ in range(channels):
                frame_bytes.extend(sample)
        return bytes(frame_bytes)

    # Fallback for uncommon sample widths.
    return _build_silence_pcm(
        sample_rate=sample_rate,
        channels=channels,
        sample_width=sample_width,
        milliseconds=ms,
    )


def _prepend_wav_silence(wav_path: str, milliseconds: int):
    lead_ms = max(0, int(milliseconds))
    if lead_ms <= 0:
        return
    try:
        with wave.open(wav_path, "rb") as src:
            params = src.getparams()
            channels = int(src.getnchannels())
            sample_width = int(src.getsampwidth())
            sample_rate = int(src.getframerate())
            frames = src.readframes(src.getnframes())
    except Exception:
        return

    if channels <= 0 or sample_width <= 0 or sample_rate <= 0:
        return

    silence_frames = int(round(sample_rate * (lead_ms / 1000.0)))
    if silence_frames <= 0:
        return
    silence = b"\x00" * (silence_frames * channels * sample_width)

    try:
        with wave.open(wav_path, "wb") as dst:
            dst.setparams(params)
            dst.writeframes(silence)
            dst.writeframes(frames)
    except Exception:
        return


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
