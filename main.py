from __future__ import annotations

import sys

from PyQt6.QtWidgets import QApplication
from qfluentwidgets import setTheme, Theme

from gui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("CharaPicker")
    app.setOrganizationName("CharaPicker")

    setTheme(Theme.AUTO)

    window = MainWindow()
    window.show()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
