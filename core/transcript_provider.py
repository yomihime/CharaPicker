from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from core.extraction_plan import (
    DerivedArtifact,
    DerivedArtifactKind,
    DerivedArtifactStatus,
    ExtractionUnit,
    FormalExtractionRunPlan,
    MaterialRef,
    MediaType,
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

    def prepare_run_plan(self, project_id: str, run_plan: FormalExtractionRunPlan) -> FormalExtractionRunPlan:
        if run_plan.project_id != project_id:
            raise ValueError(
                f"run plan project_id mismatch: expected {project_id}, got {run_plan.project_id}"
            )
        artifacts_by_id = {artifact.artifact_id: artifact for artifact in run_plan.derived_artifacts}
        for episode in run_plan.episodes:
            transcript_units = [
                unit
                for unit in episode.units
                if unit.media_type in {MediaType.VIDEO, MediaType.AUDIO}
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
                    metadata={"scope": "episode"},
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
    ) -> list[TranscriptArtifactRequest]:
        requests: list[TranscriptArtifactRequest] = []
        for artifact in run_plan.derived_artifacts:
            if artifact.derived_kind != DerivedArtifactKind.TRANSCRIPT:
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
            if warning:
                artifact.warnings.append(warning)
            return

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
