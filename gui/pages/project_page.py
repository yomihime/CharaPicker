from __future__ import annotations

import re
import logging
from pathlib import Path

from PyQt6.QtCore import QObject, QRegularExpression, QSize, Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFontMetrics, QKeySequence, QRegularExpressionValidator, QShortcut
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
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
from core.models import SourceProcessingConfig, SourceProcessingPreset, SourceSegmentMode
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
from utils.paths import project_paths
from utils.source_importer import (
    SUPPORTED_SOURCE_SUFFIXES,
    clean_raw_sources,
    import_sources_to_raw,
    link_raw_sources_to_materials,
    remove_project_sources,
    remove_raw_sources,
    source_raw_target_pairs,
    source_raw_targets,
)
from utils.state_manager import create_project_config, delete_project_config, list_project_configs, save_project_config

LOGGER = logging.getLogger(__name__)
MM_SS_VALIDATOR = QRegularExpressionValidator(QRegularExpression(r"[0-5]\d:[0-5]\d"))
HH_MM_SS_VALIDATOR = QRegularExpressionValidator(QRegularExpression(r"\d\d:[0-5]\d:[0-5]\d"))
SOURCE_KIND_ROLE = int(Qt.ItemDataRole.UserRole)
SOURCE_PATH_ROLE = int(Qt.ItemDataRole.UserRole) + 1
SOURCE_STATUS_ROLE = int(Qt.ItemDataRole.UserRole) + 2
SOURCE_KIND_EXTERNAL = "external"
SOURCE_KIND_PROJECT = "project"
SOURCE_STATUS_NEW = "new"
SOURCE_STATUS_PROCESSED = "processed"
SOURCE_STATUS_STALE = "stale"
SOURCE_STATUS_RAW_CLEANED = "rawCleaned"
PROCESSING_PRESETS = [
    SourceProcessingPreset.ORIGINAL,
    SourceProcessingPreset.SEGMENT_TRANSCODE,
    SourceProcessingPreset.SEGMENT_ONLY,
    SourceProcessingPreset.TRANSCODE_ONLY,
]

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


class SourceProcessingWorker(QObject):
    progressChanged = pyqtSignal(int, int, str)
    succeeded = pyqtSignal(object, int, bool)
    failed = pyqtSignal(str)
    cancelled = pyqtSignal()
    finished = pyqtSignal()

    def __init__(self, config: ProjectConfig, uses_original_sources: bool) -> None:
        super().__init__()
        self.config = config
        self.uses_original_sources = uses_original_sources
        self._cancel_requested = False

    def cancel(self) -> None:
        self._cancel_requested = True

    def run(self) -> None:
        try:
            raw_sources = import_sources_to_raw(
                self.config.project_id,
                self.config.source_paths,
                progress=self._emit_progress,
                cancelled=lambda: self._cancel_requested,
            )
            if self._cancel_requested:
                self.cancelled.emit()
                return
            raw_root = project_paths(self.config.project_id).raw
            reimported_paths = {
                self._raw_relative_path(raw_root, raw_source)
                for raw_source in raw_sources
            }
            updated_config = self.config
            if reimported_paths:
                updated_config = self.config.model_copy(
                    update={
                        "raw_cleaned_paths": [
                            path for path in self.config.raw_cleaned_paths if path not in reimported_paths
                        ]
                    }
                )

            linked_count = 0
            if self.uses_original_sources:
                linked_count = link_raw_sources_to_materials(
                    self.config.project_id,
                    raw_sources,
                    progress=self._emit_progress,
                )
            if self._cancel_requested:
                self.cancelled.emit()
                return
            save_project_config(updated_config)
            self.succeeded.emit(updated_config, linked_count, self.uses_original_sources)
        except RuntimeError as exc:
            if str(exc) == "Source processing cancelled":
                self.cancelled.emit()
                return
            LOGGER.warning("Source processing failed", exc_info=True)
            self.failed.emit(str(exc))
        except Exception as exc:
            LOGGER.warning("Source processing failed", exc_info=True)
            self.failed.emit(str(exc))
        finally:
            self.finished.emit()

    def _emit_progress(self, done: int, total: int, name: str) -> None:
        if self._cancel_requested:
            raise RuntimeError("Source processing cancelled")
        self.progressChanged.emit(done, total, name)

    def _raw_relative_path(self, raw_root: Path, raw_source: Path) -> str:
        try:
            return raw_source.resolve().relative_to(raw_root.resolve()).as_posix()
        except ValueError:
            return raw_source.name


class SourceProcessingDialog(FluentDialog):
    cancelRequested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(t("project.processing.dialog.title"), parent, width=520, height=190, close_rejects=False)
        self._cancel_requested = False
        self._finished = False
        self.close_button.clicked.connect(self.reject)
        self.status_label = BodyLabel(t("project.processing.dialog.scanning"), self.dialog_card)
        self.status_label.setWordWrap(True)
        self.content_layout.addWidget(self.status_label)

        self.progress_bar = ProgressBar(self.dialog_card)
        self.progress_bar.setRange(0, 0)
        self.content_layout.addWidget(self.progress_bar)

    def set_progress(self, done: int, total: int, name: str) -> None:
        if total <= 0:
            self.progress_bar.setRange(0, 0)
            self.status_label.setText(t("project.processing.dialog.scanning"))
            return
        self.progress_bar.setRange(0, total)
        self.progress_bar.setValue(done)
        self.status_label.setText(t("project.processing.dialog.progress", done=done, total=total, name=name))

    def finish(self) -> None:
        self._finished = True
        self.accept()

    def reject(self) -> None:
        if self._finished:
            super().reject()
            return
        if self._cancel_requested:
            return
        self._cancel_requested = True
        self.close_button.setEnabled(False)
        self.status_label.setText(t("project.processing.dialog.canceling"))
        self.cancelRequested.emit()


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


class SourceListRow(QWidget):
    def __init__(self, text: str, status: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 0, 8, 0)
        layout.setSpacing(8)

        path_label = QLabel(text, self)
        path_label.setMinimumWidth(0)
        path_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        path_label.setToolTip(text)
        layout.addWidget(path_label, 1)

        status_label = QLabel(self._status_icon(status), self)
        status_label.setToolTip(t(f"project.source.status.{status}"))
        status_label.setFixedWidth(18)
        status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(status_label)
        self._full_text = text
        self._path_label = path_label
        self._status_label = status_label

    def _status_icon(self, status: str) -> str:
        if status == SOURCE_STATUS_RAW_CLEANED:
            return "R"
        if status == SOURCE_STATUS_PROCESSED:
            return "✓"
        if status == SOURCE_STATUS_STALE:
            return "!"
        return "+"

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        metrics = QFontMetrics(self._path_label.font())
        self._path_label.setText(metrics.elidedText(self._full_text, Qt.TextElideMode.ElideMiddle, self._path_label.width()))


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
        self._source_processing_thread: QThread | None = None
        self._source_processing_worker: SourceProcessingWorker | None = None
        self._source_processing_dialog: SourceProcessingDialog | None = None

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
        project_row.setSpacing(12)
        self.project_combo = ComboBox(form_card)
        self.new_project_button = PushButton(t("project.new"), form_card)
        self.delete_project_button = PushButton(t("project.delete"), form_card)
        project_row.addWidget(self.project_combo, 1)
        project_row.addWidget(self.new_project_button)
        project_row.addWidget(self.delete_project_button)

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
        self.clean_raw_button = PushButton(t("project.source.cleanRaw"), form_card)
        for button in (self.add_file_button, self.add_folder_button, self.remove_source_button, self.clean_raw_button):
            button.setMinimumWidth(112)
        source_actions.addWidget(self.add_file_button)
        source_actions.addWidget(self.add_folder_button)
        source_actions.addWidget(self.remove_source_button)
        source_actions.addWidget(self.clean_raw_button)
        source_actions.addStretch(1)

        self.sources_list = QListWidget(form_card)
        self.sources_list.setObjectName("sourcesList")
        self.sources_list.setMinimumHeight(120)
        self.sources_list.setMaximumHeight(156)
        self.sources_list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.sources_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.sources_list.setAlternatingRowColors(True)
        select_all_shortcut = QShortcut(QKeySequence.StandardKey.SelectAll, self.sources_list)
        select_all_shortcut.activated.connect(self.sources_list.selectAll)
        source_area.addWidget(self.sources_list, 1)
        source_area.setAlignment(self.sources_list, Qt.AlignmentFlag.AlignTop)
        source_area.addLayout(source_actions)
        source_area.setAlignment(source_actions, Qt.AlignmentFlag.AlignTop)
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
        self.delete_project_button.clicked.connect(self._delete_project)
        self.add_file_button.clicked.connect(self._add_files)
        self.add_folder_button.clicked.connect(self._add_folder)
        self.clean_raw_button.clicked.connect(self._clean_selected_raw_sources)
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
        project = self._selected_project()
        if project is None:
            raise RuntimeError("No project selected")
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
        return ProjectConfig(
            project_id=project.project_id,
            name=project.name,
            target_characters=targets,
            extraction_mode=mode,
            source_paths=sources,
            source_processing=self._current_processing_config(),
            raw_cleaned_paths=project.raw_cleaned_paths,
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
        if not self._has_project():
            return
        config = self.current_config()
        self._upsert_project(config)
        self.configSaved.emit(config)

    def _emit_preview(self) -> None:
        if not self._has_project():
            return
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

    def _current_processing_config(self) -> SourceProcessingConfig:
        preset_index = self.processing_preset_combo.currentIndex()
        segment_mode = SourceSegmentMode.TIME if self.segment_mode_combo.currentIndex() == 0 else SourceSegmentMode.COUNT
        return SourceProcessingConfig(
            preset=PROCESSING_PRESETS[preset_index] if 0 <= preset_index < len(PROCESSING_PRESETS) else PROCESSING_PRESETS[0],
            trim_enabled=self.trim_check.isChecked(),
            trim_start=self.trim_start_time.text(),
            trim_end=self.trim_end_time.text(),
            transcode_enabled=self.transcode_check.isChecked(),
            codec=self.codec_combo.currentText(),
            resolution=self.resolution_combo.currentText(),
            segment_enabled=self.segment_check.isChecked(),
            segment_mode=segment_mode,
            segment_time=self.segment_time.text(),
            segment_count=self.segment_count_slider.value(),
        )

    def _apply_processing_config(self, config: SourceProcessingConfig) -> None:
        try:
            preset_index = PROCESSING_PRESETS.index(config.preset)
        except ValueError:
            preset_index = 0
        self.processing_preset_combo.setCurrentIndex(preset_index)
        self.trim_check.setChecked(config.trim_enabled)
        self.trim_start_time.setText(config.trim_start.replace(":", ""))
        self.trim_end_time.setText(config.trim_end.replace(":", ""))
        self.transcode_check.setChecked(config.transcode_enabled)
        self.codec_combo.setCurrentText(config.codec)
        self.resolution_combo.setCurrentText(config.resolution)
        self.segment_check.setChecked(config.segment_enabled)
        self.segment_mode_combo.setCurrentIndex(0 if config.segment_mode == SourceSegmentMode.TIME else 1)
        self.segment_time.setText(config.segment_time.replace(":", ""))
        self.segment_count_slider.setValue(config.segment_count)
        self._sync_processing_options()
        self._sync_segment_mode()

    def _sync_processing_options(self) -> None:
        uses_original = self._uses_original_sources()
        has_project = self._has_project()
        self.processing_preset_combo.setEnabled(has_project)
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
            widget.setEnabled(has_project and not uses_original)
        self.segment_count_label.setEnabled(has_project and not uses_original)
        self._refresh_ffmpeg_state()

    def _sync_segment_mode(self) -> None:
        by_time = self.segment_mode_combo.currentIndex() == 0
        self.segment_time.setVisible(by_time)
        self.segment_count_slider.setVisible(not by_time)
        self.segment_count_label.setVisible(not by_time)

    def _sync_segment_count_label(self, value: int) -> None:
        self.segment_count_label.setText(str(value))

    def _start_source_processing(self) -> None:
        if not self._has_project():
            return
        if self._source_processing_thread is not None:
            return
        config = self.current_config()

        if not self._uses_original_sources() and not has_ffmpeg_binary():
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

        self._source_processing_dialog = SourceProcessingDialog(self)
        self._source_processing_dialog.show()
        self.process_sources_button.setEnabled(False)
        self._source_processing_thread = QThread(self)
        self._source_processing_worker = SourceProcessingWorker(config, self._uses_original_sources())
        self._source_processing_worker.moveToThread(self._source_processing_thread)
        self._source_processing_thread.started.connect(self._source_processing_worker.run)
        self._source_processing_dialog.cancelRequested.connect(self._source_processing_worker.cancel)
        self._source_processing_worker.progressChanged.connect(self._update_source_processing_progress)
        self._source_processing_worker.succeeded.connect(self._finish_source_processing_success)
        self._source_processing_worker.failed.connect(self._finish_source_processing_failure)
        self._source_processing_worker.cancelled.connect(self._finish_source_processing_cancelled)
        self._source_processing_worker.finished.connect(self._source_processing_thread.quit)
        self._source_processing_worker.finished.connect(self._source_processing_worker.deleteLater)
        self._source_processing_thread.finished.connect(self._source_processing_thread.deleteLater)
        self._source_processing_thread.finished.connect(self._clear_source_processing_worker)
        self._source_processing_thread.start()

    def _update_source_processing_progress(self, done: int, total: int, name: str) -> None:
        if self._source_processing_dialog is not None:
            self._source_processing_dialog.set_progress(done, total, name)

    def _finish_source_processing_success(self, config: ProjectConfig, linked_count: int, uses_original_sources: bool) -> None:
        if self._source_processing_dialog is not None:
            self._source_processing_dialog.finish()
        self._upsert_project(config)
        self._refresh_project_sources(config.project_id)
        if uses_original_sources:
            InfoBar.success(
                title=t("project.processing.done.title"),
                content=t("project.processing.done.original", count=linked_count),
                parent=self.window(),
                position=InfoBarPosition.TOP_RIGHT,
                duration=3500,
            )
            return
        InfoBar.info(
            title=t("project.processing.placeholder.title"),
            content=t("project.processing.placeholder.content"),
            parent=self.window(),
            position=InfoBarPosition.TOP_RIGHT,
            duration=4500,
        )

    def _finish_source_processing_failure(self, error: str) -> None:
        if self._source_processing_dialog is not None:
            self._source_processing_dialog.finish()
        InfoBar.warning(
            title=t("project.processing.failure.title"),
            content=t("project.processing.failure.content", error=self._short_error(error)),
            parent=self.window(),
            position=InfoBarPosition.TOP_RIGHT,
            duration=7000,
        )

    def _finish_source_processing_cancelled(self) -> None:
        if self._source_processing_dialog is not None:
            self._source_processing_dialog.finish()
        InfoBar.info(
            title=t("project.processing.cancelled.title"),
            content=t("project.processing.cancelled.content"),
            parent=self.window(),
            position=InfoBarPosition.TOP_RIGHT,
            duration=3000,
        )

    def _clear_source_processing_worker(self) -> None:
        self.process_sources_button.setEnabled(self._has_project())
        self._source_processing_thread = None
        self._source_processing_worker = None
        self._source_processing_dialog = None

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
            self.project_combo.addItem(t("project.empty.placeholder"))
        else:
            for project in self.projects:
                self.project_combo.addItem(project.name)
        self._loading_project = False
        self._sync_project_actions()
        self._load_selected_project()

    def _selected_project(self) -> ProjectConfig | None:
        index = self.project_combo.currentIndex()
        if 0 <= index < len(self.projects):
            return self.projects[index]
        return None

    def _has_project(self) -> bool:
        return bool(self.projects)

    def _sync_project_actions(self) -> None:
        has_project = self._has_project()
        self.project_combo.setEnabled(has_project)
        self.delete_project_button.setEnabled(has_project)
        self.targets_edit.setEnabled(has_project)
        self.mode_combo.setEnabled(has_project)
        self.add_file_button.setEnabled(has_project)
        self.add_folder_button.setEnabled(has_project)
        self.remove_source_button.setEnabled(has_project)
        self.clean_raw_button.setEnabled(has_project)
        self.sources_list.setEnabled(has_project)
        self.processing_preset_combo.setEnabled(has_project)
        self.trim_check.setEnabled(has_project)
        self.transcode_check.setEnabled(has_project)
        self.segment_check.setEnabled(has_project)
        self.process_sources_button.setEnabled(has_project)
        self.save_button.setEnabled(has_project)
        self.preview_button.setEnabled(has_project)
        self._sync_processing_options()

    def _load_selected_project(self) -> None:
        if self._loading_project:
            return
        project = self._selected_project()
        if project is None:
            self.targets_edit.clear()
            self.sources_list.clear()
            self.clear_events()
            return
        self.targets_edit.setText(", ".join(project.target_characters))
        self.mode_combo.setCurrentIndex(0 if project.extraction_mode == ExtractionMode.PREVIEW else 1)
        self._apply_processing_config(project.source_processing)
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
        project = ProjectConfig(project_id=project_id, name=name)
        create_project_config(project)
        self.projects.insert(0, project)
        self._refresh_project_combo()
        self.project_combo.setCurrentIndex(0)

    def _delete_project(self) -> None:
        index = self.project_combo.currentIndex()
        if not 0 <= index < len(self.projects):
            return

        project = self.projects[index]
        dialog = MessageBox(
            t("project.delete.dialog.title"),
            t("project.delete.dialog.content", name=project.name),
            self.window(),
        )
        dialog.yesButton.setText(t("project.delete.dialog.confirm"))
        dialog.cancelButton.setText(t("project.delete.dialog.cancel"))
        if not dialog.exec():
            return

        delete_project_config(project.project_id)
        del self.projects[index]
        self._refresh_project_combo()
        if self.projects:
            self.project_combo.setCurrentIndex(min(index, len(self.projects) - 1))
        InfoBar.success(
            title=t("project.delete.success.title"),
            content=t("project.delete.success.content", name=project.name),
            parent=self.window(),
            position=InfoBarPosition.TOP_RIGHT,
            duration=3500,
        )

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
        display_text = self._source_display_text(source_path, source_kind)
        status = self._source_status(source_path, source_kind)
        item = QListWidgetItem("")
        item.setSizeHint(QSize(0, 26))
        item.setData(SOURCE_KIND_ROLE, source_kind)
        item.setData(SOURCE_PATH_ROLE, source_path)
        item.setData(SOURCE_STATUS_ROLE, status)
        item.setToolTip(t(f"project.source.status.{status}"))
        self.sources_list.addItem(item)
        self.sources_list.setItemWidget(item, SourceListRow(display_text, status, self.sources_list))

    def _source_display_text(self, source_path: str, source_kind: str) -> str:
        if source_kind == SOURCE_KIND_PROJECT:
            project = self._selected_project()
            if project is not None:
                raw_root = project_paths(project.project_id).raw
                try:
                    return Path(source_path).resolve().relative_to(raw_root.resolve()).as_posix()
                except ValueError:
                    return source_path
        return source_path

    def _source_status(self, source_path: str, source_kind: str) -> str:
        project = self._selected_project()
        if project is None:
            return SOURCE_STATUS_NEW
        paths = project_paths(project.project_id)
        if source_kind == SOURCE_KIND_PROJECT:
            raw_source = Path(source_path)
            material_target = self._material_target_for_raw(paths.raw, paths.materials, raw_source)
            return SOURCE_STATUS_PROCESSED if material_target.exists() or material_target.is_symlink() else SOURCE_STATUS_STALE

        source = Path(source_path).expanduser()
        raw_pairs = source_raw_target_pairs(project.project_id, [source_path])
        raw_targets = [raw_target for _, raw_target in raw_pairs]
        cleaned_paths = set(project.raw_cleaned_paths)
        if not raw_targets:
            return SOURCE_STATUS_NEW
        if all(self._raw_relative_path(paths.raw, raw_target) in cleaned_paths for raw_target in raw_targets):
            material_targets = [
                self._material_target_for_raw(paths.raw, paths.materials, raw_target)
                for raw_target in raw_targets
            ]
            if material_targets and all(material_target.exists() for material_target in material_targets):
                return SOURCE_STATUS_RAW_CLEANED
        existing_raw_targets = [raw_target for raw_target in raw_targets if raw_target.exists()]
        if not existing_raw_targets:
            return SOURCE_STATUS_NEW
        if len(existing_raw_targets) != len(raw_targets):
            return SOURCE_STATUS_STALE
        if self._external_source_is_newer(source, raw_pairs):
            return SOURCE_STATUS_STALE
        material_targets = [
            self._material_target_for_raw(paths.raw, paths.materials, raw_target)
            for raw_target in existing_raw_targets
        ]
        if material_targets and all(material_target.exists() or material_target.is_symlink() for material_target in material_targets):
            return SOURCE_STATUS_PROCESSED
        return SOURCE_STATUS_STALE

    def _material_target_for_raw(self, raw_root: Path, materials_root: Path, raw_source: Path) -> Path:
        try:
            relative_path = raw_source.resolve().relative_to(raw_root.resolve())
        except ValueError:
            return materials_root / raw_source.name
        return materials_root / relative_path

    def _raw_relative_path(self, raw_root: Path, raw_source: Path) -> str:
        try:
            return raw_source.resolve().relative_to(raw_root.resolve()).as_posix()
        except ValueError:
            return raw_source.name

    def _external_source_is_newer(self, source: Path, raw_pairs: list[tuple[Path, Path]]) -> bool:
        try:
            if source.is_file():
                if not raw_pairs:
                    return False
                return source.stat().st_mtime > raw_pairs[0][1].stat().st_mtime
            if source.is_dir():
                return any(source_path.stat().st_mtime > raw_target.stat().st_mtime for source_path, raw_target in raw_pairs)
        except OSError:
            return False
        return False

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
        external_paths = [
            self.sources_list.item(index).data(SOURCE_PATH_ROLE)
            for index in range(self.sources_list.count())
            if self.sources_list.item(index).data(SOURCE_KIND_ROLE) == SOURCE_KIND_EXTERNAL
            and self.sources_list.item(index).data(SOURCE_PATH_ROLE)
        ]
        shadowed_raw_paths = {path.resolve() for path in source_raw_targets(project_id, external_paths)}
        existing = {
            self.sources_list.item(index).data(SOURCE_PATH_ROLE)
            for index in range(self.sources_list.count())
        }
        for source_path in self._project_source_paths(project_id):
            if source_path.resolve() in shadowed_raw_paths:
                continue
            source_text = str(source_path)
            if source_text not in existing:
                self._add_source_item(source_text, SOURCE_KIND_PROJECT)
                existing.add(source_text)
        self._refresh_source_status_rows()

    def _refresh_source_status_rows(self) -> None:
        for row in range(self.sources_list.count()):
            item = self.sources_list.item(row)
            source_path = item.data(SOURCE_PATH_ROLE) or item.text()
            source_kind = item.data(SOURCE_KIND_ROLE)
            status = self._source_status(source_path, source_kind)
            display_text = self._source_display_text(source_path, source_kind)
            item.setText("")
            item.setData(SOURCE_STATUS_ROLE, status)
            item.setToolTip(t(f"project.source.status.{status}"))
            self.sources_list.setItemWidget(item, SourceListRow(display_text, status, self.sources_list))

    def _clean_selected_raw_sources(self) -> None:
        project = self._selected_project()
        if project is None:
            return
        raw_sources = self._selected_raw_sources(project.project_id)
        if not raw_sources:
            return

        dialog = MessageBox(
            t("project.source.cleanRaw.dialog.title"),
            t("project.source.cleanRaw.dialog.content"),
            self.window(),
        )
        dialog.yesButton.setText(t("project.source.cleanRaw.dialog.confirm"))
        dialog.cancelButton.setText(t("project.source.cleanRaw.dialog.cancel"))
        if not dialog.exec():
            return

        cleaned_paths = clean_raw_sources(project.project_id, raw_sources)
        if not cleaned_paths:
            return
        merged_paths = sorted(set(project.raw_cleaned_paths).union(cleaned_paths))
        updated_project = project.model_copy(update={"raw_cleaned_paths": merged_paths})
        self._upsert_project(updated_project)
        save_project_config(self.current_config())
        self._refresh_project_sources(project.project_id)
        InfoBar.success(
            title=t("project.source.cleanRaw.success.title"),
            content=t("project.source.cleanRaw.success.content", count=len(cleaned_paths)),
            parent=self.window(),
            position=InfoBarPosition.TOP_RIGHT,
            duration=4000,
        )

    def _selected_raw_sources(self, project_id: str) -> list[Path]:
        raw_sources: list[Path] = []
        for item in self.sources_list.selectedItems():
            source_path = item.data(SOURCE_PATH_ROLE)
            source_kind = item.data(SOURCE_KIND_ROLE)
            if not source_path:
                continue
            if source_kind == SOURCE_KIND_EXTERNAL:
                raw_sources.extend(path for path in source_raw_targets(project_id, [source_path]) if path.exists())
            elif source_kind == SOURCE_KIND_PROJECT:
                raw_source = Path(source_path)
                if raw_source.exists():
                    raw_sources.append(raw_source)
        return raw_sources

    def _remove_selected_sources(self) -> None:
        project = self._selected_project()
        if project is None:
            return
        removed_any = False
        for item in self.sources_list.selectedItems():
            source_kind = item.data(SOURCE_KIND_ROLE)
            source_path = item.data(SOURCE_PATH_ROLE)
            if not source_path:
                continue
            if source_kind == SOURCE_KIND_EXTERNAL:
                remove_project_sources(project.project_id, [source_path])
            elif source_kind == SOURCE_KIND_PROJECT:
                remove_raw_sources(project.project_id, [Path(source_path)])
            else:
                continue
            row = self.sources_list.row(item)
            self.sources_list.takeItem(row)
            removed_any = True
        if removed_any:
            config = self.current_config()
            self._upsert_project(config)
            save_project_config(config)
            self._refresh_project_sources(project.project_id)
            InfoBar.success(
                title=t("project.source.remove.success.title"),
                content=t("project.source.remove.success.content"),
                parent=self.window(),
                position=InfoBarPosition.TOP_RIGHT,
                duration=3000,
            )

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
