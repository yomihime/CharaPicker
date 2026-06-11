from __future__ import annotations

import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from core import extractor as extractor_module  # noqa: E402
from core import knowledge_base as kb  # noqa: E402
from core import source_scanner  # noqa: E402
from core import transcript_provider as transcript_provider_module  # noqa: E402
from core.extraction_plan import (  # noqa: E402
    DerivedArtifactKind,
    DerivedArtifactStatus,
    FormalExtractionMode,
    MediaType,
)
from core.extractor import Extractor  # noqa: E402
from core.models import (  # noqa: E402
    EpisodeTranscript,
    ExtractionMode,
    ProjectPaths,
    TranscriptMetadata,
    TranscriptSource,
)
from core.transcript_provider import TranscriptProvider  # noqa: E402


@contextmanager
def _isolated_material_tree(project_id: str) -> Iterator[ProjectPaths]:
    original_kb_ensure_project_tree = kb.ensure_project_tree
    original_ensure_project_tree = source_scanner.ensure_project_tree
    original_extractor_ensure_project_tree = extractor_module.ensure_project_tree
    original_transcript_provider_ensure_project_tree = transcript_provider_module.ensure_project_tree
    with TemporaryDirectory(prefix="charapicker-plan-builder-") as temp_dir:
        root = Path(temp_dir) / "projects" / project_id
        paths = ProjectPaths(
            root=root,
            raw=root / "raw",
            materials=root / "materials",
            cache=root / "cache",
            knowledge_base=root / "knowledge_base",
            output=root / "output",
            config=root / "config.json",
            facts=root / "knowledge_base" / "facts.json",
            targeted_insights=root / "knowledge_base" / "targeted_insights.json",
        )
        for directory in (
            paths.raw,
            paths.materials,
            paths.cache,
            paths.knowledge_base,
            paths.output,
        ):
            directory.mkdir(parents=True, exist_ok=True)

        def fake_ensure_project_tree(requested_project_id: str) -> ProjectPaths:
            assert requested_project_id == project_id
            return paths

        kb.ensure_project_tree = fake_ensure_project_tree
        source_scanner.ensure_project_tree = fake_ensure_project_tree
        extractor_module.ensure_project_tree = fake_ensure_project_tree
        transcript_provider_module.ensure_project_tree = fake_ensure_project_tree
        try:
            yield paths
        finally:
            kb.ensure_project_tree = original_kb_ensure_project_tree
            source_scanner.ensure_project_tree = original_ensure_project_tree
            extractor_module.ensure_project_tree = original_extractor_ensure_project_tree
            transcript_provider_module.ensure_project_tree = (
                original_transcript_provider_ensure_project_tree
            )


def _write_material(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"validation")


def _assert_video_materials_build_run_plan() -> None:
    project_id = "validation-plan-builder"
    with _isolated_material_tree(project_id) as paths:
        _write_material(paths.materials / "Season 01" / "Episode 01" / "segment_0001.mp4")
        _write_material(paths.materials / "Season 01" / "Episode 01" / "segment_0002.mp4")
        _write_material(paths.materials / "standalone.mp4")

        original_legacy_scanner = source_scanner.scan_formal_video_materials

        def fail_if_legacy_public_scanner_is_used(_project_id: str) -> dict:
            raise AssertionError("prepare_formal_extraction_run_plan used legacy public scanner")

        source_scanner.scan_formal_video_materials = fail_if_legacy_public_scanner_is_used
        try:
            plan = Extractor().prepare_formal_extraction_run_plan(
                project_id,
                mode=ExtractionMode.FAST,
            )
        finally:
            source_scanner.scan_formal_video_materials = original_legacy_scanner

        assert plan.mode == FormalExtractionMode.FAST
        assert plan.media_types == [MediaType.VIDEO]
        assert plan.unit_count == 3
        assert len(plan.episodes) == 2
        assert {unit.media_type for unit in plan.all_units} == {MediaType.VIDEO}
        assert all(unit.material_ref.relative_path for unit in plan.all_units)

        chunk_inputs = Extractor()._collect_formal_video_chunk_inputs_from_run_plan(project_id, plan)
        assert len(chunk_inputs) == plan.unit_count
        assert all(chunk_input["unit_ref"] for chunk_input in chunk_inputs)
        assert all(
            chunk_input["material_ref"]["source_media_type"] == "video"
            for chunk_input in chunk_inputs
        )
        assert all(chunk_input["source_trace"]["unit_refs"] for chunk_input in chunk_inputs)
        assert all(chunk_input["source_trace"]["material_refs"] for chunk_input in chunk_inputs)

        TranscriptProvider().prepare_run_plan(project_id, plan)
        transcript_artifacts = [
            artifact
            for artifact in plan.derived_artifacts
            if artifact.derived_kind == DerivedArtifactKind.TRANSCRIPT
        ]
        assert len(transcript_artifacts) == len(plan.episodes)
        assert all(artifact.content_kind == MediaType.TEXT for artifact in transcript_artifacts)
        assert all(artifact.status == DerivedArtifactStatus.PENDING for artifact in transcript_artifacts)
        assert all(artifact.source_refs for artifact in transcript_artifacts)
        assert all(artifact.artifact_path.endswith("episode_transcript.json") for artifact in transcript_artifacts)
        assert all(unit.derived_refs for unit in plan.all_units)

        requests = TranscriptProvider().collect_requests(project_id, plan)
        assert len(requests) == len(transcript_artifacts)
        assert all(request.material_paths for request in requests)

        calls: list[dict] = []

        def fake_transcribe(project_id: str, season_id: str, episode_id: str, material_paths, options):
            calls.append(
                {
                    "project_id": project_id,
                    "season_id": season_id,
                    "episode_id": episode_id,
                    "material_count": len(material_paths),
                    "language": options.language,
                }
            )
            return EpisodeTranscript(
                source=TranscriptSource(
                    season_id=season_id,
                    episode_id=episode_id,
                    material_paths=[str(path) for path in material_paths],
                ),
                transcription=TranscriptMetadata(backend="fake", language=options.language),
            )

        fake_provider = TranscriptProvider(transcribe=fake_transcribe)
        transcript = fake_provider.ensure_transcript(project_id, requests[0], language="zh")
        fake_provider.mark_status(plan, requests[0].artifact_id, DerivedArtifactStatus.READY)
        assert transcript.transcription.language == "zh"
        assert calls[0]["material_count"] >= 1
        assert any(artifact.status == DerivedArtifactStatus.READY for artifact in plan.derived_artifacts)

        payload = plan.model_dump(mode="json")
        assert payload["mode"] == "fast"
        assert payload["media_types"] == ["video"]
        assert "source_manifest" not in payload
        assert "video_input_mode" not in payload

        plan_path = kb.save_extraction_run_plan(project_id, plan)
        assert plan_path == kb.extraction_run_plan_path(project_id, plan.run_id)
        assert plan_path.exists()
        loaded_plan = kb.load_extraction_run_plan(project_id, plan.run_id)
        assert loaded_plan.run_id == plan.run_id
        assert loaded_plan.unit_count == plan.unit_count

        kb.initialize_structure_from_run_plan(project_id, loaded_plan)
        for episode in loaded_plan.episodes:
            assert kb.chunks_root_path(project_id, episode.season_id, episode.episode_id).is_dir()
        assert not kb.source_manifest_path(project_id).exists()


def main() -> None:
    _assert_video_materials_build_run_plan()
    print("extraction plan builder validation passed")


if __name__ == "__main__":
    main()
