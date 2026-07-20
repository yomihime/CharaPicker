from __future__ import annotations

import json
import struct
import subprocess
import sys
import zlib
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.extraction_plan import FormalExtractionRunPlan  # noqa: E402
from core.models import ProjectConfig  # noqa: E402
from core.source_scanner import scan_formal_materials  # noqa: E402
from utils.archive_backend import (  # noqa: E402
    ArchiveBackendCancelledError,
    ArchiveBackendCapability,
    ArchiveContainerInvalidError,
    ArchiveEntry,
    ArchiveListing,
    ArchivePasswordRequiredError,
    _parse_listing,
    probe_archive_backend,
)
from utils.material_preprocessing import (  # noqa: E402
    PreprocessingLimits,
    PreprocessingRequest,
    build_project_preprocessing_request,
    preprocess_material,
    preprocess_project_source,
)
from utils.material_processing_middleware import process_source_request  # noqa: E402
from utils.media_types import (  # noqa: E402
    InputFormatSupportState,
    input_format_profile,
    is_preprocessable_source,
    project_input_file_patterns,
)
from utils.source_importer import clean_raw_sources, remove_project_sources  # noqa: E402
import utils.paths as path_utils  # noqa: E402


def _request(
    root: Path,
    source: Path,
    *,
    limits: PreprocessingLimits | None = None,
) -> PreprocessingRequest:
    return PreprocessingRequest(
        source_path=source,
        source_raw_path=f"raw/{source.name}",
        output_root=root / "materials" / "derived_inputs" / "archive_fixture",
        output_root_reference="materials/derived_inputs/archive_fixture",
        manifest_path=root / "cache" / "material_preprocessing" / "archive_fixture.json",
        preprocessor_key="archive",
        limits=limits or PreprocessingLimits(),
        staging_root=root / "cache" / "material_preprocessing" / "tmp",
    )


def _project_request(project_root: Path, raw_source: Path) -> PreprocessingRequest:
    return build_project_preprocessing_request(
        raw_root=project_root / "raw",
        materials_root=project_root / "materials",
        cache_root=project_root / "cache",
        raw_source=raw_source,
        preprocessor_key="archive",
    )


def _warning_codes(result) -> set[str]:
    return {warning.code for warning in result.warnings}


def _available_capability() -> ArchiveBackendCapability:
    return ArchiveBackendCapability(
        available=True,
        backend_name="fake-7zip",
        version="1.0",
        supported_formats=frozenset({"7z", "rar"}),
        executable_path=Path("fake-7z"),
    )


@dataclass
class _FakeArchiveBackend:
    capability: ArchiveBackendCapability
    listing: ArchiveListing | None = None
    extracted_files: dict[str, bytes] = field(default_factory=dict)
    list_failure: Exception | None = None
    test_failure: Exception | None = None
    extract_failure: Exception | None = None
    list_calls: int = 0
    test_calls: int = 0
    extract_calls: int = 0

    def probe(self, required_format=None) -> ArchiveBackendCapability:
        if (
            self.capability.available
            and required_format is not None
            and required_format not in self.capability.supported_formats
        ):
            return ArchiveBackendCapability(
                available=False,
                backend_name=self.capability.backend_name,
                version=self.capability.version,
                supported_formats=self.capability.supported_formats,
                reason=f"{required_format}_format_unsupported",
            )
        return self.capability

    def list_archive(self, source_path, *, archive_format, cancelled=None) -> ArchiveListing:
        self.list_calls += 1
        if self.list_failure is not None:
            raise self.list_failure
        assert self.listing is not None
        assert self.listing.archive_format == archive_format
        return self.listing

    def test_archive(self, source_path, *, archive_format, cancelled=None) -> None:
        self.test_calls += 1
        if self.test_failure is not None:
            raise self.test_failure

    def extract_archive(
        self,
        source_path,
        destination,
        *,
        archive_format,
        cancelled=None,
    ) -> None:
        self.extract_calls += 1
        if self.extract_failure is not None:
            raise self.extract_failure
        destination.mkdir(parents=True, exist_ok=False)
        for source_entry_path, content in self.extracted_files.items():
            relative = PurePosixPath(source_entry_path.replace("\\", "/"))
            target = destination.joinpath(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)


def _listing(
    entries: list[ArchiveEntry],
    *,
    archive_format: str = "7z",
    packed_size_bytes: int = 128,
) -> ArchiveListing:
    return ArchiveListing(
        archive_format=archive_format,
        entries=tuple(entries),
        packed_size_bytes=packed_size_bytes,
    )


def _file_entry(
    path: str,
    content: bytes,
    *,
    packed_size_bytes: int | None = None,
    encrypted: bool = False,
    is_special: bool = False,
) -> ArchiveEntry:
    return ArchiveEntry(
        source_path=path,
        size_bytes=len(content),
        packed_size_bytes=(len(content) if packed_size_bytes is None else packed_size_bytes),
        is_directory=False,
        encrypted=encrypted,
        is_special=is_special,
    )


def _write_7z(
    path: Path,
    entries: list[tuple[str, bytes]],
    *,
    password: str = "",
) -> None:
    capability = probe_archive_backend("7z")
    assert capability.available and capability.executable_path is not None
    fixture_root = path.parent / f".{path.stem}-contents"
    fixture_root.mkdir(parents=True, exist_ok=True)
    for relative_path, content in entries:
        target = fixture_root.joinpath(*PurePosixPath(relative_path).parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        str(capability.executable_path),
        "a",
        "-t7z",
        "-mx=1",
        "-bd",
        "-y",
    ]
    if password:
        command.extend([f"-p{password}", "-mhe=on"])
    command.extend([str(path.resolve()), "."])
    completed = subprocess.run(
        command,
        cwd=fixture_root,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert completed.returncode == 0


def _rar4_header(header_type: int, flags: int, body: bytes = b"") -> bytes:
    header_size = 7 + len(body)
    header_without_crc = bytes((header_type,)) + struct.pack("<HH", flags, header_size) + body
    header_crc = zlib.crc32(header_without_crc) & 0xFFFF
    return struct.pack("<H", header_crc) + header_without_crc


def _write_rar(path: Path, entries: list[tuple[str, bytes]]) -> None:
    payload = bytearray(b"Rar!\x1a\x07\x00")
    payload.extend(_rar4_header(0x73, 0, b"\x00" * 6))
    for source_path, content in entries:
        encoded_name = source_path.replace("/", "\\").encode("ascii")
        file_body = struct.pack(
            "<IIBIIBBHI",
            len(content),
            len(content),
            2,
            zlib.crc32(content) & 0xFFFFFFFF,
            0,
            20,
            0x30,
            len(encoded_name),
            0x20,
        ) + encoded_name
        payload.extend(_rar4_header(0x74, 0x8000, file_body))
        payload.extend(content)
    payload.extend(_rar4_header(0x7B, 0))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def _assert_backend_probe_and_fake_contract(root: Path) -> None:
    capability = probe_archive_backend("7z")
    assert capability.available
    assert capability.backend_name == "7zip"
    assert capability.version
    assert {"7z", "rar"} <= capability.supported_formats

    source = root / "fake.7z"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"fake archive handled by injected backend")
    files = {
        "chapters/01.txt": b"chapter one",
        "pages/001.png": b"page one",
        "metadata.bin": b"ignored",
        "nested/book.epub": b"ignored nested",
    }
    backend = _FakeArchiveBackend(
        capability=_available_capability(),
        listing=_listing([_file_entry(path, content) for path, content in files.items()]),
        extracted_files=files,
    )
    request = _request(root, source)
    result = preprocess_material(request, archive_backend=backend)
    assert result.succeeded
    assert len(result.derived_materials) == 2
    assert _warning_codes(result) == {
        "entry_suffix_unsupported",
        "nested_container_not_supported",
    }
    assert backend.list_calls == backend.test_calls == backend.extract_calls == 1
    assert (request.output_root / "text" / "chapters" / "01.txt").read_bytes() == b"chapter one"
    assert (request.output_root / "images" / "pages" / "001.png").is_file()
    manifest = json.loads(request.manifest_path.read_text(encoding="utf-8"))
    assert manifest["source_suffix"] == ".7z"
    assert manifest["preprocessor"] == "archive"
    assert len(manifest["entry_summaries"]) == 4
    assert {item["status"] for item in manifest["entry_summaries"]} == {
        "materialized",
        "rejected",
    }
    assert not any("executable_path" in warning.get("context", {}) for warning in manifest["warnings"])


def _assert_fake_backend_failure_boundaries(root: Path) -> None:
    source = root / "fake.7z"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"fake")

    missing = _FakeArchiveBackend(
        ArchiveBackendCapability(
            available=False,
            backend_name="missing-7zip",
            reason="executable_not_found",
        )
    )
    missing_result = preprocess_material(
        _request(root / "missing", source),
        archive_backend=missing,
    )
    assert missing_result.status == "failed"
    assert _warning_codes(missing_result) == {"archive_backend_unavailable"}
    assert missing.list_calls == missing.test_calls == missing.extract_calls == 0

    password = _FakeArchiveBackend(
        _available_capability(),
        list_failure=ArchivePasswordRequiredError("ArchivePasswordRequired"),
    )
    password_result = preprocess_material(
        _request(root / "password", source),
        archive_backend=password,
    )
    assert password_result.status == "failed"
    assert _warning_codes(password_result) == {"archive_password_protected"}

    content = b"valid"
    corrupt = _FakeArchiveBackend(
        _available_capability(),
        listing=_listing([_file_entry("valid.txt", content)]),
        test_failure=ArchiveContainerInvalidError("ArchiveContainerInvalid"),
    )
    corrupt_result = preprocess_material(
        _request(root / "corrupt", source),
        archive_backend=corrupt,
    )
    assert corrupt_result.status == "failed"
    assert _warning_codes(corrupt_result) == {"archive_container_invalid"}
    assert corrupt.extract_calls == 0

    unsafe = _FakeArchiveBackend(
        _available_capability(),
        listing=_listing([_file_entry("../escape.txt", b"escape")]),
    )
    unsafe_result = preprocess_material(
        _request(root / "unsafe", source),
        archive_backend=unsafe,
    )
    assert unsafe_result.status == "failed"
    assert _warning_codes(unsafe_result) == {"entry_path_unsafe"}
    assert unsafe.test_calls == unsafe.extract_calls == 0
    assert not (root / "escape.txt").exists()

    encrypted = _FakeArchiveBackend(
        _available_capability(),
        listing=_listing([_file_entry("secret.txt", b"secret", encrypted=True)]),
    )
    encrypted_result = preprocess_material(
        _request(root / "encrypted-entry", source),
        archive_backend=encrypted,
    )
    assert encrypted_result.status == "failed"
    assert _warning_codes(encrypted_result) == {"archive_password_protected"}
    assert encrypted.extract_calls == 0

    special = _FakeArchiveBackend(
        _available_capability(),
        listing=_listing([_file_entry("link.txt", b"target", is_special=True)]),
    )
    special_result = preprocess_material(
        _request(root / "special-entry", source),
        archive_backend=special,
    )
    assert special_result.status == "failed"
    assert _warning_codes(special_result) == {"entry_type_unsupported"}
    assert special.extract_calls == 0

    special_directory = _FakeArchiveBackend(
        _available_capability(),
        listing=_listing(
            [
                ArchiveEntry(
                    source_path="linked-directory",
                    size_bytes=0,
                    packed_size_bytes=0,
                    is_directory=True,
                    encrypted=False,
                    is_special=True,
                )
            ]
        ),
    )
    special_directory_result = preprocess_material(
        _request(root / "special-directory", source),
        archive_backend=special_directory,
    )
    assert special_directory_result.status == "failed"
    assert _warning_codes(special_directory_result) == {"entry_type_unsupported"}
    assert special_directory.extract_calls == 0

    collision_files = {
        "Case/Name.txt": b"first",
        "case/name.TXT": b"second",
    }
    collision = _FakeArchiveBackend(
        _available_capability(),
        listing=_listing(
            [_file_entry(path, content) for path, content in collision_files.items()]
        ),
    )
    collision_result = preprocess_material(
        _request(root / "collision", source),
        archive_backend=collision,
    )
    assert collision_result.status == "failed"
    assert _warning_codes(collision_result) == {"entry_path_collision"}
    assert collision.extract_calls == 0

    ratio = _FakeArchiveBackend(
        _available_capability(),
        listing=_listing(
            [_file_entry("repeated.txt", b"x" * 128, packed_size_bytes=1)],
            packed_size_bytes=1,
        ),
    )
    ratio_result = preprocess_material(
        _request(
            root / "ratio",
            source,
            limits=PreprocessingLimits(max_compression_ratio=10),
        ),
        archive_backend=ratio,
    )
    assert ratio_result.status == "failed"
    assert _warning_codes(ratio_result) == {"compression_ratio_limit_exceeded"}
    assert ratio.extract_calls == 0

    cancelled = _FakeArchiveBackend(
        _available_capability(),
        list_failure=ArchiveBackendCancelledError("ArchiveBackendCancelled"),
    )
    cancelled_result = preprocess_material(
        _request(root / "cancelled", source),
        archive_backend=cancelled,
    )
    assert cancelled_result.status == "cancelled"
    assert not cancelled_result.manifest_path.exists()

    mismatched = _FakeArchiveBackend(
        _available_capability(),
        listing=_listing([_file_entry("listed.txt", b"listed")]),
        extracted_files={"listed.txt": b"listed", "extra.txt": b"extra"},
    )
    mismatch_result = preprocess_material(
        _request(root / "mismatched", source),
        archive_backend=mismatched,
    )
    assert mismatch_result.status == "failed"
    assert _warning_codes(mismatch_result) == {"archive_extracted_tree_invalid"}
    assert not mismatch_result.output_root.exists()

    oversized = _FakeArchiveBackend(
        _available_capability(),
        listing=_listing([_file_entry("large.txt", b"12345")]),
    )
    oversized_result = preprocess_material(
        _request(
            root / "oversized",
            source,
            limits=PreprocessingLimits(max_entry_size_bytes=4),
        ),
        archive_backend=oversized,
    )
    assert oversized_result.status == "failed"
    assert _warning_codes(oversized_result) == {"entry_size_limit_exceeded"}
    assert oversized.extract_calls == 0


def _assert_missing_backend_workflow(root: Path) -> None:
    import utils.archive_material_preprocessor as archive_preprocessor

    projects_root = root / "projects"
    external_source = root / "external" / "missing-backend.7z"
    external_source.parent.mkdir(parents=True)
    external_source.write_bytes(b"fake")
    project_id = "7z-missing-backend"
    config = ProjectConfig(
        project_id=project_id,
        name="Missing archive backend validation",
        source_paths=[str(external_source)],
    )
    missing = _FakeArchiveBackend(
        ArchiveBackendCapability(
            available=False,
            backend_name="missing-7zip",
            reason="executable_not_found",
        )
    )

    previous_projects_root = path_utils.PROJECTS_ROOT
    original_default_backend = archive_preprocessor.default_archive_backend
    path_utils.PROJECTS_ROOT = projects_root
    archive_preprocessor.default_archive_backend = lambda: missing
    try:
        result = process_source_request(config)
        project_root = projects_root / project_id
        raw_source = project_root / "raw" / external_source.name
        assert result.preprocessed_source_count == 0
        assert result.derived_material_count == 0
        assert result.preprocessing_warning_codes == ["archive_backend_unavailable"]
        assert raw_source.is_file()
        assert not (project_root / "materials" / external_source.name).exists()
        assert not list((project_root / "cache" / "material_preprocessing").rglob("*.json"))
        assert remove_project_sources(project_id, [str(external_source)]) == 1
        assert not raw_source.exists()
    finally:
        archive_preprocessor.default_archive_backend = original_default_backend
        path_utils.PROJECTS_ROOT = previous_projects_root


def _assert_7z_profile_end_to_end(root: Path) -> None:
    projects_root = root / "projects"
    external_source = root / "external" / "mixed-materials.7z"
    _write_7z(
        external_source,
        [
            ("pages/001.png", b"page-one"),
            ("text/chapter.txt", b"chapter"),
            ("metadata.bin", b"ignored"),
            ("nested/book.epub", b"nested"),
        ],
    )
    project_id = "7z-profile-e2e"
    config = ProjectConfig(
        project_id=project_id,
        name="7z profile validation",
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
        assert result.derived_material_count == 2
        assert set(result.preprocessing_warning_codes) == {
            "entry_suffix_unsupported",
            "nested_container_not_supported",
        }
        assert raw_source.is_file()
        assert not (project_root / "materials" / external_source.name).exists()

        request = _project_request(project_root, raw_source)
        manifest = json.loads(request.manifest_path.read_text(encoding="utf-8"))
        assert manifest["source_suffix"] == ".7z"
        assert manifest["preprocessor"] == "archive"
        assert len(manifest["entry_summaries"]) >= 4
        assert {record["source_entry_path"] for record in manifest["derived_materials"]} == {
            "pages\\001.png",
            "text\\chapter.txt",
        }

        episodes = scan_formal_materials(project_id)
        units = [unit for episode in episodes for unit in episode.units]
        assert len(units) == 2
        assert {unit.media_type.value for unit in units} == {"image", "text"}
        assert {
            unit.material_ref.metadata["source_entry_path"] for unit in units
        } == {"pages\\001.png", "text\\chapter.txt"}
        assert all(
            unit.material_ref.metadata["preprocessed_from_raw"] == f"raw/{external_source.name}"
            for unit in units
        )
        run_plan = FormalExtractionRunPlan(project_id=project_id, episodes=episodes)
        assert len(run_plan.all_units) == 2
        assert all(
            unit.material_ref.metadata["container_format"] == "7z"
            for unit in run_plan.all_units
        )

        reused = preprocess_project_source(
            _project_request(project_root, raw_source),
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


def _assert_real_backend_failure_boundaries(root: Path) -> None:
    encrypted_source = root / "encrypted" / "secret.7z"
    _write_7z(encrypted_source, [("secret.txt", b"secret")], password="validation-password")
    encrypted_result = preprocess_material(_request(root / "encrypted", encrypted_source))
    assert encrypted_result.status == "failed"
    assert _warning_codes(encrypted_result) == {"archive_password_protected"}
    assert not encrypted_result.manifest_path.exists()

    corrupt_source = root / "corrupt" / "corrupt.7z"
    corrupt_source.parent.mkdir(parents=True)
    corrupt_source.write_bytes(b"not a 7z archive")
    corrupt_result = preprocess_material(_request(root / "corrupt", corrupt_source))
    assert corrupt_result.status == "failed"
    assert _warning_codes(corrupt_result) == {"archive_container_invalid"}
    assert not corrupt_result.manifest_path.exists()


def _assert_rar_fake_contract_and_boundaries(root: Path) -> None:
    capability = probe_archive_backend("rar")
    assert capability.available
    assert "rar" in capability.supported_formats

    source = root / "fake.rar"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"fake RAR handled by injected backend")
    files = {
        "chapters/01.txt": b"rar chapter",
        "pages/001.jpg": b"rar image",
        "nested/archive.7z": b"ignored nested",
    }
    backend = _FakeArchiveBackend(
        capability=_available_capability(),
        listing=_listing(
            [_file_entry(path, content) for path, content in files.items()],
            archive_format="rar",
        ),
        extracted_files=files,
    )
    request = _request(root / "valid", source)
    result = preprocess_material(request, archive_backend=backend)
    assert result.succeeded
    assert len(result.derived_materials) == 2
    assert _warning_codes(result) == {"nested_container_not_supported"}
    assert backend.list_calls == backend.test_calls == backend.extract_calls == 1

    password = _FakeArchiveBackend(
        _available_capability(),
        list_failure=ArchivePasswordRequiredError("ArchivePasswordRequired"),
    )
    password_result = preprocess_material(
        _request(root / "password", source),
        archive_backend=password,
    )
    assert password_result.status == "failed"
    assert _warning_codes(password_result) == {"archive_password_protected"}

    unsafe = _FakeArchiveBackend(
        _available_capability(),
        listing=_listing(
            [_file_entry("../escape.txt", b"escape")],
            archive_format="rar",
        ),
    )
    unsafe_result = preprocess_material(
        _request(root / "unsafe", source),
        archive_backend=unsafe,
    )
    assert unsafe_result.status == "failed"
    assert _warning_codes(unsafe_result) == {"entry_path_unsafe"}
    assert unsafe.test_calls == unsafe.extract_calls == 0
    assert not (root / "escape.txt").exists()


def _assert_rar5_listing_contract() -> None:
    listing = _parse_listing(
        """Path = fixture.rar
Type = Rar5
Physical Size = 128

----------
Path = pages\\001.png
Folder = -
Size = 4
Packed Size = 4
Attributes = A
Encrypted = -
Volume Index =
""",
        "rar",
    )
    assert listing.archive_format == "rar"
    assert listing.packed_size_bytes == 128
    assert len(listing.entries) == 1
    assert listing.entries[0].source_path == "pages\\001.png"


def _assert_rar_missing_backend_workflow(root: Path) -> None:
    import utils.archive_material_preprocessor as archive_preprocessor

    projects_root = root / "projects"
    external_source = root / "external" / "missing-backend.rar"
    external_source.parent.mkdir(parents=True)
    external_source.write_bytes(b"fake")
    project_id = "rar-missing-backend"
    config = ProjectConfig(
        project_id=project_id,
        name="Missing RAR backend validation",
        source_paths=[str(external_source)],
    )
    missing = _FakeArchiveBackend(
        ArchiveBackendCapability(
            available=False,
            backend_name="missing-7zip",
            reason="executable_not_found",
        )
    )

    previous_projects_root = path_utils.PROJECTS_ROOT
    original_default_backend = archive_preprocessor.default_archive_backend
    path_utils.PROJECTS_ROOT = projects_root
    archive_preprocessor.default_archive_backend = lambda: missing
    try:
        result = process_source_request(config)
        project_root = projects_root / project_id
        raw_source = project_root / "raw" / external_source.name
        assert result.preprocessed_source_count == 0
        assert result.derived_material_count == 0
        assert result.preprocessing_warning_codes == ["archive_backend_unavailable"]
        assert raw_source.is_file()
        assert not (project_root / "materials" / external_source.name).exists()
        assert remove_project_sources(project_id, [str(external_source)]) == 1
        assert not raw_source.exists()
    finally:
        archive_preprocessor.default_archive_backend = original_default_backend
        path_utils.PROJECTS_ROOT = previous_projects_root


def _assert_rar_profile_end_to_end(root: Path) -> None:
    projects_root = root / "projects"
    external_source = root / "external" / "mixed-materials.rar"
    _write_rar(
        external_source,
        [
            ("pages/001.png", b"rar-page"),
            ("text/chapter.txt", b"rar-chapter"),
            ("metadata.bin", b"ignored"),
            ("nested/book.epub", b"nested"),
        ],
    )
    project_id = "rar-profile-e2e"
    config = ProjectConfig(
        project_id=project_id,
        name="RAR profile validation",
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
        assert result.derived_material_count == 2
        assert set(result.preprocessing_warning_codes) == {
            "entry_suffix_unsupported",
            "nested_container_not_supported",
        }
        assert raw_source.is_file()
        assert not (project_root / "materials" / external_source.name).exists()

        request = _project_request(project_root, raw_source)
        manifest = json.loads(request.manifest_path.read_text(encoding="utf-8"))
        assert manifest["source_suffix"] == ".rar"
        assert manifest["preprocessor"] == "archive"
        assert {record["source_entry_path"] for record in manifest["derived_materials"]} == {
            "pages\\001.png",
            "text\\chapter.txt",
        }

        episodes = scan_formal_materials(project_id)
        units = [unit for episode in episodes for unit in episode.units]
        assert len(units) == 2
        assert {unit.media_type.value for unit in units} == {"image", "text"}
        assert all(
            unit.material_ref.metadata["preprocessed_from_raw"] == f"raw/{external_source.name}"
            for unit in units
        )
        run_plan = FormalExtractionRunPlan(project_id=project_id, episodes=episodes)
        assert len(run_plan.all_units) == 2
        assert all(
            unit.material_ref.metadata["container_format"] == "rar"
            for unit in run_plan.all_units
        )

        reused = preprocess_project_source(
            _project_request(project_root, raw_source),
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


def _assert_real_rar_corrupt_boundary(root: Path) -> None:
    corrupt_source = root / "corrupt" / "corrupt.rar"
    corrupt_source.parent.mkdir(parents=True)
    corrupt_source.write_bytes(b"not a RAR archive")
    corrupt_result = preprocess_material(_request(root / "corrupt", corrupt_source))
    assert corrupt_result.status == "failed"
    assert _warning_codes(corrupt_result) == {"archive_container_invalid"}
    assert not corrupt_result.manifest_path.exists()


def _assert_cbr_fake_failure_boundaries(root: Path) -> None:
    source = root / "fake.cbr"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"fake CBR handled by injected backend")

    password = _FakeArchiveBackend(
        _available_capability(),
        list_failure=ArchivePasswordRequiredError("ArchivePasswordRequired"),
    )
    password_result = preprocess_material(
        _request(root / "password", source),
        archive_backend=password,
    )
    assert password_result.status == "failed"
    assert _warning_codes(password_result) == {"archive_password_protected"}

    unsafe = _FakeArchiveBackend(
        _available_capability(),
        listing=_listing(
            [_file_entry("../escape.png", b"escape")],
            archive_format="rar",
        ),
    )
    unsafe_result = preprocess_material(
        _request(root / "unsafe", source),
        archive_backend=unsafe,
    )
    assert unsafe_result.status == "failed"
    assert _warning_codes(unsafe_result) == {"entry_path_unsafe"}
    assert unsafe.test_calls == unsafe.extract_calls == 0
    assert not (root / "escape.png").exists()


def _assert_cbr_missing_backend_workflow(root: Path) -> None:
    import utils.archive_material_preprocessor as archive_preprocessor

    projects_root = root / "projects"
    external_source = root / "external" / "missing-backend.cbr"
    external_source.parent.mkdir(parents=True)
    external_source.write_bytes(b"fake")
    project_id = "cbr-missing-backend"
    config = ProjectConfig(
        project_id=project_id,
        name="Missing CBR backend validation",
        source_paths=[str(external_source)],
    )
    missing = _FakeArchiveBackend(
        ArchiveBackendCapability(
            available=False,
            backend_name="missing-7zip",
            reason="executable_not_found",
        )
    )

    previous_projects_root = path_utils.PROJECTS_ROOT
    original_default_backend = archive_preprocessor.default_archive_backend
    path_utils.PROJECTS_ROOT = projects_root
    archive_preprocessor.default_archive_backend = lambda: missing
    try:
        result = process_source_request(config)
        project_root = projects_root / project_id
        raw_source = project_root / "raw" / external_source.name
        assert result.preprocessed_source_count == 0
        assert result.derived_material_count == 0
        assert result.preprocessing_warning_codes == ["archive_backend_unavailable"]
        assert raw_source.is_file()
        assert not (project_root / "materials" / external_source.name).exists()
        assert remove_project_sources(project_id, [str(external_source)]) == 1
        assert not raw_source.exists()
    finally:
        archive_preprocessor.default_archive_backend = original_default_backend
        path_utils.PROJECTS_ROOT = previous_projects_root


def _assert_cbr_profile_end_to_end(root: Path) -> None:
    projects_root = root / "projects"
    external_source = root / "external" / "chapter.cbr"
    _write_rar(
        external_source,
        [
            ("chapter/page10.png", b"page-ten"),
            ("cover/page1.webp", b"cover"),
            ("chapter/page2.jpg", b"page-two"),
            ("notes.txt", b"not a comic page"),
            ("nested/archive.zip", b"nested"),
        ],
    )
    project_id = "cbr-profile-e2e"
    config = ProjectConfig(
        project_id=project_id,
        name="CBR profile validation",
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
        assert result.derived_material_count == 3
        assert set(result.preprocessing_warning_codes) == {
            "cbr_entry_not_image",
            "nested_container_not_supported",
        }
        assert raw_source.is_file()
        assert not (project_root / "materials" / external_source.name).exists()

        request = _project_request(project_root, raw_source)
        manifest = json.loads(request.manifest_path.read_text(encoding="utf-8"))
        assert manifest["source_suffix"] == ".cbr"
        assert manifest["preprocessor"] == "archive"
        records = manifest["derived_materials"]
        assert [record["source_entry_path"] for record in records] == [
            "chapter\\page2.jpg",
            "chapter\\page10.png",
            "cover\\page1.webp",
        ]
        assert [record["page_number"] for record in records] == [1, 2, 3]
        assert all(record["content_form_hint"] == "manga" for record in records)
        assert [Path(record["material_relative_path"]).name for record in records] == [
            "page_0001.jpg",
            "page_0002.png",
            "page_0003.webp",
        ]
        assert set(manifest["failed_entries"]) == {
            "notes.txt",
            "nested\\archive.zip",
        }

        episodes = scan_formal_materials(project_id)
        assert len(episodes) == 1
        episode = episodes[0]
        assert "manga" in {content_form.value for content_form in episode.content_forms}
        assert [
            unit.material_ref.metadata["source_entry_path"] for unit in episode.units
        ] == [
            "chapter\\page2.jpg",
            "chapter\\page10.png",
            "cover\\page1.webp",
        ]
        assert [unit.material_ref.page_range.start_page for unit in episode.units] == [1, 2, 3]
        run_plan = FormalExtractionRunPlan(project_id=project_id, episodes=episodes)
        assert [unit.material_ref.metadata["page_number"] for unit in run_plan.all_units] == [
            1,
            2,
            3,
        ]
        assert all(
            unit.material_ref.metadata["container_format"] == "cbr"
            for unit in run_plan.all_units
        )

        reused = preprocess_project_source(
            _project_request(project_root, raw_source),
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


def _assert_real_cbr_corrupt_boundary(root: Path) -> None:
    corrupt_source = root / "corrupt" / "corrupt.cbr"
    corrupt_source.parent.mkdir(parents=True)
    corrupt_source.write_bytes(b"not a CBR archive")
    corrupt_result = preprocess_material(_request(root / "corrupt", corrupt_source))
    assert corrupt_result.status == "failed"
    assert _warning_codes(corrupt_result) == {"archive_container_invalid"}
    assert not corrupt_result.manifest_path.exists()


def _assert_profile_gate() -> None:
    for suffix in (".7z", ".rar", ".cbr"):
        profile = input_format_profile(f"fixture{suffix}")
        assert profile is not None
        assert profile.state == InputFormatSupportState.ENABLED
        assert profile.display_name_key == f"project.inputFormat.{suffix.lstrip('.')}"
        assert is_preprocessable_source(f"fixture{suffix}")
        assert f"*{suffix}" in project_input_file_patterns()


def main() -> None:
    with TemporaryDirectory(prefix="charapicker-archive-validation-") as temp_dir:
        root = Path(temp_dir)
        _assert_backend_probe_and_fake_contract(root / "backend")
        _assert_fake_backend_failure_boundaries(root / "fake-boundaries")
        _assert_missing_backend_workflow(root / "missing-workflow")
        _assert_7z_profile_end_to_end(root / "profile")
        _assert_real_backend_failure_boundaries(root / "real-boundaries")
        _assert_rar_fake_contract_and_boundaries(root / "rar-fake")
        _assert_rar5_listing_contract()
        _assert_rar_missing_backend_workflow(root / "rar-missing-workflow")
        _assert_rar_profile_end_to_end(root / "rar-profile")
        _assert_real_rar_corrupt_boundary(root / "rar-real-boundaries")
        _assert_cbr_fake_failure_boundaries(root / "cbr-fake")
        _assert_cbr_missing_backend_workflow(root / "cbr-missing-workflow")
        _assert_cbr_profile_end_to_end(root / "cbr-profile")
        _assert_real_cbr_corrupt_boundary(root / "cbr-real-boundaries")
        _assert_profile_gate()
    print("7z/RAR/CBR archive material preprocessing validation passed")


if __name__ == "__main__":
    main()
