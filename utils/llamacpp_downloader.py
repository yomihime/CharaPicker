from __future__ import annotations

import json
import shutil
import tempfile
import urllib.error
import urllib.request
import zipfile
from collections.abc import Callable
from pathlib import Path

from utils.env_manager import BIN_ROOT, find_usable_llamacpp_binary

LLAMACPP_LATEST_RELEASE_API = "https://api.github.com/repos/ggml-org/llama.cpp/releases/latest"
USER_AGENT = "CharaPicker/0.1"

ProgressCallback = Callable[[int, str], None]


class LlamaCppDownloadError(RuntimeError):
    pass


class LlamaCppDownloadCancelled(LlamaCppDownloadError):
    pass


CancelCallback = Callable[[], bool]


def _check_cancel(cancelled: CancelCallback | None) -> None:
    if cancelled and cancelled():
        raise LlamaCppDownloadCancelled("Download cancelled.")


def _request_json(url: str, cancelled: CancelCallback | None = None) -> dict:
    _check_cancel(cancelled)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            _check_cancel(cancelled)
            data = json.loads(response.read().decode("utf-8"))
            _check_cancel(cancelled)
            return data
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        raise LlamaCppDownloadError(str(exc)) from exc


def _asset_score(asset_name: str) -> int:
    name = asset_name.lower()
    if not name.endswith(".zip") or "bin-win" not in name or "x64" not in name:
        return -1
    if "arm64" in name:
        return -1

    score = 0
    if "cpu" in name:
        score += 50
    if "avx2" in name:
        score += 40
    if "cuda" in name or "cudart" in name or "cu12" in name or "cu13" in name:
        score -= 40
    if "vulkan" in name or "sycl" in name or "hip" in name:
        score -= 30
    return score


def select_windows_x64_asset(release: dict) -> dict:
    assets = release.get("assets", [])
    candidates = [
        asset
        for asset in assets
        if isinstance(asset, dict) and _asset_score(str(asset.get("name", ""))) >= 0
    ]
    if not candidates:
        raise LlamaCppDownloadError("No Windows x64 llama.cpp binary asset found.")
    return max(candidates, key=lambda asset: _asset_score(str(asset.get("name", ""))))


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

    bin_root.mkdir(parents=True, exist_ok=True)
    emit(0, "release")
    release = _request_json(LLAMACPP_LATEST_RELEASE_API, cancelled)
    _check_cancel(cancelled)
    asset = select_windows_x64_asset(release)
    asset_name = str(asset.get("name", "llama.cpp.zip"))
    download_url = str(asset.get("browser_download_url", ""))
    if not download_url:
        raise LlamaCppDownloadError("Selected llama.cpp asset has no download URL.")

    request = urllib.request.Request(download_url, headers={"User-Agent": USER_AGENT})
    with tempfile.TemporaryDirectory(prefix="llamacpp-", dir=bin_root) as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        archive_path = temp_dir / asset_name
        extract_dir = temp_dir / "extract"
        extract_dir.mkdir()

        emit(5, "download")
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                _check_cancel(cancelled)
                total_size = int(response.headers.get("Content-Length") or 0)
                downloaded = 0
                with archive_path.open("wb") as archive:
                    while True:
                        _check_cancel(cancelled)
                        chunk = response.read(1024 * 256)
                        if not chunk:
                            break
                        archive.write(chunk)
                        downloaded += len(chunk)
                        if total_size:
                            emit(5 + int(downloaded / total_size * 75), "download")
        except (OSError, urllib.error.URLError) as exc:
            raise LlamaCppDownloadError(str(exc)) from exc

        emit(82, "extract")
        try:
            _extract_zip_safely(archive_path, extract_dir, cancelled)
        except (OSError, zipfile.BadZipFile) as exc:
            raise LlamaCppDownloadError(str(exc)) from exc

        emit(92, "install")
        for source in extract_dir.rglob("*"):
            if source.is_file():
                relative_path = source.relative_to(extract_dir)
                target = bin_root / relative_path
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)

    binary = find_usable_llamacpp_binary(bin_root)
    if binary is None:
        raise LlamaCppDownloadError("Downloaded archive does not include a usable llama.cpp binary.")

    emit(100, "done")
    return binary
