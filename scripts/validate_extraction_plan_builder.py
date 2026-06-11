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
from core.extraction_plan import FormalExtractionMode, MediaType  # noqa: E402
from core.extractor import Extractor  # noqa: E402
from core.models import ExtractionMode, ProjectPaths  # noqa: E402


@contextmanager
def _isolated_material_tree(project_id: str) -> Iterator[ProjectPaths]:
    original_kb_ensure_project_tree = kb.ensure_project_tree
    original_ensure_project_tree = source_scanner.ensure_project_tree
    original_extractor_ensure_project_tree = extractor_module.ensure_project_tree
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
        try:
            yield paths
        finally:
            kb.ensure_project_tree = original_kb_ensure_project_tree
            source_scanner.ensure_project_tree = original_ensure_project_tree
            extractor_module.ensure_project_tree = original_extractor_ensure_project_tree


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
