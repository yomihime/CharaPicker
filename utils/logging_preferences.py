from __future__ import annotations

import logging

from utils.global_store import get_global_value, set_global_value


LOG_LEVEL_KEY = "logging/level"
DEBUG_LOG_LEVEL = "DEBUG"
INFO_LOG_LEVEL = "INFO"
WARNING_LOG_LEVEL = "WARNING"
ERROR_LOG_LEVEL = "ERROR"
CRITICAL_LOG_LEVEL = "CRITICAL"
DEFAULT_LOG_LEVEL = INFO_LOG_LEVEL
SUPPORTED_LOG_LEVELS = (
    DEBUG_LOG_LEVEL,
    INFO_LOG_LEVEL,
    WARNING_LOG_LEVEL,
    ERROR_LOG_LEVEL,
    CRITICAL_LOG_LEVEL,
)
LOG_LEVEL_NAMES = {
    DEBUG_LOG_LEVEL: "settings.logLevel.debug",
    INFO_LOG_LEVEL: "settings.logLevel.info",
    WARNING_LOG_LEVEL: "settings.logLevel.warning",
    ERROR_LOG_LEVEL: "settings.logLevel.error",
    CRITICAL_LOG_LEVEL: "settings.logLevel.critical",
}
LOG_LEVEL_VALUES = {
    DEBUG_LOG_LEVEL: logging.DEBUG,
    INFO_LOG_LEVEL: logging.INFO,
    WARNING_LOG_LEVEL: logging.WARNING,
    ERROR_LOG_LEVEL: logging.ERROR,
    CRITICAL_LOG_LEVEL: logging.CRITICAL,
}


def normalize_log_level(level: str) -> str:
    normalized_level = level.strip().upper()
    return normalized_level if normalized_level in SUPPORTED_LOG_LEVELS else DEFAULT_LOG_LEVEL


def log_level_preference() -> str:
    return normalize_log_level(str(get_global_value(LOG_LEVEL_KEY, DEFAULT_LOG_LEVEL)))


def set_log_level_preference(level: str) -> None:
    set_global_value(LOG_LEVEL_KEY, normalize_log_level(level))


def logging_level_value(level: str | None = None) -> int:
    return LOG_LEVEL_VALUES[normalize_log_level(level or log_level_preference())]
