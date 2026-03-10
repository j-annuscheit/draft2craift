from shared.domain.feedback import FeedbackEntry, FeedbackType


def test_feedback_entry_keeps_payload():
    entry = FeedbackEntry(
        session_id="s1",
        feedback_type=FeedbackType.FREEFORM,
        text="too verbose",
        category="style",
    )
    assert entry.session_id == "s1"
    assert entry.feedback_type is FeedbackType.FREEFORM
    assert entry.category == "style"
