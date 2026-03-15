"""Typed runtime ports for wiring ChatDock integrations."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(slots=True)
class ChatDockContextPorts:
    """Context providers consumed by ChatDock."""

    build_context: Callable[[], dict]
    canvas_selection_text: Callable[[], str]


@dataclass(slots=True)
class ChatDockActionPorts:
    """Cross-component actions triggered from ChatDock."""

    apply_selection_rewrite: Callable[[str, str, tuple[int, int] | None], tuple[bool, str]]
    open_fact_result: Callable[[str, str], tuple[bool, str]]
    generate_glossary: Callable[[dict, Callable[[bool, str], None]], tuple[bool, str]]
    generate_mindmap: Callable[
        [dict, str, str, Callable[[bool, str], None]],
        tuple[bool, str],
    ]

