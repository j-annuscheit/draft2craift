"""Structured RAG configuration models."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class BackendConfig:
    """Backend toggles and sentence-transformer settings."""

    use_tfidf: bool = True
    use_st: bool = False
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
    """Query expansion (HyDE) parameters."""

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
    score_threshold: float = 0.15


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


_LEGACY_KEY_MAP: dict[str, tuple[str, str]] = {
    "use_tfidf": ("backend", "use_tfidf"),
    "use_st": ("backend", "use_st"),
    "use_regex_search": ("backend", "use_regex_search"),
    "st_model_name": ("backend", "st_model_name"),
    "st_n_threads": ("backend", "st_n_threads"),
    "chunk_size": ("chunking", "chunk_size"),
    "chunk_overlap": ("chunking", "chunk_overlap"),
    "chunking_strategy": ("chunking", "strategy"),
    "include_headings": ("chunking", "include_headings"),
    "include_filename": ("chunking", "include_filename"),
    "use_hyde": ("hyde", "use_hyde"),
    "hyde_min_words": ("hyde", "min_words"),
    "hyde_tfidf_mode": ("hyde", "tfidf_mode"),
    "hyde_st_mode": ("hyde", "st_mode"),
    "hyde_st_hypotheses": ("hyde", "st_hypotheses"),
    "hyde_use_doc_context": ("hyde", "use_doc_context"),
    "extended_context": ("context", "enabled"),
    "extended_context_before": ("context", "before_chars"),
    "extended_context_after": ("context", "after_chars"),
    "selection_mode": ("selection", "mode"),
    "top_k": ("selection", "top_k"),
    "score_threshold": ("selection", "score_threshold"),
    "regex_max_results": ("literal", "max_results"),
    "literal_use_llm_terms": ("literal", "use_llm_terms"),
    "literal_llm_max_terms": ("literal", "max_llm_terms"),
    "llm_rerank_enabled": ("rerank", "enabled"),
    "llm_rerank_min_score": ("rerank", "min_score"),
    "llm_rerank_max_candidates": ("rerank", "max_candidates"),
}


_SECTION_CLASSES = {
    "backend": BackendConfig,
    "chunking": ChunkingConfig,
    "hyde": HyDEConfig,
    "context": ContextConfig,
    "selection": SelectionConfig,
    "literal": LiteralConfig,
    "rerank": RerankConfig,
}


_SECTION_FIELD_ALIASES: dict[str, dict[str, str]] = {
    "chunking": {"chunking_strategy": "strategy"},
    "hyde": {
        "hyde_min_words": "min_words",
        "hyde_tfidf_mode": "tfidf_mode",
        "hyde_st_mode": "st_mode",
        "hyde_st_hypotheses": "st_hypotheses",
        "hyde_use_doc_context": "use_doc_context",
    },
    "context": {
        "extended_context": "enabled",
        "extended_context_before": "before_chars",
        "extended_context_after": "after_chars",
    },
    "selection": {"selection_mode": "mode"},
    "literal": {
        "regex_max_results": "max_results",
        "literal_use_llm_terms": "use_llm_terms",
        "literal_llm_max_terms": "max_llm_terms",
    },
    "rerank": {
        "llm_rerank_enabled": "enabled",
        "llm_rerank_min_score": "min_score",
        "llm_rerank_max_candidates": "max_candidates",
    },
}


def _clone_section(section: Any) -> Any:
    return section.__class__(**asdict(section))


def _normalise_field(section: str, field_name: str) -> str:
    aliases = _SECTION_FIELD_ALIASES.get(section, {})
    return aliases.get(field_name, field_name)


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

    def copy(self) -> "RAGConfig":
        return RAGConfig(
            backend=_clone_section(self.backend),
            chunking=_clone_section(self.chunking),
            hyde=_clone_section(self.hyde),
            context=_clone_section(self.context),
            selection=_clone_section(self.selection),
            literal=_clone_section(self.literal),
            rerank=_clone_section(self.rerank),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_flat_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for legacy_key, (section_name, field_name) in _LEGACY_KEY_MAP.items():
            section = getattr(self, section_name)
            result[legacy_key] = getattr(section, field_name)
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
                    field_name = _normalise_field(section_name, str(raw_field))
                    if field_name not in merged:
                        if strict:
                            raise KeyError(f"Unknown RAGConfig key: {key}.{raw_field}")
                        continue
                    merged[field_name] = raw_value
                setattr(cfg, section_name, cls(**merged))
                continue

            if key in _LEGACY_KEY_MAP:
                section_name, field_name = _LEGACY_KEY_MAP[key]
                setattr(getattr(cfg, section_name), field_name, value)
                continue

            if "." in str(key):
                section_name, raw_field = str(key).split(".", 1)
                if section_name not in _SECTION_CLASSES:
                    if strict:
                        raise KeyError(f"Unknown RAGConfig key: {key}")
                    continue
                field_name = _normalise_field(section_name, raw_field)
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
