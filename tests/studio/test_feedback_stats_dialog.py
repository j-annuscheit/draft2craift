from __future__ import annotations

from pathlib import Path

from shared.domain.user_mode import USER_MODE_CONFIG_PATH, reload_user_mode_config
from studio.feedback.stats_dialog import FeedbackStatsDialog


class _FeedbackStatsServiceStub:
    def __init__(self, counters: dict | None = None) -> None:
        self._counters = dict(counters or {})

    def get_counters(self) -> dict:
        return dict(self._counters)


def _write_stats_mode_config(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "alpha.toml").write_text(
        """
version = 1
id = "alpha"
label = "Alpha"
order = 0
default_profile = true

[visibility]

[labels]
"feedback.stats.window_title" = "Feedback Statistics"
"feedback.stats.summary.empty" = "No feedback recorded yet."
"feedback.stats.header.feature" = "Feature"
"feedback.stats.header.events" = "Events"
"feedback.stats.header.positive" = "Positive"
"feedback.stats.header.negative" = "Negative"
"feedback.stats.button.refresh" = "Refresh"
"feedback.stats.button.close" = "Close"
""".strip(),
        encoding="utf-8",
    )

    (path / "beta.toml").write_text(
        """
version = 1
id = "beta"
label = "Beta"
order = 1
default_profile = false

[visibility]

[labels]
"feedback.stats.window_title" = "Feedback Statistik"
"feedback.stats.summary.empty" = "Noch kein Feedback erfasst."
"feedback.stats.header.feature" = "Funktion"
"feedback.stats.header.events" = "Events"
"feedback.stats.header.positive" = "Positiv"
"feedback.stats.header.negative" = "Negativ"
"feedback.stats.button.refresh" = "Aktualisieren"
"feedback.stats.button.close" = "Schließen"
""".strip(),
        encoding="utf-8",
    )


def _headers(dialog: FeedbackStatsDialog) -> list[str]:
    return [dialog._table.horizontalHeaderItem(i).text() for i in range(4)]


def test_feedback_stats_dialog_labels_are_profile_driven(tmp_path: Path, qt_app):
    _ = qt_app
    cfg = tmp_path / "user_modes"
    _write_stats_mode_config(cfg)

    try:
        reload_user_mode_config(cfg)
        dialog = FeedbackStatsDialog(_FeedbackStatsServiceStub(counters={}), user_mode="beta")

        assert dialog.windowTitle() == "Feedback Statistik"
        assert dialog._summary_lbl.text() == "Noch kein Feedback erfasst."
        assert _headers(dialog) == ["Funktion", "Events", "Positiv", "Negativ"]
        assert dialog._refresh_btn.text() == "Aktualisieren"
        assert dialog._close_btn is not None
        assert dialog._close_btn.text() == "Schließen"

        dialog.set_user_mode("alpha")
        assert dialog.windowTitle() == "Feedback Statistics"
        assert dialog._summary_lbl.text() == "No feedback recorded yet."
        assert _headers(dialog) == ["Feature", "Events", "Positive", "Negative"]
        assert dialog._refresh_btn.text() == "Refresh"
        assert dialog._close_btn.text() == "Close"
    finally:
        reload_user_mode_config(USER_MODE_CONFIG_PATH)
