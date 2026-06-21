from __future__ import annotations

import base64
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
from core.extraction_plan import MediaType, RegionRef  # noqa: E402
from core.extractor import Extractor  # noqa: E402
from core.image_unit_handler import (  # noqa: E402
    DEFAULT_IMAGE_OUTPUT_TOKENS_PER_IMAGE,
    ImageUnitHandler,
    ImageUnitHandlerConfig,
)
from core.models import ExtractionArtifactStage, ProjectConfig, ProjectPaths  # noqa: E402
from utils.ai_model_middleware import ModelCallRequest  # noqa: E402
from utils.cloud_model_presets import CloudModelPreset  # noqa: E402


PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9Z8gAAAABJRU5ErkJggg=="
)


@contextmanager
def _isolated_project(project_id: str) -> Iterator[ProjectPaths]:
    original_scanner_tree = source_scanner.ensure_project_tree
    original_extractor_tree = extractor_module.ensure_project_tree
    original_kb_tree = kb.ensure_project_tree
    with TemporaryDirectory(prefix="charapicker-image-unit-") as temp_dir:
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


class _FakeImageModel:
    def __init__(self) -> None:
        self.requests: list[ModelCallRequest] = []

    def __call__(self, request: ModelCallRequest) -> FormalExtractionJsonResult:
        self.requests.append(request)
        source_path = str(request.metadata.get("source_path", ""))
        return FormalExtractionJsonResult(
            payload={
                "facts": [f"visible:{source_path}"],
                "behavior_traits": [],
                "dialogue_style": [],
                "relationship_interactions": [],
                "conflicts": [],
                "character_state_changes": [],
                "insight_summary": f"image:{source_path}",
                "evidence_refs": [],
            },
            content="{}",
            token_usage={"prompt_tokens": 8, "completion_tokens": 4, "total_tokens": 12},
            requested_output_tokens=request.max_tokens,
            finish_reason="stop",
            estimated_context_tokens=40,
            model_metadata={"validation": True},
        )


def _preset(provider: str = "openai") -> CloudModelPreset:
    return CloudModelPreset(
        name="validation",
        provider=provider,
        base_url="https://example.invalid/v1",
        api_key="validation-key",
        model_name="validation-model",
        context_window_tokens=8_192,
    )


def _assert_material_validation() -> None:
    with TemporaryDirectory(prefix="charapicker-image-parse-") as temp_dir:
        root = Path(temp_dir)
        valid_path = root / "valid.png"
        invalid_path = root / "invalid.png"
        unsupported_path = root / "unsupported.bmp"
        valid_path.write_bytes(PNG_1X1)
        invalid_path.write_bytes(b"not-an-image")
        unsupported_path.write_bytes(b"BM")

        parsed = ImageUnitHandler().parse_material(valid_path)
        assert parsed.mime_type == "image/png"
        assert parsed.size_bytes == len(PNG_1X1)
        assert (parsed.width, parsed.height) == (1, 1)
        assert parsed.data_url.startswith("data:image/png;base64,")

        try:
            ImageUnitHandler().parse_material(invalid_path)
        except ValueError as exc:
            assert "signature" in str(exc)
        else:
            raise AssertionError("expected invalid PNG signature to fail")

        try:
            ImageUnitHandler().parse_material(unsupported_path)
        except ValueError as exc:
            assert "unsupported static image suffix" in str(exc)
        else:
            raise AssertionError("expected BMP to remain unsupported")

        try:
            ImageUnitHandler(ImageUnitHandlerConfig(max_image_bytes=8)).parse_material(valid_path)
        except ValueError as exc:
            assert "exceeds byte limit" in str(exc)
        else:
            raise AssertionError("expected oversized image to fail")


def _assert_scan_handler_and_workflows() -> None:
    project_id = "validation-image-unit"
    with _isolated_project(project_id) as paths:
        image_dir = paths.materials / "images"
        image_dir.mkdir()
        image_dir.joinpath("002.png").write_bytes(PNG_1X1)
        image_dir.joinpath("001.png").write_bytes(PNG_1X1)
        image_dir.joinpath("010.png").write_bytes(PNG_1X1)
        image_dir.joinpath("animation.gif").write_bytes(b"GIF89a")

        extractor = Extractor()
        run_plan = extractor.prepare_formal_extraction_run_plan(project_id)
        image_episode = next(
            episode
            for episode in run_plan.episodes
            if any(unit.media_type == MediaType.IMAGE for unit in episode.units)
        )
        assert [unit.material_ref.relative_path for unit in image_episode.units] == [
            "images/001.png",
            "images/002.png",
            "images/010.png",
            "images/animation.gif",
        ]
        assert image_episode.metadata["page_order"] == [
            "images/001.png",
            "images/002.png",
            "images/010.png",
            "images/animation.gif",
        ]
        assert image_episode.metadata["supported_page_count"] == 3
        assert image_episode.metadata["warnings"] == [
            "images/animation.gif: animated_image_not_supported"
        ]
        supported_units = [
            unit
            for unit in image_episode.units
            if unit.material_ref.relative_path.endswith(".png")
        ]
        gif_unit = next(
            unit
            for unit in image_episode.units
            if unit.material_ref.relative_path.endswith(".gif")
        )
        assert [unit.material_ref.page_range.start_page for unit in supported_units] == [1, 2, 3]
        assert [unit.material_ref.metadata["chapter_id"] for unit in supported_units] == [
            image_episode.episode_id,
            image_episode.episode_id,
            image_episode.episode_id,
        ]
        assert all(unit.handler_options["formal_support"] == "supported" for unit in supported_units)
        assert gif_unit.handler_options["formal_support"] == "unsupported"

        fake_model = _FakeImageModel()
        handler = ImageUnitHandler(
            ImageUnitHandlerConfig(provider="openai"),
            model_call=fake_model,
        )
        assert handler.supports(supported_units[0]) is True
        assert handler.supports(gif_unit) is False

        material_ref = supported_units[0].material_ref.model_copy(
            update={
                "region": RegionRef(x=0.1, y=0.2, width=0.5, height=0.6),
            }
        )
        region_unit = supported_units[0].model_copy(update={"material_ref": material_ref})
        execution = handler.execute(
            materials_root=paths.materials,
            unit=region_unit,
            season_id=image_episode.season_id,
            extraction_stage=ExtractionArtifactStage.PREVIEW,
            extraction_run_id="",
            run_type="preview_trial",
            backend="openai_compatible",
            model_name="validation-model",
            base_url="https://example.invalid/v1",
            api_key="validation-key",
        )
        assert len(execution.chunks) == 1
        chunk = execution.chunks[0]
        locator = chunk.source_trace["evidence_refs"][0]["locator"]
        assert locator["page_range"] == {"start_page": 1, "end_page": 1}
        assert locator["region"] == {
            "x": 0.1,
            "y": 0.2,
            "width": 0.5,
            "height": 0.6,
            "unit": "normalized",
        }
        assert locator["pixel_size"] == {"width": 1, "height": 1}
        assert chunk.evidence_refs == [
            "images/001.png#page=1&region=0.1,0.2,0.5,0.6,normalized"
        ]
        request = fake_model.requests[-1]
        assert request.max_tokens == DEFAULT_IMAGE_OUTPUT_TOKENS_PER_IMAGE
        assert request.metadata["output_budget_basis"] == "per_image"
        assert request.metadata["output_budget_source"] == "internal_default"
        assert isinstance(request.messages[-1].content, list)
        assert request.messages[-1].content[-1]["image_url"]["url"].startswith(
            "data:image/png;base64,"
        )

        skipped = extractor._extract_image_units(
            project_id,
            run_plan,
            preset=_preset("deepseek"),
            extraction_stage=ExtractionArtifactStage.PREVIEW,
            handler=handler,
        )
        assert skipped[0] == 0
        assert skipped[3]["skipped_chunks"] == 3

        workflow_handler = ImageUnitHandler(
            ImageUnitHandlerConfig(provider="openai"),
            model_call=fake_model,
        )
        extractor._image_unit_handler = lambda _preset_value: workflow_handler
        preview_output = extractor.run_preview_streaming(
            ProjectConfig(project_id=project_id),
            cloud_preset=_preset(),
        )
        assert "image:images/001.png" in preview_output
        assert "image:images/002.png" in preview_output

        full_chunks = extractor.run_full_extraction_streaming(
            ProjectConfig(project_id=project_id),
            cloud_preset=_preset(),
        )
        assert len(full_chunks) == 3
        assert all(chunk.source_kind == "image" for chunk in full_chunks)
        assert all(chunk.source_counts["images"] == 1 for chunk in full_chunks)
        episode_content = kb.load_episode_content(
            project_id,
            full_chunks[0].season_id,
            full_chunks[0].episode_id,
        )
        assert episode_content["source_kind"] == "image"
        assert len(episode_content["source_trace"]["material_refs"]) == 3


def main() -> None:
    _assert_material_validation()
    _assert_scan_handler_and_workflows()
    print("image unit handler validation passed")


if __name__ == "__main__":
    main()
