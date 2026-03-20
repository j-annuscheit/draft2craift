from shared.services.rag.tfidf import BM25Index, TFIDFIndex, compute_idf, tfidf_score


def test_tfidf_score_prefers_matching_document():
    docs = ["apple banana", "car train"]
    idf = compute_idf(docs)
    score_match = tfidf_score("apple", docs[0], idf)
    score_non_match = tfidf_score("apple", docs[1], idf)
    assert score_match > score_non_match


def test_bm25_index_prefers_matching_document():
    index = BM25Index(k1=1.2, b=0.75)
    index.add_documents_batch(
        {
            "doc_a": "apple banana apple",
            "doc_b": "car train bus",
        }
    )

    ranked = index.search("apple", top_k=2)
    assert ranked
    assert ranked[0][0] == "doc_a"
    assert ranked[0][1] > 0.0


def test_bm25_index_state_roundtrip():
    index = BM25Index(k1=1.4, b=0.65)
    index.add_document("doc_a", "secure token rotation and short expiry")
    state = index.dump_state()

    restored = BM25Index()
    restored.load_state(state)
    ranked = restored.search("token expiry", top_k=1)

    assert ranked
    assert ranked[0][0] == "doc_a"


def test_tfidf_index_state_roundtrip():
    index = TFIDFIndex()
    index.add_document("doc_a", "solar rooftop emissions reduction")
    state = index.dump_state()

    restored = TFIDFIndex()
    restored.load_state(state)
    ranked = restored.search("solar", top_k=1)

    assert ranked
    assert ranked[0][0] == "doc_a"
