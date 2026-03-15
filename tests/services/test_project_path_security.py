from __future__ import annotations

from pathlib import Path

import pytest

from shared.services.project.manager import ProjectManager
from shared.services.project.project_loader import ProjectLoader
from shared.services.project.project_paths import ProjectPaths
from shared.services.project.project_saver import ProjectSaver


def test_project_paths_reject_relative_traversal(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("DRAFT2CRAIFT_APP_DATA_DIR", str(tmp_path))
    with pytest.raises(ValueError, match="traversal"):
        ProjectPaths("../../etc/cron.d")


def test_project_paths_allow_relative_folder_within_app_data_dir(
    monkeypatch, tmp_path: Path
):
    monkeypatch.setenv("DRAFT2CRAIFT_APP_DATA_DIR", str(tmp_path))
    paths = ProjectPaths("projects/demo")
    assert paths.base == (tmp_path / "projects" / "demo").resolve()


def test_project_paths_enforce_allowed_root(tmp_path: Path):
    root = (tmp_path / "allowed").resolve()
    outside = (tmp_path / "outside").resolve()
    root.mkdir(parents=True, exist_ok=True)
    outside.mkdir(parents=True, exist_ok=True)

    with pytest.raises(ValueError, match="allowed root"):
        ProjectPaths(str(outside), allowed_root=str(root))


def test_project_paths_resolve_child_blocks_traversal_and_absolute(tmp_path: Path):
    paths = ProjectPaths(str(tmp_path / "project"))

    assert paths.resolve_canvas_file("doc_0001.md") == (
        paths.canvas / "doc_0001.md"
    ).resolve()

    with pytest.raises(ValueError, match="escapes"):
        paths.resolve_canvas_file("../secret.md")

    with pytest.raises(ValueError, match="must be relative"):
        paths.resolve_canvas_file("/tmp/secret.md")


def test_project_loader_does_not_read_outside_project_folder(tmp_path: Path):
    project_dir = (tmp_path / "project").resolve()
    project_dir.mkdir(parents=True, exist_ok=True)
    outside = (tmp_path / "secret.md").resolve()
    outside.write_text("TOP SECRET", encoding="utf-8")

    paths = ProjectPaths(str(project_dir))
    loader = ProjectLoader(paths=paths)

    with pytest.raises(ValueError, match="escapes"):
        loader._read_canvas_content("../secret.md")
    with pytest.raises(ValueError, match="escapes"):
        loader._read_knowledge_markdown("../secret.md")


def test_project_manager_blocks_save_outside_allowed_root(tmp_path: Path, monkeypatch):
    root = (tmp_path / "allowed").resolve()
    outside = (tmp_path / "outside").resolve()
    root.mkdir(parents=True, exist_ok=True)
    outside.mkdir(parents=True, exist_ok=True)

    save_called = {"value": False}

    def _fake_save(self, mw):
        _ = self, mw
        save_called["value"] = True

    monkeypatch.setattr(ProjectSaver, "save", _fake_save)
    manager = ProjectManager(allowed_root=root)

    ok = manager.save_project(object(), str(outside))

    assert ok is False
    assert "allowed root" in manager.last_error
    assert save_called["value"] is False
