"""ChatDock method implementations."""
from __future__ import annotations

import json
import os

from .deps import *  # noqa: F403

_GEN_DIALOG_SETTINGS_KEY = "chat/generation_dialog_v2"
_GEN_DIALOG_TAB_ORDER = ("factcheck", "glossary", "mindmap", "graph", "chunkmap")
_FACTCHECK_METHOD_KEYS = ("nli", "llm_claim_nli", "llm_global", "llm_chunk")


def _env_flag(name: str) -> bool:
    return str(os.environ.get(name, "")).strip().casefold() in {"1", "true", "yes", "on"}


def _generation_settings_store(self):
    parent_fn = getattr(self, "parent", None)
    host = parent_fn() if callable(parent_fn) else None
    app_settings = getattr(host, "_app_settings", None)
    if app_settings is not None and hasattr(app_settings, "value") and hasattr(app_settings, "setValue"):
        return app_settings
    return QSettings("draft2craift", "draft2craift")


def _recommended_map_defaults(*, mode: str) -> dict[str, object]:
    mode_clean = str(mode or "").strip().casefold()
    base: dict[str, object] = {
        "map_depth": 2,
        "retrieval_strategy": "agent",
        "factcheck": True,
        "max_nodes": 32,
        "max_refinement_rounds": 1,
        "use_full_context": False,
        "context_max_chars": 50_000,
        "allow_rag_search": True,
        "allow_regex_search": True,
        "allow_heading_search": True,
        "allow_full_text_search": True,
        "allow_query_narrowing": True,
        "allow_heading_summaries": True,
        "agent_max_regex_calls": 0,
        "budget_seconds": 54.0,
        "agent_budget_points": 18.0,
        "log_draft_markdown": False,
    }
    if mode_clean == "graph":
        base["max_nodes"] = 28
        base["budget_seconds"] = 48.0
        base["agent_budget_points"] = 16.0
    elif mode_clean == "chunkmap":
        base["map_depth"] = 1
        base["retrieval_strategy"] = "none"
        base["factcheck"] = False
        base["max_refinement_rounds"] = 0
        base["use_full_context"] = True
        base["context_max_chars"] = 120_000
        base["agent_max_regex_calls"] = 0
        base["budget_seconds"] = 36.0
        base["agent_budget_points"] = 12.0
    return base


def _default_generation_dialog_state(self) -> dict[str, object]:
    return {
        "last_tab": "mindmap",
        "factcheck": {
            "methods": ["nli", "llm_claim_nli"],
        },
        "glossary": {
            "query": "",
            "max_terms": 32,
        },
        "mindmap": {
            "query": "",
            "options": _recommended_map_defaults(mode="mindmap"),
        },
        "graph": {
            "query": "",
            "options": _recommended_map_defaults(mode="graph"),
        },
        "chunkmap": {
            "query": "",
            "options": _recommended_map_defaults(mode="chunkmap"),
        },
    }


def _load_generation_dialog_state(self) -> dict[str, object]:
    defaults = _default_generation_dialog_state(self)
    settings = _generation_settings_store(self)
    raw = settings.value(_GEN_DIALOG_SETTINGS_KEY, "")
    if isinstance(raw, dict):
        loaded = dict(raw)
    else:
        loaded = {}
        try:
            loaded = dict(json.loads(str(raw or "")) or {})
        except Exception:
            loaded = {}
    if not loaded:
        return defaults

    merged = dict(defaults)
    last_tab = str(loaded.get("last_tab", merged.get("last_tab", "mindmap")) or "").strip().casefold()
    if last_tab in _GEN_DIALOG_TAB_ORDER:
        merged["last_tab"] = last_tab

    loaded_fact = loaded.get("factcheck", {})
    if isinstance(loaded_fact, dict):
        methods = loaded_fact.get("methods", merged["factcheck"]["methods"])
        if isinstance(methods, (list, tuple, set)):
            clean = [str(m).strip() for m in methods if str(m).strip() in _FACTCHECK_METHOD_KEYS]
            if clean:
                merged["factcheck"]["methods"] = clean

    loaded_glossary = loaded.get("glossary", {})
    if isinstance(loaded_glossary, dict):
        merged["glossary"]["query"] = str(loaded_glossary.get("query", merged["glossary"]["query"]) or "")
        try:
            merged["glossary"]["max_terms"] = max(
                8,
                min(256, int(loaded_glossary.get("max_terms", merged["glossary"]["max_terms"]) or 32)),
            )
        except (TypeError, ValueError):
            pass

    for mode in ("mindmap", "graph", "chunkmap"):
        loaded_map = loaded.get(mode, {})
        if not isinstance(loaded_map, dict):
            continue
        if "query" in loaded_map:
            merged[mode]["query"] = str(loaded_map.get("query", merged[mode]["query"]) or "")
        loaded_opts = loaded_map.get("options", {})
        if isinstance(loaded_opts, dict):
            opts = dict(merged[mode]["options"])
            try:
                opts.update(
                    {
                        "map_depth": max(0, min(12, int(loaded_opts.get("map_depth", opts["map_depth"]) or 0))),
                        "retrieval_strategy": str(
                            loaded_opts.get("retrieval_strategy", opts["retrieval_strategy"])
                            or opts["retrieval_strategy"]
                        ).strip().casefold(),
                        "factcheck": bool(loaded_opts.get("factcheck", opts["factcheck"])),
                        "max_nodes": max(4, min(512, int(loaded_opts.get("max_nodes", opts["max_nodes"]) or 32))),
                        "max_refinement_rounds": max(
                            0,
                            min(6, int(loaded_opts.get("max_refinement_rounds", opts["max_refinement_rounds"]) or 0)),
                        ),
                        "use_full_context": bool(loaded_opts.get("use_full_context", opts["use_full_context"])),
                        "context_max_chars": max(
                            4_000,
                            min(
                                1_000_000,
                                int(loaded_opts.get("context_max_chars", opts["context_max_chars"]) or 50_000),
                            ),
                        ),
                        "allow_rag_search": bool(loaded_opts.get("allow_rag_search", opts["allow_rag_search"])),
                        "allow_regex_search": bool(
                            loaded_opts.get("allow_regex_search", opts["allow_regex_search"])
                        ),
                        "allow_heading_search": bool(
                            loaded_opts.get("allow_heading_search", opts["allow_heading_search"])
                        ),
                        "allow_full_text_search": bool(
                            loaded_opts.get("allow_full_text_search", opts["allow_full_text_search"])
                        ),
                        "allow_query_narrowing": bool(
                            loaded_opts.get("allow_query_narrowing", opts["allow_query_narrowing"])
                        ),
                        "allow_heading_summaries": bool(
                            loaded_opts.get("allow_heading_summaries", opts["allow_heading_summaries"])
                        ),
                        "agent_max_regex_calls": max(
                            0,
                            min(500, int(loaded_opts.get("agent_max_regex_calls", opts["agent_max_regex_calls"]) or 0)),
                        ),
                        "budget_seconds": max(
                            5.0,
                            min(
                                7200.0,
                                float(
                                    loaded_opts.get(
                                        "budget_seconds",
                                        float(loaded_opts.get("agent_budget_points", opts["agent_budget_points"]) or 0.0)
                                        * 3.0,
                                    )
                                    or 0.0
                                ),
                            ),
                        ),
                        "agent_budget_points": max(
                            1.0,
                            min(
                                500.0,
                                float(loaded_opts.get("agent_budget_points", opts["agent_budget_points"]) or 0.0),
                            ),
                        ),
                        "log_draft_markdown": bool(
                            loaded_opts.get("log_draft_markdown", opts["log_draft_markdown"])
                        ),
                    }
                )
            except (TypeError, ValueError):
                pass
            if opts["retrieval_strategy"] not in {"agent", "rag", "none"}:
                opts["retrieval_strategy"] = str(merged[mode]["options"].get("retrieval_strategy", "agent"))
            merged[mode]["options"] = opts
    return merged


def _save_generation_dialog_state(self, payload: dict[str, object]) -> None:
    settings = _generation_settings_store(self)
    try:
        settings.setValue(_GEN_DIALOG_SETTINGS_KEY, json.dumps(dict(payload or {}), ensure_ascii=True))
        sync_fn = getattr(settings, "sync", None)
        if callable(sync_fn):
            sync_fn()
    except Exception:
        pass

def _resolve_agentic_run_options(
    self,
    *,
    workflow_key: str,
    env_enabled_key: str,
    env_profile_key: str,
    default_profile_id: str,
) -> dict:
    getter = getattr(self, "get_agentic_settings", None)
    if callable(getter):
        try:
            settings = getter()
            run_options_for = getattr(settings, "run_options_for", None)
            if callable(run_options_for):
                options = dict(run_options_for(workflow_key) or {})
                if options:
                    return options
        except Exception:
            pass

    return {
        "enabled": _env_flag(env_enabled_key),
        "profile_id": str(
            os.environ.get(env_profile_key, default_profile_id) or default_profile_id
        ).strip() or default_profile_id,
    }


def _collect_agentic_sources(self, ctx: dict) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    builder = getattr(self, "_build_source_contexts_from_context", None)
    if callable(builder):
        try:
            rows = list(builder(ctx) or [])
            for name, content in rows:
                clean_name = str(name or "").strip()
                clean_content = str(content or "").strip()
                if not clean_name or not clean_content:
                    continue
                out.append((clean_name, clean_content))
        except Exception:
            pass
    for name, content in list(ctx.get("file_contents", []) or []):
        clean_name = str(name or "").strip()
        clean_content = str(content or "").strip()
        if not clean_name or not clean_content:
            continue
        out.append((clean_name, clean_content))
    for path, _score, excerpt in list(ctx.get("rag_results", []) or []):
        label = str(path or "").strip() or "RAG"
        text = str(excerpt or "").strip()
        if text:
            out.append((label, text))
    dedup: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for name, text in out:
        key = (name.casefold(), text)
        if key in seen:
            continue
        seen.add(key)
        dedup.append((name, text))
    return dedup


def _try_send_agentic_chat(self, *, msg: str, ctx: dict) -> bool:
    run_options = _resolve_agentic_run_options(
        self,
        workflow_key="chat",
        env_enabled_key="D2C_AGENTIC_CHAT",
        env_profile_key="D2C_AGENTIC_CHAT_PROFILE",
        default_profile_id="chat_v2_local",
    )
    if not bool(run_options.get("enabled", False)):
        return False
    try:
        from shared.services.agentic import AgenticWorkflowService, build_tools
    except Exception:
        return False
    profile_id = str(
        run_options.get("profile_id", "chat_v2_local")
        or "chat_v2_local"
    ).strip() or "chat_v2_local"
    sources = _collect_agentic_sources(self, ctx)
    try:
        result = AgenticWorkflowService().run_chat(
            request={"question": str(msg or "")},
            profile_id=profile_id,
            enabled=bool(run_options.get("enabled", False)),
            tools=build_tools(
                llm_manager=self.llm,
                source_texts=sources,
            ),
        )
    except Exception:
        return False
    if not bool(result.ok):
        return False

    payload = dict(result.result.get("response", {}) or {})
    answer = str(payload.get("text", "") or "").strip()
    if not answer:
        return False
    citations = list(payload.get("citations", []) or [])
    if citations:
        lines = [answer, "", "Quellen:"]
        for idx, row in enumerate(citations[:5], 1):
            lines.append(f"{idx}. {row}")
        answer = "\n".join(lines)
    self.history.add_message("assistant", answer)
    self._last_assistant_msg = answer
    self._last_use_case = "chat_answer"
    self._maybe_auto_read_response(answer)
    self.history.activate_feedback("chat_answer")
    return True


def _try_send_agentic_canvas(
    self,
    *,
    instruction: str,
    selected_text: str,
    selected_span: tuple[int, int] | None,
    ctx: dict,
) -> bool:
    run_options = _resolve_agentic_run_options(
        self,
        workflow_key="canvas",
        env_enabled_key="D2C_AGENTIC_CANVAS",
        env_profile_key="D2C_AGENTIC_CANVAS_PROFILE",
        default_profile_id="canvas_v2_local",
    )
    if not bool(run_options.get("enabled", False)):
        return False
    if self._selection_apply_handler is None:
        return False
    try:
        from shared.services.agentic import AgenticWorkflowService, build_tools
    except Exception:
        return False

    apply_state: dict[str, object] = {"ok": False, "info": "", "text": ""}

    def _apply_target(text: str):
        ok, info = self._selection_apply_handler(
            str(text or ""),
            str(selected_text or ""),
            selected_span,
        )
        apply_state["ok"] = bool(ok)
        apply_state["info"] = str(info or "")
        apply_state["text"] = str(text or "")
        if not ok:
            raise RuntimeError(str(info or "apply_failed"))

    profile_id = str(
        run_options.get("profile_id", "canvas_v2_local")
        or "canvas_v2_local"
    ).strip() or "canvas_v2_local"
    sources = _collect_agentic_sources(self, ctx)
    try:
        result = AgenticWorkflowService().run_canvas(
            request={
                "instruction": str(instruction or ""),
                "selected_text": str(selected_text or ""),
            },
            profile_id=profile_id,
            enabled=bool(run_options.get("enabled", False)),
            tools=build_tools(
                llm_manager=self.llm,
                source_texts=sources,
                canvas_apply=_apply_target,
            ),
        )
    except Exception:
        return False
    if not bool(result.ok):
        return False
    if not bool(apply_state.get("ok", False)):
        return False

    text = str(apply_state.get("text", "") or "")
    info = str(apply_state.get("info", "") or "")
    self._last_assistant_msg = text
    self._last_use_case = "canvas_edit"
    notify_success = getattr(self, "_notify_canvas_apply_success", None)
    if callable(notify_success):
        notify_success(info)
    else:
        self.history.add_message(
            "system",
            f"✅ Selection updated in draft workspace. {info}".strip(),
        )
        self.history.activate_feedback("canvas_edit")
    return True


def _send_glossary_generation(
    self,
    *,
    query_override: str | None = None,
    options: dict | None = None,
):
    if not self._require_loaded_model():
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

    query = (
        str(query_override).strip()
        if query_override is not None
        else ""
    )
    if query:
        self.history.add_message(
            "user",
            f"Glossar aus aktuellem Kontext\nFokus: {query}",
        )
    else:
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

    payload_options = dict(options or {}) if isinstance(options, dict) else None
    ok, info = self._glossary_request_handler(ctx, query, payload_options, done)
    if ok:
        self.history.add_message("system", "⏳ Glossar wird erstellt…")
        return
    self.history.add_message("system", f"⚠ Glossar fehlgeschlagen: {info}")

def _send_claim_precompute(self):
    if not self._require_loaded_model():
        return
    if self._aux_generating:
        self.history.add_message(
            "system",
            "⚠ Eine Hintergrundaufgabe läuft bereits. Bitte kurz warten.",
        )
        return
    if bool(getattr(self, "_pending_fact_check", False)):
        self.history.add_message(
            "system",
            "⚠ Faktencheck läuft bereits. Bitte zuerst abschließen.",
        )
        return
    if bool(getattr(self, "_pending_chunk_claim_precompute", False)):
        self.history.add_message(
            "system",
            "⚠ Chunk-Claim-Vorkalkulation läuft bereits.",
        )
        return
    if self.llm.worker.isRunning():
        self.history.add_message(
            "system",
            "⚠ Modell ist beschäftigt. Bitte nach aktueller Generation erneut versuchen.",
        )
        return

    ctx = self._collect_shared_context()
    if not bool(ctx.get("grounding_has_sources", False)):
        self.history.add_message(
            "system",
            "⚠ Keine Quellen ausgewählt. Bitte Dokumente und/oder RAG-Kontext aktivieren.",
        )
        return
    sources = self._build_source_contexts_from_context(ctx)
    if not sources:
        self.history.add_message(
            "system",
            "⚠ Keine verwertbaren Quelltexte für die Claim-Vorkalkulation gefunden.",
        )
        return

    ok, info = self._start_chunk_claim_precompute(sources)
    if ok:
        if "Cache vollständig" in str(info):
            self.history.add_message("system", f"ℹ {info}")
        else:
            self.history.add_message("system", f"⏳ {info}")
        return
    self.history.add_message("system", f"⚠ Claim-Vorkalkulation fehlgeschlagen: {info}")

def _build_map_generation_tab(
    self,
    *,
    mode: str,
    state: dict[str, object],
    parent=None,
) -> dict[str, object]:
    mode_clean = str(mode or "").strip().casefold()
    is_chunk_mode = mode_clean == "chunkmap"
    mode_title = {
        "mindmap": "MindMap",
        "graph": "Wissensgraph",
        "chunkmap": "Chunk-Darstellung",
    }.get(mode_clean, "MindMap")

    defaults = dict(_recommended_map_defaults(mode=mode_clean))
    saved_options = state.get("options", {}) if isinstance(state.get("options", {}), dict) else {}
    options = dict(defaults)
    options.update(dict(saved_options))
    query_default = str(state.get("query", "") or "")

    tab = QWidget(parent)
    layout = QVBoxLayout(tab)
    layout.setContentsMargins(8, 8, 8, 8)
    layout.setSpacing(8)

    intro = QLabel(
        f"{mode_title}: Agentischer Lauf mit steuerbaren Retrieval-/Budget-Parametern.",
        tab,
    )
    intro.setWordWrap(True)
    layout.addWidget(intro)

    query_edit = QPlainTextEdit(tab)
    query_edit.setPlaceholderText("Optionale Fokusfrage (leer = automatischer Überblick)")
    query_edit.setPlainText(query_default)
    query_edit.setMaximumHeight(72)
    if is_chunk_mode:
        query_edit.setPlaceholderText("Optionaler Fokus für Chunk-Darstellung")
    layout.addWidget(query_edit)

    form = QFormLayout()
    form.setContentsMargins(0, 0, 0, 0)
    form.setSpacing(8)

    depth_widget = QWidget(tab)
    depth_layout = QVBoxLayout(depth_widget)
    depth_layout.setContentsMargins(0, 0, 0, 0)
    depth_layout.setSpacing(4)
    slider = QSlider(Qt.Orientation.Horizontal, depth_widget)
    slider.setRange(0, 6)
    slider.setSingleStep(1)
    slider.setPageStep(1)
    slider.setTickInterval(1)
    slider.setTickPosition(QSlider.TickPosition.TicksBelow)
    slider.setValue(max(0, min(6, int(options.get("map_depth", defaults["map_depth"]) or 0))))
    depth_layout.addWidget(slider)
    depth_value = QLabel(depth_widget)
    depth_layout.addWidget(depth_value)
    form.addRow("Ausbautiefe:", depth_widget)

    retrieval_combo = QComboBox(tab)
    retrieval_combo.addItem("Agent wählt Tools", "agent")
    retrieval_combo.addItem("Klassisch RAG", "rag")
    retrieval_combo.addItem("Kein Retrieval", "none")
    retrieval_idx = retrieval_combo.findData(
        str(options.get("retrieval_strategy", defaults["retrieval_strategy"]) or "agent").strip().casefold()
    )
    retrieval_combo.setCurrentIndex(retrieval_idx if retrieval_idx >= 0 else 0)
    form.addRow("Retrieval:", retrieval_combo)

    factcheck_cb = QCheckBox("Faktenprüfung aktivieren", tab)
    factcheck_cb.setChecked(bool(options.get("factcheck", defaults["factcheck"])))
    form.addRow("Qualität:", factcheck_cb)

    max_nodes_spin = QSpinBox(tab)
    max_nodes_spin.setRange(4, 512)
    max_nodes_spin.setSingleStep(4)
    max_nodes_spin.setValue(max(4, min(512, int(options.get("max_nodes", defaults["max_nodes"]) or 32))))
    form.addRow("Max. Knoten:", max_nodes_spin)

    max_ref_spin = QSpinBox(tab)
    max_ref_spin.setRange(0, 6)
    max_ref_spin.setValue(
        max(0, min(6, int(options.get("max_refinement_rounds", defaults["max_refinement_rounds"]) or 0)))
    )
    form.addRow("Refinement-Runden:", max_ref_spin)

    use_full_context_cb = QCheckBox("Gesamten Kontext an Generation geben", tab)
    use_full_context_cb.setChecked(bool(options.get("use_full_context", defaults["use_full_context"])))
    form.addRow("Kontextmodus:", use_full_context_cb)

    context_max_chars_spin = QSpinBox(tab)
    context_max_chars_spin.setRange(4_000, 1_000_000)
    context_max_chars_spin.setSingleStep(2_000)
    context_max_chars_spin.setValue(
        max(4_000, min(1_000_000, int(options.get("context_max_chars", defaults["context_max_chars"]) or 50_000)))
    )
    context_max_chars_spin.setSuffix(" Zeichen")
    form.addRow("Kontext-Limit:", context_max_chars_spin)

    agent_tools_row = QWidget(tab)
    agent_tools_layout = QHBoxLayout(agent_tools_row)
    agent_tools_layout.setContentsMargins(0, 0, 0, 0)
    agent_tools_layout.setSpacing(8)
    allow_rag_cb = QCheckBox("Vektor/RAG", agent_tools_row)
    allow_rag_cb.setChecked(bool(options.get("allow_rag_search", defaults["allow_rag_search"])))
    agent_tools_layout.addWidget(allow_rag_cb)
    allow_regex_cb = QCheckBox("Regex", agent_tools_row)
    allow_regex_cb.setChecked(bool(options.get("allow_regex_search", defaults["allow_regex_search"])))
    agent_tools_layout.addWidget(allow_regex_cb)
    allow_heading_cb = QCheckBox("Überschriften", agent_tools_row)
    allow_heading_cb.setChecked(bool(options.get("allow_heading_search", defaults["allow_heading_search"])))
    agent_tools_layout.addWidget(allow_heading_cb)
    allow_full_text_cb = QCheckBox("Volltext", agent_tools_row)
    allow_full_text_cb.setChecked(bool(options.get("allow_full_text_search", defaults["allow_full_text_search"])))
    agent_tools_layout.addWidget(allow_full_text_cb)
    agent_tools_layout.addStretch()
    form.addRow("Agent-Tools:", agent_tools_row)

    agent_search_row = QWidget(tab)
    agent_search_layout = QHBoxLayout(agent_search_row)
    agent_search_layout.setContentsMargins(0, 0, 0, 0)
    agent_search_layout.setSpacing(8)
    allow_narrowing_cb = QCheckBox("Suche einschränken", agent_search_row)
    allow_narrowing_cb.setChecked(bool(options.get("allow_query_narrowing", defaults["allow_query_narrowing"])))
    agent_search_layout.addWidget(allow_narrowing_cb)
    allow_heading_summary_cb = QCheckBox("Abschnitts-Inhalte laden", agent_search_row)
    allow_heading_summary_cb.setChecked(
        bool(options.get("allow_heading_summaries", defaults["allow_heading_summaries"]))
    )
    agent_search_layout.addWidget(allow_heading_summary_cb)
    agent_search_layout.addStretch()
    form.addRow("Suche-Optionen:", agent_search_row)

    agent_budget_row = QWidget(tab)
    agent_budget_layout = QHBoxLayout(agent_budget_row)
    agent_budget_layout.setContentsMargins(0, 0, 0, 0)
    agent_budget_layout.setSpacing(8)
    agent_budget_layout.addWidget(QLabel("Regex-Limit:", agent_budget_row))
    regex_limit_spin = QSpinBox(agent_budget_row)
    regex_limit_spin.setRange(0, 500)
    regex_limit_spin.setSpecialValueText("unbegrenzt")
    regex_limit_spin.setValue(
        max(0, min(500, int(options.get("agent_max_regex_calls", defaults["agent_max_regex_calls"]) or 0)))
    )
    agent_budget_layout.addWidget(regex_limit_spin)
    agent_budget_layout.addWidget(QLabel("Budget:", agent_budget_row))
    budget_spin = QDoubleSpinBox(agent_budget_row)
    budget_spin.setRange(5.0, 7200.0)
    budget_spin.setDecimals(0)
    budget_spin.setSingleStep(5.0)
    _budget_default_s = float(options.get("budget_seconds", float(options.get("agent_budget_points", defaults["agent_budget_points"]) or 0.0) * 3.0) or 0.0)
    budget_spin.setValue(
        max(5.0, min(7200.0, _budget_default_s))
    )
    budget_spin.setSuffix(" Sek.")
    budget_spin.setToolTip(
        "Erwartete maximale Laufzeit in Sekunden.\n"
        "Das System misst echte LLM-Aufrufzeiten und reguliert die Schleife\n"
        "automatisch innerhalb dieses Zeitbudgets."
    )
    agent_budget_layout.addWidget(budget_spin)
    agent_budget_layout.addStretch()
    form.addRow("Agent-Budget:", agent_budget_row)

    log_draft_cb = QCheckBox("Rohentwurf im Laufartefakt speichern", tab)
    log_draft_cb.setChecked(bool(options.get("log_draft_markdown", defaults["log_draft_markdown"])))
    log_draft_cb.setToolTip(
        "Speichert den generierten Rohentwurf nur für Diagnosezwecke im Laufartefakt. "
        "Standardmäßig bleibt das aus."
    )
    form.addRow("Diagnose:", log_draft_cb)

    if mode_clean == "chunkmap":
        retrieval_idx_none = retrieval_combo.findData("none")
        if retrieval_idx_none >= 0:
            retrieval_combo.setCurrentIndex(retrieval_idx_none)
        retrieval_combo.setEnabled(False)
        factcheck_cb.setChecked(False)
        factcheck_cb.setEnabled(False)
        max_nodes_spin.setMinimum(0)
        max_nodes_spin.setValue(0)
        max_nodes_spin.setEnabled(False)
        max_ref_spin.setValue(0)
        max_ref_spin.setEnabled(False)
        use_full_context_cb.setChecked(True)
        use_full_context_cb.setEnabled(False)
        factcheck_cb.setToolTip("In der Chunk-Darstellung wird kein separates Faktchecking durchgeführt.")
        max_nodes_spin.setToolTip("Für Chunk-Darstellung wird die Knotenanzahl automatisch aus dem Chunking abgeleitet.")

    def _sync_depth_label(value: int) -> None:
        depth_value.setText(f"Tiefe: {int(value)}")

    def _sync_agent_controls() -> None:
        retrieval_mode = str(retrieval_combo.currentData() or "").strip().casefold()
        is_agent = (retrieval_mode == "agent") and (not is_chunk_mode)
        context_limit_relevant = bool(use_full_context_cb.isChecked()) or retrieval_mode == "none" or is_chunk_mode
        has_agent_tool = bool(
            allow_rag_cb.isChecked()
            or allow_regex_cb.isChecked()
            or allow_heading_cb.isChecked()
            or allow_full_text_cb.isChecked()
        )
        allow_rag_cb.setEnabled(is_agent)
        allow_regex_cb.setEnabled(is_agent)
        allow_heading_cb.setEnabled(is_agent)
        allow_full_text_cb.setEnabled(is_agent)
        allow_narrowing_cb.setEnabled(is_agent)
        allow_heading_summary_cb.setEnabled(is_agent and bool(allow_heading_cb.isChecked()))
        regex_limit_spin.setEnabled(is_agent and bool(allow_regex_cb.isChecked()))
        budget_spin.setEnabled(is_agent and has_agent_tool)
        context_max_chars_spin.setEnabled(context_limit_relevant and (not is_chunk_mode or use_full_context_cb.isChecked()))
        max_ref_spin.setEnabled(bool(factcheck_cb.isEnabled()) and bool(factcheck_cb.isChecked()))

    def _collect() -> dict[str, object]:
        retrieval_value = str(retrieval_combo.currentData() or "rag")
        factcheck_value = bool(factcheck_cb.isChecked())
        max_nodes_value = int(max_nodes_spin.value())
        max_ref_value = int(max_ref_spin.value())
        use_full_context_value = bool(use_full_context_cb.isChecked())
        if not factcheck_value:
            max_ref_value = 0
        if is_chunk_mode:
            retrieval_value = "none"
            factcheck_value = False
            max_nodes_value = 0
            max_ref_value = 0
            use_full_context_value = True
        return {
            "query": str(query_edit.toPlainText() or "").strip(),
            "options": {
                "map_depth": int(slider.value()),
                "retrieval_strategy": retrieval_value,
                "factcheck": factcheck_value,
                "max_nodes": max_nodes_value,
                "max_refinement_rounds": max_ref_value,
                "use_full_context": use_full_context_value,
                "context_max_chars": int(context_max_chars_spin.value()),
                "allow_rag_search": bool(allow_rag_cb.isChecked()),
                "allow_regex_search": bool(allow_regex_cb.isChecked()),
                "allow_heading_search": bool(allow_heading_cb.isChecked()),
                "allow_full_text_search": bool(allow_full_text_cb.isChecked()),
                "allow_query_narrowing": bool(allow_narrowing_cb.isChecked()),
                "allow_heading_summaries": bool(allow_heading_summary_cb.isChecked()),
                "agent_max_regex_calls": int(regex_limit_spin.value()),
                "budget_seconds": float(budget_spin.value()),
                "agent_budget_points": float(budget_spin.value()) / 3.0,
                "log_draft_markdown": bool(log_draft_cb.isChecked()),
            },
        }

    def _apply(payload: dict[str, object]) -> None:
        tab_query = str(payload.get("query", "") or "")
        tab_opts = payload.get("options", {}) if isinstance(payload.get("options", {}), dict) else {}
        if is_chunk_mode:
            tab_opts = dict(tab_opts)
            tab_opts["retrieval_strategy"] = "none"
            tab_opts["factcheck"] = False
            tab_opts["max_nodes"] = 0
            tab_opts["max_refinement_rounds"] = 0
            tab_opts["use_full_context"] = True
        query_edit.setPlainText(tab_query)
        slider.setValue(max(0, min(6, int(tab_opts.get("map_depth", defaults["map_depth"]) or 0))))
        retrieval_idx_local = retrieval_combo.findData(
            str(tab_opts.get("retrieval_strategy", defaults["retrieval_strategy"]) or "agent").strip().casefold()
        )
        retrieval_combo.setCurrentIndex(retrieval_idx_local if retrieval_idx_local >= 0 else 0)
        factcheck_cb.setChecked(bool(tab_opts.get("factcheck", defaults["factcheck"])))
        max_nodes_spin.setValue(max(4, min(512, int(tab_opts.get("max_nodes", defaults["max_nodes"]) or 32))))
        max_ref_spin.setValue(
            max(0, min(6, int(tab_opts.get("max_refinement_rounds", defaults["max_refinement_rounds"]) or 0)))
        )
        use_full_context_cb.setChecked(bool(tab_opts.get("use_full_context", defaults["use_full_context"])))
        context_max_chars_spin.setValue(
            max(4_000, min(1_000_000, int(tab_opts.get("context_max_chars", defaults["context_max_chars"]) or 50_000)))
        )
        allow_rag_cb.setChecked(bool(tab_opts.get("allow_rag_search", defaults["allow_rag_search"])))
        allow_regex_cb.setChecked(bool(tab_opts.get("allow_regex_search", defaults["allow_regex_search"])))
        allow_heading_cb.setChecked(bool(tab_opts.get("allow_heading_search", defaults["allow_heading_search"])))
        allow_full_text_cb.setChecked(bool(tab_opts.get("allow_full_text_search", defaults["allow_full_text_search"])))
        allow_narrowing_cb.setChecked(bool(tab_opts.get("allow_query_narrowing", defaults["allow_query_narrowing"])))
        allow_heading_summary_cb.setChecked(
            bool(tab_opts.get("allow_heading_summaries", defaults["allow_heading_summaries"]))
        )
        regex_limit_spin.setValue(
            max(0, min(500, int(tab_opts.get("agent_max_regex_calls", defaults["agent_max_regex_calls"]) or 0)))
        )
        _tab_budget_s = float(
            tab_opts.get(
                "budget_seconds",
                float(tab_opts.get("agent_budget_points", defaults["agent_budget_points"]) or 0.0) * 3.0,
            )
            or 0.0
        )
        budget_spin.setValue(
            max(5.0, min(7200.0, _tab_budget_s))
        )
        log_draft_cb.setChecked(bool(tab_opts.get("log_draft_markdown", defaults["log_draft_markdown"])))
        _sync_agent_controls()

    retrieval_combo.currentIndexChanged.connect(_sync_agent_controls)
    allow_heading_cb.toggled.connect(lambda _checked=False: _sync_agent_controls())
    allow_regex_cb.toggled.connect(lambda _checked=False: _sync_agent_controls())
    allow_rag_cb.toggled.connect(lambda _checked=False: _sync_agent_controls())
    allow_full_text_cb.toggled.connect(lambda _checked=False: _sync_agent_controls())
    factcheck_cb.toggled.connect(lambda _checked=False: _sync_agent_controls())
    use_full_context_cb.toggled.connect(lambda _checked=False: _sync_agent_controls())
    slider.valueChanged.connect(_sync_depth_label)
    _sync_depth_label(int(slider.value()))
    _sync_agent_controls()

    layout.addLayout(form)
    layout.addStretch()
    return {"widget": tab, "collect": _collect, "apply": _apply}


def _prompt_generation_control_center(
    self,
    *,
    initial_tab: str = "mindmap",
) -> dict[str, object] | None:
    initial_tab_clean = str(initial_tab or "").strip().casefold()
    state = _load_generation_dialog_state(self)
    if initial_tab_clean in _GEN_DIALOG_TAB_ORDER:
        state["last_tab"] = initial_tab_clean

    dialog = QDialog(self)
    dialog.setWindowTitle("Generierungszentrum")
    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(12, 12, 12, 12)
    layout.setSpacing(10)

    intro = QLabel(
        "Wähle den gewünschten Workflow und konfiguriere die Laufparameter. "
        "Alle Werte werden lokal gespeichert und sind wiederholbar.",
        dialog,
    )
    intro.setWordWrap(True)
    layout.addWidget(intro)

    tabs = QTabWidget(dialog)
    layout.addWidget(tabs)

    tab_index_by_key: dict[str, int] = {}
    map_tabs: dict[str, dict[str, object]] = {}

    # Faktencheck tab
    fact_tab = QWidget(tabs)
    fact_layout = QVBoxLayout(fact_tab)
    fact_layout.setContentsMargins(8, 8, 8, 8)
    fact_layout.setSpacing(8)
    fact_intro = QLabel(
        "Prüft markierten Draft-Text (oder Draft/Prompt-Fallback) gegen aktive Quellen.",
        fact_tab,
    )
    fact_intro.setWordWrap(True)
    fact_layout.addWidget(fact_intro)
    fact_cbs: dict[str, QCheckBox] = {}
    method_labels = dict(getattr(self, "_FACTCHECK_MODE_LABELS", {}) or {})
    selected_methods = state.get("factcheck", {}).get("methods", [])
    selected_set = {
        str(m).strip()
        for m in (selected_methods if isinstance(selected_methods, (list, tuple, set)) else [])
    }
    for method in _FACTCHECK_METHOD_KEYS:
        cb = QCheckBox(method_labels.get(method, method), fact_tab)
        cb.setChecked(method in selected_set)
        fact_cbs[method] = cb
        fact_layout.addWidget(cb)
    fact_layout.addStretch()
    tab_index_by_key["factcheck"] = tabs.addTab(fact_tab, "Faktencheck")

    # Glossar tab
    glossary_tab = QWidget(tabs)
    glossary_layout = QVBoxLayout(glossary_tab)
    glossary_layout.setContentsMargins(8, 8, 8, 8)
    glossary_layout.setSpacing(8)
    glossary_intro = QLabel(
        "Erstellt ein Glossar aus den aktiven Kontextquellen.",
        glossary_tab,
    )
    glossary_intro.setWordWrap(True)
    glossary_layout.addWidget(glossary_intro)
    glossary_query = QPlainTextEdit(glossary_tab)
    glossary_query.setPlaceholderText("Optionale Fokusfrage")
    glossary_query.setMaximumHeight(72)
    glossary_query.setPlainText(str(state.get("glossary", {}).get("query", "") or ""))
    glossary_layout.addWidget(glossary_query)
    glossary_form = QFormLayout()
    glossary_form.setContentsMargins(0, 0, 0, 0)
    glossary_terms = QSpinBox(glossary_tab)
    glossary_terms.setRange(8, 256)
    try:
        glossary_terms.setValue(max(8, min(256, int(state.get("glossary", {}).get("max_terms", 32) or 32))))
    except (TypeError, ValueError):
        glossary_terms.setValue(32)
    glossary_form.addRow("Max. Begriffe:", glossary_terms)
    glossary_layout.addLayout(glossary_form)
    glossary_layout.addStretch()
    tab_index_by_key["glossary"] = tabs.addTab(glossary_tab, "Glossar")

    # MindMap / Graph / Chunk tabs
    for mode, label in (
        ("mindmap", "MindMap"),
        ("graph", "Wissensgraph"),
        ("chunkmap", "Chunk-Darstellung"),
    ):
        mode_state = state.get(mode, {})
        tab_parts = _build_map_generation_tab(
            self,
            mode=mode,
            state=dict(mode_state if isinstance(mode_state, dict) else {}),
            parent=tabs,
        )
        map_tabs[mode] = tab_parts
        tab_index_by_key[mode] = tabs.addTab(tab_parts["widget"], label)

    def _collect_state() -> dict[str, object]:
        out: dict[str, object] = {
            "last_tab": "mindmap",
            "factcheck": {"methods": []},
            "glossary": {
                "query": str(glossary_query.toPlainText() or "").strip(),
                "max_terms": int(glossary_terms.value()),
            },
        }
        current_idx = int(tabs.currentIndex())
        for key, idx in tab_index_by_key.items():
            if idx == current_idx:
                out["last_tab"] = key
                break
        methods = [k for k in _FACTCHECK_METHOD_KEYS if fact_cbs.get(k) is not None and fact_cbs[k].isChecked()]
        out["factcheck"]["methods"] = methods
        for mode in ("mindmap", "graph", "chunkmap"):
            collector = map_tabs[mode]["collect"]
            out[mode] = dict(collector())
        return out

    def _apply_state(payload: dict[str, object]) -> None:
        fact_payload = payload.get("factcheck", {})
        method_set = set(
            str(m).strip()
            for m in (
                fact_payload.get("methods", [])
                if isinstance(fact_payload, dict)
                and isinstance(fact_payload.get("methods", []), (list, tuple, set))
                else []
            )
        )
        for key, cb in fact_cbs.items():
            cb.setChecked(key in method_set)
        glossary_payload = payload.get("glossary", {})
        if isinstance(glossary_payload, dict):
            glossary_query.setPlainText(str(glossary_payload.get("query", "") or ""))
            try:
                glossary_terms.setValue(max(8, min(256, int(glossary_payload.get("max_terms", 32) or 32))))
            except (TypeError, ValueError):
                glossary_terms.setValue(32)
        for mode in ("mindmap", "graph", "chunkmap"):
            mode_payload = payload.get(mode, {})
            if not isinstance(mode_payload, dict):
                mode_payload = {}
            applier = map_tabs[mode]["apply"]
            applier(dict(mode_payload))
        tab_key = str(payload.get("last_tab", "mindmap") or "mindmap").strip().casefold()
        if tab_key in tab_index_by_key:
            tabs.setCurrentIndex(int(tab_index_by_key[tab_key]))

    button_row = QHBoxLayout()
    button_row.setContentsMargins(0, 0, 0, 0)
    button_row.setSpacing(8)
    reset_btn = QPushButton("Reset auf Standard", dialog)
    cancel_btn = QPushButton("Abbrechen", dialog)
    start_btn = QPushButton("Starte Generierung", dialog)
    start_btn.setStyleSheet(BTN_PRIMARY)
    button_row.addWidget(reset_btn)
    button_row.addStretch()
    button_row.addWidget(cancel_btn)
    button_row.addWidget(start_btn)
    layout.addLayout(button_row)

    result: dict[str, object] = {}

    def _handle_reset() -> None:
        _apply_state(_default_generation_dialog_state(self))

    def _handle_start() -> None:
        collected = _collect_state()
        tab_key = str(collected.get("last_tab", "mindmap") or "mindmap").strip().casefold()
        if tab_key == "factcheck":
            methods = list(collected.get("factcheck", {}).get("methods", []) or [])
            if not methods:
                self.history.add_message(
                    "system",
                    "⚠ Faktencheck: Bitte mindestens eine Methode auswählen.",
                )
                return
        if tab_key in {"mindmap", "graph", "chunkmap"}:
            map_payload = collected.get(tab_key, {})
            options = map_payload.get("options", {}) if isinstance(map_payload, dict) else {}
            retrieval_mode = str(options.get("retrieval_strategy", "rag") or "rag").strip().casefold()
            if retrieval_mode == "agent":
                has_agent_tool = bool(
                    options.get("allow_rag_search", False)
                    or options.get("allow_regex_search", False)
                    or options.get("allow_heading_search", False)
                    or options.get("allow_full_text_search", False)
                )
                if not has_agent_tool:
                    self.history.add_message(
                        "system",
                        "⚠ Agent-Retrieval benötigt mindestens ein aktives Tool (RAG/Regex/Überschriften/Volltext).",
                    )
                    return
        _save_generation_dialog_state(self, collected)
        if tab_key == "factcheck":
            result.update(
                {
                    "action": "factcheck",
                    "methods": list(collected.get("factcheck", {}).get("methods", []) or []),
                }
            )
        elif tab_key == "glossary":
            result.update(
                {
                    "action": "glossary",
                    "query": str(collected.get("glossary", {}).get("query", "") or "").strip(),
                    "options": {
                        "max_terms": int(collected.get("glossary", {}).get("max_terms", 32) or 32),
                    },
                }
            )
        else:
            map_payload = collected.get(tab_key, {})
            if not isinstance(map_payload, dict):
                map_payload = {}
            result.update(
                {
                    "action": "mindmap",
                    "mode": tab_key,
                    "query": str(map_payload.get("query", "") or "").strip(),
                    "map_options": dict(map_payload.get("options", {}) or {}),
                }
            )
        dialog.accept()

    _apply_state(state)
    reset_btn.clicked.connect(_handle_reset)
    cancel_btn.clicked.connect(dialog.reject)
    start_btn.clicked.connect(_handle_start)

    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    return result if result else None


def _start_map_generation_from_selection(
    self,
    *,
    ctx: dict,
    mode: str,
    query: str,
    map_options: dict[str, object] | None = None,
) -> None:
    mode_clean = str(mode or "mindmap").strip().casefold()
    mode_label = {
        "mindmap": "MindMap",
        "graph": "Wissensgraph",
        "chunkmap": "Chunk-Darstellung",
    }.get(mode_clean, "MindMap")

    if self._mindmap_request_handler is None:
        self.history.add_message(
            "system",
            "⚠ Kein MindMap/Graph-Handler konfiguriert.",
        )
        return
    if not self._require_loaded_model():
        return
    if self.llm.worker.isRunning():
        self.history.add_message(
            "system",
            "⚠ Modell ist beschäftigt. Bitte nach aktueller Generation erneut versuchen.",
        )
        return

    query_text = str(query or "").strip()
    if query_text:
        self.history.add_message(
            "user",
            f"{mode_label} aus aktuellem Kontext\nQuery: {query_text}",
        )
    else:
        self.history.add_message("user", f"{mode_label} aus aktuellem Kontext")

    self.history.reset_feedback()
    map_payload = dict(map_options or {})
    map_depth = int(map_payload.get("map_depth", 0) or 0)

    def done(ok: bool, info: str):
        if ok:
            self._last_use_case = "mindmap"
            detail = str(info or "").strip()
            message = f"✅ {mode_label} erstellt."
            if detail:
                message = f"{message}\n{detail}"
            self.history.add_message("system", message)
            self.history.activate_feedback("mindmap")
            return
        self.history.add_message("system", f"⚠ {mode_label} fehlgeschlagen: {info}")

    ok, info = self._mindmap_request_handler(
        ctx,
        query_raw=query_text,
        mode_hint=mode_clean,
        map_depth=map_depth,
        map_options=map_payload,
        done_cb=done,
    )
    if ok:
        self.history.add_message("system", f"⏳ {mode_label} wird erstellt…")
        return
    self.history.add_message("system", f"⚠ {mode_label} fehlgeschlagen: {info}")


def _open_generation_control_center(
    self,
    _checked: bool = False,
    *,
    initial_tab: str = "mindmap",
    require_model_on_open: bool = False,
):
    _ = _checked
    if self._aux_generating:
        self.history.add_message(
            "system",
            "⚠ Eine Hintergrundaufgabe läuft bereits. Bitte kurz warten.",
        )
        return
    if require_model_on_open and not self._require_loaded_model():
        return

    ctx = self._collect_shared_context()
    if not self._has_any_context_content(ctx):
        self.history.add_message(
            "system",
            "⚠ Kein Kontext ausgewählt. Bitte im Context-Bereich Quellen aktivieren.",
        )
        return

    selection = _prompt_generation_control_center(self, initial_tab=initial_tab)
    if not selection:
        return
    action = str(selection.get("action", "") or "").strip().casefold()
    if action == "factcheck":
        sender = getattr(self, "_send_fact_check", None)
        if callable(sender):
            sender(selected_methods=list(selection.get("methods", []) or []))
        else:
            self.history.add_message(
                "system",
                "⚠ Faktencheck-Funktion ist nicht verfügbar.",
            )
        return
    if action == "glossary":
        _send_glossary_generation(
            self,
            query_override=str(selection.get("query", "") or "").strip(),
            options=dict(selection.get("options", {}) or {}),
        )
        return
    _start_map_generation_from_selection(
        self,
        ctx=ctx,
        mode=str(selection.get("mode", "mindmap") or "mindmap"),
        query=str(selection.get("query", "") or ""),
        map_options=dict(selection.get("map_options", {}) or {}),
    )


def _send_mindmap_generation(self):
    # Dedicated quick-entry for map workflows: fail early when no model is loaded.
    _open_generation_control_center(
        self,
        initial_tab="mindmap",
        require_model_on_open=True,
    )

def _send(self):
    msg = self.input_box.toPlainText().strip()
    if not msg:
        return

    self._last_user_msg = msg
    self._last_use_case = "chat_answer"
    self.history.reset_feedback()
    self._reset_fact_pipeline_state()
    if not self._require_loaded_model():
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
    if selection_apply_mode and _try_send_agentic_canvas(
        self,
        instruction=msg,
        selected_text=str(selected_text or ""),
        selected_span=selected_span,
        ctx=ctx,
    ):
        return
    if (not selection_apply_mode) and _try_send_agentic_chat(
        self,
        msg=msg,
        ctx=ctx,
    ):
        return
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

__all__ = [
    "_send_glossary_generation",
    "_send_claim_precompute",
    "_open_generation_control_center",
    "_send_mindmap_generation",
    "_send",
]
