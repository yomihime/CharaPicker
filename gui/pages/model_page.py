from __future__ import annotations

import logging
from pathlib import Path

from PyQt6.QtCore import QObject, QThread, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    ComboBox,
    FluentIcon as FIF,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    ListWidget,
    PasswordLineEdit,
    PlainTextEdit,
    ProgressBar,
    PushButton,
    SearchLineEdit,
    SubtitleLabel,
    SwitchButton,
    TransparentToolButton,
)

from utils.cloud_models import CloudModelListError, fetch_openai_compatible_models
from utils.cloud_model_presets import (
    CloudModelPreset,
    delete_cloud_model_preset,
    load_cloud_model_presets,
    upsert_cloud_model_preset,
)
from utils.env_manager import has_llamacpp_binary
from utils.i18n import t
from utils.llamacpp_downloader import (
    LlamaCppDownloadCancelled,
    LlamaCppDownloadError,
    download_and_install_llamacpp,
)
from utils.paths import APP_ROOT


MODELS_ROOT = APP_ROOT / "models"
LOCAL_MODEL_SUFFIXES = {".bin", ".gguf", ".model", ".onnx", ".pt", ".pth", ".safetensors"}
LOGGER = logging.getLogger(__name__)


class LlamaCppDownloadWorker(QObject):
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
        LOGGER.info("llama.cpp download worker started")
        try:
            binary = download_and_install_llamacpp(
                progress=lambda value, step: self.progressChanged.emit(value, step),
                cancelled=lambda: self._cancel_requested,
            )
        except LlamaCppDownloadCancelled:
            LOGGER.info("llama.cpp download cancelled")
            self.cancelled.emit()
        except LlamaCppDownloadError as exc:
            LOGGER.warning("llama.cpp download failed", exc_info=True)
            self.failed.emit(str(exc))
        else:
            LOGGER.info("llama.cpp download succeeded; binary=%s", binary)
            self.succeeded.emit(str(binary))
        finally:
            self.finished.emit()


class CloudModelListWorker(QObject):
    succeeded = pyqtSignal(list)
    failed = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, base_url: str, api_key: str) -> None:
        super().__init__()
        self.base_url = base_url
        self.api_key = api_key

    def run(self) -> None:
        LOGGER.info("Cloud model list worker started; base_url=%s", self.base_url)
        try:
            models = fetch_openai_compatible_models(self.base_url, self.api_key)
        except CloudModelListError as exc:
            LOGGER.warning("Cloud model list worker failed; base_url=%s", self.base_url, exc_info=True)
            self.failed.emit(str(exc))
        else:
            LOGGER.info("Cloud model list worker succeeded; base_url=%s count=%s", self.base_url, len(models))
            self.succeeded.emit(models)
        finally:
            self.finished.emit()


class LlamaCppDownloadDialog(QDialog):
    cancelRequested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._finished = False
        self._cancel_requested = False
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle(t("model.local.download.title"))
        self.setModal(True)
        self.resize(520, 210)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        card = CardWidget(self)
        card.setStyleSheet("CardWidget { background-color: palette(window); }")
        card.setBorderRadius(8)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(14)

        header = QHBoxLayout()
        header.addWidget(SubtitleLabel(t("model.local.download.title"), card))
        header.addStretch(1)
        self.close_button = TransparentToolButton(FIF.CLOSE, card)
        header.addWidget(self.close_button)
        layout.addLayout(header)

        self.status_label = BodyLabel(t("model.local.download.progress.release"), card)
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.progress_bar = ProgressBar(card)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        actions = QHBoxLayout()
        actions.addStretch(1)
        self.cancel_button = PushButton(t("model.local.download.cancel"), card)
        actions.addWidget(self.cancel_button)
        layout.addLayout(actions)

        root.addWidget(card)
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
        self.status_label.setText(t("model.local.download.progress.canceling"))
        self.cancelRequested.emit()

    def mark_finished(self) -> None:
        self._finished = True

    def reject(self) -> None:
        if self._finished:
            super().reject()
            return
        self.request_cancel()


class CloudModelSelectDialog(QDialog):
    modelSelected = pyqtSignal(str)

    def __init__(self, models: list[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._models = models
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle(t("model.cloud.models.title"))
        self.setModal(True)
        self.resize(560, 460)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        card = CardWidget(self)
        card.setStyleSheet("CardWidget { background-color: palette(window); }")
        card.setBorderRadius(8)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(12)

        header = QHBoxLayout()
        header.addWidget(SubtitleLabel(t("model.cloud.models.title"), card))
        header.addStretch(1)
        close_button = TransparentToolButton(FIF.CLOSE, card)
        header.addWidget(close_button)
        layout.addLayout(header)

        self.search_edit = SearchLineEdit(card)
        self.search_edit.setPlaceholderText(t("model.cloud.models.search.placeholder"))
        layout.addWidget(self.search_edit)

        self.model_list = ListWidget(card)
        self.model_list.setMinimumHeight(260)
        layout.addWidget(self.model_list, 1)

        actions = QHBoxLayout()
        actions.addStretch(1)
        cancel_button = PushButton(t("model.cloud.models.cancel"), card)
        select_button = PushButton(t("model.cloud.models.select"), card)
        actions.addWidget(cancel_button)
        actions.addWidget(select_button)
        layout.addLayout(actions)

        root.addWidget(card)
        close_button.clicked.connect(self.reject)
        cancel_button.clicked.connect(self.reject)
        select_button.clicked.connect(self._select_current)
        self.search_edit.textChanged.connect(self._filter_models)
        self.model_list.itemDoubleClicked.connect(lambda _item: self._select_current())
        self._filter_models("")

    def _select_current(self) -> None:
        current_item = self.model_list.currentItem()
        if current_item is None:
            return
        self.modelSelected.emit(current_item.text())
        self.accept()

    def _filter_models(self, keyword: str) -> None:
        keyword = keyword.strip().lower()
        self.model_list.clear()
        for model in self._models:
            if not keyword or keyword in model.lower():
                self.model_list.addItem(model)
        if self.model_list.count() > 0:
            self.model_list.setCurrentRow(0)


class ModelPage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("modelPage")
        self._download_thread: QThread | None = None
        self._download_worker: LlamaCppDownloadWorker | None = None
        self._download_dialog: LlamaCppDownloadDialog | None = None
        self._cloud_models_thread: QThread | None = None
        self._cloud_models_worker: CloudModelListWorker | None = None
        self._cloud_presets: list[CloudModelPreset] = []
        self._loading_cloud_preset = False

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(18)

        root.addWidget(SubtitleLabel(t("model.title"), self))

        mode_card = CardWidget(self)
        mode_card.setBorderRadius(8)
        mode_layout = QHBoxLayout(mode_card)
        mode_layout.setContentsMargins(20, 18, 20, 20)
        mode_layout.setSpacing(12)
        mode_layout.addWidget(BodyLabel(t("model.mode.local"), mode_card))

        self.cloud_mode_switch = SwitchButton(mode_card)
        mode_layout.addWidget(self.cloud_mode_switch)
        mode_layout.addWidget(BodyLabel(t("model.mode.cloud"), mode_card))
        mode_layout.addStretch(1)
        root.addWidget(mode_card)

        self.local_card = CardWidget(self)
        self.local_card.setBorderRadius(8)
        local_form = QFormLayout(self.local_card)
        local_form.setContentsMargins(20, 18, 20, 20)
        local_form.setSpacing(12)

        local_model_row = QHBoxLayout()
        self.local_model_combo = ComboBox(self.local_card)
        self.refresh_local_models_button = PushButton(t("model.local.models.refresh"), self.local_card)
        local_model_row.addWidget(self.local_model_combo, 1)
        local_model_row.addWidget(self.refresh_local_models_button)

        self.local_runner_combo = ComboBox(self.local_card)
        self.local_runner_combo.addItem(t("model.local.runner.llama"))

        runner_row = QHBoxLayout()
        runner_row.addWidget(self.local_runner_combo, 1)

        self.download_llamacpp_button = PushButton(t("model.local.downloadLlamacpp"), self.local_card)
        self.download_llamacpp_button.setVisible(not has_llamacpp_binary())
        runner_row.addWidget(self.download_llamacpp_button)

        self.use_cache = SwitchButton(self.local_card)
        self.use_cache.setChecked(True)

        self.test_local_model_button = PushButton(t("model.local.test"), self.local_card)
        self.local_test_result = PlainTextEdit(self.local_card)
        self.local_test_result.setPlaceholderText(t("model.local.test.placeholder"))
        self.local_test_result.setReadOnly(True)
        self.local_test_result.setMinimumHeight(96)

        local_form.addRow(t("model.local.select"), local_model_row)
        local_form.addRow(t("model.local.runner"), runner_row)
        local_form.addRow(t("model.local.cache"), self.use_cache)
        local_form.addRow(t("model.local.test.action"), self.test_local_model_button)
        local_form.addRow(t("model.local.test.result"), self.local_test_result)
        root.addWidget(self.local_card)

        self.cloud_card = CardWidget(self)
        self.cloud_card.setBorderRadius(8)
        cloud_form = QFormLayout(self.cloud_card)
        cloud_form.setContentsMargins(20, 18, 20, 20)
        cloud_form.setSpacing(12)

        preset_row = QHBoxLayout()
        self.cloud_preset_combo = ComboBox(self.cloud_card)
        self.cloud_preset_name = LineEdit(self.cloud_card)
        self.cloud_preset_name.setPlaceholderText(t("model.cloud.preset.name.placeholder"))
        self.save_cloud_preset_button = PushButton(t("model.cloud.preset.save"), self.cloud_card)
        self.delete_cloud_preset_button = PushButton(t("model.cloud.preset.delete"), self.cloud_card)
        preset_row.addWidget(self.cloud_preset_combo, 1)
        preset_row.addWidget(self.cloud_preset_name, 1)
        preset_row.addWidget(self.save_cloud_preset_button)
        preset_row.addWidget(self.delete_cloud_preset_button)

        self.cloud_provider_combo = ComboBox(self.cloud_card)
        self.cloud_provider_combo.addItems(
            [
                t("model.cloud.provider.openaiCompatible"),
                t("model.cloud.provider.custom"),
            ]
        )

        self.cloud_base_url = LineEdit(self.cloud_card)
        self.cloud_base_url.setPlaceholderText(t("model.cloud.baseUrl.placeholder"))

        self.cloud_api_key = PasswordLineEdit(self.cloud_card)
        self.cloud_api_key.setPlaceholderText(t("model.cloud.apiKey.placeholder"))

        self.cloud_model_name = LineEdit(self.cloud_card)
        self.cloud_model_name.setPlaceholderText(t("model.cloud.modelName.placeholder"))
        model_name_row = QHBoxLayout()
        model_name_row.addWidget(self.cloud_model_name, 1)
        self.fetch_cloud_models_button = PushButton(t("model.cloud.models.fetch"), self.cloud_card)
        model_name_row.addWidget(self.fetch_cloud_models_button)

        self.test_cloud_model_button = PushButton(t("model.cloud.test"), self.cloud_card)
        self.cloud_test_result = PlainTextEdit(self.cloud_card)
        self.cloud_test_result.setPlaceholderText(t("model.cloud.test.placeholder"))
        self.cloud_test_result.setReadOnly(True)
        self.cloud_test_result.setMinimumHeight(96)

        cloud_form.addRow(t("model.cloud.preset"), preset_row)
        cloud_form.addRow(t("model.cloud.provider"), self.cloud_provider_combo)
        cloud_form.addRow(t("model.cloud.baseUrl"), self.cloud_base_url)
        cloud_form.addRow(t("model.cloud.apiKey"), self.cloud_api_key)
        cloud_form.addRow(t("model.cloud.modelName"), model_name_row)
        cloud_form.addRow(t("model.cloud.test.action"), self.test_cloud_model_button)
        cloud_form.addRow(t("model.cloud.test.result"), self.cloud_test_result)
        root.addWidget(self.cloud_card)

        root.addStretch(1)

        self.cloud_mode_switch.checkedChanged.connect(self._set_cloud_mode)
        self.download_llamacpp_button.clicked.connect(self._download_llamacpp)
        self.refresh_local_models_button.clicked.connect(self._refresh_local_models)
        self.test_local_model_button.clicked.connect(self._fake_test_local_model)
        self.fetch_cloud_models_button.clicked.connect(self._fetch_cloud_models)
        self.test_cloud_model_button.clicked.connect(self._fake_test_cloud_model)
        self.cloud_preset_combo.currentIndexChanged.connect(self._load_selected_cloud_preset)
        self.save_cloud_preset_button.clicked.connect(self._save_current_cloud_preset)
        self.delete_cloud_preset_button.clicked.connect(self._delete_selected_cloud_preset)
        self._refresh_local_models()
        self._refresh_cloud_presets()
        self._set_cloud_mode(False)

    def _set_cloud_mode(self, enabled: bool) -> None:
        LOGGER.info("Model page mode changed; cloud_enabled=%s", enabled)
        self.local_card.setVisible(not enabled)
        self.cloud_card.setVisible(enabled)

    def _download_llamacpp(self) -> None:
        if self._download_thread is not None:
            LOGGER.info("llama.cpp download ignored because a download is already running")
            return

        LOGGER.info("llama.cpp download requested")
        self._download_dialog = LlamaCppDownloadDialog(self)
        self._download_dialog.show()

        self.download_llamacpp_button.setEnabled(False)
        self._download_thread = QThread(self)
        self._download_worker = LlamaCppDownloadWorker()
        self._download_worker.moveToThread(self._download_thread)
        self._download_thread.started.connect(self._download_worker.run)
        self._download_dialog.cancelRequested.connect(self._download_worker.cancel)
        self._download_worker.progressChanged.connect(self._update_download_progress)
        self._download_worker.succeeded.connect(self._finish_download_success)
        self._download_worker.failed.connect(self._finish_download_failure)
        self._download_worker.cancelled.connect(self._finish_download_cancelled)
        self._download_worker.finished.connect(self._download_thread.quit)
        self._download_worker.finished.connect(self._download_worker.deleteLater)
        self._download_thread.finished.connect(self._download_thread.deleteLater)
        self._download_thread.finished.connect(self._clear_download_worker)
        self._download_thread.start()

    def _update_download_progress(self, value: int, step: str) -> None:
        if self._download_dialog is None:
            return
        self._download_dialog.set_progress(value, t(f"model.local.download.progress.{step}"))

    def _finish_download_success(self, binary_path: str) -> None:
        if self._download_dialog is not None:
            self._download_dialog.mark_finished()
            self._download_dialog.set_progress(100, t("model.local.download.progress.done"))
            self._download_dialog.close()
        self.download_llamacpp_button.setVisible(False)
        InfoBar.success(
            title=t("model.local.download.success.title"),
            content=t("model.local.download.success.content", path=binary_path),
            parent=self.window(),
            position=InfoBarPosition.TOP_RIGHT,
            duration=4500,
        )

    def _finish_download_failure(self, error: str) -> None:
        if self._download_dialog is not None:
            self._download_dialog.mark_finished()
            self._download_dialog.close()
        InfoBar.warning(
            title=t("model.local.download.failure.title"),
            content=t("model.local.download.failure.content", error=self._short_error(error)),
            parent=self.window(),
            position=InfoBarPosition.TOP_RIGHT,
            duration=7000,
        )

    def _finish_download_cancelled(self) -> None:
        if self._download_dialog is not None:
            self._download_dialog.mark_finished()
            self._download_dialog.close()
        InfoBar.info(
            title=t("model.local.download.cancelled.title"),
            content=t("model.local.download.cancelled.content"),
            parent=self.window(),
            position=InfoBarPosition.TOP_RIGHT,
            duration=3500,
        )

    def _clear_download_worker(self) -> None:
        self.download_llamacpp_button.setEnabled(True)
        self.download_llamacpp_button.setVisible(not has_llamacpp_binary())
        self._download_thread = None
        self._download_worker = None
        self._download_dialog = None

    def _short_error(self, error: str) -> str:
        error = " ".join(error.split())
        max_length = 120
        if len(error) <= max_length:
            return error
        return f"{error[:max_length]}..."

    def _refresh_local_models(self) -> None:
        selected_path = self.local_model_combo.currentData()
        candidates = self._local_model_candidates()
        LOGGER.info("Local model list refreshed; count=%s", len(candidates))
        self.local_model_combo.clear()
        if not candidates:
            self.local_model_combo.addItem(t("model.local.models.empty"), "")
            self.test_local_model_button.setEnabled(False)
            return

        self.test_local_model_button.setEnabled(True)
        selected_index = 0
        for index, model_path in enumerate(candidates):
            display_path = model_path.as_posix()
            self.local_model_combo.addItem(display_path, display_path)
            if display_path == selected_path:
                selected_index = index
        self.local_model_combo.setCurrentIndex(selected_index)

    def _local_model_candidates(self) -> list[Path]:
        if not MODELS_ROOT.exists():
            return []

        candidates: list[Path] = []
        for path in sorted(MODELS_ROOT.iterdir(), key=lambda item: item.name.lower()):
            if path.name.startswith("."):
                continue
            if path.is_file() and self._is_model_file(path):
                candidates.append(path.relative_to(APP_ROOT))
                continue
            if path.is_dir() and self._directory_contains_model(path):
                candidates.append(path.relative_to(APP_ROOT))
        return candidates

    def _directory_contains_model(self, path: Path) -> bool:
        return any(candidate.is_file() and self._is_model_file(candidate) for candidate in path.rglob("*"))

    def _is_model_file(self, path: Path) -> bool:
        return path.suffix.lower() in LOCAL_MODEL_SUFFIXES

    def _fake_test_local_model(self) -> None:
        self.local_test_result.setPlainText(
            t(
                "model.local.test.fakeResult",
                model_path=self.local_model_combo.currentData() or t("model.local.test.empty"),
                runner=self.local_runner_combo.currentText(),
                cache=t("model.local.test.cache.enabled")
                if self.use_cache.isChecked()
                else t("model.local.test.cache.disabled"),
            )
        )

    def _fetch_cloud_models(self) -> None:
        if self._cloud_models_thread is not None:
            LOGGER.info("Cloud model fetch ignored because a fetch is already running")
            return

        base_url = self.cloud_base_url.text().strip()
        api_key = self.cloud_api_key.text().strip()
        if not base_url:
            LOGGER.warning("Cloud model fetch blocked because base URL is empty")
            InfoBar.warning(
                title=t("model.cloud.models.failure.title"),
                content=t("model.cloud.models.baseUrlRequired"),
                parent=self.window(),
                position=InfoBarPosition.TOP_RIGHT,
                duration=4000,
            )
            return

        LOGGER.info("Cloud model fetch requested; base_url=%s has_api_key=%s", base_url, bool(api_key))
        self.fetch_cloud_models_button.setEnabled(False)
        self.fetch_cloud_models_button.setText(t("model.cloud.models.fetching"))
        self._cloud_models_thread = QThread(self)
        self._cloud_models_worker = CloudModelListWorker(base_url, api_key)
        self._cloud_models_worker.moveToThread(self._cloud_models_thread)
        self._cloud_models_thread.started.connect(self._cloud_models_worker.run)
        self._cloud_models_worker.succeeded.connect(self._show_cloud_models)
        self._cloud_models_worker.failed.connect(self._show_cloud_models_failure)
        self._cloud_models_worker.finished.connect(self._cloud_models_thread.quit)
        self._cloud_models_worker.finished.connect(self._cloud_models_worker.deleteLater)
        self._cloud_models_thread.finished.connect(self._cloud_models_thread.deleteLater)
        self._cloud_models_thread.finished.connect(self._clear_cloud_models_worker)
        self._cloud_models_thread.start()

    def _show_cloud_models(self, models: list[str]) -> None:
        LOGGER.info("Showing cloud model selection dialog; count=%s", len(models))
        dialog = CloudModelSelectDialog(models, self)
        dialog.modelSelected.connect(self.cloud_model_name.setText)
        dialog.exec()

    def _show_cloud_models_failure(self, error: str) -> None:
        LOGGER.warning("Showing cloud model fetch failure; error=%s", self._short_error(error))
        InfoBar.warning(
            title=t("model.cloud.models.failure.title"),
            content=t("model.cloud.models.failure.content", error=self._short_error(error)),
            parent=self.window(),
            position=InfoBarPosition.TOP_RIGHT,
            duration=7000,
        )

    def _clear_cloud_models_worker(self) -> None:
        self.fetch_cloud_models_button.setEnabled(True)
        self.fetch_cloud_models_button.setText(t("model.cloud.models.fetch"))
        self._cloud_models_thread = None
        self._cloud_models_worker = None

    def _fake_test_cloud_model(self) -> None:
        self.cloud_test_result.setPlainText(
            t(
                "model.cloud.test.fakeResult",
                provider=self.cloud_provider_combo.currentText(),
                base_url=self.cloud_base_url.text().strip() or t("model.cloud.test.empty"),
                model_name=self.cloud_model_name.text().strip() or t("model.cloud.test.empty"),
            )
        )

    def _refresh_cloud_presets(self, selected_name: str | None = None) -> None:
        self._cloud_presets = load_cloud_model_presets()
        self._loading_cloud_preset = True
        self.cloud_preset_combo.clear()
        self.cloud_preset_combo.addItem(t("model.cloud.preset.none"))
        for preset in self._cloud_presets:
            self.cloud_preset_combo.addItem(preset.name)

        index = 0
        if selected_name:
            for preset_index, preset in enumerate(self._cloud_presets, start=1):
                if preset.name == selected_name:
                    index = preset_index
                    break
        self.cloud_preset_combo.setCurrentIndex(index)
        self._loading_cloud_preset = False
        self._load_selected_cloud_preset()

    def _load_selected_cloud_preset(self) -> None:
        if self._loading_cloud_preset:
            return
        index = self.cloud_preset_combo.currentIndex() - 1
        if not 0 <= index < len(self._cloud_presets):
            self.cloud_preset_name.clear()
            return

        preset = self._cloud_presets[index]
        self.cloud_preset_name.setText(preset.name)
        self.cloud_base_url.setText(preset.base_url)
        self.cloud_api_key.setText(preset.api_key)
        self.cloud_model_name.setText(preset.model_name)
        provider_index = 0 if preset.provider != "custom" else 1
        self.cloud_provider_combo.setCurrentIndex(provider_index)

    def _save_current_cloud_preset(self) -> None:
        name = self.cloud_preset_name.text().strip()
        if not name:
            LOGGER.warning("Cloud model preset save blocked because name is empty")
            InfoBar.warning(
                title=t("model.cloud.preset.save.failure.title"),
                content=t("model.cloud.preset.name.required"),
                parent=self.window(),
                position=InfoBarPosition.TOP_RIGHT,
                duration=3500,
            )
            return

        preset = CloudModelPreset(
            name=name,
            provider="custom" if self.cloud_provider_combo.currentIndex() == 1 else "openaiCompatible",
            base_url=self.cloud_base_url.text().strip(),
            api_key=self.cloud_api_key.text().strip(),
            model_name=self.cloud_model_name.text().strip(),
        )
        upsert_cloud_model_preset(preset)
        LOGGER.info("Cloud model preset saved from UI; name=%s provider=%s", name, preset.provider)
        self._refresh_cloud_presets(selected_name=name)
        InfoBar.success(
            title=t("model.cloud.preset.save.success.title"),
            content=t("model.cloud.preset.save.success.content", name=name),
            parent=self.window(),
            position=InfoBarPosition.TOP_RIGHT,
            duration=3500,
        )

    def _delete_selected_cloud_preset(self) -> None:
        index = self.cloud_preset_combo.currentIndex() - 1
        if not 0 <= index < len(self._cloud_presets):
            return
        name = self._cloud_presets[index].name
        delete_cloud_model_preset(name)
        LOGGER.info("Cloud model preset deleted from UI; name=%s", name)
        self._refresh_cloud_presets()
        InfoBar.info(
            title=t("model.cloud.preset.delete.success.title"),
            content=t("model.cloud.preset.delete.success.content", name=name),
            parent=self.window(),
            position=InfoBarPosition.TOP_RIGHT,
            duration=3500,
        )
