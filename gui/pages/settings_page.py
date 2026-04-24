from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QFormLayout, QVBoxLayout, QWidget
from qfluentwidgets import CardWidget, ComboBox, LineEdit, SubtitleLabel, SwitchButton

from utils.i18n import (
    SUPPORTED_LOCALES,
    SYSTEM_LOCALE,
    locale_name,
    locale_preference,
    set_locale_preference,
    t,
)


class SettingsPage(QWidget):
    languageChanged = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("settingsPage")
        self._language_values = [SYSTEM_LOCALE, *SUPPORTED_LOCALES]
        self._loading_language = False

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(18)
        root.addWidget(SubtitleLabel(t("settings.title"), self))

        card = CardWidget(self)
        card.setBorderRadius(8)
        form = QFormLayout(card)
        form.setContentsMargins(20, 18, 20, 20)
        form.setSpacing(12)

        self.model_path = LineEdit(card)
        self.model_path.setPlaceholderText(t("settings.modelPath.placeholder"))

        self.runner_combo = ComboBox(card)
        self.runner_combo.addItems(
            [
                t("settings.runner.local"),
                t("settings.runner.openai"),
                t("settings.runner.manual"),
            ]
        )

        self.use_cache = SwitchButton(card)
        self.use_cache.setChecked(True)

        self.language_combo = ComboBox(card)
        self._load_language_options()

        form.addRow(t("settings.field.modelPath"), self.model_path)
        form.addRow(t("settings.field.runner"), self.runner_combo)
        form.addRow(t("settings.field.cache"), self.use_cache)
        form.addRow(t("settings.field.language"), self.language_combo)
        root.addWidget(card)
        root.addStretch(1)

        self.language_combo.currentIndexChanged.connect(self._change_language)

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
