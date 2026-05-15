from __future__ import annotations

import logging

from PyQt6.QtCore import QObject, QThread, QSize, pyqtSignal
from PyQt6.QtGui import QIcon
from qfluentwidgets import (
    FluentIcon as FIF,
    FluentWindow,
    InfoBar,
    InfoBarPosition,
    MessageBox,
    NavigationItemPosition,
)

from core.compiler import compile_character_state, compile_preview_character_state_from_knowledge_base
from core.extractor import ExtractionStoppedError, Extractor, PREVIEW_MIN_OUTPUT_TOKENS_PER_MINUTE
from core.generator import render_profile_markdown
from core.models import ExtractionMode, ProjectConfig
from gui.pages.about_page import AboutPage
from gui.pages.model_page import ModelPage
from gui.pages.output_page import OutputPage
from gui.pages.prompt_page import PromptPage
from gui.pages.project_page import ProjectPage
from gui.pages.settings_page import SettingsPage
from res import APP_ICON_PATH
from utils.i18n import t
from utils.logging_middleware import apply_log_level_preference
from utils.startup_middleware import StartupWarmupSnapshot
from utils.cloud_model_presets import CloudModelPreset
from utils.state_manager import save_project_config
from utils.theme import apply_theme_preference


LOGGER = logging.getLogger(__name__)


class PreviewWorker(QObject):
    insightGenerated = pyqtSignal(dict)
    progressChanged = pyqtSignal(int)
    tokenUsageChanged = pyqtSignal(dict)
    succeeded = pyqtSignal(str)
    failed = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(
        self,
        extractor: Extractor,
        config: ProjectConfig,
        cloud_preset: CloudModelPreset | None = None,
    ) -> None:
        super().__init__()
        self.extractor = extractor
        self.config = config
        self.cloud_preset = cloud_preset

    def run(self) -> None:
        try:
            content = self.extractor.run_preview_streaming(
                self.config,
                cloud_preset=self.cloud_preset,
                emit_event=lambda event: self.insightGenerated.emit(event),
                emit_progress=lambda value: self.progressChanged.emit(value),
                emit_token_usage=lambda usage: self.tokenUsageChanged.emit(usage),
            )
            if not content.strip():
                self.failed.emit(t("extractor.chunk.noChunkJson"))
                return
            self.succeeded.emit(content)
        except ExtractionStoppedError as exc:
            LOGGER.warning("Preview worker stopped; reason=%s", exc)
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Preview worker failed", exc_info=True)
            self.failed.emit(str(exc))
        finally:
            self.finished.emit()


class FullExtractionWorker(QObject):
    insightGenerated = pyqtSignal(dict)
    progressChanged = pyqtSignal(int)
    tokenUsageChanged = pyqtSignal(dict)
    succeeded = pyqtSignal(int)
    failed = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(
        self,
        extractor: Extractor,
        config: ProjectConfig,
        cloud_preset: CloudModelPreset | None = None,
    ) -> None:
        super().__init__()
        self.extractor = extractor
        self.config = config
        self.cloud_preset = cloud_preset

    def run(self) -> None:
        try:
            chunks = self.extractor.run_full_extraction_streaming(
                self.config,
                cloud_preset=self.cloud_preset,
                emit_event=lambda event: self.insightGenerated.emit(event),
                emit_progress=lambda value: self.progressChanged.emit(value),
                emit_token_usage=lambda usage: self.tokenUsageChanged.emit(usage),
            )
            self.succeeded.emit(len(chunks))
        except ExtractionStoppedError as exc:
            LOGGER.warning("Full extraction worker stopped; reason=%s", exc)
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Full extraction worker failed", exc_info=True)
            self.failed.emit(str(exc))
        finally:
            self.finished.emit()


class MainWindow(FluentWindow):
    def __init__(self, startup_snapshot: StartupWarmupSnapshot | None = None) -> None:
        super().__init__()
        LOGGER.info("Main window initialization started")
        self.setWindowTitle("CharaPicker")
        self._apply_window_icon()
        self.resize(1180, 760)
        self.setMinimumSize(QSize(980, 640))

        self.extractor = Extractor(self)
        self._extraction_thread: QThread | None = None
        self._preview_worker: PreviewWorker | None = None
        self._full_extraction_worker: FullExtractionWorker | None = None

        self.project_page = ProjectPage(
            self,
            initial_projects=startup_snapshot.project_configs if startup_snapshot else None,
            initial_encoder_options=startup_snapshot.encoder_options if startup_snapshot else None,
            initial_ffmpeg_ready=startup_snapshot.ffmpeg_ready if startup_snapshot else None,
        )
        self.output_page = OutputPage(self)
        self.model_page = ModelPage(
            self,
            initial_llamacpp_ready=startup_snapshot.llamacpp_ready if startup_snapshot else None,
            initial_local_models=startup_snapshot.local_models if startup_snapshot else None,
            initial_cloud_presets=startup_snapshot.cloud_presets if startup_snapshot else None,
        )
        self.prompt_page = PromptPage(self)
        self.about_page = AboutPage(self)
        self.settings_page = SettingsPage(self)

        self._init_navigation()
        self._connect_signals()
        LOGGER.info("Main window initialization finished")

    def _apply_window_icon(self) -> None:
        icon = QIcon(str(APP_ICON_PATH))
        if not icon.isNull():
            self.setWindowIcon(icon)

    def _init_navigation(self) -> None:
        self.addSubInterface(self.project_page, FIF.HOME, t("app.nav.home"))
        self.addSubInterface(self.output_page, FIF.DOCUMENT, t("app.nav.output"))
        self.addSubInterface(self.model_page, FIF.ROBOT, t("app.nav.model"))
        self.addSubInterface(self.prompt_page, FIF.EDIT, t("app.nav.prompts"))
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
        self.project_page.extractionRequested.connect(self.run_extraction)
        self.project_page.configSaved.connect(self.save_config)
        self.settings_page.languageChanged.connect(self.show_language_changed)
        self.settings_page.themeChanged.connect(self.apply_theme_changed)
        self.settings_page.logLevelChanged.connect(self.apply_log_level_changed)

    def save_config(self, config: ProjectConfig) -> None:
        LOGGER.info("Saving project config from UI; project_id=%s", config.project_id)
        path = save_project_config(config)
        InfoBar.success(
            title=t("app.config.saved.title"),
            content=t("app.config.saved.content", path=path),
            parent=self,
            position=InfoBarPosition.TOP_RIGHT,
            duration=3000,
        )

    def _confirm_low_preview_token_budget(self, preset: CloudModelPreset) -> bool:
        if preset.max_output_tokens >= PREVIEW_MIN_OUTPUT_TOKENS_PER_MINUTE:
            return True
        dialog = MessageBox(
            t("app.preview.lowTokenBudget.dialog.title"),
            t(
                "app.preview.lowTokenBudget.dialog.content",
                tokens_per_minute=preset.max_output_tokens,
                minimum=PREVIEW_MIN_OUTPUT_TOKENS_PER_MINUTE,
            ),
            self,
        )
        dialog.yesButton.setText(t("app.preview.lowTokenBudget.dialog.continue"))
        dialog.cancelButton.setText(t("app.preview.lowTokenBudget.dialog.cancel"))
        confirmed = bool(dialog.exec())
        LOGGER.info(
            "Low preview output token budget confirmation resolved; "
            "tokens_per_minute=%s minimum=%s confirmed=%s",
            preset.max_output_tokens,
            PREVIEW_MIN_OUTPUT_TOKENS_PER_MINUTE,
            confirmed,
        )
        return confirmed

    def run_extraction(self, config: ProjectConfig) -> None:
        if config.extraction_mode == ExtractionMode.FULL:
            self.run_full_extraction(config)
            return
        self.run_preview(config)

    def run_preview(self, config: ProjectConfig) -> None:
        if self._extraction_thread is not None:
            return
        LOGGER.info(
            "Preview requested; project_id=%s targets=%s sources=%s",
            config.project_id,
            len(config.target_characters),
            len(config.source_paths),
        )
        cloud_preset = self.model_page.current_cloud_video_preset()
        if cloud_preset is not None and not self._confirm_low_preview_token_budget(cloud_preset):
            return
        self.switchTo(self.project_page)
        self.project_page.clear_events()
        self.project_page.set_extraction_running(True)
        if cloud_preset is not None:
            LOGGER.info(
                "Preview will use current cloud UI settings; preset=%s provider=%s model=%s "
                "tokens_per_minute=%s",
                cloud_preset.name,
                cloud_preset.provider,
                cloud_preset.model_name,
                cloud_preset.max_output_tokens,
            )
        self._extraction_thread = QThread(self)
        self._preview_worker = PreviewWorker(self.extractor, config, cloud_preset)
        self._preview_worker.moveToThread(self._extraction_thread)
        self._extraction_thread.started.connect(self._preview_worker.run)
        self._preview_worker.insightGenerated.connect(self.project_page.append_event)
        self._preview_worker.progressChanged.connect(self.project_page.set_progress)
        self._preview_worker.tokenUsageChanged.connect(self.project_page.set_token_usage)
        self._preview_worker.succeeded.connect(lambda _content: self._on_preview_succeeded(config))
        self._preview_worker.failed.connect(self._on_preview_failed)
        self._preview_worker.finished.connect(self._clear_extraction_worker)
        self._preview_worker.finished.connect(self._extraction_thread.quit)
        self._preview_worker.finished.connect(self._preview_worker.deleteLater)
        self._extraction_thread.finished.connect(self._extraction_thread.deleteLater)
        self._extraction_thread.start()

    def run_full_extraction(self, config: ProjectConfig) -> None:
        if self._extraction_thread is not None:
            return
        LOGGER.info(
            "Full extraction requested from UI; project_id=%s targets=%s sources=%s",
            config.project_id,
            len(config.target_characters),
            len(config.source_paths),
        )
        cloud_preset = self.model_page.current_cloud_video_preset()
        self.switchTo(self.project_page)
        self.project_page.clear_events()
        self.project_page.set_extraction_running(True)
        if cloud_preset is not None:
            LOGGER.info(
                "Full extraction will use current cloud UI settings; preset=%s provider=%s model=%s "
                "tokens_per_minute=%s",
                cloud_preset.name,
                cloud_preset.provider,
                cloud_preset.model_name,
                cloud_preset.max_output_tokens,
            )
        self._extraction_thread = QThread(self)
        self._full_extraction_worker = FullExtractionWorker(self.extractor, config, cloud_preset)
        self._full_extraction_worker.moveToThread(self._extraction_thread)
        self._extraction_thread.started.connect(self._full_extraction_worker.run)
        self._full_extraction_worker.insightGenerated.connect(self.project_page.append_event)
        self._full_extraction_worker.progressChanged.connect(self.project_page.set_progress)
        self._full_extraction_worker.tokenUsageChanged.connect(self.project_page.set_token_usage)
        self._full_extraction_worker.succeeded.connect(lambda count: self._on_full_extraction_succeeded(config, count))
        self._full_extraction_worker.failed.connect(self._on_full_extraction_failed)
        self._full_extraction_worker.finished.connect(self._clear_extraction_worker)
        self._full_extraction_worker.finished.connect(self._extraction_thread.quit)
        self._full_extraction_worker.finished.connect(self._full_extraction_worker.deleteLater)
        self._extraction_thread.finished.connect(self._extraction_thread.deleteLater)
        self._extraction_thread.start()

    def _on_preview_succeeded(self, config: ProjectConfig) -> None:
        first_character = config.target_characters[0] if config.target_characters else t("app.preview.defaultCharacter")
        try:
            state = compile_preview_character_state_from_knowledge_base(config.project_id, first_character)
        except Exception:
            LOGGER.warning(
                "Knowledge-base-backed preview output failed; project_id=%s character=%s",
                config.project_id,
                first_character,
                exc_info=True,
            )
            state = None
        if state is None:
            state = compile_character_state(first_character)
        self.output_page.set_markdown(render_profile_markdown(state))
        InfoBar.info(
            title=t("app.preview.done.title"),
            content=t("app.preview.done.content"),
            parent=self,
            position=InfoBarPosition.TOP_RIGHT,
            duration=3500,
        )
        LOGGER.info("Preview completed; project_id=%s", config.project_id)

    def _on_preview_failed(self, error: str) -> None:
        InfoBar.warning(
            title=t("project.processing.failure.title"),
            content=t("project.processing.failure.content", error=error),
            parent=self,
            position=InfoBarPosition.TOP_RIGHT,
            duration=5000,
        )

    def _on_full_extraction_succeeded(self, config: ProjectConfig, chunk_count: int) -> None:
        InfoBar.info(
            title=t("app.full.done.title"),
            content=t("app.full.done.content", project_id=config.project_id, count=chunk_count),
            parent=self,
            position=InfoBarPosition.TOP_RIGHT,
            duration=4500,
        )
        LOGGER.info(
            "Full extraction completed from UI; project_id=%s chunk_count=%s",
            config.project_id,
            chunk_count,
        )

    def _on_full_extraction_failed(self, error: str) -> None:
        InfoBar.warning(
            title=t("app.full.failed.title"),
            content=t("app.full.failed.content", error=error),
            parent=self,
            position=InfoBarPosition.TOP_RIGHT,
            duration=6000,
        )

    def _clear_extraction_worker(self) -> None:
        self.project_page.set_extraction_running(False)
        self._preview_worker = None
        self._full_extraction_worker = None
        self._extraction_thread = None

    def show_language_changed(self, _locale: str) -> None:
        LOGGER.info("Language preference changed; locale=%s", _locale)
        InfoBar.info(
            title=t("settings.language.changed.title"),
            content=t("settings.language.changed.content"),
            parent=self,
            position=InfoBarPosition.TOP_RIGHT,
            duration=4500,
        )

    def apply_theme_changed(self, theme: str) -> None:
        LOGGER.info("Theme preference changed; theme=%s", theme)
        apply_theme_preference(theme)
        self.project_page.apply_theme_colors()
        InfoBar.info(
            title=t("settings.theme.changed.title"),
            content=t("settings.theme.changed.content"),
            parent=self,
            position=InfoBarPosition.TOP_RIGHT,
            duration=3000,
        )

    def apply_log_level_changed(self, level: str) -> None:
        apply_log_level_preference()
        LOGGER.info("Log level preference changed; level=%s", level)
