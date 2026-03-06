"""Chat dock orchestration for model load, chat and fact-check flows."""
from __future__ import annotations

from difflib import SequenceMatcher
from typing import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDockWidget,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from core.user_modes import USER_MODE_PLUS, mode_rank, normalize_user_mode
from services.llm.manager import (
    CANVAS_REWRITE_CLOSE,
    CANVAS_REWRITE_OPEN,
    GROUNDING_INSUFFICIENT_MESSAGE,
    LLMManager,
)
from services.feedback.service import FeedbackService
from features.canvas.structured_graph import contains_structured_graph

from .context_panel import ContextSelectorPanel
from .factcheck_pipeline import FactCheckPipelineMixin
from .history import ChatHistoryWidget
from .model_panel import ModelLoadPanel
from .rewrite import extract_canvas_rewrite
from .styles import BTN_DANGER, BTN_NEUTRAL, BTN_PRIMARY, CTX_CB_STYLE


class ChatDock(FactCheckPipelineMixin, QDockWidget):
    """
    AI Chat Dock.

    ``context_getter`` must return:
    ``{file_contents, rag_results, selected_text, grounding_required,
    grounding_has_sources}``.
    """

    read_aloud_requested = Signal(str)
    read_aloud_stop_requested = Signal()
    tts_mode_changed = Signal(str)

    def __init__(self, llm_manager: LLMManager, parent=None):
        super().__init__("AI Chat", parent)
        self.llm = llm_manager
        self._user_mode = USER_MODE_PLUS
        self._context_getter: Callable[[], dict] | None = None
        self._canvas_selection_getter: Callable[[], str] | None = None
        self._selection_apply_handler: (
            Callable[[str, str, tuple[int, int] | None], tuple[bool, str]] | None
        ) = None
        self._fact_result_handler: Callable[[str, str], tuple[bool, str]] | None = None
        self._glossary_request_handler: (
            Callable[[dict, Callable[[bool, str], None]], tuple[bool, str]] | None
        ) = None
        self._mindmap_request_handler: (
            Callable[
                [dict, str, str, Callable[[bool, str], None]],
                tuple[bool, str],
            ]
            | None
        ) = None

        self._pending_apply_to_canvas = False
        self._pending_selected_text = ""
        self._pending_selected_span: tuple[int, int] | None = None
        self._pending_apply_retry_count = 0
        self._pending_apply_retry_limit = 1
        self._pending_apply_context: dict = {}
        self._history_stream_open = False
        self._chat_tts_mode = "off"
        self._read_aloud_active = False

        self._pending_fact_check = False
        self._pending_fact_stage = ""
        self._pending_fact_target_text = ""
        self._pending_fact_target_label = ""
        self._pending_fact_sources: list[tuple[str, str]] = []
        self._pending_fact_facts: list[str] = []
        self._pending_fact_results: list[dict[str, str]] = []
        self._pending_fact_index = 0
        self._llm_generating = False
        self._aux_generating = False
        self._model_panel_last_size = 160

        self._feedback_service: FeedbackService | None = None
        self._last_user_msg = ""
        self._last_assistant_msg = ""
        self._last_use_case = "chat_answer"

        self._setup_dock()
        self._connect_signals()
        self.set_user_mode(self._user_mode)
        self.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        features = QDockWidget.DockWidgetFeature.DockWidgetMovable
        features |= QDockWidget.DockWidgetFeature.DockWidgetFloatable
        features |= QDockWidget.DockWidgetFeature.DockWidgetClosable
        self.setFeatures(features)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_feedback_service(self, service: FeedbackService):
        self._feedback_service = service

    def set_context_getter(self, getter: Callable[[], dict]):
        self._context_getter = getter

    def set_canvas_selection_getter(self, getter: Callable[[], str] | None):
        self._canvas_selection_getter = getter

    def set_selection_apply_handler(
        self,
        handler: Callable[[str, str, tuple[int, int] | None], tuple[bool, str]],
    ):
        self._selection_apply_handler = handler

    def set_fact_result_handler(self, handler: Callable[[str, str], tuple[bool, str]]):
        self._fact_result_handler = handler

    def set_glossary_request_handler(
        self,
        handler: Callable[[dict, Callable[[bool, str], None]], tuple[bool, str]],
    ):
        self._glossary_request_handler = handler

    def set_mindmap_request_handler(
        self,
        handler: Callable[[dict, str, str, Callable[[bool, str], None]], tuple[bool, str]],
    ):
        self._mindmap_request_handler = handler

    def set_aux_task_running(self, running: bool):
        self._aux_generating = bool(running)
        self._apply_busy_state()

    def add_document(self, name: str, content: str):
        """Register an imported document in the context selector."""
        self.context_panel.add_document(name, content)

    def remove_document(self, name: str):
        """Remove an imported document from the context selector."""
        self.context_panel.remove_document(name)

    def get_context_selection(self) -> tuple[bool, bool, list[tuple[str, str]]]:
        """Return ``(use_canvas, use_rag, [(name, content), ...])``."""
        return self.context_panel.get_selection()

    def update_context_bar(self, parts: list[str]):
        """Update the context indicator bar with part labels."""
        if parts:
            self._ctx_bar.setText("Context: " + " | ".join(parts))
            return
        self._ctx_bar.setText("Context: —")

    def set_user_mode(self, mode: str):
        self._user_mode = normalize_user_mode(mode)
        self.model_panel.set_user_mode(self._user_mode)
        show_apply = mode_rank(self._user_mode) >= mode_rank(USER_MODE_PLUS)
        if not show_apply:
            self.apply_selection_cb.setChecked(False)
        self.apply_selection_cb.setVisible(show_apply)

    def set_chat_tts_mode(self, mode: str):
        normalized = self._normalize_tts_mode(mode)
        self._chat_tts_mode = normalized
        combo = getattr(self, "chat_tts_combo", None)
        if combo is not None:
            for idx in range(combo.count()):
                data = str(combo.itemData(idx) or "").strip().lower()
                if data == normalized:
                    combo.blockSignals(True)
                    combo.setCurrentIndex(idx)
                    combo.blockSignals(False)
                    break
        self.tts_mode_changed.emit(normalized)

    def chat_tts_mode(self) -> str:
        return str(self._chat_tts_mode or "off")

    def set_read_aloud_active(self, active: bool):
        self._read_aloud_active = bool(active)
        btn = getattr(self, "play_last_btn", None)
        if btn is None:
            return
        if self._read_aloud_active:
            btn.setText("⏹")
            btn.setToolTip("Vorlesen stoppen")
            return
        btn.setText("🔊")
        btn.setToolTip("Letzte Modellantwort vorlesen")

    def is_model_panel_visible(self) -> bool:
        splitter = getattr(self, "_main_splitter", None)
        if splitter is None:
            return True
        sizes = splitter.sizes()
        if len(sizes) != 3:
            return True
        return int(sizes[0]) > 8

    def set_model_panel_visible(self, visible: bool):
        splitter = getattr(self, "_main_splitter", None)
        if splitter is None:
            return
        sizes = splitter.sizes()
        if len(sizes) != 3:
            return

        total = int(sum(sizes))
        if total <= 0:
            total = 1
        model_size, ctx_size, chat_size = [int(s) for s in sizes]

        min_model = 72
        min_ctx = 52
        min_chat = 96

        if not bool(visible):
            if model_size > 8:
                self._model_panel_last_size = model_size
            remaining = total
            ctx_chat_total = max(1, ctx_size + chat_size)
            ctx_target = int(round(remaining * (ctx_size / ctx_chat_total)))
            ctx_target = max(min_ctx, min(ctx_target, max(min_ctx, remaining - min_chat)))
            chat_target = max(min_chat, remaining - ctx_target)
            splitter.setSizes([0, ctx_target, chat_target])
            return

        available_for_model = max(0, total - (min_ctx + min_chat))
        if available_for_model <= 0:
            splitter.setSizes([0, max(min_ctx, total // 3), max(min_chat, total // 2)])
            return

        desired = int(self._model_panel_last_size or min_model)
        model_target = max(min_model, min(desired, available_for_model))
        remaining = max(0, total - model_target)
        ctx_chat_total = max(1, ctx_size + chat_size)
        ctx_target = int(round(remaining * (ctx_size / ctx_chat_total)))
        ctx_target = max(min_ctx, min(ctx_target, max(min_ctx, remaining - min_chat)))
        chat_target = max(min_chat, remaining - ctx_target)
        splitter.setSizes([model_target, ctx_target, chat_target])

    def toggle_model_panel(self) -> bool:
        new_visible = not self.is_model_panel_visible()
        self.set_model_panel_visible(new_visible)
        return new_visible

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _setup_dock(self):
        container = QWidget()
        container.setMinimumWidth(300)
        outer = QVBoxLayout(container)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Vertical)
        self._main_splitter = splitter
        splitter.setStyleSheet(
            "QSplitter::handle { background: palette(mid); height: 2px; }"
            "QSplitter::handle:hover { background: palette(highlight); }"
        )

        self.model_panel = ModelLoadPanel()
        splitter.addWidget(self.model_panel)
        splitter.setCollapsible(0, True)

        self.context_panel = ContextSelectorPanel()
        self.context_panel.preferred_height_changed.connect(
            self._apply_context_panel_height
        )
        splitter.addWidget(self.context_panel)
        splitter.setCollapsible(1, True)

        chat_widget = QWidget()
        chat_widget.setStyleSheet("background: palette(base);")
        chat_layout = QVBoxLayout(chat_widget)
        chat_layout.setContentsMargins(0, 0, 0, 0)
        chat_layout.setSpacing(0)

        inner = QSplitter(Qt.Orientation.Vertical)
        inner.setStyleSheet(
            "QSplitter::handle { background: palette(mid); height: 3px; }"
            "QSplitter::handle:hover { background: palette(highlight); }"
        )

        history_widget = QWidget()
        history_widget.setStyleSheet("background: palette(base);")
        history_layout = QVBoxLayout(history_widget)
        history_layout.setContentsMargins(0, 0, 0, 0)
        history_layout.setSpacing(0)

        self.history = ChatHistoryWidget()
        history_layout.addWidget(self.history)

        ctx_row = QWidget()
        ctx_row.setStyleSheet(
            "background: palette(alternate-base); border-top: 1px solid palette(mid);"
        )
        ctx_layout = QHBoxLayout(ctx_row)
        ctx_layout.setContentsMargins(8, 2, 8, 2)
        ctx_layout.setSpacing(0)

        self._ctx_bar = QLabel("Context: —")
        self._ctx_bar.setSizePolicy(
            QSizePolicy.Policy.Maximum,
            QSizePolicy.Policy.Fixed,
        )
        self._ctx_bar.setStyleSheet(
            "background: transparent; color: palette(placeholder-text); font-size: 9px;"
        )
        ctx_layout.addWidget(self._ctx_bar, 0, Qt.AlignmentFlag.AlignLeft)
        ctx_layout.addStretch(1)
        history_layout.addWidget(ctx_row)

        inner.addWidget(history_widget)
        inner.addWidget(self._build_input_area())
        inner.setSizes([340, 120])
        inner.setCollapsible(0, False)
        inner.setCollapsible(1, False)

        chat_layout.addWidget(inner)
        splitter.addWidget(chat_widget)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 0)
        splitter.setStretchFactor(2, 1)
        splitter.setSizes([160, self.context_panel.preferred_height(), 380])

        outer.addWidget(splitter)
        self.setWidget(container)

    @staticmethod
    def _normalize_context_text(text: str) -> str:
        return (
            str(text or "")
            .replace("\u2029", "\n")
            .replace("\r\n", "\n")
            .strip()
        )

    def _apply_context_panel_height(self, height: int):
        splitter = getattr(self, "_main_splitter", None)
        if splitter is None:
            return
        sizes = splitter.sizes()
        if len(sizes) != 3:
            return
        total = sum(sizes)
        if total <= 0:
            return

        min_model = 72
        min_chat = 96
        max_ctx = max(52, total - (min_model + min_chat))
        ctx_height = max(52, min(int(height), max_ctx))
        remaining = max(min_model + min_chat, total - ctx_height)

        model_target = sizes[0]
        chat_target = sizes[2]
        model_chat_total = model_target + chat_target
        if model_chat_total <= 0:
            model_target = max(min_model, remaining // 4)
        else:
            ratio = model_target / model_chat_total
            model_target = int(round(remaining * ratio))

        model_target = max(
            min_model,
            min(model_target, max(min_model, remaining - min_chat)),
        )
        chat_target = max(min_chat, remaining - model_target)
        splitter.setSizes([model_target, ctx_height, chat_target])

    def _build_input_area(self) -> QWidget:
        area = QWidget()
        area.setMinimumHeight(80)
        area.setStyleSheet("background: palette(alternate-base); border-top: 1px solid palette(mid);")
        layout = QVBoxLayout(area)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        self.input_box = QPlainTextEdit()
        self.input_box.setPlaceholderText("Ask the AI… (Ctrl+Enter to send)")
        self.input_box.setStyleSheet(
            """
            QPlainTextEdit {
                background: palette(base); color: palette(text);
                border: 1px solid palette(mid); border-radius: 4px;
                padding: 4px; font-size: 11px;
            }
            QPlainTextEdit:focus { border-color: palette(highlight); }
            """
        )
        layout.addWidget(self.input_box)

        self.apply_selection_cb = QCheckBox(
            "Apply rewrite directly to selected Draft text"
        )
        self.apply_selection_cb.setChecked(False)
        self.apply_selection_cb.setToolTip(
            "If enabled and a draft selection exists, the model must return\n"
            "a structured rewrite block and the selected text is replaced directly."
        )
        self.apply_selection_cb.setStyleSheet(CTX_CB_STYLE)
        layout.addWidget(self.apply_selection_cb)

        self.fact_btn = QPushButton("Faktencheck")
        self.fact_btn.setStyleSheet(BTN_NEUTRAL)
        self.fact_btn.setToolTip(
            "Prüft den markierten Text (oder den aktuellen Draft-Text) "
            "gegen ausgewählte Dokumente/RAG-Quellen."
        )
        self.fact_btn.clicked.connect(self._send_fact_check)

        self.glossary_btn = QPushButton("Glossar")
        self.glossary_btn.setStyleSheet(BTN_NEUTRAL)
        self.glossary_btn.setToolTip(
            "Erstellt ein Glossar nur aus den aktuell ausgewählten Kontextquellen."
        )
        self.glossary_btn.clicked.connect(self._send_glossary_generation)

        self.mindmap_btn = QPushButton("MindMap/Graph")
        self.mindmap_btn.setStyleSheet(BTN_NEUTRAL)
        self.mindmap_btn.setToolTip(
            "Erstellt MindMap/Graph nur aus den aktuell ausgewählten Kontextquellen.\n"
            "Modus wird nach Klick im Popup gewählt."
        )
        self.mindmap_btn.clicked.connect(self._send_mindmap_generation)

        btn_row = QHBoxLayout()

        new_tab_btn = QPushButton("+ Tab")
        new_tab_btn.setToolTip("Neue Unterhaltung starten")
        new_tab_btn.setStyleSheet(BTN_NEUTRAL)
        new_tab_btn.clicked.connect(lambda: self.history.add_tab())

        clear_btn = QPushButton("🗑")
        clear_btn.setToolTip("Clear chat")
        clear_btn.setFixedWidth(32)
        clear_btn.setStyleSheet(BTN_NEUTRAL)
        clear_btn.clicked.connect(self.history.clear_history)

        self.play_last_btn = QPushButton("🔊")
        self.play_last_btn.setToolTip("Letzte Modellantwort vorlesen")
        self.play_last_btn.setFixedWidth(32)
        self.play_last_btn.setStyleSheet(BTN_NEUTRAL)
        self.play_last_btn.clicked.connect(self._play_last_answer)

        self.chat_tts_combo = QComboBox()
        self.chat_tts_combo.addItem("TTS: aus", "off")
        self.chat_tts_combo.addItem("TTS: einmal", "once")
        self.chat_tts_combo.addItem("TTS: an", "always")
        self.chat_tts_combo.setStyleSheet(BTN_NEUTRAL)
        self.chat_tts_combo.setToolTip(
            "aus: kein Vorlesen\n"
            "einmal: naechste Modellantwort vorlesen\n"
            "an: jede fertige Modellantwort vorlesen"
        )
        self.chat_tts_combo.currentIndexChanged.connect(
            self._on_chat_tts_combo_changed
        )

        btn_row.addWidget(new_tab_btn)
        btn_row.addWidget(clear_btn)
        btn_row.addWidget(self.play_last_btn)
        btn_row.addWidget(self.chat_tts_combo)
        btn_row.addStretch()

        self.stop_btn = QPushButton("⬛ Stop")
        self.stop_btn.setStyleSheet(BTN_DANGER)
        self.stop_btn.clicked.connect(self.llm.stop)
        self.stop_btn.setVisible(False)

        self.send_btn = QPushButton("Send ↵")
        self.send_btn.setStyleSheet(BTN_PRIMARY)
        self.send_btn.clicked.connect(self._send)

        btn_row.addWidget(self.stop_btn)
        btn_row.addWidget(self.send_btn)

        layout.addLayout(btn_row)

        task_row = QHBoxLayout()
        task_row.setContentsMargins(0, 0, 0, 0)
        task_row.setSpacing(4)
        task_row.addWidget(self.fact_btn)
        task_row.addWidget(self.glossary_btn)
        task_row.addWidget(self.mindmap_btn)
        task_row.addStretch()
        layout.addLayout(task_row)
        return area

    def _connect_signals(self):
        self.model_panel.load_requested.connect(
            lambda path, params: self.llm.load_model(path, **params)
        )
        self.llm.model_loaded.connect(self.model_panel.on_model_loaded)
        self.llm.token_received.connect(self._on_token)
        self.llm.generation_complete.connect(self._on_complete)
        self.llm.error_occurred.connect(self._on_error)
        self.llm.is_generating.connect(self._on_generating)
        self.history.feedback_submitted.connect(self._on_chat_feedback_submitted)

        shortcut = QShortcut(QKeySequence("Ctrl+Return"), self.input_box)
        shortcut.activated.connect(self._send)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _collect_shared_context(self) -> dict:
        """
        Return one canonical context payload for chat + all side actions.

        This guarantees that Chat, Faktencheck, Glossar and MindMap/Graph
        all consume exactly the same selected context sources.
        """
        ctx: dict = {}
        if self._context_getter:
            raw = self._context_getter()
            if isinstance(raw, dict):
                ctx = raw
        return {
            "file_contents": list(ctx.get("file_contents", []) or []),
            "rag_results": list(ctx.get("rag_results", []) or []),
            "selected_text": str(ctx.get("selected_text", "") or ""),
            "selected_span": ctx.get("selected_span", None),
            "grounding_required": bool(ctx.get("grounding_required", False)),
            "grounding_has_sources": bool(
                ctx.get("grounding_has_sources", False)
            ),
            "grounding_selected_docs": int(
                ctx.get("grounding_selected_docs", 0) or 0
            ),
            "grounding_rag_selected": bool(
                ctx.get("grounding_rag_selected", False)
            ),
            "grounding_rag_has_data": bool(
                ctx.get("grounding_rag_has_data", False)
            ),
        }

    @staticmethod
    def _has_any_context_content(ctx: dict) -> bool:
        selected_text = str(ctx.get("selected_text", "") or "").strip()
        if selected_text:
            return True
        for _name, content in list(ctx.get("file_contents", []) or []):
            if str(content or "").strip():
                return True
        for _path, _score, excerpt in list(ctx.get("rag_results", []) or []):
            if str(excerpt or "").strip():
                return True
        return False

    def _reset_pending_canvas_rewrite(self):
        self._pending_apply_to_canvas = False
        self._pending_selected_text = ""
        self._pending_selected_span = None
        self._pending_apply_retry_count = 0
        self._pending_apply_context = {}

    @staticmethod
    def _canvas_rewrite_retry_user_message() -> str:
        return (
            "Es wurde nicht die richtige Markierung für den ersetzten Text verwendet.\n"
            "Die Aufgabe bleibt unverändert dieselbe, inklusive Ausgabeform und Struktur.\n"
            "Behalte die Form standardmäßig bei: Liste bleibt Liste, Tabelle bleibt Tabelle, "
            "JSON bleibt JSON, Markdown bleibt Markdown.\n"
            "Nur wenn die ursprüngliche Nutzeranweisung explizit eine "
            "Format-Umwandlung fordert (z. B. zu Fließtext), darf die Form geändert werden.\n"
            "Bitte gib NUR den finalen Ersatzinhalt in folgendem exakten Format aus:\n"
            f"{CANVAS_REWRITE_OPEN}\n"
            "TEXT_DER_DEN_ZU_ERSETZENDEN_TEXT_ERSETZT\n"
            f"{CANVAS_REWRITE_CLOSE}\n"
            "Keine Erklärung, keine zusätzlichen Präfixe/Suffixe."
        )

    @staticmethod
    def _canvas_scope_retry_user_message() -> str:
        return (
            "Es wurde offenbar Text außerhalb der Auswahl wiederholt.\n"
            "Bitte korrigiere das und ersetze NUR den selektierten Bereich, "
            "NICHT den gesamten Canvas/Draft.\n"
            "Die Aufgabe bleibt unverändert dieselbe, inklusive Ausgabeform und Struktur.\n"
            "Behalte die Form standardmäßig bei.\n"
            "Nur wenn die ursprüngliche Nutzeranweisung explizit eine "
            "Format-Umwandlung fordert, darf die Form geändert werden.\n"
            "Gib NUR den finalen Ersatzinhalt in folgendem exakten Format aus:\n"
            f"{CANVAS_REWRITE_OPEN}\n"
            "TEXT_DER_DEN_ZU_ERSETZENDEN_TEXT_ERSETZT\n"
            f"{CANVAS_REWRITE_CLOSE}\n"
            "Keine Erklärung, keine zusätzlichen Präfixe/Suffixe."
        )

    @staticmethod
    def _contains_non_selected_canvas_repeat(
        draft_text: str,
        selected_text: str,
        replacement: str,
    ) -> bool:
        draft = ChatDock._normalize_context_text(draft_text)
        selected = ChatDock._normalize_context_text(selected_text)
        rewritten = ChatDock._normalize_context_text(replacement)
        if not draft or not selected or not rewritten:
            return False
        if draft == selected or rewritten == selected:
            return False
        if rewritten in draft and rewritten != selected:
            return True
        if draft in rewritten and draft != selected:
            return True

        start = draft.find(selected)
        if start < 0:
            return False

        before = draft[:start].strip()
        after = draft[start + len(selected):].strip()
        before_hint = before[-200:].strip()
        after_hint = after[:200].strip()
        if before_hint and len(before_hint) >= 24 and before_hint in rewritten:
            return True
        if after_hint and len(after_hint) >= 24 and after_hint in rewritten:
            return True
        return False

    @staticmethod
    def _extract_selected_replacement_from_full_draft(
        draft_text: str,
        selected_text: str,
        rewritten_text: str,
    ) -> str:
        """
        Detect exact A+B'+C pattern and extract only B'.

        Returns empty string when no unique 1:1 decomposition is possible.
        """
        draft = (
            str(draft_text or "")
            .replace("\u2029", "\n")
            .replace("\r\n", "\n")
        )
        selected = (
            str(selected_text or "")
            .replace("\u2029", "\n")
            .replace("\r\n", "\n")
        )
        rewritten = (
            str(rewritten_text or "")
            .replace("\u2029", "\n")
            .replace("\r\n", "\n")
        )
        if not draft or not selected or not rewritten:
            return ""
        if draft == selected:
            return ""

        candidates: list[str] = []

        def _similarity(a: str, b: str) -> float:
            if a == b:
                return 1.0
            if not a or not b:
                return 0.0
            max_len = max(len(a), len(b))
            if max_len <= 0:
                return 1.0
            if abs(len(a) - len(b)) / max_len > 0.05:
                return 0.0
            return SequenceMatcher(None, a, b).ratio()

        def _nearby_positions(target: int, total: int, window: int) -> list[int]:
            start = max(0, target - window)
            end = min(total, target + window)
            positions = list(range(start, end + 1))
            positions.sort(key=lambda pos: (abs(pos - target), pos))
            return positions

        similarity_threshold = 0.95
        start = 0
        while True:
            idx = draft.find(selected, start)
            if idx < 0:
                break
            end = idx + len(selected)
            prefix = draft[:idx]
            suffix = draft[end:]
            if rewritten.startswith(prefix) and rewritten.endswith(suffix):
                repl_end = len(rewritten) - len(suffix) if suffix else len(rewritten)
                candidate = rewritten[len(prefix):repl_end]
                candidates.append(candidate)
                start = idx + 1
                continue

            # Fuzzy fallback: accept minimal edits in A/C if both parts are still >=95% similar.
            total_len = len(rewritten)
            prefix_target = len(prefix)
            suffix_target = total_len - len(suffix)
            shift_window = max(4, min(64, int(max(prefix_target, len(suffix)) * 0.02)))

            prefix_hits: list[tuple[int, float]] = []
            for pos in _nearby_positions(prefix_target, total_len, shift_window):
                score = _similarity(prefix, rewritten[:pos])
                if score >= similarity_threshold:
                    prefix_hits.append((pos, score))
                    if len(prefix_hits) >= 12:
                        break

            suffix_hits: list[tuple[int, float]] = []
            for pos in _nearby_positions(suffix_target, total_len, shift_window):
                score = _similarity(suffix, rewritten[pos:])
                if score >= similarity_threshold:
                    suffix_hits.append((pos, score))
                    if len(suffix_hits) >= 12:
                        break

            best: tuple[float, int, str] | None = None
            for prefix_pos, prefix_score in prefix_hits:
                for suffix_pos, suffix_score in suffix_hits:
                    if prefix_pos > suffix_pos:
                        continue
                    edge_score = min(prefix_score, suffix_score)
                    edge_shift = abs(prefix_pos - prefix_target) + abs(suffix_pos - suffix_target)
                    middle = rewritten[prefix_pos:suffix_pos]
                    rank = (edge_score, -edge_shift, middle)
                    if best is None or rank > best:
                        best = rank
            if best is not None:
                candidates.append(best[2])
            start = idx + 1

        if len(candidates) != 1:
            return ""
        return candidates[0]

    def _retry_canvas_rewrite_format(self, retry_message: str | None = None) -> bool:
        if self._pending_apply_retry_count >= self._pending_apply_retry_limit:
            return False
        if not self.llm.is_model_loaded():
            return False
        context = dict(self._pending_apply_context or {})
        if not context:
            return False

        message = str(retry_message or self._canvas_rewrite_retry_user_message())
        self.history.add_message("user", message)

        send_ok = self.llm.send_message(
            user_message=message,
            file_contents=list(context.get("file_contents", []) or []),
            rag_results=list(context.get("rag_results", []) or []),
            selected_text=str(context.get("selected_text", "") or ""),
            chat_history=self.history.get_history()[:-1],
            selection_apply_mode=True,
            grounding_required=bool(context.get("grounding_required", False)),
            grounding_has_sources=bool(context.get("grounding_has_sources", True)),
            **dict(context.get("gen_params", {}) or {}),
        )
        if not send_ok:
            return False

        self._pending_apply_retry_count += 1
        self._pending_apply_to_canvas = True
        self.history.begin_streaming()
        self._history_stream_open = True
        return True

    def _send_glossary_generation(self):
        if not self.llm.is_model_loaded():
            self.history.add_message(
                "system",
                "⚠ No model loaded. Load a GGUF model first.",
            )
            return
        if self._aux_generating:
            self.history.add_message(
                "system",
                "⚠ Eine Hintergrundaufgabe läuft bereits. Bitte kurz warten.",
            )
            return
        if self.llm.worker.isRunning():
            self.history.add_message(
                "system",
                "⚠ Modell ist beschäftigt. Bitte nach aktueller Generation erneut versuchen.",
            )
            return
        if self._glossary_request_handler is None:
            self.history.add_message(
                "system",
                "⚠ Kein Glossar-Handler konfiguriert.",
            )
            return

        ctx = self._collect_shared_context()
        if not self._has_any_context_content(ctx):
            self.history.add_message(
                "system",
                "⚠ Kein Kontext ausgewählt. Bitte im Context-Bereich Quellen aktivieren.",
            )
            return

        self.history.add_message("user", "Glossar aus aktuellem Kontext")
        self.history.reset_feedback()

        def done(ok: bool, info: str):
            if ok:
                self._last_use_case = "glossary"
                self.history.add_message(
                    "system",
                    f"✅ Glossar erstellt. {info}".strip(),
                )
                self.history.activate_feedback("glossary")
                return
            self.history.add_message("system", f"⚠ Glossar fehlgeschlagen: {info}")

        ok, info = self._glossary_request_handler(ctx, done)
        if ok:
            self.history.add_message("system", "⏳ Glossar wird erstellt…")
            return
        self.history.add_message("system", f"⚠ Glossar fehlgeschlagen: {info}")

    def _send_mindmap_generation(self):
        if not self.llm.is_model_loaded():
            self.history.add_message(
                "system",
                "⚠ No model loaded. Load a GGUF model first.",
            )
            return
        if self._aux_generating:
            self.history.add_message(
                "system",
                "⚠ Eine Hintergrundaufgabe läuft bereits. Bitte kurz warten.",
            )
            return
        if self.llm.worker.isRunning():
            self.history.add_message(
                "system",
                "⚠ Modell ist beschäftigt. Bitte nach aktueller Generation erneut versuchen.",
            )
            return
        if self._mindmap_request_handler is None:
            self.history.add_message(
                "system",
                "⚠ Kein MindMap/Graph-Handler konfiguriert.",
            )
            return

        ctx = self._collect_shared_context()
        if not self._has_any_context_content(ctx):
            self.history.add_message(
                "system",
                "⚠ Kein Kontext ausgewählt. Bitte im Context-Bereich Quellen aktivieren.",
            )
            return

        mode_choice, accepted = QInputDialog.getItem(
            self,
            "MindMap/Graph aus Kontext",
            "Ausgabeformat:",
            ["MindMap", "Graph"],
            0,
            False,
        )
        if not accepted:
            return
        mode = (
            "graph"
            if str(mode_choice or "").strip().casefold() == "graph"
            else "mindmap"
        )
        mode_label = "Graph" if mode == "graph" else "MindMap"
        query = self.input_box.toPlainText().strip()
        if query:
            self.history.add_message(
                "user",
                f"{mode_label} aus aktuellem Kontext\nQuery: {query}",
            )
        else:
            self.history.add_message("user", f"{mode_label} aus aktuellem Kontext")

        self.history.reset_feedback()

        def done(ok: bool, info: str):
            if ok:
                self._last_use_case = "mindmap"
                self.history.add_message(
                    "system",
                    f"✅ {mode_label} erstellt. {info}".strip(),
                )
                self.history.activate_feedback("mindmap")
                return
            self.history.add_message(
                "system",
                f"⚠ {mode_label} fehlgeschlagen: {info}",
            )

        ok, info = self._mindmap_request_handler(ctx, query, mode, done)
        if ok:
            self.history.add_message("system", f"⏳ {mode_label} wird erstellt…")
            return
        self.history.add_message(
            "system",
            f"⚠ {mode_label} fehlgeschlagen: {info}",
        )

    def _send(self):
        msg = self.input_box.toPlainText().strip()
        if not msg:
            return

        self._last_user_msg = msg
        self._last_use_case = "chat_answer"
        self.history.reset_feedback()
        self._reset_fact_pipeline_state()
        if not self.llm.is_model_loaded():
            self.history.add_message(
                "system",
                "⚠ No model loaded. Load a GGUF model first.",
            )
            return
        if self._aux_generating:
            self.history.add_message(
                "system",
                "⚠ Eine Hintergrundaufgabe läuft bereits. Bitte kurz warten.",
            )
            return

        ctx = self._collect_shared_context()

        selected_text = ctx.get("selected_text", "")
        selected_span = ctx.get("selected_span", None)
        selection_apply_mode = bool(
            self.apply_selection_cb.isChecked() and selected_text and selected_text.strip()
        )
        if self.apply_selection_cb.isChecked() and not selection_apply_mode:
            self.history.add_message(
                "system",
                "⚠ 'Apply rewrite' is enabled, but no draft text is selected.",
            )
            return

        grounding_required = bool(ctx.get("grounding_required", False))
        grounding_has_sources = bool(ctx.get("grounding_has_sources", True))
        if grounding_required and not grounding_has_sources:
            mode_hint = (
                "RAG" if bool(ctx.get("grounding_rag_selected", False)) else "Dokumente"
            )
            self.history.add_message(
                "system",
                "⚠ Dokumentgebundener Modus aktiv (" + mode_hint + "). "
                "Es liegen aber keine verwertbaren Inhalte vor. "
                "Bitte zuerst RAG-Ergebnisse erzeugen und/oder Dokumente auswählen. "
                "Ohne Quellen wird keine Antwort erzeugt.",
            )
            return

        self.history.add_message("user", msg)
        self.input_box.clear()

        self._reset_pending_canvas_rewrite()
        self._pending_apply_to_canvas = selection_apply_mode
        self._pending_selected_text = selected_text if selection_apply_mode else ""
        self._pending_selected_span = (
            selected_span if selection_apply_mode else None
        )

        file_contents = list(ctx.get("file_contents", []))
        if selection_apply_mode:
            # Keep full-draft context available for coherence, but avoid
            # duplicate payloads when the selected text already equals it.
            norm_selected = self._normalize_context_text(selected_text)
            filtered: list[tuple[str, str]] = []
            for name, content in file_contents:
                if not str(name).startswith("Draft:"):
                    filtered.append((name, content))
                    continue

                norm_full_draft = self._normalize_context_text(content)
                if norm_full_draft and norm_full_draft == norm_selected:
                    continue
                filtered.append((name, content))
            file_contents = filtered

        history = self.history.get_history()[:-1]
        gen_params = self.model_panel.get_generation_params()
        if selection_apply_mode:
            self._pending_apply_context = {
                "file_contents": list(file_contents),
                "rag_results": list(ctx.get("rag_results", []) or []),
                "selected_text": selected_text,
                "selected_span": selected_span,
                "grounding_required": grounding_required,
                "grounding_has_sources": grounding_has_sources,
                "gen_params": dict(gen_params),
            }

        started = self.llm.send_message(
            user_message=msg,
            file_contents=file_contents,
            rag_results=ctx.get("rag_results", []),
            selected_text=selected_text,
            chat_history=history,
            selection_apply_mode=selection_apply_mode,
            grounding_required=grounding_required,
            grounding_has_sources=grounding_has_sources,
            **gen_params,
        )
        if started:
            self.history.begin_streaming()
            self._history_stream_open = True
            return
        self._reset_pending_canvas_rewrite()

    def _on_token(self, token: str):
        if self._pending_fact_check:
            return
        self.history.append_token(token)

    def _on_complete(self, response: str):
        if self._history_stream_open:
            self.history.finish_streaming()
            self._history_stream_open = False
        if self._pending_fact_check:
            self._handle_fact_pipeline_complete(response)
            if not self._pending_fact_check:
                self.history.activate_feedback("fact_check")
            return
        self._last_assistant_msg = str(response or "").strip()
        if contains_structured_graph(self._last_assistant_msg):
            self._last_use_case = "mindmap"
        else:
            self._last_use_case = "chat_answer"
        self._maybe_auto_read_response(response)

        if not self._pending_apply_to_canvas:
            self._pending_apply_context = {}
            self._pending_apply_retry_count = 0
            self.history.activate_feedback(self._last_use_case)
            return

        draft_text = ""
        for name, content in list(
            self._pending_apply_context.get("file_contents", []) or []
        ):
            if str(name or "").startswith("Draft:"):
                draft_text = str(content or "")
                break

        raw_replacement = extract_canvas_rewrite(
            response,
            CANVAS_REWRITE_OPEN,
            CANVAS_REWRITE_CLOSE,
        )
        if not raw_replacement:
            if GROUNDING_INSUFFICIENT_MESSAGE in response:
                self._reset_pending_canvas_rewrite()
                self.history.add_message(
                    "system",
                    f"⚠ {GROUNDING_INSUFFICIENT_MESSAGE}",
                )
                return
            if self._retry_canvas_rewrite_format():
                return
            self._reset_pending_canvas_rewrite()
            self.history.add_message(
                "system",
                "⚠ No valid rewrite block found. Draft selection was not changed.",
            )
            return

        replacement = raw_replacement
        strict_full_draft_match = False
        selected_only_replacement = self._extract_selected_replacement_from_full_draft(
            draft_text,
            self._pending_selected_text,
            raw_replacement,
        )
        if selected_only_replacement:
            replacement = selected_only_replacement
            strict_full_draft_match = True

        if self._selection_apply_handler is None:
            self._reset_pending_canvas_rewrite()
            self.history.add_message(
                "system",
                "⚠ No draft apply handler configured.",
            )
            return

        ok, info = self._selection_apply_handler(
            replacement,
            self._pending_selected_text,
            self._pending_selected_span,
        )
        if ok:
            self._reset_pending_canvas_rewrite()
            self.history.add_message(
                "system",
                f"✅ Selection updated in draft workspace. {info}".strip(),
            )
            self.history.activate_feedback("canvas_edit")
            return

        ambiguous_message = "Selection is ambiguous in source text."
        if ambiguous_message in str(info or ""):
            if strict_full_draft_match and draft_text:
                ok, info = self._selection_apply_handler(
                    raw_replacement,
                    draft_text,
                    None,
                )
                if ok:
                    self._reset_pending_canvas_rewrite()
                    self.history.add_message(
                        "system",
                        f"✅ Selection updated in draft workspace. {info}".strip(),
                    )
                    self.history.activate_feedback("canvas_edit")
                    return
            if (
                not strict_full_draft_match
                and self._contains_non_selected_canvas_repeat(
                    draft_text,
                    self._pending_selected_text,
                    replacement,
                )
            ):
                if self._retry_canvas_rewrite_format(
                    self._canvas_scope_retry_user_message()
                ):
                    return
            self._reset_pending_canvas_rewrite()
            self.history.add_message(
                "system",
                (
                    "⚠ Could not apply rewrite automatically. "
                    "Please reselect the target passage and retry."
                ),
            )
            return

        self._reset_pending_canvas_rewrite()
        info_text = str(info or "")
        if ambiguous_message in info_text:
            info_text = (
                "Selection mapping unavailable. "
                "Please reselect the target passage and retry."
            )
        self.history.add_message("system", f"⚠ Could not apply rewrite: {info_text}")

    def _play_last_answer(self):
        if self._read_aloud_active:
            self.read_aloud_stop_requested.emit()
            return
        text = self.history.get_last_message(role="assistant")
        if not text:
            self.history.add_message(
                "system",
                "⚠ Keine Assistenzantwort zum Vorlesen vorhanden.",
            )
            return
        self.read_aloud_requested.emit(text)

    def _on_chat_tts_combo_changed(self, _index: int):
        mode = "off"
        combo = getattr(self, "chat_tts_combo", None)
        if combo is not None:
            mode = str(combo.currentData() or "off").strip().lower()
        normalized = self._normalize_tts_mode(mode)
        self._chat_tts_mode = normalized
        self.tts_mode_changed.emit(normalized)

    @staticmethod
    def _normalize_tts_mode(mode: str) -> str:
        clean = str(mode or "").strip().lower()
        if clean in {"off", "once", "always"}:
            return clean
        return "off"

    def _maybe_auto_read_response(self, response: str):
        mode = self._normalize_tts_mode(self._chat_tts_mode)
        if mode == "off":
            return
        text = str(response or "").strip()
        if not text:
            return
        self.read_aloud_requested.emit(text)
        if mode == "once":
            self._chat_tts_mode = "off"
            combo = getattr(self, "chat_tts_combo", None)
            if combo is not None:
                for idx in range(combo.count()):
                    if str(combo.itemData(idx) or "") == "off":
                        combo.blockSignals(True)
                        combo.setCurrentIndex(idx)
                        combo.blockSignals(False)
                        break
            self.tts_mode_changed.emit("off")

    def _on_chat_feedback_submitted(
        self,
        use_case: str,
        sentiment: str,
        tags: list[str],
        note: str,
    ):
        if self._feedback_service is None:
            return
        model_info = ""
        panel = getattr(self, "model_panel", None)
        if panel is not None:
            model_path_widget = getattr(panel, "model_path", None)
            if model_path_widget is not None:
                model_info = str(model_path_widget.text() or "")
        payload = {
            "last_user_message": self._last_user_msg,
            "last_assistant_message": self._last_assistant_msg,
            "model": model_info,
        }
        self._feedback_service.submit_feedback(
            use_case=use_case or self._last_use_case,
            sentiment=sentiment,
            payload=payload,
            error_tags=tags or None,
            note=note,
        )

    def _on_error(self, msg: str):
        self._reset_pending_canvas_rewrite()
        self._reset_fact_pipeline_state()
        if self._history_stream_open:
            self.history.finish_streaming()
            self._history_stream_open = False
        self.history.add_message("system", f"❌ {msg}")

    def _on_generating(self, generating: bool):
        self._llm_generating = bool(generating)
        self._apply_busy_state()

    def _apply_busy_state(self):
        llm_active = bool(self._llm_generating)
        busy_any = bool(self._llm_generating or self._aux_generating)
        self.send_btn.setVisible(not llm_active)
        self.stop_btn.setVisible(llm_active)
        self.send_btn.setEnabled(not busy_any)
        self.fact_btn.setEnabled(not busy_any)
        self.glossary_btn.setEnabled(not busy_any)
        self.mindmap_btn.setEnabled(not busy_any)
        self.input_box.setReadOnly(busy_any)


__all__ = ["ChatDock"]
