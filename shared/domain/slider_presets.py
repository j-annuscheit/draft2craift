"""Data-driven slider presets loaded from data/slider_presets.toml."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tomllib


_REPO_ROOT = Path(__file__).resolve().parents[2]
SLIDER_PRESET_CONFIG_PATH = _REPO_ROOT / "data" / "slider_presets.toml"

_DEFAULT_CHAT_GENERATION_STYLE_PRESETS: tuple[dict[str, float], ...] = (
    {"temperature": 0.20, "top_p": 0.85, "repeat_penalty": 1.15},
    {"temperature": 0.70, "top_p": 0.90, "repeat_penalty": 1.10},
    {"temperature": 1.00, "top_p": 0.98, "repeat_penalty": 1.00},
)

_DEFAULT_CHAT_CONTEXT_LENGTH_PRESETS: tuple[int, ...] = (2048, 4096, 8192)

_DEFAULT_RAG_SCOPE_PRESETS: tuple[dict[str, object], ...] = (
    {
        "extended_context": False,
        "ext_before": 300,
        "ext_after": 300,
        "selection_mode": "top_k_threshold",
        "top_k": 3,
        "threshold": 0.10,
        "regex_max": 2,
    },
    {
        "extended_context": False,
        "ext_before": 500,
        "ext_after": 500,
        "selection_mode": "top_k_threshold",
        "top_k": 5,
        "threshold": 0.05,
        "regex_max": 3,
    },
    {
        "extended_context": True,
        "ext_before": 800,
        "ext_after": 800,
        "selection_mode": "top_k",
        "top_k": 8,
        "threshold": 0.0,
        "regex_max": 6,
    },
)

_DEFAULT_RAG_SPEED_QUALITY_PRESETS: tuple[dict[str, object], ...] = (
    {
        "use_hyde": False,
        "hyde_min_words": 6,
        "hyde_tfidf_mode": "keywords",
        "hyde_st_mode": "passage",
        "hyde_st_hypotheses": 3,
        "hyde_use_doc_context": False,
        "literal_use_llm_terms": False,
        "literal_llm_max_terms": 8,
        "llm_rerank_enabled": False,
        "llm_rerank_min_score": 0.45,
        "llm_rerank_max_candidates": 8,
    },
    {
        "use_hyde": True,
        "hyde_min_words": 5,
        "hyde_tfidf_mode": "keywords",
        "hyde_st_mode": "passage",
        "hyde_st_hypotheses": 3,
        "hyde_use_doc_context": False,
        "literal_use_llm_terms": False,
        "literal_llm_max_terms": 8,
        "llm_rerank_enabled": False,
        "llm_rerank_min_score": 0.45,
        "llm_rerank_max_candidates": 10,
    },
    {
        "use_hyde": True,
        "hyde_min_words": 3,
        "hyde_tfidf_mode": "passage",
        "hyde_st_mode": "multi_passage",
        "hyde_st_hypotheses": 4,
        "hyde_use_doc_context": True,
        "literal_use_llm_terms": True,
        "literal_llm_max_terms": 12,
        "llm_rerank_enabled": True,
        "llm_rerank_min_score": 0.35,
        "llm_rerank_max_candidates": 16,
    },
)


@dataclass(frozen=True, slots=True)
class _SliderPresetCatalog:
    chat_generation_style: tuple[dict[str, float], ...]
    chat_context_length: tuple[int, ...]
    rag_scope: tuple[dict[str, object], ...]
    rag_speed_quality: tuple[dict[str, object], ...]


def _copy_dict_tuple(items: tuple[dict[str, object], ...]) -> tuple[dict[str, object], ...]:
    return tuple(dict(item) for item in items)


def _copy_float_dict_tuple(items: tuple[dict[str, float], ...]) -> tuple[dict[str, float], ...]:
    return tuple(dict(item) for item in items)


def _read_toml(path: Path) -> dict:
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


def _table_array(raw: dict, *path: str) -> list[dict]:
    node: object = raw
    for key in path:
        if not isinstance(node, dict):
            return []
        node = node.get(key)
    if not isinstance(node, list):
        return []
    rows: list[dict] = []
    for entry in node:
        if isinstance(entry, dict):
            rows.append(entry)
    return rows


def _to_float(value: object, default: float) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if text:
            try:
                return float(text)
            except Exception:
                return default
    return default


def _to_int(value: object, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if text:
            try:
                return int(float(text))
            except Exception:
                return default
    return default


def _to_bool(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return bool(value)
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"true", "1", "yes", "on"}:
            return True
        if text in {"false", "0", "no", "off"}:
            return False
    return default


def _to_text(value: object, default: str) -> str:
    text = str(value or "").strip()
    return text if text else default


def _parse_chat_generation(raw: dict) -> tuple[dict[str, float], ...]:
    rows = _table_array(raw, "chat", "generation_style")
    if len(rows) != len(_DEFAULT_CHAT_GENERATION_STYLE_PRESETS):
        return _copy_float_dict_tuple(_DEFAULT_CHAT_GENERATION_STYLE_PRESETS)

    parsed: list[dict[str, float]] = []
    for idx, default in enumerate(_DEFAULT_CHAT_GENERATION_STYLE_PRESETS):
        row = rows[idx]
        parsed.append(
            {
                "temperature": _to_float(row.get("temperature"), default["temperature"]),
                "top_p": _to_float(row.get("top_p"), default["top_p"]),
                "repeat_penalty": _to_float(row.get("repeat_penalty"), default["repeat_penalty"]),
            }
        )
    return tuple(parsed)


def _parse_chat_context(raw: dict) -> tuple[int, ...]:
    rows = _table_array(raw, "chat", "context_length")
    if len(rows) != len(_DEFAULT_CHAT_CONTEXT_LENGTH_PRESETS):
        return tuple(_DEFAULT_CHAT_CONTEXT_LENGTH_PRESETS)

    parsed: list[int] = []
    for idx, default in enumerate(_DEFAULT_CHAT_CONTEXT_LENGTH_PRESETS):
        row = rows[idx]
        parsed.append(_to_int(row.get("context_tokens"), int(default)))
    return tuple(parsed)


def _parse_rag_scope(raw: dict) -> tuple[dict[str, object], ...]:
    rows = _table_array(raw, "rag", "scope")
    if len(rows) != len(_DEFAULT_RAG_SCOPE_PRESETS):
        return _copy_dict_tuple(_DEFAULT_RAG_SCOPE_PRESETS)

    parsed: list[dict[str, object]] = []
    for idx, default in enumerate(_DEFAULT_RAG_SCOPE_PRESETS):
        row = rows[idx]
        parsed.append(
            {
                "extended_context": _to_bool(row.get("extended_context"), bool(default["extended_context"])),
                "ext_before": _to_int(row.get("ext_before"), int(default["ext_before"])),
                "ext_after": _to_int(row.get("ext_after"), int(default["ext_after"])),
                "selection_mode": _to_text(row.get("selection_mode"), str(default["selection_mode"])),
                "top_k": _to_int(row.get("top_k"), int(default["top_k"])),
                "threshold": _to_float(row.get("threshold"), float(default["threshold"])),
                "regex_max": _to_int(row.get("regex_max"), int(default["regex_max"])),
            }
        )
    return tuple(parsed)


def _parse_rag_speed_quality(raw: dict) -> tuple[dict[str, object], ...]:
    rows = _table_array(raw, "rag", "speed_quality")
    if len(rows) != len(_DEFAULT_RAG_SPEED_QUALITY_PRESETS):
        return _copy_dict_tuple(_DEFAULT_RAG_SPEED_QUALITY_PRESETS)

    parsed: list[dict[str, object]] = []
    for idx, default in enumerate(_DEFAULT_RAG_SPEED_QUALITY_PRESETS):
        row = rows[idx]
        parsed.append(
            {
                "use_hyde": _to_bool(row.get("use_hyde"), bool(default["use_hyde"])),
                "hyde_min_words": _to_int(row.get("hyde_min_words"), int(default["hyde_min_words"])),
                "hyde_tfidf_mode": _to_text(row.get("hyde_tfidf_mode"), str(default["hyde_tfidf_mode"])),
                "hyde_st_mode": _to_text(row.get("hyde_st_mode"), str(default["hyde_st_mode"])),
                "hyde_st_hypotheses": _to_int(
                    row.get("hyde_st_hypotheses"),
                    int(default["hyde_st_hypotheses"]),
                ),
                "hyde_use_doc_context": _to_bool(
                    row.get("hyde_use_doc_context"),
                    bool(default["hyde_use_doc_context"]),
                ),
                "literal_use_llm_terms": _to_bool(
                    row.get("literal_use_llm_terms"),
                    bool(default["literal_use_llm_terms"]),
                ),
                "literal_llm_max_terms": _to_int(
                    row.get("literal_llm_max_terms"),
                    int(default["literal_llm_max_terms"]),
                ),
                "llm_rerank_enabled": _to_bool(
                    row.get("llm_rerank_enabled"),
                    bool(default["llm_rerank_enabled"]),
                ),
                "llm_rerank_min_score": _to_float(
                    row.get("llm_rerank_min_score"),
                    float(default["llm_rerank_min_score"]),
                ),
                "llm_rerank_max_candidates": _to_int(
                    row.get("llm_rerank_max_candidates"),
                    int(default["llm_rerank_max_candidates"]),
                ),
            }
        )
    return tuple(parsed)


def _load_catalog(path: Path | None = None) -> _SliderPresetCatalog:
    target = SLIDER_PRESET_CONFIG_PATH if path is None else Path(path)
    raw = _read_toml(target)
    return _SliderPresetCatalog(
        chat_generation_style=_parse_chat_generation(raw),
        chat_context_length=_parse_chat_context(raw),
        rag_scope=_parse_rag_scope(raw),
        rag_speed_quality=_parse_rag_speed_quality(raw),
    )


_CATALOG = _load_catalog()


def reload_slider_preset_config(path: str | Path | None = None) -> None:
    """Reload slider presets from data file (used by tests/tools)."""
    global _CATALOG
    _CATALOG = _load_catalog(None if path is None else Path(path))


def chat_generation_style_presets() -> tuple[dict[str, float], ...]:
    return _copy_float_dict_tuple(_CATALOG.chat_generation_style)


def chat_context_length_presets() -> tuple[int, ...]:
    return tuple(int(value) for value in _CATALOG.chat_context_length)


def rag_scope_presets() -> tuple[dict[str, object], ...]:
    return _copy_dict_tuple(_CATALOG.rag_scope)


def rag_speed_quality_presets() -> tuple[dict[str, object], ...]:
    return _copy_dict_tuple(_CATALOG.rag_speed_quality)
