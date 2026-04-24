from __future__ import annotations

import sys

from PyQt6.QtWidgets import QApplication
from qfluentwidgets import setTheme, Theme

from gui.splash_screen import StartupController


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("CharaPicker")
    app.setOrganizationName("CharaPicker")
    app.setQuitOnLastWindowClosed(False)

    setTheme(Theme.AUTO)

    startup = StartupController()
    app.startup_controller = startup
    startup.start()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
