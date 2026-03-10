from __future__ import annotations

import json
from pathlib import Path

from shared.services.project.manager import ProjectManager


def _write_manifest(folder: Path, payload: object) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "project.json").write_text(
        json.dumps(payload),
        encoding="utf-8",
    )


def test_load_project_rejects_non_object_manifest(tmp_path: Path):
    folder = tmp_path / "invalid_project"
    _write_manifest(folder, [])

    manager = ProjectManager()
    ok = manager.load_project(object(), str(folder))

    assert ok is False
    assert "Invalid project.json schema" in manager.last_error
    assert "Top-level JSON must be an object" in manager.last_error


def test_load_project_rejects_missing_required_manifest_fields(tmp_path: Path):
    folder = tmp_path / "missing_fields_project"
    _write_manifest(
        folder,
        {
            "version": 1,
            "canvas": {"tabs": [], "current_tab": 0},
            "knowledge": {"files": []},
            "settings": {},
            "ui": {},
            # "llm" intentionally missing
        },
    )

    manager = ProjectManager()
    ok = manager.load_project(object(), str(folder))

    assert ok is False
    assert "Invalid project.json schema" in manager.last_error
    assert "Missing required field 'llm'" in manager.last_error


def test_load_project_rejects_wrong_nested_types(tmp_path: Path):
    folder = tmp_path / "wrong_types_project"
    _write_manifest(
        folder,
        {
            "version": 1,
            "canvas": {"tabs": {}, "current_tab": 0},
            "knowledge": {"files": []},
            "settings": {},
            "llm": {},
            "ui": {},
        },
    )

    manager = ProjectManager()
    ok = manager.load_project(object(), str(folder))

    assert ok is False
    assert "Invalid project.json schema" in manager.last_error
    assert "canvas.tabs" in manager.last_error
