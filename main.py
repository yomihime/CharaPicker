from __future__ import annotations

import logging
import sys

from PyQt6.QtCore import QtMsgType, qInstallMessageHandler
from PyQt6.QtGui import QFont, QIcon
from PyQt6.QtWidgets import QApplication, QMessageBox


DEFAULT_FONT_POINT_SIZE = 10
_SUPPRESSED_QT_MESSAGE_PREFIXES = (
    "QFont::setPointSize: Point size <= 0",
)
LOGGER = logging.getLogger(__name__)


def main() -> int:
    from utils.app_metadata import APP_NAME, APP_ORGANIZATION_NAME
    from utils.logging_middleware import install_global_logging

    log_file = install_global_logging()
    LOGGER.info("Application startup begins; log_file=%s", log_file)
    _install_qt_message_filter()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_ORGANIZATION_NAME)
    app.setQuitOnLastWindowClosed(False)
    _ensure_valid_application_font(app)
    _apply_application_icon(app)

    from gui.splash_screen import StartupController
    if not _apply_theme_with_recovery():
        LOGGER.error("Application startup stopped because global configuration is unavailable")
        return 1

    startup = StartupController()
    app.startup_controller = startup
    startup.start()

    exit_code = app.exec()
    LOGGER.info("Application exited; exit_code=%s", exit_code)
    return exit_code


def _ensure_valid_application_font(app: QApplication) -> None:
    font = QFont(app.font())
    if font.pointSize() <= 0:
        font.setPointSize(DEFAULT_FONT_POINT_SIZE)
    app.setFont(font)


def _apply_application_icon(app: QApplication) -> None:
    from res import APP_ICON_PATH

    icon = QIcon(str(APP_ICON_PATH))
    if not icon.isNull():
        app.setWindowIcon(icon)


def _install_qt_message_filter() -> None:
    qInstallMessageHandler(_qt_message_handler)


def _apply_theme_with_recovery() -> bool:
    from utils.atomic_io import DataCorruptionError
    from utils.global_store import restore_global_config_backup
    from utils.theme import apply_theme_preference

    try:
        apply_theme_preference()
        return True
    except DataCorruptionError as error:
        corruption = error
        LOGGER.error(
            "Global configuration is corrupt; path=%s backup_available=%s backup_path=%s",
            error.path,
            error.backup_available,
            error.backup_path,
        )

    if not corruption.backup_available:
        _show_global_config_recovery_error(corruption, restore_failed=False)
        return False
    if not _prompt_global_config_recovery(corruption):
        return False

    try:
        restore_global_config_backup()
        apply_theme_preference()
    except (DataCorruptionError, OSError, ValueError):
        LOGGER.error("Global configuration recovery failed", exc_info=True)
        _show_global_config_recovery_error(corruption, restore_failed=True)
        return False
    LOGGER.info("Global configuration restored from backup; path=%s", corruption.path)
    return True


def _prompt_global_config_recovery(error) -> bool:
    from utils.i18n import t_system

    dialog = QMessageBox()
    dialog.setIcon(QMessageBox.Icon.Warning)
    dialog.setWindowTitle(t_system("recovery.global.title"))
    dialog.setText(
        t_system(
            "recovery.global.backupAvailable",
            path=error.path,
            backup_path=error.backup_path,
        )
    )
    restore_button = dialog.addButton(
        t_system("recovery.action.restore"),
        QMessageBox.ButtonRole.AcceptRole,
    )
    cancel_button = dialog.addButton(
        t_system("recovery.action.exit"),
        QMessageBox.ButtonRole.RejectRole,
    )
    dialog.setDefaultButton(cancel_button)
    dialog.exec()
    return dialog.clickedButton() is restore_button


def _show_global_config_recovery_error(error, *, restore_failed: bool) -> None:
    from utils.i18n import t_system

    key = "recovery.global.restoreFailed" if restore_failed else "recovery.global.noBackup"
    QMessageBox.critical(
        None,
        t_system("recovery.global.title"),
        t_system(key, path=error.path, backup_path=error.backup_path),
    )


def _qt_message_handler(message_type: QtMsgType, _context, message: str) -> None:
    if any(message.startswith(prefix) for prefix in _SUPPRESSED_QT_MESSAGE_PREFIXES):
        return

    from utils.logging_middleware import log_qt_message

    log_qt_message(message_type, message)


def _entrypoint() -> int:
    if "--health-check" in sys.argv[1:]:
        from utils.runtime_health import run_runtime_health_check

        return run_runtime_health_check()
    return main()


if __name__ == "__main__":
    raise SystemExit(_entrypoint())
