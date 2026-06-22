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
from core.extraction_ai import FormalExtractionJsonResult  # noqa: E402
from core.extraction_plan import MediaType  # noqa: E402
from core.extractor import Extractor  # noqa: E402
from core.formal_dispatch import (  # noqa: E402
    FormalDispatchKind,
    build_formal_dispatch_plan,
)
from core.native_media_insight_handler import (  # noqa: E402
    NATIVE_AUDIO_UNSUPPORTED_REASON,
    NATIVE_VIDEO_UNSUPPORTED_REASON,
    NativeMediaInsightHandler,
    NativeMediaInsightHandlerConfig,
)
from core.models import (  # noqa: E402
    ChunkExtractionResult,
    ExtractionArtifactStage,
    ProjectConfig,
    ProjectPaths,
)
from utils.ai_model_middleware import ModelCallError, ModelCallRequest  # noqa: E402
from utils.cloud_model_presets import CloudModelPreset  # noqa: E402


@contextmanager
def _isolated_project(project_id: str) -> Iterator[ProjectPaths]:
    original_scanner_tree = source_scanner.ensure_project_tree
    original_extractor_tree = extractor_module.ensure_project_tree
    original_kb_tree = kb.ensure_project_tree
    with TemporaryDirectory(prefix="charapicker-native-media-") as temp_dir:
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
        try:
            yield paths
        finally:
            source_scanner.ensure_project_tree = original_scanner_tree
            extractor_module.ensure_project_tree = original_extractor_tree
            kb.ensure_project_tree = original_kb_tree


class _FakeNativeModel:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.requests: list[ModelCallRequest] = []

    def __call__(self, request: ModelCallRequest) -> FormalExtractionJsonResult:
        self.requests.append(request)
        if self.fail:
            raise ModelCallError("native media request failed for validation")
        media_type = str(request.metadata.get("media_type", ""))
        payload = {
            "facts": [f"native fact:{media_type}"],
            "auditory_summary": ["calm voice", "distant footsteps"],
            "visual_summary": ["dim hallway"],
            "tone": ["tense"],
            "environment_sounds": ["rain"],
            "music": ["low strings"],
            "offscreen_voices": ["unknown speaker"],
            "behavior_traits": [],
            "dialogue_style": [],
            "relationship_interactions": [],
            "conflicts": [],
            "character_state_changes": [],
            "insight_summary": f"native summary:{media_type}",
            "evidence_refs": [],
        }
        return FormalExtractionJsonResult(
            payload=payload,
            content="{}",
            token_usage={"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
            requested_output_tokens=request.max_tokens,
            finish_reason="stop",
            estimated_context_tokens=42,
            model_metadata={"validation": True},
        )


def _preset(provider: str) -> CloudModelPreset:
    return CloudModelPreset(
        name="validation",
        provider=provider,
        base_url="https://example.invalid/v1",
        api_key="validation-key",
        model_name="validation-model",
        context_window_tokens=8_192,
    )


def _audio_video_units(project_id: str) -> tuple[ProjectPaths, object, object]:
    paths = kb.ensure_project_tree(project_id)
    paths.materials.joinpath("voice.wav").write_bytes(b"RIFFvalidation-audio")
    paths.materials.joinpath("clip.mp4").write_bytes(b"validation-video")
    run_plan = Extractor().prepare_formal_extraction_run_plan(project_id)
    audio_unit = next(unit for unit in run_plan.all_units if unit.media_type == MediaType.AUDIO)
    video_unit = next(unit for unit in run_plan.all_units if unit.media_type == MediaType.VIDEO)
    return paths, audio_unit, video_unit


def _assert_supported_audio_and_video_requests() -> None:
    project_id = "validation-native-media-supported"
    with _isolated_project(project_id) as paths:
        paths, audio_unit, video_unit = _audio_video_units(project_id)
        audio_model = _FakeNativeModel()
        video_model = _FakeNativeModel()
        handler = NativeMediaInsightHandler(
            NativeMediaInsightHandlerConfig(provider="aliyunBailian", video_fps=1.5),
            audio_model_call=audio_model,
            video_model_call=video_model,
        )

        audio_result = handler.execute(
            materials_root=paths.materials,
            unit=audio_unit,
            season_id="season_materials",
            extraction_stage=ExtractionArtifactStage.FULL,
            extraction_run_id="run-validation",
            run_type="formal_extraction",
            backend="openai_compatible",
            model_name="validation-model",
            base_url="https://example.invalid/v1",
            api_key="validation-key",
        )
        assert audio_model.requests
        audio_request = audio_model.requests[0]
        assert audio_request.metadata["native_media_capability"] == "audio_understanding"
        assert audio_request.metadata["does_not_replace_transcript"] is True
        assert audio_request.metadata["transcript_policy"] == "supplement_only"
        audio_parts = audio_request.messages[-1].content
        assert isinstance(audio_parts, list)
        assert any(part.get("type") == "audio_url" for part in audio_parts)
        audio_chunk = audio_result.chunks[0]
        assert audio_chunk.source_kind == "audio"
        assert audio_chunk.model_metadata["native_media_insight"] is True
        assert audio_chunk.model_metadata["does_not_replace_transcript"] is True
        assert audio_chunk.source_trace["derived_artifact_refs"] == []
        assert "auditory_summary: calm voice" in audio_chunk.facts

        video_result = handler.execute(
            materials_root=paths.materials,
            unit=video_unit,
            season_id="season_001",
            extraction_stage=ExtractionArtifactStage.FULL,
            extraction_run_id="run-validation",
            run_type="formal_extraction",
            backend="dashscope",
            model_name="validation-model",
            base_url="https://example.invalid/v1",
            api_key="validation-key",
        )
        assert video_model.requests
        video_request = video_model.requests[0]
        assert video_request.metadata["native_media_capability"] == "native_video"
        video_parts = video_request.messages[-1].content
        assert isinstance(video_parts, list)
        assert any("video" in part for part in video_parts)
        assert video_result.chunks[0].source_kind == "video"


def _assert_model_specific_audio_support() -> None:
    project_id = "validation-native-media-model-capability"
    with _isolated_project(project_id):
        _paths, audio_unit, video_unit = _audio_video_units(project_id)
        text_video_handler = NativeMediaInsightHandler(
            NativeMediaInsightHandlerConfig(
                provider="aliyunBailian",
                model_name="qwen3.6-plus",
            )
        )
        assert text_video_handler.support_status(audio_unit).supported is False
        assert (
            text_video_handler.support_status(audio_unit).reason
            == NATIVE_AUDIO_UNSUPPORTED_REASON
        )
        assert text_video_handler.support_status(video_unit).supported is True

        omni_handler = NativeMediaInsightHandler(
            NativeMediaInsightHandlerConfig(
                provider="aliyunBailian",
                model_name="qwen2.5-omni-7b",
            )
        )
        assert omni_handler.support_status(audio_unit).supported is True

        run_plan = Extractor().prepare_formal_extraction_run_plan(project_id)
        dispatch = build_formal_dispatch_plan(
            run_plan,
            image_input_supported=True,
            native_media_handler=text_video_handler,
        )
        assert dispatch.handler_unit_count(FormalDispatchKind.AUDIO_TRANSCRIPT) == 1
        assert dispatch.handler_unit_count(FormalDispatchKind.NATIVE_MEDIA) == 1
        assert any(
            item.unit.unit_id == audio_unit.unit_id
            and item.reason == NATIVE_AUDIO_UNSUPPORTED_REASON
            for item in dispatch.unsupported_units
        )


def _assert_unsupported_provider_status() -> None:
    project_id = "validation-native-media-unsupported"
    with _isolated_project(project_id) as paths:
        paths.materials.joinpath("voice.wav").write_bytes(b"RIFFvalidation-audio")
        paths.materials.joinpath("clip.mp4").write_bytes(b"validation-video")
        extractor = Extractor()
        run_plan = extractor.prepare_formal_extraction_run_plan(project_id)
        events: list[dict] = []
        created, _usage, chunks, stats = extractor._extract_native_media_insight_units(
            project_id,
            run_plan,
            preset=_preset("openai"),
            extraction_stage=ExtractionArtifactStage.FULL,
            emit_event=events.append,
        )
        assert created == 0
        assert chunks == []
        assert stats["skipped_chunks"] == 2
        reasons = {event.get("meta", {}).get("reason") for event in events}
        assert NATIVE_AUDIO_UNSUPPORTED_REASON in reasons
        assert NATIVE_VIDEO_UNSUPPORTED_REASON in reasons


def _assert_request_failure_does_not_block_video_result() -> None:
    project_id = "validation-native-media-failure"
    with _isolated_project(project_id) as paths:
        paths.materials.joinpath("clip.mp4").write_bytes(b"validation-video")
        extractor = Extractor()

        def fake_extract_full_video_units(
            _config: ProjectConfig,
            _manifest: dict,
            *,
            chunk_inputs: list[dict],
            **_kwargs: object,
        ) -> tuple[int, dict[str, int], list[ChunkExtractionResult], dict[str, int]]:
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
                insight_summary="video path still succeeded",
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

        failing_native_model = _FakeNativeModel(fail=True)
        extractor._extract_full_video_units = fake_extract_full_video_units  # type: ignore[method-assign]
        extractor._native_media_insight_handler = lambda _preset_value: NativeMediaInsightHandler(
            NativeMediaInsightHandlerConfig(provider="aliyunBailian"),
            video_model_call=failing_native_model,
        )
        events: list[dict] = []
        chunks = extractor.run_full_extraction_streaming(
            ProjectConfig(project_id=project_id),
            cloud_preset=_preset("aliyunBailian"),
            emit_event=events.append,
        )

        assert len(chunks) == 1
        assert chunks[0].insight_summary == "video path still succeeded"
        assert failing_native_model.requests
        assert any(
            event.get("meta", {}).get("reason") == "native_media_request_failed"
            for event in events
        )


def main() -> None:
    _assert_supported_audio_and_video_requests()
    _assert_model_specific_audio_support()
    _assert_unsupported_provider_status()
    _assert_request_failure_does_not_block_video_result()
    print("native media insight handler validation passed")


if __name__ == "__main__":
    main()
