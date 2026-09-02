from __future__ import annotations

import tempfile
import zipfile
from collections.abc import Callable
from pathlib import Path

from utils.app_metadata import HTTP_USER_AGENT
from utils.download_integrity import DownloadIntegrityError, download_staged_file
from utils.env_manager import find_usable_llamacpp_binary
from utils.network_middleware import NetworkMiddlewareError, redact_sensitive_text
from utils.runtime_layout import (
    BIN_ROOT,
    LLAMACPP_DIRECTORY_NAME,
    managed_runtime_install_dir,
    managed_runtime_root,
    replace_runtime_directory,
)
from utils.runtime_downloads import RuntimeDownloadManifestError, runtime_download_asset

LLAMACPP_WINDOWS_ASSET_ID = "llamacpp-win-x64-cpu"
LLAMACPP_WINDOWS_PACKAGE_ID = "win-x64-cpu"

ProgressCallback = Callable[[int, str], None]


class LlamaCppDownloadError(RuntimeError):
    pass


class LlamaCppDownloadCancelled(LlamaCppDownloadError):
    pass


CancelCallback = Callable[[], bool]


def _check_cancel(cancelled: CancelCallback | None) -> None:
    if cancelled and cancelled():
        raise LlamaCppDownloadCancelled("Download cancelled.")


def _extract_zip_safely(
    archive_path: Path,
    extract_dir: Path,
    cancelled: CancelCallback | None = None,
) -> None:
    extract_root = extract_dir.resolve()
    with zipfile.ZipFile(archive_path) as archive:
        for member in archive.infolist():
            _check_cancel(cancelled)
            target = (extract_dir / member.filename).resolve()
            if not target.is_relative_to(extract_root):
                raise LlamaCppDownloadError("Archive contains unsafe paths.")
            archive.extract(member, extract_dir)


def download_and_install_llamacpp(
    bin_root: Path = BIN_ROOT,
    progress: ProgressCallback | None = None,
    cancelled: CancelCallback | None = None,
) -> Path:
    def emit(value: int, message: str) -> None:
        if progress:
            progress(value, message)

    try:
        asset = runtime_download_asset(LLAMACPP_WINDOWS_ASSET_ID)
    except RuntimeDownloadManifestError as exc:
        raise LlamaCppDownloadError(str(exc)) from exc
    _check_cancel(cancelled)
    emit(0, "release")

    runtime_root = managed_runtime_root(bin_root, LLAMACPP_DIRECTORY_NAME)
    runtime_root.mkdir(parents=True, exist_ok=True)
    runtime_target = managed_runtime_install_dir(
        bin_root,
        LLAMACPP_DIRECTORY_NAME,
        asset.version,
        LLAMACPP_WINDOWS_PACKAGE_ID,
    )
    with tempfile.TemporaryDirectory(prefix=".staging-", dir=runtime_root) as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        archive_path = temp_dir / asset.file_name
        extract_dir = temp_dir / "extract"
        extract_dir.mkdir()

        emit(5, "download")
        try:
            download_staged_file(
                asset.url,
                archive_path,
                max_bytes=asset.max_bytes,
                expected_size=asset.size_bytes,
                expected_sha256=asset.sha256,
                headers={"User-Agent": HTTP_USER_AGENT},
                timeout=60,
                check_cancelled=lambda: _check_cancel(cancelled),
                progress=lambda downloaded, total: emit(
                    5 + int(downloaded / total * 75) if total else 5,
                    "download",
                ),
            )
        except (OSError, NetworkMiddlewareError, DownloadIntegrityError) as exc:
            raise LlamaCppDownloadError(redact_sensitive_text(exc)) from exc

        emit(82, "extract")
        try:
            _extract_zip_safely(archive_path, extract_dir, cancelled)
        except (OSError, zipfile.BadZipFile) as exc:
            raise LlamaCppDownloadError(str(exc)) from exc

        staged_binary = find_usable_llamacpp_binary(extract_dir)
        if staged_binary is None:
            raise LlamaCppDownloadError(
                "Downloaded archive does not include a usable llama.cpp binary."
            )

        emit(92, "install")
        replace_runtime_directory(extract_dir, runtime_target)

    binary = find_usable_llamacpp_binary(runtime_target)
    if binary is None:
        raise LlamaCppDownloadError("Downloaded archive does not include a usable llama.cpp binary.")

    emit(100, "done")
    return binary
