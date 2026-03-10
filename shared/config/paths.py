"""Filesystem path helpers."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


APP_NAME = "draft2craift"


@dataclass(frozen=True, slots=True)
class AppPaths:
    """Resolved app-specific folders."""

    data_dir: Path
    autosave_dir: Path
    highlights_file: Path
    logs_dir: Path


def default_app_paths(home: Path | None = None) -> AppPaths:
    root = (home or Path.home()) / ".local" / "share" / APP_NAME
    return AppPaths(
        data_dir=root,
        autosave_dir=root / "autosave",
        highlights_file=root / "highlights.json",
        logs_dir=root / "logs",
    )
