from __future__ import annotations

import shutil
import tempfile
import zipfile
from collections.abc import Callable
from pathlib import Path

from utils.app_metadata import HTTP_USER_AGENT
from utils.download_integrity import DownloadIntegrityError, download_staged_file
from utils.env_manager import BIN_ROOT
from utils.ffmpeg_tool import find_usable_ffmpeg_binary
from utils.network_middleware import NetworkMiddlewareError, redact_sensitive_text
from utils.runtime_downloads import RuntimeDownloadManifestError, runtime_download_asset

FFMPEG_WINDOWS_ASSET_ID = "ffmpeg-win-x64"

ProgressCallback = Callable[[int, str], None]
CancelCallback = Callable[[], bool]


class FfmpegDownloadError(RuntimeError):
    pass


class FfmpegDownloadCancelled(FfmpegDownloadError):
    pass


def _check_cancel(cancelled: CancelCallback | None) -> None:
    if cancelled and cancelled():
        raise FfmpegDownloadCancelled("Download cancelled.")


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
                raise FfmpegDownloadError("Archive contains unsafe paths.")
            archive.extract(member, extract_dir)


def download_and_install_ffmpeg(
    bin_root: Path = BIN_ROOT,
    progress: ProgressCallback | None = None,
    cancelled: CancelCallback | None = None,
) -> Path:
    def emit(value: int, message: str) -> None:
        if progress:
            progress(value, message)

    bin_root.mkdir(parents=True, exist_ok=True)
    try:
        asset = runtime_download_asset(FFMPEG_WINDOWS_ASSET_ID)
    except RuntimeDownloadManifestError as exc:
        raise FfmpegDownloadError(str(exc)) from exc

    with tempfile.TemporaryDirectory(prefix="ffmpeg-", dir=bin_root) as temp_dir_name:
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
            raise FfmpegDownloadError(redact_sensitive_text(exc)) from exc

        emit(82, "extract")
        try:
            _extract_zip_safely(archive_path, extract_dir, cancelled)
        except (OSError, zipfile.BadZipFile) as exc:
            raise FfmpegDownloadError(str(exc)) from exc

        emit(92, "install")
        for source in extract_dir.rglob("*"):
            if source.is_file():
                relative_path = source.relative_to(extract_dir)
                target = bin_root / relative_path
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)

    binary = find_usable_ffmpeg_binary(bin_root)
    if binary is None:
        raise FfmpegDownloadError("Downloaded archive does not include a usable ffmpeg binary.")

    emit(100, "done")
    return binary
