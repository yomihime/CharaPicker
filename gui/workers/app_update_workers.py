from __future__ import annotations

import logging

from PyQt6.QtCore import QObject, pyqtSignal

from utils.app_update import (
    AppUpdateError,
    UpdateDownloadCancelled,
    UpdatePackageUnavailableError,
    UpdateRelease,
    check_for_update,
    prepare_update,
)


LOGGER = logging.getLogger(__name__)


class UpdateCheckWorker(QObject):
    succeeded = pyqtSignal(object)
    failed = pyqtSignal(str)
    packageUnavailable = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, *, include_prereleases: bool) -> None:
        super().__init__()
        self.include_prereleases = include_prereleases

    def run(self) -> None:
        try:
            release = check_for_update(include_prereleases=self.include_prereleases)
        except UpdatePackageUnavailableError as exc:
            LOGGER.warning(
                "A newer release has no compatible automatic update package; tag=%s",
                exc.tag_name,
            )
            self.packageUnavailable.emit(exc.tag_name)
        except AppUpdateError as exc:
            LOGGER.warning("Application update check failed; error=%s", exc)
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            LOGGER.error("Application update check failed unexpectedly", exc_info=True)
            self.failed.emit(str(exc))
        else:
            self.succeeded.emit(release)
        finally:
            self.finished.emit()


class UpdateDownloadWorker(QObject):
    progressChanged = pyqtSignal(int, str)
    succeeded = pyqtSignal(object)
    failed = pyqtSignal(str)
    cancelled = pyqtSignal()
    finished = pyqtSignal()

    def __init__(self, release: UpdateRelease) -> None:
        super().__init__()
        self.release = release
        self._cancel_requested = False

    def cancel(self) -> None:
        self._cancel_requested = True

    def run(self) -> None:
        try:
            prepared = prepare_update(
                self.release,
                progress=lambda value, step: self.progressChanged.emit(value, step),
                cancelled=lambda: self._cancel_requested,
            )
        except UpdateDownloadCancelled:
            LOGGER.info("Application update download cancelled")
            self.cancelled.emit()
        except AppUpdateError as exc:
            LOGGER.warning("Application update download failed; error=%s", exc)
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            LOGGER.error("Application update download failed unexpectedly", exc_info=True)
            self.failed.emit(str(exc))
        else:
            self.succeeded.emit(prepared)
        finally:
            self.finished.emit()
