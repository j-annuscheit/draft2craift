"""
draft2craift — Document Retrieval Augmented File Tool 2 Collaboratively Revised AI Formatted Text
Entry point.
"""
import sys
import os
import multiprocessing
import faulthandler
from pathlib import Path

# Make sure sibling imports work regardless of CWD
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QSettings

from shell.window import MainWindow
from shell.theme import apply_theme


def _enable_fault_logging():
    """
    Persist Python fault traces (incl. SIGSEGV context) to disk.
    """
    try:
        target = Path.home() / ".draft2craift" / "logs" / "faulthandler.log"
        target.parent.mkdir(parents=True, exist_ok=True)
        fh = target.open("a", encoding="utf-8", errors="replace")
        faulthandler.enable(file=fh, all_threads=True)
        # Keep file handle alive for process lifetime.
        globals()["_FAULT_LOG_HANDLE"] = fh
    except Exception:
        try:
            faulthandler.enable(all_threads=True)
        except Exception:
            pass


def main():
    # High-DPI support
    os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")
    _enable_fault_logging()

    app = QApplication(sys.argv)
    app.setApplicationName("draft2craift")
    app.setOrganizationName("draft2craift")
    app.setApplicationVersion("1.0.0")
    app.setStyle("Fusion")          # consistent cross-platform look

    settings = QSettings("draft2craift", "draft2craift")
    theme_id = settings.value("ui/theme", "dark")
    apply_theme(app, theme_id)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
