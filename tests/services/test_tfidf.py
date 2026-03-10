from shared.services.rag.tfidf import compute_idf, tfidf_score


def test_tfidf_score_prefers_matching_document():
    docs = ["apple banana", "car train"]
    idf = compute_idf(docs)
    score_match = tfidf_score("apple", docs[0], idf)
    score_non_match = tfidf_score("apple", docs[1], idf)
    assert score_match > score_non_match
