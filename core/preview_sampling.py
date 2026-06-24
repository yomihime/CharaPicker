from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from core.extraction_plan import (
    ContentForm,
    EpisodePlan,
    ExtractionUnit,
    FormalExtractionRunPlan,
    MediaType,
)
from core.image_unit_handler import ImageUnitHandler
from core.text_unit_handler import TextUnitHandler


class PreviewCandidateKind(str, Enum):
    TIMED_TEXT = "timed_text"
    TRANSCRIPT = "transcript"
    TEXT = "text"
    IMAGE = "image"
    AUDIO_TRANSCRIPT = "audio_transcript"
    VIDEO = "video"


@dataclass(frozen=True)
class PreviewCandidate:
    season_id: str
    unit: ExtractionUnit
    kind: PreviewCandidateKind
    cost_rank: int


@dataclass(frozen=True)
class PreviewSkippedUnit:
    season_id: str
    unit: ExtractionUnit
    reason: str


def collect_preview_candidates(
    run_plan: FormalExtractionRunPlan,
    *,
    image_input_supported: bool,
) -> tuple[list[PreviewCandidate], list[PreviewSkippedUnit]]:
    """Return executable preview candidates ordered from cheapest to most expensive."""

    text_handler = TextUnitHandler()
    image_handler = ImageUnitHandler()
    candidates: list[PreviewCandidate] = []
    skipped: list[PreviewSkippedUnit] = []
    transcript_episodes = {
        (episode.season_id, episode.episode_id)
        for episode in run_plan.episodes
        if any(unit.unit_kind == "transcript_text" for unit in episode.units)
    }

    for episode in run_plan.episodes:
        for unit in episode.units:
            candidate = _candidate_for_unit(
                episode.season_id,
                unit,
                text_handler=text_handler,
                image_handler=image_handler,
                image_input_supported=image_input_supported,
                transcript_already_available=(
                    episode.season_id,
                    episode.episode_id,
                )
                in transcript_episodes,
            )
            if isinstance(candidate, PreviewSkippedUnit):
                skipped.append(candidate)
            elif candidate is not None:
                candidates.append(candidate)

    candidates.sort(key=_candidate_sort_key)
    skipped.sort(key=_skipped_sort_key)
    return candidates, skipped


def run_plan_for_preview_unit(
    run_plan: FormalExtractionRunPlan,
    unit_id: str,
) -> FormalExtractionRunPlan:
    """Copy a run plan while retaining only the episode and unit selected for preview."""

    episodes: list[EpisodePlan] = []
    selected_unit: ExtractionUnit | None = None
    for episode in run_plan.episodes:
        unit = next((item for item in episode.units if item.unit_id == unit_id), None)
        if unit is None:
            continue
        selected_unit = unit.model_copy(deep=True)
        episodes.append(
            episode.model_copy(
                deep=True,
                update={
                    "content_forms": [selected_unit.content_form],
                    "units": [selected_unit],
                    "derived_artifact_ids": list(selected_unit.derived_refs),
                },
            )
        )
        break

    if selected_unit is None:
        raise ValueError(f"preview unit does not exist in run plan: {unit_id}")

    selected_artifact_ids = set(selected_unit.derived_refs)
    selected_artifacts = [
        artifact.model_copy(deep=True)
        for artifact in run_plan.derived_artifacts
        if artifact.artifact_id in selected_artifact_ids
        or unit_id in artifact.coverage.get("unit_refs", [])
    ]
    return run_plan.model_copy(
        deep=True,
        update={
            "media_types": [selected_unit.media_type],
            "content_forms": [selected_unit.content_form],
            "episodes": episodes,
            "derived_artifacts": selected_artifacts,
            "warnings": [],
            "metadata": {
                **run_plan.metadata,
                "run_type": "preview_trial",
                "preview_source_run_id": run_plan.run_id,
            },
        },
    )


def _candidate_for_unit(
    season_id: str,
    unit: ExtractionUnit,
    *,
    text_handler: TextUnitHandler,
    image_handler: ImageUnitHandler,
    image_input_supported: bool,
    transcript_already_available: bool,
) -> PreviewCandidate | PreviewSkippedUnit | None:
    if unit.media_type == MediaType.TEXT:
        if not text_handler.supports(unit):
            return _skipped_unit(season_id, unit)
        if unit.unit_kind == "transcript_text":
            return PreviewCandidate(season_id, unit, PreviewCandidateKind.TRANSCRIPT, 10)
        if unit.unit_kind in {"subtitle_text", "lyrics_text"} or unit.content_form == ContentForm.SCRIPT:
            return PreviewCandidate(season_id, unit, PreviewCandidateKind.TIMED_TEXT, 8)
        return PreviewCandidate(season_id, unit, PreviewCandidateKind.TEXT, 12)

    if unit.media_type == MediaType.IMAGE:
        if not image_handler.supports(unit):
            return _skipped_unit(season_id, unit)
        if not image_input_supported:
            return PreviewSkippedUnit(season_id, unit, "model_image_input_not_supported")
        return PreviewCandidate(season_id, unit, PreviewCandidateKind.IMAGE, 20)

    if unit.media_type == MediaType.AUDIO:
        if transcript_already_available:
            return None
        if unit.handler_options.get("transcript_candidate") is True:
            return PreviewCandidate(season_id, unit, PreviewCandidateKind.AUDIO_TRANSCRIPT, 30)
        return _skipped_unit(season_id, unit)

    if unit.media_type == MediaType.VIDEO:
        return PreviewCandidate(season_id, unit, PreviewCandidateKind.VIDEO, 40)

    return _skipped_unit(season_id, unit)


def _skipped_unit(season_id: str, unit: ExtractionUnit) -> PreviewSkippedUnit:
    reason = str(unit.material_ref.metadata.get("support_reason", "")).strip()
    return PreviewSkippedUnit(
        season_id,
        unit,
        reason or "preview_handler_not_available",
    )


def _candidate_sort_key(candidate: PreviewCandidate) -> tuple[int, str, str, str, str]:
    unit = candidate.unit
    return (
        candidate.cost_rank,
        candidate.season_id,
        unit.episode_id,
        unit.material_ref.relative_path.lower(),
        unit.unit_id,
    )


def _skipped_sort_key(item: PreviewSkippedUnit) -> tuple[str, str, str, str]:
    unit = item.unit
    return (
        item.season_id,
        unit.episode_id,
        unit.material_ref.relative_path.lower(),
        unit.unit_id,
    )
