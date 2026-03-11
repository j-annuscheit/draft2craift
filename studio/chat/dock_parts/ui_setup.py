"""ChatDock method implementations."""
from __future__ import annotations

from .deps import *  # noqa: F403

_MODEL_PANEL_MIN_HEIGHT = 72
_CONTEXT_PANEL_MIN_HEIGHT = 52
_CHAT_PANEL_MIN_HEIGHT = 96
_CONTEXT_PANEL_MAX_HEIGHT = 220
_CONTEXT_PANEL_MAX_SHARE = 0.33


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
    inner.setStretchFactor(0, 1)
    inner.setStretchFactor(1, 0)
    inner.setSizes([520, 120])
    inner.setCollapsible(0, False)
    inner.setCollapsible(1, False)

    chat_layout.addWidget(inner)
    splitter.addWidget(chat_widget)
    splitter.setStretchFactor(0, 0)
    splitter.setStretchFactor(1, 0)
    splitter.setStretchFactor(2, 1)
    splitter.setSizes(
        [
            120,
            min(self.context_panel.preferred_height(), _CONTEXT_PANEL_MAX_HEIGHT),
            760,
        ]
    )

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

    model_visible = int(sizes[0]) > 8
    min_model = _MODEL_PANEL_MIN_HEIGHT if model_visible else 0
    min_chat = _CHAT_PANEL_MIN_HEIGHT
    min_ctx = _CONTEXT_PANEL_MIN_HEIGHT
    max_ctx = max(min_ctx, total - (min_model + min_chat))
    soft_ctx_cap = max(
        min_ctx,
        min(_CONTEXT_PANEL_MAX_HEIGHT, int(total * _CONTEXT_PANEL_MAX_SHARE)),
    )
    ctx_height = max(min_ctx, min(int(height), max_ctx, soft_ctx_cap))
    remaining = max(min_model + min_chat, total - ctx_height)

    model_target = int(sizes[0]) if model_visible else 0
    chat_target = sizes[2]
    model_chat_total = model_target + chat_target
    if model_visible:
        if model_chat_total <= 0:
            model_target = max(min_model, remaining // 4)
        else:
            ratio = model_target / model_chat_total
            model_target = int(round(remaining * ratio))

        model_target = max(
            min_model,
            min(model_target, max(min_model, remaining - min_chat)),
        )
    else:
        model_target = 0
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
        "gegen ausgewählte Dokumente/RAG-Quellen.\n"
        "Beim Start wählst du per Checkliste eine oder mehrere Methoden.\n"
        "Hinweis: LLM (Chunk-weise) ist sehr langsam."
    )
    self.fact_btn.clicked.connect(self._send_fact_check)

    self.claim_precompute_btn = QPushButton("Claims vorkalk.")
    self.claim_precompute_btn.setStyleSheet(BTN_NEUTRAL)
    self.claim_precompute_btn.setToolTip(
        "Extrahiert atomare Claims pro ausgewähltem Quell-Chunk und speichert sie im Cache.\n"
        "Kann unabhängig vom Faktencheck laufen und wird für weitere Features wiederverwendet."
    )
    self.claim_precompute_btn.clicked.connect(self._send_claim_precompute)

    self.glossary_btn = QPushButton("Glossar")
    self.glossary_btn.setStyleSheet(BTN_NEUTRAL)
    self.glossary_btn.setToolTip(
        "Erstellt ein Glossar nur aus den aktuell ausgewählten Kontextquellen."
    )
    self.glossary_btn.clicked.connect(self._send_glossary_generation)

    self.mindmap_btn = QPushButton("MindMap/Graph/Chunk")
    self.mindmap_btn.setStyleSheet(BTN_NEUTRAL)
    self.mindmap_btn.setToolTip(
        "Erstellt MindMap/Graph/Chunk-MindMap nur aus den aktuell ausgewählten Kontextquellen.\n"
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
    task_row.addWidget(self.claim_precompute_btn)
    task_row.addWidget(self.glossary_btn)
    task_row.addWidget(self.mindmap_btn)
    task_row.addStretch()
    layout.addLayout(task_row)
    return area

def _connect_signals(self):
    self.model_panel.load_requested.connect(
        lambda path, params: self.llm.load_model(path, **params)
    )
    self.model_panel.nli_load_requested.connect(
        lambda model_id, params: self.llm.load_nli_model(model_id, **params)
    )
    self.llm.model_loaded.connect(self.model_panel.on_model_loaded)
    self.llm.nli_model_loaded.connect(self.model_panel.on_nli_model_loaded)
    self.llm.token_received.connect(self._on_token)
    self.llm.generation_complete.connect(self._on_complete)
    self.llm.error_occurred.connect(self._on_error)
    self.llm.is_generating.connect(self._on_generating)
    self.history.feedback_submitted.connect(self._on_chat_feedback_submitted)

    shortcut = QShortcut(QKeySequence("Ctrl+Return"), self.input_box)
    shortcut.activated.connect(self._send)

__all__ = [
    "_setup_dock",
    "_normalize_context_text",
    "_apply_context_panel_height",
    "_build_input_area",
    "_connect_signals",
]
