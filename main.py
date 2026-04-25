from __future__ import annotations

import sys

from PyQt6.QtCore import QtMsgType, qInstallMessageHandler
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QApplication


DEFAULT_FONT_POINT_SIZE = 10
_SUPPRESSED_QT_MESSAGE_PREFIXES = (
    "QFont::setPointSize: Point size <= 0",
)


def main() -> int:
    _install_qt_message_filter()
    app = QApplication(sys.argv)
    app.setApplicationName("CharaPicker")
    app.setOrganizationName("CharaPicker")
    app.setQuitOnLastWindowClosed(False)
    _ensure_valid_application_font(app)

    from gui.splash_screen import StartupController
    from utils.theme import apply_theme_preference

    apply_theme_preference()

    startup = StartupController()
    app.startup_controller = startup
    startup.start()

    return app.exec()


def _ensure_valid_application_font(app: QApplication) -> None:
    font = QFont(app.font())
    if font.pointSize() <= 0:
        font.setPointSize(DEFAULT_FONT_POINT_SIZE)
    app.setFont(font)


def _install_qt_message_filter() -> None:
    qInstallMessageHandler(_qt_message_handler)


def _qt_message_handler(message_type: QtMsgType, _context, message: str) -> None:
    if any(message.startswith(prefix) for prefix in _SUPPRESSED_QT_MESSAGE_PREFIXES):
        return

    if message_type == QtMsgType.QtDebugMsg:
        stream = sys.stdout
    else:
        stream = sys.stderr
    stream.write(f"{message}\n")


if __name__ == "__main__":
    raise SystemExit(main())
