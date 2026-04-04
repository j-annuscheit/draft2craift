"""
Agent-based MindMap / Wissensgraph pipeline.

Design goals
────────────
• Budget = time (Sekunden). Das System misst echte LLM-Aufrufzeiten und
  reguliert sich selbst: kein festes Schritt-Limit.
• Vollständig agentenbasiert: Das LLM entscheidet Werkzeugwahl UND schreibt
  eigene Regex-Muster – kein Python-seitiges Pattern-Building.
• Iterative Verbesserung: suchen → Basiskarte → analysieren → nachsuchen →
  verbessern → … bis Budget erschöpft.
• Jeder Blattknoten erhält ein Zitat aus den gefundenen Belegen.
• Networkx stellt sicher, dass exakt ein zusammenhängender Graph entsteht.
• Kein hartes Knotenanzahl-Limit während der Laufzeit; max_nodes wird erst
  beim Finalisieren als Soft-Cap angewendet.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

try:
    import networkx as nx
    _NX = True
except Exception:
    _NX = False

from shared.services.agentic.contracts import StepTrace, WorkflowRunResult
from shared.domain.graph_codec import extract_graph_spec, spec_to_markdown
from shared.domain.graph_spec import GraphEdge, GraphNode, GraphSpec


def _as_int(
    value: object,
    *,
    default: int,
    min_value: int | None = None,
    max_value: int | None = None,
) -> int:
    try:
        out = int(value if value is not None else default)
    except Exception:
        out = int(default)
    if min_value is not None:
        out = max(int(min_value), out)
    if max_value is not None:
        out = min(int(max_value), out)
    return out


def _as_float(
    value: object,
    *,
    default: float,
    min_value: float | None = None,
    max_value: float | None = None,
) -> float:
    try:
        out = float(value if value is not None else default)
    except Exception:
        out = float(default)
    if min_value is not None:
        out = max(float(min_value), out)
    if max_value is not None:
        out = min(float(max_value), out)
    return out


# ── Zeitbasiertes Budget ─────────────────────────────────────────────────────

@dataclass
class _Budget:
    """
    Misst LLM-Aufrufzeiten und schätzt, ob noch ein weiterer Aufruf möglich ist.

    Parameter
    ---------
    max_seconds
        Maximal erlaubte Gesamtlaufzeit.  Vom Nutzer vorgegeben.
    """
    max_seconds: float
    _start: float = field(default_factory=time.perf_counter, init=False, repr=False)
    _llm_times: list[float] = field(default_factory=list, init=False, repr=False)
    _virtual_elapsed: float = field(default=0.0, init=False, repr=False)

    def elapsed(self) -> float:
        wall = time.perf_counter() - self._start
        return max(wall, self._virtual_elapsed)

    def remaining(self) -> float:
        return max(0.0, self.max_seconds - self.elapsed())

    def record(self, seconds: float) -> None:
        """Gemessene Dauer eines LLM-Aufrufs registrieren."""
        # Kleine Modelle/Stubs können künstlich "zu schnell" erscheinen.
        # Ein realistischer Mindestwert verhindert überlange Loops im
        # zeitbasierten Budget-Controller.
        charged = max(0.35, float(seconds))
        self._llm_times.append(charged)
        self._virtual_elapsed += charged

    def avg_llm_s(self) -> float:
        """Durchschnittliche LLM-Aufrufzeit (Sekunden)."""
        return sum(self._llm_times) / len(self._llm_times) if self._llm_times else 8.0

    def can_llm(self, safety: float = 1.8) -> bool:
        """True wenn vermutlich noch Zeit für einen LLM-Aufruf vorhanden ist."""
        return self.remaining() > self.avg_llm_s() * safety

    def est_calls(self) -> int:
        """Grobe Schätzung: wie viele LLM-Aufrufe passen noch ins Budget."""
        a = self.avg_llm_s()
        return max(0, int(self.remaining() / a)) if a > 0 else 0

    def summary(self) -> dict[str, Any]:
        return {
            "budget_s": round(self.max_seconds, 1),
            "elapsed_s": round(self.elapsed(), 1),
            "remaining_s": round(self.remaining(), 1),
            "avg_llm_s": round(self.avg_llm_s(), 2),
            "llm_calls": len(self._llm_times),
        }


@dataclass(frozen=True)
class _PipelineTuning:
    """
    Zentralisierte Pipeline-Tuningwerte.

    Damit vermeiden wir verstreute Magic Numbers und können Pro-Settings
    ohne Code-Änderungen erweitern.
    """

    max_enriched_context_chars: int = 90_000
    concept_context_chars: int = 6_000
    concept_preview_chars: int = 1_200
    concept_fallback_terms: int = 12
    gather_llm_safety: float = 1.3
    refine_llm_safety: float = 2.4
    final_refine_safety: float = 2.9
    max_consecutive_errors: int = 8
    rag_top_k: int = 6
    full_text_default_chars: int = 3_200
    obs_window: int = 3
    working_nodes_multiplier: int = 3
    working_nodes_floor: int = 64
    max_working_nodes: int = 1024
    max_logged_steps: int = 0
    quote_max_chars: int = 320
    force_agent_retrieval: bool = False

    @classmethod
    def from_request(cls, request: dict[str, Any]) -> "_PipelineTuning":
        raw = dict(request or {})
        return cls(
            max_enriched_context_chars=_as_int(
                raw.get("agent_max_enriched_context_chars"),
                default=90_000,
                min_value=8_000,
                max_value=1_000_000,
            ),
            concept_context_chars=_as_int(
                raw.get("agent_concept_context_chars"),
                default=6_000,
                min_value=600,
                max_value=64_000,
            ),
            concept_preview_chars=_as_int(
                raw.get("agent_concept_preview_chars"),
                default=1_200,
                min_value=200,
                max_value=8_000,
            ),
            concept_fallback_terms=_as_int(
                raw.get("agent_concept_fallback_terms"),
                default=12,
                min_value=2,
                max_value=80,
            ),
            gather_llm_safety=_as_float(
                raw.get("agent_gather_safety_factor"),
                default=1.3,
                min_value=0.8,
                max_value=6.0,
            ),
            refine_llm_safety=_as_float(
                raw.get("agent_refine_safety_factor"),
                default=2.4,
                min_value=0.8,
                max_value=8.0,
            ),
            final_refine_safety=_as_float(
                raw.get("agent_final_refine_safety_factor"),
                default=2.9,
                min_value=0.8,
                max_value=12.0,
            ),
            max_consecutive_errors=_as_int(
                raw.get("agent_max_consecutive_errors"),
                default=8,
                min_value=2,
                max_value=200,
            ),
            rag_top_k=_as_int(
                raw.get("agent_rag_top_k"),
                default=6,
                min_value=1,
                max_value=50,
            ),
            full_text_default_chars=_as_int(
                raw.get("agent_full_text_default_chars"),
                default=3_200,
                min_value=256,
                max_value=200_000,
            ),
            obs_window=_as_int(
                raw.get("agent_observation_window"),
                default=3,
                min_value=1,
                max_value=12,
            ),
            working_nodes_multiplier=_as_int(
                raw.get("agent_working_nodes_multiplier"),
                default=3,
                min_value=1,
                max_value=16,
            ),
            working_nodes_floor=_as_int(
                raw.get("agent_working_nodes_floor"),
                default=64,
                min_value=4,
                max_value=4096,
            ),
            max_working_nodes=_as_int(
                raw.get("agent_max_working_nodes"),
                default=1024,
                min_value=16,
                max_value=8192,
            ),
            max_logged_steps=_as_int(
                raw.get("agent_max_logged_steps"),
                default=0,
                min_value=0,
                max_value=100_000,
            ),
            quote_max_chars=_as_int(
                raw.get("agent_quote_max_chars"),
                default=320,
                min_value=80,
                max_value=2_000,
            ),
            force_agent_retrieval=bool(raw.get("force_agent_retrieval", False)),
        )


# ── Networkx: zusammenhängender Graph ────────────────────────────────────────

def _ensure_connected(spec: GraphSpec) -> GraphSpec:
    """
    Stellt sicher, dass der resultierende Graph aus genau einer Komponente
    besteht. Fehlende Verbindungen werden an einen zentralen Ankerknoten
    angehängt.
    """
    if not spec.nodes:
        return spec

    # Ankerknoten: bevorzugt Wurzel, sonst erster Knoten nach Grad.
    root = ""
    if spec.roots:
        candidate = str(spec.roots[0] or "").strip()
        if candidate in spec.nodes:
            root = candidate
    if not root:
        degrees: dict[str, int] = {nid: 0 for nid in spec.nodes}
        for nid, node in spec.nodes.items():
            for cid in (node.children or []):
                if cid in degrees:
                    degrees[nid] += 1
                    degrees[cid] += 1
        for edge in spec.edges:
            if edge.source_id in degrees:
                degrees[edge.source_id] += 1
            if edge.target_id in degrees:
                degrees[edge.target_id] += 1
        root = max(degrees.items(), key=lambda row: (row[1], row[0]))[0]
    if root not in spec.nodes:
        return spec
    if not spec.roots:
        spec.roots = [root]

    # Komponenten (ungerichtet) bestimmen.
    if _NX:
        G: Any = nx.Graph()
        for nid in spec.nodes:
            G.add_node(nid)
        for nid, node in spec.nodes.items():
            for cid in (node.children or []):
                if cid in spec.nodes:
                    G.add_edge(nid, cid)
        for edge in spec.edges:
            if edge.source_id in spec.nodes and edge.target_id in spec.nodes:
                G.add_edge(edge.source_id, edge.target_id)
        components = [set(comp) for comp in nx.connected_components(G)] if len(G) > 0 else []
    else:
        neighbors: dict[str, set[str]] = {nid: set() for nid in spec.nodes}
        for nid, node in spec.nodes.items():
            for cid in (node.children or []):
                if cid in neighbors:
                    neighbors[nid].add(cid)
                    neighbors[cid].add(nid)
        for edge in spec.edges:
            if edge.source_id in neighbors and edge.target_id in neighbors:
                neighbors[edge.source_id].add(edge.target_id)
                neighbors[edge.target_id].add(edge.source_id)
        components: list[set[str]] = []
        seen: set[str] = set()
        for nid in neighbors:
            if nid in seen:
                continue
            comp: set[str] = set()
            stack = [nid]
            while stack:
                cur = stack.pop()
                if cur in seen:
                    continue
                seen.add(cur)
                comp.add(cur)
                stack.extend(list(neighbors.get(cur, set()) - seen))
            components.append(comp)

    if len(components) <= 1:
        return spec

    # Komponente mit root zuerst.
    components.sort(key=lambda comp: (root not in comp, -len(comp)))
    root_node = spec.nodes[root]
    existing_edges = {(e.source_id, e.target_id) for e in spec.edges}
    for comp in components:
        if root in comp:
            continue
        target = sorted(comp)[0]
        if target not in spec.nodes:
            continue
        if target not in root_node.children:
            root_node.children.append(target)
        if (root, target) not in existing_edges:
            existing_edges.add((root, target))
            spec.edges.append(
                GraphEdge(
                    source_id=root,
                    target_id=target,
                    label="related_to" if str(spec.kind or "").casefold() == "graph" else "",
                )
            )
    return spec


# ── Blattknoten-Zitate ────────────────────────────────────────────────────────


def _trim_spec_to_max_nodes(spec: GraphSpec, *, max_nodes: int) -> GraphSpec:
    """
    Kürzt eine zu große Karte deterministisch auf max_nodes.

    Reihenfolge:
    1) BFS ab Wurzel(n)
    2) Falls nötig: restliche Knoten nach Grad ergänzen
    """
    limit = max(2, int(max_nodes or 2))
    if len(spec.nodes) <= limit:
        return spec

    keep_order: list[str] = []
    keep_set: set[str] = set()
    queue: list[str] = []

    for nid in list(spec.roots or []):
        if nid in spec.nodes and nid not in keep_set:
            queue.append(nid)
    if not queue and spec.nodes:
        queue.append(next(iter(spec.nodes.keys())))

    while queue and len(keep_set) < limit:
        nid = str(queue.pop(0) or "")
        if nid not in spec.nodes or nid in keep_set:
            continue
        keep_set.add(nid)
        keep_order.append(nid)
        node = spec.nodes[nid]
        for cid in list(node.children or []):
            if cid in spec.nodes and cid not in keep_set:
                queue.append(cid)
        for edge in spec.edges:
            if edge.source_id == nid and edge.target_id in spec.nodes and edge.target_id not in keep_set:
                queue.append(edge.target_id)
            if edge.target_id == nid and edge.source_id in spec.nodes and edge.source_id not in keep_set:
                queue.append(edge.source_id)

    if len(keep_set) < limit:
        degree: dict[str, int] = {nid: 0 for nid in spec.nodes}
        for nid, node in spec.nodes.items():
            for cid in list(node.children or []):
                if cid in degree:
                    degree[nid] += 1
                    degree[cid] += 1
        for edge in spec.edges:
            if edge.source_id in degree:
                degree[edge.source_id] += 1
            if edge.target_id in degree:
                degree[edge.target_id] += 1
        for nid, _deg in sorted(degree.items(), key=lambda row: (-row[1], row[0])):
            if len(keep_set) >= limit:
                break
            if nid in keep_set:
                continue
            keep_set.add(nid)
            keep_order.append(nid)

    new_nodes: dict[str, GraphNode] = {}
    for nid in keep_order:
        node = spec.nodes.get(nid)
        if node is None:
            continue
        children = [cid for cid in list(node.children or []) if cid in keep_set]
        new_nodes[nid] = GraphNode(
            node_id=str(node.node_id or nid),
            label=str(node.label or nid),
            description=str(node.description or ""),
            quote=str(node.quote or ""),
            href=str(node.href or ""),
            children=children,
        )

    new_edges = [
        GraphEdge(
            source_id=str(edge.source_id or ""),
            target_id=str(edge.target_id or ""),
            label=str(edge.label or ""),
        )
        for edge in list(spec.edges or [])
        if str(edge.source_id or "") in keep_set and str(edge.target_id or "") in keep_set
    ]
    roots = [rid for rid in list(spec.roots or []) if rid in keep_set]
    if not roots and keep_order:
        roots = [keep_order[0]]

    return GraphSpec(
        kind=str(spec.kind or "mindmap"),
        title=str(spec.title or ""),
        nodes=new_nodes,
        edges=new_edges,
        roots=roots,
        default_collapsed_ids=[nid for nid in list(spec.default_collapsed_ids or []) if nid in keep_set],
    )


def _sentence_candidates(text: str) -> list[str]:
    out: list[str] = []
    raw = str(text or "").strip()
    if not raw:
        return out
    normalized = re.sub(r"\s+", " ", raw)
    for sentence in re.split(r"(?<=[.!?])\s+", normalized):
        row = str(sentence or "").strip()
        if len(row) < 12:
            continue
        out.append(row)
    return out


def _build_quote_pool(snippets: list[str], context_text: str) -> list[str]:
    pool: list[str] = []
    seen: set[str] = set()
    for source in list(snippets or []) + [str(context_text or "")]:
        for sent in _sentence_candidates(str(source or "")):
            key = sent.casefold()
            if key in seen:
                continue
            seen.add(key)
            pool.append(sent)
    return pool


def _norm_label(text: str) -> str:
    raw = str(text or "").casefold()
    raw = re.sub(r"[^\w\s]", " ", raw, flags=re.UNICODE)
    raw = re.sub(r"\s+", " ", raw).strip()
    return raw


def _strict_missing_required_main_nodes(markdown: str, required_nodes: list[str]) -> list[str]:
    required = [str(x or "").strip() for x in list(required_nodes or []) if str(x or "").strip()]
    if not required:
        return []
    spec = extract_graph_spec(str(markdown or ""))
    if spec is None:
        return required
    labels: list[str] = []
    if spec.roots:
        rid = str(spec.roots[0] or "").strip()
        root = dict(spec.nodes or {}).get(rid)
        if root is not None:
            for cid in list(getattr(root, "children", []) or []):
                child = dict(spec.nodes or {}).get(str(cid or "").strip())
                lbl = str(getattr(child, "label", "") or "").strip()
                if lbl:
                    labels.append(lbl)
    if not labels:
        labels = [str(getattr(n, "label", "") or "").strip() for n in list(dict(spec.nodes or {}).values())]
    norm_labels = [_norm_label(x) for x in labels if _norm_label(x)]
    missing: list[str] = []
    for req in required:
        req_norm = _norm_label(req)
        if not req_norm:
            continue
        if any(lbl == req_norm for lbl in norm_labels):
            continue
        missing.append(req)
    return missing


def _add_leaf_citations(
    spec: GraphSpec,
    snippets: list[str],
    *,
    context_text: str,
    quote_max_chars: int,
) -> GraphSpec:
    """
    Jedem Blattknoten ohne Quote wird das am besten passende Zitat zugewiesen.
    Die relevanteste Einzelaussage (Satz) wird als Zitat extrahiert.
    """
    quote_pool = _build_quote_pool(list(snippets or []), str(context_text or ""))
    if not quote_pool or not spec.nodes:
        return spec

    for node in spec.nodes.values():
        if node.children or node.quote:
            continue  # kein Blatt oder bereits zitiert
        words = [w for w in re.findall(r"\w+", node.label.casefold()) if len(w) > 3]
        if not words and str(node.label or "").strip():
            words = [str(node.label).casefold()]

        best_snip, best_score = "", -1
        for snip in quote_pool:
            low = snip.casefold()
            sc = sum(1 for w in words if w in low)
            if sc > best_score:
                best_score, best_snip = sc, snip

        if not best_snip:
            continue

        quote = str(best_snip or "").strip()
        node.quote = quote[: max(80, int(quote_max_chars or 320))].strip()

    return spec


# ── Hilfsfunktionen ───────────────────────────────────────────────────────────

def _jparse(text: str) -> dict[str, Any]:
    """Extrahiert robustly das erste JSON-Objekt aus LLM-Ausgabe."""
    t = str(text or "").strip()
    # Direktes Parsen
    try:
        v = json.loads(t)
        if isinstance(v, dict):
            return v
    except Exception:
        pass
    # Erstes {...}-Objekt suchen
    depth = start = -1
    for i, ch in enumerate(t):
        if ch == "{":
            if depth < 0:
                start = i
            depth = (depth if depth >= 0 else 0) + 1
        elif ch == "}" and depth > 0:
            depth -= 1
            if depth == 0:
                try:
                    v = json.loads(t[start: i + 1])
                    if isinstance(v, dict):
                        return v
                except Exception:
                    pass
                start = depth = -1
    return {}


def _clip(text: str, n: int) -> str:
    t = str(text or "").strip()
    return t if len(t) <= n else t[: n - 3] + "..."


def _get(tools: dict, name: str) -> Any:
    fn = (tools or {}).get(name)
    return fn if callable(fn) else None


def _enriched_context(snippets: list[str], context: str, max_c: int = 45_000) -> str:
    """Kombiniert gefundene Belege mit dem Quellkontext."""
    parts: list[str] = []
    if snippets:
        parts.append("## Gefundene Belege\n" + "\n\n".join(s for s in snippets if s))
    if context:
        used = sum(len(p) for p in parts)
        budget = max_c - used
        if budget > 200:
            parts.append(context[:budget])
    return "\n\n".join(parts)


def _ingest(new_hits: list[str], snippets: list[str], seen: set[str]) -> int:
    """Fügt neue, noch nicht gesehene Snippets zur Liste hinzu."""
    added = 0
    for h in new_hits:
        k = str(h or "").strip()[:200]
        if k and k not in seen:
            seen.add(k)
            snippets.append(h)
            added += 1
    return added


def _call_map(llm_map: Any, query: str, context: str, max_nodes: int, is_graph: bool) -> str:
    """Ruft den Karten-Generator auf und gibt Markdown zurück."""
    try:
        res = llm_map(
            mode="graph" if is_graph else "mindmap",
            query=query,
            context_text=context,
            max_nodes=max_nodes,
        )
        return str((res[0] if isinstance(res, tuple) else res) or "")
    except Exception:
        return ""


# ── Schritt 1: Konzeptextraktion ──────────────────────────────────────────────

def _step_concepts(
    llm: Any,
    query: str,
    ctx: str,
    budget: _Budget,
    traces: list[StepTrace],
    *,
    tuning: _PipelineTuning,
) -> tuple[list[str], list[str]]:
    """LLM extrahiert Schlüsselkonzepte und Suchanfragen."""
    t0 = time.perf_counter()
    fallback_concepts = [
        w for w in re.findall(r"\w+", query) if len(w) > 3
    ][: max(3, int(tuning.concept_fallback_terms))]

    if not callable(llm):
        traces.append(StepTrace("concept_extraction", "skipped", 0,
                                output={"reason": "no_llm"}))
        return fallback_concepts, [query]

    prompt = (
        f"Analysiere Anfrage und Kontext.\n"
        f"Anfrage: {_clip(query, 200)}\n"
        f"Kontext (Vorschau): {_clip(ctx, max(200, int(tuning.concept_preview_chars)))}\n\n"
        f"Antworte NUR mit JSON:\n"
        f'{{"concepts":["Begriff1","Begriff2",...],'
        f'"search_queries":["Suchanfrage1","Suchanfrage2",...]}}'
    )
    t1 = time.perf_counter()
    raw = str(llm(prompt=prompt) or "")
    budget.record(time.perf_counter() - t1)

    p = _jparse(raw)
    concepts = [str(c) for c in list(p.get("concepts", [])) if c]
    queries = [str(q) for q in list(p.get("search_queries", [])) if q]

    if not concepts:
        concepts = fallback_concepts
    if not queries:
        queries = [query]

    traces.append(StepTrace(
        "concept_extraction", "ok",
        (time.perf_counter() - t0) * 1000,
        output={"concepts": len(concepts), "queries": len(queries)},
    ))
    return concepts, queries


# ── Schritt 2: Informationssammlung ──────────────────────────────────────────

def _step_gather(
    *,
    tools: dict,
    llm: Any,
    query: str,
    concepts: list[str],
    queries: list[str],
    context: str,
    strategy: str,
    allow_rag: bool,
    allow_regex: bool,
    allow_heading: bool,
    allow_full_text: bool,
    max_regex_calls: int,
    max_consecutive_nohit: int,
    max_consecutive_stale: int,
    max_iterations: int,
    is_graph: bool,
    budget: _Budget,
    traces: list[StepTrace],
    tuning: _PipelineTuning,
) -> tuple[list[str], str]:
    """
    Sammelt Textbelege via RAG, Regex, Überschriften- oder Volltext-Suche.

    strategy="rag"   → feste semantische Suche für alle Suchanfragen
    strategy="agent" → LLM wählt Werkzeuge und schreibt eigene Regex-Muster
    strategy="none"  → übersprungen
    """
    snippets: list[str] = []
    seen: set[str] = set()
    steps: list[dict] = []
    t0 = time.perf_counter()
    regex_calls = 0
    draft_hint = ""

    # ── Feste RAG-Strategie ──────────────────────────────────────────────────
    if strategy == "rag":
        rag = _get(tools, "rag.search") or _get(tools, "rag_search")
        if rag:
            for q in queries:
                if budget.remaining() < 0.25:
                    break
                try:
                    top_k = max(1, int(tuning.rag_top_k))
                    hits = list(rag(query=q, top_k=top_k, mode="hybrid") or [])
                    n = _ingest(hits, snippets, seen)
                    steps.append(
                        {
                            "tool": "rag.search",
                            "query": _clip(q, 120),
                            "raw_hits": len(hits),
                            "new_hits": n,
                            "duplicate_hits": max(0, len(hits) - n),
                        }
                    )
                except Exception as exc:
                    steps.append({"tool": "rag.search", "error": _clip(str(exc), 140)})
        traces.append(StepTrace(
            "information_gathering", "ok",
            (time.perf_counter() - t0) * 1000,
            output={"strategy": "rag", "snippets": len(snippets), "steps": steps},
        ))
        return snippets, ""

    # ── Agentenstrategie: LLM entscheidet Werkzeuge & Muster ────────────────
    if not callable(llm):
        traces.append(StepTrace("information_gathering", "skipped", 0,
                                output={"reason": "no_llm", "strategy": strategy}))
        return snippets, ""

    # Verfügbare Werkzeuge ermitteln
    avail: list[str] = []
    if allow_rag and (_get(tools, "rag.search") or _get(tools, "rag_search")):
        avail.append("rag.search")
    if allow_regex and _get(tools, "regex_search"):
        avail.append("regex_search")
    if allow_heading and _get(tools, "heading_search"):
        avail.append("heading_search")
    if allow_full_text and _get(tools, "full_text"):
        avail.append("full_text")

    if not avail:
        traces.append(StepTrace("information_gathering", "skipped", 0,
                                output={"reason": "no_tools", "strategy": strategy}))
        return snippets, ""

    obs: list[str] = []
    it = 0
    consecutive_errors = 0
    consecutive_nohit = 0
    consecutive_stale = 0

    while budget.can_llm(safety=float(tuning.gather_llm_safety)):
        if int(max_iterations or 0) > 0 and it >= int(max_iterations):
            steps.append({"it": it, "action": "max_iterations_reached", "limit": int(max_iterations)})
            break
        it += 1
        # Beispiele für das LLM bauen
        ex: list[str] = []
        if "rag.search" in avail:
            ex.append('{"action":"tool","tool":"rag.search","args":{"query":"SUCHANFRAGE","top_k":5}}')
        if "regex_search" in avail:
            ex.append('{"action":"tool","tool":"regex_search","args":{"pattern":"DEIN_REGEX_MUSTER","max_results":8}}')
        if "heading_search" in avail:
            ex.append('{"action":"tool","tool":"heading_search","args":{"pattern":"ÜBERSCHRIFT_MUSTER"}}')
        if "full_text" in avail:
            ex.append(
                '{"action":"tool","tool":"full_text","args":{"max_chars":'
                f"{max(256, int(tuning.full_text_default_chars))}"
                "}}"
            )
        ex.append('{"action":"finish","reason":"genug Belege gefunden"}')

        prompt = (
            f"Sammle Belege für "
            f"{'Wissensgraph' if is_graph else 'MindMap'}: {_clip(query, 100)}\n"
            f"Konzepte: {', '.join(concepts[: max(4, int(tuning.concept_fallback_terms))])}\n"
            f"Snippets bisher: {len(snippets)} | Budget: ~{budget.est_calls()} Aufrufe\n"
            f"Zuletzt: {chr(10).join(obs[- max(1, int(tuning.obs_window)):]) or '(noch keine)'}\n\n"
            f"Werkzeuge: {', '.join(avail)}\n\n"
            f"WICHTIG bei regex_search: Schreibe dein eigenes Python-Regex-Muster!\n"
            f"Antworte NUR JSON (ein Werkzeug oder finish):\n"
            + "\n".join(ex)
            + "\nJSON:"
        )
        t1 = time.perf_counter()
        raw = str(llm(prompt=prompt) or "")
        budget.record(time.perf_counter() - t1)

        plan = _jparse(raw)
        action = str(plan.get("action", "") or "").strip().casefold()
        tname = str(plan.get("tool", "") or "").strip()
        if not action:
            spec_hint = extract_graph_spec(raw)
            if spec_hint is not None:
                draft_hint = str(raw or "").strip()
                steps.append({"it": it, "action": "finish_with_draft_hint", "reason": "map_like_output"})
                break
        if tname == "rag_search":
            tname = "rag.search"

        # Normalisierung: falls LLM "tool" als action-Wert ausgibt
        if action in {t.replace(".", "_") for t in avail} | set(avail):
            tname = action if action in avail else action.replace("_", ".", 1)
            action = "tool"

        if action == "finish":
            steps.append({"it": it, "action": "finish",
                          "reason": _clip(str(plan.get("reason", "") or ""), 160)})
            break

        if action == "tool" and tname in avail:
            args = plan.get("args", {})
            args = dict(args) if isinstance(args, dict) else {}
            if tname == "regex_search" and int(max_regex_calls or 0) > 0 and regex_calls >= int(max_regex_calls):
                steps.append(
                    {
                        "it": it,
                        "tool": tname,
                        "skipped": "regex_limit_reached",
                        "regex_calls": regex_calls,
                    }
                )
                consecutive_errors += 1
                if consecutive_errors >= int(tuning.max_consecutive_errors):
                    steps.append({"it": it, "action": "abort", "reason": "too_many_errors"})
                    break
                continue
            fn = _get(tools, tname) or _get(tools, tname.replace(".", "_"))
            if callable(fn):
                try:
                    res = fn(**args) if args else fn()
                    hits = list(res or []) if isinstance(res, (list, tuple)) else (
                        [str(res)] if res else []
                    )
                    hits = [str(h).strip() for h in hits if str(h or "").strip()]
                    n = _ingest(hits, snippets, seen)
                    if tname == "regex_search":
                        regex_calls += 1
                    if len(hits) <= 0:
                        consecutive_nohit += 1
                    else:
                        consecutive_nohit = 0
                    if int(n or 0) <= 0:
                        consecutive_stale += 1
                    else:
                        consecutive_stale = 0
                    if hits:
                        obs.append(f"{tname}: {_clip(hits[0], 110)}")
                    steps.append(
                        {
                            "it": it,
                            "action": "tool",
                            "tool": tname,
                            "raw_hits": len(hits),
                            "new_hits": n,
                            "duplicate_hits": max(0, len(hits) - n),
                            "total_snippets": len(snippets),
                            "regex_calls": regex_calls,
                            "args": {k: _clip(str(v), 120) for k, v in args.items()},
                        }
                    )
                    consecutive_errors = 0
                except Exception as exc:
                    steps.append({"it": it, "tool": tname, "error": _clip(str(exc), 160)})
                    consecutive_errors += 1
                    consecutive_nohit += 1
                    consecutive_stale += 1
        else:
            # Ungültige Antwort → Policy-Fallback: günstigstes verfügbares Werkzeug
            fb = next((t for t in ["rag.search", "heading_search", "regex_search"] if t in avail), "")
            if fb:
                fb_fn = _get(tools, fb)
                fb_args: dict[str, Any] = {}
                if fb == "regex_search":
                    if int(max_regex_calls or 0) > 0 and regex_calls >= int(max_regex_calls):
                        fb = next((t for t in ["heading_search", "rag.search"] if t in avail), "")
                        fb_fn = _get(tools, fb) if fb else None
                    kw = "|".join(
                        re.escape(c)
                        for c in concepts[: max(2, min(6, int(tuning.concept_fallback_terms)))]
                        if len(c) > 3
                    )
                    fb_args = {"pattern": kw or re.escape(_clip(query, 30)), "max_results": 5}
                elif fb == "heading_search":
                    kw = (
                        "|".join(concepts[: max(2, min(6, int(tuning.concept_fallback_terms)))])
                        if concepts
                        else query[:30]
                    )
                    fb_args = {"pattern": kw}
                elif fb == "rag.search":
                    q_fb = queries[it % len(queries)] if queries else query
                    fb_args = {"query": q_fb, "top_k": max(1, int(tuning.rag_top_k))}
                if callable(fb_fn):
                    try:
                        res = fb_fn(**fb_args) if fb_args else fb_fn()
                        hits = list(res or []) if isinstance(res, (list, tuple)) else []
                        hits = [str(h).strip() for h in hits if str(h or "").strip()]
                        n = _ingest(hits, snippets, seen)
                        if fb == "regex_search":
                            regex_calls += 1
                        if len(hits) <= 0:
                            consecutive_nohit += 1
                        else:
                            consecutive_nohit = 0
                        if int(n or 0) <= 0:
                            consecutive_stale += 1
                        else:
                            consecutive_stale = 0
                        steps.append(
                            {
                                "it": it,
                                "action": "policy_tool",
                                "tool": fb,
                                "raw_hits": len(hits),
                                "new_hits": n,
                                "duplicate_hits": max(0, len(hits) - n),
                                "total_snippets": len(snippets),
                                "fallback": True,
                                "reason": "invalid_plan_recovery",
                                "regex_calls": regex_calls,
                            }
                        )
                        consecutive_errors = 0
                    except Exception:
                        consecutive_errors += 1
                        consecutive_nohit += 1
                        consecutive_stale += 1
            else:
                consecutive_errors += 1
                consecutive_nohit += 1
                consecutive_stale += 1

        if consecutive_errors >= int(tuning.max_consecutive_errors):
            steps.append({"it": it, "action": "abort", "reason": "too_many_errors"})
            break
        if int(max_consecutive_nohit or 0) > 0 and consecutive_nohit >= int(max_consecutive_nohit):
            steps.append(
                {
                    "it": it,
                    "action": "finish_no_signal",
                    "reason": "consecutive_nohit_limit",
                    "limit": int(max_consecutive_nohit),
                }
            )
            break
        if int(max_consecutive_stale or 0) > 0 and consecutive_stale >= int(max_consecutive_stale):
            steps.append(
                {
                    "it": it,
                    "action": "finish_no_signal",
                    "reason": "consecutive_stale_limit",
                    "limit": int(max_consecutive_stale),
                }
            )
            break

    if not steps or str(steps[-1].get("action", "") or "").casefold() != "finish":
        steps.append({"it": it, "action": "budget_exhausted", "remaining_s": round(budget.remaining(), 3)})

    logged_steps = list(steps)
    dropped_steps = 0
    max_log = int(tuning.max_logged_steps or 0)
    if max_log > 0 and len(logged_steps) > max_log:
        dropped_steps = len(logged_steps) - max_log
        logged_steps = logged_steps[-max_log:]

    traces.append(StepTrace(
        "information_gathering", "ok",
        (time.perf_counter() - t0) * 1000,
        output={
            "strategy": strategy,
            "snippets": len(snippets),
            "iterations": it,
            "regex_calls": regex_calls,
            "has_draft_hint": bool(draft_hint),
            "steps_dropped": dropped_steps,
            "steps": logged_steps,
        },
    ))
    return snippets, draft_hint


# ── Schritt 3: Basiskarte erstellen ──────────────────────────────────────────

def _step_base_map(
    *,
    llm_map: Any,
    query: str,
    snippets: list[str],
    context: str,
    working_max_nodes: int,
    context_max_chars: int,
    is_graph: bool,
    budget: _Budget,
    traces: list[StepTrace],
    tuning: _PipelineTuning,
) -> str:
    """LLM erstellt die initiale Karte aus allen gesammelten Belegen."""
    if not callable(llm_map):
        traces.append(StepTrace("base_map", "skipped", 0, output={"reason": "no_llm_map"}))
        return ""

    ctx = _enriched_context(
        snippets,
        context,
        max_c=max(8_000, int(context_max_chars)),
    )
    t0 = time.perf_counter()
    md = _call_map(llm_map, query, ctx, int(working_max_nodes), is_graph)
    budget.record(time.perf_counter() - t0)

    spec = extract_graph_spec(md)
    n = len(spec.nodes) if spec else 0
    traces.append(StepTrace(
        "base_map", "ok" if spec else "empty",
        (time.perf_counter() - t0) * 1000,
        output={
            "node_count": n,
            "ctx_chars": len(ctx),
            "context_max_chars": int(context_max_chars),
            "working_max_nodes": int(working_max_nodes),
        },
    ))
    return md


# ── Schritt 4: Iterative Verbesserung ────────────────────────────────────────

def _step_refine(
    *,
    llm: Any,
    llm_map: Any,
    tools: dict,
    query: str,
    markdown: str,
    snippets: list[str],
    context: str,
    max_nodes: int,
    working_max_nodes: int,
    context_max_chars: int,
    is_graph: bool,
    allow_rag: bool,
    allow_regex: bool,
    allow_heading: bool,
    allow_full_text: bool,
    max_regex_calls: int,
    budget: _Budget,
    traces: list[StepTrace],
    tuning: _PipelineTuning,
) -> str:
    """
    Agent-Schleife: Karte analysieren → Lücken suchen → Karte verbessern.
    Läuft bis das Budget erschöpft ist oder das LLM "done" wählt.
    """
    if not callable(llm):
        return markdown

    # Lokaler Import um zirkuläre Abhängigkeit beim Laden zu vermeiden
    from shared.services.agentic.service import _merge_mindmap_specs  # noqa: PLC0415

    avail_search: list[str] = []
    if allow_rag and (_get(tools, "rag.search") or _get(tools, "rag_search")):
        avail_search.append("rag.search")
    if allow_regex and _get(tools, "regex_search"):
        avail_search.append("regex_search")
    if allow_heading and _get(tools, "heading_search"):
        avail_search.append("heading_search")
    if allow_full_text and _get(tools, "full_text"):
        avail_search.append("full_text")

    seen_snippets: set[str] = {s[:200] for s in snippets}
    rnd = 0

    while budget.can_llm(safety=float(tuning.refine_llm_safety)):
        rnd += 1
        spec = extract_graph_spec(markdown)
        n = len(spec.nodes) if spec else 0

        # Kompakte Kartenzusammenfassung für den Prompt
        if spec:
            top_labels = [v.label for v in list(spec.nodes.values())[:8]]
            summary = (
                f"Titel: {spec.title} | Knoten: {n} | "
                f"Hauptäste: {', '.join(top_labels)}"
            )
        else:
            summary = "(noch keine Karte)"

        # Suchbeispiele aufbauen
        search_ex_lines: list[str] = []
        for st in avail_search[:2]:
            if st == "rag.search":
                search_ex_lines.append(
                    '{"action":"search","tool":"rag.search","args":{"query":"SUCHANFRAGE","top_k":5}}'
                )
            elif st == "regex_search":
                search_ex_lines.append(
                    '{"action":"search","tool":"regex_search",'
                    '"args":{"pattern":"DEIN_REGEX","max_results":8}}'
                )
            elif st == "heading_search":
                search_ex_lines.append(
                    '{"action":"search","tool":"heading_search","args":{"pattern":"MUSTER"}}'
                )

        rebuild_ex = (
            '{"action":"rebuild","focus":"FOKUS_THEMA"}'
            if callable(llm_map) else ""
        )
        done_ex = '{"action":"done","reason":"Karte ist vollständig"}'

        prompt = (
            f"Verbessere {'Wissensgraph' if is_graph else 'MindMap'}: {_clip(query, 100)}\n\n"
            f"Aktuelle Karte: {summary}\n"
            f"Belege: {len(snippets)} Snippets\n"
            f"Budget: ~{budget.est_calls()} Operationen\n\n"
            f"Wähle eine Aktion:\n"
            + ("\n".join(search_ex_lines) + "\n" if search_ex_lines else "")
            + (rebuild_ex + "\n" if rebuild_ex else "")
            + done_ex
            + "\n\nJSON:"
        )

        t1 = time.perf_counter()
        raw = str(llm(prompt=prompt) or "")
        budget.record(time.perf_counter() - t1)
        plan = _jparse(raw)
        action = str(plan.get("action", "") or "").strip().casefold()
        if not action:
            direct_spec = extract_graph_spec(raw)
            if direct_spec is not None:
                old_spec = extract_graph_spec(markdown)
                if old_spec is not None:
                    merged = _merge_mindmap_specs(
                        old_spec,
                        direct_spec,
                        max_nodes=max(
                            int(working_max_nodes),
                            int(max_nodes) * 2,
                        ),
                    )
                    merged = _ensure_connected(merged)
                    markdown = spec_to_markdown(merged)
                else:
                    markdown = str(raw or "").strip()
                after_spec = extract_graph_spec(markdown)
                new_n = len(after_spec.nodes) if after_spec else 0
                traces.append(
                    StepTrace(
                        f"refine_{rnd}",
                        "ok",
                        (time.perf_counter() - t1) * 1000,
                        output={
                            "action": "direct_map_merge",
                            "nodes_before": n,
                            "nodes_after": new_n,
                        },
                    )
                )
                continue

        # ── done ────────────────────────────────────────────────────────────
        if action == "done":
            traces.append(StepTrace(
                f"refine_{rnd}", "done",
                (time.perf_counter() - t1) * 1000,
                output={"n_nodes": n},
            ))
            break

        # ── search ──────────────────────────────────────────────────────────
        if action == "search" and avail_search:
            tname = str(plan.get("tool", "") or avail_search[0])
            if tname == "rag_search":
                tname = "rag.search"
            if tname not in avail_search:
                tname = avail_search[0]
            if tname == "regex_search" and int(max_regex_calls or 0) > 0:
                regex_used = 0
                for row in traces:
                    sid = str(getattr(row, "step_id", "") or "")
                    if not sid.startswith("refine_"):
                        continue
                    out = dict(getattr(row, "output", {}) or {})
                    if str(out.get("tool", "") or "") == "regex_search":
                        regex_used += 1
                if regex_used >= int(max_regex_calls):
                    traces.append(
                        StepTrace(
                            f"refine_{rnd}",
                            "skipped",
                            (time.perf_counter() - t1) * 1000,
                            output={
                                "action": "search",
                                "tool": tname,
                                "reason": "regex_limit_reached",
                                "regex_calls": regex_used,
                            },
                        )
                    )
                    continue
            fn = _get(tools, tname) or _get(tools, tname.replace(".", "_"))
            args = plan.get("args", {})
            args = dict(args) if isinstance(args, dict) else {}
            new_hits = 0
            raw_hits = 0
            if callable(fn):
                try:
                    res = fn(**args) if args else fn()
                    hits = list(res or []) if isinstance(res, (list, tuple)) else [str(res or "")]
                    hits = [str(h).strip() for h in hits if str(h or "").strip()]
                    raw_hits = len(hits)
                    new_hits = _ingest(hits, snippets, seen_snippets)
                except Exception:
                    pass
            traces.append(StepTrace(
                f"refine_{rnd}", "ok",
                (time.perf_counter() - t1) * 1000,
                output={"action": "search", "tool": tname,
                        "raw_hits": raw_hits, "new_hits": new_hits, "total_snippets": len(snippets)},
            ))
            continue

        # ── rebuild / improve ────────────────────────────────────────────────
        if action in ("rebuild", "update", "improve") and callable(llm_map):
            if not budget.can_llm(safety=0.9):
                break
            focus = str(plan.get("focus", query) or query)
            missing_topics = [
                str(x).strip()
                for x in list(plan.get("missing_topics", []) or [])
                if str(x).strip()
            ]
            if missing_topics:
                focus = f"{focus} | Fehlende Aspekte: {', '.join(missing_topics[:6])}"
            ctx = _enriched_context(
                snippets,
                context,
                max_c=max(8_000, int(context_max_chars)),
            )
            t2 = time.perf_counter()
            new_md = _call_map(llm_map, focus, ctx, int(working_max_nodes), is_graph)
            budget.record(time.perf_counter() - t2)

            if new_md:
                old_spec = extract_graph_spec(markdown)
                new_spec = extract_graph_spec(new_md)
                if old_spec and new_spec:
                    merged = _merge_mindmap_specs(
                        old_spec,
                        new_spec,
                        max_nodes=max(
                            int(working_max_nodes),
                            int(max_nodes) * 2,
                        ),
                    )
                    merged = _ensure_connected(merged)
                    markdown = spec_to_markdown(merged)
                elif new_spec:
                    markdown = new_md

            after_spec = extract_graph_spec(markdown)
            new_n = len(after_spec.nodes) if after_spec else 0
            traces.append(StepTrace(
                f"refine_{rnd}", "ok",
                (time.perf_counter() - t2) * 1000,
                output={"action": "rebuild", "focus": _clip(focus, 160),
                        "nodes_before": n, "nodes_after": new_n},
            ))
            continue

        # ── unbekannte Aktion → abbrechen ────────────────────────────────────
        traces.append(StepTrace(
            f"refine_{rnd}", "skipped",
            (time.perf_counter() - t1) * 1000,
            output={"action": action or "?", "raw_preview": _clip(raw, 120)},
        ))
        break

    return markdown


# ── Haupt-Pipeline ────────────────────────────────────────────────────────────

def run_mindmap_pipeline(
    *,
    request: dict[str, Any],
    tools: dict[str, Any],
    mode: str,
    workflow_id: str,
    profile_id: str,
) -> WorkflowRunResult:
    """
    Vollständige MindMap/Graph-Pipeline.

    Wichtige request-Keys
    ─────────────────────
    query, context_text, max_nodes
    budget_seconds          – bevorzugtes Budget in Sekunden
    agent_budget_points     – Fallback (1 Punkt ≈ 3 Sekunden)
    retrieval_strategy      – "agent" | "rag" | "none"
    allow_rag_search, allow_regex_search,
    allow_heading_search, allow_full_text_search
    """
    # Lokaler Import, um Zirkularität beim Modulstart zu vermeiden
    from shared.services.agentic.service import (  # noqa: PLC0415
        _extract_explicit_main_nodes,
        _grounding_issues_for_markdown,
        _missing_required_main_nodes,
        _normalize_and_validate_map_markdown,
    )

    t0 = time.perf_counter()
    traces: list[StepTrace] = []

    llm = _get(tools, "llm.generate")
    llm_map = _get(tools, "llm.generate_mindmap")

    tuning = _PipelineTuning.from_request(dict(request or {}))

    query = str(request.get("query", "") or "").strip()
    context = str(request.get("context_text", "") or "")
    max_nodes = _as_int(request.get("max_nodes"), default=32, min_value=4, max_value=4096)
    is_graph = str(mode or "") == "graph"

    # Budget: budget_seconds bevorzugt; agent_budget_points als Fallback.
    raw_bs = request.get("budget_seconds")
    if raw_bs is not None:
        budget_s = _as_float(raw_bs, default=45.0, min_value=5.0, max_value=7200.0)
    else:
        pts = _as_float(request.get("agent_budget_points"), default=18.0, min_value=0.1, max_value=20_000.0)
        budget_s = _as_float(pts * 3.0, default=45.0, min_value=5.0, max_value=7200.0)

    budget = _Budget(max_seconds=budget_s)

    strategy_requested = str(request.get("retrieval_strategy", "agent") or "agent").casefold().strip()
    if strategy_requested not in {"agent", "rag", "none"}:
        strategy_requested = "agent"
    strategy = strategy_requested
    if bool(tuning.force_agent_retrieval) and strategy != "agent":
        strategy = "agent"
        traces.append(
            StepTrace(
                step_id="retrieval_strategy_override",
                status="ok",
                duration_ms=0.0,
                output={
                    "requested": strategy_requested,
                    "effective": strategy,
                    "reason": "force_agent_retrieval",
                },
            )
        )

    allow_rag = bool(request.get("allow_rag_search", True))
    allow_regex = bool(request.get("allow_regex_search", True))
    allow_heading = bool(request.get("allow_heading_search", True))
    allow_full_text = bool(request.get("allow_full_text_search", True))
    use_full_context = bool(request.get("use_full_context", False))
    context_max_chars = _as_int(
        request.get("context_max_chars"),
        default=int(tuning.max_enriched_context_chars),
        min_value=4_000,
        max_value=2_000_000,
    )
    max_regex_calls = _as_int(request.get("agent_max_regex_calls"), default=0, min_value=0, max_value=10_000)
    max_consecutive_nohit = _as_int(
        request.get("agent_max_consecutive_nohit"),
        default=5,
        min_value=1,
        max_value=1_000,
    )
    max_consecutive_stale = _as_int(
        request.get("agent_max_consecutive_stale"),
        default=0,
        min_value=0,
        max_value=1_000,
    )
    max_iterations = _as_int(request.get("agent_max_iterations"), default=0, min_value=0, max_value=200_000)

    working_max_nodes = _as_int(
        max(
            max_nodes,
            max_nodes * int(tuning.working_nodes_multiplier),
            int(tuning.working_nodes_floor),
        ),
        default=max_nodes,
        min_value=max_nodes,
        max_value=int(tuning.max_working_nodes),
    )
    generation_context_chars = int(context_max_chars) if (strategy == "none" or use_full_context) else int(tuning.max_enriched_context_chars)

    query_origin = "user"
    # Query aus Kontext ableiten wenn leer
    if not query:
        for line in context.splitlines():
            m = re.match(r"^\s*#{1,3}\s+(.+)", line)
            if m:
                query = f"Übersicht: {m.group(1).strip()}"
                query_origin = "auto_overview"
                break
        if not query:
            query = "Übersicht der wichtigsten Inhalte"
            query_origin = "auto_overview"

    # ── Schritt 1: Konzepte ───────────────────────────────────────────────────
    concepts, search_queries = _step_concepts(
        llm,
        query,
        context[: max(300, int(tuning.concept_context_chars))],
        budget,
        traces,
        tuning=tuning,
    )

    # ── Schritt 2: Informationssammlung ──────────────────────────────────────
    snippets: list[str] = []
    draft_hint_markdown = ""
    if strategy != "none":
        snippets, draft_hint_markdown = _step_gather(
            tools=tools,
            llm=llm,
            query=query,
            concepts=concepts,
            queries=search_queries,
            context=context,
            strategy=strategy,
            allow_rag=allow_rag,
            allow_regex=allow_regex,
            allow_heading=allow_heading,
            allow_full_text=allow_full_text,
            max_regex_calls=max_regex_calls,
            max_consecutive_nohit=max_consecutive_nohit,
            max_consecutive_stale=max_consecutive_stale,
            max_iterations=max_iterations,
            is_graph=is_graph,
            budget=budget,
            traces=traces,
            tuning=tuning,
        )

    # ── Schritt 3: Basiskarte ─────────────────────────────────────────────────
    markdown = _step_base_map(
        llm_map=llm_map,
        query=query,
        snippets=snippets,
        context=context,
        working_max_nodes=working_max_nodes,
        context_max_chars=generation_context_chars,
        is_graph=is_graph,
        budget=budget,
        traces=traces,
        tuning=tuning,
    )
    if extract_graph_spec(markdown) is None and str(draft_hint_markdown or "").strip():
        markdown = str(draft_hint_markdown or "").strip()
        traces.append(
            StepTrace(
                step_id="base_map_fallback_from_gather_hint",
                status="ok",
                duration_ms=0.0,
                output={"reason": "base_map_invalid_or_empty"},
            )
        )
    base_spec = extract_graph_spec(markdown)
    base_nodes = len(base_spec.nodes) if base_spec else 0

    # ── Schritt 4: Iterative Verbesserung (Budget-abhängig) ───────────────────
    if markdown and budget.can_llm(safety=float(tuning.final_refine_safety)):
        markdown = _step_refine(
            llm=llm,
            llm_map=llm_map,
            tools=tools,
            query=query,
            markdown=markdown,
            snippets=snippets,
            context=context,
            max_nodes=max_nodes,
            working_max_nodes=working_max_nodes,
            context_max_chars=generation_context_chars,
            is_graph=is_graph,
            allow_rag=allow_rag,
            allow_regex=allow_regex,
            allow_heading=allow_heading,
            allow_full_text=allow_full_text,
            max_regex_calls=max_regex_calls,
            budget=budget,
            traces=traces,
            tuning=tuning,
        )

    refined_spec = extract_graph_spec(markdown)
    refined_nodes = len(refined_spec.nodes) if refined_spec else 0

    grounding_source_markdown = str(markdown or "")
    # ── Schritt 5: Finalisierung ──────────────────────────────────────────────
    if markdown:
        spec = extract_graph_spec(markdown)
        if spec:
            spec = _ensure_connected(spec)
            spec = _add_leaf_citations(
                spec,
                snippets,
                context_text=context,
                quote_max_chars=int(tuning.quote_max_chars),
            )
            markdown = spec_to_markdown(spec)

    raw_draft_markdown = str(markdown or "")
    log_draft_markdown = bool(request.get("log_draft_markdown", False))
    pre_validation_spec = extract_graph_spec(markdown)
    pre_validation_nodes = len(pre_validation_spec.nodes) if pre_validation_spec else 0

    # Validierung und Normalisierung via bestehender Funktion
    normalized, validation, errors = _normalize_and_validate_map_markdown(
        markdown=markdown,
        mode=mode,
        max_nodes=max_nodes,
    )

    trimmed_nodes = 0
    if (not normalized or errors) and pre_validation_spec is not None and len(pre_validation_spec.nodes) > max_nodes:
        trimmed_spec = _trim_spec_to_max_nodes(pre_validation_spec, max_nodes=max_nodes)
        trimmed_nodes = len(trimmed_spec.nodes)
        trimmed_markdown = spec_to_markdown(trimmed_spec)
        n2, v2, e2 = _normalize_and_validate_map_markdown(
            markdown=trimmed_markdown,
            mode=mode,
            max_nodes=max_nodes,
        )
        traces.append(
            StepTrace(
                step_id="structure_trim_to_max_nodes",
                status="ok" if n2 and not e2 else "skipped",
                duration_ms=0.0,
                output={
                    "before_nodes": len(pre_validation_spec.nodes),
                    "after_nodes": len(trimmed_spec.nodes),
                    "max_nodes": max_nodes,
                },
            )
        )
        if n2 and not e2:
            normalized, validation, errors = n2, v2, e2

    required_main_nodes = _extract_explicit_main_nodes(query, max_items=10) if not is_graph else []
    missing_required_nodes: list[str] = []
    grounding_issues: list[str] = []
    grounding_snapshot: dict[str, Any] = {}
    if normalized:
        evidence_context = (
            str(context or "")
            if (strategy == "none" or use_full_context)
            else _enriched_context(
                list(snippets or []),
                str(context or ""),
                max_c=max(8_000, int(generation_context_chars)),
            )
        )
        grounding_issues, grounding_snapshot = _grounding_issues_for_markdown(
            markdown=grounding_source_markdown or normalized,
            context_text=evidence_context,
            anchor_terms=[str(x or "") for x in list(concepts or [])[:8]],
        )
        if required_main_nodes:
            missing_required_nodes = _missing_required_main_nodes(normalized, required_main_nodes)
            strict_missing = _strict_missing_required_main_nodes(normalized, required_main_nodes)
            if strict_missing:
                missing_required_nodes = strict_missing

    if normalized and missing_required_nodes and callable(llm):
        strict_prompt = (
            "Repariere die MindMap strikt nach den Pflicht-Hauptknoten.\n"
            "Gib NUR einen ```mindmap Codeblock aus.\n"
            f"Pflicht-Hauptknoten: {', '.join(required_main_nodes[:10])}\n"
            f"Fehlend aktuell: {', '.join(missing_required_nodes[:10])}\n"
            f"Anfrage: {query}\n\n"
            f"Kontext:\n{_clip(context, 9000)}\n\n"
            f"Aktuelle MindMap:\n{_clip(normalized, 5000)}\n"
        )
        t_repair = time.perf_counter()
        repaired = str(llm(prompt=strict_prompt) or "").strip()
        budget.record(time.perf_counter() - t_repair)
        cand_norm, cand_val, cand_err = _normalize_and_validate_map_markdown(
            markdown=repaired,
            mode=mode,
            max_nodes=max_nodes,
        )
        cand_missing = _missing_required_main_nodes(cand_norm, required_main_nodes) if cand_norm else list(required_main_nodes)
        if cand_norm:
            strict_cand_missing = _strict_missing_required_main_nodes(cand_norm, required_main_nodes)
            if strict_cand_missing:
                cand_missing = strict_cand_missing
        cand_grounding, cand_grounding_snapshot = _grounding_issues_for_markdown(
            markdown=cand_norm or repaired,
            context_text=evidence_context,
            anchor_terms=[str(x or "") for x in list(concepts or [])[:8]],
        ) if (cand_norm or repaired) else ([], {})
        grounding_tolerated = max(int(len(grounding_issues or [])), 1) + 1
        accepted = bool(cand_norm) and not cand_err and not cand_missing and len(cand_grounding) <= grounding_tolerated
        traces.append(
            StepTrace(
                step_id="required_nodes_repair",
                status="ok" if accepted else "skipped",
                duration_ms=(time.perf_counter() - t_repair) * 1000.0,
                output={
                    "required_nodes": len(required_main_nodes),
                    "missing_before": len(missing_required_nodes),
                    "missing_after": len(cand_missing),
                    "grounding_before": len(grounding_issues),
                    "grounding_after": len(cand_grounding),
                    "grounding_tolerated": int(grounding_tolerated),
                },
            )
        )
        if accepted:
            normalized, validation, errors = cand_norm, cand_val, []
            missing_required_nodes = []
            grounding_issues = list(cand_grounding or [])
            grounding_snapshot = dict(cand_grounding_snapshot or {})

    if normalized and not errors and grounding_issues:
        errors = [
            f"Erdung: {str(msg or '').strip()}"
            for msg in list(grounding_issues or [])[:8]
            if str(msg or "").strip()
        ]
        if not errors:
            errors = ["Erdung: Keine ausreichende inhaltliche Verankerung im Kontext."]
        normalized = ""

    traces.append(
        StepTrace(
            step_id="draft_generation",
            status="ok" if pre_validation_nodes > 0 else "empty",
            duration_ms=0.0,
            output={
                "base_nodes": int(base_nodes),
                "refined_nodes": int(refined_nodes),
                "pre_validation_nodes": int(pre_validation_nodes),
            },
        )
    )
    if int(base_nodes) <= 0 and int(pre_validation_nodes) > 0:
        traces.append(
            StepTrace(
                step_id="draft_repair",
                status="ok",
                duration_ms=0.0,
                output={"reason": "base_invalid_but_recovered"},
            )
        )

    traces.append(
        StepTrace(
            step_id="structure_validation",
            status="ok" if bool(normalized) and not errors else "error",
            duration_ms=0.0,
            output={
                "node_count": int(dict(validation.get("structure_check", {})).get("node_count", 0) or 0),
                "errors": list(errors[:12] if errors else []),
            },
        )
    )

    final_spec = extract_graph_spec(normalized) if normalized else None
    node_count = len(final_spec.nodes) if final_spec else int(
        dict(validation.get("structure_check", {})).get("node_count", 0) or 0
    )
    elapsed_ms = (time.perf_counter() - t0) * 1000
    bsummary = budget.summary()

    # Schritte aus dem Gathering-Trace extrahieren (für Abwärtskompatibilität)
    gather_trace = next((t for t in traces if t.step_id == "information_gathering"), None)
    retrieval_steps: list[dict] = list(
        dict(gather_trace.output or {}).get("steps", []) if gather_trace else []
    )
    gather_output = dict(gather_trace.output or {}) if gather_trace else {}

    # Tool-Call-Zähler für Abwärtskompatibilität
    tool_calls: dict[str, int] = {}
    for step in retrieval_steps:
        tname = str(step.get("tool", "") or "")
        if tname:
            tool_calls[tname] = tool_calls.get(tname, 0) + 1

    draft_progress: list[dict[str, Any]] = []
    for tr in traces:
        sid = str(getattr(tr, "step_id", "") or "")
        out = dict(getattr(tr, "output", {}) or {})
        if sid == "base_map":
            draft_progress.append(
                {
                    "round": 0,
                    "phase": "base",
                    "node_count": int(out.get("node_count", 0) or 0),
                    "ctx_chars": int(out.get("ctx_chars", 0) or 0),
                    "working_max_nodes": int(out.get("working_max_nodes", 0) or 0),
                }
            )
        elif sid.startswith("refine_") and out:
            row = {"round": int(len(draft_progress)), "phase": "refine"}
            row.update(out)
            draft_progress.append(row)

    node_lifecycle = {
        "base_nodes": int(base_nodes),
        "after_refine_nodes": int(refined_nodes),
        "pre_validation_nodes": int(pre_validation_nodes),
        "trimmed_nodes": int(trimmed_nodes),
        "final_nodes": int(node_count),
        "node_delta_base_to_final": int(node_count - base_nodes),
    }

    state_out: dict[str, Any] = {
        "query": query,
        "effective_query": query,
        "query_origin": query_origin,
        "mode": mode,
        "node_count": node_count,
        "snippets": len(snippets),
        "concepts": concepts,
        "retrieval_strategy": strategy,
        "retrieval_strategy_requested": strategy_requested,
        "retrieval_strategy_effective": strategy,
        "agent_max_iterations": int(max_iterations),
        "agent_max_consecutive_nohit": int(max_consecutive_nohit),
        "agent_max_consecutive_stale": int(max_consecutive_stale),
        "budget": bsummary,
        "structure_validation": validation,
        "structure_check": validation.get("structure_check", {}),
        "root_label": validation.get("root_label", ""),
        "primary_children": validation.get("primary_children", []),
        "grounding_issues": list(grounding_issues[:12]),
        "grounding_snapshot": dict(grounding_snapshot or {}),
        "required_main_nodes": list(required_main_nodes[:10]),
        "missing_required_main_nodes": list(missing_required_nodes[:10]),
        "node_lifecycle": node_lifecycle,
        "draft_progress": draft_progress,
        "draft_markdown_logged": bool(log_draft_markdown),
        # Abwärtskompatibel mit Tests und altem Code
        "retrieval_agent_steps": retrieval_steps,
        "rag_snippets": snippets,
    }
    if log_draft_markdown and raw_draft_markdown.strip():
        state_out["draft_markdown_raw"] = raw_draft_markdown

    return WorkflowRunResult(
        ok=bool(normalized) and not errors,
        workflow_id=workflow_id,
        profile_id=profile_id,
        result={"markdown": normalized},
        state=state_out,
        trace=traces,
        errors=errors[:12] if errors else [],
        metrics={
            "node_count": node_count,
            "node_lifecycle": node_lifecycle,
            "snippets_gathered": len(snippets),
            "retrieval_strategy": strategy,
            "retrieval_strategy_requested": strategy_requested,
            "query_origin": query_origin,
            "draft_generation_strategy": "agent_iterative_time_budget",
            "retrieval_steps": len(retrieval_steps),
            "retrieval_iterations": int(gather_output.get("iterations", len(retrieval_steps)) or len(retrieval_steps)),
            "retrieval_steps_dropped": int(gather_output.get("steps_dropped", 0) or 0),
            "regex_calls": int(gather_output.get("regex_calls", 0) or 0),
            "agent_max_iterations": int(max_iterations),
            "agent_max_consecutive_nohit": int(max_consecutive_nohit),
            "agent_max_consecutive_stale": int(max_consecutive_stale),
            "grounding_issues": len(list(grounding_issues or [])),
            "grounding_issue_count": len(list(grounding_issues or [])),
            "required_main_nodes": list(required_main_nodes[:10]),
            "missing_required_main_nodes": list(missing_required_nodes[:10]),
            "required_main_nodes_count": len(list(required_main_nodes or [])),
            "missing_required_main_nodes_count": len(list(missing_required_nodes or [])),
            "tool_calls": tool_calls,
            **bsummary,
            "elapsed_ms": round(elapsed_ms, 1),
        },
    )
