from __future__ import annotations

import threading

from shared.services.rag.orchestrator import RAGSystem


def _entries_for_iteration(
    base: list[tuple[str, str]],
    iteration: int,
) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for idx, (name, content) in enumerate(base):
        out.append(
            (
                name,
                f"{content}\niteration={iteration} doc_idx={idx} alpha beta gamma",
            )
        )
    return out


def test_parallel_sync_index_and_search_is_stable(
    rag_system: RAGSystem,
    rag_entries: list[tuple[str, str]],
):
    rag_system.sync_index(_entries_for_iteration(rag_entries, 0))
    errors: list[BaseException] = []
    start = threading.Barrier(2)
    stop = threading.Event()

    def _run_indexing() -> None:
        try:
            start.wait(timeout=2.0)
            for i in range(6):
                rag_system.sync_index(_entries_for_iteration(rag_entries, i))
                if i % 15 == 0:
                    rag_system.index_content("volatile.md", f"volatile alpha i={i}")
                if i % 30 == 0:
                    rag_system.remove_file("volatile.md")
        except BaseException as exc:
            errors.append(exc)
        finally:
            stop.set()

    def _run_search() -> None:
        queries = ("alpha", "beta", "gamma", "architecture")
        try:
            start.wait(timeout=2.0)
            spins = 0
            while not stop.is_set() or spins < 10:
                query = queries[spins % len(queries)]
                try:
                    results, debug = rag_system.search(query, top_k=4, with_debug=True)
                except RuntimeError as exc:
                    if "RAG backend unavailable" in str(exc):
                        spins += 1
                        continue
                    raise
                assert isinstance(results, list)
                assert isinstance(debug, dict)
                spins += 1
        except BaseException as exc:
            errors.append(exc)

    index_thread = threading.Thread(target=_run_indexing, name="rag-index")
    search_thread = threading.Thread(target=_run_search, name="rag-search")

    index_thread.start()
    search_thread.start()

    index_thread.join(timeout=45.0)
    search_thread.join(timeout=45.0)

    assert not index_thread.is_alive(), "Index thread did not finish in time"
    assert not search_thread.is_alive(), "Search thread did not finish in time"
    assert not errors, f"Parallel RAG operations raised errors: {errors!r}"

    final = rag_system.search("alpha", top_k=5)
    assert isinstance(final, list)
