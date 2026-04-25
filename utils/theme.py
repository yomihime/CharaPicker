from __future__ import annotations

import logging

from qfluentwidgets import Theme, setTheme

from utils.global_store import get_global_value, set_global_value


SYSTEM_THEME = "system"
LIGHT_THEME = "light"
DARK_THEME = "dark"
SUPPORTED_THEMES = (SYSTEM_THEME, LIGHT_THEME, DARK_THEME)
THEME_NAMES = {
    SYSTEM_THEME: "settings.theme.system",
    LIGHT_THEME: "settings.theme.light",
    DARK_THEME: "settings.theme.dark",
}
LOGGER = logging.getLogger(__name__)


def theme_preference() -> str:
    value = str(get_global_value("appearance/theme", SYSTEM_THEME))
    return value if value in SUPPORTED_THEMES else SYSTEM_THEME


def set_theme_preference(theme: str) -> None:
    normalized_theme = theme if theme in SUPPORTED_THEMES else SYSTEM_THEME
    set_global_value("appearance/theme", normalized_theme)
    LOGGER.info("Theme preference saved; theme=%s", normalized_theme)


def apply_theme_preference(theme: str | None = None) -> None:
    preference = theme if theme in SUPPORTED_THEMES else theme_preference()
    if preference == DARK_THEME:
        setTheme(Theme.DARK)
    elif preference == LIGHT_THEME:
        setTheme(Theme.LIGHT)
    else:
        setTheme(Theme.AUTO)
    LOGGER.info("Theme preference applied; theme=%s", preference)
