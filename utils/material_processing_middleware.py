from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel, Field

from core.models import ProjectConfig, ProjectPaths, SourceProcessingConfig, SourceProcessingPreset
from utils.ffmpeg_tool import has_ffmpeg_binary, process_raw_sources_with_ffmpeg
from utils.material_preprocessing import (
    PreprocessingCancelledError,
    build_project_preprocessing_request,
    preprocess_project_source,
)
from utils.material_processing_events import SOURCE_PROCESSING_CANCELLED_MESSAGE
from utils.media_types import (
    input_format_profile,
    is_import_supported_source,
    is_preprocessable_source,
)
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
    preprocessed_source_count: int = 0
    derived_material_count: int = 0
    preprocessing_warning_codes: list[str] = Field(default_factory=list)
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
    direct_sources = [source for source in raw_sources if is_import_supported_source(source)]
    container_sources = [source for source in raw_sources if is_preprocessable_source(source)]
    unsupported_sources = [
        source
        for source in raw_sources
        if source not in direct_sources and source not in container_sources
    ]
    preprocessing_warnings = ["unsupported_project_input" for _source in unsupported_sources]
    preprocessed_source_count, derived_material_count, container_warnings = (
        _preprocess_container_sources(
            project_paths(config.project_id),
            container_sources,
            progress=progress,
            cancelled=cancelled,
        )
    )
    preprocessing_warnings.extend(container_warnings)
    _raise_if_cancelled(cancelled)

    linked_count = 0
    if uses_original_sources:
        linked_count = link_raw_sources_to_materials(
            config.project_id,
            direct_sources,
            progress=progress,
        )
    else:
        linked_count = process_raw_sources_with_ffmpeg(
            config.project_id,
            direct_sources,
            config.source_processing,
            progress=progress,
            cancelled=cancelled,
        )
    _raise_if_cancelled(cancelled)

    save_project_config(updated_config)
    LOGGER.info(
        "Source processing request completed through middleware; project_id=%s raw_count=%s "
        "linked_count=%s preprocessed_source_count=%s derived_material_count=%s "
        "preprocessing_warning_count=%s uses_original_sources=%s",
        config.project_id,
        len(raw_sources),
        linked_count,
        preprocessed_source_count,
        derived_material_count,
        len(preprocessing_warnings),
        uses_original_sources,
    )
    return SourceProcessingResult(
        config=updated_config,
        linked_count=linked_count,
        preprocessed_source_count=preprocessed_source_count,
        derived_material_count=derived_material_count,
        preprocessing_warning_codes=preprocessing_warnings,
        uses_original_sources=uses_original_sources,
    )


def _preprocess_container_sources(
    paths: ProjectPaths,
    sources: list[Path],
    *,
    progress: ProgressCallback | None,
    cancelled: CancelledCallback | None,
) -> tuple[int, int, list[str]]:
    completed_count = 0
    derived_count = 0
    warning_codes: list[str] = []
    total = len(sources)
    if progress is not None and total:
        progress(0, total, "")

    for index, source in enumerate(sources, start=1):
        _raise_if_cancelled(cancelled)
        profile = input_format_profile(source)
        if profile is None:
            warning_codes.append("input_format_profile_missing")
            continue
        try:
            request = build_project_preprocessing_request(
                raw_root=paths.raw,
                materials_root=paths.materials,
                cache_root=paths.cache,
                raw_source=source,
                preprocessor_key=profile.preprocessor_key,
                cancelled=cancelled,
            )
            result = preprocess_project_source(
                request,
                raw_root=paths.raw,
                materials_root=paths.materials,
                cache_root=paths.cache,
            )
        except PreprocessingCancelledError as exc:
            raise RuntimeError(SOURCE_PROCESSING_CANCELLED_MESSAGE) from exc

        warning_codes.extend(warning.code for warning in result.warnings)
        if result.status == "cancelled":
            raise RuntimeError(SOURCE_PROCESSING_CANCELLED_MESSAGE)
        if result.succeeded:
            completed_count += 1
            derived_count += len(result.derived_materials)
        elif not result.warnings:
            warning_codes.append("material_preprocessing_failed")
        if progress is not None:
            progress(index, total, _raw_relative_path(paths.raw, source))
    return completed_count, derived_count, warning_codes


def _raise_if_cancelled(cancelled: CancelledCallback | None) -> None:
    if cancelled is not None and cancelled():
        raise RuntimeError(SOURCE_PROCESSING_CANCELLED_MESSAGE)


def _raw_relative_path(raw_root: Path, raw_source: Path) -> str:
    try:
        return raw_source.resolve().relative_to(raw_root.resolve()).as_posix()
    except ValueError:
        return raw_source.name
