"""Markdown repair task methods for ``LLMManager``."""
from __future__ import annotations

import threading
from typing import Any, Callable


def fix_markdown_chunk_sync(
    self,
    markdown_chunk: str,
    stop_requested: Callable[[], bool] | None = None,
) -> tuple[str, dict[str, Any]]:
    """
    Repair Markdown formatting for one chunk while preserving content meaning.

    The call is synchronous and should only be used when the streaming worker
    is idle.
    """
    source = str(markdown_chunk or "")
    if not source.strip():
        return source, {
            "applied": False,
            "reason": "empty_input",
        }
    if not self.is_model_loaded():
        return source, {
            "applied": False,
            "reason": "model_not_loaded",
        }
    if self.worker.isRunning():
        return source, {
            "applied": False,
            "reason": "model_busy",
        }

    model = self.worker._model
    if model is None:
        return source, {
            "applied": False,
            "reason": "model_missing",
        }
    if self._log:
        caller_tid = int(threading.get_ident())
        model_tid = int(getattr(self.worker, "_model_thread_ident", 0) or 0)
        self._log.debug(
            "LLM",
            (
                "[Import-Markdown-Fix] call context"
                f"  |  caller_tid={caller_tid}"
                f"  model_tid={model_tid}"
                f"  same_thread={int(caller_tid == model_tid and model_tid != 0)}"
                f"  worker_running={int(bool(self.worker.isRunning()))}"
            ),
        )

    def _stop_requested() -> bool:
        if stop_requested is None:
            return False
        try:
            return bool(stop_requested())
        except Exception:
            return False

    system_prompt = (
        "Du bist ein strenger Markdown-Repair-Assistent.\n"
        "Du darfst NUR Markdown-Strukturfehler korrigieren.\n"
        "Erlaubt: Ueberschriftensyntax, Tabellen-Trennzeilen, Listenmarker, "
        "Codeblock-Zaeune, kaputte Zeilenumbrueche durch OCR "
        "(Worttrennung am Zeilenende, gesplittete Absatze).\n"
        "Fuehre Korrekturen IMMER direkt im Text aus, niemals als Markierung.\n"
        "Verboten sind insbesondere Korrektur-Annotationen wie *Teilwort*, "
        "_Teilwort_, [sic], Kommentare oder Erklaerungen.\n"
        "Wenn ein Wort fehlerhaft getrennt ist, gib das korrekte Wort direkt aus "
        "(z.B. 'In nerhalb' -> 'Innerhalb').\n"
        "Ueberschriften muessen immer auf einer eigenen Zeile stehen.\n"
        "Nie eine Ueberschrift an den vorherigen oder naechsten Absatz haengen.\n"
        "Wenn eine fett markierte, nummerierte Kapitelzeile vorliegt "
        "(z.B. '**5.2.4 Titel** ...'), bevorzuge eine echte "
        "Markdown-Ueberschrift statt Fettdruck.\n"
        "Setze den Absatztext danach in die naechste Zeile.\n"
        "Bewertungsskalen oder Legenden (z.B. '**0 P.** **1 P.** **2 P.**' "
        "oder Prozentlisten) sind KEINE Ueberschriften.\n"
        "Erzeuge neue Markdown-Ueberschriften nur bei klaren Kapitelzeilen "
        "wie '5.2.4 Titel' oder '3 Ergebnisse'.\n"
        "Bei Binnenstern-Schreibungen in Woertern (z.B. Kuenstler*innen) "
        "muss der Stern in Markdown escaped werden (Kuenstler\\*innen).\n"
        "Verboten: inhaltliche Umschreibungen, neue Fakten, Loeschung relevanter "
        "Aussagen, Umstellung von Satzinhalten, Stilverbesserungen.\n"
        "Zahlen, Namen, Zeitangaben, Reihenfolge und Aussagegehalt muessen "
        "erhalten bleiben.\n"
        "Wenn unsicher: Original unveraendert lassen."
    )
    source_tokens = max(1, self._count_tokens(source))
    max_out_tokens = max(280, min(2200, int(source_tokens * 2.1)))
    max_attempts = 3
    last_raw_full = ""
    last_error = ""

    for attempt in range(1, max_attempts + 1):
        retry_hint = ""
        if attempt >= 2:
            retry_hint = (
                "\nWICHTIG: Deine Antwort MUSS exakt ein <fixed_md>...</fixed_md> "
                "enthalten. Keine weiteren Tags, kein Fliesstext ausserhalb."
            )
        user_prompt = (
            "Repariere den folgenden Markdown-Block.\n"
            "Gib NUR den korrigierten Markdown-Block zurueck, eingeschlossen in:\n"
            "<fixed_md>\n"
            "...markdown...\n"
            "</fixed_md>\n"
            "Kein weiterer Text."
            f"{retry_hint}\n\n"
            "<markdown_input>\n"
            f"{source}\n"
            "</markdown_input>"
        )
        prompt = (
            "<|system|>\n"
            f"{system_prompt}\n"
            "<|user|>\n"
            f"{user_prompt}\n"
            "<|assistant|>\n"
        )
        window_err = self._check_prompt_window(prompt, max_out_tokens)
        if window_err:
            if self._log:
                self._log.error("LLM", f"Import markdown-fix context too large: {window_err}")
            self._log_llm_io(
                f"Import-Markdown-Fix#{attempt}",
                prompt,
                error=window_err,
            )
            return source, {
                "applied": False,
                "reason": "context_too_large",
                "error": window_err,
            }
        if _stop_requested():
            return source, {
                "applied": False,
                "reason": "stopped",
                "attempt": attempt,
            }
        try:
            # ``stream=False`` can monopolize the interpreter for large chunks and
            # make the GUI appear frozen. Stream incrementally so the event loop
            # keeps getting scheduling opportunities between token fetches.
            result = model(
                prompt,
                max_tokens=max_out_tokens,
                temperature=0.05,
                top_p=0.9,
                repeat_penalty=1.0,
                stop=["<|"],
                stream=True,
            )
            parts: list[str] = []
            stopped = False
            for event in result:
                if _stop_requested():
                    stopped = True
                    break
                token = str(event["choices"][0].get("text", "") or "")
                if token:
                    parts.append(token)
            raw_full = "".join(parts)
            last_raw_full = raw_full
            if stopped:
                self._log_llm_io(
                    f"Import-Markdown-Fix#{attempt}",
                    prompt,
                    output=raw_full,
                    error="stopped",
                )
                return source, {
                    "applied": False,
                    "reason": "stopped",
                    "attempt": attempt,
                    "raw_len": len(raw_full),
                }
            self._log_llm_io(f"Import-Markdown-Fix#{attempt}", prompt, raw_full)
            payload, tag_found = self._extract_tagged_payload_with_flag(
                raw_full,
                "fixed_md",
            )
            if tag_found and payload.strip():
                return payload, {
                    "applied": True,
                    "reason": "ok",
                    "attempt": attempt,
                    "tag_found": True,
                    "raw_len": len(raw_full),
                    "out_len": len(payload),
                }
        except Exception as exc:
            last_error = str(exc)
            self._log_llm_io(
                f"Import-Markdown-Fix#{attempt}",
                prompt,
                error=last_error,
            )
            if self._log:
                self._log.error("LLM", f"Import markdown-fix failed (attempt {attempt}): {exc}")

    # After 3 failed tagged attempts, use full output as a last fallback.
    fallback = str(last_raw_full or "").strip()
    if fallback:
        return fallback, {
            "applied": True,
            "reason": "fallback_raw_output",
            "attempt": max_attempts,
            "tag_found": False,
            "raw_len": len(last_raw_full),
            "out_len": len(fallback),
        }

    if last_error:
        return source, {
            "applied": False,
            "reason": "exception",
            "error": last_error,
        }
    return source, {
        "applied": False,
        "reason": "empty_output",
        "raw_preview": str(last_raw_full or "")[:220],
    }
