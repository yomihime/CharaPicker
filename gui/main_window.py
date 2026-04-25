from __future__ import annotations

from PyQt6.QtCore import QSize
from qfluentwidgets import (
    FluentIcon as FIF,
    FluentWindow,
    InfoBar,
    InfoBarPosition,
    NavigationItemPosition,
)

from core.compiler import compile_character_state
from core.extractor import Extractor
from core.generator import render_profile_markdown
from core.models import ProjectConfig
from gui.pages.about_page import AboutPage
from gui.pages.model_page import ModelPage
from gui.pages.output_page import OutputPage
from gui.pages.project_page import ProjectPage
from gui.pages.settings_page import SettingsPage
from utils.i18n import t
from utils.state_manager import save_project_config
from utils.theme import apply_theme_preference


class MainWindow(FluentWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("CharaPicker")
        self.resize(1180, 760)
        self.setMinimumSize(QSize(980, 640))

        self.extractor = Extractor(self)

        self.project_page = ProjectPage(self)
        self.output_page = OutputPage(self)
        self.model_page = ModelPage(self)
        self.about_page = AboutPage(self)
        self.settings_page = SettingsPage(self)

        self._init_navigation()
        self._connect_signals()

    def _init_navigation(self) -> None:
        self.addSubInterface(self.project_page, FIF.HOME, t("app.nav.home"))
        self.addSubInterface(self.output_page, FIF.DOCUMENT, t("app.nav.output"))
        self.addSubInterface(self.model_page, FIF.ROBOT, t("app.nav.model"))
        self.addSubInterface(
            self.about_page,
            FIF.INFO,
            t("app.nav.about"),
            NavigationItemPosition.BOTTOM,
        )
        self.addSubInterface(
            self.settings_page,
            FIF.SETTING,
            t("app.nav.settings"),
            NavigationItemPosition.BOTTOM,
        )
        self.navigationInterface.setExpandWidth(168)

    def _connect_signals(self) -> None:
        self.project_page.previewRequested.connect(self.run_preview)
        self.project_page.configSaved.connect(self.save_config)
        self.extractor.insightGenerated.connect(self.project_page.append_event)
        self.extractor.progressChanged.connect(self.project_page.set_progress)
        self.settings_page.languageChanged.connect(self.show_language_changed)
        self.settings_page.themeChanged.connect(self.apply_theme_changed)

    def save_config(self, config: ProjectConfig) -> None:
        path = save_project_config(config)
        InfoBar.success(
            title=t("app.config.saved.title"),
            content=t("app.config.saved.content", path=path),
            parent=self,
            position=InfoBarPosition.TOP_RIGHT,
            duration=3000,
        )

    def run_preview(self, config: ProjectConfig) -> None:
        self.switchTo(self.project_page)
        self.project_page.clear_events()
        self.extractor.run_preview(config)

        first_character = config.target_characters[0] if config.target_characters else t(
            "app.preview.defaultCharacter"
        )
        state = compile_character_state(first_character)
        self.output_page.set_markdown(render_profile_markdown(state))

        InfoBar.info(
            title=t("app.preview.done.title"),
            content=t("app.preview.done.content"),
            parent=self,
            position=InfoBarPosition.TOP_RIGHT,
            duration=3500,
        )

    def show_language_changed(self, _locale: str) -> None:
        InfoBar.info(
            title=t("settings.language.changed.title"),
            content=t("settings.language.changed.content"),
            parent=self,
            position=InfoBarPosition.TOP_RIGHT,
            duration=4500,
        )

    def apply_theme_changed(self, theme: str) -> None:
        apply_theme_preference(theme)
        self.project_page.apply_theme_colors()
        InfoBar.info(
            title=t("settings.theme.changed.title"),
            content=t("settings.theme.changed.content"),
            parent=self,
            position=InfoBarPosition.TOP_RIGHT,
            duration=3000,
        )
