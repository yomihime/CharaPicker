"""Safe preprocessing primitives for container-style project inputs."""

from __future__ import annotations

import hashlib
import json
import os
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
_COPY_CHUNK_SIZE = 1024 * 1024
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
class PreprocessingRequest:
    source_path: Path
    source_raw_path: str
    output_root: Path
    output_root_reference: str
    manifest_path: Path
    preprocessor_key: InputPreprocessorKey
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
    warnings: tuple[PreprocessingWarning, ...] = ()
    failed_entries: tuple[str, ...] = ()
    entry_count: int = 0
    input_size_bytes: int = 0
    expanded_size_bytes: int = 0

    @property
    def succeeded(self) -> bool:
        return self.status == "completed"


@dataclass(frozen=True)
class ArchivePathValidation:
    relative_path: PurePosixPath | None
    warning_code: str = ""
    warning_message: str = ""


class _PreprocessingCancelled(RuntimeError):
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
        source_hash = _hash_file(source, request.cancelled)
        _raise_if_cancelled(request.cancelled)
    except _PreprocessingCancelled:
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
        if request.preprocessor_key == "zip":
            from utils.zip_material_preprocessor import extract_zip_materials

            extraction = extract_zip_materials(request, staged_output)
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
            warnings=extraction.warnings,
            failed_entries=extraction.failed_entries,
            entry_count=extraction.entry_count,
            input_size_bytes=input_size,
            expanded_size_bytes=extraction.expanded_size_bytes,
        )
    except _PreprocessingCancelled:
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


def _hash_file(path: Path, cancelled: CancelledCallback | None) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(_COPY_CHUNK_SIZE):
            _raise_if_cancelled(cancelled)
            digest.update(chunk)
    return digest.hexdigest()


def _safe_file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _raise_if_cancelled(cancelled: CancelledCallback | None) -> None:
    if cancelled is not None and cancelled():
        raise _PreprocessingCancelled


def _build_manifest(
    *,
    request: PreprocessingRequest,
    source_hash: str,
    input_size_bytes: int,
    derived_materials: tuple[DerivedMaterialRecord, ...],
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
        "entry_count": entry_count,
        "input_size_bytes": input_size_bytes,
        "expanded_size_bytes": expanded_size_bytes,
        "warnings": [warning.to_dict() for warning in warnings],
        "failed_entries": list(failed_entries),
    }


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
