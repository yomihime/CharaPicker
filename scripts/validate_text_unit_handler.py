from __future__ import annotations

import json
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
from utils.ai_model_middleware import ModelCallRequest  # noqa: E402
from utils.chunker import chunk_text, chunk_text_with_ranges  # noqa: E402
from utils.cloud_model_presets import CloudModelPreset  # noqa: E402


@contextmanager
def _isolated_project(project_id: str) -> Iterator[ProjectPaths]:
    original_scanner_tree = source_scanner.ensure_project_tree
    original_extractor_tree = extractor_module.ensure_project_tree
    original_kb_tree = kb.ensure_project_tree
    with TemporaryDirectory(prefix="charapicker-text-handler-") as temp_dir:
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
                "behavior_traits": ["careful"],
                "dialogue_style": ["brief"],
                "relationship_interactions": ["A trusts B"],
                "conflicts": [],
                "character_state_changes": ["A becomes calmer"],
                "insight_summary": f"summary:{source_path}",
                "evidence_refs": [],
            },
            content="{}",
            token_usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            requested_output_tokens=request.max_tokens,
            finish_reason="stop",
            estimated_context_tokens=20,
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


def _assert_chunking() -> None:
    assert chunk_text("abcdef", 2) == ["ab", "cd", "ef"]
    result = chunk_text_with_ranges(
        "第一段文字。\n\n第二段文字。\n\n第三段文字。",
        max_chars=12,
        overlap_chars=2,
        max_chunks=8,
    )
    assert len(result.chunks) >= 2
    for chunk in result.chunks:
        assert chunk.text == "第一段文字。\n\n第二段文字。\n\n第三段文字。"[
            chunk.start_offset : chunk.end_offset
        ]
    limited = chunk_text_with_ranges(
        "0123456789" * 10,
        max_chars=20,
        overlap_chars=4,
        max_chunks=2,
    )
    assert limited.truncated is True
    assert len(limited.chunks) == 2
    assert limited.warnings[0].startswith("text_chunk_limit_reached:")


def _assert_parsing() -> None:
    with TemporaryDirectory(prefix="charapicker-text-parse-") as temp_dir:
        root = Path(temp_dir)
        txt_path = root / "novel.txt"
        md_path = root / "notes.md"
        json_path = root / "setting.json"
        scalar_path = root / "scalar.json"
        invalid_path = root / "invalid.json"
        txt_path.write_text("正文", encoding="utf-8")
        md_path.write_bytes("设定".encode("gb18030"))
        json_path.write_text('{"b": 2, "a": [1]}', encoding="utf-8")
        scalar_path.write_text('"scalar"', encoding="utf-8")
        invalid_path.write_text("{invalid", encoding="utf-8")

        handler = TextUnitHandler()
        assert handler.parse_material(txt_path).text == "正文"
        parsed_md = handler.parse_material(md_path)
        assert parsed_md.text == "设定"
        assert parsed_md.warnings == ["text_decoded_with_fallback:gb18030"]
        assert handler.parse_material(json_path).text == json.dumps(
            {"a": [1], "b": 2}, ensure_ascii=False, indent=2, sort_keys=True
        )
        for path in (scalar_path, invalid_path):
            try:
                handler.parse_material(path)
            except ValueError:
                continue
            raise AssertionError(f"expected controlled JSON rejection: {path.name}")


def _assert_text_only_workflow() -> None:
    project_id = "validation-text-only"
    with _isolated_project(project_id) as paths:
        paths.materials.joinpath("novel.md").write_text(
            "第一章\n\n角色 A 遇见角色 B。\n\n" * 12,
            encoding="utf-8",
        )
        paths.materials.joinpath("legacy.mp4").write_bytes(b"video-placeholder")

        extractor = Extractor()
        run_plan = extractor.prepare_formal_extraction_run_plan(project_id)
        assert any(unit.media_type == MediaType.VIDEO for unit in run_plan.all_units)
        text_inputs = extractor._collect_text_units_from_run_plan(run_plan)
        assert len(text_inputs) == 1
        assert text_inputs[0][1].material_ref.relative_path == "novel.md"

        fake_model = _FakeTextModel()
        handler = TextUnitHandler(
            TextUnitHandlerConfig(
                max_input_chars=80,
                overlap_chars=10,
                max_chunks_per_unit=4,
                max_output_tokens=256,
            ),
            model_call=fake_model,
        )
        unit = text_inputs[0][1]
        direct = handler.execute(
            source_root=paths.materials,
            unit=unit,
            season_id=text_inputs[0][0],
            extraction_stage=ExtractionArtifactStage.PREVIEW,
            extraction_run_id="",
            run_type="preview_trial",
            backend="openai_compatible",
            model_name="validation-model",
            base_url="https://example.invalid/v1",
            api_key="validation-key",
            chunk_limit=2,
        )
        assert len(direct.chunks) == 2
        first_chunk = direct.chunks[0]
        first_material = first_chunk.source_trace["material_refs"][0]
        assert first_chunk.source_kind == "text"
        assert first_material["source_media_type"] == "text"
        assert first_material["text_range"]["start_offset"] == 0
        assert first_material["text_range"]["end_offset"] > 0
        assert first_chunk.source_trace["evidence_refs"][0]["locator"]["text_range"]
        assert first_chunk.evidence_refs[0].startswith("novel.md#text=")
        assert first_chunk.aggregation_warnings[0].startswith("text_chunk_limit_reached:")
        assert fake_model.requests[0].purpose == "preview_text_unit_extraction"
        assert fake_model.requests[0].max_tokens == 256

        paths.materials.joinpath("legacy.mp4").unlink()
        workflow_handler = TextUnitHandler(
            TextUnitHandlerConfig(
                max_input_chars=160,
                overlap_chars=20,
                max_chunks_per_unit=8,
                max_output_tokens=256,
            ),
            model_call=fake_model,
        )
        extractor._text_unit_handler = lambda _preset_value: workflow_handler
        preview_output = extractor.run_preview_streaming(
            ProjectConfig(project_id=project_id),
            cloud_preset=_preset(),
        )
        assert "summary:novel.md" in preview_output
        preview_paths = kb.list_preview_chunk_result_paths(
            project_id,
            include_legacy_top_level=False,
        )
        assert preview_paths
        assert not kb.list_full_chunk_result_paths(project_id, include_legacy_top_level=False)

        full_chunks = extractor.run_full_extraction_streaming(
            ProjectConfig(project_id=project_id),
            cloud_preset=_preset(),
        )
        assert full_chunks
        assert all(chunk.source_kind == "text" for chunk in full_chunks)
        assert kb.list_full_chunk_result_paths(project_id, include_legacy_top_level=False)
        episode_content = kb.load_episode_content(
            project_id,
            full_chunks[0].season_id,
            full_chunks[0].episode_id,
        )
        episode_summary = kb.load_episode_summary(
            project_id,
            full_chunks[0].season_id,
            full_chunks[0].episode_id,
        )
        season_content = kb.load_season_content(project_id, full_chunks[0].season_id)
        season_summary = kb.load_season_summary(project_id, full_chunks[0].season_id)
        for payload in (episode_content, episode_summary, season_content, season_summary):
            assert payload["source_kind"] == "text"
            assert payload["media_types"] == ["text"]
            assert payload["source_trace"]["material_refs"]


def main() -> None:
    _assert_chunking()
    _assert_parsing()
    _assert_text_only_workflow()
    print("text unit handler validation passed")


if __name__ == "__main__":
    main()
