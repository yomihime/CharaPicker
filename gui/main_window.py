from __future__ import annotations

from PyQt6.QtCore import QSize
from PyQt6.QtWidgets import QWidget
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
from gui.pages.insights_page import InsightsPage
from gui.pages.output_page import OutputPage
from gui.pages.project_page import ProjectPage
from gui.pages.settings_page import SettingsPage
from utils.state_manager import save_project_config


class MainWindow(FluentWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("CharaPicker")
        self.resize(1180, 760)
        self.setMinimumSize(QSize(980, 640))

        self.extractor = Extractor(self)

        self.project_page = ProjectPage(self)
        self.insights_page = InsightsPage(self)
        self.output_page = OutputPage(self)
        self.settings_page = SettingsPage(self)

        self._init_navigation()
        self._connect_signals()

    def _init_navigation(self) -> None:
        self.addSubInterface(self.project_page, FIF.FOLDER, "项目")
        self.addSubInterface(self.insights_page, FIF.ROBOT, "洞察流")
        self.addSubInterface(self.output_page, FIF.DOCUMENT, "输出")
        self.addSubInterface(
            self.settings_page,
            FIF.SETTING,
            "设置",
            NavigationItemPosition.BOTTOM,
        )
        self.navigationInterface.setExpandWidth(168)

    def _connect_signals(self) -> None:
        self.project_page.previewRequested.connect(self.run_preview)
        self.project_page.configSaved.connect(self.save_config)
        self.extractor.insightGenerated.connect(self.insights_page.append_event)
        self.extractor.progressChanged.connect(self.insights_page.set_progress)

    def save_config(self, config: ProjectConfig) -> None:
        path = save_project_config(config)
        InfoBar.success(
            title="已保存",
            content=f"配置写入 {path}",
            parent=self,
            position=InfoBarPosition.TOP_RIGHT,
            duration=3000,
        )

    def run_preview(self, config: ProjectConfig) -> None:
        self.switchTo(self.insights_page)
        self.insights_page.clear_events()
        self.extractor.run_preview(config)

        first_character = config.target_characters[0] if config.target_characters else "示例角色"
        state = compile_character_state(first_character)
        self.output_page.set_markdown(render_profile_markdown(state))

        InfoBar.info(
            title="预览完成",
            content="当前为 UI 架构占位流程，AI 接入后会替换为真实抽取。",
            parent=self,
            position=InfoBarPosition.TOP_RIGHT,
            duration=3500,
        )
