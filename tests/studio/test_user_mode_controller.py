from __future__ import annotations

from studio.controllers.user_mode_controller import UserModeController


def test_user_mode_controller_normalizes_mode_and_tracks_payload():
    ctrl = UserModeController("  ")
    assert ctrl.get_user_mode()

    normalized = ctrl.set_user_mode("PLUS")
    assert normalized
    assert ctrl.get_user_mode() == normalized

    ctrl.set_status_feedback_payload({"mindmap": {"nodes": 3}})
    payload = ctrl.status_feedback_payload
    assert payload == {"mindmap": {"nodes": 3}}

    payload["mindmap"] = {}
    assert ctrl.status_feedback_payload == {"mindmap": {"nodes": 3}}
