from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QEvent, QObject, QSignalBlocker, QSize, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QIcon
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

from gui.pages.model_test_helpers import (
    build_data_url as _build_data_url,
    format_token_usage_line as _format_token_usage_line,
    join_failed_items as _join_failed_items,
    response_language_instruction as _response_language_instruction,
    response_language_name as _response_language_name,
    token_usage_from_metadata as _token_usage_from_metadata,
    token_usage_log_fields as _token_usage_log_fields,
)
from gui.widgets.dialog_middleware import FluentDialog
from gui.widgets.streaming_text_session import StreamingTextSession
from res.provider_icons import provider_icon_path
from utils.cloud_models import CloudModelListError, fetch_cloud_models
from utils.cloud_model_presets import (
    CLOUD_MAX_OUTPUT_TOKENS_MAX,
    CLOUD_MAX_OUTPUT_TOKENS_MIN,
    CLOUD_MAX_OUTPUT_TOKENS_STEP,
    DEFAULT_CLOUD_MAX_OUTPUT_TOKENS,
    CLOUD_PROVIDER_ALIYUN_BAILIAN,
    CLOUD_PROVIDER_IDS,
    DEFAULT_CLOUD_VIDEO_FPS,
    DEFAULT_CLOUD_API_SCHEMA,
    DEFAULT_VIDEO_INPUT_MODE,
    base_url_has_unresolved_placeholder,
    cloud_model_endpoint,
    CloudModelPreset,
    cloud_endpoint_requires_custom_base_url,
    cloud_model_provider,
    cloud_provider_endpoints,
    coerce_cloud_max_output_tokens,
    delete_cloud_model_preset,
    load_cloud_model_presets,
    normalize_cloud_api_schema,
    normalize_cloud_endpoint_id,
    normalize_cloud_provider,
    normalize_video_input_mode,
    provider_requires_aliyun_extra_body,
    provider_supports_capability,
    scale_cloud_max_output_tokens_for_video_duration,
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
from utils.ffmpeg_tool import FfmpegProcessError, probe_video_duration_seconds
from utils.ai_model_middleware import (
    ModelMiddlewareError,
    ModelCallRequest,
    ModelMessage,
    call_audio_model,
    call_image_model,
    call_text_model,
    call_video_model,
)


TEST_MEDIA_ROOT = APP_ROOT / "res" / "test_media"
IMAGE_TEST_ASSET = TEST_MEDIA_ROOT / "model_test_input.jpg"
AUDIO_TEST_ASSET = TEST_MEDIA_ROOT / "model_test_input.wav"
VIDEO_TEST_ASSET = TEST_MEDIA_ROOT / "model_test_input.mp4"
API_SCHEMA_IDS = ("openai_chat_completions", "dashscope_native")
VIDEO_INPUT_MODE_IDS = (
    "auto",
    "native_video",
    "frame_sampling",
    "frame_sampling_with_transcript",
    "audio_transcript_only",
)
LOGGER = logging.getLogger(__name__)
EASTER_TAP_TARGET = 9


def _video_max_output_tokens(max_output_tokens_per_minute: int, video_path: Path) -> int:
    try:
        duration_seconds = probe_video_duration_seconds(video_path)
    except (FfmpegProcessError, OSError):
        LOGGER.warning(
            "Cloud video test duration probe failed; video=%s",
            video_path,
            exc_info=True,
        )
        duration_seconds = 60.0
    max_tokens = scale_cloud_max_output_tokens_for_video_duration(
        max_output_tokens_per_minute,
        duration_seconds,
    )
    LOGGER.info(
        "Cloud video token budget calculated; video=%s duration_seconds=%.2f "
        "tokens_per_minute=%s request_max_tokens=%s",
        video_path.name,
        duration_seconds,
        max_output_tokens_per_minute,
        max_tokens,
    )
    return max_tokens


def _cloud_request_extra_body(provider: str) -> dict[str, Any]:
    if provider_requires_aliyun_extra_body(provider):
        return {"enable_thinking": False}
    return {}


def _status_payload(status: str, content: str) -> dict[str, Any]:
    return {"status": status, "content": content, "token_usage": {}}


def _video_mode_support_status(provider: str, video_input_mode: str) -> tuple[str, str] | None:
    mode = normalize_video_input_mode(video_input_mode, provider)
    if mode == "auto":
        if provider_supports_capability(provider, "native_video"):
            return None
        if provider_supports_capability(provider, "frame_sampling_video"):
            return None
        return ("model_unsupported", t("model.cloud.test.unsupported.video"))
    if mode == "native_video":
        if provider_supports_capability(provider, "native_video"):
            return None
        return ("api_unsupported", t("model.cloud.test.unsupported.nativeVideo"))
    if mode == "frame_sampling":
        if provider_supports_capability(provider, "frame_sampling_video"):
            return None
        return ("api_unsupported", t("model.cloud.test.unsupported.frameSampling"))
    if mode in {"frame_sampling_with_transcript", "audio_transcript_only"}:
        return ("skipped", t("model.cloud.test.unsupported.transcriptMode"))
    return ("api_unsupported", t("model.cloud.test.unsupported.video"))


def _model_supports_audio_understanding(provider: str, model_name: str) -> bool:
    provider_id = normalize_cloud_provider(provider)
    normalized_model = model_name.strip().lower().replace("_", "-")
    if provider_id == CLOUD_PROVIDER_ALIYUN_BAILIAN:
        return "omni" in normalized_model or "audio" in normalized_model
    return True


def _audio_backend_for_request(provider: str, api_schema: str) -> str:
    provider_id = normalize_cloud_provider(provider)
    normalized_schema = normalize_cloud_api_schema(api_schema, provider_id)
    if provider_id == CLOUD_PROVIDER_ALIYUN_BAILIAN and normalized_schema == "dashscope_native":
        return "dashscope"
    return cloud_model_provider(provider_id).backend_for("audio")


def _audio_input_support_status(
    provider: str,
    api_schema: str,
    model_name: str = "",
) -> tuple[str, str] | None:
    if not provider_supports_capability(provider, "audio_understanding"):
        return ("model_unsupported", t("model.cloud.test.unsupported.audio"))
    if model_name and not _model_supports_audio_understanding(provider, model_name):
        return ("model_unsupported", t("model.cloud.test.unsupported.audioModel"))
    normalized_schema = normalize_cloud_api_schema(api_schema, provider)
    backend = _audio_backend_for_request(provider, normalized_schema)
    if normalized_schema == "openai_chat_completions" and backend == "openai_compatible":
        return None
    if normalized_schema == "dashscope_native" and backend == "dashscope":
        return None
    return ("api_unsupported", t("model.cloud.test.unsupported.audioApi"))


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

    def __init__(self, provider: str, base_url: str, api_key: str, api_schema: str) -> None:
        super().__init__()
        self.provider = provider
        self.base_url = base_url
        self.api_key = api_key
        self.api_schema = api_schema

    def run(self) -> None:
        LOGGER.info("Cloud model list worker started; base_url=%s", self.base_url)
        try:
            models = fetch_cloud_models(self.provider, self.base_url, self.api_key, self.api_schema)
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

    def __init__(
        self,
        *,
        provider: str,
        base_url: str,
        api_key: str,
        model_name: str,
        max_output_tokens: int,
        locale: str,
    ) -> None:
        super().__init__()
        self.provider = provider
        self.base_url = base_url
        self.api_key = api_key
        self.model_name = model_name
        self.max_output_tokens = max_output_tokens
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
                max_tokens=self.max_output_tokens,
                stream=True,
                extra_body=_cloud_request_extra_body(self.provider),
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

    def __init__(
        self,
        *,
        provider: str,
        base_url: str,
        api_key: str,
        model_name: str,
        image_path: Path,
        max_output_tokens: int,
        locale: str,
    ) -> None:
        super().__init__()
        self.provider = provider
        self.base_url = base_url
        self.api_key = api_key
        self.model_name = model_name
        self.image_path = image_path
        self.max_output_tokens = max_output_tokens
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
                max_tokens=self.max_output_tokens,
                stream=True,
                extra_body=_cloud_request_extra_body(self.provider),
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


class CloudAudioTestWorker(QObject):
    progressChanged = pyqtSignal(str)
    succeeded = pyqtSignal(dict)
    failed = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(
        self,
        *,
        provider: str,
        api_schema: str,
        base_url: str,
        api_key: str,
        model_name: str,
        audio_path: Path,
        max_output_tokens: int,
        locale: str,
    ) -> None:
        super().__init__()
        self.provider = provider
        self.api_schema = api_schema
        self.base_url = base_url
        self.api_key = api_key
        self.model_name = model_name
        self.audio_path = audio_path
        self.max_output_tokens = max_output_tokens
        self.locale = locale

    def run(self) -> None:
        LOGGER.info(
            "Cloud audio understanding test started; base_url=%s model=%s audio=%s",
            self.base_url,
            self.model_name,
            self.audio_path,
        )
        try:
            unsupported = _audio_input_support_status(
                self.provider,
                self.api_schema,
                self.model_name,
            )
            if unsupported is not None:
                status, message = unsupported
                raise ModelMiddlewareError(f"{t(f'model.cloud.test.status.{status}')}: {message}")
            request = ModelCallRequest(
                purpose="connectivity_test_audio",
                backend=_audio_backend_for_request(self.provider, self.api_schema),
                model_name=self.model_name,
                base_url=self.base_url,
                api_key=self.api_key,
                temperature=0,
                max_tokens=self.max_output_tokens,
                stream=True,
                extra_body=_cloud_request_extra_body(self.provider),
                messages=[
                    ModelMessage(role="system", content="You are an audio connectivity test assistant."),
                    ModelMessage(
                        role="user",
                        content=[
                            {
                                "type": "audio",
                                "audio": str(self.audio_path.resolve()),
                                "format": "wav",
                            },
                            {
                                "type": "text",
                                "text": (
                                    f"{_response_language_instruction(self.locale)} "
                                    "Listen to the uploaded audio. Say briefly what you heard. "
                                    "Start with CHARA_AUDIO_OK: "
                                ),
                            },
                        ],
                    ),
                ],
                metadata={"scene": "model_page_audio_test", "api_schema": self.api_schema},
            )
            result = call_audio_model(
                request,
                on_stream_delta=lambda delta: self.progressChanged.emit(delta),
            )
        except (ModelMiddlewareError, OSError, ValueError) as exc:
            LOGGER.warning("Cloud audio understanding test failed", exc_info=True)
            self.failed.emit(str(exc))
        else:
            prompt_tokens, completion_tokens, total_tokens = _token_usage_log_fields(result.metadata)
            LOGGER.info(
                "Cloud audio understanding test succeeded; prompt_tokens=%s completion_tokens=%s total_tokens=%s",
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
        video_input_mode: str,
        max_output_tokens: int,
        locale: str,
    ) -> None:
        super().__init__()
        self.provider = provider
        self.base_url = base_url
        self.api_key = api_key
        self.model_name = model_name
        self.video_path = video_path
        self.video_fps = video_fps
        self.video_input_mode = video_input_mode
        self.max_output_tokens = max_output_tokens
        self.locale = locale

    def run(self) -> None:
        LOGGER.info(
            "Cloud video understanding test started; base_url=%s model=%s video=%s",
            self.base_url,
            self.model_name,
            self.video_path,
        )
        try:
            unsupported = _video_mode_support_status(self.provider, self.video_input_mode)
            if unsupported is not None:
                status, message = unsupported
                raise ModelMiddlewareError(f"{t(f'model.cloud.test.status.{status}')}: {message}")
            max_tokens = _video_max_output_tokens(self.max_output_tokens, self.video_path)
            request = ModelCallRequest(
                purpose="connectivity_test_video",
                backend=cloud_model_provider(self.provider).backend_for("video"),
                model_name=self.model_name,
                base_url=self.base_url,
                api_key=self.api_key,
                temperature=0,
                max_tokens=max_tokens,
                extra_body=_cloud_request_extra_body(self.provider),
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
        audio_path: Path,
        video_path: Path,
        api_schema: str,
        video_fps: float,
        video_input_mode: str,
        max_output_tokens: int,
        locale: str,
        text_prompt_override: str | None = None,
    ) -> None:
        super().__init__()
        self.provider = provider
        self.base_url = base_url
        self.api_key = api_key
        self.model_name = model_name
        self.image_path = image_path
        self.audio_path = audio_path
        self.video_path = video_path
        self.api_schema = api_schema
        self.video_fps = video_fps
        self.video_input_mode = video_input_mode
        self.max_output_tokens = max_output_tokens
        self.locale = locale
        self.text_prompt_override = text_prompt_override

    def run(self) -> None:
        LOGGER.info("Cloud all-modal test started; base_url=%s model=%s", self.base_url, self.model_name)
        try:
            results = {
                "text": self._run_text_test(),
                "image": self._run_image_test(),
                "audio": self._run_audio_test(),
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
        emitted_stream_delta = False

        def emit_stream_delta(delta: str) -> None:
            nonlocal emitted_stream_delta
            if delta:
                emitted_stream_delta = True
            self.progressChanged.emit(section, delta)

        try:
            if section == "image":
                result = call_image_model(
                    request,
                    on_stream_delta=emit_stream_delta,
                )
            elif section == "audio":
                result = call_audio_model(
                    request,
                    on_stream_delta=emit_stream_delta,
                )
            elif section == "video":
                result = call_video_model(
                    request,
                    on_stream_delta=emit_stream_delta,
                )
            else:
                result = call_text_model(
                    request,
                    on_stream_delta=emit_stream_delta,
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
            if payload["content"] and not emitted_stream_delta:
                self.progressChanged.emit(section, payload["content"])
            self.sectionFinished.emit(section, "ok", payload["token_usage"])
            return payload
        except Exception as exc:  # noqa: BLE001
            self.sectionFinished.emit(section, "error", {})
            return {"status": "error", "content": str(exc)}

    def _unsupported_section(self, section: str, status: str, message: str) -> dict[str, Any]:
        self.sectionStarted.emit(section)
        self.sectionFinished.emit(section, status, {})
        return _status_payload(status, message)

    def _run_text_test(self) -> dict[str, str]:
        if self.text_prompt_override:
            user_prompt = self.text_prompt_override
        else:
            user_prompt = (
                f"{_response_language_instruction(self.locale)} "
                "Output exactly two lines: "
                "MODEL: <the model id you are running as>; "
                "SUMMARY: <one-sentence self-introduction>."
            )
        request = ModelCallRequest(
            purpose="connectivity_test",
            backend=cloud_model_provider(self.provider).backend_for("text"),
            model_name=self.model_name,
            base_url=self.base_url,
            api_key=self.api_key,
            temperature=0,
            max_tokens=self.max_output_tokens,
            stream=True,
            extra_body=_cloud_request_extra_body(self.provider),
            messages=[
                ModelMessage(role="system", content="You are a model connectivity test assistant."),
                ModelMessage(role="user", content=user_prompt),
            ],
            metadata={"scene": "model_page_text_test"},
        )
        return self._safe_call(request, "text")

    def _run_image_test(self) -> dict[str, str]:
        if not provider_supports_capability(self.provider, "image"):
            return self._unsupported_section(
                "image",
                "model_unsupported",
                t("model.cloud.test.unsupported.image"),
            )
        image_data_url = _build_data_url(self.image_path, "image/jpeg")
        request = ModelCallRequest(
            purpose="connectivity_test_image",
            backend=cloud_model_provider(self.provider).backend_for("image"),
            model_name=self.model_name,
            base_url=self.base_url,
            api_key=self.api_key,
            temperature=0,
            max_tokens=self.max_output_tokens,
            stream=True,
            extra_body=_cloud_request_extra_body(self.provider),
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

    def _run_audio_test(self) -> dict[str, str]:
        unsupported = _audio_input_support_status(
            self.provider,
            self.api_schema,
            self.model_name,
        )
        if unsupported is not None:
            status, message = unsupported
            return self._unsupported_section("audio", status, message)
        request = ModelCallRequest(
            purpose="connectivity_test_audio",
            backend=_audio_backend_for_request(self.provider, self.api_schema),
            model_name=self.model_name,
            base_url=self.base_url,
            api_key=self.api_key,
            temperature=0,
            max_tokens=self.max_output_tokens,
            stream=True,
            extra_body=_cloud_request_extra_body(self.provider),
            messages=[
                ModelMessage(role="system", content="You are an audio connectivity test assistant."),
                ModelMessage(
                    role="user",
                    content=[
                        {"type": "audio", "audio": str(self.audio_path.resolve()), "format": "wav"},
                        {
                            "type": "text",
                            "text": (
                                f"{_response_language_instruction(self.locale)} "
                                "Listen to the uploaded audio. Say briefly what you heard. "
                                "Start with CHARA_AUDIO_OK: "
                            ),
                        },
                    ],
                ),
            ],
            metadata={"scene": "model_page_audio_test", "api_schema": self.api_schema},
        )
        return self._safe_call(request, "audio")

    def _run_video_test(self) -> dict[str, str]:
        unsupported = _video_mode_support_status(self.provider, self.video_input_mode)
        if unsupported is not None:
            status, message = unsupported
            return self._unsupported_section("video", status, message)
        max_tokens = _video_max_output_tokens(self.max_output_tokens, self.video_path)
        request = ModelCallRequest(
            purpose="connectivity_test_video",
            backend=cloud_model_provider(self.provider).backend_for("video"),
            model_name=self.model_name,
            base_url=self.base_url,
            api_key=self.api_key,
            temperature=0,
            max_tokens=max_tokens,
            extra_body=_cloud_request_extra_body(self.provider),
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
        self._cloud_audio_test_thread: QThread | None = None
        self._cloud_audio_test_worker: CloudAudioTestWorker | None = None
        self._cloud_video_test_thread: QThread | None = None
        self._cloud_video_test_worker: CloudVideoTestWorker | None = None
        self._cloud_all_test_thread: QThread | None = None
        self._cloud_all_test_worker: CloudAllTestWorker | None = None
        self._cloud_text_stream_buffer = ""
        self._cloud_image_stream_buffer = ""
        self._cloud_audio_stream_buffer = ""
        self._cloud_video_stream_buffer = ""
        self._cloud_all_stream_buffers: dict[str, str] = {
            "text": "",
            "image": "",
            "audio": "",
            "video": "",
        }
        self._cloud_all_token_usage: dict[str, dict[str, int]] = {
            "text": {},
            "image": {},
            "audio": {},
            "video": {},
        }
        self._cloud_all_section_status: dict[str, str] = {
            "text": "queued",
            "image": "queued",
            "audio": "queued",
            "video": "queued",
        }
        self._cloud_all_final_summary = ""
        self._last_valid_cloud_video_fps = DEFAULT_CLOUD_VIDEO_FPS
        self._last_valid_cloud_max_output_tokens = DEFAULT_CLOUD_MAX_OUTPUT_TOKENS
        self._cloud_stream_session: StreamingTextSession | None = None
        self._cloud_stream_kind = ""
        self._cloud_presets: list[CloudModelPreset] = []
        self._loading_cloud_preset = False
        self._restoring_model_selection = False
        self._syncing_cloud_endpoint_options = False
        self._syncing_cloud_video_fps_slider_from_text = False
        self._syncing_cloud_max_output_tokens_slider_from_text = False
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
        self.local_test_type_combo.addItem(t("model.test.type.all"), userData="all")
        self.local_test_type_combo.addItem(t("model.test.type.text"), userData="text")
        self.local_test_type_combo.addItem(t("model.test.type.image"), userData="image")
        self.local_test_type_combo.addItem(t("model.test.type.audio"), userData="audio")
        self.local_test_type_combo.addItem(t("model.test.type.video"), userData="video")
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
        self.cloud_provider_combo.setIconSize(QSize(20, 20))
        for provider_id in CLOUD_PROVIDER_IDS:
            provider = cloud_model_provider(provider_id)
            item_index = self.cloud_provider_combo.count()
            self.cloud_provider_combo.addItem(t(provider.label_key), userData=provider.provider_id)
            icon_path = provider_icon_path(provider.icon_id)
            if icon_path is not None:
                icon = QIcon(str(icon_path))
                if not icon.isNull():
                    self.cloud_provider_combo.setItemIcon(item_index, icon)

        self.cloud_endpoint_combo = ComboBox(self.cloud_card)

        self.cloud_base_url = LineEdit(self.cloud_card)
        self.cloud_base_url.setPlaceholderText(t("model.cloud.baseUrl.placeholder"))

        self.cloud_api_schema_combo = ComboBox(self.cloud_card)
        for schema_id in API_SCHEMA_IDS:
            self.cloud_api_schema_combo.addItem(
                t(f"model.cloud.apiSchema.{schema_id}"),
                userData=schema_id,
            )

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

        self.cloud_video_input_mode_combo = ComboBox(self.cloud_card)
        for mode_id in VIDEO_INPUT_MODE_IDS:
            self.cloud_video_input_mode_combo.addItem(
                t(f"model.cloud.videoInputMode.{mode_id}"),
                userData=mode_id,
            )

        max_output_tokens_row = QHBoxLayout()
        max_output_tokens_row.setSpacing(8)
        self.cloud_max_output_tokens_slider = Slider(Qt.Orientation.Horizontal, self.cloud_card)
        self.cloud_max_output_tokens_slider.setRange(
            CLOUD_MAX_OUTPUT_TOKENS_MIN // CLOUD_MAX_OUTPUT_TOKENS_STEP,
            CLOUD_MAX_OUTPUT_TOKENS_MAX // CLOUD_MAX_OUTPUT_TOKENS_STEP,
        )
        self.cloud_max_output_tokens_slider.setValue(
            DEFAULT_CLOUD_MAX_OUTPUT_TOKENS // CLOUD_MAX_OUTPUT_TOKENS_STEP
        )
        self.cloud_max_output_tokens_slider.setMaximumWidth(220)
        self.cloud_max_output_tokens = LineEdit(self.cloud_card)
        self.cloud_max_output_tokens.setPlaceholderText(str(DEFAULT_CLOUD_MAX_OUTPUT_TOKENS))
        self.cloud_max_output_tokens.setText(str(DEFAULT_CLOUD_MAX_OUTPUT_TOKENS))
        self.cloud_max_output_tokens.setMaximumWidth(82)
        max_output_tokens_row.addWidget(self.cloud_max_output_tokens_slider, 1)
        max_output_tokens_row.addWidget(self.cloud_max_output_tokens)

        self.test_cloud_model_button = PushButton(t("model.cloud.test"), self.cloud_card)
        self.cloud_test_action_label = SecretTapLabel(t("model.cloud.test.action"), self.cloud_card)
        self.cloud_test_type_combo = ComboBox(self.cloud_card)
        self.cloud_test_type_combo.addItem(t("model.test.type.all"), userData="all")
        self.cloud_test_type_combo.addItem(t("model.test.type.text"), userData="text")
        self.cloud_test_type_combo.addItem(t("model.test.type.image"), userData="image")
        self.cloud_test_type_combo.addItem(t("model.test.type.audio"), userData="audio")
        self.cloud_test_type_combo.addItem(t("model.test.type.video"), userData="video")
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

        connection_grid.addWidget(BodyLabel(t("model.cloud.endpoint"), self.cloud_card), 2, 0)
        connection_grid.addWidget(self.cloud_endpoint_combo, 2, 1)
        connection_grid.addWidget(BodyLabel(t("model.cloud.apiSchema"), self.cloud_card), 2, 2)
        connection_grid.addWidget(self.cloud_api_schema_combo, 2, 3, 1, 2)

        connection_grid.addWidget(BodyLabel(t("model.cloud.baseUrl"), self.cloud_card), 3, 0)
        connection_grid.addWidget(self.cloud_base_url, 3, 1, 1, 4)
        connection_grid.addWidget(BodyLabel(t("model.cloud.apiKey"), self.cloud_card), 4, 0)
        connection_grid.addWidget(self.cloud_api_key, 4, 1, 1, 4)

        connection_grid.addWidget(BodyLabel(t("model.cloud.videoInputMode"), self.cloud_card), 5, 0)
        connection_grid.addWidget(self.cloud_video_input_mode_combo, 5, 1)
        connection_grid.addWidget(BodyLabel(t("model.cloud.videoFps"), self.cloud_card), 5, 2)
        connection_grid.addLayout(video_fps_row, 5, 3, 1, 2)

        connection_grid.addWidget(BodyLabel(t("model.cloud.maxOutputTokens"), self.cloud_card), 6, 0)
        connection_grid.addLayout(max_output_tokens_row, 6, 1)
        connection_grid.addWidget(BodyLabel(t("model.test.type"), self.cloud_card), 6, 2)
        connection_grid.addWidget(self.cloud_test_type_combo, 6, 3, 1, 2)

        connection_grid.addWidget(self.cloud_test_action_label, 7, 0)
        connection_grid.addWidget(self.test_cloud_model_button, 7, 1, 1, 4)
        connection_grid.addWidget(
            BodyLabel(t("model.cloud.test.result"), self.cloud_card),
            8,
            0,
            1,
            1,
            Qt.AlignmentFlag.AlignTop,
        )
        connection_grid.addWidget(self.cloud_test_result, 8, 1, 1, 4)
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
        self.cloud_video_fps.textChanged.connect(self._sync_cloud_video_fps_from_text)
        self.cloud_video_fps.editingFinished.connect(self._commit_cloud_video_fps_text)
        self.cloud_max_output_tokens_slider.valueChanged.connect(
            self._sync_cloud_max_output_tokens_from_slider
        )
        self.cloud_max_output_tokens.textChanged.connect(self._sync_cloud_max_output_tokens_from_text)
        self.cloud_max_output_tokens.editingFinished.connect(self._commit_cloud_max_output_tokens_text)
        self.cloud_video_fps.installEventFilter(self)
        self.cloud_max_output_tokens.installEventFilter(self)
        self.cloud_provider_combo.currentIndexChanged.connect(self._on_cloud_provider_changed)
        self.cloud_endpoint_combo.currentIndexChanged.connect(self._on_cloud_endpoint_changed)
        self.cloud_video_input_mode_combo.currentIndexChanged.connect(
            self._sync_cloud_video_input_mode_availability
        )
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
        if kind == "audio":
            return t(
                "model.cloud.test.audio.successResult",
                provider=provider,
                base_url=base_url,
                model_name=model_name,
                asset=AUDIO_TEST_ASSET.relative_to(APP_ROOT).as_posix(),
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
                self.local_model_combo.addItem(t("model.local.models.empty"), userData="")
                self.test_local_model_button.setEnabled(False)
                return

            self.test_local_model_button.setEnabled(True)
            selected_index = 0
            for index, model_path in enumerate(candidates):
                display_path = model_path.as_posix()
                self.local_model_combo.addItem(display_path, userData=display_path)
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
                    audio_asset=AUDIO_TEST_ASSET.relative_to(APP_ROOT).as_posix(),
                    video_asset=VIDEO_TEST_ASSET.relative_to(APP_ROOT).as_posix(),
                )
            )
            return
        if test_type == "image":
            self.local_test_result.setPlainText(t("model.test.image.placeholderResult"))
            return
        if test_type == "audio":
            self.local_test_result.setPlainText(t("model.test.audio.placeholderResult"))
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

        base_url = self._validated_cloud_base_url(t("model.cloud.models.failure.title"))
        if base_url is None:
            return
        api_key = self.cloud_api_key.text().strip()

        LOGGER.info("Cloud model fetch requested; base_url=%s has_api_key=%s", base_url, bool(api_key))
        self.fetch_cloud_models_button.setEnabled(False)
        self.fetch_cloud_models_button.setText(t("model.cloud.models.fetching"))
        self._cloud_models_thread = QThread(self)
        self._cloud_models_worker = CloudModelListWorker(
            self._current_cloud_provider_id(),
            base_url,
            api_key,
            self._current_cloud_api_schema(),
        )
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

    def _current_cloud_endpoint_id(self) -> str:
        return normalize_cloud_endpoint_id(
            self._current_cloud_provider_id(),
            str(self.cloud_endpoint_combo.currentData() or ""),
            self.cloud_base_url.text().strip(),
        )

    def _current_cloud_api_schema(self) -> str:
        return normalize_cloud_api_schema(
            str(self.cloud_api_schema_combo.currentData() or DEFAULT_CLOUD_API_SCHEMA),
            self._current_cloud_provider_id(),
        )

    def _current_cloud_video_input_mode(self) -> str:
        return normalize_video_input_mode(
            str(self.cloud_video_input_mode_combo.currentData() or DEFAULT_VIDEO_INPUT_MODE),
            self._current_cloud_provider_id(),
        )

    def _set_cloud_combo_data(self, combo: ComboBox, value: str) -> None:
        index = combo.findData(value)
        if index < 0:
            index = 0
        with QSignalBlocker(combo):
            combo.setCurrentIndex(index)

    def _set_cloud_api_schema(self, api_schema: str) -> None:
        self._set_cloud_combo_data(
            self.cloud_api_schema_combo,
            normalize_cloud_api_schema(api_schema, self._current_cloud_provider_id()),
        )

    def _set_cloud_video_input_mode(self, video_input_mode: str) -> None:
        self._set_cloud_combo_data(
            self.cloud_video_input_mode_combo,
            normalize_video_input_mode(video_input_mode, self._current_cloud_provider_id()),
        )
        self._sync_cloud_video_input_mode_availability()

    def _sync_cloud_endpoint_options(
        self,
        selected_endpoint_id: str | None = None,
        base_url: str = "",
    ) -> None:
        provider_id = self._current_cloud_provider_id()
        endpoint_id = normalize_cloud_endpoint_id(
            provider_id,
            selected_endpoint_id or str(self.cloud_endpoint_combo.currentData() or ""),
            base_url or self.cloud_base_url.text().strip(),
        )
        self._syncing_cloud_endpoint_options = True
        try:
            with QSignalBlocker(self.cloud_endpoint_combo):
                self.cloud_endpoint_combo.clear()
                for endpoint in cloud_provider_endpoints(provider_id):
                    self.cloud_endpoint_combo.addItem(
                        t(endpoint.label_key),
                        userData=endpoint.endpoint_id,
                    )
                index = self.cloud_endpoint_combo.findData(endpoint_id)
                if index < 0:
                    index = 0
                self.cloud_endpoint_combo.setCurrentIndex(index)
        finally:
            self._syncing_cloud_endpoint_options = False
        self._apply_cloud_endpoint_to_base_url(preserve_existing=True)

    def _apply_cloud_endpoint_to_base_url(self, *, preserve_existing: bool) -> None:
        provider_id = self._current_cloud_provider_id()
        endpoint_id = self._current_cloud_endpoint_id()
        endpoint = cloud_model_endpoint(provider_id, endpoint_id)
        requires_custom_url = cloud_endpoint_requires_custom_base_url(provider_id, endpoint_id)
        self.cloud_base_url.setReadOnly(not requires_custom_url)
        self.cloud_base_url.setPlaceholderText(endpoint.base_url or t("model.cloud.baseUrl.placeholder"))
        if endpoint.has_placeholder:
            self.cloud_base_url.setToolTip(
                t(
                    "model.cloud.baseUrl.workspaceTooltip",
                    token=endpoint.placeholder_token,
                )
            )
        else:
            self.cloud_base_url.setToolTip("")
        if endpoint.base_url and (not preserve_existing or not self.cloud_base_url.text().strip()):
            self.cloud_base_url.setText(endpoint.base_url)
        elif not endpoint.base_url and not preserve_existing:
            self.cloud_base_url.clear()

    def _on_cloud_provider_changed(self) -> None:
        provider = cloud_model_provider(self._current_cloud_provider_id())
        self._sync_cloud_endpoint_options(provider.default_endpoint_id)
        self._set_cloud_api_schema(provider.default_api_schema)
        self._set_cloud_video_input_mode(provider.default_video_input_mode)
        self._apply_cloud_endpoint_to_base_url(preserve_existing=False)
        self._sync_cloud_video_fps_availability()

    def _on_cloud_endpoint_changed(self) -> None:
        if self._syncing_cloud_endpoint_options:
            return
        self._apply_cloud_endpoint_to_base_url(preserve_existing=False)

    def _validated_cloud_base_url(self, title: str) -> str | None:
        base_url = self.cloud_base_url.text().strip()
        if not base_url:
            LOGGER.warning("Cloud action blocked because base URL is empty")
            InfoBar.warning(
                title=title,
                content=t("model.cloud.models.baseUrlRequired"),
                parent=self.window(),
                position=InfoBarPosition.TOP_RIGHT,
                duration=4000,
            )
            return None
        if base_url_has_unresolved_placeholder(base_url):
            LOGGER.warning("Cloud action blocked because base URL contains an unresolved placeholder")
            InfoBar.warning(
                title=title,
                content=t("model.cloud.models.baseUrlPlaceholder", token="{WorkspaceId}"),
                parent=self.window(),
                position=InfoBarPosition.TOP_RIGHT,
                duration=5000,
            )
            return None
        return base_url

    def _current_cloud_video_fps(self) -> float:
        self._commit_cloud_video_fps_text()
        return self._last_valid_cloud_video_fps

    def _current_cloud_max_output_tokens(self) -> int:
        self._commit_cloud_max_output_tokens_text()
        return self._last_valid_cloud_max_output_tokens

    def current_cloud_video_preset(self) -> CloudModelPreset | None:
        base_url = self.cloud_base_url.text().strip()
        model_name = self.cloud_model_name.text().strip()
        if not base_url or not model_name:
            return None
        return CloudModelPreset(
            name=self.cloud_preset_name.text().strip() or self.cloud_preset_combo.currentText().strip(),
            provider=self._current_cloud_provider_id(),
            endpoint_id=self._current_cloud_endpoint_id(),
            base_url=base_url,
            api_schema=self._current_cloud_api_schema(),
            api_key=self.cloud_api_key.text().strip(),
            model_name=model_name,
            video_input_mode=self._current_cloud_video_input_mode(),
            video_fps=self._current_cloud_video_fps(),
            max_output_tokens=self._current_cloud_max_output_tokens(),
        )

    def current_cloud_preset_for_preview(self) -> CloudModelPreset | None:
        return self.current_cloud_video_preset()

    def _sync_cloud_video_fps_from_slider(self, value: int) -> None:
        if self._syncing_cloud_video_fps_slider_from_text:
            return
        self._set_cloud_video_fps(value / 10.0)

    def _sync_cloud_max_output_tokens_from_slider(self, value: int) -> None:
        if self._syncing_cloud_max_output_tokens_slider_from_text:
            return
        self._set_cloud_max_output_tokens(value * CLOUD_MAX_OUTPUT_TOKENS_STEP)

    def _sync_cloud_video_fps_from_text(self, text: str) -> None:
        try:
            value = float(text.strip())
        except ValueError:
            return
        if not 0.1 <= value <= 10.0:
            return
        normalized = round(value, 1)
        self._last_valid_cloud_video_fps = normalized
        self._set_cloud_video_fps_slider_value(int(round(normalized * 10)))

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
        self._set_cloud_video_fps_slider_value(slider_value)
        with QSignalBlocker(self.cloud_video_fps):
            self.cloud_video_fps.setText(f"{normalized:.1f}")

    def _set_cloud_video_fps_slider_value(self, slider_value: int) -> None:
        self._syncing_cloud_video_fps_slider_from_text = True
        try:
            self.cloud_video_fps_slider.setValue(slider_value)
        finally:
            self._syncing_cloud_video_fps_slider_from_text = False
        self.cloud_video_fps_slider._adjustHandlePos()
        self.cloud_video_fps_slider.update()

    def _sync_cloud_max_output_tokens_from_text(self, text: str) -> None:
        try:
            value = int(text.strip())
        except ValueError:
            return
        if value <= 0:
            return
        normalized = coerce_cloud_max_output_tokens(value)
        self._last_valid_cloud_max_output_tokens = normalized
        self._set_cloud_max_output_tokens_slider_value(
            normalized // CLOUD_MAX_OUTPUT_TOKENS_STEP
        )

    def _commit_cloud_max_output_tokens_text(self) -> None:
        try:
            value = int(self.cloud_max_output_tokens.text().strip())
        except ValueError:
            self._set_cloud_max_output_tokens(self._last_valid_cloud_max_output_tokens)
            return
        self._set_cloud_max_output_tokens(value)

    def _set_cloud_max_output_tokens(self, value: int) -> None:
        normalized = coerce_cloud_max_output_tokens(value)
        self._last_valid_cloud_max_output_tokens = normalized
        slider_value = normalized // CLOUD_MAX_OUTPUT_TOKENS_STEP
        self._set_cloud_max_output_tokens_slider_value(slider_value)
        with QSignalBlocker(self.cloud_max_output_tokens):
            self.cloud_max_output_tokens.setText(str(normalized))

    def _set_cloud_max_output_tokens_slider_value(self, slider_value: int) -> None:
        self._syncing_cloud_max_output_tokens_slider_from_text = True
        try:
            self.cloud_max_output_tokens_slider.setValue(slider_value)
        finally:
            self._syncing_cloud_max_output_tokens_slider_from_text = False
        self.cloud_max_output_tokens_slider._adjustHandlePos()
        self.cloud_max_output_tokens_slider.update()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.cloud_video_fps:
            self._schedule_cloud_video_fps_text_sync(event)
        elif watched is self.cloud_max_output_tokens:
            self._schedule_cloud_max_output_tokens_text_sync(event)
        return super().eventFilter(watched, event)

    def _schedule_cloud_video_fps_text_sync(self, event: QEvent) -> None:
        if event.type() in {
            QEvent.Type.KeyRelease,
            QEvent.Type.InputMethod,
            QEvent.Type.MouseButtonRelease,
        }:
            QTimer.singleShot(0, lambda: self._sync_cloud_video_fps_from_text(self.cloud_video_fps.text()))

    def _schedule_cloud_max_output_tokens_text_sync(self, event: QEvent) -> None:
        if event.type() in {
            QEvent.Type.KeyRelease,
            QEvent.Type.InputMethod,
            QEvent.Type.MouseButtonRelease,
        }:
            QTimer.singleShot(
                0,
                lambda: self._sync_cloud_max_output_tokens_from_text(
                    self.cloud_max_output_tokens.text()
                ),
            )

    def _sync_cloud_video_fps_availability(self) -> None:
        provider = cloud_model_provider(self._current_cloud_provider_id())
        video_input_mode = self._current_cloud_video_input_mode()
        supports_fps = provider.supports_video_fps and video_input_mode != "audio_transcript_only"
        if video_input_mode == "native_video":
            supports_fps = provider.video_fps_mode == "direct"
        elif video_input_mode in {"frame_sampling", "frame_sampling_with_transcript"}:
            supports_fps = provider_supports_capability(provider.provider_id, "frame_sampling_video")

        self.cloud_video_fps.setEnabled(supports_fps)
        self.cloud_video_fps_slider.setEnabled(supports_fps)
        tooltip = t(f"model.cloud.videoFps.mode.{provider.video_fps_mode}")
        self.cloud_video_fps.setToolTip(tooltip)
        self.cloud_video_fps_slider.setToolTip(tooltip)

    def _sync_cloud_video_input_mode_availability(self) -> None:
        video_input_mode = self._current_cloud_video_input_mode()
        unsupported = _video_mode_support_status(
            self._current_cloud_provider_id(),
            video_input_mode,
        )
        transcript_notice = (
            t("model.cloud.videoInputMode.transcriptNotice")
            if video_input_mode in {"frame_sampling_with_transcript", "audio_transcript_only"}
            else ""
        )
        if unsupported is None:
            tooltip = t("model.cloud.videoInputMode.supported")
        else:
            status, message = unsupported
            tooltip = t(
                "model.cloud.videoInputMode.unsupported",
                status=t(f"model.cloud.test.status.{status}"),
                reason=message,
            )
        if transcript_notice:
            tooltip = f"{tooltip}\n{transcript_notice}"
        self.cloud_video_input_mode_combo.setToolTip(tooltip)
        self._sync_cloud_video_fps_availability()

    def _test_cloud_model(self) -> None:
        test_type = self.cloud_test_type_combo.currentData() or "all"
        if test_type == "all":
            self._test_cloud_all(text_prompt_override=self._consume_cloud_all_easter_prompt())
            return
        self._reset_cloud_easter_tap_counter()
        if test_type == "image":
            self._test_cloud_image()
            return
        if test_type == "audio":
            self._test_cloud_audio()
            return
        if test_type == "video":
            self._test_cloud_video()
            return

        if self._is_cloud_test_running():
            LOGGER.info("Cloud text understanding test ignored because a test is already running")
            return

        base_url = self._validated_cloud_base_url(t("model.cloud.test.failure.title"))
        if base_url is None:
            return
        model_name = self.cloud_model_name.text().strip()
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
            max_output_tokens=self._current_cloud_max_output_tokens(),
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

    def _show_cloud_single_test_unsupported(self, test_type: str, status: str, message: str) -> None:
        status_text = t(f"model.cloud.test.status.{status}")
        template_key = f"model.cloud.test.{test_type}.unsupportedResult"
        asset_map = {
            "image": IMAGE_TEST_ASSET,
            "audio": AUDIO_TEST_ASSET,
            "video": VIDEO_TEST_ASSET,
        }
        asset = asset_map.get(test_type, VIDEO_TEST_ASSET)
        self._set_cloud_test_result_text(
            t(
                template_key,
                provider=self.cloud_provider_combo.currentText(),
                base_url=self.cloud_base_url.text().strip() or t("model.cloud.test.empty"),
                model_name=self.cloud_model_name.text().strip() or t("model.cloud.test.empty"),
                asset=asset.relative_to(APP_ROOT).as_posix(),
                status=status_text,
                reason=message,
            )
        )
        InfoBar.info(
            title=t("model.cloud.test.unsupported.title"),
            content=t("model.cloud.test.unsupported.content", status=status_text, reason=message),
            parent=self.window(),
            position=InfoBarPosition.TOP_RIGHT,
            duration=5000,
        )

    def _test_cloud_image(self) -> None:
        if self._is_cloud_test_running():
            LOGGER.info("Cloud image understanding test ignored because a test is already running")
            return

        base_url = self._validated_cloud_base_url(t("model.cloud.test.failure.title"))
        if base_url is None:
            return
        model_name = self.cloud_model_name.text().strip()
        if not model_name:
            InfoBar.warning(
                title=t("model.cloud.test.failure.title"),
                content=t("model.cloud.test.modelRequired"),
                parent=self.window(),
                position=InfoBarPosition.TOP_RIGHT,
                duration=4000,
            )
            return
        if not provider_supports_capability(self._current_cloud_provider_id(), "image"):
            self._show_cloud_single_test_unsupported(
                "image",
                "model_unsupported",
                t("model.cloud.test.unsupported.image"),
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
            max_output_tokens=self._current_cloud_max_output_tokens(),
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

    def _test_cloud_audio(self) -> None:
        if self._is_cloud_test_running():
            LOGGER.info("Cloud audio understanding test ignored because a test is already running")
            return

        base_url = self._validated_cloud_base_url(t("model.cloud.test.failure.title"))
        if base_url is None:
            return
        model_name = self.cloud_model_name.text().strip()
        if not model_name:
            InfoBar.warning(
                title=t("model.cloud.test.failure.title"),
                content=t("model.cloud.test.modelRequired"),
                parent=self.window(),
                position=InfoBarPosition.TOP_RIGHT,
                duration=4000,
            )
            return
        unsupported = _audio_input_support_status(
            self._current_cloud_provider_id(),
            self._current_cloud_api_schema(),
            model_name,
        )
        if unsupported is not None:
            status, message = unsupported
            self._show_cloud_single_test_unsupported("audio", status, message)
            return
        if not AUDIO_TEST_ASSET.exists():
            short_error = self._short_error(t("model.test.audio.assetMissing", path=AUDIO_TEST_ASSET.as_posix()))
            self._set_cloud_test_result_text(
                t(
                    "model.cloud.test.audio.failureResult",
                    provider=self.cloud_provider_combo.currentText(),
                    base_url=base_url,
                    model_name=model_name,
                    asset=AUDIO_TEST_ASSET.as_posix(),
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
        self._cloud_audio_test_thread = QThread(self)
        self._cloud_audio_test_worker = CloudAudioTestWorker(
            provider=self._current_cloud_provider_id(),
            api_schema=self._current_cloud_api_schema(),
            base_url=base_url,
            api_key=self.cloud_api_key.text().strip(),
            model_name=model_name,
            audio_path=AUDIO_TEST_ASSET,
            max_output_tokens=self._current_cloud_max_output_tokens(),
            locale=locale,
        )
        self._cloud_audio_stream_buffer = ""
        self._cloud_audio_test_worker.moveToThread(self._cloud_audio_test_thread)
        self._cloud_audio_test_thread.started.connect(self._cloud_audio_test_worker.run)
        self._cloud_audio_test_worker.progressChanged.connect(self._show_cloud_audio_test_stream)
        self._cloud_audio_test_worker.succeeded.connect(self._show_cloud_audio_test_success)
        self._cloud_audio_test_worker.failed.connect(self._show_cloud_audio_test_failure)
        self._cloud_audio_test_worker.finished.connect(self._cloud_audio_test_thread.quit)
        self._cloud_audio_test_worker.finished.connect(self._cloud_audio_test_worker.deleteLater)
        self._cloud_audio_test_thread.finished.connect(self._cloud_audio_test_thread.deleteLater)
        self._cloud_audio_test_thread.finished.connect(self._clear_cloud_audio_test_worker)
        self._cloud_audio_test_thread.start()

    def _test_cloud_video(self) -> None:
        if self._is_cloud_test_running():
            LOGGER.info("Cloud video understanding test ignored because a test is already running")
            return

        base_url = self._validated_cloud_base_url(t("model.cloud.test.failure.title"))
        if base_url is None:
            return
        model_name = self.cloud_model_name.text().strip()
        if not model_name:
            InfoBar.warning(
                title=t("model.cloud.test.failure.title"),
                content=t("model.cloud.test.modelRequired"),
                parent=self.window(),
                position=InfoBarPosition.TOP_RIGHT,
                duration=4000,
            )
            return
        unsupported = _video_mode_support_status(
            self._current_cloud_provider_id(),
            self._current_cloud_video_input_mode(),
        )
        if unsupported is not None:
            status, message = unsupported
            self._show_cloud_single_test_unsupported("video", status, message)
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
            video_input_mode=self._current_cloud_video_input_mode(),
            max_output_tokens=self._current_cloud_max_output_tokens(),
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

        base_url = self._validated_cloud_base_url(t("model.cloud.test.failure.title"))
        if base_url is None:
            return
        model_name = self.cloud_model_name.text().strip()
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
            audio_path=AUDIO_TEST_ASSET,
            video_path=VIDEO_TEST_ASSET,
            api_schema=self._current_cloud_api_schema(),
            video_fps=self._current_cloud_video_fps(),
            video_input_mode=self._current_cloud_video_input_mode(),
            max_output_tokens=self._current_cloud_max_output_tokens(),
            locale=locale,
            text_prompt_override=text_prompt_override,
        )
        self._cloud_all_stream_buffers = {"text": "", "image": "", "audio": "", "video": ""}
        self._cloud_all_token_usage = {"text": {}, "image": {}, "audio": {}, "video": {}}
        self._cloud_all_section_status = {
            "text": "queued",
            "image": "queued",
            "audio": "queued",
            "video": "queued",
        }
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

    def _show_cloud_audio_test_success(self, payload: dict) -> None:
        content = str(payload.get("content", "")).strip() or t("model.cloud.test.empty")
        token_usage = payload.get("token_usage") if isinstance(payload.get("token_usage"), dict) else {}
        response = f"{content}\n{_format_token_usage_line(token_usage)}"
        locale = current_locale()
        self._set_cloud_test_result_text(
            t(
                "model.cloud.test.audio.successResult",
                provider=self.cloud_provider_combo.currentText(),
                base_url=self.cloud_base_url.text().strip() or t("model.cloud.test.empty"),
                model_name=self.cloud_model_name.text().strip() or t("model.cloud.test.empty"),
                asset=AUDIO_TEST_ASSET.relative_to(APP_ROOT).as_posix(),
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

    def _show_cloud_audio_test_stream(self, delta: str) -> None:
        self._cloud_audio_stream_buffer += delta
        self._append_cloud_stream_delta("audio", delta)

    def _show_cloud_audio_test_failure(self, error: str) -> None:
        short_error = self._short_error(error)
        self._set_cloud_test_result_text(
            t(
                "model.cloud.test.audio.failureResult",
                provider=self.cloud_provider_combo.currentText(),
                base_url=self.cloud_base_url.text().strip() or t("model.cloud.test.empty"),
                model_name=self.cloud_model_name.text().strip() or t("model.cloud.test.empty"),
                asset=AUDIO_TEST_ASSET.relative_to(APP_ROOT).as_posix(),
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
                self._cloud_audio_test_thread,
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

    def _clear_cloud_audio_test_worker(self) -> None:
        self.test_cloud_model_button.setEnabled(True)
        self.test_cloud_model_button.setText(t("model.cloud.test"))
        self._cloud_audio_test_thread = None
        self._cloud_audio_test_worker = None

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
        audio_result = results.get("audio", {})
        video_result = results.get("video", {})
        locale = current_locale()
        result_items = (
            ("text", text_result),
            ("image", image_result),
            ("audio", audio_result),
            ("video", video_result),
        )
        success_count = sum(1 for _key, item in result_items if item.get("status") == "ok")
        all_ok = success_count == len(result_items)
        failure_statuses = {"error", "failed"}
        failed_items: list[str] = []
        non_failure_items: list[str] = []
        for key, item in result_items:
            status = str(item.get("status") or "error")
            if status in failure_statuses:
                failed_items.append(t(f"model.test.type.{key}"))
            elif status != "ok":
                non_failure_items.append(t(f"model.test.type.{key}"))
        summary = (
            t("model.cloud.test.all.final.success")
            if all_ok
            else (
                t(
                    "model.cloud.test.all.final.failure",
                    failed_items=_join_failed_items(failed_items, locale),
                )
                if failed_items
                else t(
                    "model.cloud.test.all.final.completed",
                    skipped_items=_join_failed_items(non_failure_items, locale),
                )
            )
        )
        for section, result in result_items:
            status = str(result.get("status") or "error")
            self._cloud_all_stream_buffers[section] = str(result.get("content") or "")
            self._cloud_all_section_status[section] = status
            token_usage = result.get("token_usage")
            self._cloud_all_token_usage[section] = token_usage if status == "ok" and isinstance(token_usage, dict) else {}
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
        elif failed_items:
            InfoBar.warning(
                title=t("model.cloud.test.failure.title"),
                content=t("model.cloud.test.partialFailure.content"),
                parent=self.window(),
                position=InfoBarPosition.TOP_RIGHT,
                duration=5000,
            )
        else:
            InfoBar.info(
                title=t("model.cloud.test.unsupported.title"),
                content=summary,
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
        self._cloud_all_section_status[section] = status
        if status == "ok" and isinstance(token_usage, dict):
            self._cloud_all_token_usage[section] = token_usage
        elif status != "ok":
            self._cloud_all_token_usage[section] = {}
        self._set_cloud_test_result_text(self._render_cloud_all_report(None))

    def _render_cloud_all_report(self, final_summary: str | None) -> str:
        locale = current_locale()
        header_lines = [
            f"{t('model.cloud.provider')}: {self.cloud_provider_combo.currentText()}",
            f"{t('model.cloud.endpoint')}: {self.cloud_endpoint_combo.currentText()}",
            f"{t('model.cloud.apiSchema')}: {self.cloud_api_schema_combo.currentText()}",
            f"{t('model.cloud.videoInputMode')}: {self.cloud_video_input_mode_combo.currentText()}",
            f"{t('model.cloud.baseUrl')}: {self.cloud_base_url.text().strip() or t('model.cloud.test.empty')}",
            f"{t('model.cloud.modelName')}: {self.cloud_model_name.text().strip() or t('model.cloud.test.empty')}",
            f"{t('model.cloud.test.report.targetLanguage')}: {_response_language_name(locale)}",
            f"{t('model.cloud.test.report.imageAsset')}: {IMAGE_TEST_ASSET.relative_to(APP_ROOT).as_posix()}",
            f"{t('model.cloud.test.report.audioAsset')}: {AUDIO_TEST_ASSET.relative_to(APP_ROOT).as_posix()}",
            f"{t('model.cloud.test.report.videoAsset')}: {VIDEO_TEST_ASSET.relative_to(APP_ROOT).as_posix()}",
        ]
        sections: list[str] = []
        for key in ("text", "image", "audio", "video"):
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
                    f"{t('model.cloud.test.report.finalSummary')}: {final_summary}",
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
            self._sync_cloud_endpoint_options(base_url=self.cloud_base_url.text().strip())
            self._apply_cloud_endpoint_to_base_url(preserve_existing=True)
            self._set_cloud_api_schema(DEFAULT_CLOUD_API_SCHEMA)
            self._set_cloud_video_input_mode(DEFAULT_VIDEO_INPUT_MODE)
            self._set_cloud_video_fps(DEFAULT_CLOUD_VIDEO_FPS)
            self._set_cloud_max_output_tokens(DEFAULT_CLOUD_MAX_OUTPUT_TOKENS)
            self._sync_cloud_video_fps_availability()
            return

        preset = self._cloud_presets[index]
        if not self._restoring_model_selection:
            set_last_cloud_preset_name(preset.name)
        self.cloud_preset_name.setText(preset.name)
        provider_id = normalize_cloud_provider(preset.provider)
        provider_index = self.cloud_provider_combo.findData(provider_id)
        if provider_index < 0:
            provider_index = 0
        with QSignalBlocker(self.cloud_provider_combo):
            self.cloud_provider_combo.setCurrentIndex(provider_index)
        self._sync_cloud_endpoint_options(preset.endpoint_id, preset.base_url)
        self._set_cloud_api_schema(preset.api_schema)
        self._set_cloud_video_input_mode(preset.video_input_mode)
        self.cloud_base_url.setText(preset.base_url)
        self._apply_cloud_endpoint_to_base_url(preserve_existing=True)
        self.cloud_api_key.setText(preset.api_key)
        self.cloud_model_name.setText(preset.model_name)
        self._set_cloud_video_fps(preset.video_fps)
        self._set_cloud_max_output_tokens(preset.max_output_tokens)
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
            endpoint_id=self._current_cloud_endpoint_id(),
            base_url=self.cloud_base_url.text().strip(),
            api_schema=self._current_cloud_api_schema(),
            api_key=self.cloud_api_key.text().strip(),
            model_name=self.cloud_model_name.text().strip(),
            video_input_mode=self._current_cloud_video_input_mode(),
            video_fps=self._current_cloud_video_fps(),
            max_output_tokens=self._current_cloud_max_output_tokens(),
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
