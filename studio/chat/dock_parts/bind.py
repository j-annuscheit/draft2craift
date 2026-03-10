"""Bind split method implementations to ChatDock."""
from __future__ import annotations

from . import callbacks, context_helpers, public_api, send_actions, ui_setup

_METHOD_MODULES = (
    public_api,
    ui_setup,
    context_helpers,
    send_actions,
    callbacks,
)

def bind_chat_dock(cls):
    for module in _METHOD_MODULES:
        for name in getattr(module, "__all__", ()):
            setattr(cls, name, getattr(module, name))
