from __future__ import annotations

import re

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QListWidget,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    ComboBox,
    LineEdit,
    PrimaryPushButton,
    ProgressBar,
    PushButton,
    SubtitleLabel,
)

from core.models import ExtractionMode, ProjectConfig
from gui.widgets.insight_stream_panel import InsightStreamPanel
from utils.i18n import t
from utils.state_manager import list_project_configs


class ProjectPage(QWidget):
    previewRequested = pyqtSignal(ProjectConfig)
    configSaved = pyqtSignal(ProjectConfig)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("projectPage")
        self.projects = list_project_configs()
        self._loading_project = False

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(18)

        header = QHBoxLayout()
        header.addWidget(SubtitleLabel(t("project.title"), self))
        header.addStretch(1)
        root.addLayout(header)

        form_card = CardWidget(self)
        form_card.setBorderRadius(8)
        form = QGridLayout(form_card)
        form.setContentsMargins(20, 18, 20, 20)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(12)

        project_row = QHBoxLayout()
        self.project_combo = ComboBox(form_card)
        self.new_project_button = PushButton(t("project.new"), form_card)
        project_row.addWidget(self.project_combo, 1)
        project_row.addWidget(self.new_project_button)

        self.targets_edit = LineEdit(form_card)
        self.targets_edit.setPlaceholderText(t("project.character.placeholder"))

        self.mode_combo = ComboBox(form_card)
        self.mode_combo.addItems([t("project.mode.preview"), t("project.mode.full")])

        source_area = QHBoxLayout()
        source_actions = QVBoxLayout()
        self.add_file_button = PushButton(t("project.source.addFile"), form_card)
        self.add_folder_button = PushButton(t("project.source.addFolder"), form_card)
        self.remove_source_button = PushButton(t("project.source.remove"), form_card)
        source_actions.addWidget(self.add_file_button)
        source_actions.addWidget(self.add_folder_button)
        source_actions.addWidget(self.remove_source_button)
        source_actions.addStretch(1)

        self.sources_list = QListWidget(form_card)
        self.sources_list.setMinimumHeight(116)
        self.sources_list.setAlternatingRowColors(True)
        source_area.addWidget(self.sources_list, 1)
        source_area.addLayout(source_actions)

        form.addWidget(BodyLabel(t("project.field.project"), form_card), 0, 0)
        form.addLayout(project_row, 0, 1)
        form.addWidget(BodyLabel(t("project.field.characters"), form_card), 1, 0)
        form.addWidget(self.targets_edit, 1, 1)
        form.addWidget(BodyLabel(t("project.field.mode"), form_card), 2, 0)
        form.addWidget(self.mode_combo, 2, 1)
        form.addWidget(BodyLabel(t("project.field.sources"), form_card), 3, 0)
        form.addLayout(source_area, 3, 1)
        form.setColumnStretch(1, 1)
        root.addWidget(form_card)

        insight_card = CardWidget(self)
        insight_card.setBorderRadius(8)
        insight_card.setMinimumHeight(280)
        insight_layout = QVBoxLayout(insight_card)
        insight_layout.setContentsMargins(18, 14, 18, 18)
        insight_layout.setSpacing(10)

        insight_header = QHBoxLayout()
        insight_header.addWidget(SubtitleLabel(t("project.insights.title"), insight_card))
        insight_header.addStretch(1)
        insight_layout.addLayout(insight_header)

        insight_layout.addWidget(BodyLabel(t("project.progress.label"), insight_card))
        self.progress = ProgressBar(insight_card)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        insight_layout.addWidget(self.progress)

        self.stream_panel = InsightStreamPanel(insight_card)
        insight_layout.addWidget(self.stream_panel, 1)
        root.addWidget(insight_card, 1)

        actions = QHBoxLayout()
        actions.addStretch(1)
        self.save_button = PushButton(t("project.save"), self)
        self.preview_button = PrimaryPushButton(t("project.preview"), self)
        actions.addWidget(self.save_button)
        actions.addWidget(self.preview_button)
        root.addLayout(actions)

        self.project_combo.currentIndexChanged.connect(self._load_selected_project)
        self.new_project_button.clicked.connect(self._add_project)
        self.add_file_button.clicked.connect(self._add_files)
        self.add_folder_button.clicked.connect(self._add_folder)
        self.remove_source_button.clicked.connect(self._remove_selected_sources)
        self.save_button.clicked.connect(self._emit_save)
        self.preview_button.clicked.connect(self._emit_preview)
        self._refresh_project_combo()

    def current_config(self) -> ProjectConfig:
        targets = [
            target.strip()
            for target in self.targets_edit.text().replace("，", ",").split(",")
            if target.strip()
        ]
        sources = [
            self.sources_list.item(index).text()
            for index in range(self.sources_list.count())
        ]
        mode = ExtractionMode.PREVIEW if self.mode_combo.currentIndex() == 0 else ExtractionMode.FULL
        project = self._selected_project()
        return ProjectConfig(
            project_id=project.project_id,
            name=project.name,
            target_characters=targets,
            extraction_mode=mode,
            source_paths=sources,
            created_at=project.created_at,
        )

    def append_event(self, event: dict) -> None:
        self.stream_panel.append_event(event)

    def clear_events(self) -> None:
        self.progress.setValue(0)
        self.stream_panel.clear_events()

    def set_progress(self, value: int) -> None:
        self.progress.setValue(value)

    def _emit_save(self) -> None:
        config = self.current_config()
        self._upsert_project(config)
        self.configSaved.emit(config)

    def _emit_preview(self) -> None:
        self.previewRequested.emit(self.current_config())

    def _refresh_project_combo(self) -> None:
        self._loading_project = True
        self.project_combo.clear()
        if not self.projects:
            name = t("project.defaultName", index=1)
            self.projects.append(ProjectConfig(project_id=self._make_project_id(name), name=name))
        for project in self.projects:
            self.project_combo.addItem(project.name)
        self._loading_project = False
        self._load_selected_project()

    def _selected_project(self) -> ProjectConfig:
        index = self.project_combo.currentIndex()
        if 0 <= index < len(self.projects):
            return self.projects[index]
        name = t("project.defaultName", index=1)
        return ProjectConfig(project_id=self._make_project_id(name), name=name)

    def _load_selected_project(self) -> None:
        if self._loading_project:
            return
        project = self._selected_project()
        self.targets_edit.setText(", ".join(project.target_characters))
        self.mode_combo.setCurrentIndex(0 if project.extraction_mode == ExtractionMode.PREVIEW else 1)
        self.sources_list.clear()
        for source_path in project.source_paths:
            self.sources_list.addItem(source_path)
        self.clear_events()

    def _add_project(self) -> None:
        default_name = self._next_project_name()
        name, accepted = QInputDialog.getText(
            self,
            t("project.new.dialog.title"),
            t("project.new.dialog.label"),
            text=default_name,
        )
        if not accepted:
            return

        name = name.strip() or default_name
        name = self._unique_project_name(name)
        project_id = self._make_project_id(name)
        self.projects.insert(0, ProjectConfig(project_id=project_id, name=name))
        self._refresh_project_combo()
        self.project_combo.setCurrentIndex(0)

    def _upsert_project(self, config: ProjectConfig) -> None:
        for index, project in enumerate(self.projects):
            if project.project_id == config.project_id:
                self.projects[index] = config
                return
        self.projects.insert(0, config)

    def _add_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, t("project.fileDialog.files"))
        self._append_sources(paths)

    def _add_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, t("project.fileDialog.folder"))
        if path:
            self._append_sources([path])

    def _append_sources(self, paths: list[str]) -> None:
        existing = {
            self.sources_list.item(index).text()
            for index in range(self.sources_list.count())
        }
        for path in paths:
            if path and path not in existing:
                self.sources_list.addItem(path)
                existing.add(path)

    def _remove_selected_sources(self) -> None:
        for item in self.sources_list.selectedItems():
            row = self.sources_list.row(item)
            self.sources_list.takeItem(row)

    def _next_project_name(self) -> str:
        existing_names = {project.name for project in self.projects}
        index = len(self.projects) + 1
        name = t("project.defaultName", index=index)
        while name in existing_names:
            index += 1
            name = t("project.defaultName", index=index)
        return name

    def _unique_project_name(self, name: str) -> str:
        existing_names = {project.name for project in self.projects}
        if name not in existing_names:
            return name

        index = 2
        unique_name = f"{name} {index}"
        while unique_name in existing_names:
            index += 1
            unique_name = f"{name} {index}"
        return unique_name

    def _make_project_id(self, name: str) -> str:
        cleaned_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "-", name).strip(" .-")
        cleaned_name = re.sub(r"\s+", "-", cleaned_name)
        base_id = f"project-{cleaned_name or 'untitled'}"

        existing_ids = {project.project_id for project in self.projects}
        if base_id not in existing_ids:
            return base_id

        index = 2
        project_id = f"{base_id}-{index}"
        while project_id in existing_ids:
            index += 1
            project_id = f"{base_id}-{index}"
        return project_id
