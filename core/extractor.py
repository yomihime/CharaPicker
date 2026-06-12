from __future__ import annotations

import logging
import json
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

from PyQt6.QtCore import QObject, pyqtSignal

from core import knowledge_base as kb
from core import source_scanner
from core.character_card_store import mark_compiled_official_cards_stale
from core.extraction_ai import (
    FormalExtractionJsonError,
    FormalExtractionOutputTruncatedError,
    build_formal_text_json_request,
    call_formal_json_model,
    call_formal_text_json_model,
    extract_json_object as parse_model_json_object,
    extract_json_object_candidates as parse_model_json_object_candidates,
    total_token_usage,
)
from core.extraction_budget import (
    FORMAL_EPISODE_CONTENT_MERGE,
    FORMAL_EPISODE_SUMMARY,
    FORMAL_SEASON_CONTENT_MERGE,
    FORMAL_SEASON_SUMMARY,
    resolve_text_merge_output_tokens,
    text_merge_budget_warning,
)
from core.extraction_context import (
    build_current_signals,
    build_episode_context_candidate,
    estimate_context_tokens,
    select_episode_context_candidates,
)
from core.extraction_plan import (
    ContentForm,
    DerivedArtifactStatus,
    EpisodePlan,
    ExtractionUnit,
    FormalExtractionMode,
    FormalExtractionRunPlan,
    MediaType,
    SourceTrace,
)
from core.models import (
    ChunkExtractionResult,
    EpisodeTranscript,
    ExtractionArtifactStage,
    ExtractionMode,
    InsightEvent,
    InsightStatus,
    ProjectConfig,
)
from core.transcript_provider import TranscriptArtifactRequest, TranscriptProvider
from core.video_unit_handler import VideoUnitHandler, VideoUnitHandlerConfig
from utils.ai_model_middleware import (
    ModelBackend,
    ModelCallRequest,
    ModelMessage,
    ModelCallError,
    build_model_call_request,
    call_video_model,
    render_prompt_texts,
)
from utils.cloud_model_presets import (
    CLOUD_MAX_OUTPUT_TOKENS_MAX,
    CLOUD_MAX_OUTPUT_TOKENS_STEP,
    CloudModelPreset,
    VideoInputMode,
    cloud_model_provider,
    context_window_budget_tokens,
    load_cloud_model_presets,
    normalize_video_input_mode,
    provider_requires_aliyun_extra_body,
    scale_cloud_max_output_tokens_for_video_duration,
)
from utils.audio_transcription import (
    AudioTranscriptionError,
    TranscriptionOptions,
    transcribe_episode_audio as run_episode_audio_transcription,
    transcript_segments_for_material,
)
from utils.ffmpeg_tool import FfmpegProcessError, probe_video_duration_seconds
from utils.i18n import t
from utils.model_preferences import last_cloud_preset_name
from utils.paths import ensure_project_tree


LOGGER = logging.getLogger(__name__)
PREVIEW_MAX_CHUNKS = 2
PREVIEW_CHUNK_MIN_OUTPUT_TOKENS = 1024
PREVIEW_MIN_OUTPUT_TOKENS_PER_MINUTE = 512
FULL_EXTRACTION_RUN_TYPE = "formal_extraction"
FULL_EXTRACTION_MIN_OUTPUT_TOKENS_PER_MINUTE = PREVIEW_MIN_OUTPUT_TOKENS_PER_MINUTE


class ExtractionStoppedError(RuntimeError):
    pass


class Extractor(QObject):
    insightGenerated = pyqtSignal(dict)
    progressChanged = pyqtSignal(int)

    def scan_source_directory(self, source_root: str) -> dict[str, Any]:
        return source_scanner.scan_source_directory(source_root)

    def scan_formal_materials(self, project_id: str) -> list[EpisodePlan]:
        return source_scanner.scan_formal_materials(project_id)

    def prepare_formal_extraction_run_plan(
        self,
        project_id: str,
        mode: ExtractionMode = ExtractionMode.FULL,
    ) -> FormalExtractionRunPlan:
        episodes = self.scan_formal_materials(project_id)
        return FormalExtractionRunPlan(
            project_id=project_id,
            mode=self._formal_extraction_mode(mode),
            media_types=self._media_types_from_episode_plans(episodes),
            content_forms=self._content_forms_from_episode_plans(episodes),
            episodes=episodes,
            warnings=self._scan_warnings_from_episode_plans(episodes),
            metadata={
                "run_type": FULL_EXTRACTION_RUN_TYPE,
                "scan_type": source_scanner.FORMAL_MATERIAL_SCAN_TYPE,
            },
        )

    def _scan_warnings_from_episode_plans(self, episodes: list[EpisodePlan]) -> list[str]:
        warnings: list[str] = []
        for episode in episodes:
            episode_warnings = episode.metadata.get("warnings")
            if not isinstance(episode_warnings, list):
                continue
            for warning in episode_warnings:
                normalized = self._manifest_string(warning)
                if normalized and normalized not in warnings:
                    warnings.append(normalized)
        return warnings

    def _formal_extraction_mode(self, mode: ExtractionMode) -> FormalExtractionMode:
        if mode == ExtractionMode.CLEAN:
            return FormalExtractionMode.CLEAN
        if mode == ExtractionMode.FAST:
            return FormalExtractionMode.FAST
        return FormalExtractionMode.FULL

    def _legacy_manifest_from_run_plan(self, run_plan: FormalExtractionRunPlan) -> dict[str, Any]:
        seasons: list[dict[str, Any]] = []
        season_index: dict[str, int] = {}
        for episode in run_plan.episodes:
            season_id = episode.season_id
            if season_id not in season_index:
                season_index[season_id] = len(seasons)
                seasons.append(
                    {
                        "season_id": season_id,
                        "source_path": self._manifest_string(
                            episode.metadata.get("season_source_path")
                        ),
                        "display_title": self._manifest_string(
                            episode.metadata.get("season_display_title")
                        ),
                        "sort_key": self._manifest_string(episode.metadata.get("season_sort_key")),
                        "episodes": [],
                    }
                )
            seasons[season_index[season_id]]["episodes"].append(
                self._legacy_episode_from_plan(episode)
            )

        return {
            "schema_version": source_scanner.FORMAL_VIDEO_SCHEMA_VERSION,
            "source_kind": source_scanner.FORMAL_VIDEO_SOURCE_KIND,
            "scan_type": source_scanner.FORMAL_VIDEO_SCAN_TYPE,
            "source_root": str(ensure_project_tree(run_plan.project_id).materials.resolve()),
            "extraction_run_id": run_plan.run_id,
            "extraction_mode": run_plan.mode.value,
            "run_type": FULL_EXTRACTION_RUN_TYPE,
            "seasons": seasons,
        }

    def _legacy_episode_from_plan(self, episode: EpisodePlan) -> dict[str, Any]:
        return {
            "episode_id": episode.episode_id,
            "source_kind": self._manifest_string(episode.metadata.get("legacy_source_kind"))
            or source_scanner.FORMAL_VIDEO_SOURCE_KIND,
            "source_path": self._manifest_string(episode.metadata.get("legacy_source_path")),
            "display_title": episode.display_title,
            "sort_key": episode.sort_key,
            "chunks": [
                self._legacy_chunk_from_unit(unit)
                for unit in episode.units
                if unit.media_type == MediaType.VIDEO
            ],
        }

    def _legacy_chunk_from_unit(self, unit: ExtractionUnit) -> dict[str, Any]:
        material_ref = unit.material_ref
        return {
            "chunk_id": self._manifest_string(unit.metadata.get("legacy_chunk_id")) or unit.unit_id,
            "source_kind": material_ref.source_media_type.value,
            "source_path": material_ref.relative_path,
            "display_title": self._manifest_string(material_ref.metadata.get("display_title")),
            "sort_key": self._manifest_string(material_ref.metadata.get("sort_key"))
            or material_ref.relative_path.lower(),
        }

    def _media_types_from_episode_plans(self, episodes: list[EpisodePlan]) -> list[MediaType]:
        seen: set[MediaType] = set()
        output: list[MediaType] = []
        for episode in episodes:
            for unit in episode.units:
                if unit.media_type not in seen:
                    seen.add(unit.media_type)
                    output.append(unit.media_type)
        return output

    def _content_forms_from_episode_plans(self, episodes: list[EpisodePlan]) -> list[ContentForm]:
        seen: set[ContentForm] = set()
        output: list[ContentForm] = []
        for episode in episodes:
            for content_form in episode.content_forms:
                if content_form not in seen:
                    seen.add(content_form)
                    output.append(content_form)
        return output

    def _with_extraction_run_metadata(
        self,
        manifest: dict[str, Any],
        *,
        mode: ExtractionMode,
    ) -> dict[str, Any]:
        output = dict(manifest)
        output["extraction_run_id"] = self._manifest_string(
            output.get("extraction_run_id")
        ) or f"run-{uuid4().hex[:12]}"
        output["extraction_mode"] = mode.value
        output["run_type"] = FULL_EXTRACTION_RUN_TYPE
        return output

    def save_chunk_extraction_result(self, project_id: str, result: ChunkExtractionResult) -> Path:
        return kb.save_chunk_result(project_id, result)

    def save_preview_chunk_extraction_result(self, project_id: str, result: ChunkExtractionResult) -> Path:
        return kb.save_preview_chunk_result(project_id, result)

    def merge_episode_content(
        self,
        project_id: str,
        season_id: str,
        episode_id: str,
        *,
        extraction_run_id: str = "",
    ) -> Path:
        chunk_dir = kb.chunks_root_path(project_id, season_id, episode_id)
        chunk_paths = sorted(
            [path for path in chunk_dir.glob("*.json") if path.is_file()],
            key=lambda path: path.name.lower(),
        )

        chunk_results: list[dict[str, Any]] = []
        targets: list[str] = []
        facts: list[str] = []
        behavior_traits: list[str] = []
        dialogue_style: list[str] = []
        relationship_interactions: list[str] = []
        conflicts: list[str] = []
        character_state_changes: list[str] = []
        evidence_refs: list[str] = []
        aggregation_warnings: list[str] = []
        skipped_chunks = 0
        full_chunks: list[ChunkExtractionResult] = []

        for chunk_path in chunk_paths:
            if kb.is_preview_artifact_path(chunk_path):
                skipped_chunks += 1
                continue
            try:
                payload = kb.read_json_object(chunk_path)
            except (OSError, ValueError, json.JSONDecodeError):
                skipped_chunks += 1
                warning = f"chunk_read_failed:{chunk_path.name}"
                aggregation_warnings.append(warning)
                LOGGER.warning(
                    "Chunk JSON read failed during episode merge; project_id=%s season_id=%s episode_id=%s file_name=%s",
                    project_id,
                    season_id,
                    episode_id,
                    chunk_path.name,
                    exc_info=True,
                )
                continue
            if not kb.is_full_artifact_payload(payload):
                skipped_chunks += 1
                continue
            if not kb.is_matching_run_artifact_payload(payload, extraction_run_id):
                skipped_chunks += 1
                warning = f"chunk_run_mismatch:{chunk_path.name}"
                aggregation_warnings.append(warning)
                continue
            try:
                chunk = ChunkExtractionResult.model_validate(payload)
            except ValueError:
                skipped_chunks += 1
                warning = f"chunk_validation_failed:{chunk_path.name}"
                aggregation_warnings.append(warning)
                LOGGER.warning(
                    "Full chunk validation failed during episode merge; project_id=%s season_id=%s episode_id=%s file_name=%s",
                    project_id,
                    season_id,
                    episode_id,
                    chunk_path.name,
                    exc_info=True,
                )
                continue
            full_chunks.append(chunk)
            chunk_results.append(chunk.model_dump(mode="json"))
            targets.extend(chunk.targets)
            facts.extend(chunk.facts)
            behavior_traits.extend(chunk.behavior_traits)
            dialogue_style.extend(chunk.dialogue_style)
            relationship_interactions.extend(chunk.relationship_interactions)
            conflicts.extend(chunk.conflicts)
            character_state_changes.extend(chunk.character_state_changes)
            evidence_refs.extend(chunk.evidence_refs)

        if not chunk_paths:
            warning = f"no_chunk_files:{season_id}/{episode_id}"
            aggregation_warnings.append(warning)
            LOGGER.warning(
                "No chunk JSON files found during episode merge; project_id=%s season_id=%s episode_id=%s",
                project_id,
                season_id,
                episode_id,
            )
        if not chunk_results:
            warning = f"no_full_chunks:{season_id}/{episode_id}"
            aggregation_warnings.append(warning)
            LOGGER.warning(
                "No full chunk JSON files found during episode merge; project_id=%s season_id=%s episode_id=%s",
                project_id,
                season_id,
                episode_id,
            )

        source_trace = self._source_trace_from_chunks(full_chunks)
        media_types = self._media_types_from_source_trace(source_trace)
        episode_content = {
            "season_id": season_id,
            "episode_id": episode_id,
            "extraction_stage": kb.FULL_EXTRACTION_STAGE,
            "extraction_run_id": extraction_run_id,
            "run_type": FULL_EXTRACTION_RUN_TYPE,
            "source_kind": "video",
            "media_types": media_types,
            "schema_version": 1,
            "source_trace": source_trace,
            "source_counts": {
                "total_chunk_files": len(chunk_paths),
                "full_chunks": len(chunk_results),
                "skipped_chunks": skipped_chunks,
                "source_trace_units": len(source_trace.get("unit_refs", [])),
                "source_trace_materials": len(source_trace.get("material_refs", [])),
                "source_trace_derived_artifacts": len(
                    source_trace.get("derived_artifact_refs", [])
                ),
            },
            "aggregation_warnings": aggregation_warnings,
            "targets": self._deduplicate_preserve_order(targets),
            "chunk_results": chunk_results,
            "facts": self._deduplicate_preserve_order(facts),
            "behavior_traits": self._deduplicate_preserve_order(behavior_traits),
            "dialogue_style": self._deduplicate_preserve_order(dialogue_style),
            "relationship_interactions": self._deduplicate_preserve_order(relationship_interactions),
            "conflicts": self._deduplicate_preserve_order(conflicts),
            "character_state_changes": self._deduplicate_preserve_order(character_state_changes),
            "evidence_refs": self._deduplicate_preserve_order(evidence_refs),
        }
        return kb.save_episode_content(project_id, season_id, episode_id, episode_content)

    def _source_trace_from_chunks(self, chunks: list[ChunkExtractionResult]) -> dict[str, Any]:
        payloads = [chunk.model_dump(mode="json") for chunk in chunks]
        return self._source_trace_from_payloads(
            payloads,
            source_breakdown={"chunks": len(chunks)},
        )

    def _source_trace_for_episode_summary(self, episode_content: dict[str, Any]) -> dict[str, Any]:
        return self._source_trace_from_payloads(
            [episode_content],
            extra_refs={
                "episode_content_refs": [
                    self._episode_artifact_ref(
                        episode_content,
                        artifact_type="episode_content",
                        file_name="episode_content.json",
                    )
                ],
            },
            source_breakdown={"episode_contents": 1},
        )

    def _source_trace_for_season_content(
        self,
        episode_contents: list[dict[str, Any]],
        *,
        episode_summaries: list[dict[str, Any]] | None = None,
        previous_season_backgrounds: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        episode_summaries = episode_summaries or []
        previous_season_backgrounds = previous_season_backgrounds or []
        return self._source_trace_from_payloads(
            [*episode_contents, *episode_summaries, *previous_season_backgrounds],
            extra_refs={
                "episode_content_refs": [
                    self._episode_artifact_ref(
                        payload,
                        artifact_type="episode_content",
                        file_name="episode_content.json",
                    )
                    for payload in episode_contents
                ],
                "episode_summary_refs": [
                    self._episode_artifact_ref(
                        payload,
                        artifact_type="episode_summary",
                        file_name="episode_summary.json",
                    )
                    for payload in episode_summaries
                ],
                "previous_season_summary_refs": [
                    self._season_artifact_ref(
                        payload,
                        artifact_type="season_summary",
                        file_name="season_summary.json",
                    )
                    for payload in previous_season_backgrounds
                ],
            },
            source_breakdown={
                "episode_contents": len(episode_contents),
                "episode_summaries": len(episode_summaries),
                "previous_season_summaries": len(previous_season_backgrounds),
            },
        )

    def _source_trace_for_season_summary(
        self,
        season_content: dict[str, Any],
        *,
        episode_summaries: list[dict[str, Any]] | None = None,
        previous_season_backgrounds: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        episode_summaries = episode_summaries or []
        previous_season_backgrounds = previous_season_backgrounds or []
        return self._source_trace_from_payloads(
            [season_content, *episode_summaries, *previous_season_backgrounds],
            extra_refs={
                "season_content_refs": [
                    self._season_artifact_ref(
                        season_content,
                        artifact_type="season_content",
                        file_name="season_content.json",
                    )
                ],
                "episode_summary_refs": [
                    self._episode_artifact_ref(
                        payload,
                        artifact_type="episode_summary",
                        file_name="episode_summary.json",
                    )
                    for payload in episode_summaries
                ],
                "previous_season_summary_refs": [
                    self._season_artifact_ref(
                        payload,
                        artifact_type="season_summary",
                        file_name="season_summary.json",
                    )
                    for payload in previous_season_backgrounds
                ],
            },
            source_breakdown={
                "season_contents": 1,
                "episode_summaries": len(episode_summaries),
                "previous_season_summaries": len(previous_season_backgrounds),
            },
        )

    def _source_trace_from_payloads(
        self,
        payloads: list[dict[str, Any]],
        *,
        extra_refs: dict[str, list[dict[str, Any]]] | None = None,
        source_breakdown: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        material_refs = self._unique_trace_material_refs_from_payloads(payloads)
        unit_refs = self._unique_trace_string_refs_from_payloads(payloads, "unit_refs")
        derived_artifact_refs = self._unique_trace_string_refs_from_payloads(
            payloads,
            "derived_artifact_refs",
        )
        media_type_counts = self._media_type_counts_from_material_refs(material_refs)
        for payload in payloads:
            for media_type in self._media_types_from_payload(payload):
                media_type_counts.setdefault(media_type, 0)

        trace: dict[str, Any] = {
            "material_refs": material_refs,
            "unit_refs": unit_refs,
            "derived_artifact_refs": derived_artifact_refs,
            "media_types": list(media_type_counts),
        }
        for field_name in (
            "episode_content_refs",
            "episode_summary_refs",
            "season_content_refs",
            "previous_season_summary_refs",
        ):
            refs = self._unique_trace_artifact_refs_from_payloads(payloads, field_name)
            if extra_refs and field_name in extra_refs:
                refs = self._unique_artifact_refs([*refs, *extra_refs[field_name]])
            if refs:
                trace[field_name] = refs

        breakdown = dict(source_breakdown or {})
        breakdown.update(
            {
                "materials": len(material_refs),
                "units": len(unit_refs),
                "derived_artifacts": len(derived_artifact_refs),
                "media_types": media_type_counts,
            }
        )
        for field_name in (
            "episode_content_refs",
            "episode_summary_refs",
            "season_content_refs",
            "previous_season_summary_refs",
        ):
            refs = trace.get(field_name, [])
            if refs:
                breakdown[field_name] = len(refs)
        trace["source_breakdown"] = breakdown
        return trace

    def _unique_trace_material_refs_from_payloads(
        self,
        payloads: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        refs: list[dict[str, Any]] = []
        seen: set[str] = set()
        for payload in payloads:
            trace = self._payload_source_trace(payload)
            for item in trace.get("material_refs", []):
                if not isinstance(item, dict):
                    continue
                key = self._manifest_string(item.get("material_id")) or self._manifest_string(
                    item.get("relative_path")
                )
                if not key or key in seen:
                    continue
                seen.add(key)
                refs.append(item)
        return refs

    def _unique_trace_string_refs_from_payloads(
        self,
        payloads: list[dict[str, Any]],
        field_name: str,
    ) -> list[str]:
        refs: list[str] = []
        seen: set[str] = set()
        for payload in payloads:
            trace = self._payload_source_trace(payload)
            values = trace.get(field_name, [])
            if not isinstance(values, list):
                continue
            for value in values:
                ref = self._manifest_string(value)
                if not ref or ref in seen:
                    continue
                seen.add(ref)
                refs.append(ref)
        return refs

    def _unique_trace_artifact_refs_from_payloads(
        self,
        payloads: list[dict[str, Any]],
        field_name: str,
    ) -> list[dict[str, Any]]:
        refs: list[dict[str, Any]] = []
        for payload in payloads:
            trace = self._payload_source_trace(payload)
            values = trace.get(field_name, [])
            if not isinstance(values, list):
                continue
            refs.extend(item for item in values if isinstance(item, dict))
        return self._unique_artifact_refs(refs)

    def _payload_source_trace(self, payload: dict[str, Any]) -> dict[str, Any]:
        trace = payload.get("source_trace")
        return trace if isinstance(trace, dict) else {}

    def _episode_artifact_ref(
        self,
        payload: dict[str, Any],
        *,
        artifact_type: str,
        file_name: str,
    ) -> dict[str, Any]:
        season_id = self._manifest_string(payload.get("season_id"))
        episode_id = self._manifest_string(payload.get("episode_id"))
        ref = {
            "artifact_type": artifact_type,
            "season_id": season_id,
            "episode_id": episode_id,
            "path": f"seasons/{season_id}/episodes/{episode_id}/{file_name}",
        }
        extraction_run_id = self._manifest_string(payload.get("extraction_run_id"))
        if extraction_run_id:
            ref["extraction_run_id"] = extraction_run_id
        return ref

    def _season_artifact_ref(
        self,
        payload: dict[str, Any],
        *,
        artifact_type: str,
        file_name: str,
    ) -> dict[str, Any]:
        season_id = self._manifest_string(payload.get("season_id"))
        ref = {
            "artifact_type": artifact_type,
            "season_id": season_id,
            "path": f"seasons/{season_id}/{file_name}",
        }
        extraction_run_id = self._manifest_string(payload.get("extraction_run_id"))
        if extraction_run_id:
            ref["extraction_run_id"] = extraction_run_id
        return ref

    def _unique_artifact_refs(self, refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        unique_refs: list[dict[str, Any]] = []
        seen: set[str] = set()
        for ref in refs:
            key = "|".join(
                [
                    self._manifest_string(ref.get("artifact_type")),
                    self._manifest_string(ref.get("season_id")),
                    self._manifest_string(ref.get("episode_id")),
                    self._manifest_string(ref.get("path")),
                    self._manifest_string(ref.get("extraction_run_id")),
                ]
            )
            if not key.strip("|") or key in seen:
                continue
            seen.add(key)
            unique_refs.append(ref)
        return unique_refs

    def _media_type_counts_from_material_refs(
        self,
        material_refs: list[dict[str, Any]],
    ) -> dict[str, int]:
        counts: dict[str, int] = {}
        for ref in material_refs:
            media_type = self._manifest_string(
                ref.get("source_media_type") or ref.get("media_type")
            )
            if not media_type:
                continue
            counts[media_type] = counts.get(media_type, 0) + 1
        return counts

    def _media_types_from_payload(self, payload: dict[str, Any]) -> list[str]:
        media_types = payload.get("media_types")
        if isinstance(media_types, list):
            return [
                media_type
                for media_type in (self._manifest_string(value) for value in media_types)
                if media_type
            ]
        source_trace = self._payload_source_trace(payload)
        trace_media_types = source_trace.get("media_types")
        if isinstance(trace_media_types, list):
            return [
                media_type
                for media_type in (self._manifest_string(value) for value in trace_media_types)
                if media_type
            ]
        source_breakdown = source_trace.get("source_breakdown", {})
        media_type_counts = (
            source_breakdown.get("media_types") if isinstance(source_breakdown, dict) else None
        )
        if isinstance(media_type_counts, dict):
            return [
                media_type
                for media_type in (self._manifest_string(value) for value in media_type_counts)
                if media_type
            ]
        source_kind = self._manifest_string(payload.get("source_kind"))
        return [source_kind] if source_kind else []

    def _media_types_from_source_trace(self, source_trace: dict[str, Any]) -> list[str]:
        media_types = source_trace.get("media_types")
        if isinstance(media_types, list):
            return [
                media_type
                for media_type in (self._manifest_string(value) for value in media_types)
                if media_type
            ]
        return []

    def _load_episode_summaries_for_source_trace(
        self,
        project_id: str,
        season_id: str,
        episode_contents: list[dict[str, Any]],
        *,
        extraction_run_id: str,
    ) -> list[dict[str, Any]]:
        episode_summaries: list[dict[str, Any]] = []
        for episode_content in episode_contents:
            episode_id = self._manifest_string(episode_content.get("episode_id"))
            if not episode_id:
                continue
            try:
                summary = kb.load_episode_summary(project_id, season_id, episode_id)
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            if kb.is_full_artifact_payload_for_run(summary, extraction_run_id):
                episode_summaries.append(summary)
        return episode_summaries

    def merge_preview_episode_content(self, project_id: str, season_id: str, episode_id: str) -> Path:
        episode_chunks_root = kb.chunks_root_path(project_id, season_id, episode_id).resolve()
        chunk_paths = [
            path
            for path in kb.list_preview_chunk_result_paths(
                project_id,
                include_legacy_top_level=False,
            )
            if path.parent.resolve() == episode_chunks_root
        ]

        chunk_results: list[dict[str, Any]] = []
        targets: list[str] = []
        facts: list[str] = []
        behavior_traits: list[str] = []
        dialogue_style: list[str] = []
        relationship_interactions: list[str] = []
        conflicts: list[str] = []
        character_state_changes: list[str] = []
        evidence_refs: list[str] = []

        for chunk_path in chunk_paths:
            chunk = kb.load_chunk_result(chunk_path)
            chunk_results.append(chunk.model_dump(mode="json"))
            targets.extend(chunk.targets)
            facts.extend(chunk.facts)
            behavior_traits.extend(chunk.behavior_traits)
            dialogue_style.extend(chunk.dialogue_style)
            relationship_interactions.extend(chunk.relationship_interactions)
            conflicts.extend(chunk.conflicts)
            character_state_changes.extend(chunk.character_state_changes)
            evidence_refs.extend(chunk.evidence_refs)

        episode_content = {
            "season_id": season_id,
            "episode_id": episode_id,
            "extraction_stage": kb.PREVIEW_EXTRACTION_STAGE,
            "run_type": "preview_trial",
            "source_kind": "video",
            "schema_version": 1,
            "targets": self._deduplicate_preserve_order(targets),
            "chunk_results": chunk_results,
            "facts": self._deduplicate_preserve_order(facts),
            "behavior_traits": self._deduplicate_preserve_order(behavior_traits),
            "dialogue_style": self._deduplicate_preserve_order(dialogue_style),
            "relationship_interactions": self._deduplicate_preserve_order(relationship_interactions),
            "conflicts": self._deduplicate_preserve_order(conflicts),
            "character_state_changes": self._deduplicate_preserve_order(character_state_changes),
            "evidence_refs": self._deduplicate_preserve_order(evidence_refs),
        }
        return kb.save_preview_episode_content(project_id, season_id, episode_id, episode_content)

    def generate_episode_summary(
        self,
        project_id: str,
        season_id: str,
        episode_id: str,
        *,
        extraction_run_id: str = "",
    ) -> Path:
        episode_content_path = kb.episode_content_path(project_id, season_id, episode_id)
        if not episode_content_path.exists():
            raise ValueError("episode content not found; merge episode content first")

        episode_content = kb.load_episode_content(project_id, season_id, episode_id)
        if not kb.is_full_artifact_payload(episode_content):
            LOGGER.warning(
                "Non-full episode content rejected during episode summary generation; "
                "project_id=%s season_id=%s episode_id=%s stage=%s",
                project_id,
                season_id,
                episode_id,
                kb.artifact_stage_from_payload(episode_content),
            )
            raise ValueError("episode content is not a full extraction artifact")
        if not kb.is_matching_run_artifact_payload(episode_content, extraction_run_id):
            raise ValueError("episode content does not match current extraction run")
        artifact_run_id = extraction_run_id.strip() or kb.extraction_run_id_from_payload(episode_content)
        chunk_results = episode_content.get("chunk_results", [])
        insight_summaries: list[str] = []
        for chunk in chunk_results:
            if not isinstance(chunk, dict):
                continue
            insight = chunk.get("insight_summary", "")
            if isinstance(insight, str) and insight.strip():
                insight_summaries.append(insight.strip())

        source_trace = self._source_trace_for_episode_summary(episode_content)
        source_counts = episode_content.get("source_counts", {})
        if not isinstance(source_counts, dict):
            source_counts = {}
        summary = {
            "season_id": season_id,
            "episode_id": episode_id,
            "extraction_stage": kb.FULL_EXTRACTION_STAGE,
            "extraction_run_id": artifact_run_id,
            "run_type": FULL_EXTRACTION_RUN_TYPE,
            "source_kind": "video",
            "media_types": self._media_types_from_source_trace(source_trace),
            "schema_version": 1,
            "source_trace": source_trace,
            "source_counts": {
                **source_counts,
                "source_trace_episode_contents": len(
                    source_trace.get("episode_content_refs", [])
                ),
                "source_trace_units": len(source_trace.get("unit_refs", [])),
                "source_trace_materials": len(source_trace.get("material_refs", [])),
                "source_trace_derived_artifacts": len(
                    source_trace.get("derived_artifact_refs", [])
                ),
            },
            "aggregation_warnings": episode_content.get("aggregation_warnings", []),
            "character_summaries": episode_content.get("behavior_traits", []),
            "relationship_changes": episode_content.get("relationship_interactions", []),
            "major_events": episode_content.get("facts", []),
            "open_conflicts": episode_content.get("conflicts", []),
            "growth_signals": episode_content.get("character_state_changes", []),
            "insight_summary": " | ".join(self._deduplicate_preserve_order(insight_summaries)),
        }
        return kb.save_episode_summary(project_id, season_id, episode_id, summary)

    def merge_season_content(
        self,
        project_id: str,
        season_id: str,
        *,
        extraction_run_id: str = "",
    ) -> Path:
        episodes_root = kb.episodes_root_path(project_id, season_id)
        if not episodes_root.exists():
            raise ValueError("season episodes not found; initialize knowledge base structure first")

        episode_dirs = kb.list_episode_dirs(project_id, season_id)
        episode_contents: list[dict[str, Any]] = []
        targets: list[str] = []
        facts: list[str] = []
        behavior_traits: list[str] = []
        dialogue_style: list[str] = []
        relationship_interactions: list[str] = []
        conflicts: list[str] = []
        character_state_changes: list[str] = []
        evidence_refs: list[str] = []
        aggregation_warnings: list[str] = []
        skipped_episodes = 0

        for episode_dir in episode_dirs:
            episode_content_path = kb.episode_content_path(project_id, season_id, episode_dir.name)
            if not episode_content_path.exists():
                skipped_episodes += 1
                warning = f"episode_content_missing:{episode_dir.name}"
                aggregation_warnings.append(warning)
                LOGGER.warning(
                    "Episode content missing during season merge; project_id=%s season_id=%s episode_id=%s",
                    project_id,
                    season_id,
                    episode_dir.name,
                )
                continue
            try:
                payload = kb.load_episode_content(project_id, season_id, episode_dir.name)
            except (OSError, ValueError, json.JSONDecodeError):
                skipped_episodes += 1
                warning = f"episode_content_read_failed:{episode_dir.name}"
                aggregation_warnings.append(warning)
                LOGGER.warning(
                    "Episode content read failed during season merge; project_id=%s season_id=%s episode_id=%s",
                    project_id,
                    season_id,
                    episode_dir.name,
                    exc_info=True,
                )
                continue
            if not kb.is_full_artifact_payload_for_run(payload, extraction_run_id):
                skipped_episodes += 1
                warning = f"episode_content_not_full:{episode_dir.name}"
                aggregation_warnings.append(warning)
                LOGGER.warning(
                    "Non-full episode content skipped during season merge; "
                    "project_id=%s season_id=%s episode_id=%s stage=%s",
                    project_id,
                    season_id,
                    episode_dir.name,
                    kb.artifact_stage_from_payload(payload),
                )
                continue
            episode_contents.append(payload)
            targets.extend(payload.get("targets", []))
            facts.extend(payload.get("facts", []))
            behavior_traits.extend(payload.get("behavior_traits", []))
            dialogue_style.extend(payload.get("dialogue_style", []))
            relationship_interactions.extend(payload.get("relationship_interactions", []))
            conflicts.extend(payload.get("conflicts", []))
            character_state_changes.extend(payload.get("character_state_changes", []))
            evidence_refs.extend(payload.get("evidence_refs", []))

        if not episode_contents:
            warning = f"no_full_episode_contents:{season_id}"
            aggregation_warnings.append(warning)
            LOGGER.warning(
                "No full episode content found during season merge; project_id=%s season_id=%s",
                project_id,
                season_id,
            )

        source_trace = self._source_trace_for_season_content(episode_contents)
        season_content = {
            "season_id": season_id,
            "extraction_stage": kb.FULL_EXTRACTION_STAGE,
            "extraction_run_id": extraction_run_id,
            "run_type": FULL_EXTRACTION_RUN_TYPE,
            "source_kind": "video",
            "media_types": self._media_types_from_source_trace(source_trace),
            "schema_version": 1,
            "source_trace": source_trace,
            "source_counts": {
                "total_episode_dirs": len(episode_dirs),
                "full_episodes": len(episode_contents),
                "skipped_episodes": skipped_episodes,
                "source_trace_episode_contents": len(
                    source_trace.get("episode_content_refs", [])
                ),
                "source_trace_units": len(source_trace.get("unit_refs", [])),
                "source_trace_materials": len(source_trace.get("material_refs", [])),
                "source_trace_derived_artifacts": len(
                    source_trace.get("derived_artifact_refs", [])
                ),
            },
            "aggregation_warnings": aggregation_warnings,
            "episode_contents": episode_contents,
            "targets": self._deduplicate_preserve_order(targets),
            "facts": self._deduplicate_preserve_order(facts),
            "behavior_traits": self._deduplicate_preserve_order(behavior_traits),
            "dialogue_style": self._deduplicate_preserve_order(dialogue_style),
            "relationship_interactions": self._deduplicate_preserve_order(relationship_interactions),
            "conflicts": self._deduplicate_preserve_order(conflicts),
            "character_state_changes": self._deduplicate_preserve_order(character_state_changes),
            "evidence_refs": self._deduplicate_preserve_order(evidence_refs),
        }
        return kb.save_season_content(project_id, season_id, season_content)

    def generate_season_summary(
        self,
        project_id: str,
        season_id: str,
        *,
        extraction_run_id: str = "",
    ) -> Path:
        season_content_path = kb.season_content_path(project_id, season_id)
        if not season_content_path.exists():
            raise ValueError("season content not found; merge season content first")

        season_content = kb.load_season_content(project_id, season_id)
        if not kb.is_full_artifact_payload(season_content):
            LOGGER.warning(
                "Non-full season content rejected during season summary generation; project_id=%s season_id=%s stage=%s",
                project_id,
                season_id,
                kb.artifact_stage_from_payload(season_content),
            )
            raise ValueError("season content is not a full extraction artifact")
        if not kb.is_matching_run_artifact_payload(season_content, extraction_run_id):
            raise ValueError("season content does not match current extraction run")
        artifact_run_id = extraction_run_id.strip() or kb.extraction_run_id_from_payload(season_content)
        episode_contents = season_content.get("episode_contents", [])
        background_parts: list[str] = []
        for episode in episode_contents:
            if not isinstance(episode, dict):
                continue
            episode_id = episode.get("episode_id", "")
            facts = episode.get("facts", [])
            if isinstance(episode_id, str) and isinstance(facts, list) and facts:
                background_parts.append(f"{episode_id}: {'; '.join(str(item) for item in facts)}")

        episode_summaries = self._load_episode_summaries_for_source_trace(
            project_id,
            season_id,
            episode_contents,
            extraction_run_id=artifact_run_id,
        )
        source_trace = self._source_trace_for_season_summary(
            season_content,
            episode_summaries=episode_summaries,
        )
        source_counts = season_content.get("source_counts", {})
        if not isinstance(source_counts, dict):
            source_counts = {}
        summary = {
            "season_id": season_id,
            "extraction_stage": kb.FULL_EXTRACTION_STAGE,
            "extraction_run_id": artifact_run_id,
            "run_type": FULL_EXTRACTION_RUN_TYPE,
            "source_kind": "video",
            "media_types": self._media_types_from_source_trace(source_trace),
            "schema_version": 1,
            "source_trace": source_trace,
            "source_counts": {
                **source_counts,
                "source_trace_season_contents": len(
                    source_trace.get("season_content_refs", [])
                ),
                "source_trace_episode_summaries": len(
                    source_trace.get("episode_summary_refs", [])
                ),
                "source_trace_units": len(source_trace.get("unit_refs", [])),
                "source_trace_materials": len(source_trace.get("material_refs", [])),
                "source_trace_derived_artifacts": len(
                    source_trace.get("derived_artifact_refs", [])
                ),
            },
            "aggregation_warnings": season_content.get("aggregation_warnings", []),
            "final_character_states": season_content.get("character_state_changes", []),
            "relationship_baseline": season_content.get("relationship_interactions", []),
            "major_conflicts": season_content.get("conflicts", []),
            "unresolved_threads": season_content.get("conflicts", []),
            "growth_trajectory": season_content.get("behavior_traits", []),
            "background_summary": " | ".join(background_parts),
        }
        return kb.save_season_summary(project_id, season_id, summary)

    def _deduplicate_preserve_order(self, values: list[str]) -> list[str]:
        seen: set[str] = set()
        unique_values: list[str] = []
        for value in values:
            if value in seen:
                continue
            seen.add(value)
            unique_values.append(value)
        return unique_values

    def _collect_preview_chunk_json_inputs(self, project_id: str) -> list[str]:
        return [self._format_preview_chunk_input(chunk) for chunk in self._collect_preview_chunk_results(project_id)]

    def _collect_preview_chunk_results(self, project_id: str) -> list[ChunkExtractionResult]:
        chunk_paths = kb.list_preview_chunk_result_paths(project_id, include_legacy_top_level=False)
        if not chunk_paths:
            return []

        preview_chunks: list[ChunkExtractionResult] = []
        for chunk_path in chunk_paths:
            try:
                chunk = kb.load_chunk_result(chunk_path)
            except (OSError, json.JSONDecodeError, ValueError):
                LOGGER.warning("Preview chunk JSON read failed; file_name=%s", chunk_path.name, exc_info=True)
                continue
            if chunk.season_id == "season_000" or chunk.episode_id == "episode_000":
                continue
            if not self._format_preview_chunk_input(chunk):
                continue

            preview_chunks.append(chunk)
            if len(preview_chunks) >= PREVIEW_MAX_CHUNKS:
                break
        return preview_chunks

    def _format_preview_chunk_input(self, chunk: ChunkExtractionResult) -> str:
        sections: list[str] = [
            f"[CHUNK_ID] {chunk.season_id}/{chunk.episode_id}/{chunk.chunk_id}",
        ]

        if chunk.insight_summary.strip():
            sections.append(f"[INSIGHT_SUMMARY]\n{chunk.insight_summary.strip()}")

        field_mappings = [
            ("FACTS", chunk.facts),
            ("BEHAVIOR_TRAITS", chunk.behavior_traits),
            ("DIALOGUE_STYLE", chunk.dialogue_style),
            ("RELATIONSHIPS", chunk.relationship_interactions),
            ("CONFLICTS", chunk.conflicts),
            ("STATE_CHANGES", chunk.character_state_changes),
            ("EVIDENCE_REFS", chunk.evidence_refs),
        ]
        has_content = bool(chunk.insight_summary.strip())
        for label, values in field_mappings:
            cleaned = [item.strip() for item in values if isinstance(item, str) and item.strip()]
            if not cleaned:
                continue
            has_content = True
            sections.append(f"[{label}]\n" + "\n".join(f"- {item}" for item in cleaned))
        if not has_content:
            return ""
        return "\n\n".join(sections)

    def _collect_preview_video_chunks(self, project_id: str) -> list[Path]:
        return source_scanner.collect_preview_video_chunks(project_id, limit=PREVIEW_MAX_CHUNKS)

    def _build_video_chunk_part(self, video_path: Path, video_fps: float) -> dict[str, Any]:
        return {"video": f"file://{video_path.resolve().as_posix()}", "fps": video_fps}

    def _video_duration_seconds(self, video_path: Path) -> float:
        try:
            return probe_video_duration_seconds(video_path)
        except (FfmpegProcessError, OSError):
            LOGGER.warning(
                "Video chunk duration probe failed; chunk=%s",
                video_path.name,
                exc_info=True,
            )
            return 60.0

    def _preview_chunk_identity(self, project_id: str, video_path: Path, fallback_index: int) -> tuple[str, str, str]:
        return source_scanner.preview_chunk_identity(project_id, video_path, fallback_index)

    def _preview_material_relative_path(self, project_id: str, video_path: Path) -> str:
        materials_root = ensure_project_tree(project_id).materials
        try:
            return video_path.resolve().relative_to(materials_root.resolve()).as_posix()
        except ValueError:
            return video_path.resolve().as_posix()

    def _merge_preview_episode_contents(self, project_id: str, chunks: list[ChunkExtractionResult]) -> None:
        episode_keys = sorted({(chunk.season_id, chunk.episode_id) for chunk in chunks})
        for season_id, episode_id in episode_keys:
            try:
                self.merge_preview_episode_content(project_id, season_id, episode_id)
            except (OSError, ValueError):
                LOGGER.warning(
                    "Preview episode content merge failed; project_id=%s season_id=%s episode_id=%s",
                    project_id,
                    season_id,
                    episode_id,
                    exc_info=True,
                )

    def _extract_json_object(self, content: str) -> dict[str, Any]:
        return parse_model_json_object(content)

    def _extract_json_object_candidates(self, text: str) -> list[dict[str, Any]]:
        return parse_model_json_object_candidates(text)

    def _video_model_extra_body(self, provider: str) -> dict[str, Any]:
        if provider_requires_aliyun_extra_body(provider):
            return {"enable_thinking": False}
        return {}

    def _recommended_output_tokens_per_minute(
        self,
        duration_seconds: float,
        *,
        required_output_tokens: int = PREVIEW_CHUNK_MIN_OUTPUT_TOKENS,
    ) -> int:
        duration = duration_seconds if duration_seconds > 0 else 60.0
        raw_value = max(required_output_tokens, PREVIEW_CHUNK_MIN_OUTPUT_TOKENS) * 60.0 / duration
        rounded = math.ceil(raw_value / CLOUD_MAX_OUTPUT_TOKENS_STEP) * CLOUD_MAX_OUTPUT_TOKENS_STEP
        return min(max(rounded, CLOUD_MAX_OUTPUT_TOKENS_STEP), CLOUD_MAX_OUTPUT_TOKENS_MAX)

    def _output_token_limit_message(
        self,
        *,
        video_name: str,
        request_max_output_tokens: int,
        duration_seconds: float,
    ) -> str:
        return t(
            "extractor.chunk.outputTokenLimitReached",
            name=video_name,
            request_max_tokens=request_max_output_tokens,
            recommended_per_minute=self._recommended_output_tokens_per_minute(
                duration_seconds,
                required_output_tokens=request_max_output_tokens * 2,
            ),
        )

    def _emit_preview_warning(self, emit_event: Callable[[dict], None] | None, description: str) -> None:
        if emit_event is None:
            return
        emit_event(
            InsightEvent(
                title=t("extractor.chunk.title"),
                description=description,
                status=InsightStatus.WARNING,
            ).model_dump(mode="json")
        )

    def _model_first_choice(self, result: Any) -> dict[str, Any]:
        raw = result.raw if isinstance(getattr(result, "raw", None), dict) else {}
        choices = raw.get("choices")
        if not isinstance(choices, list):
            output = raw.get("output")
            if isinstance(output, dict):
                choices = output.get("choices")
        first_choice = choices[0] if isinstance(choices, list) and choices else {}
        if not isinstance(first_choice, dict):
            return {}
        return first_choice

    def _model_finish_reason(self, result: Any) -> str:
        first_choice = self._model_first_choice(result)
        return str(first_choice.get("finish_reason") or "").strip().lower()

    def _model_stopped_by_output_limit(self, result: Any) -> bool:
        return self._model_finish_reason(result) in {"length", "max_tokens"}

    def _provider_rejected_video(self, exc: Exception) -> bool:
        if not isinstance(exc, ModelCallError):
            return False
        text = str(exc)
        lower_text = text.lower()
        return (
            "DataInspectionFailed" in text
            or "inappropriate content" in lower_text
            or "data inspection" in lower_text
            or "content safety" in lower_text
        )

    def _compact_exception_message(self, exc: Exception, *, max_length: int = 300) -> str:
        text = " ".join(str(exc).split())
        if not text:
            text = exc.__class__.__name__
        if len(text) <= max_length:
            return text
        return f"{text[: max_length - 3]}..."

    def _preview_video_chunk_failed_description(
        self,
        *,
        exc: Exception,
        index: int,
        total: int,
        video_name: str,
        stop_on_rejection: bool = False,
    ) -> str:
        if self._provider_rejected_video(exc):
            return t(
                "extractor.chunk.videoRejectedByProviderStopped"
                if stop_on_rejection
                else "extractor.chunk.videoRejectedByProvider",
                current=index,
                total=total,
                name=video_name,
            )
        return t(
            "extractor.chunk.videoChunkFailed",
            current=index,
            total=total,
            name=video_name,
        )

    def _log_preview_model_response_shape(
        self,
        *,
        project_id: str,
        video_name: str,
        result: Any,
    ) -> None:
        first_choice = self._model_first_choice(result)
        message = first_choice.get("message")
        if not isinstance(message, dict):
            message = {}
        content = result.content if isinstance(getattr(result, "content", None), str) else ""
        stripped = content.strip()
        first_char = stripped[:1]
        LOGGER.warning(
            "Preview chunk model response could not be parsed as JSON; "
            "project_id=%s chunk=%s finish_reason=%s content_chars=%s stripped_chars=%s "
            "first_char=%r has_left_brace=%s has_right_brace=%s message_keys=%s",
            project_id,
            video_name,
            first_choice.get("finish_reason"),
            len(content),
            len(stripped),
            first_char,
            "{" in stripped,
            "}" in stripped,
            sorted(str(key) for key in message.keys()),
        )

    def _coerce_string_list(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        output: list[str] = []
        for item in value:
            if isinstance(item, str) and item.strip():
                output.append(item.strip())
        return output

    def _select_cloud_video_preset(self, cloud_preset: CloudModelPreset | None) -> CloudModelPreset | None:
        if cloud_preset is not None:
            if cloud_preset.base_url.strip() and cloud_preset.model_name.strip():
                return cloud_preset
            return None

        presets = load_cloud_model_presets()
        preferred_name = last_cloud_preset_name()
        preset = next(
            (
                item
                for item in presets
                if item.name == preferred_name and item.base_url.strip() and item.model_name.strip()
            ),
            None,
        )
        if preset is not None:
            return preset
        return next((item for item in presets if item.base_url.strip() and item.model_name.strip()), None)

    def _backend_for_video_input_mode(
        self,
        preset: CloudModelPreset,
        video_input_mode: VideoInputMode,
    ) -> ModelBackend:
        provider = cloud_model_provider(preset.provider)
        if video_input_mode == "audio_transcript_only":
            return provider.backend_for("text")  # type: ignore[return-value]
        if video_input_mode in {"frame_sampling", "frame_sampling_with_transcript"}:
            return provider.backend_for("image")  # type: ignore[return-value]
        return provider.backend_for("video")  # type: ignore[return-value]

    def _video_mode_requires_transcript(self, video_input_mode: VideoInputMode) -> bool:
        return VideoUnitHandler.video_mode_requires_transcript(video_input_mode)

    def _video_unit_handler(
        self,
        *,
        provider: str,
        video_fps: float,
        video_input_mode: VideoInputMode,
        max_output_tokens: int,
    ) -> VideoUnitHandler:
        return VideoUnitHandler(
            VideoUnitHandlerConfig(
                provider=provider,
                video_fps=video_fps,
                video_input_mode=video_input_mode,
                max_output_tokens_per_minute=max_output_tokens,
            )
        )

    def _collect_formal_video_chunk_inputs_from_run_plan(
        self,
        project_id: str,
        run_plan: FormalExtractionRunPlan,
    ) -> list[dict[str, Any]]:
        chunk_inputs: list[dict[str, Any]] = []
        for episode in run_plan.episodes:
            season_id = episode.season_id.strip()
            episode_id = episode.episode_id.strip()
            if not season_id or not episode_id:
                continue
            for unit in episode.units:
                if unit.media_type != MediaType.VIDEO:
                    continue
                source_path = unit.material_ref.relative_path.strip()
                if not source_path:
                    continue
                chunk_inputs.append(
                    {
                        "season_id": season_id,
                        "episode_id": episode_id,
                        "chunk_id": self._manifest_string(unit.metadata.get("legacy_chunk_id"))
                        or unit.unit_id,
                        "source_path": source_path,
                        "extraction_run_id": run_plan.run_id,
                        "video_path": self._formal_material_video_path(project_id, source_path),
                        "unit_ref": unit.unit_id,
                        "material_ref": unit.material_ref.model_dump(mode="json"),
                        "source_trace": self._source_trace_for_unit(unit).model_dump(mode="json"),
                    }
                )
        return chunk_inputs

    def _source_trace_for_unit(self, unit: ExtractionUnit) -> SourceTrace:
        return SourceTrace(
            material_refs=[unit.material_ref],
            unit_refs=[unit.unit_id],
            derived_artifact_refs=list(unit.derived_refs),
            source_breakdown={
                "materials": 1,
                "units": 1,
                unit.media_type.value: 1,
            },
        )

    def _source_trace_from_chunk_input(self, chunk_input: dict[str, Any]) -> dict[str, Any]:
        source_trace = chunk_input.get("source_trace")
        return source_trace if isinstance(source_trace, dict) else {}

    def _group_formal_video_chunk_inputs_by_episode(
        self,
        chunk_inputs: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        groups: list[dict[str, Any]] = []
        index_by_key: dict[tuple[str, str], int] = {}
        for chunk_input in chunk_inputs:
            season_id = self._manifest_string(chunk_input.get("season_id"))
            episode_id = self._manifest_string(chunk_input.get("episode_id"))
            if not season_id or not episode_id:
                continue
            key = (season_id, episode_id)
            group_index = index_by_key.get(key)
            if group_index is None:
                group_index = len(groups)
                index_by_key[key] = group_index
                groups.append(
                    {
                        "season_id": season_id,
                        "episode_id": episode_id,
                        "chunks": [],
                    }
                )
            groups[group_index]["chunks"].append(chunk_input)
        return groups

    def _load_completed_episode_context_candidates(
        self,
        project_id: str,
        season_id: str,
        current_episode_id: str,
        *,
        extraction_run_id: str,
    ) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        for episode_dir in kb.list_episode_dirs(project_id, season_id):
            episode_id = episode_dir.name
            if episode_id >= current_episode_id:
                continue
            try:
                episode_content = kb.load_episode_content(project_id, season_id, episode_id)
                episode_summary = kb.load_episode_summary(project_id, season_id, episode_id)
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            if not kb.is_full_artifact_payload_for_run(episode_content, extraction_run_id):
                continue
            if not kb.is_full_artifact_payload_for_run(episode_summary, extraction_run_id):
                continue
            candidates.append(build_episode_context_candidate(episode_content, episode_summary))
        return candidates

    def _load_full_episode_summary_for_run(
        self,
        project_id: str,
        season_id: str,
        episode_id: str,
        *,
        extraction_run_id: str,
    ) -> dict[str, Any] | None:
        if not episode_id:
            return None
        try:
            summary = kb.load_episode_summary(project_id, season_id, episode_id)
        except (OSError, ValueError, json.JSONDecodeError):
            return None
        return summary if kb.is_full_artifact_payload_for_run(summary, extraction_run_id) else None

    def _load_previous_season_backgrounds_for_run(
        self,
        project_id: str,
        manifest: dict[str, Any],
        current_season_id: str,
        *,
        extraction_run_id: str,
    ) -> list[dict[str, Any]]:
        backgrounds: list[dict[str, Any]] = []
        for season in manifest.get("seasons", []):
            if not isinstance(season, dict):
                continue
            season_id = self._manifest_string(season.get("season_id"))
            if not season_id:
                continue
            if season_id == current_season_id:
                break
            try:
                summary = kb.load_season_summary(project_id, season_id)
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            if kb.is_full_artifact_payload_for_run(summary, extraction_run_id):
                backgrounds.append(summary)
        return backgrounds

    def _build_formal_chunk_context_payload(
        self,
        project_id: str,
        manifest: dict[str, Any],
        chunk_input: dict[str, Any],
        *,
        current_episode_chunks: list[ChunkExtractionResult],
        previous_episode_id: str,
        extraction_run_id: str,
    ) -> dict[str, Any]:
        season_id = self._manifest_string(chunk_input.get("season_id"))
        episode_id = self._manifest_string(chunk_input.get("episode_id"))
        current_chunks = [chunk.model_dump(mode="json") for chunk in current_episode_chunks]
        previous_episode_summary = self._load_full_episode_summary_for_run(
            project_id,
            season_id,
            previous_episode_id,
            extraction_run_id=extraction_run_id,
        )
        previous_season_backgrounds = self._load_previous_season_backgrounds_for_run(
            project_id,
            manifest,
            season_id,
            extraction_run_id=extraction_run_id,
        )
        current_signals = build_current_signals(
            current_episode_chunks=current_chunks,
            previous_episode_summary=previous_episode_summary,
            previous_season_summary=previous_season_backgrounds[-1]
            if previous_season_backgrounds
            else None,
            episode_title=episode_id,
        )
        candidates = self._load_completed_episode_context_candidates(
            project_id,
            season_id,
            episode_id,
            extraction_run_id=extraction_run_id,
        )
        selection = select_episode_context_candidates(
            candidates,
            current_signals,
            previous_episode_id=previous_episode_id,
        )
        selected_episode_contexts = self._materialize_selected_episode_contexts(
            candidates,
            selection.get("selected_contexts", []),
        )
        context_policy = dict(selection.get("context_policy", {}))
        context_policy["selected_contexts"] = [
            {
                key: value
                for key, value in item.items()
                if key != "context"
            }
            for item in selected_episode_contexts
        ]
        context_policy["previous_episode_id"] = previous_episode_id
        context_policy["previous_season_background_count"] = len(previous_season_backgrounds)
        return {
            "current_episode_extracted_chunks": current_chunks,
            "current_season_completed_episodes": selected_episode_contexts,
            "previous_season_backgrounds": previous_season_backgrounds,
            "context_policy": context_policy,
        }

    def _materialize_selected_episode_contexts(
        self,
        candidates: list[dict[str, Any]],
        selected_contexts: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        lookup = {
            (
                self._manifest_string(candidate.get("season_id")),
                self._manifest_string(candidate.get("episode_id")),
            ): candidate
            for candidate in candidates
        }
        output: list[dict[str, Any]] = []
        for selected in selected_contexts:
            season_id = self._manifest_string(selected.get("season_id"))
            episode_id = self._manifest_string(selected.get("episode_id"))
            view = self._manifest_string(selected.get("view")) or "context_brief"
            candidate = lookup.get((season_id, episode_id))
            if not candidate:
                continue
            output.append(
                {
                    "season_id": season_id,
                    "episode_id": episode_id,
                    "view": view,
                    "estimated_tokens": selected.get("estimated_tokens", 0),
                    "relevance": selected.get("relevance", 0.0),
                    "selection_reason": selected.get("selection_reason", ""),
                    "context": candidate.get(view),
                }
            )
        return output

    def _finalize_formal_episode_context(
        self,
        project_id: str,
        manifest: dict[str, Any],
        season_id: str,
        episode_id: str,
        *,
        chunk_inputs: list[dict[str, Any]],
        episode_chunks: list[ChunkExtractionResult],
        previous_episode_id: str,
        extraction_run_id: str,
        backend: ModelBackend,
        model_name: str,
        base_url: str,
        api_key: str,
        context_window_tokens: int | None,
    ) -> tuple[bool, dict[str, int]]:
        try:
            merge_usage = self._merge_episode_content_with_ai(
                project_id,
                manifest,
                season_id,
                episode_id,
                chunk_inputs=chunk_inputs,
                episode_chunks=episode_chunks,
                previous_episode_id=previous_episode_id,
                extraction_run_id=extraction_run_id,
                backend=backend,
                model_name=model_name,
                base_url=base_url,
                api_key=api_key,
                context_window_tokens=context_window_tokens,
            )
        except Exception:  # noqa: BLE001
            LOGGER.warning(
                "Formal episode AI content merge failed; project_id=%s season_id=%s episode_id=%s",
                project_id,
                season_id,
                episode_id,
                exc_info=True,
            )
            return (False, {})

        try:
            summary_usage = self._generate_episode_summary_with_ai(
                project_id,
                season_id,
                episode_id,
                extraction_run_id=extraction_run_id,
                backend=backend,
                model_name=model_name,
                base_url=base_url,
                api_key=api_key,
                context_window_tokens=context_window_tokens,
            )
        except Exception:  # noqa: BLE001
            LOGGER.warning(
                "Formal episode AI summary after AI merge failed; "
                "project_id=%s season_id=%s episode_id=%s",
                project_id,
                season_id,
                episode_id,
                exc_info=True,
            )
            return (False, merge_usage)
        return (True, total_token_usage([merge_usage, summary_usage]))

    def _merge_episode_content_with_ai(
        self,
        project_id: str,
        manifest: dict[str, Any],
        season_id: str,
        episode_id: str,
        *,
        chunk_inputs: list[dict[str, Any]],
        episode_chunks: list[ChunkExtractionResult],
        previous_episode_id: str,
        extraction_run_id: str,
        backend: ModelBackend,
        model_name: str,
        base_url: str,
        api_key: str,
        context_window_tokens: int | None,
    ) -> dict[str, int]:
        if not episode_chunks:
            raise ValueError("episode AI merge requires at least one successful chunk")

        chunk_results = [chunk.model_dump(mode="json") for chunk in episode_chunks]
        expected_chunk_ids = [self._manifest_string(item.get("chunk_id")) for item in chunk_inputs]
        expected_chunk_ids = [item for item in expected_chunk_ids if item]
        successful_chunk_ids = {chunk.chunk_id for chunk in episode_chunks}
        missing_chunk_ids = [
            chunk_id for chunk_id in expected_chunk_ids if chunk_id not in successful_chunk_ids
        ]
        aggregation_warnings = [f"chunk_missing_or_failed:{chunk_id}" for chunk_id in missing_chunk_ids]
        source_metadata = {
            "season_id": season_id,
            "episode_id": episode_id,
            "expected_chunks": [
                {
                    "chunk_id": self._manifest_string(item.get("chunk_id")),
                    "source_path": self._manifest_string(item.get("source_path")),
                }
                for item in chunk_inputs
            ],
            "successful_chunk_ids": [chunk.chunk_id for chunk in episode_chunks],
            "missing_chunk_ids": missing_chunk_ids,
        }
        merge_context = self._build_formal_chunk_context_payload(
            project_id,
            manifest,
            {
                "season_id": season_id,
                "episode_id": episode_id,
            },
            current_episode_chunks=episode_chunks,
            previous_episode_id=previous_episode_id,
            extraction_run_id=extraction_run_id,
        )
        variables = {
            "season_id": season_id,
            "episode_id": episode_id,
            "source_metadata": source_metadata,
            "chunk_results": chunk_results,
            "current_season_completed_episodes": merge_context.get(
                "current_season_completed_episodes",
                [],
            ),
            "previous_season_backgrounds": merge_context.get("previous_season_backgrounds", []),
        }
        estimated_input_tokens = estimate_context_tokens(variables)
        requested_output_tokens = resolve_text_merge_output_tokens(
            FORMAL_EPISODE_CONTENT_MERGE,
            source_item_count=len(chunk_results),
            estimated_input_tokens=estimated_input_tokens,
            context_window_tokens=context_window_tokens,
            reserved_input_tokens=estimated_input_tokens,
        )
        budget_warning = text_merge_budget_warning(
            FORMAL_EPISODE_CONTENT_MERGE,
            requested_output_tokens=requested_output_tokens,
            context_window_tokens=context_window_tokens,
            reserved_input_tokens=estimated_input_tokens,
        )
        if budget_warning:
            aggregation_warnings.append(budget_warning)
        request = build_formal_text_json_request(
            purpose=FORMAL_EPISODE_CONTENT_MERGE,
            backend=backend,
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            variables=variables,
            max_tokens=requested_output_tokens,
            metadata={
                "project_id": project_id,
                "stage": "formal_episode_content_merge",
                "season_id": season_id,
                "episode_id": episode_id,
                "extraction_run_id": extraction_run_id,
                "context_policy": merge_context.get("context_policy", {}),
            },
        )
        result = call_formal_text_json_model(
            request,
            estimated_context_tokens=estimated_input_tokens,
        )
        payload = result.payload
        source_trace = self._source_trace_from_chunks(episode_chunks)
        episode_content = {
            "season_id": season_id,
            "episode_id": episode_id,
            "extraction_stage": kb.FULL_EXTRACTION_STAGE,
            "extraction_run_id": extraction_run_id,
            "run_type": FULL_EXTRACTION_RUN_TYPE,
            "source_kind": "video",
            "media_types": self._media_types_from_source_trace(source_trace),
            "schema_version": 1,
            "source_trace": source_trace,
            "source_counts": {
                "expected_chunks": len(expected_chunk_ids),
                "successful_chunks": len(chunk_results),
                "missing_chunks": len(missing_chunk_ids),
                "source_trace_units": len(source_trace.get("unit_refs", [])),
                "source_trace_materials": len(source_trace.get("material_refs", [])),
                "source_trace_derived_artifacts": len(
                    source_trace.get("derived_artifact_refs", [])
                ),
            },
            "context_policy": merge_context.get("context_policy", {}),
            "aggregation_warnings": aggregation_warnings
            + self._coerce_string_list(payload.get("aggregation_warnings")),
            "model_profile_id": model_name,
            "model_metadata": result.model_metadata,
            "token_usage": result.token_usage,
            "estimated_context_tokens": result.estimated_context_tokens,
            "requested_output_tokens": result.requested_output_tokens,
            "finish_reason": result.finish_reason,
            "episode_outline": str(payload.get("episode_outline", "")).strip(),
            "targets": self._coerce_string_list(payload.get("characters") or payload.get("targets")),
            "chunk_results": chunk_results,
            "facts": self._coerce_string_list(payload.get("facts")),
            "behavior_traits": self._coerce_string_list(payload.get("behavior_traits")),
            "dialogue_style": self._coerce_string_list(payload.get("dialogue_style")),
            "relationship_interactions": self._coerce_string_list(
                payload.get("relationship_interactions")
            ),
            "conflicts": self._coerce_string_list(payload.get("conflicts")),
            "character_state_changes": self._coerce_string_list(
                payload.get("character_state_changes")
            ),
            "uncertainties": self._coerce_string_list(payload.get("uncertainties")),
            "evidence_refs": self._coerce_string_list(payload.get("evidence_refs")),
            "chunk_refs": self._coerce_string_list(payload.get("chunk_refs")),
            "full_context_view": payload.get("full_context_view")
            if isinstance(payload.get("full_context_view"), dict)
            else {},
        }
        kb.save_episode_content(project_id, season_id, episode_id, episode_content)
        return result.token_usage

    def _generate_episode_summary_with_ai(
        self,
        project_id: str,
        season_id: str,
        episode_id: str,
        *,
        extraction_run_id: str,
        backend: ModelBackend,
        model_name: str,
        base_url: str,
        api_key: str,
        context_window_tokens: int | None,
    ) -> dict[str, int]:
        episode_content = kb.load_episode_content(project_id, season_id, episode_id)
        if not kb.is_full_artifact_payload_for_run(episode_content, extraction_run_id):
            raise ValueError("episode content does not match current extraction run")

        variables = {
            "season_id": season_id,
            "episode_id": episode_id,
            "episode_content": episode_content,
        }
        estimated_input_tokens = estimate_context_tokens(variables)
        requested_output_tokens = resolve_text_merge_output_tokens(
            FORMAL_EPISODE_SUMMARY,
            source_item_count=1,
            estimated_input_tokens=estimated_input_tokens,
            context_window_tokens=context_window_tokens,
            reserved_input_tokens=estimated_input_tokens,
        )
        aggregation_warnings = list(episode_content.get("aggregation_warnings", []))
        budget_warning = text_merge_budget_warning(
            FORMAL_EPISODE_SUMMARY,
            requested_output_tokens=requested_output_tokens,
            context_window_tokens=context_window_tokens,
            reserved_input_tokens=estimated_input_tokens,
        )
        if budget_warning:
            aggregation_warnings.append(budget_warning)
        request = build_formal_text_json_request(
            purpose=FORMAL_EPISODE_SUMMARY,
            backend=backend,
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            variables=variables,
            max_tokens=requested_output_tokens,
            metadata={
                "project_id": project_id,
                "stage": "formal_episode_summary",
                "season_id": season_id,
                "episode_id": episode_id,
                "extraction_run_id": extraction_run_id,
            },
        )
        result = call_formal_text_json_model(
            request,
            estimated_context_tokens=estimated_input_tokens,
        )
        payload = result.payload
        source_trace = self._source_trace_for_episode_summary(episode_content)
        source_counts = episode_content.get("source_counts", {})
        if not isinstance(source_counts, dict):
            source_counts = {}
        summary = {
            "season_id": season_id,
            "episode_id": episode_id,
            "extraction_stage": kb.FULL_EXTRACTION_STAGE,
            "extraction_run_id": extraction_run_id,
            "run_type": FULL_EXTRACTION_RUN_TYPE,
            "source_kind": "video",
            "media_types": self._media_types_from_source_trace(source_trace),
            "schema_version": 1,
            "source_trace": source_trace,
            "source_counts": {
                **source_counts,
                "source_trace_episode_contents": len(
                    source_trace.get("episode_content_refs", [])
                ),
                "source_trace_units": len(source_trace.get("unit_refs", [])),
                "source_trace_materials": len(source_trace.get("material_refs", [])),
                "source_trace_derived_artifacts": len(
                    source_trace.get("derived_artifact_refs", [])
                ),
            },
            "context_policy": episode_content.get("context_policy", {}),
            "aggregation_warnings": aggregation_warnings
            + self._coerce_string_list(payload.get("aggregation_warnings")),
            "model_profile_id": model_name,
            "model_metadata": result.model_metadata,
            "token_usage": result.token_usage,
            "requested_output_tokens": result.requested_output_tokens,
            "finish_reason": result.finish_reason,
            "character_summaries": self._coerce_string_list(
                payload.get("important_characters")
            ),
            "relationship_changes": self._coerce_string_list(
                payload.get("relationship_edges")
            ),
            "major_events": self._coerce_string_list(
                payload.get("major_events") or episode_content.get("facts")
            ),
            "open_conflicts": self._coerce_string_list(payload.get("open_threads")),
            "growth_signals": self._coerce_string_list(payload.get("continuity_hooks")),
            "insight_summary": str(
                payload.get("insight_summary") or episode_content.get("episode_outline") or ""
            ).strip(),
            "context_long": str(payload.get("context_long", "")).strip(),
            "context_brief": str(payload.get("context_brief", "")).strip(),
            "context_candidate": payload.get("context_candidate")
            if isinstance(payload.get("context_candidate"), dict)
            else {},
            "locations": self._coerce_string_list(payload.get("locations")),
            "organizations": self._coerce_string_list(payload.get("organizations")),
            "importance_score": payload.get("importance_score"),
        }
        summary["context_candidate"] = build_episode_context_candidate(episode_content, summary)
        summary["estimated_context_tokens"] = estimate_context_tokens(
            summary["context_candidate"]
        )
        kb.save_episode_summary(project_id, season_id, episode_id, summary)
        return result.token_usage

    def _finalize_formal_season_context(
        self,
        project_id: str,
        manifest: dict[str, Any],
        season_id: str,
        *,
        extraction_run_id: str,
        backend: ModelBackend,
        model_name: str,
        base_url: str,
        api_key: str,
        context_window_tokens: int | None,
        include_previous_season_backgrounds: bool = True,
    ) -> tuple[bool, dict[str, int]]:
        try:
            merge_usage = self._merge_season_content_with_ai(
                project_id,
                manifest,
                season_id,
                extraction_run_id=extraction_run_id,
                backend=backend,
                model_name=model_name,
                base_url=base_url,
                api_key=api_key,
                context_window_tokens=context_window_tokens,
                include_previous_season_backgrounds=include_previous_season_backgrounds,
            )
        except Exception:  # noqa: BLE001
            LOGGER.warning(
                "Formal season AI content merge failed; project_id=%s season_id=%s",
                project_id,
                season_id,
                exc_info=True,
            )
            return (False, {})

        try:
            summary_usage = self._generate_season_summary_with_ai(
                project_id,
                manifest,
                season_id,
                extraction_run_id=extraction_run_id,
                backend=backend,
                model_name=model_name,
                base_url=base_url,
                api_key=api_key,
                context_window_tokens=context_window_tokens,
                include_previous_season_backgrounds=include_previous_season_backgrounds,
            )
        except Exception:  # noqa: BLE001
            LOGGER.warning(
                "Formal season AI summary after AI merge failed; project_id=%s season_id=%s",
                project_id,
                season_id,
                exc_info=True,
            )
            return (False, merge_usage)
        return (True, total_token_usage([merge_usage, summary_usage]))

    def _merge_season_content_with_ai(
        self,
        project_id: str,
        manifest: dict[str, Any],
        season_id: str,
        *,
        extraction_run_id: str,
        backend: ModelBackend,
        model_name: str,
        base_url: str,
        api_key: str,
        context_window_tokens: int | None,
        include_previous_season_backgrounds: bool = True,
    ) -> dict[str, int]:
        episode_contents: list[dict[str, Any]] = []
        episode_summaries: list[dict[str, Any]] = []
        expected_episode_ids = self._season_episode_ids_from_manifest(manifest, season_id)
        missing_episode_ids: list[str] = []
        for episode_id in expected_episode_ids:
            try:
                episode_content = kb.load_episode_content(project_id, season_id, episode_id)
                episode_summary = kb.load_episode_summary(project_id, season_id, episode_id)
            except (OSError, ValueError, json.JSONDecodeError):
                missing_episode_ids.append(episode_id)
                continue
            if not kb.is_full_artifact_payload_for_run(episode_content, extraction_run_id):
                missing_episode_ids.append(episode_id)
                continue
            if not kb.is_full_artifact_payload_for_run(episode_summary, extraction_run_id):
                missing_episode_ids.append(episode_id)
                continue
            episode_contents.append(episode_content)
            episode_summaries.append(episode_summary)

        if not episode_contents:
            raise ValueError("season AI merge requires at least one completed episode")

        previous_season_backgrounds = (
            self._load_previous_season_backgrounds_for_run(
                project_id,
                manifest,
                season_id,
                extraction_run_id=extraction_run_id,
            )
            if include_previous_season_backgrounds
            else []
        )
        aggregation_warnings = [
            f"episode_missing_or_incomplete:{episode_id}" for episode_id in missing_episode_ids
        ]
        variables = {
            "season_id": season_id,
            "episode_contents": episode_contents,
            "episode_summaries": episode_summaries,
            "previous_season_backgrounds": previous_season_backgrounds,
        }
        estimated_input_tokens = estimate_context_tokens(variables)
        requested_output_tokens = resolve_text_merge_output_tokens(
            FORMAL_SEASON_CONTENT_MERGE,
            source_item_count=len(episode_contents),
            estimated_input_tokens=estimated_input_tokens,
            context_window_tokens=context_window_tokens,
            reserved_input_tokens=estimated_input_tokens,
        )
        budget_warning = text_merge_budget_warning(
            FORMAL_SEASON_CONTENT_MERGE,
            requested_output_tokens=requested_output_tokens,
            context_window_tokens=context_window_tokens,
            reserved_input_tokens=estimated_input_tokens,
        )
        if budget_warning:
            aggregation_warnings.append(budget_warning)
        request = build_formal_text_json_request(
            purpose=FORMAL_SEASON_CONTENT_MERGE,
            backend=backend,
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            variables=variables,
            max_tokens=requested_output_tokens,
            metadata={
                "project_id": project_id,
                "stage": "formal_season_content_merge",
                "season_id": season_id,
                "extraction_run_id": extraction_run_id,
            },
        )
        result = call_formal_text_json_model(
            request,
            estimated_context_tokens=estimated_input_tokens,
        )
        payload = result.payload
        source_trace = self._source_trace_for_season_content(
            episode_contents,
            episode_summaries=episode_summaries,
            previous_season_backgrounds=previous_season_backgrounds,
        )
        season_content = {
            "season_id": season_id,
            "extraction_stage": kb.FULL_EXTRACTION_STAGE,
            "extraction_run_id": extraction_run_id,
            "run_type": FULL_EXTRACTION_RUN_TYPE,
            "source_kind": "video",
            "media_types": self._media_types_from_source_trace(source_trace),
            "schema_version": 1,
            "source_trace": source_trace,
            "source_counts": {
                "expected_episodes": len(expected_episode_ids),
                "completed_episodes": len(episode_contents),
                "missing_episodes": len(missing_episode_ids),
                "previous_season_backgrounds": len(previous_season_backgrounds),
                "source_trace_episode_contents": len(
                    source_trace.get("episode_content_refs", [])
                ),
                "source_trace_episode_summaries": len(
                    source_trace.get("episode_summary_refs", [])
                ),
                "source_trace_previous_season_summaries": len(
                    source_trace.get("previous_season_summary_refs", [])
                ),
                "source_trace_units": len(source_trace.get("unit_refs", [])),
                "source_trace_materials": len(source_trace.get("material_refs", [])),
                "source_trace_derived_artifacts": len(
                    source_trace.get("derived_artifact_refs", [])
                ),
            },
            "aggregation_warnings": aggregation_warnings
            + self._coerce_string_list(payload.get("aggregation_warnings")),
            "model_profile_id": model_name,
            "model_metadata": result.model_metadata,
            "token_usage": result.token_usage,
            "estimated_context_tokens": result.estimated_context_tokens,
            "requested_output_tokens": result.requested_output_tokens,
            "finish_reason": result.finish_reason,
            "episode_contents": episode_contents,
            "episode_summaries": episode_summaries,
            "season_outline": str(payload.get("season_outline", "")).strip(),
            "targets": self._coerce_string_list(
                payload.get("major_characters") or payload.get("targets")
            ),
            "character_arcs": self._coerce_string_list(payload.get("character_arcs")),
            "facts": self._coerce_string_list(payload.get("major_events")),
            "behavior_traits": self._coerce_string_list(payload.get("character_arcs")),
            "dialogue_style": self._coerce_string_list(payload.get("dialogue_style")),
            "relationship_interactions": self._coerce_string_list(
                payload.get("relationship_map")
            ),
            "conflicts": self._coerce_string_list(
                payload.get("major_conflicts") or payload.get("unresolved_threads")
            ),
            "character_state_changes": self._coerce_string_list(
                payload.get("final_character_states") or payload.get("character_arcs")
            ),
            "unresolved_threads": self._coerce_string_list(payload.get("unresolved_threads")),
            "world_context": payload.get("world_context"),
            "episode_refs": self._coerce_string_list(payload.get("episode_refs")),
            "evidence_refs": self._coerce_string_list(payload.get("evidence_refs")),
        }
        kb.save_season_content(project_id, season_id, season_content)
        return result.token_usage

    def _generate_season_summary_with_ai(
        self,
        project_id: str,
        manifest: dict[str, Any],
        season_id: str,
        *,
        extraction_run_id: str,
        backend: ModelBackend,
        model_name: str,
        base_url: str,
        api_key: str,
        context_window_tokens: int | None,
        include_previous_season_backgrounds: bool = True,
    ) -> dict[str, int]:
        season_content = kb.load_season_content(project_id, season_id)
        if not kb.is_full_artifact_payload_for_run(season_content, extraction_run_id):
            raise ValueError("season content does not match current extraction run")

        previous_series_background = (
            self._load_previous_season_backgrounds_for_run(
                project_id,
                manifest,
                season_id,
                extraction_run_id=extraction_run_id,
            )
            if include_previous_season_backgrounds
            else []
        )
        variables = {
            "season_id": season_id,
            "season_content": season_content,
            "previous_series_background": previous_series_background,
        }
        estimated_input_tokens = estimate_context_tokens(variables)
        requested_output_tokens = resolve_text_merge_output_tokens(
            FORMAL_SEASON_SUMMARY,
            source_item_count=1,
            estimated_input_tokens=estimated_input_tokens,
            context_window_tokens=context_window_tokens,
            reserved_input_tokens=estimated_input_tokens,
        )
        aggregation_warnings = list(season_content.get("aggregation_warnings", []))
        budget_warning = text_merge_budget_warning(
            FORMAL_SEASON_SUMMARY,
            requested_output_tokens=requested_output_tokens,
            context_window_tokens=context_window_tokens,
            reserved_input_tokens=estimated_input_tokens,
        )
        if budget_warning:
            aggregation_warnings.append(budget_warning)
        request = build_formal_text_json_request(
            purpose=FORMAL_SEASON_SUMMARY,
            backend=backend,
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            variables=variables,
            max_tokens=requested_output_tokens,
            metadata={
                "project_id": project_id,
                "stage": "formal_season_summary",
                "season_id": season_id,
                "extraction_run_id": extraction_run_id,
                "previous_series_background_count": len(previous_series_background),
            },
        )
        result = call_formal_text_json_model(
            request,
            estimated_context_tokens=estimated_input_tokens,
        )
        payload = result.payload
        source_counts = season_content.get("source_counts", {})
        if not isinstance(source_counts, dict):
            source_counts = {}
        episode_summaries = [
            item for item in season_content.get("episode_summaries", []) if isinstance(item, dict)
        ]
        source_trace = self._source_trace_for_season_summary(
            season_content,
            episode_summaries=episode_summaries,
            previous_season_backgrounds=previous_series_background,
        )
        summary = {
            "season_id": season_id,
            "extraction_stage": kb.FULL_EXTRACTION_STAGE,
            "extraction_run_id": extraction_run_id,
            "run_type": FULL_EXTRACTION_RUN_TYPE,
            "source_kind": "video",
            "media_types": self._media_types_from_source_trace(source_trace),
            "schema_version": 1,
            "source_trace": source_trace,
            "source_counts": {
                **source_counts,
                "previous_series_backgrounds": len(previous_series_background),
                "source_trace_season_contents": len(
                    source_trace.get("season_content_refs", [])
                ),
                "source_trace_episode_summaries": len(
                    source_trace.get("episode_summary_refs", [])
                ),
                "source_trace_previous_season_summaries": len(
                    source_trace.get("previous_season_summary_refs", [])
                ),
                "source_trace_units": len(source_trace.get("unit_refs", [])),
                "source_trace_materials": len(source_trace.get("material_refs", [])),
                "source_trace_derived_artifacts": len(
                    source_trace.get("derived_artifact_refs", [])
                ),
            },
            "aggregation_warnings": aggregation_warnings
            + self._coerce_string_list(payload.get("aggregation_warnings")),
            "model_profile_id": model_name,
            "model_metadata": result.model_metadata,
            "token_usage": result.token_usage,
            "estimated_context_tokens": result.estimated_context_tokens,
            "requested_output_tokens": result.requested_output_tokens,
            "finish_reason": result.finish_reason,
            "final_character_states": self._coerce_string_list(
                payload.get("final_character_states")
            ),
            "relationship_baseline": self._coerce_string_list(
                payload.get("relationship_baseline")
            ),
            "major_conflicts": self._coerce_string_list(payload.get("major_conflicts")),
            "unresolved_threads": self._coerce_string_list(payload.get("unresolved_threads")),
            "growth_trajectory": self._coerce_string_list(
                payload.get("growth_trajectory")
                or payload.get("final_character_states")
                or season_content.get("character_arcs")
            ),
            "background_summary": str(
                payload.get("context_long")
                or payload.get("background_summary")
                or season_content.get("season_outline")
                or ""
            ).strip(),
            "series_background_summary": str(
                payload.get("series_background_summary")
                or payload.get("context_long")
                or ""
            ).strip(),
            "context_long": str(payload.get("context_long", "")).strip(),
            "context_brief": str(payload.get("context_brief", "")).strip(),
            "major_characters": self._coerce_string_list(payload.get("major_characters")),
            "world_context": payload.get("world_context"),
            "uncertainties": self._coerce_string_list(payload.get("uncertainties")),
        }
        kb.save_season_summary(project_id, season_id, summary)
        return result.token_usage

    def _collect_formal_episode_ids_from_manifest(self, manifest: dict[str, Any]) -> list[tuple[str, str]]:
        episode_ids: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for season in manifest.get("seasons", []):
            if not isinstance(season, dict):
                continue
            season_id = self._manifest_string(season.get("season_id"))
            if not season_id:
                continue
            for episode in season.get("episodes", []):
                if not isinstance(episode, dict):
                    continue
                episode_id = self._manifest_string(episode.get("episode_id"))
                key = (season_id, episode_id)
                if episode_id and key not in seen:
                    seen.add(key)
                    episode_ids.append(key)
        return episode_ids

    def _season_episode_ids_from_manifest(
        self,
        manifest: dict[str, Any],
        season_id: str,
    ) -> list[str]:
        episode_ids: list[str] = []
        seen: set[str] = set()
        for season in manifest.get("seasons", []):
            if not isinstance(season, dict):
                continue
            if self._manifest_string(season.get("season_id")) != season_id:
                continue
            for episode in season.get("episodes", []):
                if not isinstance(episode, dict):
                    continue
                episode_id = self._manifest_string(episode.get("episode_id"))
                if episode_id and episode_id not in seen:
                    seen.add(episode_id)
                    episode_ids.append(episode_id)
            break
        return episode_ids

    def _season_ids_from_manifest(self, manifest: dict[str, Any]) -> list[str]:
        season_ids: list[str] = []
        seen: set[str] = set()
        for season in manifest.get("seasons", []):
            if not isinstance(season, dict):
                continue
            season_id = self._manifest_string(season.get("season_id"))
            if season_id and season_id not in seen:
                seen.add(season_id)
                season_ids.append(season_id)
        return season_ids

    def transcribe_episode_audio(
        self,
        project_id: str,
        season_id: str,
        episode_id: str,
        material_paths: Path | str | list[Path | str],
        *,
        language: str = "auto",
        force_rebuild: bool = False,
    ) -> EpisodeTranscript:
        return run_episode_audio_transcription(
            project_id,
            season_id,
            episode_id,
            material_paths,
            options=TranscriptionOptions(language=language, force_rebuild=force_rebuild),
        )

    def ensure_episode_transcripts_from_manifest(
        self,
        project_id: str,
        manifest: dict[str, Any],
        *,
        language: str = "auto",
        force_rebuild: bool = False,
        emit_event: Callable[[dict], None] | None = None,
    ) -> list[EpisodeTranscript]:
        transcripts: list[EpisodeTranscript] = []
        episode_inputs = self._collect_formal_episode_transcript_inputs(project_id, manifest)
        total = len(episode_inputs)
        for index, episode_input in enumerate(episode_inputs, start=1):
            season_id = episode_input["season_id"]
            episode_id = episode_input["episode_id"]
            material_paths = episode_input["material_paths"]
            if emit_event is not None:
                emit_event(
                    InsightEvent(
                        title=t("extractor.transcript.title"),
                        description=t(
                            "extractor.transcript.transcribing",
                            current=index,
                            total=total,
                            episode=episode_id,
                        ),
                        status=InsightStatus.RUNNING,
                    ).model_dump(mode="json")
                )
            try:
                transcript = run_episode_audio_transcription(
                    project_id,
                    season_id,
                    episode_id,
                    material_paths,
                    options=TranscriptionOptions(
                        language=language,
                        force_rebuild=force_rebuild,
                    ),
                )
            except AudioTranscriptionError as exc:
                LOGGER.warning(
                    "Episode transcription failed; project_id=%s season_id=%s episode_id=%s error=%s",
                    project_id,
                    season_id,
                    episode_id,
                    self._compact_exception_message(exc),
                )
                if emit_event is not None:
                    emit_event(
                        InsightEvent(
                            title=t("extractor.transcript.title"),
                            description=t(
                                "extractor.transcript.failed",
                                episode=episode_id,
                                error=self._compact_exception_message(exc),
                            ),
                            status=InsightStatus.WARNING,
                        ).model_dump(mode="json")
                    )
                continue
            transcripts.append(transcript)
            if emit_event is not None:
                emit_event(
                    InsightEvent(
                        title=t("extractor.transcript.title"),
                        description=t(
                            "extractor.transcript.ready",
                            episode=episode_id,
                            count=len(transcript.segments),
                        ),
                        status=InsightStatus.DONE,
                    ).model_dump(mode="json")
                )
        return transcripts

    def ensure_episode_transcripts_from_run_plan(
        self,
        project_id: str,
        run_plan: FormalExtractionRunPlan,
        *,
        language: str = "auto",
        force_rebuild: bool = False,
        emit_event: Callable[[dict], None] | None = None,
    ) -> list[EpisodeTranscript]:
        provider = TranscriptProvider()
        provider.prepare_run_plan(project_id, run_plan)
        kb.save_extraction_run_plan(project_id, run_plan)
        requests = provider.collect_requests(project_id, run_plan)
        transcripts: list[EpisodeTranscript] = []
        total = len(requests)
        for index, request in enumerate(requests, start=1):
            if not request.material_paths:
                provider.mark_status(
                    run_plan,
                    request.artifact_id,
                    DerivedArtifactStatus.MISSING,
                    warning="no_material_paths",
                )
                continue
            self._emit_transcript_event(emit_event, request, index, total, InsightStatus.RUNNING)
            try:
                transcript = provider.ensure_transcript(
                    project_id,
                    request,
                    language=language,
                    force_rebuild=force_rebuild,
                )
            except AudioTranscriptionError as exc:
                warning = self._compact_exception_message(exc)
                provider.mark_status(
                    run_plan,
                    request.artifact_id,
                    DerivedArtifactStatus.FAILED,
                    warning=warning,
                )
                LOGGER.warning(
                    "Episode transcription failed; project_id=%s season_id=%s episode_id=%s error=%s",
                    project_id,
                    request.season_id,
                    request.episode_id,
                    warning,
                )
                if emit_event is not None:
                    emit_event(
                        InsightEvent(
                            title=t("extractor.transcript.title"),
                            description=t(
                                "extractor.transcript.failed",
                                episode=request.episode_id,
                                error=warning,
                            ),
                            status=InsightStatus.WARNING,
                        ).model_dump(mode="json")
                    )
                continue
            provider.mark_status(run_plan, request.artifact_id, DerivedArtifactStatus.READY)
            transcripts.append(transcript)
            self._emit_transcript_event(
                emit_event,
                request,
                index,
                total,
                InsightStatus.DONE,
                segment_count=len(transcript.segments),
            )
        kb.save_extraction_run_plan(project_id, run_plan)
        return transcripts

    def _emit_transcript_event(
        self,
        emit_event: Callable[[dict], None] | None,
        request: TranscriptArtifactRequest,
        index: int,
        total: int,
        status: InsightStatus,
        *,
        segment_count: int = 0,
    ) -> None:
        if emit_event is None:
            return
        if status == InsightStatus.DONE:
            description = t(
                "extractor.transcript.ready",
                episode=request.episode_id,
                count=segment_count,
            )
        else:
            description = t(
                "extractor.transcript.transcribing",
                current=index,
                total=total,
                episode=request.episode_id,
            )
        emit_event(
            InsightEvent(
                title=t("extractor.transcript.title"),
                description=description,
                status=status,
                meta={"artifact_id": request.artifact_id, "artifact_path": request.artifact_path},
            ).model_dump(mode="json")
        )

    def _collect_formal_episode_transcript_inputs(
        self,
        project_id: str,
        manifest: dict[str, Any],
    ) -> list[dict[str, Any]]:
        episode_inputs: list[dict[str, Any]] = []
        for season in manifest.get("seasons", []):
            if not isinstance(season, dict):
                continue
            season_id = self._manifest_string(season.get("season_id"))
            if not season_id:
                continue
            for episode in season.get("episodes", []):
                if not isinstance(episode, dict):
                    continue
                episode_id = self._manifest_string(episode.get("episode_id"))
                if not episode_id:
                    continue
                material_paths = self._episode_material_paths(project_id, episode)
                if material_paths:
                    episode_inputs.append(
                        {
                            "season_id": season_id,
                            "episode_id": episode_id,
                            "material_paths": material_paths,
                        }
                    )
        return episode_inputs

    def _episode_material_paths(self, project_id: str, episode: dict[str, Any]) -> list[Path]:
        material_paths: list[Path] = []
        for chunk in episode.get("chunks", []):
            if not isinstance(chunk, dict):
                continue
            source_path = self._manifest_string(chunk.get("source_path"))
            if not source_path:
                continue
            material_path = self._formal_material_video_path(project_id, source_path)
            if material_path.is_file():
                material_paths.append(material_path)
        if material_paths:
            return material_paths

        source_path = self._manifest_string(episode.get("source_path"))
        if not source_path:
            return []
        material_path = self._formal_material_video_path(project_id, source_path)
        return [material_path] if material_path.is_file() else []

    def _collect_formal_season_ids_from_manifest(self, manifest: dict[str, Any]) -> list[str]:
        season_ids: list[str] = []
        seen: set[str] = set()
        for season in manifest.get("seasons", []):
            if not isinstance(season, dict):
                continue
            season_id = self._manifest_string(season.get("season_id"))
            if season_id and season_id not in seen:
                seen.add(season_id)
                season_ids.append(season_id)
        return season_ids

    def _aggregate_full_outputs_from_manifest(self, project_id: str, manifest: dict[str, Any]) -> list[Path]:
        written_paths: list[Path] = []
        extraction_run_id = self._manifest_string(manifest.get("extraction_run_id"))
        for season_id, episode_id in self._collect_formal_episode_ids_from_manifest(manifest):
            try:
                written_paths.append(
                    self.merge_episode_content(
                        project_id,
                        season_id,
                        episode_id,
                        extraction_run_id=extraction_run_id,
                    )
                )
                written_paths.append(
                    self.generate_episode_summary(
                        project_id,
                        season_id,
                        episode_id,
                        extraction_run_id=extraction_run_id,
                    )
                )
            except Exception:  # noqa: BLE001
                LOGGER.warning(
                    "Full episode aggregation failed; project_id=%s season_id=%s episode_id=%s",
                    project_id,
                    season_id,
                    episode_id,
                    exc_info=True,
                )
                continue

        for season_id in self._collect_formal_season_ids_from_manifest(manifest):
            try:
                written_paths.append(
                    self.merge_season_content(
                        project_id,
                        season_id,
                        extraction_run_id=extraction_run_id,
                    )
                )
                written_paths.append(
                    self.generate_season_summary(
                        project_id,
                        season_id,
                        extraction_run_id=extraction_run_id,
                    )
                )
            except Exception:  # noqa: BLE001
                LOGGER.warning(
                    "Full season aggregation failed; project_id=%s season_id=%s",
                    project_id,
                    season_id,
                    exc_info=True,
                )
                continue
        return written_paths

    def _formal_material_video_path(self, project_id: str, source_path: str) -> Path:
        path = Path(source_path)
        if path.is_absolute():
            return path
        return ensure_project_tree(project_id).materials / path

    def _manifest_string(self, value: Any) -> str:
        return value.strip() if isinstance(value, str) else ""

    def _empty_full_extraction_stats(self, *, total_chunks: int = 0) -> dict[str, int]:
        return {
            "total_chunks": total_chunks,
            "succeeded_chunks": 0,
            "skipped_chunks": 0,
            "failed_chunks": 0,
            "succeeded_episodes": 0,
            "skipped_episodes": 0,
            "failed_episodes": 0,
            "succeeded_seasons": 0,
            "skipped_seasons": 0,
            "failed_seasons": 0,
            "stale_cards": 0,
        }

    def _normalize_fast_concurrency(self, concurrency: int | None) -> int:
        try:
            value = int(concurrency or 1)
        except (TypeError, ValueError):
            value = 1
        return max(1, min(500, value))

    def _extract_fast_video_units(
        self,
        config: ProjectConfig,
        manifest: dict[str, Any],
        *,
        chunk_inputs: list[dict[str, Any]],
        concurrency: int = 1,
        backend: ModelBackend,
        provider: str,
        model_name: str,
        base_url: str,
        api_key: str,
        video_fps: float,
        max_output_tokens: int,
        video_input_mode: VideoInputMode,
        run_plan: FormalExtractionRunPlan,
        progress_base: int = 5,
        progress_span: int = 90,
        emit_token_usage: Callable[[dict[str, int]], None] | None = None,
        emit_event: Callable[[dict], None] | None = None,
        emit_progress: Callable[[int], None] | None = None,
    ) -> tuple[int, dict[str, int], list[ChunkExtractionResult], dict[str, int]]:
        stats = self._empty_full_extraction_stats(total_chunks=len(chunk_inputs))
        if not chunk_inputs:
            return (0, {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}, [], stats)

        video_handler = self._video_unit_handler(
            provider=provider,
            video_fps=video_fps,
            video_input_mode=video_input_mode,
            max_output_tokens=max_output_tokens,
        )
        total_chunks = len(chunk_inputs)
        normalized_concurrency = self._normalize_fast_concurrency(concurrency)
        worker_count = min(normalized_concurrency, total_chunks)
        usage_total = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        extracted_chunks_with_index: list[tuple[int, ChunkExtractionResult]] = []
        transcripts_by_episode: dict[tuple[str, str], EpisodeTranscript] = {}
        if video_handler.requires_transcript():
            transcripts = self.ensure_episode_transcripts_from_run_plan(
                config.project_id,
                run_plan,
                emit_event=emit_event,
            )
            transcripts_by_episode = {
                (transcript.source.season_id, transcript.source.episode_id): transcript
                for transcript in transcripts
            }
            if not transcripts_by_episode:
                message = t("extractor.transcript.requiredUnavailable")
                self._emit_full_warning(emit_event, message)
                raise ValueError(message)

        LOGGER.info(
            "Fast extraction chunk pool started; project_id=%s total_chunks=%s concurrency=%s",
            config.project_id,
            total_chunks,
            worker_count,
        )

        def extract_one(index: int, chunk_input: dict[str, Any]) -> dict[str, Any]:
            video_path = chunk_input["video_path"]
            source_path = chunk_input["source_path"]
            duration_seconds = 0.0
            request_max_output_tokens = max_output_tokens
            try:
                if not video_path.exists() or not video_path.is_file():
                    self._emit_full_warning(
                        emit_event,
                        t("extractor.full.chunkMissing", path=source_path),
                    )
                    return {"index": index, "status": "skipped"}

                budget = video_handler.prepare_budget(video_path)
                duration_seconds = budget.duration_seconds
                request_max_output_tokens = budget.request_max_output_tokens
                if max_output_tokens < FULL_EXTRACTION_MIN_OUTPUT_TOKENS_PER_MINUTE:
                    LOGGER.warning(
                        "Fast extraction chunk output token budget is too small; "
                        "project_id=%s chunk=%s duration_seconds=%.2f request_max_tokens=%s "
                        "minimum_tokens_per_minute=%s tokens_per_minute=%s; continuing with low budget",
                        config.project_id,
                        source_path,
                        duration_seconds,
                        request_max_output_tokens,
                        FULL_EXTRACTION_MIN_OUTPUT_TOKENS_PER_MINUTE,
                        max_output_tokens,
                    )
                LOGGER.info(
                    "Fast extraction chunk video request prepared; "
                    "project_id=%s season_id=%s episode_id=%s chunk_id=%s "
                    "size_mb=%.2f duration_seconds=%.2f tokens_per_minute=%s request_max_tokens=%s",
                    config.project_id,
                    chunk_input["season_id"],
                    chunk_input["episode_id"],
                    chunk_input["chunk_id"],
                    video_path.stat().st_size / (1024 * 1024),
                    duration_seconds,
                    max_output_tokens,
                    request_max_output_tokens,
                )
                if emit_event is not None:
                    emit_event(
                        InsightEvent(
                            title=t("extractor.full.chunk.title"),
                            description=t(
                                "extractor.full.chunk.extractingVideoChunk",
                                current=index,
                                total=total_chunks,
                                name=video_path.name,
                            ),
                            status=InsightStatus.RUNNING,
                            meta={"mode": ExtractionMode.FAST.value},
                        ).model_dump(mode="json")
                    )

                transcript_context = ""
                if video_handler.requires_transcript():
                    transcript = transcripts_by_episode.get(
                        (chunk_input["season_id"], chunk_input["episode_id"])
                    )
                    if transcript is not None:
                        transcript_context = transcript_segments_for_material(
                            transcript,
                            video_path,
                            max_chars=4000,
                        )
                    if not transcript_context.strip():
                        self._emit_full_warning(
                            emit_event,
                            t(
                                "extractor.transcript.chunkMissing",
                                episode=chunk_input["episode_id"],
                                chunk=chunk_input["chunk_id"],
                            ),
                        )
                        return {"index": index, "status": "skipped"}

                fast_context = {
                    "context_policy": {
                        "mode": ExtractionMode.FAST.value,
                        "context_injection": "disabled",
                        "reason": "fast_parallel_chunk_extraction",
                    }
                }
                request = video_handler.build_formal_chunk_request(
                    project_id=config.project_id,
                    chunk_input=chunk_input,
                    backend=backend,
                    model_name=model_name,
                    base_url=base_url,
                    api_key=api_key,
                    request_max_output_tokens=request_max_output_tokens,
                    transcript_context=transcript_context,
                    formal_context=fast_context,
                )
                formal_result = call_formal_json_model(request, call_model=call_video_model)
                payload = formal_result.payload
                chunk = ChunkExtractionResult(
                    season_id=chunk_input["season_id"],
                    episode_id=chunk_input["episode_id"],
                    chunk_id=chunk_input["chunk_id"],
                    extraction_stage=ExtractionArtifactStage.FULL,
                    extraction_run_id=self._manifest_string(chunk_input.get("extraction_run_id")),
                    run_type=FULL_EXTRACTION_RUN_TYPE,
                    source_path=source_path,
                    source_kind="video",
                    source_trace=self._source_trace_from_chunk_input(chunk_input),
                    source_counts={
                        "current_episode_extracted_chunks": 0,
                        "selected_episode_contexts": 0,
                        "previous_season_backgrounds": 0,
                    },
                    context_policy=fast_context["context_policy"],
                    model_metadata=formal_result.model_metadata,
                    token_usage=formal_result.token_usage,
                    estimated_context_tokens=formal_result.estimated_context_tokens,
                    requested_output_tokens=formal_result.requested_output_tokens,
                    finish_reason=formal_result.finish_reason,
                    targets=[],
                    facts=self._coerce_string_list(payload.get("facts")),
                    behavior_traits=self._coerce_string_list(payload.get("behavior_traits")),
                    dialogue_style=self._coerce_string_list(payload.get("dialogue_style")),
                    relationship_interactions=self._coerce_string_list(payload.get("relationships")),
                    conflicts=self._coerce_string_list(payload.get("conflicts")),
                    character_state_changes=self._coerce_string_list(
                        payload.get("character_state_changes")
                    ),
                    insight_summary=str(payload.get("insight_summary", "")).strip(),
                    evidence_refs=self._coerce_string_list(payload.get("evidence_refs")),
                )
                self.save_chunk_extraction_result(config.project_id, chunk)
                if emit_event is not None:
                    emit_event(
                        InsightEvent(
                            title=t("extractor.full.chunk.title"),
                            description=t(
                                "extractor.full.chunk.saved",
                                current=index,
                                total=total_chunks,
                                name=video_path.name,
                            ),
                            status=InsightStatus.DONE,
                            meta={
                                "stream_id": f"fast_chunk_{index}",
                                "mode": ExtractionMode.FAST.value,
                                "season_id": chunk.season_id,
                                "episode_id": chunk.episode_id,
                                "chunk_id": chunk.chunk_id,
                            },
                        ).model_dump(mode="json")
                    )
                return {
                    "index": index,
                    "status": "succeeded",
                    "chunk": chunk,
                    "usage": formal_result.token_usage,
                }
            except FormalExtractionOutputTruncatedError as exc:
                LOGGER.warning(
                    "Fast chunk model response skipped because output was truncated; "
                    "project_id=%s source_path=%s request_max_tokens=%s attempts=%s",
                    config.project_id,
                    source_path,
                    request_max_output_tokens,
                    exc.attempts,
                )
                self._emit_full_warning(
                    emit_event,
                    self._output_token_limit_message(
                        video_name=video_path.name,
                        request_max_output_tokens=request_max_output_tokens,
                        duration_seconds=duration_seconds,
                    ),
                )
                return {"index": index, "status": "failed"}
            except FormalExtractionJsonError as exc:
                LOGGER.warning(
                    "Fast extraction chunk JSON retry failed; "
                    "project_id=%s season_id=%s episode_id=%s chunk_id=%s source_path=%s "
                    "attempts=%s error=%s",
                    config.project_id,
                    chunk_input["season_id"],
                    chunk_input["episode_id"],
                    chunk_input["chunk_id"],
                    source_path,
                    exc.attempts,
                    self._compact_exception_message(exc),
                )
                self._emit_full_event(
                    emit_event,
                    description=self._full_video_chunk_failed_description(
                        exc=exc,
                        index=index,
                        total=total_chunks,
                        video_name=video_path.name,
                    ),
                    status=InsightStatus.WARNING,
                )
                return {"index": index, "status": "failed"}
            except ModelCallError as exc:
                error_kind = (
                    "provider_data_inspection_failed"
                    if self._provider_rejected_video(exc)
                    else "model_call_failed"
                )
                status = (
                    "skipped"
                    if self._provider_rejected_video(exc)
                    and config.allow_provider_rejected_chunk_skip
                    else "failed"
                )
                LOGGER.warning(
                    "Fast extraction chunk completed with model service error; "
                    "project_id=%s season_id=%s episode_id=%s chunk_id=%s source_path=%s "
                    "status=%s error_kind=%s error=%s",
                    config.project_id,
                    chunk_input["season_id"],
                    chunk_input["episode_id"],
                    chunk_input["chunk_id"],
                    source_path,
                    status,
                    error_kind,
                    self._compact_exception_message(exc),
                )
                self._emit_full_event(
                    emit_event,
                    description=self._full_video_chunk_failed_description(
                        exc=exc,
                        index=index,
                        total=total_chunks,
                        video_name=video_path.name,
                    ),
                    status=InsightStatus.WARNING,
                )
                return {"index": index, "status": status}
            except Exception as exc:  # noqa: BLE001
                LOGGER.error(
                    "Fast extraction chunk failed; project_id=%s source_path=%s",
                    config.project_id,
                    source_path,
                    exc_info=True,
                )
                self._emit_full_event(
                    emit_event,
                    description=self._full_video_chunk_failed_description(
                        exc=exc,
                        index=index,
                        total=total_chunks,
                        video_name=video_path.name,
                    ),
                    status=InsightStatus.WARNING,
                )
                return {"index": index, "status": "failed"}

        processed = 0
        futures: dict[Any, tuple[int, dict[str, Any]]] = {}
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            for index, chunk_input in enumerate(chunk_inputs, start=1):
                futures[executor.submit(extract_one, index, chunk_input)] = (index, chunk_input)
            for future in as_completed(futures):
                index, chunk_input = futures[future]
                try:
                    result = future.result()
                except Exception:  # noqa: BLE001
                    LOGGER.error(
                        "Fast extraction worker failed unexpectedly; "
                        "project_id=%s season_id=%s episode_id=%s chunk_id=%s",
                        config.project_id,
                        chunk_input.get("season_id"),
                        chunk_input.get("episode_id"),
                        chunk_input.get("chunk_id"),
                        exc_info=True,
                    )
                    self._emit_full_event(
                        emit_event,
                        description=t(
                            "extractor.full.chunk.videoChunkFailed",
                            current=index,
                            total=total_chunks,
                            name=Path(str(chunk_input.get("video_path", ""))).name,
                        ),
                        status=InsightStatus.WARNING,
                    )
                    result = {"index": index, "status": "failed"}

                status = result.get("status")
                if status == "succeeded":
                    chunk = result.get("chunk")
                    if isinstance(chunk, ChunkExtractionResult):
                        extracted_chunks_with_index.append((index, chunk))
                        stats["succeeded_chunks"] += 1
                    else:
                        stats["failed_chunks"] += 1
                    token_usage = result.get("usage")
                    if isinstance(token_usage, dict):
                        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                            value = token_usage.get(key)
                            if isinstance(value, int):
                                usage_total[key] += value
                    if emit_token_usage is not None and any(usage_total.values()):
                        emit_token_usage(usage_total)
                elif status == "skipped":
                    stats["skipped_chunks"] += 1
                else:
                    stats["failed_chunks"] += 1

                processed += 1
                if emit_progress is not None:
                    emit_progress(progress_base + int(processed * progress_span / total_chunks))

        extracted_chunks = [
            chunk for _index, chunk in sorted(extracted_chunks_with_index, key=lambda item: item[0])
        ]
        return (len(extracted_chunks), usage_total, extracted_chunks, stats)

    def _finalize_fast_episode_contexts_from_chunks(
        self,
        config: ProjectConfig,
        manifest: dict[str, Any],
        *,
        chunk_inputs: list[dict[str, Any]],
        extracted_chunks: list[ChunkExtractionResult],
        concurrency: int,
        backend: ModelBackend,
        model_name: str,
        base_url: str,
        api_key: str,
        context_window_tokens: int | None,
        base_usage: dict[str, int] | None = None,
        progress_base: int = 80,
        progress_span: int = 10,
        emit_token_usage: Callable[[dict[str, int]], None] | None = None,
        emit_event: Callable[[dict], None] | None = None,
        emit_progress: Callable[[int], None] | None = None,
    ) -> tuple[dict[str, int], dict[str, int]]:
        episode_groups = self._group_formal_video_chunk_inputs_by_episode(chunk_inputs)
        episode_groups = [
            group
            for group in episode_groups
            if self._manifest_string(group.get("season_id"))
            and self._manifest_string(group.get("episode_id"))
        ]
        usage_total = {
            "prompt_tokens": int((base_usage or {}).get("prompt_tokens", 0)),
            "completion_tokens": int((base_usage or {}).get("completion_tokens", 0)),
            "total_tokens": int((base_usage or {}).get("total_tokens", 0)),
        }
        stats = {"succeeded_episodes": 0, "skipped_episodes": 0, "failed_episodes": 0}
        if not episode_groups:
            return (usage_total, stats)

        chunks_by_episode: dict[tuple[str, str], list[ChunkExtractionResult]] = {}
        for chunk in extracted_chunks:
            chunks_by_episode.setdefault((chunk.season_id, chunk.episode_id), []).append(chunk)
        order_by_chunk_key = {
            (
                self._manifest_string(item.get("season_id")),
                self._manifest_string(item.get("episode_id")),
                self._manifest_string(item.get("chunk_id")),
            ): index
            for index, item in enumerate(chunk_inputs)
        }
        for chunks in chunks_by_episode.values():
            chunks.sort(
                key=lambda chunk: order_by_chunk_key.get(
                    (chunk.season_id, chunk.episode_id, chunk.chunk_id),
                    len(order_by_chunk_key),
                )
            )

        total_episodes = len(episode_groups)
        worker_count = min(self._normalize_fast_concurrency(concurrency), total_episodes)
        extraction_run_id = self._manifest_string(manifest.get("extraction_run_id"))
        LOGGER.info(
            "Fast extraction episode merge pool started; project_id=%s total_episodes=%s concurrency=%s",
            config.project_id,
            total_episodes,
            worker_count,
        )

        def finalize_one(index: int, episode_group: dict[str, Any]) -> dict[str, Any]:
            season_id = self._manifest_string(episode_group.get("season_id"))
            episode_id = self._manifest_string(episode_group.get("episode_id"))
            episode_label = f"{season_id}/{episode_id}"
            episode_chunks = chunks_by_episode.get((season_id, episode_id), [])
            if not episode_chunks:
                self._emit_full_event(
                    emit_event,
                    title=t("extractor.fast.episode.title"),
                    description=t("extractor.fast.episode.skipped", episode=episode_label),
                    status=InsightStatus.WARNING,
                    meta={
                        "mode": ExtractionMode.FAST.value,
                        "season_id": season_id,
                        "episode_id": episode_id,
                    },
                )
                return {"index": index, "status": "skipped"}

            self._emit_full_event(
                emit_event,
                title=t("extractor.fast.episode.title"),
                description=t(
                    "extractor.fast.episode.started",
                    current=index,
                    total=total_episodes,
                    episode=episode_label,
                ),
                status=InsightStatus.RUNNING,
                meta={
                    "mode": ExtractionMode.FAST.value,
                    "season_id": season_id,
                    "episode_id": episode_id,
                    "successful_chunks": len(episode_chunks),
                },
            )
            ready, token_usage = self._finalize_formal_episode_context(
                config.project_id,
                manifest,
                season_id,
                episode_id,
                chunk_inputs=episode_group.get("chunks", []),
                episode_chunks=episode_chunks,
                previous_episode_id="",
                extraction_run_id=extraction_run_id,
                backend=backend,
                model_name=model_name,
                base_url=base_url,
                api_key=api_key,
                context_window_tokens=context_window_tokens,
            )
            if ready:
                self._emit_full_event(
                    emit_event,
                    title=t("extractor.fast.episode.title"),
                    description=t(
                        "extractor.fast.episode.saved",
                        current=index,
                        total=total_episodes,
                        episode=episode_label,
                    ),
                    status=InsightStatus.DONE,
                    meta={
                        "mode": ExtractionMode.FAST.value,
                        "season_id": season_id,
                        "episode_id": episode_id,
                    },
                )
                return {"index": index, "status": "succeeded", "usage": token_usage}

            self._emit_full_event(
                emit_event,
                title=t("extractor.fast.episode.title"),
                description=t("extractor.fast.episode.failed", episode=episode_label),
                status=InsightStatus.WARNING,
                meta={
                    "mode": ExtractionMode.FAST.value,
                    "season_id": season_id,
                    "episode_id": episode_id,
                },
            )
            return {"index": index, "status": "failed", "usage": token_usage}

        processed = 0
        futures: dict[Any, tuple[int, dict[str, Any]]] = {}
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            for index, episode_group in enumerate(episode_groups, start=1):
                futures[executor.submit(finalize_one, index, episode_group)] = (
                    index,
                    episode_group,
                )
            for future in as_completed(futures):
                index, episode_group = futures[future]
                try:
                    result = future.result()
                except Exception:  # noqa: BLE001
                    season_id = self._manifest_string(episode_group.get("season_id"))
                    episode_id = self._manifest_string(episode_group.get("episode_id"))
                    LOGGER.warning(
                        "Fast extraction episode merge worker failed unexpectedly; "
                        "project_id=%s season_id=%s episode_id=%s",
                        config.project_id,
                        season_id,
                        episode_id,
                        exc_info=True,
                    )
                    self._emit_full_event(
                        emit_event,
                        title=t("extractor.fast.episode.title"),
                        description=t(
                            "extractor.fast.episode.failed",
                            episode=f"{season_id}/{episode_id}",
                        ),
                        status=InsightStatus.WARNING,
                        meta={
                            "mode": ExtractionMode.FAST.value,
                            "season_id": season_id,
                            "episode_id": episode_id,
                        },
                    )
                    result = {"index": index, "status": "failed"}

                status = result.get("status")
                if status == "succeeded":
                    stats["succeeded_episodes"] += 1
                elif status == "skipped":
                    stats["skipped_episodes"] += 1
                else:
                    stats["failed_episodes"] += 1

                token_usage = result.get("usage")
                if isinstance(token_usage, dict):
                    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                        value = token_usage.get(key)
                        if isinstance(value, int):
                            usage_total[key] += value
                    if emit_token_usage is not None and any(usage_total.values()):
                        emit_token_usage(usage_total)

                processed += 1
                if emit_progress is not None:
                    emit_progress(progress_base + int(processed * progress_span / total_episodes))

        return (usage_total, stats)

    def _finalize_fast_season_contexts_from_episodes(
        self,
        config: ProjectConfig,
        manifest: dict[str, Any],
        *,
        concurrency: int,
        backend: ModelBackend,
        model_name: str,
        base_url: str,
        api_key: str,
        context_window_tokens: int | None,
        base_usage: dict[str, int] | None = None,
        progress_base: int = 90,
        progress_span: int = 5,
        emit_token_usage: Callable[[dict[str, int]], None] | None = None,
        emit_event: Callable[[dict], None] | None = None,
        emit_progress: Callable[[int], None] | None = None,
    ) -> tuple[dict[str, int], dict[str, int]]:
        season_ids = self._season_ids_from_manifest(manifest)
        usage_total = {
            "prompt_tokens": int((base_usage or {}).get("prompt_tokens", 0)),
            "completion_tokens": int((base_usage or {}).get("completion_tokens", 0)),
            "total_tokens": int((base_usage or {}).get("total_tokens", 0)),
        }
        stats = {"succeeded_seasons": 0, "skipped_seasons": 0, "failed_seasons": 0}
        if not season_ids:
            return (usage_total, stats)

        total_seasons = len(season_ids)
        worker_count = min(self._normalize_fast_concurrency(concurrency), total_seasons)
        extraction_run_id = self._manifest_string(manifest.get("extraction_run_id"))
        LOGGER.info(
            "Fast extraction season merge pool started; project_id=%s total_seasons=%s concurrency=%s",
            config.project_id,
            total_seasons,
            worker_count,
        )

        def has_completed_episode_context(season_id: str) -> bool:
            for episode_id in self._season_episode_ids_from_manifest(manifest, season_id):
                try:
                    episode_content = kb.load_episode_content(config.project_id, season_id, episode_id)
                    episode_summary = kb.load_episode_summary(config.project_id, season_id, episode_id)
                except (OSError, ValueError, json.JSONDecodeError):
                    continue
                if kb.is_full_artifact_payload_for_run(
                    episode_content,
                    extraction_run_id,
                ) and kb.is_full_artifact_payload_for_run(episode_summary, extraction_run_id):
                    return True
            return False

        def finalize_one(index: int, season_id: str) -> dict[str, Any]:
            if not has_completed_episode_context(season_id):
                self._emit_full_event(
                    emit_event,
                    title=t("extractor.fast.season.title"),
                    description=t("extractor.fast.season.skipped", season=season_id),
                    status=InsightStatus.WARNING,
                    meta={"mode": ExtractionMode.FAST.value, "season_id": season_id},
                )
                return {"index": index, "status": "skipped"}

            self._emit_full_event(
                emit_event,
                title=t("extractor.fast.season.title"),
                description=t(
                    "extractor.fast.season.started",
                    current=index,
                    total=total_seasons,
                    season=season_id,
                ),
                status=InsightStatus.RUNNING,
                meta={"mode": ExtractionMode.FAST.value, "season_id": season_id},
            )
            ready, token_usage = self._finalize_formal_season_context(
                config.project_id,
                manifest,
                season_id,
                extraction_run_id=extraction_run_id,
                backend=backend,
                model_name=model_name,
                base_url=base_url,
                api_key=api_key,
                context_window_tokens=context_window_tokens,
                include_previous_season_backgrounds=False,
            )
            if ready:
                self._emit_full_event(
                    emit_event,
                    title=t("extractor.fast.season.title"),
                    description=t(
                        "extractor.fast.season.saved",
                        current=index,
                        total=total_seasons,
                        season=season_id,
                    ),
                    status=InsightStatus.DONE,
                    meta={"mode": ExtractionMode.FAST.value, "season_id": season_id},
                )
                return {"index": index, "status": "succeeded", "usage": token_usage}

            self._emit_full_event(
                emit_event,
                title=t("extractor.fast.season.title"),
                description=t("extractor.fast.season.failed", season=season_id),
                status=InsightStatus.WARNING,
                meta={"mode": ExtractionMode.FAST.value, "season_id": season_id},
            )
            return {"index": index, "status": "failed", "usage": token_usage}

        processed = 0
        futures: dict[Any, tuple[int, str]] = {}
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            for index, season_id in enumerate(season_ids, start=1):
                futures[executor.submit(finalize_one, index, season_id)] = (index, season_id)
            for future in as_completed(futures):
                index, season_id = futures[future]
                try:
                    result = future.result()
                except Exception:  # noqa: BLE001
                    LOGGER.warning(
                        "Fast extraction season merge worker failed unexpectedly; "
                        "project_id=%s season_id=%s",
                        config.project_id,
                        season_id,
                        exc_info=True,
                    )
                    self._emit_full_event(
                        emit_event,
                        title=t("extractor.fast.season.title"),
                        description=t("extractor.fast.season.failed", season=season_id),
                        status=InsightStatus.WARNING,
                        meta={"mode": ExtractionMode.FAST.value, "season_id": season_id},
                    )
                    result = {"index": index, "status": "failed"}

                status = result.get("status")
                if status == "succeeded":
                    stats["succeeded_seasons"] += 1
                elif status == "skipped":
                    stats["skipped_seasons"] += 1
                else:
                    stats["failed_seasons"] += 1

                token_usage = result.get("usage")
                if isinstance(token_usage, dict):
                    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                        value = token_usage.get(key)
                        if isinstance(value, int):
                            usage_total[key] += value
                    if emit_token_usage is not None and any(usage_total.values()):
                        emit_token_usage(usage_total)

                processed += 1
                if emit_progress is not None:
                    emit_progress(progress_base + int(processed * progress_span / total_seasons))

        return (usage_total, stats)

    def _extract_full_video_units(
        self,
        config: ProjectConfig,
        manifest: dict[str, Any],
        *,
        chunk_inputs: list[dict[str, Any]],
        backend: ModelBackend,
        text_backend: ModelBackend,
        provider: str,
        model_name: str,
        base_url: str,
        api_key: str,
        video_fps: float,
        max_output_tokens: int,
        video_input_mode: VideoInputMode,
        run_plan: FormalExtractionRunPlan,
        context_window_tokens: int | None = None,
        emit_token_usage: Callable[[dict[str, int]], None] | None = None,
        emit_event: Callable[[dict], None] | None = None,
        emit_progress: Callable[[int], None] | None = None,
    ) -> tuple[int, dict[str, int], list[ChunkExtractionResult], dict[str, int]]:
        stats = self._empty_full_extraction_stats(total_chunks=len(chunk_inputs))
        if not chunk_inputs:
            return (0, {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}, [], stats)

        video_handler = self._video_unit_handler(
            provider=provider,
            video_fps=video_fps,
            video_input_mode=video_input_mode,
            max_output_tokens=max_output_tokens,
        )
        episode_groups = self._group_formal_video_chunk_inputs_by_episode(chunk_inputs)
        created = 0
        processed = 0
        usage_total = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        extracted_chunks: list[ChunkExtractionResult] = []
        total_chunks = len(chunk_inputs)
        extraction_run_id = self._manifest_string(manifest.get("extraction_run_id"))
        transcripts_by_episode: dict[tuple[str, str], EpisodeTranscript] = {}
        if video_handler.requires_transcript():
            transcripts = self.ensure_episode_transcripts_from_run_plan(
                config.project_id,
                run_plan,
                emit_event=emit_event,
            )
            transcripts_by_episode = {
                (transcript.source.season_id, transcript.source.episode_id): transcript
                for transcript in transcripts
            }
            if not transcripts_by_episode:
                message = t("extractor.transcript.requiredUnavailable")
                self._emit_full_warning(emit_event, message)
                raise ValueError(message)

        current_season_id = ""
        season_has_context = False
        completed_episode_ids_by_season: dict[str, list[str]] = {}
        for episode_group in episode_groups:
            season_id = self._manifest_string(episode_group.get("season_id"))
            episode_id = self._manifest_string(episode_group.get("episode_id"))
            if not season_id or not episode_id:
                continue
            if current_season_id and season_id != current_season_id and season_has_context:
                _season_context_ready, season_usage = self._finalize_formal_season_context(
                    config.project_id,
                    manifest,
                    current_season_id,
                    extraction_run_id=extraction_run_id,
                    backend=text_backend,
                    model_name=model_name,
                    base_url=base_url,
                    api_key=api_key,
                    context_window_tokens=context_window_tokens,
                )
                for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                    usage_total[key] += season_usage.get(key, 0)
                if emit_token_usage is not None and any(usage_total.values()):
                    emit_token_usage(usage_total)
                if _season_context_ready:
                    stats["succeeded_seasons"] += 1
                else:
                    stats["failed_seasons"] += 1
                season_has_context = False
            current_season_id = season_id
            current_episode_chunks: list[ChunkExtractionResult] = []
            completed_episode_ids = completed_episode_ids_by_season.get(season_id, [])
            previous_episode_id = completed_episode_ids[-1] if completed_episode_ids else ""

            for chunk_input in episode_group.get("chunks", []):
                index = processed + 1
                video_path = chunk_input["video_path"]
                source_path = chunk_input["source_path"]
                try:
                    if not video_path.exists() or not video_path.is_file():
                        self._emit_full_warning(
                            emit_event,
                            t("extractor.full.chunkMissing", path=source_path),
                        )
                        stats["skipped_chunks"] += 1
                        continue

                    budget = video_handler.prepare_budget(video_path)
                    duration_seconds = budget.duration_seconds
                    request_max_output_tokens = budget.request_max_output_tokens
                    if max_output_tokens < FULL_EXTRACTION_MIN_OUTPUT_TOKENS_PER_MINUTE:
                        LOGGER.warning(
                            "Full extraction chunk output token budget is too small; "
                            "project_id=%s chunk=%s duration_seconds=%.2f request_max_tokens=%s "
                            "minimum_tokens_per_minute=%s tokens_per_minute=%s; continuing with low budget",
                            config.project_id,
                            source_path,
                            duration_seconds,
                            request_max_output_tokens,
                            FULL_EXTRACTION_MIN_OUTPUT_TOKENS_PER_MINUTE,
                            max_output_tokens,
                        )
                    LOGGER.info(
                        "Full extraction chunk video request prepared; "
                        "project_id=%s season_id=%s episode_id=%s chunk_id=%s "
                        "size_mb=%.2f duration_seconds=%.2f tokens_per_minute=%s request_max_tokens=%s",
                        config.project_id,
                        chunk_input["season_id"],
                        chunk_input["episode_id"],
                        chunk_input["chunk_id"],
                        video_path.stat().st_size / (1024 * 1024),
                        duration_seconds,
                        max_output_tokens,
                        request_max_output_tokens,
                    )
                    LOGGER.debug(
                        "Full extraction chunk source selected; "
                        "project_id=%s season_id=%s episode_id=%s chunk_id=%s source_path=%s",
                        config.project_id,
                        chunk_input["season_id"],
                        chunk_input["episode_id"],
                        chunk_input["chunk_id"],
                        source_path,
                    )
                    if emit_event is not None:
                        emit_event(
                            InsightEvent(
                                title=t("extractor.full.chunk.title"),
                                description=t(
                                    "extractor.full.chunk.extractingVideoChunk",
                                    current=index,
                                    total=total_chunks,
                                    name=video_path.name,
                                ),
                                status=InsightStatus.RUNNING,
                            ).model_dump(mode="json")
                    )

                    transcript_context = ""
                    if video_handler.requires_transcript():
                        transcript = transcripts_by_episode.get(
                            (chunk_input["season_id"], chunk_input["episode_id"])
                        )
                        if transcript is not None:
                            transcript_context = transcript_segments_for_material(
                                transcript,
                                video_path,
                                max_chars=4000,
                            )
                        if not transcript_context.strip():
                            self._emit_full_warning(
                                emit_event,
                                t(
                                    "extractor.transcript.chunkMissing",
                                    episode=chunk_input["episode_id"],
                                    chunk=chunk_input["chunk_id"],
                                ),
                            )
                            stats["skipped_chunks"] += 1
                            continue

                    chunk_context = self._build_formal_chunk_context_payload(
                        config.project_id,
                        manifest,
                        chunk_input,
                        current_episode_chunks=current_episode_chunks,
                        previous_episode_id=previous_episode_id,
                        extraction_run_id=extraction_run_id,
                    )
                    request = video_handler.build_formal_chunk_request(
                        project_id=config.project_id,
                        chunk_input=chunk_input,
                        backend=backend,
                        model_name=model_name,
                        base_url=base_url,
                        api_key=api_key,
                        request_max_output_tokens=request_max_output_tokens,
                        transcript_context=transcript_context,
                        formal_context=chunk_context,
                    )
                    formal_result = call_formal_json_model(request, call_model=call_video_model)
                    token_usage = formal_result.token_usage
                    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                        value = token_usage.get(key)
                        if isinstance(value, int):
                            usage_total[key] += value
                    if emit_token_usage is not None and any(usage_total.values()):
                        emit_token_usage(usage_total)
                    payload = formal_result.payload

                    chunk = ChunkExtractionResult(
                        season_id=chunk_input["season_id"],
                        episode_id=chunk_input["episode_id"],
                        chunk_id=chunk_input["chunk_id"],
                        extraction_stage=ExtractionArtifactStage.FULL,
                        extraction_run_id=self._manifest_string(chunk_input.get("extraction_run_id")),
                        run_type=FULL_EXTRACTION_RUN_TYPE,
                        source_path=source_path,
                        source_kind="video",
                        source_trace=self._source_trace_from_chunk_input(chunk_input),
                        source_counts={
                            "current_episode_extracted_chunks": len(current_episode_chunks),
                            "selected_episode_contexts": len(
                                chunk_context.get("current_season_completed_episodes", [])
                            ),
                            "previous_season_backgrounds": len(
                                chunk_context.get("previous_season_backgrounds", [])
                            ),
                        },
                        context_policy=chunk_context.get("context_policy", {}),
                        model_metadata=formal_result.model_metadata,
                        token_usage=formal_result.token_usage,
                        estimated_context_tokens=formal_result.estimated_context_tokens,
                        requested_output_tokens=formal_result.requested_output_tokens,
                        finish_reason=formal_result.finish_reason,
                        targets=[],
                        facts=self._coerce_string_list(payload.get("facts")),
                        behavior_traits=self._coerce_string_list(payload.get("behavior_traits")),
                        dialogue_style=self._coerce_string_list(payload.get("dialogue_style")),
                        relationship_interactions=self._coerce_string_list(payload.get("relationships")),
                        conflicts=self._coerce_string_list(payload.get("conflicts")),
                        character_state_changes=self._coerce_string_list(
                            payload.get("character_state_changes")
                        ),
                        insight_summary=str(payload.get("insight_summary", "")).strip(),
                        evidence_refs=self._coerce_string_list(payload.get("evidence_refs")),
                    )
                    self.save_chunk_extraction_result(config.project_id, chunk)
                    extracted_chunks.append(chunk)
                    current_episode_chunks.append(chunk)
                    created += 1
                    stats["succeeded_chunks"] += 1
                    if emit_event is not None:
                        emit_event(
                            InsightEvent(
                                title=t("extractor.full.chunk.title"),
                                description=t(
                                    "extractor.full.chunk.saved",
                                    current=index,
                                    total=total_chunks,
                                    name=video_path.name,
                                ),
                                status=InsightStatus.DONE,
                                meta={
                                    "stream_id": f"full_chunk_{index}",
                                    "season_id": chunk.season_id,
                                    "episode_id": chunk.episode_id,
                                    "chunk_id": chunk.chunk_id,
                                },
                            ).model_dump(mode="json")
                        )
                except FormalExtractionOutputTruncatedError as exc:
                    LOGGER.warning(
                        "Full chunk model response skipped because output was truncated; "
                        "project_id=%s source_path=%s request_max_tokens=%s attempts=%s",
                        config.project_id,
                        source_path,
                        request_max_output_tokens,
                        exc.attempts,
                    )
                    self._emit_full_warning(
                        emit_event,
                        self._output_token_limit_message(
                            video_name=video_path.name,
                            request_max_output_tokens=request_max_output_tokens,
                            duration_seconds=duration_seconds,
                        ),
                    )
                    stats["failed_chunks"] += 1
                    continue
                except FormalExtractionJsonError as exc:
                    LOGGER.warning(
                        "Full extraction chunk JSON retry failed; "
                        "project_id=%s season_id=%s episode_id=%s chunk_id=%s source_path=%s "
                        "attempts=%s error=%s",
                        config.project_id,
                        chunk_input["season_id"],
                        chunk_input["episode_id"],
                        chunk_input["chunk_id"],
                        source_path,
                        exc.attempts,
                        self._compact_exception_message(exc),
                    )
                    if emit_event is not None:
                        emit_event(
                            InsightEvent(
                                title=t("extractor.full.chunk.title"),
                                description=self._full_video_chunk_failed_description(
                                    exc=exc,
                                    index=index,
                                    total=total_chunks,
                                    video_name=video_path.name,
                                ),
                                status=InsightStatus.WARNING,
                            ).model_dump(mode="json")
                        )
                    stats["failed_chunks"] += 1
                    continue
                except ModelCallError as exc:
                    error_kind = (
                        "provider_data_inspection_failed"
                        if self._provider_rejected_video(exc)
                        else "model_call_failed"
                    )
                    if self._provider_rejected_video(exc) and not config.allow_provider_rejected_chunk_skip:
                        description = self._full_video_chunk_failed_description(
                            exc=exc,
                            index=index,
                            total=total_chunks,
                            video_name=video_path.name,
                            stop_on_rejection=True,
                        )
                        LOGGER.warning(
                            "Full extraction stopped after provider rejected a chunk; "
                            "project_id=%s season_id=%s episode_id=%s chunk_id=%s source_path=%s error=%s",
                            config.project_id,
                            chunk_input["season_id"],
                            chunk_input["episode_id"],
                            chunk_input["chunk_id"],
                            source_path,
                            self._compact_exception_message(exc),
                        )
                        self._emit_full_warning(emit_event, description)
                        raise ExtractionStoppedError(description) from exc
                    if self._provider_rejected_video(exc):
                        stats["skipped_chunks"] += 1
                    else:
                        stats["failed_chunks"] += 1
                    LOGGER.warning(
                        "Full extraction chunk skipped after model service error; "
                        "project_id=%s season_id=%s episode_id=%s chunk_id=%s source_path=%s "
                        "error_kind=%s error=%s",
                        config.project_id,
                        chunk_input["season_id"],
                        chunk_input["episode_id"],
                        chunk_input["chunk_id"],
                        source_path,
                        error_kind,
                        self._compact_exception_message(exc),
                    )
                    if emit_event is not None:
                        emit_event(
                            InsightEvent(
                                title=t("extractor.full.chunk.title"),
                                description=self._full_video_chunk_failed_description(
                                    exc=exc,
                                    index=index,
                                    total=total_chunks,
                                    video_name=video_path.name,
                                ),
                                status=InsightStatus.WARNING,
                            ).model_dump(mode="json")
                        )
                    continue
                except Exception as exc:  # noqa: BLE001
                    stats["failed_chunks"] += 1
                    LOGGER.error(
                        "Full extraction chunk failed; project_id=%s source_path=%s",
                        config.project_id,
                        source_path,
                        exc_info=True,
                    )
                    if emit_event is not None:
                        emit_event(
                            InsightEvent(
                                title=t("extractor.full.chunk.title"),
                                description=self._full_video_chunk_failed_description(
                                    exc=exc,
                                    index=index,
                                    total=total_chunks,
                                    video_name=video_path.name,
                                ),
                                status=InsightStatus.WARNING,
                            ).model_dump(mode="json")
                        )
                    continue
                finally:
                    processed += 1
                    if emit_progress is not None:
                        emit_progress(5 + int(processed * 90 / total_chunks))

            if current_episode_chunks:
                episode_context_ready, episode_usage = self._finalize_formal_episode_context(
                    config.project_id,
                    manifest,
                    season_id,
                    episode_id,
                    chunk_inputs=episode_group.get("chunks", []),
                    episode_chunks=current_episode_chunks,
                    previous_episode_id=previous_episode_id,
                    extraction_run_id=extraction_run_id,
                    backend=text_backend,
                    model_name=model_name,
                    base_url=base_url,
                    api_key=api_key,
                    context_window_tokens=context_window_tokens,
                )
                for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                    usage_total[key] += episode_usage.get(key, 0)
                if emit_token_usage is not None and any(usage_total.values()):
                    emit_token_usage(usage_total)
                if episode_context_ready:
                    completed_episode_ids_by_season.setdefault(season_id, []).append(episode_id)
                    season_has_context = True
                    stats["succeeded_episodes"] += 1
                else:
                    stats["failed_episodes"] += 1

        if current_season_id and season_has_context:
            _season_context_ready, season_usage = self._finalize_formal_season_context(
                config.project_id,
                manifest,
                current_season_id,
                extraction_run_id=extraction_run_id,
                backend=text_backend,
                model_name=model_name,
                base_url=base_url,
                api_key=api_key,
                context_window_tokens=context_window_tokens,
            )
            for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                usage_total[key] += season_usage.get(key, 0)
            if emit_token_usage is not None and any(usage_total.values()):
                emit_token_usage(usage_total)
            if _season_context_ready:
                stats["succeeded_seasons"] += 1
            else:
                stats["failed_seasons"] += 1
        return (created, usage_total, extracted_chunks, stats)

    def _emit_full_warning(self, emit_event: Callable[[dict], None] | None, description: str) -> None:
        if emit_event is None:
            return
        emit_event(
            InsightEvent(
                title=t("extractor.full.chunk.title"),
                description=description,
                status=InsightStatus.WARNING,
            ).model_dump(mode="json")
        )

    def _emit_full_event(
        self,
        emit_event: Callable[[dict], None] | None,
        *,
        description: str,
        status: InsightStatus,
        title: str = "",
        meta: dict[str, Any] | None = None,
    ) -> None:
        if emit_event is None:
            return
        emit_event(
            InsightEvent(
                title=title or t("extractor.full.chunk.title"),
                description=description,
                status=status,
                meta=meta or {},
            ).model_dump(mode="json")
        )

    def _full_video_chunk_failed_description(
        self,
        *,
        exc: Exception,
        index: int,
        total: int,
        video_name: str,
        stop_on_rejection: bool = False,
    ) -> str:
        if self._provider_rejected_video(exc):
            return t(
                "extractor.full.chunk.videoRejectedByProviderStopped"
                if stop_on_rejection
                else "extractor.full.chunk.videoRejectedByProvider",
                current=index,
                total=total,
                name=video_name,
            )
        return t(
            "extractor.full.chunk.videoChunkFailed",
            current=index,
            total=total,
            name=video_name,
        )

    def _log_full_model_response_shape(
        self,
        *,
        project_id: str,
        source_path: str,
        result: Any,
    ) -> None:
        first_choice = self._model_first_choice(result)
        message = first_choice.get("message")
        if not isinstance(message, dict):
            message = {}
        content = result.content if isinstance(getattr(result, "content", None), str) else ""
        stripped = content.strip()
        first_char = stripped[:1]
        LOGGER.warning(
            "Full extraction chunk model response could not be parsed as JSON; "
            "project_id=%s source_path=%s finish_reason=%s content_chars=%s stripped_chars=%s "
            "first_char=%r has_left_brace=%s has_right_brace=%s message_keys=%s",
            project_id,
            source_path,
            first_choice.get("finish_reason"),
            len(content),
            len(stripped),
            first_char,
            "{" in stripped,
            "}" in stripped,
            sorted(str(key) for key in message.keys()),
        )

    def _extract_preview_chunk_json_from_materials(
        self,
        config: ProjectConfig,
        *,
        backend: ModelBackend,
        provider: str,
        model_name: str,
        base_url: str,
        api_key: str,
        video_fps: float,
        max_output_tokens: int,
        emit_token_usage: Callable[[dict[str, int]], None] | None = None,
        emit_event: Callable[[dict], None] | None = None,
        emit_progress: Callable[[int], None] | None = None,
    ) -> tuple[int, dict[str, int], list[ChunkExtractionResult]]:
        videos = self._collect_preview_video_chunks(config.project_id)
        if not videos:
            return (0, {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}, [])
        created = 0
        processed = 0
        usage_total = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        extracted_chunks: list[ChunkExtractionResult] = []
        total_videos = max(1, len(videos))
        for index, video_path in enumerate(videos, start=1):
            try:
                duration_seconds = self._video_duration_seconds(video_path)
                request_max_output_tokens = scale_cloud_max_output_tokens_for_video_duration(
                    max_output_tokens,
                    duration_seconds,
                )
                if max_output_tokens < PREVIEW_MIN_OUTPUT_TOKENS_PER_MINUTE:
                    LOGGER.warning(
                        "Preview chunk output token budget is too small; "
                        "project_id=%s chunk=%s duration_seconds=%.2f request_max_tokens=%s "
                        "minimum_tokens_per_minute=%s tokens_per_minute=%s; continuing with low budget",
                        config.project_id,
                        video_path.name,
                        duration_seconds,
                        request_max_output_tokens,
                        PREVIEW_MIN_OUTPUT_TOKENS_PER_MINUTE,
                        max_output_tokens,
                    )
                LOGGER.info(
                    "Preview chunk video request prepared; "
                    "project_id=%s chunk_index=%s size_mb=%.2f duration_seconds=%.2f "
                    "tokens_per_minute=%s request_max_tokens=%s",
                    config.project_id,
                    index,
                    video_path.stat().st_size / (1024 * 1024),
                    duration_seconds,
                    max_output_tokens,
                    request_max_output_tokens,
                )
                LOGGER.debug(
                    "Preview chunk source selected; project_id=%s chunk=%s",
                    config.project_id,
                    video_path.name,
                )
                if emit_event is not None:
                    emit_event(
                        InsightEvent(
                            title=t("extractor.chunk.title"),
                            description=t(
                                "extractor.chunk.extractingVideoChunk",
                                current=index,
                                total=total_videos,
                                name=video_path.name,
                            ),
                            status=InsightStatus.RUNNING,
                        ).model_dump(mode="json")
                    )
                source_path = self._preview_material_relative_path(config.project_id, video_path)
                system_prompt, user_text = render_prompt_texts(
                    purpose="preview_video_chunk_extraction",
                    variables={"source_path": source_path},
                )
                request = ModelCallRequest(
                    purpose="preview_video_chunk_extraction",
                    backend=backend,
                    model_name=model_name,
                    base_url=base_url,
                    api_key=api_key,
                    messages=[
                        ModelMessage(
                            role="system",
                            content=system_prompt,
                        ),
                        ModelMessage(
                            role="user",
                            content=[
                                {"type": "text", "text": user_text},
                                self._build_video_chunk_part(video_path, video_fps),
                            ],
                        ),
                    ],
                    temperature=0.2,
                    max_tokens=request_max_output_tokens,
                    stream=False,
                    timeout_seconds=240,
                    response_format={"type": "json_object"},
                    extra_body=self._video_model_extra_body(provider),
                    metadata={
                        "project_id": config.project_id,
                        "stage": "preview_chunk_extraction",
                        "source_path": source_path,
                    },
                )
                result = call_video_model(request)
                token_usage = result.metadata.get("token_usage")
                if isinstance(token_usage, dict):
                    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                        value = token_usage.get(key)
                        if isinstance(value, int):
                            usage_total[key] += value
                    if emit_token_usage is not None and any(usage_total.values()):
                        emit_token_usage(usage_total)
                try:
                    payload = self._extract_json_object(result.content)
                except ValueError:
                    self._log_preview_model_response_shape(
                        project_id=config.project_id,
                        video_name=video_path.name,
                        result=result,
                    )
                    if self._model_stopped_by_output_limit(result):
                        message = self._output_token_limit_message(
                            video_name=video_path.name,
                            request_max_output_tokens=request_max_output_tokens,
                            duration_seconds=duration_seconds,
                        )
                        self._emit_preview_warning(emit_event, message)
                        continue
                    raise
                season_id, episode_id, chunk_id = self._preview_chunk_identity(
                    config.project_id,
                    video_path,
                    index,
                )
                chunk = ChunkExtractionResult(
                    season_id=season_id,
                    episode_id=episode_id,
                    chunk_id=chunk_id,
                    extraction_stage=ExtractionArtifactStage.PREVIEW,
                    run_type="preview_trial",
                    source_path=source_path,
                    source_kind="video",
                    targets=[],
                    facts=self._coerce_string_list(payload.get("facts")),
                    behavior_traits=self._coerce_string_list(payload.get("behavior_traits")),
                    dialogue_style=self._coerce_string_list(payload.get("dialogue_style")),
                    relationship_interactions=self._coerce_string_list(payload.get("relationships")),
                    conflicts=self._coerce_string_list(payload.get("conflicts")),
                    character_state_changes=self._coerce_string_list(payload.get("character_state_changes")),
                    insight_summary=str(payload.get("insight_summary", "")).strip(),
                    evidence_refs=self._coerce_string_list(payload.get("evidence_refs")),
                )
                self.save_preview_chunk_extraction_result(config.project_id, chunk)
                extracted_chunks.append(chunk)
                created += 1
            except ModelCallError as exc:
                error_kind = (
                    "provider_data_inspection_failed"
                    if self._provider_rejected_video(exc)
                    else "model_call_failed"
                )
                if self._provider_rejected_video(exc) and not config.allow_provider_rejected_chunk_skip:
                    description = self._preview_video_chunk_failed_description(
                        exc=exc,
                        index=index,
                        total=total_videos,
                        video_name=video_path.name,
                        stop_on_rejection=True,
                    )
                    LOGGER.warning(
                        "Preview extraction stopped after provider rejected a chunk; "
                        "project_id=%s chunk=%s error=%s",
                        config.project_id,
                        video_path.name,
                        self._compact_exception_message(exc),
                    )
                    self._emit_preview_warning(emit_event, description)
                    raise ExtractionStoppedError(description) from exc
                LOGGER.warning(
                    "Preview chunk skipped after model service error; "
                    "project_id=%s chunk=%s error_kind=%s error=%s",
                    config.project_id,
                    video_path.name,
                    error_kind,
                    self._compact_exception_message(exc),
                )
                if emit_event is not None:
                    emit_event(
                        InsightEvent(
                            title=t("extractor.chunk.title"),
                            description=self._preview_video_chunk_failed_description(
                                exc=exc,
                                index=index,
                                total=total_videos,
                                video_name=video_path.name,
                            ),
                            status=InsightStatus.WARNING,
                        ).model_dump(mode="json")
                    )
                continue
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning(
                    "Preview chunk extraction from video failed; project_id=%s chunk=%s",
                    config.project_id,
                    video_path.name,
                    exc_info=True,
                )
                if emit_event is not None:
                    emit_event(
                        InsightEvent(
                            title=t("extractor.chunk.title"),
                            description=self._preview_video_chunk_failed_description(
                                exc=exc,
                                index=index,
                                total=total_videos,
                                video_name=video_path.name,
                            ),
                            status=InsightStatus.WARNING,
                        ).model_dump(mode="json")
                    )
                continue
            finally:
                processed += 1
                if emit_progress is not None:
                    emit_progress(15 + int(processed * 75 / total_videos))
        return (created, usage_total, extracted_chunks)

    def _build_chunk_payload(
        self,
        chunk_text: str,
        *,
        previous_episode_summary: str = "",
        previous_chunk_insights: list[str] | None = None,
        previous_episode_extracted_chunks: list[ChunkExtractionResult | dict[str, Any]] | None = None,
        current_season_episode_summaries: list[dict[str, Any]] | None = None,
        previous_season_background: dict[str, Any] | None = None,
        max_previous_chunks: int = 3,
    ) -> str:
        sections = [f"[CURRENT_CHUNK]\n{chunk_text.strip()}"]
        if previous_episode_extracted_chunks:
            structured_chunks: list[dict[str, Any]] = []
            for item in previous_episode_extracted_chunks:
                if isinstance(item, ChunkExtractionResult):
                    structured_chunks.append(item.model_dump(mode="json"))
                elif isinstance(item, dict):
                    structured_chunks.append(item)
            if structured_chunks:
                sections.append(
                    "[CURRENT_EPISODE_EXTRACTED_CHUNKS]\n"
                    + json.dumps(structured_chunks, ensure_ascii=False, indent=2)
                )
        if current_season_episode_summaries:
            sections.append(
                "[CURRENT_SEASON_EPISODE_SUMMARIES]\n"
                + json.dumps(current_season_episode_summaries, ensure_ascii=False, indent=2)
            )
        if previous_season_background:
            sections.append(
                "[PREVIOUS_SEASON_BACKGROUND]\n"
                + json.dumps(previous_season_background, ensure_ascii=False, indent=2)
            )
        if previous_episode_summary.strip():
            sections.append(f"[PREVIOUS_EPISODE_SUMMARY]\n{previous_episode_summary.strip()}")
        if previous_chunk_insights:
            trimmed = [item.strip() for item in previous_chunk_insights if item.strip()]
            if trimmed:
                recent = trimmed[-max_previous_chunks:]
                joined = "\n".join(f"- {item}" for item in recent)
                sections.append(f"[PREVIOUS_CHUNK_INSIGHTS]\n{joined}")
        return "\n\n".join(sections)

    def build_targeted_insight_request(
        self,
        config: ProjectConfig,
        chunk_text: str,
        *,
        previous_episode_summary: str = "",
        previous_chunk_insights: list[str] | None = None,
        previous_episode_extracted_chunks: list[ChunkExtractionResult | dict[str, Any]] | None = None,
        current_season_episode_summaries: list[dict[str, Any]] | None = None,
        previous_season_background: dict[str, Any] | None = None,
        backend: ModelBackend,
        model_name: str,
        base_url: str = "",
        api_key: str = "",
    ) -> ModelCallRequest:
        payload = self._build_chunk_payload(
            chunk_text,
            previous_episode_summary=previous_episode_summary,
            previous_chunk_insights=previous_chunk_insights,
            previous_episode_extracted_chunks=previous_episode_extracted_chunks,
            current_season_episode_summaries=current_season_episode_summaries,
            previous_season_background=previous_season_background,
        )
        return build_model_call_request(
            purpose="targeted_insight",
            backend=backend,
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            variables={
                "chunk_text": payload,
            },
            metadata={
                "project_id": config.project_id,
                "extraction_mode": config.extraction_mode.value,
            },
        )

    def load_current_season_episode_summaries(
        self,
        project_id: str,
        season_id: str,
        current_episode_id: str,
    ) -> list[dict[str, Any]]:
        return kb.load_current_season_episode_summaries(project_id, season_id, current_episode_id)

    def load_previous_season_background(
        self,
        project_id: str,
        season_id: str,
        *,
        enabled: bool = True,
    ) -> dict[str, Any] | None:
        return kb.load_previous_season_summary(project_id, season_id, enabled=enabled)

    def run_full_extraction_streaming(
        self,
        config: ProjectConfig,
        *,
        cloud_preset: CloudModelPreset | None = None,
        fast_concurrency: int = 1,
        emit_event: Callable[[dict], None] | None = None,
        emit_progress: Callable[[int], None] | None = None,
        emit_token_usage: Callable[[dict[str, int]], None] | None = None,
    ) -> list[ChunkExtractionResult]:
        emit_event = emit_event or self.insightGenerated.emit
        emit_progress = emit_progress or self.progressChanged.emit

        LOGGER.info(
            "Full extraction started; project_id=%s sources=%s mode=%s",
            config.project_id,
            len(config.source_paths),
            config.extraction_mode.value,
        )
        emit_event(
            InsightEvent(
                title=t("extractor.full.config.title"),
                description=t("extractor.full.config.description"),
                status=InsightStatus.DONE,
            ).model_dump(mode="json")
        )
        emit_progress(5)

        is_clean_mode = config.extraction_mode == ExtractionMode.CLEAN
        is_fast_mode = config.extraction_mode == ExtractionMode.FAST
        if is_clean_mode:
            try:
                self._emit_full_event(
                    emit_event,
                    description=t("extractor.clean.started"),
                    status=InsightStatus.RUNNING,
                    title=t("extractor.clean.title"),
                )
                cleanup_result = kb.clean_regenerable_extraction_artifacts(config.project_id)
            except Exception as exc:  # noqa: BLE001
                self._emit_full_event(
                    emit_event,
                    description=t("extractor.clean.failed", error=self._compact_exception_message(exc)),
                    status=InsightStatus.WARNING,
                    title=t("extractor.clean.title"),
                )
                raise
            self._emit_full_event(
                emit_event,
                description=t(
                    "extractor.clean.finished",
                    deleted=len(cleanup_result.get("deleted_paths", [])),
                    warnings=len(cleanup_result.get("warnings", [])),
                ),
                status=InsightStatus.DONE,
                title=t("extractor.clean.title"),
                meta=cleanup_result,
            )

        if is_clean_mode:
            extraction_mode = ExtractionMode.CLEAN
        elif is_fast_mode:
            extraction_mode = ExtractionMode.FAST
        else:
            extraction_mode = ExtractionMode.FULL
        run_plan = self.prepare_formal_extraction_run_plan(
            config.project_id,
            mode=extraction_mode,
        )
        manifest = self._legacy_manifest_from_run_plan(run_plan)
        kb.save_extraction_run_plan(config.project_id, run_plan)
        kb.initialize_structure_from_run_plan(config.project_id, run_plan)
        kb.save_source_manifest(config.project_id, manifest)
        chunk_inputs = self._collect_formal_video_chunk_inputs_from_run_plan(
            config.project_id,
            run_plan,
        )
        if not chunk_inputs:
            message = t("extractor.full.noVideoMaterials")
            emit_event(
                InsightEvent(
                    title=t("extractor.full.chunk.title"),
                    description=message,
                    status=InsightStatus.WARNING,
                ).model_dump(mode="json")
            )
            LOGGER.warning(
                "Full extraction stopped because no formal extraction units were found; project_id=%s",
                config.project_id,
            )
            raise ValueError(message)

        preset = self._select_cloud_video_preset(cloud_preset)
        if preset is None:
            message = t("extractor.full.noCloudPreset")
            emit_event(
                InsightEvent(
                    title=t("extractor.full.chunk.title"),
                    description=message,
                    status=InsightStatus.WARNING,
                ).model_dump(mode="json")
            )
            LOGGER.warning("Full extraction stopped because no usable cloud preset was found")
            raise ValueError(message)

        video_input_mode = normalize_video_input_mode(preset.video_input_mode, preset.provider)
        provider_profile = cloud_model_provider(preset.provider)
        if self._video_mode_requires_transcript(video_input_mode):
            TranscriptProvider().prepare_run_plan(config.project_id, run_plan)
            kb.save_extraction_run_plan(config.project_id, run_plan)
            chunk_inputs = self._collect_formal_video_chunk_inputs_from_run_plan(
                config.project_id,
                run_plan,
            )
        if is_fast_mode:
            created_count, extraction_usage, extracted_chunks, run_stats = (
                self._extract_fast_video_units(
                    config,
                    manifest,
                    chunk_inputs=chunk_inputs,
                    concurrency=fast_concurrency,
                    backend=self._backend_for_video_input_mode(preset, video_input_mode),
                    provider=preset.provider,
                    model_name=preset.model_name,
                    base_url=preset.base_url,
                    api_key=preset.api_key,
                    video_fps=preset.video_fps,
                    max_output_tokens=preset.max_output_tokens,
                    video_input_mode=video_input_mode,
                    run_plan=run_plan,
                    progress_base=5,
                    progress_span=75,
                    emit_token_usage=emit_token_usage,
                    emit_event=emit_event,
                    emit_progress=emit_progress,
                )
            )
        else:
            created_count, extraction_usage, extracted_chunks, run_stats = (
                self._extract_full_video_units(
                    config,
                    manifest,
                    chunk_inputs=chunk_inputs,
                    backend=self._backend_for_video_input_mode(preset, video_input_mode),
                    text_backend=provider_profile.backend_for("text"),
                    provider=preset.provider,
                    model_name=preset.model_name,
                    base_url=preset.base_url,
                    api_key=preset.api_key,
                    video_fps=preset.video_fps,
                    max_output_tokens=preset.max_output_tokens,
                    video_input_mode=video_input_mode,
                    run_plan=run_plan,
                    context_window_tokens=context_window_budget_tokens(preset),
                    emit_token_usage=emit_token_usage,
                    emit_event=emit_event,
                    emit_progress=emit_progress,
                )
            )
        if is_fast_mode:
            extraction_usage, episode_stats = self._finalize_fast_episode_contexts_from_chunks(
                config,
                manifest,
                chunk_inputs=chunk_inputs,
                extracted_chunks=extracted_chunks,
                concurrency=fast_concurrency,
                backend=provider_profile.backend_for("text"),
                model_name=preset.model_name,
                base_url=preset.base_url,
                api_key=preset.api_key,
                context_window_tokens=context_window_budget_tokens(preset),
                base_usage=extraction_usage,
                emit_token_usage=emit_token_usage,
                emit_event=emit_event,
                emit_progress=emit_progress,
            )
            for key, value in episode_stats.items():
                run_stats[key] = run_stats.get(key, 0) + value
            extraction_usage, season_stats = self._finalize_fast_season_contexts_from_episodes(
                config,
                manifest,
                concurrency=fast_concurrency,
                backend=provider_profile.backend_for("text"),
                model_name=preset.model_name,
                base_url=preset.base_url,
                api_key=preset.api_key,
                context_window_tokens=context_window_budget_tokens(preset),
                base_usage=extraction_usage,
                emit_token_usage=emit_token_usage,
                emit_event=emit_event,
                emit_progress=emit_progress,
            )
            for key, value in season_stats.items():
                run_stats[key] = run_stats.get(key, 0) + value
        emit_progress(96)
        stale_card_ids: list[str] = []
        if extracted_chunks and (not is_fast_mode or run_stats.get("succeeded_seasons", 0) > 0):
            stale_card_ids = mark_compiled_official_cards_stale(
                config.project_id,
                reason="formal_extraction_updated",
            )
        run_stats["stale_cards"] = len(stale_card_ids)
        LOGGER.info(
            "Full extraction serial aggregation finished; project_id=%s stats=%s",
            config.project_id,
            run_stats,
        )
        if extracted_chunks:
            emit_event(
                InsightEvent(
                    title=t("extractor.full.chunk.title"),
                    description=t("extractor.full.chunk.complete", count=len(extracted_chunks)),
                    status=InsightStatus.DONE,
                ).model_dump(mode="json")
            )
        else:
            emit_event(
                InsightEvent(
                    title=t("extractor.full.chunk.title"),
                    description=t("extractor.full.noChunkJson"),
                    status=InsightStatus.WARNING,
                ).model_dump(mode="json")
            )
        emit_progress(100)
        if emit_token_usage is not None and not any(extraction_usage.values()):
            emit_token_usage({})
        self._emit_full_event(
            emit_event,
            description=t(
                "extractor.full.summary",
                succeeded=run_stats.get("succeeded_chunks", 0),
                skipped=run_stats.get("skipped_chunks", 0),
                failed=run_stats.get("failed_chunks", 0),
                episode_succeeded=run_stats.get("succeeded_episodes", 0),
                episode_skipped=run_stats.get("skipped_episodes", 0),
                episode_failed=run_stats.get("failed_episodes", 0),
                season_succeeded=run_stats.get("succeeded_seasons", 0),
                season_skipped=run_stats.get("skipped_seasons", 0),
                season_failed=run_stats.get("failed_seasons", 0),
                stale=run_stats.get("stale_cards", 0),
            ),
            status=InsightStatus.DONE if extracted_chunks else InsightStatus.WARNING,
            meta={**run_stats, "stale_card_ids": stale_card_ids},
        )
        LOGGER.info(
            "Full extraction finished; project_id=%s created_chunks=%s",
            config.project_id,
            created_count,
        )
        return extracted_chunks

    def run_preview(self, config: ProjectConfig) -> None:
        self.run_preview_streaming(config)

    def run_preview_streaming(
        self,
        config: ProjectConfig,
        *,
        cloud_preset: CloudModelPreset | None = None,
        emit_event: Callable[[dict], None] | None = None,
        emit_progress: Callable[[int], None] | None = None,
        emit_token_usage: Callable[[dict[str, int]], None] | None = None,
    ) -> str:
        emit_event = emit_event or self.insightGenerated.emit
        emit_progress = emit_progress or self.progressChanged.emit

        LOGGER.info(
            "Preview extraction started; project_id=%s sources=%s mode=%s",
            config.project_id,
            len(config.source_paths),
            config.extraction_mode.value,
        )
        emit_event(
            InsightEvent(
                title=t("extractor.config.title"),
                description=t("extractor.config.description"),
                status=InsightStatus.DONE,
            ).model_dump(mode="json")
        )
        emit_progress(15)

        preset = self._select_cloud_video_preset(cloud_preset)
        if preset is None:
            emit_event(
                InsightEvent(
                    title=t("extractor.chunk.title"),
                    description=t("extractor.chunk.description"),
                    status=InsightStatus.RUNNING,
                ).model_dump(mode="json")
            )
            emit_event(
                InsightEvent(
                    title=t("extractor.insight.title"),
                    description=t("extractor.insight.description"),
                    status=InsightStatus.QUEUED,
                ).model_dump(mode="json")
            )
            LOGGER.info("Preview extraction finished without cloud preset; project_id=%s", config.project_id)
            return ""

        preview_chunks: list[ChunkExtractionResult] = []
        overall_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        try:
            created_count, extraction_usage, extracted_chunks = self._extract_preview_chunk_json_from_materials(
                config,
                backend=cloud_model_provider(preset.provider).backend_for("video"),
                provider=preset.provider,
                model_name=preset.model_name,
                base_url=preset.base_url,
                api_key=preset.api_key,
                video_fps=preset.video_fps,
                max_output_tokens=preset.max_output_tokens,
                emit_token_usage=emit_token_usage,
                emit_event=emit_event,
                emit_progress=emit_progress,
            )
        except ExtractionStoppedError:
            raise
        except Exception:  # noqa: BLE001
            LOGGER.error("Preview chunk extraction from video failed; project_id=%s", config.project_id, exc_info=True)
            created_count = 0
            extraction_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
            extracted_chunks = []
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            overall_usage[key] += extraction_usage.get(key, 0)
        if created_count > 0:
            self._merge_preview_episode_contents(config.project_id, extracted_chunks)
            preview_chunks = extracted_chunks[:PREVIEW_MAX_CHUNKS]

        if preview_chunks:
            emit_event(
                InsightEvent(
                    title=t("extractor.chunk.title"),
                    description=t("extractor.chunk.usingChunkJson", count=len(preview_chunks)),
                    status=InsightStatus.DONE,
                ).model_dump(mode="json")
            )
        else:
            emit_event(
                InsightEvent(
                    title=t("extractor.chunk.title"),
                    description=t("extractor.chunk.noChunkJson"),
                    status=InsightStatus.WARNING,
                ).model_dump(mode="json")
            )
            LOGGER.info(
                "Preview extraction aborted because no readable chunk JSON was found; project_id=%s",
                config.project_id,
            )
            return ""
        if created_count <= 0:
            emit_progress(30)

        final_outputs: list[str] = []
        total_chunks = max(1, len(preview_chunks))
        progress_base = 90 if created_count > 0 else 30
        progress_span = 5 if created_count > 0 else 65
        for index, chunk in enumerate(preview_chunks, start=1):
            preview_chunk_text = self._format_preview_chunk_input(chunk)
            if not preview_chunk_text:
                continue
            final_outputs.append(preview_chunk_text)
            summary = chunk.insight_summary.strip() or preview_chunk_text
            emit_event(
                InsightEvent(
                    title=t("extractor.insight.title"),
                    description=summary,
                    status=InsightStatus.DONE,
                    meta={
                        "stream_id": f"preview_chunk_{index}",
                        "season_id": chunk.season_id,
                        "episode_id": chunk.episode_id,
                        "chunk_id": chunk.chunk_id,
                    },
                ).model_dump(mode="json")
            )
            emit_progress(progress_base + int(index * progress_span / total_chunks))

        emit_progress(100)
        if emit_token_usage is not None and not any(overall_usage.values()):
            emit_token_usage({})
        LOGGER.info("Preview extraction finished; project_id=%s", config.project_id)
        return "\n\n".join(item for item in final_outputs if item)
