from __future__ import annotations

import logging
import json
import math
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QObject, pyqtSignal

from core import knowledge_base as kb
from core import source_scanner
from core.models import (
    ChunkExtractionResult,
    ExtractionArtifactStage,
    InsightEvent,
    InsightStatus,
    ProjectConfig,
)
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
    cloud_model_provider,
    load_cloud_model_presets,
    scale_cloud_max_output_tokens_for_video_duration,
)
from utils.ffmpeg_tool import FfmpegProcessError, probe_video_duration_seconds
from utils.i18n import t
from utils.model_preferences import last_cloud_preset_name
from utils.paths import ensure_project_tree


LOGGER = logging.getLogger(__name__)
VIDEO_SUFFIXES = source_scanner.VIDEO_SUFFIXES
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

    def scan_formal_video_materials(self, project_id: str) -> dict[str, Any]:
        return source_scanner.scan_formal_video_materials(project_id)

    def generate_source_manifest(self, project_id: str, source_root: str) -> Path:
        manifest = self.scan_source_directory(source_root)
        return kb.save_source_manifest(project_id, manifest)

    def prepare_formal_video_extraction_plan(self, project_id: str) -> dict[str, Any]:
        manifest = self.scan_formal_video_materials(project_id)
        kb.save_source_manifest(project_id, manifest)
        kb.initialize_structure(project_id, manifest)
        return manifest

    def initialize_knowledge_base_structure(self, project_id: str, manifest: dict | None = None) -> Path:
        return kb.initialize_structure(project_id, manifest)

    def save_chunk_extraction_result(self, project_id: str, result: ChunkExtractionResult) -> Path:
        return kb.save_chunk_result(project_id, result)

    def save_preview_chunk_extraction_result(self, project_id: str, result: ChunkExtractionResult) -> Path:
        return kb.save_preview_chunk_result(project_id, result)

    def merge_episode_content(self, project_id: str, season_id: str, episode_id: str) -> Path:
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
                    "Chunk JSON read failed during episode merge; project_id=%s season_id=%s episode_id=%s path=%s",
                    project_id,
                    season_id,
                    episode_id,
                    chunk_path,
                    exc_info=True,
                )
                continue
            if not kb.is_full_artifact_payload(payload):
                skipped_chunks += 1
                continue
            try:
                chunk = ChunkExtractionResult.model_validate(payload)
            except ValueError:
                skipped_chunks += 1
                warning = f"chunk_validation_failed:{chunk_path.name}"
                aggregation_warnings.append(warning)
                LOGGER.warning(
                    "Full chunk validation failed during episode merge; project_id=%s season_id=%s episode_id=%s path=%s",
                    project_id,
                    season_id,
                    episode_id,
                    chunk_path,
                    exc_info=True,
                )
                continue
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

        episode_content = {
            "season_id": season_id,
            "episode_id": episode_id,
            "extraction_stage": kb.FULL_EXTRACTION_STAGE,
            "run_type": FULL_EXTRACTION_RUN_TYPE,
            "source_kind": "video",
            "schema_version": 1,
            "source_counts": {
                "total_chunk_files": len(chunk_paths),
                "full_chunks": len(chunk_results),
                "skipped_chunks": skipped_chunks,
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

    def generate_episode_summary(self, project_id: str, season_id: str, episode_id: str) -> Path:
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
        chunk_results = episode_content.get("chunk_results", [])
        insight_summaries: list[str] = []
        for chunk in chunk_results:
            if not isinstance(chunk, dict):
                continue
            insight = chunk.get("insight_summary", "")
            if isinstance(insight, str) and insight.strip():
                insight_summaries.append(insight.strip())

        summary = {
            "season_id": season_id,
            "episode_id": episode_id,
            "extraction_stage": kb.FULL_EXTRACTION_STAGE,
            "run_type": FULL_EXTRACTION_RUN_TYPE,
            "source_kind": "video",
            "schema_version": 1,
            "source_counts": episode_content.get("source_counts", {}),
            "aggregation_warnings": episode_content.get("aggregation_warnings", []),
            "character_summaries": episode_content.get("behavior_traits", []),
            "relationship_changes": episode_content.get("relationship_interactions", []),
            "major_events": episode_content.get("facts", []),
            "open_conflicts": episode_content.get("conflicts", []),
            "growth_signals": episode_content.get("character_state_changes", []),
            "insight_summary": " | ".join(self._deduplicate_preserve_order(insight_summaries)),
        }
        return kb.save_episode_summary(project_id, season_id, episode_id, summary)

    def merge_season_content(self, project_id: str, season_id: str) -> Path:
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
            if not kb.is_full_artifact_payload(payload):
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

        season_content = {
            "season_id": season_id,
            "extraction_stage": kb.FULL_EXTRACTION_STAGE,
            "run_type": FULL_EXTRACTION_RUN_TYPE,
            "source_kind": "video",
            "schema_version": 1,
            "source_counts": {
                "total_episode_dirs": len(episode_dirs),
                "full_episodes": len(episode_contents),
                "skipped_episodes": skipped_episodes,
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

    def generate_season_summary(self, project_id: str, season_id: str) -> Path:
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
        episode_contents = season_content.get("episode_contents", [])
        background_parts: list[str] = []
        for episode in episode_contents:
            if not isinstance(episode, dict):
                continue
            episode_id = episode.get("episode_id", "")
            facts = episode.get("facts", [])
            if isinstance(episode_id, str) and isinstance(facts, list) and facts:
                background_parts.append(f"{episode_id}: {'; '.join(str(item) for item in facts)}")

        summary = {
            "season_id": season_id,
            "extraction_stage": kb.FULL_EXTRACTION_STAGE,
            "run_type": FULL_EXTRACTION_RUN_TYPE,
            "source_kind": "video",
            "schema_version": 1,
            "source_counts": season_content.get("source_counts", {}),
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
                LOGGER.warning("Preview chunk JSON read failed; path=%s", chunk_path, exc_info=True)
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
        text = content.strip()
        if not text:
            raise ValueError("empty model response")
        try:
            payload = json.loads(text)
            if isinstance(payload, dict):
                return payload
        except json.JSONDecodeError:
            pass
        candidates = list(self._extract_json_object_candidates(text))
        if candidates:
            return candidates[-1]
        raise ValueError("model response is not a JSON object")

    def _extract_json_object_candidates(self, text: str) -> list[dict[str, Any]]:
        decoder = json.JSONDecoder()
        candidates: list[dict[str, Any]] = []
        for index, char in enumerate(text):
            if char != "{":
                continue
            try:
                payload, _end = decoder.raw_decode(text[index:])
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                candidates.append(payload)
        return candidates

    def _video_model_extra_body(self, base_url: str) -> dict[str, Any]:
        if "dashscope.aliyuncs.com" in base_url.lower():
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

    def _collect_formal_video_chunk_inputs(
        self,
        project_id: str,
        manifest: dict[str, Any],
    ) -> list[dict[str, Any]]:
        chunk_inputs: list[dict[str, Any]] = []
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
                for chunk in episode.get("chunks", []):
                    if not isinstance(chunk, dict):
                        continue
                    chunk_id = self._manifest_string(chunk.get("chunk_id"))
                    source_path = self._manifest_string(chunk.get("source_path"))
                    if not chunk_id or not source_path:
                        continue
                    chunk_inputs.append(
                        {
                            "season_id": season_id,
                            "episode_id": episode_id,
                            "chunk_id": chunk_id,
                            "source_path": source_path,
                            "video_path": self._formal_material_video_path(project_id, source_path),
                        }
                    )
        return chunk_inputs

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
        for season_id, episode_id in self._collect_formal_episode_ids_from_manifest(manifest):
            try:
                written_paths.append(self.merge_episode_content(project_id, season_id, episode_id))
                written_paths.append(self.generate_episode_summary(project_id, season_id, episode_id))
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
                written_paths.append(self.merge_season_content(project_id, season_id))
                written_paths.append(self.generate_season_summary(project_id, season_id))
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

    def _extract_full_chunk_json_from_manifest(
        self,
        config: ProjectConfig,
        manifest: dict[str, Any],
        *,
        backend: ModelBackend,
        model_name: str,
        base_url: str,
        api_key: str,
        video_fps: float,
        max_output_tokens: int,
        emit_token_usage: Callable[[dict[str, int]], None] | None = None,
        emit_event: Callable[[dict], None] | None = None,
        emit_progress: Callable[[int], None] | None = None,
    ) -> tuple[int, dict[str, int], list[ChunkExtractionResult]]:
        chunk_inputs = self._collect_formal_video_chunk_inputs(config.project_id, manifest)
        if not chunk_inputs:
            return (0, {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}, [])

        created = 0
        processed = 0
        usage_total = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        extracted_chunks: list[ChunkExtractionResult] = []
        total_chunks = len(chunk_inputs)
        for index, chunk_input in enumerate(chunk_inputs, start=1):
            video_path = chunk_input["video_path"]
            source_path = chunk_input["source_path"]
            try:
                if not video_path.exists() or not video_path.is_file():
                    self._emit_full_warning(
                        emit_event,
                        t("extractor.full.chunkMissing", path=source_path),
                    )
                    continue

                duration_seconds = self._video_duration_seconds(video_path)
                request_max_output_tokens = scale_cloud_max_output_tokens_for_video_duration(
                    max_output_tokens,
                    duration_seconds,
                )
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

                request = self._build_full_video_chunk_request(
                    config,
                    chunk_input=chunk_input,
                    backend=backend,
                    model_name=model_name,
                    base_url=base_url,
                    api_key=api_key,
                    video_fps=video_fps,
                    request_max_output_tokens=request_max_output_tokens,
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
                if self._model_stopped_by_output_limit(result):
                    LOGGER.warning(
                        "Full chunk model response skipped because output was truncated; "
                        "project_id=%s source_path=%s finish_reason=%s request_max_tokens=%s content_chars=%s",
                        config.project_id,
                        source_path,
                        self._model_finish_reason(result),
                        request_max_output_tokens,
                        len(result.content) if isinstance(result.content, str) else 0,
                    )
                    self._emit_full_warning(
                        emit_event,
                        self._output_token_limit_message(
                            video_name=video_path.name,
                            request_max_output_tokens=request_max_output_tokens,
                            duration_seconds=duration_seconds,
                        ),
                    )
                    continue
                try:
                    payload = self._extract_json_object(result.content)
                except ValueError:
                    self._log_full_model_response_shape(
                        project_id=config.project_id,
                        source_path=source_path,
                        result=result,
                    )
                    raise

                chunk = ChunkExtractionResult(
                    season_id=chunk_input["season_id"],
                    episode_id=chunk_input["episode_id"],
                    chunk_id=chunk_input["chunk_id"],
                    extraction_stage=ExtractionArtifactStage.FULL,
                    run_type=FULL_EXTRACTION_RUN_TYPE,
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
                self.save_chunk_extraction_result(config.project_id, chunk)
                extracted_chunks.append(chunk)
                created += 1
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
                LOGGER.warning(
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
        return (created, usage_total, extracted_chunks)

    def _build_full_video_chunk_request(
        self,
        config: ProjectConfig,
        *,
        chunk_input: dict[str, Any],
        backend: ModelBackend,
        model_name: str,
        base_url: str,
        api_key: str,
        video_fps: float,
        request_max_output_tokens: int,
    ) -> ModelCallRequest:
        video_path = chunk_input["video_path"]
        chunk_ref = (
            f"{chunk_input['season_id']}/{chunk_input['episode_id']}/{chunk_input['chunk_id']}"
        )
        system_prompt, user_text = render_prompt_texts(
            purpose="formal_video_chunk_extraction",
            variables={
                "chunk_id": chunk_ref,
                "source_path": chunk_input["source_path"],
            },
        )
        return ModelCallRequest(
            purpose="formal_video_chunk_extraction",
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
            extra_body=self._video_model_extra_body(base_url),
            metadata={
                "project_id": config.project_id,
                "stage": "full_chunk_extraction",
                "season_id": chunk_input["season_id"],
                "episode_id": chunk_input["episode_id"],
                "chunk_id": chunk_input["chunk_id"],
                "source_path": chunk_input["source_path"],
            },
        )

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
                    extra_body=self._video_model_extra_body(base_url),
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
                if emit_progress is not None:
                    emit_progress(15 + int(created * 75 / total_videos))
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
        targets = config.target_characters or [t("extractor.noTarget")]
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
                "target_characters": targets,
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
            emit_progress(100)
            LOGGER.warning("Full extraction stopped because no usable cloud preset was found")
            raise ValueError(message)

        manifest = self.prepare_formal_video_extraction_plan(config.project_id)
        created_count, extraction_usage, extracted_chunks = self._extract_full_chunk_json_from_manifest(
            config,
            manifest,
            backend=cloud_model_provider(preset.provider).backend_for("video"),
            model_name=preset.model_name,
            base_url=preset.base_url,
            api_key=preset.api_key,
            video_fps=preset.video_fps,
            max_output_tokens=preset.max_output_tokens,
            emit_token_usage=emit_token_usage,
            emit_event=emit_event,
            emit_progress=emit_progress,
        )
        emit_progress(96)
        aggregated_paths = self._aggregate_full_outputs_from_manifest(config.project_id, manifest)
        LOGGER.info(
            "Full extraction aggregation finished; project_id=%s written_artifacts=%s",
            config.project_id,
            len(aggregated_paths),
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

        targets = ", ".join(config.target_characters) or t("extractor.noTarget")
        LOGGER.info(
            "Preview extraction started; project_id=%s targets=%s sources=%s mode=%s",
            config.project_id,
            len(config.target_characters),
            len(config.source_paths),
            config.extraction_mode.value,
        )
        emit_event(
            InsightEvent(
                title=t("extractor.config.title"),
                description=t("extractor.config.description", targets=targets),
                status=InsightStatus.DONE,
            ).model_dump(mode="json")
        )
        emit_progress(15)

        preset = cloud_preset
        if preset is None:
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
            if preset is None:
                preset = next((item for item in presets if item.base_url.strip() and item.model_name.strip()), None)
        if preset is None:
            emit_event(
                InsightEvent(
                    title=t("extractor.chunk.title"),
                    description=t("extractor.chunk.description"),
                    status=InsightStatus.RUNNING,
                ).model_dump(mode="json")
            )
            emit_progress(70)
            emit_event(
                InsightEvent(
                    title=t("extractor.insight.title"),
                    description=t("extractor.insight.description"),
                    status=InsightStatus.QUEUED,
                ).model_dump(mode="json")
            )
            emit_progress(100)
            LOGGER.info("Preview extraction finished without cloud preset; project_id=%s", config.project_id)
            return ""

        preview_chunks: list[ChunkExtractionResult] = []
        overall_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        try:
            created_count, extraction_usage, extracted_chunks = self._extract_preview_chunk_json_from_materials(
                config,
                backend=cloud_model_provider(preset.provider).backend_for("video"),
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
            LOGGER.warning("Preview chunk extraction from video failed; project_id=%s", config.project_id, exc_info=True)
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
            emit_progress(100)
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
