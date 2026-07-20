"""Narrow archive backend contract and the production 7-Zip CLI adapter."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal, Protocol

from utils.paths import APP_ROOT


ArchiveBackendFormat = Literal["7z", "rar"]
CancelledCallback = Callable[[], bool]
_SUPPORTED_EXECUTABLE_NAMES = frozenset({"7z", "7z.exe", "7zz", "7zz.exe"})
_VERSION_PATTERN = re.compile(r"^7-Zip\s+(\d+(?:\.\d+)*)", re.MULTILINE)
_FORMAT_PATTERN = re.compile(
    r"^\s*\d+.*?\s(7z|Rar|Rar5)\s+(?:7z|rar)\b",
    re.MULTILINE,
)
_ENTRY_SEPARATOR = "----------"
_COMMAND_POLL_SECONDS = 0.1
_PROBE_TIMEOUT_SECONDS = 15.0
_LIST_TIMEOUT_SECONDS = 60.0
_TEST_TIMEOUT_SECONDS = 300.0
_EXTRACT_TIMEOUT_SECONDS = 300.0


@dataclass(frozen=True)
class ArchiveBackendCapability:
    available: bool
    backend_name: str
    version: str = ""
    supported_formats: frozenset[ArchiveBackendFormat] = frozenset()
    reason: str = ""
    executable_path: Path | None = None


@dataclass(frozen=True)
class ArchiveEntry:
    source_path: str
    size_bytes: int
    packed_size_bytes: int | None
    is_directory: bool
    encrypted: bool
    is_special: bool = False


@dataclass(frozen=True)
class ArchiveListing:
    archive_format: ArchiveBackendFormat
    entries: tuple[ArchiveEntry, ...]
    packed_size_bytes: int


class ArchiveBackend(Protocol):
    def probe(
        self,
        required_format: ArchiveBackendFormat | None = None,
    ) -> ArchiveBackendCapability: ...

    def list_archive(
        self,
        source_path: Path,
        *,
        archive_format: ArchiveBackendFormat,
        cancelled: CancelledCallback | None = None,
    ) -> ArchiveListing: ...

    def test_archive(
        self,
        source_path: Path,
        *,
        archive_format: ArchiveBackendFormat,
        cancelled: CancelledCallback | None = None,
    ) -> None: ...

    def extract_archive(
        self,
        source_path: Path,
        destination: Path,
        *,
        archive_format: ArchiveBackendFormat,
        cancelled: CancelledCallback | None = None,
    ) -> None: ...


class ArchiveBackendError(RuntimeError):
    """Sanitized backend failure that does not retain command output or paths."""

    def __init__(self, error_type: str) -> None:
        super().__init__(error_type)
        self.error_type = error_type


class ArchiveBackendCancelledError(ArchiveBackendError):
    pass


class ArchiveBackendUnavailableError(ArchiveBackendError):
    pass


class ArchivePasswordRequiredError(ArchiveBackendError):
    pass


class ArchiveContainerInvalidError(ArchiveBackendError):
    pass


class ArchiveFormatUnsupportedError(ArchiveBackendError):
    pass


class SevenZipArchiveBackend:
    backend_name = "7zip"

    def __init__(self, executable_path: Path | None = None) -> None:
        self._configured_executable = executable_path
        self._capability: ArchiveBackendCapability | None = None

    def probe(
        self,
        required_format: ArchiveBackendFormat | None = None,
    ) -> ArchiveBackendCapability:
        if self._capability is None:
            self._capability = self._probe_once()
        capability = self._capability
        if (
            capability.available
            and required_format is not None
            and required_format not in capability.supported_formats
        ):
            return ArchiveBackendCapability(
                available=False,
                backend_name=capability.backend_name,
                version=capability.version,
                supported_formats=capability.supported_formats,
                reason=f"{required_format}_format_unsupported",
                executable_path=capability.executable_path,
            )
        return capability

    def list_archive(
        self,
        source_path: Path,
        *,
        archive_format: ArchiveBackendFormat,
        cancelled: CancelledCallback | None = None,
    ) -> ArchiveListing:
        completed = self._run_archive_command(
            [
                "l",
                "-slt",
                "-sccUTF-8",
                "-bd",
                "-p-",
                f"-t{archive_format}",
                str(source_path.resolve()),
            ],
            required_format=archive_format,
            timeout_seconds=_LIST_TIMEOUT_SECONDS,
            cancelled=cancelled,
        )
        if completed.returncode != 0:
            self._raise_command_failure(completed.output)
        return _parse_listing(completed.output, archive_format)

    def test_archive(
        self,
        source_path: Path,
        *,
        archive_format: ArchiveBackendFormat,
        cancelled: CancelledCallback | None = None,
    ) -> None:
        completed = self._run_archive_command(
            [
                "t",
                "-sccUTF-8",
                "-bd",
                "-bb0",
                "-p-",
                f"-t{archive_format}",
                str(source_path.resolve()),
            ],
            required_format=archive_format,
            timeout_seconds=_TEST_TIMEOUT_SECONDS,
            cancelled=cancelled,
        )
        if completed.returncode != 0:
            self._raise_command_failure(completed.output)

    def extract_archive(
        self,
        source_path: Path,
        destination: Path,
        *,
        archive_format: ArchiveBackendFormat,
        cancelled: CancelledCallback | None = None,
    ) -> None:
        destination = destination.resolve()
        destination.mkdir(parents=True, exist_ok=False)
        completed = self._run_archive_command(
            [
                "x",
                "-y",
                "-aoa",
                "-spe",
                "-sccUTF-8",
                "-bd",
                "-bb0",
                "-p-",
                f"-t{archive_format}",
                f"-o{destination}",
                str(source_path.resolve()),
            ],
            required_format=archive_format,
            timeout_seconds=_EXTRACT_TIMEOUT_SECONDS,
            cancelled=cancelled,
        )
        if completed.returncode != 0:
            self._raise_command_failure(completed.output)

    def _probe_once(self) -> ArchiveBackendCapability:
        executable = self._discover_executable()
        if executable is None:
            return ArchiveBackendCapability(
                available=False,
                backend_name=self.backend_name,
                reason="executable_not_found",
            )
        try:
            completed = _run_process(
                [str(executable), "i", "-sccUTF-8"],
                timeout_seconds=_PROBE_TIMEOUT_SECONDS,
                cancelled=None,
            )
        except ArchiveBackendError as exc:
            return ArchiveBackendCapability(
                available=False,
                backend_name=self.backend_name,
                reason=exc.error_type,
            )
        version_match = _VERSION_PATTERN.search(completed.output)
        if completed.returncode != 0 or version_match is None:
            return ArchiveBackendCapability(
                available=False,
                backend_name=self.backend_name,
                reason="identity_check_failed",
            )
        format_names = set(_FORMAT_PATTERN.findall(completed.output))
        supported_formats: set[ArchiveBackendFormat] = set()
        if "7z" in format_names:
            supported_formats.add("7z")
        if {"Rar", "Rar5"} & format_names:
            supported_formats.add("rar")
        if not supported_formats:
            return ArchiveBackendCapability(
                available=False,
                backend_name=self.backend_name,
                version=version_match.group(1),
                reason="no_supported_archive_formats",
            )
        return ArchiveBackendCapability(
            available=True,
            backend_name=self.backend_name,
            version=version_match.group(1),
            supported_formats=frozenset(supported_formats),
            executable_path=executable,
        )

    def _discover_executable(self) -> Path | None:
        configured = self._configured_executable
        if configured is None:
            configured_value = os.environ.get("CHARAPICKER_7ZIP_PATH", "").strip()
            configured = Path(configured_value) if configured_value else None
        candidates: list[Path] = []
        if configured is not None:
            candidates.append(configured)
        candidates.extend(
            [
                APP_ROOT / "bin" / "7zip" / "7z.exe",
                APP_ROOT / "bin" / "7z.exe",
            ]
        )
        for command_name in ("7z", "7zz"):
            discovered = shutil.which(command_name)
            if discovered:
                candidates.append(Path(discovered))
        for environment_name in ("ProgramFiles", "ProgramFiles(x86)"):
            program_files = os.environ.get(environment_name, "").strip()
            if program_files:
                candidates.append(Path(program_files) / "7-Zip" / "7z.exe")

        seen: set[str] = set()
        for candidate in candidates:
            try:
                resolved = candidate.expanduser().resolve()
            except OSError:
                continue
            key = os.path.normcase(str(resolved))
            if key in seen:
                continue
            seen.add(key)
            if resolved.name.casefold() not in _SUPPORTED_EXECUTABLE_NAMES:
                continue
            if resolved.is_file():
                return resolved
        return None

    def _run_archive_command(
        self,
        arguments: list[str],
        *,
        required_format: ArchiveBackendFormat,
        timeout_seconds: float,
        cancelled: CancelledCallback | None,
    ) -> _CompletedProcess:
        capability = self.probe(required_format)
        if not capability.available or capability.executable_path is None:
            if capability.reason.endswith("_format_unsupported"):
                raise ArchiveFormatUnsupportedError(capability.reason)
            raise ArchiveBackendUnavailableError(
                capability.reason or "ArchiveBackendUnavailable"
            )
        return _run_process(
            [str(capability.executable_path), *arguments],
            timeout_seconds=timeout_seconds,
            cancelled=cancelled,
        )

    @staticmethod
    def _raise_command_failure(output: str) -> None:
        normalized = output.casefold()
        password_markers = (
            "wrong password",
            "password is incorrect",
            "can not open encrypted archive",
            "cannot open encrypted archive",
            "encrypted archive",
        )
        if any(marker in normalized for marker in password_markers):
            raise ArchivePasswordRequiredError("ArchivePasswordRequired")
        raise ArchiveContainerInvalidError("ArchiveContainerInvalid")


@dataclass(frozen=True)
class _CompletedProcess:
    returncode: int
    output: str


def default_archive_backend() -> ArchiveBackend:
    return SevenZipArchiveBackend()


def probe_archive_backend(
    required_format: ArchiveBackendFormat | None = None,
    backend: ArchiveBackend | None = None,
) -> ArchiveBackendCapability:
    return (backend or default_archive_backend()).probe(required_format)


def _run_process(
    command: list[str],
    *,
    timeout_seconds: float,
    cancelled: CancelledCallback | None,
) -> _CompletedProcess:
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
        )
    except (OSError, ValueError) as exc:
        raise ArchiveBackendUnavailableError(type(exc).__name__) from exc

    try:
        remaining = timeout_seconds
        output = b""
        while True:
            if cancelled is not None and cancelled():
                process.kill()
                process.communicate()
                raise ArchiveBackendCancelledError("ArchiveBackendCancelled")
            poll_seconds = min(_COMMAND_POLL_SECONDS, remaining)
            if poll_seconds <= 0:
                process.kill()
                process.communicate()
                raise ArchiveBackendError("ArchiveBackendTimeout")
            try:
                output, _stderr = process.communicate(timeout=poll_seconds)
                break
            except subprocess.TimeoutExpired:
                remaining -= poll_seconds
    except BaseException:
        if process.poll() is None:
            process.kill()
            process.communicate()
        raise
    return _CompletedProcess(
        returncode=process.returncode,
        output=_decode_process_output(output),
    )


def _decode_process_output(value: bytes) -> str:
    for encoding in ("utf-8", "gb18030", "shift_jis"):
        try:
            return value.decode(encoding)
        except UnicodeDecodeError:
            continue
    return value.decode("utf-8", errors="replace")


def _parse_listing(output: str, expected_format: ArchiveBackendFormat) -> ArchiveListing:
    normalized = output.replace("\r\n", "\n").replace("\r", "\n")
    if _ENTRY_SEPARATOR not in normalized:
        raise ArchiveContainerInvalidError("ArchiveListingMissing")
    metadata_text, entry_text = normalized.split(_ENTRY_SEPARATOR, maxsplit=1)
    metadata = _parse_key_values(metadata_text, strict=False)
    reported_type = metadata.get("Type", "").casefold()
    if expected_format == "7z" and reported_type != "7z":
        raise ArchiveFormatUnsupportedError("ArchiveFormatMismatch")
    if expected_format == "rar" and reported_type not in {"rar", "rar5"}:
        raise ArchiveFormatUnsupportedError("ArchiveFormatMismatch")

    entries: list[ArchiveEntry] = []
    for record_text in re.split(r"\n\s*\n", entry_text.strip()):
        if not record_text.strip():
            continue
        record = _parse_key_values(record_text, strict=True)
        source_path = record.get("Path", "")
        if not source_path:
            raise ArchiveContainerInvalidError("ArchiveListingPathMissing")
        is_directory = record.get("Folder") == "+" or record.get("Attributes", "").startswith(
            "D"
        )
        entries.append(
            ArchiveEntry(
                source_path=source_path,
                size_bytes=_parse_nonnegative_int(record.get("Size"), "ArchiveEntrySize"),
                packed_size_bytes=_parse_optional_nonnegative_int(
                    record.get("Packed Size"),
                    "ArchiveEntryPackedSize",
                ),
                is_directory=is_directory,
                encrypted=record.get("Encrypted") == "+",
                is_special=_record_is_special(record),
            )
        )
    return ArchiveListing(
        archive_format=expected_format,
        entries=tuple(entries),
        packed_size_bytes=_parse_nonnegative_int(
            metadata.get("Physical Size"),
            "ArchivePhysicalSize",
        ),
    )


def _parse_key_values(value: str, *, strict: bool) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for line in value.splitlines():
        stripped = line.strip()
        if not stripped or stripped in {"--"}:
            continue
        if " = " in line:
            key, item = line.split(" = ", maxsplit=1)
        elif line.endswith(" ="):
            key, item = line[:-2], ""
        else:
            if strict:
                raise ArchiveContainerInvalidError("ArchiveListingMalformed")
            continue
        normalized_key = key.strip()
        if strict and normalized_key in parsed:
            raise ArchiveContainerInvalidError("ArchiveListingDuplicateField")
        parsed[normalized_key] = item
    return parsed


def _parse_nonnegative_int(value: str | None, error_type: str) -> int:
    if value is None:
        raise ArchiveContainerInvalidError(error_type)
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ArchiveContainerInvalidError(error_type) from exc
    if parsed < 0:
        raise ArchiveContainerInvalidError(error_type)
    return parsed


def _parse_optional_nonnegative_int(value: str | None, error_type: str) -> int | None:
    if value in {None, ""}:
        return None
    return _parse_nonnegative_int(value, error_type)


def _record_is_special(record: dict[str, str]) -> bool:
    if any(
        record.get(key, "")
        for key in ("Symbolic Link", "Hard Link", "Alternate Stream")
    ):
        return True
    attributes = record.get("Attributes", "").casefold()
    if attributes.startswith("l") or "reparse" in attributes:
        return True
    return False
