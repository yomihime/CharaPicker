from __future__ import annotations

import re
import logging
from pathlib import Path

from PyQt6.QtCore import QObject, QRegularExpression, QSize, Qt, QThread, pyqtSignal
from PyQt6.QtGui import QRegularExpressionValidator
from PyQt6.QtWidgets import (
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QListWidgetItem,
    QListWidget,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    CheckBox,
    ComboBox,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    MessageBox,
    PrimaryPushButton,
    ProgressBar,
    PushButton,
    Slider,
    SubtitleLabel,
    isDarkTheme,
)

from core.models import ExtractionMode, ProjectConfig
from gui.widgets.dialog_middleware import FluentDialog
from gui.widgets.insight_stream_panel import InsightStreamPanel
from res.colors import (
    PROJECT_SOURCE_LIST_DARK_ALTERNATE_BACKGROUND,
    PROJECT_SOURCE_LIST_DARK_BACKGROUND,
    PROJECT_SOURCE_LIST_DARK_BORDER,
    PROJECT_SOURCE_LIST_DARK_SELECTED_BACKGROUND,
    PROJECT_SOURCE_LIST_DARK_SELECTED_TEXT,
    PROJECT_SOURCE_LIST_DARK_TEXT,
    PROJECT_SOURCE_LIST_LIGHT_ALTERNATE_BACKGROUND,
    PROJECT_SOURCE_LIST_LIGHT_BACKGROUND,
    PROJECT_SOURCE_LIST_LIGHT_BORDER,
    PROJECT_SOURCE_LIST_LIGHT_SELECTED_BACKGROUND,
    PROJECT_SOURCE_LIST_LIGHT_SELECTED_TEXT,
    PROJECT_SOURCE_LIST_LIGHT_TEXT,
)
from utils.i18n import t
from utils.env_manager import has_ffmpeg_binary
from utils.ffmpeg_downloader import (
    FfmpegDownloadCancelled,
    FfmpegDownloadError,
    download_and_install_ffmpeg,
)
from utils.paths import APP_ROOT, project_paths
from utils.source_importer import SUPPORTED_SOURCE_SUFFIXES, import_original_sources
from utils.state_manager import list_project_configs

LOGGER = logging.getLogger(__name__)
MM_SS_VALIDATOR = QRegularExpressionValidator(QRegularExpression(r"[0-5]\d:[0-5]\d"))
HH_MM_SS_VALIDATOR = QRegularExpressionValidator(QRegularExpression(r"\d\d:[0-5]\d:[0-5]\d"))
SOURCE_KIND_ROLE = int(Qt.ItemDataRole.UserRole)
SOURCE_PATH_ROLE = int(Qt.ItemDataRole.UserRole) + 1
SOURCE_KIND_EXTERNAL = "external"
SOURCE_KIND_PROJECT = "project"

class FfmpegDownloadWorker(QObject):
    progressChanged = pyqtSignal(int, str)
    succeeded = pyqtSignal(str)
    failed = pyqtSignal(str)
    cancelled = pyqtSignal()
    finished = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self._cancel_requested = False

    def cancel(self) -> None:
        self._cancel_requested = True

    def run(self) -> None:
        LOGGER.info("ffmpeg download worker started")
        try:
            binary = download_and_install_ffmpeg(
                progress=lambda value, step: self.progressChanged.emit(value, step),
                cancelled=lambda: self._cancel_requested,
            )
        except FfmpegDownloadCancelled:
            LOGGER.info("ffmpeg download cancelled")
            self.cancelled.emit()
        except FfmpegDownloadError as exc:
            LOGGER.warning("ffmpeg download failed", exc_info=True)
            self.failed.emit(str(exc))
        else:
            LOGGER.info("ffmpeg download succeeded; binary=%s", binary)
            self.succeeded.emit(str(binary))
        finally:
            self.finished.emit()


class FfmpegDownloadDialog(FluentDialog):
    cancelRequested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(t("project.ffmpeg.download.title"), parent, width=520, height=210, close_rejects=False)
        self._finished = False
        self._cancel_requested = False

        self.status_label = BodyLabel(t("project.ffmpeg.download.progress.download"), self.dialog_card)
        self.status_label.setWordWrap(True)
        self.content_layout.addWidget(self.status_label)

        self.progress_bar = ProgressBar(self.dialog_card)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.content_layout.addWidget(self.progress_bar)

        actions = QHBoxLayout()
        actions.addStretch(1)
        self.cancel_button = PushButton(t("project.ffmpeg.download.cancel"), self.dialog_card)
        actions.addWidget(self.cancel_button)
        self.content_layout.addLayout(actions)

        self.cancel_button.clicked.connect(self.request_cancel)
        self.close_button.clicked.connect(self.request_cancel)

    def set_progress(self, value: int, message: str) -> None:
        self.status_label.setText(message)
        self.progress_bar.setValue(value)

    def request_cancel(self) -> None:
        if self._cancel_requested or self._finished:
            return
        self._cancel_requested = True
        self.cancel_button.setEnabled(False)
        self.close_button.setEnabled(False)
        self.status_label.setText(t("project.ffmpeg.download.progress.canceling"))
        self.cancelRequested.emit()

    def mark_finished(self) -> None:
        self._finished = True

    def reject(self) -> None:
        if self._finished:
            super().reject()
            return
        self.request_cancel()


class NewProjectDialog(FluentDialog):
    def __init__(self, default_name: str, parent: QWidget | None = None) -> None:
        super().__init__(t("project.new.dialog.title"), parent, width=460, height=230)

        description = BodyLabel(t("project.new.dialog.description"), self.dialog_card)
        description.setWordWrap(True)
        self.content_layout.addWidget(description)

        self.name_edit = LineEdit(self.dialog_card)
        self.name_edit.setPlaceholderText(t("project.new.dialog.label"))
        self.name_edit.setText(default_name)
        self.content_layout.addWidget(self.name_edit)

        actions = QHBoxLayout()
        actions.addStretch(1)
        cancel_button = PushButton(t("project.new.dialog.cancel"), self.dialog_card)
        self.create_button = PrimaryPushButton(t("project.new.dialog.create"), self.dialog_card)
        actions.addWidget(cancel_button)
        actions.addWidget(self.create_button)
        self.content_layout.addLayout(actions)

        cancel_button.clicked.connect(self.reject)
        self.create_button.clicked.connect(self.accept)
        self.name_edit.textChanged.connect(self._sync_create_button)
        self.name_edit.returnPressed.connect(self._accept_if_ready)
        self.name_edit.selectAll()
        self._sync_create_button(self.name_edit.text())

    def project_name(self) -> str:
        return self.name_edit.text().strip()

    def _sync_create_button(self, text: str) -> None:
        self.create_button.setEnabled(bool(text.strip()))

    def _accept_if_ready(self) -> None:
        if self.create_button.isEnabled():
            self.accept()


class ProjectPage(QWidget):
    previewRequested = pyqtSignal(ProjectConfig)
    configSaved = pyqtSignal(ProjectConfig)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("projectPage")
        self.projects = list_project_configs()
        self._loading_project = False
        self._ffmpeg_download_thread: QThread | None = None
        self._ffmpeg_download_worker: FfmpegDownloadWorker | None = None
        self._ffmpeg_download_dialog: FfmpegDownloadDialog | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 18)
        root.setSpacing(12)

        header = QHBoxLayout()
        header.addWidget(SubtitleLabel(t("project.title"), self))
        header.addStretch(1)
        root.addLayout(header)

        content = QHBoxLayout()
        content.setSpacing(16)

        form_card = CardWidget(self)
        form_card.setBorderRadius(8)
        form_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        form = QGridLayout(form_card)
        form.setContentsMargins(18, 16, 18, 16)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(10)

        project_row = QHBoxLayout()
        self.project_combo = ComboBox(form_card)
        self.new_project_button = PushButton(t("project.new"), form_card)
        project_row.addWidget(self.project_combo, 1)
        project_row.addWidget(self.new_project_button)

        self.targets_edit = LineEdit(form_card)
        self.targets_edit.setPlaceholderText(t("project.character.placeholder"))

        self.mode_combo = ComboBox(form_card)
        self.mode_combo.addItems([t("project.mode.preview"), t("project.mode.full")])

        source_panel = QVBoxLayout()
        source_panel.setSpacing(10)
        source_area = QHBoxLayout()
        source_area.setSpacing(12)
        source_area.setAlignment(Qt.AlignmentFlag.AlignTop)
        source_actions = QVBoxLayout()
        source_actions.setSpacing(10)
        source_actions.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.add_file_button = PushButton(t("project.source.addFile"), form_card)
        self.add_folder_button = PushButton(t("project.source.addFolder"), form_card)
        self.remove_source_button = PushButton(t("project.source.remove"), form_card)
        for button in (self.add_file_button, self.add_folder_button, self.remove_source_button):
            button.setMinimumWidth(112)
        source_actions.addWidget(self.add_file_button)
        source_actions.addWidget(self.add_folder_button)
        source_actions.addWidget(self.remove_source_button)
        source_actions.addStretch(1)

        self.sources_list = QListWidget(form_card)
        self.sources_list.setObjectName("sourcesList")
        self.sources_list.setMinimumHeight(120)
        self.sources_list.setMaximumHeight(156)
        self.sources_list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.sources_list.setAlternatingRowColors(True)
        source_area.addWidget(self.sources_list, 1)
        source_area.setAlignment(self.sources_list, Qt.AlignmentFlag.AlignTop)
        source_area.addLayout(source_actions)
        source_panel.addLayout(source_area)

        processing_panel = QWidget(form_card)
        processing_layout = QGridLayout(processing_panel)
        processing_layout.setContentsMargins(0, 10, 0, 0)
        processing_layout.setHorizontalSpacing(12)
        processing_layout.setVerticalSpacing(7)

        processing_title = BodyLabel(t("project.processing.title"), processing_panel)
        processing_title.setMinimumWidth(88)
        self.ffmpeg_status_label = BodyLabel("", processing_panel)
        self.ffmpeg_status_label.setWordWrap(True)
        processing_layout.addWidget(processing_title, 0, 0)
        processing_layout.addWidget(self.ffmpeg_status_label, 0, 1)

        processing_layout.addWidget(BodyLabel(t("project.processing.preset"), processing_panel), 1, 0)
        self.processing_preset_combo = ComboBox(processing_panel)
        self.processing_preset_combo.addItems(
            [
                t("project.processing.preset.original"),
                t("project.processing.preset.segmentTranscode"),
                t("project.processing.preset.segmentOnly"),
                t("project.processing.preset.transcodeOnly"),
            ]
        )
        self.processing_preset_combo.setMinimumWidth(260)
        processing_layout.addWidget(self.processing_preset_combo, 1, 1)
        self.download_ffmpeg_button = PushButton(t("project.ffmpeg.download.button"), processing_panel)
        self.download_ffmpeg_button.setMinimumWidth(128)
        self.download_ffmpeg_button.setVisible(not has_ffmpeg_binary())
        self.process_sources_button = PrimaryPushButton(t("project.processing.start"), processing_panel)
        self.process_sources_button.setMinimumWidth(112)
        process_actions = QHBoxLayout()
        process_actions.setSpacing(8)
        process_actions.addWidget(self.download_ffmpeg_button)
        process_actions.addWidget(self.process_sources_button)
        processing_layout.addLayout(process_actions, 1, 2)
        processing_layout.setColumnStretch(1, 1)

        options_panel = QWidget(form_card)
        options_layout = QGridLayout(options_panel)
        options_layout.setContentsMargins(0, 2, 0, 0)
        options_layout.setHorizontalSpacing(12)
        options_layout.setVerticalSpacing(8)

        self.trim_check = CheckBox(t("project.processing.trim"), options_panel)
        self.trim_start_time = LineEdit(options_panel)
        self.trim_end_time = LineEdit(options_panel)
        for time_edit in (self.trim_start_time, self.trim_end_time):
            time_edit.setValidator(MM_SS_VALIDATOR)
            time_edit.setInputMask("00:00;_")
            time_edit.setText("0000")
            time_edit.setMaximumWidth(74)
        options_layout.addWidget(self.trim_check, 0, 0)
        trim_row = QHBoxLayout()
        trim_row.setSpacing(8)
        trim_row.addWidget(BodyLabel(t("project.processing.trim.start"), options_panel))
        trim_row.addWidget(self.trim_start_time)
        trim_row.addSpacing(10)
        trim_row.addWidget(BodyLabel(t("project.processing.trim.end"), options_panel))
        trim_row.addWidget(self.trim_end_time)
        trim_row.addStretch(1)
        options_layout.addLayout(trim_row, 0, 1)

        self.transcode_check = CheckBox(t("project.processing.transcode"), options_panel)
        self.codec_combo = ComboBox(options_panel)
        self.codec_combo.addItems(["H.264", "H.265"])
        self.resolution_combo = ComboBox(options_panel)
        self.resolution_combo.addItems(
            [
                t("project.processing.resolution.540p"),
                t("project.processing.resolution.720p"),
                t("project.processing.resolution.1080p"),
                t("project.processing.resolution.original"),
            ]
        )
        transcode_row = QHBoxLayout()
        transcode_row.setSpacing(8)
        transcode_row.addWidget(BodyLabel(t("project.processing.codec"), options_panel))
        transcode_row.addWidget(self.codec_combo)
        transcode_row.addWidget(BodyLabel(t("project.processing.resolution"), options_panel))
        transcode_row.addWidget(self.resolution_combo)
        transcode_row.addStretch(1)
        options_layout.addWidget(self.transcode_check, 1, 0)
        options_layout.addLayout(transcode_row, 1, 1)

        self.segment_check = CheckBox(t("project.processing.segment"), options_panel)
        self.segment_mode_combo = ComboBox(options_panel)
        self.segment_mode_combo.addItems(
            [
                t("project.processing.segment.byTime"),
                t("project.processing.segment.byCount"),
            ]
        )
        self.segment_time = LineEdit(options_panel)
        self.segment_time.setValidator(HH_MM_SS_VALIDATOR)
        self.segment_time.setInputMask("00:00:00;_")
        self.segment_time.setText("000200")
        self.segment_time.setMaximumWidth(94)
        self.segment_count_slider = Slider(Qt.Orientation.Horizontal, options_panel)
        self.segment_count_slider.setRange(1, 20)
        self.segment_count_slider.setValue(4)
        self.segment_count_slider.setMaximumWidth(180)
        self.segment_count_label = BodyLabel("4", options_panel)
        segment_row = QHBoxLayout()
        segment_row.setSpacing(8)
        segment_row.addWidget(self.segment_mode_combo)
        segment_row.addWidget(self.segment_time)
        segment_row.addSpacing(12)
        segment_row.addWidget(self.segment_count_slider)
        segment_row.addWidget(self.segment_count_label)
        segment_row.addStretch(1)
        options_layout.addWidget(self.segment_check, 2, 0)
        options_layout.addLayout(segment_row, 2, 1)
        options_layout.setColumnStretch(1, 1)

        processing_block = QVBoxLayout()
        processing_block.setSpacing(8)
        processing_block.addWidget(processing_panel)
        processing_block.addWidget(options_panel)

        form.addWidget(BodyLabel(t("project.field.project"), form_card), 0, 0)
        form.addLayout(project_row, 0, 1)
        form.addWidget(BodyLabel(t("project.field.characters"), form_card), 1, 0)
        form.addWidget(self.targets_edit, 1, 1)
        form.addWidget(BodyLabel(t("project.field.mode"), form_card), 2, 0)
        form.addWidget(self.mode_combo, 2, 1)
        form.addWidget(BodyLabel(t("project.field.sources"), form_card), 3, 0, alignment=Qt.AlignmentFlag.AlignTop)
        form.addLayout(source_panel, 3, 1)
        form.addLayout(processing_block, 4, 0, 1, 2)
        form_spacer = QWidget(form_card)
        form_spacer.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        form.addWidget(form_spacer, 5, 0, 1, 2)
        form.setRowStretch(3, 0)
        form.setRowStretch(4, 0)
        form.setRowStretch(5, 1)
        form.setColumnStretch(1, 1)
        content.addWidget(form_card, 3)

        insight_card = CardWidget(self)
        insight_card.setBorderRadius(8)
        insight_layout = QVBoxLayout(insight_card)
        insight_layout.setContentsMargins(18, 14, 18, 16)
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
        content.addWidget(insight_card, 2)
        root.addLayout(content, 1)

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
        self.mode_combo.currentIndexChanged.connect(self._sync_preview_button_text)
        self.download_ffmpeg_button.clicked.connect(self._download_ffmpeg)
        self.process_sources_button.clicked.connect(self._start_source_processing)
        self.processing_preset_combo.currentIndexChanged.connect(self._sync_processing_options)
        self.segment_mode_combo.currentIndexChanged.connect(self._sync_segment_mode)
        self.segment_count_slider.valueChanged.connect(self._sync_segment_count_label)
        self._refresh_project_combo()
        self._sync_preview_button_text()
        self._refresh_ffmpeg_state()
        self._sync_processing_options()
        self._sync_segment_mode()
        self.apply_theme_colors()

    def current_config(self) -> ProjectConfig:
        targets = [
            target.strip()
            for target in self.targets_edit.text().replace("，", ",").split(",")
            if target.strip()
        ]
        sources = [
            self.sources_list.item(index).data(SOURCE_PATH_ROLE) or self.sources_list.item(index).text()
            for index in range(self.sources_list.count())
            if self.sources_list.item(index).data(SOURCE_KIND_ROLE) == SOURCE_KIND_EXTERNAL
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

    def apply_theme_colors(self) -> None:
        if isDarkTheme():
            self.sources_list.setStyleSheet(
                f"""
                QListWidget#sourcesList {{
                    background: {PROJECT_SOURCE_LIST_DARK_BACKGROUND};
                    border: 1px solid {PROJECT_SOURCE_LIST_DARK_BORDER};
                    border-radius: 6px;
                    color: {PROJECT_SOURCE_LIST_DARK_TEXT};
                    alternate-background-color: {PROJECT_SOURCE_LIST_DARK_ALTERNATE_BACKGROUND};
                    outline: none;
                }}

                QListWidget#sourcesList::item {{
                    padding: 3px 8px;
                    border-radius: 4px;
                }}

                QListWidget#sourcesList::item:selected {{
                    background: {PROJECT_SOURCE_LIST_DARK_SELECTED_BACKGROUND};
                    color: {PROJECT_SOURCE_LIST_DARK_SELECTED_TEXT};
                }}
                """
            )
        else:
            self.sources_list.setStyleSheet(
                f"""
                QListWidget#sourcesList {{
                    background: {PROJECT_SOURCE_LIST_LIGHT_BACKGROUND};
                    border: 1px solid {PROJECT_SOURCE_LIST_LIGHT_BORDER};
                    border-radius: 6px;
                    color: {PROJECT_SOURCE_LIST_LIGHT_TEXT};
                    alternate-background-color: {PROJECT_SOURCE_LIST_LIGHT_ALTERNATE_BACKGROUND};
                    outline: none;
                }}

                QListWidget#sourcesList::item {{
                    padding: 3px 8px;
                    border-radius: 4px;
                }}

                QListWidget#sourcesList::item:selected {{
                    background: {PROJECT_SOURCE_LIST_LIGHT_SELECTED_BACKGROUND};
                    color: {PROJECT_SOURCE_LIST_LIGHT_SELECTED_TEXT};
                }}
                """
            )
        self.stream_panel.apply_theme_colors()

    def _emit_save(self) -> None:
        config = self.current_config()
        if self._uses_original_sources():
            import_original_sources(config.project_id, config.source_paths)
            self._refresh_project_sources(config.project_id)
        self._upsert_project(config)
        self.configSaved.emit(config)

    def _emit_preview(self) -> None:
        self.previewRequested.emit(self.current_config())

    def _sync_preview_button_text(self) -> None:
        key = "project.preview" if self.mode_combo.currentIndex() == 0 else "project.fullExtraction"
        self.preview_button.setText(t(key))

    def _refresh_ffmpeg_state(self) -> None:
        has_ffmpeg = has_ffmpeg_binary()
        self.ffmpeg_status_label.setText(
            t("project.ffmpeg.status.notRequired")
            if self._uses_original_sources()
            else t("project.ffmpeg.status.ready")
            if has_ffmpeg
            else t("project.ffmpeg.status.missing")
        )
        self.download_ffmpeg_button.setVisible(not self._uses_original_sources() and not has_ffmpeg)

    def _uses_original_sources(self) -> bool:
        return self.processing_preset_combo.currentIndex() == 0

    def _sync_processing_options(self) -> None:
        uses_original = self._uses_original_sources()
        for widget in (
            self.trim_check,
            self.trim_start_time,
            self.trim_end_time,
            self.transcode_check,
            self.codec_combo,
            self.resolution_combo,
            self.segment_check,
            self.segment_mode_combo,
            self.segment_time,
            self.segment_count_slider,
        ):
            widget.setEnabled(not uses_original)
        self.segment_count_label.setEnabled(not uses_original)
        self._refresh_ffmpeg_state()

    def _sync_segment_mode(self) -> None:
        by_time = self.segment_mode_combo.currentIndex() == 0
        self.segment_time.setVisible(by_time)
        self.segment_count_slider.setVisible(not by_time)
        self.segment_count_label.setVisible(not by_time)

    def _sync_segment_count_label(self, value: int) -> None:
        self.segment_count_label.setText(str(value))

    def _start_source_processing(self) -> None:
        config = self.current_config()
        if self._uses_original_sources():
            imported_count = import_original_sources(config.project_id, config.source_paths)
            self._refresh_project_sources(config.project_id)
            InfoBar.success(
                title=t("project.processing.done.title"),
                content=t("project.processing.done.original", count=imported_count),
                parent=self.window(),
                position=InfoBarPosition.TOP_RIGHT,
                duration=3500,
            )
            return

        if not has_ffmpeg_binary():
            dialog = MessageBox(
                t("project.ffmpeg.missing.dialog.title"),
                t("project.ffmpeg.missing.dialog.content"),
                self.window(),
            )
            dialog.yesButton.setText(t("project.ffmpeg.download.button"))
            dialog.cancelButton.setText(t("project.ffmpeg.missing.dialog.cancel"))
            if dialog.exec():
                self._download_ffmpeg()
            return

        InfoBar.info(
            title=t("project.processing.placeholder.title"),
            content=t("project.processing.placeholder.content"),
            parent=self.window(),
            position=InfoBarPosition.TOP_RIGHT,
            duration=4500,
        )

    def _download_ffmpeg(self) -> None:
        if self._ffmpeg_download_thread is not None:
            LOGGER.info("ffmpeg download ignored because a download is already running")
            return

        LOGGER.info("ffmpeg download requested")
        self._ffmpeg_download_dialog = FfmpegDownloadDialog(self)
        self._ffmpeg_download_dialog.show()

        self.download_ffmpeg_button.setEnabled(False)
        self._ffmpeg_download_thread = QThread(self)
        self._ffmpeg_download_worker = FfmpegDownloadWorker()
        self._ffmpeg_download_worker.moveToThread(self._ffmpeg_download_thread)
        self._ffmpeg_download_thread.started.connect(self._ffmpeg_download_worker.run)
        self._ffmpeg_download_dialog.cancelRequested.connect(self._ffmpeg_download_worker.cancel)
        self._ffmpeg_download_worker.progressChanged.connect(self._update_ffmpeg_download_progress)
        self._ffmpeg_download_worker.succeeded.connect(self._finish_ffmpeg_download_success)
        self._ffmpeg_download_worker.failed.connect(self._finish_ffmpeg_download_failure)
        self._ffmpeg_download_worker.cancelled.connect(self._finish_ffmpeg_download_cancelled)
        self._ffmpeg_download_worker.finished.connect(self._ffmpeg_download_thread.quit)
        self._ffmpeg_download_worker.finished.connect(self._ffmpeg_download_worker.deleteLater)
        self._ffmpeg_download_thread.finished.connect(self._ffmpeg_download_thread.deleteLater)
        self._ffmpeg_download_thread.finished.connect(self._clear_ffmpeg_download_worker)
        self._ffmpeg_download_thread.start()

    def _update_ffmpeg_download_progress(self, value: int, step: str) -> None:
        if self._ffmpeg_download_dialog is None:
            return
        self._ffmpeg_download_dialog.set_progress(value, t(f"project.ffmpeg.download.progress.{step}"))

    def _finish_ffmpeg_download_success(self, binary_path: str) -> None:
        if self._ffmpeg_download_dialog is not None:
            self._ffmpeg_download_dialog.mark_finished()
            self._ffmpeg_download_dialog.set_progress(100, t("project.ffmpeg.download.progress.done"))
            self._ffmpeg_download_dialog.close()
        self.download_ffmpeg_button.setVisible(False)
        self.ffmpeg_status_label.setText(t("project.ffmpeg.status.ready"))
        InfoBar.success(
            title=t("project.ffmpeg.download.success.title"),
            content=t("project.ffmpeg.download.success.content", path=binary_path),
            parent=self.window(),
            position=InfoBarPosition.TOP_RIGHT,
            duration=4500,
        )

    def _finish_ffmpeg_download_failure(self, error: str) -> None:
        if self._ffmpeg_download_dialog is not None:
            self._ffmpeg_download_dialog.mark_finished()
            self._ffmpeg_download_dialog.close()
        InfoBar.warning(
            title=t("project.ffmpeg.download.failure.title"),
            content=t("project.ffmpeg.download.failure.content", error=self._short_error(error)),
            parent=self.window(),
            position=InfoBarPosition.TOP_RIGHT,
            duration=7000,
        )

    def _finish_ffmpeg_download_cancelled(self) -> None:
        if self._ffmpeg_download_dialog is not None:
            self._ffmpeg_download_dialog.mark_finished()
            self._ffmpeg_download_dialog.close()
        InfoBar.info(
            title=t("project.ffmpeg.download.cancelled.title"),
            content=t("project.ffmpeg.download.cancelled.content"),
            parent=self.window(),
            position=InfoBarPosition.TOP_RIGHT,
            duration=3500,
        )

    def _clear_ffmpeg_download_worker(self) -> None:
        self.download_ffmpeg_button.setEnabled(True)
        self._refresh_ffmpeg_state()
        self._ffmpeg_download_thread = None
        self._ffmpeg_download_worker = None
        self._ffmpeg_download_dialog = None

    def _short_error(self, error: str) -> str:
        error = " ".join(error.split())
        max_length = 120
        if len(error) <= max_length:
            return error
        return f"{error[:max_length]}..."

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
        self._sync_preview_button_text()
        self.sources_list.clear()
        for source_path in project.source_paths:
            self._add_source_item(source_path, SOURCE_KIND_EXTERNAL)
        self._refresh_project_sources(project.project_id)
        self.clear_events()

    def _add_project(self) -> None:
        default_name = self._next_project_name()
        dialog = NewProjectDialog(default_name, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        name = dialog.project_name() or default_name
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
            self.sources_list.item(index).data(SOURCE_PATH_ROLE) or self.sources_list.item(index).text()
            for index in range(self.sources_list.count())
        }
        for path in paths:
            if path and path not in existing:
                self._add_source_item(path, SOURCE_KIND_EXTERNAL)
                existing.add(path)

    def _add_source_item(self, source_path: str, source_kind: str) -> None:
        display_text = source_path
        if source_kind == SOURCE_KIND_PROJECT:
            try:
                display_text = t(
                    "project.source.projectItem",
                    path=Path(source_path).resolve().relative_to(APP_ROOT).as_posix(),
                )
            except ValueError:
                display_text = t("project.source.projectItem", path=source_path)

        item = QListWidgetItem(display_text)
        item.setSizeHint(QSize(0, 26))
        item.setData(SOURCE_KIND_ROLE, source_kind)
        item.setData(SOURCE_PATH_ROLE, source_path)
        self.sources_list.addItem(item)

    def _project_source_paths(self, project_id: str) -> list[Path]:
        raw_root = project_paths(project_id).raw
        if not raw_root.exists():
            return []
        paths = [
            path
            for path in raw_root.rglob("*")
            if path.is_file() and (not path.suffix or path.suffix.lower() in SUPPORTED_SOURCE_SUFFIXES)
        ]
        return sorted(paths, key=lambda path: path.relative_to(raw_root).as_posix().lower())

    def _refresh_project_sources(self, project_id: str) -> None:
        for row in reversed(range(self.sources_list.count())):
            item = self.sources_list.item(row)
            if item.data(SOURCE_KIND_ROLE) == SOURCE_KIND_PROJECT:
                self.sources_list.takeItem(row)
        existing = {
            self.sources_list.item(index).data(SOURCE_PATH_ROLE)
            for index in range(self.sources_list.count())
        }
        for source_path in self._project_source_paths(project_id):
            source_text = str(source_path)
            if source_text not in existing:
                self._add_source_item(source_text, SOURCE_KIND_PROJECT)
                existing.add(source_text)

    def _remove_selected_sources(self) -> None:
        for item in self.sources_list.selectedItems():
            if item.data(SOURCE_KIND_ROLE) != SOURCE_KIND_EXTERNAL:
                continue
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
