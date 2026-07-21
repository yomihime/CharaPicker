"""ZIP listing and extraction behind the material preprocessing boundary."""

from __future__ import annotations

import hashlib
import re
import stat
import zipfile
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath

from utils.material_preprocessing import (
    DerivedMaterialRecord,
    PreprocessingCancelledError,
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


_READ_CHUNK_SIZE = 1024 * 1024
_NATURAL_SORT_PATTERN = re.compile(r"\d+|\D+")
_MEDIA_OUTPUT_DIRECTORIES = {
    "video": "video",
    "image": "images",
    "audio": "audio",
    "text": "text",
}


@dataclass(frozen=True)
class SafeZipEntry:
    info: zipfile.ZipInfo
    source_path: str
    relative_path: PurePosixPath


@dataclass(frozen=True)
class _ValidatedZipEntry:
    info: zipfile.ZipInfo
    source_path: str
    relative_output_path: PurePosixPath
    media_type: str
    content_form_hint: str
    page_number: int | None = None


def extract_zip_materials(
    request: PreprocessingRequest,
    staged_output: Path,
) -> PreprocessingExtractionSummary:
    warnings: list[PreprocessingWarning] = []
    failed_entries: list[str] = []

    try:
        with zipfile.ZipFile(request.source_path) as archive:
            entries, entry_count, fatal = _validate_entries(
                archive.infolist(),
                request,
                warnings,
                failed_entries,
            )
            if fatal:
                return PreprocessingExtractionSummary(
                    warnings=tuple(warnings),
                    failed_entries=tuple(failed_entries),
                    entry_count=entry_count,
                    fatal=True,
                )
            derived, expanded_size = _extract_entries(
                archive,
                entries,
                request,
                staged_output,
                warnings,
                failed_entries,
            )
    except (zipfile.BadZipFile, zipfile.LargeZipFile, OSError) as exc:
        warnings.append(
            PreprocessingWarning(
                code="zip_container_invalid",
                message="The ZIP container is damaged or unreadable.",
                context={"error_type": type(exc).__name__},
            )
        )
        return PreprocessingExtractionSummary(
            warnings=tuple(warnings),
            failed_entries=tuple(failed_entries),
            fatal=True,
        )

    if not derived:
        warnings.append(
            PreprocessingWarning(
                code="no_supported_entries",
                message="The container did not contain supported material entries.",
            )
        )
    return PreprocessingExtractionSummary(
        derived_materials=tuple(derived),
        warnings=tuple(warnings),
        failed_entries=tuple(failed_entries),
        entry_count=entry_count,
        expanded_size_bytes=expanded_size,
    )


def validate_zip_container_entries(
    infos: list[zipfile.ZipInfo],
    request: PreprocessingRequest,
    warnings: list[PreprocessingWarning],
    failed_entries: list[str],
) -> tuple[list[SafeZipEntry], int, bool]:
    entry_count = len(infos)
    if entry_count > request.limits.max_entries:
        warnings.append(
            PreprocessingWarning(
                code="entry_count_limit_exceeded",
                message="The container has more entries than the safety limit allows.",
                context={
                    "entry_count": entry_count,
                    "limit": request.limits.max_entries,
                },
            )
        )
        return [], entry_count, True

    expanded_size = sum(info.file_size for info in infos if not info.is_dir())
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
        return [], entry_count, True

    safe_entries: list[SafeZipEntry] = []
    source_keys: set[str] = set()
    for info in infos:
        _raise_if_cancelled(request.cancelled)
        entry_name = info.filename
        candidate_name = entry_name.rstrip("/\\") if info.is_dir() else entry_name
        path_validation = validate_archive_entry_path(candidate_name)
        if path_validation.relative_path is None:
            _reject_entry(
                warnings,
                failed_entries,
                entry_name,
                path_validation.warning_code,
                path_validation.warning_message,
            )
            continue
        if info.is_dir():
            continue
        relative_entry = path_validation.relative_path
        if _is_unsupported_file_type(info):
            _reject_entry(
                warnings,
                failed_entries,
                entry_name,
                "entry_type_unsupported",
                "Archive links and special file entries are not supported.",
            )
            continue
        if info.flag_bits & 0x1:
            _reject_entry(
                warnings,
                failed_entries,
                entry_name,
                "entry_encrypted",
                "Encrypted archive entries are not supported.",
            )
            continue
        if info.file_size > request.limits.max_entry_size_bytes:
            _reject_entry(
                warnings,
                failed_entries,
                entry_name,
                "entry_size_limit_exceeded",
                "The archive entry exceeds the per-file safety limit.",
                size_bytes=info.file_size,
                limit=request.limits.max_entry_size_bytes,
            )
            continue
        compression_ratio = info.file_size / max(info.compress_size, 1)
        if compression_ratio > request.limits.max_compression_ratio:
            _reject_entry(
                warnings,
                failed_entries,
                entry_name,
                "compression_ratio_limit_exceeded",
                "The archive entry compression ratio exceeds the safety limit.",
                compression_ratio=round(compression_ratio, 2),
                limit=request.limits.max_compression_ratio,
            )
            continue
        source_key = normalized_path_key(relative_entry)
        if _collides_with_output(source_key, source_keys):
            _reject_entry(
                warnings,
                failed_entries,
                entry_name,
                "entry_path_collision",
                "The archive entry collides with another normalized entry path.",
            )
            continue
        source_keys.add(source_key)
        safe_entries.append(
            SafeZipEntry(
                info=info,
                source_path=entry_name,
                relative_path=relative_entry,
            )
        )
    return safe_entries, entry_count, False


def _validate_entries(
    infos: list[zipfile.ZipInfo],
    request: PreprocessingRequest,
    warnings: list[PreprocessingWarning],
    failed_entries: list[str],
) -> tuple[list[_ValidatedZipEntry], int, bool]:
    safe_entries, entry_count, fatal = validate_zip_container_entries(
        infos,
        request,
        warnings,
        failed_entries,
    )
    if fatal:
        return [], entry_count, True
    validated: list[_ValidatedZipEntry] = []
    output_keys: set[str] = set()
    for safe_entry in safe_entries:
        info = safe_entry.info
        entry_name = safe_entry.source_path
        relative_entry = safe_entry.relative_path
        suffix = relative_entry.suffix.lower()
        if suffix in INPUT_FORMAT_SUFFIXES:
            _reject_entry(
                warnings,
                failed_entries,
                entry_name,
                "nested_container_not_supported",
                "Nested input containers are not expanded.",
            )
            continue
        if request.preprocessor_key == "cbz" and suffix not in IMAGE_SUFFIXES:
            _reject_entry(
                warnings,
                failed_entries,
                entry_name,
                "cbz_entry_not_image",
                "CBZ containers only accept image page entries.",
            )
            continue
        if request.preprocessor_key != "cbz" and suffix in VIDEO_SUFFIXES:
            _reject_entry(
                warnings,
                failed_entries,
                entry_name,
                "container_video_requires_explicit_import",
                "Video files must be imported explicitly instead of through a container.",
            )
            continue
        if request.preprocessor_key != "cbz" and suffix not in CONTAINER_MATERIAL_SUFFIXES:
            _reject_entry(
                warnings,
                failed_entries,
                entry_name,
                "entry_suffix_unsupported",
                "The archive entry suffix is not in the material allowlist.",
            )
            continue

        profile = source_support_profile(suffix)
        if profile.media_type is None:
            _reject_entry(
                warnings,
                failed_entries,
                entry_name,
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
                entry_name,
                "entry_path_collision",
                "The archive entry collides with another normalized output path.",
            )
            continue
        output_keys.add(output_key)
        validated.append(
            _ValidatedZipEntry(
                info=info,
                source_path=entry_name,
                relative_output_path=output_path,
                media_type=profile.media_type,
                content_form_hint=(
                    "manga"
                    if request.preprocessor_key == "cbz"
                    else profile.content_form_hint
                ),
            )
        )
    if request.preprocessor_key == "cbz":
        validated = _finalize_cbz_page_order(validated)
    return validated, entry_count, False


def _extract_entries(
    archive: zipfile.ZipFile,
    entries: list[_ValidatedZipEntry],
    request: PreprocessingRequest,
    staged_output: Path,
    warnings: list[PreprocessingWarning],
    failed_entries: list[str],
) -> tuple[list[DerivedMaterialRecord], int]:
    derived: list[DerivedMaterialRecord] = []
    expanded_size = 0

    for entry in entries:
        _raise_if_cancelled(request.cancelled)
        target = ensure_path_within_root(staged_output, entry.relative_output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        written = 0
        try:
            with archive.open(entry.info, "r") as source, target.open("xb") as output:
                while chunk := source.read(_READ_CHUNK_SIZE):
                    _raise_if_cancelled(request.cancelled)
                    written += len(chunk)
                    if written > request.limits.max_entry_size_bytes:
                        raise ValueError("entry size exceeded its declared safety limit")
                    output.write(chunk)
                    digest.update(chunk)
        except PreprocessingCancelledError:
            raise
        except (
            EOFError,
            NotImplementedError,
            OSError,
            RuntimeError,
            ValueError,
            zipfile.BadZipFile,
        ) as exc:
            target.unlink(missing_ok=True)
            _reject_entry(
                warnings,
                failed_entries,
                entry.source_path,
                "entry_read_failed",
                "The archive entry could not be extracted safely.",
                error_type=type(exc).__name__,
            )
            continue

        expanded_size += written
        relative_material = PurePosixPath(
            request.output_root_reference,
            *entry.relative_output_path.parts,
        ).as_posix()
        derived.append(
            DerivedMaterialRecord(
                material_relative_path=relative_material,
                source_entry_path=entry.source_path,
                media_type=entry.media_type,
                content_form_hint=entry.content_form_hint,
                original_name=PurePosixPath(entry.source_path.replace("\\", "/")).name,
                size_bytes=written,
                fingerprint=f"sha256:{digest.hexdigest()}",
                page_number=entry.page_number,
            )
        )
    return derived, expanded_size


def _is_unsupported_file_type(info: zipfile.ZipInfo) -> bool:
    unix_mode = (info.external_attr >> 16) & 0xFFFF
    file_type = stat.S_IFMT(unix_mode)
    return file_type not in {0, stat.S_IFREG}


def _finalize_cbz_page_order(
    entries: list[_ValidatedZipEntry],
) -> list[_ValidatedZipEntry]:
    ordered = sorted(entries, key=lambda entry: _natural_sort_key(entry.source_path))
    return [
        replace(
            entry,
            relative_output_path=PurePosixPath(
                "images",
                "pages",
                f"page_{page_number:04d}{PurePosixPath(entry.source_path).suffix.lower()}",
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
