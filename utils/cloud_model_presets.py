from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from typing import Literal

from utils.global_store import get_global_value, set_global_value

CLOUD_MODEL_PRESETS_KEY = "model/cloudPresets"
LOGGER = logging.getLogger(__name__)
CloudProviderId = Literal["aliyunBailian", "openai", "deepseek", "openrouter", "custom"]
CloudModelModality = Literal["text", "image", "video", "audio"]
VideoFpsMode = Literal["direct", "frame_sampling", "none"]
CloudApiSchema = Literal["openai_chat_completions", "dashscope_native"]
CloudCapability = Literal[
    "text",
    "image",
    "video",
    "audio_transcription",
    "audio_understanding",
    "audio_generation",
    "video_audio_understanding",
    "json_mode",
    "streaming",
    "model_list",
    "native_video",
    "frame_sampling_video",
]
CloudModelListKind = Literal["openai_compatible", "none"]
VideoInputMode = Literal[
    "auto",
    "native_video",
    "frame_sampling",
    "frame_sampling_with_transcript",
    "audio_transcript_only",
]
DEFAULT_CLOUD_VIDEO_FPS = 2.0
DEFAULT_CLOUD_MAX_OUTPUT_TOKENS = 2048
CLOUD_MAX_OUTPUT_TOKENS_MIN = 128
CLOUD_MAX_OUTPUT_TOKENS_MAX = 8192
CLOUD_MAX_OUTPUT_TOKENS_STEP = 128
DEFAULT_CONTEXT_WINDOW_FALLBACK_TOKENS = 32768
CLOUD_CONTEXT_WINDOW_TOKENS_MIN = 4096
CLOUD_CONTEXT_WINDOW_TOKENS_MAX = 10_000_000
DEFAULT_CLOUD_API_SCHEMA: CloudApiSchema = "openai_chat_completions"
DEFAULT_VIDEO_INPUT_MODE: VideoInputMode = "auto"
CUSTOM_ENDPOINT_ID = "custom"
ALIYUN_EU_WORKSPACE_PLACEHOLDER = "{WorkspaceId}"
CLOUD_CONTEXT_WINDOW_SOURCE_MANUAL = "manual"
CLOUD_CONTEXT_WINDOW_SOURCE_BUILT_IN = "built_in"
CLOUD_CONTEXT_WINDOW_SOURCE_PROVIDER = "provider"

# Exact model context windows can drift over time. Keep this table conservative and
# only add entries after confirming provider documentation.
CLOUD_MODEL_CONTEXT_WINDOW_TOKENS: dict[tuple[str, str], int] = {}

CLOUD_PROVIDER_ALIYUN_BAILIAN = "aliyunBailian"
CLOUD_PROVIDER_OPENAI = "openai"
CLOUD_PROVIDER_DEEPSEEK = "deepseek"
CLOUD_PROVIDER_OPENROUTER = "openrouter"
CLOUD_PROVIDER_CUSTOM = "custom"
CLOUD_PROVIDER_OPENAI_COMPATIBLE = "openaiCompatible"

CLOUD_PROVIDER_IDS: tuple[CloudProviderId, ...] = (
    CLOUD_PROVIDER_ALIYUN_BAILIAN,
    CLOUD_PROVIDER_OPENAI,
    CLOUD_PROVIDER_DEEPSEEK,
    CLOUD_PROVIDER_OPENROUTER,
    CLOUD_PROVIDER_CUSTOM,
)


@dataclass(frozen=True, slots=True)
class CloudEndpointPreset:
    endpoint_id: str
    label_key: str
    base_url: str
    editable: bool = False
    placeholder_token: str = ""

    @property
    def has_placeholder(self) -> bool:
        return bool(self.placeholder_token and self.placeholder_token in self.base_url)


@dataclass(slots=True)
class CloudModelPreset:
    name: str
    provider: str
    base_url: str
    api_key: str
    model_name: str
    endpoint_id: str = ""
    api_schema: str = DEFAULT_CLOUD_API_SCHEMA
    video_input_mode: str = DEFAULT_VIDEO_INPUT_MODE
    video_fps: float = DEFAULT_CLOUD_VIDEO_FPS
    max_output_tokens: int = DEFAULT_CLOUD_MAX_OUTPUT_TOKENS
    context_window_tokens: int | None = None
    context_window_source: str = ""


@dataclass(frozen=True, slots=True)
class CloudModelProvider:
    provider_id: CloudProviderId
    label_key: str
    model_list_kind: CloudModelListKind
    text_backend: str
    image_backend: str
    video_backend: str
    audio_backend: str
    video_fps_mode: VideoFpsMode
    default_endpoint_id: str
    default_api_schema: CloudApiSchema
    default_video_input_mode: VideoInputMode
    endpoints: tuple[CloudEndpointPreset, ...]
    capabilities: frozenset[CloudCapability]
    requires_aliyun_extra_body: bool = False
    icon_id: str = ""

    def backend_for(self, modality: CloudModelModality) -> str:
        if modality == "audio":
            return self.audio_backend
        if modality == "video":
            return self.video_backend
        if modality == "image":
            return self.image_backend
        return self.text_backend

    @property
    def supports_video_fps(self) -> bool:
        return self.video_fps_mode != "none"

    def endpoint_by_id(self, endpoint_id: str) -> CloudEndpointPreset | None:
        for endpoint in self.endpoints:
            if endpoint.endpoint_id == endpoint_id:
                return endpoint
        return None

    def default_endpoint(self) -> CloudEndpointPreset:
        return self.endpoint_by_id(self.default_endpoint_id) or self.endpoints[0]

    def has_capability(self, capability: CloudCapability) -> bool:
        return capability in self.capabilities


CLOUD_MODEL_PROVIDERS: dict[CloudProviderId, CloudModelProvider] = {
    CLOUD_PROVIDER_ALIYUN_BAILIAN: CloudModelProvider(
        provider_id=CLOUD_PROVIDER_ALIYUN_BAILIAN,
        label_key="model.cloud.provider.aliyunBailian",
        model_list_kind="openai_compatible",
        text_backend="openai_compatible",
        image_backend="openai_compatible",
        video_backend="dashscope",
        audio_backend="openai_compatible",
        video_fps_mode="direct",
        default_endpoint_id="cn",
        default_api_schema=DEFAULT_CLOUD_API_SCHEMA,
        default_video_input_mode=DEFAULT_VIDEO_INPUT_MODE,
        endpoints=(
            CloudEndpointPreset(
                endpoint_id="cn",
                label_key="model.cloud.endpoint.aliyunBailian.cn",
                base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            ),
            CloudEndpointPreset(
                endpoint_id="intl",
                label_key="model.cloud.endpoint.aliyunBailian.intl",
                base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
            ),
            CloudEndpointPreset(
                endpoint_id="us",
                label_key="model.cloud.endpoint.aliyunBailian.us",
                base_url="https://dashscope-us.aliyuncs.com/compatible-mode/v1",
            ),
            CloudEndpointPreset(
                endpoint_id="hk",
                label_key="model.cloud.endpoint.aliyunBailian.hk",
                base_url="https://cn-hongkong.dashscope.aliyuncs.com/compatible-mode/v1",
            ),
            CloudEndpointPreset(
                endpoint_id="eu",
                label_key="model.cloud.endpoint.aliyunBailian.eu",
                base_url=(
                    "https://{WorkspaceId}.eu-central-1.maas.aliyuncs.com/"
                    "compatible-mode/v1"
                ),
                editable=True,
                placeholder_token=ALIYUN_EU_WORKSPACE_PLACEHOLDER,
            ),
            CloudEndpointPreset(
                endpoint_id=CUSTOM_ENDPOINT_ID,
                label_key="model.cloud.endpoint.custom",
                base_url="",
                editable=True,
            ),
        ),
        capabilities=frozenset(
            {
                "text",
                "image",
                "video",
                "audio_understanding",
                "model_list",
                "native_video",
                "streaming",
                "json_mode",
            }
        ),
        requires_aliyun_extra_body=True,
        icon_id="aliyun",
    ),
    CLOUD_PROVIDER_OPENAI: CloudModelProvider(
        provider_id=CLOUD_PROVIDER_OPENAI,
        label_key="model.cloud.provider.openai",
        model_list_kind="openai_compatible",
        text_backend="openai_compatible",
        image_backend="openai_compatible",
        video_backend="openai_compatible",
        audio_backend="openai_compatible",
        video_fps_mode="frame_sampling",
        default_endpoint_id="default",
        default_api_schema=DEFAULT_CLOUD_API_SCHEMA,
        default_video_input_mode=DEFAULT_VIDEO_INPUT_MODE,
        endpoints=(
            CloudEndpointPreset(
                endpoint_id="default",
                label_key="model.cloud.endpoint.openai.default",
                base_url="https://api.openai.com/v1",
            ),
            CloudEndpointPreset(
                endpoint_id=CUSTOM_ENDPOINT_ID,
                label_key="model.cloud.endpoint.custom",
                base_url="",
                editable=True,
            ),
        ),
        capabilities=frozenset(
            {
                "text",
                "image",
                "video",
                "model_list",
                "frame_sampling_video",
                "streaming",
                "json_mode",
            }
        ),
        icon_id="openai",
    ),
    CLOUD_PROVIDER_DEEPSEEK: CloudModelProvider(
        provider_id=CLOUD_PROVIDER_DEEPSEEK,
        label_key="model.cloud.provider.deepseek",
        model_list_kind="openai_compatible",
        text_backend="openai_compatible",
        image_backend="openai_compatible",
        video_backend="openai_compatible",
        audio_backend="openai_compatible",
        video_fps_mode="none",
        default_endpoint_id="default",
        default_api_schema=DEFAULT_CLOUD_API_SCHEMA,
        default_video_input_mode=DEFAULT_VIDEO_INPUT_MODE,
        endpoints=(
            CloudEndpointPreset(
                endpoint_id="default",
                label_key="model.cloud.endpoint.deepseek.default",
                base_url="https://api.deepseek.com",
            ),
            CloudEndpointPreset(
                endpoint_id=CUSTOM_ENDPOINT_ID,
                label_key="model.cloud.endpoint.custom",
                base_url="",
                editable=True,
            ),
        ),
        capabilities=frozenset({"text", "model_list", "streaming"}),
        icon_id="deepseek",
    ),
    CLOUD_PROVIDER_OPENROUTER: CloudModelProvider(
        provider_id=CLOUD_PROVIDER_OPENROUTER,
        label_key="model.cloud.provider.openrouter",
        model_list_kind="openai_compatible",
        text_backend="openai_compatible",
        image_backend="openai_compatible",
        video_backend="openai_compatible",
        audio_backend="openai_compatible",
        video_fps_mode="frame_sampling",
        default_endpoint_id="default",
        default_api_schema=DEFAULT_CLOUD_API_SCHEMA,
        default_video_input_mode=DEFAULT_VIDEO_INPUT_MODE,
        endpoints=(
            CloudEndpointPreset(
                endpoint_id="default",
                label_key="model.cloud.endpoint.openrouter.default",
                base_url="https://openrouter.ai/api/v1",
            ),
            CloudEndpointPreset(
                endpoint_id=CUSTOM_ENDPOINT_ID,
                label_key="model.cloud.endpoint.custom",
                base_url="",
                editable=True,
            ),
        ),
        capabilities=frozenset(
            {
                "text",
                "image",
                "video",
                "model_list",
                "frame_sampling_video",
                "streaming",
            }
        ),
        icon_id="openrouter",
    ),
    CLOUD_PROVIDER_CUSTOM: CloudModelProvider(
        provider_id=CLOUD_PROVIDER_CUSTOM,
        label_key="model.cloud.provider.custom",
        model_list_kind="openai_compatible",
        text_backend="openai_compatible",
        image_backend="openai_compatible",
        video_backend="openai_compatible",
        audio_backend="openai_compatible",
        video_fps_mode="frame_sampling",
        default_endpoint_id=CUSTOM_ENDPOINT_ID,
        default_api_schema=DEFAULT_CLOUD_API_SCHEMA,
        default_video_input_mode=DEFAULT_VIDEO_INPUT_MODE,
        endpoints=(
            CloudEndpointPreset(
                endpoint_id=CUSTOM_ENDPOINT_ID,
                label_key="model.cloud.endpoint.custom",
                base_url="",
                editable=True,
            ),
        ),
        capabilities=frozenset(
            {
                "text",
                "image",
                "video",
                "model_list",
                "frame_sampling_video",
                "streaming",
            }
        ),
        icon_id="cloud",
    ),
}


def _normalized_url(value: str) -> str:
    return value.strip().rstrip("/").lower()


def _looks_like_aliyun_eu_endpoint(base_url: str) -> bool:
    normalized = _normalized_url(base_url)
    return normalized.endswith(".eu-central-1.maas.aliyuncs.com/compatible-mode/v1")


def normalize_cloud_provider(provider: str) -> CloudProviderId:
    normalized = provider.strip()
    aliases = {
        "dashscope": CLOUD_PROVIDER_ALIYUN_BAILIAN,
        "aliyun": CLOUD_PROVIDER_ALIYUN_BAILIAN,
        "aliyun_bailian": CLOUD_PROVIDER_ALIYUN_BAILIAN,
        "aliBailian": CLOUD_PROVIDER_ALIYUN_BAILIAN,
        "openaiCompatible": CLOUD_PROVIDER_CUSTOM,
        "openai_compatible": CLOUD_PROVIDER_CUSTOM,
        "openai-compatible": CLOUD_PROVIDER_CUSTOM,
        "customOpenAI": CLOUD_PROVIDER_CUSTOM,
    }
    normalized = aliases.get(normalized, normalized)
    if not normalized:
        return CLOUD_PROVIDER_ALIYUN_BAILIAN
    if normalized in CLOUD_MODEL_PROVIDERS:
        return normalized  # type: ignore[return-value]
    return CLOUD_PROVIDER_CUSTOM


def cloud_model_provider(provider: str) -> CloudModelProvider:
    return CLOUD_MODEL_PROVIDERS[normalize_cloud_provider(provider)]


def cloud_provider_endpoints(provider: str) -> tuple[CloudEndpointPreset, ...]:
    return cloud_model_provider(provider).endpoints


def cloud_model_endpoint(provider: str, endpoint_id: str) -> CloudEndpointPreset:
    provider_config = cloud_model_provider(provider)
    endpoint = provider_config.endpoint_by_id(endpoint_id)
    if endpoint is not None:
        return endpoint
    return provider_config.default_endpoint()


def infer_cloud_endpoint_id(provider: str, base_url: str) -> str:
    provider_config = cloud_model_provider(provider)
    normalized_base_url = _normalized_url(base_url)
    if not normalized_base_url:
        return provider_config.default_endpoint_id
    if (
        provider_config.provider_id == CLOUD_PROVIDER_ALIYUN_BAILIAN
        and _looks_like_aliyun_eu_endpoint(base_url)
    ):
        return "eu"
    for endpoint in provider_config.endpoints:
        if endpoint.endpoint_id == CUSTOM_ENDPOINT_ID:
            continue
        if _normalized_url(endpoint.base_url) == normalized_base_url:
            return endpoint.endpoint_id
    return CUSTOM_ENDPOINT_ID


def normalize_cloud_endpoint_id(provider: str, endpoint_id: str, base_url: str = "") -> str:
    provider_config = cloud_model_provider(provider)
    normalized = endpoint_id.strip()
    if normalized and provider_config.endpoint_by_id(normalized) is not None:
        return normalized
    return infer_cloud_endpoint_id(provider_config.provider_id, base_url)


def cloud_endpoint_base_url(provider: str, endpoint_id: str) -> str:
    return cloud_model_endpoint(provider, endpoint_id).base_url


def cloud_endpoint_requires_custom_base_url(provider: str, endpoint_id: str) -> bool:
    endpoint = cloud_model_endpoint(provider, endpoint_id)
    return endpoint.editable


def base_url_has_unresolved_placeholder(base_url: str) -> bool:
    return "{" in base_url and "}" in base_url


def normalize_cloud_api_schema(api_schema: str, provider: str) -> CloudApiSchema:
    normalized = api_schema.strip()
    if normalized in ("openai_chat_completions", "dashscope_native"):
        return normalized  # type: ignore[return-value]
    return cloud_model_provider(provider).default_api_schema


def normalize_video_input_mode(video_input_mode: str, provider: str = "") -> VideoInputMode:
    normalized = video_input_mode.strip()
    valid_modes = {
        "auto",
        "native_video",
        "frame_sampling",
        "frame_sampling_with_transcript",
        "audio_transcript_only",
    }
    if normalized in valid_modes:
        return normalized  # type: ignore[return-value]
    if provider:
        return cloud_model_provider(provider).default_video_input_mode
    return DEFAULT_VIDEO_INPUT_MODE


def provider_supports_capability(provider: str, capability: CloudCapability) -> bool:
    return cloud_model_provider(provider).has_capability(capability)


def provider_requires_aliyun_extra_body(provider: str) -> bool:
    return cloud_model_provider(provider).requires_aliyun_extra_body


def complete_cloud_model_preset(preset: CloudModelPreset) -> CloudModelPreset:
    provider_id = normalize_cloud_provider(preset.provider)
    endpoint_id = normalize_cloud_endpoint_id(provider_id, preset.endpoint_id, preset.base_url)
    api_schema = normalize_cloud_api_schema(preset.api_schema, provider_id)
    video_input_mode = normalize_video_input_mode(preset.video_input_mode, provider_id)
    base_url = preset.base_url.strip()
    if not base_url:
        base_url = cloud_endpoint_base_url(provider_id, endpoint_id)
    context_window_tokens, context_window_source = complete_context_window_tokens(
        provider_id,
        preset.model_name,
        preset.context_window_tokens,
        preset.context_window_source,
    )
    return CloudModelPreset(
        name=preset.name,
        provider=provider_id,
        endpoint_id=endpoint_id,
        base_url=base_url,
        api_schema=api_schema,
        video_input_mode=video_input_mode,
        api_key=preset.api_key,
        model_name=preset.model_name,
        video_fps=_coerce_video_fps(preset.video_fps),
        max_output_tokens=coerce_cloud_max_output_tokens(preset.max_output_tokens),
        context_window_tokens=context_window_tokens,
        context_window_source=context_window_source,
    )


def load_cloud_model_presets() -> list[CloudModelPreset]:
    raw_value = get_global_value(CLOUD_MODEL_PRESETS_KEY, [])
    if isinstance(raw_value, str):
        try:
            raw_presets = json.loads(raw_value)
        except json.JSONDecodeError:
            LOGGER.warning("Cloud model presets could not be decoded")
            return []
    else:
        raw_presets = raw_value
    if not isinstance(raw_presets, list):
        LOGGER.warning("Cloud model presets ignored because stored value is not a list")
        return []

    presets: list[CloudModelPreset] = []
    for item in raw_presets:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        presets.append(
            complete_cloud_model_preset(
                CloudModelPreset(
                    name=name,
                    provider=str(item.get("provider", "")),
                    endpoint_id=str(item.get("endpoint_id", "")),
                    base_url=str(item.get("base_url", "")),
                    api_schema=str(item.get("api_schema", "")),
                    video_input_mode=str(item.get("video_input_mode", "")),
                    api_key=str(item.get("api_key", "")),
                    model_name=str(item.get("model_name", "")),
                    video_fps=_coerce_video_fps(item.get("video_fps")),
                    max_output_tokens=coerce_cloud_max_output_tokens(item.get("max_output_tokens")),
                    context_window_tokens=coerce_context_window_tokens(item.get("context_window_tokens")),
                    context_window_source=str(item.get("context_window_source", "")),
                )
            )
        )
    LOGGER.info("Cloud model presets loaded; count=%s", len(presets))
    return presets


def save_cloud_model_presets(presets: list[CloudModelPreset]) -> None:
    normalized_presets = [complete_cloud_model_preset(preset) for preset in presets]
    set_global_value(CLOUD_MODEL_PRESETS_KEY, [asdict(preset) for preset in normalized_presets])
    LOGGER.info("Cloud model presets saved; count=%s", len(normalized_presets))


def upsert_cloud_model_preset(preset: CloudModelPreset) -> list[CloudModelPreset]:
    normalized_preset = complete_cloud_model_preset(preset)
    presets = [item for item in load_cloud_model_presets() if item.name != normalized_preset.name]
    presets.append(normalized_preset)
    save_cloud_model_presets(presets)
    return presets


def delete_cloud_model_preset(name: str) -> list[CloudModelPreset]:
    presets = [item for item in load_cloud_model_presets() if item.name != name]
    save_cloud_model_presets(presets)
    return presets


def _coerce_video_fps(value: object) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return DEFAULT_CLOUD_VIDEO_FPS
    if parsed <= 0:
        return DEFAULT_CLOUD_VIDEO_FPS
    return min(parsed, 10.0)


def coerce_cloud_max_output_tokens(value: object) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return DEFAULT_CLOUD_MAX_OUTPUT_TOKENS
    if parsed <= 0:
        return DEFAULT_CLOUD_MAX_OUTPUT_TOKENS
    rounded = int(round(parsed / CLOUD_MAX_OUTPUT_TOKENS_STEP) * CLOUD_MAX_OUTPUT_TOKENS_STEP)
    return min(max(rounded, CLOUD_MAX_OUTPUT_TOKENS_MIN), CLOUD_MAX_OUTPUT_TOKENS_MAX)


def coerce_context_window_tokens(value: object) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    if parsed <= 0:
        return None
    return min(max(parsed, CLOUD_CONTEXT_WINDOW_TOKENS_MIN), CLOUD_CONTEXT_WINDOW_TOKENS_MAX)


def complete_context_window_tokens(
    provider: str,
    model_name: str,
    value: object,
    source: str = "",
) -> tuple[int | None, str]:
    normalized_source = source.strip()
    context_window_tokens = coerce_context_window_tokens(value)
    if context_window_tokens is not None and normalized_source != CLOUD_CONTEXT_WINDOW_SOURCE_BUILT_IN:
        return (context_window_tokens, normalized_source or CLOUD_CONTEXT_WINDOW_SOURCE_MANUAL)

    inferred_tokens = infer_context_window_tokens(provider, model_name)
    if inferred_tokens is not None:
        return (inferred_tokens, CLOUD_CONTEXT_WINDOW_SOURCE_BUILT_IN)

    return (None, "")


def infer_context_window_tokens(provider: str, model_name: str) -> int | None:
    provider_id = normalize_cloud_provider(provider)
    normalized_model = _normalize_model_context_key(model_name)
    if not normalized_model:
        return None
    return CLOUD_MODEL_CONTEXT_WINDOW_TOKENS.get((provider_id, normalized_model))


def context_window_budget_tokens(preset: CloudModelPreset) -> int:
    return preset.context_window_tokens or DEFAULT_CONTEXT_WINDOW_FALLBACK_TOKENS


def scale_cloud_max_output_tokens_for_video_duration(
    max_output_tokens_per_minute: object,
    duration_seconds: object,
) -> int:
    tokens_per_minute = coerce_cloud_max_output_tokens(max_output_tokens_per_minute)
    try:
        duration = float(duration_seconds)
    except (TypeError, ValueError):
        duration = 60.0
    if duration <= 0:
        duration = 60.0
    return max(1, int(tokens_per_minute * duration / 60.0 + 0.5))


def _normalize_model_context_key(model_name: str) -> str:
    return model_name.strip().lower().replace("_", "-")
