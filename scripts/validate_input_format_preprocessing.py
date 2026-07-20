from __future__ import annotations

import json
import os
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
    input_format_profile,
    is_import_supported_source,
    is_preprocessable_source,
    project_input_file_patterns,
)
from core.source_scanner import scan_formal_materials  # noqa: E402
from utils.source_importer import (  # noqa: E402
    clean_raw_sources,
    link_raw_sources_to_materials,
    remove_raw_sources,
)
import utils.paths as path_utils  # noqa: E402


def _request(
    root: Path,
    source: Path,
    *,
    limits: PreprocessingLimits | None = None,
    cancelled=None,
) -> PreprocessingRequest:
    return PreprocessingRequest(
        source_path=source,
        source_raw_path=f"raw/{source.name}",
        output_root=root / "materials" / "derived_inputs" / "fixture_abc123",
        output_root_reference="materials/derived_inputs/fixture_abc123",
        manifest_path=root / "cache" / "material_preprocessing" / "abc123.json",
        preprocessor_key="zip",
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


def _assert_valid_extract_and_manifest(root: Path) -> None:
    source = root / "valid.zip"
    _write_zip(
        source,
        [
            ("chapters/01.txt", b"chapter one"),
            ("pages/001.png", b"not-a-real-png-but-safe-fixture"),
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
    assert manifest["entry_count"] == 4
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
    archive_bytes = bytearray(encrypted_source.read_bytes())
    for signature, flag_offset in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
        header = archive_bytes.find(signature)
        assert header >= 0
        flag_position = header + flag_offset
        flags = int.from_bytes(archive_bytes[flag_position : flag_position + 2], "little")
        archive_bytes[flag_position : flag_position + 2] = (flags | 0x1).to_bytes(2, "little")
    encrypted_source.write_bytes(archive_bytes)

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


def _assert_candidate_format_remains_disabled() -> None:
    profile = input_format_profile("fixture.zip")
    assert profile is not None
    assert profile.state == InputFormatSupportState.CANDIDATE
    assert is_preprocessable_source("fixture.zip") is False
    assert is_import_supported_source("fixture.zip") is False
    assert "*.zip" not in project_input_file_patterns()


def _project_request(project_root: Path, raw_source: Path) -> PreprocessingRequest:
    return build_project_preprocessing_request(
        raw_root=project_root / "raw",
        materials_root=project_root / "materials",
        cache_root=project_root / "cache",
        raw_source=raw_source,
        preprocessor_key="zip",
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
    assert request.output_root.name.endswith(result.source_hash[:16])
    assert request.output_root_reference.startswith("derived_inputs/")
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
        assert not request.output_root.exists()
        assert not request.manifest_path.exists()

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


def main() -> None:
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        _assert_valid_extract_and_manifest(root / "valid")
        _assert_unsafe_paths_and_collisions(root / "unsafe")
        _assert_special_file_and_encryption_rejected(root / "special")
        _assert_limits(root / "limits")
        _assert_corrupt_and_cancelled_leave_no_partial_output(root / "failures")
        _assert_project_lifecycle_and_source_trace(root / "lifecycle")
    _assert_candidate_format_remains_disabled()
    print("input format preprocessing validation passed")


if __name__ == "__main__":
    main()
