from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QObject, QSignalBlocker, Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    ComboBox,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    ListWidget,
    PasswordLineEdit,
    PlainTextEdit,
    ProgressBar,
    PushButton,
    SearchLineEdit,
    Slider,
    SubtitleLabel,
    SwitchButton,
)

from gui.widgets.dialog_middleware import FluentDialog
from gui.widgets.streaming_text_session import StreamingTextSession
from gui.pages.model_test_helpers import (
    build_data_url as _build_data_url,
    format_token_usage_line as _format_token_usage_line,
    join_failed_items as _join_failed_items,
    response_language_instruction as _response_language_instruction,
    response_language_name as _response_language_name,
    token_usage_from_metadata as _token_usage_from_metadata,
    token_usage_log_fields as _token_usage_log_fields,
)
from utils.cloud_models import CloudModelListError, fetch_cloud_models
from utils.cloud_model_presets import (
    CLOUD_PROVIDER_IDS,
    DEFAULT_CLOUD_VIDEO_FPS,
    CloudModelPreset,
    cloud_model_provider,
    delete_cloud_model_preset,
    load_cloud_model_presets,
    normalize_cloud_provider,
    upsert_cloud_model_preset,
)
from utils.env_manager import has_llamacpp_binary
from utils.i18n import current_locale, t
from utils.llamacpp_downloader import (
    LlamaCppDownloadCancelled,
    LlamaCppDownloadError,
    download_and_install_llamacpp,
)
from utils.local_model_catalog import list_local_model_candidates
from utils.model_preferences import (
    last_cloud_preset_name,
    last_local_model_path,
    last_model_page_mode,
    set_last_cloud_preset_name,
    set_last_local_model_path,
    set_last_model_page_mode,
)
from utils.paths import APP_ROOT
from utils.ai_model_middleware import (
    ModelMiddlewareError,
    ModelCallRequest,
    ModelMessage,
    call_image_model,
    call_text_model,
    call_video_model,
)


TEST_MEDIA_ROOT = APP_ROOT / "res" / "test_media"
IMAGE_TEST_ASSET = TEST_MEDIA_ROOT / "model_test_input.jpg"
VIDEO_TEST_ASSET = TEST_MEDIA_ROOT / "model_test_input.mp4"
LOGGER = logging.getLogger(__name__)
EASTER_TAP_TARGET = 9
EASTER_PROMPT_OVERRIDE = (
    "请使用中文写一段对 yomihime（如月怜） 的赞美文字，整体风格偏向赞颂美少女气质。"
    "必须为原创连贯长文，长度不少于1000个中文汉字。"
    "内容可以围绕：创作者气场、审美品味、温柔与坚韧并存的个性、灵感感染力、舞台感与表达力。"
    "语气请真诚、有画面感，但不要使用低俗、露骨或色情内容。"
    "不要输出列表，不要分点，直接输出完整正文。"
)


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

    def __init__(self, provider: str, base_url: str, api_key: str) -> None:
        super().__init__()
        self.provider = provider
        self.base_url = base_url
        self.api_key = api_key

    def run(self) -> None:
        LOGGER.info("Cloud model list worker started; base_url=%s", self.base_url)
        try:
            models = fetch_cloud_models(self.provider, self.base_url, self.api_key)
        except CloudModelListError as exc:
            LOGGER.warning("Cloud model list worker failed; base_url=%s", self.base_url, exc_info=True)
            self.failed.emit(str(exc))
        else:
            LOGGER.info("Cloud model list worker succeeded; base_url=%s count=%s", self.base_url, len(models))
            self.succeeded.emit(models)
        finally:
            self.finished.emit()


class CloudTextTestWorker(QObject):
    progressChanged = pyqtSignal(str)
    succeeded = pyqtSignal(dict)
    failed = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, *, provider: str, base_url: str, api_key: str, model_name: str, locale: str) -> None:
        super().__init__()
        self.provider = provider
        self.base_url = base_url
        self.api_key = api_key
        self.model_name = model_name
        self.locale = locale

    def run(self) -> None:
        LOGGER.info(
            "Cloud text understanding test started; base_url=%s model=%s",
            self.base_url,
            self.model_name,
        )
        try:
            request = ModelCallRequest(
                purpose="connectivity_test",
                backend=cloud_model_provider(self.provider).backend_for("text"),
                model_name=self.model_name,
                base_url=self.base_url,
                api_key=self.api_key,
                temperature=0,
                max_tokens=64,
                stream=True,
                messages=[
                    ModelMessage(role="system", content="You are a model connectivity test assistant."),
                    ModelMessage(
                        role="user",
                        content=(
                            f"{_response_language_instruction(self.locale)} "
                            "Output exactly two lines: "
                            "MODEL: <the model id you are running as>; "
                            "SUMMARY: <one-sentence self-introduction>."
                        ),
                    ),
                ],
                metadata={"scene": "model_page_text_test"},
            )
            result = call_text_model(
                request,
                on_stream_delta=lambda delta: self.progressChanged.emit(delta),
            )
        except (ModelMiddlewareError, ValueError) as exc:
            LOGGER.warning("Cloud text understanding test failed", exc_info=True)
            self.failed.emit(str(exc))
        else:
            prompt_tokens, completion_tokens, total_tokens = _token_usage_log_fields(result.metadata)
            LOGGER.info(
                "Cloud text understanding test succeeded; prompt_tokens=%s completion_tokens=%s total_tokens=%s",
                prompt_tokens,
                completion_tokens,
                total_tokens,
            )
            self.succeeded.emit({"content": result.content, "token_usage": _token_usage_from_metadata(result.metadata)})
        finally:
            self.finished.emit()


class CloudImageTestWorker(QObject):
    progressChanged = pyqtSignal(str)
    succeeded = pyqtSignal(dict)
    failed = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, *, provider: str, base_url: str, api_key: str, model_name: str, image_path: Path, locale: str) -> None:
        super().__init__()
        self.provider = provider
        self.base_url = base_url
        self.api_key = api_key
        self.model_name = model_name
        self.image_path = image_path
        self.locale = locale

    def run(self) -> None:
        LOGGER.info(
            "Cloud image understanding test started; base_url=%s model=%s image=%s",
            self.base_url,
            self.model_name,
            self.image_path,
        )
        try:
            image_data_url = _build_data_url(self.image_path, "image/jpeg")
            request = ModelCallRequest(
                purpose="connectivity_test_image",
                backend=cloud_model_provider(self.provider).backend_for("image"),
                model_name=self.model_name,
                base_url=self.base_url,
                api_key=self.api_key,
                temperature=0,
                max_tokens=96,
                stream=True,
                messages=[
                    ModelMessage(role="system", content="You are a vision connectivity test assistant."),
                    ModelMessage(
                        role="user",
                        content=[
                            {
                                "type": "text",
                                "text": (
                                    f"{_response_language_instruction(self.locale)} "
                                    "Describe the main subject in one short sentence. Start with CHARA_IMAGE_OK: "
                                ),
                            },
                            {"type": "image_url", "image_url": {"url": image_data_url}},
                        ],
                    ),
                ],
                metadata={"scene": "model_page_image_test"},
            )
            result = call_image_model(
                request,
                on_stream_delta=lambda delta: self.progressChanged.emit(delta),
            )
        except (ModelMiddlewareError, OSError, ValueError) as exc:
            LOGGER.warning("Cloud image understanding test failed", exc_info=True)
            self.failed.emit(str(exc))
        else:
            prompt_tokens, completion_tokens, total_tokens = _token_usage_log_fields(result.metadata)
            LOGGER.info(
                "Cloud image understanding test succeeded; prompt_tokens=%s completion_tokens=%s total_tokens=%s",
                prompt_tokens,
                completion_tokens,
                total_tokens,
            )
            self.succeeded.emit({"content": result.content, "token_usage": _token_usage_from_metadata(result.metadata)})
        finally:
            self.finished.emit()


class CloudVideoTestWorker(QObject):
    progressChanged = pyqtSignal(str)
    succeeded = pyqtSignal(dict)
    failed = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(
        self,
        *,
        provider: str,
        base_url: str,
        api_key: str,
        model_name: str,
        video_path: Path,
        video_fps: float,
        locale: str,
    ) -> None:
        super().__init__()
        self.provider = provider
        self.base_url = base_url
        self.api_key = api_key
        self.model_name = model_name
        self.video_path = video_path
        self.video_fps = video_fps
        self.locale = locale

    def run(self) -> None:
        LOGGER.info(
            "Cloud video understanding test started; base_url=%s model=%s video=%s",
            self.base_url,
            self.model_name,
            self.video_path,
        )
        try:
            request = ModelCallRequest(
                purpose="connectivity_test_video",
                backend=cloud_model_provider(self.provider).backend_for("video"),
                model_name=self.model_name,
                base_url=self.base_url,
                api_key=self.api_key,
                temperature=0,
                max_tokens=96,
                messages=[
                    ModelMessage(role="system", content="You are a video connectivity test assistant."),
                    ModelMessage(
                        role="user",
                        content=[
                            {
                                "type": "text",
                                "text": (
                                    f"{_response_language_instruction(self.locale)} "
                                    "The video is uploaded as a local video file. "
                                    "Describe the video's main scene in one short sentence. "
                                    "Start with CHARA_VIDEO_OK: "
                                ),
                            },
                            {"type": "video", "video": str(self.video_path.resolve()), "fps": self.video_fps},
                        ],
                    ),
                ],
                metadata={"scene": "model_page_video_test"},
            )
            result = call_video_model(
                request,
                on_stream_delta=lambda delta: self.progressChanged.emit(delta),
            )
        except (ModelMiddlewareError, OSError, ValueError) as exc:
            LOGGER.warning("Cloud video understanding test failed", exc_info=True)
            self.failed.emit(str(exc))
        else:
            prompt_tokens, completion_tokens, total_tokens = _token_usage_log_fields(result.metadata)
            LOGGER.info(
                "Cloud video understanding test succeeded; prompt_tokens=%s completion_tokens=%s total_tokens=%s",
                prompt_tokens,
                completion_tokens,
                total_tokens,
            )
            self.succeeded.emit({"content": result.content, "token_usage": _token_usage_from_metadata(result.metadata)})
        finally:
            self.finished.emit()


class CloudAllTestWorker(QObject):
    progressChanged = pyqtSignal(str, str)
    sectionStarted = pyqtSignal(str)
    sectionFinished = pyqtSignal(str, str, dict)
    succeeded = pyqtSignal(dict)
    failed = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(
        self,
        *,
        provider: str,
        base_url: str,
        api_key: str,
        model_name: str,
        image_path: Path,
        video_path: Path,
        video_fps: float,
        locale: str,
        text_prompt_override: str | None = None,
    ) -> None:
        super().__init__()
        self.provider = provider
        self.base_url = base_url
        self.api_key = api_key
        self.model_name = model_name
        self.image_path = image_path
        self.video_path = video_path
        self.video_fps = video_fps
        self.locale = locale
        self.text_prompt_override = text_prompt_override

    def run(self) -> None:
        LOGGER.info("Cloud all-modal test started; base_url=%s model=%s", self.base_url, self.model_name)
        try:
            results = {
                "text": self._run_text_test(),
                "image": self._run_image_test(),
                "video": self._run_video_test(),
            }
            self.succeeded.emit(results)
        except (ModelMiddlewareError, OSError, ValueError) as exc:
            LOGGER.warning("Cloud all-modal test failed", exc_info=True)
            self.failed.emit(str(exc))
        finally:
            self.finished.emit()

    def _safe_call(self, request: ModelCallRequest, section: str) -> dict[str, Any]:
        self.sectionStarted.emit(section)
        try:
            if section == "image":
                result = call_image_model(
                    request,
                    on_stream_delta=lambda delta: self.progressChanged.emit(section, delta),
                )
            elif section == "video":
                result = call_video_model(
                    request,
                    on_stream_delta=lambda delta: self.progressChanged.emit(section, delta),
                )
            else:
                result = call_text_model(
                    request,
                    on_stream_delta=lambda delta: self.progressChanged.emit(section, delta),
                )
            prompt_tokens, completion_tokens, total_tokens = _token_usage_log_fields(result.metadata)
            LOGGER.info(
                "Cloud all-modal section succeeded; section=%s prompt_tokens=%s completion_tokens=%s total_tokens=%s",
                section,
                prompt_tokens,
                completion_tokens,
                total_tokens,
            )
            payload = {
                "status": "ok",
                "content": result.content.strip(),
                "token_usage": _token_usage_from_metadata(result.metadata),
            }
            self.sectionFinished.emit(section, "ok", payload["token_usage"])
            return payload
        except Exception as exc:  # noqa: BLE001
            self.sectionFinished.emit(section, "error", {})
            return {"status": "error", "content": str(exc)}

    def _run_text_test(self) -> dict[str, str]:
        if self.text_prompt_override:
            user_prompt = self.text_prompt_override
            max_tokens = 2200
        else:
            user_prompt = (
                f"{_response_language_instruction(self.locale)} "
                "Output exactly two lines: "
                "MODEL: <the model id you are running as>; "
                "SUMMARY: <one-sentence self-introduction>."
            )
            max_tokens = 64
        request = ModelCallRequest(
            purpose="connectivity_test",
            backend=cloud_model_provider(self.provider).backend_for("text"),
            model_name=self.model_name,
            base_url=self.base_url,
            api_key=self.api_key,
            temperature=0,
            max_tokens=max_tokens,
            stream=True,
            messages=[
                ModelMessage(role="system", content="You are a model connectivity test assistant."),
                ModelMessage(role="user", content=user_prompt),
            ],
            metadata={"scene": "model_page_text_test"},
        )
        return self._safe_call(request, "text")

    def _run_image_test(self) -> dict[str, str]:
        image_data_url = _build_data_url(self.image_path, "image/jpeg")
        request = ModelCallRequest(
            purpose="connectivity_test_image",
            backend=cloud_model_provider(self.provider).backend_for("image"),
            model_name=self.model_name,
            base_url=self.base_url,
            api_key=self.api_key,
            temperature=0,
            max_tokens=96,
            stream=True,
            messages=[
                ModelMessage(role="system", content="You are a vision connectivity test assistant."),
                ModelMessage(
                    role="user",
                    content=[
                        {
                            "type": "text",
                            "text": (
                                f"{_response_language_instruction(self.locale)} "
                                "Describe the main subject in one short sentence. Start with CHARA_IMAGE_OK: "
                            ),
                        },
                        {"type": "image_url", "image_url": {"url": image_data_url}},
                    ],
                ),
            ],
            metadata={"scene": "model_page_image_test"},
        )
        return self._safe_call(request, "image")

    def _run_video_test(self) -> dict[str, str]:
        request = ModelCallRequest(
            purpose="connectivity_test_video",
            backend=cloud_model_provider(self.provider).backend_for("video"),
            model_name=self.model_name,
            base_url=self.base_url,
            api_key=self.api_key,
            temperature=0,
            max_tokens=96,
            messages=[
                ModelMessage(role="system", content="You are a video connectivity test assistant."),
                ModelMessage(
                    role="user",
                    content=[
                        {
                            "type": "text",
                            "text": (
                                f"{_response_language_instruction(self.locale)} "
                                "The video is uploaded as a local video file. "
                                "Describe the video's main scene in one short sentence. "
                                "Start with CHARA_VIDEO_OK: "
                            ),
                        },
                        {"type": "video", "video": str(self.video_path.resolve()), "fps": self.video_fps},
                    ],
                ),
            ],
            metadata={"scene": "model_page_video_test"},
        )
        return self._safe_call(request, "video")


class LlamaCppDownloadDialog(FluentDialog):
    cancelRequested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(t("model.local.download.title"), parent, width=520, height=210, close_rejects=False)
        self._finished = False
        self._cancel_requested = False

        self.status_label = BodyLabel(t("model.local.download.progress.release"), self.dialog_card)
        self.status_label.setWordWrap(True)
        self.content_layout.addWidget(self.status_label)

        self.progress_bar = ProgressBar(self.dialog_card)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.content_layout.addWidget(self.progress_bar)

        actions = QHBoxLayout()
        actions.addStretch(1)
        self.cancel_button = PushButton(t("model.local.download.cancel"), self.dialog_card)
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
        self.status_label.setText(t("model.local.download.progress.canceling"))
        self.cancelRequested.emit()

    def mark_finished(self) -> None:
        self._finished = True

    def reject(self) -> None:
        if self._finished:
            super().reject()
            return
        self.request_cancel()


class CloudModelSelectDialog(FluentDialog):
    modelSelected = pyqtSignal(str)

    def __init__(self, models: list[str], parent: QWidget | None = None) -> None:
        super().__init__(
            t("model.cloud.models.title"),
            parent,
            width=560,
            height=460,
            margins=(22, 20, 22, 20),
            spacing=12,
        )
        self._models = models

        self.search_edit = SearchLineEdit(self.dialog_card)
        self.search_edit.setPlaceholderText(t("model.cloud.models.search.placeholder"))
        self.content_layout.addWidget(self.search_edit)

        self.model_list = ListWidget(self.dialog_card)
        self.model_list.setMinimumHeight(260)
        self.content_layout.addWidget(self.model_list, 1)

        actions = QHBoxLayout()
        actions.addStretch(1)
        cancel_button = PushButton(t("model.cloud.models.cancel"), self.dialog_card)
        select_button = PushButton(t("model.cloud.models.select"), self.dialog_card)
        actions.addWidget(cancel_button)
        actions.addWidget(select_button)
        self.content_layout.addLayout(actions)

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


class SecretTapLabel(BodyLabel):
    clicked = pyqtSignal()

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        self.clicked.emit()
        super().mousePressEvent(event)


class ModelPage(QWidget):
    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        initial_llamacpp_ready: bool | None = None,
        initial_local_models: list[Path] | None = None,
        initial_cloud_presets: list[CloudModelPreset] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("modelPage")
        self._download_thread: QThread | None = None
        self._download_worker: LlamaCppDownloadWorker | None = None
        self._download_dialog: LlamaCppDownloadDialog | None = None
        self._cloud_models_thread: QThread | None = None
        self._cloud_models_worker: CloudModelListWorker | None = None
        self._cloud_text_test_thread: QThread | None = None
        self._cloud_text_test_worker: CloudTextTestWorker | None = None
        self._cloud_image_test_thread: QThread | None = None
        self._cloud_image_test_worker: CloudImageTestWorker | None = None
        self._cloud_video_test_thread: QThread | None = None
        self._cloud_video_test_worker: CloudVideoTestWorker | None = None
        self._cloud_all_test_thread: QThread | None = None
        self._cloud_all_test_worker: CloudAllTestWorker | None = None
        self._cloud_text_stream_buffer = ""
        self._cloud_image_stream_buffer = ""
        self._cloud_video_stream_buffer = ""
        self._cloud_all_stream_buffers: dict[str, str] = {"text": "", "image": "", "video": ""}
        self._cloud_all_token_usage: dict[str, dict[str, int]] = {"text": {}, "image": {}, "video": {}}
        self._cloud_all_section_status: dict[str, str] = {"text": "queued", "image": "queued", "video": "queued"}
        self._cloud_all_final_summary = ""
        self._last_valid_cloud_video_fps = DEFAULT_CLOUD_VIDEO_FPS
        self._cloud_stream_session: StreamingTextSession | None = None
        self._cloud_stream_kind = ""
        self._cloud_presets: list[CloudModelPreset] = []
        self._loading_cloud_preset = False
        self._restoring_model_selection = False
        self._llamacpp_ready_cache = initial_llamacpp_ready
        self._cloud_easter_tap_count = 0

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
        local_grid = QGridLayout(self.local_card)
        local_grid.setContentsMargins(24, 20, 24, 22)
        local_grid.setHorizontalSpacing(18)
        local_grid.setVerticalSpacing(12)

        local_model_row = QHBoxLayout()
        local_model_row.setSpacing(10)
        self.local_model_combo = ComboBox(self.local_card)
        self.refresh_local_models_button = PushButton(t("model.local.models.refresh"), self.local_card)
        local_model_row.addWidget(self.local_model_combo, 1)
        local_model_row.addWidget(self.refresh_local_models_button)

        self.local_runner_combo = ComboBox(self.local_card)
        self.local_runner_combo.addItem(t("model.local.runner.llama"))

        runner_row = QHBoxLayout()
        runner_row.setSpacing(10)
        runner_row.addWidget(self.local_runner_combo, 1)

        self.download_llamacpp_button = PushButton(t("model.local.downloadLlamacpp"), self.local_card)
        self.download_llamacpp_button.setVisible(not self._llamacpp_ready())
        runner_row.addWidget(self.download_llamacpp_button)

        self.use_cache = SwitchButton(self.local_card)
        self.use_cache.setChecked(True)

        self.test_local_model_button = PushButton(t("model.local.test"), self.local_card)
        self.local_test_type_combo = ComboBox(self.local_card)
        self.local_test_type_combo.addItem(t("model.test.type.all"), "all")
        self.local_test_type_combo.addItem(t("model.test.type.text"), "text")
        self.local_test_type_combo.addItem(t("model.test.type.image"), "image")
        self.local_test_type_combo.addItem(t("model.test.type.video"), "video")
        self.local_test_result = PlainTextEdit(self.local_card)
        self.local_test_result.setPlaceholderText(t("model.local.test.placeholder"))
        self.local_test_result.setReadOnly(True)
        self.local_test_result.setMinimumHeight(96)

        local_grid.addWidget(BodyLabel(t("model.local.select"), self.local_card), 0, 0)
        local_grid.addLayout(local_model_row, 0, 1, 1, 4)
        local_grid.addWidget(BodyLabel(t("model.local.runner"), self.local_card), 1, 0)
        local_grid.addLayout(runner_row, 1, 1, 1, 4)
        local_grid.addWidget(BodyLabel(t("model.local.cache"), self.local_card), 2, 0)
        local_grid.addWidget(self.use_cache, 2, 1, 1, 4)
        local_grid.addWidget(BodyLabel(t("model.test.type"), self.local_card), 3, 0)
        local_grid.addWidget(self.local_test_type_combo, 3, 1, 1, 4)
        local_grid.addWidget(BodyLabel(t("model.local.test.action"), self.local_card), 4, 0)
        local_grid.addWidget(self.test_local_model_button, 4, 1, 1, 4)
        local_grid.addWidget(
            BodyLabel(t("model.local.test.result"), self.local_card),
            5,
            0,
            1,
            1,
            Qt.AlignmentFlag.AlignTop,
        )
        local_grid.addWidget(self.local_test_result, 5, 1, 1, 4)
        local_grid.setColumnStretch(0, 0)
        local_grid.setColumnStretch(1, 1)
        local_grid.setColumnStretch(2, 0)
        local_grid.setColumnStretch(3, 2)
        local_grid.setColumnStretch(4, 0)
        root.addWidget(self.local_card)

        self.cloud_card = CardWidget(self)
        self.cloud_card.setBorderRadius(8)
        cloud_layout = QVBoxLayout(self.cloud_card)
        cloud_layout.setContentsMargins(24, 20, 24, 22)
        cloud_layout.setSpacing(16)

        self.cloud_preset_combo = ComboBox(self.cloud_card)
        self.cloud_preset_name = LineEdit(self.cloud_card)
        self.cloud_preset_name.setPlaceholderText(t("model.cloud.preset.name.placeholder"))
        self.save_cloud_preset_button = PushButton(t("model.cloud.preset.save"), self.cloud_card)
        self.delete_cloud_preset_button = PushButton(t("model.cloud.preset.delete"), self.cloud_card)
        preset_actions = QHBoxLayout()
        preset_actions.setSpacing(10)
        preset_actions.addWidget(self.save_cloud_preset_button)
        preset_actions.addWidget(self.delete_cloud_preset_button)

        self.cloud_provider_combo = ComboBox(self.cloud_card)
        for provider_id in CLOUD_PROVIDER_IDS:
            provider = cloud_model_provider(provider_id)
            self.cloud_provider_combo.addItem(t(provider.label_key), provider.provider_id)

        self.cloud_base_url = LineEdit(self.cloud_card)
        self.cloud_base_url.setPlaceholderText(t("model.cloud.baseUrl.placeholder"))

        self.cloud_api_key = PasswordLineEdit(self.cloud_card)
        self.cloud_api_key.setPlaceholderText(t("model.cloud.apiKey.placeholder"))

        self.cloud_model_name = LineEdit(self.cloud_card)
        self.cloud_model_name.setPlaceholderText(t("model.cloud.modelName.placeholder"))
        model_name_row = QHBoxLayout()
        model_name_row.setSpacing(10)
        model_name_row.addWidget(self.cloud_model_name, 1)
        self.fetch_cloud_models_button = PushButton(t("model.cloud.models.fetch"), self.cloud_card)
        model_name_row.addWidget(self.fetch_cloud_models_button)

        video_fps_row = QHBoxLayout()
        video_fps_row.setSpacing(8)
        self.cloud_video_fps_slider = Slider(Qt.Orientation.Horizontal, self.cloud_card)
        self.cloud_video_fps_slider.setRange(1, 100)
        self.cloud_video_fps_slider.setValue(int(DEFAULT_CLOUD_VIDEO_FPS * 10))
        self.cloud_video_fps_slider.setMaximumWidth(220)
        self.cloud_video_fps = LineEdit(self.cloud_card)
        self.cloud_video_fps.setPlaceholderText(f"{DEFAULT_CLOUD_VIDEO_FPS:.1f}")
        self.cloud_video_fps.setText(f"{DEFAULT_CLOUD_VIDEO_FPS:.1f}")
        self.cloud_video_fps.setMaximumWidth(72)
        video_fps_row.addWidget(self.cloud_video_fps_slider, 1)
        video_fps_row.addWidget(self.cloud_video_fps)

        self.test_cloud_model_button = PushButton(t("model.cloud.test"), self.cloud_card)
        self.cloud_test_action_label = SecretTapLabel(t("model.cloud.test.action"), self.cloud_card)
        self.cloud_test_type_combo = ComboBox(self.cloud_card)
        self.cloud_test_type_combo.addItem(t("model.test.type.all"), "all")
        self.cloud_test_type_combo.addItem(t("model.test.type.text"), "text")
        self.cloud_test_type_combo.addItem(t("model.test.type.image"), "image")
        self.cloud_test_type_combo.addItem(t("model.test.type.video"), "video")
        self.cloud_test_result = PlainTextEdit(self.cloud_card)
        self.cloud_test_result.setPlaceholderText(t("model.cloud.test.placeholder"))
        self.cloud_test_result.setReadOnly(True)
        self.cloud_test_result.setMinimumHeight(96)
        self._cloud_stream_session = StreamingTextSession(self.cloud_test_result)

        connection_grid = QGridLayout()
        connection_grid.setHorizontalSpacing(18)
        connection_grid.setVerticalSpacing(12)
        connection_grid.addWidget(BodyLabel(t("model.cloud.preset"), self.cloud_card), 0, 0)
        connection_grid.addWidget(self.cloud_preset_combo, 0, 1)
        connection_grid.addWidget(BodyLabel(t("model.cloud.preset.name"), self.cloud_card), 0, 2)
        connection_grid.addWidget(self.cloud_preset_name, 0, 3)
        connection_grid.addLayout(preset_actions, 0, 4)

        connection_grid.addWidget(BodyLabel(t("model.cloud.provider"), self.cloud_card), 1, 0)
        connection_grid.addWidget(self.cloud_provider_combo, 1, 1)
        connection_grid.addWidget(BodyLabel(t("model.cloud.modelName"), self.cloud_card), 1, 2)
        connection_grid.addLayout(model_name_row, 1, 3, 1, 2)

        connection_grid.addWidget(BodyLabel(t("model.cloud.baseUrl"), self.cloud_card), 2, 0)
        connection_grid.addWidget(self.cloud_base_url, 2, 1, 1, 4)
        connection_grid.addWidget(BodyLabel(t("model.cloud.apiKey"), self.cloud_card), 3, 0)
        connection_grid.addWidget(self.cloud_api_key, 3, 1, 1, 4)

        connection_grid.addWidget(BodyLabel(t("model.cloud.videoFps"), self.cloud_card), 4, 0)
        connection_grid.addLayout(video_fps_row, 4, 1)
        connection_grid.addWidget(BodyLabel(t("model.test.type"), self.cloud_card), 4, 2)
        connection_grid.addWidget(self.cloud_test_type_combo, 4, 3, 1, 2)

        connection_grid.addWidget(self.cloud_test_action_label, 5, 0)
        connection_grid.addWidget(self.test_cloud_model_button, 5, 1, 1, 4)
        connection_grid.addWidget(
            BodyLabel(t("model.cloud.test.result"), self.cloud_card),
            6,
            0,
            1,
            1,
            Qt.AlignmentFlag.AlignTop,
        )
        connection_grid.addWidget(self.cloud_test_result, 6, 1, 1, 4)
        connection_grid.setColumnStretch(0, 0)
        connection_grid.setColumnStretch(1, 1)
        connection_grid.setColumnStretch(2, 0)
        connection_grid.setColumnStretch(3, 2)
        connection_grid.setColumnStretch(4, 0)
        cloud_layout.addLayout(connection_grid)
        root.addWidget(self.cloud_card)

        root.addStretch(1)

        self.cloud_mode_switch.checkedChanged.connect(self._set_cloud_mode)
        self.download_llamacpp_button.clicked.connect(self._download_llamacpp)
        self.refresh_local_models_button.clicked.connect(self._refresh_local_models_from_button)
        self.test_local_model_button.clicked.connect(self._test_local_model)
        self.fetch_cloud_models_button.clicked.connect(self._fetch_cloud_models)
        self.test_cloud_model_button.clicked.connect(self._test_cloud_model)
        self.cloud_test_action_label.clicked.connect(self._record_cloud_easter_tap)
        self.local_model_combo.currentIndexChanged.connect(self._remember_selected_local_model)
        self.cloud_video_fps_slider.valueChanged.connect(self._sync_cloud_video_fps_from_slider)
        self.cloud_video_fps.editingFinished.connect(self._commit_cloud_video_fps_text)
        self.cloud_provider_combo.currentIndexChanged.connect(self._sync_cloud_video_fps_availability)
        self.cloud_preset_combo.currentIndexChanged.connect(self._load_selected_cloud_preset)
        self.save_cloud_preset_button.clicked.connect(self._save_current_cloud_preset)
        self.delete_cloud_preset_button.clicked.connect(self._delete_selected_cloud_preset)
        self._restore_model_selection(
            preloaded_local_models=initial_local_models,
            preloaded_presets=initial_cloud_presets,
        )

    def _set_cloud_mode(self, enabled: bool) -> None:
        LOGGER.info("Model page mode changed; cloud_enabled=%s", enabled)
        self.local_card.setVisible(not enabled)
        self.cloud_card.setVisible(enabled)
        if not self._restoring_model_selection:
            set_last_model_page_mode("cloud" if enabled else "local")

    def _restore_model_selection(
        self,
        *,
        preloaded_local_models: list[Path] | None = None,
        preloaded_presets: list[CloudModelPreset] | None = None,
    ) -> None:
        self._restoring_model_selection = True
        try:
            self._populate_local_models(preloaded_local_models or [], selected_path=last_local_model_path())
            self._refresh_cloud_presets(
                selected_name=last_cloud_preset_name(),
                preloaded_presets=preloaded_presets,
            )
            self._sync_cloud_video_fps_availability()
            cloud_enabled = last_model_page_mode() == "cloud"
            blocker = QSignalBlocker(self.cloud_mode_switch)
            try:
                self.cloud_mode_switch.setChecked(cloud_enabled)
            finally:
                del blocker
            self._set_cloud_mode(cloud_enabled)
        finally:
            self._restoring_model_selection = False

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
        self._llamacpp_ready_cache = True
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
        self._llamacpp_ready_cache = None
        self.download_llamacpp_button.setVisible(not self._llamacpp_ready())
        self._download_thread = None
        self._download_worker = None
        self._download_dialog = None

    def _short_error(self, error: str) -> str:
        error = " ".join(error.split())
        max_length = 120
        if len(error) <= max_length:
            return error
        return f"{error[:max_length]}..."

    def _set_cloud_test_result_text(self, text: str) -> None:
        if self._cloud_stream_session is not None:
            self._cloud_stream_session.reset(text)
        else:
            self.cloud_test_result.setPlainText(text)
            scrollbar = self.cloud_test_result.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())

    def _start_cloud_stream_render(self, kind: str) -> None:
        if self._cloud_stream_session is None:
            return
        if self._cloud_stream_session.active and self._cloud_stream_kind == kind:
            return
        self._cloud_stream_kind = kind
        self._cloud_stream_session.start(self._build_cloud_stream_header(kind))

    def _append_cloud_stream_delta(self, kind: str, delta: str) -> None:
        if not delta:
            return
        if self._cloud_stream_session is None:
            return
        self._start_cloud_stream_render(kind)
        self._cloud_stream_session.append_delta(delta)

    def _build_cloud_stream_header(self, kind: str) -> str:
        locale = current_locale()
        base_url = self.cloud_base_url.text().strip() or t("model.cloud.test.empty")
        model_name = self.cloud_model_name.text().strip() or t("model.cloud.test.empty")
        provider = self.cloud_provider_combo.currentText()
        if kind == "text":
            return t(
                "model.cloud.test.text.successResult",
                provider=provider,
                base_url=base_url,
                model_name=model_name,
                target_language=_response_language_name(locale),
                response="",
            )
        if kind == "image":
            return t(
                "model.cloud.test.image.successResult",
                provider=provider,
                base_url=base_url,
                model_name=model_name,
                asset=IMAGE_TEST_ASSET.relative_to(APP_ROOT).as_posix(),
                target_language=_response_language_name(locale),
                response="",
            )
        if kind == "video":
            return t(
                "model.cloud.test.video.successResult",
                provider=provider,
                base_url=base_url,
                model_name=model_name,
                asset=VIDEO_TEST_ASSET.relative_to(APP_ROOT).as_posix(),
                target_language=_response_language_name(locale),
                response="",
            )
        return ""

    def _refresh_local_models(self, selected_path: str | None = None) -> None:
        selected_path = selected_path if selected_path is not None else self.local_model_combo.currentData()
        candidates = list_local_model_candidates()
        LOGGER.info("Local model list refreshed; count=%s", len(candidates))
        self._populate_local_models(candidates, selected_path=str(selected_path or ""))

    def _populate_local_models(self, candidates: list[Path], selected_path: str | None = None) -> None:
        blocker = QSignalBlocker(self.local_model_combo)
        try:
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
        finally:
            del blocker

    def _refresh_local_models_from_button(self) -> None:
        self._refresh_local_models()

    def _remember_selected_local_model(self, _index: int | None = None) -> None:
        if self._restoring_model_selection:
            return
        set_last_local_model_path(str(self.local_model_combo.currentData() or ""))

    def _test_local_model(self) -> None:
        test_type = self.local_test_type_combo.currentData() or "all"
        if test_type == "all":
            self.local_test_result.setPlainText(
                t(
                    "model.local.test.all.placeholderResult",
                    model_path=self.local_model_combo.currentData() or t("model.local.test.empty"),
                    runner=self.local_runner_combo.currentText(),
                    cache=t("model.local.test.cache.enabled")
                    if self.use_cache.isChecked()
                    else t("model.local.test.cache.disabled"),
                    image_asset=IMAGE_TEST_ASSET.relative_to(APP_ROOT).as_posix(),
                    video_asset=VIDEO_TEST_ASSET.relative_to(APP_ROOT).as_posix(),
                )
            )
            return
        if test_type == "image":
            self.local_test_result.setPlainText(t("model.test.image.placeholderResult"))
            return
        if test_type == "video":
            self.local_test_result.setPlainText(t("model.test.video.placeholderResult"))
            return

        self.local_test_result.setPlainText(
            t(
                "model.local.test.text.placeholderResult",
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
        self._cloud_models_worker = CloudModelListWorker(self._current_cloud_provider_id(), base_url, api_key)
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

    def _current_cloud_provider_id(self) -> str:
        return normalize_cloud_provider(str(self.cloud_provider_combo.currentData() or ""))

    def _current_cloud_video_fps(self) -> float:
        self._commit_cloud_video_fps_text()
        return self._last_valid_cloud_video_fps

    def _sync_cloud_video_fps_from_slider(self, value: int) -> None:
        self._set_cloud_video_fps(value / 10.0)

    def _commit_cloud_video_fps_text(self) -> None:
        try:
            value = float(self.cloud_video_fps.text().strip())
        except ValueError:
            self._set_cloud_video_fps(self._last_valid_cloud_video_fps)
            return
        if not 0.1 <= value <= 10.0:
            self._set_cloud_video_fps(self._last_valid_cloud_video_fps)
            return
        self._set_cloud_video_fps(value)

    def _set_cloud_video_fps(self, value: float) -> None:
        normalized = round(min(max(value, 0.1), 10.0), 1)
        self._last_valid_cloud_video_fps = normalized
        slider_value = int(round(normalized * 10))
        with QSignalBlocker(self.cloud_video_fps_slider):
            self.cloud_video_fps_slider.setValue(slider_value)
        with QSignalBlocker(self.cloud_video_fps):
            self.cloud_video_fps.setText(f"{normalized:.1f}")

    def _sync_cloud_video_fps_availability(self) -> None:
        provider = cloud_model_provider(self._current_cloud_provider_id())
        self.cloud_video_fps.setEnabled(provider.supports_video_fps)
        self.cloud_video_fps_slider.setEnabled(provider.supports_video_fps)
        self.cloud_video_fps.setToolTip(t(f"model.cloud.videoFps.mode.{provider.video_fps_mode}"))
        self.cloud_video_fps_slider.setToolTip(t(f"model.cloud.videoFps.mode.{provider.video_fps_mode}"))

    def _test_cloud_model(self) -> None:
        test_type = self.cloud_test_type_combo.currentData() or "all"
        if test_type == "all":
            self._test_cloud_all(text_prompt_override=self._consume_cloud_all_easter_prompt())
            return
        self._reset_cloud_easter_tap_counter()
        if test_type == "image":
            self._test_cloud_image()
            return
        if test_type == "video":
            self._test_cloud_video()
            return

        if self._is_cloud_test_running():
            LOGGER.info("Cloud text understanding test ignored because a test is already running")
            return

        base_url = self.cloud_base_url.text().strip()
        model_name = self.cloud_model_name.text().strip()
        if not base_url:
            InfoBar.warning(
                title=t("model.cloud.test.failure.title"),
                content=t("model.cloud.models.baseUrlRequired"),
                parent=self.window(),
                position=InfoBarPosition.TOP_RIGHT,
                duration=4000,
            )
            return
        if not model_name:
            InfoBar.warning(
                title=t("model.cloud.test.failure.title"),
                content=t("model.cloud.test.modelRequired"),
                parent=self.window(),
                position=InfoBarPosition.TOP_RIGHT,
                duration=4000,
            )
            return

        self.test_cloud_model_button.setEnabled(False)
        self.test_cloud_model_button.setText(t("model.cloud.test.running"))
        self._cloud_stream_kind = ""
        locale = current_locale()
        self._cloud_text_test_thread = QThread(self)
        self._cloud_text_test_worker = CloudTextTestWorker(
            provider=self._current_cloud_provider_id(),
            base_url=base_url,
            api_key=self.cloud_api_key.text().strip(),
            model_name=model_name,
            locale=locale,
        )
        self._cloud_text_stream_buffer = ""
        self._cloud_text_test_worker.moveToThread(self._cloud_text_test_thread)
        self._cloud_text_test_thread.started.connect(self._cloud_text_test_worker.run)
        self._cloud_text_test_worker.progressChanged.connect(self._show_cloud_text_test_stream)
        self._cloud_text_test_worker.succeeded.connect(self._show_cloud_text_test_success)
        self._cloud_text_test_worker.failed.connect(self._show_cloud_text_test_failure)
        self._cloud_text_test_worker.finished.connect(self._cloud_text_test_thread.quit)
        self._cloud_text_test_worker.finished.connect(self._cloud_text_test_worker.deleteLater)
        self._cloud_text_test_thread.finished.connect(self._cloud_text_test_thread.deleteLater)
        self._cloud_text_test_thread.finished.connect(self._clear_cloud_text_test_worker)
        self._cloud_text_test_thread.start()

    def _test_cloud_image(self) -> None:
        if self._is_cloud_test_running():
            LOGGER.info("Cloud image understanding test ignored because a test is already running")
            return

        base_url = self.cloud_base_url.text().strip()
        model_name = self.cloud_model_name.text().strip()
        if not base_url:
            InfoBar.warning(
                title=t("model.cloud.test.failure.title"),
                content=t("model.cloud.models.baseUrlRequired"),
                parent=self.window(),
                position=InfoBarPosition.TOP_RIGHT,
                duration=4000,
            )
            return
        if not model_name:
            InfoBar.warning(
                title=t("model.cloud.test.failure.title"),
                content=t("model.cloud.test.modelRequired"),
                parent=self.window(),
                position=InfoBarPosition.TOP_RIGHT,
                duration=4000,
            )
            return
        if not IMAGE_TEST_ASSET.exists():
            short_error = self._short_error(t("model.test.image.assetMissing", path=IMAGE_TEST_ASSET.as_posix()))
            self._set_cloud_test_result_text(
                t(
                    "model.cloud.test.image.failureResult",
                    provider=self.cloud_provider_combo.currentText(),
                    base_url=base_url,
                    model_name=model_name,
                    asset=IMAGE_TEST_ASSET.as_posix(),
                    error=short_error,
                )
            )
            InfoBar.warning(
                title=t("model.cloud.test.failure.title"),
                content=short_error,
                parent=self.window(),
                position=InfoBarPosition.TOP_RIGHT,
                duration=5000,
            )
            return

        self.test_cloud_model_button.setEnabled(False)
        self.test_cloud_model_button.setText(t("model.cloud.test.running"))
        self._cloud_stream_kind = ""
        locale = current_locale()
        self._cloud_image_test_thread = QThread(self)
        self._cloud_image_test_worker = CloudImageTestWorker(
            provider=self._current_cloud_provider_id(),
            base_url=base_url,
            api_key=self.cloud_api_key.text().strip(),
            model_name=model_name,
            image_path=IMAGE_TEST_ASSET,
            locale=locale,
        )
        self._cloud_image_stream_buffer = ""
        self._cloud_image_test_worker.moveToThread(self._cloud_image_test_thread)
        self._cloud_image_test_thread.started.connect(self._cloud_image_test_worker.run)
        self._cloud_image_test_worker.progressChanged.connect(self._show_cloud_image_test_stream)
        self._cloud_image_test_worker.succeeded.connect(self._show_cloud_image_test_success)
        self._cloud_image_test_worker.failed.connect(self._show_cloud_image_test_failure)
        self._cloud_image_test_worker.finished.connect(self._cloud_image_test_thread.quit)
        self._cloud_image_test_worker.finished.connect(self._cloud_image_test_worker.deleteLater)
        self._cloud_image_test_thread.finished.connect(self._cloud_image_test_thread.deleteLater)
        self._cloud_image_test_thread.finished.connect(self._clear_cloud_image_test_worker)
        self._cloud_image_test_thread.start()

    def _test_cloud_video(self) -> None:
        if self._is_cloud_test_running():
            LOGGER.info("Cloud video understanding test ignored because a test is already running")
            return

        base_url = self.cloud_base_url.text().strip()
        model_name = self.cloud_model_name.text().strip()
        if not base_url:
            InfoBar.warning(
                title=t("model.cloud.test.failure.title"),
                content=t("model.cloud.models.baseUrlRequired"),
                parent=self.window(),
                position=InfoBarPosition.TOP_RIGHT,
                duration=4000,
            )
            return
        if not model_name:
            InfoBar.warning(
                title=t("model.cloud.test.failure.title"),
                content=t("model.cloud.test.modelRequired"),
                parent=self.window(),
                position=InfoBarPosition.TOP_RIGHT,
                duration=4000,
            )
            return
        if not VIDEO_TEST_ASSET.exists():
            short_error = self._short_error(t("model.test.video.assetMissing", path=VIDEO_TEST_ASSET.as_posix()))
            self._set_cloud_test_result_text(
                t(
                    "model.cloud.test.video.failureResult",
                    provider=self.cloud_provider_combo.currentText(),
                    base_url=base_url,
                    model_name=model_name,
                    asset=VIDEO_TEST_ASSET.as_posix(),
                    error=short_error,
                )
            )
            InfoBar.warning(
                title=t("model.cloud.test.failure.title"),
                content=short_error,
                parent=self.window(),
                position=InfoBarPosition.TOP_RIGHT,
                duration=5000,
            )
            return

        self.test_cloud_model_button.setEnabled(False)
        self.test_cloud_model_button.setText(t("model.cloud.test.running"))
        self._cloud_stream_kind = ""
        locale = current_locale()
        self._cloud_video_test_thread = QThread(self)
        self._cloud_video_test_worker = CloudVideoTestWorker(
            provider=self._current_cloud_provider_id(),
            base_url=base_url,
            api_key=self.cloud_api_key.text().strip(),
            model_name=model_name,
            video_path=VIDEO_TEST_ASSET,
            video_fps=self._current_cloud_video_fps(),
            locale=locale,
        )
        self._cloud_video_stream_buffer = ""
        self._cloud_video_test_worker.moveToThread(self._cloud_video_test_thread)
        self._cloud_video_test_thread.started.connect(self._cloud_video_test_worker.run)
        self._cloud_video_test_worker.progressChanged.connect(self._show_cloud_video_test_stream)
        self._cloud_video_test_worker.succeeded.connect(self._show_cloud_video_test_success)
        self._cloud_video_test_worker.failed.connect(self._show_cloud_video_test_failure)
        self._cloud_video_test_worker.finished.connect(self._cloud_video_test_thread.quit)
        self._cloud_video_test_worker.finished.connect(self._cloud_video_test_worker.deleteLater)
        self._cloud_video_test_thread.finished.connect(self._cloud_video_test_thread.deleteLater)
        self._cloud_video_test_thread.finished.connect(self._clear_cloud_video_test_worker)
        self._cloud_video_test_thread.start()

    def _test_cloud_all(self, *, text_prompt_override: str | None = None) -> None:
        if self._is_cloud_test_running():
            LOGGER.info("Cloud all-modal test ignored because a test is already running")
            return

        base_url = self.cloud_base_url.text().strip()
        model_name = self.cloud_model_name.text().strip()
        if not base_url:
            InfoBar.warning(
                title=t("model.cloud.test.failure.title"),
                content=t("model.cloud.models.baseUrlRequired"),
                parent=self.window(),
                position=InfoBarPosition.TOP_RIGHT,
                duration=4000,
            )
            return
        if not model_name:
            InfoBar.warning(
                title=t("model.cloud.test.failure.title"),
                content=t("model.cloud.test.modelRequired"),
                parent=self.window(),
                position=InfoBarPosition.TOP_RIGHT,
                duration=4000,
            )
            return

        self.test_cloud_model_button.setEnabled(False)
        self.test_cloud_model_button.setText(t("model.cloud.test.running"))
        locale = current_locale()
        self._cloud_all_test_thread = QThread(self)
        self._cloud_all_test_worker = CloudAllTestWorker(
            provider=self._current_cloud_provider_id(),
            base_url=base_url,
            api_key=self.cloud_api_key.text().strip(),
            model_name=model_name,
            image_path=IMAGE_TEST_ASSET,
            video_path=VIDEO_TEST_ASSET,
            video_fps=self._current_cloud_video_fps(),
            locale=locale,
            text_prompt_override=text_prompt_override,
        )
        self._cloud_all_stream_buffers = {"text": "", "image": "", "video": ""}
        self._cloud_all_token_usage = {"text": {}, "image": {}, "video": {}}
        self._cloud_all_section_status = {"text": "queued", "image": "queued", "video": "queued"}
        self._cloud_all_final_summary = ""
        self._set_cloud_test_result_text(self._render_cloud_all_report(None))
        self._cloud_all_test_worker.moveToThread(self._cloud_all_test_thread)
        self._cloud_all_test_thread.started.connect(self._cloud_all_test_worker.run)
        self._cloud_all_test_worker.progressChanged.connect(self._show_cloud_all_test_stream)
        self._cloud_all_test_worker.sectionStarted.connect(self._show_cloud_all_test_section_started)
        self._cloud_all_test_worker.sectionFinished.connect(self._show_cloud_all_test_section_finished)
        self._cloud_all_test_worker.succeeded.connect(self._show_cloud_all_test_result)
        self._cloud_all_test_worker.failed.connect(self._show_cloud_all_test_failure)
        self._cloud_all_test_worker.finished.connect(self._cloud_all_test_thread.quit)
        self._cloud_all_test_worker.finished.connect(self._cloud_all_test_worker.deleteLater)
        self._cloud_all_test_thread.finished.connect(self._cloud_all_test_thread.deleteLater)
        self._cloud_all_test_thread.finished.connect(self._clear_cloud_all_test_worker)
        self._cloud_all_test_thread.start()

    def _record_cloud_easter_tap(self) -> None:
        if self._cloud_easter_tap_count >= EASTER_TAP_TARGET + 1:
            self._cloud_easter_tap_count = 0
        self._cloud_easter_tap_count += 1

    def _consume_cloud_all_easter_prompt(self) -> str | None:
        matched = self._cloud_easter_tap_count == EASTER_TAP_TARGET
        self._reset_cloud_easter_tap_counter()
        if matched:
            LOGGER.info("Model page easter egg triggered")
            return EASTER_PROMPT_OVERRIDE
        return None

    def _reset_cloud_easter_tap_counter(self) -> None:
        self._cloud_easter_tap_count = 0

    def _show_cloud_text_test_success(self, payload: dict) -> None:
        content = str(payload.get("content", "")).strip() or t("model.cloud.test.empty")
        token_usage = payload.get("token_usage") if isinstance(payload.get("token_usage"), dict) else {}
        response = f"{content}\n{_format_token_usage_line(token_usage)}"
        locale = current_locale()
        self._set_cloud_test_result_text(
            t(
                "model.cloud.test.text.successResult",
                provider=self.cloud_provider_combo.currentText(),
                base_url=self.cloud_base_url.text().strip() or t("model.cloud.test.empty"),
                model_name=self.cloud_model_name.text().strip() or t("model.cloud.test.empty"),
                target_language=_response_language_name(locale),
                response=response,
            )
        )
        InfoBar.success(
            title=t("model.cloud.test.success.title"),
            content=t("model.cloud.test.success.content"),
            parent=self.window(),
            position=InfoBarPosition.TOP_RIGHT,
            duration=3000,
        )

    def _show_cloud_text_test_stream(self, delta: str) -> None:
        self._cloud_text_stream_buffer += delta
        self._append_cloud_stream_delta("text", delta)

    def _show_cloud_text_test_failure(self, error: str) -> None:
        short_error = self._short_error(error)
        self._set_cloud_test_result_text(
            t(
                "model.cloud.test.text.failureResult",
                provider=self.cloud_provider_combo.currentText(),
                base_url=self.cloud_base_url.text().strip() or t("model.cloud.test.empty"),
                model_name=self.cloud_model_name.text().strip() or t("model.cloud.test.empty"),
                error=short_error,
            )
        )
        InfoBar.warning(
            title=t("model.cloud.test.failure.title"),
            content=t("model.cloud.test.failure.content", error=short_error),
            parent=self.window(),
            position=InfoBarPosition.TOP_RIGHT,
            duration=7000,
        )

    def _show_cloud_image_test_success(self, payload: dict) -> None:
        content = str(payload.get("content", "")).strip() or t("model.cloud.test.empty")
        token_usage = payload.get("token_usage") if isinstance(payload.get("token_usage"), dict) else {}
        response = f"{content}\n{_format_token_usage_line(token_usage)}"
        locale = current_locale()
        self._set_cloud_test_result_text(
            t(
                "model.cloud.test.image.successResult",
                provider=self.cloud_provider_combo.currentText(),
                base_url=self.cloud_base_url.text().strip() or t("model.cloud.test.empty"),
                model_name=self.cloud_model_name.text().strip() or t("model.cloud.test.empty"),
                asset=IMAGE_TEST_ASSET.relative_to(APP_ROOT).as_posix(),
                target_language=_response_language_name(locale),
                response=response,
            )
        )
        InfoBar.success(
            title=t("model.cloud.test.success.title"),
            content=t("model.cloud.test.success.content"),
            parent=self.window(),
            position=InfoBarPosition.TOP_RIGHT,
            duration=3000,
        )

    def _show_cloud_image_test_stream(self, delta: str) -> None:
        self._cloud_image_stream_buffer += delta
        self._append_cloud_stream_delta("image", delta)

    def _show_cloud_image_test_failure(self, error: str) -> None:
        short_error = self._short_error(error)
        self._set_cloud_test_result_text(
            t(
                "model.cloud.test.image.failureResult",
                provider=self.cloud_provider_combo.currentText(),
                base_url=self.cloud_base_url.text().strip() or t("model.cloud.test.empty"),
                model_name=self.cloud_model_name.text().strip() or t("model.cloud.test.empty"),
                asset=IMAGE_TEST_ASSET.relative_to(APP_ROOT).as_posix(),
                error=short_error,
            )
        )
        InfoBar.warning(
            title=t("model.cloud.test.failure.title"),
            content=t("model.cloud.test.failure.content", error=short_error),
            parent=self.window(),
            position=InfoBarPosition.TOP_RIGHT,
            duration=7000,
        )

    def _is_cloud_test_running(self) -> bool:
        return any(
            thread is not None
            for thread in (
                self._cloud_text_test_thread,
                self._cloud_image_test_thread,
                self._cloud_video_test_thread,
                self._cloud_all_test_thread,
            )
        )

    def _clear_cloud_text_test_worker(self) -> None:
        self.test_cloud_model_button.setEnabled(True)
        self.test_cloud_model_button.setText(t("model.cloud.test"))
        self._cloud_text_test_thread = None
        self._cloud_text_test_worker = None

    def _clear_cloud_image_test_worker(self) -> None:
        self.test_cloud_model_button.setEnabled(True)
        self.test_cloud_model_button.setText(t("model.cloud.test"))
        self._cloud_image_test_thread = None
        self._cloud_image_test_worker = None

    def _show_cloud_video_test_success(self, payload: dict) -> None:
        content = str(payload.get("content", "")).strip() or t("model.cloud.test.empty")
        token_usage = payload.get("token_usage") if isinstance(payload.get("token_usage"), dict) else {}
        response = f"{content}\n{_format_token_usage_line(token_usage)}"
        locale = current_locale()
        self._set_cloud_test_result_text(
            t(
                "model.cloud.test.video.successResult",
                provider=self.cloud_provider_combo.currentText(),
                base_url=self.cloud_base_url.text().strip() or t("model.cloud.test.empty"),
                model_name=self.cloud_model_name.text().strip() or t("model.cloud.test.empty"),
                asset=VIDEO_TEST_ASSET.relative_to(APP_ROOT).as_posix(),
                target_language=_response_language_name(locale),
                response=response,
            )
        )
        InfoBar.success(
            title=t("model.cloud.test.success.title"),
            content=t("model.cloud.test.success.content"),
            parent=self.window(),
            position=InfoBarPosition.TOP_RIGHT,
            duration=3000,
        )

    def _show_cloud_video_test_stream(self, delta: str) -> None:
        self._cloud_video_stream_buffer += delta
        self._append_cloud_stream_delta("video", delta)

    def _show_cloud_video_test_failure(self, error: str) -> None:
        short_error = self._short_error(error)
        self._set_cloud_test_result_text(
            t(
                "model.cloud.test.video.failureResult",
                provider=self.cloud_provider_combo.currentText(),
                base_url=self.cloud_base_url.text().strip() or t("model.cloud.test.empty"),
                model_name=self.cloud_model_name.text().strip() or t("model.cloud.test.empty"),
                asset=VIDEO_TEST_ASSET.relative_to(APP_ROOT).as_posix(),
                error=short_error,
            )
        )
        InfoBar.warning(
            title=t("model.cloud.test.failure.title"),
            content=t("model.cloud.test.failure.content", error=short_error),
            parent=self.window(),
            position=InfoBarPosition.TOP_RIGHT,
            duration=7000,
        )

    def _clear_cloud_video_test_worker(self) -> None:
        self.test_cloud_model_button.setEnabled(True)
        self.test_cloud_model_button.setText(t("model.cloud.test"))
        self._cloud_video_test_thread = None
        self._cloud_video_test_worker = None

    def _show_cloud_all_test_result(self, results: dict) -> None:
        text_result = results.get("text", {})
        image_result = results.get("image", {})
        video_result = results.get("video", {})
        locale = current_locale()
        success_count = sum(1 for item in (text_result, image_result, video_result) if item.get("status") == "ok")
        all_ok = success_count == 3
        failed_items: list[str] = []
        for key, item in (("text", text_result), ("image", image_result), ("video", video_result)):
            if item.get("status") != "ok":
                failed_items.append(t(f"model.test.type.{key}"))
        summary = (
            t("model.cloud.test.all.final.success")
            if all_ok
            else t("model.cloud.test.all.final.failure", failed_items=_join_failed_items(failed_items, locale))
        )
        if text_result.get("status") == "ok":
            self._cloud_all_stream_buffers["text"] = text_result.get("content", "")
            self._cloud_all_section_status["text"] = "ok"
            self._cloud_all_token_usage["text"] = text_result.get("token_usage", {})
        else:
            self._cloud_all_section_status["text"] = "error"
            self._cloud_all_token_usage["text"] = {}
        if image_result.get("status") == "ok":
            self._cloud_all_stream_buffers["image"] = image_result.get("content", "")
            self._cloud_all_section_status["image"] = "ok"
            self._cloud_all_token_usage["image"] = image_result.get("token_usage", {})
        else:
            self._cloud_all_section_status["image"] = "error"
            self._cloud_all_token_usage["image"] = {}
        if video_result.get("status") == "ok":
            self._cloud_all_stream_buffers["video"] = video_result.get("content", "")
            self._cloud_all_section_status["video"] = "ok"
            self._cloud_all_token_usage["video"] = video_result.get("token_usage", {})
        else:
            self._cloud_all_section_status["video"] = "error"
            self._cloud_all_token_usage["video"] = {}
        self._cloud_all_final_summary = summary
        self._set_cloud_test_result_text(self._render_cloud_all_report(summary))
        if all_ok:
            InfoBar.success(
                title=t("model.cloud.test.success.title"),
                content=t("model.cloud.test.success.content"),
                parent=self.window(),
                position=InfoBarPosition.TOP_RIGHT,
                duration=3000,
            )
        else:
            InfoBar.warning(
                title=t("model.cloud.test.failure.title"),
                content=t("model.cloud.test.partialFailure.content"),
                parent=self.window(),
                position=InfoBarPosition.TOP_RIGHT,
                duration=5000,
            )

    def _show_cloud_all_test_stream(self, section: str, delta: str) -> None:
        if section not in self._cloud_all_stream_buffers:
            return
        if self._cloud_all_section_status.get(section) == "queued":
            self._cloud_all_section_status[section] = "running"
        self._cloud_all_stream_buffers[section] += delta
        self._set_cloud_test_result_text(self._render_cloud_all_report(None))

    def _show_cloud_all_test_section_started(self, section: str) -> None:
        if section not in self._cloud_all_section_status:
            return
        self._cloud_all_section_status[section] = "running"
        self._set_cloud_test_result_text(self._render_cloud_all_report(None))

    def _show_cloud_all_test_section_finished(self, section: str, status: str, token_usage: dict) -> None:
        if section not in self._cloud_all_section_status:
            return
        self._cloud_all_section_status[section] = "ok" if status == "ok" else "error"
        if status == "ok" and isinstance(token_usage, dict):
            self._cloud_all_token_usage[section] = token_usage
        elif status != "ok":
            self._cloud_all_token_usage[section] = {}
        self._set_cloud_test_result_text(self._render_cloud_all_report(None))

    def _render_cloud_all_report(self, final_summary: str | None) -> str:
        locale = current_locale()
        header_lines = [
            f"{t('model.cloud.provider')}：{self.cloud_provider_combo.currentText()}",
            f"{t('model.cloud.baseUrl')}：{self.cloud_base_url.text().strip() or t('model.cloud.test.empty')}",
            f"{t('model.cloud.modelName')}：{self.cloud_model_name.text().strip() or t('model.cloud.test.empty')}",
            f"{t('model.cloud.test.report.targetLanguage')}：{_response_language_name(locale)}",
            f"{t('model.cloud.test.report.imageAsset')}：{IMAGE_TEST_ASSET.relative_to(APP_ROOT).as_posix()}",
            f"{t('model.cloud.test.report.videoAsset')}：{VIDEO_TEST_ASSET.relative_to(APP_ROOT).as_posix()}",
        ]
        sections: list[str] = []
        for key in ("text", "image", "video"):
            status_key = self._cloud_all_section_status.get(key, "queued")
            content = self._cloud_all_stream_buffers.get(key, "")
            token_usage = self._cloud_all_token_usage.get(key, {})
            if status_key == "queued" and not content:
                continue
            status_text = t(f"model.cloud.test.status.{status_key}")
            body = content or status_text
            token_line = _format_token_usage_line(token_usage) if status_key == "ok" and token_usage else ""
            sections.extend(
                [
                    f"[{t(f'model.test.type.{key}')}] {status_text}",
                    body,
                    token_line,
                    "",
                ]
            )
        if not sections:
            sections.append(t("model.cloud.test.all.summary.running"))
        if final_summary:
            sections.extend(
                [
                    "",
                    f"{t('model.cloud.test.report.finalSummary')}：{final_summary}",
                ]
            )
        return "\n".join(header_lines + [""] + sections)

    def _show_cloud_all_test_failure(self, error: str) -> None:
        short_error = self._short_error(error)
        self._set_cloud_test_result_text(
            t(
                "model.cloud.test.failure.content",
                error=short_error,
            )
        )
        InfoBar.warning(
            title=t("model.cloud.test.failure.title"),
            content=t("model.cloud.test.failure.content", error=short_error),
            parent=self.window(),
            position=InfoBarPosition.TOP_RIGHT,
            duration=7000,
        )

    def _clear_cloud_all_test_worker(self) -> None:
        self.test_cloud_model_button.setEnabled(True)
        self.test_cloud_model_button.setText(t("model.cloud.test"))
        self._cloud_all_test_thread = None
        self._cloud_all_test_worker = None

    def _refresh_cloud_presets(
        self,
        selected_name: str | None = None,
        *,
        preloaded_presets: list[CloudModelPreset] | None = None,
    ) -> None:
        self._cloud_presets = list(preloaded_presets) if preloaded_presets is not None else load_cloud_model_presets()
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

    def _llamacpp_ready(self) -> bool:
        if self._llamacpp_ready_cache is None:
            self._llamacpp_ready_cache = has_llamacpp_binary()
        return self._llamacpp_ready_cache

    def _load_selected_cloud_preset(self) -> None:
        if self._loading_cloud_preset:
            return
        index = self.cloud_preset_combo.currentIndex() - 1
        if not 0 <= index < len(self._cloud_presets):
            if not self._restoring_model_selection:
                set_last_cloud_preset_name("")
            self.cloud_preset_name.clear()
            self._set_cloud_video_fps(DEFAULT_CLOUD_VIDEO_FPS)
            self._sync_cloud_video_fps_availability()
            return

        preset = self._cloud_presets[index]
        if not self._restoring_model_selection:
            set_last_cloud_preset_name(preset.name)
        self.cloud_preset_name.setText(preset.name)
        self.cloud_base_url.setText(preset.base_url)
        self.cloud_api_key.setText(preset.api_key)
        self.cloud_model_name.setText(preset.model_name)
        self._set_cloud_video_fps(preset.video_fps)
        provider_id = normalize_cloud_provider(preset.provider)
        provider_index = self.cloud_provider_combo.findData(provider_id)
        if provider_index < 0:
            provider_index = 0
        self.cloud_provider_combo.setCurrentIndex(provider_index)
        self._sync_cloud_video_fps_availability()

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
            provider=self._current_cloud_provider_id(),
            base_url=self.cloud_base_url.text().strip(),
            api_key=self.cloud_api_key.text().strip(),
            model_name=self.cloud_model_name.text().strip(),
            video_fps=self._current_cloud_video_fps(),
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
