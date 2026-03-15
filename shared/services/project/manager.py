"""Facade for project save/load orchestration."""
from __future__ import annotations

from pathlib import Path
import shutil
import tempfile
from typing import Any

from shared.config.paths import app_data_dir

from .project_loader import ProjectLoader, ProjectSchemaError
from .project_archive import create_project_archive, extract_project_archive
from .project_paths import ProjectPaths
from .project_saver import ProjectSaver


class ProjectManager:
    """Coordinate project persistence services and expose last error details."""

    def __init__(self, *, allowed_root: str | Path | None = None):
        self._last_error: str = ""
        self._allowed_root = allowed_root
        self._active_import_workspace: Path | None = None

    @property
    def last_error(self) -> str:
        return self._last_error

    def save_project(
        self,
        mw: Any,
        folder: str,
        *,
        include_st_embeddings: bool = True,
    ) -> bool:
        """Write all application state into *folder*."""
        self._last_error = ""
        try:
            paths = ProjectPaths(folder, allowed_root=self._allowed_root)
            saver = ProjectSaver(paths=paths, include_st_embeddings=include_st_embeddings)
            saver.save(mw)
            return True
        except Exception as exc:
            self._last_error = f"Could not save project:\n{exc}"
            return False

    def export_project_archive(
        self,
        mw: Any,
        archive_path: str,
        *,
        include_st_embeddings: bool = True,
    ) -> bool:
        """Serialize app state and export it as ``.d2c`` archive."""
        self._last_error = ""
        try:
            archive_target = self._resolve_user_path(
                archive_path,
                kind="archive",
            )
            with tempfile.TemporaryDirectory(prefix="draft2craift_export_") as tmp_dir:
                project_folder = Path(tmp_dir).resolve(strict=False)
                saver = ProjectSaver(
                    paths=ProjectPaths(project_folder),
                    include_st_embeddings=include_st_embeddings,
                )
                saver.save(mw)
                create_project_archive(project_folder, archive_target)
            return True
        except Exception as exc:
            self._last_error = f"Could not export project archive:\n{exc}"
            return False

    def load_project(self, mw: Any, folder: str) -> bool:
        """Restore all application state from *folder*."""
        self._last_error = ""
        try:
            paths = ProjectPaths(folder, allowed_root=self._allowed_root)
            loader = ProjectLoader(paths=paths)
            loader.load(mw)
            self._cleanup_active_import_workspace()
            return True
        except ProjectSchemaError as exc:
            self._last_error = (
                "Could not load project:\n"
                f"Invalid project.json schema: {exc}"
            )
            return False
        except Exception as exc:
            self._last_error = f"Could not load project:\n{exc}"
            return False

    def import_project_archive(self, mw: Any, archive_path: str) -> bool:
        """Extract ``.d2c`` archive and restore app state from extracted project."""
        self._last_error = ""
        workspace: Path | None = None
        load_started = False
        previous_workspace = self._active_import_workspace

        try:
            source_archive = self._resolve_user_path(
                archive_path,
                kind="archive",
                require_existing=True,
            )
            if not source_archive.is_file():
                raise ValueError(f"Archive path is not a file: {source_archive}")

            workspace = self._create_import_workspace()
            project_root = extract_project_archive(source_archive, workspace)

            load_started = True
            loader = ProjectLoader(
                paths=ProjectPaths(
                    project_root,
                    allowed_root=workspace,
                )
            )
            loader.load(mw)
        except ProjectSchemaError as exc:
            self._last_error = (
                "Could not import project archive:\n"
                f"Invalid project.json schema: {exc}"
            )
            if load_started and workspace is not None:
                self._active_import_workspace = workspace
            elif workspace is not None:
                shutil.rmtree(workspace, ignore_errors=True)
            return False
        except Exception as exc:
            self._last_error = f"Could not import project archive:\n{exc}"
            if load_started and workspace is not None:
                self._active_import_workspace = workspace
            elif workspace is not None:
                shutil.rmtree(workspace, ignore_errors=True)
            return False

        self._active_import_workspace = workspace
        if (
            previous_workspace is not None
            and workspace is not None
            and previous_workspace != workspace
        ):
            shutil.rmtree(previous_workspace, ignore_errors=True)
        return True

    def _create_import_workspace(self) -> Path:
        if self._allowed_root is None:
            base_dir = None
        else:
            root = Path(self._allowed_root).expanduser().resolve(strict=False)
            base_dir = root / ".d2c_imports"
            base_dir.mkdir(parents=True, exist_ok=True)
        temp_path = tempfile.mkdtemp(prefix="draft2craift_import_", dir=base_dir)
        return Path(temp_path).resolve(strict=False)

    def _resolve_user_path(
        self,
        path: str | Path,
        *,
        kind: str,
        require_existing: bool = False,
    ) -> Path:
        path_text = str(path or "").strip()
        if not path_text:
            raise ValueError(f"{kind.capitalize()} path is empty.")

        raw = Path(path_text).expanduser()
        allowed_root = (
            Path(self._allowed_root).expanduser().resolve(strict=False)
            if self._allowed_root is not None
            else None
        )
        if raw.is_absolute():
            resolved = raw.resolve(strict=False)
        else:
            anchor = allowed_root or app_data_dir()
            resolved = (anchor / raw).resolve(strict=False)

        if allowed_root is not None and not _is_relative_to(resolved, allowed_root):
            raise ValueError(
                f"{kind.capitalize()} path escapes allowed root: {resolved} not in {allowed_root}"
            )
        if require_existing and not resolved.exists():
            raise FileNotFoundError(f"{kind.capitalize()} path does not exist: {resolved}")
        return resolved

    def _cleanup_active_import_workspace(self) -> None:
        workspace = self._active_import_workspace
        if workspace is None:
            return
        shutil.rmtree(workspace, ignore_errors=True)
        self._active_import_workspace = None


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
