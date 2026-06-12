from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from core.extraction_plan import (
    ContentForm,
    DerivedArtifact,
    DerivedArtifactKind,
    DerivedArtifactStatus,
    ExtractionUnit,
    FormalExtractionRunPlan,
    MaterialRef,
    MaterialOrigin,
    MediaType,
    TextRange,
    TimeRange,
)
from core.models import EpisodeTranscript
from utils.audio_transcription import TranscriptionOptions, transcribe_episode_audio
from utils.paths import ensure_project_tree


TranscriptRunner = Callable[
    [str, str, str, Sequence[Path], TranscriptionOptions],
    EpisodeTranscript,
]


@dataclass(frozen=True, slots=True)
class TranscriptArtifactRequest:
    season_id: str
    episode_id: str
    artifact_id: str
    artifact_path: str
    material_paths: list[Path]


def _default_transcript_runner(
    project_id: str,
    season_id: str,
    episode_id: str,
    material_paths: Sequence[Path],
    options: TranscriptionOptions,
) -> EpisodeTranscript:
    return transcribe_episode_audio(
        project_id,
        season_id,
        episode_id,
        list(material_paths),
        options=options,
    )


class TranscriptProvider:
    def __init__(self, transcribe: TranscriptRunner | None = None) -> None:
        self._transcribe = transcribe or _default_transcript_runner

    def prepare_run_plan(
        self,
        project_id: str,
        run_plan: FormalExtractionRunPlan,
        *,
        include_video: bool = True,
        include_audio: bool = True,
    ) -> FormalExtractionRunPlan:
        if run_plan.project_id != project_id:
            raise ValueError(
                f"run plan project_id mismatch: expected {project_id}, got {run_plan.project_id}"
            )
        artifacts_by_id = {artifact.artifact_id: artifact for artifact in run_plan.derived_artifacts}
        for episode in run_plan.episodes:
            transcript_units = [
                unit
                for unit in episode.units
                if (include_video and unit.media_type == MediaType.VIDEO)
                or (include_audio and unit.media_type == MediaType.AUDIO)
            ]
            if not transcript_units:
                continue

            artifact_id = self._artifact_id(episode.season_id, episode.episode_id)
            artifact = artifacts_by_id.get(artifact_id)
            source_refs = self._unique_material_refs(transcript_units)
            unit_refs = [unit.unit_id for unit in transcript_units]
            if artifact is None:
                artifact = DerivedArtifact(
                    artifact_id=artifact_id,
                    derived_kind=DerivedArtifactKind.TRANSCRIPT,
                    content_kind=MediaType.TEXT,
                    source_refs=source_refs,
                    artifact_path=self._artifact_path(episode.season_id, episode.episode_id),
                    coverage={
                        "season_id": episode.season_id,
                        "episode_id": episode.episode_id,
                        "unit_refs": unit_refs,
                        "material_refs": [ref.material_id for ref in source_refs],
                    },
                    generation={"provider": "audio_transcription"},
                    status=DerivedArtifactStatus.PENDING,
                    metadata={
                        "scope": "episode",
                        "source_media_types": sorted(
                            {unit.media_type.value for unit in transcript_units}
                        ),
                    },
                )
                run_plan.derived_artifacts.append(artifact)
                artifacts_by_id[artifact_id] = artifact
            else:
                artifact.source_refs = source_refs
                artifact.artifact_path = artifact.artifact_path or self._artifact_path(
                    episode.season_id,
                    episode.episode_id,
                )
                artifact.coverage = {
                    **artifact.coverage,
                    "season_id": episode.season_id,
                    "episode_id": episode.episode_id,
                    "unit_refs": unit_refs,
                    "material_refs": [ref.material_id for ref in source_refs],
                }
                artifact.generation = {
                    **artifact.generation,
                    "provider": artifact.generation.get("provider") or "audio_transcription",
                }
                artifact.metadata = {
                    **artifact.metadata,
                    "source_media_types": sorted(
                        {unit.media_type.value for unit in transcript_units}
                    ),
                }

            for unit in transcript_units:
                if artifact_id not in unit.derived_refs:
                    unit.derived_refs.append(artifact_id)
            if artifact_id not in episode.derived_artifact_ids:
                episode.derived_artifact_ids.append(artifact_id)
        return run_plan

    def collect_requests(
        self,
        project_id: str,
        run_plan: FormalExtractionRunPlan,
        *,
        include_video: bool = True,
        include_audio: bool = True,
    ) -> list[TranscriptArtifactRequest]:
        requests: list[TranscriptArtifactRequest] = []
        for artifact in run_plan.derived_artifacts:
            if artifact.derived_kind != DerivedArtifactKind.TRANSCRIPT:
                continue
            source_media_types = {ref.source_media_type for ref in artifact.source_refs}
            if not (
                (include_video and MediaType.VIDEO in source_media_types)
                or (include_audio and MediaType.AUDIO in source_media_types)
            ):
                continue
            season_id = str(artifact.coverage.get("season_id", "")).strip()
            episode_id = str(artifact.coverage.get("episode_id", "")).strip()
            if not season_id or not episode_id:
                continue
            material_paths = [
                path
                for path in (
                    self._material_path(project_id, ref.relative_path)
                    for ref in artifact.source_refs
                )
                if path.is_file()
            ]
            requests.append(
                TranscriptArtifactRequest(
                    season_id=season_id,
                    episode_id=episode_id,
                    artifact_id=artifact.artifact_id,
                    artifact_path=artifact.artifact_path,
                    material_paths=material_paths,
                )
            )
        return requests

    def ensure_transcript(
        self,
        project_id: str,
        request: TranscriptArtifactRequest,
        *,
        language: str = "auto",
        force_rebuild: bool = False,
    ) -> EpisodeTranscript:
        return self._transcribe(
            project_id,
            request.season_id,
            request.episode_id,
            request.material_paths,
            TranscriptionOptions(language=language, force_rebuild=force_rebuild),
        )

    def mark_status(
        self,
        run_plan: FormalExtractionRunPlan,
        artifact_id: str,
        status: DerivedArtifactStatus,
        *,
        warning: str = "",
    ) -> None:
        for artifact in run_plan.derived_artifacts:
            if artifact.artifact_id != artifact_id:
                continue
            artifact.status = status
            if warning and warning not in artifact.warnings:
                artifact.warnings.append(warning)
            return

    def materialize_text_unit(
        self,
        run_plan: FormalExtractionRunPlan,
        artifact_id: str,
        transcript: EpisodeTranscript,
    ) -> ExtractionUnit:
        artifact = next(
            (
                item
                for item in run_plan.derived_artifacts
                if item.artifact_id == artifact_id
                and item.derived_kind == DerivedArtifactKind.TRANSCRIPT
            ),
            None,
        )
        if artifact is None:
            raise ValueError(f"transcript artifact does not exist: {artifact_id}")
        season_id = str(artifact.coverage.get("season_id", "")).strip()
        episode_id = str(artifact.coverage.get("episode_id", "")).strip()
        episode = next(
            (
                item
                for item in run_plan.episodes
                if item.season_id == season_id and item.episode_id == episode_id
            ),
            None,
        )
        if episode is None:
            raise ValueError(
                f"transcript artifact episode does not exist: {season_id}/{episode_id}"
            )

        time_range = self._transcript_time_range(transcript)
        content_form = self._transcript_content_form(artifact, episode.content_forms)
        material_ref = MaterialRef(
            material_id=f"derived_{artifact.artifact_id}",
            relative_path=artifact.artifact_path,
            source_media_type=MediaType.TEXT,
            content_form=content_form,
            origin=MaterialOrigin.DERIVED,
            fingerprint=transcript.source.source_fingerprint,
            time_range=time_range,
            text_range=TextRange(section="episode_transcript"),
            metadata={
                "derived_artifact_id": artifact.artifact_id,
                "derived_kind": artifact.derived_kind.value,
                "source_material_ids": [ref.material_id for ref in artifact.source_refs],
                "source_material_refs": [
                    ref.model_dump(mode="json") for ref in artifact.source_refs
                ],
                "transcription_backend": transcript.transcription.backend,
            },
        )
        unit = ExtractionUnit(
            unit_id=self._transcript_unit_id(artifact.artifact_id),
            episode_id=episode_id,
            media_type=MediaType.TEXT,
            content_form=content_form,
            material_ref=material_ref,
            origin=MaterialOrigin.DERIVED,
            unit_kind="transcript_text",
            derived_refs=[artifact.artifact_id],
            budget_hint={"basis": "text_chunk", "source": "transcript"},
            handler_options={
                "storage_root": "knowledge_base",
                "preview_support": "supported",
                "formal_support": "supported",
                "speaker_policy": "explicit_only",
            },
            metadata={
                "season_id": season_id,
                "derived_artifact_id": artifact.artifact_id,
                "transcript_segment_count": len(transcript.segments),
            },
        )
        existing_index = next(
            (
                index
                for index, item in enumerate(episode.units)
                if item.unit_kind == "transcript_text"
                and item.metadata.get("derived_artifact_id") == artifact.artifact_id
            ),
            None,
        )
        if existing_index is None:
            episode.units.append(unit)
        else:
            episode.units[existing_index] = unit

        artifact.status = DerivedArtifactStatus.READY
        artifact.coverage = {
            **artifact.coverage,
            "segment_count": len(transcript.segments),
            "text_chars": len(transcript.plain_text),
            "time_range": time_range.model_dump(mode="json") if time_range else None,
        }
        artifact.generation = {
            **artifact.generation,
            "provider": transcript.transcription.backend,
            "language": transcript.transcription.language,
            "cache_key": transcript.transcription.cache_key,
        }
        return unit

    def remove_text_unit(
        self,
        run_plan: FormalExtractionRunPlan,
        artifact_id: str,
    ) -> None:
        for episode in run_plan.episodes:
            episode.units = [
                unit
                for unit in episode.units
                if not (
                    unit.unit_kind == "transcript_text"
                    and unit.metadata.get("derived_artifact_id") == artifact_id
                )
            ]

    def _material_path(self, project_id: str, relative_path: str) -> Path:
        path = Path(relative_path)
        if path.is_absolute():
            return path
        return ensure_project_tree(project_id).materials / path

    def _unique_material_refs(self, units: list[ExtractionUnit]) -> list[MaterialRef]:
        refs: list[MaterialRef] = []
        seen: set[str] = set()
        for unit in units:
            material_id = unit.material_ref.material_id
            if material_id in seen:
                continue
            seen.add(material_id)
            refs.append(unit.material_ref)
        return refs

    def _artifact_id(self, season_id: str, episode_id: str) -> str:
        return f"transcript_{season_id}_{episode_id}"

    def _artifact_path(self, season_id: str, episode_id: str) -> str:
        return f"seasons/{season_id}/episodes/{episode_id}/episode_transcript.json"

    @staticmethod
    def _transcript_unit_id(artifact_id: str) -> str:
        digest = hashlib.sha256(artifact_id.encode("utf-8")).hexdigest()[:12]
        return f"unit_transcript_{digest}"

    @staticmethod
    def _transcript_time_range(transcript: EpisodeTranscript) -> TimeRange | None:
        if not transcript.segments:
            return None
        return TimeRange(
            start_seconds=min(segment.start_seconds for segment in transcript.segments),
            end_seconds=max(
                max(segment.start_seconds, segment.end_seconds)
                for segment in transcript.segments
            ),
        )

    @staticmethod
    def _transcript_content_form(
        artifact: DerivedArtifact,
        episode_content_forms: list[ContentForm],
    ) -> ContentForm:
        if any(ref.source_media_type == MediaType.AUDIO for ref in artifact.source_refs):
            return ContentForm.AUDIO_DRAMA
        return episode_content_forms[0] if episode_content_forms else ContentForm.UNKNOWN
