from __future__ import annotations

import sys

from PyQt6.QtWidgets import QApplication

from gui.splash_screen import StartupController
from utils.theme import apply_theme_preference


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("CharaPicker")
    app.setOrganizationName("CharaPicker")
    app.setQuitOnLastWindowClosed(False)

    apply_theme_preference()

    startup = StartupController()
    app.startup_controller = startup
    startup.start()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
