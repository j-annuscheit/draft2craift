from shared.services.rag.chunking import chunk_text


def test_chunk_text_applies_overlap():
    text = "abcdefghij"
    chunks = chunk_text(text, chunk_size=4, overlap=2)
    assert chunks == ["abcd", "cdef", "efgh", "ghij"]
