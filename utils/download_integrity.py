from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from utils.network_middleware import open_response


SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")
DEFAULT_DOWNLOAD_CHUNK_BYTES = 256 * 1024

CancelCheck = Callable[[], None]
ProgressCallback = Callable[[int, int], None]


class DownloadIntegrityError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class DownloadResult:
    size_bytes: int
    sha256: str


def download_staged_file(
    url: str,
    destination: Path,
    *,
    max_bytes: int,
    expected_sha256: str = "",
    expected_size: int | None = None,
    headers: dict[str, str] | None = None,
    timeout: int | float = 60,
    check_cancelled: CancelCheck | None = None,
    progress: ProgressCallback | None = None,
    chunk_size: int = DEFAULT_DOWNLOAD_CHUNK_BYTES,
) -> DownloadResult:
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    if expected_size is not None and expected_size < 0:
        raise ValueError("expected_size cannot be negative")
    normalized_digest = expected_sha256.strip().lower()
    if normalized_digest and SHA256_PATTERN.fullmatch(normalized_digest) is None:
        raise ValueError("expected_sha256 must contain exactly 64 hexadecimal characters")

    destination.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    downloaded = 0
    try:
        with open_response(
            "GET",
            url,
            headers=headers,
            timeout=timeout,
            stream=True,
        ) as response:
            _check_cancelled(check_cancelled)
            if response.status_code >= 400:
                raise DownloadIntegrityError(f"HTTP {response.status_code}")
            declared_size = _content_length(response.headers.get("Content-Length"))
            _validate_declared_size(
                declared_size,
                max_bytes=max_bytes,
                expected_size=expected_size,
            )
            progress_total = declared_size or expected_size or 0
            with destination.open("wb") as output:
                for chunk in response.iter_content(chunk_size=chunk_size):
                    _check_cancelled(check_cancelled)
                    if not chunk:
                        continue
                    downloaded += len(chunk)
                    if downloaded > max_bytes:
                        raise DownloadIntegrityError("Download exceeded the configured size limit.")
                    if declared_size is not None and downloaded > declared_size:
                        raise DownloadIntegrityError("Download exceeded its declared Content-Length.")
                    output.write(chunk)
                    digest.update(chunk)
                    if progress is not None:
                        progress(downloaded, progress_total)

        if declared_size is not None and downloaded != declared_size:
            raise DownloadIntegrityError("Download size does not match Content-Length.")
        if expected_size is not None and downloaded != expected_size:
            raise DownloadIntegrityError("Download size does not match the trusted asset manifest.")
        actual_digest = digest.hexdigest()
        if normalized_digest and actual_digest != normalized_digest:
            raise DownloadIntegrityError("Download failed SHA-256 verification.")
        if progress is not None:
            progress(downloaded, progress_total)
        return DownloadResult(size_bytes=downloaded, sha256=actual_digest)
    except BaseException:
        destination.unlink(missing_ok=True)
        raise


def file_matches_integrity(
    path: Path,
    *,
    expected_size: int,
    expected_sha256: str,
    chunk_size: int = 1024 * 1024,
) -> bool:
    normalized_digest = expected_sha256.strip().lower()
    if expected_size < 0 or SHA256_PATTERN.fullmatch(normalized_digest) is None:
        raise ValueError("expected file integrity metadata is invalid")
    try:
        if not path.is_file() or path.stat().st_size != expected_size:
            return False
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(chunk_size), b""):
                digest.update(chunk)
        return digest.hexdigest() == normalized_digest
    except OSError:
        return False


def _content_length(raw_value: object) -> int | None:
    if raw_value is None or str(raw_value).strip() == "":
        return None
    try:
        value = int(str(raw_value).strip())
    except ValueError as exc:
        raise DownloadIntegrityError("Download returned an invalid Content-Length.") from exc
    if value < 0:
        raise DownloadIntegrityError("Download returned an invalid Content-Length.")
    return value


def _validate_declared_size(
    declared_size: int | None,
    *,
    max_bytes: int,
    expected_size: int | None,
) -> None:
    if declared_size is not None and declared_size > max_bytes:
        raise DownloadIntegrityError("Download exceeds the configured size limit.")
    if expected_size is not None:
        if expected_size > max_bytes:
            raise DownloadIntegrityError("Trusted asset size exceeds the configured size limit.")
        if declared_size is not None and declared_size != expected_size:
            raise DownloadIntegrityError(
                "Content-Length does not match the trusted asset manifest."
            )


def _check_cancelled(check_cancelled: CancelCheck | None) -> None:
    if check_cancelled is not None:
        check_cancelled()
