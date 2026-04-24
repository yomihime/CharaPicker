from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QLocale, QSettings


I18N_ROOT = Path(__file__).resolve().parents[1] / "i18n"
DEFAULT_LOCALE = "zh_CN"
SYSTEM_LOCALE = "system"
SUPPORTED_LOCALES = ("zh_CN", "zh_TW", "en_US", "ja_JP")
LOCALE_NAMES = {
    SYSTEM_LOCALE: "System",
    "zh_CN": "简体中文",
    "zh_TW": "繁體中文",
    "en_US": "English",
    "ja_JP": "日本語",
}


def current_locale() -> str:
    env_locale = os.getenv("CHARAPICKER_LOCALE")
    if env_locale:
        return normalize_locale(env_locale)

    preference = locale_preference()
    if preference == SYSTEM_LOCALE:
        return system_locale()
    return normalize_locale(preference)


def locale_preference() -> str:
    value = QSettings().value("language/locale", SYSTEM_LOCALE, str)
    if value == SYSTEM_LOCALE:
        return SYSTEM_LOCALE
    return normalize_locale(value)


def set_locale_preference(locale: str) -> None:
    QSettings().setValue("language/locale", locale if locale == SYSTEM_LOCALE else normalize_locale(locale))


def system_locale() -> str:
    return normalize_locale(QLocale.system().name())


def normalize_locale(locale: str) -> str:
    normalized = locale.replace("-", "_")
    if normalized in SUPPORTED_LOCALES:
        return normalized
    language = normalized.split("_", maxsplit=1)[0].lower()
    if language == "zh":
        return "zh_TW" if normalized.lower() in {"zh_tw", "zh_hk", "zh_mo"} else "zh_CN"
    if language == "ja":
        return "ja_JP"
    if language == "en":
        return "en_US"
    return DEFAULT_LOCALE


def locale_name(locale: str) -> str:
    if locale == SYSTEM_LOCALE:
        return f"{LOCALE_NAMES[SYSTEM_LOCALE]} ({LOCALE_NAMES[system_locale()]})"
    return LOCALE_NAMES.get(normalize_locale(locale), LOCALE_NAMES[DEFAULT_LOCALE])


@lru_cache(maxsize=8)
def load_messages(locale: str) -> dict[str, str]:
    path = I18N_ROOT / f"{locale}.json"
    if not path.exists():
        path = I18N_ROOT / f"{DEFAULT_LOCALE}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {str(key): str(value) for key, value in data.items()}


def t(key: str, **kwargs: Any) -> str:
    messages = load_messages(current_locale())
    fallback = load_messages(DEFAULT_LOCALE)
    text = messages.get(key, fallback.get(key, key))
    if kwargs:
        return text.format(**kwargs)
    return text
