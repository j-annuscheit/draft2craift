"""Structured RAG configuration models."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class BackendConfig:
    """Compatibility options for older UI controls.

    V2 retrieval is executed via LlamaIndex + LanceDB regardless of these flags.
    """

    use_tfidf: bool = True
    lexical_mode: str = "tfidf"
    bm25_k1: float = 1.2
    bm25_b: float = 0.75
    use_st: bool = True
    use_regex_search: bool = True
    st_model_name: str = "paraphrase-multilingual-MiniLM-L12-v2"
    st_n_threads: int = 0


@dataclass(slots=True)
class ChunkingConfig:
    """Chunk generation strategy and text-prefix options."""

    chunk_size: int = 800
    chunk_overlap: int = 150
    strategy: str = "sliding_window"
    include_headings: bool = True
    include_filename: bool = True


@dataclass(slots=True)
class HyDEConfig:
    """Legacy query-expansion settings kept for project-file compatibility."""

    use_hyde: bool = True
    min_words: int = 5
    tfidf_mode: str = "keywords"
    st_mode: str = "passage"
    st_hypotheses: int = 3
    use_doc_context: bool = False


@dataclass(slots=True)
class ContextConfig:
    """Extended context extraction around chunk spans."""

    enabled: bool = False
    before_chars: int = 500
    after_chars: int = 500


@dataclass(slots=True)
class SelectionConfig:
    """Result selection policy."""

    mode: str = "top_k"
    top_k: int = 5
    score_threshold: float = 0.05


@dataclass(slots=True)
class LiteralConfig:
    """Literal/regex backend options."""

    max_results: int = 3
    use_llm_terms: bool = False
    max_llm_terms: int = 8


@dataclass(slots=True)
class RerankConfig:
    """LLM reranking options."""

    enabled: bool = False
    min_score: float = 0.45
    max_candidates: int = 10


@dataclass(slots=True)
class SectionRoutingConfig:
    """Heading/summary-aware section routing before final retrieval selection."""

    enabled: bool = True
    mode: str = "hybrid"
    top_k: int = 8
    min_score: float = 0.08
    strict_filter: bool = False
    score_boost: float = 0.15
    max_summary_chars: int = 900
    summary_sentences: int = 3
    expand_query: bool = True
    expand_query_max_sections: int = 2


_SECTION_CLASSES = {
    "backend": BackendConfig,
    "chunking": ChunkingConfig,
    "hyde": HyDEConfig,
    "context": ContextConfig,
    "selection": SelectionConfig,
    "literal": LiteralConfig,
    "rerank": RerankConfig,
    "routing": SectionRoutingConfig,
}

def _clone_section(section: Any) -> Any:
    return section.__class__(**asdict(section))


@dataclass(slots=True)
class RAGConfig:
    """Top-level RAG configuration composed of focused section configs."""

    backend: BackendConfig = field(default_factory=BackendConfig)
    chunking: ChunkingConfig = field(default_factory=ChunkingConfig)
    hyde: HyDEConfig = field(default_factory=HyDEConfig)
    context: ContextConfig = field(default_factory=ContextConfig)
    selection: SelectionConfig = field(default_factory=SelectionConfig)
    literal: LiteralConfig = field(default_factory=LiteralConfig)
    rerank: RerankConfig = field(default_factory=RerankConfig)
    routing: SectionRoutingConfig = field(default_factory=SectionRoutingConfig)

    def copy(self) -> "RAGConfig":
        return RAGConfig(
            backend=_clone_section(self.backend),
            chunking=_clone_section(self.chunking),
            hyde=_clone_section(self.hyde),
            context=_clone_section(self.context),
            selection=_clone_section(self.selection),
            literal=_clone_section(self.literal),
            rerank=_clone_section(self.rerank),
            routing=_clone_section(self.routing),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_flat_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for section_name, cls in _SECTION_CLASSES.items():
            section = getattr(self, section_name)
            for field_name in asdict(cls()).keys():
                result[f"{section_name}.{field_name}"] = getattr(section, field_name)
        return result

    def with_overrides(self, overrides: dict[str, Any], *, strict: bool = True) -> "RAGConfig":
        cfg = self.copy()

        for key, value in (overrides or {}).items():
            if key in _SECTION_CLASSES and isinstance(value, dict):
                section_name = str(key)
                cls = _SECTION_CLASSES[section_name]
                current = getattr(cfg, section_name)
                merged = asdict(current)
                for raw_field, raw_value in value.items():
                    field_name = str(raw_field)
                    if field_name not in merged:
                        if strict:
                            raise KeyError(f"Unknown RAGConfig key: {key}.{raw_field}")
                        continue
                    merged[field_name] = raw_value
                setattr(cfg, section_name, cls(**merged))
                continue

            if "." in str(key):
                section_name, raw_field = str(key).split(".", 1)
                if section_name not in _SECTION_CLASSES:
                    if strict:
                        raise KeyError(f"Unknown RAGConfig key: {key}")
                    continue
                field_name = raw_field
                section = getattr(cfg, section_name)
                if not hasattr(section, field_name):
                    if strict:
                        raise KeyError(f"Unknown RAGConfig key: {key}")
                    continue
                setattr(section, field_name, value)
                continue

            if strict:
                raise KeyError(f"Unknown RAGConfig key: {key}")

        return cfg

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "RAGConfig":
        if not raw:
            return cls()
        base = cls()
        return base.with_overrides(dict(raw), strict=False)
