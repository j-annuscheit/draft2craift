from __future__ import annotations

from pathlib import Path

import shared.services.rag.orchestrator as rag_orchestrator
from shared.services.rag.config import RAGConfig
from shared.services.rag.orchestrator import RAGSystem


def test_dump_state_keeps_backward_compat_key_without_st_runtime() -> None:
    rag = RAGSystem(config=RAGConfig())
    state = rag.dump_state()
    assert bool(state.get("has_st_embeddings")) is False


def test_hf_offline_helper_sets_expected_env(monkeypatch) -> None:
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    monkeypatch.delenv("TRANSFORMERS_OFFLINE", raising=False)
    monkeypatch.delenv("HF_DATASETS_OFFLINE", raising=False)

    rag_orchestrator._ensure_hf_offline_env()

    assert rag_orchestrator.os.environ.get("HF_HUB_OFFLINE") == "1"
    assert rag_orchestrator.os.environ.get("TRANSFORMERS_OFFLINE") == "1"
    assert rag_orchestrator.os.environ.get("HF_DATASETS_OFFLINE") == "1"


def test_resolve_local_hf_model_ref_prefers_cached_snapshot(tmp_path: Path, monkeypatch) -> None:
    hub_root = tmp_path / "hub"
    snapshots = (
        hub_root
        / "models--sentence-transformers--paraphrase-multilingual-MiniLM-L12-v2"
        / "snapshots"
    )
    older = snapshots / "aaa111"
    newer = snapshots / "bbb222"
    older.mkdir(parents=True, exist_ok=True)
    newer.mkdir(parents=True, exist_ok=True)
    rag_orchestrator.os.utime(older, (1000, 1000))
    rag_orchestrator.os.utime(newer, (2000, 2000))

    monkeypatch.setenv("HF_HUB_CACHE", str(hub_root))
    resolved = rag_orchestrator._resolve_local_hf_model_ref(
        "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    )
    assert resolved == str(newer)
