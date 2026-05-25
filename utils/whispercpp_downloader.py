from __future__ import annotations

import json
import re
import shutil
import tempfile
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from utils.app_metadata import HTTP_USER_AGENT
from utils.env_manager import (
    BIN_ROOT,
    WHISPERCPP_ROOT,
    WHISPER_MODEL_ROOT,
    find_usable_whisper_runtime_binary,
)
from utils.network_middleware import NetworkMiddlewareError, open_response, read_json, redact_sensitive_text

WHISPERCPP_LATEST_RELEASE_API = "https://api.github.com/repos/ggml-org/whisper.cpp/releases/latest"
WHISPER_MODEL_BASE_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/{file_name}"
DEFAULT_WHISPER_RUNTIME_PACKAGE_ID = "win-x64-cpu"
DEFAULT_WHISPER_MODEL_ID = "tiny"

ProgressCallback = Callable[[int, str], None]
CancelCallback = Callable[[], bool]


@dataclass(frozen=True, slots=True)
class WhisperRuntimePackage:
    package_id: str
    label_key: str
    include_keywords: tuple[str, ...]
    exclude_keywords: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class WhisperModelPackage:
    model_id: str
    label_key: str
    file_name: str
    size_label: str


class WhisperCppDownloadError(RuntimeError):
    pass


class WhisperCppDownloadCancelled(WhisperCppDownloadError):
    pass


RUNTIME_PACKAGES: tuple[WhisperRuntimePackage, ...] = (
    WhisperRuntimePackage(
        package_id="win-x64-cpu",
        label_key="project.whisper.runtime.winX64Cpu",
        include_keywords=("whisper", "bin", "x64"),
        exclude_keywords=(
            "arm64",
            "blas",
            "cuda",
            "cublas",
            "cu12",
            "cu13",
            "hip",
            "openvino",
            "rocm",
            "sycl",
            "vulkan",
        ),
    ),
    WhisperRuntimePackage(
        package_id="win-x64-blas",
        label_key="project.whisper.runtime.winX64Blas",
        include_keywords=("whisper", "bin", "x64", "blas"),
        exclude_keywords=("arm64", "cuda", "cublas", "cu12", "cu13", "hip", "openvino", "rocm", "sycl"),
    ),
    WhisperRuntimePackage(
        package_id="win-x64-cuda",
        label_key="project.whisper.runtime.winX64Cuda",
        include_keywords=("whisper", "bin", "x64"),
        exclude_keywords=("arm64", "openvino", "rocm", "sycl", "vulkan"),
    ),
)

MODEL_PACKAGES: tuple[WhisperModelPackage, ...] = (
    WhisperModelPackage(
        model_id="tiny",
        label_key="project.whisper.model.tiny",
        file_name="ggml-tiny.bin",
        size_label="~75 MB",
    ),
    WhisperModelPackage(
        model_id="base",
        label_key="project.whisper.model.base",
        file_name="ggml-base.bin",
        size_label="~142 MB",
    ),
    WhisperModelPackage(
        model_id="small",
        label_key="project.whisper.model.small",
        file_name="ggml-small.bin",
        size_label="~466 MB",
    ),
)


def whisper_runtime_packages() -> tuple[WhisperRuntimePackage, ...]:
    return RUNTIME_PACKAGES


def whisper_model_packages() -> tuple[WhisperModelPackage, ...]:
    return MODEL_PACKAGES


def whisper_runtime_package(package_id: str) -> WhisperRuntimePackage:
    for package in RUNTIME_PACKAGES:
        if package.package_id == package_id:
            return package
    raise WhisperCppDownloadError(f"Unknown whisper.cpp runtime package: {package_id}")


def whisper_model_package(model_id: str) -> WhisperModelPackage:
    for package in MODEL_PACKAGES:
        if package.model_id == model_id:
            return package
    raise WhisperCppDownloadError(f"Unknown Whisper model package: {model_id}")


def download_and_install_whisper(
    runtime_package_id: str = DEFAULT_WHISPER_RUNTIME_PACKAGE_ID,
    model_id: str = DEFAULT_WHISPER_MODEL_ID,
    *,
    bin_root: Path = BIN_ROOT,
    model_root: Path = WHISPER_MODEL_ROOT,
    progress: ProgressCallback | None = None,
    cancelled: CancelCallback | None = None,
) -> tuple[Path, Path]:
    def emit(value: int, message: str) -> None:
        if progress:
            progress(value, message)

    runtime_package = whisper_runtime_package(runtime_package_id)
    model_package = whisper_model_package(model_id)

    bin_root.mkdir(parents=True, exist_ok=True)
    model_root.mkdir(parents=True, exist_ok=True)

    emit(0, "release")
    release = _request_json(WHISPERCPP_LATEST_RELEASE_API, cancelled)
    _check_cancel(cancelled)
    tag_name = str(release.get("tag_name") or "latest").strip() or "latest"
    with tempfile.TemporaryDirectory(prefix="whispercpp-", dir=bin_root) as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        staged_model_path = temp_dir / model_package.file_name

        staged_runtime_dir, installed_runtime_package = _download_and_stage_runtime(
            release,
            runtime_package,
            temp_dir,
            emit,
            cancelled,
        )

        emit(68, "downloadModel")
        model_url = WHISPER_MODEL_BASE_URL.format(file_name=model_package.file_name)
        _download_file(model_url, staged_model_path, 68, 92, "downloadModel", emit, cancelled)

        emit(94, "install")
        runtime_target = _runtime_install_dir(bin_root, tag_name, installed_runtime_package.package_id)
        _replace_directory(staged_runtime_dir, runtime_target)
        model_target = model_root / model_package.file_name
        staged_model_path.replace(model_target)

    runtime_binary = find_usable_whisper_runtime_binary(runtime_target)
    if runtime_binary is None:
        raise WhisperCppDownloadError("Installed whisper.cpp runtime is not usable.")
    if not model_target.is_file():
        raise WhisperCppDownloadError("Installed Whisper model is missing.")

    emit(100, "done")
    return runtime_binary, model_target


def remove_installed_whisper(
    *,
    runtime_root: Path = WHISPERCPP_ROOT,
    model_root: Path = WHISPER_MODEL_ROOT,
    remove_models: bool = True,
) -> None:
    _remove_path_inside(runtime_root, BIN_ROOT)
    if remove_models:
        _remove_path_inside(model_root, BIN_ROOT.parent / "models")


def select_runtime_asset(release: dict, package: WhisperRuntimePackage) -> dict:
    assets = release.get("assets", [])
    candidates = [
        asset
        for asset in assets
        if isinstance(asset, dict) and _runtime_asset_score(str(asset.get("name", "")), package) >= 0
    ]
    if not candidates:
        raise WhisperCppDownloadError(f"No matching whisper.cpp asset found for {package.package_id}.")
    return max(candidates, key=lambda asset: _runtime_asset_score(str(asset.get("name", "")), package))


def _download_and_stage_runtime(
    release: dict,
    package: WhisperRuntimePackage,
    temp_dir: Path,
    emit: ProgressCallback,
    cancelled: CancelCallback | None,
) -> tuple[Path, WhisperRuntimePackage]:
    packages = [package]
    fallback_package = whisper_runtime_package(DEFAULT_WHISPER_RUNTIME_PACKAGE_ID)
    if package.package_id != fallback_package.package_id:
        packages.append(fallback_package)

    failed_packages: list[str] = []
    for candidate_package in packages:
        stage_dir = temp_dir / f"runtime-{_safe_segment(candidate_package.package_id)}"
        extract_dir = temp_dir / f"extract-{_safe_segment(candidate_package.package_id)}"
        stage_dir.mkdir()
        extract_dir.mkdir()
        asset = select_runtime_asset(release, candidate_package)
        asset_name = str(asset.get("name", "whisper.cpp.zip"))
        download_url = str(asset.get("browser_download_url", ""))
        if not download_url:
            raise WhisperCppDownloadError("Selected whisper.cpp asset has no download URL.")

        archive_path = temp_dir / asset_name
        emit(5, "download")
        _download_file(download_url, archive_path, 5, 54, "download", emit, cancelled)

        emit(56, "extract")
        try:
            _extract_zip_safely(archive_path, extract_dir, cancelled)
        except (OSError, zipfile.BadZipFile) as exc:
            raise WhisperCppDownloadError(str(exc)) from exc

        emit(64, "stageRuntime")
        _copy_tree_contents(extract_dir, stage_dir, cancelled)
        runtime_binary = find_usable_whisper_runtime_binary(stage_dir)
        if runtime_binary is not None:
            return stage_dir, candidate_package
        failed_packages.append(candidate_package.package_id)

    raise WhisperCppDownloadError(
        "Downloaded archive does not include a usable whisper.cpp runtime: "
        + ", ".join(failed_packages)
    )


def _check_cancel(cancelled: CancelCallback | None) -> None:
    if cancelled and cancelled():
        raise WhisperCppDownloadCancelled("Download cancelled.")


def _request_json(url: str, cancelled: CancelCallback | None = None) -> dict:
    _check_cancel(cancelled)
    try:
        data = read_json(url, headers={"User-Agent": HTTP_USER_AGENT}, timeout=30)
        _check_cancel(cancelled)
    except (OSError, NetworkMiddlewareError, ValueError, json.JSONDecodeError) as exc:
        raise WhisperCppDownloadError(redact_sensitive_text(exc)) from exc
    if not isinstance(data, dict):
        raise WhisperCppDownloadError("Release response is not a JSON object.")
    return data


def _runtime_asset_score(asset_name: str, package: WhisperRuntimePackage) -> int:
    name = asset_name.lower()
    if not name.endswith(".zip"):
        return -1
    if package.package_id == "win-x64-cuda" and not any(
        token in name for token in ("cuda", "cublas", "cu12", "cu13")
    ):
        return -1
    if any(keyword not in name for keyword in package.include_keywords):
        return -1
    if any(keyword in name for keyword in package.exclude_keywords):
        return -1

    score = 10
    if "cpu" in name:
        score += 30
    if "avx2" in name:
        score += 8
    if "noavx" in name:
        score -= 3
    if package.package_id == "win-x64-cuda" and any(token in name for token in ("cuda", "cublas", "cu12", "cu13")):
        score += 40
        version_match = re.search(r"(?:cuda|cublas|cu)(?:[-_]?)(\d+)(?:[._-](\d+))?", name)
        if version_match:
            major = int(version_match.group(1))
            minor = int(version_match.group(2) or 0)
            score += major * 10 + minor
    return score


def _download_file(
    url: str,
    target_path: Path,
    start_percent: int,
    end_percent: int,
    step: str,
    emit: ProgressCallback,
    cancelled: CancelCallback | None,
) -> None:
    try:
        with open_response(
            "GET",
            url,
            headers={"User-Agent": HTTP_USER_AGENT},
            timeout=60,
            stream=True,
        ) as response:
            _check_cancel(cancelled)
            if response.status_code >= 400:
                raise WhisperCppDownloadError(f"HTTP {response.status_code}")
            total_size = int(response.headers.get("Content-Length") or 0)
            downloaded = 0
            with target_path.open("wb") as target:
                for chunk in response.iter_content(chunk_size=1024 * 256):
                    _check_cancel(cancelled)
                    if not chunk:
                        continue
                    target.write(chunk)
                    downloaded += len(chunk)
                    if total_size:
                        span = max(end_percent - start_percent, 1)
                        emit(start_percent + int(downloaded / total_size * span), step)
    except (OSError, NetworkMiddlewareError) as exc:
        raise WhisperCppDownloadError(redact_sensitive_text(exc)) from exc


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
                raise WhisperCppDownloadError("Archive contains unsafe paths.")
            archive.extract(member, extract_dir)


def _copy_tree_contents(source_root: Path, target_root: Path, cancelled: CancelCallback | None) -> None:
    for source in source_root.rglob("*"):
        _check_cancel(cancelled)
        if source.is_file():
            relative_path = source.relative_to(source_root)
            target = target_root / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)


def _replace_directory(source_dir: Path, target_dir: Path) -> None:
    target_dir.parent.mkdir(parents=True, exist_ok=True)
    backup_dir = target_dir.with_name(f"{target_dir.name}.backup")
    if backup_dir.exists():
        shutil.rmtree(backup_dir)
    if target_dir.exists():
        target_dir.replace(backup_dir)
    try:
        source_dir.replace(target_dir)
    except OSError:
        if backup_dir.exists() and not target_dir.exists():
            backup_dir.replace(target_dir)
        raise
    if backup_dir.exists():
        shutil.rmtree(backup_dir)


def _runtime_install_dir(bin_root: Path, tag_name: str, package_id: str) -> Path:
    safe_tag = _safe_segment(tag_name)
    safe_package_id = _safe_segment(package_id)
    runtime_root = WHISPERCPP_ROOT if bin_root == BIN_ROOT else bin_root / "whisper.cpp"
    return runtime_root / safe_tag / safe_package_id


def _safe_segment(value: str) -> str:
    cleaned = "".join(character if character.isalnum() or character in "._-" else "-" for character in value)
    return cleaned.strip(".-") or "unknown"


def _remove_path_inside(path: Path, allowed_root: Path) -> None:
    resolved_path = path.resolve()
    resolved_root = allowed_root.resolve()
    if not resolved_path.is_relative_to(resolved_root):
        raise WhisperCppDownloadError("Refusing to remove a path outside the managed runtime roots.")
    if resolved_path.is_file():
        resolved_path.unlink()
    elif resolved_path.is_dir():
        shutil.rmtree(resolved_path)
