"""Dialog for configuring agentic workflow runtime behavior."""
from __future__ import annotations

from collections.abc import Mapping, Sequence

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from shared.domain.user_mode import (
    default_user_mode,
    normalize_user_mode,
    resolve_feature_label,
)
from shared.services.agentic.settings import AgenticRuntimeSettings

_WORKFLOW_ROWS = (
    ("factcheck", "Faktencheck"),
    ("chat", "Chat (Q&A)"),
    ("canvas", "Canvas Rewrite"),
    ("mindmap", "Mindmap/Graph"),
    ("graph", "Graph (Connected)"),
)
_MAP_RESULT_DETAIL_OPTIONS = (
    ("auto", "Automatisch"),
    ("compact", "Kompakt"),
    ("standard", "Standard"),
    ("detailed", "Detailliert"),
)


class AgenticSettingsDialog(QDialog):
    """Edits persistent runtime settings for agentic workflows."""

    def __init__(
        self,
        settings: AgenticRuntimeSettings,
        *,
        profile_ids_by_workflow: Mapping[str, Sequence[str]] | None = None,
        user_mode: str | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._base = settings.clone()
        self._profile_ids_by_workflow = {
            str(key): [
                str(item or "").strip()
                for item in list(values or [])
                if str(item or "").strip()
            ]
            for key, values in dict(profile_ids_by_workflow or {}).items()
        }
        self._user_mode = normalize_user_mode(
            default_user_mode() if user_mode is None else user_mode
        )

        self._intro_label: QLabel | None = None
        self._workflow_group: QGroupBox | None = None
        self._runtime_group: QGroupBox | None = None
        self._map_pro_group: QGroupBox | None = None
        self._buttons_box: QDialogButtonBox | None = None

        self._workflow_enabled: dict[str, QCheckBox] = {}
        self._workflow_profiles: dict[str, QComboBox] = {}
        self._workflow_row_labels: dict[str, QLabel] = {}

        self._runtime_row_labels: dict[str, QLabel] = {}
        self._env_name_edit: QLineEdit | None = None
        self._overlay_profiles_edit: QLineEdit | None = None
        self._strict_policy_cb: QCheckBox | None = None
        self._trace_enabled_cb: QCheckBox | None = None
        self._cache_enabled_cb: QCheckBox | None = None
        self._map_result_detail_combo: QComboBox | None = None

        # Mindmap / Graph pro settings
        self._mindmap_retrieval_combo: QComboBox | None = None
        self._mindmap_agent_iter_spin: QSpinBox | None = None
        self._mindmap_factcheck_cb: QCheckBox | None = None
        self._mindmap_max_nodes_spin: QSpinBox | None = None
        self._mindmap_max_refinements_spin: QSpinBox | None = None
        self._mindmap_use_full_context_cb: QCheckBox | None = None
        self._mindmap_context_max_chars_spin: QSpinBox | None = None
        self._mindmap_agent_allow_rag_cb: QCheckBox | None = None
        self._mindmap_agent_allow_regex_cb: QCheckBox | None = None
        self._mindmap_agent_allow_heading_cb: QCheckBox | None = None
        self._mindmap_agent_allow_full_text_cb: QCheckBox | None = None
        self._mindmap_agent_allow_query_narrowing_cb: QCheckBox | None = None
        self._mindmap_agent_allow_heading_summaries_cb: QCheckBox | None = None
        self._mindmap_agent_max_regex_calls_spin: QSpinBox | None = None
        self._graph_retrieval_combo: QComboBox | None = None
        self._graph_agent_iter_spin: QSpinBox | None = None
        self._graph_factcheck_cb: QCheckBox | None = None
        self._graph_max_nodes_spin: QSpinBox | None = None
        self._graph_use_full_context_cb: QCheckBox | None = None
        self._graph_context_max_chars_spin: QSpinBox | None = None
        self._graph_agent_allow_rag_cb: QCheckBox | None = None
        self._graph_agent_allow_regex_cb: QCheckBox | None = None
        self._graph_agent_allow_heading_cb: QCheckBox | None = None
        self._graph_agent_allow_full_text_cb: QCheckBox | None = None
        self._graph_agent_allow_query_narrowing_cb: QCheckBox | None = None
        self._graph_agent_allow_heading_summaries_cb: QCheckBox | None = None
        self._graph_agent_max_regex_calls_spin: QSpinBox | None = None

        self.resize(800, 720)
        self._build_ui()
        self._load_values()
        self.set_user_mode(self._user_mode)

    def set_user_mode(self, mode: str) -> None:
        self._user_mode = normalize_user_mode(mode)
        self._apply_labels()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        intro = QLabel("")
        intro.setWordWrap(True)
        self._intro_label = intro
        root.addWidget(intro)

        workflows_group = QGroupBox("")
        self._workflow_group = workflows_group
        workflows_form = QFormLayout(workflows_group)
        workflows_form.setHorizontalSpacing(14)
        workflows_form.setVerticalSpacing(8)
        for workflow_key, fallback_label in _WORKFLOW_ROWS:
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(8)

            enabled_cb = QCheckBox("")
            enabled_cb.stateChanged.connect(
                lambda _state=0, key=workflow_key: self._sync_row_enabled_state(key)
            )
            combo = self._new_profile_combo(
                self._profile_ids_by_workflow.get(workflow_key, ())
            )
            row_layout.addWidget(enabled_cb)
            row_layout.addWidget(combo, 1)

            row_label = QLabel(fallback_label)
            workflows_form.addRow(row_label, row_widget)
            self._workflow_enabled[workflow_key] = enabled_cb
            self._workflow_profiles[workflow_key] = combo
            self._workflow_row_labels[workflow_key] = row_label

        root.addWidget(workflows_group)

        runtime_group = QGroupBox("")
        self._runtime_group = runtime_group
        runtime_form = QFormLayout(runtime_group)
        runtime_form.setHorizontalSpacing(14)
        runtime_form.setVerticalSpacing(8)

        env_edit = QLineEdit()
        env_edit.setPlaceholderText("dev / stage / prod")
        runtime_env_label = QLabel("Environment Profil")
        runtime_form.addRow(runtime_env_label, env_edit)
        self._runtime_row_labels["env_name"] = runtime_env_label
        self._env_name_edit = env_edit

        overlay_edit = QLineEdit()
        overlay_edit.setPlaceholderText("profil_a,profil_b")
        runtime_overlay_label = QLabel("Overlay Profile")
        runtime_form.addRow(runtime_overlay_label, overlay_edit)
        self._runtime_row_labels["overlay_profiles"] = runtime_overlay_label
        self._overlay_profiles_edit = overlay_edit

        strict_cb = QCheckBox("")
        runtime_strict_label = QLabel("Strict Policy")
        runtime_form.addRow(runtime_strict_label, strict_cb)
        self._runtime_row_labels["strict_policy"] = runtime_strict_label
        self._strict_policy_cb = strict_cb

        trace_cb = QCheckBox("")
        runtime_trace_label = QLabel("Run Tracing")
        runtime_form.addRow(runtime_trace_label, trace_cb)
        self._runtime_row_labels["trace_enabled"] = runtime_trace_label
        self._trace_enabled_cb = trace_cb

        cache_cb = QCheckBox("")
        runtime_cache_label = QLabel("Tool Cache")
        runtime_form.addRow(runtime_cache_label, cache_cb)
        self._runtime_row_labels["cache_enabled"] = runtime_cache_label
        self._cache_enabled_cb = cache_cb

        detail_combo = QComboBox()
        for value, fallback in _MAP_RESULT_DETAIL_OPTIONS:
            detail_combo.addItem(fallback, value)
        runtime_detail_label = QLabel("Mindmap/Graph Ausgabe")
        runtime_form.addRow(runtime_detail_label, detail_combo)
        self._runtime_row_labels["map_result_detail_level"] = runtime_detail_label
        self._map_result_detail_combo = detail_combo

        root.addWidget(runtime_group)

        # ── Mindmap / Graph pro settings ──────────────────────────────────
        map_pro_group = QGroupBox("Mindmap / Graph — Agenten-Einstellungen (Pro)")
        self._map_pro_group = map_pro_group
        map_pro_outer = QVBoxLayout(map_pro_group)
        map_pro_outer.setContentsMargins(8, 8, 8, 8)
        map_pro_outer.setSpacing(6)

        map_tabs = QTabWidget()
        map_tabs.setDocumentMode(True)
        map_pro_outer.addWidget(map_tabs)

        # ── MindMap tab ────────────────────────────────────────────────────
        mm_tab = QWidget()
        mm_form = QFormLayout(mm_tab)
        mm_form.setHorizontalSpacing(12)
        mm_form.setVerticalSpacing(8)
        mm_form.setContentsMargins(8, 8, 8, 8)

        # Row: Retrieval strategy + agent iterations (tightly coupled)
        mm_retrieval_row = QWidget()
        mm_ret_layout = QHBoxLayout(mm_retrieval_row)
        mm_ret_layout.setContentsMargins(0, 0, 0, 0)
        mm_ret_layout.setSpacing(8)
        mm_retrieval_combo = QComboBox()
        mm_retrieval_combo.addItem("Agent (autonom)", "agent")
        mm_retrieval_combo.addItem("Feste RAG-Suche", "rag")
        mm_retrieval_combo.addItem("Keine Suche", "none")
        mm_retrieval_combo.setToolTip(
            "Retrieval-Strategie vor der MindMap-Generierung:\n"
            "• Agent: LLM wählt selbst Werkzeuge (RAG, Regex, Überschriften, Volltext)\n"
            "• Feste RAG-Suche: klassische Konzept-Extraktion → semantische Suche\n"
            "• Keine Suche: Kontext wird unverändert übergeben"
        )
        self._mindmap_retrieval_combo = mm_retrieval_combo
        mm_ret_layout.addWidget(mm_retrieval_combo)
        mm_ret_layout.addWidget(QLabel("Budget:"))
        mm_iter_spin = QSpinBox()
        mm_iter_spin.setRange(5, 3600)
        mm_iter_spin.setValue(45)
        mm_iter_spin.setSuffix(" Sek.")
        mm_iter_spin.setToolTip(
            "Maximales Zeit-Budget in Sekunden.\n"
            "Das System misst echte LLM-Aufrufzeiten und stoppt automatisch\n"
            "bevor das Budget überschritten wird. Je mehr Zeit, desto besser\n"
            "wird die Karte durch weitere Suchen und Überarbeitungen."
        )
        self._mindmap_agent_iter_spin = mm_iter_spin
        mm_ret_layout.addWidget(mm_iter_spin)
        mm_ret_layout.addStretch()
        mm_form.addRow("Retrieval:", mm_retrieval_row)

        # Row: Quality controls
        mm_quality_row = QWidget()
        mm_qual_layout = QHBoxLayout(mm_quality_row)
        mm_qual_layout.setContentsMargins(0, 0, 0, 0)
        mm_qual_layout.setSpacing(12)
        mm_fact_cb = QCheckBox("Faktentreue-Prüfung")
        mm_fact_cb.setToolTip(
            "Jeder Knoten wird nach der Generierung gegen die Quelldokumente geprüft.\n"
            "Nicht belegte Behauptungen werden in einer Überarbeitungsrunde entfernt."
        )
        mm_fact_cb.setChecked(True)
        self._mindmap_factcheck_cb = mm_fact_cb
        mm_qual_layout.addWidget(mm_fact_cb)
        mm_qual_layout.addWidget(QLabel("Überarbeitungsrunden:"))
        mm_ref_spin = QSpinBox()
        mm_ref_spin.setRange(0, 3)
        mm_ref_spin.setValue(1)
        mm_ref_spin.setSuffix(" Runden")
        mm_ref_spin.setSpecialValueText("kein Überarbeiten")
        mm_ref_spin.setToolTip(
            "Anzahl Faktentreue-Überarbeitungsrunden (0 = deaktiviert).\n"
            "Jede Runde schickt das Ergebnis nochmals durch LLM + Verifikation."
        )
        self._mindmap_max_refinements_spin = mm_ref_spin
        mm_qual_layout.addWidget(mm_ref_spin)
        mm_qual_layout.addStretch()
        mm_form.addRow("Qualität:", mm_quality_row)

        # Row: Node count limit
        mm_nodes_spin = QSpinBox()
        mm_nodes_spin.setRange(8, 200)
        mm_nodes_spin.setValue(32)
        mm_nodes_spin.setSuffix(" Knoten")
        mm_nodes_spin.setToolTip(
            "Maximale Knotenanzahl in der generierten MindMap.\n"
            "Kleinere Werte (20–35) liefern mit kleinen Modellen bessere Ergebnisse."
        )
        self._mindmap_max_nodes_spin = mm_nodes_spin
        mm_form.addRow("Max. Knoten:", mm_nodes_spin)

        # Row: Agent tool toggles
        mm_tools_row = QWidget()
        mm_tools_layout = QHBoxLayout(mm_tools_row)
        mm_tools_layout.setContentsMargins(0, 0, 0, 0)
        mm_tools_layout.setSpacing(10)
        mm_rag_cb = QCheckBox("Vektor/RAG")
        mm_rag_cb.setToolTip("Semantische Vektorsuche (LanceDB / Sentence-Transformers) freigeben.")
        mm_rag_cb.setChecked(True)
        self._mindmap_agent_allow_rag_cb = mm_rag_cb
        mm_tools_layout.addWidget(mm_rag_cb)
        mm_regex_cb = QCheckBox("Regex")
        mm_regex_cb.setToolTip("Reguläre-Ausdrucks-Suche über Quelltexte freigeben.")
        mm_regex_cb.setChecked(True)
        self._mindmap_agent_allow_regex_cb = mm_regex_cb
        mm_tools_layout.addWidget(mm_regex_cb)
        mm_heading_cb = QCheckBox("Überschriften")
        mm_heading_cb.setToolTip("Abschnittsüberschriften-Suche freigeben.")
        mm_heading_cb.setChecked(True)
        self._mindmap_agent_allow_heading_cb = mm_heading_cb
        mm_tools_layout.addWidget(mm_heading_cb)
        mm_full_text_cb = QCheckBox("Volltext")
        mm_full_text_cb.setToolTip(
            "Rohtext-Auszüge freigeben (teuer: ~10 Budgetpunkte pro Aufruf).\n"
            "Nur für sehr langen Kontext sinnvoll."
        )
        mm_full_text_cb.setChecked(True)
        self._mindmap_agent_allow_full_text_cb = mm_full_text_cb
        mm_tools_layout.addWidget(mm_full_text_cb)
        mm_tools_layout.addStretch()
        mm_form.addRow("Agent-Tools:", mm_tools_row)

        # Row: Context settings
        mm_ctx_row = QWidget()
        mm_ctx_layout = QHBoxLayout(mm_ctx_row)
        mm_ctx_layout.setContentsMargins(0, 0, 0, 0)
        mm_ctx_layout.setSpacing(8)
        mm_full_ctx_cb = QCheckBox("Gesamten Kontext übergeben")
        mm_full_ctx_cb.setToolTip(
            "Den gesamten Dokument-Kontext direkt an die Generierung übergeben\n"
            "statt fokussierter Retrieval-Snippets. Für kurze Dokumente empfohlen."
        )
        mm_full_ctx_cb.setChecked(False)
        self._mindmap_use_full_context_cb = mm_full_ctx_cb
        mm_ctx_layout.addWidget(mm_full_ctx_cb)
        mm_ctx_layout.addWidget(QLabel("Limit:"))
        mm_ctx_spin = QSpinBox()
        mm_ctx_spin.setRange(4_000, 1_000_000)
        mm_ctx_spin.setSingleStep(2_000)
        mm_ctx_spin.setValue(50_000)
        mm_ctx_spin.setSuffix(" Zeichen")
        mm_ctx_spin.setToolTip("Maximale Zeichen des Kontextes, der an die Generierung übergeben wird.")
        self._mindmap_context_max_chars_spin = mm_ctx_spin
        mm_ctx_layout.addWidget(mm_ctx_spin)
        mm_ctx_layout.addStretch()
        mm_form.addRow("Kontext:", mm_ctx_row)

        # Row: Search policy options
        mm_policy_row = QWidget()
        mm_policy_layout = QHBoxLayout(mm_policy_row)
        mm_policy_layout.setContentsMargins(0, 0, 0, 0)
        mm_policy_layout.setSpacing(10)
        mm_narrow_cb = QCheckBox("Suche einschränken")
        mm_narrow_cb.setToolTip(
            "Agent darf Suchbegriffe zwischen Iterationen verfeinern/einschränken.\n"
            "Deaktivieren erzwingt, dass die Originalfrage unverändert bleibt."
        )
        mm_narrow_cb.setChecked(True)
        self._mindmap_agent_allow_query_narrowing_cb = mm_narrow_cb
        mm_policy_layout.addWidget(mm_narrow_cb)
        mm_heading_summary_cb = QCheckBox("Abschnitts-Inhalte laden")
        mm_heading_summary_cb.setToolTip(
            "Beim Überschriften-Suchtreffer den zugehörigen Abschnitts-Text mitladen.\n"
            "Deaktivieren liefert nur Überschriftenlisten (schneller, weniger kontextreich)."
        )
        mm_heading_summary_cb.setChecked(True)
        self._mindmap_agent_allow_heading_summaries_cb = mm_heading_summary_cb
        mm_policy_layout.addWidget(mm_heading_summary_cb)
        mm_policy_layout.addWidget(QLabel("Regex-Limit:"))
        mm_regex_limit_spin = QSpinBox()
        mm_regex_limit_spin.setRange(0, 500)
        mm_regex_limit_spin.setValue(4)
        mm_regex_limit_spin.setSpecialValueText("unbegrenzt")
        mm_regex_limit_spin.setToolTip(
            "Maximale Anzahl Regex-Suchen pro Lauf.\n"
            "0 = unbegrenzt. Empfehlung: 4 für kleine Modelle."
        )
        self._mindmap_agent_max_regex_calls_spin = mm_regex_limit_spin
        mm_policy_layout.addWidget(mm_regex_limit_spin)
        mm_policy_layout.addStretch()
        mm_form.addRow("Suche-Optionen:", mm_policy_row)

        map_tabs.addTab(mm_tab, "MindMap")

        # ── Graph tab ──────────────────────────────────────────────────────
        g_tab = QWidget()
        g_form = QFormLayout(g_tab)
        g_form.setHorizontalSpacing(12)
        g_form.setVerticalSpacing(8)
        g_form.setContentsMargins(8, 8, 8, 8)

        # Row: Retrieval strategy + agent iterations
        g_retrieval_row = QWidget()
        g_ret_layout = QHBoxLayout(g_retrieval_row)
        g_ret_layout.setContentsMargins(0, 0, 0, 0)
        g_ret_layout.setSpacing(8)
        g_retrieval_combo = QComboBox()
        g_retrieval_combo.addItem("Agent (autonom)", "agent")
        g_retrieval_combo.addItem("Feste RAG-Suche", "rag")
        g_retrieval_combo.addItem("Keine Suche", "none")
        g_retrieval_combo.setToolTip(
            "Retrieval-Strategie vor der Graph-Generierung:\n"
            "• Agent: LLM wählt selbst Werkzeuge (RAG, Regex, Überschriften, Volltext)\n"
            "• Feste RAG-Suche: klassische Konzept-Extraktion → semantische Suche\n"
            "• Keine Suche: Kontext wird unverändert übergeben"
        )
        self._graph_retrieval_combo = g_retrieval_combo
        g_ret_layout.addWidget(g_retrieval_combo)
        g_ret_layout.addWidget(QLabel("Budget:"))
        g_iter_spin = QSpinBox()
        g_iter_spin.setRange(5, 3600)
        g_iter_spin.setValue(40)
        g_iter_spin.setSuffix(" Sek.")
        g_iter_spin.setToolTip(
            "Maximales Zeit-Budget in Sekunden.\n"
            "Das System misst echte LLM-Aufrufzeiten und stoppt automatisch\n"
            "bevor das Budget überschritten wird."
        )
        self._graph_agent_iter_spin = g_iter_spin
        g_ret_layout.addWidget(g_iter_spin)
        g_ret_layout.addStretch()
        g_form.addRow("Retrieval:", g_retrieval_row)

        # Row: Quality controls
        g_quality_row = QWidget()
        g_qual_layout = QHBoxLayout(g_quality_row)
        g_qual_layout.setContentsMargins(0, 0, 0, 0)
        g_qual_layout.setSpacing(12)
        g_fact_cb = QCheckBox("Faktentreue-Prüfung")
        g_fact_cb.setToolTip(
            "Jedes Tripel (Subjekt | Relation | Objekt) wird gegen die Quelldokumente\n"
            "geprüft. Nicht belegte Tripel werden entfernt."
        )
        g_fact_cb.setChecked(True)
        self._graph_factcheck_cb = g_fact_cb
        g_qual_layout.addWidget(g_fact_cb)
        g_qual_layout.addStretch()
        g_form.addRow("Qualität:", g_quality_row)

        # Row: Edge/node limit
        g_nodes_spin = QSpinBox()
        g_nodes_spin.setRange(8, 200)
        g_nodes_spin.setValue(32)
        g_nodes_spin.setSuffix(" Kanten")
        g_nodes_spin.setToolTip(
            "Maximale Anzahl Kanten (Tripel) im generierten Wissensgraph.\n"
            "Empfehlung: 20–40 für übersichtliche Ergebnisse."
        )
        self._graph_max_nodes_spin = g_nodes_spin
        g_form.addRow("Max. Kanten:", g_nodes_spin)

        # Row: Agent tool toggles
        g_tools_row = QWidget()
        g_tools_layout = QHBoxLayout(g_tools_row)
        g_tools_layout.setContentsMargins(0, 0, 0, 0)
        g_tools_layout.setSpacing(10)
        g_rag_cb = QCheckBox("Vektor/RAG")
        g_rag_cb.setToolTip("Semantische Vektorsuche freigeben.")
        g_rag_cb.setChecked(True)
        self._graph_agent_allow_rag_cb = g_rag_cb
        g_tools_layout.addWidget(g_rag_cb)
        g_regex_cb = QCheckBox("Regex")
        g_regex_cb.setToolTip("Reguläre-Ausdrucks-Suche freigeben.")
        g_regex_cb.setChecked(True)
        self._graph_agent_allow_regex_cb = g_regex_cb
        g_tools_layout.addWidget(g_regex_cb)
        g_heading_cb = QCheckBox("Überschriften")
        g_heading_cb.setToolTip("Abschnittsüberschriften-Suche freigeben.")
        g_heading_cb.setChecked(True)
        self._graph_agent_allow_heading_cb = g_heading_cb
        g_tools_layout.addWidget(g_heading_cb)
        g_full_text_cb = QCheckBox("Volltext")
        g_full_text_cb.setToolTip("Rohtext-Auszüge freigeben (teuer, ~10 Budgetpunkte).")
        g_full_text_cb.setChecked(True)
        self._graph_agent_allow_full_text_cb = g_full_text_cb
        g_tools_layout.addWidget(g_full_text_cb)
        g_tools_layout.addStretch()
        g_form.addRow("Agent-Tools:", g_tools_row)

        # Row: Context settings
        g_ctx_row = QWidget()
        g_ctx_layout = QHBoxLayout(g_ctx_row)
        g_ctx_layout.setContentsMargins(0, 0, 0, 0)
        g_ctx_layout.setSpacing(8)
        g_full_ctx_cb = QCheckBox("Gesamten Kontext übergeben")
        g_full_ctx_cb.setToolTip("Den gesamten Dokument-Kontext direkt an die Generierung übergeben.")
        g_full_ctx_cb.setChecked(False)
        self._graph_use_full_context_cb = g_full_ctx_cb
        g_ctx_layout.addWidget(g_full_ctx_cb)
        g_ctx_layout.addWidget(QLabel("Limit:"))
        g_ctx_spin = QSpinBox()
        g_ctx_spin.setRange(4_000, 1_000_000)
        g_ctx_spin.setSingleStep(2_000)
        g_ctx_spin.setValue(50_000)
        g_ctx_spin.setSuffix(" Zeichen")
        self._graph_context_max_chars_spin = g_ctx_spin
        g_ctx_layout.addWidget(g_ctx_spin)
        g_ctx_layout.addStretch()
        g_form.addRow("Kontext:", g_ctx_row)

        # Row: Search policy options
        g_policy_row = QWidget()
        g_policy_layout = QHBoxLayout(g_policy_row)
        g_policy_layout.setContentsMargins(0, 0, 0, 0)
        g_policy_layout.setSpacing(10)
        g_narrow_cb = QCheckBox("Suche einschränken")
        g_narrow_cb.setToolTip("Agent darf Suchbegriffe zwischen Iterationen verfeinern.")
        g_narrow_cb.setChecked(True)
        self._graph_agent_allow_query_narrowing_cb = g_narrow_cb
        g_policy_layout.addWidget(g_narrow_cb)
        g_heading_summary_cb = QCheckBox("Abschnitts-Inhalte laden")
        g_heading_summary_cb.setToolTip("Beim Überschriften-Suchtreffer den zugehörigen Abschnitts-Text mitladen.")
        g_heading_summary_cb.setChecked(True)
        self._graph_agent_allow_heading_summaries_cb = g_heading_summary_cb
        g_policy_layout.addWidget(g_heading_summary_cb)
        g_policy_layout.addWidget(QLabel("Regex-Limit:"))
        g_regex_limit_spin = QSpinBox()
        g_regex_limit_spin.setRange(0, 500)
        g_regex_limit_spin.setValue(4)
        g_regex_limit_spin.setSpecialValueText("unbegrenzt")
        self._graph_agent_max_regex_calls_spin = g_regex_limit_spin
        g_policy_layout.addWidget(g_regex_limit_spin)
        g_policy_layout.addStretch()
        g_form.addRow("Suche-Optionen:", g_policy_row)

        map_tabs.addTab(g_tab, "Wissensgraph")

        root.addWidget(map_pro_group)

        root.addStretch(1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self._buttons_box = buttons
        root.addWidget(buttons)

        if self._mindmap_retrieval_combo is not None:
            self._mindmap_retrieval_combo.currentIndexChanged.connect(
                lambda _idx=0: self._sync_map_pro_controls()
            )
        if self._graph_retrieval_combo is not None:
            self._graph_retrieval_combo.currentIndexChanged.connect(
                lambda _idx=0: self._sync_map_pro_controls()
            )
        if self._mindmap_agent_allow_heading_cb is not None:
            self._mindmap_agent_allow_heading_cb.toggled.connect(
                lambda _checked=False: self._sync_map_pro_controls()
            )
        if self._graph_agent_allow_heading_cb is not None:
            self._graph_agent_allow_heading_cb.toggled.connect(
                lambda _checked=False: self._sync_map_pro_controls()
            )

    @staticmethod
    def _new_profile_combo(profile_ids: Sequence[str]) -> QComboBox:
        combo = QComboBox()
        combo.setEditable(True)
        seen: set[str] = set()
        for item in list(profile_ids or []):
            text = str(item or "").strip()
            if not text:
                continue
            key = text.casefold()
            if key in seen:
                continue
            seen.add(key)
            combo.addItem(text)
        line_edit = combo.lineEdit()
        if line_edit is not None:
            line_edit.setPlaceholderText("profile_id")
        return combo

    def _load_values(self) -> None:
        self._set_row_values(
            "factcheck",
            enabled=bool(self._base.factcheck_enabled),
            profile_id=str(self._base.factcheck_profile_id or ""),
        )
        self._set_row_values(
            "chat",
            enabled=bool(self._base.chat_enabled),
            profile_id=str(self._base.chat_profile_id or ""),
        )
        self._set_row_values(
            "canvas",
            enabled=bool(self._base.canvas_enabled),
            profile_id=str(self._base.canvas_profile_id or ""),
        )
        self._set_row_values(
            "mindmap",
            enabled=bool(self._base.mindmap_enabled),
            profile_id=str(self._base.mindmap_profile_id or ""),
        )
        self._set_row_values(
            "graph",
            enabled=bool(self._base.graph_enabled),
            profile_id=str(self._base.graph_profile_id or ""),
        )

        if self._env_name_edit is not None:
            self._env_name_edit.setText(str(self._base.env_name or ""))
        if self._overlay_profiles_edit is not None:
            self._overlay_profiles_edit.setText(
                str(self._base.overlay_profile_ids_raw or "")
            )
        if self._strict_policy_cb is not None:
            self._strict_policy_cb.setChecked(bool(self._base.strict_policy))
        if self._trace_enabled_cb is not None:
            self._trace_enabled_cb.setChecked(bool(self._base.trace_enabled))
        if self._cache_enabled_cb is not None:
            self._cache_enabled_cb.setChecked(bool(self._base.cache_enabled))
        if self._map_result_detail_combo is not None:
            value = str(self._base.map_result_detail_level or "auto").strip().casefold()
            index = self._map_result_detail_combo.findData(value)
            self._map_result_detail_combo.setCurrentIndex(index if index >= 0 else 0)

        for key, _label in _WORKFLOW_ROWS:
            self._sync_row_enabled_state(key)

        if self._mindmap_retrieval_combo is not None:
            retrieval = str(getattr(self._base, "mindmap_retrieval_strategy", "agent") or "agent").strip().casefold()
            idx = self._mindmap_retrieval_combo.findData(retrieval)
            self._mindmap_retrieval_combo.setCurrentIndex(idx if idx >= 0 else 0)
        if self._mindmap_agent_iter_spin is not None:
            self._mindmap_agent_iter_spin.setValue(
                int(float(getattr(self._base, "mindmap_budget_seconds", 45) or 45))
            )
        if self._mindmap_factcheck_cb is not None:
            self._mindmap_factcheck_cb.setChecked(bool(getattr(self._base, "mindmap_factcheck", True)))
        if self._mindmap_max_nodes_spin is not None:
            self._mindmap_max_nodes_spin.setValue(int(getattr(self._base, "mindmap_max_nodes", 32) or 32))
        if self._mindmap_max_refinements_spin is not None:
            self._mindmap_max_refinements_spin.setValue(
                int(getattr(self._base, "mindmap_max_refinement_rounds", 1) or 1)
            )
        if self._mindmap_use_full_context_cb is not None:
            self._mindmap_use_full_context_cb.setChecked(
                bool(getattr(self._base, "mindmap_use_full_context", False))
            )
        if self._mindmap_context_max_chars_spin is not None:
            self._mindmap_context_max_chars_spin.setValue(
                int(getattr(self._base, "mindmap_context_max_chars", 50_000) or 50_000)
            )
        if self._mindmap_agent_allow_rag_cb is not None:
            self._mindmap_agent_allow_rag_cb.setChecked(
                bool(getattr(self._base, "mindmap_agent_allow_rag", True))
            )
        if self._mindmap_agent_allow_regex_cb is not None:
            self._mindmap_agent_allow_regex_cb.setChecked(
                bool(getattr(self._base, "mindmap_agent_allow_regex", True))
            )
        if self._mindmap_agent_allow_heading_cb is not None:
            self._mindmap_agent_allow_heading_cb.setChecked(
                bool(getattr(self._base, "mindmap_agent_allow_heading", True))
            )
        if self._mindmap_agent_allow_full_text_cb is not None:
            self._mindmap_agent_allow_full_text_cb.setChecked(
                bool(getattr(self._base, "mindmap_agent_allow_full_text", True))
            )
        if self._mindmap_agent_allow_query_narrowing_cb is not None:
            self._mindmap_agent_allow_query_narrowing_cb.setChecked(
                bool(getattr(self._base, "mindmap_agent_allow_query_narrowing", True))
            )
        if self._mindmap_agent_allow_heading_summaries_cb is not None:
            self._mindmap_agent_allow_heading_summaries_cb.setChecked(
                bool(getattr(self._base, "mindmap_agent_allow_heading_summaries", True))
            )
        if self._mindmap_agent_max_regex_calls_spin is not None:
            self._mindmap_agent_max_regex_calls_spin.setValue(
                int(getattr(self._base, "mindmap_agent_max_regex_calls", 4) or 4)
            )
        if self._graph_retrieval_combo is not None:
            retrieval = str(getattr(self._base, "graph_retrieval_strategy", "agent") or "agent").strip().casefold()
            idx = self._graph_retrieval_combo.findData(retrieval)
            self._graph_retrieval_combo.setCurrentIndex(idx if idx >= 0 else 0)
        if self._graph_agent_iter_spin is not None:
            self._graph_agent_iter_spin.setValue(
                int(float(getattr(self._base, "graph_budget_seconds", 40) or 40))
            )
        if self._graph_factcheck_cb is not None:
            self._graph_factcheck_cb.setChecked(bool(getattr(self._base, "graph_factcheck", True)))
        if self._graph_max_nodes_spin is not None:
            self._graph_max_nodes_spin.setValue(int(getattr(self._base, "graph_max_nodes", 32) or 32))
        if self._graph_use_full_context_cb is not None:
            self._graph_use_full_context_cb.setChecked(
                bool(getattr(self._base, "graph_use_full_context", False))
            )
        if self._graph_context_max_chars_spin is not None:
            self._graph_context_max_chars_spin.setValue(
                int(getattr(self._base, "graph_context_max_chars", 50_000) or 50_000)
            )
        if self._graph_agent_allow_rag_cb is not None:
            self._graph_agent_allow_rag_cb.setChecked(
                bool(getattr(self._base, "graph_agent_allow_rag", True))
            )
        if self._graph_agent_allow_regex_cb is not None:
            self._graph_agent_allow_regex_cb.setChecked(
                bool(getattr(self._base, "graph_agent_allow_regex", True))
            )
        if self._graph_agent_allow_heading_cb is not None:
            self._graph_agent_allow_heading_cb.setChecked(
                bool(getattr(self._base, "graph_agent_allow_heading", True))
            )
        if self._graph_agent_allow_full_text_cb is not None:
            self._graph_agent_allow_full_text_cb.setChecked(
                bool(getattr(self._base, "graph_agent_allow_full_text", True))
            )
        if self._graph_agent_allow_query_narrowing_cb is not None:
            self._graph_agent_allow_query_narrowing_cb.setChecked(
                bool(getattr(self._base, "graph_agent_allow_query_narrowing", True))
            )
        if self._graph_agent_allow_heading_summaries_cb is not None:
            self._graph_agent_allow_heading_summaries_cb.setChecked(
                bool(getattr(self._base, "graph_agent_allow_heading_summaries", True))
            )
        if self._graph_agent_max_regex_calls_spin is not None:
            self._graph_agent_max_regex_calls_spin.setValue(
                int(getattr(self._base, "graph_agent_max_regex_calls", 4) or 4)
            )
        self._sync_map_pro_controls()

    def _set_row_values(self, workflow_key: str, *, enabled: bool, profile_id: str) -> None:
        checkbox = self._workflow_enabled.get(str(workflow_key))
        combo = self._workflow_profiles.get(str(workflow_key))
        if checkbox is None or combo is None:
            return
        checkbox.setChecked(bool(enabled))
        if profile_id:
            index = combo.findText(profile_id)
            if index < 0:
                combo.addItem(profile_id)
                index = combo.findText(profile_id)
            if index >= 0:
                combo.setCurrentIndex(index)
            else:
                combo.setEditText(profile_id)

    def _sync_row_enabled_state(self, workflow_key: str) -> None:
        checkbox = self._workflow_enabled.get(str(workflow_key))
        combo = self._workflow_profiles.get(str(workflow_key))
        if checkbox is None or combo is None:
            return
        combo.setEnabled(bool(checkbox.isChecked()))

    def _sync_map_pro_controls(self) -> None:
        mm_is_agent = False
        if self._mindmap_retrieval_combo is not None:
            mm_is_agent = str(self._mindmap_retrieval_combo.currentData() or "").strip().casefold() == "agent"
        if self._mindmap_agent_iter_spin is not None:
            self._mindmap_agent_iter_spin.setEnabled(mm_is_agent)
        mm_heading_enabled = bool(
            self._mindmap_agent_allow_heading_cb.isChecked()
            if self._mindmap_agent_allow_heading_cb is not None
            else True
        )
        if self._mindmap_agent_allow_rag_cb is not None:
            self._mindmap_agent_allow_rag_cb.setEnabled(mm_is_agent)
        if self._mindmap_agent_allow_regex_cb is not None:
            self._mindmap_agent_allow_regex_cb.setEnabled(mm_is_agent)
        if self._mindmap_agent_allow_heading_cb is not None:
            self._mindmap_agent_allow_heading_cb.setEnabled(mm_is_agent)
        if self._mindmap_agent_allow_full_text_cb is not None:
            self._mindmap_agent_allow_full_text_cb.setEnabled(mm_is_agent)
        if self._mindmap_agent_allow_query_narrowing_cb is not None:
            self._mindmap_agent_allow_query_narrowing_cb.setEnabled(mm_is_agent)
        if self._mindmap_agent_allow_heading_summaries_cb is not None:
            self._mindmap_agent_allow_heading_summaries_cb.setEnabled(mm_is_agent and mm_heading_enabled)
        if self._mindmap_agent_max_regex_calls_spin is not None:
            self._mindmap_agent_max_regex_calls_spin.setEnabled(mm_is_agent)

        g_is_agent = False
        if self._graph_retrieval_combo is not None:
            g_is_agent = str(self._graph_retrieval_combo.currentData() or "").strip().casefold() == "agent"
        if self._graph_agent_iter_spin is not None:
            self._graph_agent_iter_spin.setEnabled(g_is_agent)
        g_heading_enabled = bool(
            self._graph_agent_allow_heading_cb.isChecked()
            if self._graph_agent_allow_heading_cb is not None
            else True
        )
        if self._graph_agent_allow_rag_cb is not None:
            self._graph_agent_allow_rag_cb.setEnabled(g_is_agent)
        if self._graph_agent_allow_regex_cb is not None:
            self._graph_agent_allow_regex_cb.setEnabled(g_is_agent)
        if self._graph_agent_allow_heading_cb is not None:
            self._graph_agent_allow_heading_cb.setEnabled(g_is_agent)
        if self._graph_agent_allow_full_text_cb is not None:
            self._graph_agent_allow_full_text_cb.setEnabled(g_is_agent)
        if self._graph_agent_allow_query_narrowing_cb is not None:
            self._graph_agent_allow_query_narrowing_cb.setEnabled(g_is_agent)
        if self._graph_agent_allow_heading_summaries_cb is not None:
            self._graph_agent_allow_heading_summaries_cb.setEnabled(g_is_agent and g_heading_enabled)
        if self._graph_agent_max_regex_calls_spin is not None:
            self._graph_agent_max_regex_calls_spin.setEnabled(g_is_agent)

    def _apply_labels(self) -> None:
        self.setWindowTitle(
            resolve_feature_label(
                self._user_mode,
                "agentic.settings.window_title",
                "Agentic Workflow Settings",
            )
        )
        if self._intro_label is not None:
            self._intro_label.setText(
                resolve_feature_label(
                    self._user_mode,
                    "agentic.settings.intro",
                    "Konfiguriert zentrale Agenten-Workflows für Factcheck, Chat, "
                    "Canvas und Mindmap. Änderungen greifen sofort für neue Läufe.",
                )
            )
        if self._workflow_group is not None:
            self._workflow_group.setTitle(
                resolve_feature_label(
                    self._user_mode,
                    "agentic.settings.group.workflows",
                    "Workflows",
                )
            )
        if self._runtime_group is not None:
            self._runtime_group.setTitle(
                resolve_feature_label(
                    self._user_mode,
                    "agentic.settings.group.runtime",
                    "Runtime / Policy",
                )
            )

        for workflow_key, fallback in _WORKFLOW_ROWS:
            label_widget = self._workflow_row_labels.get(workflow_key)
            enabled_cb = self._workflow_enabled.get(workflow_key)
            combo = self._workflow_profiles.get(workflow_key)
            if label_widget is not None:
                label_widget.setText(
                    resolve_feature_label(
                        self._user_mode,
                        f"agentic.settings.workflow.{workflow_key}.row_label",
                        fallback,
                    )
                )
            if enabled_cb is not None:
                enabled_cb.setText(
                    resolve_feature_label(
                        self._user_mode,
                        f"agentic.settings.workflow.{workflow_key}.enabled",
                        "Aktiv",
                    )
                )
            if combo is not None:
                combo.setToolTip(
                    resolve_feature_label(
                        self._user_mode,
                        f"agentic.settings.workflow.{workflow_key}.profile.tooltip",
                        "Profil-ID für diesen Workflow.",
                    )
                )

        row_defaults = {
            "env_name": "Environment Profil",
            "overlay_profiles": "Overlay Profile",
            "strict_policy": "Strict Policy",
            "trace_enabled": "Run Tracing",
            "cache_enabled": "Tool Cache",
            "map_result_detail_level": "Mindmap/Graph Ausgabe",
        }
        for row_key, label_widget in self._runtime_row_labels.items():
            label_widget.setText(
                resolve_feature_label(
                    self._user_mode,
                    f"agentic.settings.runtime.{row_key}.row_label",
                    row_defaults.get(row_key, row_key),
                )
            )

        if self._strict_policy_cb is not None:
            self._strict_policy_cb.setText(
                resolve_feature_label(
                    self._user_mode,
                    "agentic.settings.runtime.strict_policy.value_label",
                    "Unzulässige Tools/Steps strikt blockieren",
                )
            )
        if self._trace_enabled_cb is not None:
            self._trace_enabled_cb.setText(
                resolve_feature_label(
                    self._user_mode,
                    "agentic.settings.runtime.trace_enabled.value_label",
                    "Run-Traces unter runs/agentic schreiben",
                )
            )
        if self._cache_enabled_cb is not None:
            self._cache_enabled_cb.setText(
                resolve_feature_label(
                    self._user_mode,
                    "agentic.settings.runtime.cache_enabled.value_label",
                    "Tool-Cache aktivieren",
                )
            )
        if self._map_result_detail_combo is not None:
            for idx, (value, fallback) in enumerate(_MAP_RESULT_DETAIL_OPTIONS):
                self._map_result_detail_combo.setItemText(
                    idx,
                    resolve_feature_label(
                        self._user_mode,
                        f"agentic.settings.runtime.map_result_detail_level.option.{value}",
                        fallback,
                    ),
                )
            self._map_result_detail_combo.setToolTip(
                resolve_feature_label(
                    self._user_mode,
                    "agentic.settings.runtime.map_result_detail_level.tooltip",
                    "Steuert, wie ausfuehrlich Mindmap-/Graph-Ergebnisse im Chat zusammengefasst werden.",
                )
            )
        if self._env_name_edit is not None:
            self._env_name_edit.setToolTip(
                resolve_feature_label(
                    self._user_mode,
                    "agentic.settings.runtime.env_name.tooltip",
                    "Optional: lädt zusätzliches Profil _env_<name>.",
                )
            )
        if self._overlay_profiles_edit is not None:
            self._overlay_profiles_edit.setToolTip(
                resolve_feature_label(
                    self._user_mode,
                    "agentic.settings.runtime.overlay_profiles.tooltip",
                    "Komma-getrennte zusätzliche Overlay-Profile.",
                )
            )
        if self._buttons_box is not None:
            ok_btn = self._buttons_box.button(QDialogButtonBox.StandardButton.Ok)
            if ok_btn is not None:
                ok_btn.setText(
                    resolve_feature_label(
                        self._user_mode,
                        "agentic.settings.button.ok",
                        "OK",
                    )
                )
            cancel_btn = self._buttons_box.button(
                QDialogButtonBox.StandardButton.Cancel
            )
            if cancel_btn is not None:
                cancel_btn.setText(
                    resolve_feature_label(
                        self._user_mode,
                        "agentic.settings.button.cancel",
                        "Abbrechen",
                    )
                )

    def get_settings(self) -> AgenticRuntimeSettings:
        data = {
            "factcheck_enabled": bool(
                self._workflow_enabled["factcheck"].isChecked()
            ),
            "chat_enabled": bool(self._workflow_enabled["chat"].isChecked()),
            "canvas_enabled": bool(self._workflow_enabled["canvas"].isChecked()),
            "mindmap_enabled": bool(self._workflow_enabled["mindmap"].isChecked()),
            "graph_enabled": bool(self._workflow_enabled["graph"].isChecked()),
            "factcheck_profile_id": str(
                self._workflow_profiles["factcheck"].currentText() or ""
            ).strip(),
            "chat_profile_id": str(
                self._workflow_profiles["chat"].currentText() or ""
            ).strip(),
            "canvas_profile_id": str(
                self._workflow_profiles["canvas"].currentText() or ""
            ).strip(),
            "mindmap_profile_id": str(
                self._workflow_profiles["mindmap"].currentText() or ""
            ).strip(),
            "graph_profile_id": str(
                self._workflow_profiles["graph"].currentText() or ""
            ).strip(),
            "strict_policy": bool(
                self._strict_policy_cb.isChecked() if self._strict_policy_cb else False
            ),
            "trace_enabled": bool(
                self._trace_enabled_cb.isChecked() if self._trace_enabled_cb else False
            ),
            "cache_enabled": bool(
                self._cache_enabled_cb.isChecked() if self._cache_enabled_cb else True
            ),
            "map_result_detail_level": str(
                self._map_result_detail_combo.currentData()
                if self._map_result_detail_combo is not None
                else "auto"
            ).strip()
            or "auto",
            "env_name": str(
                self._env_name_edit.text() if self._env_name_edit else ""
            ).strip(),
            "overlay_profile_ids_raw": str(
                self._overlay_profiles_edit.text()
                if self._overlay_profiles_edit
                else ""
            ).strip(),
            "mindmap_retrieval_strategy": str(
                self._mindmap_retrieval_combo.currentData()
                if self._mindmap_retrieval_combo is not None
                else "agent"
            ).strip()
            or "agent",
            "mindmap_budget_seconds": float(
                self._mindmap_agent_iter_spin.value() if self._mindmap_agent_iter_spin else 45
            ),
            "mindmap_agent_max_iterations": int(
                self._mindmap_agent_iter_spin.value() if self._mindmap_agent_iter_spin else 45
            ),
            "mindmap_use_full_context": bool(
                self._mindmap_use_full_context_cb.isChecked() if self._mindmap_use_full_context_cb else False
            ),
            "mindmap_context_max_chars": int(
                self._mindmap_context_max_chars_spin.value() if self._mindmap_context_max_chars_spin else 50_000
            ),
            "mindmap_agent_allow_rag": bool(
                self._mindmap_agent_allow_rag_cb.isChecked() if self._mindmap_agent_allow_rag_cb else True
            ),
            "mindmap_agent_allow_regex": bool(
                self._mindmap_agent_allow_regex_cb.isChecked() if self._mindmap_agent_allow_regex_cb else True
            ),
            "mindmap_agent_allow_heading": bool(
                self._mindmap_agent_allow_heading_cb.isChecked() if self._mindmap_agent_allow_heading_cb else True
            ),
            "mindmap_agent_allow_full_text": bool(
                self._mindmap_agent_allow_full_text_cb.isChecked() if self._mindmap_agent_allow_full_text_cb else True
            ),
            "mindmap_agent_allow_query_narrowing": bool(
                self._mindmap_agent_allow_query_narrowing_cb.isChecked()
                if self._mindmap_agent_allow_query_narrowing_cb
                else True
            ),
            "mindmap_agent_allow_heading_summaries": bool(
                self._mindmap_agent_allow_heading_summaries_cb.isChecked()
                if self._mindmap_agent_allow_heading_summaries_cb
                else True
            ),
            "mindmap_agent_max_regex_calls": int(
                self._mindmap_agent_max_regex_calls_spin.value()
                if self._mindmap_agent_max_regex_calls_spin
                else 4
            ),
            "mindmap_factcheck": bool(
                self._mindmap_factcheck_cb.isChecked() if self._mindmap_factcheck_cb else True
            ),
            "mindmap_max_nodes": int(
                self._mindmap_max_nodes_spin.value() if self._mindmap_max_nodes_spin else 32
            ),
            "mindmap_max_refinement_rounds": int(
                self._mindmap_max_refinements_spin.value() if self._mindmap_max_refinements_spin else 1
            ),
            "graph_retrieval_strategy": str(
                self._graph_retrieval_combo.currentData()
                if self._graph_retrieval_combo is not None
                else "agent"
            ).strip()
            or "agent",
            "graph_budget_seconds": float(
                self._graph_agent_iter_spin.value() if self._graph_agent_iter_spin else 40
            ),
            "graph_agent_max_iterations": int(
                self._graph_agent_iter_spin.value() if self._graph_agent_iter_spin else 40
            ),
            "graph_use_full_context": bool(
                self._graph_use_full_context_cb.isChecked() if self._graph_use_full_context_cb else False
            ),
            "graph_context_max_chars": int(
                self._graph_context_max_chars_spin.value() if self._graph_context_max_chars_spin else 50_000
            ),
            "graph_agent_allow_rag": bool(
                self._graph_agent_allow_rag_cb.isChecked() if self._graph_agent_allow_rag_cb else True
            ),
            "graph_agent_allow_regex": bool(
                self._graph_agent_allow_regex_cb.isChecked() if self._graph_agent_allow_regex_cb else True
            ),
            "graph_agent_allow_heading": bool(
                self._graph_agent_allow_heading_cb.isChecked() if self._graph_agent_allow_heading_cb else True
            ),
            "graph_agent_allow_full_text": bool(
                self._graph_agent_allow_full_text_cb.isChecked() if self._graph_agent_allow_full_text_cb else True
            ),
            "graph_agent_allow_query_narrowing": bool(
                self._graph_agent_allow_query_narrowing_cb.isChecked()
                if self._graph_agent_allow_query_narrowing_cb
                else True
            ),
            "graph_agent_allow_heading_summaries": bool(
                self._graph_agent_allow_heading_summaries_cb.isChecked()
                if self._graph_agent_allow_heading_summaries_cb
                else True
            ),
            "graph_agent_max_regex_calls": int(
                self._graph_agent_max_regex_calls_spin.value()
                if self._graph_agent_max_regex_calls_spin
                else 4
            ),
            "graph_factcheck": bool(
                self._graph_factcheck_cb.isChecked() if self._graph_factcheck_cb else True
            ),
            "graph_max_nodes": int(
                self._graph_max_nodes_spin.value() if self._graph_max_nodes_spin else 32
            ),
        }
        return AgenticRuntimeSettings.from_dict(data)
