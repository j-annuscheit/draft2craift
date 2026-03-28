from __future__ import annotations

from shared.services.speech.tts_parts.helpers_text import _normalize_text_for_tts


def test_pronunciation_overrides_replace_custom_terms():
    text = "Deep Learning Algorithmus erklärt fortschrittliche Systeme."

    normalized = _normalize_text_for_tts(text)

    assert "Diip Loer-ning" in normalized
