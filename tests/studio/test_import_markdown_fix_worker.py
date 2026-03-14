from __future__ import annotations

import unittest

from shared.services.llm.markdown_fix_tasks import fix_markdown_chunk_sync
from studio.importer.workers import MarkdownLLMFixWorker


class _FakeWorker:
    def isRunning(self):
        return False


class _FakeModel:
    def __init__(self, tokens: list[str]):
        self.tokens = list(tokens)
        self.calls: list[dict[str, object]] = []

    def __call__(self, prompt, **kwargs):
        self.calls.append({"prompt": prompt, **kwargs})

        def _iter():
            for token in self.tokens:
                yield {"choices": [{"text": token}]}

        return _iter()


class _FakeManager:
    def __init__(self, model):
        self.worker = _FakeWorker()
        self._stream_model = model
        self._log = None
        self.logged_io: list[tuple[str, str | None]] = []

    def is_model_loaded(self):
        return True

    def _count_tokens(self, text):
        return max(1, len(str(text or "").split()))

    def _check_prompt_window(self, prompt, max_out_tokens):
        _ = prompt, max_out_tokens
        return ""

    def _log_llm_io(self, call_name, prompt, output=None, error=None):
        _ = prompt
        self.logged_io.append((str(call_name), str(error) if error is not None else None))

    def _stream_backend_text(
        self,
        prompt,
        *,
        max_tokens,
        temperature,
        top_p,
        repeat_penalty,
        stop_tokens,
        stop_requested=None,
    ):
        _ = max_tokens, temperature, top_p, repeat_penalty, stop_tokens
        result = self._stream_model(prompt, stream=True)
        for event in result:
            if callable(stop_requested) and bool(stop_requested()):
                break
            token = str(event["choices"][0].get("text", "") or "")
            if token:
                yield token

    @staticmethod
    def _extract_tagged_payload_with_flag(raw_text, tag):
        text = str(raw_text or "")
        open_tag = f"<{tag}>"
        close_tag = f"</{tag}>"
        if open_tag in text and close_tag in text:
            start = text.index(open_tag) + len(open_tag)
            end = text.index(close_tag, start)
            return text[start:end].strip(), True
        return text.strip(), False


class ImportMarkdownFixWorkerTests(unittest.TestCase):
    def test_strip_new_single_emphasis_markup(self):
        original = "In nerhalb des Abschnitts."
        candidate = "In *nerhalb* des Abschnitts."
        cleaned = MarkdownLLMFixWorker._strip_new_single_emphasis_markup(
            original,
            candidate,
        )
        self.assertEqual(cleaned, "In nerhalb des Abschnitts.")

    def test_escape_internal_word_asterisks(self):
        source = "Künstler*innen und Sportler*innen"
        escaped = MarkdownLLMFixWorker._escape_internal_word_asterisks(source)
        self.assertEqual(escaped, r"Künstler\*innen und Sportler\*innen")

    def test_promote_bold_numbered_heading_with_inline_body(self):
        source = (
            "**5.2.4 Basis- und Vergleichstexte** "
            "Im Anschluss an die Erhebung der persoenlichen Daten ..."
        )
        out = MarkdownLLMFixWorker._promote_bold_numbered_headings(source, offset=1)
        self.assertTrue(out.startswith("#### 5.2.4 Basis- und Vergleichstexte"))
        self.assertIn(
            "\n\nIm Anschluss an die Erhebung der persoenlichen Daten ...",
            out,
        )

    def test_do_not_promote_score_legend_line_with_multiple_bold_spans(self):
        source = "**0 P.** **1 P.** **2 P.** Trifft nicht zu Trifft teilweise zu Trifft zu"
        out = MarkdownLLMFixWorker._promote_bold_numbered_headings(source, offset=1)
        self.assertEqual(out, source)

    def test_do_not_relevel_score_like_heading(self):
        source = "## 0 P."
        out = MarkdownLLMFixWorker._normalize_numbered_heading_levels(
            source,
            offset=1,
        )
        self.assertEqual(out, source)

    def test_normalize_numbered_heading_levels(self):
        source = "### 5.2.4 Basis- und Vergleichstexte"
        out = MarkdownLLMFixWorker._normalize_numbered_heading_levels(
            source,
            offset=1,
        )
        self.assertEqual(out, "#### 5.2.4 Basis- und Vergleichstexte")

    def test_infer_numbered_heading_offset(self):
        source = (
            "## 1 Einleitung\n"
            "### 1.1 Ziel\n"
            "#### 1.1.1 Methodik\n"
        )
        offset = MarkdownLLMFixWorker._infer_numbered_heading_offset(source, default=1)
        self.assertEqual(offset, 1)

    def test_fix_markdown_chunk_sync_uses_streaming_generation(self):
        model = _FakeModel(["<fixed_md>\n## Titel\n", "Text\n", "</fixed_md>"])
        manager = _FakeManager(model)

        output, meta = fix_markdown_chunk_sync(manager, "# Titel\nText\n")

        self.assertEqual(output, "## Titel\nText")
        self.assertEqual(meta.get("reason"), "ok")
        self.assertEqual(len(model.calls), 1)
        self.assertTrue(bool(model.calls[0].get("stream")))

    def test_fix_markdown_chunk_sync_stops_cleanly(self):
        model = _FakeModel(["<fixed_md>\nTeil", "weise", "</fixed_md>"])
        manager = _FakeManager(model)
        calls = {"count": 0}

        def stop_requested():
            calls["count"] += 1
            return calls["count"] >= 2

        source = "# Original\nText\n"
        output, meta = fix_markdown_chunk_sync(
            manager,
            source,
            stop_requested=stop_requested,
        )

        self.assertEqual(output, source)
        self.assertEqual(meta.get("reason"), "stopped")
        self.assertTrue(any(error == "stopped" for _name, error in manager.logged_io))


if __name__ == "__main__":
    unittest.main()
