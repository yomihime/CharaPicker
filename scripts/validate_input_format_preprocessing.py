from __future__ import annotations

import json
import os
import shutil
import stat
import sys
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from utils.material_preprocessing import (  # noqa: E402
    PREPROCESSING_MANIFEST_SCHEMA_VERSION,
    PreprocessingLimits,
    PreprocessingRequest,
    build_project_preprocessing_request,
    complete_preprocessing_manifest_for_raw,
    current_preprocessing_manifest_for_raw,
    preprocess_project_source,
    preprocess_material,
    preprocessing_material_metadata_index,
)
from utils.media_types import (  # noqa: E402
    InputFormatSupportState,
    InputPreprocessorKey,
    input_format_profile,
    is_import_supported_source,
    is_preprocessable_source,
    project_input_file_patterns,
)
from core.source_scanner import scan_formal_materials  # noqa: E402
from core.extraction_plan import FormalExtractionRunPlan  # noqa: E402
from core.models import (  # noqa: E402
    ProjectConfig,
    SourceProcessingConfig,
    SourceProcessingPreset,
)
import utils.material_processing_middleware as processing_middleware  # noqa: E402
from utils.material_processing_middleware import (  # noqa: E402
    MaterialProcessingError,
    process_source_request,
    source_processing_requires_ffmpeg,
)
from utils.source_importer import (  # noqa: E402
    clean_raw_sources,
    link_raw_sources_to_materials,
    remove_project_sources,
    remove_raw_sources,
)
import utils.paths as path_utils  # noqa: E402


def _request(
    root: Path,
    source: Path,
    *,
    preprocessor_key: InputPreprocessorKey = "zip",
    limits: PreprocessingLimits | None = None,
    cancelled=None,
) -> PreprocessingRequest:
    return PreprocessingRequest(
        source_path=source,
        source_raw_path=f"raw/{source.name}",
        output_root=root / "materials" / "derived_inputs" / "fixture_abc123",
        output_root_reference="materials/derived_inputs/fixture_abc123",
        manifest_path=root / "cache" / "material_preprocessing" / "abc123.json",
        preprocessor_key=preprocessor_key,
        limits=limits or PreprocessingLimits(),
        cancelled=cancelled,
        staging_root=root / "cache" / "material_preprocessing" / "tmp",
    )


def _warning_codes(result) -> set[str]:
    return {warning.code for warning in result.warnings}


def _write_zip(path: Path, entries: list[tuple[str, bytes]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries:
            archive.writestr(name, content)


def _write_epub(
    path: Path,
    entries: list[tuple[str, bytes]],
    *,
    include_mimetype: bool = True,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        if include_mimetype:
            archive.writestr(
                "mimetype",
                b"application/epub+zip",
                compress_type=zipfile.ZIP_STORED,
            )
        for name, content in entries:
            archive.writestr(name, content, compress_type=zipfile.ZIP_DEFLATED)


def _mark_first_zip_entry_encrypted(path: Path) -> None:
    archive_bytes = bytearray(path.read_bytes())
    for signature, flag_offset in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
        header = archive_bytes.find(signature)
        assert header >= 0
        flag_position = header + flag_offset
        flags = int.from_bytes(archive_bytes[flag_position : flag_position + 2], "little")
        archive_bytes[flag_position : flag_position + 2] = (flags | 0x1).to_bytes(
            2,
            "little",
        )
    path.write_bytes(archive_bytes)


def _assert_valid_extract_and_manifest(root: Path) -> None:
    source = root / "valid.zip"
    _write_zip(
        source,
        [
            ("chapters/01.txt", b"chapter one"),
            ("pages/001.png", b"not-a-real-png-but-safe-fixture"),
            ("video/episode.mp4", b"video-must-be-imported-explicitly"),
            ("metadata.bin", b"ignored"),
            ("nested/book.epub", b"ignored"),
        ],
    )

    request = _request(root, source)
    result = preprocess_material(request)
    assert result.succeeded
    assert len(result.derived_materials) == 2
    assert _warning_codes(result) == {
        "entry_suffix_unsupported",
        "nested_container_not_supported",
        "container_video_requires_explicit_import",
    }
    assert (request.output_root / "text" / "chapters" / "01.txt").read_bytes() == b"chapter one"
    assert (request.output_root / "images" / "pages" / "001.png").is_file()

    manifest = json.loads(request.manifest_path.read_text(encoding="utf-8"))
    expected_fields = {
        "schema_version",
        "source_raw_path",
        "source_suffix",
        "source_hash",
        "preprocessor",
        "created_at",
        "output_root",
        "derived_materials",
        "entry_count",
        "input_size_bytes",
        "expanded_size_bytes",
        "warnings",
        "failed_entries",
    }
    assert expected_fields <= manifest.keys()
    assert manifest["schema_version"] == PREPROCESSING_MANIFEST_SCHEMA_VERSION
    assert manifest["source_raw_path"] == "raw/valid.zip"
    assert manifest["preprocessor"] == "zip"
    assert manifest["entry_count"] == 5
    assert len(manifest["derived_materials"]) == 2
    assert all(
        Path(record["material_relative_path"]).as_posix().startswith(
            "materials/derived_inputs/fixture_abc123/"
        )
        for record in manifest["derived_materials"]
    )


def _assert_unsafe_paths_and_collisions(root: Path) -> None:
    source = root / "unsafe.zip"
    decomposed_name = "cafe\u0301.txt"
    _write_zip(
        source,
        [
            ("../unsafe-directory/", b""),
            ("../escape.txt", b"escape"),
            ("C:/drive.txt", b"drive"),
            ("CON.txt", b"reserved"),
            ("folder/trailing. /file.txt", b"trailing"),
            ("Case/Name.txt", b"first"),
            ("case/name.TXT", b"second"),
            ("caf\u00e9.txt", b"unicode-first"),
            (decomposed_name, b"unicode-second"),
        ],
    )

    request = _request(root, source)
    result = preprocess_material(request)
    assert result.succeeded
    assert "entry_path_unsafe" in _warning_codes(result)
    assert "entry_path_collision" in _warning_codes(result)
    assert not (root / "escape.txt").exists()
    output_root = request.output_root.resolve()
    assert all(path.resolve().is_relative_to(output_root) for path in output_root.rglob("*"))


def _assert_special_file_and_encryption_rejected(root: Path) -> None:
    source = root / "special.zip"
    source.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(source, "w") as archive:
        symlink = zipfile.ZipInfo("link.txt")
        symlink.create_system = 3
        symlink.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(symlink, "target.txt")

    result = preprocess_material(_request(root, source))
    assert result.succeeded
    assert "entry_type_unsupported" in _warning_codes(result)

    encrypted_source = root / "encrypted.zip"
    _write_zip(encrypted_source, [("secret.txt", b"secret")])
    _mark_first_zip_entry_encrypted(encrypted_source)

    encrypted_result = preprocess_material(_request(root, encrypted_source))
    assert encrypted_result.succeeded
    assert "entry_encrypted" in _warning_codes(encrypted_result)


def _assert_limits(root: Path) -> None:
    count_source = root / "count.zip"
    _write_zip(count_source, [("one.txt", b"1"), ("two.txt", b"2")])
    count_result = preprocess_material(
        _request(root, count_source, limits=PreprocessingLimits(max_entries=1))
    )
    assert count_result.status == "failed"
    assert _warning_codes(count_result) == {"entry_count_limit_exceeded"}
    assert not _request(root, count_source).output_root.exists()

    entry_source = root / "entry-size.zip"
    _write_zip(entry_source, [("large.txt", b"12345"), ("small.txt", b"ok")])
    entry_result = preprocess_material(
        _request(root, entry_source, limits=PreprocessingLimits(max_entry_size_bytes=4))
    )
    assert entry_result.succeeded
    assert "entry_size_limit_exceeded" in _warning_codes(entry_result)
    assert {record.source_entry_path for record in entry_result.derived_materials} == {"small.txt"}

    total_source = root / "total-size.zip"
    _write_zip(total_source, [("one.txt", b"123"), ("two.txt", b"456")])
    total_result = preprocess_material(
        _request(root, total_source, limits=PreprocessingLimits(max_expanded_size_bytes=5))
    )
    assert total_result.status == "failed"
    assert _warning_codes(total_result) == {"expanded_size_limit_exceeded"}

    ratio_source = root / "ratio.zip"
    _write_zip(ratio_source, [("repeated.txt", b"A" * 4096), ("normal.txt", b"normal")])
    ratio_result = preprocess_material(
        _request(root, ratio_source, limits=PreprocessingLimits(max_compression_ratio=5))
    )
    assert ratio_result.succeeded
    assert "compression_ratio_limit_exceeded" in _warning_codes(ratio_result)


def _assert_corrupt_and_cancelled_leave_no_partial_output(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    corrupt = root / "corrupt.zip"
    corrupt.write_bytes(b"not a zip")
    corrupt_request = _request(root, corrupt)
    corrupt_result = preprocess_material(corrupt_request)
    assert corrupt_result.status == "failed"
    assert _warning_codes(corrupt_result) == {"zip_container_invalid"}
    assert not corrupt_request.output_root.exists()
    assert not corrupt_request.manifest_path.exists()

    source = root / "cancelled.zip"
    _write_zip(source, [("one.txt", b"one"), ("two.txt", b"two")])
    checks = 0

    def cancelled() -> bool:
        nonlocal checks
        checks += 1
        return checks >= 4

    cancelled_request = _request(root, source, cancelled=cancelled)
    cancelled_request.output_root.mkdir(parents=True)
    (cancelled_request.output_root / "existing.txt").write_text("keep", encoding="utf-8")
    cancelled_request.manifest_path.parent.mkdir(parents=True, exist_ok=True)
    cancelled_request.manifest_path.write_text("existing manifest", encoding="utf-8")
    cancelled_result = preprocess_material(cancelled_request)
    assert cancelled_result.status == "cancelled"
    assert (cancelled_request.output_root / "existing.txt").read_text(encoding="utf-8") == "keep"
    assert cancelled_request.manifest_path.read_text(encoding="utf-8") == "existing manifest"
    staging_root = cancelled_request.staging_root
    assert staging_root is not None
    assert not list(staging_root.glob(".material-preprocessing-*"))


def _assert_profiles_enabled_without_opening_archive_formats() -> None:
    for suffix in (".zip", ".cbz", ".epub", ".pdf", ".7z", ".rar", ".cbr"):
        profile = input_format_profile(f"fixture{suffix}")
        assert profile is not None
        assert profile.state == InputFormatSupportState.ENABLED
        assert is_preprocessable_source(f"fixture{suffix}") is True
        assert is_import_supported_source(f"fixture{suffix}") is False
        assert f"*{suffix}" in project_input_file_patterns()


def _project_request(
    project_root: Path,
    raw_source: Path,
    preprocessor_key: InputPreprocessorKey = "zip",
) -> PreprocessingRequest:
    return build_project_preprocessing_request(
        raw_root=project_root / "raw",
        materials_root=project_root / "materials",
        cache_root=project_root / "cache",
        raw_source=raw_source,
        preprocessor_key=preprocessor_key,
    )


def _assert_project_lifecycle_and_source_trace(root: Path) -> None:
    projects_root = root / "projects"
    project_id = "input-format-lifecycle"
    project_root = projects_root / project_id
    raw_root = project_root / "raw"
    materials_root = project_root / "materials"
    cache_root = project_root / "cache"
    for path in (raw_root, materials_root, cache_root, project_root / "knowledge_base"):
        path.mkdir(parents=True, exist_ok=True)

    raw_source = raw_root / "collection.zip"
    _write_zip(
        raw_source,
        [("chapters/01.txt", b"chapter"), ("pages/001.png", b"image")],
    )
    request = _project_request(project_root, raw_source)
    result = preprocess_project_source(
        request,
        raw_root=raw_root,
        materials_root=materials_root,
        cache_root=cache_root,
    )
    assert result.succeeded and not result.reused
    assert request.output_root == materials_root / "derived_inputs" / "collection.zip"
    assert request.output_root_reference == "derived_inputs/collection.zip"
    assert request.manifest_path == (
        cache_root / "material_preprocessing" / "manifests" / "collection.zip.json"
    )
    assert request.source_raw_path == "raw/collection.zip"

    reused = preprocess_project_source(
        _project_request(project_root, raw_source),
        raw_root=raw_root,
        materials_root=materials_root,
        cache_root=cache_root,
    )
    assert reused.succeeded and reused.reused
    assert current_preprocessing_manifest_for_raw(
        raw_root=raw_root,
        materials_root=materials_root,
        cache_root=cache_root,
        raw_source=raw_source,
    ) is not None

    source_stat = raw_source.stat()
    os.utime(
        raw_source,
        ns=(source_stat.st_atime_ns, source_stat.st_mtime_ns + 1_000_000),
    )
    assert current_preprocessing_manifest_for_raw(
        raw_root=raw_root,
        materials_root=materials_root,
        cache_root=cache_root,
        raw_source=raw_source,
    ) is None
    refreshed_reuse = preprocess_project_source(
        _project_request(project_root, raw_source),
        raw_root=raw_root,
        materials_root=materials_root,
        cache_root=cache_root,
    )
    assert refreshed_reuse.reused
    assert current_preprocessing_manifest_for_raw(
        raw_root=raw_root,
        materials_root=materials_root,
        cache_root=cache_root,
        raw_source=raw_source,
    ) is not None

    metadata_index = preprocessing_material_metadata_index(materials_root)
    assert len(metadata_index) == 2
    assert all(
        metadata["preprocessed_from_raw"] == "raw/collection.zip"
        for metadata in metadata_index.values()
    )
    assert {metadata["source_entry_path"] for metadata in metadata_index.values()} == {
        "chapters/01.txt",
        "pages/001.png",
    }

    text_record = next(
        record for record in result.derived_materials if record.media_type == "text"
    )
    text_material = materials_root / text_record.material_relative_path
    text_material.write_bytes(b"CHAPTER")
    assert current_preprocessing_manifest_for_raw(
        raw_root=raw_root,
        materials_root=materials_root,
        cache_root=cache_root,
        raw_source=raw_source,
    ) is None
    assert preprocessing_material_metadata_index(materials_root) == {}
    repaired = preprocess_project_source(
        _project_request(project_root, raw_source),
        raw_root=raw_root,
        materials_root=materials_root,
        cache_root=cache_root,
    )
    assert repaired.succeeded and not repaired.reused
    assert text_material.read_bytes() == b"chapter"

    previous_projects_root = path_utils.PROJECTS_ROOT
    path_utils.PROJECTS_ROOT = projects_root
    try:
        episodes = scan_formal_materials(project_id)
        units = [unit for episode in episodes for unit in episode.units]
        assert len(units) == 2
        assert all(unit.material_ref.metadata["preprocessed_from_raw"] for unit in units)
        assert {
            unit.material_ref.metadata["source_entry_path"] for unit in units
        } == {"chapters/01.txt", "pages/001.png"}
        assert all(not unit.material_ref.relative_path.startswith("cache/") for unit in units)
        assert link_raw_sources_to_materials(project_id, [raw_source]) == 0
        assert not (materials_root / raw_source.name).exists()

        cleaned = clean_raw_sources(project_id, [raw_source])
        assert cleaned == ["collection.zip"]
        assert not raw_source.exists()
        assert request.output_root.is_dir()
        assert request.manifest_path.is_file()
        assert complete_preprocessing_manifest_for_raw(
            raw_root=raw_root,
            materials_root=materials_root,
            cache_root=cache_root,
            raw_source=raw_source,
        ) is not None

        _write_zip(raw_source, [("replacement.txt", b"replacement")])
        replacement_request = _project_request(project_root, raw_source)
        replacement = preprocess_project_source(
            replacement_request,
            raw_root=raw_root,
            materials_root=materials_root,
            cache_root=cache_root,
        )
        assert replacement.succeeded
        assert replacement.source_hash != result.source_hash
        assert replacement_request.output_root == request.output_root
        assert replacement_request.manifest_path == request.manifest_path
        assert request.output_root.exists()
        assert request.manifest_path.exists()

        replacement_output = replacement_request.output_root
        replacement_manifest = replacement_request.manifest_path
        raw_source.write_bytes(b"damaged replacement")
        failed_request = _project_request(project_root, raw_source)
        failed = preprocess_project_source(
            failed_request,
            raw_root=raw_root,
            materials_root=materials_root,
            cache_root=cache_root,
        )
        assert failed.status == "failed"
        assert replacement_output.is_dir()
        assert replacement_manifest.is_file()
        stale_units = [
            unit for episode in scan_formal_materials(project_id) for unit in episode.units
        ]
        assert stale_units == []

        assert remove_raw_sources(project_id, [raw_source]) == 1
        assert not raw_source.exists()
        assert not replacement_output.exists()
        assert not replacement_manifest.exists()
    finally:
        path_utils.PROJECTS_ROOT = previous_projects_root


def _assert_source_relative_artifact_isolation(root: Path) -> None:
    projects_root = root / "projects"
    project_id = "input-format-source-isolation"
    project_root = projects_root / project_id
    raw_root = project_root / "raw"
    materials_root = project_root / "materials"
    cache_root = project_root / "cache"
    for path in (raw_root, materials_root, cache_root, project_root / "knowledge_base"):
        path.mkdir(parents=True, exist_ok=True)

    first_source = raw_root / "groupA" / "book.zip"
    second_source = raw_root / "groupB" / "book.zip"
    _write_zip(first_source, [("chapter.txt", b"same content")])
    second_source.parent.mkdir(parents=True)
    shutil.copy2(first_source, second_source)

    first_request = _project_request(project_root, first_source)
    second_request = _project_request(project_root, second_source)
    first_result = preprocess_project_source(
        first_request,
        raw_root=raw_root,
        materials_root=materials_root,
        cache_root=cache_root,
    )
    second_result = preprocess_project_source(
        second_request,
        raw_root=raw_root,
        materials_root=materials_root,
        cache_root=cache_root,
    )
    assert first_result.succeeded and second_result.succeeded
    assert first_result.source_hash == second_result.source_hash
    assert first_request.output_root == materials_root / "derived_inputs" / "groupA" / "book.zip"
    assert second_request.output_root == materials_root / "derived_inputs" / "groupB" / "book.zip"
    assert first_request.output_root != second_request.output_root
    assert first_request.manifest_path != second_request.manifest_path
    assert first_request.manifest_path.is_file()
    assert second_request.manifest_path.is_file()

    metadata_index = preprocessing_material_metadata_index(materials_root)
    assert {
        metadata["preprocessed_from_raw"] for metadata in metadata_index.values()
    } == {"raw/groupA/book.zip", "raw/groupB/book.zip"}

    previous_projects_root = path_utils.PROJECTS_ROOT
    path_utils.PROJECTS_ROOT = projects_root
    try:
        assert remove_raw_sources(project_id, [first_source]) == 1
        assert not first_request.output_root.exists()
        assert not first_request.manifest_path.exists()
        assert second_request.output_root.is_dir()
        assert second_request.manifest_path.is_file()
        assert current_preprocessing_manifest_for_raw(
            raw_root=raw_root,
            materials_root=materials_root,
            cache_root=cache_root,
            raw_source=second_source,
        ) is not None
    finally:
        path_utils.PROJECTS_ROOT = previous_projects_root


def _assert_zip_profile_end_to_end(root: Path) -> None:
    projects_root = root / "projects"
    external_source = root / "external" / "mixed-materials.zip"
    _write_zip(
        external_source,
        [
            ("pages/001.png", b"page-one"),
            ("pages/002.jpg", b"page-two"),
            ("pages/animation.gif", b"gif"),
            ("pages/scan.bmp", b"bmp"),
            ("text/chapter.txt", b"chapter"),
            ("video/episode.mp4", b"video-must-be-imported-explicitly"),
            ("unknown.bin", b"unknown"),
            ("nested/book.epub", b"nested"),
        ],
    )
    project_id = "zip-profile-e2e"
    config = ProjectConfig(
        project_id=project_id,
        name="ZIP profile validation",
        source_paths=[str(external_source)],
    )

    previous_projects_root = path_utils.PROJECTS_ROOT
    path_utils.PROJECTS_ROOT = projects_root
    try:
        result = process_source_request(config)
        project_root = projects_root / project_id
        raw_source = project_root / "raw" / external_source.name
        assert result.linked_count == 0
        assert result.preprocessed_source_count == 1
        assert result.derived_material_count == 5
        assert set(result.preprocessing_warning_codes) == {
            "entry_suffix_unsupported",
            "nested_container_not_supported",
            "container_video_requires_explicit_import",
        }
        assert raw_source.is_file()
        assert not (project_root / "materials" / external_source.name).exists()

        manifests = list(
            (project_root / "cache" / "material_preprocessing").rglob("*.json")
        )
        assert len(manifests) == 1
        manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
        assert manifest["source_suffix"] == ".zip"
        assert manifest["preprocessor"] == "zip"
        assert len(manifest["derived_materials"]) == 5
        assert set(manifest["failed_entries"]) == {
            "unknown.bin",
            "nested/book.epub",
            "video/episode.mp4",
        }

        episodes = scan_formal_materials(project_id)
        units = [unit for episode in episodes for unit in episode.units]
        assert len(units) == 5
        assert {unit.media_type.value for unit in units} == {"image", "text"}
        image_episode = next(
            episode for episode in episodes if any(unit.media_type.value == "image" for unit in episode.units)
        )
        assert "manga" in {content_form.value for content_form in image_episode.content_forms}
        support_reasons = {
            unit.material_ref.metadata.get("support_reason") for unit in image_episode.units
        }
        assert {"animated_image_not_supported", "bmp_image_not_supported"} <= support_reasons
        assert all(
            unit.material_ref.metadata["preprocessed_from_raw"]
            == f"raw/{external_source.name}"
            for unit in units
        )
        assert not any(unit.material_ref.relative_path.endswith(".bin") for unit in units)
        assert not any(unit.material_ref.relative_path.endswith(".epub") for unit in units)
        assert not any(unit.media_type.value == "video" for unit in units)

        artifact_request = _project_request(project_root, raw_source)
        artifact_output = artifact_request.output_root
        artifact_manifest = artifact_request.manifest_path
        assert remove_project_sources(project_id, [str(external_source)]) == 1
        assert not raw_source.exists()
        assert not artifact_output.exists()
        assert not artifact_manifest.exists()

        process_source_request(config)
        raw_source = project_root / "raw" / external_source.name
        artifact_request = _project_request(project_root, raw_source)
        assert clean_raw_sources(project_id, [raw_source]) == [external_source.name]
        assert not raw_source.exists()
        assert artifact_request.output_root.exists()
        assert artifact_request.manifest_path.exists()

        external_source.unlink()
        assert remove_project_sources(project_id, [str(external_source)]) == 0
        assert not artifact_request.output_root.exists()
        assert not artifact_request.manifest_path.exists()
    finally:
        path_utils.PROJECTS_ROOT = previous_projects_root


def _assert_ffmpeg_requirement_and_skip_policy(root: Path) -> None:
    projects_root = root / "projects"
    external_root = root / "external"
    archive_source = external_root / "book.zip"
    text_source = external_root / "notes.txt"
    video_source = external_root / "episode.mp4"
    _write_zip(archive_source, [("chapters/01.txt", b"chapter one")])
    text_source.write_text("notes", encoding="utf-8")
    video_source.write_bytes(b"video fixture")
    processing_config = SourceProcessingConfig(
        preset=SourceProcessingPreset.TRANSCODE_ONLY,
        transcode_enabled=True,
    )

    skip_config = ProjectConfig(
        project_id="ffmpeg-skip-policy",
        name="FFmpeg skip policy validation",
        source_paths=[str(archive_source), str(text_source), str(video_source)],
        source_processing=processing_config,
    )
    container_only_config = ProjectConfig(
        project_id="ffmpeg-container-only",
        name="FFmpeg container-only validation",
        source_paths=[str(archive_source)],
        source_processing=processing_config,
    )
    original_config = skip_config.model_copy(
        update={
            "project_id": "ffmpeg-original",
            "source_processing": SourceProcessingConfig(),
        }
    )
    defensive_error_config = skip_config.model_copy(
        update={"project_id": "ffmpeg-error-after-preprocess"}
    )

    previous_projects_root = path_utils.PROJECTS_ROOT
    previous_has_ffmpeg_binary = processing_middleware.has_ffmpeg_binary
    path_utils.PROJECTS_ROOT = projects_root
    processing_middleware.has_ffmpeg_binary = lambda: False
    try:
        assert source_processing_requires_ffmpeg(skip_config)
        assert not source_processing_requires_ffmpeg(container_only_config)
        assert not source_processing_requires_ffmpeg(original_config)

        result = process_source_request(
            skip_config,
            ffmpeg_unavailable_policy="skip_video",
        )
        project_root = projects_root / skip_config.project_id
        assert result.linked_count == 1
        assert result.preprocessed_source_count == 1
        assert result.derived_material_count == 1
        assert result.skipped_video_count == 1
        assert result.preprocessing_warning_codes == ["ffmpeg_video_skipped"]
        assert (project_root / "raw" / video_source.name).is_file()
        assert (project_root / "materials" / text_source.name).is_file()
        assert not (project_root / "materials" / video_source.name).exists()
        assert list((project_root / "materials" / "derived_inputs").rglob("01.txt"))

        container_result = process_source_request(container_only_config)
        assert container_result.preprocessed_source_count == 1
        assert container_result.derived_material_count == 1
        assert container_result.skipped_video_count == 0

        try:
            process_source_request(defensive_error_config)
        except MaterialProcessingError:
            pass
        else:
            raise AssertionError("Missing FFmpeg must stop direct video processing")
        defensive_root = projects_root / defensive_error_config.project_id
        assert (defensive_root / "raw" / video_source.name).is_file()
        assert (defensive_root / "materials" / text_source.name).is_file()
        assert list((defensive_root / "materials" / "derived_inputs").rglob("01.txt"))
        assert not (defensive_root / "materials" / video_source.name).exists()
    finally:
        processing_middleware.has_ffmpeg_binary = previous_has_ffmpeg_binary
        path_utils.PROJECTS_ROOT = previous_projects_root


def _assert_cbz_profile_end_to_end(root: Path) -> None:
    projects_root = root / "projects"
    external_source = root / "external" / "chapter.cbz"
    _write_zip(
        external_source,
        [
            ("chapter/page10.png", b"page-ten"),
            ("cover/page1.webp", b"cover"),
            ("chapter/page2.jpg", b"page-two"),
            ("notes.txt", b"not a comic page"),
            ("nested/archive.zip", b"nested"),
            ("../escape.png", b"escape"),
        ],
    )
    project_id = "cbz-profile-e2e"
    config = ProjectConfig(
        project_id=project_id,
        name="CBZ profile validation",
        source_paths=[str(external_source)],
    )

    previous_projects_root = path_utils.PROJECTS_ROOT
    path_utils.PROJECTS_ROOT = projects_root
    try:
        result = process_source_request(config)
        project_root = projects_root / project_id
        raw_source = project_root / "raw" / external_source.name
        assert result.preprocessed_source_count == 1
        assert result.derived_material_count == 3
        assert set(result.preprocessing_warning_codes) == {
            "cbz_entry_not_image",
            "nested_container_not_supported",
            "entry_path_unsafe",
        }
        assert raw_source.is_file()
        assert not (project_root / "materials" / external_source.name).exists()
        assert not (root / "escape.png").exists()

        request = _project_request(project_root, raw_source, "cbz")
        manifest = json.loads(request.manifest_path.read_text(encoding="utf-8"))
        assert manifest["source_suffix"] == ".cbz"
        assert manifest["preprocessor"] == "cbz"
        records = manifest["derived_materials"]
        assert [record["source_entry_path"] for record in records] == [
            "chapter/page2.jpg",
            "chapter/page10.png",
            "cover/page1.webp",
        ]
        assert [record["page_number"] for record in records] == [1, 2, 3]
        material_paths = [Path(record["material_relative_path"]) for record in records]
        assert [path.name for path in material_paths] == [
            "page_0001.jpg",
            "page_0002.png",
            "page_0003.webp",
        ]
        assert len({path.parent.as_posix() for path in material_paths}) == 1

        episodes = scan_formal_materials(project_id)
        assert len(episodes) == 1
        episode = episodes[0]
        assert "manga" in {content_form.value for content_form in episode.content_forms}
        assert [
            unit.material_ref.metadata["source_entry_path"] for unit in episode.units
        ] == [
            "chapter/page2.jpg",
            "chapter/page10.png",
            "cover/page1.webp",
        ]
        assert [unit.material_ref.page_range.start_page for unit in episode.units] == [
            1,
            2,
            3,
        ]

        assert clean_raw_sources(project_id, [raw_source]) == [external_source.name]
        assert not raw_source.exists()
        assert request.output_root.exists()
        external_source.unlink()
        assert remove_project_sources(project_id, [str(external_source)]) == 0
        assert not request.output_root.exists()
        assert not request.manifest_path.exists()

        empty_source = root / "external" / "empty.cbz"
        _write_zip(empty_source, [("notes.txt", b"notes")])
        empty_config = ProjectConfig(
            project_id="cbz-empty",
            name="Empty CBZ validation",
            source_paths=[str(empty_source)],
        )
        empty_result = process_source_request(empty_config)
        empty_raw = projects_root / "cbz-empty" / "raw" / empty_source.name
        assert empty_result.preprocessed_source_count == 1
        assert empty_result.derived_material_count == 0
        assert set(empty_result.preprocessing_warning_codes) == {
            "cbz_entry_not_image",
            "no_supported_entries",
        }
        assert clean_raw_sources("cbz-empty", [empty_raw]) == []
        assert empty_raw.exists()
        assert remove_project_sources("cbz-empty", [str(empty_source)]) == 1

        corrupt_source = root / "external" / "corrupt.cbz"
        corrupt_source.write_bytes(b"not a CBZ")
        corrupt_config = ProjectConfig(
            project_id="cbz-corrupt",
            name="Corrupt CBZ validation",
            source_paths=[str(corrupt_source)],
        )
        corrupt_result = process_source_request(corrupt_config)
        assert corrupt_result.preprocessed_source_count == 0
        assert corrupt_result.derived_material_count == 0
        assert corrupt_result.preprocessing_warning_codes == ["zip_container_invalid"]
        assert not list(
            (projects_root / "cbz-corrupt" / "cache" / "material_preprocessing").rglob(
                "*.json"
            )
        )
        assert remove_project_sources("cbz-corrupt", [str(corrupt_source)]) == 1
    finally:
        path_utils.PROJECTS_ROOT = previous_projects_root


def _epub_container_xml(opf_path: str = "OPS/package.opf") -> bytes:
    return (
        "<?xml version='1.0' encoding='UTF-8'?>"
        "<container xmlns='urn:oasis:names:tc:opendocument:xmlns:container' "
        "version='1.0'><rootfiles><rootfile full-path='"
        f"{opf_path}' media-type='application/oebps-package+xml'/>"
        "</rootfiles></container>"
    ).encode("utf-8")


def _assert_epub_profile_end_to_end(root: Path) -> None:
    projects_root = root / "projects"
    external_source = root / "external" / "novel.epub"
    package = b"""<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0">
  <manifest>
    <item id="chapter-one" href="Text/chapter1.xhtml" media-type="application/xhtml+xml"/>
    <item id="cover" href="Images/cover.jpg" media-type="image/jpeg"/>
    <item id="chapter-two" href="Text/chapter2.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="chapter-two"/>
    <itemref idref="missing-chapter"/>
    <itemref idref="chapter-one"/>
  </spine>
</package>"""
    chapter_two = b"""<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
  <head><title>Second chapter</title><style>ignored</style></head>
  <body><section><h1>Second</h1><p><ruby>&#28450;&#23383;<rt>&#12363;&#12435;&#12376;</rt></ruby>
  <a epub:type="noteref" href="#note">footnote</a></p>
  <img src="../Images/cover.jpg" alt="character portrait"/>
  <script>ignored script</script></section></body>
</html>"""
    damaged_chapter_one = b"""<html><head><title>First chapter</title></head>
<body><h1>First</h1><p>Recovered malformed chapter</body></html>"""
    _write_epub(
        external_source,
        [
            ("META-INF/container.xml", _epub_container_xml()),
            ("OPS/package.opf", package),
            ("OPS/Text/chapter1.xhtml", damaged_chapter_one),
            ("OPS/Text/chapter2.xhtml", chapter_two),
            ("OPS/Images/cover.jpg", b"embedded-image"),
        ],
    )
    project_id = "epub-profile-e2e"
    config = ProjectConfig(
        project_id=project_id,
        name="EPUB profile validation",
        source_paths=[str(external_source)],
    )

    previous_projects_root = path_utils.PROJECTS_ROOT
    path_utils.PROJECTS_ROOT = projects_root
    try:
        result = process_source_request(config)
        project_root = projects_root / project_id
        raw_source = project_root / "raw" / external_source.name
        assert result.preprocessed_source_count == 1
        assert result.derived_material_count == 2
        assert result.preprocessing_warning_codes == ["epub_xhtml_malformed_fallback"]
        assert raw_source.is_file()
        assert not (project_root / "materials" / external_source.name).exists()

        request = _project_request(project_root, raw_source, "epub")
        manifest = json.loads(request.manifest_path.read_text(encoding="utf-8"))
        assert manifest["source_suffix"] == ".epub"
        assert manifest["preprocessor"] == "epub"
        records = manifest["derived_materials"]
        assert [record["source_entry_path"] for record in records] == [
            "OPS/Text/chapter2.xhtml",
            "OPS/Text/chapter1.xhtml",
        ]
        assert [record["chapter_index"] for record in records] == [1, 2]
        assert all(record["content_form_hint"] == "novel" for record in records)
        summaries = manifest["entry_summaries"]
        assert [summary["source_entry_path"] for summary in summaries if summary["role"] == "image"] == [
            "OPS/Images/cover.jpg"
        ]
        assert [summary["status"] for summary in summaries if summary["role"] == "image"] == [
            "observed_not_materialized"
        ]
        assert [summary["spine_index"] for summary in summaries if summary["role"] == "chapter"] == [
            1,
            2,
        ]

        chapter_one = (request.output_root / "text" / "chapters" / "chapter_0001.txt").read_text(
            encoding="utf-8"
        )
        assert "Second" in chapter_one
        assert "\u6f22\u5b57" in chapter_one
        assert "\u304b\u3093\u3058" not in chapter_one
        assert "footnote" in chapter_one
        assert "[Image: character portrait]" in chapter_one
        chapter_two = (request.output_root / "text" / "chapters" / "chapter_0002.txt").read_text(
            encoding="utf-8"
        )
        assert "Recovered malformed chapter" in chapter_two

        episodes = scan_formal_materials(project_id)
        units = [unit for episode in episodes for unit in episode.units]
        assert len(units) == 2
        assert {unit.media_type.value for unit in units} == {"text"}
        assert {unit.content_form.value for unit in units} == {"novel"}
        assert [unit.material_ref.metadata["source_entry_path"] for unit in units] == [
            "OPS/Text/chapter2.xhtml",
            "OPS/Text/chapter1.xhtml",
        ]
        assert [unit.material_ref.metadata["chapter_index"] for unit in units] == [1, 2]
        assert all(
            unit.material_ref.metadata["preprocessed_from_raw"] == "raw/novel.epub"
            for unit in units
        )
        assert not any(unit.media_type.value == "image" for unit in units)
        run_plan = FormalExtractionRunPlan(project_id=project_id, episodes=episodes)
        assert [
            unit.material_ref.metadata["source_entry_path"] for unit in run_plan.all_units
        ] == ["OPS/Text/chapter2.xhtml", "OPS/Text/chapter1.xhtml"]
        assert [
            unit.material_ref.metadata["chapter_index"] for unit in run_plan.all_units
        ] == [1, 2]

        reused = preprocess_project_source(
            _project_request(project_root, raw_source, "epub"),
            raw_root=project_root / "raw",
            materials_root=project_root / "materials",
            cache_root=project_root / "cache",
        )
        assert reused.succeeded and reused.reused

        assert clean_raw_sources(project_id, [raw_source]) == [external_source.name]
        assert not raw_source.exists()
        assert request.output_root.exists()
        external_source.unlink()
        assert remove_project_sources(project_id, [str(external_source)]) == 0
        assert not request.output_root.exists()
        assert not request.manifest_path.exists()
    finally:
        path_utils.PROJECTS_ROOT = previous_projects_root


def _assert_epub_failure_and_fallback_boundaries(root: Path) -> None:
    missing_opf = root / "missing-opf" / "missing.epub"
    _write_epub(
        missing_opf,
        [
            ("Text/02.xhtml", b"<html><body><p>Second path</p></body></html>"),
            ("Text/01.xhtml", b"<html><body><p>First path</p></body></html>"),
        ],
        include_mimetype=False,
    )
    missing_result = preprocess_material(
        _request(root / "missing-opf", missing_opf, preprocessor_key="epub")
    )
    assert missing_result.succeeded
    assert [record.source_entry_path for record in missing_result.derived_materials] == [
        "Text/01.xhtml",
        "Text/02.xhtml",
    ]
    assert {
        "epub_mimetype_missing",
        "epub_opf_missing_fallback",
        "epub_document_order_fallback",
    } <= _warning_codes(missing_result)

    missing_spine = root / "missing-spine" / "missing-spine.epub"
    package_without_spine = b"""<package xmlns="http://www.idpf.org/2007/opf">
<manifest>
  <item id="second" href="../Text/02.xhtml" media-type="application/xhtml+xml"/>
  <item id="first" href="../Text/01.xhtml" media-type="application/xhtml+xml"/>
  <item id="unsafe" href="../../escape.xhtml" media-type="application/xhtml+xml"/>
</manifest></package>"""
    _write_epub(
        missing_spine,
        [
            ("META-INF/container.xml", _epub_container_xml()),
            ("OPS/package.opf", package_without_spine),
            ("Text/01.xhtml", b"<html><body>First</body></html>"),
            ("Text/02.xhtml", b"<html><body>Second</body></html>"),
        ],
    )
    spine_result = preprocess_material(
        _request(root / "missing-spine", missing_spine, preprocessor_key="epub")
    )
    assert spine_result.succeeded
    assert [record.source_entry_path for record in spine_result.derived_materials] == [
        "Text/02.xhtml",
        "Text/01.xhtml",
    ]
    assert {"epub_spine_missing_fallback", "epub_manifest_item_invalid"} <= _warning_codes(
        spine_result
    )

    drm_source = root / "drm" / "protected.epub"
    _write_epub(drm_source, [("META-INF/encryption.xml", b"<encryption/>")])
    drm_result = preprocess_material(
        _request(root / "drm", drm_source, preprocessor_key="epub")
    )
    assert drm_result.status == "failed"
    assert "epub_drm_unsupported" in _warning_codes(drm_result)
    assert not drm_result.manifest_path.exists()

    encrypted_source = root / "encrypted" / "encrypted.epub"
    _write_epub(encrypted_source, [("chapter.xhtml", b"<html>secret</html>")])
    _mark_first_zip_entry_encrypted(encrypted_source)
    encrypted_result = preprocess_material(
        _request(root / "encrypted", encrypted_source, preprocessor_key="epub")
    )
    assert encrypted_result.status == "failed"
    assert {"entry_encrypted", "epub_encryption_unsupported"} <= _warning_codes(
        encrypted_result
    )

    unsafe_xhtml = root / "unsafe-xhtml" / "unsafe.epub"
    unsafe_package = b"""<package xmlns="http://www.idpf.org/2007/opf">
<manifest><item id="chapter" href="Text/chapter.xhtml" media-type="application/xhtml+xml"/></manifest>
<spine><itemref idref="chapter"/></spine></package>"""
    _write_epub(
        unsafe_xhtml,
        [
            ("META-INF/container.xml", _epub_container_xml()),
            ("OPS/package.opf", unsafe_package),
            (
                "OPS/Text/chapter.xhtml",
                b"<!DOCTYPE html [<!ENTITY unsafe 'blocked'>]><html>&unsafe;</html>",
            ),
        ],
    )
    unsafe_result = preprocess_material(
        _request(root / "unsafe-xhtml", unsafe_xhtml, preprocessor_key="epub")
    )
    assert unsafe_result.succeeded
    assert unsafe_result.derived_materials == ()
    assert {"epub_xhtml_unsafe_declaration", "epub_no_readable_chapters"} <= _warning_codes(
        unsafe_result
    )

    corrupt_source = root / "corrupt" / "corrupt.epub"
    corrupt_source.parent.mkdir(parents=True)
    corrupt_source.write_bytes(b"not an EPUB")
    corrupt_result = preprocess_material(
        _request(root / "corrupt", corrupt_source, preprocessor_key="epub")
    )
    assert corrupt_result.status == "failed"
    assert _warning_codes(corrupt_result) == {"epub_container_invalid"}
    assert not corrupt_result.manifest_path.exists()


def main() -> None:
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        _assert_valid_extract_and_manifest(root / "valid")
        _assert_unsafe_paths_and_collisions(root / "unsafe")
        _assert_special_file_and_encryption_rejected(root / "special")
        _assert_limits(root / "limits")
        _assert_corrupt_and_cancelled_leave_no_partial_output(root / "failures")
        _assert_project_lifecycle_and_source_trace(root / "lifecycle")
        _assert_source_relative_artifact_isolation(root / "source-isolation")
        _assert_zip_profile_end_to_end(root / "zip-profile")
        _assert_ffmpeg_requirement_and_skip_policy(root / "ffmpeg-policy")
        _assert_cbz_profile_end_to_end(root / "cbz-profile")
        _assert_epub_profile_end_to_end(root / "epub-profile")
        _assert_epub_failure_and_fallback_boundaries(root / "epub-boundaries")
    _assert_profiles_enabled_without_opening_archive_formats()
    print("input format preprocessing validation passed")


if __name__ == "__main__":
    main()
