#!/usr/bin/env python3
"""Entry point for Test Studio."""
from __future__ import annotations

from pathlib import Path
import sys


def _resolve_run_app():
    if __package__ in {None, ""}:
        project_root = Path(__file__).resolve().parents[1]
        root_text = str(project_root)
        if root_text not in sys.path:
            sys.path.insert(0, root_text)
    from test_studio.app import main as run_app
    return run_app


def main(argv: list[str] | None = None) -> int:
    """Run Test Studio."""
    run_app = _resolve_run_app()
    return run_app(argv)


if __name__ == "__main__":
    raise SystemExit(main())
