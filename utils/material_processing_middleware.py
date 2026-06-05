from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel, Field

from core.models import ProjectConfig, SourceProcessingConfig, SourceProcessingPreset
from utils.ffmpeg_tool import has_ffmpeg_binary, process_raw_sources_with_ffmpeg
from utils.material_processing_events import SOURCE_PROCESSING_CANCELLED_MESSAGE
from utils.paths import project_paths
from utils.source_importer import import_sources_to_raw, link_raw_sources_to_materials
from utils.state_manager import save_project_config


LOGGER = logging.getLogger(__name__)

ProgressCallback = Callable[[int, int, str], None]
CancelledCallback = Callable[[], bool]


class MaterialProcessingError(RuntimeError):
    pass


class ToolValidationResult(BaseModel):
    is_valid: bool
    requires_ffmpeg: bool
    ffmpeg_ready: bool
    missing_tools: list[str] = Field(default_factory=list)


class SourceProcessingResult(BaseModel):
    config: ProjectConfig
    linked_count: int = 0
    uses_original_sources: bool = True


def validate_source_processing_tools(config: SourceProcessingConfig) -> ToolValidationResult:
    requires_ffmpeg = config.preset != SourceProcessingPreset.ORIGINAL
    ffmpeg_ready = has_ffmpeg_binary()
    missing_tools: list[str] = []
    if requires_ffmpeg and not ffmpeg_ready:
        missing_tools.append("ffmpeg")
    return ToolValidationResult(
        is_valid=not missing_tools,
        requires_ffmpeg=requires_ffmpeg,
        ffmpeg_ready=ffmpeg_ready,
        missing_tools=missing_tools,
    )


def process_source_request(
    config: ProjectConfig,
    *,
    progress: ProgressCallback | None = None,
    cancelled: CancelledCallback | None = None,
) -> SourceProcessingResult:
    LOGGER.info(
        "Source processing request started; project_id=%s source_count=%s preset=%s "
        "trim_enabled=%s transcode_enabled=%s segment_enabled=%s segment_mode=%s "
        "codec=%s encoder_configured=%s resolution=%s",
        config.project_id,
        len(config.source_paths),
        config.source_processing.preset.value,
        config.source_processing.trim_enabled,
        config.source_processing.transcode_enabled,
        config.source_processing.segment_enabled,
        config.source_processing.segment_mode.value,
        config.source_processing.codec,
        bool(config.source_processing.encoder),
        config.source_processing.resolution,
    )
    validation = validate_source_processing_tools(config.source_processing)
    if not validation.is_valid:
        LOGGER.warning(
            "Source processing tool validation failed; project_id=%s missing_tools=%s "
            "requires_ffmpeg=%s ffmpeg_ready=%s",
            config.project_id,
            validation.missing_tools,
            validation.requires_ffmpeg,
            validation.ffmpeg_ready,
        )
        raise MaterialProcessingError("Required source processing tools are unavailable.")

    raw_sources = import_sources_to_raw(
        config.project_id,
        config.source_paths,
        progress=progress,
        cancelled=cancelled,
    )
    _raise_if_cancelled(cancelled)

    raw_root = project_paths(config.project_id).raw
    reimported_paths = {_raw_relative_path(raw_root, raw_source) for raw_source in raw_sources}
    updated_config = config
    if reimported_paths:
        updated_config = config.model_copy(
            update={
                "raw_cleaned_paths": [
                    path for path in config.raw_cleaned_paths if path not in reimported_paths
                ]
            }
        )

    uses_original_sources = config.source_processing.preset == SourceProcessingPreset.ORIGINAL
    linked_count = 0
    if uses_original_sources:
        linked_count = link_raw_sources_to_materials(
            config.project_id,
            raw_sources,
            progress=progress,
        )
    else:
        linked_count = process_raw_sources_with_ffmpeg(
            config.project_id,
            raw_sources,
            config.source_processing,
            progress=progress,
            cancelled=cancelled,
        )
    _raise_if_cancelled(cancelled)

    save_project_config(updated_config)
    LOGGER.info(
        "Source processing request completed through middleware; project_id=%s raw_count=%s "
        "linked_count=%s uses_original_sources=%s",
        config.project_id,
        len(raw_sources),
        linked_count,
        uses_original_sources,
    )
    return SourceProcessingResult(
        config=updated_config,
        linked_count=linked_count,
        uses_original_sources=uses_original_sources,
    )


def _raise_if_cancelled(cancelled: CancelledCallback | None) -> None:
    if cancelled is not None and cancelled():
        raise RuntimeError(SOURCE_PROCESSING_CANCELLED_MESSAGE)


def _raw_relative_path(raw_root: Path, raw_source: Path) -> str:
    try:
        return raw_source.resolve().relative_to(raw_root.resolve()).as_posix()
    except ValueError:
        return raw_source.name
