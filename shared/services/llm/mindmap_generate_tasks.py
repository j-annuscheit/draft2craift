"""Model-based mindmap/graph generation for ``LLMManager``."""
from __future__ import annotations

import re
from typing import Any

from shared.domain.graph_codec import extract_graph_spec, spec_to_markdown

from .mindmap_chunk_tasks import _generate_chunk_mindmap_sync

_JSON_OBJECT_RE = re.compile(r"\{[\s\S]*\}")


def generate_mindmap_sync(
    self,
    *,
    context_text: str,
    query: str = "",
    mode: str = "mindmap",
    max_nodes: int = 28,
    chunking_strategy: str = "sliding_window",
    chunk_size: int = 900,
    chunk_overlap: int = 160,
) -> tuple[str, dict[str, Any]]:
    """Generate a structured MindMap/Wissensgraph markdown block."""
    context = str(context_text or "").strip()
    if not context:
        return "", {
            "applied": False,
            "reason": "empty_context",
        }
    mode_clean = self._normalize_mindmap_mode(mode)
    if mode_clean == "chunkmap":
        return self._generate_chunk_mindmap_sync(
            context_text=context,
            query=str(query or ""),
            max_nodes=max_nodes,
            chunking_strategy=chunking_strategy,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
    if not self.is_model_loaded():
        return "", {
            "applied": False,
            "reason": "model_not_loaded",
        }
    if self.worker.isRunning():
        if self._log:
            self._log.debug(
                "LLM",
                "MindMap generation skipped – model busy.",
            )
        return "", {
            "applied": False,
            "reason": "model_busy",
        }

    if mode_clean == "graph":
        system_key = "graph_system"
        user_key = "graph_user"
        hard_system_rules = (
            "HARTE REGELN (immer befolgen):\n"
            "- Kein Inhaltsverzeichnis und kein Kapitelgerüst ausgeben.\n"
            "- Nur Tripel im Format Subjekt | Relation | Objekt.\n"
            "- Relation darf nicht leer/generisch sein.\n"
            "- Keine Entitäts-Dubletten, keine Selbstkanten, keine Halluzinationen.\n"
            "- Ziel ist ein möglichst zusammenhängender Graph mit einer dominanten Hauptkomponente.\n"
            "- Neue Tripel sollen bevorzugt an bereits eingeführte Entitäten andocken.\n"
            "- Viele isolierte Mini-Subgraphen vermeiden; wenn nicht belegbar verbindbar, weglassen."
        )
        hard_user_rules = (
            "Zusatzregeln:\n"
            "- Verwerfe TOC-/Layout-Zeilen (z. B. \"Inhaltsverzeichnis\", \"1.2\", Seitenzahlen).\n"
            "- Wenn du nur Strukturüberschriften findest, gib stattdessen die stärksten inhaltlichen Beziehungen aus.\n"
            "- Bevorzuge gemeinsame Entitäten als Brücken zwischen Teilaspekten.\n"
            "- Isolierte Inseln nur wenn der Kontext keine belegbare Verbindung liefert."
        )
    else:
        system_key = "mindmap_system"
        user_key = "mindmap_user"
        hard_system_rules = (
            "HARTE REGELN (immer befolgen):\n"
            "- Kein Inhaltsverzeichnis und kein Kapitelgerüst ausgeben.\n"
            "- Nur konzeptuelle Knoten und Beziehungen (nicht Dokument-Navigation).\n"
            "- Blätter müssen Kurz-Zitate enthalten: Label :: \"Zitat\".\n"
            "- Keine Halluzinationen.\n"
            "- MindMap muss wirklich hierarchisch sein, nicht flache Liste:\n"
            "  * genau 1 Wurzelknoten,\n"
            "  * darunter 3-7 Hauptäste,\n"
            "  * pro Hauptast 2-4 Unterknoten,\n"
            "  * mehrere Blattknoten mit Direktzitaten.\n"
            "- Einrückung: exakt 2 Leerzeichen je Ebene.\n"
            "- Mehrere Einrückungsebenen sind ausdrücklich erlaubt.\n"
            "- Die Hierarchie wird ausschließlich über diese Einrückungen gebildet.\n"
            "- Hierarchierichtung strikt: Oben steht das übergeordnete Ganze, unten nur Teilaspekte/Unterkategorien/Belege.\n"
            "- Ein allgemeinerer Begriff darf niemals unter einem spezielleren Begriff stehen."
        )
        hard_user_rules = (
            "Zusatzregeln:\n"
            "- Verwerfe TOC-/Layout-Zeilen (z. B. \"Inhaltsverzeichnis\", \"1.2\", Seitenzahlen).\n"
            "- Wenn der Kontext viele Überschriften enthält, priorisiere dennoch inhaltliche Aussagen und Befunde.\n"
            "- Forme die Ausgabe als Baum (Konzept->Unterkonzept->Beleg), nicht als Stichwortsammlung.\n"
            "- Nutze bei Bedarf mehrere Einrückungsstufen; jede zusätzliche Einrückung ist eine tiefere Ebene.\n"
            "- Prüfe jede Eltern->Kind-Kante: Kind muss ein Teil/eine Spezifizierung des Elternknotens sein.\n"
            "- Wenn eine Kante umgekehrt ist (Unterpunkt allgemeiner als Parent), Richtung korrigieren."
        )
    limit = max(8, min(96, int(max_nodes)))
    question = str(query or "").strip()
    if not question:
        question = "Erstelle eine strukturierte Übersicht."

    system_prompt = str(self._prompts.get(system_key, "") or "").strip()
    if hard_system_rules not in system_prompt:
        system_prompt = (system_prompt + "\n\n" + hard_system_rules).strip()
    user_block = self._render_prompt_template(
        user_key,
        {
            "context": context,
            "query": question,
            "mode": mode_clean,
            "max_nodes": str(limit),
        },
    )
    user_block = str(user_block or "").strip()
    if hard_user_rules not in user_block:
        if mode_clean == "mindmap":
            # Keep context as final section in the user prompt.
            user_block = (hard_user_rules + "\n\n" + user_block).strip()
        else:
            user_block = (user_block + "\n\n" + hard_user_rules).strip()
    prompt = (
        "<|system|>\n"
        f"{system_prompt}\n"
        "<|user|>\n"
        f"{user_block}\n"
        "<|assistant|>\n"
    )
    max_out_tokens = max(320, min(3600, limit * 140))
    window_err = self._check_prompt_window(prompt, max_out_tokens)
    if window_err:
        if self._log:
            self._log.error("LLM", f"MindMap context too large: {window_err}")
        return "", {
            "applied": False,
            "reason": "context_too_large",
            "error": window_err,
        }

    try:
        raw_full = self._generate_backend_text(
            prompt,
            max_tokens=max_out_tokens,
            temperature=0.2,
            top_p=0.9,
            repeat_penalty=1.05,
            stop_tokens=["<|"],
        )
        self._log_llm_io("MindMap", prompt, raw_full)
        raw = str(raw_full or "").strip()
        if not raw:
            return "", {
                "applied": True,
                "reason": "empty",
            }

        spec = extract_graph_spec(raw)
        if spec is None:
            spec = extract_graph_spec(f"```{mode_clean}\n{raw}\n```")
        if spec is None:
            json_match = _JSON_OBJECT_RE.search(raw)
            if json_match is not None:
                candidate = f"```{mode_clean}\n{json_match.group(0)}\n```"
                spec = extract_graph_spec(candidate)
        if spec is None:
            return "", {
                "applied": False,
                "reason": "parse_failed",
                "raw_preview": raw[:320],
            }

        if mode_clean == "graph":
            spec.kind = "graph"
        else:
            spec.kind = "mindmap"

        if spec.title.strip() in {"MindMap", "Wissensgraph"} and question:
            prefix = "Wissensgraph" if spec.kind == "graph" else "MindMap"
            spec.title = f"{prefix}: {question[:96]}"

        if spec.kind == "graph":
            for edge in spec.edges:
                if not str(edge.label or "").strip():
                    edge.label = "bezogen_auf"
        else:
            for node in spec.nodes.values():
                if node.children:
                    continue
                quote = str(getattr(node, "quote", "") or "").strip()
                if quote:
                    continue
                desc = str(node.description or "").strip()
                if not desc:
                    continue
                node.quote = desc[:220]

        markdown = spec_to_markdown(spec)
        return markdown, {
            "applied": True,
            "reason": "ok",
            "kind": spec.kind,
            "nodes": len(spec.nodes),
            "edges": len(spec.edges),
        }
    except Exception as exc:
        self._log_llm_io("MindMap", prompt, error=str(exc))
        if self._log:
            self._log.error("LLM", f"MindMap generation failed: {exc}")
        return "", {
            "applied": False,
            "reason": "exception",
            "error": str(exc),
        }
