"""PromptEditorDialog — standalone dialog for editing all LLM prompt templates."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from shared.domain.user_mode import USER_MODE_PLUS


class PromptEditorDialog(QDialog):
    """Tabbed editor for all system/user/structure prompts."""

    def __init__(self, llm_manager, user_mode: str, parent=None):
        super().__init__(parent)
        self._llm_manager = llm_manager
        self._user_mode = user_mode
        self._editors: dict[str, QTextEdit] = {}
        self._setup_ui()

    def _setup_ui(self):
        self.setWindowTitle("Edit Prompts")
        self.resize(980, 700)
        self.setStyleSheet("background: palette(window); color: palette(window-text);")

        layout = QVBoxLayout(self)
        lbl = QLabel(
            "Prompt-Editor: System/User/Struktur-Prompts sind hier getrennt organisiert.\n"
            "System = Rollenregeln, User = Aufgabenblock, Struktur = Aufbau-/Titeltexte.\n"
            "Ablauf pro LLM-Aufruf: <|system|> + (optional Strukturblöcke) + <|user|>."
        )
        lbl.setStyleSheet("color: palette(placeholder-text); font-size: 11px;")
        lbl.setWordWrap(True)
        layout.addWidget(lbl)

        prompt_values = self._llm_manager.get_prompt_set()
        prompt_defaults = self._llm_manager.get_prompt_defaults()
        top_tabs = QTabWidget()
        top_tabs.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid palette(mid);
                border-radius: 4px;
                background: palette(base);
            }
            QTabBar::tab {
                background: palette(alternate-base);
                color: palette(text);
                padding: 6px 12px;
                border: 1px solid palette(mid);
                border-bottom: none;
            }
            QTabBar::tab:selected {
                background: palette(base);
                color: palette(highlight);
            }
        """)

        prompt_specs = {
            "chat_system": {
                "group": "Chat",
                "title": "Chat: System",
                "kind": "System",
                "desc": "Globale Rolle und Antwortstil des Chat-Modells.",
            },
            "chat_grounding_rules": {
                "group": "Chat",
                "title": "Chat: Grounding-Regeln",
                "kind": "System",
                "desc": "Erzwingt dokumentgebundenes Antworten bei RAG/Datei-Kontext.",
                "placeholders": "{insufficient_message}, {citation_rule}",
            },
            "chat_canvas_rewrite_rules": {
                "group": "Chat",
                "title": "Draft: Rewrite-Regeln",
                "kind": "System",
                "desc": "Regeln für direktes Umschreiben einer Draft-Auswahl.",
                "placeholders": "{canvas_open}, {canvas_close}, {grounding_note}, {insufficient_message}",
            },
            "chat_citation_rule_answer": {
                "group": "Chat",
                "title": "Chat: Zitatregel Antwort",
                "kind": "Baustein",
                "desc": "Zusatzregel für normale Antworten im Grounding-Modus.",
            },
            "chat_citation_rule_rewrite": {
                "group": "Chat",
                "title": "Chat: Zitatregel Rewrite",
                "kind": "Baustein",
                "desc": "Zusatzregel für Draft-Rewrite im Grounding-Modus.",
            },
            "chat_grounding_note_rewrite": {
                "group": "Chat",
                "title": "Chat: Grounding-Hinweis Rewrite",
                "kind": "Baustein",
                "desc": "Wird in Rewrite-Regeln eingeblendet, wenn Quellenpflicht aktiv ist.",
            },
            "claim_extract_system": {
                "group": "Faktencheck",
                "title": "Claim Extract: System",
                "kind": "System",
                "desc": "Rolle für atomare Claim-Extraktion aus EINEM Eingabetext.",
            },
            "claim_extract_user": {
                "group": "Faktencheck",
                "title": "Claim Extract: User",
                "kind": "User",
                "desc": "Konkreter Auftrag für atomare Claim-Extraktion.",
                "placeholders": "{input_label}, {fact_limit}",
            },
            "fact_verify_system": {
                "group": "Faktencheck",
                "title": "Verify: System",
                "kind": "System",
                "desc": "Rolle für Einzel-Fakt-Prüfung gegen Quellen.",
            },
            "fact_verify_user": {
                "group": "Faktencheck",
                "title": "Verify: User",
                "kind": "User",
                "desc": "Konkreter Auftrag für eine einzelne Faktprüfung.",
                "placeholders": "{allowed_sources}, {fact}",
            },
            "nli_verify_system": {
                "group": "Faktencheck",
                "title": "NLI Verify: System",
                "kind": "System",
                "desc": "Workflow-Beschreibung für Transformers-NLI (Claim-vs-Chunk).",
            },
            "nli_verify_user": {
                "group": "Faktencheck",
                "title": "NLI Verify: User",
                "kind": "User",
                "desc": "Input-Template je Chunk/Fakt-Paar (premise/hypothesis).",
                "placeholders": "{premise}, {hypothesis}",
            },
            "hyde_tfidf_system": {
                "group": "RAG",
                "title": "HyDE TF-IDF: System",
                "kind": "System",
                "desc": "Rolle für Begriffserweiterung im TF-IDF-Backend.",
            },
            "hyde_tfidf_user": {
                "group": "RAG",
                "title": "HyDE TF-IDF: User",
                "kind": "User",
                "desc": "Auftrag zur Generierung von Literal-Suchbegriffen.",
                "placeholders": "{query}",
            },
            "hyde_st_single_system": {
                "group": "RAG",
                "title": "HyDE ST Single: System",
                "kind": "System",
                "desc": "Rolle für 1 hypothetischen Absatz (semantische Suche).",
            },
            "hyde_st_single_user": {
                "group": "RAG",
                "title": "HyDE ST Single: User",
                "kind": "User",
                "desc": "Auftrag für eine einzelne hypothetische Passage.",
                "placeholders": "{query}",
            },
            "hyde_st_multi_system": {
                "group": "RAG",
                "title": "HyDE ST Multi: System",
                "kind": "System",
                "desc": "Rolle für mehrere hypothetische Absätze.",
            },
            "hyde_st_multi_user": {
                "group": "RAG",
                "title": "HyDE ST Multi: User",
                "kind": "User",
                "desc": "Auftrag für Multi-Passage-HyDE.",
                "placeholders": "{query}, {n_hypotheses}",
            },
            "literal_terms_system": {
                "group": "RAG",
                "title": "Literal Terms: System",
                "kind": "System",
                "desc": "Rolle für LLM-gestützte Literal-Begriffe.",
            },
            "literal_terms_user": {
                "group": "RAG",
                "title": "Literal Terms: User",
                "kind": "User",
                "desc": "Auftrag zur Begriffsgenerierung für Literal Search.",
                "placeholders": "{query}, {max_terms}",
            },
            "rag_rerank_system": {
                "group": "RAG",
                "title": "Rerank: System",
                "kind": "System",
                "desc": "Rolle für Klassifikation von Treffern (sinnvoll/nicht_sinnvoll).",
            },
            "rag_rerank_user": {
                "group": "RAG",
                "title": "Rerank: User",
                "kind": "User",
                "desc": "Auftrag zum Bewerten einzelner RAG-Trefferlisten.",
                "placeholders": "{query}, {items}",
            },
            "mindmap_system": {
                "group": "MindMap",
                "title": "MindMap: System",
                "kind": "System",
                "desc": "Rolle für vereinfachte MindMap-Ausgabe aus Kontext.",
            },
            "mindmap_user": {
                "group": "MindMap",
                "title": "MindMap: User",
                "kind": "User",
                "desc": "Auftrag + Ausgabeformat für mehrstufige MindMap-Hierarchie mit Blatt-Zitaten.",
                "placeholders": "{context}, {query}, {max_nodes}",
            },
            "graph_system": {
                "group": "MindMap",
                "title": "Graph: System",
                "kind": "System",
                "desc": "Rolle für Wissensgraph-Ausgabe mit Relationen.",
            },
            "graph_user": {
                "group": "MindMap",
                "title": "Graph: User",
                "kind": "User",
                "desc": "Auftrag + Ausgabeformat für Tripel mit möglichst zusammenhängender Graph-Struktur.",
                "placeholders": "{context}, {query}, {max_nodes}",
            },
            "glossary_system": {
                "group": "Glossar",
                "title": "Glossar: System",
                "kind": "System",
                "desc": "Rolle für automatische Glossar-Extraktion aus Kontext.",
            },
            "glossary_user": {
                "group": "Glossar",
                "title": "Glossar: User",
                "kind": "User",
                "desc": "Auftrag + Ausgabeformat für Glossar-JSON.",
                "placeholders": "{context}, {max_terms}",
            },
            "chat_section_grounding_title": {
                "group": "Erweitert",
                "title": "Struktur: Grounding-Überschrift",
                "kind": "Struktur",
                "desc": "Abschnittsüberschrift im finalen Prompt vor Grounding-Regeln.",
            },
            "chat_section_rewrite_title": {
                "group": "Erweitert",
                "title": "Struktur: Rewrite-Überschrift",
                "kind": "Struktur",
                "desc": "Abschnittsüberschrift im Prompt vor Rewrite-Regeln.",
            },
            "chat_section_context_title": {
                "group": "Erweitert",
                "title": "Struktur: Kontext-Start",
                "kind": "Struktur",
                "desc": "Starttitel für den gesamten Kontextblock.",
            },
            "chat_section_context_end": {
                "group": "Erweitert",
                "title": "Struktur: Kontext-Ende",
                "kind": "Struktur",
                "desc": "Schließt den Kontextblock im Prompt ab.",
            },
            "chat_section_files_title": {
                "group": "Erweitert",
                "title": "Struktur: Dateien-Titel",
                "kind": "Struktur",
                "desc": "Titel vor angehängten Dokumenten im Kontextblock.",
            },
            "chat_section_rag_title": {
                "group": "Erweitert",
                "title": "Struktur: RAG-Titel",
                "kind": "Struktur",
                "desc": "Titel vor RAG-Auszügen im Kontextblock.",
            },
            "chat_section_selected_title": {
                "group": "Erweitert",
                "title": "Struktur: Auswahl-Titel",
                "kind": "Struktur",
                "desc": "Titel vor markierter Draft-Auswahl im Kontextblock.",
            },
            "fact_check_system": {
                "group": "Legacy",
                "title": "Legacy: FactCheck (ungenutzt)",
                "kind": "Legacy",
                "desc": "Derzeit nicht aktiv im Codepfad. Nur für Rückwärtskompatibilität alter Projekte.",
            },
        }
        group_order = (
            ["Chat", "Faktencheck", "Glossar", "MindMap"]
            if self._user_mode == USER_MODE_PLUS
            else ["Chat", "Faktencheck", "Glossar", "MindMap", "RAG", "Erweitert", "Legacy"]
        )
        grouped: dict[str, list[str]] = {g: [] for g in group_order}
        for key in self._llm_manager.PROMPT_KEYS:
            spec = prompt_specs.get(key, {})
            grp = str(spec.get("group", "Erweitert"))
            if grp not in grouped:
                grouped[grp] = []
            grouped[grp].append(key)

        def _simple_flow(system_key: str, user_key: str, extra: list[str] | None = None) -> str:
            lines = ["<|system|>", "{" + system_key + "}"]
            if extra:
                lines.extend(extra)
            lines.extend(["<|user|>", "{" + user_key + "}", "<|assistant|>"])
            return "\n".join(lines)

        def _flow_preview_for_key(key: str) -> str:
            if key in {
                "chat_system", "chat_grounding_rules", "chat_canvas_rewrite_rules",
                "chat_citation_rule_answer", "chat_citation_rule_rewrite",
                "chat_grounding_note_rewrite", "chat_section_grounding_title",
                "chat_section_rewrite_title", "chat_section_context_title",
                "chat_section_context_end", "chat_section_files_title",
                "chat_section_rag_title", "chat_section_selected_title",
            }:
                return "\n".join([
                    "Beispiel-Flow (Chat):",
                    "<|system|>",
                    "{chat_system}",
                    "{chat_section_grounding_title}        # optional bei dokumentgebundenem Modus",
                    "{chat_grounding_rules}",
                    "{chat_section_rewrite_title}          # optional bei Draft-Rewrite",
                    "{chat_canvas_rewrite_rules}",
                    "{chat_section_context_title}          # optional wenn Kontext vorhanden",
                    "{chat_section_files_title}",
                    "{chat_section_rag_title}",
                    "{chat_section_selected_title}",
                    "{chat_section_context_end}",
                    "<|user|>",
                    "[Nutzeranfrage]",
                    "<|assistant|>",
                ])
            if key.startswith("claim_extract_"):
                return "\n".join([
                    "Beispiel-Flow (Faktencheck: Claim-Extraktion):",
                    "<|system|>", "{claim_extract_system}", "<|user|>",
                    "{claim_extract_user}   # mit {input_label}, {fact_limit}", "<|assistant|>",
                ])
            if key.startswith("fact_verify_"):
                return "\n".join([
                    "Beispiel-Flow (Faktencheck: Verifikation):",
                    "<|system|>", "{fact_verify_system}", "<|user|>",
                    "{fact_verify_user}    # mit {allowed_sources}, {fact}", "<|assistant|>",
                ])
            if key.startswith("nli_verify_"):
                return "\n".join([
                    "Beispiel-Flow (Faktencheck: NLI via Transformers):",
                    "Wird pro Fakt über alle Quell-Chunks iteriert.",
                    "[backend=transformers-cross-encoder]",
                    "<|workflow|>", "{nli_verify_system}", "<|input|>",
                    "{nli_verify_user}     # mit {premise}, {hypothesis}",
                ])
            if key == "fact_check_system":
                return "\n".join([
                    "Legacy-Hinweis:",
                    "Dieser Prompt ist aktuell nicht im aktiven Ablauf verdrahtet.",
                    "Aktiv genutzt werden stattdessen:",
                    "- claim_extract_system + claim_extract_user",
                    "- fact_verify_system + fact_verify_user",
                    "- nli_verify_system + nli_verify_user (wenn NLI aktiv)",
                ])
            if key.startswith("hyde_tfidf_"):
                return _simple_flow("hyde_tfidf_system", "hyde_tfidf_user")
            if key.startswith("hyde_st_single_"):
                return _simple_flow("hyde_st_single_system", "hyde_st_single_user")
            if key.startswith("hyde_st_multi_"):
                return _simple_flow("hyde_st_multi_system", "hyde_st_multi_user")
            if key.startswith("literal_terms_"):
                return _simple_flow("literal_terms_system", "literal_terms_user")
            if key.startswith("rag_rerank_"):
                return _simple_flow("rag_rerank_system", "rag_rerank_user")
            if key.startswith("mindmap_"):
                return _simple_flow("mindmap_system", "mindmap_user")
            if key.startswith("graph_"):
                return _simple_flow("graph_system", "graph_user")
            if key.startswith("glossary_"):
                return _simple_flow("glossary_system", "glossary_user")
            return "\n".join([
                "Beispiel-Flow:", "<|system|>", "{system_prompt}",
                "<|user|>", "{user_prompt}", "<|assistant|>",
            ])

        group_tabs: dict[str, QTabWidget] = {}
        group_keys: dict[str, list[str]] = {}
        tab_style_inner = """
            QTabWidget::pane {
                border: 1px solid palette(mid);
                border-radius: 4px;
                background: palette(base);
            }
            QTabBar::tab {
                background: palette(alternate-base);
                color: palette(text);
                padding: 5px 10px;
                border: 1px solid palette(mid);
                border-bottom: none;
            }
            QTabBar::tab:selected {
                background: palette(base);
                color: palette(highlight);
            }
        """
        editor_style = """
            QTextEdit {
                background: palette(base); color: palette(text);
                border: 1px solid palette(mid); border-radius: 4px;
                padding: 6px; font-size: 11px;
            }
        """

        for group in group_order:
            keys = grouped.get(group, [])
            if not keys:
                continue

            group_page = QWidget()
            group_layout = QVBoxLayout(group_page)
            group_layout.setContentsMargins(8, 8, 8, 8)
            group_layout.setSpacing(8)

            info = QLabel(
                "Nur diese Prompts werden direkt in die jeweiligen LLM-Aufrufe übernommen."
                if group != "Legacy"
                else "Legacy-Prompts sind nur für alte Projekte vorhanden und aktuell nicht aktiv verdrahtet."
            )
            info.setWordWrap(True)
            info.setStyleSheet("color: palette(placeholder-text); font-size: 10px;")
            group_layout.addWidget(info)

            inner_tabs = QTabWidget()
            inner_tabs.setStyleSheet(tab_style_inner)

            group_keys[group] = []
            for key in keys:
                spec = prompt_specs.get(key, {})
                title = str(spec.get("title", key))
                kind = str(spec.get("kind", "Prompt"))
                desc = str(spec.get("desc", "")).strip()
                placeholders = str(spec.get("placeholders", "")).strip()

                tab = QWidget()
                tab_layout = QVBoxLayout(tab)
                tab_layout.setContentsMargins(8, 8, 8, 8)
                tab_layout.setSpacing(6)

                meta_lines = [f"Typ: {kind}"]
                if desc:
                    meta_lines.append(f"Verwendung: {desc}")
                if placeholders:
                    meta_lines.append(f"Platzhalter: {placeholders}")
                pair_hint = ""
                if key.endswith("_system"):
                    partner = key[:-7] + "_user"
                    if partner in prompt_values:
                        pair_hint = (
                            f"Zusammenhang: Wird zusammen mit '{partner}' "
                            "im selben LLM-Aufruf verwendet "
                            "(Regeln im System-Block, Auftrag im User-Block)."
                        )
                elif key.endswith("_user"):
                    partner = key[:-5] + "_system"
                    if partner in prompt_values:
                        pair_hint = (
                            f"Zusammenhang: Nutzt die Leitplanken aus '{partner}' "
                            "im selben LLM-Aufruf "
                            "(dieser Prompt liefert den konkreten Auftrag)."
                        )
                if pair_hint:
                    meta_lines.append(pair_hint)
                meta = QLabel("\n".join(meta_lines))
                meta.setWordWrap(True)
                meta.setStyleSheet("color: palette(placeholder-text); font-size: 10px;")
                tab_layout.addWidget(meta)

                flow_lbl = QLabel("Prompt-Flow-Vorschau")
                flow_lbl.setStyleSheet("color: palette(highlight); font-size: 10px; font-weight: bold;")
                tab_layout.addWidget(flow_lbl)

                flow_view = QTextEdit()
                flow_view.setReadOnly(True)
                flow_view.setStyleSheet("""
                    QTextEdit {
                        background: palette(base); color: palette(placeholder-text);
                        border: 1px solid palette(mid); border-radius: 4px;
                        padding: 6px; font-size: 10px;
                    }
                """)
                flow_view.setPlainText(_flow_preview_for_key(key))
                flow_view.setMaximumHeight(170)
                tab_layout.addWidget(flow_view)

                editor = QTextEdit()
                editor.setPlainText(prompt_values.get(key, ""))
                editor.setStyleSheet(editor_style)
                tab_layout.addWidget(editor, 1)

                inner_tabs.addTab(tab, title)
                self._editors[key] = editor
                group_keys[group].append(key)

            group_layout.addWidget(inner_tabs, 1)
            top_tabs.addTab(group_page, group)
            group_tabs[group] = inner_tabs

        layout.addWidget(top_tabs, 1)

        reset_btn = QPushButton("Reset Current To Default")
        reset_group_btn = QPushButton("Reset Group To Default")
        reset_all_btn = QPushButton("Reset All To Default")
        btn_style = (
            "QPushButton{background:palette(alternate-base);color:palette(text);"
            "border:none;border-radius:4px;padding:6px 10px;}"
            "QPushButton:hover{border:1px solid palette(highlight);}"
        )
        reset_btn.setStyleSheet(btn_style)
        reset_group_btn.setStyleSheet(btn_style)
        reset_all_btn.setStyleSheet(btn_style)

        def _current_key() -> str | None:
            gidx = top_tabs.currentIndex()
            if gidx < 0:
                return None
            group = top_tabs.tabText(gidx)
            inner = group_tabs.get(group)
            keys = group_keys.get(group, [])
            if inner is None:
                return None
            iidx = inner.currentIndex()
            if iidx < 0 or iidx >= len(keys):
                return None
            return keys[iidx]

        def _reset_current_prompt():
            key = _current_key()
            if not key:
                return
            ed = self._editors.get(key)
            if ed is not None:
                ed.setPlainText(prompt_defaults.get(key, ""))

        def _reset_current_group():
            gidx = top_tabs.currentIndex()
            if gidx < 0:
                return
            group = top_tabs.tabText(gidx)
            for key in group_keys.get(group, []):
                ed = self._editors.get(key)
                if ed is not None:
                    ed.setPlainText(prompt_defaults.get(key, ""))

        def _reset_all():
            for key, ed in self._editors.items():
                ed.setPlainText(prompt_defaults.get(key, ""))

        reset_btn.clicked.connect(_reset_current_prompt)
        reset_group_btn.clicked.connect(_reset_current_group)
        reset_all_btn.clicked.connect(_reset_all)

        action_row = QHBoxLayout()
        action_row.addWidget(reset_btn)
        action_row.addWidget(reset_group_btn)
        action_row.addWidget(reset_all_btn)
        action_row.addStretch()
        layout.addLayout(action_row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accept(self):
        new_prompts = self._llm_manager.get_prompt_set()
        for key, editor in self._editors.items():
            new_prompts[key] = editor.toPlainText()
        self._llm_manager.set_prompt_set(new_prompts)
        super().accept()
