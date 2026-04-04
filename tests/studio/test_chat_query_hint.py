from __future__ import annotations

from types import SimpleNamespace

from studio.chat.dock_parts import context_helpers, public_api


def test_get_user_query_hint_does_not_fallback_to_last_message():
    dock = SimpleNamespace(
        input_box=SimpleNamespace(toPlainText=lambda: "   "),
        _last_user_msg="alte frage aus dem verlauf",
    )
    assert public_api.get_user_query_hint(dock) == ""


def test_collect_shared_context_uses_current_input_over_context_query():
    dock = SimpleNamespace(
        _context_getter=lambda: {
            "file_contents": [],
            "rag_results": [],
            "selected_text": "",
            "selected_span": None,
            "user_query": "query aus context getter",
            "grounding_required": False,
            "grounding_has_sources": False,
            "grounding_selected_docs": 0,
            "grounding_rag_selected": False,
            "grounding_rag_has_data": False,
        },
        input_box=SimpleNamespace(toPlainText=lambda: "aktuelle eingabe"),
        _last_user_msg="alte nachricht",
    )
    ctx = context_helpers._collect_shared_context(dock)
    assert str(ctx.get("user_query", "")) == "aktuelle eingabe"


def test_collect_shared_context_uses_context_query_when_input_empty():
    dock = SimpleNamespace(
        _context_getter=lambda: {
            "file_contents": [],
            "rag_results": [],
            "selected_text": "",
            "selected_span": None,
            "user_query": "query aus context getter",
            "grounding_required": False,
            "grounding_has_sources": False,
            "grounding_selected_docs": 0,
            "grounding_rag_selected": False,
            "grounding_rag_has_data": False,
        },
        input_box=SimpleNamespace(toPlainText=lambda: "  "),
        _last_user_msg="alte nachricht",
    )
    ctx = context_helpers._collect_shared_context(dock)
    assert str(ctx.get("user_query", "")) == "query aus context getter"
