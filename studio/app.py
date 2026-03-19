"""Qt application bootstrap for Writing Studio."""
from __future__ import annotations

import ctypes
import faulthandler
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from shared.config.setting_keys import ThemeSettingsKeys

if TYPE_CHECKING:
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication


def _prefer_system_libstdcpp_for_torch_extensions() -> None:
    """Preload a system libstdc++ that provides newer CXXABI symbols.

    This avoids runtime import failures for CUDA extensions (for example
    ``causal_conv1d_cuda`` used by Mamba models) when Qt loads an older
    conda-provided ``libstdc++.so.6`` first.
    """
    if not sys.platform.startswith("linux"):
        return
    if str(os.environ.get("D2C_DISABLE_SYSTEM_LIBSTDCXX", "")).strip().casefold() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return

    candidates = (
        "/usr/lib/x86_64-linux-gnu/libstdc++.so.6",
        "/lib/x86_64-linux-gnu/libstdc++.so.6",
    )
    mode = int(getattr(os, "RTLD_GLOBAL", 0) | getattr(os, "RTLD_NOW", 0))
    for path in candidates:
        if not os.path.exists(path):
            continue
        try:
            lib = ctypes.CDLL(path, mode=mode)
            getattr(lib, "__cxa_call_terminate")
        except Exception:
            continue
        os.environ.setdefault("D2C_PRELOADED_LIBSTDCXX", path)
        return


def _enable_fault_logging() -> None:
    """Persist Python fault traces (including SIGSEGV context) to disk."""
    try:
        target = Path.home() / ".draft2craift" / "logs" / "faulthandler.log"
        target.parent.mkdir(parents=True, exist_ok=True)
        handle = target.open("a", encoding="utf-8", errors="replace")
        faulthandler.enable(file=handle, all_threads=True)
        globals()["_FAULT_LOG_HANDLE"] = handle
    except Exception:
        try:
            faulthandler.enable(all_threads=True)
        except Exception:
            pass


def create_application(argv: list[str] | None = None) -> "QApplication":
    _prefer_system_libstdcpp_for_torch_extensions()
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication
    from studio.theme import apply_theme

    os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")
    _enable_fault_logging()
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("draft2craift")
    app.setOrganizationName("draft2craift")
    app.setApplicationVersion("1.0.0")
    app.setStyle("Fusion")
    settings = QSettings("draft2craift", "draft2craift")
    setattr(app, "_draft2craift_settings", settings)
    apply_theme(app, settings.value(ThemeSettingsKeys.UI_THEME, "dark"))
    return app


def run(argv: list[str] | None = None) -> int:
    app = create_application(argv)
    from PySide6.QtCore import QSettings
    from studio.window import MainWindow

    settings = getattr(app, "_draft2craift_settings", None)
    if not isinstance(settings, QSettings):
        raise RuntimeError("Application settings are not initialized.")
    window = MainWindow(app_settings=settings)
    window.show()
    return app.exec()
