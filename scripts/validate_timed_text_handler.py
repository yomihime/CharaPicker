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
from core.models import ExtractionArtifactStage, ProjectConfig, ProjectPaths  # noqa: E402
from core.text_unit_handler import TextUnitHandler, TextUnitHandlerConfig  # noqa: E402
from core.timed_text_parser import parse_timed_text  # noqa: E402
from utils.ai_model_middleware import ModelCallRequest  # noqa: E402
from utils.cloud_model_presets import CloudModelPreset  # noqa: E402


SRT_TEXT = """1
00:00:01,250 --> 00:00:03,500
<i>Hello</i>

2
00:00:04,000 --> 00:00:05,750
World
"""

ASS_TEXT = """[Script Info]
Title: Validation

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:02.50,Default,Alice,0,0,0,,{\\i1}Hello\\Nthere
Dialogue: 0,0:00:03.00,0:00:04.00,Default,,0,0,0,,Unknown speaker line
"""


@contextmanager
def _isolated_project(project_id: str) -> Iterator[ProjectPaths]:
    original_scanner_tree = source_scanner.ensure_project_tree
    original_extractor_tree = extractor_module.ensure_project_tree
    original_kb_tree = kb.ensure_project_tree
    with TemporaryDirectory(prefix="charapicker-timed-text-") as temp_dir:
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
            token_usage={"prompt_tokens": 6, "completion_tokens": 3, "total_tokens": 9},
            requested_output_tokens=request.max_tokens,
            finish_reason="stop",
            estimated_context_tokens=30,
            model_metadata={"validation": True},
        )


def _preset() -> CloudModelPreset:
    return CloudModelPreset(
        name="validation",
        provider="openai",
        base_url="https://example.invalid/v1",
        api_key="validation-key",
        model_name="validation-model",
        context_window_tokens=8_192,
    )


def _assert_parsers() -> None:
    with TemporaryDirectory(prefix="charapicker-timed-parse-") as temp_dir:
        root = Path(temp_dir)
        srt_path = root / "episode.srt"
        ass_path = root / "episode.ass"
        vtt_path = root / "episode.vtt"
        srt = parse_timed_text(srt_path, SRT_TEXT)
        ass = parse_timed_text(ass_path, ASS_TEXT)

        assert srt.format_name == "srt"
        assert len(srt.segments) == 2
        assert srt.segments[0].source_line == 2
        assert srt.segments[0].start_seconds == 1.25
        assert srt.segments[0].end_seconds == 3.5
        assert srt.segments[0].text == "Hello"
        assert srt.segments[0].raw_text == "<i>Hello</i>"
        assert srt.segments[0].speaker == ""
        assert "speaker=unknown" in srt.text

        assert ass.format_name == "ass"
        assert len(ass.segments) == 2
        assert ass.segments[0].speaker == "Alice"
        assert ass.segments[0].text == "Hello\nthere"
        assert ass.segments[0].raw_text == r"{\i1}Hello\Nthere"
        assert ass.segments[1].speaker == ""
        assert "speaker=unknown" in ass.text

        try:
            parse_timed_text(vtt_path, "WEBVTT")
        except ValueError:
            pass
        else:
            raise AssertionError("expected VTT to remain unsupported")


def _assert_scan_and_extraction() -> None:
    project_id = "validation-timed-text"
    with _isolated_project(project_id) as paths:
        paths.materials.joinpath("episode01.mp4").write_bytes(b"video")
        paths.materials.joinpath("episode01.srt").write_text(SRT_TEXT, encoding="utf-8")
        paths.materials.joinpath("standalone.ass").write_text(ASS_TEXT, encoding="utf-8")
        paths.materials.joinpath("deferred.vtt").write_text("WEBVTT", encoding="utf-8")

        extractor = Extractor()
        run_plan = extractor.prepare_formal_extraction_run_plan(project_id)
        video_episode = next(
            episode
            for episode in run_plan.episodes
            if any(unit.media_type == MediaType.VIDEO for unit in episode.units)
        )
        associated_srt = next(
            unit
            for unit in video_episode.units
            if unit.material_ref.relative_path == "episode01.srt"
        )
        assert associated_srt.unit_kind == "subtitle_text"
        assert associated_srt.metadata["associated_video_episode"] is True
        assert associated_srt.handler_options["speaker_policy"] == "explicit_only"

        text_units = {
            unit.material_ref.relative_path: unit
            for episode in run_plan.episodes
            for unit in episode.units
            if unit.media_type == MediaType.TEXT
        }
        assert text_units["standalone.ass"].metadata["timed_text_supported"] is True
        assert text_units["deferred.vtt"].metadata["timed_text_supported"] is False
        assert text_units["deferred.vtt"].handler_options["formal_support"] == "unsupported"
        assert "deferred.vtt: vtt_timed_text_not_supported" in run_plan.warnings

        fake_model = _FakeTextModel()
        handler = TextUnitHandler(
            TextUnitHandlerConfig(
                max_input_chars=500,
                overlap_chars=20,
                max_chunks_per_unit=8,
                max_output_tokens=256,
            ),
            model_call=fake_model,
        )
        assert handler.supports(associated_srt) is True
        assert handler.supports(text_units["standalone.ass"]) is True
        assert handler.supports(text_units["deferred.vtt"]) is False

        result = handler.execute(
            materials_root=paths.materials,
            unit=associated_srt,
            season_id=video_episode.season_id,
            extraction_stage=ExtractionArtifactStage.PREVIEW,
            extraction_run_id="",
            run_type="preview_trial",
            backend="openai_compatible",
            model_name="validation-model",
            base_url="https://example.invalid/v1",
            api_key="validation-key",
        )
        assert len(result.chunks) == 1
        chunk = result.chunks[0]
        material_ref = chunk.source_trace["material_refs"][0]
        locator = chunk.source_trace["evidence_refs"][0]["locator"]
        assert material_ref["time_range"] == {"start_seconds": 1.25, "end_seconds": 5.75}
        assert locator["source_line_start"] == 2
        assert locator["source_line_end"] == 6
        assert locator["timed_text_segments"][0]["raw_text"] == "<i>Hello</i>"
        assert locator["timed_text_segments"][0]["speaker"] == ""
        assert chunk.evidence_refs == ["episode01.srt#time=1.250-5.750&lines=2-6"]
        user_prompt = str(fake_model.requests[-1].messages[-1].content)
        assert "speaker=unknown" in user_prompt
        assert "不得根据台词内容猜测或强行归属" in user_prompt

        paths.materials.joinpath("episode01.mp4").unlink()
        paths.materials.joinpath("episode01.srt").unlink()
        workflow_handler = TextUnitHandler(
            TextUnitHandlerConfig(max_input_chars=500, max_output_tokens=256),
            model_call=fake_model,
        )
        extractor._text_unit_handler = lambda _preset_value: workflow_handler
        preview_output = extractor.run_preview_streaming(
            ProjectConfig(project_id=project_id),
            cloud_preset=_preset(),
        )
        assert "summary:standalone.ass" in preview_output

        full_chunks = extractor.run_full_extraction_streaming(
            ProjectConfig(project_id=project_id),
            cloud_preset=_preset(),
        )
        assert len(full_chunks) == 1
        full_chunk = full_chunks[0]
        assert full_chunk.source_kind == "text"
        assert full_chunk.source_counts["timed_text_segments"] == 2
        episode_content = kb.load_episode_content(
            project_id,
            full_chunk.season_id,
            full_chunk.episode_id,
        )
        assert episode_content["source_kind"] == "text"
        assert episode_content["source_trace"]["material_refs"][0]["time_range"]


def main() -> None:
    _assert_parsers()
    _assert_scan_and_extraction()
    print("timed text handler validation passed")


if __name__ == "__main__":
    main()
