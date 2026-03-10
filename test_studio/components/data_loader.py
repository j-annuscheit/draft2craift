"""Run discovery for Test Studio."""
from __future__ import annotations

import pathlib

from test_studio.components.run_parsers import load_run_entry
from test_studio.models import RunEntry


def discover_runs(root_dir: pathlib.Path) -> list[RunEntry]:
    if not root_dir.exists():
        return []

    runs: list[RunEntry] = []
    for path in sorted(root_dir.rglob("*.summary.json")):
        run = load_run_entry(path)
        if run is not None:
            runs.append(run)

    runs.sort(key=lambda item: (item.timestamp, item.run_name), reverse=True)
    return runs
