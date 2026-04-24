from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QGridLayout, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    ComboBox,
    LineEdit,
    PlainTextEdit,
    PrimaryPushButton,
    PushButton,
    SubtitleLabel,
)

from core.models import ExtractionMode, ProjectConfig


class ProjectPage(QWidget):
    previewRequested = pyqtSignal(ProjectConfig)
    configSaved = pyqtSignal(ProjectConfig)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("projectPage")

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(18)

        header = SubtitleLabel("项目配置", self)
        root.addWidget(header)

        form_card = CardWidget(self)
        form_card.setBorderRadius(8)
        form = QGridLayout(form_card)
        form.setContentsMargins(20, 18, 20, 20)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(12)

        self.name_edit = LineEdit(form_card)
        self.name_edit.setPlaceholderText("例如: 长篇小说角色档案")
        self.name_edit.setText("CharaPicker Demo")

        self.targets_edit = LineEdit(form_card)
        self.targets_edit.setPlaceholderText("用逗号分隔，例如: 林渊, 沈青")

        self.mode_combo = ComboBox(form_card)
        self.mode_combo.addItems(["预览模式", "完整抽取"])

        self.sources_edit = PlainTextEdit(form_card)
        self.sources_edit.setPlaceholderText("每行一个原文文件或目录路径")
        self.sources_edit.setFixedHeight(112)

        form.addWidget(BodyLabel("项目名称", form_card), 0, 0)
        form.addWidget(self.name_edit, 0, 1)
        form.addWidget(BodyLabel("目标角色", form_card), 1, 0)
        form.addWidget(self.targets_edit, 1, 1)
        form.addWidget(BodyLabel("抽取模式", form_card), 2, 0)
        form.addWidget(self.mode_combo, 2, 1)
        form.addWidget(BodyLabel("素材路径", form_card), 3, 0)
        form.addWidget(self.sources_edit, 3, 1)
        form.setColumnStretch(1, 1)
        root.addWidget(form_card)

        actions = QHBoxLayout()
        actions.addStretch(1)
        self.save_button = PushButton("保存配置", self)
        self.preview_button = PrimaryPushButton("运行预览", self)
        actions.addWidget(self.save_button)
        actions.addWidget(self.preview_button)
        root.addLayout(actions)
        root.addStretch(1)

        self.save_button.clicked.connect(self._emit_save)
        self.preview_button.clicked.connect(self._emit_preview)

    def current_config(self) -> ProjectConfig:
        targets = [
            target.strip()
            for target in self.targets_edit.text().replace("，", ",").split(",")
            if target.strip()
        ]
        sources = [
            line.strip()
            for line in self.sources_edit.toPlainText().splitlines()
            if line.strip()
        ]
        mode = ExtractionMode.PREVIEW if self.mode_combo.currentIndex() == 0 else ExtractionMode.FULL
        return ProjectConfig(
            name=self.name_edit.text().strip() or "Untitled Project",
            target_characters=targets,
            extraction_mode=mode,
            source_paths=sources,
        )

    def _emit_save(self) -> None:
        self.configSaved.emit(self.current_config())

    def _emit_preview(self) -> None:
        self.previewRequested.emit(self.current_config())
