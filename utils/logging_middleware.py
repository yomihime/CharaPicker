from __future__ import annotations

import logging
import sys
import threading
from datetime import datetime
from pathlib import Path
from types import TracebackType

from utils.paths import LOGS_ROOT


LOG_FILE_TIME_FORMAT = "%Y%m%d_%H%M%S_%f"
MAX_LOG_FILE_COUNT = 20
LOG_RECORD_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
LOG_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def install_global_logging(logs_root: Path = LOGS_ROOT) -> Path:
    logs_root.mkdir(parents=True, exist_ok=True)
    log_file = logs_root / f"{datetime.now().strftime(LOG_FILE_TIME_FORMAT)}.log"

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
        handler.close()

    formatter = logging.Formatter(LOG_RECORD_FORMAT, datefmt=LOG_TIME_FORMAT)

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.INFO)
    stream_handler.setFormatter(formatter)
    root_logger.addHandler(stream_handler)

    _install_exception_hooks()
    _prune_old_log_files(logs_root, keep_count=MAX_LOG_FILE_COUNT)
    logging.getLogger(__name__).info("Global logging initialized: %s", log_file)
    return log_file


def _prune_old_log_files(logs_root: Path, keep_count: int) -> None:
    log_files = sorted(
        (path for path in logs_root.glob("*.log") if path.is_file()),
        key=lambda path: (path.stat().st_mtime, path.name),
    )
    stale_files = log_files[: max(0, len(log_files) - keep_count)]
    for stale_file in stale_files:
        try:
            stale_file.unlink()
        except OSError:
            logging.getLogger(__name__).warning(
                "Failed to delete old log file: %s",
                stale_file,
                exc_info=True,
            )


def _install_exception_hooks() -> None:
    def handle_exception(
        exception_type: type[BaseException],
        exception: BaseException,
        traceback: TracebackType | None,
    ) -> None:
        logging.getLogger("exception").critical(
            "Uncaught exception",
            exc_info=(exception_type, exception, traceback),
        )
        sys.__excepthook__(exception_type, exception, traceback)

    def handle_thread_exception(args: threading.ExceptHookArgs) -> None:
        logging.getLogger("exception.thread").critical(
            "Uncaught thread exception",
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )
        threading.__excepthook__(args)

    sys.excepthook = handle_exception
    threading.excepthook = handle_thread_exception
