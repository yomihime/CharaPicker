from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter
from typing import TypeVar

from core.models import ProjectConfig
from utils.atomic_io import DataCorruptionError
from utils.cloud_model_presets import CloudModelPreset, load_cloud_model_presets
from utils.env_manager import WhisperStatus, has_llamacpp_binary, whisper_status
from utils.ffmpeg_tool import DeviceOption, has_ffmpeg_binary, list_available_device_options
from utils.local_model_catalog import list_local_model_candidates
from utils.state_manager import scan_project_configs


LOGGER = logging.getLogger(__name__)
StartupProgressCallback = Callable[[str, int], None]
ProbeResult = TypeVar("ProbeResult")


@dataclass(slots=True)
class StartupWarmupSnapshot:
    project_configs: list[ProjectConfig] = field(default_factory=list)
    project_config_issues: list[DataCorruptionError] = field(default_factory=list)
    ffmpeg_ready: bool = False
    encoder_options: list[DeviceOption] = field(default_factory=list)
    llamacpp_ready: bool = False
    whisper_status: WhisperStatus | None = None
    local_models: list[Path] = field(default_factory=list)
    cloud_presets: list[CloudModelPreset] = field(default_factory=list)


def warmup_startup_context(progress: StartupProgressCallback | None = None) -> StartupWarmupSnapshot:
    started_at = perf_counter()
    snapshot = StartupWarmupSnapshot()

    _emit_progress(progress, "startup.status.boot", 12)
    project_scan = _run_timed_probe("projects", scan_project_configs)
    snapshot.project_configs = project_scan.configs
    snapshot.project_config_issues = project_scan.issues

    _emit_progress(progress, "startup.status.theme", 34)
    _emit_progress(progress, "startup.status.window", 66)
    with ThreadPoolExecutor(max_workers=5, thread_name_prefix="startup-probe") as executor:
        ffmpeg_future = executor.submit(_run_timed_probe, "ffmpeg", _probe_ffmpeg)
        llamacpp_future = executor.submit(
            _run_timed_probe,
            "llamacpp",
            has_llamacpp_binary,
        )
        whisper_future = executor.submit(_run_timed_probe, "whisper", whisper_status)
        local_models_future = executor.submit(
            _run_timed_probe,
            "local_models",
            list_local_model_candidates,
        )
        cloud_presets_future = executor.submit(
            _run_timed_probe,
            "cloud_presets",
            load_cloud_model_presets,
        )

        snapshot.encoder_options, snapshot.ffmpeg_ready = ffmpeg_future.result()
        snapshot.llamacpp_ready = llamacpp_future.result()
        snapshot.whisper_status = whisper_future.result()
        snapshot.local_models = local_models_future.result()
        snapshot.cloud_presets = cloud_presets_future.result()

    _emit_progress(progress, "startup.status.workspace", 88)
    LOGGER.info(
        "Startup warmup completed; projects=%s project_config_issues=%s ffmpeg_ready=%s "
        "encoder_options=%s llamacpp_ready=%s whisper_ready=%s local_models=%s cloud_presets=%s "
        "duration_ms=%.1f",
        len(snapshot.project_configs),
        len(snapshot.project_config_issues),
        snapshot.ffmpeg_ready,
        len(snapshot.encoder_options),
        snapshot.llamacpp_ready,
        snapshot.whisper_status.ready if snapshot.whisper_status is not None else False,
        len(snapshot.local_models),
        len(snapshot.cloud_presets),
        (perf_counter() - started_at) * 1000,
    )
    return snapshot


def _probe_ffmpeg() -> tuple[list[DeviceOption], bool]:
    encoder_options = list_available_device_options()
    ffmpeg_ready = bool(encoder_options)
    if not ffmpeg_ready:
        # Some FFmpeg builds may be usable but report no preferred encoder candidates.
        ffmpeg_ready = has_ffmpeg_binary()
    return encoder_options, ffmpeg_ready


def _run_timed_probe(name: str, probe: Callable[[], ProbeResult]) -> ProbeResult:
    started_at = perf_counter()
    try:
        return probe()
    finally:
        LOGGER.info(
            "Startup warmup probe finished; probe=%s duration_ms=%.1f",
            name,
            (perf_counter() - started_at) * 1000,
        )


def _emit_progress(progress: StartupProgressCallback | None, message_key: str, value: int) -> None:
    if progress is not None:
        progress(message_key, value)
