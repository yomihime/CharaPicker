from __future__ import annotations

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
from core.formal_dispatch import FormalDispatchKind, build_formal_dispatch_plan  # noqa: E402
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
from core.text_unit_handler import TextUnitHandler, TextUnitHandlerConfig  # noqa: E402
from core.transcript_provider import TranscriptProvider  # noqa: E402
from utils.ai_model_middleware import ModelCallRequest  # noqa: E402
from utils.audio_transcription import TranscriptionOptions  # noqa: E402
from utils.cloud_model_presets import CloudModelPreset  # noqa: E402


@contextmanager
def _isolated_project(project_id: str) -> Iterator[ProjectPaths]:
    original_scanner_tree = source_scanner.ensure_project_tree
    original_extractor_tree = extractor_module.ensure_project_tree
    original_kb_tree = kb.ensure_project_tree
    original_provider_tree = transcript_provider_module.ensure_project_tree
    with TemporaryDirectory(prefix="charapicker-formal-dispatch-") as temp_dir:
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


class _FakeTextModel:
    def __init__(self) -> None:
        self.requests: list[ModelCallRequest] = []

    def __call__(self, request: ModelCallRequest) -> FormalExtractionJsonResult:
        self.requests.append(request)
        source_path = str(request.metadata.get("source_path", ""))
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
            token_usage={"prompt_tokens": 5, "completion_tokens": 4, "total_tokens": 9},
            requested_output_tokens=request.max_tokens,
            finish_reason="stop",
            estimated_context_tokens=24,
            model_metadata={"validation": True},
        )


class _FakeTranscriptRunner:
    def __call__(
        self,
        project_id: str,
        season_id: str,
        episode_id: str,
        material_paths: Sequence[Path],
        options: TranscriptionOptions,
    ) -> EpisodeTranscript:
        transcript = EpisodeTranscript(
            source=TranscriptSource(
                material_path=str(material_paths[0]),
                material_paths=[str(path) for path in material_paths],
                source_fingerprint="sha256:formal-dispatch",
                season_id=season_id,
                episode_id=episode_id,
            ),
            transcription=TranscriptMetadata(
                backend="validation",
                language=options.language,
                cache_key="sha256:formal-dispatch-cache",
            ),
            segments=[TranscriptSegment(start_seconds=0.0, end_seconds=1.0, text="Line")],
            plain_text="Line",
        )
        kb.save_episode_transcript(project_id, transcript)
        return transcript


def _preset(provider: str = "openai") -> CloudModelPreset:
    return CloudModelPreset(
        name="validation",
        provider=provider,
        base_url="https://example.invalid/v1",
        api_key="validation-key",
        model_name="validation-model",
        context_window_tokens=8_192,
    )


def _write_mixed_materials(paths: ProjectPaths) -> None:
    paths.materials.joinpath("clip.mp4").write_bytes(b"validation-video")
    paths.materials.joinpath("notes.txt").write_text("Character notes", encoding="utf-8")
    paths.materials.joinpath("dialogue.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nHello\n",
        encoding="utf-8",
    )
    paths.materials.joinpath("deferred.vtt").write_text("WEBVTT\n", encoding="utf-8")
    paths.materials.joinpath("cover.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    paths.materials.joinpath("voice.wav").write_bytes(b"RIFFvalidation-audio")


def _assert_dispatch_plan_covers_current_handlers() -> None:
    project_id = "validation-formal-dispatch-plan"
    with _isolated_project(project_id) as paths:
        _write_mixed_materials(paths)
        extractor = Extractor()
        run_plan = extractor.prepare_formal_extraction_run_plan(project_id)
        plan = build_formal_dispatch_plan(run_plan, image_input_supported=True)
        assert plan.has_handler(FormalDispatchKind.VIDEO)
        assert plan.has_handler(FormalDispatchKind.TEXT)
        assert plan.has_handler(FormalDispatchKind.IMAGE)
        assert plan.has_handler(FormalDispatchKind.AUDIO_TRANSCRIPT)
        assert any(item.reason == "vtt_timed_text_not_supported" for item in plan.unsupported_units)

        provider = TranscriptProvider(transcribe=_FakeTranscriptRunner())
        extractor.ensure_episode_transcripts_from_run_plan(
            project_id,
            run_plan,
            include_video=False,
            include_audio=True,
            provider=provider,
        )
        plan = build_formal_dispatch_plan(run_plan, image_input_supported=True)
        assert plan.handler_unit_count(FormalDispatchKind.TEXT) >= 3


def _assert_unsupported_units_do_not_block_supported_text() -> None:
    project_id = "validation-formal-dispatch-unsupported"
    with _isolated_project(project_id) as paths:
        paths.materials.joinpath("notes.txt").write_text("Character notes", encoding="utf-8")
        paths.materials.joinpath("deferred.vtt").write_text("WEBVTT\n", encoding="utf-8")
        paths.materials.joinpath("cover.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        extractor = Extractor()
        fake_model = _FakeTextModel()
        extractor._text_unit_handler = lambda _preset_value: TextUnitHandler(
            TextUnitHandlerConfig(max_input_chars=500, max_output_tokens=256),
            model_call=fake_model,
        )
        events: list[dict] = []
        chunks = extractor.run_full_extraction_streaming(
            ProjectConfig(project_id=project_id),
            cloud_preset=_preset("deepseek"),
            emit_event=events.append,
        )

        assert len(chunks) == 1
        assert chunks[0].source_path == "notes.txt"
        assert fake_model.requests
        unsupported_reasons = {
            event.get("meta", {}).get("reason")
            for event in events
            if event.get("status") == "warning"
        }
        assert "vtt_timed_text_not_supported" in unsupported_reasons
        assert "model_image_input_not_supported" in unsupported_reasons
        assert kb.list_full_chunk_result_paths(project_id, include_legacy_top_level=False)


def _assert_video_still_uses_legacy_video_path() -> None:
    project_id = "validation-formal-dispatch-video"
    with _isolated_project(project_id) as paths:
        paths.materials.joinpath("clip.mp4").write_bytes(b"validation-video")
        extractor = Extractor()
        recorded_inputs: list[dict] = []
        events: list[dict] = []

        def fake_extract_full_video_units(
            _config: ProjectConfig,
            _manifest: dict,
            *,
            chunk_inputs: list[dict],
            **_kwargs: object,
        ) -> tuple[int, dict[str, int], list[ChunkExtractionResult], dict[str, int]]:
            recorded_inputs.extend(chunk_inputs)
            chunk = ChunkExtractionResult(
                season_id=chunk_inputs[0]["season_id"],
                episode_id=chunk_inputs[0]["episode_id"],
                chunk_id=chunk_inputs[0]["chunk_id"],
                extraction_stage=ExtractionArtifactStage.FULL,
                extraction_run_id=chunk_inputs[0]["extraction_run_id"],
                run_type="formal_extraction",
                source_path=chunk_inputs[0]["source_path"],
                source_kind="video",
                source_trace=chunk_inputs[0]["source_trace"],
                insight_summary="summary:clip.mp4",
            )
            extractor.save_chunk_extraction_result(project_id, chunk)
            return (
                1,
                {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                [chunk],
                {
                    "succeeded_chunks": 1,
                    "skipped_chunks": 0,
                    "failed_chunks": 0,
                    "succeeded_episodes": 0,
                    "skipped_episodes": 0,
                    "failed_episodes": 0,
                    "succeeded_seasons": 0,
                    "skipped_seasons": 0,
                    "failed_seasons": 0,
                },
            )

        extractor._extract_full_video_units = fake_extract_full_video_units  # type: ignore[method-assign]
        chunks = extractor.run_full_extraction_streaming(
            ProjectConfig(project_id=project_id),
            cloud_preset=_preset(),
            emit_event=events.append,
        )

        assert chunks
        assert recorded_inputs
        first_input = recorded_inputs[0]
        assert first_input["source_path"] == "clip.mp4"
        assert first_input["source_trace"]["unit_refs"]
        assert any(
            "video" in event.get("meta", {}).get("dispatch_handlers", [])
            for event in events
        )
        assert kb.list_full_chunk_result_paths(project_id, include_legacy_top_level=False)


def main() -> None:
    _assert_dispatch_plan_covers_current_handlers()
    _assert_unsupported_units_do_not_block_supported_text()
    _assert_video_still_uses_legacy_video_path()
    print("formal dispatch validation passed")


if __name__ == "__main__":
    main()
