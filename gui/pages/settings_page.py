from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QFormLayout, QVBoxLayout, QWidget
from qfluentwidgets import CardWidget, ComboBox, SubtitleLabel

from utils.i18n import (
    SUPPORTED_LOCALES,
    SYSTEM_LOCALE,
    locale_name,
    locale_preference,
    set_locale_preference,
    t,
)
from utils.theme import (
    SUPPORTED_THEMES,
    THEME_NAMES,
    set_theme_preference,
    theme_preference,
)


class SettingsPage(QWidget):
    languageChanged = pyqtSignal(str)
    themeChanged = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("settingsPage")
        self._language_values = [SYSTEM_LOCALE, *SUPPORTED_LOCALES]
        self._loading_language = False
        self._theme_values = list(SUPPORTED_THEMES)
        self._loading_theme = False

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(18)
        root.addWidget(SubtitleLabel(t("settings.title"), self))

        card = CardWidget(self)
        card.setBorderRadius(8)
        form = QFormLayout(card)
        form.setContentsMargins(20, 18, 20, 20)
        form.setSpacing(12)

        self.language_combo = ComboBox(card)
        self._load_language_options()

        self.theme_combo = ComboBox(card)
        self._load_theme_options()

        form.addRow(t("settings.field.language"), self.language_combo)
        form.addRow(t("settings.field.theme"), self.theme_combo)
        root.addWidget(card)
        root.addStretch(1)

        self.language_combo.currentIndexChanged.connect(self._change_language)
        self.theme_combo.currentIndexChanged.connect(self._change_theme)

    def _load_language_options(self) -> None:
        self._loading_language = True
        self.language_combo.clear()
        for locale in self._language_values:
            self.language_combo.addItem(locale_name(locale))

        preference = locale_preference()
        index = self._language_values.index(preference) if preference in self._language_values else 0
        self.language_combo.setCurrentIndex(index)
        self._loading_language = False

    def _change_language(self) -> None:
        if self._loading_language:
            return
        index = self.language_combo.currentIndex()
        if not 0 <= index < len(self._language_values):
            return
        locale = self._language_values[index]
        set_locale_preference(locale)
        self.languageChanged.emit(locale)

    def _load_theme_options(self) -> None:
        self._loading_theme = True
        self.theme_combo.clear()
        for theme in self._theme_values:
            self.theme_combo.addItem(t(THEME_NAMES[theme]))

        preference = theme_preference()
        index = self._theme_values.index(preference) if preference in self._theme_values else 0
        self.theme_combo.setCurrentIndex(index)
        self._loading_theme = False

    def _change_theme(self) -> None:
        if self._loading_theme:
            return
        index = self.theme_combo.currentIndex()
        if not 0 <= index < len(self._theme_values):
            return
        theme = self._theme_values[index]
        set_theme_preference(theme)
        self.themeChanged.emit(theme)
