from __future__ import annotations

import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from pydantic import ValidationError  # noqa: E402

from core.extraction_plan import (  # noqa: E402
    ContentForm,
    DerivedArtifact,
    DerivedArtifactKind,
    DerivedArtifactStatus,
    EpisodePlan,
    EvidenceRef,
    ExtractionUnit,
    FormalExtractionRunPlan,
    MaterialRef,
    MediaType,
    SourceTrace,
    TimeRange,
)


def _assert_media_type_vocabulary() -> None:
    assert {item.value for item in MediaType} == {"video", "image", "audio", "text"}
    assert "transcript" not in {item.value for item in MediaType}


def _build_sample_plan() -> FormalExtractionRunPlan:
    material_ref = MaterialRef(
        material_id="material-video-001",
        relative_path="video/sample/episode-01/chunk-001.mp4",
        source_media_type=MediaType.VIDEO,
        content_form=ContentForm.ANIME,
        fingerprint="sha256:sample",
        time_range=TimeRange(start_seconds=0, end_seconds=120),
    )
    transcript = DerivedArtifact(
        artifact_id="artifact-transcript-001",
        derived_kind=DerivedArtifactKind.TRANSCRIPT,
        content_kind=MediaType.TEXT,
        source_refs=[material_ref],
        artifact_path="derived/transcripts/episode-01/chunk-001.json",
        coverage={"time_range": {"start_seconds": 0, "end_seconds": 120}},
        generation={"provider": "validation"},
        status=DerivedArtifactStatus.READY,
    )
    unit = ExtractionUnit(
        unit_id="unit-video-001",
        episode_id="episode-01",
        media_type=MediaType.VIDEO,
        content_form=ContentForm.ANIME,
        material_ref=material_ref,
        unit_kind="video_chunk",
        derived_refs=[transcript.artifact_id],
        budget_hint={"max_context_tokens": 4096},
        model_requirements={"supports_video": True},
        context_policy={"include_derived_text": True},
    )
    episode = EpisodePlan(
        season_id="season-01",
        episode_id="episode-01",
        display_title="Episode 01",
        sort_key="001",
        content_forms=[ContentForm.ANIME],
        units=[unit],
        derived_artifact_ids=[transcript.artifact_id],
    )
    return FormalExtractionRunPlan(
        project_id="validation-project",
        media_types=[MediaType.VIDEO],
        content_forms=[ContentForm.ANIME],
        episodes=[episode],
        derived_artifacts=[transcript],
        model_profile_id="validation-profile",
    )


def _assert_transcript_is_derived_text(plan: FormalExtractionRunPlan) -> None:
    transcript = plan.derived_artifacts[0]
    assert transcript.derived_kind == DerivedArtifactKind.TRANSCRIPT
    assert transcript.content_kind == MediaType.TEXT
    assert transcript.content_kind in MediaType
    assert transcript.derived_kind.value not in {item.value for item in MediaType}


def _assert_serialization_shape(plan: FormalExtractionRunPlan) -> None:
    payload = plan.model_dump(mode="json")
    assert payload["run_id"].startswith("run-")
    assert payload["media_types"] == ["video"]
    assert payload["content_forms"] == ["anime"]
    assert payload["derived_artifacts"][0]["derived_kind"] == "transcript"
    assert payload["derived_artifacts"][0]["content_kind"] == "text"
    assert "source_manifest" not in payload
    assert "manifest_path" not in payload
    assert "video_input_mode" not in payload
    assert "transcript_required" not in payload
    assert "transcript_ready" not in payload
    assert plan.unit_count == 1
    assert plan.all_units[0].derived_refs == ["artifact-transcript-001"]


def _assert_source_trace_shape(plan: FormalExtractionRunPlan) -> None:
    material_ref = plan.all_units[0].material_ref
    evidence = EvidenceRef(
        evidence_id="evidence-001",
        material_ref=material_ref,
        unit_ref="unit-video-001",
        derived_artifact_ref="artifact-transcript-001",
        locator={"time_range": {"start_seconds": 12, "end_seconds": 18}},
        quote_policy="short_excerpt_only",
        confidence=0.9,
    )
    trace = SourceTrace(
        material_refs=[material_ref],
        unit_refs=["unit-video-001"],
        derived_artifact_refs=["artifact-transcript-001"],
        evidence_refs=[evidence],
        source_breakdown={"material": 1, "derived_artifact": 1},
    )
    payload = trace.model_dump(mode="json")
    assert payload["material_refs"][0]["source_media_type"] == "video"
    assert payload["derived_artifact_refs"] == ["artifact-transcript-001"]
    assert payload["evidence_refs"][0]["confidence"] == 0.9


def _assert_old_fields_are_rejected() -> None:
    try:
        FormalExtractionRunPlan(project_id="validation-project", source_manifest={})
    except ValidationError:
        return
    raise AssertionError("FormalExtractionRunPlan accepted old source_manifest field")


def main() -> None:
    _assert_media_type_vocabulary()
    plan = _build_sample_plan()
    _assert_transcript_is_derived_text(plan)
    _assert_serialization_shape(plan)
    _assert_source_trace_shape(plan)
    _assert_old_fields_are_rejected()
    print("extraction plan model validation passed")


if __name__ == "__main__":
    main()
