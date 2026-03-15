"""Qt application bootstrap for Writing Studio."""
from __future__ import annotations

import faulthandler
import os
import sys
from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from shared.config.setting_keys import ThemeSettingsKeys
from studio.theme import apply_theme
from studio.window import MainWindow


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


def create_application(argv: list[str] | None = None) -> QApplication:
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
    settings = getattr(app, "_draft2craift_settings", None)
    if not isinstance(settings, QSettings):
        raise RuntimeError("Application settings are not initialized.")
    window = MainWindow(app_settings=settings)
    window.show()
    return app.exec()
