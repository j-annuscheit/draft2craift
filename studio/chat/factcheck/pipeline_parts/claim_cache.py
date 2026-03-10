"""FactCheckPipelineMixin method implementations."""
from __future__ import annotations

from .deps import *  # noqa: F403

@classmethod
def _empty_chunk_claim_cache(cls) -> dict[str, object]:
    return {
        "version": int(cls._CLAIM_CACHE_VERSION),
        "chunk_size": int(cls._CLAIM_CHUNK_SIZE),
        "chunk_overlap": int(cls._CLAIM_CHUNK_OVERLAP),
        "docs": {},
    }

@classmethod
def _sanitize_chunk_claim_cache_payload(
    cls,
    raw_payload: object,
) -> dict[str, object]:
    payload = raw_payload if isinstance(raw_payload, dict) else {}
    docs_in = payload.get("docs", {})
    docs_out: dict[str, object] = {}
    if isinstance(docs_in, dict):
        for source_hash, raw_doc in docs_in.items():
            key = str(source_hash or "").strip()
            if not key or not isinstance(raw_doc, dict):
                continue
            chunks_in = raw_doc.get("chunks", {})
            chunks_out: dict[str, object] = {}
            if isinstance(chunks_in, dict):
                for chunk_hash, raw_chunk in chunks_in.items():
                    ckey = str(chunk_hash or "").strip()
                    if not ckey or not isinstance(raw_chunk, dict):
                        continue
                    claims = raw_chunk.get("claims", [])
                    claim_list: list[str] = []
                    if isinstance(claims, list):
                        for item in claims:
                            claim = cls._collapse_ws(item)
                            if claim:
                                claim_list.append(claim)
                    chunks_out[ckey] = {
                        "chunk_index": int(raw_chunk.get("chunk_index", 0) or 0),
                        "chunk_text": str(raw_chunk.get("chunk_text", "") or ""),
                        "claims": claim_list,
                        "updated_at": str(raw_chunk.get("updated_at", "") or ""),
                    }
            docs_out[key] = {
                "source_name": str(raw_doc.get("source_name", "") or ""),
                "source_hash": key,
                "chunk_size": int(raw_doc.get("chunk_size", cls._CLAIM_CHUNK_SIZE) or cls._CLAIM_CHUNK_SIZE),
                "chunk_overlap": int(raw_doc.get("chunk_overlap", cls._CLAIM_CHUNK_OVERLAP) or cls._CLAIM_CHUNK_OVERLAP),
                "chunks": chunks_out,
            }
    return {
        "version": int(payload.get("version", cls._CLAIM_CACHE_VERSION) or cls._CLAIM_CACHE_VERSION),
        "chunk_size": int(payload.get("chunk_size", cls._CLAIM_CHUNK_SIZE) or cls._CLAIM_CHUNK_SIZE),
        "chunk_overlap": int(payload.get("chunk_overlap", cls._CLAIM_CHUNK_OVERLAP) or cls._CLAIM_CHUNK_OVERLAP),
        "docs": docs_out,
    }

def _ensure_chunk_claim_cache(self) -> dict[str, object]:
    cache = getattr(self, "_chunk_claim_cache", None)
    if not isinstance(cache, dict):
        cache = self._empty_chunk_claim_cache()
        setattr(self, "_chunk_claim_cache", cache)
        return cache

    normalized = self._sanitize_chunk_claim_cache_payload(cache)
    setattr(self, "_chunk_claim_cache", normalized)
    return normalized

def export_chunk_claim_cache(self) -> dict[str, object]:
    cache = self._ensure_chunk_claim_cache()
    try:
        return json.loads(json.dumps(cache, ensure_ascii=False))
    except Exception:
        return self._empty_chunk_claim_cache()

def import_chunk_claim_cache(self, payload: object):
    normalized = self._sanitize_chunk_claim_cache_payload(payload)
    setattr(self, "_chunk_claim_cache", normalized)

@staticmethod
def _hash_text(text: str) -> str:
    return hashlib.sha1(str(text or "").encode("utf-8", errors="ignore")).hexdigest()

def _build_source_chunk_entries(
    self,
    sources: list[tuple[str, str]],
) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    chunk_size = int(self._CLAIM_CHUNK_SIZE)
    chunk_overlap = int(self._CLAIM_CHUNK_OVERLAP)
    for source_name, source_text in list(sources or []):
        clean_source = str(source_name or "").strip()
        clean_text = str(source_text or "")
        if not clean_source or not clean_text.strip():
            continue
        source_hash = self._hash_text(clean_text)
        chunk_list = chunk_source_text(
            clean_text,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
        for chunk_index, chunk in enumerate(chunk_list):
            chunk_text = str(chunk or "").strip()
            if not chunk_text:
                continue
            out.append(
                {
                    "source": clean_source,
                    "source_hash": source_hash,
                    "chunk_index": int(chunk_index),
                    "chunk_text": chunk_text,
                    "chunk_hash": self._hash_text(chunk_text),
                }
            )
    return out

def _get_cached_chunk_claims(self, entry: dict[str, object]) -> list[str]:
    cache = self._ensure_chunk_claim_cache()
    docs = cache.get("docs", {})
    if not isinstance(docs, dict):
        return []
    source_hash = str(entry.get("source_hash", "") or "").strip()
    chunk_hash = str(entry.get("chunk_hash", "") or "").strip()
    if not source_hash or not chunk_hash:
        return []
    doc = docs.get(source_hash, {})
    if not isinstance(doc, dict):
        return []
    chunks = doc.get("chunks", {})
    if not isinstance(chunks, dict):
        return []
    item = chunks.get(chunk_hash, {})
    if not isinstance(item, dict):
        return []
    claims = item.get("claims", [])
    if not isinstance(claims, list):
        return []
    out: list[str] = []
    for claim in claims:
        text = self._collapse_ws(claim)
        if text:
            out.append(text)
    return out

def _store_cached_chunk_claims(
    self,
    entry: dict[str, object],
    claims: list[str],
):
    cache = self._ensure_chunk_claim_cache()
    docs = cache.setdefault("docs", {})
    if not isinstance(docs, dict):
        docs = {}
        cache["docs"] = docs

    source_hash = str(entry.get("source_hash", "") or "").strip()
    chunk_hash = str(entry.get("chunk_hash", "") or "").strip()
    if not source_hash or not chunk_hash:
        return

    doc = docs.get(source_hash)
    if not isinstance(doc, dict):
        doc = {
            "source_name": str(entry.get("source", "") or ""),
            "source_hash": source_hash,
            "chunk_size": int(self._CLAIM_CHUNK_SIZE),
            "chunk_overlap": int(self._CLAIM_CHUNK_OVERLAP),
            "chunks": {},
        }
        docs[source_hash] = doc

    chunks = doc.get("chunks", {})
    if not isinstance(chunks, dict):
        chunks = {}
        doc["chunks"] = chunks

    claim_list: list[str] = []
    seen: set[str] = set()
    for claim in list(claims or []):
        text = self._collapse_ws(claim)
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        claim_list.append(text)

    chunks[chunk_hash] = {
        "chunk_index": int(entry.get("chunk_index", 0) or 0),
        "chunk_text": str(entry.get("chunk_text", "") or ""),
        "claims": claim_list,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    setattr(self, "_chunk_claim_cache", cache)

def _build_claim_nli_units(
    self,
    chunk_entries: list[dict[str, object]],
) -> list[dict[str, str]]:
    units: list[dict[str, str]] = []
    for entry in list(chunk_entries or []):
        source_name = str(entry.get("source", "") or "").strip()
        chunk_text = str(entry.get("chunk_text", "") or "").strip()
        if not source_name or not chunk_text:
            continue
        claims = self._get_cached_chunk_claims(entry)
        for claim in claims:
            units.append(
                {
                    "source": source_name,
                    "premise": claim,
                    "evidence": chunk_text,
                    "mode": "chunk_claim",
                }
            )
    return units

@staticmethod
def _build_source_contexts_from_context(ctx: dict) -> list[tuple[str, str]]:
    file_contents = list(ctx.get("file_contents", []) or [])
    rag_results = list(ctx.get("rag_results", []) or [])

    out: list[tuple[str, str]] = []
    for name, content in file_contents:
        clean_name = str(name or "").strip()
        clean_content = str(content or "").strip()
        if not clean_name or not clean_content:
            continue
        if clean_name.startswith("Draft:"):
            continue
        out.append((clean_name, clean_content))

    for path, _score, excerpt in rag_results:
        label = os.path.basename(str(path or "").strip())
        label = label or str(path or "").strip() or "RAG Results"
        text = str(excerpt or "").strip()
        if not text:
            continue
        out.append((label, text))
    return out

@classmethod
def _normalize_atomic_claims(cls, claims: list[str]) -> list[str]:
    """
    Enforce atomic claims post-processing.

    The LLM is prompted to emit atomic claims, but we still split obvious
    multi-claim bundles conservatively to keep one statement per row.
    """
    out: list[str] = []
    seen: set[str] = set()
    for raw_claim in list(claims or []):
        base = cls._collapse_ws(raw_claim)
        if not base:
            continue

        candidates = [base]
        split_parts = re.split(
            r"\s*;\s+|\s+(?:und|sowie|wobei|außerdem|zudem|hingegen)\s+",
            base,
            flags=re.IGNORECASE,
        )
        valid_parts = [
            cls._collapse_ws(part).strip(" ,;:-")
            for part in split_parts
            if len(re.findall(r"\w+", part, flags=re.UNICODE)) >= 5
        ]
        if len(valid_parts) >= 2:
            candidates = valid_parts

        for cand in candidates:
            text = cls._collapse_ws(cand)
            if len(text) < 6:
                continue
            key = text.casefold()
            if key in seen:
                continue
            seen.add(key)
            out.append(text)
    return out

def _parse_atomic_claims_from_response(
    self,
    response: str,
    source_text: str,
) -> list[str]:
    parsed = parse_fact_candidates(response, source_text)
    atomized = self._normalize_atomic_claims(parsed)
    return atomized

__all__ = [
    "_empty_chunk_claim_cache",
    "_sanitize_chunk_claim_cache_payload",
    "_ensure_chunk_claim_cache",
    "export_chunk_claim_cache",
    "import_chunk_claim_cache",
    "_hash_text",
    "_build_source_chunk_entries",
    "_get_cached_chunk_claims",
    "_store_cached_chunk_claims",
    "_build_claim_nli_units",
    "_build_source_contexts_from_context",
    "_normalize_atomic_claims",
    "_parse_atomic_claims_from_response",
]
