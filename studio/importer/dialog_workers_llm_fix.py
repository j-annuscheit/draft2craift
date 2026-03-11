"""LLM-fix batch orchestration methods for file-import dialog mixin."""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt

from .ui_constants import _STATUS_DONE, _STATUS_ERROR
from .workers import MarkdownLLMFixWorker


def _llm_fix_label_prefix(self, path: str) -> str:
    entry = self._entries.get(str(path or ""))
    name = str(getattr(entry, "name", "") or "").strip()
    return f"LLM-Fix ({name})" if name else "LLM-Fix"


def _set_llm_fix_status_for_path(
    self,
    path: str,
    text: str,
    *,
    tooltip: str = "",
    visible: bool = True,
):
    key = str(path or "").strip()
    if not key:
        return
    cache = getattr(self, "_llm_fix_status_by_path", None)
    if not isinstance(cache, dict):
        cache = {}
        setattr(self, "_llm_fix_status_by_path", cache)
    cache[key] = {
        "text": str(text or ""),
        "tooltip": str(tooltip or text or ""),
        "visible": bool(visible),
    }
    if str(getattr(self, "_current_path", "") or "").strip() != key:
        return
    self._preview_status.setText(str(text or ""))
    self._preview_status.setToolTip(str(tooltip or text or ""))
    self._preview_status.setVisible(bool(visible))


def _sync_llm_fix_status_for_current_path(self):
    key = str(getattr(self, "_current_path", "") or "").strip()
    cache = getattr(self, "_llm_fix_status_by_path", None)
    state = cache.get(key) if isinstance(cache, dict) and key else None
    if isinstance(state, dict):
        text = str(state.get("text", "") or "")
        tooltip = str(state.get("tooltip", "") or text)
        visible = bool(state.get("visible", False))
        self._preview_status.setText(text)
        self._preview_status.setToolTip(tooltip)
        self._preview_status.setVisible(visible and bool(text.strip()))
        return
    current_text = str(self._preview_status.text() or "").strip()
    if current_text.startswith("LLM-Fix") or current_text.startswith("Fix by LLM"):
        self._preview_status.setText("")
        self._preview_status.setToolTip("")
        self._preview_status.setVisible(False)


def _resolve_llm_manager(self) -> Any:
    parent = self.parent()
    while parent is not None:
        manager = getattr(parent, "llm_manager", None)
        if manager is not None:
            return manager
        parent_fn = getattr(parent, "parent", None)
        parent = parent_fn() if callable(parent_fn) else None
    return None


def _ordered_entry_paths(self) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    file_list = getattr(self, "_list", None)
    if file_list is not None:
        for idx in range(file_list.count()):
            item = file_list.item(idx)
            path = str(item.data(Qt.ItemDataRole.UserRole) or "").strip()
            if not path or path in seen or path not in self._entries:
                continue
            ordered.append(path)
            seen.add(path)
    for path in self._entries.keys():
        key = str(path or "").strip()
        if not key or key in seen:
            continue
        ordered.append(key)
        seen.add(key)
    return ordered


def _llm_fix_candidate_paths(self) -> list[str]:
    candidates: list[str] = []
    for path in self._ordered_entry_paths():
        entry = self._entries.get(path)
        if entry is None:
            continue
        if str(entry.markdown or "").strip():
            candidates.append(path)
    return candidates


def _finish_llm_fix_batch(self):
    self._llm_fix_batch_active = False
    self._llm_fix_queue = []
    self._llm_fix_total = 0
    self._llm_fix_done_count = 0
    self._update_open_button_state()
    self._refresh_llm_fix_button()


def _start_next_llm_fix_job(self, manager: Any):
    running = getattr(self, "_llm_fix_worker", None)
    if running is not None and running.isRunning():
        return

    queue = getattr(self, "_llm_fix_queue", None)
    if not isinstance(queue, list):
        queue = []
        self._llm_fix_queue = queue

    while queue:
        path = str(queue.pop(0) or "").strip()
        entry = self._entries.get(path)
        markdown = str(getattr(entry, "markdown", "") or "")
        if entry is None or not markdown.strip():
            self._llm_fix_done_count = int(self._llm_fix_done_count) + 1
            continue

        running_fn = getattr(getattr(manager, "worker", None), "isRunning", None)
        if callable(running_fn) and bool(running_fn()):
            msg = f"{self._llm_fix_label_prefix(path)}: LLM beschaeftigt."
            self._set_llm_fix_status_for_path(path, msg, tooltip=msg, visible=True)
            self._finish_llm_fix_batch()
            return

        file_total = max(1, int(getattr(self, "_llm_fix_total", 1) or 1))
        file_idx = max(1, min(file_total, int(self._llm_fix_done_count) + 1))
        start_msg = (
            f"{self._llm_fix_label_prefix(path)}: "
            f"Datei {file_idx}/{file_total} startet…"
        )
        self._set_llm_fix_status_for_path(
            path,
            start_msg,
            tooltip=start_msg,
            visible=True,
        )
        self._llm_fix_path = path
        self._llm_fix_worker = MarkdownLLMFixWorker(manager, markdown, self)
        self._llm_fix_worker.progress.connect(self._on_llm_fix_progress)
        self._llm_fix_worker.done.connect(self._on_llm_fix_done)
        self._update_open_button_state()
        self._refresh_llm_fix_button()
        self._llm_fix_worker.start()
        return

    total_files = int(getattr(self, "_llm_fix_total", 0) or 0)
    done_files = min(total_files, int(getattr(self, "_llm_fix_done_count", 0) or 0))
    current = str(getattr(self, "_current_path", "") or "").strip()
    if current and total_files > 0:
        summary = f"LLM-Fix: Batch fertig ({done_files}/{total_files} Dateien)."
        self._set_llm_fix_status_for_path(
            current,
            summary,
            tooltip=summary,
            visible=True,
        )
    self._finish_llm_fix_batch()


def _refresh_llm_fix_button(self):
    btn = getattr(self, "_btn_llm_fix", None)
    if btn is None:
        return
    default_tip = (
        "Korrigiert die Markdown-Struktur fuer alle geladenen Dateien nacheinander "
        "(Ueberschriften, Tabellen, Zeilenumbrueche, OCR-Formatfehler). "
        "Inhalte sollen unveraendert bleiben."
    )
    if bool(getattr(self, "_llm_fix_batch_active", False)):
        btn.setEnabled(False)
        btn.setToolTip("Fix by LLM laeuft bereits…")
        return
    llm_worker = getattr(self, "_llm_fix_worker", None)
    if llm_worker is not None and llm_worker.isRunning():
        btn.setEnabled(False)
        btn.setToolTip("Fix by LLM laeuft bereits…")
        return

    if not self._llm_fix_candidate_paths():
        btn.setEnabled(False)
        btn.setToolTip("Zuerst Dateien konvertieren, damit Markdown vorhanden ist.")
        return

    manager = self._resolve_llm_manager()
    if manager is None:
        btn.setEnabled(False)
        btn.setToolTip("Kein LLM-Manager gefunden.")
        return
    if not bool(getattr(manager, "is_model_loaded", lambda: False)()):
        btn.setEnabled(False)
        btn.setToolTip("Bitte zuerst ein GGUF-Modell laden.")
        return
    running_fn = getattr(getattr(manager, "worker", None), "isRunning", None)
    if callable(running_fn) and bool(running_fn()):
        btn.setEnabled(False)
        btn.setToolTip("LLM ist aktuell beschaeftigt.")
        return

    btn.setEnabled(True)
    btn.setToolTip(default_tip)


def _run_llm_fix_current_markdown(self):
    if bool(getattr(self, "_llm_fix_batch_active", False)):
        return
    running = self._llm_fix_worker
    if running is not None and running.isRunning():
        return

    candidates = self._llm_fix_candidate_paths()
    if not candidates:
        path = str(getattr(self, "_current_path", "") or "").strip()
        if not path and self._entries:
            path = next(iter(self._entries.keys()))
        msg = f"{self._llm_fix_label_prefix(path)}: kein Markdown vorhanden."
        self._set_llm_fix_status_for_path(path, msg, tooltip=msg, visible=True)
        self._refresh_llm_fix_button()
        return

    manager = self._resolve_llm_manager()
    if manager is None or not bool(getattr(manager, "is_model_loaded", lambda: False)()):
        path = str(getattr(self, "_current_path", "") or "").strip() or candidates[0]
        msg = f"{self._llm_fix_label_prefix(path)}: kein Modell geladen."
        self._set_llm_fix_status_for_path(path, msg, tooltip=msg, visible=True)
        self._refresh_llm_fix_button()
        return
    running_fn = getattr(getattr(manager, "worker", None), "isRunning", None)
    if callable(running_fn) and bool(running_fn()):
        path = str(getattr(self, "_current_path", "") or "").strip() or candidates[0]
        msg = f"{self._llm_fix_label_prefix(path)}: LLM beschaeftigt."
        self._set_llm_fix_status_for_path(path, msg, tooltip=msg, visible=True)
        self._refresh_llm_fix_button()
        return

    self._llm_fix_queue = list(candidates)
    self._llm_fix_total = len(candidates)
    self._llm_fix_done_count = 0
    self._llm_fix_batch_active = True
    self._start_next_llm_fix_job(manager)


def _on_llm_fix_progress(self, done: int, total: int, info: str):
    total_safe = max(1, int(total))
    done_safe = max(0, min(int(done), total_safe))
    path = str(getattr(self, "_llm_fix_path", "") or "")
    file_total = max(1, int(getattr(self, "_llm_fix_total", 1) or 1))
    file_idx = max(1, min(file_total, int(getattr(self, "_llm_fix_done_count", 0)) + 1))
    text = (
        f"{self._llm_fix_label_prefix(path)}: "
        f"Datei {file_idx}/{file_total}, Block {done_safe}/{total_safe}"
    )
    detail = str(info or "").strip()
    self._set_llm_fix_status_for_path(
        path,
        text,
        tooltip=f"{text} ({detail})" if detail else text,
        visible=True,
    )


def _on_llm_fix_done(self, markdown: str, meta: object):
    self._llm_fix_worker = None
    path = str(getattr(self, "_llm_fix_path", "") or "")
    self._llm_fix_path = None
    entry = self._entries.get(path) if path else None
    fixed = str(markdown or "")
    if entry is not None and fixed:
        entry.markdown = fixed
        if entry.status != _STATUS_ERROR:
            entry.status = _STATUS_DONE
            self._update_list_item(path, _STATUS_DONE)
        if self._current_path == path:
            self._preview.set_markdown_text(fixed)
            if entry.is_pdf():
                self._pdf_viewer.update_markdown(fixed)

    meta_map = meta if isinstance(meta, dict) else {}
    chunks = int(meta_map.get("chunks", 0) or 0)
    processed = int(meta_map.get("processed_chunks", 0) or 0)
    changed = int(meta_map.get("changed_chunks", 0) or 0)
    unchanged = int(meta_map.get("unchanged_chunks", 0) or 0)
    rejected = int(meta_map.get("rejected_chunks", 0) or 0)
    errors = int(meta_map.get("error_chunks", 0) or 0)
    skipped = int(meta_map.get("skipped_chunks", 0) or 0)
    stopped = bool(meta_map.get("stopped", False))
    reason = str(meta_map.get("reason", "") or "")
    file_total = max(1, int(getattr(self, "_llm_fix_total", 1) or 1))
    file_idx = max(1, min(file_total, int(getattr(self, "_llm_fix_done_count", 0)) + 1))
    skipped_total = max(0, unchanged + rejected + skipped)
    skipped_breakdown = (
        f"skipped={skipped_total} "
        f"(gleich={unchanged}, fehlgeschlagen={rejected}, nicht_bearbeitet={skipped})"
    )

    if stopped:
        message = (
            f"{self._llm_fix_label_prefix(path)}: Datei {file_idx}/{file_total} "
            f"gestoppt | geaendert={changed} | {skipped_breakdown} | fehler={errors}"
        )
        detail_message = (
            f"Fix by LLM gestoppt: {processed}/{chunks} bearbeitet, "
            f"{skipped} uebersprungen."
        )
    elif chunks > 0:
        message = (
            f"{self._llm_fix_label_prefix(path)}: Datei {file_idx}/{file_total} | "
            f"geaendert={changed}/{chunks} | {skipped_breakdown} | fehler={errors}"
        )
        detail_message = (
            f"Fix by LLM fertig: {changed}/{chunks} Bloecke geaendert, "
            f"{unchanged} unveraendert, {rejected} verworfen, {errors} Fehler."
        )
    elif reason:
        message = (
            f"{self._llm_fix_label_prefix(path)}: Datei {file_idx}/{file_total} | "
            f"{reason} | {skipped_breakdown} | fehler={errors}"
        )
        detail_message = f"Fix by LLM: {reason}"
    else:
        message = (
            f"{self._llm_fix_label_prefix(path)}: Datei {file_idx}/{file_total} "
            f"beendet | geaendert={changed} | {skipped_breakdown} | fehler={errors}"
        )
        detail_message = message
    self._set_llm_fix_status_for_path(
        path,
        message,
        tooltip=detail_message,
        visible=True,
    )
    self._llm_fix_done_count = min(
        int(getattr(self, "_llm_fix_total", 0) or 0),
        int(getattr(self, "_llm_fix_done_count", 0) or 0) + 1,
    )
    manager = self._resolve_llm_manager()
    if bool(getattr(self, "_llm_fix_batch_active", False)) and manager is not None:
        self._start_next_llm_fix_job(manager)
        return
    self._finish_llm_fix_batch()

