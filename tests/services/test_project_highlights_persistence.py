from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from shared.services.highlights.store import HighlightStore
from shared.services.project.project_loader import ProjectLoader
from shared.services.project.project_paths import ProjectPaths
from shared.services.project.project_saver import ProjectSaver


def test_project_paths_expose_highlights_file(tmp_path: Path):
    paths = ProjectPaths(str(tmp_path / "project-a"))
    assert paths.highlights == paths.base / "highlights.json"


def test_project_saver_writes_highlights_snapshot(tmp_path: Path):
    runtime_store = HighlightStore(path=tmp_path / "runtime" / "highlights.json")
    runtime_store.replace_glossary_entries(
        entries=[{"term": "LLM", "definition": "Large language model"}],
        panel_scope="*",
        apply_all_tabs=True,
    )

    paths = ProjectPaths(str(tmp_path / "project-b"))
    saver = ProjectSaver(paths=paths, include_st_embeddings=False)

    with patch(
        "shared.services.project.project_saver.get_highlight_store",
        return_value=runtime_store,
    ):
        saver._save_highlights()

    saved = json.loads(paths.highlights.read_text(encoding="utf-8"))
    assert isinstance(saved.get("highlights"), list)
    assert len(saved["highlights"]) > 0
    assert saved.get("settings", {}).get("glossary_enabled") is True


def test_project_loader_rebinds_store_to_project_highlights_file(tmp_path: Path):
    paths = ProjectPaths(str(tmp_path / "project-c"))
    paths.base.mkdir(parents=True, exist_ok=True)
    paths.highlights.write_text(
        json.dumps(
            {
                "version": 2,
                "highlights": [],
                "settings": {"glossary_enabled": False},
            }
        ),
        encoding="utf-8",
    )

    runtime_store = HighlightStore(path=tmp_path / "runtime2" / "highlights.json")
    runtime_store.set_glossary_enabled(True)

    loader = ProjectLoader(paths=paths)
    with patch(
        "shared.services.project.project_loader.get_highlight_store",
        return_value=runtime_store,
    ):
        loader._restore_highlights(mw=object())

    assert runtime_store.path == paths.highlights.resolve(strict=False)
    assert runtime_store.is_glossary_enabled() is False


def test_project_loader_syncs_glossary_toggle_action(tmp_path: Path):
    class _ActionStub:
        def __init__(self):
            self.checked = None

        def blockSignals(self, _value: bool):
            return False

        def setChecked(self, value: bool):
            self.checked = bool(value)

    class _MainWindowStub:
        def __init__(self):
            self._action_glossary_overlay = _ActionStub()

    paths = ProjectPaths(str(tmp_path / "project-d"))
    paths.base.mkdir(parents=True, exist_ok=True)
    paths.highlights.write_text(
        json.dumps(
            {
                "version": 2,
                "highlights": [],
                "settings": {"glossary_enabled": False},
            }
        ),
        encoding="utf-8",
    )

    runtime_store = HighlightStore(path=tmp_path / "runtime3" / "highlights.json")
    runtime_store.set_glossary_enabled(True)

    window = _MainWindowStub()
    loader = ProjectLoader(paths=paths)
    with patch(
        "shared.services.project.project_loader.get_highlight_store",
        return_value=runtime_store,
    ):
        loader._restore_highlights(mw=window)

    assert window._action_glossary_overlay.checked is False
