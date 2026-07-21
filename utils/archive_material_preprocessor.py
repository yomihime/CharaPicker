"""7z/RAR listing and extraction behind the material preprocessing boundary."""

from __future__ import annotations

import hashlib
import os
import re
import stat
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath

from utils.archive_backend import (
    ArchiveBackend,
    ArchiveBackendCancelledError,
    ArchiveBackendError,
    ArchiveBackendFormat,
    ArchiveContainerInvalidError,
    ArchiveEntry,
    ArchiveFormatUnsupportedError,
    ArchiveListing,
    ArchivePasswordRequiredError,
    default_archive_backend,
)
from utils.material_preprocessing import (
    DerivedMaterialRecord,
    PreprocessingCancelledError,
    PreprocessingEntrySummary,
    PreprocessingExtractionSummary,
    PreprocessingRequest,
    PreprocessingWarning,
    _raise_if_cancelled,
    ensure_path_within_root,
    normalized_path_key,
    validate_archive_entry_path,
)
from utils.media_types import (
    CONTAINER_MATERIAL_SUFFIXES,
    IMAGE_SUFFIXES,
    INPUT_FORMAT_SUFFIXES,
    VIDEO_SUFFIXES,
    source_support_profile,
)


_COPY_CHUNK_SIZE = 1024 * 1024
_NATURAL_SORT_PATTERN = re.compile(r"\d+|\D+")
_MEDIA_OUTPUT_DIRECTORIES = {
    "video": "video",
    "image": "images",
    "audio": "audio",
    "text": "text",
}
_SOURCE_FORMATS: dict[str, ArchiveBackendFormat] = {
    ".7z": "7z",
    ".rar": "rar",
    ".cbr": "rar",
}


@dataclass(frozen=True)
class _ValidatedArchiveEntry:
    listing_index: int
    entry: ArchiveEntry
    relative_source_path: PurePosixPath
    relative_output_path: PurePosixPath
    media_type: str
    content_form_hint: str
    page_number: int | None = None


class _PostExtractionValidationError(RuntimeError):
    def __init__(self, error_type: str) -> None:
        super().__init__(error_type)
        self.error_type = error_type


def extract_archive_materials(
    request: PreprocessingRequest,
    staged_output: Path,
    *,
    backend: ArchiveBackend | None = None,
) -> PreprocessingExtractionSummary:
    suffix = request.source_path.suffix.lower()
    archive_format = _SOURCE_FORMATS.get(suffix)
    if archive_format is None:
        return _fatal_summary(
            PreprocessingWarning(
                code="archive_format_unsupported",
                message="The archive input suffix is not supported by this preprocessor.",
                context={"format": suffix.lstrip(".")},
            )
        )

    selected_backend = backend or default_archive_backend()
    capability = selected_backend.probe(archive_format)
    if not capability.available:
        return _fatal_summary(
            PreprocessingWarning(
                code="archive_backend_unavailable",
                message="The configured archive backend is unavailable.",
                context={
                    "backend": capability.backend_name,
                    "version": capability.version,
                    "format": archive_format,
                    "reason": capability.reason or "unavailable",
                },
            )
        )

    try:
        listing = selected_backend.list_archive(
            request.source_path,
            archive_format=archive_format,
            cancelled=request.cancelled,
        )
    except ArchiveBackendCancelledError as exc:
        raise PreprocessingCancelledError from exc
    except ArchiveBackendError as exc:
        return _backend_failure_summary(exc, operation="list")

    validated, statuses, warnings, failed_entries, fatal = _validate_listing(
        listing,
        request,
        comic_only=suffix == ".cbr",
    )
    summaries = _build_entry_summaries(listing.entries, validated, statuses)
    expanded_size = sum(entry.size_bytes for entry in listing.entries if not entry.is_directory)
    if fatal:
        return PreprocessingExtractionSummary(
            entry_summaries=summaries,
            warnings=tuple(warnings),
            failed_entries=tuple(failed_entries),
            entry_count=len(listing.entries),
            expanded_size_bytes=expanded_size,
            fatal=True,
        )

    try:
        selected_backend.test_archive(
            request.source_path,
            archive_format=archive_format,
            cancelled=request.cancelled,
        )
    except ArchiveBackendCancelledError as exc:
        raise PreprocessingCancelledError from exc
    except ArchiveBackendError as exc:
        failure = _backend_failure_summary(
            exc,
            operation="test",
            entry_summaries=summaries,
            entry_count=len(listing.entries),
            expanded_size_bytes=expanded_size,
        )
        return failure

    if not validated:
        warnings.append(
            PreprocessingWarning(
                code="no_supported_entries",
                message="The container did not contain supported material entries.",
            )
        )
        return PreprocessingExtractionSummary(
            entry_summaries=summaries,
            warnings=tuple(warnings),
            failed_entries=tuple(failed_entries),
            entry_count=len(listing.entries),
            expanded_size_bytes=expanded_size,
        )

    extracted_root = staged_output.parent / "archive_backend_output"
    try:
        selected_backend.extract_archive(
            request.source_path,
            extracted_root,
            archive_format=archive_format,
            cancelled=request.cancelled,
        )
        actual_files = _validate_extracted_tree(extracted_root, listing, request)
        derived = _materialize_validated_entries(
            validated,
            actual_files,
            request,
            staged_output,
        )
    except ArchiveBackendCancelledError as exc:
        raise PreprocessingCancelledError from exc
    except ArchiveBackendError as exc:
        return _backend_failure_summary(
            exc,
            operation="extract",
            entry_summaries=summaries,
            entry_count=len(listing.entries),
            expanded_size_bytes=expanded_size,
        )
    except _PostExtractionValidationError as exc:
        return PreprocessingExtractionSummary(
            entry_summaries=summaries,
            warnings=(
                PreprocessingWarning(
                    code="archive_extracted_tree_invalid",
                    message="The extracted archive tree did not match its validated listing.",
                    context={"error_type": exc.error_type},
                ),
            ),
            entry_count=len(listing.entries),
            expanded_size_bytes=expanded_size,
            fatal=True,
        )

    return PreprocessingExtractionSummary(
        derived_materials=tuple(derived),
        entry_summaries=summaries,
        warnings=tuple(warnings),
        failed_entries=tuple(failed_entries),
        entry_count=len(listing.entries),
        expanded_size_bytes=expanded_size,
    )


def _validate_listing(
    listing: ArchiveListing,
    request: PreprocessingRequest,
    *,
    comic_only: bool,
) -> tuple[
    list[_ValidatedArchiveEntry],
    dict[int, str],
    list[PreprocessingWarning],
    list[str],
    bool,
]:
    warnings: list[PreprocessingWarning] = []
    failed_entries: list[str] = []
    statuses: dict[int, str] = {}
    entries = listing.entries
    if len(entries) > request.limits.max_entries:
        warnings.append(
            PreprocessingWarning(
                code="entry_count_limit_exceeded",
                message="The container has more entries than the safety limit allows.",
                context={"entry_count": len(entries), "limit": request.limits.max_entries},
            )
        )
        return [], statuses, warnings, failed_entries, True

    expanded_size = sum(entry.size_bytes for entry in entries if not entry.is_directory)
    if expanded_size > request.limits.max_expanded_size_bytes:
        warnings.append(
            PreprocessingWarning(
                code="expanded_size_limit_exceeded",
                message="The container expanded size exceeds the safety limit.",
                context={
                    "expanded_size_bytes": expanded_size,
                    "limit": request.limits.max_expanded_size_bytes,
                },
            )
        )
        return [], statuses, warnings, failed_entries, True
    aggregate_ratio = expanded_size / max(listing.packed_size_bytes, 1)
    if aggregate_ratio > request.limits.max_compression_ratio:
        warnings.append(
            PreprocessingWarning(
                code="compression_ratio_limit_exceeded",
                message="The archive compression ratio exceeds the safety limit.",
                context={
                    "compression_ratio": round(aggregate_ratio, 2),
                    "limit": request.limits.max_compression_ratio,
                },
            )
        )
        return [], statuses, warnings, failed_entries, True

    safe_source_keys: set[str] = set()
    safe_paths: dict[int, PurePosixPath] = {}
    structural_failure = False
    for index, entry in enumerate(entries):
        _raise_if_cancelled(request.cancelled)
        candidate_name = entry.source_path.rstrip("/\\") if entry.is_directory else entry.source_path
        path_validation = validate_archive_entry_path(candidate_name)
        if path_validation.relative_path is None:
            _reject_entry(
                warnings,
                failed_entries,
                statuses,
                index,
                entry.source_path,
                path_validation.warning_code,
                path_validation.warning_message,
            )
            structural_failure = True
            continue
        relative_path = path_validation.relative_path
        if entry.is_special:
            _reject_entry(
                warnings,
                failed_entries,
                statuses,
                index,
                entry.source_path,
                "entry_type_unsupported",
                "Archive links and special file entries are not supported.",
            )
            structural_failure = True
            continue
        if entry.is_directory:
            statuses[index] = "directory"
            continue
        source_key = normalized_path_key(relative_path)
        if _collides_with_output(source_key, safe_source_keys):
            _reject_entry(
                warnings,
                failed_entries,
                statuses,
                index,
                entry.source_path,
                "entry_path_collision",
                "The archive entry collides with another normalized entry path.",
            )
            structural_failure = True
            continue
        safe_source_keys.add(source_key)
        safe_paths[index] = relative_path
        if entry.encrypted:
            _reject_entry(
                warnings,
                failed_entries,
                statuses,
                index,
                entry.source_path,
                "archive_password_protected",
                "Password-protected archives are not supported.",
            )
            structural_failure = True
            continue
        if entry.size_bytes > request.limits.max_entry_size_bytes:
            _reject_entry(
                warnings,
                failed_entries,
                statuses,
                index,
                entry.source_path,
                "entry_size_limit_exceeded",
                "The archive entry exceeds the per-file safety limit.",
                size_bytes=entry.size_bytes,
                limit=request.limits.max_entry_size_bytes,
            )
            structural_failure = True
            continue
        if entry.packed_size_bytes is not None and entry.size_bytes:
            entry_ratio = entry.size_bytes / max(entry.packed_size_bytes, 1)
            if entry_ratio > request.limits.max_compression_ratio:
                _reject_entry(
                    warnings,
                    failed_entries,
                    statuses,
                    index,
                    entry.source_path,
                    "compression_ratio_limit_exceeded",
                    "The archive entry compression ratio exceeds the safety limit.",
                    compression_ratio=round(entry_ratio, 2),
                    limit=request.limits.max_compression_ratio,
                )
                structural_failure = True

    if structural_failure:
        return [], statuses, warnings, failed_entries, True

    validated: list[_ValidatedArchiveEntry] = []
    output_keys: set[str] = set()
    for index, entry in enumerate(entries):
        if entry.is_directory:
            continue
        relative_entry = safe_paths[index]
        suffix = relative_entry.suffix.lower()
        if suffix in INPUT_FORMAT_SUFFIXES:
            _reject_entry(
                warnings,
                failed_entries,
                statuses,
                index,
                entry.source_path,
                "nested_container_not_supported",
                "Nested input containers are not expanded.",
            )
            continue
        if comic_only and suffix not in IMAGE_SUFFIXES:
            _reject_entry(
                warnings,
                failed_entries,
                statuses,
                index,
                entry.source_path,
                "cbr_entry_not_image",
                "CBR containers only accept image page entries.",
            )
            continue
        if not comic_only and suffix in VIDEO_SUFFIXES:
            _reject_entry(
                warnings,
                failed_entries,
                statuses,
                index,
                entry.source_path,
                "container_video_requires_explicit_import",
                "Video files must be imported explicitly instead of through a container.",
            )
            continue
        if not comic_only and suffix not in CONTAINER_MATERIAL_SUFFIXES:
            _reject_entry(
                warnings,
                failed_entries,
                statuses,
                index,
                entry.source_path,
                "entry_suffix_unsupported",
                "The archive entry suffix is not in the material allowlist.",
            )
            continue
        profile = source_support_profile(suffix)
        if profile.media_type is None:
            _reject_entry(
                warnings,
                failed_entries,
                statuses,
                index,
                entry.source_path,
                "entry_media_type_unknown",
                "The archive entry could not be mapped to a supported media type.",
            )
            continue
        output_path = PurePosixPath(
            _MEDIA_OUTPUT_DIRECTORIES[profile.media_type],
            *relative_entry.parts,
        )
        output_key = normalized_path_key(output_path)
        if _collides_with_output(output_key, output_keys):
            _reject_entry(
                warnings,
                failed_entries,
                statuses,
                index,
                entry.source_path,
                "entry_path_collision",
                "The archive entry collides with another normalized output path.",
            )
            continue
        output_keys.add(output_key)
        statuses[index] = "materialized"
        validated.append(
            _ValidatedArchiveEntry(
                listing_index=index,
                entry=entry,
                relative_source_path=relative_entry,
                relative_output_path=output_path,
                media_type=profile.media_type,
                content_form_hint="manga" if comic_only else profile.content_form_hint,
            )
        )
    if comic_only:
        validated = _finalize_comic_page_order(validated)
    return validated, statuses, warnings, failed_entries, False


def _validate_extracted_tree(
    extracted_root: Path,
    listing: ArchiveListing,
    request: PreprocessingRequest,
) -> dict[str, Path]:
    root = extracted_root.resolve()
    listed_files: dict[str, ArchiveEntry] = {}
    for entry in listing.entries:
        if entry.is_directory:
            continue
        validation = validate_archive_entry_path(entry.source_path)
        if validation.relative_path is None:
            raise _PostExtractionValidationError("UnsafeListedPath")
        listed_files[normalized_path_key(validation.relative_path)] = entry

    actual_files: dict[str, Path] = {}
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            children = list(os.scandir(current))
        except OSError as exc:
            raise _PostExtractionValidationError(type(exc).__name__) from exc
        for child in children:
            _raise_if_cancelled(request.cancelled)
            try:
                child_stat = child.stat(follow_symlinks=False)
            except OSError as exc:
                raise _PostExtractionValidationError(type(exc).__name__) from exc
            if child.is_symlink() or _stat_is_reparse_point(child_stat):
                raise _PostExtractionValidationError("ExtractedLinkOrReparsePoint")
            path = Path(child.path)
            try:
                relative = path.relative_to(root)
            except ValueError as exc:
                raise _PostExtractionValidationError("ExtractedPathEscaped") from exc
            validation = validate_archive_entry_path(PurePosixPath(*relative.parts).as_posix())
            if validation.relative_path is None:
                raise _PostExtractionValidationError("ExtractedPathUnsafe")
            if stat.S_ISDIR(child_stat.st_mode):
                stack.append(path)
                continue
            if not stat.S_ISREG(child_stat.st_mode):
                raise _PostExtractionValidationError("ExtractedFileTypeUnsupported")
            key = normalized_path_key(validation.relative_path)
            if key in actual_files:
                raise _PostExtractionValidationError("ExtractedPathCollision")
            listed = listed_files.get(key)
            if listed is None:
                raise _PostExtractionValidationError("ExtractedFileNotListed")
            if child_stat.st_size != listed.size_bytes:
                raise _PostExtractionValidationError("ExtractedSizeMismatch")
            if child_stat.st_size > request.limits.max_entry_size_bytes:
                raise _PostExtractionValidationError("ExtractedEntryLimitExceeded")
            actual_files[key] = path
    if actual_files.keys() != listed_files.keys():
        raise _PostExtractionValidationError("ListedFileMissingAfterExtraction")
    actual_total = sum(path.stat().st_size for path in actual_files.values())
    if actual_total > request.limits.max_expanded_size_bytes:
        raise _PostExtractionValidationError("ExtractedTotalLimitExceeded")
    return actual_files


def _materialize_validated_entries(
    entries: list[_ValidatedArchiveEntry],
    actual_files: dict[str, Path],
    request: PreprocessingRequest,
    staged_output: Path,
) -> list[DerivedMaterialRecord]:
    derived: list[DerivedMaterialRecord] = []
    for entry in entries:
        _raise_if_cancelled(request.cancelled)
        source_key = normalized_path_key(entry.relative_source_path)
        source = actual_files.get(source_key)
        if source is None:
            raise _PostExtractionValidationError("ValidatedMaterialMissing")
        target = ensure_path_within_root(staged_output, entry.relative_output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        written = 0
        try:
            with source.open("rb") as input_file, target.open("xb") as output_file:
                while chunk := input_file.read(_COPY_CHUNK_SIZE):
                    _raise_if_cancelled(request.cancelled)
                    written += len(chunk)
                    if written > request.limits.max_entry_size_bytes:
                        raise _PostExtractionValidationError("MaterializedEntryLimitExceeded")
                    output_file.write(chunk)
                    digest.update(chunk)
        except PreprocessingCancelledError:
            raise
        except _PostExtractionValidationError:
            target.unlink(missing_ok=True)
            raise
        except OSError as exc:
            target.unlink(missing_ok=True)
            raise _PostExtractionValidationError(type(exc).__name__) from exc
        if written != entry.entry.size_bytes:
            target.unlink(missing_ok=True)
            raise _PostExtractionValidationError("MaterializedSizeMismatch")
        relative_material = PurePosixPath(
            request.output_root_reference,
            *entry.relative_output_path.parts,
        ).as_posix()
        derived.append(
            DerivedMaterialRecord(
                material_relative_path=relative_material,
                source_entry_path=entry.entry.source_path,
                media_type=entry.media_type,
                content_form_hint=entry.content_form_hint,
                original_name=PurePosixPath(
                    entry.entry.source_path.replace("\\", "/")
                ).name,
                size_bytes=written,
                fingerprint=f"sha256:{digest.hexdigest()}",
                page_number=entry.page_number,
            )
        )
    return derived


def _build_entry_summaries(
    entries: tuple[ArchiveEntry, ...],
    validated: list[_ValidatedArchiveEntry],
    statuses: dict[int, str],
) -> tuple[PreprocessingEntrySummary, ...]:
    validated_by_index = {item.listing_index: item for item in validated}
    summaries: list[PreprocessingEntrySummary] = []
    for index, entry in enumerate(entries):
        item = validated_by_index.get(index)
        suffix = PurePosixPath(entry.source_path.replace("\\", "/")).suffix.lower()
        summaries.append(
            PreprocessingEntrySummary(
                source_entry_path=entry.source_path,
                role="directory" if entry.is_directory else "entry",
                media_type=item.media_type if item is not None else "",
                media_subtype=suffix.lstrip("."),
                page_number=item.page_number if item is not None else None,
                size_bytes=entry.size_bytes,
                status=statuses.get(index, "observed"),
            )
        )
    return tuple(summaries)


def _backend_failure_summary(
    error: ArchiveBackendError,
    *,
    operation: str,
    entry_summaries: tuple[PreprocessingEntrySummary, ...] = (),
    entry_count: int = 0,
    expanded_size_bytes: int = 0,
) -> PreprocessingExtractionSummary:
    if isinstance(error, ArchivePasswordRequiredError):
        code = "archive_password_protected"
        message = "Password-protected archives are not supported."
    elif isinstance(error, ArchiveFormatUnsupportedError):
        code = "archive_format_unsupported"
        message = "The archive backend does not support this archive format."
    elif isinstance(error, ArchiveContainerInvalidError):
        code = "archive_container_invalid"
        message = "The archive is damaged or unreadable."
    else:
        code = "archive_backend_failed"
        message = "The archive backend could not complete preprocessing."
    return PreprocessingExtractionSummary(
        entry_summaries=entry_summaries,
        warnings=(
            PreprocessingWarning(
                code=code,
                message=message,
                context={"operation": operation, "error_type": error.error_type},
            ),
        ),
        entry_count=entry_count,
        expanded_size_bytes=expanded_size_bytes,
        fatal=True,
    )


def _fatal_summary(warning: PreprocessingWarning) -> PreprocessingExtractionSummary:
    return PreprocessingExtractionSummary(warnings=(warning,), fatal=True)


def _finalize_comic_page_order(
    entries: list[_ValidatedArchiveEntry],
) -> list[_ValidatedArchiveEntry]:
    ordered = sorted(entries, key=lambda entry: _natural_sort_key(entry.entry.source_path))
    return [
        replace(
            entry,
            relative_output_path=PurePosixPath(
                "images",
                "pages",
                f"page_{page_number:04d}{entry.relative_source_path.suffix.lower()}",
            ),
            page_number=page_number,
        )
        for page_number, entry in enumerate(ordered, start=1)
    ]


def _natural_sort_key(value: str) -> tuple[tuple[int, int | str], ...]:
    normalized = value.replace("\\", "/").casefold()
    return tuple(
        (0, int(part)) if part.isdigit() else (1, part)
        for part in _NATURAL_SORT_PATTERN.findall(normalized)
    )


def _stat_is_reparse_point(value: os.stat_result) -> bool:
    attributes = getattr(value, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attributes & reparse_flag)


def _collides_with_output(candidate: str, existing: set[str]) -> bool:
    if candidate in existing:
        return True
    candidate_parts = candidate.split("/")
    for index in range(1, len(candidate_parts)):
        if "/".join(candidate_parts[:index]) in existing:
            return True
    prefix = f"{candidate}/"
    return any(path.startswith(prefix) for path in existing)


def _reject_entry(
    warnings: list[PreprocessingWarning],
    failed_entries: list[str],
    statuses: dict[int, str],
    index: int,
    entry_name: str,
    code: str,
    message: str,
    **context: str | int | float | bool,
) -> None:
    warnings.append(
        PreprocessingWarning(
            code=code,
            message=message,
            entry_path=entry_name,
            context=context,
        )
    )
    failed_entries.append(entry_name)
    statuses[index] = "rejected"
