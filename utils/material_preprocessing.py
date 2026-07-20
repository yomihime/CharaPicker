"""Safe preprocessing primitives for container-style project inputs."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Callable, Literal

from utils.media_types import InputPreprocessorKey


CancelledCallback = Callable[[], bool]
PreprocessingStatus = Literal["completed", "failed", "cancelled"]
WarningContextValue = str | int | float | bool

PREPROCESSING_MANIFEST_SCHEMA_VERSION = 1
DERIVED_INPUTS_DIRECTORY_NAME = "derived_inputs"
PREPROCESSING_CACHE_DIRECTORY_NAME = "material_preprocessing"
_COPY_CHUNK_SIZE = 1024 * 1024
_SOURCE_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


@dataclass(frozen=True)
class PreprocessingLimits:
    max_entries: int = 4096
    max_entry_size_bytes: int = 512 * 1024 * 1024
    max_expanded_size_bytes: int = 4 * 1024 * 1024 * 1024
    max_compression_ratio: float = 200.0

    def __post_init__(self) -> None:
        if self.max_entries <= 0:
            raise ValueError("max_entries must be positive")
        if self.max_entry_size_bytes <= 0:
            raise ValueError("max_entry_size_bytes must be positive")
        if self.max_expanded_size_bytes <= 0:
            raise ValueError("max_expanded_size_bytes must be positive")
        if self.max_compression_ratio <= 0:
            raise ValueError("max_compression_ratio must be positive")


DEFAULT_PREPROCESSING_LIMITS = PreprocessingLimits()


@dataclass(frozen=True)
class PreprocessingWarning:
    code: str
    message: str
    entry_path: str | None = None
    context: dict[str, WarningContextValue] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "code": self.code,
            "message": self.message,
        }
        if self.entry_path is not None:
            payload["entry_path"] = self.entry_path
        if self.context:
            payload["context"] = dict(self.context)
        return payload


@dataclass(frozen=True)
class DerivedMaterialRecord:
    material_relative_path: str
    source_entry_path: str
    media_type: str
    content_form_hint: str
    original_name: str
    size_bytes: int
    fingerprint: str
    page_number: int | None = None
    chapter_index: int | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "material_relative_path": self.material_relative_path,
            "source_entry_path": self.source_entry_path,
            "media_type": self.media_type,
            "content_form_hint": self.content_form_hint,
            "page_number": self.page_number,
            "chapter_index": self.chapter_index,
            "original_name": self.original_name,
            "size_bytes": self.size_bytes,
            "fingerprint": self.fingerprint,
        }


@dataclass(frozen=True)
class PreprocessingEntrySummary:
    source_entry_path: str
    role: str
    media_type: str = ""
    media_subtype: str = ""
    spine_index: int | None = None
    title: str = ""
    size_bytes: int = 0
    status: str = "observed"

    def to_dict(self) -> dict[str, object]:
        return {
            "source_entry_path": self.source_entry_path,
            "role": self.role,
            "media_type": self.media_type,
            "media_subtype": self.media_subtype,
            "spine_index": self.spine_index,
            "title": self.title,
            "size_bytes": self.size_bytes,
            "status": self.status,
        }


@dataclass(frozen=True)
class PreprocessingExtractionSummary:
    derived_materials: tuple[DerivedMaterialRecord, ...] = ()
    entry_summaries: tuple[PreprocessingEntrySummary, ...] = ()
    warnings: tuple[PreprocessingWarning, ...] = ()
    failed_entries: tuple[str, ...] = ()
    entry_count: int = 0
    expanded_size_bytes: int = 0
    fatal: bool = False


@dataclass(frozen=True)
class PreprocessingRequest:
    source_path: Path
    source_raw_path: str
    output_root: Path
    output_root_reference: str
    manifest_path: Path
    preprocessor_key: InputPreprocessorKey
    source_hash: str = ""
    limits: PreprocessingLimits = DEFAULT_PREPROCESSING_LIMITS
    cancelled: CancelledCallback | None = None
    staging_root: Path | None = None


@dataclass(frozen=True)
class PreprocessingResult:
    status: PreprocessingStatus
    source_hash: str
    output_root: Path
    manifest_path: Path
    derived_materials: tuple[DerivedMaterialRecord, ...] = ()
    entry_summaries: tuple[PreprocessingEntrySummary, ...] = ()
    warnings: tuple[PreprocessingWarning, ...] = ()
    failed_entries: tuple[str, ...] = ()
    entry_count: int = 0
    input_size_bytes: int = 0
    expanded_size_bytes: int = 0
    reused: bool = False

    @property
    def succeeded(self) -> bool:
        return self.status == "completed"


@dataclass(frozen=True)
class ArchivePathValidation:
    relative_path: PurePosixPath | None
    warning_code: str = ""
    warning_message: str = ""


@dataclass(frozen=True)
class PreprocessingArtifactPaths:
    source_hash: str
    source_raw_path: str
    output_root: Path
    output_root_reference: str
    manifest_path: Path


class PreprocessingCancelledError(RuntimeError):
    pass


def preprocess_material(request: PreprocessingRequest) -> PreprocessingResult:
    """Preprocess one source without exposing partial output or manifest files."""
    source = request.source_path.resolve()
    output_root = request.output_root.resolve()
    manifest_path = request.manifest_path.resolve()
    input_size = _safe_file_size(source)

    request_warning = _validate_request(request, source, output_root, manifest_path)
    if request_warning is not None:
        return _failed_result(request, request_warning, input_size_bytes=input_size)

    try:
        source_hash = request.source_hash or source_content_hash(source, request.cancelled)
        if not _SOURCE_HASH_PATTERN.fullmatch(source_hash):
            return _failed_result(
                request,
                PreprocessingWarning(
                    code="source_hash_invalid",
                    message="The preprocessing source hash is invalid.",
                ),
                input_size_bytes=input_size,
            )
        _raise_if_cancelled(request.cancelled)
    except PreprocessingCancelledError:
        return _cancelled_result(request, input_size_bytes=input_size)
    except OSError as exc:
        return _failed_result(
            request,
            PreprocessingWarning(
                code="source_read_failed",
                message="The source container could not be read.",
                context={"error_type": type(exc).__name__},
            ),
            input_size_bytes=input_size,
        )

    staging_parent = (request.staging_root or output_root.parent).resolve()
    staging_parent.mkdir(parents=True, exist_ok=True)
    stage_root = Path(tempfile.mkdtemp(prefix=".material-preprocessing-", dir=staging_parent))
    staged_output = stage_root / "output"
    staged_manifest = stage_root / "manifest.json"
    staged_output.mkdir()

    try:
        if request.preprocessor_key in {"zip", "cbz"}:
            from utils.zip_material_preprocessor import extract_zip_materials

            extraction = extract_zip_materials(request, staged_output)
        elif request.preprocessor_key == "epub":
            from utils.epub_material_preprocessor import extract_epub_materials

            extraction = extract_epub_materials(request, staged_output)
        else:
            return _failed_result(
                request,
                PreprocessingWarning(
                    code="preprocessor_not_implemented",
                    message="The selected input preprocessor is not implemented.",
                    context={"preprocessor": request.preprocessor_key},
                ),
                source_hash=source_hash,
                input_size_bytes=input_size,
            )

        _raise_if_cancelled(request.cancelled)
        if extraction.fatal:
            return PreprocessingResult(
                status="failed",
                source_hash=source_hash,
                output_root=request.output_root,
                manifest_path=request.manifest_path,
                warnings=extraction.warnings,
                entry_summaries=extraction.entry_summaries,
                failed_entries=extraction.failed_entries,
                entry_count=extraction.entry_count,
                input_size_bytes=input_size,
                expanded_size_bytes=extraction.expanded_size_bytes,
            )

        manifest = _build_manifest(
            request=request,
            source_hash=source_hash,
            input_size_bytes=input_size,
            derived_materials=extraction.derived_materials,
            entry_summaries=extraction.entry_summaries,
            warnings=extraction.warnings,
            failed_entries=extraction.failed_entries,
            entry_count=extraction.entry_count,
            expanded_size_bytes=extraction.expanded_size_bytes,
        )
        staged_manifest.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        _raise_if_cancelled(request.cancelled)
        _commit_preprocessing_outputs(
            staged_output=staged_output,
            output_root=output_root,
            staged_manifest=staged_manifest,
            manifest_path=manifest_path,
            stage_root=stage_root,
        )
        return PreprocessingResult(
            status="completed",
            source_hash=source_hash,
            output_root=request.output_root,
            manifest_path=request.manifest_path,
            derived_materials=extraction.derived_materials,
            entry_summaries=extraction.entry_summaries,
            warnings=extraction.warnings,
            failed_entries=extraction.failed_entries,
            entry_count=extraction.entry_count,
            input_size_bytes=input_size,
            expanded_size_bytes=extraction.expanded_size_bytes,
        )
    except PreprocessingCancelledError:
        return _cancelled_result(
            request,
            source_hash=source_hash,
            input_size_bytes=input_size,
        )
    except OSError as exc:
        return _failed_result(
            request,
            PreprocessingWarning(
                code="preprocessing_io_failed",
                message="The preprocessing output could not be written.",
                context={"error_type": type(exc).__name__},
            ),
            source_hash=source_hash,
            input_size_bytes=input_size,
        )
    finally:
        shutil.rmtree(stage_root, ignore_errors=True)


def source_content_hash(path: Path, cancelled: CancelledCallback | None = None) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(_COPY_CHUNK_SIZE):
            _raise_if_cancelled(cancelled)
            digest.update(chunk)
    return digest.hexdigest()


def preprocessing_artifact_paths(
    *,
    raw_root: Path,
    materials_root: Path,
    cache_root: Path,
    raw_source: Path,
    source_hash: str,
) -> PreprocessingArtifactPaths:
    if not _SOURCE_HASH_PATTERN.fullmatch(source_hash):
        raise ValueError("source_hash must be a lowercase SHA-256 digest")
    relative_raw = raw_source.resolve().relative_to(raw_root.resolve())
    source_raw_path = PurePosixPath("raw", *relative_raw.parts).as_posix()
    safe_stem = _safe_source_stem(raw_source.stem)
    derived_name = f"{safe_stem}_{source_hash[:16]}"
    output_reference = PurePosixPath(DERIVED_INPUTS_DIRECTORY_NAME, derived_name).as_posix()
    return PreprocessingArtifactPaths(
        source_hash=source_hash,
        source_raw_path=source_raw_path,
        output_root=materials_root / DERIVED_INPUTS_DIRECTORY_NAME / derived_name,
        output_root_reference=output_reference,
        manifest_path=cache_root / PREPROCESSING_CACHE_DIRECTORY_NAME / f"{source_hash}.json",
    )


def build_project_preprocessing_request(
    *,
    raw_root: Path,
    materials_root: Path,
    cache_root: Path,
    raw_source: Path,
    preprocessor_key: InputPreprocessorKey,
    cancelled: CancelledCallback | None = None,
    limits: PreprocessingLimits = DEFAULT_PREPROCESSING_LIMITS,
) -> PreprocessingRequest:
    source_hash = source_content_hash(raw_source, cancelled)
    artifacts = preprocessing_artifact_paths(
        raw_root=raw_root,
        materials_root=materials_root,
        cache_root=cache_root,
        raw_source=raw_source,
        source_hash=source_hash,
    )
    return PreprocessingRequest(
        source_path=raw_source,
        source_raw_path=artifacts.source_raw_path,
        output_root=artifacts.output_root,
        output_root_reference=artifacts.output_root_reference,
        manifest_path=artifacts.manifest_path,
        preprocessor_key=preprocessor_key,
        source_hash=source_hash,
        limits=limits,
        cancelled=cancelled,
        staging_root=cache_root / PREPROCESSING_CACHE_DIRECTORY_NAME / "tmp",
    )


def preprocess_project_source(
    request: PreprocessingRequest,
    *,
    raw_root: Path,
    materials_root: Path,
    cache_root: Path,
) -> PreprocessingResult:
    existing = load_preprocessing_manifest(request.manifest_path)
    if existing is not None and preprocessing_manifest_is_complete(
        existing,
        materials_root=materials_root,
        expected_source_hash=request.source_hash,
        expected_source_raw_path=request.source_raw_path,
    ):
        refreshed = dict(existing)
        refreshed["input_size_bytes"] = _safe_file_size(request.source_path)
        refreshed["source_mtime_ns"] = _safe_file_mtime_ns(request.source_path)
        try:
            _write_json_atomically(request.manifest_path, refreshed)
        except OSError:
            pass
        else:
            return _result_from_manifest(request, refreshed, reused=True)

    result = preprocess_material(request)
    if result.succeeded:
        remove_stale_preprocessing_artifacts(
            raw_root=raw_root,
            materials_root=materials_root,
            cache_root=cache_root,
            raw_source=request.source_path,
            keep_source_hash=result.source_hash,
        )
    return result


def load_preprocessing_manifest(path: Path) -> dict[str, object] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("schema_version") != PREPROCESSING_MANIFEST_SCHEMA_VERSION:
        return None
    return payload


def preprocessing_material_metadata_index(materials_root: Path) -> dict[str, dict[str, object]]:
    cache_directory = (
        materials_root.parent / "cache" / PREPROCESSING_CACHE_DIRECTORY_NAME
    )
    index: dict[str, dict[str, object]] = {}
    if not cache_directory.is_dir():
        return index

    for manifest_path in sorted(cache_directory.glob("*.json")):
        manifest = load_preprocessing_manifest(manifest_path)
        if manifest is None:
            continue
        source_raw_path = _manifest_string(manifest.get("source_raw_path"))
        source_hash = _manifest_string(manifest.get("source_hash"))
        preprocessor = _manifest_string(manifest.get("preprocessor"))
        source_suffix = _manifest_string(manifest.get("source_suffix"))
        output_reference = _safe_material_reference(
            _manifest_string(manifest.get("output_root"))
        )
        if (
            not source_raw_path
            or not _SOURCE_HASH_PATTERN.fullmatch(source_hash)
            or not output_reference
            or not preprocessing_manifest_is_complete(
                manifest,
                materials_root=materials_root,
            )
            or not _manifest_matches_current_raw(materials_root.parent, manifest)
        ):
            continue
        records = manifest.get("derived_materials")
        if not isinstance(records, list):
            continue
        for record in records:
            if not isinstance(record, dict):
                continue
            relative_path = _safe_material_reference(
                _manifest_string(record.get("material_relative_path"))
            )
            if not relative_path:
                continue
            if not relative_path.startswith(f"{output_reference}/"):
                continue
            metadata: dict[str, object] = {
                "preprocessed_from_raw": source_raw_path,
                "preprocessor": preprocessor,
                "source_entry_path": _manifest_string(record.get("source_entry_path")),
                "container_format": source_suffix.lstrip("."),
                "source_hash": source_hash,
            }
            content_form_hint = _manifest_string(record.get("content_form_hint"))
            if content_form_hint:
                metadata["preprocessed_content_form_hint"] = content_form_hint
            for key in ("page_number", "chapter_index"):
                value = record.get(key)
                if isinstance(value, int) and not isinstance(value, bool):
                    metadata[key] = value
            fingerprint = _manifest_string(record.get("fingerprint"))
            if fingerprint:
                metadata["preprocessed_fingerprint"] = fingerprint
            index[relative_path] = metadata
    return index


def material_path_is_active_preprocessed_output(
    materials_root: Path,
    material_path: Path,
    metadata_index: dict[str, dict[str, object]],
) -> bool:
    try:
        relative_path = material_path.resolve().relative_to(materials_root.resolve())
    except ValueError:
        return False
    relative_reference = relative_path.as_posix()
    if not relative_path.parts or relative_path.parts[0] != DERIVED_INPUTS_DIRECTORY_NAME:
        return True
    return relative_reference in metadata_index


def preprocessing_manifest_is_complete(
    manifest: dict[str, object],
    *,
    materials_root: Path,
    expected_source_hash: str = "",
    expected_source_raw_path: str = "",
) -> bool:
    source_hash = _manifest_string(manifest.get("source_hash"))
    source_raw_path = _manifest_string(manifest.get("source_raw_path"))
    if not _SOURCE_HASH_PATTERN.fullmatch(source_hash):
        return False
    if expected_source_hash and source_hash != expected_source_hash:
        return False
    if expected_source_raw_path and source_raw_path != _normalized_reference(
        expected_source_raw_path
    ):
        return False
    output_reference = _safe_material_reference(_manifest_string(manifest.get("output_root")))
    records = manifest.get("derived_materials")
    if not output_reference or not isinstance(records, list) or not records:
        return False
    output_root = _path_from_material_reference(materials_root, output_reference)
    if output_root is None or not output_root.is_dir():
        return False
    for record in records:
        if not isinstance(record, dict):
            return False
        reference = _safe_material_reference(
            _manifest_string(record.get("material_relative_path"))
        )
        material_path = _path_from_material_reference(materials_root, reference)
        if material_path is None or not material_path.is_file():
            return False
        size_bytes = record.get("size_bytes")
        if isinstance(size_bytes, int):
            try:
                if material_path.stat().st_size != size_bytes:
                    return False
            except OSError:
                return False
    return True


def complete_preprocessing_manifest_for_raw(
    *,
    raw_root: Path,
    materials_root: Path,
    cache_root: Path,
    raw_source: Path,
) -> dict[str, object] | None:
    source_reference = _raw_source_reference(raw_root, raw_source)
    if not source_reference:
        return None
    for _path, manifest in _manifests_for_source(cache_root, source_reference):
        if preprocessing_manifest_is_complete(
            manifest,
            materials_root=materials_root,
            expected_source_raw_path=source_reference,
        ):
            return manifest
    return None


def current_preprocessing_manifest_for_raw(
    *,
    raw_root: Path,
    materials_root: Path,
    cache_root: Path,
    raw_source: Path,
) -> dict[str, object] | None:
    if not raw_source.is_file():
        return None
    try:
        source_stat = raw_source.stat()
    except OSError:
        return None
    source_reference = _raw_source_reference(raw_root, raw_source)
    if not source_reference:
        return None
    for _path, manifest in _manifests_for_source(cache_root, source_reference):
        if manifest.get("input_size_bytes") != source_stat.st_size:
            continue
        if manifest.get("source_mtime_ns") != source_stat.st_mtime_ns:
            continue
        if preprocessing_manifest_is_complete(
            manifest,
            materials_root=materials_root,
            expected_source_raw_path=source_reference,
        ):
            return manifest
    return None


def remove_preprocessing_artifacts_for_raw(
    *,
    raw_root: Path,
    materials_root: Path,
    cache_root: Path,
    raw_source: Path,
) -> int:
    source_reference = _raw_source_reference(raw_root, raw_source)
    if not source_reference:
        return 0
    removed = 0
    for manifest_path, manifest in _manifests_for_source(cache_root, source_reference):
        if _remove_manifest_output(materials_root, manifest):
            removed += 1
        manifest_path.unlink(missing_ok=True)

    if raw_source.is_file():
        try:
            source_hash = source_content_hash(raw_source)
            artifacts = preprocessing_artifact_paths(
                raw_root=raw_root,
                materials_root=materials_root,
                cache_root=cache_root,
                raw_source=raw_source,
                source_hash=source_hash,
            )
            if artifacts.output_root.exists():
                shutil.rmtree(artifacts.output_root)
                removed += 1
            artifacts.manifest_path.unlink(missing_ok=True)
        except (OSError, ValueError):
            pass
    return removed


def remove_stale_preprocessing_artifacts(
    *,
    raw_root: Path,
    materials_root: Path,
    cache_root: Path,
    raw_source: Path,
    keep_source_hash: str,
) -> int:
    source_reference = _raw_source_reference(raw_root, raw_source)
    if not source_reference:
        return 0
    removed = 0
    for manifest_path, manifest in _manifests_for_source(cache_root, source_reference):
        if _manifest_string(manifest.get("source_hash")) == keep_source_hash:
            continue
        if _remove_manifest_output(materials_root, manifest):
            removed += 1
        manifest_path.unlink(missing_ok=True)
    return removed


def _safe_source_stem(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value)
    safe = "".join(
        "_" if character in '<>:"/\\|?*' or ord(character) < 32 else character
        for character in normalized
    ).strip(" .")
    safe = re.sub(r"\s+", "_", safe)
    if not safe or safe.split(".", maxsplit=1)[0].upper() in _WINDOWS_RESERVED_NAMES:
        safe = "source"
    return safe[:40].rstrip(" .") or "source"


def _manifest_matches_current_raw(
    project_root: Path,
    manifest: dict[str, object],
) -> bool:
    source_reference = _normalized_reference(
        _manifest_string(manifest.get("source_raw_path"))
    )
    if not _is_safe_project_reference(source_reference):
        return False
    source_parts = PurePosixPath(source_reference).parts
    if not source_parts or source_parts[0] != "raw":
        return False
    raw_source = project_root.joinpath(*source_parts)
    if not raw_source.exists():
        return True
    try:
        source_stat = raw_source.stat()
    except OSError:
        return False
    return (
        manifest.get("input_size_bytes") == source_stat.st_size
        and manifest.get("source_mtime_ns") == source_stat.st_mtime_ns
    )


def _normalized_reference(value: str) -> str:
    return PurePosixPath(value.replace("\\", "/")).as_posix()


def _safe_material_reference(value: str) -> str:
    normalized = _normalized_reference(value) if value else ""
    if not _is_safe_project_reference(normalized):
        return ""
    parts = PurePosixPath(normalized).parts
    if not parts or parts[0] != DERIVED_INPUTS_DIRECTORY_NAME:
        return ""
    return PurePosixPath(*parts).as_posix()


def _path_from_material_reference(materials_root: Path, reference: str) -> Path | None:
    if not reference:
        return None
    target = materials_root.joinpath(*PurePosixPath(reference).parts).resolve()
    try:
        target.relative_to(materials_root.resolve())
    except ValueError:
        return None
    return target


def _raw_source_reference(raw_root: Path, raw_source: Path) -> str:
    try:
        relative = raw_source.resolve().relative_to(raw_root.resolve())
    except ValueError:
        return ""
    return PurePosixPath("raw", *relative.parts).as_posix()


def _manifests_for_source(
    cache_root: Path,
    source_reference: str,
) -> list[tuple[Path, dict[str, object]]]:
    directory = cache_root / PREPROCESSING_CACHE_DIRECTORY_NAME
    if not directory.is_dir():
        return []
    matches: list[tuple[Path, dict[str, object]]] = []
    for manifest_path in sorted(directory.glob("*.json")):
        manifest = load_preprocessing_manifest(manifest_path)
        if manifest is None:
            continue
        if _manifest_string(manifest.get("source_raw_path")) == source_reference:
            matches.append((manifest_path, manifest))
    return matches


def _remove_manifest_output(materials_root: Path, manifest: dict[str, object]) -> bool:
    reference = _safe_material_reference(_manifest_string(manifest.get("output_root")))
    output_root = _path_from_material_reference(materials_root, reference)
    if output_root is None or not output_root.exists():
        return False
    try:
        if output_root.is_dir():
            shutil.rmtree(output_root)
        else:
            output_root.unlink()
    except OSError:
        return False
    return True


def _result_from_manifest(
    request: PreprocessingRequest,
    manifest: dict[str, object],
    *,
    reused: bool,
) -> PreprocessingResult:
    derived_materials: list[DerivedMaterialRecord] = []
    records = manifest.get("derived_materials")
    if isinstance(records, list):
        for record in records:
            if not isinstance(record, dict):
                continue
            derived_materials.append(
                DerivedMaterialRecord(
                    material_relative_path=_manifest_string(
                        record.get("material_relative_path")
                    ),
                    source_entry_path=_manifest_string(record.get("source_entry_path")),
                    media_type=_manifest_string(record.get("media_type")),
                    content_form_hint=_manifest_string(record.get("content_form_hint")),
                    original_name=_manifest_string(record.get("original_name")),
                    size_bytes=_manifest_int(record.get("size_bytes")),
                    fingerprint=_manifest_string(record.get("fingerprint")),
                    page_number=_manifest_optional_int(record.get("page_number")),
                    chapter_index=_manifest_optional_int(record.get("chapter_index")),
                )
            )

    entry_summaries: list[PreprocessingEntrySummary] = []
    summary_records = manifest.get("entry_summaries")
    if isinstance(summary_records, list):
        for summary in summary_records:
            if not isinstance(summary, dict):
                continue
            entry_summaries.append(
                PreprocessingEntrySummary(
                    source_entry_path=_manifest_string(
                        summary.get("source_entry_path")
                    ),
                    role=_manifest_string(summary.get("role")),
                    media_type=_manifest_string(summary.get("media_type")),
                    media_subtype=_manifest_string(summary.get("media_subtype")),
                    spine_index=_manifest_optional_int(summary.get("spine_index")),
                    title=_manifest_string(summary.get("title")),
                    size_bytes=_manifest_int(summary.get("size_bytes")),
                    status=_manifest_string(summary.get("status")) or "observed",
                )
            )

    warnings: list[PreprocessingWarning] = []
    warning_records = manifest.get("warnings")
    if isinstance(warning_records, list):
        for warning in warning_records:
            if not isinstance(warning, dict):
                continue
            context = warning.get("context")
            warnings.append(
                PreprocessingWarning(
                    code=_manifest_string(warning.get("code")),
                    message=_manifest_string(warning.get("message")),
                    entry_path=_manifest_string(warning.get("entry_path")) or None,
                    context=(
                        {
                            str(key): value
                            for key, value in context.items()
                            if isinstance(value, (str, int, float, bool))
                        }
                        if isinstance(context, dict)
                        else {}
                    ),
                )
            )
    failed_entries = manifest.get("failed_entries")
    return PreprocessingResult(
        status="completed",
        source_hash=_manifest_string(manifest.get("source_hash")),
        output_root=request.output_root,
        manifest_path=request.manifest_path,
        derived_materials=tuple(derived_materials),
        entry_summaries=tuple(entry_summaries),
        warnings=tuple(warnings),
        failed_entries=(
            tuple(value for value in failed_entries if isinstance(value, str))
            if isinstance(failed_entries, list)
            else ()
        ),
        entry_count=_manifest_int(manifest.get("entry_count")),
        input_size_bytes=_manifest_int(manifest.get("input_size_bytes")),
        expanded_size_bytes=_manifest_int(manifest.get("expanded_size_bytes")),
        reused=reused,
    )


def _write_json_atomically(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.updating")
    temporary.unlink(missing_ok=True)
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def validate_archive_entry_path(entry_name: str) -> ArchivePathValidation:
    """Normalize one archive entry and reject paths unsafe on supported platforms."""
    if not entry_name or "\x00" in entry_name:
        return ArchivePathValidation(None, "entry_path_unsafe", "Archive entry path is empty.")

    normalized_separators = entry_name.replace("\\", "/")
    if normalized_separators.startswith("/") or normalized_separators.startswith("//"):
        return ArchivePathValidation(
            None,
            "entry_path_unsafe",
            "Absolute archive entry paths are not allowed.",
        )
    if len(normalized_separators) >= 2 and normalized_separators[1] == ":":
        return ArchivePathValidation(
            None,
            "entry_path_unsafe",
            "Drive-qualified archive entry paths are not allowed.",
        )

    raw_parts = normalized_separators.split("/")
    if any(part in {"", ".", ".."} for part in raw_parts):
        return ArchivePathValidation(
            None,
            "entry_path_unsafe",
            "Archive entry path traversal or empty segments are not allowed.",
        )

    normalized_parts: list[str] = []
    for part in raw_parts:
        normalized = unicodedata.normalize("NFC", part)
        if (
            normalized.endswith((" ", "."))
            or ":" in normalized
            or any(ord(character) < 32 for character in normalized)
        ):
            return ArchivePathValidation(
                None,
                "entry_path_unsafe",
                "Archive entry contains a platform-unsafe filename.",
            )
        basename = normalized.split(".", maxsplit=1)[0].upper()
        if basename in _WINDOWS_RESERVED_NAMES:
            return ArchivePathValidation(
                None,
                "entry_path_unsafe",
                "Archive entry uses a reserved Windows filename.",
            )
        normalized_parts.append(normalized)

    return ArchivePathValidation(PurePosixPath(*normalized_parts))


def normalized_path_key(path: PurePosixPath) -> str:
    return unicodedata.normalize("NFC", path.as_posix()).casefold()


def ensure_path_within_root(root: Path, relative_path: PurePosixPath) -> Path:
    target = root.joinpath(*relative_path.parts).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError("derived material escaped its output root") from exc
    return target


def _validate_request(
    request: PreprocessingRequest,
    source: Path,
    output_root: Path,
    manifest_path: Path,
) -> PreprocessingWarning | None:
    if not source.is_file():
        return PreprocessingWarning(
            code="source_missing",
            message="The source container does not exist or is not a file.",
        )
    if not _is_safe_project_reference(request.source_raw_path):
        return PreprocessingWarning(
            code="source_reference_invalid",
            message="The source raw path must be a non-empty project-relative path.",
        )
    if not _is_safe_project_reference(request.output_root_reference):
        return PreprocessingWarning(
            code="output_reference_invalid",
            message="The output root reference must be a non-empty project-relative path.",
        )
    try:
        manifest_path.relative_to(output_root)
    except ValueError:
        return None
    return PreprocessingWarning(
        code="manifest_path_invalid",
        message="The preprocessing manifest must be stored outside the material output root.",
    )


def _is_safe_project_reference(value: str) -> bool:
    normalized = value.replace("\\", "/")
    if not normalized or normalized.startswith("/"):
        return False
    parts = normalized.split("/")
    return not any(
        part in {"", ".", ".."} or ":" in part or "\x00" in part for part in parts
    )


def _safe_file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _raise_if_cancelled(cancelled: CancelledCallback | None) -> None:
    if cancelled is not None and cancelled():
        raise PreprocessingCancelledError


def _build_manifest(
    *,
    request: PreprocessingRequest,
    source_hash: str,
    input_size_bytes: int,
    derived_materials: tuple[DerivedMaterialRecord, ...],
    entry_summaries: tuple[PreprocessingEntrySummary, ...],
    warnings: tuple[PreprocessingWarning, ...],
    failed_entries: tuple[str, ...],
    entry_count: int,
    expanded_size_bytes: int,
) -> dict[str, object]:
    return {
        "schema_version": PREPROCESSING_MANIFEST_SCHEMA_VERSION,
        "source_raw_path": PurePosixPath(
            request.source_raw_path.replace("\\", "/")
        ).as_posix(),
        "source_suffix": request.source_path.suffix.lower(),
        "source_hash": source_hash,
        "preprocessor": request.preprocessor_key,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "output_root": PurePosixPath(
            request.output_root_reference.replace("\\", "/")
        ).as_posix(),
        "derived_materials": [record.to_dict() for record in derived_materials],
        "entry_summaries": [summary.to_dict() for summary in entry_summaries],
        "entry_count": entry_count,
        "input_size_bytes": input_size_bytes,
        "source_mtime_ns": _safe_file_mtime_ns(request.source_path),
        "expanded_size_bytes": expanded_size_bytes,
        "warnings": [warning.to_dict() for warning in warnings],
        "failed_entries": list(failed_entries),
    }


def _safe_file_mtime_ns(path: Path) -> int:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return 0


def _manifest_string(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _manifest_int(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _manifest_optional_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _commit_preprocessing_outputs(
    *,
    staged_output: Path,
    output_root: Path,
    staged_manifest: Path,
    manifest_path: Path,
    stage_root: Path,
) -> None:
    output_root.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    output_backup = stage_root / "previous-output"
    manifest_backup = stage_root / "previous-manifest.json"
    output_replaced = False
    manifest_replaced = False

    try:
        if output_root.exists():
            os.replace(output_root, output_backup)
        os.replace(staged_output, output_root)
        output_replaced = True

        if manifest_path.exists():
            os.replace(manifest_path, manifest_backup)
        os.replace(staged_manifest, manifest_path)
        manifest_replaced = True
    except OSError:
        if manifest_replaced and manifest_path.exists():
            manifest_path.unlink()
        if manifest_backup.exists():
            os.replace(manifest_backup, manifest_path)
        if output_replaced and output_root.exists():
            shutil.rmtree(output_root, ignore_errors=True)
        if output_backup.exists():
            os.replace(output_backup, output_root)
        raise

    if output_backup.exists():
        shutil.rmtree(output_backup, ignore_errors=True)
    if manifest_backup.exists():
        manifest_backup.unlink(missing_ok=True)


def _failed_result(
    request: PreprocessingRequest,
    warning: PreprocessingWarning,
    *,
    source_hash: str = "",
    input_size_bytes: int = 0,
) -> PreprocessingResult:
    return PreprocessingResult(
        status="failed",
        source_hash=source_hash,
        output_root=request.output_root,
        manifest_path=request.manifest_path,
        warnings=(warning,),
        input_size_bytes=input_size_bytes,
    )


def _cancelled_result(
    request: PreprocessingRequest,
    *,
    source_hash: str = "",
    input_size_bytes: int = 0,
) -> PreprocessingResult:
    return PreprocessingResult(
        status="cancelled",
        source_hash=source_hash,
        output_root=request.output_root,
        manifest_path=request.manifest_path,
        warnings=(
            PreprocessingWarning(
                code="preprocessing_cancelled",
                message="Material preprocessing was cancelled.",
            ),
        ),
        input_size_bytes=input_size_bytes,
    )
