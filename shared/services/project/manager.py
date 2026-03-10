"""Facade for project save/load orchestration."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .project_loader import ProjectLoader, ProjectSchemaError
from .project_paths import ProjectPaths
from .project_saver import ProjectSaver


class ProjectManager:
    """Coordinate project persistence services and expose last error details."""

    def __init__(self, *, allowed_root: str | Path | None = None):
        self._last_error: str = ""
        self._allowed_root = allowed_root

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

    def load_project(self, mw: Any, folder: str) -> bool:
        """Restore all application state from *folder*."""
        self._last_error = ""
        try:
            paths = ProjectPaths(folder, allowed_root=self._allowed_root)
            loader = ProjectLoader(paths=paths)
            loader.load(mw)
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
