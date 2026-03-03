"""
draft2craift — Document Retrieval Augmented File Tool 2 Collaboratively Revised AI Formatted Text
Entry point.
"""
import sys
import os
import multiprocessing

# Make sure sibling imports work regardless of CWD
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

from shell.window import MainWindow
from shell.theme import apply_dark_theme


def main():
    # High-DPI support
    os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")

    app = QApplication(sys.argv)
    app.setApplicationName("draft2craift")
    app.setOrganizationName("draft2craift")
    app.setApplicationVersion("1.0.0")
    app.setStyle("Fusion")          # consistent cross-platform look

    apply_dark_theme(app)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
