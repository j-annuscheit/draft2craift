from __future__ import annotations

import types
import time

from shared.services.llm.chat_context_runtime import (
    _on_complete,
    _on_error,
    _on_token,
)


class _RecorderSignal:
    def __init__(self, name: str, events: list[tuple[str, tuple[object, ...]]]):
        self._name = str(name)
        self._events = events

    def emit(self, *args):  # noqa: ANN002
        self._events.append((self._name, tuple(args)))


def test_on_error_resets_generating_before_emitting_error():
    events: list[tuple[str, tuple[object, ...]]] = []
    dummy = types.SimpleNamespace(
        _log=None,
        is_generating=_RecorderSignal("is_generating", events),
        error_occurred=_RecorderSignal("error_occurred", events),
    )

    _on_error(dummy, "boom")

    assert events == [
        ("is_generating", (False,)),
        ("error_occurred", ("boom",)),
    ]


def test_on_token_hides_think_blocks_across_split_tokens():
    events: list[tuple[str, tuple[object, ...]]] = []
    dummy = types.SimpleNamespace(
        _log=None,
        _token_count=0,
        _gen_start=time.perf_counter(),
        _forbidden_chars=set(),
        _hide_think_blocks=True,
        _think_stream_pending="",
        _think_stream_inside=False,
        token_received=_RecorderSignal("token_received", events),
        generation_complete=_RecorderSignal("generation_complete", events),
        is_generating=_RecorderSignal("is_generating", events),
        _apply_forbidden_filter=lambda text: str(text or ""),
    )

    _on_token(dummy, "<thi")
    _on_token(dummy, "nk>internal")
    _on_token(dummy, "</th")
    _on_token(dummy, "ink>Antwort")
    _on_complete(dummy, "<think>internal</think>Antwort")

    payloads = [args[0] for name, args in events if name == "token_received"]
    assert "".join(payloads) == "Antwort"


def test_on_complete_strips_think_block_from_final_response():
    events: list[tuple[str, tuple[object, ...]]] = []
    dummy = types.SimpleNamespace(
        _log=None,
        _token_count=2,
        _gen_start=time.perf_counter(),
        _forbidden_chars=set(),
        _hide_think_blocks=True,
        _think_stream_pending="",
        _think_stream_inside=False,
        token_received=_RecorderSignal("token_received", events),
        generation_complete=_RecorderSignal("generation_complete", events),
        is_generating=_RecorderSignal("is_generating", events),
        _apply_forbidden_filter=lambda text: str(text or ""),
    )

    _on_complete(dummy, "<think>internal</think>Visible")

    assert ("generation_complete", ("Visible",)) in events
    assert ("is_generating", (False,)) in events
    assert getattr(dummy, "_last_think_text", "") == "internal"


def test_on_complete_strips_prefix_when_only_closing_think_tag_exists():
    events: list[tuple[str, tuple[object, ...]]] = []
    dummy = types.SimpleNamespace(
        _log=None,
        _token_count=1,
        _gen_start=time.perf_counter(),
        _forbidden_chars=set(),
        _hide_think_blocks=True,
        _think_stream_pending="",
        _think_stream_inside=False,
        token_received=_RecorderSignal("token_received", events),
        generation_complete=_RecorderSignal("generation_complete", events),
        is_generating=_RecorderSignal("is_generating", events),
        _apply_forbidden_filter=lambda text: str(text or ""),
    )

    _on_complete(dummy, "internal chain of thought</think>Visible")

    assert ("generation_complete", ("Visible",)) in events
    assert getattr(dummy, "_last_think_text", "") == "internal chain of thought"


def test_on_token_hides_implicit_think_prefix_when_stream_starts_inside():
    events: list[tuple[str, tuple[object, ...]]] = []
    dummy = types.SimpleNamespace(
        _log=None,
        _token_count=0,
        _gen_start=time.perf_counter(),
        _forbidden_chars=set(),
        _hide_think_blocks=True,
        _think_stream_pending="",
        _think_stream_inside=True,
        _think_stream_implicit_prefix=True,
        token_received=_RecorderSignal("token_received", events),
        generation_complete=_RecorderSignal("generation_complete", events),
        is_generating=_RecorderSignal("is_generating", events),
        _apply_forbidden_filter=lambda text: str(text or ""),
    )

    _on_token(dummy, "internal")
    _on_token(dummy, "</think>Antwort")
    _on_complete(dummy, "internal</think>Antwort")

    payloads = [args[0] for name, args in events if name == "token_received"]
    assert "".join(payloads) == "Antwort"


def test_on_token_emits_thinking_delta_without_close_tag_or_answer_tail():
    events: list[tuple[str, tuple[object, ...]]] = []
    dummy = types.SimpleNamespace(
        _log=None,
        _token_count=0,
        _gen_start=time.perf_counter(),
        _forbidden_chars=set(),
        _hide_think_blocks=True,
        _think_stream_pending="",
        _think_stream_inside=True,
        _think_stream_implicit_prefix=True,
        _last_think_text="",
        thinking_received=_RecorderSignal("thinking_received", events),
        token_received=_RecorderSignal("token_received", events),
        generation_complete=_RecorderSignal("generation_complete", events),
        is_generating=_RecorderSignal("is_generating", events),
        _apply_forbidden_filter=lambda text: str(text or ""),
    )

    _on_token(dummy, "inter")
    _on_token(dummy, "nal</think>Antwort")
    _on_complete(dummy, "internal</think>Antwort")

    think_payloads = [args[0] for name, args in events if name == "thinking_received"]
    visible_payloads = [args[0] for name, args in events if name == "token_received"]
    assert "".join(think_payloads) == "internal"
    assert "".join(visible_payloads) == "Antwort"
    assert getattr(dummy, "_last_think_text", "") == "internal"


def test_on_complete_does_not_treat_plain_text_as_thinking_for_implicit_prefix():
    events: list[tuple[str, tuple[object, ...]]] = []
    dummy = types.SimpleNamespace(
        _log=None,
        _token_count=0,
        _gen_start=time.perf_counter(),
        _forbidden_chars=set(),
        _hide_think_blocks=True,
        _think_stream_pending="",
        _think_stream_inside=True,
        _think_stream_implicit_prefix=True,
        _last_think_text="",
        thinking_received=_RecorderSignal("thinking_received", events),
        token_received=_RecorderSignal("token_received", events),
        generation_complete=_RecorderSignal("generation_complete", events),
        is_generating=_RecorderSignal("is_generating", events),
        _apply_forbidden_filter=lambda text: str(text or ""),
    )

    _on_token(dummy, "Kuchen")
    _on_complete(dummy, "Kuchen")

    think_payloads = [args[0] for name, args in events if name == "thinking_received"]
    visible_payloads = [args[0] for name, args in events if name == "token_received"]
    assert "".join(think_payloads) == ""
    assert "".join(visible_payloads) == "Kuchen"
    assert ("generation_complete", ("Kuchen",)) in events
    assert getattr(dummy, "_last_think_text", "") == ""


def test_on_complete_implicit_prefix_without_close_keeps_reasoning_as_thinking():
    events: list[tuple[str, tuple[object, ...]]] = []
    dummy = types.SimpleNamespace(
        _log=None,
        _token_count=0,
        _gen_start=time.perf_counter(),
        _forbidden_chars=set(),
        _hide_think_blocks=True,
        _think_stream_pending="",
        _think_stream_inside=True,
        _think_stream_implicit_prefix=True,
        _last_think_text="",
        thinking_received=_RecorderSignal("thinking_received", events),
        token_received=_RecorderSignal("token_received", events),
        generation_complete=_RecorderSignal("generation_complete", events),
        is_generating=_RecorderSignal("is_generating", events),
        _apply_forbidden_filter=lambda text: str(text or ""),
    )

    payload = "I need to reason step by step before I answer."
    _on_token(dummy, payload)
    _on_complete(dummy, payload)

    think_payloads = [args[0] for name, args in events if name == "thinking_received"]
    visible_payloads = [args[0] for name, args in events if name == "token_received"]
    assert "".join(think_payloads) == payload
    assert "".join(visible_payloads) == ""
    assert ("generation_complete", (payload,)) in events
    assert getattr(dummy, "_last_think_text", "") == payload
