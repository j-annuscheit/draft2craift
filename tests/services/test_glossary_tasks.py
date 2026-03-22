from __future__ import annotations

from types import SimpleNamespace

from shared.services.llm.glossary_tasks import generate_glossary_sync


class _GlossaryHarness:
    def __init__(self) -> None:
        self.worker = SimpleNamespace(isRunning=lambda: False)
        self._prompts = {"glossary_system": "System prompt"}
        self.prompt_calls: list[str] = []
        self._log = None

    def is_model_loaded(self) -> bool:
        return True

    def _n_ctx(self) -> int:
        return 32768

    def _render_prompt_template(self, key: str, values: dict[str, str]) -> str:
        _ = key
        return (
            "Kontext:\n"
            f"{values.get('context', '')}\n\n"
            f"Maximal {values.get('max_terms', '')} Einträge.\n"
        )

    def _check_prompt_window(self, prompt: str, max_tokens: int) -> str:
        self.prompt_calls.append(str(prompt))
        _ = max_tokens
        return ""

    def _generate_backend_text(self, prompt: str, **kwargs) -> str:
        self.prompt_calls.append(str(prompt))
        _ = kwargs
        return '[{"term":"Alpha","definition":"Beta"}]'

    def _log_llm_io(self, *args, **kwargs) -> None:
        _ = args, kwargs


def test_generate_glossary_sync_uses_full_context_without_compaction():
    harness = _GlossaryHarness()
    tail = "TAIL_FULL_CONTEXT_GLOSSARY_TASK"
    context_text = ("X" * 32000) + tail

    entries, meta = generate_glossary_sync(
        harness,
        context_text=context_text,
        max_terms=8,
        focus_query="Technische Risiken",
    )

    assert entries
    assert meta.get("applied") is True
    assert meta.get("context_compacted") is False
    assert int(meta.get("context_chars_used", 0) or 0) == len(context_text)
    assert harness.prompt_calls
    assert tail in harness.prompt_calls[-1]
    assert "[... Kontext gekürzt ...]" not in harness.prompt_calls[-1]
