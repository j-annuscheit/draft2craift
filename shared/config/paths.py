"""Filesystem path helpers."""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

try:
    from platformdirs import user_data_dir as _platform_user_data_dir
except Exception:  # pragma: no cover - optional dependency
    _platform_user_data_dir = None


APP_NAME = "draft2craift"


@dataclass(frozen=True, slots=True)
class AppPaths:
    """Resolved app-specific folders."""

    data_dir: Path
    autosave_dir: Path
    highlights_file: Path
    logs_dir: Path


def _resolve_user_path(raw: str, *, home: Path) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = home / path
    return path.resolve(strict=False)


def app_data_dir(home: Path | None = None) -> Path:
    """Return writable app data directory without relying on CWD."""
    home_dir = home or Path.home()

    env_raw = str(os.getenv("DRAFT2CRAIFT_APP_DATA_DIR", "")).strip()
    if env_raw:
        return _resolve_user_path(env_raw, home=home_dir)

    # Keep deterministic behavior for tests/callers that inject `home`.
    if home is None and _platform_user_data_dir is not None:
        try:
            raw = str(_platform_user_data_dir(APP_NAME, APP_NAME) or "").strip()
        except Exception:
            raw = ""
        if raw:
            return _resolve_user_path(raw, home=home_dir)

    return (home_dir / ".draft2craift").resolve(strict=False)


def default_app_paths(home: Path | None = None) -> AppPaths:
    root = app_data_dir(home=home)
    return AppPaths(
        data_dir=root,
        autosave_dir=root / "autosave",
        highlights_file=root / "highlights.json",
        logs_dir=root / "logs",
    )
