from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from typing import Literal

from utils.global_store import get_global_value, set_global_value

CLOUD_MODEL_PRESETS_KEY = "model/cloudPresets"
LOGGER = logging.getLogger(__name__)
CloudProviderId = Literal["aliyunBailian", "openaiCompatible", "custom"]
CloudModelModality = Literal["text", "image", "video"]
VideoFpsMode = Literal["direct", "frame_sampling", "none"]
DEFAULT_CLOUD_VIDEO_FPS = 2.0
DEFAULT_CLOUD_MAX_OUTPUT_TOKENS = 2048
CLOUD_MAX_OUTPUT_TOKENS_MIN = 128
CLOUD_MAX_OUTPUT_TOKENS_MAX = 8192
CLOUD_MAX_OUTPUT_TOKENS_STEP = 128

CLOUD_PROVIDER_ALIYUN_BAILIAN = "aliyunBailian"
CLOUD_PROVIDER_OPENAI_COMPATIBLE = "openaiCompatible"
CLOUD_PROVIDER_CUSTOM = "custom"

CLOUD_PROVIDER_IDS: tuple[CloudProviderId, ...] = (
    CLOUD_PROVIDER_ALIYUN_BAILIAN,
    CLOUD_PROVIDER_OPENAI_COMPATIBLE,
    CLOUD_PROVIDER_CUSTOM,
)


@dataclass(slots=True)
class CloudModelPreset:
    name: str
    provider: str
    base_url: str
    api_key: str
    model_name: str
    video_fps: float = DEFAULT_CLOUD_VIDEO_FPS
    max_output_tokens: int = DEFAULT_CLOUD_MAX_OUTPUT_TOKENS


@dataclass(frozen=True, slots=True)
class CloudModelProvider:
    provider_id: CloudProviderId
    label_key: str
    model_list_kind: str
    text_backend: str
    image_backend: str
    video_backend: str
    video_fps_mode: VideoFpsMode

    def backend_for(self, modality: CloudModelModality) -> str:
        if modality == "video":
            return self.video_backend
        if modality == "image":
            return self.image_backend
        return self.text_backend

    @property
    def supports_video_fps(self) -> bool:
        return self.video_fps_mode != "none"


CLOUD_MODEL_PROVIDERS: dict[CloudProviderId, CloudModelProvider] = {
    CLOUD_PROVIDER_ALIYUN_BAILIAN: CloudModelProvider(
        provider_id=CLOUD_PROVIDER_ALIYUN_BAILIAN,
        label_key="model.cloud.provider.aliyunBailian",
        model_list_kind="openai_compatible",
        text_backend="openai_compatible",
        image_backend="openai_compatible",
        video_backend="dashscope",
        video_fps_mode="direct",
    ),
    CLOUD_PROVIDER_OPENAI_COMPATIBLE: CloudModelProvider(
        provider_id=CLOUD_PROVIDER_OPENAI_COMPATIBLE,
        label_key="model.cloud.provider.openaiCompatible",
        model_list_kind="openai_compatible",
        text_backend="openai_compatible",
        image_backend="openai_compatible",
        video_backend="openai_compatible",
        video_fps_mode="frame_sampling",
    ),
    CLOUD_PROVIDER_CUSTOM: CloudModelProvider(
        provider_id=CLOUD_PROVIDER_CUSTOM,
        label_key="model.cloud.provider.custom",
        model_list_kind="openai_compatible",
        text_backend="openai_compatible",
        image_backend="openai_compatible",
        video_backend="openai_compatible",
        video_fps_mode="frame_sampling",
    ),
}


def normalize_cloud_provider(provider: str) -> CloudProviderId:
    normalized = provider.strip()
    aliases = {
        "dashscope": CLOUD_PROVIDER_ALIYUN_BAILIAN,
        "aliyun": CLOUD_PROVIDER_ALIYUN_BAILIAN,
        "aliyun_bailian": CLOUD_PROVIDER_ALIYUN_BAILIAN,
        "aliBailian": CLOUD_PROVIDER_ALIYUN_BAILIAN,
    }
    normalized = aliases.get(normalized, normalized)
    if normalized in CLOUD_MODEL_PROVIDERS:
        return normalized  # type: ignore[return-value]
    if normalized == CLOUD_PROVIDER_CUSTOM:
        return CLOUD_PROVIDER_CUSTOM
    if normalized == CLOUD_PROVIDER_OPENAI_COMPATIBLE:
        return CLOUD_PROVIDER_OPENAI_COMPATIBLE
    return CLOUD_PROVIDER_ALIYUN_BAILIAN


def cloud_model_provider(provider: str) -> CloudModelProvider:
    return CLOUD_MODEL_PROVIDERS[normalize_cloud_provider(provider)]


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
            CloudModelPreset(
                name=name,
                provider=normalize_cloud_provider(str(item.get("provider", ""))),
                base_url=str(item.get("base_url", "")),
                api_key=str(item.get("api_key", "")),
                model_name=str(item.get("model_name", "")),
                video_fps=_coerce_video_fps(item.get("video_fps")),
                max_output_tokens=coerce_cloud_max_output_tokens(item.get("max_output_tokens")),
            )
        )
    LOGGER.info("Cloud model presets loaded; count=%s", len(presets))
    return presets


def save_cloud_model_presets(presets: list[CloudModelPreset]) -> None:
    set_global_value(CLOUD_MODEL_PRESETS_KEY, [asdict(preset) for preset in presets])
    LOGGER.info("Cloud model presets saved; count=%s", len(presets))


def upsert_cloud_model_preset(preset: CloudModelPreset) -> list[CloudModelPreset]:
    presets = [item for item in load_cloud_model_presets() if item.name != preset.name]
    presets.append(preset)
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
