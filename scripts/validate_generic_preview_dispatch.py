from __future__ import annotations

import base64
import sys
from collections.abc import Iterator, Sequence
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
from core.extraction_ai import FormalExtractionJsonResult  # noqa: E402
from core.extractor import Extractor  # noqa: E402
from core.image_unit_handler import ImageUnitHandler, ImageUnitHandlerConfig  # noqa: E402
from core.models import (  # noqa: E402
    ChunkExtractionResult,
    EpisodeTranscript,
    ExtractionArtifactStage,
    ProjectConfig,
    ProjectPaths,
    TranscriptMetadata,
    TranscriptSegment,
    TranscriptSource,
)
from core.preview_sampling import (  # noqa: E402
    PreviewCandidateKind,
    collect_preview_candidates,
    run_plan_for_preview_unit,
)
from core.text_unit_handler import TextUnitHandler, TextUnitHandlerConfig  # noqa: E402
from core.transcript_provider import TranscriptProvider  # noqa: E402
from utils.ai_model_middleware import ModelCallRequest  # noqa: E402
from utils.audio_transcription import TranscriptionOptions  # noqa: E402
from utils.cloud_model_presets import CloudModelPreset  # noqa: E402


_PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9Z0X8AAAAASUVORK5CYII="
)


@contextmanager
def _isolated_project(project_id: str) -> Iterator[ProjectPaths]:
    original_scanner_tree = source_scanner.ensure_project_tree
    original_extractor_tree = extractor_module.ensure_project_tree
    original_kb_tree = kb.ensure_project_tree
    original_provider_tree = transcript_provider_module.ensure_project_tree
    with TemporaryDirectory(prefix="charapicker-generic-preview-") as temp_dir:
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

        source_scanner.ensure_project_tree = fake_ensure_project_tree
        extractor_module.ensure_project_tree = fake_ensure_project_tree
        kb.ensure_project_tree = fake_ensure_project_tree
        transcript_provider_module.ensure_project_tree = fake_ensure_project_tree
        try:
            yield paths
        finally:
            source_scanner.ensure_project_tree = original_scanner_tree
            extractor_module.ensure_project_tree = original_extractor_tree
            kb.ensure_project_tree = original_kb_tree
            transcript_provider_module.ensure_project_tree = original_provider_tree


class _FakeStructuredModel:
    def __init__(self, *, fail_suffix: str = "") -> None:
        self.fail_suffix = fail_suffix
        self.requests: list[ModelCallRequest] = []

    def __call__(self, request: ModelCallRequest) -> FormalExtractionJsonResult:
        self.requests.append(request)
        source_path = str(request.metadata.get("source_path", ""))
        if self.fail_suffix and source_path.endswith(self.fail_suffix):
            raise ValueError(f"validation failure: {source_path}")
        return FormalExtractionJsonResult(
            payload={
                "facts": [f"fact:{source_path}"],
                "behavior_traits": [],
                "dialogue_style": [],
                "relationship_interactions": [],
                "conflicts": [],
                "character_state_changes": [],
                "insight_summary": f"summary:{source_path}",
                "evidence_refs": [],
            },
            content="{}",
            token_usage={"prompt_tokens": 6, "completion_tokens": 4, "total_tokens": 10},
            requested_output_tokens=request.max_tokens,
            finish_reason="stop",
            estimated_context_tokens=32,
            model_metadata={"validation": True},
        )


class _FakeTranscriptRunner:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(
        self,
        project_id: str,
        season_id: str,
        episode_id: str,
        material_paths: Sequence[Path],
        options: TranscriptionOptions,
    ) -> EpisodeTranscript:
        self.calls += 1
        transcript = EpisodeTranscript(
            source=TranscriptSource(
                material_path=str(material_paths[0]),
                material_paths=[str(path) for path in material_paths],
                material_time_ranges=[
                    {
                        "material_path": str(material_paths[0]),
                        "start_seconds": 0.0,
                        "end_seconds": 2.0,
                    }
                ],
                source_fingerprint="sha256:generic-preview",
                season_id=season_id,
                episode_id=episode_id,
            ),
            transcription=TranscriptMetadata(
                backend="validation",
                language=options.language,
                cache_key="sha256:generic-preview-cache",
            ),
            segments=[TranscriptSegment(start_seconds=0.0, end_seconds=2.0, text="Hello")],
            plain_text="Hello",
        )
        kb.save_episode_transcript(project_id, transcript)
        return transcript


def _preset() -> CloudModelPreset:
    return CloudModelPreset(
        name="validation",
        provider="openai",
        base_url="https://example.invalid/v1",
        api_key="validation-key",
        model_name="validation-model",
        context_window_tokens=8_192,
    )


def _assert_cost_sampling_failure_backfill_and_isolation() -> None:
    project_id = "validation-generic-preview"
    with _isolated_project(project_id) as paths:
        paths.materials.joinpath("a_dialogue.srt").write_text(
            "1\n00:00:00,000 --> 00:00:01,000\nOpening line\n",
            encoding="utf-8",
        )
        paths.materials.joinpath("b_notes.txt").write_text("Character notes", encoding="utf-8")
        paths.materials.joinpath("c_cover.png").write_bytes(_PNG_1X1)
        paths.materials.joinpath("d_deferred.vtt").write_text("WEBVTT\n", encoding="utf-8")
        paths.materials.joinpath("e_animated.gif").write_bytes(b"GIF89a")
        paths.materials.joinpath("z_clip.mp4").write_bytes(b"validation-video")

        extractor = Extractor()
        run_plan = extractor.prepare_formal_extraction_run_plan(project_id)
        candidates, skipped = collect_preview_candidates(
            run_plan,
            image_input_supported=True,
        )
        assert [candidate.kind for candidate in candidates] == [
            PreviewCandidateKind.TIMED_TEXT,
            PreviewCandidateKind.TEXT,
            PreviewCandidateKind.IMAGE,
            PreviewCandidateKind.VIDEO,
        ]
        assert {item.reason for item in skipped} == {
            "vtt_timed_text_not_supported",
            "animated_image_not_supported",
        }
        single_unit_plan = run_plan_for_preview_unit(run_plan, candidates[1].unit.unit_id)
        assert single_unit_plan.unit_count == 1
        assert single_unit_plan.all_units[0].unit_id == candidates[1].unit.unit_id

        text_model = _FakeStructuredModel(fail_suffix="a_dialogue.srt")
        image_model = _FakeStructuredModel()
        extractor._text_unit_handler = lambda _preset_value: TextUnitHandler(
            TextUnitHandlerConfig(max_input_chars=500, max_output_tokens=256),
            model_call=text_model,
        )
        extractor._image_unit_handler = lambda _preset_value: ImageUnitHandler(
            ImageUnitHandlerConfig(provider="openai"),
            model_call=image_model,
        )
        events: list[dict] = []
        output = extractor.run_preview_streaming(
            ProjectConfig(project_id=project_id),
            cloud_preset=_preset(),
            emit_event=events.append,
        )

        assert "summary:b_notes.txt" in output
        assert "summary:c_cover.png" in output
        assert "a_dialogue.srt" not in output
        assert len(text_model.requests) == 2
        assert len(image_model.requests) == 1
        assert any(event.get("meta", {}).get("reason") == "vtt_timed_text_not_supported" for event in events)
        assert any(event.get("meta", {}).get("reason") == "animated_image_not_supported" for event in events)
        assert any(
            event.get("status") == "warning"
            and event.get("meta", {}).get("relative_path") == "a_dialogue.srt"
            for event in events
        )

        preview_paths = kb.list_preview_chunk_result_paths(
            project_id,
            include_legacy_top_level=False,
        )
        assert len(preview_paths) == 2
        assert all(kb.is_preview_artifact_path(path) for path in preview_paths)
        assert not kb.list_full_chunk_result_paths(project_id, include_legacy_top_level=False)
        for preview_path in preview_paths:
            chunk = kb.load_chunk_result(preview_path)
            assert chunk.extraction_stage == ExtractionArtifactStage.PREVIEW
            assert kb.preview_episode_content_path(
                project_id,
                chunk.season_id,
                chunk.episode_id,
            ).is_file()
            assert not kb.episode_content_path(
                project_id,
                chunk.season_id,
                chunk.episode_id,
            ).exists()
        assert not kb.extraction_runs_root_path(project_id).exists()


def _assert_audio_preview_does_not_persist_formal_run_plan() -> None:
    project_id = "validation-generic-preview-audio"
    with _isolated_project(project_id) as paths:
        paths.materials.joinpath("voice.wav").write_bytes(b"RIFFvalidation-audio")
        runner = _FakeTranscriptRunner()
        model = _FakeStructuredModel()
        extractor = Extractor()
        extractor._transcript_provider = lambda: TranscriptProvider(transcribe=runner)
        extractor._text_unit_handler = lambda _preset_value: TextUnitHandler(
            TextUnitHandlerConfig(max_input_chars=500, max_output_tokens=256),
            model_call=model,
        )
        output = extractor.run_preview_streaming(
            ProjectConfig(project_id=project_id),
            cloud_preset=_preset(),
        )

        assert "summary:seasons/" in output
        assert runner.calls == 1
        assert kb.list_preview_chunk_result_paths(project_id, include_legacy_top_level=False)
        assert not kb.list_full_chunk_result_paths(project_id, include_legacy_top_level=False)
        assert not kb.extraction_runs_root_path(project_id).exists()


def _assert_candidate_attempt_cap() -> None:
    project_id = "validation-generic-preview-cap"
    with _isolated_project(project_id) as paths:
        for index in range(6):
            paths.materials.joinpath(f"notes_{index}.txt").write_text(
                f"Character notes {index}",
                encoding="utf-8",
            )
        extractor = Extractor()
        attempted_unit_ids: list[str] = []

        def fake_execute_candidate(
            _config: ProjectConfig,
            _run_plan: object,
            candidate: object,
            **_kwargs: object,
        ) -> tuple[int, dict[str, int], list[ChunkExtractionResult]]:
            attempted_unit_ids.append(candidate.unit.unit_id)  # type: ignore[attr-defined]
            return 0, {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}, []

        extractor._execute_preview_candidate = fake_execute_candidate  # type: ignore[method-assign]
        output = extractor.run_preview_streaming(
            ProjectConfig(project_id=project_id),
            cloud_preset=_preset(),
        )
        assert output == ""
        assert len(attempted_unit_ids) == 4


def _assert_video_candidate_uses_selected_path() -> None:
    project_id = "validation-generic-preview-video"
    with _isolated_project(project_id) as paths:
        video_path = paths.materials / "clip.mp4"
        video_path.write_bytes(b"validation-video")
        extractor = Extractor()
        selected_paths: list[Path] = []

        def fake_video_preview(
            config: ProjectConfig,
            **kwargs: object,
        ) -> tuple[int, dict[str, int], list[ChunkExtractionResult]]:
            assert config.project_id == project_id
            paths_value = kwargs.get("video_paths")
            assert isinstance(paths_value, list)
            selected_paths.extend(path for path in paths_value if isinstance(path, Path))
            chunk = ChunkExtractionResult(
                season_id="season_001",
                episode_id="episode_001",
                chunk_id="clip",
                extraction_stage=ExtractionArtifactStage.PREVIEW,
                run_type="preview_trial",
                source_path="clip.mp4",
                source_kind="video",
                insight_summary="summary:clip.mp4",
            )
            extractor.save_preview_chunk_extraction_result(project_id, chunk)
            return 1, {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}, [chunk]

        extractor._extract_preview_chunk_json_from_materials = fake_video_preview  # type: ignore[method-assign]
        output = extractor.run_preview_streaming(
            ProjectConfig(project_id=project_id),
            cloud_preset=_preset(),
        )
        assert "summary:clip.mp4" in output
        assert selected_paths == [video_path]
        assert not kb.list_full_chunk_result_paths(project_id, include_legacy_top_level=False)


def main() -> None:
    _assert_cost_sampling_failure_backfill_and_isolation()
    _assert_audio_preview_does_not_persist_formal_run_plan()
    _assert_candidate_attempt_cap()
    _assert_video_candidate_uses_selected_path()
    print("generic preview dispatch validation passed")


if __name__ == "__main__":
    main()
