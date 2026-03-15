from __future__ import annotations

import json
from pathlib import Path
import zipfile

import pytest

from shared.services.project.manager import ProjectManager
from shared.services.project.project_archive import (
    ProjectArchiveError,
    create_project_archive,
    extract_project_archive,
)
from shared.services.project.project_loader import ProjectLoader
from shared.services.project.project_saver import ProjectSaver


def _create_project_folder(base: Path) -> None:
    for folder in ("canvas", "knowledge", "rag", "chat", "logs"):
        (base / folder).mkdir(parents=True, exist_ok=True)

    manifest = {
        "version": 1,
        "rag_config": {},
        "canvas": {"tabs": [], "current_tab": 0},
        "knowledge": {"files": []},
        "settings": {},
        "llm": {},
        "ui": {},
    }
    (base / "project.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )
    (base / "canvas" / "doc_0000.md").write_text("# Draft\n", encoding="utf-8")
    (base / "chat" / "history.json").write_text(
        json.dumps({"current_tab": 0, "tabs": []}),
        encoding="utf-8",
    )
    (base / "logs" / "entries.json").write_text("[]", encoding="utf-8")
    (base / "highlights.json").write_text("{}", encoding="utf-8")


def test_create_and_extract_project_archive_roundtrip(tmp_path: Path):
    project_dir = tmp_path / "project_source"
    _create_project_folder(project_dir)

    archive_path = create_project_archive(project_dir, tmp_path / "bundle")

    assert archive_path.exists()
    assert archive_path.suffix == ".d2c"
    with zipfile.ZipFile(archive_path, "r") as archive:
        names = set(archive.namelist())
    assert "project.json" in names
    assert "canvas/doc_0000.md" in names

    imported_root = extract_project_archive(archive_path, tmp_path / "imported")
    assert (imported_root / "project.json").exists()
    assert (imported_root / "canvas" / "doc_0000.md").exists()


def test_extract_project_archive_supports_single_wrapping_root_folder(tmp_path: Path):
    archive_path = tmp_path / "wrapped.d2c"
    root = "wrapped_project"
    with zipfile.ZipFile(archive_path, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for folder in ("canvas", "knowledge", "rag", "chat", "logs"):
            archive.writestr(f"{root}/{folder}/", b"")
        archive.writestr(f"{root}/project.json", "{}")
        archive.writestr(f"{root}/canvas/doc_0000.md", "# Draft")

    imported_root = extract_project_archive(archive_path, tmp_path / "target")

    assert imported_root.name == root
    assert (imported_root / "project.json").exists()
    assert (imported_root / "canvas" / "doc_0000.md").exists()


def test_extract_project_archive_rejects_non_zip(tmp_path: Path):
    invalid_archive = tmp_path / "broken.d2c"
    invalid_archive.write_text("not a zip", encoding="utf-8")

    with pytest.raises(ProjectArchiveError, match="valid ZIP"):
        extract_project_archive(invalid_archive, tmp_path / "target")


def test_extract_project_archive_rejects_missing_required_dirs(tmp_path: Path):
    archive_path = tmp_path / "missing_dirs.d2c"
    with zipfile.ZipFile(archive_path, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("project.json", "{}")

    with pytest.raises(ProjectArchiveError, match="missing required folders"):
        extract_project_archive(archive_path, tmp_path / "target")


def test_extract_project_archive_rejects_unsafe_paths(tmp_path: Path):
    archive_path = tmp_path / "unsafe.d2c"
    with zipfile.ZipFile(archive_path, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for folder in ("canvas", "knowledge", "rag", "chat", "logs"):
            archive.writestr(f"{folder}/", b"")
        archive.writestr("project.json", "{}")
        archive.writestr("../../escape.txt", "malicious")

    with pytest.raises(ProjectArchiveError, match="unsafe"):
        extract_project_archive(archive_path, tmp_path / "target")


def test_project_manager_exports_archive_with_d2c_suffix(tmp_path: Path, monkeypatch):
    def _fake_save(self, _mw):
        _create_project_folder(self._paths.base)

    monkeypatch.setattr(ProjectSaver, "save", _fake_save)
    manager = ProjectManager()

    ok = manager.export_project_archive(object(), str(tmp_path / "exported_project"))

    assert ok is True
    assert (tmp_path / "exported_project.d2c").exists()


def test_project_manager_imports_archive(tmp_path: Path, monkeypatch):
    source_project = tmp_path / "project_source"
    _create_project_folder(source_project)
    archive_path = create_project_archive(source_project, tmp_path / "project_export.d2c")

    load_calls = {"count": 0}

    def _fake_load(self, _mw):
        load_calls["count"] += 1
        assert self._paths.manifest.exists()

    monkeypatch.setattr(ProjectLoader, "load", _fake_load)
    manager = ProjectManager()

    ok = manager.import_project_archive(object(), str(archive_path))

    assert ok is True
    assert load_calls["count"] == 1


def test_project_manager_import_reports_invalid_archive(tmp_path: Path):
    bad_archive = tmp_path / "bad_project.d2c"
    bad_archive.write_text("broken", encoding="utf-8")
    manager = ProjectManager()

    ok = manager.import_project_archive(object(), str(bad_archive))

    assert ok is False
    assert "Could not import project archive" in manager.last_error
