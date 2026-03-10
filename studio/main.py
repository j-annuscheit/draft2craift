"""CLI entry point for Writing Studio."""
from __future__ import annotations

import multiprocessing
from pathlib import Path
import sys


def _resolve_run():
    if __package__ in {None, ""}:
        project_root = Path(__file__).resolve().parents[1]
        root_text = str(project_root)
        if root_text not in sys.path:
            sys.path.insert(0, root_text)
    from studio.app import run
    return run


def main() -> int:
    multiprocessing.freeze_support()
    run = _resolve_run()
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
