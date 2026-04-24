from __future__ import annotations

from PyQt6.QtCore import QSettings
from qfluentwidgets import Theme, setTheme


SYSTEM_THEME = "system"
LIGHT_THEME = "light"
DARK_THEME = "dark"
SUPPORTED_THEMES = (SYSTEM_THEME, LIGHT_THEME, DARK_THEME)
THEME_NAMES = {
    SYSTEM_THEME: "settings.theme.system",
    LIGHT_THEME: "settings.theme.light",
    DARK_THEME: "settings.theme.dark",
}


def theme_preference() -> str:
    value = QSettings().value("appearance/theme", SYSTEM_THEME, str)
    return value if value in SUPPORTED_THEMES else SYSTEM_THEME


def set_theme_preference(theme: str) -> None:
    QSettings().setValue("appearance/theme", theme if theme in SUPPORTED_THEMES else SYSTEM_THEME)


def apply_theme_preference(theme: str | None = None) -> None:
    preference = theme if theme in SUPPORTED_THEMES else theme_preference()
    if preference == DARK_THEME:
        setTheme(Theme.DARK)
    elif preference == LIGHT_THEME:
        setTheme(Theme.LIGHT)
    else:
        setTheme(Theme.AUTO)
