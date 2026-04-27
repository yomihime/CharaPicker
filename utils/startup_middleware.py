from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from core.models import ProjectConfig
from utils.cloud_model_presets import CloudModelPreset, load_cloud_model_presets
from utils.env_manager import has_llamacpp_binary
from utils.ffmpeg_tool import DeviceOption, has_ffmpeg_binary, list_available_device_options
from utils.state_manager import list_project_configs


LOGGER = logging.getLogger(__name__)
StartupProgressCallback = Callable[[str, int], None]


@dataclass(slots=True)
class StartupWarmupSnapshot:
    project_configs: list[ProjectConfig] = field(default_factory=list)
    ffmpeg_ready: bool = False
    encoder_options: list[DeviceOption] = field(default_factory=list)
    llamacpp_ready: bool = False
    cloud_presets: list[CloudModelPreset] = field(default_factory=list)


def warmup_startup_context(progress: StartupProgressCallback | None = None) -> StartupWarmupSnapshot:
    snapshot = StartupWarmupSnapshot()

    _emit_progress(progress, "startup.status.boot", 12)
    snapshot.project_configs = list_project_configs()

    _emit_progress(progress, "startup.status.theme", 34)
    snapshot.encoder_options = list_available_device_options()
    snapshot.ffmpeg_ready = bool(snapshot.encoder_options)
    if not snapshot.ffmpeg_ready:
        # Some FFmpeg builds may be usable but report no preferred encoder candidates.
        snapshot.ffmpeg_ready = has_ffmpeg_binary()

    _emit_progress(progress, "startup.status.window", 66)
    snapshot.llamacpp_ready = has_llamacpp_binary()
    snapshot.cloud_presets = load_cloud_model_presets()

    _emit_progress(progress, "startup.status.workspace", 88)
    LOGGER.info(
        "Startup warmup completed; projects=%s ffmpeg_ready=%s encoder_options=%s llamacpp_ready=%s cloud_presets=%s",
        len(snapshot.project_configs),
        snapshot.ffmpeg_ready,
        len(snapshot.encoder_options),
        snapshot.llamacpp_ready,
        len(snapshot.cloud_presets),
    )
    return snapshot


def _emit_progress(progress: StartupProgressCallback | None, message_key: str, value: int) -> None:
    if progress is not None:
        progress(message_key, value)
