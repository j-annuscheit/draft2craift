"""Chunk-based mindmap helpers for ``LLMManager``."""
from __future__ import annotations

import re
from typing import Any

from shared.domain.graph_codec import spec_to_markdown
from shared.domain.graph_spec import GraphEdge, GraphNode, GraphSpec
from shared.services.rag.config import RAGConfig
from shared.services.rag.orchestrator import RAGSystem

_COLLAPSE_WS_RE = re.compile(r"\s+")
_SLUG_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def _collapse_ws(value: object) -> str:
    return _COLLAPSE_WS_RE.sub(" ", str(value or "")).strip()


def _collapse_ws(value: object) -> str:
    return _COLLAPSE_WS_RE.sub(" ", str(value or "")).strip()


def _normalize_mindmap_mode(mode: str) -> str:
    value = str(mode or "").strip().casefold()
    if ("chunk" in value) or ("abschnitt" in value) or ("section" in value):
        return "chunkmap"
    if "graph" in value or "wissens" in value:
        return "graph"
    return "mindmap"

def _slug_node_id(text: str, fallback: str) -> str:
    raw = _SLUG_NON_ALNUM_RE.sub("-", str(text or "").strip().casefold()).strip("-")
    return raw or fallback

def _chunk_leaf_label(index: int, chunk_text: str) -> str:
    lead = _collapse_ws(chunk_text)
    if not lead:
        return f"Chunk {index:02d}"
    return f"Chunk {index:02d}: {lead}"

def _generate_chunk_mindmap_sync(
    self,
    *,
    context_text: str,
    query: str,
    max_nodes: int,
    chunking_strategy: str,
    chunk_size: int,
    chunk_overlap: int,
) -> tuple[str, dict[str, Any]]:
    strategy = str(chunking_strategy or "").strip().casefold()
    if strategy not in {"sliding_window", "section", "recursive"}:
        strategy = "sliding_window"

    size = max(220, min(4200, int(chunk_size or 900)))
    overlap = max(0, min(size - 20, int(chunk_overlap or 160)))
    # chunkmap: max_nodes <= 0 means "no hard leaf limit".
    try:
        requested_limit = int(max_nodes)
    except Exception:
        requested_limit = 0
    leaf_limit = requested_limit if requested_limit > 0 else 0

    cfg = RAGConfig.from_dict(
        {
            "backend": {
                "use_tfidf": False,
                "use_st": False,
                "use_regex_search": False,
            },
            "hyde": {
                "use_hyde": False,
            },
            "chunking": {
                "chunk_size": size,
                "chunk_overlap": overlap,
                "strategy": strategy,
                "include_headings": True,
                "include_filename": False,
            },
        }
    )

    try:
        chunker = RAGSystem(config=cfg)
        chunk_rows = chunker._build_chunks(context_text, doc_name="Kontext")  # pylint: disable=protected-access
    except Exception as exc:
        if self._log:
            self._log.error("LLM", f"Chunk-MindMap chunking failed: {exc}")
        return "", {
            "applied": False,
            "reason": "chunking_exception",
            "error": str(exc),
        }

    if not chunk_rows:
        return "", {
            "applied": False,
            "reason": "no_chunks",
        }

    question = str(query or "").strip()
    title = "Chunk-MindMap"
    if question:
        title = f"Chunk-MindMap: {question[:96]}"

    root_label = question[:120] if question else "Kontext"
    root_id = "root"
    nodes: dict[str, GraphNode] = {
        root_id: GraphNode(node_id=root_id, label=root_label or "Kontext")
    }
    roots = [root_id]
    edges: list[GraphEdge] = []
    edge_seen: set[tuple[str, str]] = set()
    used_ids: set[str] = {root_id}
    path_to_node: dict[tuple[str, ...], str] = {(): root_id}

    def alloc_node_id(prefix: str, seed: str) -> str:
        base = self._slug_node_id(seed, prefix)
        candidate = f"{prefix}-{base}"
        candidate = candidate.strip("-")
        if not candidate:
            candidate = prefix
        if candidate not in used_ids:
            used_ids.add(candidate)
            return candidate
        idx = 2
        while True:
            probe = f"{candidate}-{idx}"
            if probe not in used_ids:
                used_ids.add(probe)
                return probe
            idx += 1

    def connect(parent_id: str, child_id: str):
        parent = nodes.get(parent_id)
        if parent is not None and child_id not in parent.children:
            parent.children.append(child_id)
        key = (parent_id, child_id)
        if key in edge_seen:
            return
        edge_seen.add(key)
        edges.append(GraphEdge(source_id=parent_id, target_id=child_id, label=""))

    chunk_count = 0
    total_chunks = 0
    truncated = False

    for row in chunk_rows:
        chunk_text = str(row.get("raw_text", "") or "").strip()
        if not chunk_text:
            continue
        total_chunks += 1
        if leaf_limit > 0 and chunk_count >= leaf_limit:
            truncated = True
            continue

        breadcrumb_raw = row.get("breadcrumb", [])
        breadcrumb: list[str] = []
        if isinstance(breadcrumb_raw, list):
            for item in breadcrumb_raw:
                token = _collapse_ws(item)
                if token:
                    breadcrumb.append(token)
        if not breadcrumb:
            breadcrumb = ["Ohne Ueberschrift"]

        parent_id = root_id
        path_parts: list[str] = []
        for heading in breadcrumb:
            path_parts.append(heading)
            path_key = tuple(path_parts)
            heading_node_id = path_to_node.get(path_key, "")
            if not heading_node_id:
                heading_node_id = alloc_node_id("h", " / ".join(path_parts))
                nodes[heading_node_id] = GraphNode(
                    node_id=heading_node_id,
                    label=heading,
                )
                path_to_node[path_key] = heading_node_id
                connect(parent_id, heading_node_id)
            parent_id = heading_node_id

        chunk_count += 1
        leaf_id = alloc_node_id("chunk", str(chunk_count))
        nodes[leaf_id] = GraphNode(
            node_id=leaf_id,
            label=self._chunk_leaf_label(chunk_count, chunk_text),
            quote=chunk_text,
        )
        connect(parent_id, leaf_id)

    if chunk_count <= 0:
        return "", {
            "applied": False,
            "reason": "no_nonempty_chunks",
        }

    spec = GraphSpec(
        kind="mindmap",
        title=title,
        nodes=nodes,
        roots=roots,
        edges=edges,
    )
    markdown = spec_to_markdown(spec)
    if self._log:
        self._log.info(
            "LLM",
            "Chunk-MindMap erstellt"
            f"  |  chunks={chunk_count}/{total_chunks}"
            f"  |  strategy={strategy}"
            f"  |  chunk_size={size}"
            f"  |  overlap={overlap}",
        )
    return markdown, {
        "applied": True,
        "reason": "ok",
        "kind": "mindmap",
        "variant": "chunkmap",
        "nodes": len(nodes),
        "edges": len(edges),
        "chunks": chunk_count,
        "chunks_total": total_chunks,
        "chunking_strategy": strategy,
        "chunk_size": size,
        "chunk_overlap": overlap,
        "truncated": truncated,
    }
