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
from core.extraction_plan import ContentForm, MediaType  # noqa: E402
from core.extractor import Extractor  # noqa: E402
from core.models import ProjectPaths  # noqa: E402


@contextmanager
def _isolated_project(project_id: str) -> Iterator[ProjectPaths]:
    original_scanner_tree = source_scanner.ensure_project_tree
    original_extractor_tree = extractor_module.ensure_project_tree
    original_kb_tree = kb.ensure_project_tree
    with TemporaryDirectory(prefix="charapicker-multi-scan-") as temp_dir:
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

        def fake_ensure_project_tree(_project_id: str) -> ProjectPaths:
            assert _project_id == project_id
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


def _write_fixture(path: Path, payload: bytes = b"fixture") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def _assert_multi_material_scan() -> None:
    project_id = "validation-multi-material-scan"
    with _isolated_project(project_id) as paths:
        _write_fixture(paths.materials / "episode01.mp4")
        _write_fixture(paths.materials / "episode01.srt", b"1\n00:00:00,000 --> 00:00:01,000\nHi")
        _write_fixture(paths.materials / "novel.md", b"chapter one")
        _write_fixture(paths.materials / "setting_notes.txt", b"character setting")
        _write_fixture(paths.materials / "voice.wav")
        _write_fixture(paths.materials / "images" / "001.png")
        _write_fixture(paths.materials / "images" / "002.jpg")
        _write_fixture(paths.materials / "images" / "animation.gif")
        _write_fixture(paths.materials / "season_a" / "episode02.mkv")
        kb.source_manifest_path(project_id).write_text(
            json.dumps({"seasons": [{"episode_id": "must-not-be-read"}]}),
            encoding="utf-8",
        )

        legacy_scan = source_scanner._scan_formal_video_materials(project_id)
        episodes = source_scanner.scan_formal_materials(project_id)
        repeated = source_scanner.scan_formal_materials(project_id)
        assert [episode.model_dump(mode="json") for episode in episodes] == [
            episode.model_dump(mode="json") for episode in repeated
        ]

        video_units = [
            unit
            for episode in episodes
            for unit in episode.units
            if unit.media_type == MediaType.VIDEO
        ]
        legacy_video_paths = [
            chunk["source_path"]
            for season in legacy_scan["seasons"]
            for episode in season["episodes"]
            for chunk in episode["chunks"]
        ]
        assert [unit.material_ref.relative_path for unit in video_units] == legacy_video_paths

        episode01 = next(
            episode
            for episode in episodes
            if any(
                unit.material_ref.relative_path == "episode01.mp4" for unit in episode.units
            )
        )
        assert [unit.media_type for unit in episode01.units] == [MediaType.VIDEO, MediaType.TEXT]
        assert episode01.units[1].unit_kind == "subtitle_text"
        assert episode01.units[1].metadata["associated_video_episode"] is True
        assert ContentForm.SCRIPT in episode01.content_forms

        standalone_units = {
            unit.material_ref.relative_path: unit
            for episode in episodes
            for unit in episode.units
            if unit.media_type != MediaType.VIDEO
        }
        assert standalone_units["novel.md"].content_form == ContentForm.NOVEL
        assert standalone_units["novel.md"].material_ref.text_range is not None
        assert standalone_units["setting_notes.txt"].content_form == ContentForm.SETTING_BOOK
        assert standalone_units["voice.wav"].media_type == MediaType.AUDIO
        assert standalone_units["voice.wav"].handler_options["transcript_candidate"] is True
        assert standalone_units["images/001.png"].material_ref.page_range.start_page == 1
        assert standalone_units["images/002.jpg"].material_ref.page_range.start_page == 2
        gif_unit = standalone_units["images/animation.gif"]
        assert gif_unit.handler_options["formal_support"] == "unsupported"

        image_episode = next(
            episode
            for episode in episodes
            if any(unit.material_ref.relative_path == "images/001.png" for unit in episode.units)
        )
        assert image_episode.content_forms == [ContentForm.IMAGE_SET]
        assert image_episode.metadata["manga_candidate"] is True
        assert image_episode.metadata["warnings"] == [
            "images/animation.gif: animated_image_not_supported"
        ]

        plan = Extractor().prepare_formal_extraction_run_plan(project_id)
        assert set(plan.media_types) == {
            MediaType.VIDEO,
            MediaType.IMAGE,
            MediaType.AUDIO,
            MediaType.TEXT,
        }
        assert "images/animation.gif: animated_image_not_supported" in plan.warnings
        assert plan.metadata["scan_type"] == source_scanner.FORMAL_MATERIAL_SCAN_TYPE

        plan_path = kb.save_extraction_run_plan(project_id, plan)
        loaded = kb.load_extraction_run_plan(project_id, plan.run_id)
        assert plan_path.exists()
        assert loaded.unit_count == plan.unit_count
        assert loaded.warnings == plan.warnings
        assert json.loads(kb.source_manifest_path(project_id).read_text(encoding="utf-8")) == {
            "seasons": [{"episode_id": "must-not-be-read"}]
        }


def main() -> None:
    _assert_multi_material_scan()
    print("multi-material scanner validation passed")


if __name__ == "__main__":
    main()
