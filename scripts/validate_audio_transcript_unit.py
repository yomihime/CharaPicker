from __future__ import annotations

import json
import sys
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace


APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from core import extractor as extractor_module  # noqa: E402
from core import knowledge_base as kb  # noqa: E402
from core import source_scanner  # noqa: E402
from core import transcript_provider as transcript_provider_module  # noqa: E402
from core.extraction_ai import FormalExtractionJsonResult  # noqa: E402
from core.extraction_plan import (  # noqa: E402
    DerivedArtifactKind,
    DerivedArtifactStatus,
    MaterialOrigin,
    MediaType,
)
from core.extractor import Extractor  # noqa: E402
from core.models import (  # noqa: E402
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
from utils import audio_transcription as audio_transcription_module  # noqa: E402
from utils.ai_model_middleware import ModelCallRequest  # noqa: E402
from utils.audio_transcription import AudioTranscriptionError, TranscriptionOptions  # noqa: E402
from utils.cloud_model_presets import CloudModelPreset  # noqa: E402


@contextmanager
def _isolated_project(project_id: str) -> Iterator[ProjectPaths]:
    original_scanner_tree = source_scanner.ensure_project_tree
    original_extractor_tree = extractor_module.ensure_project_tree
    original_kb_tree = kb.ensure_project_tree
    original_provider_tree = transcript_provider_module.ensure_project_tree
    original_audio_tree = audio_transcription_module.ensure_project_tree
    with TemporaryDirectory(prefix="charapicker-audio-transcript-") as temp_dir:
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
        audio_transcription_module.ensure_project_tree = fake_ensure_project_tree
        try:
            yield paths
        finally:
            source_scanner.ensure_project_tree = original_scanner_tree
            extractor_module.ensure_project_tree = original_extractor_tree
            kb.ensure_project_tree = original_kb_tree
            transcript_provider_module.ensure_project_tree = original_provider_tree
            audio_transcription_module.ensure_project_tree = original_audio_tree


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
                "dialogue_style": ["measured"],
                "relationship_interactions": [],
                "conflicts": [],
                "character_state_changes": [],
                "insight_summary": f"summary:{source_path}",
                "evidence_refs": [],
            },
            content="{}",
            token_usage={"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10},
            requested_output_tokens=request.max_tokens,
            finish_reason="stop",
            estimated_context_tokens=36,
            model_metadata={"validation": True},
        )


class _FakeTranscriptRunner:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
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
        if self.fail:
            raise AudioTranscriptionError("No usable whisper.cpp runtime was found.")
        transcript = EpisodeTranscript(
            source=TranscriptSource(
                material_path=str(material_paths[0]),
                material_paths=[str(path) for path in material_paths],
                material_time_ranges=[
                    {
                        "material_path": str(material_paths[0]),
                        "start_seconds": 0.0,
                        "end_seconds": 3.0,
                    }
                ],
                source_fingerprint="sha256:validation",
                season_id=season_id,
                episode_id=episode_id,
            ),
            transcription=TranscriptMetadata(
                backend="whisper.cpp",
                language=options.language,
                cache_key="sha256:validation-cache",
            ),
            segments=[
                TranscriptSegment(start_seconds=0.0, end_seconds=1.25, text="Hello"),
                TranscriptSegment(start_seconds=1.25, end_seconds=3.0, text="World"),
            ],
            plain_text="Hello\nWorld",
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


def _assert_audio_transcription_cache() -> None:
    project_id = "validation-audio-cache"
    with _isolated_project(project_id) as paths:
        audio_path = paths.materials / "episode.wav"
        audio_path.write_bytes(b"RIFFvalidation-wave")
        runtime_path = paths.root / "whisper.exe"
        model_path = paths.root / "model.bin"
        runtime_path.write_bytes(b"runtime")
        model_path.write_bytes(b"model")

        original_status = audio_transcription_module.whisper_status
        original_run = audio_transcription_module._run_whisper_cli
        call_count = 0

        def fake_status() -> SimpleNamespace:
            return SimpleNamespace(
                runtime_ready=True,
                runtime_path=runtime_path,
                model_ready=True,
                model_path=model_path,
            )

        def fake_run_whisper_cli(**kwargs: object) -> None:
            nonlocal call_count
            call_count += 1
            output_prefix = Path(str(kwargs["output_prefix"]))
            output_prefix.with_suffix(".json").write_text(
                json.dumps(
                    {
                        "transcription": [
                            {
                                "text": "cached line",
                                "timestamps": {
                                    "from": "00:00:00.000",
                                    "to": "00:00:01.500",
                                },
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            output_prefix.with_suffix(".txt").write_text("cached line", encoding="utf-8")

        audio_transcription_module.whisper_status = fake_status
        audio_transcription_module._run_whisper_cli = fake_run_whisper_cli
        try:
            first = audio_transcription_module.transcribe_episode_audio(
                project_id,
                "season_materials",
                "episode_audio",
                audio_path,
            )
            second = audio_transcription_module.transcribe_episode_audio(
                project_id,
                "season_materials",
                "episode_audio",
                audio_path,
            )
        finally:
            audio_transcription_module.whisper_status = original_status
            audio_transcription_module._run_whisper_cli = original_run

        assert call_count == 1
        assert first.transcription.cache_key == second.transcription.cache_key
        assert second.plain_text == "cached line"


def _assert_artifact_unit_and_workflows() -> None:
    project_id = "validation-audio-transcript"
    with _isolated_project(project_id) as paths:
        paths.materials.joinpath("drama.wav").write_bytes(b"RIFFaudio")
        extractor = Extractor()
        run_plan = extractor.prepare_formal_extraction_run_plan(project_id)
        audio_unit = next(
            unit
            for episode in run_plan.episodes
            for unit in episode.units
            if unit.media_type == MediaType.AUDIO
        )
        assert audio_unit.handler_options["transcript_candidate"] is True
        assert audio_unit.handler_options["formal_support"] == "supported"

        runner = _FakeTranscriptRunner()
        provider = TranscriptProvider(transcribe=runner)
        provider.prepare_run_plan(
            project_id,
            run_plan,
            include_video=False,
            include_audio=True,
        )
        assert len(run_plan.derived_artifacts) == 1
        artifact = run_plan.derived_artifacts[0]
        assert artifact.derived_kind == DerivedArtifactKind.TRANSCRIPT
        assert artifact.content_kind == MediaType.TEXT
        assert artifact.status == DerivedArtifactStatus.PENDING
        assert artifact.source_refs[0].source_media_type == MediaType.AUDIO
        assert artifact.coverage["unit_refs"] == [audio_unit.unit_id]
        requests = provider.collect_requests(
            project_id,
            run_plan,
            include_video=False,
            include_audio=True,
        )
        assert len(requests) == 1
        assert requests[0].material_paths == [paths.materials / "drama.wav"]

        transcripts = extractor.ensure_episode_transcripts_from_run_plan(
            project_id,
            run_plan,
            include_video=False,
            include_audio=True,
            provider=provider,
        )
        assert len(transcripts) == 1
        assert artifact.status == DerivedArtifactStatus.READY
        assert artifact.coverage["segment_count"] == 2
        assert artifact.coverage["text_chars"] == len("Hello\nWorld")
        assert artifact.coverage["time_range"] == {
            "start_seconds": 0.0,
            "end_seconds": 3.0,
        }
        transcript_unit = next(
            unit
            for episode in run_plan.episodes
            for unit in episode.units
            if unit.unit_kind == "transcript_text"
        )
        assert transcript_unit.media_type == MediaType.TEXT
        assert transcript_unit.origin == MaterialOrigin.DERIVED
        assert transcript_unit.material_ref.origin == MaterialOrigin.DERIVED
        assert transcript_unit.material_ref.relative_path == artifact.artifact_path
        assert transcript_unit.derived_refs == [artifact.artifact_id]
        assert transcript_unit.handler_options["storage_root"] == "knowledge_base"
        assert transcript_unit.material_ref.metadata["source_material_ids"] == [
            audio_unit.material_ref.material_id
        ]
        loaded = kb.load_episode_transcript(
            project_id,
            transcript_unit.metadata["season_id"],
            transcript_unit.episode_id,
        )
        assert loaded.transcription.cache_key == "sha256:validation-cache"

        fake_model = _FakeTextModel()
        text_handler = TextUnitHandler(
            TextUnitHandlerConfig(max_input_chars=500, max_output_tokens=256),
            model_call=fake_model,
        )
        extractor._transcript_provider = lambda: provider
        extractor._text_unit_handler = lambda _preset_value: text_handler
        preview_output = extractor.run_preview_streaming(
            ProjectConfig(project_id=project_id),
            cloud_preset=_preset(),
        )
        assert "summary:seasons/" in preview_output

        full_chunks = extractor.run_full_extraction_streaming(
            ProjectConfig(project_id=project_id),
            cloud_preset=_preset(),
        )
        assert len(full_chunks) == 1
        chunk = full_chunks[0]
        assert chunk.extraction_stage == ExtractionArtifactStage.FULL
        assert chunk.source_kind == "text"
        assert chunk.source_counts["transcript_segments"] == 2
        assert chunk.source_trace["derived_artifact_refs"]
        assert chunk.source_trace["material_refs"][0]["origin"] == "derived"
        locator = chunk.source_trace["evidence_refs"][0]["locator"]
        assert locator["time_range"] == {"start_seconds": 0.0, "end_seconds": 3.0}
        assert "source_line_start" not in locator
        assert chunk.evidence_refs == [
            f"{artifact.artifact_path}#time=0.000-3.000"
        ]
        user_prompt = str(fake_model.requests[-1].messages[-1].content)
        assert "每段转写文本的时间范围" in user_prompt
        assert "不得根据台词内容猜测或强行归属" in user_prompt

        stale_plan = run_plan.model_copy(deep=True)
        failing_provider = TranscriptProvider(transcribe=_FakeTranscriptRunner(fail=True))
        extractor.ensure_episode_transcripts_from_run_plan(
            project_id,
            stale_plan,
            force_rebuild=True,
            include_video=False,
            include_audio=True,
            provider=failing_provider,
        )
        assert stale_plan.derived_artifacts[0].status == DerivedArtifactStatus.FAILED
        assert not any(
            unit.unit_kind == "transcript_text"
            for episode in stale_plan.episodes
            for unit in episode.units
        )


def _assert_transcription_failure_does_not_block_text() -> None:
    project_id = "validation-audio-transcript-failure"
    with _isolated_project(project_id) as paths:
        paths.materials.joinpath("voice.wav").write_bytes(b"RIFFaudio")
        paths.materials.joinpath("notes.txt").write_text("Character notes", encoding="utf-8")
        failing_provider = TranscriptProvider(transcribe=_FakeTranscriptRunner(fail=True))
        fake_model = _FakeTextModel()
        text_handler = TextUnitHandler(
            TextUnitHandlerConfig(max_input_chars=500, max_output_tokens=256),
            model_call=fake_model,
        )
        extractor = Extractor()
        extractor._transcript_provider = lambda: failing_provider
        extractor._text_unit_handler = lambda _preset_value: text_handler
        events: list[dict] = []
        chunks = extractor.run_full_extraction_streaming(
            ProjectConfig(project_id=project_id),
            cloud_preset=_preset(),
            emit_event=events.append,
        )
        assert len(chunks) == 1
        assert chunks[0].source_path == "notes.txt"
        assert any(event.get("status") == "warning" for event in events)
        saved_plan = kb.load_extraction_run_plan(project_id, chunks[0].extraction_run_id)
        artifact = next(
            item
            for item in saved_plan.derived_artifacts
            if item.derived_kind == DerivedArtifactKind.TRANSCRIPT
        )
        assert artifact.status == DerivedArtifactStatus.FAILED
        assert artifact.warnings == ["No usable whisper.cpp runtime was found."]
        assert not any(
            unit.unit_kind == "transcript_text"
            for episode in saved_plan.episodes
            for unit in episode.units
        )


def main() -> None:
    _assert_audio_transcription_cache()
    _assert_artifact_unit_and_workflows()
    _assert_transcription_failure_does_not_block_text()
    print("audio transcript unit validation passed")


if __name__ == "__main__":
    main()
